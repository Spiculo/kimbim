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
from .common import lengths, level_guid


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
            "mode": "live" if session.live else "offline"}


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


@tool("levels.add", {"required": ["name", "elevation"], "properties": {
    "name": {"type": "string"},
    "elevation": {"type": ["number", "string"], "description": "Project units or a string with units (\"3m\")."}}},
    writes=True)
def levels_add(session, name, elevation):
    """Add a level at an elevation."""
    r = bridge(A.add_storey, name, lengths(session, elevation)[0])
    return {"guid": r["guid"], "name": name}


@tool("levels.edit", {"required": ["level"], "properties": {
    "level": {"type": "string", "description": "Level name or GlobalId."}, "name": {"type": "string"},
    "elevation": {"type": ["number", "string"], "description": "New elevation; the level's elements move with it."},
    "move_above": {"type": "boolean", "description": "Move the levels above by the same amount (default false)."}}},
    writes=True)
def levels_edit(session, level, name=None, elevation=None, move_above=False):
    """Rename a level or move it to a new elevation."""
    if name is None and elevation is None:
        raise AgentError("bad_input", hint="give a name or an elevation")
    guid = level_guid(level)
    target = lengths(session, elevation)[0] if elevation is not None else None
    if name is not None:
        bridge(L.rename_storey, guid, name)
    if target is not None:
        bridge(L.set_storey_elevation, guid, target, bool(move_above))
    return {"guid": guid}


@tool("levels.delete", {"required": ["level"], "properties": {
    "level": {"type": "string", "description": "Level name or GlobalId."},
    "elements": {"type": "string", "enum": ["refuse", "delete", "move"], "description":
                 "What to do with the level's elements: refuse (default), delete them, or move them to move_to."},
    "move_to": {"type": "string", "description": "Level that receives the elements when elements is move."}}},
    writes=True)
def levels_delete(session, level, elements="refuse", move_to=""):
    """Delete a level."""
    if elements == "move" and not move_to:
        raise AgentError("bad_input", hint="elements \"move\" needs move_to")
    bridge(L.delete_storey, level_guid(level), elements, level_guid(move_to) if move_to else "")
    return {"deleted": level}
