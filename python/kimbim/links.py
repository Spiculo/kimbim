# SPDX-License-Identifier: GPL-3.0-or-later
"""Linked models (Archicad hotlinks): another IFC file shown in this model as a read-only reference.

The linked file is tessellated once, transformed by the link's placement (x, y, z, rotation about Z,
uniform scale) and baked into a single `IfcBuildingElementProxy` (ObjectType "Linked model") with one
triangulated body: IFC4 `IfcTriangulatedFaceSet`, IFC2X3 `IfcShellBasedSurfaceModel` (through
terrain._representation). The proxy is contained in a level and carries `KIMBIM_Link`:

    Path, Name, Transform (JSON), ElementCount, SourceHash (sha1 of the file), Updated (ISO)

`update_link` re-reads the source and rebuilds the body in place (same GlobalId). Every change is one
undo step. Same protocol as app_bridge: strings in, JSON out, never raise.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import pathlib

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.geom
import ifcopenshell.util.element
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import terrain

PSET = "KIMBIM_Link"
OBJECT_TYPE = "Linked model"
TRANSFORM_KEYS = ("x", "y", "z", "rotation", "scale")


# ---------------------------------------------------------------- options and source geometry

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
    """The link placement: x, y, z (metres), rotation (degrees), uniform scale, visible."""
    out = {"x": 0.0, "y": 0.0, "z": 0.0, "rotation": 0.0, "scale": 1.0, "visible": True}
    for key in TRANSFORM_KEYS:
        if options.get(key) is not None:
            out[key] = _number(options[key], key)
    if out["scale"] <= 0:
        raise ValueError("the scale must be positive")
    if options.get("visible") is not None:
        out["visible"] = bool(options["visible"])
    return out


def _parse_transform(value) -> dict:
    try:
        data = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        data = None
    return _transform(data) if isinstance(data, dict) else _transform({})


def _apply(points, transform: dict) -> list[tuple[float, float, float]]:
    """Scale, rotate about Z and translate the source's world points (metres)."""
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


def _source(path: str):
    """(world points, triangles, element count, sha1) from the linked IFC file, in metres."""
    source = pathlib.Path(path)
    if not source.is_file():
        raise ValueError(f"the linked file does not exist: {path}")
    try:
        data = source.read_bytes()
        f = ifcopenshell.open(str(source))
    except Exception as ex:  # noqa: BLE001 - unreadable or not IFC
        raise ValueError(f"{type(ex).__name__}: {ex}") from None
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    try:
        iterator = ifcopenshell.geom.iterator(settings, f, 1)
        if not iterator.initialize():
            raise ValueError("the linked model has no geometry")
        points, faces, elements = [], [], 0
        while True:
            shape = iterator.get()
            verts = shape.geometry.verts
            triangles = shape.geometry.faces
            if len(triangles):
                offset = len(points)
                points.extend((float(verts[i]), float(verts[i + 1]), float(verts[i + 2]))
                              for i in range(0, len(verts), 3))
                faces.extend((int(triangles[i]) + offset, int(triangles[i + 1]) + offset,
                              int(triangles[i + 2]) + offset) for i in range(0, len(triangles), 3))
                elements += 1
            if not iterator.next():
                break
    except ValueError:
        raise
    except Exception as ex:  # noqa: BLE001
        raise ValueError(f"{type(ex).__name__}: {ex}") from None
    if not faces:
        raise ValueError("the linked model has no geometry")
    return points, faces, elements, hashlib.sha1(data).hexdigest()


def _bounds(points) -> dict:
    return {"min": [round(min(p[i] for p in points), 6) for i in range(3)],
            "max": [round(max(p[i] for p in points), 6) for i in range(3)]}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- the proxy

def _level(level_guid: str):
    if level_guid:
        storey = A._by_guid(level_guid)
        return storey if storey is not None and storey.is_a("IfcBuildingStorey") else None
    storeys = sorted(B._model.by_type("IfcBuildingStorey"), key=lambda s: s.id())
    return storeys[0] if storeys else None


def _create(level, name: str, path: str, transform: dict, points, faces, elements: int,
            source_hash: str) -> str:
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
            "Path": path,
            "Name": name,
            "Transform": json.dumps(transform),
            "ElementCount": int(elements),
            "SourceHash": source_hash,
            "Updated": _now(),
        })
        made["guid"] = element.GlobalId
        return 1, [element.GlobalId], []

    B._run(action)
    return made["guid"]


def _replace_representation(element, points, faces) -> None:
    """Rebuild the proxy's body in place, dropping its previous representation."""
    f = B._model
    definition = element.Representation
    if definition is not None:
        for representation in list(definition.Representations or ()):
            ifcopenshell.api.geometry.unassign_representation(f, product=element, representation=representation)
            ifcopenshell.api.geometry.remove_representation(f, representation=representation)
    ifcopenshell.api.geometry.assign_representation(f, product=element,
                                                    representation=terrain._representation(points, faces))


def _link(guid: str):
    """(element, KIMBIM_Link values) for a linked model, or (None, None)."""
    element = A._by_guid(guid)
    if element is None or not element.is_a("IfcBuildingElementProxy"):
        return None, None
    data = ifcopenshell.util.element.get_pset(element, PSET)
    return (element, data) if data else (None, None)


def _links() -> list:
    out = []
    for pset in B._model.by_type("IfcPropertySet"):
        if pset.Name != PSET:
            continue
        for element in B._pset_users(pset):
            if element.is_a("IfcBuildingElementProxy"):
                out.append((element, ifcopenshell.util.element.get_pset(element, PSET) or {}))
    return sorted(out, key=lambda pair: pair[0].id())


def _triangles(element) -> int:
    _points, triangles = terrain._mesh(element)
    return triangles


# ---------------------------------------------------------------- public commands

def link_model(path: str, options_json: str = "") -> str:
    """Link an IFC file as one read-only proxy. Options: {name, level, x, y, z, rotation, scale, visible}."""
    if B._model is None:
        return A._fail("no model open")
    if not isinstance(path, str) or not path.strip():
        return A._fail("no linked file given")
    try:
        options = _options(options_json)
        transform = _transform(options)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    level = _level(options.get("level") or "")
    if level is None:
        return A._fail("unknown level")
    name = str(options.get("name") or "").strip() or pathlib.Path(path).stem
    try:
        points, faces, elements, source_hash = _source(path)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    points = _apply(points, transform)
    try:
        guid = _create(level, name, str(pathlib.Path(path).resolve()), transform, points, faces,
                       elements, source_hash)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "guid": guid, "elements": elements, "triangles": len(faces),
                    "bounds": _bounds(points)})


def list_links() -> str:
    """Every linked model: GlobalId, name, path, source element count, triangles, transform and update time."""
    if B._model is None:
        return B._dump({"ok": True, "links": []})
    out = []
    for element, data in _links():
        out.append({
            "guid": element.GlobalId,
            "name": element.Name or "",
            "path": str(data.get("Path") or ""),
            "elements": int(data.get("ElementCount") or 0),
            "triangles": _triangles(element),
            "transform": _parse_transform(data.get("Transform")),
            "updated": str(data.get("Updated") or ""),
        })
    return B._dump({"ok": True, "links": out})


def update_link(guid: str) -> str:
    """Re-read a linked file and rebuild its proxy in place (same GlobalId, one undo step)."""
    if B._model is None:
        return A._fail("no model open")
    element, data = _link(guid)
    if element is None:
        return A._fail("not a linked model")
    try:
        points, faces, elements, source_hash = _source(str(data.get("Path") or ""))
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    transform = _parse_transform(data.get("Transform"))
    points = _apply(points, transform)

    def action():
        _replace_representation(element, points, faces)
        pset = B._own_pset(element, PSET)
        if pset is None:
            pset = ifcopenshell.api.pset.add_pset(B._model, product=element, name=PSET)
        ifcopenshell.api.pset.edit_pset(B._model, pset=pset, properties={
            "SourceHash": source_hash, "Updated": _now(), "ElementCount": int(elements)})
        return 1, [guid], []

    try:
        B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "guid": guid, "elements": elements, "triangles": len(faces),
                    "bounds": _bounds(points)})


def set_link_transform(guid: str, transform_json: str) -> str:
    """Move, rotate or scale a linked model and rebuild it (one undo step)."""
    if B._model is None:
        return A._fail("no model open")
    element, data = _link(guid)
    if element is None:
        return A._fail("not a linked model")
    try:
        changes = _options(transform_json)
        transform = _parse_transform(data.get("Transform"))
        for key in TRANSFORM_KEYS:
            if changes.get(key) is not None:
                transform[key] = _number(changes[key], key)
        if transform["scale"] <= 0:
            raise ValueError("the scale must be positive")
        if changes.get("visible") is not None:
            transform["visible"] = bool(changes["visible"])
        points, faces, elements, source_hash = _source(str(data.get("Path") or ""))
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    points = _apply(points, transform)

    def action():
        _replace_representation(element, points, faces)
        pset = B._own_pset(element, PSET)
        if pset is None:
            pset = ifcopenshell.api.pset.add_pset(B._model, product=element, name=PSET)
        ifcopenshell.api.pset.edit_pset(B._model, pset=pset, properties={
            "Transform": json.dumps(transform), "Updated": _now(),
            "SourceHash": source_hash, "ElementCount": int(elements)})
        return 1, [guid], []

    try:
        B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "guid": guid, "elements": elements, "triangles": len(faces),
                    "bounds": _bounds(points)})


def unlink(guid: str) -> str:
    """Remove a linked model's proxy (one undo step). The linked file itself is left alone."""
    if B._model is None:
        return A._fail("no model open")
    element, _data = _link(guid)
    if element is None:
        return A._fail("not a linked model")

    def action():
        ifcopenshell.api.root.remove_product(B._model, product=element)
        return 1, [], [guid]

    try:
        B._run(action)
    except Exception as ex:  # noqa: BLE001
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "guid": guid})
