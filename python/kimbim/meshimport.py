# SPDX-License-Identifier: GPL-3.0-or-later
"""Generic mesh import (SketchUp, Rhino, OBJ, STL, PLY): a triangulated object from a mesh file.

The file is parsed here (no extra dependency), polygons are fanned into triangles, and the points are
scaled, rotated about Z and translated into world metres. The object is one
`IfcBuildingElementProxy` (ObjectType "Imported mesh", IFC4 and IFC2X3) with a tessellated body: IFC4
`IfcTriangulatedFaceSet`, IFC2X3 `IfcShellBasedSurfaceModel` (through terrain._representation). It is
contained in a level and carries `KIMBIM_MeshImport`:

    Source, Format (obj/stl/ply), Triangles, Scale, Rotation, Bounds (JSON)

Same protocol as app_bridge: strings in, JSON out, never raise.
"""
from __future__ import annotations

import json
import math
import pathlib
import struct

import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import terrain

PSET = "KIMBIM_MeshImport"
OBJECT_TYPE = "Imported mesh"
FORMATS = ("obj", "stl", "ply")

_FLOAT = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


# ---------------------------------------------------------------- options and transform

def _options(options_json: str) -> dict:
    if not options_json:
        return {}
    data = json.loads(options_json)
    if not isinstance(data, dict):
        raise ValueError("options must be an object")
    return data


def _number(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number") from None


def _transform(options: dict) -> dict:
    """The import placement: x, y, z (metres), rotation (degrees about Z), uniform scale."""
    out = {"x": 0.0, "y": 0.0, "z": 0.0, "rotation": 0.0, "scale": 1.0}
    for key in ("scale", "rotation", "x", "y", "z"):
        if options.get(key) is not None:
            out[key] = _number(options[key], key)
    if out["scale"] <= 0:
        raise ValueError("the scale must be positive")
    return out


def _apply(points, transform: dict) -> list[tuple[float, float, float]]:
    """Scale, rotate about Z and translate the file's points into world metres."""
    angle = math.radians(transform["rotation"])
    cos, sin = math.cos(angle), math.sin(angle)
    scale = transform["scale"]
    out = []
    for x, y, z in points:
        x, y, z = x * scale, y * scale, z * scale
        out.append((x * cos - y * sin + transform["x"],
                    x * sin + y * cos + transform["y"],
                    z + transform["z"]))
    return out


# ---------------------------------------------------------------- parsers

def _float(token: str, what: str) -> float:
    try:
        return float(token)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is not a number: {token}") from None


def _index(token: str, count: int, what: str, base: int = 1) -> int:
    try:
        i = int(token)
    except (TypeError, ValueError):
        raise ValueError(f"{what} is not a whole number: {token}") from None
    if base == 1:  # OBJ is 1-based and its negative indices count from the end
        if i == 0:
            raise ValueError(f"{what} is zero")
        i = i - 1 if i > 0 else count + i
    if not 0 <= i < count:
        raise ValueError(f"{what} {token} is outside the vertex list")
    return i


def _fan(corners: list[int]) -> list[list[int]]:
    """A polygon as triangles around its first vertex."""
    return [[corners[0], corners[k], corners[k + 1]] for k in range(1, len(corners) - 1)]


def _triangles(vertices) -> tuple[list, list]:
    """Points and triangles from a flat run of triangle vertices (STL), merging repeated points."""
    points, index, faces = [], {}, []
    for start in range(0, len(vertices), 3):
        corners = []
        for point in vertices[start:start + 3]:
            key = (round(point[0], 9), round(point[1], 9), round(point[2], 9))
            if key not in index:
                index[key] = len(points)
                points.append(point)
            corners.append(index[key])
        faces.append(corners)
    return points, faces


def _obj(text: str) -> tuple[list, list]:
    points, faces = [], []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        tag = parts[0].lower()
        if tag == "v":
            if len(parts) < 4:
                raise ValueError("an OBJ vertex needs three coordinates")
            points.append(tuple(_float(v, "an OBJ vertex coordinate") for v in parts[1:4]))
        elif tag == "f":
            corners = []
            for token in parts[1:]:
                corners.append(_index(token.split("/")[0], len(points), "an OBJ face index"))
            if len(corners) < 3:
                raise ValueError("an OBJ face needs at least three vertices")
            faces.extend(_fan(corners))
    return points, faces


def _stl_binary(data: bytes, count: int) -> tuple[list, list]:
    vertices = []
    for n in range(count):
        base = 84 + n * 50
        for k in range(3):
            x, y, z = struct.unpack_from("<3f", data, base + 12 + k * 12)
            vertices.append((float(x), float(y), float(z)))
    return _triangles(vertices)


def _stl_ascii(text: str) -> tuple[list, list]:
    vertices = []
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0].lower() == "vertex":
            if len(parts) < 4:
                raise ValueError("an STL vertex needs three coordinates")
            vertices.append(tuple(_float(v, "an STL vertex coordinate") for v in parts[1:4]))
    if len(vertices) % 3:
        raise ValueError("the STL file does not hold whole facets")
    return _triangles(vertices)


def _stl(data: bytes) -> tuple[list, list]:
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if count and 84 + count * 50 == len(data):
            return _stl_binary(data, count)
    text = data.decode("utf-8", errors="replace")
    if "facet" not in text.lower() and len(data) >= 84:  # a binary file with trailing bytes
        count = struct.unpack_from("<I", data, 80)[0]
        if count and 84 + count * 50 <= len(data):
            return _stl_binary(data, count)
    return _stl_ascii(text)


def _ply(text: str) -> tuple[list, list]:
    lines = text.splitlines()
    if not lines or lines[0].strip().lower() != "ply":
        raise ValueError("not a PLY file")
    fmt, elements, cursor = None, [], 1
    ended = False
    while cursor < len(lines):
        line = lines[cursor].strip()
        cursor += 1
        if not line or line.startswith(("comment", "obj_info")):
            continue
        parts = line.split()
        if parts[0] == "format":
            fmt = parts[1].lower() if len(parts) > 1 else ""
        elif parts[0] == "element":
            if len(parts) < 3:
                raise ValueError("a PLY element needs a name and a count")
            elements.append({"name": parts[1].lower(),
                             "count": int(parts[2]), "properties": []})
        elif parts[0] == "property":
            if not elements:
                raise ValueError("a PLY property needs an element")
            elements[-1]["properties"].append(parts[1:])
        elif parts[0] == "end_header":
            ended = True
            break
    if not ended:
        raise ValueError("the PLY header has no end_header")
    if fmt != "ascii":
        raise ValueError(f"only ASCII PLY is supported (this file is {fmt or 'unknown'})")

    points, faces = [], []
    for element in elements:
        scalar = [p[1].lower() for p in element["properties"] if p and p[0] != "list"]
        vertex = element["name"] == "vertex"
        if vertex:
            missing = [axis for axis in ("x", "y", "z") if axis not in scalar]
            if missing:
                raise ValueError("the PLY vertices need x, y and z")
            axes = [scalar.index(axis) for axis in ("x", "y", "z")]
        for _ in range(element["count"]):
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            if cursor >= len(lines):
                raise ValueError("the PLY file ends before its data")
            parts = lines[cursor].split()
            cursor += 1
            if vertex:
                if len(parts) < len(scalar):
                    raise ValueError("a PLY vertex has too few values")
                points.append(tuple(_float(parts[i], "a PLY vertex coordinate") for i in axes))
            elif element["name"] == "face":
                values = [int(v) for v in parts]
                n = values[0] if values else 0
                if n < 3 or len(values) < n + 1:
                    raise ValueError("a PLY face needs at least three vertices")
                corners = [_index(str(v), len(points), "a PLY face index", base=0)
                           for v in values[1:n + 1]]
                faces.extend(_fan(corners))
    return points, faces


def _format(path: str) -> str:
    suffix = pathlib.Path(path).suffix.lower().lstrip(".")
    if suffix not in FORMATS:
        raise ValueError(f"unsupported mesh format: {suffix or 'none'} (expected obj, stl or ply)")
    return suffix


def _read(path: str) -> tuple[list, list, str]:
    """(points, triangles, format) from an OBJ, STL or PLY file, in the file's own units."""
    fmt = _format(path)
    source = pathlib.Path(path)
    if not source.is_file():
        raise ValueError(f"the mesh file does not exist: {path}")
    data = source.read_bytes()
    if not data.strip():
        raise ValueError("the mesh file is empty")
    try:
        if fmt == "obj":
            points, faces = _obj(data.decode("utf-8-sig", errors="replace"))
        elif fmt == "stl":
            points, faces = _stl(data)
        else:
            points, faces = _ply(data.decode("utf-8-sig", errors="replace"))
    except ValueError:
        raise
    except Exception as ex:  # noqa: BLE001 - a malformed file must never raise
        raise ValueError(f"{type(ex).__name__}: {ex}") from None
    if len(points) < 3 or not faces:
        raise ValueError("the mesh file has no triangles")
    return points, faces, fmt


# ---------------------------------------------------------------- the proxy

def _level(level_guid: str):
    """The level to contain the object: the given storey, or the first one."""
    if level_guid:
        storey = A._by_guid(level_guid)
        if storey is None or not storey.is_a("IfcBuildingStorey"):
            return None
        return storey
    storeys = sorted(B._model.by_type("IfcBuildingStorey"), key=lambda s: s.id())
    return storeys[0] if storeys else None


def _create(level, name: str, source: str, fmt: str, transform: dict, points, faces) -> str:
    made = {}

    def action():
        f = B._model
        element = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingElementProxy", name=name)
        element.ObjectType = OBJECT_TYPE
        ifcopenshell.api.spatial.assign_container(f, products=[element], relating_structure=level)
        ifcopenshell.api.geometry.edit_object_placement(f, product=element, matrix=np.eye(4), is_si=True)
        representation = terrain._representation(points, faces)
        ifcopenshell.api.geometry.assign_representation(f, product=element, representation=representation)
        pset = ifcopenshell.api.pset.add_pset(f, product=element, name=PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "Source": source,
            "Format": fmt,
            "Triangles": len(faces),
            "Scale": float(transform["scale"]),
            "Rotation": float(transform["rotation"]),
            "Bounds": json.dumps(terrain._bounds(points), separators=(",", ":")),
        })
        made["guid"] = element.GlobalId
        return 1, [element.GlobalId], []

    B._run(action)
    return made["guid"]


# ---------------------------------------------------------------- public commands

def mesh_formats() -> str:
    """The mesh file formats the importer reads."""
    return B._dump({"ok": True, "formats": list(FORMATS)})


def import_mesh(path: str, level_guid: str = "", options_json: str = "") -> str:
    """Import an OBJ, STL or PLY file as one proxy. Options: {name, scale, rotation, x, y, z}."""
    if B._model is None:
        return A._fail("no model open")
    if not isinstance(path, str) or not path.strip():
        return A._fail("no mesh file given")
    level = _level(level_guid)
    if level is None:
        return A._fail("unknown level")
    try:
        options = _options(options_json)
        transform = _transform(options)
        points, faces, fmt = _read(path)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    name = str(options.get("name") or "").strip() or pathlib.Path(path).stem or "Imported mesh"
    points = _apply(points, transform)
    try:
        guid = _create(level, name, str(pathlib.Path(path).resolve()), fmt, transform, points, faces)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "guid": guid, "name": name, "triangles": len(faces),
                    "bounds": terrain._bounds(points), "format": fmt})
