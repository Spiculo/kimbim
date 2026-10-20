# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 2: project settings (defaults, validation, dirty, merge, units)."""
import json

from kimbim import app_bridge as b
from kimbim import settings as S


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def test_a_new_model_has_the_default_settings():
    assert call("new_project", "x")["ok"]
    s = call("project_settings")
    assert s["ok"] and s["settings"] == S.DEFAULTS and s["settings"]["plan_cut_height"] == 1.2
    assert call("state")["dirty"] is False


def test_changing_a_setting_marks_the_model_unsaved_and_unknown_keys_are_kept():
    assert call("new_project", "x")["ok"]
    r = call("set_project_settings", json.dumps({"plan_cut_height": 1.1, "future_key": {"a": 1}}))
    assert r["ok"] and r["dirty"] is True
    assert call("project_settings")["settings"]["future_key"] == {"a": 1}
    assert call("state")["dirty"] is True
    S.mark_saved()
    assert call("state")["dirty"] is False


def test_bad_values_are_refused_and_change_nothing():
    assert call("new_project", "x")["ok"]
    for bad in ({"plan_cut_height": -1}, {"drawing_scale": 0}, {"sheet_paper": "B5"}, {"length_unit": "ft"},
                {"length_decimals": 9}, {"hidden_layers": "A-WALL"}, {"area_unit": "ft²"},
                {"angle_decimals": 9}, {"orphan_tags": "x"}):
        r = call("set_project_settings", json.dumps(bad))
        assert not r["ok"], bad
    assert call("project_settings")["settings"] == S.DEFAULTS and call("state")["dirty"] is False
    assert not call("set_project_settings", "not json")["ok"]


def test_the_area_unit_formats_areas():
    assert call("new_project", "x")["ok"]
    assert call("set_project_settings", json.dumps({"area_unit": "cm²"}))["ok"]
    assert S.format_area(1.5) == "15000.00 cm²"  # D92
    assert S.format_area(1.5, unit=False) == "15000.00"


def test_bytes_round_trip_is_canonical():
    d = {**S.DEFAULTS, "hidden_layers": ["A-WALL"], "zz": 1}
    assert S.from_bytes(S.to_bytes(d)) == d
    assert S.to_bytes(d) == S.to_bytes(dict(reversed(list(d.items()))))  # key order doesn't matter
    assert S.from_bytes(None) == S.DEFAULTS and S.from_bytes(b"garbage") == S.DEFAULTS


def test_merge_takes_each_sides_change_and_ours_on_a_conflict():
    base = {**S.DEFAULTS}
    ours = {**base, "plan_cut_height": 1.1, "drawing_scale": 50}
    theirs = {**base, "sheet_paper": "A3", "drawing_scale": 200}
    merged, conflicts = S.merge(base, ours, theirs)
    assert merged["plan_cut_height"] == 1.1 and merged["sheet_paper"] == "A3" and merged["drawing_scale"] == 50
    assert conflicts == ["drawing_scale"]
    assert S.changed_keys(base, merged) == ["drawing_scale", "plan_cut_height", "sheet_paper"]


def test_lengths_follow_the_unit_and_decimals():
    S.load({"length_unit": "mm", "length_decimals": 0})
    assert S.format_length(3.5) == "3500 mm" and S.format_length(3.5, unit=False) == "3500"
    S.load({"length_unit": "cm", "length_decimals": 1})
    assert S.format_length(3.5) == "350.0 cm"
    S.load(None)
    assert S.format_length(3.5) == "3.50 m"


def test_new_dimensions_are_labelled_in_the_project_unit():
    assert call("new_project", "x")["ok"]
    assert call("set_project_settings", json.dumps({"length_unit": "mm", "length_decimals": 0}))["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    r = call("add_annotation", level, "dimension", json.dumps([[0, 0], [3.5, 0], [3.5, 1]]), "")
    assert r["ok"], r
    texts = [a["text"] for a in call("annotations", level)["annotations"] if a["kind"] == "dimension"]
    assert texts == ["3500"]
