# SPDX-License-Identifier: GPL-3.0-or-later
"""Pen sets, line types, element styles, visibility, overrides, layer combinations and purposes
(step 3, D73). The tables live in the project settings (D72); an empty table means the built-ins.
Same protocol as app_bridge for the bridge functions (strings in, JSON out, never raise).
"""
from __future__ import annotations

import colorsys
import copy
import json
import re
import weakref

import ifcopenshell.util.element

KINDS = ("walls", "columns", "beams", "slabs", "roofs", "stairs", "railings", "doors", "windows",
         "coverings", "furniture", "plumbing", "hvac", "electrical", "structure_other", "rooms",
         "annotations", "grids", "other")
TABLES = ("pen_sets", "line_types", "element_styles", "visibility_sets", "override_sets",
          "layer_combinations", "purposes", "renovation_filters", "fill_patterns")
STATUS_KEYS = ("existing", "demolish", "new")  # renovation status (D74)
FILTER_SHOW = ("as_is", "hide", "override")
FILTER_FIELDS = ("pen", "cut_pen", "projection_pen", "line", "fill", "surface", "transparency")
_STATUS_LABELS = {"existing": "Existing", "demolish": "To be demolished", "new": "New"}
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
          27: "Highlight 2", 28: "Highlight 3", 31: "Existing", 32: "Demolition", 33: "Demolition fill"}
# D74: the renovation pens; black and white in the Permit set (permit drawings print in black).
_RENOVATION_PENS = {"default": {31: ("#808080", .18), 32: ("#c09000", .25), 33: ("#f8e8a0", .18)},
                    "Permit": {31: ("#808080", .18), 32: ("#000000", .25), 33: ("#ffffff", .18)}}
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
    "pen_sets": {name: _pen_set({**roles, **_RENOVATION_PENS.get(name, _RENOVATION_PENS["default"])})
                 for name, roles in _SETS.items()},
    "line_types": {"Solid": [], "Dashed": [3.0, 1.5], "Dotted": [0.3, 1.0], "Dash-dot": [4.0, 1.0, 0.5, 1.0],
                   "Centre": [8.0, 1.5, 1.5, 1.5], "Hidden": [1.5, 1.0]},
    "element_styles": _STYLES,
    # D84: fill patterns, hatch-line families in mm on paper (AutoCAD .pat style, see drafting.py).
    "fill_patterns": {
        "Solid": {"solid": True, "lines": []},
        "Empty": {"lines": []},
        "Diagonal": {"lines": [{"angle": 45, "spacing": 2.0}]},
        "Crosshatch": {"lines": [{"angle": 45, "spacing": 2.0}, {"angle": 135, "spacing": 2.0}]},
        "Horizontal": {"lines": [{"angle": 0, "spacing": 2.0}]},
        "Brick": {"lines": [{"angle": 0, "spacing": 2.0}, {"angle": 90, "spacing": 2.0, "shift": 2.0, "dash": [2.0, 2.0]}]},
        # zigzag rows 2 mm high, 2 mm period: two families of dashes that meet at the peaks
        "Insulation": {"lines": [
            {"angle": 63.434949, "spacing": 0.894427, "shift": 1.788854, "dash": [2.236068, 2.236068]},
            {"angle": 116.565051, "spacing": 0.894427, "shift": -1.788854, "dash": [2.236068, 2.236068]}]},
        "Concrete": {"lines": [{"angle": 0, "spacing": 1.2, "shift": 0.6, "dash": [0.1, 1.1]},
                               {"angle": 60, "spacing": 2.5, "shift": 1.0, "dash": [0.4, 2.6]}]},
    },
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
        "Working": {"pen_set": "Working", "visibility": "Everything", "overrides": "None", "layers": None,
                    "renovation": "Everything"},
        "Highlight": {"pen_set": "Highlight", "visibility": "Everything", "overrides": "Fire rating", "layers": None,
                      "renovation": "Everything"},
        "Permit": {"pen_set": "Permit", "visibility": "Architectural", "overrides": "None", "layers": None,
                   "renovation": "Everything"},
        "Presentation": {"pen_set": "Presentation", "visibility": "No furniture", "overrides": "None", "layers": None,
                         "renovation": "Everything"},
        "Demo": {"pen_set": "Demo", "visibility": "Everything", "overrides": "External walls", "layers": None,
                 "renovation": "Everything"},
        "Existing": {"pen_set": "Permit", "visibility": "Architectural", "overrides": "None", "layers": None,
                     "renovation": "Existing plan"},
        "Demolition": {"pen_set": "Permit", "visibility": "Architectural", "overrides": "None", "layers": None,
                       "renovation": "Demolition plan"},
        "New construction": {"pen_set": "Permit", "visibility": "Architectural", "overrides": "None", "layers": None,
                             "renovation": "New plan"},
    },
    # D74, Archicad's built-in renovation filters: each status shown as is, hidden or overridden.
    "renovation_filters": {
        "Everything": {"existing": {"show": "as_is"}, "demolish": {"show": "as_is"}, "new": {"show": "as_is"}},
        "Existing plan": {"existing": {"show": "as_is"}, "demolish": {"show": "as_is"}, "new": {"show": "hide"}},
        "Demolition plan": {"existing": {"show": "as_is"},
                            "demolish": {"show": "override", "pen": 32, "line": "Dashed", "fill": 33,
                                         "surface": "#f0c020"},
                            "new": {"show": "hide"}},
        "New plan": {"existing": {"show": "override", "pen": 31, "fill": 31}, "demolish": {"show": "hide"},
                     "new": {"show": "as_is"}},
        "Planned": {"existing": {"show": "as_is"}, "demolish": {"show": "hide"}, "new": {"show": "as_is"}},
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
    elif key == "fill_patterns":
        for name, p in value.items():
            if not isinstance(p, dict) or not isinstance(p.get("lines", []), list):
                return f"fill pattern {name}: a list of hatch lines"
            if "solid" in p and not isinstance(p["solid"], bool):
                return f"fill pattern {name}: solid is true or false"
            if len(p.get("lines", [])) > 8:
                return f"fill pattern {name}: at most 8 hatch line families"
            for line in p.get("lines", []):
                if not isinstance(line, dict) or not _number(line.get("spacing")) or line["spacing"] < 0.1:
                    return f"fill pattern {name}: each hatch line needs a spacing of at least 0.1 mm"
                if not _number(line.get("angle", 0)) or not _number(line.get("shift", 0)):
                    return f"fill pattern {name}: angle and shift are numbers"
                origin = line.get("origin", [0, 0])
                if not (isinstance(origin, list) and len(origin) == 2 and all(_number(v) for v in origin)):
                    return f"fill pattern {name}: the origin is two numbers"
                d = line.get("dash", [])
                if not isinstance(d, list) or not all(_number(x) and x > 0 for x in d) or len(d) % 2 or len(d) > 12:
                    return f"fill pattern {name}: dashes and gaps come in pairs, above 0"
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
            if "renovation" in v and not isinstance(v["renovation"], str):
                return f"purpose {name}: the renovation filter is a name"
    elif key == "renovation_filters":
        for name, flt in value.items():
            if not isinstance(flt, dict):
                return f"filter {name}: expected an object"
            for status, t in flt.items():
                if status not in STATUS_KEYS:
                    return f"filter {name}: unknown status {status}"
                if not isinstance(t, dict) or t.get("show") not in FILTER_SHOW:
                    return f"filter {name}: show is as_is, hide or override"
                for k, v in t.items():
                    if k == "show":
                        continue
                    if k not in FILTER_FIELDS:
                        return f"filter {name}: unknown field {k}"
                    if k in ("pen", "cut_pen", "projection_pen", "fill") and not _pen_no(v):
                        return f"filter {name}: pens are 1-255"
                    if k == "surface" and not (isinstance(v, str) and _COLOR.match(v)):
                        return f"filter {name}: colour must be #rrggbb"
                    if k == "transparency" and not (_number(v) and 0 <= v <= 1):
                        return f"filter {name}: transparency must be 0-1"
                    if k == "line" and not isinstance(v, str):
                        return f"filter {name}: the line type is a name"
    return None


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
# Kinds whose cut isn't filled (door swings, glazing, room outlines), unless an override gives a fill.
NO_FILL = ("doors", "windows", "rooms", "annotations", "grids")
_SKIP = ("IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcOpeningElement")


def _is(e, cls: str) -> bool:
    try:
        return e.is_a(cls)
    except RuntimeError:  # a class this schema doesn't have
        return False


_kind_by_class: dict[str, str | None] = {}


def _class_kind(element) -> str | None:
    """The kind an IFC class gives (cached per schema and class); None: decided by the element's type."""
    key = element.is_a(True)  # "IFC4.IfcWall": per schema and class
    if key not in _kind_by_class:
        kind = next((k for k, classes in _KIND_CLASSES if any(_is(element, c) for c in classes)), None)
        if kind is None and not _is(element, "IfcDistributionElement"):
            kind = "other"
        _kind_by_class[key] = kind
    return _kind_by_class[key]


def kind_of(element) -> str:
    kind = _class_kind(element)
    if kind is not None:
        return kind
    t = ifcopenshell.util.element.get_type(element)  # IFC2X3 flow elements: by their type
    if t is not None:
        for kind, classes in _KIND_CLASSES:
            if kind in _MEP and any(_is(t, c + "Type") for c in classes):
                return kind
    return "other"


# ---------------------------------------------------------------- rules

class _Facts:
    """An element's properties, layer and materials, read once and only when a rule asks."""

    def __init__(self, element, shared: dict | None = None):
        self.element = element
        self._shared = {} if shared is None else shared  # property indexes, shared by one resolve
        self._layer = False
        self._materials = None
        self._kind = None

    @property
    def kind(self) -> str:
        if self._kind is None:
            self._kind = kind_of(self.element)
        return self._kind

    def prop(self, name: str):
        key = ("property", name)
        if key not in self._shared:
            try:
                self._shared[key] = _property_index(self.element.file, name)
            except Exception:  # an IFC this reader doesn't follow: no properties
                self._shared[key] = {}
        return self._shared[key].get(self.element.id())

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


def _value(v):
    return getattr(v, "wrappedValue", v)


def _property_index(f, name: str) -> dict:
    """{element id: value} for one property name ("Name" or "Pset.Name") across the file: one pass over
    its single values and quantities, then up to the elements through their psets and types. Own
    values win over type values. Much faster than reading every element's psets (the Clinic's Revit
    psets are large)."""
    pset_name, prop = name.split(".", 1) if "." in name else (None, name)
    own, typed = {}, {}
    for cls, attr in (("IfcPropertySingleValue", "NominalValue"), ("IfcPropertyEnumeratedValue", "EnumerationValues"),
                      ("IfcPhysicalSimpleQuantity", None)):
        try:
            candidates = f.by_type(cls)
        except RuntimeError:
            continue
        for p in candidates:
            if p.Name != prop:
                continue
            if attr == "EnumerationValues":  # an enumeration (e.g. Status): its first value
                values = p.EnumerationValues or ()
                value = _value(values[0]) if values else None
            else:
                value = (_value(getattr(p, attr)) if getattr(p, attr) is not None else None) if attr else _value(p[3])
            for owner in f.get_inverse(p):
                if not owner.is_a("IfcPropertySetDefinition") or (pset_name and owner.Name != pset_name):
                    continue
                for user in f.get_inverse(owner):
                    if user.is_a("IfcRelDefinesByProperties"):
                        for o in user.RelatedObjects:
                            own[o.id()] = value
                    elif user.is_a("IfcTypeObject"):
                        for rel in f.get_inverse(user):
                            if rel.is_a("IfcRelDefinesByType"):
                                for o in rel.RelatedObjects:
                                    typed.setdefault(o.id(), value)
    return {**typed, **own}


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
    # Keyed by the model state and the settings; the entry also holds a weak reference to its model, as
    # a new model can reuse a freed one's id().
    key = (id(model), B._current_id() if model is B._model else 0, name,
           json.dumps({k: st.get(k) for k in GRAPHICS_KEYS}, sort_keys=True))
    hit = _cache.get(key)
    if hit is not None and hit[0]() is model:
        return hit[1]
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
    # D74: the renovation filter shows, hides or overrides each status; override rules apply on top.
    filters = effective("renovation_filters", st)
    flt_name = p.get("renovation") if p.get("renovation") in filters else ("Everything" if "Everything" in filters else "")
    flt = filters.get(flt_name) or {}
    flt_active = any(t.get("show") != "as_is" for t in flt.values())
    from . import renovation

    styles, index, elements, hidden = [], {}, {}, []
    shared: dict = {}
    legend_hits: dict = {}  # (source, key) -> [style of the first element it applied to, [guids]]
    for e in _products(model) if model is not None else ():
        facts = _Facts(e, shared)
        if facts.kind in hidden_kinds or any(matches(r.get("when", {}), e, facts) for r in vis_rules):
            hidden.append(e.GlobalId)
            continue
        status = renovation.status_of(e, facts) if flt_active else "new"
        treatment = flt.get(status, {"show": "as_is"}) if flt_active else {"show": "as_is"}
        if treatment.get("show") == "hide":
            hidden.append(e.GlobalId)
            continue
        base = styles_by_kind.get(facts.kind) or builtin_styles[facts.kind]
        cut_pen, proj_pen = base["cut"]["pen"], base["projection"]["pen"]
        cut_line, proj_line, fill_pen = base["cut"]["line"], base["projection"]["line"], base["fill"]
        if facts.kind in NO_FILL:
            fill_pen = None
        surface = transparency = None
        if treatment.get("show") == "override":
            then = treatment
            cut_pen = then.get("cut_pen", then.get("pen", cut_pen))
            proj_pen = then.get("projection_pen", then.get("pen", proj_pen))
            if "line" in then:
                cut_line = proj_line = then["line"]
            fill_pen = then.get("fill", fill_pen)
            surface, transparency = then.get("surface", surface), then.get("transparency", transparency)
        rule = next((r for r in rules if matches(r.get("when", {}), e, facts)), None)  # the first match wins
        if rule is not None:
            then = rule.get("then", {})
            if then.get("hide"):
                hidden.append(e.GlobalId)
                continue
            cut_pen = then.get("cut_pen", then.get("pen", cut_pen))
            proj_pen = then.get("projection_pen", then.get("pen", proj_pen))
            if "line" in then:
                cut_line = proj_line = then["line"]
            fill_pen = then.get("fill", fill_pen)
            surface, transparency = then.get("surface", surface), then.get("transparency", transparency)
        style = {"cut": _line(pens, line_types, cut_pen, cut_line),
                 "projection": _line(pens, line_types, proj_pen, proj_line),
                 "fill": pen(pens, fill_pen)["color"] if fill_pen is not None else None,
                 "surface": surface, "transparency": transparency}
        k = json.dumps(style, sort_keys=True)
        if k not in index:
            index[k] = len(styles)
            styles.append(style)
        elements[e.GlobalId] = index[k]
        if flt_active:
            legend_hits.setdefault(("renovation", status), [index[k], []])[1].append(e.GlobalId)
        if rule is not None:
            legend_hits.setdefault(("override", rule.get("name", "")), [index[k], []])[1].append(e.GlobalId)
    legend, members = [], []
    reno = sorted((k, v) for k, v in legend_hits.items() if k[0] == "renovation")
    reno.sort(key=lambda kv: STATUS_KEYS.index(kv[0][1]))
    if any(flt.get(k[1], {}).get("show") == "override" for k, _ in reno):  # as-is rows only explain an override
        for (src, key), (style_no, guids) in reno:
            legend.append({"label": _STATUS_LABELS[key], "source": src, "key": key, "style": style_no,
                           "override": flt.get(key, {}).get("show") == "override"})
            members.append(guids)
    for (src, key), (style_no, guids) in legend_hits.items():
        if src == "override":
            legend.append({"label": key, "source": src, "key": key, "style": style_no, "override": True})
            members.append(guids)
    ann = styles_by_kind.get("annotations") or builtin_styles["annotations"]
    out = {"purpose": name, "purposes": list(purposes), "pen_set": set_name, "visibility": vis_name or "", "overrides": ovr_name or "",
           "pens": {str(n): pen(pens, n) for n in range(1, 256)},
           "pen_names": {n: p["name"] for n, p in pens.items() if isinstance(p, dict) and p.get("name")},
           "current_pen": st.get("current_pen", 23), "annotation_pen": ann["projection"]["pen"],
           "styles": styles, "elements": elements, "hidden": hidden,
           "renovation": flt_name, "legend": legend, "legend_members": members}
    if len(_cache) > 8:
        _cache.clear()
    _cache[key] = (weakref.ref(model) if model is not None else (lambda: None), out)
    return out


# ---------------------------------------------------------------- bridge

def _fail(message: str) -> str:
    from . import app_bridge as B

    return B._dump({"ok": False, "error": message})


def graphics_state() -> str:
    from . import app_bridge as B
    from . import settings as S

    st = S.current()
    res = {k: v for k, v in resolve(settings=st).items() if k != "legend_members"}  # members stay in Python
    return B._dump({"ok": True, **res, "hidden_layers": st.get("hidden_layers", []),
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
    flts = effective("renovation_filters", st)
    for name, p in purposes.items():
        if p["pen_set"] not in pens:
            return f"purpose {name} uses a pen set that doesn't exist: {p['pen_set']}"
        if p["visibility"] not in vis:
            return f"purpose {name} uses a visibility set that doesn't exist: {p['visibility']}"
        if p["overrides"] not in ovr:
            return f"purpose {name} uses an override set that doesn't exist: {p['overrides']}"
        if p.get("layers") is not None and p["layers"] not in combos:
            return f"purpose {name} uses a layer combination that doesn't exist: {p['layers']}"
        if p.get("renovation") is not None and p["renovation"] not in flts:
            return f"purpose {name} uses a renovation filter that doesn't exist: {p['renovation']}"
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


# ---------------------------------------------------------------- drawings

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
            dm = re.search(r'data-dash="([^"]*)"', attrs)  # a drafting shape's line type (D84), mm on paper
            dash = [float(v) for v in dm.group(1).split()] if dm else []
            tag = tag[:-1] + _stroke({"color": p["color"], "weight": p["weight"], "dash": dash}, k) + f' color="{p["color"]}">'
        elif guid in elements:
            st = styles[elements[guid]]
            if re.search(r'class="projection\b', attrs):
                tag = tag[:-1] + _stroke(st["projection"], k) + ' fill="none">'
            else:
                fill = f' fill="{st["fill"]}" fill-rule="evenodd"' if st["fill"] else ' fill="none"'
                tag = tag[:-1] + _stroke(st["cut"], k) + fill + ">"
        else:  # drawn but not styled by the purpose (e.g. a site's terrain): a plain line
            plain = {"color": FALLBACK_PEN["color"], "weight": FALLBACK_PEN["weight"], "dash": []}
            tag = tag[:-1] + _stroke(plain, k) + ' fill="none">'
        out.append(tag)
        pos = m.end()
    out.append(svg[pos:])
    svg = "".join(out)
    # Annotation text is filled in its pen's colour (the overlay writes black text).
    svg = re.sub(r'(<g data-kind="annotation"[^>]*color="(#[0-9a-fA-F]{6})"[^>]*>)(.*?)(</g>)',
                 lambda m: m.group(1) + m.group(3).replace('fill="#000000"', f'fill="{m.group(2)}"')
                 .replace('data-fill="pen"', f'fill="{m.group(2)}"') + m.group(4),
                 svg, flags=re.S)
    # D84: a fill's background takes its background pen's colour.
    svg = re.sub(r'data-fill-pen="(\d+)"', lambda m: f'fill="{pen(pens, int(m.group(1)))["color"]}"', svg)
    for group in ("kimcad-overlay", "kimcad-drafting"):
        svg = svg.replace(f'class="{group}" fill="none" stroke="#000000" stroke-width="0.18"',
                          f'class="{group}" fill="none" stroke="#000000" stroke-width="{_fmt(0.18 / k)}"', 1)
    return svg


# ---------------------------------------------------------------- legends (D74)

LEGEND_EMPTY = "Everything is drawn with its element styles"
_ROW, _TITLE, _SWATCH_W, _SWATCH_H = 7.0, 8.0, 10.0, 5.0


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def legend_svg(resolved: dict, guids=None) -> tuple:
    """The legend as SVG in paper mm (top-left 0,0): a title, then a swatch and a label per entry;
    returns (body, width, height). `guids`: only entries that apply to one of these elements (a sheet's
    drawings). Renovation rows shown as is only explain an overridden one: without one they are left out."""
    styles = resolved.get("styles", [])
    rows = [e for e, members in zip(resolved.get("legend", []), resolved.get("legend_members", []))
            if guids is None or guids.intersection(members)]
    if not any(e.get("override") for e in rows if e["source"] == "renovation"):
        rows = [e for e in rows if e["source"] != "renovation"]
    parts = ['<text x="0" y="5" font-size="4" font-family="sans-serif">Legend</text>']
    y = _TITLE
    if not rows:
        parts.append(f'<text x="0" y="{y + 4:g}" font-size="3" font-family="sans-serif">{_xml(LEGEND_EMPTY)}</text>')
        return "\n".join(parts), 1.8 * len(LEGEND_EMPTY), y + _ROW
    longest = 0
    for e in rows:
        st = styles[e["style"]]
        fill = st.get("fill") or st.get("surface") or "none"
        parts.append(f'<g class="kimcad-legend-row"><rect x="0" y="{y:g}" width="{_SWATCH_W:g}" height="{_SWATCH_H:g}" '
                     f'fill="{fill}"{_stroke(st["cut"], 1.0)}/>'
                     f'<text x="{_SWATCH_W + 3:g}" y="{y + 4:g}" font-size="3" font-family="sans-serif">'
                     f'{_xml(e["label"])}</text></g>')
        longest = max(longest, len(e["label"]))
        y += _ROW
    return "\n".join(parts), _SWATCH_W + 3 + 1.8 * longest, y
