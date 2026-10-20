# SPDX-License-Identifier: GPL-3.0-or-later
"""Show on levels (D91, Archicad's "Show on stories" and Revit's view range): which levels an element
shows on. The rule is stored per element in KIMBIM_ShowOn.Levels and read by drawgen (which runs in
its own process, so the rule parser lives there): "home" (the default), "up" / "up:N", "down" /
"down:N", "all", "range:LO..HI" (offsets from the home level) or a small expression over `d`.
This module is the bridge that writes it. Same protocol as app_bridge (strings in, JSON out).
"""
from __future__ import annotations

import ifcopenshell.util.element

PSET = "KIMBIM_ShowOn"
DEFAULT = "home"

# The rule parser and resolver live in drawgen (the drawing worker cannot import the package).
from .drawgen import home_level, shows_on  # noqa: E402,F401  (re-exported for callers and tests)


def set_show_on(guids_json: str, rule: str) -> str:
    """Inside an action: the elements' show-on rule (one undo step)."""
    import ifcopenshell.api.pset

    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    rule = (rule or DEFAULT).strip() or DEFAULT
    try:
        elements = B._elements(guids_json)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    if not elements:
        return A._fail("no elements selected")

    def action():
        for e in elements:
            data = ifcopenshell.util.element.get_pset(e, PSET, should_inherit=False)
            pset = e.file.by_id(data["id"]) if data else ifcopenshell.api.pset.add_pset(e.file, product=e, name=PSET)
            ifcopenshell.api.pset.edit_pset(e.file, pset=pset, properties={"Levels": rule})
        return len(elements), [e.GlobalId for e in elements], []

    try:
        return B._dump(B._run(action))
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
