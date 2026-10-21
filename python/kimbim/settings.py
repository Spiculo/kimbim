# SPDX-License-Identifier: GPL-3.0-or-later
"""Project settings (step 2, D72): values that belong to the project, not the computer. They live in
the `.kim` / project folder and in every version's tree (settings.json), so going back to a version
brings back its settings. Unknown keys are kept, so an older KimBim never drops a newer one's settings.

Same protocol as app_bridge for the bridge functions (strings in, JSON out, never raise).
"""
from __future__ import annotations

import copy
import json

from . import app_bridge as B

DEFAULTS = {
    "plan_cut_height": 1.2,
    "plan_cut_levels": {},  # D91: per-level overrides of the plan slice (level guid -> metres)
    "view_depth": 0.5,  # D91: how far below a plan's level it still sees (Revit's view range)
    "view_depth_levels": {},  # D91: per-level overrides of the view depth (level guid -> metres)
    "hidden_layers": [],
    "locked_layers": [],
    "drawing_scale": 100,
    "scales": [500, 100, 50, 20],  # D93: the scales a drawing can be placed at; users add more
    "sheet_paper": "A1",
    "length_unit": "m",
    "length_decimals": 2,
    "area_unit": "m²",  # D92: how areas are shown (project setting)
    "level_reference": "project",  # D92: level dimensions from project zero, the level or sea level
    "north_arrow_style": "circle",  # D92: the plan north arrow's symbol
    "scale_bar_style": "bar",  # D92: the plan scale bar's symbol
    "sea_level": 0.0,  # D92: the project zero's elevation above sea level (m)
    "angle_decimals": 2,   # D92: decimals for angles in annotations
    "radius_decimals": 2,  # D92: decimals for radii and diameters
    "orphan_tags": "delete",  # D92: what a tag whose element is gone does: "delete" or "keep"
    "pen_sets": {},
    "line_types": {},
    "fill_patterns": {},  # D84: the project's fill patterns (empty: the built-ins)
    "element_styles": {},
    "visibility_sets": {},
    "override_sets": {},
    "layer_combinations": {},
    "purposes": {},
    "renovation_filters": {},
    "renovation_styles": {},  # D93: renovation look presets (pen, line, fill, colour) by status
    "renovation_preset": "Uruguay",  # D93: the active renovation-styles preset
    "legend_mode": "auto",  # D91: sheet legends: "auto" (all rules when they fit), "all" or "used"
    "plan_symbols": True,  # D91: plans show library objects' 2D plan symbol (else the 3D body)
    "purpose": "",
    "current_pen": 23,
    "sheet_purposes": {},
    "status_for_new": "new",
    "ifc_status_default": "existing",  # D91: the status offered for unmarked elements of an opened IFC
    "schedules": {},  # schedule schemes by id: the project's own and its edited built-ins (D77)
    "selection_criteria": {},
    "selection_sets": {},
    "ids_files": {},  # IDS files by name: their XML, kept in the project so it is versioned (D81)
    "clash_sets": {},  # clash detection sets by name (D81)
    "underlays": [],  # DXF, PDF and image underlays on levels: file, placement, display (D85)
    "sheet_files": [],  # D98: the picture files placed on sheets (so versions and .kim files keep them)
    "texture_files": [],  # D96: the surfaces' texture pictures (likewise)
    "tag_styles": {},  # tag styles by id: the project's own and its edited built-ins (D87)
    "stair_rules": {},  # building-code limits for stair and ramp warnings (D88; empty: the defaults)
    "check_tolerance": 0.002,   # D92: clash hard tolerance (m)
    "check_clearance": 0.05,    # D92: clash clearance (m)
    "check_ignore_joined": True,  # D92: walls joined to each other do not clash
    "check_partial_duplicates": False,  # D92: also flag elements that only partly overlap
    "imported_walls": "rebuild",  # D92: splitting an imported wall rebuilds it (default) or keeps its shape and cuts it
    "stair_riser": 0.175,  # D92: a new stair's target riser (m)
    "stair_tread": 0.28,  # D92: a new stair's tread when fixed (m)
    "stair_tread_mode": "fixed",  # D92: a new stair's tread is fixed or from 2 risers + tread = 625 mm
    "stair_arrow": "top",  # D92: the plan symbol's arrow: top (default), bottom or both
    "stair_riser_numbers": False,  # D92: number the risers on the plan
    "construction_grid": {"spacing": 1.0, "subdivisions": 4, "angle": 0.0, "origin": [0.0, 0.0]},  # D98
    "wall_reference_line": "Outside face",
    "layers_in_3d": True,
    "member_material_scope": "element",  # D97: a column's or beam's material: its own (Archicad) or its type's (Revit)
    "wall_profiles": {},
    "favourites": {},  # D97: Archicad's Favourites, by name: {tool, fields {object name: value}, object?}  # D97: complex wall sections by name: [[across, up], ...] metres from the base line  # D96: walls and slabs show each layer on their ends and tops in 3D  # D97: where a new wall's clicked line is (Archicad default)
}
UNITS = {"m": 1.0, "cm": 100.0, "mm": 1000.0}
AREA_UNITS = {"m²": 1.0, "cm²": 10000.0, "mm²": 1000000.0}

_current: dict = copy.deepcopy(DEFAULTS)
_saved: dict = copy.deepcopy(DEFAULTS)
kept = False  # set by documents: the settings are saved with the open document (.kim or folder)


def current() -> dict:
    return copy.deepcopy(_current)


def load(data: dict | None, dirty: bool = False) -> None:
    """The open document's settings (defaults filled in). `dirty`: they differ from what is saved."""
    global _current, _saved
    _current = {**copy.deepcopy(DEFAULTS), **copy.deepcopy(data or {})}
    if not dirty:
        _saved = copy.deepcopy(_current)


def mark_saved() -> None:
    global _saved
    _saved = copy.deepcopy(_current)


def restore(data: dict) -> None:
    """Put back a snapshot of `current()` (D92: undo/redo of a settings-only step, e.g. an underlay
    edit). `_saved` is left alone, so the dirty state follows."""
    global _current
    _current = copy.deepcopy(data)


def is_dirty() -> bool:
    return _current != _saved


def to_bytes(d: dict | None = None) -> bytes:
    return (json.dumps(_current if d is None else d, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def from_bytes(b: bytes | None) -> dict:
    try:
        data = json.loads(b) if b else {}
    except ValueError:
        data = {}
    return {**copy.deepcopy(DEFAULTS), **(data if isinstance(data, dict) else {})}


def changed_keys(a: dict, b: dict) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def merge(base: dict, ours: dict, theirs: dict) -> tuple[dict, list[str]]:
    """Key by key against the common version: a key changed on one side takes that side; changed
    differently on both, ours wins and the key is reported."""
    merged, conflicts = {}, []
    for k in sorted(set(base) | set(ours) | set(theirs)):
        b, o, t = base.get(k), ours.get(k), theirs.get(k)
        if k == "underlays" and o != t:  # D85: underlay by underlay, so two options can each add one
            from .underlays import merge_entries

            value, clash = merge_entries(b or [], o or [], t or [])
            merged[k] = value
            if clash:
                conflicts.append(k)
            continue
        if o == t or t == b:
            value = o
        elif o == b:
            value = t
        else:
            value = o
            conflicts.append(k)
        if value is not None:
            merged[k] = value
    return merged, conflicts


def _error(key: str, value) -> str | None:
    from .sheets import PAPERS

    number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if key == "plan_cut_height" and not (number and 0 < value <= 20):
        return "the plan cut height must be between 0 and 20 m"
    if key == "view_depth" and not (number and 0 <= value <= 20):
        return "the view depth below must be between 0 and 20 m"
    if key == "view_depth_levels" and not (isinstance(value, dict) and all(
            isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 20
            for k, v in value.items())):
        return "the per-level view depths must be numbers between 0 and 20 m"
    if key == "plan_cut_levels" and not (isinstance(value, dict) and all(
            isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v <= 20
            for k, v in value.items())):
        return "the per-level plan cut heights must be numbers between 0 and 20 m"
    if key == "drawing_scale" and not (isinstance(value, int) and not isinstance(value, bool) and value > 0):
        return "the drawing scale must be a whole number above 0"
    if key == "scales" and not (isinstance(value, list) and value and all(
            isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in value)):
        return "the scales must be a non-empty list of whole numbers above 0"
    if key == "sheet_paper" and value not in PAPERS:
        return f"unknown paper size {value}"
    if key == "length_unit" and value not in UNITS:
        return f"unknown length unit {value}"
    if key == "area_unit" and value not in AREA_UNITS:
        return f"unknown area unit {value}"
    if key == "level_reference" and value not in ("project", "level", "sea"):
        return f"unknown level dimension reference {value}"
    if key == "north_arrow_style" and value not in ("circle", "needle", "arrow"):
        return f"unknown north arrow style {value}"
    if key == "scale_bar_style" and value not in ("bar", "line"):
        return f"unknown scale bar style {value}"
    if key == "sea_level" and not (number and -10000 <= value <= 10000):
        return "the sea level must be between -10000 and 10000 m"
    if key in ("angle_decimals", "radius_decimals") and not (isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 4):
        return f"{key} must be between 0 and 4"
    if key == "orphan_tags" and value not in ("delete", "keep"):
        return f"unknown orphan tag choice {value}"
    if key == "length_decimals" and not (isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 4):
        return "decimals must be between 0 and 4"
    if key in ("hidden_layers", "locked_layers") and not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
        return f"{key} must be a list of layer names"
    if key == "status_for_new" and value not in ("existing", "demolish", "new", "temporary", "auxiliary"):
        return f"unknown renovation status {value}"
    if key == "ifc_status_default" and value not in ("existing", "demolish", "leave"):
        return f"unknown default for unmarked elements {value}"
    if key == "renovation_preset" and not isinstance(value, str):
        return "the renovation style preset is a name"
    if key == "legend_mode" and value not in ("auto", "all", "used"):
        return f"unknown legend mode {value}"
    if key == "plan_symbols" and not isinstance(value, bool):
        return "plan symbols is true or false"
    if key == "schedules":  # schedule schemes by id (D77)
        from .schedules import table_error

        return table_error(value)
    if key == "tag_styles":  # D87
        from .tags import table_error as tag_table_error

        return tag_table_error(value)
    if key in ("selection_criteria", "selection_sets"):
        from . import queries

        return queries.validate(key, value)
    if key == "underlays":
        from . import underlays

        return underlays.validate(value)
    if key in ("sheet_files", "texture_files") and not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
        return f"{key} is a list of file names"
    if key == "stair_rules":
        from . import stairs

        return stairs.validate_rules(value)
    if key in ("check_tolerance", "check_clearance") and not (number and 0 <= value <= 10):
        return f"{key} must be between 0 and 10 m"
    if key == "check_ignore_joined" and not isinstance(value, bool):
        return "check_ignore_joined must be true or false"
    if key == "check_partial_duplicates" and not isinstance(value, bool):
        return "check_partial_duplicates must be true or false"
    if key == "imported_walls" and value not in ("rebuild", "keep"):
        return f"unknown imported wall choice {value}"
    if key == "stair_riser" and not (number and 0.05 <= value <= 0.5):
        return "the stair riser target must be between 0.05 and 0.5 m"
    if key == "stair_tread" and not (number and 0.05 <= value <= 1.0):
        return "the stair tread must be between 0.05 and 1.0 m"
    if key == "stair_tread_mode" and value not in ("fixed", "blondel"):
        return f"unknown stair tread mode {value}"
    if key == "stair_arrow" and value not in ("top", "bottom", "both"):
        return f"unknown stair arrow position {value}"
    if key == "stair_riser_numbers" and not isinstance(value, bool):
        return "stair_riser_numbers must be true or false"
    if key == "construction_grid":
        g = value if isinstance(value, dict) else {}

        def num(v):
            return isinstance(v, (int, float)) and not isinstance(v, bool)

        if not (num(g.get("spacing")) and 0.001 <= g["spacing"] <= 10000):
            return "the grid spacing must be between 0.001 and 10000 m"
        if not (isinstance(g.get("subdivisions"), int) and not isinstance(g.get("subdivisions"), bool)
                and 1 <= g["subdivisions"] <= 100):
            return "the grid subdivisions must be 1-100"
        if not num(g.get("angle")):
            return "the grid angle is a number of degrees"
        o = g.get("origin")
        if not (isinstance(o, list) and len(o) == 2 and all(num(v) for v in o)):
            return "the grid origin is [x, y]"
    if key == "favourites":
        if not isinstance(value, dict) or not all(
                isinstance(k, str) and k.strip() and isinstance(v, dict) and isinstance(v.get("tool"), str)
                and isinstance(v.get("fields", {}), dict) for k, v in value.items()):
            return "favourites are a table by name of {tool, fields}"
        return None
    if key == "wall_profiles":
        from . import configure

        return configure.profiles_error(value)
    if key == "member_material_scope" and value not in ("element", "type"):
        return "member_material_scope must be element or type"
    if key == "layers_in_3d" and not isinstance(value, bool):
        return "layers_in_3d must be true or false"
    if key == "wall_reference_line":
        from . import configure

        if value not in configure.REFERENCES:
            return f"unknown wall reference line {value}"
    if key in ("ids_files", "clash_sets"):
        from . import checks

        return checks.validate(key, value)
    from . import graphics

    if key in graphics.TABLES or key in ("purpose", "current_pen", "sheet_purposes"):
        return graphics.validate(key, value)
    return None


def format_length(metres: float, unit: bool = True, decimals: int | None = None) -> str:
    u = _current.get("length_unit", "m")
    d = int(_current.get("length_decimals", 2)) if decimals is None else int(decimals)
    text = f"{metres * UNITS.get(u, 1.0):.{d}f}"
    return f"{text} {u}" if unit else text


def format_area(square_metres: float, unit: bool = True) -> str:
    """An area in the project's area unit (D92), like format_length for lengths."""
    u = _current.get("area_unit", "m²")
    text = f"{square_metres * AREA_UNITS.get(u, 1.0):.{int(_current.get('length_decimals', 2))}f}"
    return f"{text} {u}" if unit else text


# ---------------------------------------------------------------- bridge

def project_settings() -> str:
    from .documents import state_fields

    return B._dump({"ok": True, "settings": current(), "defaults": copy.deepcopy(DEFAULTS),
                    "kept": state_fields()["kept"]})


def set_project_settings(changes_json: str) -> str:
    global _current
    try:
        changes = json.loads(changes_json)
    except ValueError as ex:
        return B._dump({"ok": False, "error": f"bad input: {ex}"})
    if not isinstance(changes, dict):
        return B._dump({"ok": False, "error": "bad input: expected an object"})
    for k, v in changes.items():
        if (err := _error(k, v)) is not None:
            return B._dump({"ok": False, "error": err})
    _current = {**_current, **copy.deepcopy(changes)}
    if {"stair_arrow", "stair_riser_numbers"} & set(changes):  # D92: stairs keep their plan data current
        from . import stairs

        stairs.refresh_plan_settings()
    return B._dump({"ok": True, "settings": current(), "dirty": B._dirty()})
