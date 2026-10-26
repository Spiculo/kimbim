# SPDX-License-Identifier: GPL-3.0-or-later
"""Read tools about the project: info, settings, levels (D102)."""
from __future__ import annotations

import json

from ... import app_bridge as B
from ... import authoring as A
from ... import graphics as G
from ... import levels as L
from ... import settings as S
from ... import versioning as V
from ..catalogue import tool


@tool("project.info", {})
def info(session):
    """Describe the open project: name, schema, levels, element counts per kind, the current option and whether
    there are unsaved changes."""
    counts: dict[str, int] = {}
    for e in G._products(B._model):
        k = G.kind_of(e)
        counts[k] = counts.get(k, 0) + 1
    state = json.loads(V.project_state())
    projects = B._model.by_type("IfcProject")
    return {"name": (projects[0].Name or "") if projects else "", "schema": B._model.schema,
            "kind": session.kind, "source": session.source, "unit": session.unit,
            "levels": [{"guid": s["guid"], "name": s["name"], "elevation": s["elevation"]}
                       for s in json.loads(A.storeys())["storeys"]],
            "counts": counts, "option": state.get("option", ""), "options": state.get("options", []),
            "versioned": state.get("versioned", False), "unsaved": bool(state.get("dirty", False)),
            "mode": "offline"}


@tool("project.settings", {"properties": {"keys": {"type": "array", "items": {"type": "string"},
                                                    "description": "Only these settings (default: all)."}}})
def settings(session, keys=None):
    """Read the project settings (units, decimals, display options...), all or just the named keys."""
    current = json.loads(S.project_settings())["settings"]
    if keys is not None:
        current = {k: current[k] for k in keys if k in current}
    return current


@tool("levels.list", {})
def levels_list(session):
    """List the levels from the lowest: GlobalId, name, elevation, height to the next level and element count."""
    return json.loads(L.levels_table())["levels"]
