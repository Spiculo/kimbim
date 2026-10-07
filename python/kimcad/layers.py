# SPDX-License-Identifier: GPL-3.0-or-later
"""Layers and views for the desktop app (owner feedback, Slice 11).

Layers are IFC presentation layers (IfcPresentationLayerAssignment) holding the elements'
representations, so other IFC tools see them. Visibility and locks are view state, not model
data: they live in views. A view is a named collection of layer states (plus level, plan/3D, cut
height), stored in the model as a KIMCAD property set on IfcProject so it travels with the file
and its versions. Same protocol as app_bridge.
"""
from __future__ import annotations

import json

import ifcopenshell.api.layer
import ifcopenshell.api.pset
import ifcopenshell.util.element

from . import app_bridge as B

VIEWS_PSET = "KIMCAD_Views"
_active = ""


def forget() -> None:
    global _active
    _active = ""


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def _all() -> list:
    return list(B._model.by_type("IfcPresentationLayerAssignment")) if B._model is not None else []


def _named(name: str):
    return next((l for l in _all() if l.Name == name), None)


def _representations(element) -> list:
    rep = getattr(element, "Representation", None)
    return list(rep.Representations) if rep is not None else []


def _owners() -> dict:
    """representation id -> product, in one pass (inverse lookups per item are far too slow on
    real files: thousands of layered items in Revit exports)."""
    out = {}
    for product in B._model.by_type("IfcProduct"):
        shape = product.Representation
        if shape is not None:
            for rep in shape.Representations:
                out[rep.id()] = product
    return out


def _members(layer, owners) -> list:
    out, seen = [], set()
    for item in layer.AssignedItems or ():
        product = owners.get(item.id())
        if product is not None and product.id() not in seen:
            seen.add(product.id())
            out.append(product)
    return out


def layers() -> str:
    found = _all()
    owners = _owners() if found else {}
    listing = sorted(({"name": l.Name or "", "count": len(_members(l, owners))} for l in found),
                     key=lambda x: x["name"].lower())
    return B._dump({"layers": listing, "active": _active})


def layer_members() -> str:
    found = _all()
    owners = _owners() if found else {}
    return B._dump({"layers": {l.Name or "": [p.GlobalId for p in _members(l, owners)] for l in found},
                    "active": _active})


def _unassign(element) -> None:
    f = B._model
    for rep in _representations(element):
        for layer in list(getattr(rep, "LayerAssignments", ()) or ()):
            ifcopenshell.api.layer.unassign_layer(f, items=[rep], layer=layer)


def _assign(element, layer) -> None:
    reps = _representations(element)
    if reps:
        ifcopenshell.api.layer.assign_layer(B._model, items=reps, layer=layer)


def element_layer(element):
    for rep in _representations(element):
        for layer in getattr(rep, "LayerAssignments", ()) or ():
            return layer
    return None


# ---- helpers for modeling commands (called inside their transaction)

def assign_active(*elements) -> None:
    """New elements go on the active layer (if there is one)."""
    layer = _named(_active) if _active else None
    if layer is None:
        return
    for e in elements:
        _assign(e, layer)


def copy_layer(source, target) -> None:
    layer = element_layer(source)
    if layer is not None:
        _unassign(target)
        _assign(target, layer)


def carry_layers(old_representation, new_representation) -> None:
    for layer in list(getattr(old_representation, "LayerAssignments", ()) or ()):
        ifcopenshell.api.layer.assign_layer(B._model, items=[new_representation], layer=layer)


# ---- commands

def create_layer(name: str) -> str:
    name = (name or "").strip()
    if B._model is None:
        return _fail("no model open")
    if not name:
        return _fail("a layer needs a name")
    if _named(name) is not None:
        return _fail(f"there is already a layer called {name}")
    return B._dump(B._run(lambda: (ifcopenshell.api.layer.add_layer(B._model, name=name), 1)[1]))


def rename_layer(old: str, new: str) -> str:
    layer = _named(old) if B._model is not None else None
    new = (new or "").strip()
    if layer is None:
        return _fail(f"no layer called {old}")
    if not new or (_named(new) is not None and new != old):
        return _fail("choose a new, unused name")
    global _active

    def action():
        ifcopenshell.api.layer.edit_layer(B._model, layer=layer, attributes={"Name": new})
        return 1

    r = B._run(action)
    if _active == old:
        _active = new
    return B._dump(r)


def delete_layer(name: str) -> str:
    """Delete a layer; its elements stay, without a layer."""
    global _active
    layer = _named(name) if B._model is not None else None
    if layer is None:
        return _fail(f"no layer called {name}")
    r = B._run(lambda: (ifcopenshell.api.layer.remove_layer(B._model, layer=layer), 1)[1])
    if _active == name:
        _active = ""
    return B._dump(r)


def assign_layer(guids_json: str, name: str) -> str:
    """Move elements to a layer (an element is on one layer)."""
    layer = _named(name) if B._model is not None else None
    if layer is None:
        return _fail(f"no layer called {name}")
    elements = [e for e in B._elements(guids_json) if _representations(e)]
    if not elements:
        return _fail("nothing selected that has a shape")

    def action():
        for e in elements:
            _unassign(e)
            _assign(e, layer)
        return len(elements)

    return B._dump(B._run(action))


def set_active_layer(name: str) -> str:
    global _active
    if name and _named(name) is None:
        return _fail(f"no layer called {name}")
    _active = name or ""
    return B._dump({"ok": True, "active": _active})


# ---- views

def _views_dict() -> dict:
    projects = B._model.by_type("IfcProject") if B._model is not None else []
    if not projects:
        return {}
    raw = ifcopenshell.util.element.get_psets(projects[0]).get(VIEWS_PSET, {}).get("Views")
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def views() -> str:
    return B._dump({"views": [{"name": k, "data": v} for k, v in sorted(_views_dict().items(), key=lambda kv: kv[0].lower())]})


def _store_views(data: dict):
    f = B._model
    project = f.by_type("IfcProject")[0]
    pset = next((d.RelatingPropertyDefinition for d in getattr(project, "IsDefinedBy", ()) or ()
                 if d.is_a("IfcRelDefinesByProperties") and d.RelatingPropertyDefinition.Name == VIEWS_PSET), None)
    if pset is None:
        pset = ifcopenshell.api.pset.add_pset(f, product=project, name=VIEWS_PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"Views": f.createIfcText(json.dumps(data, ensure_ascii=False))})


def save_view(name: str, data_json: str) -> str:
    name = (name or "").strip()
    if B._model is None or not B._model.by_type("IfcProject"):
        return _fail("no model open")
    if not name:
        return _fail("a view needs a name")
    try:
        data = json.loads(data_json)
    except ValueError as ex:
        return _fail(str(ex))
    current = _views_dict()
    current[name] = data
    return B._dump(B._run(lambda: (_store_views(current), 1)[1]))


def delete_view(name: str) -> str:
    current = _views_dict()
    if name not in current:
        return _fail(f"no view called {name}")
    del current[name]
    return B._dump(B._run(lambda: (_store_views(current), 1)[1]))
