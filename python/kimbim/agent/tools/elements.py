# SPDX-License-Identifier: GPL-3.0-or-later
"""Element tools: find and get (D102). Elements are chosen with the shared SELECTOR."""
from __future__ import annotations

import json

import ifcopenshell.util.element

from ... import app_bridge as B
from ... import authoring as A
from ... import graphics as G
from ..catalogue import SELECTOR, AgentError, bridge, tool


def _offset(cursor: str) -> int:
    try:
        n = int(cursor or 0)
    except ValueError:
        n = -1
    if n < 0:
        raise AgentError("bad_input", hint="cursor must come from a previous next_cursor")
    return n


def _level_name(e) -> str:
    for rel in getattr(e, "ContainedInStructure", None) or ():
        return rel.RelatingStructure.Name or ""
    return ""


@tool("elements.find", {"required": ["elements"], "properties": {
    "elements": SELECTOR,
    "limit": {"type": "integer", "description": "Page size (default 200)."},
    "cursor": {"type": "string", "description": "next_cursor from the previous page."}}})
def find(session, elements, limit=200, cursor=""):
    """Find elements and list them: GlobalId, label, kind and level, a page at a time."""
    guids = session.resolve(elements)
    start, limit = _offset(cursor), max(1, int(limit))
    items = []
    for g in guids[start:start + limit]:
        e = B._model.by_guid(g)
        items.append({"guid": g, "label": session.label(g), "kind": G.kind_of(e), "level": _level_name(e)})
    end = start + limit
    return {"items": items, "total": len(guids), "next_cursor": str(end) if end < len(guids) else ""}


def _related(e) -> dict:
    """The wall a door/window sits in (host), or what fills a wall's openings (openings), as GlobalIds."""
    out: dict = {}
    for fill in getattr(e, "FillsVoids", None) or ():
        for void in getattr(fill.RelatingOpeningElement, "VoidsElements", None) or ():
            out["host"] = void.RelatingBuildingElement.GlobalId
    fillers = [f.RelatedBuildingElement.GlobalId for v in getattr(e, "HasOpenings", None) or ()
               for f in getattr(v.RelatedOpeningElement, "HasFillings", None) or ()]
    if fillers:
        out["openings"] = fillers
    return out


@tool("elements.get", {"required": ["elements"], "properties": {
    "elements": SELECTOR, "limit": {"type": "integer", "description": "Most elements to describe (default 50)."}}})
def get(session, elements, limit=50):
    """Describe elements in full: class, type, level, dimensions (metres), property sets, host and openings."""
    guids = session.resolve(elements)
    limit = max(1, int(limit))
    out = []
    for g in guids[:limit]:
        e = B._model.by_guid(g)
        t = ifcopenshell.util.element.get_type(e)
        props = bridge("properties_multi", json.dumps([g]))
        psets = {name: {k: v["value"] for k, v in group.items()}
                 for name, group in (props.get("psets") or {}).items() if name != A.DIMENSIONS}
        row = {"guid": g, "label": session.label(g), "class": e.is_a(), "type": (t.Name or "") if t else "",
               "level": _level_name(e),
               "dimensions": {"unit": "m", "values": {n: round(v, 6) for n, v, _ in A.element_dimensions(e)}},
               "properties": psets}
        row.update(_related(e))
        out.append(row)
    return {"items": out, "total": len(guids), "truncated": len(guids) > limit}
