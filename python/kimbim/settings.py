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
    "hidden_layers": [],
    "locked_layers": [],
    "drawing_scale": 100,
    "sheet_paper": "A1",
    "length_unit": "m",
    "length_decimals": 2,
    "area_unit": "m²",  # D92: how areas are shown (project setting)
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
    "purpose": "",
    "current_pen": 23,
    "sheet_purposes": {},
    "status_for_new": "new",
    "schedules": {},  # schedule schemes by id: the project's own and its edited built-ins (D77)
    "selection_criteria": {},
    "selection_sets": {},
    "ids_files": {},  # IDS files by name: their XML, kept in the project so it is versioned (D81)
    "clash_sets": {},  # clash detection sets by name (D81)
    "underlays": [],  # DXF, PDF and image underlays on levels: file, placement, display (D85)
    "tag_styles": {},  # tag styles by id: the project's own and its edited built-ins (D87)
    "stair_rules": {},  # building-code limits for stair and ramp warnings (D88; empty: the defaults)
    "check_tolerance": 0.002,   # D92: clash hard tolerance (m)
    "check_clearance": 0.05,    # D92: clash clearance (m)
    "check_ignore_joined": True,  # D92: walls joined to each other do not clash
    "check_partial_duplicates": False,  # D92: also flag elements that only partly overlap
    "imported_walls": "rebuild",  # D92: splitting an imported wall rebuilds it (default) or keeps its shape and cuts it
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
    if key == "drawing_scale" and not (isinstance(value, int) and not isinstance(value, bool) and value > 0):
        return "the drawing scale must be a whole number above 0"
    if key == "sheet_paper" and value not in PAPERS:
        return f"unknown paper size {value}"
    if key == "length_unit" and value not in UNITS:
        return f"unknown length unit {value}"
    if key == "area_unit" and value not in AREA_UNITS:
        return f"unknown area unit {value}"
    if key in ("angle_decimals", "radius_decimals") and not (isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 4):
        return f"{key} must be between 0 and 4"
    if key == "orphan_tags" and value not in ("delete", "keep"):
        return f"unknown orphan tag choice {value}"
    if key == "length_decimals" and not (isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 4):
        return "decimals must be between 0 and 4"
    if key in ("hidden_layers", "locked_layers") and not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
        return f"{key} must be a list of layer names"
    if key == "status_for_new" and value not in ("existing", "demolish", "new"):
        return f"unknown renovation status {value}"
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
    return B._dump({"ok": True, "settings": current(), "dirty": B._dirty()})
