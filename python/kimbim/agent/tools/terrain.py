# SPDX-License-Identifier: GPL-3.0-or-later
"""Terrain tools (D102): create a site mesh from survey points or contour polylines, flatten building
pads, list the terrains and delete one. Points are [x, y, z] in project units or strings with units;
the bridge takes world metres."""
from __future__ import annotations

import json

from ... import terrain as T
from ..catalogue import AgentError, bridge, tool
from .common import lengths, level_guid

_LENGTH = {"type": ["number", "string"], "description": "Project units or a string with units (\"50cm\")."}
_POINT = {"type": "array", "items": _LENGTH, "description": "[x, y, z] in project units or strings with units."}
_POINT2 = {"type": "array", "items": _LENGTH, "description": "[x, y] in project units or strings with units."}
_LEVEL = {"type": "string", "description": "Level name or GlobalId."}
_TERRAIN = {"type": "string", "description": "GlobalId of the terrain."}


def _points(session, points, name: str) -> list[list[float]]:
    out = []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 3:
            raise AgentError("bad_input", hint=f"{name} must be [x, y, z]")
        out.append(list(lengths(session, *p)))
    return out


def _pad_points(session, points) -> list[list[float]]:
    out = []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise AgentError("bad_input", hint="each pad point must be [x, y]")
        out.append(list(lengths(session, *p)))
    return out


def _options(session, name: str, spacing) -> str:
    options = {"name": name} if name else {}
    if spacing is not None:
        options["spacing"] = lengths(session, spacing)[0]
    return json.dumps(options)


@tool("terrain.create", {"required": ["level", "points"], "properties": {
    "level": _LEVEL,
    "points": {"type": "array", "items": _POINT, "description": "Survey points, at least three."},
    "name": {"type": "string", "description": "Terrain name (default \"Terrain\")."},
    "spacing": {**_LENGTH, "description": "Sample spacing kept in the property set (optional)."}}},
    writes=True)
def create(session, level, points, name="", spacing=None):
    """Create a terrain mesh from survey points ([x, y, z]) on a level, triangulated in plan."""
    storey = level_guid(level)
    r = bridge(T.create_terrain, storey, json.dumps(_points(session, points, "points")),
               _options(session, name, spacing))
    return {"guids": [r["guid"]], "triangles": r["triangles"], "bounds_m": r["bounds"]}


@tool("terrain.from_contours", {"required": ["level", "contours"], "properties": {
    "level": _LEVEL,
    "contours": {"type": "array", "items": {"type": "array", "items": _POINT},
                 "description": "Contour polylines, each at least two [x, y, z] points."},
    "name": {"type": "string", "description": "Terrain name (default \"Terrain\")."},
    "spacing": {**_LENGTH, "description": "Sample spacing along the contours (default 2 m)."}}},
    writes=True)
def from_contours(session, level, contours, name="", spacing="2m"):
    """Create a terrain mesh from contour polylines, sampled along each segment before triangulating."""
    storey = level_guid(level)
    sampled = [_points(session, contour, "each contour") for contour in contours]
    r = bridge(T.create_terrain_from_contours, storey, json.dumps(sampled),
               _options(session, name, spacing))
    return {"guids": [r["guid"]], "triangles": r["triangles"], "bounds_m": r["bounds"]}


@tool("terrain.pad", {"required": ["terrain", "points", "elevation"], "properties": {
    "terrain": _TERRAIN,
    "points": {"type": "array", "items": _POINT2,
               "description": "Closed pad outline, at least three [x, y] points."},
    "elevation": {**_LENGTH, "description": "Elevation to flatten the pad to."}}}, writes=True)
def pad(session, terrain, points, elevation):
    """Flatten the terrain vertices inside a closed outline to one elevation (a building pad)."""
    r = bridge(T.set_building_pad, terrain, json.dumps(_pad_points(session, points)),
               lengths(session, elevation)[0])
    return {"guid": r["guid"], "pads": r["pads"], "triangles": r["triangles"]}


@tool("terrain.pads", {"required": ["terrain"], "properties": {"terrain": _TERRAIN}})
def pads(session, terrain):
    """List a terrain's building pads: outline points and elevation."""
    return {"pads": bridge(T.list_building_pads, terrain)["pads"]}


@tool("terrain.clear_pads", {"required": ["terrain"], "properties": {"terrain": _TERRAIN}}, writes=True)
def clear_pads(session, terrain):
    """Remove a terrain's building pads and restore the surface kept before the first pad."""
    r = bridge(T.clear_building_pads, terrain)
    return {"guid": r["guid"], "pads": 0, "triangles": r["triangles"]}


@tool("terrain.list", {})
def list_terrains(session):
    """List the terrains: GlobalId, name, point count, triangle count and world bounds."""
    return {"terrains": bridge(T.list_terrains)["terrains"]}


@tool("terrain.delete", {"required": ["guid"], "properties": {
    "guid": {"type": "string", "description": "GlobalId of the terrain."}}}, writes=True)
def delete(session, guid):
    """Delete a terrain."""
    bridge(T.delete_terrain, guid)
    return {"removed": guid}
