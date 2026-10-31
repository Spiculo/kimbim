# SPDX-License-Identifier: GPL-3.0-or-later
"""Export tools (D102): write the model as an IFC file with a scope and property mapping. The export
writes a file, not the model, so it is not a write tool."""
from __future__ import annotations

import json

from ... import ifcexport as E
from ..catalogue import bridge, tool

_PATH = {"type": "string", "description": "Path of the IFC file to write."}
_OPTIONS = {"type": ["object", "string"],
            "description": "Export options: scope (all, selection, level, class), guids, levels, classes, "
                           "include_annotations, include_spaces, include_openings, property_map. "
                           "export.options lists the model's classes and levels."}


def _json(options) -> str:
    return options if isinstance(options, str) else json.dumps(options or {})


@tool("export.options", {})
def options(session):
    """List what an IFC export can include: scopes, product classes with counts, levels and defaults."""
    r = bridge(E.export_options)
    return {k: r[k] for k in ("scopes", "classes", "levels", "defaults")}


@tool("export.ifc", {"required": ["path"], "properties": {"path": _PATH, "options": _OPTIONS}})
def ifc(session, path, options=None):
    """Export the model as an IFC file. Scope all (default), selection (GlobalIds), level or class;
    optionally drop annotations, spaces or openings and rename properties through property_map."""
    r = bridge(E.export_ifc, path, _json(options))
    return {k: r[k] for k in ("path", "products", "removed", "classes", "bytes")}
