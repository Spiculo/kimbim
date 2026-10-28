# SPDX-License-Identifier: GPL-3.0-or-later
"""Classifications (M2): Uniclass, OmniClass and local systems, their references and assignments.

IFC keeps a system as `IfcClassification` and each code used as an `IfcClassificationReference`
under it; assigning a reference to elements is an `IfcRelAssociatesClassification`. KimBim ships
the metadata for the common systems (creating one is one undo step, like any edit) and lets offices
add their own. Codes are deliberately not bundled: the project keeps the references it uses.

Same protocol as app_bridge (strings in, JSON out, never raise).
"""
from __future__ import annotations

import json

import ifcopenshell.api.classification
import ifcopenshell.util.element

from . import app_bridge as B

SYSTEMS = {
    "Uniclass 2015": {"source": "NBS", "edition": "2015",
                      "description": "Uniclass 2015 (NBS) classification for the UK"},
    "OmniClass": {"source": "CSI/CSC", "edition": "2019",
                  "description": "OmniClass construction classification system (North America)"},
    "Local": {"source": "Office", "edition": "", "description": "The office's own classification"},
}


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def _model():
    return B._model


def _ref(reference) -> dict:
    source = getattr(reference, "ReferencedSource", None)
    system = source if source is not None and source.is_a("IfcClassification") else None
    if system is None and source is not None:
        system = getattr(source, "ReferencedSource", None)
    return {"id": reference.id(), "identification": reference.Identification or "",
            "name": reference.Name or "", "system": getattr(system, "Name", "") if system else "",
            "system_id": system.id() if system else None,
            "key": f"{getattr(system, 'Name', '')}|{reference.Identification or ''}"}


def _system(c) -> dict:
    refs = [r for r in _model().by_type("IfcClassificationReference")
            if getattr(r, "ReferencedSource", None) is not None and
            ((getattr(r.ReferencedSource, "id", lambda: None)() == c.id()) or
             (getattr(getattr(r.ReferencedSource, "ReferencedSource", None), "id", lambda: None)() == c.id()))]
    return {"id": c.id(), "name": c.Name or "", "source": c.Source or "",
            "edition": c.Edition or "", "description": c.Description or "",
            "references": [_ref(r) for r in sorted(refs, key=lambda x: (x.Identification or "", x.Name or ""))]}


def systems() -> str:
    """Every classification system in the model and the references used under it."""
    if _model() is None:
        return _fail("no model open")
    return B._dump({"ok": True, "systems": [_system(c) for c in _model().by_type("IfcClassification")],
                    "built_in": sorted(SYSTEMS)})


def create_system(name: str, source: str = "", edition: str = "", description: str = "") -> str:
    """A new classification system (or a shipped one by name), one undo step."""
    if _model() is None:
        return _fail("no model open")
    name = (name or "").strip()
    if not name:
        return _fail("a classification system needs a name")
    if any((c.Name or "") == name for c in _model().by_type("IfcClassification")):
        return _fail(f"there is already a classification system called {name}")
    defaults = SYSTEMS.get(name, {})

    made = {}

    def action():
        c = ifcopenshell.api.classification.add_classification(_model(), classification=name)
        ifcopenshell.api.classification.edit_classification(_model(), classification=c, attributes={
            "Source": source or defaults.get("source", ""), "Edition": edition or defaults.get("edition", ""),
            "Description": description or defaults.get("description", "")})
        made["id"] = str(c.id())
        return 1

    try:
        B._run(action)
        return B._dump({"ok": True, "id": made["id"]})
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


def add_reference(system: str, identification: str, name: str = "") -> str:
    """A code under a classification system, one undo step. `system` is a GlobalId or its name."""
    if _model() is None:
        return _fail("no model open")
    c = next((x for x in _model().by_type("IfcClassification")
              if str(x.id()) == str(system) or (x.Name or "") == system), None)
    if c is None:
        return _fail(f"no classification system {system}")
    identification = (identification or "").strip()
    if not identification:
        return _fail("a classification reference needs an identification (its code)")
    if any(r.Identification == identification and
           getattr(getattr(r, "ReferencedSource", None), "Name", None) == c.Name
           for r in _model().by_type("IfcClassificationReference")):
        return _fail(f"{identification} is already in {c.Name}")

    made = {}

    def action():
        r = _model().create_entity("IfcClassificationReference", Identification=identification,
                                   Name=name or None, ReferencedSource=c)
        made["id"] = str(r.id())
        return 1

    try:
        B._run(action)
        return B._dump({"ok": True, "id": made["id"]})
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


def remove_reference(reference: str) -> str:
    """Delete a code and every assignment that uses it, one undo step."""
    if _model() is None:
        return _fail("no model open")
    def _key(x):
        return f"{getattr(getattr(x, 'ReferencedSource', None), 'Name', '')}|{x.Identification or ''}"

    r = next((x for x in _model().by_type("IfcClassificationReference")
              if str(x.id()) == str(reference) or _key(x) == str(reference)), None)
    if r is None:
        return _fail("unknown classification reference")

    def action():
        products = list(ifcopenshell.util.element.get_referenced_elements(r))
        if products:
            ifcopenshell.api.classification.remove_reference(_model(), reference=r, products=products)
        if any(x is r for x in _model().by_type("IfcClassificationReference")):
            _model().remove(r)  # the API deletes it when the last assignment goes; otherwise do
        return 1

    try:
        B._run(action)
        return B._dump({"ok": True})
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


def assign_classification(guids_json: str, references: list[str]) -> str:
    """Assign one or more classification references to elements, one undo step."""
    if _model() is None:
        return _fail("no model open")
    try:
        elements = B._elements(guids_json)
    except ValueError as ex:
        return _fail(str(ex))
    wanted = {str(x) for x in references}
    refs = [x for x in _model().by_type("IfcClassificationReference")
            if str(x.id()) in wanted or
            f"{getattr(getattr(x, 'ReferencedSource', None), 'Name', '')}|{x.Identification or ''}" in wanted]
    if not refs:
        return _fail("choose at least one classification reference")

    def action():
        for r in refs:
            ifcopenshell.api.classification.add_reference(_model(), products=elements, reference=r)
        return len(elements) * len(refs)

    try:
        out = B._run(action)
        return B._dump({"ok": True, "assigned": out.get("changed", 0)})
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


def unassign_classification(guids_json: str, references: list[str]) -> str:
    """Remove classification references from elements, one undo step."""
    if _model() is None:
        return _fail("no model open")
    try:
        elements = B._elements(guids_json)
    except ValueError as ex:
        return _fail(str(ex))
    wanted = {str(x) for x in references}
    removed = 0

    def action():
        nonlocal removed
        for rel in list(_model().by_type("IfcRelAssociatesClassification")):
            ref = getattr(rel, "RelatingClassification", None)
            if ref is None or not ref.is_a("IfcClassificationReference"):
                continue
            key = f"{getattr(getattr(ref, 'ReferencedSource', None), 'Name', '')}|{ref.Identification or ''}"
            if str(ref.id()) not in wanted and key not in wanted:
                continue
            keep = [e for e in rel.RelatedObjects if e not in elements]
            removed += len(rel.RelatedObjects) - len(keep)
            if keep:
                rel.RelatedObjects = keep
            else:
                _model().remove(rel)
        return removed

    try:
        out = B._run(action)
        return B._dump({"ok": True, "removed": out.get("changed", 0)})
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


def summary_for(elements) -> list[dict]:
    """The unique classifications of a selection (for the Properties panel)."""
    seen = {}
    for e in elements:
        for rel in getattr(e, "HasAssociations", ()) or ():
            if rel.is_a("IfcRelAssociatesClassification") and rel.RelatingClassification is not None:
                row = _ref(rel.RelatingClassification)
                seen[row["key"]] = row
    return sorted(seen.values(), key=lambda x: (x["system"], x["identification"]))


def of_element(guids_json: str) -> str:
    """The classifications of each selected element: {guid: [{reference, system, identification, name}]}."""
    if _model() is None:
        return _fail("no model open")
    try:
        elements = B._elements(guids_json)
    except ValueError as ex:
        return _fail(str(ex))
    out = {}
    for e in elements:
        rows = []
        for rel in getattr(e, "HasAssociations", ()) or ():
            if not rel.is_a("IfcRelAssociatesClassification"):
                continue
            r = rel.RelatingClassification
            if r is None:
                continue
            row = _ref(r)
            rows.append(row)
        out[e.GlobalId] = sorted(rows, key=lambda x: (x["system"], x["identification"]))
    return B._dump({"ok": True, "elements": out})
