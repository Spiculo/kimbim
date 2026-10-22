# SPDX-License-Identifier: GPL-3.0-or-later
"""Everyday editing (Slice 17), after Archicad's Edit menu: copy with an offset or onto another level
(copy/paste, drag with Ctrl), Duplicate, Mirror (in place, or a copy), Multiply (linear and polar
arrays) and Offset. Copies get new GlobalIds and keep their layers; walls bring their doors/windows
and the joins between copied walls are copied. Same protocol as app_bridge.
"""
from __future__ import annotations

import json
import math

import ifcopenshell.api.geometry
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import numpy as np

from . import app_bridge as B
from . import authoring as A

DUPLICATE_OFFSET = (1.0, 1.0)  # metres: Archicad's Duplicate places the copy at an offset


def _translation(dx, dy, dz=0.0):
    t = np.eye(4)
    t[:3, 3] = [dx / A._scale(), dy / A._scale(), dz / A._scale()]
    return t


def _check(guids_json):
    elements = A._copyable(guids_json)
    if not elements:
        return None, A._fail("select the elements to copy (doors and windows come with their wall)")
    for e in elements:
        container = ifcopenshell.util.element.get_container(e)
        if container is None or not container.is_a("IfcBuildingStorey"):
            return None, A._fail(f"{e.GlobalId} is not on a level")
    return elements, None


def _copies(elements, transform, target=None):
    """Inside an action: copy each level's elements with `transform` (project units), onto `target`
    (a storey, keeping the height above the level) or their own level."""
    pairs = []
    by_level = {}
    for e in elements:
        by_level.setdefault(ifcopenshell.util.element.get_container(e), []).append(e)
    for level, group in by_level.items():
        t = transform.copy()
        if target is not None:
            t = _translation(0, 0, A._elevation(target) - A._elevation(level)) @ t
        pairs += A._copy_elements(group, target or level, t)
    return pairs


def _run_copy(elements, make_pairs):
    made = {}

    def action():
        pairs = make_pairs()
        made["copies"] = [c.GlobalId for e, c in pairs if e in elements]
        return len(made["copies"]), [c.GlobalId for _, c in pairs], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guids": made["copies"]})


def copy_elements(guids_json: str, dx, dy, dz=0.0, storey_guid: str = "") -> str:
    """Copy elements moved by (dx, dy, dz) metres; onto another level when `storey_guid` is given
    (paste on another level keeps the plan position, as in Archicad)."""
    if B._model is None:
        return A._fail("no model open")
    elements, error = _check(guids_json)
    if error:
        return error
    try:
        t = _translation(float(dx), float(dy), float(dz or 0.0))
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    target = A._by_guid(storey_guid) if storey_guid else None
    if storey_guid and (target is None or not target.is_a("IfcBuildingStorey")):
        return A._fail("unknown level")
    return _run_copy(elements, lambda: _copies(elements, t, target))


def duplicate_elements(guids_json: str) -> str:
    """Archicad's Duplicate (Ctrl+D): a copy next to the original, offset by 1 m in x and y."""
    return copy_elements(guids_json, *DUPLICATE_OFFSET)


def array_elements(guids_json: str, kind: str, params_json: str) -> str:
    """Multiply (Archicad): `linear` {dx, dy, count}: count copies, each (dx, dy) further; `polar`
    {cx, cy, angle, count}: count copies, each turned `angle` radians further around (cx, cy)."""
    if B._model is None:
        return A._fail("no model open")
    elements, error = _check(guids_json)
    if error:
        return error
    try:
        p = json.loads(params_json)
        count = int(p["count"])
        if kind == "linear":
            dx, dy = float(p["dx"]), float(p["dy"])
        elif kind == "polar":
            cx, cy, angle = float(p["cx"]), float(p["cy"]), float(p["angle"])
        else:
            return A._fail(f"unknown array kind {kind}")
    except (KeyError, TypeError, ValueError) as ex:
        return A._fail(f"bad parameters: {ex}")
    if not 1 <= count <= 1000:
        return A._fail("the number of copies must be between 1 and 1000")

    def make():
        pairs = []
        for i in range(1, count + 1):
            if kind == "linear":
                t = _translation(dx * i, dy * i)
            else:
                a = angle * i
                rot = np.array([[math.cos(a), -math.sin(a), 0, 0], [math.sin(a), math.cos(a), 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
                t = _translation(cx, cy) @ rot @ _translation(-cx, -cy)
            pairs += _copies(elements, t)
        return pairs

    return _run_copy(elements, make)


# ---------------------------------------------------------------- mirror

def _annotations():
    from . import annotations

    return annotations


def _stairs():
    from . import stairs

    return stairs


def _reflection(x1, y1, x2, y2):
    """2D reflection across the line through (x1, y1)-(x2, y2), as a function on (x, y) metres and
    on directions."""
    d = np.array([x2 - x1, y2 - y1], dtype=float)
    d /= np.linalg.norm(d)
    o = np.array([x1, y1], dtype=float)

    def point(p):
        v = np.asarray(p[:2], dtype=float) - o
        return o + 2 * np.dot(v, d) * d - v

    def direction(v):
        v = np.asarray(v[:2], dtype=float)
        return 2 * np.dot(v, d) * d - v

    return point, direction


def _mirror_placement(e, point, direction):
    """Reflect an element's position and heading (it stays upright and right-handed; its own shape is
    not reflected — fine for symmetric profiles such as columns and beams)."""
    s = A._scale()
    m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
    origin = point(m[:2, 3] * s) / s
    x = direction(m[:2, 0])
    matrix = np.eye(4)
    matrix[:2, 0] = x
    matrix[:2, 1] = [-x[1], x[0]]
    matrix[:2, 3] = origin
    matrix[2, 3] = m[2, 3]
    ifcopenshell.api.geometry.edit_object_placement(B._model, product=e, matrix=matrix, is_si=False)


def _flip_hand(door):
    """A mirrored door swings the other way: LEFT <-> RIGHT in its operation type."""
    op = getattr(door, "OperationType", None)
    if not op or op == "NOTDEFINED":
        door_type = ifcopenshell.util.element.get_type(door)
        op = getattr(door_type, "OperationType", None) or "SINGLE_SWING_LEFT"
    flipped = op.replace("LEFT", "\0").replace("RIGHT", "LEFT").replace("\0", "RIGHT")
    if flipped != op and hasattr(door, "OperationType"):
        door.OperationType = flipped


def _mirror(elements, point, direction):
    """Inside an action: mirror elements in place (GlobalIds kept). Walls are reversed so their
    layers land on the mirrored side; their doors/windows move to the mirrored spot (and swing the
    other way); slab outlines are reflected; other elements get a reflected position and heading.
    Returns the other elements it changed: the moved doors/windows and the walls that lost a join."""
    f = B._model
    walls = [e for e in elements if e.is_a("IfcWall") and A._axis_world(e) is not None]
    # Openings first read in the original walls (their distance from the wall start).
    hosted = []
    for w in walls:
        length = float(np.linalg.norm(np.subtract(*A._axis_world(w))))
        for rel in getattr(w, "HasOpenings", ()) or ():
            for fill in getattr(rel.RelatedOpeningElement, "HasFillings", ()) or ():
                info = A._opening_info(fill.RelatedBuildingElement)
                if info is not None:
                    hosted.append((fill.RelatedBuildingElement, w, length, info))
    released = []
    for w in walls:
        p1, p2 = A._axis_world(w)
        # Joins to walls that are not mirrored are dropped (they would no longer meet); those walls
        # lose their corner, so they are rebuilt below.
        for rel in list(getattr(w, "ConnectedTo", ()) or ()) + list(getattr(w, "ConnectedFrom", ()) or ()):
            if rel.is_a("IfcRelConnectsPathElements"):
                other = rel.RelatedElement if rel.RelatingElement == w else rel.RelatingElement
                if other not in walls:
                    f.remove(rel)
                    if other.is_a("IfcWall") and other not in released:
                        released.append(other)
        A._reaxis(w, point(p2), point(p1))  # reversed: start <-> end
    for w in walls:  # joins between mirrored walls: their ends swapped
        for rel in getattr(w, "ConnectedTo", ()) or ():
            if rel.is_a("IfcRelConnectsPathElements"):
                swap = {"ATSTART": "ATEND", "ATEND": "ATSTART"}
                rel.RelatingConnectionType = swap.get(rel.RelatingConnectionType, rel.RelatingConnectionType)
                rel.RelatedConnectionType = swap.get(rel.RelatedConnectionType, rel.RelatedConnectionType)
    for w in walls + released:
        if A._layer_set(w) is not None:
            A._regenerate(f, w)
    for element, wall, length, (opening, _, along, width, height, sill) in hosted:
        A._apply_opening_edit(element, opening, wall, length - along, width, height, sill)
        if element.is_a("IfcDoor"):
            _flip_hand(element)
    for e in elements:
        if e in walls:
            continue
        if e.is_a("IfcSlab") and _slab_outline_world(e):
            outline = [point(p) for p in _slab_outline_world(e)]
            _set_slab_outline(e, list(reversed(outline)))
        elif e.is_a("IfcAnnotation") and _annotations().mirror(e, point):
            pass  # plan annotations and drafting shapes: their points reflected (text stays readable)
        elif _stairs().mirror(e, point, direction):
            pass  # D88: stairs and ramps turn the other way, railings' paths are reflected
        else:
            _mirror_placement(e, point, direction)
    return [h[0] for h in hosted] + released


def mirror_elements(guids_json: str, x1, y1, x2, y2, copy=False) -> str:
    """Mirror across the line (x1, y1)-(x2, y2) (metres). `copy`: mirror a copy and keep the
    originals (Archicad: Ctrl while mirroring)."""
    if B._model is None:
        return A._fail("no model open")
    elements, error = _check(guids_json)
    if error:
        return error
    try:
        x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if math.hypot(x2 - x1, y2 - y1) < 1e-9:
        return A._fail("the mirror line needs two different points")
    point, direction = _reflection(x1, y1, x2, y2)
    copy = A._truthy(copy)
    made = {}

    def action():
        if copy:
            pairs = _copies(elements, np.eye(4))
            targets = [c for e, c in pairs if e in elements]
            made["copies"] = [c.GlobalId for c in targets]
        else:
            targets = list(elements)
            made["copies"] = []
        fills = _mirror(targets, point, direction)
        changed = [t.GlobalId for t in targets] + [x.GlobalId for x in fills]
        for w in targets:  # walls joined to mirrored ones were re-shaped too
            changed += [n.GlobalId for n in A._connected_walls(w)] if w.is_a("IfcWall") else []
        return len(targets), list(dict.fromkeys(changed)), []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guids": made["copies"]})


# ---------------------------------------------------------------- slabs: outlines

def _slab_solid(slab):
    body = ifcopenshell.util.representation.get_representation(slab, "Model", "Body", "MODEL_VIEW")
    for item in (body.Items if body is not None else ()):
        if item.is_a("IfcExtrudedAreaSolid") and item.SweptArea.is_a("IfcArbitraryClosedProfileDef"):
            return item
    return None


def _curve_points(curve):
    if curve.is_a("IfcPolyline"):
        return [tuple(float(c) for c in p.Coordinates[:2]) for p in curve.Points]
    if curve.is_a("IfcIndexedPolyCurve"):
        return [tuple(float(c) for c in p[:2]) for p in curve.Points.CoordList]
    return []


def _slab_outline_world(slab):
    """A slab's outline in world metres (closing point dropped), or [] if it has no simple profile."""
    solid = _slab_solid(slab)
    if solid is None:
        return []
    s = A._scale()
    pts = _curve_points(solid.SweptArea.OuterCurve)
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    m = ifcopenshell.util.placement.get_local_placement(slab.ObjectPlacement)
    position = ifcopenshell.util.placement.get_axis2placement(solid.Position) if solid.Position else np.eye(4)
    full = m @ position
    return [tuple((full @ np.array([x, y, 0.0, 1.0]))[:2] * s) for x, y in pts]


def _set_slab_outline(slab, outline):
    """Inside an action: rebuild a slab's body with a new outline (world metres), same thickness."""
    f = B._model
    s = A._scale()
    m = ifcopenshell.util.placement.get_local_placement(slab.ObjectPlacement)
    inverse = np.linalg.inv(m)
    local = [tuple((inverse @ np.array([x / s, y / s, 0.0, 1.0]))[:2] * s) for x, y in outline]
    solid = _slab_solid(slab)
    depth = float(solid.Depth) * s if solid is not None else 0.2
    representation = ifcopenshell.api.geometry.add_slab_representation(
        f, context=A._body_context(), depth=depth, polyline=local)
    A._replace_body(slab, representation)


def slab_outlines(storey_guid: str) -> str:
    """[{guid, points}]: the outlines of a level's slabs (world metres), for editing their corners."""
    storey = A._by_guid(storey_guid) if B._model is not None else None
    out = []
    for e in (A._contained(storey) if storey is not None else ()):
        if e.is_a("IfcSlab") and (pts := _slab_outline_world(e)):
            out.append({"guid": e.GlobalId, "points": [[round(x, 6), round(y, 6)] for x, y in pts]})
    return B._dump({"slabs": out})


def set_slab_outline(guid: str, points_json: str) -> str:
    """A slab's outline from new points (world metres, D98: a corner moved, added or deleted), its
    thickness and level kept (one undo step). At least three points, not crossing itself."""
    from . import drafting

    slab = A._by_guid(guid) if B._model is not None else None
    if slab is None or not slab.is_a("IfcSlab") or not _slab_outline_world(slab):
        return A._fail("not a slab with an outline")
    try:
        points = [(float(x), float(y)) for x, y in json.loads(points_json)]
    except (TypeError, ValueError) as ex:
        return A._fail(f"bad points: {ex}")
    if len(points) < 3:
        return A._fail("a slab needs at least three corners")
    if not drafting.is_simple(points) or abs(drafting.area(points)) < 1e-6:
        return A._fail("the outline would cross itself")

    def action():
        _set_slab_outline(slab, points)
        return 1, [slab.GlobalId], []

    return B._dump(B._run(action))


def slab_outline(guid: str) -> str:
    slab = A._by_guid(guid) if B._model is not None else None
    if slab is None or not slab.is_a("IfcSlab"):
        return A._fail("not a slab")
    return B._dump({"ok": True, "points": [[round(x, 6), round(y, 6)] for x, y in _slab_outline_world(slab)]})


def _offset_polygon(points, distance):
    """Offset a simple polygon's edges outwards by `distance` (inwards if negative), mitred corners."""
    pts = [np.array(p, dtype=float) for p in points]
    n = len(pts)
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) / 2
    sign = 1.0 if area > 0 else -1.0  # counter-clockwise: outwards is to the right of each edge
    lines = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        d = (b - a) / np.linalg.norm(b - a)
        normal = np.array([d[1], -d[0]]) * sign
        lines.append((a + normal * distance, d))
    out = []
    for i in range(n):
        (p, u), (q, v) = lines[i - 1], lines[i]
        den = u[0] * v[1] - u[1] * v[0]
        if abs(den) < 1e-12:
            out.append(tuple(q))
            continue
        t = ((q[0] - p[0]) * v[1] - (q[1] - p[1]) * v[0]) / den
        out.append(tuple(p + u * t))
    return out


FILLET_STEP_DEGREES = 10.0  # a fillet's arc as segments of at most this angle


def round_corners(points, closed: bool, size: float, mode: str = "fillet"):
    """Archicad's Fillet/Chamfer: every corner of a polyline (both ends kept when open) rounded with an
    arc of radius `size` (segments) or cut `size` back along each edge. A corner whose edges are too
    short takes the largest size that fits (half of each edge); straight corners are left alone."""
    pts = [np.array(p, dtype=float) for p in points]
    n = len(pts)
    out = []
    for i in range(n):
        if not closed and (i == 0 or i == n - 1):
            out.append(tuple(pts[i]))
            continue
        p, a, b = pts[i], pts[i - 1], pts[(i + 1) % n]
        la, lb = np.linalg.norm(a - p), np.linalg.norm(b - p)
        if la < 1e-9 or lb < 1e-9:
            out.append(tuple(p))
            continue
        u, v = (a - p) / la, (b - p) / lb
        turn = math.acos(max(-1.0, min(1.0, float(u @ v))))  # the corner's inside angle
        if turn > math.pi - 1e-6 or turn < 1e-6:
            out.append(tuple(p))
            continue
        if mode == "chamfer":
            t = min(size, la / 2, lb / 2)
            out += [tuple(p + u * t), tuple(p + v * t)]
            continue
        t = min(size / math.tan(turn / 2), la / 2, lb / 2)  # the tangent points' distance from the corner
        r = t * math.tan(turn / 2)
        bis = (u + v) / np.linalg.norm(u + v)
        centre = p + bis * (r / math.sin(turn / 2))
        s0, s1 = p + u * t - centre, p + v * t - centre
        a0, a1 = math.atan2(s0[1], s0[0]), math.atan2(s1[1], s1[0])
        sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi  # the short way round
        steps = max(1, math.ceil(abs(math.degrees(sweep)) / FILLET_STEP_DEGREES))
        out += [tuple(centre + r * np.array([math.cos(a0 + sweep * k / steps), math.sin(a0 + sweep * k / steps)]))
                for k in range(steps + 1)]
    return [(round(float(x), 6), round(float(y), 6)) for x, y in out]


def _wall_corner(w1, w2):
    """Where two straight walls' axes meet: (corner, u, v, end1, end2), u and v pointing from the corner
    along each wall, endN "start" or "end" (the end at the corner); None when they are parallel."""
    (a1, b1), (a2, b2) = (tuple(np.array(p, dtype=float) for p in A._axis_world(w)) for w in (w1, w2))
    d1, d2 = b1 - a1, b2 - a2
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-9:
        return None
    t = ((a2[0] - a1[0]) * d2[1] - (a2[1] - a1[1]) * d2[0]) / den
    corner = a1 + d1 * t
    out = [corner]
    for a, b in ((a1, b1), (a2, b2)):
        near_end = np.linalg.norm(b - corner) < np.linalg.norm(a - corner)
        far = a if near_end else b
        out.append((far - corner) / np.linalg.norm(far - corner))
    ends = ["end" if np.linalg.norm(b - corner) < np.linalg.norm(a - corner) else "start" for a, b in ((a1, b1), (a2, b2))]
    return out[0], out[1], out[2], ends[0], ends[1]


def _fillet_walls(w1, w2, size: float, mode: str) -> str:
    """Archicad's Fillet/Chamfer on two walls meeting at a corner: both pulled back from it and a
    curved wall tangent to both (fillet, radius `size` on the axes) or a straight one (chamfer, `size`
    back along each) between them, its layers continuing the first wall's (one undo step)."""
    from . import configure, curved_walls, layers, renovation

    corner = _wall_corner(w1, w2)
    if corner is None:
        return A._fail("the two walls are parallel: they have no corner")
    p, u, v, end1, end2 = corner
    turn = math.acos(max(-1.0, min(1.0, float(u @ v))))
    if turn < 1e-3 or turn > math.pi - 1e-3:
        return A._fail("the walls are in line: there is no corner to round")
    (a1, b1), (a2, b2) = (tuple(np.array(q, dtype=float) for q in A._axis_world(w)) for w in (w1, w2))
    room = min(np.linalg.norm((a1 if end1 == "end" else b1) - p), np.linalg.norm((a2 if end2 == "end" else b2) - p))
    t = size if mode == "chamfer" else size / math.tan(turn / 2)
    if t >= room - A.MIN_WALL_LENGTH:
        return A._fail(f"too big for these walls: at most {room * (1 if mode == 'chamfer' else math.tan(turn / 2)):.3f} m")
    q1, q2 = p + u * t, p + v * t
    storey = ifcopenshell.util.element.get_container(w1)
    wall_type = ifcopenshell.util.element.get_type(w1)
    height = A._wall_height(w1) or 3.0
    # walking w1 towards the corner, then on to w2: the new wall continues w1's faces
    usage = configure.usage_of(w1, reversed_=(end1 == "start"))
    made = {}

    def action():
        f = B._model
        for rel in list(A._path_joins(w1)):  # the corner's join goes; the walls now end at the new wall
            others = {rel.RelatingElement, rel.RelatedElement}
            if w2 in others:
                f.remove(rel)
        for w, end, q in ((w1, end1, q1), (w2, end2, q2)):
            a, b = (np.array(x, dtype=float) for x in A._axis_world(w))
            A._reaxis(w, q if end == "start" else a, b if end == "start" else q)
            A._regenerate(f, w, length=float(np.linalg.norm(b - a)), height=A._wall_height(w) or height)
        if mode == "chamfer":
            new = A._new_wall(storey, wall_type, q1, q2, height, usage_from=usage)
            for other, point in ((w1, q1), (w2, q2)):
                ifcopenshell.api.geometry.connect_wall(f, wall1=new, wall2=other, is_atpath=False)
            for w in (new, w1, w2):
                A._regenerate(f, w, length=float(np.linalg.norm(q2 - q1)), height=height)
        else:
            r = t * math.tan(turn / 2)
            bis = (u + v) / np.linalg.norm(u + v)
            centre = p + bis * (r / math.sin(turn / 2))
            through = centre - bis * r
            new = curved_walls.new_curved_wall(storey, wall_type, q1, q2, through, height, usage_from=usage)
        layers.assign_active(new)
        renovation.stamp_new(new)
        made["wall"] = new
        return 1, [w1.GlobalId, w2.GlobalId, new.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(str(ex) if isinstance(ex, ValueError) else f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["wall"].GlobalId})


def fillet_corners(guids_json: str, size, mode: str = "fillet") -> str:
    """Fillet or chamfer the corners of the selected slabs and 2D polylines and fills (one undo step)."""
    from . import annotations as N

    if B._model is None:
        return A._fail("no model open")
    if mode not in ("fillet", "chamfer"):
        return A._fail(f"unknown mode {mode}")
    try:
        size = float(size)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if size <= 0:
        return A._fail("the radius or distance must be more than zero")
    walls = [e for e in B._elements(guids_json) if e.is_a("IfcWall")]
    if walls:  # D97: two walls meeting at a corner: a curved (fillet) or straight (chamfer) wall between
        from . import curved_walls

        if len(walls) != 2:
            return A._fail("select the two walls of the corner")
        if (why := curved_walls.refusal(walls)) is not None:
            return A._fail(why)
        if any(A._axis_world(w) is None or A._layer_set(w) is None for w in walls):
            return A._fail("select two layered walls drawn by KimBim")
        return _fillet_walls(walls[0], walls[1], size, mode)
    slabs, shapes = [], []
    for e in B._elements(guids_json):
        if e.is_a("IfcSlab") and _slab_outline_world(e):
            slabs.append(e)
        elif e.is_a("IfcAnnotation"):
            data = N._read(e)
            if data and data[0] in ("polyline", "fill"):
                shapes.append((e, data[0] == "fill" or bool(N.extra_of(e).get("Closed"))))
    if not slabs and not shapes:
        return A._fail("select slabs, polylines or fills")

    def action():
        changed = []
        for slab in slabs:
            _set_slab_outline(slab, round_corners(_slab_outline_world(slab), True, size, mode))
            changed.append(slab.GlobalId)
        for a, closed in shapes:
            world = [(float(p[0]), float(p[1])) for p in N.world_points(a)]
            if closed and len(world) > 1 and np.allclose(world[0], world[-1]):
                world = world[:-1]
            N.replace_points(a, round_corners(world, closed, size, mode))
            changed.append(a.GlobalId)
        return len(changed), changed, []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def offset_elements(guids_json: str, distance) -> str:
    """Offset (Archicad): walls get a parallel copy `distance` metres to the left of their axis
    (negative: to the right); slabs grow (shrink if negative) their outline in place."""
    if B._model is None:
        return A._fail("no model open")
    elements = [e for e in B._elements(guids_json) if e.is_a("IfcWall") or e.is_a("IfcSlab")]
    if not elements:
        return A._fail("select walls or slabs to offset")
    try:
        distance = float(distance)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if abs(distance) < 1e-9:
        return A._fail("the offset distance must not be zero")
    walls = [e for e in elements if e.is_a("IfcWall") and A._axis_world(e) is not None]
    slabs = [e for e in elements if e.is_a("IfcSlab") and _slab_outline_world(e)]
    made = {}

    def action():
        copies, changed = [], []
        for w in walls:
            (x1, y1), (x2, y2) = A._axis_world(w)
            length = math.hypot(x2 - x1, y2 - y1)
            nx, ny = -(y2 - y1) / length, (x2 - x1) / length
            pairs = A._copy_elements([w], ifcopenshell.util.element.get_container(w),
                                     _translation(nx * distance, ny * distance))
            copies += [c for e, c in pairs if e is w]
            changed += [c.GlobalId for _, c in pairs]
        for slab in slabs:
            outline = _offset_polygon(_slab_outline_world(slab), distance)
            _set_slab_outline(slab, outline)
            changed.append(slab.GlobalId)
        made["copies"] = [c.GlobalId for c in copies]
        return len(walls) + len(slabs), changed, []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guids": made["copies"]})


def resize_elements(guids_json: str, cx, cy, factor) -> str:
    """Archicad's Resize: the selection scaled by `factor` about (cx, cy) in plan (metres). Walls,
    slabs and 2D shapes take the new lengths and outlines (thicknesses and heights stay); doors and
    windows keep their size, their place along the wall scaled; other elements move (one undo step)."""
    from . import annotations as N
    from . import curved_walls, drafting

    if B._model is None:
        return A._fail("no model open")
    picked = [e for e in B._elements(guids_json) if e.is_a("IfcProduct")]
    try:
        k = float(factor)
        if str(cx).strip() == "" or str(cy).strip() == "":  # about the selection's middle
            pts = []
            for e in picked:
                if e.is_a("IfcWall") and A._axis_world(e) is not None:
                    pts += list(A._axis_world(e))
                elif getattr(e, "ObjectPlacement", None) is not None:
                    pts.append(tuple(ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)[:2, 3] * A._scale()))
            pts = np.array(pts, dtype=float) if pts else np.zeros((1, 2))
            c = (pts.min(axis=0) + pts.max(axis=0)) / 2
        else:
            c = np.array([float(cx), float(cy)])
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if k <= 0 or abs(k - 1.0) < 1e-12:
        return A._fail("the factor must be more than 0 and not 1")
    hosted = {x for e in picked for x in A._hosted(e)}
    elements = [e for e in picked if e not in hosted]
    if not elements:
        return A._fail("select what to resize")
    scaled = lambda p: c + (np.asarray(p, dtype=float)[:2] - c) * k  # noqa: E731
    plans = []
    for e in elements:
        if e.is_a("IfcWall") and curved_walls.is_curved(e):
            plans.append(("curved", e, None))
        elif e.is_a("IfcWall") and A._axis_world(e) is not None and A._layer_set(e) is not None:
            a, b = (np.array(p, dtype=float) for p in A._axis_world(e))
            if np.linalg.norm(b - a) * k < A.MIN_WALL_LENGTH:
                return A._fail(f"{e.Name or 'a wall'} would have no length")
            plans.append(("wall", e, (scaled(a), scaled(b))))
        elif e.is_a("IfcSlab") and _slab_outline_world(e):
            plans.append(("slab", e, [tuple(scaled(p)) for p in _slab_outline_world(e)]))
        elif e.is_a("IfcAnnotation") and (data := N._read(e)) and data[0] in drafting.KINDS + ("dimension",):
            plans.append(("shape", e, [tuple(scaled(p)) for p in N.world_points(e)]))
        elif getattr(e, "ObjectPlacement", None) is not None:
            plans.append(("move", e, None))
    openings = {}
    for kind, e, _ in plans:
        if kind in ("wall", "curved"):
            openings[e] = [(fill, opening, along, width) + tuple(A._opening_info(fill)[4:])
                           for fill, opening, along, width in _fills(e)]

    def action():
        f = B._model
        s = A._scale()
        walls = []
        for kind, e, data in plans:
            if kind == "wall":
                A._reaxis(e, *data)
                walls.append(e)
            elif kind == "curved":
                m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
                inverse = np.linalg.inv(m)
                local = []
                for x, y in curved_walls.arc_of(e):
                    w = (m @ np.array([x / s, y / s, 0.0, 1.0]))[:2] * s
                    w = scaled(w)
                    local.append(list((inverse @ np.array([w[0] / s, w[1] / s, 0.0, 1.0]))[:2] * s))
                from . import configure

                configure._write_pset(e, curved_walls.WALL_PSET, {"Arc": json.dumps(local)})
                walls.append(e)
            elif kind == "slab":
                _set_slab_outline(e, data)
            elif kind == "shape":
                N.replace_points(e, data)
                read = N._read(e)
                if read[0] == "dimension":  # it measures again
                    origin = data[0]
                    local = [(x - origin[0], y - origin[1]) for x, y in data]
                    text = N._measure(local)
                    N._set(e, read[0], text, local, read[3], read[4])
                    e.Name = text[:60]
            else:
                m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
                moved = m.copy()
                moved[:2, 3] = scaled(m[:2, 3] * s) / s
                ifcopenshell.api.geometry.edit_object_placement(f, product=e, matrix=moved, is_si=False,
                                                                should_transform_children=True)
        for w in walls:
            A._regenerate(f, w, length=A._wall_length(w), height=A._wall_height(w) or 3.0)
        for w in walls:
            for fill, opening, along, width, height, sill in openings.get(w, ()):
                along = min(max(along * k, width / 2), A._wall_length(w) - width / 2)
                A._apply_opening_edit(fill, opening, w, along, width, height, sill)
        return len(plans), [e.GlobalId for _, e, _ in plans] + [x.GlobalId for e in walls for x in A._hosted(e)
                                                               if not x.is_a("IfcOpeningElement")], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(str(ex) if isinstance(ex, ValueError) else f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def _fills(wall):
    """(door/window, opening, along, width) in a wall."""
    out = []
    for rel in getattr(wall, "HasOpenings", ()) or ():
        opening = rel.RelatedOpeningElement
        for fill in getattr(opening, "HasFillings", ()) or ():
            info = A._opening_info(fill.RelatedBuildingElement)
            if info is not None:
                out.append((fill.RelatedBuildingElement, opening, info[2], info[3]))
    return out
