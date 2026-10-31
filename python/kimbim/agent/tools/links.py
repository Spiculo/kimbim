# SPDX-License-Identifier: GPL-3.0-or-later
"""Linked-model tools (D102): link another IFC as a read-only reference, list, update, transform and
remove it. The linked file is tessellated into one proxy; each change is one undo step."""
from __future__ import annotations

import json

from ... import links as L
from ..catalogue import AgentError, bridge, tool
from .common import level_guid

_PATH = {"type": "string", "description": "Path of the IFC file to link."}
_GUID = {"type": "string", "description": "GlobalId of the linked model (links.list lists them)."}
_OPTIONS = {"type": ["object", "string"],
            "description": "Link options: name, level (name or GlobalId), x, y, z (metres), "
                           "rotation (degrees), scale, visible."}
_TRANSFORM = {"type": ["object", "string"],
              "description": "Placement changes: x, y, z (metres), rotation (degrees), scale, visible."}


def _json(value) -> str:
    return value if isinstance(value, str) else json.dumps(value or {})


@tool("links.add", {"required": ["path"], "properties": {"path": _PATH, "options": _OPTIONS}},
      writes=True)
def add(session, path, options=None):
    """Link an IFC file as a read-only reference on a level (default the first), with a placement."""
    try:
        opts = dict(options) if isinstance(options, dict) else json.loads(options or "{}")
    except (TypeError, ValueError):
        raise AgentError("bad_input", hint="options must be an object") from None
    if not isinstance(opts, dict):
        raise AgentError("bad_input", hint="options must be an object")
    if opts.get("level"):
        opts["level"] = level_guid(opts["level"])
    r = bridge(L.link_model, path, json.dumps(opts))
    return {"guid": r["guid"], "elements": r["elements"], "triangles": r["triangles"],
            "bounds_m": r["bounds"]}


@tool("links.list", {})
def list_links(session):
    """List the linked models: GlobalId, name, path, source element count, triangles, transform and update time."""
    return {"links": bridge(L.list_links)["links"]}


@tool("links.update", {"required": ["guid"], "properties": {"guid": _GUID}}, writes=True)
def update(session, guid):
    """Re-read a linked model's file and rebuild its geometry (same GlobalId)."""
    r = bridge(L.update_link, guid)
    return {"guid": r["guid"], "elements": r["elements"], "triangles": r["triangles"],
            "bounds_m": r["bounds"]}


@tool("links.set_transform", {"required": ["guid"], "properties": {
    "guid": _GUID, "transform": _TRANSFORM}}, writes=True)
def set_transform(session, guid, transform):
    """Move, rotate or scale a linked model and rebuild it."""
    r = bridge(L.set_link_transform, guid, _json(transform))
    return {"guid": r["guid"], "elements": r["elements"], "triangles": r["triangles"],
            "bounds_m": r["bounds"]}


@tool("links.remove", {"required": ["guid"], "properties": {"guid": _GUID}}, writes=True)
def remove(session, guid):
    """Remove a linked model from the project (the linked file itself is left alone)."""
    bridge(L.unlink, guid)
    return {"removed": guid}
