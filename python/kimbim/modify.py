# SPDX-License-Identifier: GPL-3.0-or-later
"""Split, trim / extend, corner, join (merge) and unjoin for walls and beams (doc 14 §4, D80).

Revit's Split element, Trim/Extend to element and to corner, Archicad's Merge and Revit's join
toggles, kept connected the D54 way: pieces of a split wall stay joined, a wall trimmed or extended
to a wall is joined to it, and the opt-out (Ctrl in the app, `join=0` here) leaves them apart.
Every command is one undo step through app_bridge._run, keeps GlobalIds of what it keeps, and
reports the shapes it changed so the app re-meshes only those. Lengths in metres (world plan
coordinates). Same protocol as app_bridge: strings in, JSON out, never raise.
"""
from __future__ import annotations

import math

import ifcopenshell.api.geometry
import ifcopenshell.api.layer
import ifcopenshell.api.root
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import layers
from . import renovation

EPS = 1e-6          # metres: "the same point"
TOUCH = 0.002       # metres: collinear walls this close count as touching (merge)
END_MARGIN = 0.01   # metres: a split this close to an end would make a sliver


def _num(*values):
    return [float(v) for v in values]


def _vec(p):
    return np.asarray(p, dtype=float)


def _cross(a, b) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _intersect(a1, a2, b1, b2):
    """Parameter (0 at a1, 1 at a2) where line a meets line b, or None if they are parallel."""
    a1, a2, b1, b2 = (_vec(p)[:2] for p in (a1, a2, b1, b2))
    da, db = a2 - a1, b2 - b1
    den = _cross(da, db)
    if abs(den) < 1e-9 * max(float(np.linalg.norm(da) * np.linalg.norm(db)), 1e-12):
        return None
    return _cross(b1 - a1, db) / den


def _param(p, a1, a2) -> float:
    """Where a point projects onto the line a1-a2 (0 at a1, 1 at a2)."""
    a1, a2, p = _vec(a1)[:2], _vec(a2)[:2], _vec(p)[:2]
    d = a2 - a1
    return float(np.dot(p - a1, d) / np.dot(d, d))


def _distance_to_line(p, a1, a2) -> float:
    a1, a2, p = _vec(a1)[:2], _vec(a2)[:2], _vec(p)[:2]
    d = a2 - a1
    return abs(_cross(d, p - a1)) / float(np.linalg.norm(d))


def _distance_to_segment(p, a1, a2) -> float:
    t = min(max(_param(p, a1, a2), 0.0), 1.0)
    a1, a2 = _vec(a1)[:2], _vec(a2)[:2]
    return float(np.linalg.norm(_vec(p)[:2] - (a1 + (a2 - a1) * t)))


# ---------------------------------------------------------------- walls and beams as lines

def _editable_wall(wall) -> str:
    """'' if KimBim can rebuild this wall's shape (a wall with an axis and layers), else why not."""
    if A._axis_world(wall) is None:
        return "the wall has no axis"
    if A._layer_set(wall) is None:
        return "the wall has no layers (its shape comes from another program)"
    return ""


def _foreign_bodies(wall) -> list:
    """Body representations KimBim didn't make (e.g. Revit's, on the plain Model context)."""
    ours = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
    return [r for r in (wall.Representation.Representations if wall.Representation else ())
            if r.RepresentationIdentifier == "Body" and r != ours]


def _adopt(wall):
    """Inside an action: an imported layered wall gets KimBim's own shape (D80) — rebuilt from its
    axis, layers and height, as walls drawn here are — so it can be split, trimmed and merged.
    Its doors/windows keep their place. Walls with KimBim's shape are left alone."""
    if not wall.is_a("IfcWall") or A._layer_set(wall) is None or A._axis_world(wall) is None:
        return
    foreign = _foreign_bodies(wall)
    if not foreign or ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW"):
        return
    f = B._model
    s = A._scale()
    p1, p2 = _wall_line(wall)
    zs = [float(p.Coordinates[2]) for r in foreign for p in f.traverse(r)
          if p.is_a("IfcCartesianPoint") and len(p.Coordinates) == 3]
    depths = [float(x.Depth) for r in foreign for x in f.traverse(r) if x.is_a("IfcExtrudedAreaSolid")]
    if depths:  # an extrusion: its depth (from the placement up)
        bottom, height = 0.0, max(depths)
    elif zs and max(zs) - min(zs) > 1e-9:  # a surface model or brep: its vertices' height range
        bottom, height = min(zs), max(zs) - min(zs)
    else:
        bottom, height = 0.0, 3.0 / s
    wall_layers = [layer for r in foreign for layer in (getattr(r, "LayerAssignments", ()) or ())]
    for r in list(wall.Representation.Representations):
        if r.RepresentationIdentifier in ("Body", "Axis"):
            ifcopenshell.api.geometry.unassign_representation(f, product=wall, representation=r)
            if r.id():
                ifcopenshell.api.geometry.remove_representation(f, representation=r)
    A._reaxis(wall, p1, p2)
    if abs(bottom) > 1e-9:
        m = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
        m[2, 3] += bottom
        ifcopenshell.api.geometry.edit_object_placement(f, product=wall, matrix=m, is_si=False)
    new = A._regenerate(f, wall, length=math.dist(p1, p2), height=height * s)
    if new is not None:
        for layer in dict.fromkeys(wall_layers):  # the wall stays on its layer
            if layer.id():
                ifcopenshell.api.layer.assign_layer(f, items=[new], layer=layer)


def _beam_solid(beam):
    body = ifcopenshell.util.representation.get_representation(beam, "Model", "Body", "MODEL_VIEW") \
        or ifcopenshell.util.representation.get_representation(beam, "Model", "Body")
    items = list(body.Items) if body is not None else []
    if len(items) == 1 and items[0].is_a("IfcExtrudedAreaSolid"):
        return items[0]
    return None


def _beam_axis(beam):
    """(start, end) of a beam's extrusion in world metres (3D), or None when its body is not one
    extrusion (KimBim's beams, most exported ones)."""
    solid = _beam_solid(beam)
    if solid is None or beam.ObjectPlacement is None:
        return None
    s = A._scale()
    m = ifcopenshell.util.placement.get_local_placement(beam.ObjectPlacement)
    p = ifcopenshell.util.placement.get_axis2placement(solid.Position) if solid.Position else np.eye(4)
    d = _vec(solid.ExtrudedDirection.DirectionRatios)
    d = d / np.linalg.norm(d) * float(solid.Depth)
    a = (m @ p @ np.array([0.0, 0.0, 0.0, 1.0]))[:3] * s
    b = (m @ p @ np.array([d[0], d[1], d[2], 1.0]))[:3] * s
    if np.linalg.norm((b - a)[:2]) < A.MIN_WALL_LENGTH:
        return None  # vertical: not a beam in plan
    return a, b


def _set_beam_axis(beam, a, b):
    """Inside an action: a beam's extrusion now runs from a to b (world metres, on its old line):
    its placement slides along the line and the extrusion gets the new length."""
    s = A._scale()
    old_a, old_b = _beam_axis(beam)
    solid = _beam_solid(beam)
    m = ifcopenshell.util.placement.get_local_placement(beam.ObjectPlacement)
    m = m.copy()
    m[:3, 3] += (_vec(a) - old_a) / s
    ifcopenshell.api.geometry.edit_object_placement(B._model, product=beam, matrix=m, is_si=False)
    solid.Depth = float(solid.Depth) * float(np.linalg.norm(_vec(b) - _vec(a)) / np.linalg.norm(old_b - old_a))


def _wall_line(wall):
    """A wall's axis in world metres. KimBim's walls keep it on Plan/Axis/GRAPH_VIEW; exported walls
    (e.g. Revit's) often put their Axis polyline on the plain Model context, where
    authoring._axis_world doesn't look (it would answer a 1 m stub)."""
    if ifcopenshell.util.representation.get_representation(wall, "Plan", "Axis", "GRAPH_VIEW") is not None:
        return A._axis_world(wall)
    for r in (wall.Representation.Representations if wall.Representation else ()):
        if r.RepresentationIdentifier != "Axis":
            continue
        for item in r.Items:
            if item.is_a("IfcPolyline") and len(item.Points) >= 2:
                m = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
                s = A._scale()
                pts = []
                for p in (item.Points[0], item.Points[-1]):
                    c = list(p.Coordinates) + [0.0] * (3 - len(p.Coordinates))
                    pts.append(tuple((m @ np.array([c[0], c[1], c[2], 1.0]))[:2] * s))
                if math.dist(*pts) > EPS:
                    return pts[0], pts[1]
    return A._axis_world(wall)


def _line(e):
    """((x1, y1), (x2, y2)) plan axis of a wall or beam in metres, or None."""
    if e.is_a("IfcWall"):
        return _wall_line(e)
    if e.is_a("IfcBeam"):
        axis = _beam_axis(e)
        return (tuple(axis[0][:2]), tuple(axis[1][:2])) if axis is not None else None
    return None


def _check(e, what="this") -> str:
    if e is None:
        return f"{what} is not a wall or beam"
    if e.is_a("IfcWall"):
        return _editable_wall(e)
    if e.is_a("IfcBeam"):
        return "" if _beam_axis(e) is not None else "the beam's shape is not a straight extrusion"
    return f"{what} is not a wall or beam"


def _width(e) -> float:
    if e.is_a("IfcWall"):
        ls = A._layer_set(e)
        return A._thickness(ls) if ls is not None else 0.0
    t = ifcopenshell.util.element.get_type(e)
    profile = A._profile(t) if t is not None else None
    return A._profile_size(profile)[0] if profile is not None else 0.0


def _other(rel, e):
    return rel.RelatedElement if rel.RelatingElement == e else rel.RelatingElement


def _mine(rel, e) -> str:
    return rel.RelatingConnectionType if rel.RelatingElement == e else rel.RelatedConnectionType


def _set_mine(rel, e, value):
    if rel.RelatingElement == e:
        rel.RelatingConnectionType = value
    else:
        rel.RelatedConnectionType = value


def _replace_in(rel, old, new):
    if rel.RelatingElement == old:
        rel.RelatingElement = new
    else:
        rel.RelatedElement = new


def _joined(a, b) -> list:
    return [r for r in A._path_joins(a) if _other(r, a) == b]


def _path_param(rel, e, line) -> float | None:
    """Where the element joined to `e` by an ATPATH join meets e's axis (0..1 along e)."""
    other = _other(rel, e)
    other_line = _line(other)
    return _intersect(line[0], line[1], *other_line) if other_line is not None else None


def _hosted_fills(wall):
    """[(door/window, opening, along, width)] in a wall, `along` the centre's distance from its start."""
    out = []
    for rel in getattr(wall, "HasOpenings", ()) or ():
        opening = rel.RelatedOpeningElement
        for fill in getattr(opening, "HasFillings", ()) or ():
            info = A._opening_info(fill.RelatedBuildingElement)
            if info is not None:
                out.append((fill.RelatedBuildingElement, opening, info[2], info[3]))
    return out


def _bare_openings(wall):
    """Openings with nothing in them (plain holes), with their extent along the wall (metres)."""
    out = []
    axis = _wall_line(wall)
    for rel in getattr(wall, "HasOpenings", ()) or ():
        opening = rel.RelatedOpeningElement
        if getattr(opening, "HasFillings", None):
            continue
        m = ifcopenshell.util.placement.get_local_placement(opening.ObjectPlacement)
        along = _param(m[:2, 3] * A._scale(), *axis) * math.dist(*axis)
        out.append((opening, along))
    return out


def _rehost(opening, wall):
    """Inside an action: an opening now cuts `wall` (same world place); its door/window follows."""
    world = ifcopenshell.util.placement.get_local_placement(opening.ObjectPlacement)
    for rel in opening.VoidsElements:
        rel.RelatingBuildingElement = wall
    if opening.ObjectPlacement is not None and opening.ObjectPlacement.is_a("IfcLocalPlacement"):
        opening.ObjectPlacement.PlacementRelTo = wall.ObjectPlacement
    ifcopenshell.api.geometry.edit_object_placement(B._model, product=opening, matrix=world, is_si=False)


def _copy_piece(e):
    """Inside an action: a copy of a wall or beam (type, properties, material, layer, status,
    level) with the same shape, without its openings and joins."""
    f = B._model
    c = ifcopenshell.api.root.copy_class(f, product=e)
    for rel in list(getattr(c, "HasOpenings", ()) or ()):  # copy_class duplicates empty holes
        ifcopenshell.api.root.remove_product(f, product=rel.RelatedOpeningElement)
    for identifier, context in (("Body", "Model"), ("Axis", "Plan")):
        if ifcopenshell.util.representation.get_representation(e, context, identifier):
            ifcopenshell.api.geometry.copy_representation(f, source=e, target=c, context_identifier=identifier)
    layers.copy_layer(e, c)
    renovation.copy_status(e, c)
    return c


def _regen(walls):
    f = B._model
    rebuilt = []
    for w in dict.fromkeys(walls):
        if w.is_a("IfcWall") and w.id() and A._axis_world(w) is not None and A._layer_set(w) is not None:
            if A._regenerate(f, w) is not None:
                rebuilt.append(w.GlobalId)
    return rebuilt


def _set_line(e, p1, p2, z=None):
    """Inside an action: a wall or beam now runs p1 -> p2 (plan metres; beams keep their slope)."""
    if e.is_a("IfcWall"):
        A._reaxis(e, p1, p2)
        A._regenerate(B._model, e, length=math.dist(p1, p2), height=A._wall_height(e) or 3.0)
    else:
        a, b = _beam_axis(e)
        line = (a[:2], b[:2])
        t1, t2 = _param(p1, *line), _param(p2, *line)
        _set_beam_axis(e, a + (b - a) * t1, a + (b - a) * t2)


def _visible(elements) -> list:
    """GlobalIds to re-mesh: the elements and the doors/windows they host."""
    out = []
    for e in elements:
        if e is None or not e.id():
            continue
        out.append(e.GlobalId)
        out += [x.GlobalId for x in A._hosted(e) if not x.is_a("IfcOpeningElement")]
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- split

def split_element(guid: str, x, y, join="1") -> str:
    """Split a wall or beam at the point of its axis nearest (x, y): the element keeps its GlobalId
    and the part from its start; a new element of the same type, properties, layer and status gets
    the rest. Doors/windows go with the piece they are in (a split through one is refused), joins
    at the far end go to the new piece, and the two pieces are joined unless `join` is false."""
    if B._model is None:
        return A._fail("no model open")
    e = A._by_guid(guid)
    error = _check(e)
    if error:
        return A._fail(error)
    try:
        x, y = _num(x, y)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    line = _line(e)
    length = math.dist(*line)
    t = _param((x, y), *line)
    at = t * length
    if at < END_MARGIN or at > length - END_MARGIN:
        return A._fail("split inside the element, not at its end")
    p1, p2 = _vec(line[0]), _vec(line[1])
    point = p1 + (p2 - p1) * t
    fills, holes = [], []
    if e.is_a("IfcWall"):
        for fill, opening, along, width in _hosted_fills(e):
            if along - width / 2 - EPS < at < along + width / 2 + EPS:
                return A._fail(f"the split point is inside {fill.Name or 'a door or window'}: split beside it")
            fills.append((opening, along > at))
        holes = [(opening, along > at) for opening, along in _bare_openings(e)]
    join = A._truthy(join)
    made = {}

    def action():
        f = B._model
        _adopt(e)
        piece = _copy_piece(e)
        neighbours = []
        for rel in A._path_joins(e):
            mine = _mine(rel, e)
            moves = mine == "ATEND"
            if mine == "ATPATH":
                where = _path_param(rel, e, line)
                moves = where is not None and where > t
            if moves:
                _replace_in(rel, e, piece)
            neighbours.append(_other(rel, e))
        rebuilt = []
        if e.is_a("IfcWall"):
            A._reaxis(piece, point, p2)
            for opening, moves in fills + holes:
                if moves:
                    _rehost(opening, piece)
            A._reaxis(e, p1, point)
            if join:
                ifcopenshell.api.geometry.connect_path(
                    f, relating_element=e, related_element=piece, relating_connection="ATEND", related_connection="ATSTART")
            rebuilt = _regen([e, piece, *neighbours])
        else:
            a, b = _beam_axis(e)
            mid = a + (b - a) * t
            _set_beam_axis(piece, mid, b)
            _set_beam_axis(e, a, mid)
        made["piece"] = piece.GlobalId
        return 1, _visible([e, piece]) + rebuilt, []

    return _finish(action, made)


def _finish(action, made):
    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, **made})


# ---------------------------------------------------------------- trim / extend

def _end_to(e, line, t, keep_t):
    """Which end moves when e's line is cut or extended at parameter t, keeping the side of keep_t:
    returns 0 (start) or 1 (end)."""
    if t <= 0:
        return 0
    if t >= 1:
        return 1
    return 1 if keep_t < t else 0


def _plan_end(e, line, t, keep_t, holes="refuse"):
    """(end index, new p1, new p2, doomed) or an error string. `holes` (D92) decides what happens to a
    door, window or opening the trim would leave outside the wall: "refuse" (default), "delete" it, or
    "keep" it where it is."""
    k = _end_to(e, line, t, keep_t)
    p1, p2 = _vec(line[0]), _vec(line[1])
    q = p1 + (p2 - p1) * t
    new = (q, p2) if k == 0 else (p1, q)
    length = float(np.linalg.norm(new[1] - new[0]))
    if length < A.MIN_WALL_LENGTH:
        return "the element would have no length"
    doomed = []
    if e.is_a("IfcWall"):
        full = math.dist(*line)
        lo, hi = (t * full, full) if k == 0 else (0.0, t * full)
        for fill, opening, along, width in _hosted_fills(e):
            if along - width / 2 < lo - EPS or along + width / 2 > hi + EPS:
                if holes == "refuse":
                    return f"{fill.Name or 'a door or window'} would be cut off: move or delete it first"
                if holes == "delete":
                    doomed.append(fill)
        for opening, along in _bare_openings(e):
            if not lo - EPS <= along <= hi + EPS:
                if holes == "refuse":
                    return "an opening would be cut off: delete it first"
                if holes == "delete":
                    doomed.append(opening)
    return k, new[0], new[1], doomed


def _apply_end(e, line, k, p1, p2, t):
    """Inside an action: give e its new line, dropping joins at the end that moved and T joins of
    walls that end on the part cut away. Returns the walls that lost a join."""
    f = B._model
    lost = []
    for rel in A._path_joins(e):
        mine = _mine(rel, e)
        drop = mine == ("ATSTART" if k == 0 else "ATEND")
        if mine == "ATPATH":
            where = _path_param(rel, e, line)
            drop = where is not None and ((k == 0 and where < t - EPS) or (k == 1 and where > t + EPS))
        if drop:
            lost.append(_other(rel, e))
            f.remove(rel)
    _set_line(e, p1, p2)
    return lost


def _join_end(e, k, other, point):
    """Inside an action: join wall e's end k to wall `other`: an L at other's end, else a T."""
    if not (e.is_a("IfcWall") and other is not None and other.is_a("IfcWall")):
        return
    oline = _wall_line(other)
    mine = "ATSTART" if k == 0 else "ATEND"
    if min(math.dist(point, oline[0]), math.dist(point, oline[1])) <= max(_width(other), 0.01):
        theirs = "ATSTART" if math.dist(point, oline[0]) < math.dist(point, oline[1]) else "ATEND"
    else:
        theirs = "ATPATH"
    for rel in _joined(e, other):
        B._model.remove(rel)
    ifcopenshell.api.geometry.connect_path(B._model, relating_element=e, related_element=other,
                                           relating_connection=mine, related_connection=theirs)


def trim_extend(guid: str, x, y, boundary_guid: str = "", bx1=0, by1=0, bx2=0, by2=0, join="1",
                holes="refuse") -> str:
    """Trim or extend a wall or beam to a boundary (Revit's Trim/Extend to element): the boundary
    is a wall or beam (`boundary_guid`) or a line (bx1, by1)-(bx2, by2), e.g. a grid line. When
    the boundary crosses the element, the side clicked at (x, y) stays; otherwise the nearer end
    reaches the boundary. A wall that reaches a wall is joined to it unless `join` is false; the
    joins at the end that moved are dropped (as when stretching). `holes` (D92) decides an opening
    the trim would leave outside: "refuse" (default), "delete" it or "keep" it."""
    if B._model is None:
        return A._fail("no model open")
    if holes not in ("refuse", "delete", "keep"):
        return A._fail(f"unknown opening choice {holes}")
    e = A._by_guid(guid)
    error = _check(e)
    if error:
        return A._fail(error)
    boundary = A._by_guid(boundary_guid) if boundary_guid else None
    try:
        x, y = _num(x, y)
        if boundary is not None:
            if _line(boundary) is None:
                return A._fail("the boundary is not a wall or beam")
            b1, b2 = (_vec(p) for p in _line(boundary))
        else:
            b1, b2 = _vec(_num(bx1, by1)), _vec(_num(bx2, by2))
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if boundary is e:
        return A._fail("pick another element as the boundary")
    if np.linalg.norm(b2 - b1) < EPS:
        return A._fail("the boundary has no length")
    line = _line(e)
    t = _intersect(line[0], line[1], b1, b2)
    if t is None:
        return A._fail("the element is parallel to the boundary")
    plan = _plan_end(e, line, t, _param((x, y), *line), holes)
    if isinstance(plan, str):
        return A._fail(plan)
    k, p1, p2, doomed = plan
    join = A._truthy(join)

    def action():
        _adopt(e)
        old_neighbours = [_other(r, e) for r in A._path_joins(e)]
        lost = _apply_end(e, line, k, p1, p2, t)
        if join:
            _join_end(e, k, boundary, p1 if k == 0 else p2)
        removed = []
        deleted = []
        if doomed:
            _, deleted, removed = A._delete_cascade(list(dict.fromkeys(doomed)))
        rebuilt = _regen([e, *lost, *old_neighbours, *([boundary] if boundary is not None else [])])
        return 1, _visible([e]) + rebuilt + deleted, removed

    return _finish(action, {})


def trim_corner(guid1: str, x1, y1, guid2: str, x2, y2, join="1", holes="refuse") -> str:
    """Trim/extend two walls or beams to their corner (Revit's Trim/Extend to corner, Archicad's
    Intersect): both reach the point where their lines cross, each keeping the side it was clicked
    on (x1, y1 / x2, y2), and two walls are joined there in an L unless `join` is false. `holes`
    (D92) decides an opening the trim would leave outside: "refuse", "delete" or "keep"."""
    if B._model is None:
        return A._fail("no model open")
    if holes not in ("refuse", "delete", "keep"):
        return A._fail(f"unknown opening choice {holes}")
    a, b = A._by_guid(guid1), A._by_guid(guid2)
    for e, what in ((a, "the first element"), (b, "the second element")):
        error = _check(e, what)
        if error:
            return A._fail(error)
    if a is b:
        return A._fail("pick two different elements")
    try:
        x1, y1, x2, y2 = _num(x1, y1, x2, y2)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    la, lb = _line(a), _line(b)
    ta, tb = _intersect(*la, *lb), _intersect(*lb, *la)
    if ta is None:
        return A._fail("the two are parallel: they never meet")
    plans = []
    for e, line, t, click in ((a, la, ta, (x1, y1)), (b, lb, tb, (x2, y2))):
        plan = _plan_end(e, line, t, _param(click, *line), holes)
        if isinstance(plan, str):
            return A._fail(plan)
        plans.append((e, line, t, plan))
    join = A._truthy(join)

    def action():
        f = B._model
        touched = []
        doomed = []
        _adopt(a)
        _adopt(b)
        for e, line, t, (k, p1, p2, holes_out) in plans:
            touched += [_other(r, e) for r in A._path_joins(e)]
            touched += _apply_end(e, line, k, p1, p2, t)
            doomed += holes_out
        for rel in _joined(a, b):
            f.remove(rel)
        if join and a.is_a("IfcWall") and b.is_a("IfcWall"):
            ka, kb = plans[0][3][0], plans[1][3][0]
            ifcopenshell.api.geometry.connect_path(
                f, relating_element=a, related_element=b,
                relating_connection="ATSTART" if ka == 0 else "ATEND", related_connection="ATSTART" if kb == 0 else "ATEND")
        removed = []
        deleted = []
        if doomed:
            _, deleted, removed = A._delete_cascade(list(dict.fromkeys(doomed)))
        rebuilt = _regen([a, b, *touched])
        return 2, _visible([a, b]) + rebuilt + deleted, removed

    return _finish(action, {})


# ---------------------------------------------------------------- join / merge / unjoin

def _same_level(a, b) -> bool:
    return ifcopenshell.util.element.get_container(a) == ifcopenshell.util.element.get_container(b)


def _base_z(e) -> float:
    return float(ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)[2][3]) * A._scale()


def _collinear(a, b) -> bool:
    la, lb = _line(a), _line(b)
    tol = max(TOUCH, 1e-3)
    return all(_distance_to_line(p, *la) <= tol for p in lb)


def _merge_plan(a, b):
    """The merged extent along a's line (0..1 params) or an error."""
    la, lb = _line(a), _line(b)
    length = math.dist(*la)
    sb = sorted(_param(p, *la) for p in lb)
    gap = max(sb[0] - 1.0, 0.0 - sb[1], 0.0) * length
    if gap > TOUCH:
        return "they don't touch: stretch one to the other first"
    if ifcopenshell.util.element.get_type(a) != ifcopenshell.util.element.get_type(b):
        return "only elements of the same type can be merged"
    if not _same_level(a, b):
        return "they are on different levels"
    if a.is_a("IfcWall"):
        if abs(A._wall_height(a) - A._wall_height(b)) > 1e-3 or abs(_base_z(a) - _base_z(b)) > 1e-3:
            return "they have different heights"
    else:
        za, zb = _beam_axis(a), _beam_axis(b)
        if any(abs(_param(p, *la) * (za[1][2] - za[0][2]) + za[0][2] - p[2]) > 1e-3 for p in zb):
            return "they are at different heights"
        if getattr(b, "HasOpenings", None):
            return "the second beam has openings"
    return min(0.0, sb[0]), max(1.0, sb[1])


def _merge(a, b, lo, hi):
    """Inside an action: a takes b's extent, doors/windows and joins; b goes."""
    f = B._model
    la, lb = _line(a), _line(b)
    p1, p2 = _vec(la[0]), _vec(la[1])
    q1, q2 = p1 + (p2 - p1) * lo, p1 + (p2 - p1) * hi
    touched = []
    for rel in _joined(a, b):
        f.remove(rel)
    # a's own joins at an end that is no longer an end are dropped.
    for rel in A._path_joins(a):
        mine = _mine(rel, a)
        if (mine == "ATSTART" and lo < -EPS) or (mine == "ATEND" and hi > 1 + EPS):
            touched.append(_other(rel, a))
            f.remove(rel)
    # b's joins move to a: at the merged wall's ends they stay end joins, inside they become T joins.
    for rel in A._path_joins(b):
        other = _other(rel, b)
        touched.append(other)
        mine = _mine(rel, b)
        if mine in ("ATSTART", "ATEND"):
            tb = _param(lb[0] if mine == "ATSTART" else lb[1], *la)
            new = "ATSTART" if abs(tb - lo) * math.dist(*la) < TOUCH else "ATEND" if abs(tb - hi) * math.dist(*la) < TOUCH else "ATPATH"
        else:
            new = mine
        if _joined(a, other) or (new != "ATPATH" and any(_mine(r, a) == new for r in A._path_joins(a))):
            f.remove(rel)  # a is already joined there
            continue
        _set_mine(rel, b, new)
        _replace_in(rel, b, a)
    if a.is_a("IfcWall"):
        for rel in list(getattr(b, "HasOpenings", ()) or ()):
            _rehost(rel.RelatedOpeningElement, a)
    removed = [b.GlobalId]
    ifcopenshell.api.root.remove_product(f, product=b)
    if a.is_a("IfcWall"):
        A._reaxis(a, q1, q2)
        A._regenerate(f, a, length=float(np.linalg.norm(q2 - q1)), height=A._wall_height(a) or 3.0)
    else:
        za = _beam_axis(a)
        _set_beam_axis(a, za[0] + (za[1] - za[0]) * lo, za[0] + (za[1] - za[0]) * hi)
    return touched, removed


def _touch_plan(a, b):
    """(a's connection, b's connection) for an L or T join of two walls that meet, or an error."""
    la, lb = _wall_line(a), _wall_line(b)
    wa, wb = max(_width(a), 0.01), max(_width(b), 0.01)
    ends = [(i, j, math.dist(la[i], lb[j])) for i in (0, 1) for j in (0, 1)]
    i, j, d = min(ends, key=lambda x: x[2])
    names = ("ATSTART", "ATEND")
    if d <= max(wa, wb):
        return names[i], names[j]
    for i in (0, 1):
        if _distance_to_segment(la[i], *lb) <= wb / 2 + 0.01:
            return names[i], "ATPATH"
    for j in (0, 1):
        if _distance_to_segment(lb[j], *la) <= wa / 2 + 0.01:
            return "ATPATH", names[j]
    return "these walls don't meet: use Trim to corner"


def join_elements(guid1: str, guid2: str) -> str:
    """Join two walls (or beams): collinear elements of the same type that touch are merged into
    the first (Archicad's Merge; it keeps its GlobalId, the second's doors/windows and joins);
    two walls that meet get an L or T join, so they follow each other when edited (D54)."""
    if B._model is None:
        return A._fail("no model open")
    a, b = A._by_guid(guid1), A._by_guid(guid2)
    for e, what in ((a, "the first element"), (b, "the second element")):
        error = _check(e, what)
        if error:
            return A._fail(error)
    if a is b:
        return A._fail("pick two different elements")
    if a.is_a() != b.is_a() and not (a.is_a("IfcWall") and b.is_a("IfcWall")):
        return A._fail("a wall joins walls, a beam joins beams")
    if _collinear(a, b):
        plan = _merge_plan(a, b)
        if isinstance(plan, str):
            return A._fail(plan)
        lo, hi = plan
        made = {"merged": True}

        def merge():
            _adopt(a)
            _adopt(b)
            touched, removed = _merge(a, b, lo, hi)
            rebuilt = _regen(touched)
            return 1, _visible([a]) + rebuilt, removed

        return _finish(merge, made)
    if not a.is_a("IfcWall"):
        return A._fail("beams are only merged when they are in line")
    if _joined(a, b):
        return A._fail("they are already joined")
    plan = _touch_plan(a, b)
    if isinstance(plan, str):
        return A._fail(plan)
    mine, theirs = plan

    def connect():
        _adopt(a)
        _adopt(b)
        if theirs == "ATPATH" or mine != "ATPATH":
            ifcopenshell.api.geometry.connect_path(B._model, relating_element=a, related_element=b,
                                                   relating_connection=mine, related_connection=theirs)
        else:
            ifcopenshell.api.geometry.connect_path(B._model, relating_element=b, related_element=a,
                                                   relating_connection=theirs, related_connection=mine)
        _regen([a, b])
        return 2, _visible([a, b]), []

    return _finish(connect, {"merged": False})


def unjoin_elements(guids_json: str) -> str:
    """Break the joins between the given walls (one wall: all its joins). Unjoined walls no longer
    follow each other's edits (D54) and get plain ends."""
    if B._model is None:
        return A._fail("no model open")
    walls = [e for e in B._elements(guids_json) if e.is_a("IfcWall") or e.is_a("IfcBeam")]
    if not walls:
        return A._fail("pick the walls to unjoin")
    rels = []
    for w in walls:
        for rel in A._path_joins(w):
            if len(walls) == 1 or _other(rel, w) in walls:
                rels.append(rel)
    rels = list(dict.fromkeys(rels))
    if not rels:
        return A._fail("they are not joined")
    touched = list(dict.fromkeys(x for rel in rels for x in (rel.RelatingElement, rel.RelatedElement)))

    def action():
        for w in touched:
            _adopt(w)
        for rel in rels:
            B._model.remove(rel)
        _regen(touched)
        return len(rels), _visible(touched), []

    return _finish(action, {})


def modify_targets(storey_guid: str) -> str:
    """Beams on a level as plan lines (walls and grid lines come from snap_data), for picking."""
    storey = A._by_guid(storey_guid) if B._model is not None else None
    beams = []
    for rel in getattr(storey, "ContainsElements", ()) or () if storey is not None else ():
        for e in rel.RelatedElements:
            if e.is_a("IfcBeam"):
                axis = _beam_axis(e)
                if axis is not None:
                    beams.append({"guid": e.GlobalId, "x1": round(float(axis[0][0]), 6), "y1": round(float(axis[0][1]), 6),
                                  "x2": round(float(axis[1][0]), 6), "y2": round(float(axis[1][1]), 6),
                                  "width": round(_width(e), 6)})
    return B._dump({"beams": beams})
