# SPDX-License-Identifier: GPL-3.0-or-later
"""Renovation status (Archicad's model, D74): Existing, To be demolished, New. Stored where IFC keeps it,
Pset_<Class>Common.Status (an enumerated value: EXISTING, DEMOLISH, NEW), or KIMBIM_Renovation.Status
where the schema's template for the class has no Status (IFC2X3, spaces, furniture occurrences). Read
from any pset's Status or Archicad's "Renovation Status"; no status, or an unknown one, is New.
Same protocol as app_bridge for the bridge functions (strings in, JSON out, never raise).
"""
from __future__ import annotations

import functools
import json

import ifcopenshell.api.pset
import ifcopenshell.util.element
import ifcopenshell.util.pset

STATUSES = ("existing", "demolish", "new")
IFC_VALUE = {"existing": "EXISTING", "demolish": "DEMOLISH", "new": "NEW"}
PSET = "KIMBIM_Renovation"
NAMES = ("Status", "Renovation Status")


def normalize(value) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    text = str(value or "").strip().lower()
    if text == "existing":
        return "existing"
    if text in ("demolish", "demolished", "to be demolished"):
        return "demolish"
    return "new"


@functools.lru_cache(maxsize=None)
def _common_for(schema: str, ifc_class: str) -> str | None:
    template = ifcopenshell.util.pset.get_template(schema)
    for t in template.get_applicable(ifc_class, pset_only=True):
        if t.Name.endswith("Common") and not t.Name.endswith("TypeCommon") \
                and any(p.Name == "Status" for p in t.HasPropertyTemplates):
            return t.Name
    return None


def common_pset(element) -> str | None:
    """The standard pset whose Status this element's class can carry, if its schema has one."""
    return _common_for(element.file.schema, element.is_a())


def _stored(element):
    """The element's Status (or Renovation Status) value, own over its type's; None if it has none.
    Reads only this element's psets (a resolve over the whole file uses the per-name index instead)."""
    sources = [element]
    element_type = ifcopenshell.util.element.get_type(element)
    if element_type is not None:
        sources.append(element_type)
    for source in sources:
        psets = ifcopenshell.util.element.get_psets(source, psets_only=True, should_inherit=False)
        for name in NAMES:
            for props in psets.values():
                if props.get(name) is not None:
                    return props[name]
    return None


def status_of(element, facts=None) -> str:
    """`facts`: a graphics._Facts sharing the file-wide index (many elements); without it, only this
    element is read (one element: Properties, copies)."""
    if facts is None:
        return normalize(_stored(element))
    for name in NAMES:
        v = facts.prop(name)
        if v is not None:
            return normalize(v)
    return "new"


def _own_pset(element, name):
    data = ifcopenshell.util.element.get_pset(element, name, should_inherit=False)
    return element.file.by_id(data["id"]) if data else None


def write_status(element, status: str) -> None:
    """Inside an action: the element's own status, in one place (the other place's Status is removed)."""
    f = element.file
    target = common_pset(element)
    if target:
        ps = _own_pset(element, target) or ifcopenshell.api.pset.add_pset(f, product=element, name=target)
        ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"Status": [IFC_VALUE[status]]})
        stale = _own_pset(element, PSET)
        if stale is not None and any(p.Name == "Status" for p in stale.HasProperties):
            ifcopenshell.api.pset.edit_pset(f, pset=stale, properties={"Status": None})
    else:
        ps = _own_pset(element, PSET) or ifcopenshell.api.pset.add_pset(f, product=element, name=PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"Status": IFC_VALUE[status]})


# ---------------------------------------------------------------- new elements, copies, the bridge

def _for_new() -> str:
    from . import settings as S

    value = S.current().get("status_for_new", "new")
    return value if value in STATUSES else "new"


def stamp_new(*elements) -> None:
    """New building elements get the status for new elements (annotations and drawings are not stamped)."""
    status = _for_new()
    for e in elements:
        if e is not None and not e.is_a("IfcAnnotation"):
            write_status(e, status)


def copy_status(source, target) -> None:
    """Copies keep their source's status, as they keep its layer."""
    if not source.is_a("IfcAnnotation"):
        write_status(target, status_of(source))


def _edit(elements, status) -> str:
    from . import app_bridge as B

    def action():
        for e in elements:
            write_status(e, status)
        return len(elements)  # restyled, not reshaped: no re-meshing (the app restyles from graphics_state)

    try:
        return B._dump(B._run(action))
    except Exception as ex:
        return B._dump({"ok": False, "error": f"{type(ex).__name__}: {ex}"})


def set_status(guids_json: str, status: str) -> str:
    from . import app_bridge as B

    if B._model is None:
        return B._dump({"ok": False, "error": "no model open"})
    if status not in STATUSES:
        return B._dump({"ok": False, "error": f"unknown renovation status {status}"})
    elements = [e for e in B._elements(guids_json) if not e.is_a("IfcAnnotation")]
    if not elements:
        return B._dump({"ok": False, "error": "no building elements selected"})
    return _edit(elements, status)


def set_status_for_new(status: str) -> str:
    from . import app_bridge as B
    from . import settings as S

    if status not in STATUSES:
        return B._dump({"ok": False, "error": f"unknown renovation status {status}"})
    r = json.loads(S.set_project_settings(json.dumps({"status_for_new": status})))
    return B._dump({"ok": r["ok"], "dirty": r.get("dirty", False), **({"error": r["error"]} if not r["ok"] else {})})


def _unmarked_elements() -> list:
    """Building elements with no status at all, own or from the type (an explicit NEW is marked)."""
    from . import app_bridge as B
    from . import graphics

    shared: dict = {}
    out = []
    for e in graphics._products(B._model):
        if e.is_a("IfcAnnotation") or e.is_a("IfcGrid"):
            continue
        facts = graphics._Facts(e, shared)
        if all(facts.prop(n) is None for n in NAMES):
            out.append(e)
    return out


def unmarked() -> str:
    from . import app_bridge as B

    if B._model is None:
        return B._dump({"ok": False, "error": "no model open"})
    els = _unmarked_elements()
    return B._dump({"ok": True, "count": len(els), "guids": [e.GlobalId for e in els]})


def mark_unmarked(status: str) -> str:
    """Elements with no status at all (an imported survey) get this one, in one undo step."""
    from . import app_bridge as B

    if B._model is None:
        return B._dump({"ok": False, "error": "no model open"})
    if status not in ("existing", "demolish"):
        return B._dump({"ok": False, "error": "mark unmarked elements as existing or demolish"})
    return _edit(_unmarked_elements(), status)
