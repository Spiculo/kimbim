# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 3 (D73): pen sets, line types, element styles, visibility, overrides, purposes."""
import json
import re

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


import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.type

from kimcad.testing import _reset_owner, _set_owner, build_model


def _model(schema="IFC4"):
    f = ifcopenshell.file(schema=schema)  # kept alive by the caller: entities don't hold their file
    if schema == "IFC2X3":
        _set_owner(f)  # IFC2X3 needs an owner history; tests reset it in a finally
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
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
    try:
        _check_ifc2x3_flow_by_type()
    finally:
        _reset_owner()  # the IFC2X3 owner callbacks are global


def _check_ifc2x3_flow_by_type():
    f = _model("IFC2X3")
    seg = _el(f, "IfcFlowSegment")
    t = ifcopenshell.api.root.create_entity(f, ifc_class="IfcPipeSegmentType")
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


def test_doors_windows_and_rooms_have_no_cut_fill():
    """Door swings and room outlines must not be filled (the serializer's CSS did this before D73)."""
    f = _model()
    door, room, wall = _el(f, "IfcDoor"), _el(f, "IfcSpace"), _el(f, "IfcWall")
    r = g.resolve("Working", model=f)
    assert r["styles"][r["elements"][door.GlobalId]]["fill"] is None
    assert r["styles"][r["elements"][room.GlobalId]]["fill"] is None
    assert r["styles"][r["elements"][wall.GlobalId]]["fill"] == "#b8a898"
    out = g.style_svg(f'<g class="IfcDoor" ifc:guid="{door.GlobalId}"><path d="M0,0"/></g>', r)
    assert 'fill="none"' in out and "fill-rule" not in out


def test_graphics_state_names_the_pens():
    r = call("graphics_state")
    assert r["pen_names"]["23"] == "Annotations" and r["pen_names"]["10"] == "Walls cut"
    assert "30" not in r["pen_names"]  # free pens have no name
