# SPDX-License-Identifier: GPL-3.0-or-later
"""Create tools: types, wall, slab, column, beam, opening, room (D102). Lengths go through units.parse_length;
types are chosen by name or GlobalId and default to the first listed."""
from __future__ import annotations

import json
import math

from ... import app_bridge as B
from ... import authoring as A
from ... import levels as L
from ... import rooms
from .. import messages, units
from ..catalogue import SELECTOR, AgentError, bridge, tool
from .common import lengths, level_guid, pick_type, point

KINDS = ("wall", "slab", "column", "beam", "door", "window")
_LISTERS = {"wall": A.wall_types, "slab": A.slab_types, "column": A.column_types, "beam": A.beam_types}
_LENGTH = {"type": ["number", "string"], "description": "Project units or a string with units (\"50cm\")."}
_POINT = {"type": "array", "items": _LENGTH, "description": "[x, y] in project units or strings with units."}
_TYPE = {"type": "string", "description": "Type name or GlobalId (create.types lists them); default the first."}
_LEVEL = {"type": "string", "description": "Level name or GlobalId."}


def _types(kind: str, create_defaults: bool = True) -> list[dict]:
    """The types of a kind. Creating the defaults of a model that has none is a model change: only write tools do."""
    if kind in ("door", "window"):
        return bridge(A.opening_types, kind, create_defaults)["types"]
    return bridge(_LISTERS[kind], create_defaults)["types"]


def _type(kind: str, ref) -> str:
    return pick_type(_types(kind), ref)


def _level_info(level: str) -> dict:
    guid = level_guid(level)
    info = next((r for r in json.loads(L.levels_table())["levels"] if r["guid"] == guid), None)
    if info is not None:
        return info
    # A KimBim model is a storey below the building: the create tools can draw the unit in it too.
    storey = next(r for r in json.loads(A.storeys())["storeys"] if r["guid"] == guid)
    return {**storey, "height": storey.get("height") or 3.0}


def _level_height(info: dict) -> float:
    return info["height"] or 3.0  # the top level has no next one: 3 m


@tool("create.types", {"required": ["kind"], "properties": {
    "kind": {"type": "string", "enum": list(KINDS)}}})
def types(session, kind):
    """List the types you can create of a kind: GlobalId, name and size (wall thickness, default door/window sizes)."""
    found = _types(kind, create_defaults=False)  # a read tool changes nothing
    out = {"kind": kind, "types": found}
    if not found:
        out["hint"] = f"The project has no {kind} types yet; a create tool makes the defaults when no type is given."
    return out


@tool("create.wall", {"required": ["level", "start", "end"], "properties": {
    "level": _LEVEL, "start": _POINT, "end": _POINT, "height": _LENGTH, "type": _TYPE,
    "join": {"type": "boolean", "description": "Join the ends to walls that meet them (default true)."}}},
    writes=True)
def wall(session, level, start, end, height=None, type="", join=True):
    """Create a straight wall on a level. Its ends join the walls they touch unless join is false."""
    storey = level_guid(level)
    x1, y1 = point(session, start, "start")
    x2, y2 = point(session, end, "end")
    h = lengths(session, height)[0] if height is not None else _level_height(_level_info(level))
    wall_type = _type("wall", type)
    js = bridge(A.wall_join_at, storey, x1, y1)["guid"] if join else ""
    je = bridge(A.wall_join_at, storey, x2, y2)["guid"] if join else ""
    r = bridge(A.create_wall, storey, wall_type, x1, y1, x2, y2, h, js, je)
    return {"guids": [r["guid"]], "length_m": round(math.dist((x1, y1), (x2, y2)), 6), "height_m": round(h, 6)}


@tool("create.slab", {"required": ["level"], "properties": {
    "level": _LEVEL, "points": {"type": "array", "items": _POINT, "description": "Outline, at least 3 points."},
    "from_walls": SELECTOR, "type": _TYPE,
    "offset": {**_LENGTH, "description": "Top of the slab above the level (default 0)."}}}, writes=True)
def slab(session, level, points=None, from_walls=None, type="", offset=0):
    """Create a slab on a level from an outline or from a closed loop of walls (the outline follows their outer faces)."""
    storey = level_guid(level)
    if (points is None) == (from_walls is None):
        raise AgentError("bad_input", hint="give points or from_walls, not both")
    if points is not None:
        outline = [list(point(session, p, "points")) for p in points]
    else:
        outline = bridge(A.slab_outline_from_walls, json.dumps(session.resolve(from_walls)))["points"]
    off = lengths(session, offset)[0]
    r = bridge(A.create_slab, storey, _type("slab", type), json.dumps(outline), off)
    return {"guids": [r["guid"]], "points_m": outline}


@tool("create.curtain_wall", {"required": ["level", "start", "end"], "properties": {
    "level": _LEVEL, "start": _POINT, "end": _POINT, "height": _LENGTH,
    "spacing": {**_LENGTH, "description": "Mullion spacing (default 1.5 m)."},
    "panel_thickness": {**_LENGTH, "description": "Glass panel thickness (default 4 cm)."}}}, writes=True)
def curtain_wall(session, level, start, end, height=None, spacing="1.5m", panel_thickness="4cm"):
    """Create an IfcCurtainWall on a level, with its glazed panel and mullion spacing."""
    storey = level_guid(level)
    x1, y1 = point(session, start, "start")
    x2, y2 = point(session, end, "end")
    h = lengths(session, height)[0] if height is not None else _level_height(_level_info(level))
    r = bridge(A.create_curtain_wall, storey, x1, y1, x2, y2, h,
               lengths(session, spacing)[0], lengths(session, panel_thickness)[0])
    return {"guids": [r["guid"]], "length_m": round(math.dist((x1, y1), (x2, y2)), 6), "height_m": round(h, 6)}


@tool("create.slab_edge", {"required": ["slab"], "properties": {
    "slab": {"type": "string", "description": "GlobalId of the slab."},
    "width": _LENGTH, "depth": _LENGTH}},
    writes=True)
def slab_edge(session, slab, width="2cm", depth="20cm"):
    """Add a raised edge around a slab, one IfcMember per side."""
    r = bridge(A.add_slab_edge, slab, lengths(session, width)[0], lengths(session, depth)[0])
    return {"guids": r["edges"]}


@tool("create.column", {"required": ["level", "at"], "properties": {
    "level": _LEVEL, "at": _POINT, "height": _LENGTH, "type": _TYPE,
    "rotation": {"type": ["number", "string"], "description": "Degrees (90, \"90deg\") or \"1.57rad\"."}}}, writes=True)
def column(session, level, at, height=None, type="", rotation=0):
    """Create a column standing on a level."""
    storey = level_guid(level)
    x, y = point(session, at, "at")
    h = lengths(session, height)[0] if height is not None else _level_height(_level_info(level))
    try:
        turn = math.radians(units.parse_angle(rotation))
    except ValueError:
        raise AgentError("bad_input", hint=messages.text("hint_bad_angle", value=rotation)) from None
    r = bridge(A.create_column, storey, _type("column", type), x, y, h, turn)
    return {"guids": [r["guid"]], "height_m": round(h, 6)}


@tool("create.beam", {"required": ["level", "start", "end"], "properties": {
    "level": _LEVEL, "start": _POINT, "end": _POINT, "type": _TYPE,
    "top": {**_LENGTH, "description": "Height of the beam's top above the level (default the level's height)."}}},
    writes=True)
def beam(session, level, start, end, top=None, type=""):
    """Create a beam between two points on a level."""
    storey = level_guid(level)
    info = _level_info(level)
    x1, y1 = point(session, start, "start")
    x2, y2 = point(session, end, "end")
    above = lengths(session, top)[0] if top is not None else _level_height(info)
    r = bridge(A.create_beam, storey, _type("beam", type), x1, y1, x2, y2, info["elevation"] + above)
    return {"guids": [r["guid"]], "top_m": round(info["elevation"] + above, 6)}


@tool("create.opening", {"required": ["kind", "wall", "along"], "properties": {
    "kind": {"type": "string", "enum": ["door", "window"]},
    "wall": {"type": "string", "description": "GlobalId of the wall."},
    "along": {**_LENGTH, "description": "Distance from the wall's start to the centre of the opening."},
    "width": _LENGTH, "height": _LENGTH, "sill": {**_LENGTH, "description": "Bottom above the wall's base."},
    "type": _TYPE}}, writes=True)
def opening(session, kind, wall, along, width=None, height=None, sill=None, type=""):
    """Put a door or window in a wall. Sizes default to the type's own."""
    try:
        host = B._model.by_guid(wall)
    except RuntimeError:
        host = None
    if host is None or not host.is_a("IfcWall"):
        raise AgentError("not_found", what=wall)
    type_guid = _type(kind, type)
    base = A._opening_defaults(B._model.by_guid(type_guid))
    width_m, height_m, sill_m = [lengths(session, v)[0] if v is not None else d
                                 for v, d in zip((width, height, sill), base)]
    r = bridge(A.insert_opening, kind, wall, type_guid, lengths(session, along)[0], width_m, height_m, sill_m)
    return {"guids": [r["guid"]], "width_m": round(width_m, 6), "height_m": round(height_m, 6),
            "sill_m": round(sill_m, 6)}


@tool("create.room", {"required": ["level", "at"], "properties": {
    "level": _LEVEL, "at": _POINT, "name": {"type": "string"}}}, writes=True)
def room(session, level, at, name=""):
    """Create a room filling the walled-in space around a point."""
    x, y = point(session, at, "at")
    r = bridge(rooms.create_room, level_guid(level), x, y, name)
    return {"guids": [r["guid"]]}
