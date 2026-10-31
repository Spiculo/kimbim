# SPDX-License-Identifier: GPL-3.0-or-later
"""Attribute manager tools (D102): move an office's standards between projects as one JSON file.

Catalogue and export only read the project (the export writes a file, not the model); import changes
the settings and the IFC entities, so it is a write tool.
"""
from __future__ import annotations

import json

from ... import attributes as A
from ..catalogue import bridge, tool

_PATH = {"type": "string", "description": "Path of the attribute file (kimbim-attributes/1 JSON)."}
_OPTIONS = {"type": ["object", "string"],
            "description": "Import options: groups (pens, line_types, fill_patterns, element_styles, "
                           "visibility_sets, graphic_overrides, layer_combinations, purposes, "
                           "renovation_filters, renovation_styles, layers, materials, surfaces, composites; "
                           "default all) and replace (false: keep what the project already has)."}


def _json(options) -> str:
    return options if isinstance(options, str) else json.dumps(options or {})


@tool("attributes.catalogue", {})
def catalogue(session):
    """List the project's attribute groups with their counts, and its layers, materials, surfaces and
    composites, so an attribute file can be exported or imported with the right groups selected."""
    return bridge(A.attribute_catalogue)


@tool("attributes.export", {"required": ["path"], "properties": {"path": _PATH}})
def export(session, path):
    """Write the project's pens, line types, fill patterns, element styles, visibility and override sets,
    layer combinations, purposes, renovation styles, layers, materials, surfaces and composites to one
    self-contained JSON file, to carry the office's standards to another project."""
    r = bridge(A.export_attributes, path)
    return {k: r[k] for k in ("path", "format", "counts")}


@tool("attributes.import", {"required": ["path"], "properties": {"path": _PATH, "options": _OPTIONS}}, writes=True)
def import_file(session, path, options=None):
    """Import an attribute file into the open project: settings tables merge by name, IFC layers,
    materials, surfaces and composites are created where missing (or updated with replace). Returns the
    counts imported and what was skipped."""
    r = bridge(A.import_attributes, path, _json(options))
    return {k: r[k] for k in ("imported", "skipped", "settings", "dirty")}
