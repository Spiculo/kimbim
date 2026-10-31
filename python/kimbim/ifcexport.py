# SPDX-License-Identifier: GPL-3.0-or-later
"""Configurable IFC export (docs/14 §18: "what to export" and property mapping).

The export never touches the open model: it writes the current in-memory model to a temporary
file, reopens that copy, filters the copy and writes the result to `path`. A scope keeps the
spatial structure (project, site, building, storeys), types and materials, and removes the
products outside it:

    all        every product (only the include_* flags filter)
    selection  the given GlobalIds (and what they decompose into) plus their spatial containers
    level      the products contained in the given levels
    class      the products whose IFC class matches one of the given classes

`property_map` renames properties, e.g. {"Pset_WallCommon": {"FireRating": "FireRatingNew"}}.
Same protocol as app_bridge: strings in, JSON out, never raise.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

import ifcopenshell
import ifcopenshell.api.root

from . import app_bridge as B
from . import authoring as A

SCOPES = ("all", "selection", "level", "class")
DEFAULTS = {
    "scope": "all",
    "guids": [],
    "levels": [],
    "classes": [],
    "include_annotations": True,
    "include_spaces": True,
    "include_openings": True,
    "property_map": {},
}
# The spatial structure the export always keeps. IfcSpace is a spatial element too, but it is a
# product the include_spaces flag (and the scopes) filter, so it is not in this list.
_CONTAINERS = ("IfcSite", "IfcBuilding", "IfcBuildingStorey")


def _options(options_json: str) -> dict:
    if not options_json:
        return {}
    data = json.loads(options_json)
    if not isinstance(data, dict):
        raise ValueError("options must be an object")
    return data


def _products(f) -> list:
    """The products an export can filter: everything except the spatial structure itself."""
    return [p for p in f.by_type("IfcProduct") if not any(p.is_a(c) for c in _CONTAINERS)]


def _counts(f) -> list[dict]:
    counts: dict[str, int] = {}
    for p in _products(f):
        counts[p.is_a()] = counts.get(p.is_a(), 0) + 1
    return [{"name": name, "count": count} for name, count in sorted(counts.items())]


def _by_guid(f, guid: str):
    try:
        return f.by_guid(guid)
    except RuntimeError:
        return None


def _descendants(product) -> list:
    """The products a product decomposes or nests into (stair flights, railings, parts...)."""
    out, todo, seen = [], [product], set()
    while todo:
        parent = todo.pop()
        relations = list(getattr(parent, "IsDecomposedBy", ()) or ())
        relations += list(getattr(parent, "IsNestedBy", ()) or ())
        for rel in relations:
            for child in rel.RelatedObjects:
                if child.id() not in seen:
                    seen.add(child.id())
                    out.append(child)
                    todo.append(child)
    return out


def _contained(spatial) -> list:
    """The products a spatial element contains or decomposes into (spaces, storey contents)."""
    out = []
    for rel in getattr(spatial, "ContainsElements", ()) or ():
        out.extend(rel.RelatedElements)
    for rel in getattr(spatial, "IsDecomposedBy", ()) or ():
        out.extend(rel.RelatedObjects)
    return out


def _subtree(spatial) -> list:
    """A spatial element's contained products and all their decomposition children."""
    out, todo, seen = [], list(_contained(spatial)), set()
    while todo:
        product = todo.pop()
        if product.id() in seen:
            continue
        seen.add(product.id())
        out.append(product)
        todo.extend(_descendants(product))
    return out


def _scope_ids(f, options: dict) -> set | None:
    """The ids of the products a scope keeps; None means every product."""
    scope = options.get("scope") or "all"
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}; use one of {', '.join(SCOPES)}")
    if scope == "all":
        return None

    keep: set[int] = set()
    if scope == "selection":
        for guid in options.get("guids") or []:
            product = _by_guid(f, str(guid))
            if product is None or not product.is_a("IfcProduct"):
                continue
            if any(product.is_a(c) for c in _CONTAINERS):
                keep.update(p.id() for p in _subtree(product))
            else:
                keep.add(product.id())
                keep.update(p.id() for p in _descendants(product))
        if not keep:
            raise ValueError("the selection has no products in the model")
    elif scope == "level":
        levels = options.get("levels") or []
        if not levels:
            raise ValueError("no levels given")
        for guid in levels:
            level = _by_guid(f, str(guid))
            if level is None or not any(level.is_a(c) for c in _CONTAINERS):
                raise ValueError(f"unknown level {guid}")
            keep.update(p.id() for p in _subtree(level))
    else:  # class
        classes = [str(c) for c in (options.get("classes") or []) if str(c).strip()]
        if not classes:
            raise ValueError("no classes given")
        for product in _products(f):
            if any(product.is_a(name) for name in classes):
                keep.add(product.id())
                keep.update(p.id() for p in _descendants(product))
    return keep


def _excluded(product, options: dict) -> bool:
    if not options.get("include_annotations", True) and product.is_a("IfcAnnotation"):
        return True
    if not options.get("include_spaces", True) and product.is_a("IfcSpace"):
        return True
    return not options.get("include_openings", True) and product.is_a("IfcOpeningElement")


def _filter(f, keep: set | None, options: dict) -> int:
    """Remove the products outside the scope and the excluded classes; returns how many went."""
    before = len(_products(f))
    doomed = [p for p in _products(f) if (keep is not None and p.id() not in keep) or _excluded(p, options)]
    for product in doomed:
        try:
            current = f.by_id(product.id())  # an earlier removal may have cascaded
        except RuntimeError:
            continue
        ifcopenshell.api.root.remove_product(f, product=current)
    return before - len(_products(f))


def _rename_properties(f, property_map) -> None:
    if not property_map:
        return
    if not isinstance(property_map, dict):
        raise ValueError("property_map must be an object")
    renames = {}
    for pset, mapping in property_map.items():
        if not isinstance(mapping, dict):
            raise ValueError("each property_map entry must be an object")
        renames[str(pset)] = {str(old): str(new) for old, new in mapping.items() if str(new).strip()}
    for pset in f.by_type("IfcPropertySet"):
        mapping = renames.get(pset.Name or "")
        if not mapping:
            continue
        for prop in pset.HasProperties or ():
            new = mapping.get(prop.Name or "")
            if new:
                prop.Name = new


def export_options() -> str:
    """What can be exported: scopes, product classes with counts, levels and the defaults."""
    if B._model is None:
        return A._fail("no model open")
    storeys = sorted(B._model.by_type("IfcBuildingStorey"), key=A._elevation)
    return B._dump({
        "ok": True,
        "scopes": list(SCOPES),
        "classes": _counts(B._model),
        "levels": [{"guid": s.GlobalId, "name": s.Name or ""} for s in storeys],
        "defaults": dict(DEFAULTS),
    })


def export_ifc(path: str, options_json: str = "") -> str:
    """Write the model to `path` with a scope and optional property renames (see the module doc)."""
    if B._model is None:
        return A._fail("no model open")
    if not isinstance(path, str) or not path.strip():
        return A._fail("no export path given")
    try:
        options = _options(options_json)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))

    folder = tempfile.mkdtemp(prefix="kimbim-export-")
    try:
        temp = os.path.join(folder, "model.ifc")
        B._model.write(temp)
        f = ifcopenshell.open(temp)
        # Scope and property map apply to the exported copy only (the open model is never changed).
        keep = _scope_ids(f, options)
        removed = _filter(f, keep, options)
        _rename_properties(f, options.get("property_map"))
        if not _products(f):
            return A._fail("the export has no products")
        f.write(path)
        size = os.path.getsize(path)
        counts = _counts(f)
    except Exception as ex:  # noqa: BLE001 - the GUI shows the reason, the app stays usable
        return A._fail(f"{type(ex).__name__}: {ex}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    return B._dump({
        "ok": True,
        "path": path,
        "products": sum(c["count"] for c in counts),
        "removed": removed,
        "classes": counts,
        "bytes": size,
    })
