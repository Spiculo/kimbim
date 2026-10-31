# SPDX-License-Identifier: GPL-3.0-or-later
"""Terrain (site mesh), after Archicad's Mesh: a triangulated surface from survey points or from
contour polylines. The surface is a Delaunay triangulation of the points in plan, with each point's
own elevation (contours are sampled along their segments first). IFC4 stores it as an
`IfcTriangulatedFaceSet`; IFC2X3, which has no tessellated face set, as an
`IfcShellBasedSurfaceModel` of triangular `IfcOpenShell`s.

The element is an `IfcGeographicElement` (IFC2X3: `IfcBuildingElementProxy`) with ObjectType
"Terrain", placed at the world origin (the points are world metres) and contained in a level.
`KIMBIM_Terrain` keeps the source, the point count and the elevation range. Same protocol as
app_bridge: strings in, JSON out, never raise.
"""
from __future__ import annotations

import json
import math

import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import ifcopenshell.util.shape_builder
import numpy as np
from shapely.geometry import MultiPoint, Point, Polygon
from shapely.ops import triangulate

from . import app_bridge as B
from . import authoring as A

PSET = "KIMBIM_Terrain"
DEFAULT_SPACING = 2.0  # metres between samples along a contour
_EPS = 1e-9


# ---------------------------------------------------------------- triangulation (world metres)

def _point(value) -> tuple[float, float, float]:
    """One [x, y, z] triple, in metres."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("each point must be [x, y, z]")
    return float(value[0]), float(value[1]), float(value[2])


def _points(points_json: str) -> list[tuple[float, float, float]]:
    data = json.loads(points_json)
    if not isinstance(data, list):
        raise ValueError("points must be a list of [x, y, z]")
    return [_point(p) for p in data]


def _contours(contours_json: str) -> list[list[tuple[float, float, float]]]:
    data = json.loads(contours_json)
    if not isinstance(data, list) or not data:
        raise ValueError("contours must be a list of polylines")
    out = []
    for contour in data:
        if not isinstance(contour, list) or len(contour) < 2:
            raise ValueError("each contour needs at least two points")
        out.append([_point(p) for p in contour])
    return out


def _options(options_json: str) -> dict:
    if not options_json:
        return {}
    data = json.loads(options_json)
    if not isinstance(data, dict):
        raise ValueError("options must be an object")
    return data


def _sample(contours, spacing: float) -> list[tuple[float, float, float]]:
    """Contour vertices plus a sample every `spacing` metres along each segment (linear in 3D)."""
    out = []
    for contour in contours:
        out.append(contour[0])
        for a, b in zip(contour, contour[1:]):
            length = math.dist(a, b)
            steps = max(1, math.ceil(length / spacing))
            for k in range(1, steps + 1):
                t = k / steps
                out.append((a[0] + (b[0] - a[0]) * t,
                            a[1] + (b[1] - a[1]) * t,
                            a[2] + (b[2] - a[2]) * t))
    return out


def _triangulate(points) -> tuple[list, list[list[int]]]:
    """Unique, sorted points and their Delaunay triangles (counter-clockwise in plan, indices into
    the returned points). Raises ValueError for fewer than three distinct points or collinear ones."""
    unique = {}
    for x, y, z in sorted(points, key=lambda p: (p[0], p[1], p[2])):
        key = (round(x, 9), round(y, 9))
        unique.setdefault(key, (x, y, z))  # the lowest elevation of a repeated plan point
    pts = sorted(unique.values(), key=lambda p: (p[0], p[1], p[2]))
    if len(pts) < 3:
        raise ValueError("a terrain needs at least three distinct points")
    index = {(round(x, 9), round(y, 9)): i for i, (x, y, _z) in enumerate(pts)}
    faces = []
    for triangle in triangulate(MultiPoint([(x, y) for x, y, _z in pts])):
        corners = [index[(round(x, 9), round(y, 9))] for x, y in list(triangle.exterior.coords)[:3]]
        a, b, c = (pts[i] for i in corners)
        cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if abs(cross) < _EPS:
            continue  # collinear: no surface
        faces.append(corners if cross > 0 else [corners[0], corners[2], corners[1]])
    if not faces:
        raise ValueError("the terrain points are collinear")
    return pts, faces


def _bounds(points) -> dict:
    return {"min": [round(min(p[i] for p in points), 6) for i in range(3)],
            "max": [round(max(p[i] for p in points), 6) for i in range(3)]}


# ---------------------------------------------------------------- the element

def _ifc2x3() -> bool:
    return B._model.schema_identifier.upper().startswith("IFC2X3")


def _representation(points, faces):
    """The body: a tessellated face set in IFC4, triangular shells in IFC2X3 (model units)."""
    f, s = B._model, A._scale()
    local = [(x / s, y / s, z / s) for x, y, z in points]
    context = A._body_context()
    if _ifc2x3():
        ifc_points = [f.createIfcCartesianPoint([float(c) for c in p]) for p in local]
        shells = []
        for face in faces:
            loop = f.createIfcPolyLoop([ifc_points[i] for i in face])
            bound = f.createIfcFaceOuterBound(loop, True)
            shells.append(f.createIfcFace([bound]))
        shell = f.createIfcOpenShell(shells)
        model = f.createIfcShellBasedSurfaceModel([shell])
        return f.createIfcShapeRepresentation(context, "Body", "SurfaceModel", [model])
    builder = ifcopenshell.util.shape_builder.ShapeBuilder(f)
    item = builder.triangulated_face_set(local, faces)
    return builder.get_representation(context, [item])


def _level(level_guid: str):
    """The level to contain the terrain: the given storey, or the first one."""
    if level_guid:
        storey = A._by_guid(level_guid)
        if storey is None or not storey.is_a("IfcBuildingStorey"):
            return None
        return storey
    storeys = sorted(B._model.by_type("IfcBuildingStorey"), key=lambda s: s.id())
    return storeys[0] if storeys else None


def _create(level, points, faces, name: str, source: str, spacing=None) -> str:
    made = {}

    def action():
        f = B._model
        if _ifc2x3():
            element = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingElementProxy", name=name)
            element.ObjectType = "Terrain"
        else:
            element = ifcopenshell.api.root.create_entity(f, ifc_class="IfcGeographicElement", name=name,
                                                          predefined_type="USERDEFINED")
            element.ObjectType = "Terrain"
        ifcopenshell.api.spatial.assign_container(f, products=[element], relating_structure=level)
        ifcopenshell.api.geometry.edit_object_placement(f, product=element, matrix=np.eye(4), is_si=True)
        representation = _representation(points, faces)
        ifcopenshell.api.geometry.assign_representation(f, product=element, representation=representation)
        pset = ifcopenshell.api.pset.add_pset(f, product=element, name=PSET)
        properties = {"Source": source, "PointCount": len(points),
                      "MinElevation": float(min(p[2] for p in points)),
                      "MaxElevation": float(max(p[2] for p in points))}
        if spacing is not None:
            properties["Spacing"] = float(spacing)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties=properties)
        made["guid"] = element.GlobalId
        return 1, [element.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["guid"], "triangles": len(faces), "bounds": _bounds(points)})


# ---------------------------------------------------------------- public commands

def create_terrain(level_guid: str, points_json: str, options_json: str = "") -> str:
    """A terrain mesh from survey points [[x, y, z], ...] (world metres). Options: {name, spacing}."""
    if B._model is None:
        return A._fail("no model open")
    level = _level(level_guid)
    if level is None:
        return A._fail("unknown level")
    try:
        points = _points(points_json)
        options = _options(options_json)
        name = str(options.get("name") or "Terrain").strip() or "Terrain"
        spacing = float(options["spacing"]) if options.get("spacing") is not None else None
        if spacing is not None and spacing <= 0:
            return A._fail("the spacing must be positive")
        points, faces = _triangulate(points)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    return _create(level, points, faces, name, "points", spacing)


def create_terrain_from_contours(level_guid: str, contours_json: str, options_json: str = "") -> str:
    """A terrain mesh from contour polylines [[[x, y, z], ...], ...] (world metres), sampled every
    `spacing` metres (default 2 m). Options: {name, spacing}."""
    if B._model is None:
        return A._fail("no model open")
    level = _level(level_guid)
    if level is None:
        return A._fail("unknown level")
    try:
        contours = _contours(contours_json)
        options = _options(options_json)
        name = str(options.get("name") or "Terrain").strip() or "Terrain"
        spacing = float(options.get("spacing", DEFAULT_SPACING))
        if spacing <= 0:
            return A._fail("the spacing must be positive")
        points, faces = _triangulate(_sample(contours, spacing))
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    return _create(level, points, faces, name, "contours", spacing)


def _mesh_data(element):
    """(world points, triangles as index triples) from the terrain's body."""
    rep = ifcopenshell.util.representation.get_representation(element, "Model", "Body", "MODEL_VIEW")
    if rep is None:
        for candidate in (element.Representation.Representations if element.Representation else ()):
            if candidate.RepresentationIdentifier == "Body":
                rep = candidate
                break
    s = A._scale()
    matrix = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
    points, index, faces = [], {}, []

    def world(coordinates):
        c = [float(v) for v in coordinates]
        return tuple((matrix @ np.array([c[0] * s, c[1] * s, c[2] * s, 1.0]))[:3])

    def add(point):
        key = (round(point[0], 9), round(point[1], 9), round(point[2], 9))
        if key not in index:
            index[key] = len(points)
            points.append(point)
        return index[key]

    for item in (rep.Items if rep is not None else ()):
        if item.is_a("IfcTriangulatedFaceSet"):
            coordinates = [add(world(c)) for c in (item.Coordinates.CoordList if item.Coordinates else ())]
            for triangle in item.CoordIndex or ():
                faces.append([coordinates[int(i) - 1] for i in triangle])
        elif item.is_a("IfcShellBasedSurfaceModel"):
            for shell in item.SbsmBoundary or ():
                for face in shell.CfsFaces or ():
                    for bound in face.Bounds or ():
                        loop = bound.Bound
                        if not loop.is_a("IfcPolyLoop"):
                            continue
                        corners = [add(world(p.Coordinates)) for p in loop.Polygon]
                        if len(corners) == 3:
                            faces.append(corners)
                        elif len(corners) > 3:  # a polygon loop: fan it into triangles
                            faces.extend([corners[0], corners[i], corners[i + 1]]
                                         for i in range(1, len(corners) - 1))
    return points, faces


def _mesh(element):
    """(world points, triangle count) from the terrain's body."""
    points, faces = _mesh_data(element)
    return points, len(faces)


def _terrains():
    """(element, pset values) for every KimBim terrain, found through KIMBIM_Terrain."""
    out = []
    for pset in B._model.by_type("IfcPropertySet"):
        if pset.Name != PSET:
            continue
        for element in B._pset_users(pset):
            if element.is_a("IfcElement"):
                out.append((element, ifcopenshell.util.element.get_pset(element, PSET) or {}))
    return sorted(out, key=lambda pair: pair[0].id())


# ---------------------------------------------------------------- building pads

def _pad_polygon(points_json: str):
    """A closed pad outline [[x, y], ...] as clean points and a shapely Polygon."""
    data = json.loads(points_json)
    if not isinstance(data, list):
        raise ValueError("pad points must be a list of [x, y]")
    points = []
    for p in data:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            raise ValueError("each pad point must be [x, y]")
        q = (float(p[0]), float(p[1]))
        if not points or math.dist(q, points[-1]) > 1e-9:
            points.append(q)
    if len(points) > 1 and math.dist(points[0], points[-1]) <= 1e-9:
        points.pop()  # the closing point repeats the first
    if len(points) < 3:
        raise ValueError("a building pad needs at least three points")
    polygon = Polygon(points)
    if not polygon.is_valid or polygon.area <= _EPS:
        raise ValueError("the building pad outline is not a simple polygon")
    return points, polygon


def _terrain_element(terrain_guid: str):
    """(element, KIMBIM_Terrain pset) for a terrain GlobalId, or (None, None)."""
    element = A._by_guid(terrain_guid)
    if element is None or not ifcopenshell.util.element.get_pset(element, PSET):
        return None, None
    for rel in getattr(element, "IsDefinedBy", ()) or ():
        if (rel.is_a("IfcRelDefinesByProperties")
                and rel.RelatingPropertyDefinition.is_a("IfcPropertySet")
                and rel.RelatingPropertyDefinition.Name == PSET):
            return element, rel.RelatingPropertyDefinition
    return None, None


def _pads_from(data: dict) -> list:
    raw = data.get("Pads")
    if not raw:
        return []
    try:
        pads = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    return pads if isinstance(pads, list) else []


def _stored_mesh(data: dict):
    """The mesh kept before the first pad (BasePoints/BaseFaces), or None."""
    raw_points, raw_faces = data.get("BasePoints"), data.get("BaseFaces")
    if not raw_points or not raw_faces:
        return None
    try:
        points = [tuple(float(v) for v in p) for p in json.loads(raw_points)]
        faces = [[int(i) for i in face] for face in json.loads(raw_faces)]
    except (TypeError, ValueError):
        return None
    if len(points) < 3 or not faces:
        return None
    return points, faces


def _mesh_properties(points, faces, pads) -> dict:
    return {"Pads": json.dumps(pads, separators=(",", ":")),
            "PointCount": len(points),
            "MinElevation": float(min(p[2] for p in points)),
            "MaxElevation": float(max(p[2] for p in points))}


def set_building_pad(terrain_guid: str, points_json: str, elevation, options_json: str = "") -> str:
    """Flatten every terrain vertex inside a closed pad outline (world metres) to `elevation`.

    The pad is kept in `KIMBIM_Terrain.Pads`; the mesh from before the first pad is kept in
    `BasePoints`/`BaseFaces`, so `clear_building_pads` can restore the original surface. One undo step.
    """
    if B._model is None:
        return A._fail("no model open")
    try:
        elevation = float(elevation)
        pad_points, polygon = _pad_polygon(points_json)
        _options(options_json)  # accepted for future options; must still be an object
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    element, pset = _terrain_element(terrain_guid)
    if element is None:
        return A._fail("not a terrain")
    made = {}

    def action():
        data = ifcopenshell.util.element.get_pset(element, PSET) or {}
        current_points, current_faces = _mesh_data(element)
        base = _stored_mesh(data) or (current_points, current_faces)
        pads = _pads_from(data) + [{"points": [[round(x, 9), round(y, 9)] for x, y in pad_points],
                                    "elevation": elevation}]
        flattened = [(x, y, elevation if polygon.covers(Point(x, y)) else z)
                     for x, y, z in current_points]
        points, faces = _triangulate(flattened)
        A._replace_body(element, _representation(points, faces))
        properties = _mesh_properties(points, faces, pads)
        properties["BasePoints"] = json.dumps([[round(c, 9) for c in p] for p in base[0]], separators=(",", ":"))
        properties["BaseFaces"] = json.dumps(base[1], separators=(",", ":"))
        ifcopenshell.api.pset.edit_pset(B._model, pset=pset, properties=properties)
        made["pads"], made["triangles"] = len(pads), len(faces)
        return 1, [element.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": terrain_guid, "pads": made["pads"], "triangles": made["triangles"]})


def list_building_pads(terrain_guid: str) -> str:
    """The building pads of a terrain, as stored in KIMBIM_Terrain.Pads."""
    if B._model is None:
        return B._dump({"ok": True, "pads": []})
    element, _pset = _terrain_element(terrain_guid)
    if element is None:
        return A._fail("not a terrain")
    data = ifcopenshell.util.element.get_pset(element, PSET) or {}
    return B._dump({"ok": True, "pads": _pads_from(data)})


def clear_building_pads(terrain_guid: str) -> str:
    """Remove every pad and rebuild the mesh from the surface kept before the first pad.

    Without `BasePoints`/`BaseFaces` (a terrain whose pads came from elsewhere) the current, already
    flattened vertices are kept: clearing the pad records cannot restore elevations it never stored.
    """
    if B._model is None:
        return A._fail("no model open")
    element, pset = _terrain_element(terrain_guid)
    if element is None:
        return A._fail("not a terrain")
    made = {}

    def action():
        data = ifcopenshell.util.element.get_pset(element, PSET) or {}
        base = _stored_mesh(data)
        points, faces = base if base is not None else _mesh_data(element)
        A._replace_body(element, _representation(points, faces))
        ifcopenshell.api.pset.edit_pset(B._model, pset=pset, properties={
            "Pads": None, "BasePoints": None, "BaseFaces": None,
            "PointCount": len(points),
            "MinElevation": float(min(p[2] for p in points)),
            "MaxElevation": float(max(p[2] for p in points))})
        made["triangles"] = len(faces)
        return 1, [element.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": terrain_guid, "pads": 0, "triangles": made["triangles"]})


def list_terrains() -> str:
    """Every terrain: GlobalId, name, point count, triangle count and world bounds."""
    if B._model is None:
        return B._dump({"ok": True, "terrains": []})
    out = []
    for element, data in _terrains():
        points, triangles = _mesh(element)
        out.append({"guid": element.GlobalId, "name": element.Name or "",
                    "points": int(data.get("PointCount") or len(points)), "triangles": triangles,
                    "bounds": _bounds(points) if points else None})
    return B._dump({"ok": True, "terrains": out})


def delete_terrain(guid: str) -> str:
    """Delete a terrain (one undo step)."""
    if B._model is None:
        return A._fail("no model open")
    element = A._by_guid(guid)
    if element is None or not any(e.GlobalId == guid for e, _data in _terrains()):
        return A._fail("not a terrain")

    def action():
        ifcopenshell.api.root.remove_product(B._model, product=element)
        return 1, [], [guid]

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": guid})
