# SPDX-License-Identifier: GPL-3.0-or-later
"""Keynote tools (doc 14 §13): the project's keynote table and the keynotes placed on plans (D59).

The table is a project setting; saving or deleting a keynote is a write tool because it changes the
project. Placing a keynote is a model edit; refreshing rewrites the placed keynotes' text from the table.
"""
from __future__ import annotations

import json

from ... import keynotes as K
from ..catalogue import bridge, tool
from .common import level_guid, point as as_point

_CODE = {"type": "string", "description": "The keynote code, e.g. \"A-1\"."}


@tool("keynotes.list", {})
def list_(session):
    """List the project's keynotes: code, text and category, sorted by code."""
    return {"keynotes": bridge(K.keynote_table)["keynotes"]}


@tool("keynotes.save", {"required": ["code", "text"], "properties": {
    "code": _CODE,
    "text": {"type": "string", "description": "What the keynote says."},
    "category": {"type": "string", "description": "Its group, e.g. \"Structure\" (optional)."}}},
    writes=True)
def save(session, code, text, category=""):
    """Add or change a keynote in the table; run keynotes.refresh to rewrite the keynotes already placed."""
    return {"keynote": bridge(K.save_keynote, code, text, category)["keynote"]}


@tool("keynotes.delete", {"required": ["code"], "properties": {"code": _CODE}}, writes=True)
def delete(session, code):
    """Remove a keynote from the table; the keynotes already placed keep the text they show."""
    bridge(K.delete_keynote, code)
    return {"code": code}


@tool("keynotes.place", {"required": ["level", "point", "code"], "properties": {
    "level": {"type": "string", "description": "Level name or GlobalId."},
    "point": {"type": "array", "items": {"type": "number"},
              "description": "[x, y] where the keynote's text goes, in project units."},
    "code": _CODE,
    "leader": {"type": "array", "items": {"type": "number"},
               "description": "[x, y] the leader's arrow points at (project units); omit for no leader."},
    "size": {"type": "number", "minimum": 0.5, "maximum": 50,
             "description": "Text height in millimetres on paper (default 2.5)."}}},
    writes=True)
def place(session, level, point, code, leader=None, size=None):
    """Place a keynote on a plan: its text at [x, y], optionally with a leader to another point."""
    options = {}
    if leader is not None:
        options["leader"] = list(as_point(session, leader, "leader"))
    if size is not None:
        options["size"] = float(size)
    x, y = as_point(session, point, "point")
    r = bridge(K.place_keynote, level_guid(level), x, y, code, json.dumps(options))
    return {"guid": r["guid"], "annotation": r["annotation"]}


@tool("keynotes.refresh", {}, writes=True)
def refresh(session):
    """Rewrite every placed keynote's text from the table (one undo step); returns how many changed."""
    r = bridge(K.update_keynote_annotations)
    return {"updated": r.get("updated", 0), "guids": r.get("guids", [])}
