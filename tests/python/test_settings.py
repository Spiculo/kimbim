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
    assert s["ok"] and _defaults(s["settings"]) and s["settings"]["plan_cut_height"] == 1.2
    assert s["settings"]["view_depth"] == 0.5 and s["settings"]["view_depth_levels"] == {}
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
                {"length_decimals": 9}, {"hidden_layers": "A-WALL"}, {"ifc_status_default": "maybe"},
                {"legend_mode": "sometimes"}, {"plan_cut_levels": {"lvl": -1}}, {"plan_symbols": "yes"},
                {"view_depth": -1}, {"view_depth_levels": {"lvl": -1}}, {"area_unit": "ft²"},
                {"angle_decimals": 9}, {"orphan_tags": "x"}, {"level_reference": "datum"},
                {"sea_level": "high"}, {"north_arrow_style": "star"}, {"scale_bar_style": "zigzag"}):
        r = call("set_project_settings", json.dumps(bad))
        assert not r["ok"], bad
    assert _defaults(call("project_settings")["settings"]) and call("state")["dirty"] is False
    assert not call("set_project_settings", "not json")["ok"]


def test_the_default_status_for_unmarked_ifc_elements_is_a_setting():
    assert call("new_project", "x")["ok"]
    assert S.DEFAULTS["ifc_status_default"] == "existing"  # D91
    for ok in ("existing", "demolish", "leave"):
        assert call("set_project_settings", json.dumps({"ifc_status_default": ok}))["ok"], ok


def test_the_builtin_scales_and_user_scales():
    assert call("new_project", "x")["ok"]
    assert S.DEFAULTS["scales"] == [500, 100, 50, 20]  # D93
    assert call("set_project_settings", json.dumps({"scales": [200, 100, 50, 20, 10]}))["ok"]
    for bad in ([], [0], [-5], "100"):
        assert not call("set_project_settings", json.dumps({"scales": bad}))["ok"], bad


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


def _defaults(settings: dict) -> bool:
    """The defaults, but for the pictures a new project's catalogue surfaces carry (D96)."""
    return {k: v for k, v in settings.items() if k != "texture_files"} ==         {k: v for k, v in S.DEFAULTS.items() if k != "texture_files"}


def test_favourites_are_kept_with_the_project():
    """D97: Archicad's Favourites: named tool settings, saved in the project's settings."""
    assert json.loads(b.new_project("Fav"))["ok"]
    fav = {"Brick 3 m": {"tool": "wall", "fields": {"wallHeight": 3.0, "wallReference": "Outside face"}}}
    assert json.loads(b.set_project_settings(json.dumps({"favourites": fav})))["ok"]
    assert json.loads(b.project_settings())["settings"]["favourites"] == fav
    assert not json.loads(b.set_project_settings(json.dumps({"favourites": {"x": {"fields": {}}}})))["ok"]
    assert not json.loads(b.set_project_settings(json.dumps({"favourites": []})))["ok"]


def test_a_settings_file_is_put_in_place_for_the_open_model(tmp_path):
    # D102: the snapshot server renders with the project's settings file
    assert call("new_project", "x")["ok"]
    path = tmp_path / "settings.json"
    path.write_bytes(S.to_bytes({"length_unit": "mm", "future_key": 3}))
    r = call("load_settings_file", str(path))
    assert r["ok"] and r["settings"]["length_unit"] == "mm" and r["settings"]["future_key"] == 3
    assert call("project_settings")["settings"]["plan_cut_height"] == 1.2  # defaults filled in
    assert call("state")["dirty"] is False
    bad = call("load_settings_file", str(tmp_path / "missing.json"))
    assert bad["ok"] is False and "missing.json" in bad["error"]
