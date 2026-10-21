# SPDX-License-Identifier: GPL-3.0-or-later
"""Rooms (Slice 18), after Archicad's zones: click inside walls and the room takes the shape the wall
faces enclose. A room is an IfcSpace in its level (number in Name, name in LongName, as Archicad
exports zones), with its area in Qto_SpaceBaseQuantities. KimBim keeps the clicked point
(KIMBIM_Room.SeedX/SeedY), so when walls move the room is re-fitted in the same undo step.
Same protocol as app_bridge.
"""
from __future__ import annotations

import csv
import json
import math

import ifcopenshell.api.aggregate
import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.unit
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import layers
from . import renovation

PSET = "KIMBIM_Room"
QTO = "Qto_SpaceBaseQuantities"
DEFAULT_HEIGHT = 3.0  # metres, on the top level (else up to the next level)
_EPS = 1e-7


# ---------------------------------------------------------------- the boundary from wall faces


def _ws(storey) -> bool:
    from .worksheets import is_worksheet

    return is_worksheet(storey)

def _faces(storey):
    """Wall faces on a level as segments (world metres): both sides of each wall axis, extended at
    the ends so faces of joined walls cross, plus the wall ends."""
    segments = []
    for e in A._contained(storey):
        if not e.is_a("IfcWall"):
            continue
        axis = A._axis_world(e)
        layer_set = A._layer_set(e)
        if axis is None or layer_set is None:
            continue
        t = A._thickness(layer_set)
        p1, p2 = np.array(axis[0], dtype=float), np.array(axis[1], dtype=float)
        d = p2 - p1
        length = float(np.linalg.norm(d))
        if length < _EPS:
            continue
        d /= length
        n = np.array([-d[1], d[0]])
        ext = max(t, 0.5)
        for side in (1, -1):
            a = p1 + n * side * t / 2 - d * ext
            b = p2 + n * side * t / 2 + d * ext
            segments.append((a, b))
        segments.append((p1 + n * t / 2, p1 - n * t / 2))
        segments.append((p2 + n * t / 2, p2 - n * t / 2))
    return segments


def _intersection(a, b, c, d):
    """Parameter t on a-b where it crosses c-d (both within their extents), or None."""
    r, s = b - a, d - c
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return t
    return None


def _graph(segments):
    """Planar graph of the segments split where they cross: {node: set(neighbours)}, nodes rounded."""
    key = lambda p: (round(float(p[0]), 6), round(float(p[1]), 6))  # noqa: E731
    adjacency = {}
    for i, (a, b) in enumerate(segments):
        ts = {0.0, 1.0}
        for j, (c, d) in enumerate(segments):
            if i != j:
                t = _intersection(a, b, c, d)
                if t is not None:
                    ts.add(min(max(t, 0.0), 1.0))
        points = [key(a + (b - a) * t) for t in sorted(ts)]
        for p, q in zip(points, points[1:]):
            if p != q:
                adjacency.setdefault(p, set()).add(q)
                adjacency.setdefault(q, set()).add(p)
    # Dangling ends (the face extensions past a corner) bound no room.
    changed = True
    while changed:
        changed = False
        for node in [n for n, nb in adjacency.items() if len(nb) < 2]:
            for other in adjacency.pop(node, ()):
                adjacency.get(other, set()).discard(node)
            changed = True
    return adjacency


def boundary(storey, x, y):
    """The polygon (counter-clockwise, world metres) of the wall-enclosed region around (x, y), or
    None if the point is not enclosed (or sits inside a wall)."""
    adjacency = _graph(_faces(storey))
    p = np.array([x, y], dtype=float)
    # The edge first hit by a ray towards +x; the region is on its left when walked the right way.
    best, start = math.inf, None
    for a, nbs in adjacency.items():
        for b in nbs:
            if a >= b:
                continue
            A_, B_ = np.array(a), np.array(b)
            if (A_[1] > y) == (B_[1] > y) or abs(B_[1] - A_[1]) < 1e-12:
                continue
            t = (y - A_[1]) / (B_[1] - A_[1])
            hit = A_[0] + t * (B_[0] - A_[0])
            if hit > x and hit - x < best:
                best = hit - x
                cross = (B_[0] - A_[0]) * (y - A_[1]) - (B_[1] - A_[1]) * (x - A_[0])
                start = (a, b) if cross > 0 else (b, a)
    if start is None:
        return None
    polygon, (u, v) = [start[0]], start
    for _ in range(10000):
        polygon.append(v)
        back = math.atan2(u[1] - v[1], u[0] - v[0])
        # Next edge: the first one clockwise from the way back (keeps the region on the left).
        options = [w for w in adjacency[v] if w != u] or [u]
        u, v = v, max(options, key=lambda w: (math.atan2(w[1] - v[1], w[0] - v[0]) - back) % (2 * math.pi) - 2 * math.pi
                      if (math.atan2(w[1] - v[1], w[0] - v[0]) - back) % (2 * math.pi) > 1e-12 else -1e9)
        if (u, v) == start:
            break
    else:
        return None
    polygon = polygon[:-1]
    pts = _simplify([np.array(q) for q in polygon])
    if len(pts) < 3 or _signed_area(pts) <= 1e-6 or not _inside(p, pts):
        return None  # the outside of the building, or a degenerate region
    return [(float(q[0]), float(q[1])) for q in pts]


def _simplify(points):
    """Drop repeated and collinear points."""
    out = []
    for q in points:
        if out and np.linalg.norm(q - out[-1]) < 1e-6:
            continue
        out.append(q)
    if len(out) > 1 and np.linalg.norm(out[0] - out[-1]) < 1e-6:
        out.pop()
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
            if abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 1e-9:
                out.pop(i)
                changed = True
                break
    return out


def _signed_area(points) -> float:
    n = len(points)
    return sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1] for i in range(n)) / 2


def _perimeter(points) -> float:
    return sum(math.dist(points[i], points[(i + 1) % len(points)]) for i in range(len(points)))


def _inside(p, polygon) -> bool:
    inside = False
    n = len(polygon)
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        if (a[1] > p[1]) != (b[1] > p[1]):
            if p[0] < a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
                inside = not inside
    return inside


# ---------------------------------------------------------------- rooms in the model

def _rooms(storey=None):
    """KimBim's rooms (spaces with KIMBIM_Room), found through their property sets: imported models can
    have hundreds of other spaces."""
    out = []
    for pset in B._model.by_type("IfcPropertySet"):
        if pset.Name != PSET:
            continue
        for space in B._pset_users(pset):
            if space.is_a("IfcSpace") and (storey is None or ifcopenshell.util.element.get_aggregate(space) == storey):
                out.append(space)
    return sorted(out, key=lambda s: s.id())


def _height(storey) -> float:
    above = sorted((A._elevation(s) for s in B._model.by_type("IfcBuildingStorey")
                    if not A._is_model(s) and not _ws(s) and A._elevation(s) > A._elevation(storey) + 1e-6))
    return above[0] - A._elevation(storey) if above else DEFAULT_HEIGHT


def _shape(space, storey, outline):
    """Inside an action: the room's body (its outline extruded to the level above) and its areas."""
    f = B._model
    height = _height(storey)
    matrix = np.eye(4)
    matrix[2][3] = A._elevation(storey)
    ifcopenshell.api.geometry.edit_object_placement(f, product=space, matrix=matrix, is_si=True)
    representation = ifcopenshell.api.geometry.add_slab_representation(
        f, context=A._body_context(), depth=height, polyline=outline)
    A._replace_body(space, representation)
    # Quantities are in the project's units (D77): lengths in its length unit, areas in its area unit.
    s, sa = A._scale(), ifcopenshell.util.unit.calculate_unit_scale(f, "AREAUNIT")
    area = abs(_signed_area(outline)) / sa
    qto = ifcopenshell.util.element.get_pset(space, QTO)
    qto = f.by_id(qto["id"]) if qto else ifcopenshell.api.pset.add_qto(f, product=space, name=QTO)
    ifcopenshell.api.pset.edit_qto(f, qto=qto, properties={
        "NetFloorArea": round(area, 6), "GrossFloorArea": round(area, 6),
        "NetPerimeter": round(_perimeter(outline) / s, 6), "Height": round(height / s, 6)})


def _next_number(storey) -> str:
    levels = sorted((s for s in B._model.by_type("IfcBuildingStorey") if not A._is_model(s) and not _ws(s)),
                    key=A._elevation)
    base = (levels.index(storey) + 1) * 100 if storey in levels else 100
    taken = {s.Name for s in _rooms()}
    n = base + 1
    while str(n) in taken:
        n += 1
    return str(n)


def create_room(storey_guid: str, x, y, name: str = "") -> str:
    """A room filling the wall-enclosed region around (x, y) on a level (Archicad: a zone placed with
    the magic wand). Numbered per level: 101, 102... on the first level, 201... on the second."""
    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    try:
        x, y = float(x), float(y)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    outline = boundary(storey, x, y)
    if outline is None:
        return A._fail("click inside a space enclosed by walls")
    for other in _rooms(storey):
        if _inside((x, y), _outline(other)):
            return A._fail(f"there is already a room here ({other.Name} {other.LongName or ''})".strip())
    number = _next_number(storey)
    made = {}

    def action():
        f = B._model
        space = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSpace", name=number, predefined_type="INTERNAL")
        space.LongName = (name or "").strip() or "Room"
        ifcopenshell.api.aggregate.assign_object(f, products=[space], relating_object=storey)
        pset = ifcopenshell.api.pset.add_pset(f, product=space, name=PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"SeedX": x, "SeedY": y})
        _shape(space, storey, outline)
        layers.assign_active(space)
        renovation.stamp_new(space)
        made["guid"] = space.GlobalId
        return 1, [space.GlobalId], []

    r = B._run(action)
    return B._dump({**r, "guid": made["guid"]})


def _outline(space):
    """The room's outline in world metres, from its body."""
    from . import editing

    return editing._slab_outline_world(space)


def rooms(storey_guid: str) -> str:
    """[{guid, number, name, area, perimeter, points, label}] on a level (world metres)."""
    storey = A._by_guid(storey_guid) if B._model is not None else None
    out = []
    if storey is not None:
        from . import tags

        spaces = [(space, _outline(space)) for space in _rooms(storey)]
        spaces = [(space, pts) for space, pts in spaces if pts]
        template = tags.styles()["room"].get("template", "")
        stamps = tags.texts([(space, template) for space, _ in spaces]) if spaces else {}
        for space, pts in spaces:
            # From the outline (what the stamp shows; the room is re-fitted to it), in metres. The stamp's
            # text is the room stamp tag style's (D87).
            out.append({"guid": space.GlobalId, "number": space.Name or "", "name": space.LongName or "",
                        "area": round(abs(_signed_area(pts)), 6), "perimeter": round(_perimeter(pts), 6),
                        "points": [[round(px, 6), round(py, 6)] for px, py in pts], "label": _stamp_point(space, pts),
                        "stamp": stamps[space.GlobalId + "|" + template]})
    out.sort(key=lambda r: r["number"])
    return B._dump({"rooms": out})


def _stamp_point(space, points):
    """Where the stamp goes: where the room was clicked (Archicad's zone reference point) while that is
    inside the room, else a point inside it."""
    data = ifcopenshell.util.element.get_pset(space, PSET) or {}
    seed = (float(data.get("SeedX", math.nan)), float(data.get("SeedY", math.nan)))
    if not math.isnan(seed[0]) and _inside(seed, points):
        return [round(seed[0], 6), round(seed[1], 6)]
    return _label_point(points)


def _label_point(points):
    """Where the stamp goes: the centroid, or (for odd shapes) a point inside the room."""
    a = _signed_area(points)
    if abs(a) < 1e-9:
        return [points[0][0], points[0][1]]
    cx = cy = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        k = x0 * y1 - x1 * y0
        cx += (x0 + x1) * k
        cy += (y0 + y1) * k
    c = (cx / (6 * a), cy / (6 * a))
    if not _inside(c, points):  # e.g. an L: the middle of the longest edge, nudged inwards
        i = max(range(n), key=lambda i: math.dist(points[i], points[(i + 1) % n]))
        (x0, y0), (x1, y1) = points[i], points[(i + 1) % n]
        length = math.dist((x0, y0), (x1, y1))
        c = ((x0 + x1) / 2 - (y1 - y0) / length * 0.6, (y0 + y1) / 2 + (x1 - x0) / length * 0.6)
    return [round(c[0], 6), round(c[1], 6)]


def edit_room(guid: str, changes_json: str) -> str:
    """{name, number}."""
    space = A._by_guid(guid) if B._model is not None else None
    if space is None or not space.is_a("IfcSpace"):
        return A._fail("not a room")
    try:
        changes = json.loads(changes_json)
    except ValueError as ex:
        return A._fail(str(ex))

    def action():
        if changes.get("name") is not None:
            space.LongName = str(changes["name"]).strip() or space.LongName
        if changes.get("number"):
            space.Name = str(changes["number"]).strip()
        return 1

    return B._dump(B._run(action))


def _is_wall(guid) -> bool:
    try:
        return B._model.by_guid(guid).is_a("IfcWall")
    except RuntimeError:
        return False


def _refit(changed, removed):
    """After an edit: rooms on levels whose walls changed take their walls' new shape (same undo step).
    A room whose walls no longer enclose it keeps its last shape."""
    if B._model is None or not B._model.by_type("IfcSpace"):
        return []
    if not removed and not any(_is_wall(g) for g in changed):
        return []  # only walls shape rooms (cheap check for every edit)
    levels = set()
    for g in list(changed) + list(removed):
        try:
            e = B._model.by_guid(g)
        except RuntimeError:
            levels = None  # something was deleted: check every level
            break
        if e.is_a("IfcWall"):
            container = ifcopenshell.util.element.get_container(e)
            if container is not None:
                levels.add(container)
    out = []
    for space in _rooms():
        storey = ifcopenshell.util.element.get_aggregate(space)
        if storey is None or (levels is not None and storey not in levels):
            continue
        data = ifcopenshell.util.element.get_pset(space, PSET) or {}
        outline = boundary(storey, float(data.get("SeedX", 0.0)), float(data.get("SeedY", 0.0)))
        if outline is None or np.allclose(sorted(outline), sorted(_outline(space)), atol=1e-6):
            continue
        _shape(space, storey, outline)
        out.append(space.GlobalId)
    return out


B.AFTER_ACTION.append(_refit)


# ---------------------------------------------------------------- schedule

def room_schedule() -> str:
    """Every room (space): number, name, level, area (m²), perimeter (m), height (m); by level then
    number. The "rooms" schedule of kimbim.schedules (D77) in its original shape."""
    from . import schedules

    if B._model is None:
        return B._dump({"rows": []})
    scheme = {"name": "Rooms", "classes": ["IfcSpace"], "fields": [
        {"source": "attribute", "name": "Name"}, {"source": "attribute", "name": "LongName"},
        {"source": "info", "name": "level"}, {"source": "quantity", "name": "area"},
        {"source": "quantity", "name": "perimeter"}, {"source": "quantity", "name": "height"}]}
    data = schedules.compute(scheme)
    rows = []
    for r in data["rows"]:
        number, name, level, area, perimeter, height = r["values"]
        rows.append({"guid": r["guids"][0], "number": number or "", "name": name or "", "level": level or "",
                     "area": round(float(area or 0.0), 2), "perimeter": round(float(perimeter or 0.0), 2),
                     "height": round(float(height or 0.0), 2)})
    return B._dump({"rows": rows, "total_area": round(sum(r["area"] for r in rows), 2)})


def export_room_schedule(path: str) -> str:
    """The room schedule as CSV (UTF-8, comma-separated, a total row)."""
    data = json.loads(room_schedule())
    try:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Number", "Name", "Level", "Area (m²)", "Perimeter (m)", "Height (m)"])
            for r in data["rows"]:
                w.writerow([r["number"], r["name"], r["level"], f"{r['area']:.2f}", f"{r['perimeter']:.2f}", f"{r['height']:.2f}"])
            w.writerow(["Total", "", "", f"{data['total_area']:.2f}", "", ""])
    except OSError as ex:
        return A._fail(str(ex))
    return B._dump({"ok": True, "path": path, "rooms": len(data["rows"])})
