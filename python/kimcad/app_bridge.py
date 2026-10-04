# SPDX-License-Identifier: GPL-3.0-or-later
"""The desktop app's view of an open IFC model (docs/01: the model engine owns the working state).

The C++ app embeds Python and calls these functions. Protocol: plain strings and bytes only,
JSON for structured data, raw little-endian arrays for meshes. Functions never raise; errors are
returned as {"ok": false, "error": ...} or {"error": ...} so the GUI can show them.
"""
from __future__ import annotations

import json
import traceback

import ifcopenshell
import ifcopenshell.util.element

_model: ifcopenshell.file | None = None


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def open_model(path: str) -> str:
    global _model
    try:
        f = ifcopenshell.open(path)
    except Exception as e:  # unreadable or not IFC: report, keep the app usable
        return _dump({"ok": False, "error": f"{type(e).__name__}: {e}"})
    _model = f
    projects = f.by_type("IfcProject")
    return _dump({
        "ok": True,
        "schema": f.schema_identifier,
        "project": (projects[0].Name or "") if projects else "",
        "elements": len(f.by_type("IfcElement")),
    })


def _node(e) -> dict:
    children = []
    for rel in getattr(e, "IsDecomposedBy", None) or ():
        children.extend(rel.RelatedObjects)
    for rel in getattr(e, "ContainsElements", None) or ():
        children.extend(rel.RelatedElements)
    children.sort(key=lambda c: (c.is_a(), c.Name or "", c.GlobalId))
    return {"guid": e.GlobalId, "type": e.is_a(), "name": e.Name or "", "children": [_node(c) for c in children]}


def spatial_tree() -> str:
    if _model is None:
        return _dump({"error": "no model open"})
    projects = _model.by_type("IfcProject")
    if not projects:
        return _dump({"error": "the model has no IfcProject"})
    return _dump(_node(projects[0]))


def _scalar(v):
    if isinstance(v, ifcopenshell.entity_instance):
        return None if v.id() else v.wrappedValue  # entity references are not shown as attributes
    if isinstance(v, (tuple, list)):
        items = [_scalar(x) for x in v]
        return None if any(i is None for i in items) else items
    return v


def properties(guid: str) -> str:
    if _model is None:
        return _dump({"error": "no model open"})
    try:
        e = _model.by_guid(guid)
    except RuntimeError:
        return _dump({"error": f"unknown GlobalId {guid}"})
    try:
        attributes = {k: s for k, v in e.get_info(recursive=False).items() if k not in ("id", "type") and (s := _scalar(v)) is not None}
        psets = {
            name: {k: _scalar(v) if not isinstance(v, (str, int, float, bool)) else v for k, v in props.items() if k != "id"}
            for name, props in ifcopenshell.util.element.get_psets(e).items()
        }
        return _dump({"guid": guid, "type": e.is_a(), "name": e.Name or "", "attributes": attributes, "psets": psets})
    except Exception as ex:
        return _dump({"error": f"{type(ex).__name__}: {ex}", "trace": traceback.format_exc()[-400:]})


def _write_test_model(path: str) -> str:
    """Write a small model (2 walls on one storey) for the app's C++ tests and self-test."""
    from .testing import build_model

    build_model(walls=2).write(path)
    return _dump({"ok": True, "path": path})
