# SPDX-License-Identifier: GPL-3.0-or-later
"""Library object tools: the catalogue, versions, placing and changing parameters (D102)."""
from __future__ import annotations

import json
import math

from ... import app_bridge as B
from ... import library as Lib
from ... import objversions as OV
from .. import messages, units
from ..catalogue import SELECTOR, AgentError, bridge, tool
from .common import lengths, level_guid, point


def _definition(key: str):
    obj = OV._definition(key)
    if obj is None:
        raise AgentError("not_found", what=key)
    return obj


def _values(session, obj, parameters: dict) -> dict:
    """Parameter values for the bridge: lengths with units become metres; the rest pass through."""
    out = {}
    for name, value in (parameters or {}).items():
        p = obj.param(name)
        out[name] = lengths(session, value)[0] if p is not None and p.kind == "length" else value
    return out


@tool("objects.library", {})
def library(session):
    """List the library objects (furniture, sanitary, kitchen...): id, name, category, IFC class, size (metres)
    and parameters with their kind, default and limits."""
    data = bridge(Lib.library_objects)
    items = [{"id": o["id"], "name": o["name"], "category": o["category"], "ifc_class": o["ifc_class"],
              "width_m": o["width"], "depth_m": o["depth"], "height_m": o["height"],
              "parameters": [{k: p[k] for k in ("key", "label", "kind", "value", "min", "max", "options") if k in p}
                             for p in o["params"]]} for o in data["objects"]]
    return {"objects": items, "unit": "m"}


@tool("objects.versions", {"required": ["object"], "properties": {
    "object": {"type": "string", "description": "A library object id (objects.library)."}}})
def versions(session, object):
    """List the saved versions of a library object (the project's and the office's) and its default values."""
    _definition(object)
    return bridge(OV.object_versions, object)


@tool("objects.place", {"required": ["object", "level", "at"], "properties": {
    "object": {"type": "string", "description": "A library object id (objects.library)."},
    "level": {"type": "string", "description": "Level name or GlobalId."},
    "at": {"type": "array", "items": {"type": ["number", "string"]}, "description": "[x, y] of the object's origin."},
    "angle": {"type": ["number", "string"], "description": "Degrees (90, \"90deg\") or \"1.57rad\"."},
    "version": {"type": "string", "description": "A saved version's id (objects.versions); parameters are then ignored."},
    "parameters": {"type": "object", "description": "{parameter: value}; lengths accept units (\"45cm\")."}}},
    writes=True)
def place(session, object, level, at, angle=0, version="", parameters=None):
    """Place a library object on a level."""
    obj = _definition(object)
    storey = level_guid(level)
    x, y = point(session, at, "at")
    try:
        turn = math.radians(units.parse_angle(angle))
    except ValueError:
        raise AgentError("bad_input", hint=messages.text("hint_bad_angle", value=angle)) from None
    r = bridge(Lib.place_object, storey, object, json.dumps(_values(session, obj, parameters)), x, y, turn, "", version)
    return {"guids": [r["guid"]], "type": r["type"]}


@tool("objects.set_parameters", {"required": ["elements", "parameters"], "properties": {
    "elements": SELECTOR,
    "parameters": {"type": "object", "description": "{parameter: value}; lengths accept units (\"45cm\")."},
    "scope": {"type": "string", "enum": ["all", "selection"], "description":
              "all: every placement of the same type changes; selection: only these. Default: all when these are "
              "every placement of their type, else only these."}}}, writes=True)
def set_parameters(session, elements, parameters, scope=""):
    """Change parameters of placed library objects."""
    guids = session.resolve(elements)
    found = [Lib._object_of(B._model.by_guid(g)) for g in guids]
    objs = [f[0] for f in found if f is not None]
    if not objs:
        raise AgentError("bad_input", hint="none of the elements is a library object")
    for name, value in parameters.items():
        obj = next((o for o in objs if o.param(name) is not None), None)
        if obj is None:
            raise AgentError("bad_input", hint=f"no selected object has a parameter {name}")
        bridge(Lib.set_object_parameter, json.dumps(guids), name, _values(session, obj, {name: value})[name],
               {"all": "type"}.get(scope, scope))
    return {"elements": len(guids), "parameters": list(parameters)}


@tool("objects.assign_version", {"required": ["elements", "version"], "properties": {
    "elements": SELECTOR, "version": {"type": "string", "description": "A version id (objects.versions); \"#default\" for the default."}}},
    writes=True)
def assign_version(session, elements, version):
    """Move placed library objects to a saved version."""
    guids = session.resolve(elements)
    bridge(OV.assign_version, json.dumps(guids), version)
    return {"elements": len(guids)}


@tool("objects.update_from_library", {"properties": {"elements": SELECTOR}}, writes=True)
def update_from_library(session, elements=None):
    """Regenerate placed objects from the library's current definition (all of them when no elements are given)."""
    guids = session.resolve(elements) if elements is not None else []
    given = json.dumps(guids) if guids else ""
    if not Lib._outdated(Lib._targets(given)) and not Lib._outdated_versions_of(given):
        return {"updated": 0}  # already current: the bridge calls that a failure, an agent just wants the state
    bridge(Lib.update_from_library, given)
    return {"updated": len(guids) or "all"}
