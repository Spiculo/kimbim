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
import ifcopenshell.api.grid
import ifcopenshell.api.material
import ifcopenshell.api.project
import ifcopenshell.api.pset
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
from . import layers

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
        layers.assign_active(wall)
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
                info = _opening_info(fill) if fill is not None else None
                if info is None:
                    continue
                _, _, along, width, height, sill = info
                openings.append({"guid": fill.GlobalId, "wall": e.GlobalId, "along": round(along, 6), "width": round(width, 6),
                                 "height": round(height, 6), "sill": round(sill, 6)})
    return B._dump({"walls": walls, "openings": openings, "grid": _grid_lines(storey)})


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
        layers.assign_active(slab)
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


def _wall_frame(wall):
    """placed(along, across, up) -> placement matrix (project units) in the wall's frame: `along`
    from the axis start, `across` to the left of the axis, `up` from the wall base (all metres)."""
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

    return placed


def _filling_representation(kind, element_type, width, height):
    f, s = B._model, _scale()
    if kind == "door":
        return ifcopenshell.api.geometry.add_door_representation(
            f, context=_body_context(), overall_height=height / s, overall_width=width / s,
            operation_type=getattr(element_type, "OperationType", None) or "SINGLE_SWING_LEFT")
    return ifcopenshell.api.geometry.add_window_representation(
        f, context=_body_context(), overall_height=height / s, overall_width=width / s,
        partition_type=getattr(element_type, "PartitioningType", None) or "SINGLE_PANEL")


def _replace_body(product, representation):
    """Swap a product's body representation (keeps the product and its GlobalId)."""
    f = B._model
    old = ifcopenshell.util.representation.get_representation(product, "Model", "Body", "MODEL_VIEW")
    if old is not None:
        layers.carry_layers(old, representation)  # the element stays on its layer
        ifcopenshell.api.geometry.unassign_representation(f, product=product, representation=old)
        ifcopenshell.api.geometry.remove_representation(f, representation=old)
    ifcopenshell.api.geometry.assign_representation(f, product=product, representation=representation)


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
        placed = _wall_frame(wall)
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
        representation = _filling_representation(kind, opening_type, width, height)
        ifcopenshell.api.geometry.assign_representation(f, product=element, representation=representation)
        ifcopenshell.api.geometry.edit_object_placement(
            f, product=element, matrix=placed(along - width / 2, -thickness / 2, sill), is_si=False)
        ifcopenshell.api.feature.add_filling(f, opening=opening, element=element)
        container = ifcopenshell.util.element.get_container(wall)
        if container is not None:
            ifcopenshell.api.spatial.assign_container(f, products=[element], relating_structure=container)
        layers.assign_active(element)
        made["element"] = element
        return 1, [wall.GlobalId, element.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["element"].GlobalId})


# ---------------------------------------------------------------- columns and beams (Slice 6)

# (name, profile class, width, depth) in metres; circles use width as the diameter.
DEFAULT_COLUMN_TYPES = [("Column 300x300", "IfcRectangleProfileDef", 0.3, 0.3), ("Column D300", "IfcCircleProfileDef", 0.3, 0.3)]
DEFAULT_BEAM_TYPES = [("Beam 200x400", "IfcRectangleProfileDef", 0.2, 0.4)]


def _profile_set(element):
    material = ifcopenshell.util.element.get_material(element, should_skip_usage=True)
    return material if material is not None and material.is_a("IfcMaterialProfileSet") else None


def _profile(element):
    profile_set = _profile_set(element)
    profiles = list(profile_set.MaterialProfiles or ()) if profile_set else []
    return profiles[0].Profile if profiles else None


def _profile_size(profile) -> tuple[float, float]:
    s = _scale()
    if profile.is_a("IfcCircleProfileDef"):
        return 2 * float(profile.Radius) * s, 2 * float(profile.Radius) * s
    if profile.is_a("IfcRectangleProfileDef"):
        return float(profile.XDim) * s, float(profile.YDim) * s
    return 0.0, 0.0


def _profile_types(ifc_class: str, defaults) -> list:
    f = B._model
    if not [t for t in f.by_type(ifc_class) if _profile(t) is not None]:
        s = _scale()
        for name, profile_class, width, depth in defaults:
            t = ifcopenshell.api.root.create_entity(f, ifc_class=ifc_class, name=name)
            # Position is optional in IFC4, but some readers (web-ifc) need it: write the origin.
            origin = f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0)))
            if profile_class == "IfcCircleProfileDef":
                profile = f.create_entity(profile_class, ProfileType="AREA", ProfileName=name, Position=origin, Radius=width / 2 / s)
            else:
                profile = f.create_entity(profile_class, ProfileType="AREA", ProfileName=name, Position=origin,
                                          XDim=width / s, YDim=depth / s)
            profile_set = ifcopenshell.api.material.add_material_set(f, name=name, set_type="IfcMaterialProfileSet")
            material_name = "Concrete" if ifc_class == "IfcColumnType" else "Steel"
            material = next((m for m in f.by_type("IfcMaterial") if m.Name == material_name), None) \
                or ifcopenshell.api.material.add_material(f, name=material_name)
            ifcopenshell.api.material.add_profile(f, profile_set=profile_set, material=material, profile=profile)
            ifcopenshell.api.material.assign_material(f, products=[t], material=profile_set)
    out = []
    for t in f.by_type(ifc_class):
        profile = _profile(t)
        if profile is None:
            continue
        width, depth = _profile_size(profile)
        out.append({"guid": t.GlobalId, "name": t.Name or "", "width": round(width, 6), "depth": round(depth, 6)})
    return out


def column_types() -> str:
    return B._dump({"types": _profile_types("IfcColumnType", DEFAULT_COLUMN_TYPES) if B._model is not None else []})


def beam_types() -> str:
    return B._dump({"types": _profile_types("IfcBeamType", DEFAULT_BEAM_TYPES) if B._model is not None else []})


def _profile_element(storey_guid, type_guid, type_class):
    storey, element_type = _by_guid(storey_guid), _by_guid(type_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return None, None, "unknown level"
    if element_type is None or not element_type.is_a(type_class) or _profile(element_type) is None:
        return None, None, "unknown type or type without a profile"
    return storey, element_type, ""


def create_column(storey_guid: str, type_guid: str, x, y, height, rotation=0.0) -> str:
    """A column standing on the level at (x, y), `height` m tall, turned `rotation` radians."""
    if B._model is None:
        return _fail("no model open")
    storey, column_type, error = _profile_element(storey_guid, type_guid, "IfcColumnType")
    if error:
        return _fail(error)
    try:
        x, y, height, rotation = float(x), float(y), float(height), float(rotation or 0.0)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    if height <= 0:
        return _fail("the column height must be positive")
    made = {}

    def action():
        f = B._model
        column = ifcopenshell.api.root.create_entity(f, ifc_class="IfcColumn", name=column_type.Name)
        ifcopenshell.api.type.assign_type(f, related_objects=[column], relating_type=column_type)
        representation = ifcopenshell.api.geometry.add_profile_representation(
            f, context=_body_context(), profile=_profile(column_type), depth=height)
        ifcopenshell.api.geometry.assign_representation(f, product=column, representation=representation)
        c, s = math.cos(rotation), math.sin(rotation)
        matrix = np.array([[c, -s, 0, x], [s, c, 0, y], [0, 0, 1, _elevation(storey)], [0, 0, 0, 1]], dtype=float)
        ifcopenshell.api.geometry.edit_object_placement(f, product=column, matrix=matrix, is_si=True)
        ifcopenshell.api.spatial.assign_container(f, products=[column], relating_structure=storey)
        layers.assign_active(column)
        made["element"] = column
        return 1, [column.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["element"].GlobalId})


def create_beam(storey_guid: str, type_guid: str, x1, y1, x2, y2, top) -> str:
    """A beam from (x1, y1) to (x2, y2) whose top is at `top` (absolute metres)."""
    if B._model is None:
        return _fail("no model open")
    storey, beam_type, error = _profile_element(storey_guid, type_guid, "IfcBeamType")
    if error:
        return _fail(error)
    try:
        x1, y1, x2, y2, top = float(x1), float(y1), float(x2), float(y2), float(top)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    length = math.hypot(x2 - x1, y2 - y1)
    if length < MIN_WALL_LENGTH:
        return _fail("the beam has no length")
    made = {}

    def action():
        f = B._model
        beam = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBeam", name=beam_type.Name)
        ifcopenshell.api.type.assign_type(f, related_objects=[beam], relating_type=beam_type)
        # Profile Y up, extrusion (local Z) along the beam, top centre on the placement.
        representation = ifcopenshell.api.geometry.add_profile_representation(
            f, context=_body_context(), profile=_profile(beam_type), depth=length, cardinal_point=8)
        ifcopenshell.api.geometry.assign_representation(f, product=beam, representation=representation)
        dx, dy = (x2 - x1) / length, (y2 - y1) / length
        matrix = np.array([[-dy, 0, dx, x1], [dx, 0, dy, y1], [0, 1, 0, top], [0, 0, 0, 1]], dtype=float)
        ifcopenshell.api.geometry.edit_object_placement(f, product=beam, matrix=matrix, is_si=True)
        ifcopenshell.api.spatial.assign_container(f, products=[beam], relating_structure=storey)
        layers.assign_active(beam)
        made["element"] = beam
        return 1, [beam.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["element"].GlobalId})


# ---------------------------------------------------------------- grids (Slice 6)

def _level_grid(storey):
    for rel in getattr(storey, "ContainsElements", ()) or ():
        for e in rel.RelatedElements:
            if e.is_a("IfcGrid"):
                return e
    return None


def _grid_axes(grid) -> list:
    """All axes of a grid in creation order."""
    axes = list(grid.UAxes or ()) + list(grid.VAxes or ()) + list(getattr(grid, "WAxes", None) or ())
    return sorted(axes, key=lambda a: a.id())


def _next_tag(existing: set, letters: bool) -> str:
    n = 0
    while True:
        n += 1
        if letters:
            tag, k = "", n
            while k > 0:
                k, r = divmod(k - 1, 26)
                tag = chr(ord("A") + r) + tag
        else:
            tag = str(n)
        if tag not in existing:
            return tag


def add_grid_axis(storey_guid: str, x1, y1, x2, y2, tag: str = "") -> str:
    """A grid line on a level (its IfcGrid is created on first use). Without a tag, axes closer to
    vertical get letters (A, B, ...) and the others numbers (1, 2, ...)."""
    if B._model is None:
        return _fail("no model open")
    storey = _by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return _fail("unknown level")
    try:
        x1, y1, x2, y2 = float(x1), float(y1), float(x2), float(y2)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    if math.hypot(x2 - x1, y2 - y1) < MIN_WALL_LENGTH:
        return _fail("the grid line has no length")
    vertical = abs(y2 - y1) >= abs(x2 - x1)
    made = {}

    def action():
        f = B._model
        grid = _level_grid(storey)
        if grid is None:
            grid = ifcopenshell.api.root.create_entity(f, ifc_class="IfcGrid", name="Grid")
            matrix = np.eye(4)
            matrix[2][3] = _elevation(storey)
            ifcopenshell.api.geometry.edit_object_placement(f, product=grid, matrix=matrix, is_si=True)
            ifcopenshell.api.spatial.assign_container(f, products=[grid], relating_structure=storey)
        existing = {a.AxisTag for a in _grid_axes(grid)}
        axis_tag = tag or _next_tag(existing, letters=vertical)
        axis = ifcopenshell.api.grid.create_grid_axis(f, grid=grid, axis_tag=axis_tag, uvw_axes="UAxes" if vertical else "VAxes")
        origin = ifcopenshell.util.placement.get_local_placement(grid.ObjectPlacement)[:3, 3] * _scale()
        ifcopenshell.api.grid.create_axis_curve(f, p1=np.array([x1 - origin[0], y1 - origin[1], 0.0]),
                                                p2=np.array([x2 - origin[0], y2 - origin[1], 0.0]), grid_axis=axis, is_si=True)
        made["grid"], made["tag"] = grid, axis_tag
        return 1, [], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["grid"].GlobalId, "tag": made["tag"]})


def _grid_lines(storey) -> list:
    grid = _level_grid(storey)
    if grid is None:
        return []
    m = ifcopenshell.util.placement.get_local_placement(grid.ObjectPlacement)
    s = _scale()
    out = []
    for axis in _grid_axes(grid):
        curve = axis.AxisCurve
        points = list(curve.Points) if curve is not None and curve.is_a("IfcPolyline") else []
        if len(points) < 2:
            continue
        ends = []
        for p in (points[0], points[-1]):
            c = list(p.Coordinates) + [0.0] * (3 - len(p.Coordinates))
            ends.append((m @ np.array([c[0], c[1], c[2], 1.0]))[:2] * s)
        out.append({"guid": grid.GlobalId, "tag": axis.AxisTag, "x1": round(float(ends[0][0]), 6), "y1": round(float(ends[0][1]), 6),
                    "x2": round(float(ends[1][0]), 6), "y2": round(float(ends[1][1]), 6)})
    return out


# ---------------------------------------------------------------- editing geometry (Slice 6)

def _path_joins(wall) -> list:
    return [r for r in list(getattr(wall, "ConnectedTo", ()) or ()) + list(getattr(wall, "ConnectedFrom", ()) or ())
            if r.is_a("IfcRelConnectsPathElements")]


def _hosted(element) -> list:
    """Openings in an element and the doors/windows filling them (they move with it)."""
    out = []
    for rel in getattr(element, "HasOpenings", ()) or ():
        opening = rel.RelatedOpeningElement
        out.append(opening)
        out += [r.RelatedBuildingElement for r in getattr(opening, "HasFillings", ()) or ()]
    return out


def _placement_parent(element):
    placement = getattr(element, "ObjectPlacement", None)
    rel_to = getattr(placement, "PlacementRelTo", None) if placement is not None else None
    places = getattr(rel_to, "PlacesObject", None) if rel_to is not None else None
    return places[0] if places else None


def _transform(guids_json: str, transform_si, detach=False) -> str:
    """Apply a rigid world transform (4x4, metres) to the elements and what they host.

    Walls joined at an end to a moved wall are dragged along: their joined end slides along their
    own line to meet the moved wall (D54), so corners stay closed and the walls stay straight. With `detach`, those joins are dropped instead and
    the moved walls go alone."""
    if B._model is None:
        return _fail("no model open")
    elements = [e for e in B._elements(guids_json) if e.is_a("IfcProduct") and getattr(e, "ObjectPlacement", None)]
    if not elements:
        return _fail("nothing to move")
    moved = set(elements)
    for e in list(elements):
        moved.update(_hosted(e))

    def has_moving_ancestor(e):
        parent = _placement_parent(e)
        while parent is not None:
            if parent in moved:
                return True
            parent = _placement_parent(parent)
        return False

    t = np.array(transform_si, dtype=float)
    roots = [e for e in elements if not has_moving_ancestor(e)]
    walls = [e for e in elements if e.is_a("IfcWall")]
    broken, neighbours = [], []
    dragged = {}  # neighbour -> [new start, new end] (metres), ends joined to moved walls follow
    for w in walls:
        for rel in _path_joins(w):
            other = rel.RelatedElement if rel.RelatingElement == w else rel.RelatingElement
            if other in moved:
                continue
            if other not in neighbours:
                neighbours.append(other)
            if detach:
                broken.append(rel)
                continue
            theirs = rel.RelatedConnectionType if rel.RelatingElement == w else rel.RelatingConnectionType
            axis = _axis_world(other)
            if theirs not in ("ATSTART", "ATEND") or axis is None:
                continue  # the moved wall ends on the other's path: the join just regenerates
            ends = dragged.setdefault(other, [np.array(axis[0], dtype=float), np.array(axis[1], dtype=float)])
            k = 0 if theirs == "ATSTART" else 1
            ends[k] = _follow_end(np.array(axis[k], dtype=float), np.array(axis[1 - k], dtype=float), w, t)
    for n, (p1, p2) in dragged.items():
        if float(np.linalg.norm(p2 - p1)) < MIN_WALL_LENGTH:
            return _fail(f"moving this would shrink wall {n.GlobalId} to nothing")

    def action():
        f = B._model
        s = _scale()
        t_units = t.copy()
        t_units[:3, 3] = t[:3, 3] / s
        for rel in dict.fromkeys(broken):
            f.remove(rel)  # detached: joins to walls that stay put no longer hold
        for e in roots:
            world = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
            ifcopenshell.api.geometry.edit_object_placement(
                f, product=e, matrix=t_units @ world, is_si=False, should_transform_children=True)
        for n, (p1, p2) in dragged.items():
            _reaxis(n, p1, p2)
        for w in [*walls, *neighbours]:
            if _axis_world(w) is not None and _layer_set(w) is not None:
                ifcopenshell.api.geometry.regenerate_wall_representation(f, wall=w)
        changed = [e.GlobalId for e in moved if not e.is_a("IfcOpeningElement")] + [n.GlobalId for n in neighbours]
        return len(roots), changed, []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def _follow_end(end, other_end, moved_wall, t):
    """Where a joined wall's end goes when the wall it joins moves by `t` (metres): it slides along
    its own line to meet the moved wall's new axis line, so it stays straight (D54). Only when the
    two are parallel does it follow the full movement."""
    axis = _axis_world(moved_wall)
    q1 = (t @ np.array([axis[0][0], axis[0][1], 0.0, 1.0]))[:2]
    q2 = (t @ np.array([axis[1][0], axis[1][1], 0.0, 1.0]))[:2]
    d_own, d_moved = end - other_end, q2 - q1

    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]

    denom = cross(d_own, d_moved)
    if abs(denom) < 1e-9 * max(np.linalg.norm(d_own) * np.linalg.norm(d_moved), 1e-12):
        return (t @ np.array([end[0], end[1], 0.0, 1.0]))[:2]
    return other_end + d_own * (cross(q1 - other_end, d_moved) / denom)


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes")


def move_elements(guids_json: str, dx, dy, dz=0.0, detach=False) -> str:
    """Move elements (and the doors/windows they host) by (dx, dy, dz) metres; joined walls follow
    unless `detach`."""
    try:
        t = np.eye(4)
        t[:3, 3] = [float(dx), float(dy), float(dz or 0.0)]
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    return _transform(guids_json, t, _truthy(detach))


def rotate_elements(guids_json: str, cx, cy, angle, detach=False) -> str:
    """Rotate elements by `angle` radians around the vertical line through (cx, cy); joined walls
    follow unless `detach`."""
    try:
        cx, cy, angle = float(cx), float(cy), float(angle)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    c, s = math.cos(angle), math.sin(angle)
    rotation = np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
    to_origin, back = np.eye(4), np.eye(4)
    to_origin[:2, 3] = [-cx, -cy]
    back[:2, 3] = [cx, cy]
    return _transform(guids_json, back @ rotation @ to_origin, _truthy(detach))


def set_wall_axis(wall_guid: str, x1, y1, x2, y2) -> str:
    """Stretch/extend a wall to a new axis (metres). Joins at an end that moved are dropped; its
    doors and windows keep their place; the wall keeps its GlobalId."""
    if B._model is None:
        return _fail("no model open")
    wall = _by_guid(wall_guid)
    if wall is None or not wall.is_a("IfcWall") or _axis_world(wall) is None:
        return _fail("not a wall with an axis")
    try:
        p1, p2 = np.array([float(x1), float(y1)]), np.array([float(x2), float(y2)])
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    length = float(np.linalg.norm(p2 - p1))
    if length < MIN_WALL_LENGTH:
        return _fail("the wall has no length")
    a0, a1 = (np.array(p) for p in _axis_world(wall))
    start_moved, end_moved = np.linalg.norm(p1 - a0) > 1e-6, np.linalg.norm(p2 - a1) > 1e-6
    height = _wall_height(wall) or 3.0
    dropped, neighbours = [], []
    for rel in _path_joins(wall):
        mine = rel.RelatingConnectionType if rel.RelatingElement == wall else rel.RelatedConnectionType
        other = rel.RelatedElement if rel.RelatingElement == wall else rel.RelatingElement
        if (mine == "ATSTART" and start_moved) or (mine == "ATEND" and end_moved):
            dropped.append(rel)
        neighbours.append(other)

    def action():
        f = B._model
        for rel in dropped:
            f.remove(rel)
        _reaxis(wall, p1, p2)
        ifcopenshell.api.geometry.regenerate_wall_representation(f, wall=wall, length=length, height=height)
        for n in neighbours:
            ifcopenshell.api.geometry.regenerate_wall_representation(f, wall=n)
        return 1, [wall.GlobalId, *(n.GlobalId for n in neighbours), *(e.GlobalId for e in _hosted(wall) if not e.is_a("IfcOpeningElement"))], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def _reaxis(wall, p1, p2):
    """Give a wall a new axis from p1 to p2 (world metres) inside an action: placement at p1 along
    the axis (its doors/windows keep their place) and a new Plan/Axis line of the new length.
    The caller regenerates the body."""
    f = B._model
    s = _scale()
    p1, p2 = np.asarray(p1, dtype=float), np.asarray(p2, dtype=float)
    length = float(np.linalg.norm(p2 - p1))
    z = float(ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)[2][3])
    d = (p2 - p1) / length
    matrix = np.array([[d[0], -d[1], 0, p1[0] / s], [d[1], d[0], 0, p1[1] / s], [0, 0, 1, z], [0, 0, 0, 1]], dtype=float)
    ifcopenshell.api.geometry.edit_object_placement(f, product=wall, matrix=matrix, is_si=False)
    # A new axis of the new length (in the wall's own frame): the wall's
    # geometry is rebuilt from it; without one it would be rebuilt from the old body.
    context = ifcopenshell.util.representation.get_context(f, "Plan", "Axis", "GRAPH_VIEW")
    if context is None:
        plan = ifcopenshell.util.representation.get_context(f, "Plan") or ifcopenshell.api.context.add_context(
            f, context_type="Plan")
        context = ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="Axis",
                                                       target_view="GRAPH_VIEW", parent=plan)
    new_axis = ifcopenshell.api.geometry.add_axis_representation(f, context=context, axis=((0.0, 0.0), (length, 0.0)))  # metres
    old_axis = ifcopenshell.util.representation.get_representation(wall, "Plan", "Axis", "GRAPH_VIEW")
    if old_axis is not None:
        ifcopenshell.api.geometry.unassign_representation(f, product=wall, representation=old_axis)
        ifcopenshell.api.geometry.remove_representation(f, representation=old_axis)
    ifcopenshell.api.geometry.assign_representation(f, product=wall, representation=new_axis)


def set_wall_height(guids_json: str, height) -> str:
    """Change the height of walls (metres)."""
    if B._model is None:
        return _fail("no model open")
    try:
        height = float(height)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    if height <= 0:
        return _fail("the wall height must be positive")
    walls = [w for w in B._elements(guids_json) if w.is_a("IfcWall")]
    if not walls:
        return _fail("no walls selected")

    def action():
        f = B._model
        for w in walls:
            body = ifcopenshell.util.representation.get_representation(w, "Model", "Body", "MODEL_VIEW")
            for solid in (f.traverse(body) if body is not None else ()):
                if solid.is_a("IfcExtrudedAreaSolid"):
                    solid.Depth = height / _scale()
            if _axis_world(w) is not None and _layer_set(w) is not None:
                ifcopenshell.api.geometry.regenerate_wall_representation(f, wall=w, height=height)
        return len(walls), [w.GlobalId for w in walls], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def _opening_info(element):
    """(opening, wall, along, width, height, sill) of a door/window in a wall (metres), or None."""
    fills = list(getattr(element, "FillsVoids", ()) or ()) if element is not None else []
    if not fills:
        return None
    opening = fills[0].RelatingOpeningElement
    voids = list(getattr(opening, "VoidsElements", ()) or ())
    wall = voids[0].RelatingBuildingElement if voids else None
    axis = _axis_world(wall) if wall is not None else None
    if axis is None:
        return None
    s = _scale()
    width = float(element.OverallWidth or 0.0) * s
    height = float(element.OverallHeight or 0.0) * s
    m = ifcopenshell.util.placement.get_local_placement(opening.ObjectPlacement)
    wm = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
    corner = np.array([m[0][3], m[1][3]]) * s
    u = np.array(axis[1]) - np.array(axis[0])
    u = u / np.linalg.norm(u)
    along = float(np.dot(corner - np.array(axis[0]), u)) + width / 2
    sill = float(m[2][3] - wm[2][3]) * s
    return opening, wall, along, width, height, sill


def _opening_fit_error(wall, along, width, height, sill) -> str:
    axis = _axis_world(wall)
    if axis is None or _layer_set(wall) is None:
        return "the host wall has no axis or layers"
    length = math.dist(axis[0], axis[1])
    if width <= 0 or height <= 0 or along - width / 2 < -1e-6 or along + width / 2 > length + 1e-6:
        return "the opening doesn't fit in the wall"
    wall_height = _wall_height(wall)
    if wall_height and sill + height > wall_height + 1e-6:
        return "the opening is taller than the wall"
    return ""


def _apply_opening_edit(element, opening, wall, along, width, height, sill):
    """Inside an action: re-place and resize a door/window and its opening."""
    f = B._model
    s = _scale()
    thickness = _thickness(_layer_set(wall))
    kind = "door" if element.is_a("IfcDoor") else "window"
    placed = _wall_frame(wall)
    _replace_body(opening, ifcopenshell.api.geometry.add_wall_representation(
        f, context=_body_context(), length=width, height=height, thickness=thickness + 0.02))
    ifcopenshell.api.geometry.edit_object_placement(
        f, product=opening, matrix=placed(along - width / 2, -(thickness / 2 + 0.01), sill), is_si=False)
    _replace_body(element, _filling_representation(kind, ifcopenshell.util.element.get_type(element), width, height))
    ifcopenshell.api.geometry.edit_object_placement(
        f, product=element, matrix=placed(along - width / 2, -thickness / 2, sill), is_si=False)
    element.OverallWidth, element.OverallHeight = width / s, height / s


def edit_opening(guid: str, along, width, height, sill) -> str:
    """Move a door/window along its wall and/or resize it (metres); keeps its GlobalId."""
    if B._model is None:
        return _fail("no model open")
    element = _by_guid(guid)
    info = _opening_info(element)
    if info is None:
        return _fail("not a door or window in a wall")
    opening, wall = info[0], info[1]
    try:
        along, width, height, sill = float(along), float(width), float(height), float(sill)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    error = _opening_fit_error(wall, along, width, height, sill)
    if error:
        return _fail(error)

    def action():
        _apply_opening_edit(element, opening, wall, along, width, height, sill)
        return 1, [wall.GlobalId, element.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def slide_openings(guids_json: str, dx, dy) -> str:
    """Slide doors/windows along their walls by the along-wall part of (dx, dy); one undo step."""
    if B._model is None:
        return _fail("no model open")
    try:
        d = np.array([float(dx), float(dy)])
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    plan = []
    for element in B._elements(guids_json):
        info = _opening_info(element)
        if info is None:
            return _fail("only doors and windows in walls can slide")
        opening, wall, along, width, height, sill = info
        axis = _axis_world(wall)
        u = np.array(axis[1]) - np.array(axis[0])
        u = u / np.linalg.norm(u)
        new_along = along + float(np.dot(d, u))
        error = _opening_fit_error(wall, new_along, width, height, sill)
        if error:
            return _fail(error)
        plan.append((element, opening, wall, new_along, width, height, sill))
    if not plan:
        return _fail("nothing to slide")

    def action():
        for element, opening, wall, along, width, height, sill in plan:
            _apply_opening_edit(element, opening, wall, along, width, height, sill)
        return len(plan), [x for e, _, w, *_ in plan for x in (w.GlobalId, e.GlobalId)], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


# ---------------------------------------------------------------- two-storey houses (Slice 7)

def _copy_shape(source, target):
    for identifier in ("Body", "Axis"):
        if ifcopenshell.util.representation.get_representation(source, "Model" if identifier == "Body" else "Plan", identifier):
            ifcopenshell.api.geometry.copy_representation(B._model, source=source, target=target, context_identifier=identifier)


def _place_like(source, target, dz_units, parent=None):
    """Give `target` the world placement of `source` raised by dz (project units), optionally
    relative to `parent` (so hosted copies follow their copied host)."""
    world = ifcopenshell.util.placement.get_local_placement(source.ObjectPlacement).copy()
    world[2][3] += dz_units
    if parent is not None and target.ObjectPlacement is not None:
        target.ObjectPlacement.PlacementRelTo = parent.ObjectPlacement
    ifcopenshell.api.geometry.edit_object_placement(B._model, product=target, matrix=world, is_si=False)


def copy_to_storey(guids_json: str, storey_guid: str) -> str:
    """Copy elements to another level, at the same plan position and the same height above their
    level. Walls bring their openings and the doors/windows in them; joins between copied walls are
    copied too. Doors/windows on their own are copied only with their wall."""
    if B._model is None:
        return _fail("no model open")
    target = _by_guid(storey_guid)
    if target is None or not target.is_a("IfcBuildingStorey"):
        return _fail("unknown level")
    elements = [e for e in B._elements(guids_json) if e.is_a("IfcProduct") and not getattr(e, "FillsVoids", None)
                and not e.is_a("IfcOpeningElement")]
    if not elements:
        return _fail("select the walls, slabs, columns or beams to copy (doors and windows come with their wall)")
    sources = {}
    for e in elements:
        container = ifcopenshell.util.element.get_container(e)
        if container is None or not container.is_a("IfcBuildingStorey"):
            return _fail(f"{e.GlobalId} is not on a level")
        sources[e] = container
    made = {}

    def action():
        f = B._model
        s = _scale()
        copies = {}
        changed = []
        for e in elements:
            dz = (_elevation(target) - _elevation(sources[e])) / s
            c = ifcopenshell.api.root.copy_class(f, product=e)
            _copy_shape(e, c)
            layers.copy_layer(e, c)
            _place_like(e, c, dz)
            ifcopenshell.api.spatial.assign_container(f, products=[c], relating_structure=target)
            copies[e] = c
            changed.append(c.GlobalId)
            # copy_class duplicates the openings (same order); give them shapes and their fillings.
            originals = [r.RelatedOpeningElement for r in getattr(e, "HasOpenings", ()) or ()]
            duplicates = [r.RelatedOpeningElement for r in getattr(c, "HasOpenings", ()) or ()]
            if len(duplicates) != len(originals):  # copy_class didn't duplicate them: do it here
                for d in duplicates:
                    ifcopenshell.api.root.remove_product(f, product=d)
                duplicates = []
                for opening in originals:
                    opening_copy = ifcopenshell.api.root.copy_class(f, product=opening)
                    ifcopenshell.api.feature.add_feature(f, feature=opening_copy, element=c)
                    duplicates.append(opening_copy)
            for opening, opening_copy in zip(originals, duplicates):
                if not opening_copy.Representation:
                    _copy_shape(opening, opening_copy)
                _place_like(opening, opening_copy, dz, parent=c)
                for fill in getattr(opening, "HasFillings", ()) or ():
                    element = fill.RelatedBuildingElement
                    element_copy = ifcopenshell.api.root.copy_class(f, product=element)
                    _copy_shape(element, element_copy)
                    layers.copy_layer(element, element_copy)
                    ifcopenshell.api.feature.add_filling(f, opening=opening_copy, element=element_copy)
                    _place_like(element, element_copy, dz, parent=opening_copy)
                    ifcopenshell.api.spatial.assign_container(f, products=[element_copy], relating_structure=target)
                    changed.append(element_copy.GlobalId)
        # Joins between copied walls, as between the originals.
        for e in elements:
            for rel in getattr(e, "ConnectedTo", ()) or ():
                if rel.is_a("IfcRelConnectsPathElements") and rel.RelatedElement in copies:
                    ifcopenshell.api.geometry.connect_path(
                        f, relating_element=copies[e], related_element=copies[rel.RelatedElement],
                        relating_connection=rel.RelatingConnectionType, related_connection=rel.RelatedConnectionType)
        for e, c in copies.items():
            if c.is_a("IfcWall") and _axis_world(c) is not None and _layer_set(c) is not None:
                ifcopenshell.api.geometry.regenerate_wall_representation(f, wall=c)
        made["copies"] = [copies[e].GlobalId for e in elements]
        return len(copies), changed, []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guids": made["copies"]})


MAX_RISER = 0.175  # metres
TREAD = 0.28       # metres (going)
STAIR_WAIST = 0.2  # metres, vertical thickness under the top step


def create_stair(storey_guid: str, x, y, angle, width, height) -> str:
    """A straight-flight stair going up `height` metres from the level, starting at (x, y) and
    climbing in direction `angle` (radians); risers <= 175 mm, goings 280 mm."""
    if B._model is None:
        return _fail("no model open")
    storey = _by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return _fail("unknown level")
    try:
        x, y, angle, width, height = float(x), float(y), float(angle), float(width), float(height)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    if width <= 0 or height <= 0:
        return _fail("the stair needs a width and a height")
    risers = math.ceil(height / MAX_RISER - 1e-9)
    riser = height / risers
    run = (risers - 1) * TREAD
    made = {}

    def action():
        f = B._model
        s = _scale()
        # Side profile (x along the run, y up), saw-tooth on top, straight underside.
        pts = [(0.0, 0.0)]
        for i in range(1, risers):
            pts += [((i - 1) * TREAD, i * riser), (i * TREAD, i * riser)]
        pts += [(run, height), (run, max(height - STAIR_WAIST, 0.0)), (min(TREAD, run), 0.0)]
        curve = f.createIfcPolyline([f.createIfcCartesianPoint((px / s, py / s)) for px, py in pts + [pts[0]]])
        profile = f.createIfcArbitraryClosedProfileDef("AREA", None, curve)
        position = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, width / 2 / s, 0.0)),
                                               f.createIfcDirection((0.0, -1.0, 0.0)), f.createIfcDirection((1.0, 0.0, 0.0)))
        solid = f.createIfcExtrudedAreaSolid(profile, position, f.createIfcDirection((0.0, 0.0, 1.0)), width / s)
        representation = f.createIfcShapeRepresentation(_body_context(), "Body", "SweptSolid", [solid])
        stair = ifcopenshell.api.root.create_entity(f, ifc_class="IfcStair", name="Stair", predefined_type="STRAIGHT_RUN_STAIR")
        ifcopenshell.api.geometry.assign_representation(f, product=stair, representation=representation)
        c, sn = math.cos(angle), math.sin(angle)
        matrix = np.array([[c, -sn, 0, x], [sn, c, 0, y], [0, 0, 1, _elevation(storey)], [0, 0, 0, 1]], dtype=float)
        ifcopenshell.api.geometry.edit_object_placement(f, product=stair, matrix=matrix, is_si=True)
        ifcopenshell.api.spatial.assign_container(f, products=[stair], relating_structure=storey)
        pset = ifcopenshell.api.pset.add_pset(f, product=stair, name="Pset_StairCommon")
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "NumberOfRiser": risers, "NumberOfTreads": risers - 1,
            "RiserHeight": riser / s, "TreadLength": TREAD / s})
        layers.assign_active(stair)
        made["stair"] = stair
        return 1, [stair.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["stair"].GlobalId, "risers": risers, "riser": round(riser, 6), "run": round(run, 6)})


def add_slab_opening(slab_guid: str, points_json: str) -> str:
    """A hole through a slab with this outline (plan metres), e.g. for a stair."""
    if B._model is None:
        return _fail("no model open")
    slab = _by_guid(slab_guid)
    if slab is None or not slab.is_a("IfcSlab"):
        return _fail("not a slab")
    try:
        outline = _clean_polygon(json.loads(points_json))
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    if outline is None:
        return _fail("the outline needs at least 3 points and must not cross itself")
    layer_set = _layer_set(ifcopenshell.util.element.get_type(slab)) if ifcopenshell.util.element.get_type(slab) else None
    thickness = _thickness(layer_set) if layer_set else 0.3
    bottom = float(ifcopenshell.util.placement.get_local_placement(slab.ObjectPlacement)[2][3]) * _scale()

    def action():
        f = B._model
        opening = ifcopenshell.api.root.create_entity(f, ifc_class="IfcOpeningElement", name="Slab opening")
        representation = ifcopenshell.api.geometry.add_slab_representation(
            f, context=_body_context(), depth=thickness + 0.02, polyline=outline)
        ifcopenshell.api.geometry.assign_representation(f, product=opening, representation=representation)
        matrix = np.eye(4)
        matrix[2][3] = bottom - 0.01
        ifcopenshell.api.geometry.edit_object_placement(f, product=opening, matrix=matrix, is_si=True)
        ifcopenshell.api.feature.add_feature(f, feature=opening, element=slab)
        return 1, [slab.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


# ---------------------------------------------------------------- dimensions in the Properties panel

DIMENSIONS = "Dimensions"


def _extrusion_depth(element) -> float:
    representation = ifcopenshell.util.representation.get_representation(element, "Model", "Body", "MODEL_VIEW")
    depths = [float(e.Depth) for e in B._model.traverse(representation) if e.is_a("IfcExtrudedAreaSolid")] if representation else []
    return max(depths, default=0.0) * _scale()


def element_dimensions(e) -> list[tuple[str, float, bool]]:
    """(name, metres, editable) shown in the Properties panel's Dimensions group."""
    if e.is_a("IfcWall") and _axis_world(e) is not None:
        a, b = _axis_world(e)
        layer_set = _layer_set(e)
        return [("Length", math.dist(a, b), True), ("Height", _wall_height(e), True),
                ("Thickness", _thickness(layer_set) if layer_set else 0.0, False)]
    if e.is_a("IfcDoor") or e.is_a("IfcWindow"):
        info = _opening_info(e)
        if info is not None:
            _, _, _, width, height, sill = info
            return [("Width", width, True), ("Height", height, True), ("Sill height", sill, True)]
    if e.is_a("IfcColumn"):
        return [("Height", _extrusion_depth(e), True)]
    if e.is_a("IfcBeam"):
        return [("Length", _extrusion_depth(e), True)]
    if e.is_a("IfcSlab"):
        t = ifcopenshell.util.element.get_type(e)
        layer_set = _layer_set(t) if t is not None else None
        return [("Thickness", _thickness(layer_set) if layer_set else _extrusion_depth(e), False)]
    return []


def _stretch_plan(wall, p1, p2):
    """Joins dropped and neighbours to regenerate when a wall gets the axis p1-p2 (metres)."""
    a0, a1 = (np.array(p) for p in _axis_world(wall))
    start_moved, end_moved = np.linalg.norm(p1 - a0) > 1e-6, np.linalg.norm(p2 - a1) > 1e-6
    dropped, neighbours = [], []
    for rel in _path_joins(wall):
        mine = rel.RelatingConnectionType if rel.RelatingElement == wall else rel.RelatedConnectionType
        other = rel.RelatedElement if rel.RelatingElement == wall else rel.RelatingElement
        if (mine == "ATSTART" and start_moved) or (mine == "ATEND" and end_moved):
            dropped.append(rel)
        neighbours.append(other)
    return dropped, neighbours


def set_dimension(guids_json: str, name: str, value) -> str:
    """Change a dimension of the selected elements (metres): wall Length (from its start) or Height,
    door/window Width, Height or Sill height, column Height, beam Length (from its start)."""
    if B._model is None:
        return _fail("no model open")
    try:
        metres = float(str(value).strip().replace(",", "."))
    except ValueError:
        return _fail(f"not a number: {value}")
    if name != "Sill height" and metres <= 0:
        return _fail(f"{name} must be more than 0")
    plan = []
    for e in B._elements(guids_json):
        current = {n: (v, editable) for n, v, editable in element_dimensions(e)}
        if name not in current:
            continue
        if not current[name][1]:
            return _fail(f"{name} can't be changed here (it comes from the type)")
        if e.is_a("IfcDoor") or e.is_a("IfcWindow"):
            opening, wall, along, width, height, sill = _opening_info(e)
            width, height, sill = (metres if name == "Width" else width, metres if name == "Height" else height,
                                   metres if name == "Sill height" else sill)
            error = _opening_fit_error(wall, along, width, height, sill)
            if error:
                return _fail(error)
            plan.append(("opening", e, (opening, wall, along, width, height, sill)))
        elif e.is_a("IfcWall") and name == "Length":
            a, b = (np.array(p, dtype=float) for p in _axis_world(e))
            p2 = a + (b - a) / np.linalg.norm(b - a) * metres
            plan.append(("wall-length", e, (a, p2, _stretch_plan(e, a, p2))))
        elif e.is_a("IfcWall"):
            plan.append(("wall-height", e, metres))
        elif e.is_a("IfcColumn") or e.is_a("IfcBeam"):
            element_type = ifcopenshell.util.element.get_type(e)
            if element_type is None or _profile(element_type) is None:
                return _fail(f"{e.Name or e.GlobalId} has no profile type")
            plan.append(("profile", e, (_profile(element_type), metres, e.is_a("IfcBeam"))))
    if not plan:
        return _fail(f"no selected element has a {name}")

    def action():
        f = B._model
        changed = []
        for kind, e, data in plan:
            if kind == "opening":
                opening, wall, along, width, height, sill = data
                _apply_opening_edit(e, opening, wall, along, width, height, sill)
                changed += [wall.GlobalId, e.GlobalId]
            elif kind == "wall-length":
                p1, p2, (dropped, neighbours) = data
                for rel in dropped:
                    if rel.id():
                        f.remove(rel)
                height = _wall_height(e) or 3.0
                _reaxis(e, p1, p2)
                ifcopenshell.api.geometry.regenerate_wall_representation(f, wall=e, length=float(np.linalg.norm(p2 - p1)), height=height)
                for n in neighbours:
                    ifcopenshell.api.geometry.regenerate_wall_representation(f, wall=n)
                changed += [e.GlobalId, *(n.GlobalId for n in neighbours),
                            *(x.GlobalId for x in _hosted(e) if not x.is_a("IfcOpeningElement"))]
            elif kind == "wall-height":
                body = ifcopenshell.util.representation.get_representation(e, "Model", "Body", "MODEL_VIEW")
                for solid in (f.traverse(body) if body is not None else ()):
                    if solid.is_a("IfcExtrudedAreaSolid"):
                        solid.Depth = data / _scale()
                ifcopenshell.api.geometry.regenerate_wall_representation(f, wall=e, height=data)
                changed.append(e.GlobalId)
            else:  # column height / beam length: a new extrusion of the type's profile
                profile, metres_, beam = data
                representation = ifcopenshell.api.geometry.add_profile_representation(
                    f, context=_body_context(), profile=profile, depth=metres_, cardinal_point=8 if beam else 5)
                _replace_body(e, representation)
                changed.append(e.GlobalId)
        return len(plan), changed, []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)
