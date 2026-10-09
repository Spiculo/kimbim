# SPDX-License-Identifier: GPL-3.0-or-later
"""Renovation status (Archicad's model, D74): Existing, To be demolished, New. Stored where IFC keeps it,
Pset_<Class>Common.Status (an enumerated value: EXISTING, DEMOLISH, NEW), or KIMCAD_Renovation.Status
where the schema's template for the class has no Status (IFC2X3, spaces, furniture occurrences). Read
from any pset's Status or Archicad's "Renovation Status"; no status, or an unknown one, is New.
Same protocol as app_bridge for the bridge functions (strings in, JSON out, never raise).
"""
from __future__ import annotations

import functools

import ifcopenshell.api.pset
import ifcopenshell.util.element
import ifcopenshell.util.pset

STATUSES = ("existing", "demolish", "new")
IFC_VALUE = {"existing": "EXISTING", "demolish": "DEMOLISH", "new": "NEW"}
PSET = "KIMCAD_Renovation"
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


def status_of(element, facts=None) -> str:
    from . import graphics

    facts = facts if facts is not None else graphics._Facts(element)
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
