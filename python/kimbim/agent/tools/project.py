# SPDX-License-Identifier: GPL-3.0-or-later
"""Tools about the project: info, settings, set_settings, levels (D102)."""
from __future__ import annotations

import json

from ... import app_bridge as B
from ... import authoring as A
from ... import graphics as G
from ... import levels as L
from ... import settings as S
from ... import versioning as V
from ..catalogue import AgentError, bridge, tool


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


RESERVED = ("agent_changes", "agent_scripts")  # the review rules: only the architect changes them (spec §4.3)


def _check_settings(session, changes):
    """Refused before a task starts: the review rules, and values settings.py would refuse."""
    reserved = sorted(set(changes) & set(RESERVED))
    if reserved:
        raise AgentError("setting_reserved", key=reserved[0])
    for k, v in changes.items():
        if (err := S._error(k, v)) is not None:
            raise AgentError("bad_input", hint=err)


@tool("project.set_settings", {"required": ["changes"], "properties": {
    "changes": {"type": "object", "description": "Settings to change, {key: value} (keys as project.settings)."}}},
    writes=True, check=_check_settings)
def set_settings(session, changes):
    """Change project settings (units, decimals, display options...) as one undo step."""
    current = bridge(S.set_project_settings, json.dumps(changes))["settings"]
    return {k: current.get(k) for k in changes}


@tool("levels.list", {})
def levels_list(session):
    """List the levels from the lowest: GlobalId, name, elevation, height to the next level and element count."""
    return {"levels": json.loads(L.levels_table())["levels"], "unit": "m"}  # metres, like every tool number
