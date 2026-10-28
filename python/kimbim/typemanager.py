# SPDX-License-Identifier: GPL-3.0-or-later
"""The type manager (M2): list types, assign one, make one from an element, edit a type and push its
values to every occurrence.

Types are ordinary IFC type objects (`IfcWallType`, `IfcDoorType`...). Instances inherit their type's
property sets but may override a value (D50); *update all* removes those overrides so every occurrence
shows the type value. Same protocol as app_bridge (strings in, JSON out, never raise).
"""
from __future__ import annotations

import json

import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.type
import ifcopenshell.util.element

from . import app_bridge as B

_TYPE_CLASSES = {
    "IfcWall": ("IfcWallType",), "IfcWallStandardCase": ("IfcWallType",),
    "IfcSlab": ("IfcSlabType",), "IfcRoof": ("IfcRoofType",),
    "IfcColumn": ("IfcColumnType",), "IfcBeam": ("IfcBeamType",),
    "IfcDoor": ("IfcDoorType", "IfcDoorStyle"), "IfcWindow": ("IfcWindowType", "IfcWindowStyle"),
    "IfcStair": ("IfcStairType",), "IfcRamp": ("IfcRampType",), "IfcRailing": ("IfcRailingType",),
    "IfcCovering": ("IfcCoveringType",), "IfcPlate": ("IfcPlateType",), "IfcMember": ("IfcMemberType",),
    "IfcFurnishingElement": ("IfcFurnitureType", "IfcFurnishingElementType"),
    "IfcFurniture": ("IfcFurnitureType",), "IfcSanitaryTerminal": ("IfcSanitaryTerminalType",),
    "IfcSpace": ("IfcSpaceType",),
}


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def _type_of(e):
    return B._type_of(e)


def _type_class(model, element_class: str) -> str | None:
    for name in _TYPE_CLASSES.get(element_class, ()):
        try:
            B._schema().declaration_by_name(name)
            return name
        except Exception:
            continue
    return None


def _entry(t) -> dict:
    occurrences = ifcopenshell.util.element.get_types(t)
    return {"guid": t.GlobalId, "name": t.Name or t.is_a(), "class": t.is_a(),
            "description": getattr(t, "Description", None) or "", "tag": getattr(t, "Tag", None) or "",
            "count": len(occurrences)}


def list_types() -> str:
    """Every type in the model and how many elements use it."""
    if B._model is None:
        return _fail("no model open")
    types = sorted(B._model.by_type("IfcTypeObject"), key=lambda t: (t.is_a(), t.Name or ""))
    return B._dump({"ok": True, "types": [_entry(t) for t in types]})


def type_of(guids_json: str) -> str:
    """The types of the selected elements, with the untyped ones' GlobalIds."""
    if B._model is None:
        return _fail("no model open")
    try:
        elements = B._elements(guids_json)
    except ValueError as ex:
        return _fail(str(ex))
    types, untyped = {}, []
    for e in elements:
        t = _type_of(e)
        if t is None:
            untyped.append(e.GlobalId)
        else:
            types.setdefault(t.GlobalId, _entry(t))
    return B._dump({"ok": True, "types": list(types.values()), "untyped": untyped})


def assign_type(guids_json: str, type_guid: str) -> str:
    """Assign an existing type to the elements, one undo step (their representation follows it)."""
    if B._model is None:
        return _fail("no model open")
    try:
        elements = B._elements(guids_json)
        t = B._model.by_guid(type_guid)
    except (ValueError, RuntimeError):
        return _fail("unknown element or type")
    if not elements:
        return _fail("select at least one element")
    if not t.is_a("IfcTypeObject"):
        return _fail(f"{t.is_a()} is not a type")

    def action():
        ifcopenshell.api.type.assign_type(B._model, related_objects=elements, relating_type=t,
                                          should_map_representations=True)
        return len(elements)

    try:
        out = B._run(action)
        return B._dump({"ok": True, "assigned": out.get("changed", 0), "type": _entry(t)})
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


def create_type(guids_json: str, name: str = "") -> str:
    """Make a type from the first selected element (its property sets), assign it to all, one undo step."""
    if B._model is None:
        return _fail("no model open")
    try:
        elements = B._elements(guids_json)
    except ValueError as ex:
        return _fail(str(ex))
    if not elements:
        return _fail("select an element to make the type from")
    source = elements[0]
    type_class = _type_class(B._model, source.is_a())
    if type_class is None:
        return _fail(f"{source.is_a()} has no IFC type class to make")
    made = {}

    def action():
        t = ifcopenshell.api.root.create_entity(B._model, ifc_class=type_class,
                                                name=name.strip() or (source.Name or source.is_a()))
        copied = []
        for pset_name, props in ifcopenshell.util.element.get_psets(source).items():
            values = {k: v for k, v in props.items() if k not in ("id", "type")}
            if not values:
                continue
            ps = ifcopenshell.api.pset.add_pset(B._model, product=t, name=pset_name)
            ifcopenshell.api.pset.edit_pset(B._model, pset=ps, properties=values)
            copied.append(pset_name)
        ifcopenshell.api.type.assign_type(B._model, related_objects=elements, relating_type=t,
                                          should_map_representations=True)
        # Occurrences inherit the type: drop the copies that became overrides on each one.
        for o in elements:
            for pset_name in copied:
                own = B._own_pset(o, pset_name)
                if own is not None:
                    ifcopenshell.api.pset.remove_pset(B._model, product=o, pset=own)
        made["type"] = _entry(t)
        return len(elements)

    try:
        out = B._run(action)
        return B._dump({"ok": True, "type": made["type"], "assigned": out.get("changed", 0)})
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


def edit_type(type_guid: str, changes_json: str = "{}") -> str:
    """Edit a type: name, description, tag and property values (`{"psets": {pset: {prop: value}}}`)."""
    if B._model is None:
        return _fail("no model open")
    try:
        t = B._model.by_guid(type_guid)
        changes = json.loads(changes_json or "{}")
    except (RuntimeError, ValueError):
        return _fail("unknown type or bad changes")
    if not t.is_a("IfcTypeObject"):
        return _fail(f"{t.is_a()} is not a type")
    psets = changes.get("psets") if isinstance(changes.get("psets"), dict) else {}
    plan = []
    try:
        for pset_name, props in psets.items():
            for prop, value in (props or {}).items():
                existing = B._type_property(t, pset_name, prop)
                ifc_type = B._value_type(existing, B._infer_type(value))
                plan.append((pset_name, prop, ifc_type, B._convert(value, ifc_type)))
    except ValueError as ex:
        return _fail(str(ex))

    def action():
        for key in ("Name", "Description", "Tag"):
            if key in changes:
                setattr(t, key, changes[key] if changes[key] != "" else None)
        for pset_name, prop, ifc_type, converted in plan:
            ps = B._type_pset(t, pset_name) or ifcopenshell.api.pset.add_pset(
                B._model, product=t, name=pset_name)
            ifcopenshell.api.pset.edit_pset(B._model, pset=ps,
                                            properties={prop: B._model.create_entity(ifc_type, converted)})
        return 1

    try:
        B._run(action)
        return B._dump({"ok": True, "type": _entry(t)})
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


def update_type_all(type_guid: str) -> str:
    """Drop every occurrence's override of the type's properties, so all show the type's values."""
    if B._model is None:
        return _fail("no model open")
    try:
        t = B._model.by_guid(type_guid)
    except RuntimeError:
        return _fail("unknown type")
    occurrences = ifcopenshell.util.element.get_types(t)
    removed = 0

    def action():
        nonlocal removed
        for o in occurrences:
            for ps in getattr(t, "HasPropertySets", None) or ():
                own = B._own_pset(o, ps.Name or "")
                if own is None:
                    continue
                for prop in list(getattr(ps, "HasProperties", None) or ()):
                    if any(p.Name == prop.Name for p in (own.HasProperties or ())):
                        ifcopenshell.api.pset.edit_pset(B._model, pset=own, properties={prop.Name: None},
                                                        should_purge=True)
                        removed += 1
        return removed

    try:
        out = B._run(action)
        return B._dump({"ok": True, "removed": out.get("changed", 0), "occurrences": len(occurrences)})
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


def type_details(type_guid: str) -> str:
    """A type's name, properties and the elements that use it."""
    if B._model is None:
        return _fail("no model open")
    try:
        t = B._model.by_guid(type_guid)
    except RuntimeError:
        return _fail("unknown type")
    psets = {k: {p: v for p, v in props.items() if p not in ("id", "type")}
             for k, props in ifcopenshell.util.element.get_psets(t).items()}
    return B._dump({"ok": True, "type": _entry(t), "psets": psets,
                    "occurrences": [e.GlobalId for e in ifcopenshell.util.element.get_types(t)]})
