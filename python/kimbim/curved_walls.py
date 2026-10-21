# SPDX-License-Identifier: GPL-3.0-or-later
"""Curved walls (D97, Archicad's Wall tool, Curved geometry method): a layered wall along an arc.

The arc is kept in the wall's own coordinates in `KIMBIM_Wall.Arc` (start, end and a point on it,
metres) with the wall's height; its axis is an IfcIndexedPolyCurve arc (start, end, middle: readers
that take an axis' first two points get the chord) and its body the band between the layers' outer
radii, as an arc-sided profile extruded up (IFC4; IFC2X3 gets arcs as short segments). The layers
stack across the arc as on a straight wall: a reference line or composite change rebuilds the body.
Curved walls are not joined or given openings (yet): ifcopenshell's regenerator only knows lines.
"""
from __future__ import annotations

import json
import math

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.type
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import numpy as np

from . import app_bridge as B

WALL_PSET = "KIMBIM_Wall"
ARC_STEP_DEGREES = 5.0  # IFC2X3: arcs as segments of at most this angle


def _fail(message: str) -> str:
    return json.dumps({"ok": False, "error": message})


def _pset(wall) -> dict:
    return ifcopenshell.util.element.get_pset(wall, WALL_PSET) or {}


def is_curved(wall) -> bool:
    return bool(_pset(wall).get("Arc"))


def arc_of(wall):
    """(start, end, through) in the wall's own coordinates (metres), or None."""
    raw = _pset(wall).get("Arc")
    if not raw:
        return None
    pts = json.loads(raw)
    return tuple(tuple(float(c) for c in p) for p in pts)


def frame(start, end, through):
    """(centre, radius, start angle, sweep) of the arc from `start` through `through` to `end`."""
    from . import drafting

    return drafting.arc_frame(start, through, end)


def length(wall) -> float:
    """The arc's length (metres)."""
    arc = arc_of(wall)
    fr = frame(*arc) if arc else None
    return abs(fr[1] * fr[3]) if fr else 0.0


def refusal(elements) -> str | None:
    """Why an edit that needs a straight axis can't touch these elements (a curved wall), or None."""
    for e in elements:
        if e.is_a("IfcWall") and is_curved(e):
            return f"{e.Name or 'the wall'} is curved: this works on straight walls only"
    return None


def refusal_of(*guids) -> str | None:
    """refusal() for elements given by GlobalId (unknown ones are left to the caller)."""
    if B._model is None:
        return None
    found = []
    for g in guids:
        try:
            found.append(B._model.by_guid(g))
        except (RuntimeError, TypeError):
            continue
    return refusal(found)


def _offsets(wall):
    """(y0, y1): the body's sides to the axis' left (metres), from the layer usage."""
    from . import authoring as A

    usage = ifcopenshell.util.element.get_material(wall, should_skip_usage=False)
    s = A._scale()
    total = sum(float(l.LayerThickness or 0.0) for l in usage.ForLayerSet.MaterialLayers) * s
    off = float(usage.OffsetFromReferenceLine or 0.0) * s
    return (off, off + total) if usage.DirectionSense != "NEGATIVE" else (off - total, off)


def _arc_points(centre, r, a0, sweep, n):
    return [(centre[0] + r * math.cos(a0 + sweep * i / n), centre[1] + r * math.sin(a0 + sweep * i / n))
            for i in range(n + 1)]


def _curve(f, centre, r, a0, sweep, reverse=False):
    """IFC4: (points, one arc segment); IFC2X3: points only (a polyline)."""
    if f.schema == "IFC2X3":
        n = max(2, math.ceil(abs(math.degrees(sweep)) / ARC_STEP_DEGREES))
        pts = _arc_points(centre, r, a0, sweep, n)
    else:
        pts = _arc_points(centre, r, a0, sweep, 2)  # start, middle, end
    return list(reversed(pts)) if reverse else pts


def rebuild(wall) -> bool:
    """The body and axis from the stored arc and the wall's layers (the regenerator's stand-in)."""
    from . import authoring as A

    arc = arc_of(wall)
    if arc is None:
        return False
    f = B._model
    start, end, through = arc
    fr = frame(start, end, through)
    if fr is None:
        raise ValueError("the arc's three points are in a line")
    centre, R, a0, sweep = fr
    left = 1.0 if sweep > 0 else -1.0  # counter-clockwise: the axis' left is towards the centre
    y0, y1 = _offsets(wall)
    ra, rb = R - left * y0, R - left * y1
    if min(ra, rb) <= 0.01:
        raise ValueError("the wall is thicker than its arc's radius")
    height = float(_pset(wall).get("Height") or 3.0)
    k = 1.0 / A._scale()
    mitres = {end: m for end, m in ((j["end"], mitre(wall, j)) for j in arc_joins(wall)) if m is not None}
    reach = 3 * abs(y1 - y0) / max(min(ra, rb), 0.01)  # past a joined end, for its mitre to cut back
    b0 = a0 - left * (reach if "start" in mitres else 0.0)
    bsweep = sweep + left * (reach if "start" in mitres else 0.0) + left * (reach if "end" in mitres else 0.0)
    outer = _curve(f, centre, ra, b0, bsweep)
    inner = _curve(f, centre, rb, b0, bsweep, reverse=True)
    pts = outer + inner
    if f.schema == "IFC2X3":
        curve = f.createIfcPolyline([f.createIfcCartesianPoint((x * k, y * k)) for x, y in pts + pts[:1]])
        axis_curve = f.createIfcPolyline([f.createIfcCartesianPoint((x * k, y * k))
                                          for x, y in _curve(f, centre, R, a0, sweep)])
    else:
        coords = f.createIfcCartesianPointList2D([(x * k, y * k) for x, y in pts])
        curve = f.createIfcIndexedPolyCurve(coords, [
            f.createIfcArcIndex((1, 2, 3)), f.createIfcLineIndex((3, 4)),
            f.createIfcArcIndex((4, 5, 6)), f.createIfcLineIndex((6, 1))], False)
        a_start, a_mid, a_end = _curve(f, centre, R, a0, sweep)
        axis_curve = f.createIfcIndexedPolyCurve(  # start, end, middle: the chord comes first
            f.createIfcCartesianPointList2D([(x * k, y * k) for x, y in (a_start, a_end, a_mid)]),
            [f.createIfcArcIndex((1, 3, 2))], False)
    profile = f.createIfcArbitraryClosedProfileDef("AREA", None, curve)
    solid = f.createIfcExtrudedAreaSolid(profile, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None),
                                         f.createIfcDirection((0.0, 0.0, 1.0)), height * k)
    m = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
    inverse = np.linalg.inv(m)
    s = A._scale()
    for end, (q0, q1, away) in mitres.items():  # cut back to each mitre, on the side away from the arc
        lq0, lq1 = ((inverse @ np.array([q[0] / s, q[1] / s, 0.0, 1.0]))[:2] for q in (q0, q1))
        laway = (inverse[:2, :2] @ np.asarray(away, dtype=float))
        d = lq1 - lq0
        n = np.array([d[1], -d[0]]) / np.linalg.norm(d)
        if n @ laway < 0:
            n = -n
        plane = f.createIfcPlane(f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(lq0[0]), float(lq0[1]), 0.0)),
                                                             f.createIfcDirection((float(n[0]), float(n[1]), 0.0)),
                                                             f.createIfcDirection((0.0, 0.0, 1.0))))
        solid = f.createIfcBooleanClippingResult("DIFFERENCE", solid, f.createIfcHalfSpaceSolid(plane, False))
    A._replace_body(wall, f.createIfcShapeRepresentation(A._body_context(), "Body",
                                                         "Clipping" if mitres else "SweptSolid", [solid]))
    axis_rep = f.createIfcShapeRepresentation(_axis_context(), "Axis", "Curve2D", [axis_curve])
    old = ifcopenshell.util.representation.get_representation(wall, "Plan", "Axis", "GRAPH_VIEW")
    if old is not None:
        ifcopenshell.api.geometry.unassign_representation(f, product=wall, representation=old)
        ifcopenshell.api.geometry.remove_representation(f, representation=old)
    ifcopenshell.api.geometry.assign_representation(f, product=wall, representation=axis_rep)
    return True


def _axis_context():
    import ifcopenshell.api.context

    f = B._model
    ctx = ifcopenshell.util.representation.get_context(f, "Plan", "Axis", "GRAPH_VIEW")
    if ctx is None:
        plan = ifcopenshell.util.representation.get_context(f, "Plan")
        if plan is None:
            plan = ifcopenshell.api.context.add_context(f, context_type="Plan")
        ctx = ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="Axis",
                                                   target_view="GRAPH_VIEW", parent=plan)
    return ctx


def new_curved_wall(storey, wall_type, p1, p2, pm, height: float, reference: str = "", usage_from=None):
    """Inside an action: a curved wall from p1 through pm to p2 (world metres) on a level; its layers by
    `reference` ("" = centred) or `usage_from` ((offset metres, direction sense, reference name))."""
    from . import authoring as A
    from . import configure

    f = B._model
    wall = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name=wall_type.Name)
    ifcopenshell.api.type.assign_type(f, related_objects=[wall], relating_type=wall_type)
    if usage_from is not None:
        configure.set_usage(wall, *usage_from)
    elif reference:
        configure.apply_reference(wall, reference)
    else:
        A._centre_on_axis(wall, A._thickness(A._layer_set(wall_type)))
    matrix = np.eye(4)
    matrix[2, 3] = A._elevation(storey)
    ifcopenshell.api.geometry.edit_object_placement(f, product=wall, matrix=matrix, is_si=True)
    ifcopenshell.api.spatial.assign_container(f, products=[wall], relating_structure=storey)
    configure._write_pset(wall, WALL_PSET, {"Arc": json.dumps([list(map(float, p1)), list(map(float, p2)),
                                                               list(map(float, pm))]), "Height": float(height)})
    rebuild(wall)
    return wall


def create_curved_wall(storey_guid: str, type_guid: str, x1, y1, xm, ym, x2, y2, height, reference: str = "") -> str:
    """A curved wall of a layered type from (x1, y1) through (xm, ym) to (x2, y2) on a level (one undo
    step). `reference` (configure.REFERENCES): where the drawn arc is in the wall; "" = its centre."""
    from . import authoring as A
    from . import configure, layers, renovation

    if B._model is None:
        return _fail("no model open")
    try:
        p1, pm, p2 = (float(x1), float(y1)), (float(xm), float(ym)), (float(x2), float(y2))
        height = float(height)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    storey, wall_type = A._by_guid(storey_guid), A._by_guid(type_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return _fail("unknown level")
    if wall_type is None or A._layer_set(wall_type) is None:
        return _fail("unknown or non-layered wall type")
    if height <= 0:
        return _fail("the wall height must be positive")
    if reference and reference not in configure.REFERENCES:
        return _fail(f"unknown reference line {reference}")
    if frame(p1, p2, pm) is None or min(math.dist(p1, pm), math.dist(pm, p2)) < A.MIN_WALL_LENGTH:
        return _fail("the three points of a curved wall must not be in a line")
    made = {}

    def action():
        wall = new_curved_wall(storey, wall_type, p1, p2, pm, height, reference)
        layers.assign_active(wall)
        renovation.stamp_new(wall)
        made["wall"] = wall
        return 1, [wall.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(str(ex) if isinstance(ex, ValueError) else f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["wall"].GlobalId})


def ends_world(wall):
    """The arc's start and end in world metres."""
    from . import authoring as A

    start, end, _through = arc_of(wall)
    m = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
    s = A._scale()
    return [(m @ np.array([x / s, y / s, 0.0, 1.0]))[:2] * s for x, y in (start, end)]


def set_ends(wall, p1, p2) -> str:
    """Stretch a curved wall (D97, Archicad): its ends go round its circle to where p1 and p2 (world
    metres) point from its centre, keeping the radius and the way it turns; both ends moved by the
    same amount move the whole wall. Its doors and windows keep their place (one undo step)."""
    from . import authoring as A

    a, b = ends_world(wall)
    d1, d2 = np.asarray(p1, dtype=float) - a, np.asarray(p2, dtype=float) - b
    m = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
    s = A._scale()
    inverse = np.linalg.inv(m)
    (cx, cy), radius, a0, sweep = frame(*arc_of(wall))
    if np.linalg.norm(d1) > 1e-9 and np.allclose(d1, d2, atol=1e-9):  # the whole wall, its doors with it
        return A.move_elements(json.dumps([wall.GlobalId]), float(d1[0]), float(d1[1]))
    local = [(inverse @ np.array([q[0] / s, q[1] / s, 0.0, 1.0]))[:2] * s for q in (p1, p2)]
    turn = 1.0 if sweep > 0 else -1.0
    s0 = math.atan2(local[0][1] - cy, local[0][0] - cx)
    s1 = math.atan2(local[1][1] - cy, local[1][0] - cx)
    new_sweep = ((s1 - s0) * turn) % (2 * math.pi) * turn
    if abs(new_sweep) * radius < A.MIN_WALL_LENGTH:
        return A._fail("the wall has no length")
    at = lambda angle: (cx + radius * math.cos(angle), cy + radius * math.sin(angle))  # noqa: E731
    start, end, through = at(s0), at(s0 + new_sweep), at(s0 + new_sweep / 2)
    old = _pset(wall).get("Arc")

    def action():
        from . import configure

        configure._write_pset(wall, WALL_PSET, {"Arc": json.dumps([list(start), list(end), list(through)])})
        A._regenerate(B._model, wall)  # its body, and the walls mitred into it
        for e in A._hosted(wall):  # each door or window where it was, if it is still on the wall
            info = A._opening_info(e) if not e.is_a("IfcOpeningElement") else None
            if info is not None and A._opening_fit_error(wall, *info[2:]):
                configure._write_pset(wall, WALL_PSET, {"Arc": old})
                raise ValueError(f"{e.Name or 'a door or window'} would be off the wall")
        A._refit_openings(wall)
        return 1, [wall.GlobalId, *(e.GlobalId for e in A._hosted(wall) if not e.is_a("IfcOpeningElement"))], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(str(ex) if isinstance(ex, ValueError) else f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def set_length(wall, metres: float) -> str:
    """A curved wall's arc made `metres` long from its start (D97): its end goes round the circle."""
    from . import authoring as A

    (cx, cy), radius, a0, sweep = frame(*arc_of(wall))
    turned = metres / radius
    if turned >= 2 * math.pi - 1e-6:
        return A._fail("a curved wall can't go all the way round its circle")
    m = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
    s = A._scale()
    angle = a0 + (turned if sweep > 0 else -turned)
    local = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
    end = (m @ np.array([local[0] / s, local[1] / s, 0.0, 1.0]))[:2] * s
    start, _old_end = ends_world(wall)
    return set_ends(wall, start, end)


# ---------------------------------------------------------------- joins with straight walls (D97)
# A straight wall drawn to or from a curved wall's end meets it in a mitre, as Archicad's walls do:
# the line through where their outside faces meet and where their inside faces meet (the arc's faces
# taken along its tangent there). The regenerator knows only lines, so KimBim keeps these joins in
# KIMBIM_Wall.ArcJoins on both walls ([{wall, end}]: the other wall, and which end of this one) and
# recomputes the mitre from both walls as they are whenever either is rebuilt.

def arc_joins(wall) -> list:
    raw = _pset(wall).get("ArcJoins")
    return [j for j in (json.loads(raw) if raw else []) if _partner(j) is not None]


def _partner(join):
    try:
        return B._model.by_guid(join["wall"])
    except (RuntimeError, KeyError, TypeError):
        return None


def _ends(wall):
    """(start, end) of a wall's axis in world metres: the arc's or the line's."""
    from . import authoring as A

    if is_curved(wall):
        return tuple(np.asarray(p, dtype=float) for p in ends_world(wall))
    return tuple(np.asarray(p, dtype=float) for p in A._axis_world(wall))


def _leaving(wall, end):
    """(unit direction from the end into the wall, unit normal to the wall's left there), world."""
    from . import authoring as A

    if is_curved(wall):
        (cx, cy), radius, a0, sweep = frame(*arc_of(wall))
        m = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
        turn = 1.0 if sweep > 0 else -1.0
        angle = a0 if end == "start" else a0 + sweep
        tangent = np.array([-math.sin(angle), math.cos(angle)]) * turn  # along the arc's travel
        tangent = m[:2, :2] @ tangent
        tangent /= np.linalg.norm(tangent)
        left = np.array([-tangent[1], tangent[0]])
        return (tangent if end == "start" else -tangent), left
    a, b = _ends(wall)
    u = (b - a) / np.linalg.norm(b - a)
    return (u if end == "start" else -u), np.array([-u[1], u[0]])


def _sides(wall):
    """(y0, y1) of the wall's body across its axis (to its left, metres)."""
    from . import authoring as A

    usage = ifcopenshell.util.element.get_material(wall, should_skip_usage=False)
    if usage is None or not usage.is_a("IfcMaterialLayerSetUsage"):
        t = A._thickness(A._layer_set(wall)) if A._layer_set(wall) else 0.0
        return -t / 2, t / 2
    return _offsets(wall)


def mitre(wall, join):
    """(q0, q1, away) of a join's mitre, world metres: the line through q0 and q1, and the direction
    across it into the other wall (the side this wall is cut back from); None when the walls no
    longer meet there or run on in line (nothing to cut)."""
    other = _partner(join)
    if other is None:
        return None
    mine = join["end"]
    point = _ends(wall)[0 if mine == "start" else 1]
    theirs = min(("start", "end"), key=lambda e: np.linalg.norm(_ends(other)[0 if e == "start" else 1] - point))
    if np.linalg.norm(_ends(other)[0 if theirs == "start" else 1] - point) > 0.02:
        return None  # one of them moved away: no longer joined
    d1, n1 = _leaving(wall, mine)
    d2, n2 = _leaving(other, theirs)
    if abs(d1[0] * d2[1] - d1[1] * d2[0]) < 1e-6:
        return None  # in line: they meet square
    s1, s2 = _sides(wall), _sides(other)
    # walking through the corner, the walls' left sides match when one arrives and the other leaves
    same = (mine == "end") != (theirs == "end")
    pairs = [(s1[0], s2[0] if same else -s2[0]), (s1[1], s2[1] if same else -s2[1])]
    qs = []
    for y1, y2 in pairs:
        p1, p2 = point + n1 * y1, point + n2 * y2
        den = d1[0] * d2[1] - d1[1] * d2[0]
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
        qs.append(p1 + d1 * t)
    if np.linalg.norm(qs[1] - qs[0]) < 1e-6:
        return None
    return qs[0], qs[1], d2


def adjust_straight(wall):
    """Inside an action, after the regenerator built a straight wall: its ends joined to curved walls
    reach their mitres (the footprint's corners there slide along the wall to the mitre line)."""
    from . import authoring as A

    joins = [(j, mitre(wall, j)) for j in arc_joins(wall)]
    joins = [(j, m) for j, m in joins if m is not None]
    if not joins:
        return
    rep = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
    solids = []
    for item in (rep.Items if rep is not None else ()):
        while item.is_a("IfcBooleanResult"):
            item = item.FirstOperand
        if item.is_a("IfcExtrudedAreaSolid"):
            solids.append(item)
    m = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
    inverse = np.linalg.inv(m)
    s = A._scale()
    for solid in solids:
        curve = getattr(solid.SweptArea, "OuterCurve", None)
        if curve is None:
            continue
        place = ifcopenshell.util.placement.get_axis2placement(solid.Position) if solid.Position else np.eye(4)
        if curve.is_a("IfcPolyline"):
            coords = [list(p.Coordinates) for p in curve.Points]
        elif curve.is_a("IfcIndexedPolyCurve"):
            coords = [list(c) for c in curve.Points.CoordList]
        else:
            continue
        xs = [float(c[0]) for c in coords]
        for join, (q0, q1, _away) in joins:
            # the mitre in the profile's own coordinates
            to_profile = np.linalg.inv(place) @ inverse
            lq0, lq1 = ((to_profile @ np.array([q[0] / s, q[1] / s, 0.0, 1.0]))[:2] for q in (q0, q1))
            target = min(xs) if join["end"] == "start" else max(xs)
            for c in coords:
                if abs(float(c[0]) - target) < 1e-6 and abs(lq1[1] - lq0[1]) > 1e-12:
                    c[0] = float(lq0[0] + (lq1[0] - lq0[0]) * (float(c[1]) - lq0[1]) / (lq1[1] - lq0[1]))
        f = B._model
        if curve.is_a("IfcPolyline"):
            for p, c in zip(curve.Points, coords):
                p.Coordinates = tuple(float(v) for v in c)
        else:
            curve.Points = f.createIfcCartesianPointList2D([tuple(float(v) for v in c[:2]) for c in coords])


def join_to_curved(straight, curved, point) -> bool:
    """Inside an action: record a mitred join between a straight wall's end at `point` and a curved
    wall's end there (both walls rebuilt by the caller); False if neither of its ends is there."""
    from . import configure

    s_end = min(("start", "end"), key=lambda e: np.linalg.norm(_ends(straight)[0 if e == "start" else 1] - point))
    c_end = min(("start", "end"), key=lambda e: np.linalg.norm(_ends(curved)[0 if e == "start" else 1] - point))
    if np.linalg.norm(_ends(curved)[0 if c_end == "start" else 1] - np.asarray(point)) > 0.02:
        return False
    for wall, end, other in ((straight, s_end, curved), (curved, c_end, straight)):
        joins = [j for j in arc_joins(wall) if j["end"] != end]
        joins.append({"wall": other.GlobalId, "end": end})
        configure._write_pset(wall, WALL_PSET, {"ArcJoins": json.dumps(joins)})
    return True
