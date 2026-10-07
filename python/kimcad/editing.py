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
