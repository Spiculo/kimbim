# SPDX-License-Identifier: GPL-3.0-or-later
"""Worksheets (D98, Archicad's independent Worksheet viewpoints): 2D drawing spaces for details,
sketches and pictures that are not cut from the model.

A worksheet is stored the way models are (D58): an ``IfcBuildingStorey`` marked by
``KIMBIM_Worksheet.IsWorksheet``, far below the building (``DEPTH``) so nothing of the model is near
it. Everything drawn on it is ordinary plan annotation (lines, fills, text, dimensions, labels, D59,
D84, D87) and images are underlays placed on it (D85: Archicad's Figure tool), so every 2D tool works
in its tab unchanged. Its plan drawing (named after the worksheet) is what goes on sheets.
"""
from __future__ import annotations

import ifcopenshell
import ifcopenshell.api.document
import ifcopenshell.api.pset
import ifcopenshell.util.element

from . import app_bridge as B

PSET = "KIMBIM_Worksheet"
DEPTH = 1000.0  # metres below the lowest level
GAP = 100.0     # between worksheets


def is_worksheet(storey) -> bool:
    return bool(ifcopenshell.util.element.get_psets(storey).get(PSET, {}).get("IsWorksheet"))


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def worksheets() -> str:
    if B._model is None:
        return B._dump({"ok": True, "worksheets": []})
    from . import drawings

    plans = drawings._plans_by_storey()
    out = []
    for s in B._model.by_type("IfcBuildingStorey"):
        if is_worksheet(s):
            d = plans.get(s.GlobalId)
            out.append({"guid": s.GlobalId, "name": s.Name or "", "drawing": d.GlobalId if d is not None else ""})
    out.sort(key=lambda w: w["name"].lower())
    return B._dump({"ok": True, "worksheets": out})


def create_worksheet(name: str) -> str:
    """A new worksheet and its drawing, one undo step."""
    if B._model is None:
        return _fail("no model open")
    from . import authoring as A
    from . import drawgen as G
    from . import drawings

    name = (name or "").strip()
    if not name:
        return _fail("a worksheet needs a name")
    storeys = B._model.by_type("IfcBuildingStorey")
    if any((s.Name or "") == name for s in storeys):
        return _fail(f"there is already a level, model or worksheet called {name}")
    real = [A._elevation(s) for s in storeys if not A._is_model(s) and not is_worksheet(s)]
    taken = [A._elevation(s) for s in storeys if is_worksheet(s)]
    elevation = min(real + [0.0]) - DEPTH - GAP * len(taken)
    made = {}

    def action():
        storey = A._make_storey(name, elevation)
        pset = ifcopenshell.api.pset.add_pset(B._model, product=storey, name=PSET)
        ifcopenshell.api.pset.edit_pset(B._model, pset=pset, properties={"IsWorksheet": True})
        drawing = drawings._new(name, {"kind": "plan", "points": [], "look": [], "depth": None, "auto": True,
                                       "side": "", "storey": storey.GlobalId, "cut": G.PLAN_CUT, "worksheet": True},
                                bounds=[[-10.0, -10.0, elevation], [10.0, 10.0, elevation + 3.0]])
        made["guid"], made["drawing"] = storey.GlobalId, drawing.GlobalId
        return 1

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["guid"], "drawing": made["drawing"], "elevation": elevation})


def _worksheet(guid: str):
    try:
        s = B._model.by_guid(guid)
    except (RuntimeError, AttributeError):
        return None
    return s if s.is_a("IfcBuildingStorey") and is_worksheet(s) else None


def rename_worksheet(guid: str, name: str) -> str:
    """A worksheet's new name, its drawing's too (one undo step)."""
    if B._model is None:
        return _fail("no model open")
    from . import drawings

    ws = _worksheet(guid)
    name = (name or "").strip()
    if ws is None:
        return _fail("not a worksheet")
    if not name:
        return _fail("a worksheet needs a name")
    if any((s.Name or "") == name and s != ws for s in B._model.by_type("IfcBuildingStorey")):
        return _fail(f"there is already a level, model or worksheet called {name}")
    drawing = drawings._plans_by_storey().get(ws.GlobalId)

    def action():
        ws.Name = name
        if drawing is not None:
            drawing.Name = name
        return 1

    return B._dump(B._run(action))


def delete_worksheet(guid: str) -> str:
    """A worksheet with what is drawn on it, its pictures and its drawing (off every sheet), one undo step."""
    if B._model is None:
        return _fail("no model open")
    import ifcopenshell.api.root

    from . import drawings, settings as S, sheets

    ws = _worksheet(guid)
    if ws is None:
        return _fail("not a worksheet")
    drawing = drawings._plans_by_storey().get(ws.GlobalId)

    def action():
        f = B._model
        if drawing is not None:
            for sheet in sheets._sheets():
                for ref in list(sheets._views(sheet)):
                    if sheets._link(ref) == drawing.GlobalId:
                        ifcopenshell.api.document.remove_reference(f, reference=ref)
            ifcopenshell.api.root.remove_product(f, product=drawing)
        contained = [e for rel in list(ws.ContainsElements or ()) for e in rel.RelatedElements]
        for e in contained:
            ifcopenshell.api.root.remove_product(f, product=e)
        st = S.current()
        st["underlays"] = [u for u in st.get("underlays") or () if u.get("storey") != ws.GlobalId]
        S.restore(st)
        ifcopenshell.api.root.remove_product(f, product=ws)
        return 1

    return B._dump(B._run_settings(action, affects_drawings=True))
