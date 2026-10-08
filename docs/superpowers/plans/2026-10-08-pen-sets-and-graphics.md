# Pen sets, line types, visibility and purposes: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Archicad-style pen sets, line types, element styles, visibility sets, override rules, layer combinations and purposes, applied to the 3D view, plan tabs, drawings, sheets and PDF, switched from one drop-down in the bottom bar.

**Architecture:**
- **Python** (`graphics.py`) owns the tables:
  - the built-ins, validation and element kinds;
  - rule matching and resolution into `{styles, elements → style, hidden}`, cached per model state and
    settings;
  - styling of drawing SVGs, which is a cheap step separate from the hidden-line pass.
- **C++** (`Graphics`) parses the resolved state and restyles OCCT batches, poché and annotations.
- **Editors** are Qt dialogs that write validated tables through `set_graphics`.
- Everything lives in the project settings (D72): versioned, merged, carried by templates.

**Tech stack:**
- Python 3.12 with ifcopenshell 0.9.0, for the tables and resolution;
- IfcOpenShell's SVG serializer with `svg-segment-projection` and `svg-no-css`, for drawings;
- C++ Qt 6 with OCCT and Graphic3d line aspects, for the app;
- pixi tasks to build and test.

**Spec:** `docs/superpowers/specs/2026-10-08-pen-sets-and-graphics-design.md`

## Global constraints

- Bridge protocol: strings in, JSON out, never raise (`B._dump`, `{"ok": false, "error": ...}`).
- Pens are numbered 1–255. Colours are `#rrggbb`. Weights are mm on paper, 0.05–5.0. Missing pen
  fallback: black, 0.18.
- Line types are dash/gap lists in mm on paper, even count, values > 0; `[]` is solid; "Solid" is
  always present.
- Element kinds, in this order: walls, columns, beams, slabs, roofs, stairs, railings, doors, windows,
  coverings, furniture, plumbing, hvac, electrical, structure_other, rooms, annotations, grids, other.
- Settings keys: `pen_sets`, `line_types`, `element_styles`, `visibility_sets`, `override_sets`,
  `layer_combinations`, `purposes`, `purpose`, `current_pen`, `sheet_purposes`. An empty table means
  the built-ins.
- On-screen weights: 1 px; with True line weights, `clamp(round(weight_mm × 4), 1, 6)` px.
- Compare colours win over graphics surfaces.
- Hidden by visibility is separate from H/I and from layers: Show all doesn't reveal it, and it isn't
  selectable.
- A 0.50 mm pen prints 0.50 mm at any sheet scale (weights and dashes ÷ k, where k = 100 / scale).
- UI strings in English with Spanish in `kimcad_es.ts` (`pixi run check-translations` must pass), and
  an SPDX header on new files (`pixi run check-spdx`).
- Tests: `pixi run test` (Python), `pixi run app-test` (C++). A single C++ test runs with
  `KIMCAD_PYTHON_PATH=$PWD/python pixi run build/app/<test>.exe <fn> -o out.txt,txt`.

## Review focus

1. **IFC2X3 files** (the Clinic). The Fire rating and LoadBearing rules read properties from type
   objects and IFC2X3 psets, and must not crash on elements without psets. Tests:
   `test_rules_read_type_properties` and `test_resolve_ifc2x3_flow_by_type` (Task 2).
2. **A stale or hand-edited settings file**: unknown pen numbers, a purpose naming a deleted set, a
   line type missing. Display must fall back, never fail. Test: `test_resolve_falls_back_on_missing_names`
   (Task 2).
3. **Sheets at 1:50 and 1:200.** Printed weights must stay the pen weight. Test:
   `test_sheet_weights_do_not_scale` (Task 4).
4. **Editing after switching purpose.** New elements must get the purpose's style, not a default.
   Test: `newElementsGetThePurposeStyle` (Task 8).
5. **Deleting the pen set or visibility set the current purpose uses.** The purpose falls back, and the
   editor refuses deleting the last one. Tests: `test_set_graphics_refuses_removing_the_last_set`
   (Task 3) and the fallback test above.

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `python/kimcad/graphics.py` | new | Built-ins, `effective`, `validate`, `kind_of`, `matches`, `resolve`, `style_svg`, bridge functions |
| `python/kimcad/settings.py` | modify | DEFAULTS for the new keys; `_error` delegates to `graphics.validate` |
| `python/kimcad/app_bridge.py` | modify | Re-export graphics bridge functions; `set_annotation_pen` |
| `python/kimcad/drawgen.py` | modify | `svg-segment-projection`, `svg-no-css`, overlay tagging |
| `python/kimcad/drawings.py` | modify | `generate_drawing` styles (k = 1) and excludes graphics-hidden elements |
| `python/kimcad/sheets.py` | modify | `sheet_svg` styles each view with k = 100 / scale and the sheet's purpose; `set_sheet_purpose` |
| `python/kimcad/annotations.py` | modify | `Pen` on annotations; `current_pen` for new ones; `set_annotation_pen` |
| `tests/python/test_graphics.py` | new | Tables, validation, kinds, rules, resolve, style_svg, bridge |
| `tests/python/test_drawings.py`, `test_sheets.py`, `test_annotations.py` | modify | Styled drawings, sheet weights, annotation pens |
| `app/src/Graphics.{h,cpp}` | new | Parsed resolved state; line widths, patterns |
| `app/src/ElementBatch.{h,cpp}` | modify | Per-element line style, surface, graphics-hidden; grouped line arrays |
| `app/src/Scene.h`, `Viewport.{h,cpp}` | modify | `setGraphics`, poché per fill, annotation pens |
| `app/src/PenGrid.{h,cpp}` | new | 16×16 swatch grid widget and popup |
| `app/src/StatusStrip.{h,cpp}` | modify | Live pen button, purpose drop-down, graphics popup |
| `app/src/GraphicsDialogs.{h,cpp}` | new | Seven editors |
| `app/src/MainWindow.{h,cpp}`, `SheetsPanel.{h,cpp}`, `Preferences.{h,cpp}` | modify | Graphics menu, refresh, True line weights, views and sheet purpose |
| `app/tests/test_graphics.cpp` | new | Graphics parsing; PenGrid; editors |
| `app/tests/test_element_batch.cpp`, `test_main_window.cpp` | modify | Batch styles; end-to-end behaviour |
| `docs/…` | modify | D73, docs 04/13/14/11, translations |

---

### Task 1: Graphics tables, built-ins and validation (Python)

**Files:**
- Create: `python/kimcad/graphics.py`
- Modify: `python/kimcad/settings.py:15-24` (DEFAULTS), `:87-105` (`_error`)
- Test: `tests/python/test_graphics.py`

**Interfaces:**
- Produces:
  - `KINDS: tuple[str, ...]`, `TABLES: tuple[str, ...]` (the seven table keys), `OPS`;
  - `builtin(key) -> dict`;
  - `effective(key, settings=None) -> dict` (stored table, or built-ins when empty);
  - `validate(key, value) -> str | None`;
  - `pen(pens: dict, n) -> {"color", "weight"}`, `dash(line_types, name) -> list[float]`;
  - `current_purpose(settings=None) -> str`.
- Settings DEFAULTS gains `line_types: {}`, `element_styles: {}`, `visibility_sets: {}`,
  `override_sets: {}`, `layer_combinations: {}`, `purposes: {}`, `purpose: ""`, `current_pen: 23`,
  `sheet_purposes: {}` (`pen_sets: {}` exists).

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 3 (D73): pen sets, line types, element styles, visibility, overrides, purposes."""
import json

import pytest

from kimcad import app_bridge as b
from kimcad import graphics as g
from kimcad import settings as s


def setup_function():
    s.load(None)


def test_builtins_are_complete_and_valid():
    for key in g.TABLES:
        table = g.builtin(key)
        assert table, key
        assert g.validate(key, table) is None, (key, g.validate(key, table))
    pens = g.builtin("pen_sets")
    assert set(pens) == {"Working", "Permit", "Presentation", "Highlight", "Demo"}
    for name, pen_set in pens.items():
        assert set(pen_set["pens"]) == {str(n) for n in range(1, 256)}, name
    assert g.builtin("pen_sets")["Permit"]["pens"]["10"] == {"color": "#000000", "weight": 0.5, "name": "Walls cut"}
    assert set(g.builtin("element_styles")) == set(g.KINDS)
    assert g.builtin("line_types")["Solid"] == []
    assert set(g.builtin("purposes")) == {"Working", "Highlight", "Permit", "Presentation", "Demo"}


def test_effective_is_the_stored_table_or_the_builtins():
    assert g.effective("line_types") == g.builtin("line_types")
    s.load({"line_types": {"Solid": [], "Long": [10.0, 2.0]}})
    assert g.effective("line_types") == {"Solid": [], "Long": [10.0, 2.0]}
    assert g.current_purpose() == "Working"
    s.load({"purpose": "Permit"})
    assert g.current_purpose() == "Permit"
    s.load({"purpose": "Gone"})
    assert g.current_purpose() == "Working"  # falls back to the first purpose


@pytest.mark.parametrize("key,value,message", [
    ("pen_sets", {"A": {"pens": {"300": {"color": "#000000", "weight": 0.2}}}}, "pen 300 is out of range (1-255)"),
    ("pen_sets", {"A": {"pens": {"1": {"color": "red", "weight": 0.2}}}}, "pen 1: colour must be #rrggbb"),
    ("pen_sets", {"A": {"pens": {"1": {"color": "#000000", "weight": 9}}}}, "pen 1: weight must be 0.05-5 mm"),
    ("pen_sets", {"": {"pens": {}}}, "a name can't be empty"),
    ("line_types", {"Solid": [], "Bad": [1.0]}, "line type Bad: dashes and gaps come in pairs"),
    ("line_types", {"Solid": [], "Bad": [1.0, -1.0]}, "line type Bad: lengths must be above 0"),
    ("line_types", {"Dashed": [1.0, 1.0]}, "the Solid line type can't be removed"),
    ("element_styles", {"towers": {"cut": {"pen": 1, "line": "Solid"}, "projection": {"pen": 1, "line": "Solid"}, "fill": 1}}, "unknown element kind towers"),
    ("visibility_sets", {"A": {"hidden_kinds": ["towers"], "rules": []}}, "unknown element kind towers"),
    ("override_sets", {"A": {"rules": [{"name": "r", "when": {"colour": "x"}, "then": {}}]}}, "rule r: unknown condition colour"),
    ("override_sets", {"A": {"rules": [{"name": "r", "when": {"property": "X", "op": "near"}, "then": {}}]}}, "rule r: unknown operator near"),
    ("override_sets", {"A": {"rules": [{"name": "r", "when": {}, "then": {"transparency": 2}}]}}, "rule r: transparency must be 0-1"),
    ("purposes", {"A": {"pen_set": "Working", "visibility": "Everything", "overrides": "None", "layers": 3}}, "purpose A: layers must be a name or null"),
    ("current_pen", 0, "the current pen must be 1-255"),
    ("sheet_purposes", {"A01": 3}, "sheet purposes must map sheet numbers to purpose names"),
])
def test_validation_refuses_bad_tables(key, value, message):
    assert g.validate(key, value) == message


def test_empty_tables_mean_builtins_and_are_valid():
    for key in g.TABLES:
        assert g.validate(key, {}) is None


def test_settings_refuse_bad_graphics_through_the_bridge():
    r = json.loads(s.set_project_settings(json.dumps({"current_pen": 300})))
    assert not r["ok"] and r["error"] == "the current pen must be 1-255"
    r = json.loads(s.set_project_settings(json.dumps({"current_pen": 5})))
    assert r["ok"] and r["settings"]["current_pen"] == 5


def test_pen_and_dash_fall_back():
    pens = g.builtin("pen_sets")["Working"]["pens"]
    assert g.pen(pens, 10)["weight"] == 0.5
    assert g.pen({}, 10) == {"color": "#000000", "weight": 0.18}
    assert g.pen(pens, "x") == {"color": "#000000", "weight": 0.18}
    assert g.dash(g.builtin("line_types"), "Dashed") == [3.0, 1.5]
    assert g.dash(g.builtin("line_types"), "Missing") == []
```

- [ ] **Step 2: Run them to watch them fail**

Run: `pixi run pytest tests/python/test_graphics.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'kimcad.graphics'`, or ImportError).

- [ ] **Step 3: Write `graphics.py` (tables part)**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pen sets, line types, element styles, visibility, overrides, layer combinations and purposes
(step 3, D73). The tables live in the project settings (D72); an empty table means the built-ins.
Same protocol as app_bridge for the bridge functions (strings in, JSON out, never raise).
"""
from __future__ import annotations

import colorsys
import copy
import re

KINDS = ("walls", "columns", "beams", "slabs", "roofs", "stairs", "railings", "doors", "windows",
         "coverings", "furniture", "plumbing", "hvac", "electrical", "structure_other", "rooms",
         "annotations", "grids", "other")
TABLES = ("pen_sets", "line_types", "element_styles", "visibility_sets", "override_sets",
          "layer_combinations", "purposes")
OPS = ("equals", "not_equals", "contains", "exists", "missing", "true", "false", "less", "more")
WHEN = ("kind", "ifc_class", "property", "op", "value", "layer", "material")
THEN = ("pen", "cut_pen", "projection_pen", "line", "fill", "surface", "transparency", "hide")
FALLBACK_PEN = {"color": "#000000", "weight": 0.18}
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

# Pen roles (the same numbers in every set, so switching the set restyles everything).
_ROLES = {10: "Walls cut", 11: "Walls projection", 12: "Walls fill", 13: "Structure cut",
          14: "Structure projection", 15: "Structure fill", 16: "Doors and windows",
          17: "Stairs and railings", 18: "Furniture", 19: "Plumbing", 20: "HVAC", 21: "Electrical",
          22: "Rooms", 23: "Annotations", 24: "Grids", 25: "Other", 26: "Highlight",
          27: "Highlight 2", 28: "Highlight 3"}
_GENERIC = {1: 0.13, 2: 0.18, 3: 0.25, 4: 0.35, 5: 0.50, 6: 0.70, 7: 1.00}
_HIGHLIGHT = {26: ("#e02020", 0.5), 27: ("#2050e0", 0.5), 28: ("#f08010", 0.5)}
_SETS = {  # pen: (colour, weight) for pens 10-25 (fills use the weight only nominally)
    "Working": {10: ("#5a3a22", .5), 11: ("#8a6a4a", .18), 12: ("#b8a898", .18), 13: ("#1f3f7a", .5),
                14: ("#4a6aa8", .18), 15: ("#9aa8c0", .18), 16: ("#2e6b3a", .25), 17: ("#6a3a8a", .18),
                18: ("#7a7a2a", .13), 19: ("#1a9aaa", .18), 20: ("#d07a1a", .18), 21: ("#b02a9a", .18),
                22: ("#3a9a5a", .13), 23: ("#000000", .18), 24: ("#c03030", .13), 25: ("#707070", .18)},
    "Permit": {10: ("#000000", .5), 11: ("#000000", .18), 12: ("#404040", .18), 13: ("#000000", .5),
               14: ("#000000", .18), 15: ("#404040", .18), 16: ("#000000", .25), 17: ("#000000", .18),
               18: ("#000000", .13), 19: ("#000000", .18), 20: ("#000000", .18), 21: ("#000000", .18),
               22: ("#000000", .13), 23: ("#000000", .18), 24: ("#000000", .13), 25: ("#000000", .18)},
    "Presentation": {10: ("#000000", .5), 11: ("#555555", .18), 12: ("#808080", .18), 13: ("#000000", .5),
                     14: ("#555555", .18), 15: ("#808080", .18), 16: ("#555555", .18), 17: ("#555555", .18),
                     18: ("#999999", .13), 19: ("#888888", .13), 20: ("#888888", .13), 21: ("#888888", .13),
                     22: ("#888888", .13), 23: ("#000000", .18), 24: ("#888888", .13), 25: ("#555555", .18)},
    "Highlight": {10: ("#909090", .25), 11: ("#c0c0c0", .13), 12: ("#d8d8d8", .13), 13: ("#909090", .25),
                  14: ("#c0c0c0", .13), 15: ("#d8d8d8", .13), 16: ("#c0c0c0", .13), 17: ("#c0c0c0", .13),
                  18: ("#c0c0c0", .13), 19: ("#c0c0c0", .13), 20: ("#c0c0c0", .13), 21: ("#c0c0c0", .13),
                  22: ("#c0c0c0", .13), 23: ("#808080", .18), 24: ("#c0c0c0", .13), 25: ("#c0c0c0", .13)},
    "Demo": {10: ("#8a1010", .5), 11: ("#c03030", .18), 12: ("#d09090", .18), 13: ("#1030a0", .5),
             14: ("#3060d0", .18), 15: ("#90a0d0", .18), 16: ("#108030", .25), 17: ("#7020a0", .25),
             18: ("#808000", .18), 19: ("#00a0b0", .25), 20: ("#e07000", .25), 21: ("#c000a0", .25),
             22: ("#20a040", .13), 23: ("#000000", .18), 24: ("#d02020", .13), 25: ("#606060", .18)},
}


def _hex(r: float, g: float, b: float) -> str:
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def _pen_set(roles: dict) -> dict:
    pens = {}
    for n in range(1, 256):
        if n in _GENERIC:
            pen = {"color": "#000000", "weight": _GENERIC[n]}
        elif n in roles:
            pen = {"color": roles[n][0], "weight": roles[n][1]}
        elif n in _HIGHLIGHT:
            pen = {"color": _HIGHLIGHT[n][0], "weight": _HIGHLIGHT[n][1]}
        elif n >= 30:
            i = n - 30  # a 16-wide colour ramp, darker row by row
            pen = {"color": _hex(*colorsys.hsv_to_rgb((i % 16) / 16, 0.7, 1.0 - (i // 16) * 0.06)), "weight": 0.18}
        else:
            pen = {"color": "#808080", "weight": 0.18}
        if n in _ROLES:
            pen["name"] = _ROLES[n]
        pens[str(n)] = pen
    return {"pens": pens}


def _style(cut, proj, fill, line="Solid", proj_line=None) -> dict:
    return {"cut": {"pen": cut, "line": line}, "projection": {"pen": proj, "line": proj_line or line}, "fill": fill}


_STYLES = {
    "walls": _style(10, 11, 12), "columns": _style(13, 14, 15), "beams": _style(13, 14, 15),
    "slabs": _style(13, 14, 15), "roofs": _style(13, 14, 15), "structure_other": _style(13, 14, 15),
    "stairs": _style(17, 17, 12), "railings": _style(17, 17, 12), "doors": _style(16, 16, 12),
    "windows": _style(16, 16, 12), "coverings": _style(25, 25, 12), "furniture": _style(18, 18, 12),
    "plumbing": _style(19, 19, 12), "hvac": _style(20, 20, 12), "electrical": _style(21, 21, 12),
    "rooms": _style(22, 22, 12, "Dotted"), "annotations": _style(23, 23, 12), "grids": _style(24, 24, 12, "Centre"),
    "other": _style(25, 25, 12),
}
_NOT_STRUCTURE = ["doors", "windows", "furniture", "plumbing", "hvac", "electrical", "coverings", "railings", "rooms"]
_BUILTINS = {
    "pen_sets": {name: _pen_set(roles) for name, roles in _SETS.items()},
    "line_types": {"Solid": [], "Dashed": [3.0, 1.5], "Dotted": [0.3, 1.0], "Dash-dot": [4.0, 1.0, 0.5, 1.0],
                   "Centre": [8.0, 1.5, 1.5, 1.5], "Hidden": [1.5, 1.0]},
    "element_styles": _STYLES,
    "visibility_sets": {
        "Everything": {"hidden_kinds": [], "rules": []},
        "Architectural": {"hidden_kinds": ["plumbing", "hvac", "electrical"], "rules": []},
        "No furniture": {"hidden_kinds": ["furniture"], "rules": []},
        "Structure only": {"hidden_kinds": _NOT_STRUCTURE, "rules": [
            {"name": "Not load-bearing", "when": {"property": "LoadBearing", "op": "false"}, "then": {"hide": True}}]},
    },
    "override_sets": {
        "None": {"rules": []},
        "Fire rating": {"rules": [
            {"name": f"{m} min", "when": {"property": "FireRating", "op": "contains", "value": m},
             "then": {"pen": pen, "surface": surface}}
            for m, pen, surface in (("120", 26, "#b01010"), ("90", 26, "#e05040"), ("60", 27, "#4070e0"),
                                    ("30", 28, "#f0a030"))]},
        "Load-bearing walls": {"rules": [
            {"name": "Load-bearing", "when": {"kind": "walls", "property": "LoadBearing", "op": "true"},
             "then": {"pen": 26, "surface": "#e05040"}}]},
        "External walls": {"rules": [
            {"name": "External", "when": {"kind": "walls", "property": "IsExternal", "op": "true"},
             "then": {"pen": 27, "surface": "#5080e0"}}]},
        "Highlight by layer": {"rules": [
            {"name": "A-Highlight layer", "when": {"layer": "A-Highlight"}, "then": {"pen": 26}, "enabled": False}]},
    },
    "layer_combinations": {"All visible": {"hidden": [], "locked": []}},
    "purposes": {
        "Working": {"pen_set": "Working", "visibility": "Everything", "overrides": "None", "layers": None},
        "Highlight": {"pen_set": "Highlight", "visibility": "Everything", "overrides": "Fire rating", "layers": None},
        "Permit": {"pen_set": "Permit", "visibility": "Architectural", "overrides": "None", "layers": None},
        "Presentation": {"pen_set": "Presentation", "visibility": "No furniture", "overrides": "None", "layers": None},
        "Demo": {"pen_set": "Demo", "visibility": "Everything", "overrides": "External walls", "layers": None},
    },
}


def builtin(key: str) -> dict:
    return copy.deepcopy(_BUILTINS[key])


def _settings(settings):
    from . import settings as S

    return S.current() if settings is None else settings


def effective(key: str, settings: dict | None = None) -> dict:
    stored = _settings(settings).get(key)
    return copy.deepcopy(stored) if isinstance(stored, dict) and stored else builtin(key)


def current_purpose(settings: dict | None = None) -> str:
    st = _settings(settings)
    purposes = effective("purposes", st)
    name = st.get("purpose") or ""
    return name if name in purposes else next(iter(purposes))


def pen(pens: dict, n) -> dict:
    p = pens.get(str(n)) if isinstance(pens, dict) else None
    if not isinstance(p, dict):
        return dict(FALLBACK_PEN)
    return {"color": p.get("color", FALLBACK_PEN["color"]), "weight": p.get("weight", FALLBACK_PEN["weight"])}


def dash(line_types: dict, name) -> list:
    d = line_types.get(name) if isinstance(line_types, dict) else None
    return list(d) if isinstance(d, list) else []


# ---------------------------------------------------------------- validation

def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _pen_no(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 255


def _names(table) -> str | None:
    if not isinstance(table, dict):
        return "expected an object"
    if any(not isinstance(k, str) or not k.strip() for k in table):
        return "a name can't be empty"
    if any(len(k) > 64 for k in table):
        return "names are at most 64 characters"
    return None


def _rule_error(rule) -> str | None:
    if not isinstance(rule, dict) or not isinstance(rule.get("when", {}), dict) or not isinstance(rule.get("then", {}), dict):
        return "a rule needs a condition and an effect"
    name = rule.get("name", "")
    for k in rule.get("when", {}):
        if k not in WHEN:
            return f"rule {name}: unknown condition {k}"
    when, then = rule.get("when", {}), rule.get("then", {})
    if "op" in when and when["op"] not in OPS:
        return f"rule {name}: unknown operator {when['op']}"
    kinds = when.get("kind")
    for kind in (kinds if isinstance(kinds, list) else [kinds] if kinds is not None else []):
        if kind not in KINDS:
            return f"unknown element kind {kind}"
    for k, v in then.items():
        if k not in THEN:
            return f"rule {name}: unknown effect {k}"
        if k in ("pen", "cut_pen", "projection_pen", "fill") and not _pen_no(v):
            return f"rule {name}: pens are 1-255"
        if k == "surface" and not (isinstance(v, str) and _COLOR.match(v)):
            return f"rule {name}: colour must be #rrggbb"
        if k == "transparency" and not (_number(v) and 0 <= v <= 1):
            return f"rule {name}: transparency must be 0-1"
        if k in ("hide",) and not isinstance(v, bool):
            return f"rule {name}: hide is true or false"
        if k == "line" and not isinstance(v, str):
            return f"rule {name}: the line type is a name"
    if "enabled" in rule and not isinstance(rule["enabled"], bool):
        return f"rule {name}: enabled is true or false"
    return None


def validate(key: str, value) -> str | None:
    """None, or what is wrong with `value` for settings key `key` (one of the graphics keys)."""
    if key == "purpose":
        return None if isinstance(value, str) else "the purpose is a name"
    if key == "current_pen":
        return None if _pen_no(value) else "the current pen must be 1-255"
    if key == "sheet_purposes":
        ok = isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())
        return None if ok else "sheet purposes must map sheet numbers to purpose names"
    if (err := _names(value)) is not None:
        return err
    if not value:
        return None  # empty: the built-ins
    if key == "pen_sets":
        for set_name, pen_set in value.items():
            pens = pen_set.get("pens") if isinstance(pen_set, dict) else None
            if not isinstance(pens, dict):
                return f"pen set {set_name}: no pens"
            for n, p in pens.items():
                if not (isinstance(n, str) and n.isdigit() and 1 <= int(n) <= 255):
                    return f"pen {n} is out of range (1-255)"
                if not isinstance(p, dict) or not isinstance(p.get("color"), str) or not _COLOR.match(p["color"]):
                    return f"pen {n}: colour must be #rrggbb"
                if not (_number(p.get("weight")) and 0.05 <= p["weight"] <= 5.0):
                    return f"pen {n}: weight must be 0.05-5 mm"
                if "name" in p and not isinstance(p["name"], str):
                    return f"pen {n}: the name is text"
    elif key == "line_types":
        if "Solid" not in value:
            return "the Solid line type can't be removed"
        for name, d in value.items():
            if not isinstance(d, list) or not all(_number(x) for x in d):
                return f"line type {name}: a list of lengths"
            if len(d) % 2:
                return f"line type {name}: dashes and gaps come in pairs"
            if any(x <= 0 for x in d):
                return f"line type {name}: lengths must be above 0"
            if len(d) > 12:
                return f"line type {name}: at most 6 dash and gap pairs"
    elif key == "element_styles":
        for kind, st in value.items():
            if kind not in KINDS:
                return f"unknown element kind {kind}"
            if not isinstance(st, dict):
                return f"{kind}: expected an object"
            for part in ("cut", "projection"):
                p = st.get(part)
                if not isinstance(p, dict) or not _pen_no(p.get("pen")) or not isinstance(p.get("line"), str):
                    return f"{kind} {part}: a pen (1-255) and a line type"
            if not _pen_no(st.get("fill")):
                return f"{kind} fill: pens are 1-255"
    elif key in ("visibility_sets", "override_sets"):
        for set_name, v in value.items():
            if not isinstance(v, dict) or not isinstance(v.get("rules", []), list):
                return f"{set_name}: expected rules"
            if key == "visibility_sets":
                hidden = v.get("hidden_kinds", [])
                if not isinstance(hidden, list):
                    return f"{set_name}: hidden kinds are a list"
                for kind in hidden:
                    if kind not in KINDS:
                        return f"unknown element kind {kind}"
            for rule in v.get("rules", []):
                if (err := _rule_error(rule)) is not None:
                    return err
    elif key == "layer_combinations":
        for name, v in value.items():
            if not isinstance(v, dict) or not all(isinstance(v.get(k, []), list) and all(isinstance(x, str) for x in v.get(k, []))
                                                  for k in ("hidden", "locked")):
                return f"layer combination {name}: hidden and locked are lists of layer names"
    elif key == "purposes":
        for name, v in value.items():
            if not isinstance(v, dict) or not all(isinstance(v.get(k), str) for k in ("pen_set", "visibility", "overrides")):
                return f"purpose {name}: a pen set, a visibility set and an override set"
            if v.get("layers") is not None and not isinstance(v.get("layers"), str):
                return f"purpose {name}: layers must be a name or null"
    return None
```

- [ ] **Step 4: Wire it into `settings.py`**

In `DEFAULTS` add, after `"pen_sets": {}`:

```python
    "line_types": {},
    "element_styles": {},
    "visibility_sets": {},
    "override_sets": {},
    "layer_combinations": {},
    "purposes": {},
    "purpose": "",
    "current_pen": 23,
    "sheet_purposes": {},
```

In `_error`, replace the `pen_sets` check with:

```python
    from . import graphics

    if key in graphics.TABLES or key in ("purpose", "current_pen", "sheet_purposes"):
        return graphics.validate(key, value)
```

- [ ] **Step 5: Run the tests and the settings tests**

Run: `pixi run pytest tests/python/test_graphics.py tests/python/test_settings.py tests/python/test_settings_history.py -q`
Expected: all pass. If a settings test compared DEFAULTS exactly, update its expectation to include the new keys. That is a ruling: the new keys are the spec's.

- [ ] **Step 6: Commit**

```bash
git add python/kimcad/graphics.py python/kimcad/settings.py tests/python/test_graphics.py
git commit -m "feat(graphics): pen sets, line types, element styles, visibility, overrides and purposes tables with built-ins and validation"
```

---

### Task 2: Element kinds, rules and resolution (Python)

**Files:**
- Modify: `python/kimcad/graphics.py`
- Test: `tests/python/test_graphics.py`

**Interfaces:**
- Consumes: Task 1 (`effective`, `pen`, `dash`, `current_purpose`, `KINDS`).
- Produces:
  - `kind_of(element) -> str`
  - `matches(when: dict, element, facts: _Facts) -> bool`
  - `resolve(purpose: str | None = None, model=None, settings=None) -> dict`:

```
{"purpose": str, "pen_set": str, "visibility": str, "overrides": str,
 "pens": {"1": {"color", "weight"}, ...},          # the pen set, all 255
 "current_pen": int, "annotation_pen": int,         # annotations kind's projection pen
 "styles": [{"cut": {"color", "weight", "dash": [..]}, "projection": {...},
             "fill": "#rrggbb", "surface": "#rrggbb"|None, "transparency": float|None}],
 "elements": {guid: style_index}, "hidden": [guid, ...]}
```

  It is cached on `(id(model), B._current_id(), purpose, json of the graphics settings)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/python/test_graphics.py`)

```python
import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root

from kimcad.testing import build_model


def _model(schema="IFC4"):
    f = ifcopenshell.api.root.create_entity(ifcopenshell.file(schema=schema), ifc_class="IfcProject", name="P").file
    return f


def _el(f, cls, **psets):
    e = ifcopenshell.api.root.create_entity(f, ifc_class=cls)
    for pset_name, props in psets.items():
        p = ifcopenshell.api.pset.add_pset(f, product=e, name=pset_name)
        ifcopenshell.api.pset.edit_pset(f, pset=p, properties=props)
    return e


def test_kind_of_ifc4_classes():
    f = _model()
    assert g.kind_of(_el(f, "IfcWall")) == "walls"
    assert g.kind_of(_el(f, "IfcWallStandardCase")) == "walls"
    assert g.kind_of(_el(f, "IfcFurniture")) == "furniture"
    assert g.kind_of(_el(f, "IfcPipeSegment")) == "plumbing"
    assert g.kind_of(_el(f, "IfcDuctSegment")) == "hvac"
    assert g.kind_of(_el(f, "IfcLightFixture")) == "electrical"
    assert g.kind_of(_el(f, "IfcFooting")) == "structure_other"
    assert g.kind_of(_el(f, "IfcSpace")) == "rooms"
    assert g.kind_of(_el(f, "IfcBuildingElementProxy")) == "other"


def test_resolve_ifc2x3_flow_by_type():
    f = _model("IFC2X3")
    seg = _el(f, "IfcFlowSegment")
    t = ifcopenshell.api.root.create_entity(f, ifc_class="IfcPipeSegmentType")
    import ifcopenshell.api.type
    ifcopenshell.api.type.assign_type(f, related_objects=[seg], relating_type=t)
    assert g.kind_of(seg) == "plumbing"
    assert g.kind_of(_el(f, "IfcFurnishingElement")) == "furniture"
    assert g.kind_of(_el(f, "IfcFlowTerminal")) == "other"  # no type: any other MEP


def test_rule_operators():
    f = _model()
    w = _el(f, "IfcWall", Pset_WallCommon={"FireRating": "EI 60", "LoadBearing": True, "IsExternal": False})
    facts = g._Facts(w)
    assert g.matches({"property": "FireRating", "op": "contains", "value": "60"}, w, facts)
    assert g.matches({"property": "Pset_WallCommon.FireRating", "op": "equals", "value": "ei 60"}, w, facts)
    assert not g.matches({"property": "FireRating", "op": "equals", "value": "60"}, w, facts)
    assert g.matches({"property": "LoadBearing", "op": "true"}, w, facts)
    assert g.matches({"property": "IsExternal", "op": "false"}, w, facts)
    assert g.matches({"property": "Nope", "op": "missing"}, w, facts)
    assert not g.matches({"property": "Nope", "op": "exists"}, w, facts)
    assert not g.matches({"property": "Nope", "op": "equals", "value": "x"}, w, facts)  # missing never matches
    assert g.matches({"kind": ["walls", "slabs"], "ifc_class": "IfcWall"}, w, facts)
    assert not g.matches({"kind": "slabs"}, w, facts)


def test_rules_read_type_properties():
    f = _model()
    w = _el(f, "IfcWall")
    t = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWallType")
    p = ifcopenshell.api.pset.add_pset(f, product=t, name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=p, properties={"FireRating": "90"})
    import ifcopenshell.api.type
    ifcopenshell.api.type.assign_type(f, related_objects=[w], relating_type=t)
    assert g.matches({"property": "FireRating", "op": "contains", "value": "90"}, w, g._Facts(w))


def test_numbers_compare_as_numbers():
    f = _model()
    w = _el(f, "IfcWall", Custom={"Thickness": 0.3})
    facts = g._Facts(w)
    assert g.matches({"property": "Thickness", "op": "more", "value": "0.25"}, w, facts)
    assert not g.matches({"property": "Thickness", "op": "less", "value": "0.25"}, w, facts)
    assert not g.matches({"property": "Thickness", "op": "less", "value": "thick"}, w, facts)


def test_resolve_styles_elements_and_hidden():
    f = _model()
    wall = _el(f, "IfcWall", Pset_WallCommon={"FireRating": "60", "LoadBearing": False})
    chair = _el(f, "IfcFurniture")
    r = g.resolve("Working", model=f)
    st = r["styles"][r["elements"][wall.GlobalId]]
    assert st["cut"] == {"color": "#5a3a22", "weight": 0.5, "dash": []}
    assert st["projection"]["color"] == "#8a6a4a" and st["fill"] == "#b8a898" and st["surface"] is None
    assert r["hidden"] == [] and r["current_pen"] == 23 and r["annotation_pen"] == 23
    assert len(r["pens"]) == 255
    r = g.resolve("Highlight", model=f)  # Fire rating overrides
    st = r["styles"][r["elements"][wall.GlobalId]]
    assert st["cut"]["color"] == "#2050e0" and st["surface"] == "#4070e0"  # 60 min: pen 27
    r = g.resolve("Presentation", model=f)  # No furniture
    assert r["hidden"] == [chair.GlobalId]
    s.load({"purposes": {**g.builtin("purposes"), "S": {"pen_set": "Permit", "visibility": "Structure only",
                                                         "overrides": "None", "layers": None}}})
    r = g.resolve("S", model=f)
    assert set(r["hidden"]) == {wall.GlobalId, chair.GlobalId}  # LoadBearing false hides the wall


def test_first_matching_rule_wins_and_disabled_rules_are_skipped():
    f = _model()
    wall = _el(f, "IfcWall", Pset_WallCommon={"FireRating": "60"})
    rules = [{"name": "off", "when": {"kind": "walls"}, "then": {"pen": 5}, "enabled": False},
             {"name": "a", "when": {"kind": "walls"}, "then": {"pen": 26, "line": "Dashed"}},
             {"name": "b", "when": {"kind": "walls"}, "then": {"pen": 27}}]
    s.load({"override_sets": {"None": {"rules": []}, "T": {"rules": rules}},
            "purposes": {"P": {"pen_set": "Working", "visibility": "Everything", "overrides": "T", "layers": None}}})
    r = g.resolve("P", model=f)
    st = r["styles"][r["elements"][wall.GlobalId]]
    assert st["cut"]["color"] == "#e02020" and st["projection"]["dash"] == [3.0, 1.5]


def test_resolve_falls_back_on_missing_names():
    f = _model()
    wall = _el(f, "IfcWall")
    s.load({"purposes": {"P": {"pen_set": "Gone", "visibility": "Gone", "overrides": "Gone", "layers": None}},
            "element_styles": {**g.builtin("element_styles"),
                               "walls": {"cut": {"pen": 200, "line": "Gone"}, "projection": {"pen": 11, "line": "Solid"}, "fill": 12}},
            "pen_sets": {"Only": {"pens": {"11": {"color": "#123456", "weight": 0.3}}}}})
    r = g.resolve("Nope", model=f)  # unknown purpose: the first one
    assert r["purpose"] == "P" and r["pen_set"] == "Only"
    st = r["styles"][r["elements"][wall.GlobalId]]
    assert st["cut"] == {"color": "#000000", "weight": 0.18, "dash": []}  # pen 200 missing, line Gone
    assert st["projection"]["color"] == "#123456"
    assert r["hidden"] == []


def test_resolve_skips_spatial_structure_openings_and_drawings():
    m = build_model()
    r = g.resolve("Working", model=m)
    kinds = {m.by_guid(gid).is_a() for gid in r["elements"]}
    assert not kinds & {"IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcOpeningElement"}


def test_resolve_is_cached_on_the_model_state():
    f = _model()
    _el(f, "IfcWall")
    a = g.resolve("Working", model=f)
    assert g.resolve("Working", model=f) is a
    s.load({"current_pen": 5})
    assert g.resolve("Working", model=f) is not a
```

- [ ] **Step 2: Run them to watch them fail**

Run: `pixi run pytest tests/python/test_graphics.py -q`
Expected: the new tests fail with `AttributeError: module 'kimcad.graphics' has no attribute 'kind_of'`.

- [ ] **Step 3: Implement** (append to `graphics.py`)

```python
import json

import ifcopenshell.util.element

# ---------------------------------------------------------------- element kinds

_KIND_CLASSES = (
    ("walls", ("IfcWall", "IfcCurtainWall")), ("columns", ("IfcColumn",)), ("beams", ("IfcBeam",)),
    ("slabs", ("IfcSlab",)), ("roofs", ("IfcRoof",)),
    ("stairs", ("IfcStair", "IfcStairFlight", "IfcRamp", "IfcRampFlight")), ("railings", ("IfcRailing",)),
    ("doors", ("IfcDoor",)), ("windows", ("IfcWindow",)), ("coverings", ("IfcCovering",)),
    ("furniture", ("IfcFurnishingElement",)),
    ("plumbing", ("IfcPipeSegment", "IfcPipeFitting", "IfcSanitaryTerminal", "IfcValve", "IfcPump", "IfcTank",
                  "IfcWasteTerminal", "IfcFireSuppressionTerminal")),
    ("hvac", ("IfcDuctSegment", "IfcDuctFitting", "IfcAirTerminal", "IfcFan", "IfcUnitaryEquipment", "IfcCoil",
              "IfcBoiler", "IfcChiller", "IfcDamper")),
    ("electrical", ("IfcCableSegment", "IfcCableCarrierSegment", "IfcCableFitting", "IfcCableCarrierFitting",
                    "IfcLightFixture", "IfcLamp", "IfcOutlet", "IfcSwitchingDevice", "IfcElectricAppliance",
                    "IfcElectricDistributionBoard")),
    ("structure_other", ("IfcFooting", "IfcPile", "IfcMember", "IfcPlate")),
    ("rooms", ("IfcSpace",)), ("annotations", ("IfcAnnotation",)), ("grids", ("IfcGrid",)),
)
_MEP = ("plumbing", "hvac", "electrical")
_SKIP = ("IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcOpeningElement")


def _is(e, cls: str) -> bool:
    try:
        return e.is_a(cls)
    except RuntimeError:  # a class this schema doesn't have
        return False


def kind_of(element) -> str:
    for kind, classes in _KIND_CLASSES:
        if any(_is(element, c) for c in classes):
            return kind
    if _is(element, "IfcDistributionElement"):  # IFC2X3 flow elements: by their type
        t = ifcopenshell.util.element.get_type(element)
        if t is not None:
            for kind, classes in _KIND_CLASSES:
                if kind in _MEP and any(_is(t, c + "Type") for c in classes):
                    return kind
    return "other"


# ---------------------------------------------------------------- rules

class _Facts:
    """An element's properties, layer and materials, read once and only when a rule asks."""

    def __init__(self, element):
        self.element = element
        self._psets = None
        self._layer = False
        self._materials = None
        self._kind = None

    @property
    def kind(self) -> str:
        if self._kind is None:
            self._kind = kind_of(self.element)
        return self._kind

    def prop(self, name: str):
        if self._psets is None:
            try:
                self._psets = ifcopenshell.util.element.get_psets(self.element)
            except Exception:  # an IFC this reader doesn't follow: no properties
                self._psets = {}
        if "." in name:
            pset, prop = name.split(".", 1)
            return self._psets.get(pset, {}).get(prop)
        for props in self._psets.values():
            if name in props and name != "id":
                return props[name]
        return None

    @property
    def layer(self):
        if self._layer is False:
            from . import layers

            layer = layers.element_layer(self.element)
            self._layer = layer.Name if layer is not None else None
        return self._layer

    @property
    def materials(self) -> list:
        if self._materials is None:
            try:
                self._materials = [m.Name or "" for m in ifcopenshell.util.element.get_materials(self.element)]
            except Exception:
                self._materials = []
        return self._materials


def _text(v) -> str:
    return str(v).strip().lower()


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def matches(when: dict, element, facts: _Facts) -> bool:
    if "kind" in when:
        kinds = when["kind"] if isinstance(when["kind"], list) else [when["kind"]]
        if facts.kind not in kinds:
            return False
    if "ifc_class" in when and not _is(element, when["ifc_class"]):
        return False
    if "layer" in when and _text(facts.layer or "") != _text(when["layer"]):
        return False
    if "material" in when and not any(_text(when["material"]) in _text(m) for m in facts.materials):
        return False
    if "property" in when:
        v = facts.prop(when["property"])
        op, want = when.get("op", "exists"), when.get("value")
        if op == "missing":
            return v is None
        if v is None:
            return False
        if op == "exists":
            return True
        if op in ("true", "false"):
            truth = v if isinstance(v, bool) else _text(v) in ("true", "yes", "1", ".t.")
            return truth if op == "true" else not truth
        if op in ("less", "more"):
            a, b = _float(v), _float(want)
            return a is not None and b is not None and (a < b if op == "less" else a > b)
        if op == "equals":
            return _text(v) == _text(want)
        if op == "not_equals":
            return _text(v) != _text(want)
        if op == "contains":
            return _text(want) in _text(v)
    return True


# ---------------------------------------------------------------- resolution

_cache: dict = {}
GRAPHICS_KEYS = TABLES + ("purpose", "current_pen")


def _products(model):
    for e in model.by_type("IfcProduct"):
        if any(_is(e, c) for c in _SKIP):
            continue
        if _is(e, "IfcAnnotation") and getattr(e, "ObjectType", None) == "DRAWING":
            continue
        yield e


def _line(pens, line_types, pen_no, line_name) -> dict:
    p = pen(pens, pen_no)
    return {"color": p["color"], "weight": p["weight"], "dash": dash(line_types, line_name)}


def resolve(purpose: str | None = None, model=None, settings: dict | None = None) -> dict:
    from . import app_bridge as B

    model = B._model if model is None else model
    st = _settings(settings)
    purposes = effective("purposes", st)
    name = purpose if purpose in purposes else current_purpose(st)
    key = (id(model), B._current_id() if model is B._model else id(model), name,
           json.dumps({k: st.get(k) for k in GRAPHICS_KEYS}, sort_keys=True))
    if key in _cache:
        return _cache[key]
    p = purposes[name]
    pen_sets, vis_sets, ovr_sets = effective("pen_sets", st), effective("visibility_sets", st), effective("override_sets", st)
    set_name = p.get("pen_set") if p.get("pen_set") in pen_sets else next(iter(pen_sets))
    vis_name = p.get("visibility") if p.get("visibility") in vis_sets else None
    ovr_name = p.get("overrides") if p.get("overrides") in ovr_sets else None
    pens = pen_sets[set_name].get("pens", {})
    line_types = effective("line_types", st)
    styles_by_kind = effective("element_styles", st)
    builtin_styles = _BUILTINS["element_styles"]
    vis = vis_sets.get(vis_name) or {"hidden_kinds": [], "rules": []}
    hidden_kinds = set(vis.get("hidden_kinds", []))
    vis_rules = [r for r in vis.get("rules", []) if r.get("enabled", True)]
    rules = [r for r in (ovr_sets.get(ovr_name) or {}).get("rules", []) if r.get("enabled", True)]
    styles, index, elements, hidden = [], {}, {}, []
    for e in _products(model) if model is not None else ():
        facts = _Facts(e)
        if facts.kind in hidden_kinds or any(matches(r.get("when", {}), e, facts) for r in vis_rules):
            hidden.append(e.GlobalId)
            continue
        base = styles_by_kind.get(facts.kind) or builtin_styles[facts.kind]
        cut_pen, proj_pen = base["cut"]["pen"], base["projection"]["pen"]
        cut_line, proj_line, fill_pen = base["cut"]["line"], base["projection"]["line"], base["fill"]
        surface = transparency = None
        for r in rules:
            if matches(r.get("when", {}), e, facts):
                then = r.get("then", {})
                if then.get("hide"):
                    hidden.append(e.GlobalId)
                    break
                cut_pen = then.get("cut_pen", then.get("pen", cut_pen))
                proj_pen = then.get("projection_pen", then.get("pen", proj_pen))
                cut_line = proj_line = then.get("line", None) or cut_line
                if "line" not in then:
                    proj_line = base["projection"]["line"]
                fill_pen = then.get("fill", fill_pen)
                surface, transparency = then.get("surface"), then.get("transparency")
                break
        else:
            pass
        if hidden and hidden[-1] == e.GlobalId:
            continue
        style = {"cut": _line(pens, line_types, cut_pen, cut_line),
                 "projection": _line(pens, line_types, proj_pen, proj_line),
                 "fill": pen(pens, fill_pen)["color"], "surface": surface, "transparency": transparency}
        k = json.dumps(style, sort_keys=True)
        if k not in index:
            index[k] = len(styles)
            styles.append(style)
        elements[e.GlobalId] = index[k]
    ann = styles_by_kind.get("annotations") or builtin_styles["annotations"]
    out = {"purpose": name, "pen_set": set_name, "visibility": vis_name or "", "overrides": ovr_name or "",
           "pens": {str(n): pen(pens, n) for n in range(1, 256)},
           "current_pen": st.get("current_pen", 23), "annotation_pen": ann["projection"]["pen"],
           "styles": styles, "elements": elements, "hidden": hidden}
    if len(_cache) > 8:
        _cache.clear()
    _cache[key] = out
    return out
```

Ruling allowance: if `ifcopenshell.api.type.assign_type` takes different argument names in 0.9.0, adjust
the test call to the installed signature. That is a test-harness detail, so ledger it.

- [ ] **Step 4: Run the tests**

Run: `pixi run pytest tests/python/test_graphics.py -q`
Expected: all pass.

- [ ] **Step 5: Time it on the Clinic** (performance check, not a test)

```bash
pixi run python -c "import sys,time,json; sys.path.insert(0,'python'); from kimcad import app_bridge as B, graphics as g; B.open_model(r'tests/corpus/files/community/IFC 2.3.0.1 (IFC 2x3)/Medical-Dental Clinic/Clinic_Architectural.ifc'); [ (lambda t: (g.resolve(p), print(p, round(time.perf_counter()-t,2))))(time.perf_counter()) for p in ('Working','Highlight','Permit')]"
```

Expected: Working < 0.2 s, Highlight (property rules) < 1 s. Write the numbers into the ledger. If
Highlight is over 1 s, cache `_Facts` psets per type object. That is a ruling.

- [ ] **Step 6: Commit**

```bash
git add python/kimcad/graphics.py tests/python/test_graphics.py
git commit -m "feat(graphics): element kinds (IFC4 and IFC2X3 by type), rules and resolution per purpose"
```

---

### Task 3: Graphics bridge functions (Python)

**Files:**
- Modify: `python/kimcad/graphics.py`, `python/kimcad/app_bridge.py` (re-exports near the settings re-exports)
- Test: `tests/python/test_graphics.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces (bridge, JSON strings):
  - `graphics_state() -> {"ok", ...resolve() fields..., "hidden_layers", "locked_layers"}`. When a
    purpose has a layer combination, the response carries the settings' current layer lists.
  - `graphics_tables() -> {"ok", "tables": {key: effective table for each of TABLES}, "purpose",
    "current_pen", "sheet_purposes", "kinds": [...], "builtins": [names per table]}`
  - `set_graphics(changes_json) -> {"ok", "dirty"}`. Changes are a subset of the graphics keys. It
    refuses: an invalid table; removing the last entry of a table that needs one (pen_sets, purposes);
    a purpose naming a missing set. The message is plain.
  - `set_purpose(name) -> {"ok", "dirty", "hidden_layers", "locked_layers"}`. Sets `purpose`, and
    applies the purpose's layer combination, if any, to `hidden_layers` and `locked_layers`.
  - `set_current_pen(n) -> {"ok", "dirty"}`.

- [ ] **Step 1: Failing tests**

```python
def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def test_graphics_state_and_tables_through_the_bridge():
    b.close_model() if hasattr(b, "close_model") else None
    r = call("graphics_state")
    assert r["ok"] and r["purpose"] == "Working" and len(r["pens"]) == 255
    t = call("graphics_tables")
    assert t["ok"] and set(t["tables"]) == set(g.TABLES) and t["kinds"] == list(g.KINDS)
    assert "Permit" in t["builtins"]["pen_sets"]


def test_set_graphics_writes_valid_tables_only():
    sets = g.builtin("pen_sets")
    sets["Office"] = sets["Permit"]
    assert call("set_graphics", json.dumps({"pen_sets": sets}))["ok"]
    assert "Office" in s.current()["pen_sets"]
    r = call("set_graphics", json.dumps({"line_types": {"Dashed": [1, 1]}}))
    assert not r["ok"] and r["error"] == "the Solid line type can't be removed"
    r = call("set_graphics", json.dumps({"colour": 1}))
    assert not r["ok"] and r["error"] == "unknown graphics setting colour"


def test_set_graphics_refuses_removing_the_last_set():
    r = call("set_graphics", json.dumps({"pen_sets": {}}))  # {} means built-ins: allowed
    assert r["ok"]
    r = call("set_graphics", json.dumps({"purposes": {"P": {"pen_set": "Nope", "visibility": "Everything",
                                                             "overrides": "None", "layers": None}}}))
    assert not r["ok"] and r["error"] == "purpose P uses a pen set that doesn't exist: Nope"


def test_set_purpose_applies_its_layer_combination():
    s.load({"layer_combinations": {"Plans": {"hidden": ["A-Furniture"], "locked": ["A-Grid"]}},
            "purposes": {**g.builtin("purposes"),
                         "Plans": {"pen_set": "Permit", "visibility": "Everything", "overrides": "None", "layers": "Plans"}}})
    r = call("set_purpose", "Plans")
    assert r["ok"] and r["hidden_layers"] == ["A-Furniture"] and r["locked_layers"] == ["A-Grid"]
    assert s.current()["purpose"] == "Plans" and s.current()["hidden_layers"] == ["A-Furniture"]
    r = call("set_purpose", "Working")  # no combination: the layers stay
    assert r["hidden_layers"] == ["A-Furniture"]
    assert not call("set_purpose", "Nope")["ok"]


def test_set_current_pen():
    assert call("set_current_pen", "7")["ok"] and s.current()["current_pen"] == 7
    assert not call("set_current_pen", "0")["ok"]
```

- [ ] **Step 2: Run to watch them fail**

Run: `pixi run pytest tests/python/test_graphics.py -q -k "bridge or set_"`
Expected: FAIL (`AttributeError: module 'kimcad.app_bridge' has no attribute 'graphics_state'`).

- [ ] **Step 3: Implement** (append to `graphics.py`)

```python
# ---------------------------------------------------------------- bridge

def _fail(message: str) -> str:
    from . import app_bridge as B

    return B._dump({"ok": False, "error": message})


def graphics_state() -> str:
    from . import app_bridge as B
    from . import settings as S

    st = S.current()
    return B._dump({"ok": True, **resolve(settings=st), "hidden_layers": st.get("hidden_layers", []),
                    "locked_layers": st.get("locked_layers", [])})


def graphics_tables() -> str:
    from . import app_bridge as B
    from . import settings as S

    st = S.current()
    return B._dump({"ok": True, "tables": {k: effective(k, st) for k in TABLES}, "purpose": current_purpose(st),
                    "current_pen": st.get("current_pen", 23), "sheet_purposes": st.get("sheet_purposes", {}),
                    "kinds": list(KINDS), "builtins": {k: list(_BUILTINS[k]) for k in TABLES}})


def _references_error(st: dict) -> str | None:
    purposes = effective("purposes", st)
    pens, vis, ovr = effective("pen_sets", st), effective("visibility_sets", st), effective("override_sets", st)
    combos = effective("layer_combinations", st)
    for name, p in purposes.items():
        if p["pen_set"] not in pens:
            return f"purpose {name} uses a pen set that doesn't exist: {p['pen_set']}"
        if p["visibility"] not in vis:
            return f"purpose {name} uses a visibility set that doesn't exist: {p['visibility']}"
        if p["overrides"] not in ovr:
            return f"purpose {name} uses an override set that doesn't exist: {p['overrides']}"
        if p.get("layers") is not None and p["layers"] not in combos:
            return f"purpose {name} uses a layer combination that doesn't exist: {p['layers']}"
    return None


def set_graphics(changes_json: str) -> str:
    from . import app_bridge as B
    from . import settings as S

    try:
        changes = json.loads(changes_json)
    except ValueError as ex:
        return _fail(f"bad input: {ex}")
    if not isinstance(changes, dict):
        return _fail("bad input: expected an object")
    for k, v in changes.items():
        if k not in TABLES and k not in ("purpose", "current_pen", "sheet_purposes"):
            return _fail(f"unknown graphics setting {k}")
        if (err := validate(k, v)) is not None:
            return _fail(err)
    merged = {**S.current(), **changes}
    if (err := _references_error(merged)) is not None:
        return _fail(err)
    r = json.loads(S.set_project_settings(json.dumps(changes)))
    return B._dump({"ok": r["ok"], "dirty": r.get("dirty", False), **({"error": r["error"]} if not r["ok"] else {})})


def set_purpose(name: str) -> str:
    from . import app_bridge as B
    from . import settings as S

    st = S.current()
    purposes = effective("purposes", st)
    if name not in purposes:
        return _fail(f"no purpose called {name}")
    changes = {"purpose": name}
    combo = purposes[name].get("layers")
    combos = effective("layer_combinations", st)
    if combo is not None and combo in combos:
        changes["hidden_layers"] = list(combos[combo].get("hidden", []))
        changes["locked_layers"] = list(combos[combo].get("locked", []))
    r = json.loads(S.set_project_settings(json.dumps(changes)))
    cur = S.current()
    return B._dump({"ok": r["ok"], "dirty": r.get("dirty", False), "hidden_layers": cur["hidden_layers"],
                    "locked_layers": cur["locked_layers"]})


def set_current_pen(n: str) -> str:
    from . import app_bridge as B
    from . import settings as S

    try:
        value = int(n)
    except (TypeError, ValueError):
        return _fail("the current pen must be 1-255")
    r = json.loads(S.set_project_settings(json.dumps({"current_pen": value})))
    return B._dump({"ok": r["ok"], "dirty": r.get("dirty", False), **({"error": r["error"]} if not r["ok"] else {})})
```

In `app_bridge.py`, next to the settings re-exports:

```python
from .graphics import (  # noqa: E402,F401
    graphics_state,
    graphics_tables,
    set_current_pen,
    set_graphics,
    set_purpose,
)
```

Note: the `setup_function` in the test file calls `s.load(None)`, so the settings start at the defaults.
The first test's `close_model` line is defensive. If `app_bridge` has no close function, the model left
by earlier tests is fine: `graphics_state` resolves whatever is open.

- [ ] **Step 4: Run the tests**

Run: `pixi run pytest tests/python/test_graphics.py tests/python/test_settings.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add python/kimcad/graphics.py python/kimcad/app_bridge.py tests/python/test_graphics.py
git commit -m "feat(graphics): bridge: graphics_state, graphics_tables, set_graphics, set_purpose (applies layer combinations), set_current_pen"
```

---

### Task 4: Drawings and sheets styled by the purpose (Python)

**Files:**
- Modify: `python/kimcad/drawgen.py` (settings in `generate`, overlay tags), `python/kimcad/graphics.py`
  (`style_svg`), `python/kimcad/drawings.py:258-289`, `python/kimcad/sheets.py:460-492` (+ `set_sheet_purpose`)
- Test: `tests/python/test_graphics.py`, `tests/python/test_drawings.py`, `tests/python/test_sheets.py`

**Interfaces:**
- Consumes: `resolve`.
- Produces:
  - `graphics.style_svg(svg: str, resolved: dict, k: float = 1.0) -> str`.
  - `drawings.generate_drawing(guid, include_json)` returns a styled SVG. Graphics-hidden elements are
    removed from the include list before generation. When no include list is given, the include list
    is all drawn products minus the hidden ones.
  - `sheets.set_sheet_purpose(number, purpose) -> {"ok"}`. An empty purpose means "Current"; it writes
    `sheet_purposes`.
  - `sheets.sheet_svg(number)` styles each view with the sheet's purpose and `k = 100 / scale`.

**SVG structure after this task.**
- Cut elements: `<g class="section"> <g class="IfcWall" ifc:guid="…"> <path …/> </g> …`.
- Projection: `<g class="projection IfcSlab" ifc:guid="…">`.
- Overlay parts get `data-kind` (`swing`, `window`, `room`, `annotation`, `marker`). Annotations also
  get `ifc:guid`.

**Styling rules (`style_svg`):**
- For each `<g … class="…" … ifc:guid="G">`:
  - When G is in `resolved["hidden"]`, the whole group up to its matching `</g>` is removed.
  - When G is in `resolved["elements"]`, presentation attributes are added to the opening tag. A
    projection group uses the style's projection line and `fill="none"`. A cut group uses the cut line
    and `fill="<fill>"` with `fill-rule="evenodd"`.
  - The width is `weight / k`. `stroke-dasharray` is the dash list ÷ k (omitted when empty).
  - `stroke-linecap="butt"`.
- Annotations in the overlay use pen `annotation_pen`, or the annotation's own pen. That pen is given
  as `data-pen` on its group by drawgen, read from `KIMCAD_Annotation.Pen` (Task 5 writes it; until
  then it is absent).
- The overlay's default stroke-width (`0.18`) is divided by k.
- Any SVG `<style>` block is removed (svg-no-css should already omit it).

- [ ] **Step 1: Failing tests**

`tests/python/test_graphics.py`:

```python
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:ifc="http://www.ifcopenshell.org/ns">'
       '<g class="section"><g class="IfcWall" ifc:guid="W1"><path d="M0,0 L1,1"/></g>'
       '<g class="IfcFurniture" ifc:guid="F1"><path d="M0,0 L2,2"/><g><path d="M1,1"/></g></g></g>'
       '<g class="projection IfcWall" ifc:guid="W1"><path d="M3,3"/></g></svg>')


def test_style_svg_applies_lines_fills_and_removes_hidden():
    resolved = {"styles": [{"cut": {"color": "#111111", "weight": 0.5, "dash": []},
                            "projection": {"color": "#222222", "weight": 0.18, "dash": [3.0, 1.5]},
                            "fill": "#333333", "surface": None, "transparency": None}],
                "elements": {"W1": 0}, "hidden": ["F1"], "pens": {}, "annotation_pen": 23}
    out = g.style_svg(SVG, resolved, k=2.0)
    assert 'ifc:guid="F1"' not in out and "M2,2" not in out and "M1,1" not in out
    cut = re.search(r'<g class="IfcWall" ifc:guid="W1"([^>]*)>', out).group(1)
    assert 'stroke="#111111"' in cut and 'stroke-width="0.25"' in cut and 'fill="#333333"' in cut
    proj = re.search(r'<g class="projection IfcWall" ifc:guid="W1"([^>]*)>', out).group(1)
    assert 'stroke="#222222"' in proj and 'stroke-width="0.09"' in proj and 'stroke-dasharray="1.5 0.75"' in proj
    assert 'fill="none"' in proj
```

(with `import re` at the top of the test file).

`tests/python/test_drawings.py`. Change the assertion in
`test_section_shows_cut_walls_and_slabs_filled_and_the_rest_in_projection` from
`'class="projection"' in svg` to `'class="projection' in svg`. Then add:

```python
def test_drawings_are_styled_by_the_purpose(house):
    from kimcad import settings as s
    guid = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, -1)["guid"]
    working = call("generate_drawing", guid, "")["svg"]
    assert 'stroke="#5a3a22"' in working  # Working: walls cut, dark brown
    assert call("set_purpose", "Permit")["ok"]
    permit = call("generate_drawing", guid, "")["svg"]
    assert 'stroke="#5a3a22"' not in permit and 'stroke="#000000"' in permit
    assert call("set_purpose", "Working")["ok"]
    s.load(None)


def test_hidden_kinds_are_left_out_of_drawings(house):
    from kimcad import settings as s
    guid = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, -1)["guid"]
    assert "IfcWall" in call("generate_drawing", guid, "")["svg"]
    vis = {**call("graphics_tables")["tables"]["visibility_sets"], "No walls": {"hidden_kinds": ["walls"], "rules": []}}
    purposes = {**call("graphics_tables")["tables"]["purposes"],
                "NW": {"pen_set": "Working", "visibility": "No walls", "overrides": "None", "layers": None}}
    assert call("set_graphics", json.dumps({"visibility_sets": vis, "purposes": purposes}))["ok"]
    assert call("set_purpose", "NW")["ok"]
    assert "IfcWall" not in call("generate_drawing", guid, "")["svg"]
    s.load(None)
```

`tests/python/test_sheets.py`. Using the module's existing sheet helpers (read the file for the
fixture that makes a sheet with a placed drawing), add:

```python
def test_sheet_weights_do_not_scale(house):  # adapt the fixture name to the module's
    number = <make a sheet and place one section at scale 50 using the module's helpers>
    svg = call("sheet_svg", number)["svg"]
    view = svg.split('class="kimcad-view"', 1)[1]
    widths = {float(w) for w in re.findall(r'<g class="IfcWall"[^>]*stroke-width="([\d.]+)"', view)}
    assert widths == {0.25}  # 0.50 mm pen / k (k = 100/50 = 2): prints 0.50 mm on paper
    assert call("set_sheet_purpose", number, "Permit")["ok"]
    assert 'stroke="#5a3a22"' not in call("sheet_svg", number)["svg"]
    assert call("set_sheet_purpose", number, "")["ok"]
```

Executing this step means reading `tests/python/test_sheets.py` and writing the concrete setup with
its helpers (`new_sheet`, `place_drawing`), with a section created as in `test_drawings.py`.

- [ ] **Step 2: Run to watch them fail**

Run: `pixi run pytest tests/python/test_graphics.py tests/python/test_drawings.py tests/python/test_sheets.py -q`
Expected: the new tests fail (`style_svg` missing, no `stroke="#5a3a22"`, `set_sheet_purpose` missing).

- [ ] **Step 3: Implement**

`drawgen.generate`, in the settings tuple, add `("svg-segment-projection", True), ("svg-no-css", True)`.

`drawgen.overlay`: tag the parts by kind. Change the plan block to:

```python
            for e in f.by_type("IfcDoor"):
                if ifcopenshell.util.element.get_container(e) == storey and e.ObjectPlacement is not None:
                    parts += _tagged("swing", door_swings(e, to_paper))
            for e in f.by_type("IfcWindow"):
                if ifcopenshell.util.element.get_container(e) == storey and e.ObjectPlacement is not None:
                    parts += _tagged("window", window_symbol(e, to_paper))
            parts += _tagged("room", room_stamps(storey, to_paper))
            parts += plan_annotations(storey, to_paper)  # tags each annotation itself (with its guid and pen)
            parts += _tagged("marker", markers(f, to_paper, storey_elevation(storey)))
```

with

```python
def _tagged(kind: str, parts: list) -> list:
    return [f'<g data-kind="{kind}">', *parts, "</g>"] if parts else []
```

Inside `plan_annotations`, wrap each annotation's output in
`<g data-kind="annotation" ifc:guid="{a.GlobalId}"{pen_attr}>…</g>`. `pen_attr` is
` data-pen="{n}"` when its `KIMCAD_Annotation` pset has an integer `Pen`, otherwise empty. Read the
function first; it loops over the storey's annotations.

`graphics.style_svg`:

```python
_GROUP = re.compile(r'<g\b([^>]*?)\bifc:guid="([^"]+)"([^>]*)>')


def _end_of_group(svg: str, start: int) -> int:
    """Index just after the </g> closing the <g> that starts at `start`."""
    depth, i = 0, start
    for m in re.finditer(r"<g\b[^>]*?(/?)>|</g>", svg[start:]):
        if m.group(0).startswith("</g"):
            depth -= 1
        elif not m.group(1):
            depth += 1
        if depth == 0:
            return start + m.end()
    return len(svg)


def _fmt(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _stroke(line: dict, k: float) -> str:
    out = f' stroke="{line["color"]}" stroke-width="{_fmt(line["weight"] / k)}" stroke-linecap="butt"'
    if line["dash"]:
        out += f' stroke-dasharray="{" ".join(_fmt(d / k) for d in line["dash"])}"'
    return out


def style_svg(svg: str, resolved: dict, k: float = 1.0) -> str:
    svg = re.sub(r"<style[^>]*>.*?</style>", "", svg, flags=re.S)
    hidden = set(resolved.get("hidden", []))
    elements, styles = resolved.get("elements", {}), resolved.get("styles", [])
    pens = resolved.get("pens", {})
    out, pos = [], 0
    for m in _GROUP.finditer(svg):
        if m.start() < pos:
            continue  # inside a removed group
        out.append(svg[pos:m.start()])
        guid, attrs = m.group(2), m.group(1) + m.group(3)
        if guid in hidden:
            pos = _end_of_group(svg, m.start())
            continue
        tag = m.group(0)
        if 'data-kind="annotation"' in attrs:
            pm = re.search(r'data-pen="(\d+)"', attrs)
            p = pen(pens, int(pm.group(1)) if pm else resolved.get("annotation_pen", 23))
            tag = tag[:-1] + _stroke({"color": p["color"], "weight": p["weight"], "dash": []}, k) + f' color="{p["color"]}">'
        elif guid in elements:
            st = styles[elements[guid]]
            if re.search(r'class="projection\b', attrs):
                tag = tag[:-1] + _stroke(st["projection"], k) + ' fill="none">'
            else:
                tag = tag[:-1] + _stroke(st["cut"], k) + f' fill="{st["fill"]}" fill-rule="evenodd">'
        out.append(tag)
        pos = m.end()
    out.append(svg[pos:])
    svg = "".join(out)
    return svg.replace('class="kimcad-overlay" fill="none" stroke="#000000" stroke-width="0.18"',
                       f'class="kimcad-overlay" fill="none" stroke="#000000" stroke-width="{_fmt(0.18 / k)}"', 1)
```

Annotation text inside the overlay has `fill="#000000"` set by the overlay. In the annotation branch,
also replace that inside the group: after building the output, run
`re.sub(r'(<g data-kind="annotation"[^>]*color="(#[0-9a-f]{6})"[^>]*>)(.*?)</g>', …)` to set the text
`fill` to the colour. Keep it simple: a second pass over annotation groups that replaces
`fill="#000000"` with `fill="<color>"` inside them.

`drawings.generate_drawing`, before computing the cache key:

```python
    from . import graphics

    resolved = graphics.resolve()
    if resolved["hidden"]:
        hidden = set(resolved["hidden"])
        wanted = json.loads(include_json) if include_json else [p.GlobalId for p in G.drawn_products(B._model)]
        include_json = json.dumps(sorted(gid for gid in wanted if gid not in hidden))
```

Return `graphics.style_svg(svg, resolved, 1.0)` in both the cached and the fresh paths (the cache keeps
the unstyled SVG).

`sheets`:
- `sheet_svg` resolves `purpose = settings.current()["sheet_purposes"].get(number)` and
  `resolved = graphics.resolve(purpose or None)`.
- `_drawing_size(guid)` uses `generate_drawing`, which returns an SVG styled for the current purpose.
  Change `_drawing_size` to call a new `drawings.raw_drawing(guid, include_json) -> (ok, svg_or_error)`.
  It is the unstyled body of `generate_drawing`, which then becomes `raw_drawing` + `style_svg`. The
  sheet styles with `style_svg(svg, resolved, k)`, where `k = 100.0 / p["scale"]`.
- The sheet's hidden elements must come from the sheet's purpose: `raw_drawing` takes the include
  list computed from `resolved["hidden"]` as above.
- Add:

```python
def set_sheet_purpose(number: str, purpose: str) -> str:
    from . import graphics, settings as S

    if _sheet(number) is None:
        return A._fail("unknown sheet")
    current = dict(S.current().get("sheet_purposes", {}))
    if purpose:
        if purpose not in graphics.effective("purposes"):
            return A._fail(f"no purpose called {purpose}")
        current[number] = purpose
    else:
        current.pop(number, None)
    r = json.loads(S.set_project_settings(json.dumps({"sheet_purposes": current})))
    return B._dump({"ok": r["ok"], "dirty": r.get("dirty", False)})
```

  Re-export `set_sheet_purpose` where the other sheets functions are re-exported in `app_bridge`.
  Check with `grep -n "sheet_svg" python/kimcad/app_bridge.py`.

- [ ] **Step 4: Run the drawing, sheet and graphics tests**

Run: `pixi run pytest tests/python/test_graphics.py tests/python/test_drawings.py tests/python/test_sheets.py tests/python/test_annotations.py -q`
Expected: pass. Existing tests that looked for `class="projection"` exactly, or for CSS text, must be
updated to the new structure. That is a ruling: the spec changes the SVG structure.

- [ ] **Step 5: Run the M4 check**

Run: `pixi run m4`
Expected: passes (the sheet PDF still exports). If it checks colours or CSS, update it to the styled
output and ledger a ruling.

- [ ] **Step 6: Commit**

```bash
git add python/kimcad/drawgen.py python/kimcad/graphics.py python/kimcad/drawings.py python/kimcad/sheets.py python/kimcad/app_bridge.py tests/python
git commit -m "feat(graphics): drawings and sheets styled by the purpose; weights and dashes divided by the sheet scale; sheet purposes"
```

---

### Task 5: Annotation pens (Python)

**Files:**
- Modify: `python/kimcad/annotations.py` (`_set`, `_read`, `add_annotation`, `annotations`, new `set_annotation_pen`), `app_bridge.py` re-export
- Test: `tests/python/test_annotations.py`

**Interfaces:**
- Produces:
  - `annotations(storey)` items gain `"pen": int | None`.
  - New annotations get `Pen = settings.current_pen`.
  - `set_annotation_pen(guid, pen) -> {"ok"}` (undoable, validated 1–255).

- [ ] **Step 1: Failing test** (append; reuse the module's fixtures and its `call` helper)

```python
def test_annotations_take_the_current_pen_and_can_change_it(house):  # adapt to the module's fixture
    from kimcad import settings as s
    assert json.loads(s.set_project_settings(json.dumps({"current_pen": 26})))["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    guid = call("add_annotation", storey, "text", json.dumps([[1.0, 1.0]]), "Hello")["guid"]
    a = next(x for x in call("annotations", storey)["annotations"] if x["guid"] == guid)
    assert a["pen"] == 26
    assert call("set_annotation_pen", guid, "5")["ok"]
    a = next(x for x in call("annotations", storey)["annotations"] if x["guid"] == guid)
    assert a["pen"] == 5
    assert not call("set_annotation_pen", guid, "300")["ok"]
    s.load(None)
```

- [ ] **Step 2: Run to watch it fail**

Run: `pixi run pytest tests/python/test_annotations.py -q -k pen`
Expected: FAIL (`KeyError: 'pen'`).

- [ ] **Step 3: Implement**
- `_set(annotation, kind, text, local, size=None, pen=None)`: when `pen` is None, keep the existing
  `Pen` (read from the pset); otherwise write `"Pen": int(pen)`.
- `_read` returns a 5th value, `pen`: an int or None. Update its callers to unpack it.
- `add_annotation` passes `pen=settings.current()["current_pen"]`.
- `annotations()` puts `"pen": pen` in each item.
- `set_annotation_pen(guid, pen)`:
  - Validate `1 <= int(pen) <= 255`.
  - Run, through the same undoable transaction helper that `set_annotation_size` uses, a call of
    `_set(..., pen=int(pen))` with the current kind, text and points.
- Re-export it in `app_bridge` next to `set_annotation_size`.
- `drawgen.plan_annotations` reads `Pen` for `data-pen` (Task 4 left the hook).

- [ ] **Step 4: Run** `pixi run pytest tests/python/test_annotations.py tests/python/test_drawings.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add python/kimcad/annotations.py python/kimcad/drawgen.py python/kimcad/app_bridge.py tests/python/test_annotations.py
git commit -m "feat(graphics): annotations carry a pen; new ones take the current pen"
```

---

### Task 6: C++ `Graphics`: the resolved state

**Files:**
- Create: `app/src/Graphics.h`, `app/src/Graphics.cpp`, `app/tests/test_graphics.cpp`
- Modify: `app/CMakeLists.txt` (source + `kimcad_test(test_graphics)`)

**Interfaces:**
- Produces:

```cpp
namespace kimcad {
struct LineStyle {
    QColor color = Qt::black;
    double weight = 0.18;          // mm on paper
    QVector<double> dash;          // mm on paper; empty = solid
    bool operator==(const LineStyle& o) const { return color == o.color && weight == o.weight && dash == o.dash; }
};
struct ElementStyle {
    LineStyle cut, projection;
    QColor fill = QColor(64, 64, 70);
    std::optional<QColor> surface;
    std::optional<double> transparency;
};
class Graphics {
public:
    static Graphics fromJson(const QJsonObject& state); // graphics_state's reply
    const ElementStyle* styleOf(const QString& guid) const;   // null: no style (keep defaults)
    bool isHidden(const QString& guid) const { return m_hidden.contains(guid); }
    const QSet<QString>& hidden() const { return m_hidden; }
    LineStyle pen(int n) const;                    // fallback black 0.18
    int currentPen() const { return m_currentPen; }
    int annotationPen() const { return m_annotationPen; }
    QString purpose() const { return m_purpose; }
    bool isEmpty() const { return m_styles.isEmpty() && m_hidden.isEmpty(); }
    // Screen width in pixels: 1, or with true weights clamp(round(weight * 4), 1, 6).
    static float pixels(double weightMm, bool trueWeights);
    // OCCT 16-bit screen pattern for a dash list (empty: 0xFFFF): each mm ~ 2 bits, dash bits set.
    static uint16_t pattern(const QVector<double>& dashMm);
private:
    QVector<ElementStyle> m_styles;
    QHash<QString, int> m_elements;
    QSet<QString> m_hidden;
    QHash<int, LineStyle> m_pens;
    int m_currentPen = 23, m_annotationPen = 23;
    QString m_purpose;
};
}
```

- [ ] **Step 1: Failing tests** (`app/tests/test_graphics.cpp`)

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonArray>
#include <QJsonDocument>
#include <QtTest>

#include "Graphics.h"

class TestGraphics : public QObject {
    Q_OBJECT
private slots:
    void parsesStylesHiddenAndPens()
    {
        const QByteArray json = R"({"ok": true, "purpose": "Working", "current_pen": 26, "annotation_pen": 23,
            "pens": {"26": {"color": "#e02020", "weight": 0.5}},
            "styles": [{"cut": {"color": "#111111", "weight": 0.5, "dash": []},
                        "projection": {"color": "#222222", "weight": 0.18, "dash": [3.0, 1.5]},
                        "fill": "#333333", "surface": "#445566", "transparency": 0.5}],
            "elements": {"W1": 0}, "hidden": ["F1"]})";
        const auto g = kimcad::Graphics::fromJson(QJsonDocument::fromJson(json).object());
        QCOMPARE(g.purpose(), QString("Working"));
        QCOMPARE(g.currentPen(), 26);
        const kimcad::ElementStyle* s = g.styleOf("W1");
        QVERIFY(s);
        QCOMPARE(s->cut.color, QColor("#111111"));
        QCOMPARE(s->projection.dash, (QVector<double>{3.0, 1.5}));
        QCOMPARE(s->fill, QColor("#333333"));
        QCOMPARE(*s->surface, QColor("#445566"));
        QCOMPARE(*s->transparency, 0.5);
        QVERIFY(!g.styleOf("nope"));
        QVERIFY(g.isHidden("F1"));
        QCOMPARE(g.pen(26).color, QColor("#e02020"));
        QCOMPARE(g.pen(99).color, QColor(Qt::black)); // missing: fallback
        QCOMPARE(g.pen(99).weight, 0.18);
    }
    void badInputGivesAnEmptyState()
    {
        const auto g = kimcad::Graphics::fromJson(QJsonObject{{"ok", false}});
        QVERIFY(g.isEmpty());
        QCOMPARE(g.currentPen(), 23);
        const auto bad = kimcad::Graphics::fromJson(QJsonDocument::fromJson(
            R"({"ok": true, "styles": [], "elements": {"W1": 5}})").object());
        QVERIFY(!bad.styleOf("W1")); // index out of range is ignored
    }
    void pixelsAndPatterns()
    {
        QCOMPARE(kimcad::Graphics::pixels(0.5, false), 1.0f);
        QCOMPARE(kimcad::Graphics::pixels(0.5, true), 2.0f);
        QCOMPARE(kimcad::Graphics::pixels(0.13, true), 1.0f);
        QCOMPARE(kimcad::Graphics::pixels(5.0, true), 6.0f);
        QCOMPARE(kimcad::Graphics::pattern({}), uint16_t(0xFFFF));
        QVERIFY(kimcad::Graphics::pattern({3.0, 1.5}) != 0xFFFF);
        QVERIFY(kimcad::Graphics::pattern({3.0, 1.5}) != 0);
    }
};

QTEST_MAIN(TestGraphics)
#include "test_graphics.moc"
```

- [ ] **Step 2: Build and watch it fail**

Run: `pixi run app-build`
Expected: compile error (`Graphics.h` not found). This is the RED for a new class.

- [ ] **Step 3: Implement `Graphics.cpp`**

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include "Graphics.h"

#include <QJsonArray>

#include <algorithm>
#include <cmath>

namespace kimcad {

namespace {
LineStyle line(const QJsonObject& o)
{
    LineStyle l;
    const QColor c(o.value("color").toString());
    if (c.isValid())
        l.color = c;
    if (o.value("weight").isDouble())
        l.weight = o.value("weight").toDouble();
    for (const auto& d : o.value("dash").toArray())
        if (d.toDouble() > 0)
            l.dash << d.toDouble();
    if (l.dash.size() % 2)
        l.dash.clear();
    return l;
}
}

Graphics Graphics::fromJson(const QJsonObject& state)
{
    Graphics g;
    if (!state.value("ok").toBool())
        return g;
    g.m_purpose = state.value("purpose").toString();
    g.m_currentPen = state.value("current_pen").toInt(23);
    g.m_annotationPen = state.value("annotation_pen").toInt(23);
    for (const auto& v : state.value("styles").toArray()) {
        const QJsonObject o = v.toObject();
        ElementStyle s;
        s.cut = line(o.value("cut").toObject());
        s.projection = line(o.value("projection").toObject());
        const QColor fill(o.value("fill").toString());
        if (fill.isValid())
            s.fill = fill;
        const QColor surface(o.value("surface").toString());
        if (surface.isValid())
            s.surface = surface;
        if (o.value("transparency").isDouble())
            s.transparency = std::clamp(o.value("transparency").toDouble(), 0.0, 1.0);
        g.m_styles << s;
    }
    const QJsonObject elements = state.value("elements").toObject();
    for (auto it = elements.constBegin(); it != elements.constEnd(); ++it) {
        const int i = it.value().toInt(-1);
        if (i >= 0 && i < g.m_styles.size())
            g.m_elements.insert(it.key(), i);
    }
    for (const auto& h : state.value("hidden").toArray())
        g.m_hidden.insert(h.toString());
    const QJsonObject pens = state.value("pens").toObject();
    for (auto it = pens.constBegin(); it != pens.constEnd(); ++it)
        g.m_pens.insert(it.key().toInt(), line(it.value().toObject()));
    return g;
}

const ElementStyle* Graphics::styleOf(const QString& guid) const
{
    const auto it = m_elements.constFind(guid);
    return it == m_elements.constEnd() ? nullptr : &m_styles[*it];
}

LineStyle Graphics::pen(int n) const
{
    return m_pens.value(n, LineStyle{});
}

float Graphics::pixels(double weightMm, bool trueWeights)
{
    return trueWeights ? float(std::clamp(int(std::lround(weightMm * 4.0)), 1, 6)) : 1.0f;
}

uint16_t Graphics::pattern(const QVector<double>& dashMm)
{
    if (dashMm.isEmpty())
        return 0xFFFF;
    // 16 bits, one bit ~ 0.5 mm of the pattern scaled to fit: dashes set, gaps clear.
    double total = 0;
    for (double d : dashMm)
        total += d;
    uint16_t bits = 0;
    int bit = 0;
    for (int i = 0; i < dashMm.size() && bit < 16; ++i) {
        const int n = std::max(1, int(std::lround(dashMm[i] / total * 16.0)));
        for (int k = 0; k < n && bit < 16; ++k, ++bit)
            if (i % 2 == 0)
                bits |= uint16_t(1u << (15 - bit));
    }
    return bits == 0 ? 0xFFFF : bits;
}

} // namespace kimcad
```

Add `src/Graphics.cpp` to `kimcad_core`'s sources in `app/CMakeLists.txt`, and add
`kimcad_test(test_graphics)`.

- [ ] **Step 4: Build and run**

Run: `pixi run app-build && KIMCAD_PYTHON_PATH=$PWD/python pixi run build/app/test_graphics.exe -o out.txt,txt; tail -3 out.txt`
Expected: `Totals: 5 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/src/Graphics.h app/src/Graphics.cpp app/tests/test_graphics.cpp app/CMakeLists.txt
git commit -m "feat(app): Graphics: the resolved purpose (styles, hidden, pens), screen widths and line patterns"
```

---

### Task 7: ElementBatch styles: lines per style, surfaces, hidden by visibility

**Files:**
- Modify: `app/src/ElementBatch.h`, `app/src/ElementBatch.cpp`
- Test: `app/tests/test_element_batch.cpp`

**Interfaces:**
- Consumes: `LineStyle` (Task 6).
- Produces:

```cpp
struct BatchLine { Quantity_Color color; float width = 1.0f; uint16_t pattern = 0xFFFF; };
void setLineStyle(int i, std::optional<BatchLine> line);      // nullopt: the mode's default line
void setSurface(int i, std::optional<Quantity_Color> color, double transparency = 0.0);
void setGraphicsHidden(int i, bool hidden);                  // hidden by the visibility set
bool isGraphicsHidden(int i) const;
int lineGroupCount() const;                                  // groups made by the last Compute (tests)
```

  `isHidden(i)` becomes user, layer **or** graphics hidden. `setHidden(i, false)` (Show all) doesn't
  clear graphics hidden. Surface priority: Compare override (`setColorOverride`) > `setSurface` >
  palette.

- [ ] **Step 1: Failing tests** (read the file's helpers first; it builds a `MeshChunk` with a few boxes)

```cpp
    void linesAreGroupedByStyle()
    {
        Handle(kimcad::ElementBatch) b = new kimcad::ElementBatch(threeBoxes()); // use the file's chunk helper
        b->setLineStyle(0, kimcad::BatchLine{Quantity_Color(1, 0, 0, Quantity_TOC_RGB), 2.0f, 0xFFFF});
        b->setLineStyle(1, kimcad::BatchLine{Quantity_Color(1, 0, 0, Quantity_TOC_RGB), 2.0f, 0xFFFF});
        Handle(Prs3d_Presentation) prs = new Prs3d_Presentation(dummyStructureManager()); // see note
        b->Compute(nullptr, prs, kimcad::ElementBatch::Shaded);
        QCOMPARE(b->lineGroupCount(), 2); // red (0 and 1) and the default (2)
    }
    void graphicsHiddenSurvivesShowAll()
    {
        Handle(kimcad::ElementBatch) b = new kimcad::ElementBatch(threeBoxes());
        b->setGraphicsHidden(1, true);
        QVERIFY(b->isHidden(1));
        b->setHidden(1, false); // Show all
        QVERIFY(b->isHidden(1));
        QCOMPARE(b->visibleCount(), 2);
        b->setGraphicsHidden(1, false);
        QVERIFY(!b->isHidden(1));
        QCOMPARE(b->visibleCount(), 3);
    }
```

Note: if `test_element_batch.cpp` already computes presentations through an `AIS_InteractiveContext`
on an offscreen viewer, display the batch there and read `lineGroupCount()` after `Redisplay`. Use the
file's pattern for computing presentations (read it first); `lineGroupCount` is the observable.

- [ ] **Step 2: Build and run to watch them fail**

Run: `pixi run app-build`
Expected: compile errors (`setLineStyle` missing). RED.

- [ ] **Step 3: Implement**
- Members: `std::vector<std::optional<BatchLine>> m_line; std::vector<std::optional<Quantity_Color>> m_surface; std::vector<double> m_alpha; std::vector<char> m_graphicsHidden; int m_lineGroups = 0;`.
  Size them in the constructor like `m_hidden`.
- `isHidden(i)` returns `m_hidden || m_layerHidden || m_graphicsHidden`.
- `setGraphicsHidden` mirrors `setLayerHidden`: keep `wasHidden`, set the flag, call `updateVisible`.
- `addElement`: `color = fixed ? *fixed : m_override[i].value_or(m_surface[i].value_or(colorFor(type)))`.
- `addLines(prs, defaultColor)`:
  - Bucket the visible elements' segments by key `(r, g, b, width, pattern)`. A missing style uses
    `(defaultColor, 1.0f, 0xFFFF)`.
  - For each bucket, make one `Graphic3d_ArrayOfSegments` and one group. The aspect is a
    `Graphic3d_AspectLine3d(color, Aspect_TOL_SOLID, width)`; when `pattern != 0xFFFF`, call
    `aspect->SetLinePattern(pattern)`.
  - `m_lineGroups = buckets`.
  - In LinesOnly mode, keep the black default for unstyled elements. Styled elements use their style
    in both modes.
- Transparency (`m_alpha`) needs its own group. Draw elements with alpha > 0 in a second
  triangles group with `aspect->SetAlphaMode(Graphic3d_AlphaMode_Blend)`, and front and back
  materials with `SetTransparency(alpha)`. Shaded mode only.

- [ ] **Step 4: Build and run** `test_element_batch` (all functions)
Expected: all pass, including the old ones.

- [ ] **Step 5: Commit**

```bash
git add app/src/ElementBatch.h app/src/ElementBatch.cpp app/tests/test_element_batch.cpp
git commit -m "feat(app): batches draw lines per style, override surfaces and transparency, and hide by visibility"
```

---

### Task 8: Scene and Viewport apply graphics; MainWindow refreshes them

**Files:**
- Modify: `app/src/Scene.h` (a `Graphics graphics; bool trueWeights = false;`),
  `app/src/Viewport.{h,cpp}` (`setGraphics`, `applyGraphics(batch)`, `rebuildSection` per style,
  `AnnotationPrs` by pen, `Annotation::pen`), `app/src/MainWindow.{h,cpp}` (`refreshGraphics()`,
  View › True line weights, calls after load, edits, settings changes),
  `app/src/Preferences.{h,cpp}` (`trueLineWeights` bool, key `true_line_weights`, default false)
- Test: `app/tests/test_main_window.cpp`

**Interfaces:**
- Consumes: `Graphics::fromJson`, the batch setters, the `graphics_state` bridge, and `pen` on annotations.
- Produces:
  - `void Viewport::setGraphics(const Graphics& g, bool trueWeights)`: stores them in the scene,
    applies them to every batch (line, surface, graphics hidden), deselects graphics-hidden elements,
    redisplays, rebuilds poché.
  - `const Graphics& Viewport::graphics() const`.
  - `void MainWindow::refreshGraphics()`: calls `graphics_state`, then `m_viewport->setGraphics(…)`,
    then updates the status strip pen (Task 9).
  - `bool MainWindow::setPurpose(const QString& name)`: calls `set_purpose`, then sets `m_hiddenLayers`
    and `m_lockedLayers` from the reply, `refreshLayers()`, `refreshGraphics()`, regenerates the open
    drawing and sheet tabs, and `refreshProject()` (title `*`).

- [ ] **Step 1: Failing tests** (`test_main_window.cpp`; follow the file's patterns: quiet window, `newProject`, wall tool helpers)

```cpp
    // D73: picking a purpose restyles the view; hidden kinds can't be selected and survive Show all.
    void purposesRestyleAndHide()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        // a wall and a furniture element through the bridge helpers the file already uses
        const QString wall = addWallForTest(w);           // use the file's existing way to add a wall
        QVERIFY(w.setPurpose("Permit"));
        const kimcad::ElementStyle* s = w.viewport()->graphics().styleOf(wall);
        QVERIFY(s);
        QCOMPARE(s->projection.color, QColor("#000000"));
        QVERIFY(w.setPurpose("Working"));
        QCOMPARE(w.viewport()->graphics().styleOf(wall)->projection.color, QColor("#8a6a4a"));
        QVERIFY(w.close());
    }
    void newElementsGetThePurposeStyle()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        QVERIFY(w.setPurpose("Permit"));
        const QString wall = addWallForTest(w);
        QVERIFY(w.viewport()->graphics().styleOf(wall));
        QCOMPARE(w.viewport()->graphics().styleOf(wall)->cut.color, QColor("#000000"));
        QVERIFY(w.close());
    }
    void hiddenKindsAreNotSelectableAndSurviveShowAll()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        const QString wall = addWallForTest(w);
        // a visibility set hiding walls, and a purpose using it, through the bridge
        QVERIFY(w.setGraphicsForTest(R"({"visibility_sets": {"Everything": {"hidden_kinds": [], "rules": []},
            "No walls": {"hidden_kinds": ["walls"], "rules": []}},
            "purposes": {"NW": {"pen_set": "Working", "visibility": "No walls", "overrides": "None", "layers": null}}})"));
        QVERIFY(w.setPurpose("NW"));
        QVERIFY(w.viewport()->graphics().isHidden(wall));
        w.viewport()->selectGuids({wall});
        QVERIFY(w.viewport()->selectedGuids().isEmpty());
        w.viewport()->showAll();
        QVERIFY(w.viewport()->visibleGuids().indexOf(wall) < 0); // use the Viewport's existing visible-list API
        QVERIFY(w.close());
    }
    void trueLineWeightsAreAPreference()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        QVERIFY(!w.preferences().trueLineWeights());
        w.setTrueLineWeights(true);
        QVERIFY(w.preferences().trueLineWeights());
        QVERIFY(w.close());
    }
```

`addWallForTest`, `setGraphicsForTest` and the visible-list call are placeholders for the file's real
helpers. When executing, read `test_main_window.cpp` for how other tests add a wall (e.g. through
`bridge`, or through the wall tool) and which Viewport getter lists visible guids. Add
`bool MainWindow::setGraphics(const QString& changesJson)` as public API: it calls `set_graphics`,
then `refreshGraphics()`. The editors use it too (Task 10), so it isn't test-only.

- [ ] **Step 2: Build and watch it fail**: compile errors for the missing API (RED).

- [ ] **Step 3: Implement**

Viewport:

```cpp
void Viewport::applyGraphics(const Handle(ElementBatch)& batch) const
{
    const Graphics& g = m_scene->graphics;
    for (int i = 0; i < batch->elementCount(); ++i) {
        const QString guid = batch->guid(i);
        batch->setGraphicsHidden(i, g.isHidden(guid));
        const ElementStyle* s = g.styleOf(guid);
        if (!s) {
            batch->setLineStyle(i, std::nullopt);
            batch->setSurface(i, std::nullopt);
            continue;
        }
        const QColor c = s->projection.color;
        batch->setLineStyle(i, BatchLine{Quantity_Color(c.redF(), c.greenF(), c.blueF(), Quantity_TOC_sRGB),
            Graphics::pixels(s->projection.weight, m_scene->trueWeights), Graphics::pattern(s->projection.dash)});
        batch->setSurface(i, s->surface ? std::optional<Quantity_Color>(Quantity_Color(s->surface->redF(),
            s->surface->greenF(), s->surface->blueF(), Quantity_TOC_sRGB)) : std::nullopt, s->transparency.value_or(0.0));
    }
}
```

- `setGraphics` stores, applies to all batches, removes graphics-hidden guids from the selection (as
  `setLayerState` does), `redisplay(all)`, then `rebuildSection()`.
- Wherever a batch is created or reloaded and `applyLayerState(batch)` is called, also call
  `applyGraphics(batch)`. New elements from edits come with the next `refreshGraphics()`.
- `rebuildSection`: group the loops by fill colour and cut line style. `SectionPrs` takes
  `std::vector<SectionPart{loops, QColor fill, LineStyle cut}>`. It makes one fill group and one line
  group per part (width `Graphics::pixels(cut.weight, true)`, so plan cuts stay bold as today: 0.50 →
  2 px; pattern from the dash list). Unstyled elements use today's dark grey fill and 2 px black lines.
- `AnnotationPrs`: `Viewport::Annotation` gains `int pen = 0`. The ink is
  `pen > 0 ? scene graphics pen(pen).color : (kind default as today)`, except markers and rooms, which
  keep their colours. The line width is `Graphics::pixels(weight, trueWeights)`, at least 1.5 for
  dimensions as today. Viewport passes the scene's graphics into the annotation's constructor.

MainWindow:
- `refreshGraphics()` is called at the end of the load-finished handler (where `refreshLayers()` is
  called after a model loads), in `refreshLayers()` itself (edits refresh layers), and after
  `setProjectSettings`.
- `refreshAnnotations` reads `o.value("pen").toInt(0)` into `a.pen`.
- View menu: a checkable "True line weights" action, bound to `m_prefs.trueLineWeights()`. Toggling
  saves the preference, sets `m_scene->trueWeights` through `setTrueLineWeights(bool)`, and calls
  `refreshGraphics()`.
- `setPurpose` as in the Interfaces above. Drawing and sheet tabs regenerate through the existing
  `regenerateDrawing(guid)` for each open drawing view.

- [ ] **Step 4: Build, then run the four new tests and the whole `test_main_window`**
Expected: pass.

- [ ] **Step 5: Run the app self-tests** `pixi run app-test`
Expected: 38/38 (37 + test_graphics). The self-tests count elements and selection; graphics must not
change them under the Working purpose with the Everything visibility.

- [ ] **Step 6: Commit**

```bash
git add app/src app/tests/test_main_window.cpp
git commit -m "feat(app): views draw with the purpose's pens and line types, poché by fill pen, annotations by pen, hidden kinds; View > True line weights"
```

---

### Task 9: PenGrid and the live pen button

**Files:**
- Create: `app/src/PenGrid.h`, `app/src/PenGrid.cpp`
- Modify: `app/src/StatusStrip.{h,cpp}`, `app/src/MainWindow.cpp`, `app/CMakeLists.txt`
- Test: `app/tests/test_graphics.cpp`, `app/tests/test_main_window.cpp`

**Interfaces:**
- Produces:

```cpp
class PenGrid : public QWidget {      // 16 x 16 swatches, pens 1..255 (cell 0 empty)
    Q_OBJECT
public:
    explicit PenGrid(QWidget* parent = nullptr);
    void setPens(const QHash<int, LineStyle>& pens);   // colours and weights shown; tooltip "23 · 0.18 mm · Annotations"
    void setNames(const QHash<int, QString>& names);
    void setCurrent(int pen);
    int current() const;
    static int pick(QWidget* anchor, const QHash<int, LineStyle>& pens, const QHash<int, QString>& names, int current); // popup; 0 = cancelled
signals:
    void penClicked(int pen);
};
```

  In StatusStrip: `void setPen(int number, const QColor& color, double weight)`, `QString penText() const`
  ("23 · 0.18") and the signal `penRequested()`. The button is enabled and shows a colour swatch icon.
  MainWindow handles `penRequested`:
  1. `PenGrid::pick`;
  2. `set_current_pen`;
  3. if exactly annotations are selected, `set_annotation_pen` for each, then `refreshAnnotations`;
  4. `refreshGraphics`.
- `Graphics` gains `QHash<int, LineStyle> pens() const` and `QHash<int, QString> penNames() const`.
  `graphics_state` adds `"pen_names": {n: name}` from the set's pens.

- [ ] **Step 1: Failing tests**

```cpp
    // test_graphics.cpp
    void penGridClicksReportThePen()
    {
        kimcad::PenGrid grid;
        grid.resize(16 * 20, 16 * 20);
        QSignalSpy clicked(&grid, &kimcad::PenGrid::penClicked);
        QTest::mouseClick(&grid, Qt::LeftButton, {}, QPoint(20 * 7 + 10, 20 * 1 + 10)); // row 1, col 7 = pen 23
        QCOMPARE(clicked.count(), 1);
        QCOMPARE(clicked.at(0).at(0).toInt(), 23);
        QTest::mouseClick(&grid, Qt::LeftButton, {}, QPoint(10, 10)); // cell 0: no pen
        QCOMPARE(clicked.count(), 1);
    }
```

```cpp
    // test_main_window.cpp
    void thePenButtonShowsAndSetsTheCurrentPen()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        auto* pen = w.findChild<QToolButton*>("penButton");
        QVERIFY(pen && pen->isEnabled());
        QVERIFY(pen->text().startsWith("23"));
        QVERIFY(w.setCurrentPen(26));
        QVERIFY(pen->text().startsWith("26"));
        QCOMPARE(w.projectSettings().value("current_pen").toInt(), 26); // use the file's settings accessor
        QVERIFY(w.close());
    }
```

  Add `bool MainWindow::setCurrentPen(int)` as public API; the popup handler uses it too.

- [ ] **Step 2: Build, watch it fail** (compile errors: RED).

- [ ] **Step 3: Implement**
- `PenGrid` paints 16×16 cells sized `width()/16` × `height()/16`. Cell `i` is pen `i` for 1..255, and
  cell 0 is left blank. Each cell is filled with the pen colour, with a 1 px border, and the current
  cell gets a thick outline.
  - `mousePressEvent`: `pen = row * 16 + col`; if it is 1..255, set it current, emit `penClicked`.
  - `pick()` builds a `QDialog` (`Qt::Popup`) holding a 320×320 grid at `anchor->mapToGlobal(...)`.
    `penClicked` closes the dialog with that pen; the result is 0 if the dialog is dismissed.
  - Tooltips from `event()` on `QEvent::ToolTip`.
- `StatusStrip`: the pen button is enabled, shows the text `"%1 · %2"` (number, weight) and an icon
  (a 12×12 pixmap filled with the colour). `clicked` → `penRequested`.
- `MainWindow::refreshGraphics` ends with
  `m_status->setPen(g.currentPen(), g.pen(g.currentPen()).color, g.pen(g.currentPen()).weight)`.

- [ ] **Step 4: Build and run both tests, then `pixi run app-test`**. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/src/PenGrid.h app/src/PenGrid.cpp app/src/StatusStrip.h app/src/StatusStrip.cpp app/src/MainWindow.h app/src/MainWindow.cpp app/src/Graphics.h app/src/Graphics.cpp python/kimcad/graphics.py app/CMakeLists.txt app/tests
git commit -m "feat(app): the pen button shows the current pen and picks one from a 16x16 grid; selected annotations take it"
```

---

### Task 10: Editors for pen sets, line types and element styles (part 3a)

**Files:**
- Create: `app/src/GraphicsDialogs.h`, `app/src/GraphicsDialogs.cpp`
- Modify: `app/src/MainWindow.cpp` (Graphics menu between View and Model), `app/CMakeLists.txt`
- Test: `app/tests/test_graphics.cpp`

**Interfaces:**
- Consumes: `graphics_tables` output (`tables`), `PenGrid`, and `MainWindow::setGraphics(json)`.
- Produces: each dialog is constructed from the tables `QJsonObject`, edits a copy, and exposes
  `QJsonObject changes() const`. That returns only the keys it changed: `{"pen_sets": {...}}` for
  example, or `{}`. MainWindow runs `exec()`, then, if accepted and the changes aren't empty,
  `setGraphics(changes)`; an error shows in a message box (quiet: status).
  - `PenSetsDialog(const QJsonObject& tables, QWidget*)`: object names `penSet` (combo), `newSet`,
    `copySet`, `renameSet`, `deleteSet`, `grid` (PenGrid), `penColor` (QPushButton),
    `penWeight` (QDoubleSpinBox 0.05–5.0 step 0.05), `penName` (QLineEdit). Public helpers for tests:
    `selectSet(name)`, `selectPen(n)`, `setPenColor(QColor)`, `copySetAs(name)`, `deleteCurrentSet()`.
  - `LineTypesDialog`: a table `lineTypes` (Name | Pattern "3 1.5"), `addLine`, `deleteLine`. The
    Solid row can't be deleted or edited. A bad pattern turns the cell red and disables OK.
  - `ElementStylesDialog`: a table `elementStyles` with one row per kind. The cut pen, projection pen
    and fill pen cells are buttons that open `PenGrid::pick`; the line type cells are combos of the
    line type names. Plus `resetStyles`. Helpers: `setCutPen(kind, n)`, `setProjectionLine(kind, name)`.

- [ ] **Step 1: Failing tests** (`test_graphics.cpp`; build the tables JSON by running the Python bridge, `PythonEngine` as in `test_python_engine.cpp`, or a small hand-written tables object)

```cpp
    void penSetsDialogReportsOnlyChangedTables()
    {
        const QJsonObject tables = tablesFromBridge(); // PythonEngine::instance().callJson("graphics_tables").object().value("tables")
        kimcad::PenSetsDialog d(tables, nullptr);
        QVERIFY(d.changes().isEmpty());
        d.selectSet("Permit");
        d.selectPen(10);
        d.setPenColor(QColor("#123456"));
        const QJsonObject c = d.changes();
        QCOMPARE(c.keys(), QStringList{"pen_sets"});
        QCOMPARE(c.value("pen_sets").toObject().value("Permit").toObject().value("pens").toObject()
                     .value("10").toObject().value("color").toString(), QString("#123456"));
    }
    void theLastPenSetCannotBeDeleted()
    {
        QJsonObject tables = tablesFromBridge();
        QJsonObject one{{"Only", tables.value("pen_sets").toObject().value("Permit")}};
        tables.insert("pen_sets", one);
        kimcad::PenSetsDialog d(tables, nullptr);
        QVERIFY(!d.findChild<QPushButton*>("deleteSet")->isEnabled());
    }
    void lineTypesRefuseBadPatterns()
    {
        kimcad::LineTypesDialog d(tablesFromBridge(), nullptr);
        QVERIFY(d.setPattern("Dashed", "3 1.5 2"));  // returns validity: false
        // ...: setPattern returns false for an odd count; OK is disabled
        QVERIFY(!d.okEnabled());
        QVERIFY(d.setPattern("Dashed", "4 2"));
        QVERIFY(d.okEnabled());
        QCOMPARE(d.changes().value("line_types").toObject().value("Dashed").toArray().size(), 2);
    }
    void elementStylesChangeAPen()
    {
        kimcad::ElementStylesDialog d(tablesFromBridge(), nullptr);
        d.setCutPen("walls", 7);
        QCOMPARE(d.changes().value("element_styles").toObject().value("walls").toObject()
                     .value("cut").toObject().value("pen").toInt(), 7);
    }
```

Fix up the `lineTypesRefuseBadPatterns` lines when writing them: `setPattern` returns whether the text
is valid. The odd-count case asserts `QVERIFY(!d.setPattern("Dashed", "3 1.5 2"))`.

- [ ] **Step 2: Build and watch it fail** (RED: classes missing).
- [ ] **Step 3: Implement the three dialogs and the menu.**
  - Graphics menu: Pen sets…, Line types…, Element styles…, a separator, Visibility sets…,
    Overrides…, Layer combinations…, Purposes… The last four are wired in Tasks 11–12. Add them now,
    disabled, with "Coming in this step" tooltips, only if Task 11 isn't done in the same session.
    Otherwise add each item with its dialog.
  - Each dialog keeps `m_original` (the incoming table) and `m_table` (the edited copy).
    `changes()` returns `{key: m_table}` when they differ.
  - Pen-set editor:
    - "New" copies the built-in Working set under a new name.
    - "Copy" duplicates the current set.
    - "Rename" and "Delete" go through a QInputDialog; in quiet test mode, use the helper methods.
    - Delete is disabled when one set is left. Purposes that use a deleted or renamed set are updated
      in the same `changes()`, which then also carries `purposes`. Renaming keeps references by
      updating them; deleting points them to the first remaining set.
  - All strings go through `tr()`.
- [ ] **Step 4: Build and run** `test_graphics` + `pixi run app-test`. Expected: pass.
- [ ] **Step 5: Commit**

```bash
git add app/src/GraphicsDialogs.h app/src/GraphicsDialogs.cpp app/src/MainWindow.cpp app/CMakeLists.txt app/tests/test_graphics.cpp
git commit -m "feat(app): Graphics menu: pen sets (16x16 grid), line types and element styles editors"
```

---

### Task 11: Visibility and override editors (part 3b)

**Files:**
- Modify: `app/src/GraphicsDialogs.{h,cpp}`, `app/src/MainWindow.cpp` (menu items)
- Test: `app/tests/test_graphics.cpp`

**Interfaces:**
- `RuleEditor` (a QWidget form used by both dialogs):
  - Condition fields: kind (combo with "Any" + the kinds), IFC class (line edit), property (line
    edit), operator (combo of OPS), value, layer, material.
  - Effect fields: pen, cut pen, projection pen (pen buttons with "—"), line type (combo with "—"),
    fill pen, surface (colour button with "—"), transparency (spin; −1 = none), hide (check).
  - `QJsonObject rule() const` and `void setRule(const QJsonObject&)`. Empty fields are left out.
- `VisibilitySetsDialog(tables)`: the set combo with New, Copy, Rename and Delete (the last can't be
  deleted); a `hiddenKinds` checklist (QListWidget with checkable items, one per kind); a `rules` list
  with Add, Delete and the RuleEditor. Helpers: `selectSet`, `setKindHidden(kind, bool)`,
  `addRule(QJsonObject)`. `changes()` → `visibility_sets` (and `purposes` if references changed).
- `OverridesDialog(tables)`: the set combo with New, Copy, Rename and Delete; a rule list with Up,
  Down, Add, Delete and an enabled tick per item; the RuleEditor. Helpers: `selectSet`, `addRule`,
  `moveRule(from, to)`, `setRuleEnabled(i, bool)`. `changes()` → `override_sets` (+ `purposes`).

- [ ] **Step 1: Failing tests**

```cpp
    void visibilityHidesKindsAndKeepsRules()
    {
        kimcad::VisibilitySetsDialog d(tablesFromBridge(), nullptr);
        d.selectSet("Everything");
        d.setKindHidden("furniture", true);
        d.addRule(QJsonObject{{"name", "Not load-bearing"},
            {"when", QJsonObject{{"property", "LoadBearing"}, {"op", "false"}}}, {"then", QJsonObject{{"hide", true}}}});
        const QJsonObject set = d.changes().value("visibility_sets").toObject().value("Everything").toObject();
        QCOMPARE(set.value("hidden_kinds").toArray(), QJsonArray{"furniture"});
        QCOMPARE(set.value("rules").toArray().size(), 1);
    }
    void overrideRulesKeepTheirOrder()
    {
        kimcad::OverridesDialog d(tablesFromBridge(), nullptr);
        d.selectSet("Fire rating");
        d.moveRule(3, 0);
        d.setRuleEnabled(1, false);
        const QJsonArray rules = d.changes().value("override_sets").toObject().value("Fire rating").toObject()
                                     .value("rules").toArray();
        QCOMPARE(rules.at(0).toObject().value("name").toString(), QString("30 min"));
        QCOMPARE(rules.at(1).toObject().value("enabled").toBool(true), false);
    }
    void ruleEditorRoundTrips()
    {
        kimcad::RuleEditor e;
        const QJsonObject rule{{"name", "x"}, {"when", QJsonObject{{"kind", "walls"}, {"property", "FireRating"},
            {"op", "contains"}, {"value", "60"}}}, {"then", QJsonObject{{"pen", 26}, {"surface", "#e05040"}}}};
        e.setRule(rule);
        QCOMPARE(e.rule(), rule);
    }
```

- [ ] **Step 2: Build, watch it fail** (RED).
- [ ] **Step 3: Implement**, then wire the menu items to `exec()` and `setGraphics(changes)`.
- [ ] **Step 4: Build and run** `test_graphics` + `pixi run app-test`. Expected: pass.
- [ ] **Step 5: Commit**

```bash
git add app/src/GraphicsDialogs.h app/src/GraphicsDialogs.cpp app/src/MainWindow.cpp app/tests/test_graphics.cpp
git commit -m "feat(app): visibility sets and override rules editors"
```

---

### Task 12: Layer combinations, purposes, the bottom-bar switch, views and sheets (part 3c)

**Files:**
- Modify: `app/src/GraphicsDialogs.{h,cpp}` (`LayerCombinationsDialog`, `PurposesDialog`),
  `app/src/StatusStrip.{h,cpp}` (purpose combo + "…" popup), `app/src/MainWindow.{h,cpp}` (wiring,
  views store and apply `purpose`, the sheet purpose submenu handler), `app/src/SheetsPanel.{h,cpp}`
  (context menu "Purpose ▸")
- Test: `app/tests/test_graphics.cpp`, `app/tests/test_main_window.cpp`

**Interfaces:**
- `LayerCombinationsDialog(tables, QStringList layers, QStringList hidden, QStringList locked)`: the set
  combo with New, Copy, Rename and Delete; a table `layerStates` (Layer | Shown | Locked);
  `fromCurrent` copies the hidden and locked layers given. Helpers: `selectSet`, `setShown(layer, bool)`,
  `setLocked(layer, bool)`, `takeCurrent()`. `changes()` → `layer_combinations` (+ `purposes`).
- `PurposesDialog(tables)`: a list `purposes` with New, Copy, Rename and Delete (one must remain);
  four combos `penSetOf`, `visibilityOf`, `overridesOf`, `layersOf` ("—" for none). Helpers:
  `selectPurpose`, `setPieces(pen, vis, ovr, layers)`. `changes()` → `purposes`.
- StatusStrip:
  - `void setPurposes(const QStringList& names, const QString& current)`.
  - Signals `purposeRequested(QString)` and `graphicsPopupRequested()`.
  - Object names `purpose` (QComboBox) and `graphicsButton` ("…").
- MainWindow:
  - `purposeRequested` → `setPurpose`.
  - `graphicsPopupRequested` → a small dialog with four combos editing the current purpose's pieces.
    If the current purpose is built-in and unchanged in the tables (its name is in
    `builtins.purposes` and its entry equals the built-in), first copy it as `"<name> (modified)"`.
    Then `setGraphics({"purposes": ..., "purpose": newName})` and `setPurpose(newName)`.
  - `refreshGraphics` also calls `m_status->setPurposes(...)` from `graphics_tables`.
- Views (D57):
  - Saving a view adds `"purpose": current purpose` to the data JSON MainWindow sends to `save_view`.
  - Applying a view with a `purpose` field calls `setPurpose` before applying its layer states. The
    view's own layer states win, as today.
- Sheets: the SheetsPanel context menu gets a "Purpose" submenu ("Current" plus the purpose names,
  checkable; current value from `graphics_tables.sheet_purposes`). Signal
  `sheetPurposeRequested(number, purpose)` → `bridge("set_sheet_purpose", …)`, then regenerate that
  sheet's tab if open, then `refreshProject()`.

- [ ] **Step 1: Failing tests**

```cpp
    // test_graphics.cpp
    void purposesPickTheirPieces()
    {
        kimcad::PurposesDialog d(tablesFromBridge(), nullptr);
        d.selectPurpose("Permit");
        d.setPieces("Presentation", "No furniture", "None", "All visible");
        const QJsonObject p = d.changes().value("purposes").toObject().value("Permit").toObject();
        QCOMPARE(p.value("pen_set").toString(), QString("Presentation"));
        QCOMPARE(p.value("layers").toString(), QString("All visible"));
    }
    void layerCombinationsTakeTheCurrentLayers()
    {
        kimcad::LayerCombinationsDialog d(tablesFromBridge(), {"A-Wall", "A-Furniture"}, {"A-Furniture"}, {}, nullptr);
        d.selectSet("All visible");
        d.takeCurrent();
        const QJsonObject c = d.changes().value("layer_combinations").toObject().value("All visible").toObject();
        QCOMPARE(c.value("hidden").toArray(), QJsonArray{"A-Furniture"});
    }
```

```cpp
    // test_main_window.cpp
    void theBottomBarSwitchesPurposeAndAppliesItsLayers()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        // a layer combination hiding the active layer's name, and a purpose using it
        const QString layer = w.activeLayerForTest(); // the file's way to read the active layer name
        QVERIFY(w.setGraphics(QStringLiteral(R"({"layer_combinations": {"Hide": {"hidden": ["%1"], "locked": []}},
            "purposes": {"Working": {"pen_set": "Working", "visibility": "Everything", "overrides": "None", "layers": null},
                         "Hide": {"pen_set": "Permit", "visibility": "Everything", "overrides": "None", "layers": "Hide"}}})").arg(layer)));
        auto* combo = w.findChild<QComboBox*>("purpose");
        QVERIFY(combo);
        combo->setCurrentText("Hide");
        QCOMPARE(w.viewport()->graphics().purpose(), QString("Hide"));
        QVERIFY(w.hiddenLayersForTest().contains(layer)); // the file's accessor for m_hiddenLayers, or the layers panel state
        QVERIFY(w.close());
    }
    void viewsRememberTheirPurpose()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        QVERIFY(w.setPurpose("Permit"));
        QVERIFY(w.saveView("Permit plan"));   // the existing save-view API (read the file)
        QVERIFY(w.setPurpose("Working"));
        QVERIFY(w.applyView("Permit plan"));  // the existing apply-view API
        QCOMPARE(w.viewport()->graphics().purpose(), QString("Permit"));
        QVERIFY(w.close());
    }
    void sheetsPrintWithTheirPurpose()
    {
        // newProject, create drawings, new sheet "A01", place a drawing (the file's sheet helpers),
        // set_sheet_purpose A01 Permit through MainWindow::setSheetPurpose("A01", "Permit"),
        // then bridge("sheet_svg", {"A01"}) contains no "#5a3a22" while the current purpose is Working.
    }
```

When executing, write `sheetsPrintWithTheirPurpose` concretely with the file's existing sheet test
helpers. The `…ForTest` names stand for the existing accessors in `test_main_window.cpp`; read them
first. If none exists, add a small public getter that is useful beyond tests (e.g.
`QStringList MainWindow::hiddenLayers() const`).

- [ ] **Step 2: Build, watch it fail** (RED).
- [ ] **Step 3: Implement as described in Interfaces.**
- [ ] **Step 4: Build and run** `test_graphics`, `test_main_window` and `pixi run app-test`. Expected: pass.
- [ ] **Step 5: Commit**

```bash
git add app/src app/tests
git commit -m "feat(app): purposes in the bottom bar (with layer combinations and a graphics popup), views and sheets remember their purpose"
```

---

### Task 13: Documentation, translations and the performance record

**Files:**
- Modify:
  - `docs/decisions.md` (D73);
  - `docs/04-app-features.md` (graphics rows);
  - `docs/13-architect-feedback.md` (a "2026-10-08 (later): pen sets, line types, visibility, purposes (step 3 of 3)" section with a "Try it" table);
  - `docs/14-tool-inventory.md` (§10 rows: pen sets ✅, line types 🟡 = dash patterns, no fill patterns);
  - `docs/11-spike-results.md` (resolution timings on the Clinic from Task 2 Step 5);
  - `app/translations/kimcad_es.ts`.
- Test: `pixi run check-translations`, `pixi run check-spdx`, the full suites.

- [ ] **Step 1:** Regenerate the `.ts` files: `pixi run cmake --build build/app --target update_translations`.
  Then fill in every new Spanish string with a scratch script, the same way as in step 2 (a dict of
  English → Spanish, regex replace of `type="unfinished"`). Purposes and pen-set names are data, not
  UI strings: they stay as stored.
- [ ] **Step 2:** Write D73, one table row in the style of D72. It covers:
  - the pieces and the pen roles;
  - empty tables mean the built-ins;
  - the per-element styles resolved in Python;
  - drawings styled after generation, with weights ÷ sheet k;
  - hidden by visibility as a third kind of hidden;
  - purposes with layer combinations;
  - views and sheets remember their purpose.
- [ ] **Step 3:** Docs 04/13/14/11 as listed.
- [ ] **Step 4:** Run `pixi run check-translations`, `pixi run check-spdx`, `pixi run test`, `pixi run app-test`, `pixi run m4`.
  Expected: all pass.
- [ ] **Step 5: Commit**

```bash
git add docs app/translations
git commit -m "docs+i18n: D73 pen sets, line types, visibility, overrides and purposes; Spanish for the graphics UI"
```

---

## Self-review

- **Spec coverage:**

| Spec section | Task |
|---|---|
| Pieces, built-ins, storage, validation | Tasks 1 and 3 |
| Kinds, rules, resolution and fallbacks | Task 2 |
| Pen-set editor | Task 10 |
| Pen button | Task 9 |
| Line types | Tasks 1 and 10 |
| Element styles | Tasks 1 and 10 |
| Visibility | Tasks 2, 7, 8 and 11 |
| Overrides | Tasks 2 and 11 |
| Layer combinations and purposes | Tasks 3 and 12 |
| Views and sheets | Tasks 4 and 12 |
| Drawings and sheets | Task 4 |
| Plan and 3D | Tasks 7 and 8 |
| Annotations | Tasks 5, 8 and 9 |
| Errors | Tasks 1, 2 and 3 |
| Performance | Task 2 step 5 and Task 13 |
| Testing | spread across the tasks |
| Decision D73 | Task 13 |

- **Placeholders:** several C++ test steps name `…ForTest` helpers and "the file's helpers". Those are
  deliberate pointers to existing test utilities the executor must read. Each such step says what to
  read and gives the fallback (add a small public getter). The test shapes and assertions are fixed.
- **Type consistency:**
  - `LineStyle` and `ElementStyle` (Task 6) are used in Tasks 7, 8 and 9.
  - `BatchLine` belongs to Task 7.
  - `setGraphics(json)` in MainWindow (Task 8) is used by Tasks 10–12.
  - `setPurpose` is in Tasks 8 and 12.
  - `graphics_state` gains `pen_names` in Task 9; Task 9 notes the change in Python.
- **Review focus:** each of the five lines has a test in its owning task (Tasks 2, 3, 4, 8).
