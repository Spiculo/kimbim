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
