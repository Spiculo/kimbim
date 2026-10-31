# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesh import tools (D102): read OBJ, STL and PLY files as one proxy element on a level. The path is a
local file; scale is a factor, rotation is degrees about Z and position is [x, y, z] in project units
or strings with units. The bridge takes world metres."""
from __future__ import annotations

import json

from ... import meshimport as M
from ..catalogue import AgentError, bridge, tool
from .common import lengths, level_guid

_NUMBER = {"type": "number", "description": "A number in the file's units."}


def _number(value, name: str) -> float:
    if isinstance(value, bool):
        raise AgentError("bad_input", hint=f"{name} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise AgentError("bad_input", hint=f"{name} must be a number") from None


@tool("import.formats", {})
def formats(session):
    """List the mesh file formats the importer reads (OBJ, STL and PLY)."""
    return {"formats": bridge(M.mesh_formats)["formats"]}


@tool("import.mesh", {"required": ["path"], "properties": {
    "path": {"type": "string", "description": "Path of the .obj, .stl or .ply file."},
    "level": {"type": "string", "description": "Level name or GlobalId (default the first level)."},
    "name": {"type": "string", "description": "Object name (default the file name)."},
    "scale": {**_NUMBER, "description": "Uniform scale factor (default 1)."},
    "rotation": {**_NUMBER, "description": "Rotation about Z, in degrees (default 0)."},
    "position": {"type": "array", "items": {"type": ["number", "string"]},
                 "description": "[x, y, z] in project units or strings with units (default the origin)."}}},
    writes=True)
def mesh(session, path, level="", name="", scale=1.0, rotation=0.0, position=None):
    """Import an OBJ, STL or PLY mesh as a proxy on a level, scaled, rotated about Z and moved."""
    storey = level_guid(level) if level else ""
    options = {"scale": _number(scale, "scale"), "rotation": _number(rotation, "rotation")}
    if name:
        options["name"] = str(name)
    if position is not None:
        if not isinstance(position, (list, tuple)) or len(position) != 3:
            raise AgentError("bad_input", hint="position must be [x, y, z]")
        options["x"], options["y"], options["z"] = lengths(session, *position)
    r = bridge(M.import_mesh, str(path), storey, json.dumps(options))
    return {"guids": [r["guid"]], "name": r["name"], "format": r["format"],
            "triangles": r["triangles"], "bounds_m": r["bounds"]}
