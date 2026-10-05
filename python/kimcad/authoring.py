# SPDX-License-Identifier: GPL-3.0-or-later
"""Modeling commands for the desktop app (M3): new project, levels, layered walls and their joins.

Same protocol as app_bridge (strings in, JSON out, never raise). Lengths cross the boundary in
metres; the model keeps its own unit (new projects: millimetres, D51). Every command is one
undoable transaction through app_bridge._run and reports which shapes changed so the app can
re-mesh only those. Wall geometry and joins reuse ifcopenshell.api.geometry (Bonsai's wall logic).
"""
from __future__ import annotations

import json
import math

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.material
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.type
import ifcopenshell.api.unit
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import ifcopenshell.util.unit
import numpy as np

from . import app_bridge as B

# Default wall types created the first time a model without layered wall types needs one.
DEFAULT_WALL_TYPES = [
    ("Generic 200", [("Generic", 0.2)]),
    ("Exterior 300", [("Brick", 0.1), ("Insulation", 0.08), ("Block", 0.12)]),
]
DEFAULT_SLAB_TYPES = [
    ("Floor 200", [("Concrete", 0.2)]),
    ("Floor 300", [("Screed", 0.05), ("Insulation", 0.05), ("Concrete", 0.2)]),
]
# Doors and windows: (name, width, height, sill) in metres. IFC types have no size attributes, so
# the defaults live in a custom pset on the type (D53); occurrences carry OverallWidth/Height.
DEFAULT_OPENING_TYPES = {
    "door": [("Door 900x2100", 0.9, 2.1, 0.0), ("Door 800x2100", 0.8, 2.1, 0.0)],
    "window": [("Window 1200x1200", 1.2, 1.2, 0.9), ("Window 600x600", 0.6, 0.6, 1.5)],
}
OPENING_PSET = "KIMCAD_OpeningDefaults"
OPENING_CLASSES = {"door": ("IfcDoor", "IfcDoorType"), "window": ("IfcWindow", "IfcWindowType")}
MIN_WALL_LENGTH = 0.001  # metres; shorter clicks create nothing


def _scale() -> float:
    """Metres per model length unit."""
    return ifcopenshell.util.unit.calculate_unit_scale(B._model)


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def _by_guid(guid: str):
    try:
        return B._model.by_guid(guid) if guid else None
    except RuntimeError:
        return None


# ---------------------------------------------------------------- project and levels

def new_project(name: str = "") -> str:
    """Start an empty IFC4 project in millimetres with one level, not yet saved anywhere."""
    try:
        f = ifcopenshell.api.project.create_file(version="IFC4")
        project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name=name or "Project")
        ifcopenshell.api.unit.assign_unit(f)  # millimetres, square/cubic metres, radians
        model = ifcopenshell.api.context.add_context(f, context_type="Model")
        ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body",
                                             target_view="MODEL_VIEW", parent=model)
        plan = ifcopenshell.api.context.add_context(f, context_type="Plan")
        ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="Axis",
                                             target_view="GRAPH_VIEW", parent=plan)
        site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
        building = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Building")
        ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
        ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)
        for product in (site, building):
            ifcopenshell.api.geometry.edit_object_placement(f, product=product)
        B._model = f
        _make_storey("Level 1", 0.0)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    B._reset_history("")
    return B._dump({"ok": True, "project": project.Name})


def _elevation(storey) -> float:
    """A storey's elevation in metres, from its placement (what geometry uses), else its attribute."""
    if storey.ObjectPlacement is not None:
        return float(ifcopenshell.util.placement.get_local_placement(storey.ObjectPlacement)[2][3]) * _scale()
    return float(storey.Elevation or 0.0) * _scale()


def storeys() -> str:
    if B._model is None:
        return B._dump({"storeys": []})
    out = [{"guid": s.GlobalId, "name": s.Name or "", "elevation": round(_elevation(s), 6)}
           for s in B._model.by_type("IfcBuildingStorey")]
    return B._dump({"storeys": sorted(out, key=lambda s: s["elevation"])})


def _make_storey(name: str, elevation: float):
    f = B._model
    storey = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name=name)
    building = f.by_type("IfcBuilding")[0]
    ifcopenshell.api.aggregate.assign_object(f, products=[storey], relating_object=building)
    matrix = np.eye(4)
    matrix[2][3] = elevation
    ifcopenshell.api.geometry.edit_object_placement(f, product=storey, matrix=matrix, is_si=True)
    storey.Elevation = elevation / _scale()
    return storey


def add_storey(name: str, elevation) -> str:
    if B._model is None:
        return _fail("no model open")
    if not B._model.by_type("IfcBuilding"):
        return _fail("the model has no building to add a level to")
    try:
        elevation = float(elevation)
    except (TypeError, ValueError):
        return _fail(f"not a number: {elevation}")
    made = {}

    def action():
        made["storey"] = _make_storey(name or "Level", elevation)
        return 1

    r = B._run(action)
    return B._dump({**r, "guid": made["storey"].GlobalId})


# ---------------------------------------------------------------- wall types

def _layer_set(element):
    material = ifcopenshell.util.element.get_material(element, should_skip_usage=True)
    return material if material is not None and material.is_a("IfcMaterialLayerSet") else None


def _thickness(layer_set) -> float:
    """Total thickness of a layer set in metres."""
    return sum(float(layer.LayerThickness or 0.0) for layer in layer_set.MaterialLayers) * _scale()


def _layered_types(ifc_class: str) -> list:
    return [t for t in B._model.by_type(ifc_class) if _layer_set(t) is not None]


def _layered_wall_types() -> list:
    return _layered_types("IfcWallType")


def _create_default_wall_types():
    _create_layered_types("IfcWallType", DEFAULT_WALL_TYPES)


def _create_layered_types(ifc_class: str, defaults):
    """Library defaults. Not a user action: created outside any transaction (never undone)."""
    f = B._model
    for type_name, layers in defaults:
        wall_type = ifcopenshell.api.root.create_entity(f, ifc_class=ifc_class, name=type_name)
        layer_set = ifcopenshell.api.material.add_material_set(f, name=type_name, set_type="IfcMaterialLayerSet")
        for material_name, thickness in layers:
            material = next((m for m in f.by_type("IfcMaterial") if m.Name == material_name), None) \
                or ifcopenshell.api.material.add_material(f, name=material_name)
            layer = ifcopenshell.api.material.add_layer(f, layer_set=layer_set, material=material)
            ifcopenshell.api.material.edit_layer(f, layer=layer, attributes={"LayerThickness": thickness / _scale()})
        ifcopenshell.api.material.assign_material(f, products=[wall_type], material=layer_set)


def wall_types() -> str:
    if B._model is None:
        return B._dump({"types": []})
    if not _layered_wall_types():
        _create_default_wall_types()
    return B._dump({"types": [{"guid": t.GlobalId, "name": t.Name or "", "thickness": round(_thickness(_layer_set(t)), 6)}
                              for t in _layered_wall_types()]})


# ---------------------------------------------------------------- walls

def _body_context():
    """The Model/Body/MODEL_VIEW context walls are drawn in; created when the file lacks it (some
    exports, e.g. Revit 2011, only have other views). Call inside the action: it's part of the step."""
    f = B._model
    context = ifcopenshell.util.representation.get_context(f, "Model", "Body", "MODEL_VIEW")
    if context is None:
        model = ifcopenshell.util.representation.get_context(f, "Model") or             ifcopenshell.api.context.add_context(f, context_type="Model")
        context = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body",
                                                       target_view="MODEL_VIEW", parent=model)
    return context


def _axis_world(wall):
    """The wall's reference (axis) line in world metres: ((x1, y1), (x2, y2)), or None."""
    line = ifcopenshell.util.representation.get_reference_line(wall)
    if line is None or len(line) < 2:
        return None
    m = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
    s = _scale()
    pts = [(m @ np.array([float(p[0]), float(p[1]), 0.0, 1.0]))[:2] * s for p in (line[0], line[-1])]
    return tuple(pts[0]), tuple(pts[1])


def _connected_walls(wall) -> list:
    out = []
    for rel in list(getattr(wall, "ConnectedTo", ()) or ()) + list(getattr(wall, "ConnectedFrom", ()) or ()):
        if rel.is_a("IfcRelConnectsPathElements"):
            other = rel.RelatedElement if rel.RelatingElement == wall else rel.RelatingElement
            if other.is_a("IfcWall") and other not in out:
                out.append(other)
    return out


def _is_at_end(point, other) -> bool:
    """True when `point` (metres) is at one of `other`'s axis ends (within its thickness): an L join."""
    axis = _axis_world(other)
    layer_set = _layer_set(other)
    tolerance = max(_thickness(layer_set) if layer_set else 0.0, 0.01)
    return axis is not None and min(math.dist(point, axis[0]), math.dist(point, axis[1])) <= tolerance


def _centre_on_axis(wall, thickness_m: float):
    """Draw by the wall's centre line (like Revit/ArchiCAD defaults): offset the layers by half."""
    usage = ifcopenshell.util.element.get_material(wall, should_skip_usage=False)
    if usage is not None and usage.is_a("IfcMaterialLayerSetUsage"):
        ifcopenshell.api.material.edit_layer_usage(
            B._model, usage=usage, attributes={"OffsetFromReferenceLine": -thickness_m / 2 / _scale()})


def create_wall(storey_guid: str, type_guid: str, x1, y1, x2, y2, height, join_start_guid: str = "",
                join_end_guid: str = "") -> str:
    """A wall of a layered type from (x1, y1) to (x2, y2) on a level, joined to the given walls."""
    if B._model is None:
        return _fail("no model open")
    try:
        p1, p2 = (float(x1), float(y1)), (float(x2), float(y2))
        height = float(height)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    storey, wall_type = _by_guid(storey_guid), _by_guid(type_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return _fail("unknown level")
    if wall_type is None or _layer_set(wall_type) is None:
        return _fail("unknown or non-layered wall type")
    length = math.dist(p1, p2)
    if length < MIN_WALL_LENGTH:
        return _fail("the wall has no length")
    if height <= 0:
        return _fail("the wall height must be positive")
    joins = [(guid, point) for guid, point in ((join_start_guid, p1), (join_end_guid, p2)) if guid]
    for guid, _ in joins:
        other = _by_guid(guid)
        if other is None or not other.is_a("IfcWall"):
            return _fail(f"cannot join to {guid}: not a wall")
    made = {}

    def action():
        f = B._model
        thickness = _thickness(_layer_set(wall_type))
        wall = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name=wall_type.Name)
        ifcopenshell.api.type.assign_type(f, related_objects=[wall], relating_type=wall_type)
        _centre_on_axis(wall, thickness)
        representation = ifcopenshell.api.geometry.create_2pt_wall(
            f, element=wall, context=_body_context(), p1=p1, p2=p2,
            elevation=_elevation(storey), height=height, thickness=thickness, is_si=True)
        ifcopenshell.api.geometry.assign_representation(f, product=wall, representation=representation)
        ifcopenshell.api.spatial.assign_container(f, products=[wall], relating_structure=storey)
        ifcopenshell.api.geometry.regenerate_wall_representation(f, wall=wall, length=length, height=height)
        neighbours = []
        for guid, point in joins:
            other = B._model.by_guid(guid)
            ifcopenshell.api.geometry.connect_wall(f, wall1=wall, wall2=other, is_atpath=not _is_at_end(point, other))
            neighbours.append(other)
        for w in [wall, *neighbours]:
            ifcopenshell.api.geometry.regenerate_wall_representation(f, wall=w, length=length, height=height)
        made["wall"] = wall
        return 1, [wall.GlobalId, *(n.GlobalId for n in neighbours)], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["wall"].GlobalId})


def delete_elements(guids_json: str) -> str:
    """Delete products; walls that were joined to deleted walls are regenerated."""
    if B._model is None:
        return _fail("no model open")
    elements = [e for e in B._elements(guids_json) if e.is_a("IfcProduct")]
    # Cascade: a wall takes its openings and the doors/windows in them; a door/window takes its
    # opening, and its host wall gets its hole closed (re-meshed).
    openings, hosts = [], []
    for e in list(elements):
        for rel in getattr(e, "HasOpenings", ()) or ():
            opening = rel.RelatedOpeningElement
            openings.append(opening)
            for fill in getattr(opening, "HasFillings", ()) or ():
                if fill.RelatedBuildingElement not in elements:
                    elements.append(fill.RelatedBuildingElement)
        for fill in getattr(e, "FillsVoids", ()) or ():
            opening = fill.RelatingOpeningElement
            if opening not in openings:
                openings.append(opening)
            for void in getattr(opening, "VoidsElements", ()) or ():
                hosts.append(void.RelatingBuildingElement)
    removed = [e.GlobalId for e in elements]
    neighbours = []
    for e in elements:
        for other in _connected_walls(e) if e.is_a("IfcWall") else ():
            if other.GlobalId not in removed and other not in neighbours:
                neighbours.append(other)
    hosts = [h for h in dict.fromkeys(hosts) if h.GlobalId not in removed and h not in neighbours]

    def action():
        f = B._model
        gone = set()

        def remove(e):
            if e.id() in gone:
                return
            gone.add(e.id())
            ifcopenshell.api.root.remove_product(f, product=e)

        fillings = [e for e in elements if getattr(e, "FillsVoids", None)]
        # Doors/windows first, then the openings, then walls and the rest: removing a wall can
        # take its openings with it, so nothing is removed twice.
        for e in fillings:
            remove(e)
        for opening in openings:
            if opening.id() not in gone:
                remove(opening)
        for e in elements:
            if e.id() in gone:
                continue
            for rel in list(getattr(e, "ConnectedTo", ()) or ()) + list(getattr(e, "ConnectedFrom", ()) or ()):
                if rel.is_a("IfcRelConnectsPathElements"):
                    f.remove(rel)  # the join goes with the wall
            remove(e)
        for w in neighbours:
            ifcopenshell.api.geometry.regenerate_wall_representation(f, wall=w)
        return len(elements), [w.GlobalId for w in [*neighbours, *hosts]], removed

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "removed": len(elements)})


def snap_data(storey_guid: str) -> str:
    """Wall axes on a level, in world metres, for snapping while drawing."""
    storey = _by_guid(storey_guid) if B._model is not None else None
    if storey is None:
        return B._dump({"walls": []})
    walls, openings = [], []
    for rel in getattr(storey, "ContainsElements", ()) or ():
        for e in rel.RelatedElements:
            if not e.is_a("IfcWall"):
                continue
            axis = _axis_world(e)
            layer_set = _layer_set(e)
            if axis is None:
                continue
            walls.append({"guid": e.GlobalId, "x1": axis[0][0], "y1": axis[0][1], "x2": axis[1][0], "y2": axis[1][1],
                          "thickness": round(_thickness(layer_set), 6) if layer_set else 0.0})
            for void in getattr(e, "HasOpenings", ()) or ():
                opening = void.RelatedOpeningElement
                fill = next((r.RelatedBuildingElement for r in getattr(opening, "HasFillings", ()) or ()), None)
                if fill is None:
                    continue
                width = float(fill.OverallWidth or 0.0) * _scale()
                m = ifcopenshell.util.placement.get_local_placement(opening.ObjectPlacement)
                corner = np.array([m[0][3], m[1][3]]) * _scale()
                d = np.array(axis[1]) - np.array(axis[0])
                d = d / np.linalg.norm(d)
                along = float(np.dot(corner - np.array(axis[0]), d)) + width / 2
                openings.append({"guid": fill.GlobalId, "wall": e.GlobalId, "along": round(along, 6), "width": round(width, 6)})
    return B._dump({"walls": walls, "openings": openings})


# ---------------------------------------------------------------- slabs (Slice 5)

def slab_types() -> str:
    if B._model is None:
        return B._dump({"types": []})
    if not _layered_types("IfcSlabType"):
        _create_layered_types("IfcSlabType", DEFAULT_SLAB_TYPES)
    return B._dump({"types": [{"guid": t.GlobalId, "name": t.Name or "", "thickness": round(_thickness(_layer_set(t)), 6)}
                              for t in _layered_types("IfcSlabType")]})


def _segments_cross(a, b, c, d) -> bool:
    """Proper intersection of segments ab and cd (shared end points don't count)."""
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def _clean_polygon(points) -> list | None:
    """Closed outline as [(x, y)...] without repeats, or None if it isn't a simple polygon."""
    pts = []
    for p in points:
        q = (float(p[0]), float(p[1]))
        if not pts or math.dist(q, pts[-1]) > 1e-6:
            pts.append(q)
    if len(pts) > 1 and math.dist(pts[0], pts[-1]) <= 1e-6:
        pts.pop()
    if len(pts) < 3:
        return None
    n = len(pts)
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue  # neighbouring edges share a point
            if _segments_cross(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n]):
                return None
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) / 2
    return pts if abs(area) > 1e-9 else None


def create_slab(storey_guid: str, type_guid: str, points_json: str, offset=0.0) -> str:
    """A slab of a layered type with this outline (metres); its top is at the level + offset."""
    if B._model is None:
        return _fail("no model open")
    storey, slab_type = _by_guid(storey_guid), _by_guid(type_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return _fail("unknown level")
    if slab_type is None or not slab_type.is_a("IfcSlabType") or _layer_set(slab_type) is None:
        return _fail("unknown or non-layered slab type")
    try:
        outline = _clean_polygon(json.loads(points_json))
        offset = float(offset or 0.0)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    if outline is None:
        return _fail("the outline needs at least 3 points and must not cross itself")
    made = {}

    def action():
        f = B._model
        thickness = _thickness(_layer_set(slab_type))
        slab = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlab", name=slab_type.Name, predefined_type="FLOOR")
        ifcopenshell.api.type.assign_type(f, related_objects=[slab], relating_type=slab_type)
        representation = ifcopenshell.api.geometry.add_slab_representation(
            f, context=_body_context(), depth=thickness, polyline=outline)
        ifcopenshell.api.geometry.assign_representation(f, product=slab, representation=representation)
        matrix = np.eye(4)
        matrix[2][3] = _elevation(storey) + offset - thickness  # top of slab at the level
        ifcopenshell.api.geometry.edit_object_placement(f, product=slab, matrix=matrix, is_si=True)
        ifcopenshell.api.spatial.assign_container(f, products=[slab], relating_structure=storey)
        made["slab"] = slab
        return 1, [slab.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["slab"].GlobalId})


def slab_outline_from_walls(walls_json: str) -> str:
    """Outline at the outer faces of walls that form one closed loop (metres)."""
    if B._model is None:
        return _fail("no model open")
    walls = [w for w in B._elements(walls_json) if w.is_a("IfcWall")]
    segments = []
    for w in walls:
        axis = _axis_world(w)
        layer_set = _layer_set(w)
        if axis is None:
            return _fail(f"wall {w.GlobalId} has no axis")
        segments.append((np.array(axis[0]), np.array(axis[1]), _thickness(layer_set) if layer_set else 0.0))
    if len(segments) < 3:
        return _fail("select at least 3 walls that form a closed loop")
    tolerance = max(max(s[2] for s in segments), 0.01)
    # Chain the axes end to end.
    remaining = list(range(1, len(segments)))
    a, b, t = segments[0]
    chain = [(a, b, t)]
    current = b
    while remaining:
        nxt = None
        for k in remaining:
            p, q, th = segments[k]
            if np.linalg.norm(p - current) <= tolerance:
                nxt = (k, p, q, th)
            elif np.linalg.norm(q - current) <= tolerance:
                nxt = (k, q, p, th)
            if nxt:
                break
        if nxt is None:
            return _fail("the selected walls don't form one closed loop")
        k, p, q, th = nxt
        remaining.remove(k)
        chain.append((p, q, th))
        current = q
    if np.linalg.norm(current - chain[0][0]) > tolerance:
        return _fail("the selected walls don't form one closed loop")
    n = len(chain)
    corners = [(chain[i][0] + chain[i - 1][1]) / 2 for i in range(n)]  # corner i: start of edge i
    area = sum(corners[i][0] * corners[(i + 1) % n][1] - corners[(i + 1) % n][0] * corners[i][1] for i in range(n)) / 2
    sign = 1.0 if area > 0 else -1.0  # counter-clockwise: outward normal of (dx, dy) is (dy, -dx)
    lines = []
    for i in range(n):
        p, q = corners[i], corners[(i + 1) % n]
        d = (q - p) / np.linalg.norm(q - p)
        normal = np.array([d[1], -d[0]]) * sign
        lines.append((p + normal * chain[i][2] / 2, d))
    points = []
    for i in range(n):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        det = d1[0] * (-d2[1]) - d1[1] * (-d2[0])
        if abs(det) < 1e-12:  # collinear walls: just the offset point
            points.append(p2)
            continue
        rhs = p2 - p1
        s1 = (rhs[0] * (-d2[1]) - rhs[1] * (-d2[0])) / det
        points.append(p1 + d1 * s1)
    return B._dump({"ok": True, "points": [[round(float(x), 6), round(float(y), 6)] for x, y in points]})


# ---------------------------------------------------------------- doors and windows (Slice 5)

def _opening_defaults(t) -> tuple[float, float, float]:
    psets = ifcopenshell.util.element.get_psets(t)
    d = psets.get(OPENING_PSET, {})
    s = _scale()
    return (float(d.get("Width", 0.9 / s)) * s, float(d.get("Height", 2.1 / s)) * s, float(d.get("SillHeight", 0.0)) * s)


def opening_types(kind: str) -> str:
    if B._model is None or kind not in OPENING_CLASSES:
        return B._dump({"types": []})
    _, type_class = OPENING_CLASSES[kind]
    f = B._model
    if not f.by_type(type_class):
        import ifcopenshell.api.pset
        for name, width, height, sill in DEFAULT_OPENING_TYPES[kind]:
            t = ifcopenshell.api.root.create_entity(f, ifc_class=type_class, name=name,
                                                    predefined_type="DOOR" if kind == "door" else "WINDOW")
            if kind == "door":
                t.OperationType = "SINGLE_SWING_LEFT"
            else:
                t.PartitioningType = "SINGLE_PANEL"
            pset = ifcopenshell.api.pset.add_pset(f, product=t, name=OPENING_PSET)
            ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
                "Width": f.createIfcPositiveLengthMeasure(width / _scale()),
                "Height": f.createIfcPositiveLengthMeasure(height / _scale()),
                "SillHeight": f.createIfcLengthMeasure(sill / _scale())})
    out = []
    for t in f.by_type(type_class):
        w, h, sill = _opening_defaults(t)
        out.append({"guid": t.GlobalId, "name": t.Name or "", "width": round(w, 6), "height": round(h, 6), "sill": round(sill, 6)})
    return B._dump({"types": out})


def _wall_height(wall) -> float:
    """Extrusion depth of the wall body in metres (0 if unknown)."""
    representation = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
    depths = [float(e.Depth) for e in B._model.traverse(representation) if e.is_a("IfcExtrudedAreaSolid")] if representation else []
    return max(depths, default=0.0) * _scale()


def insert_opening(kind: str, wall_guid: str, type_guid: str, along, width, height, sill) -> str:
    """A door or window in a wall: an opening through the wall filled by the door/window, centred
    `along` metres from the wall axis start, with its bottom `sill` metres above the wall base."""
    if B._model is None:
        return _fail("no model open")
    if kind not in OPENING_CLASSES:
        return _fail(f"unknown kind {kind}")
    element_class, type_class = OPENING_CLASSES[kind]
    wall, opening_type = _by_guid(wall_guid), _by_guid(type_guid)
    if wall is None or not wall.is_a("IfcWall"):
        return _fail("not a wall")
    if opening_type is None or not opening_type.is_a(type_class):
        return _fail(f"not a {kind} type")
    try:
        along, width, height, sill = float(along), float(width), float(height), float(sill)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    axis = _axis_world(wall)
    layer_set = _layer_set(wall)
    if axis is None or layer_set is None:
        return _fail("the wall has no axis or layers")
    length = math.dist(axis[0], axis[1])
    if width <= 0 or height <= 0 or along - width / 2 < -1e-6 or along + width / 2 > length + 1e-6:
        return _fail("the opening doesn't fit in the wall")
    wall_height = _wall_height(wall)
    if wall_height and sill + height > wall_height + 1e-6:
        return _fail("the opening is taller than the wall")
    thickness = _thickness(layer_set)
    made = {}

    def action():
        f = B._model
        s = _scale()
        wm = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
        line = ifcopenshell.util.representation.get_reference_line(wall)
        start = np.array([float(line[0][0]), float(line[0][1])])
        direction = np.array([float(line[-1][0]), float(line[-1][1])]) - start
        direction = direction / np.linalg.norm(direction)

        def placed(along_m, across_m, up_m):
            local = start + direction * (along_m / s)
            matrix = wm.copy()
            point = np.array([local[0], local[1], 0.0]) + np.array([-direction[1], direction[0], 0.0]) * (across_m / s)
            point[2] = up_m / s
            matrix[:3, 3] = wm[:3, 3] + wm[:3, :3] @ point
            matrix[:3, 0] = wm[:3, :3] @ np.array([direction[0], direction[1], 0.0])
            matrix[:3, 1] = wm[:3, :3] @ np.array([-direction[1], direction[0], 0.0])
            return matrix

        context = _body_context()
        opening = ifcopenshell.api.root.create_entity(f, ifc_class="IfcOpeningElement", name=f"{kind} opening")
        opening_rep = ifcopenshell.api.geometry.add_wall_representation(
            f, context=context, length=width, height=height, thickness=thickness + 0.02)
        ifcopenshell.api.geometry.assign_representation(f, product=opening, representation=opening_rep)
        ifcopenshell.api.geometry.edit_object_placement(
            f, product=opening, matrix=placed(along - width / 2, -(thickness / 2 + 0.01), sill), is_si=False)
        ifcopenshell.api.feature.add_feature(f, feature=opening, element=wall)

        element = ifcopenshell.api.root.create_entity(f, ifc_class=element_class, name=opening_type.Name,
                                                      predefined_type="DOOR" if kind == "door" else "WINDOW")
        element.OverallWidth, element.OverallHeight = width / s, height / s
        ifcopenshell.api.type.assign_type(f, related_objects=[element], relating_type=opening_type)
        if kind == "door":
            representation = ifcopenshell.api.geometry.add_door_representation(
                f, context=context, overall_height=height / s, overall_width=width / s,
                operation_type=opening_type.OperationType or "SINGLE_SWING_LEFT")
        else:
            representation = ifcopenshell.api.geometry.add_window_representation(
                f, context=context, overall_height=height / s, overall_width=width / s,
                partition_type=opening_type.PartitioningType or "SINGLE_PANEL")
        ifcopenshell.api.geometry.assign_representation(f, product=element, representation=representation)
        ifcopenshell.api.geometry.edit_object_placement(
            f, product=element, matrix=placed(along - width / 2, -thickness / 2, sill), is_si=False)
        ifcopenshell.api.feature.add_filling(f, opening=opening, element=element)
        container = ifcopenshell.util.element.get_container(wall)
        if container is not None:
            ifcopenshell.api.spatial.assign_container(f, products=[element], relating_structure=container)
        made["element"] = element
        return 1, [wall.GlobalId, element.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["element"].GlobalId})
