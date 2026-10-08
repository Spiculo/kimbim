# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 2: project settings are versioned with the model (D72)."""
import json

import pytest

from kimcad import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def versioned(tmp_path):
    assert call("new_project", "Ajustes")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    t = call("wall_types")["types"][0]["guid"]
    wall = call("create_wall", level, t, 0, 0, 5, 0, 3.0, "", "")["guid"]
    r = call("enable_versioning", str(tmp_path / "p"), "Initial import")
    assert r["ok"], r
    return {"folder": tmp_path / "p", "wall": wall}


def test_a_settings_change_alone_is_a_version(versioned):
    assert call("set_project_settings", json.dumps({"plan_cut_height": 1.1}))["ok"]
    assert call("project_state")["unversioned"] is True
    assert call("version_changes")["settings"] == ["plan_cut_height"]
    r = call("save_version", "Lower cut")
    assert r["ok"], r
    assert call("project_state")["unversioned"] is False
    first = call("history", 10)["versions"][-1]["id"]
    assert call("compare", first, "WORKING")["settings"] == ["plan_cut_height"]
    assert not call("save_version", "again")["ok"]  # nothing changed


def test_going_back_to_a_version_brings_back_its_settings(versioned):
    assert call("create_option", "B")["ok"]
    assert call("set_project_settings", json.dumps({"drawing_scale": 50}))["ok"]
    assert call("save_version", "B at 1:50")["ok"]
    assert call("switch_option", "main")["ok"]
    assert call("project_settings")["settings"]["drawing_scale"] == 100
    assert call("switch_option", "B")["ok"]
    assert call("project_settings")["settings"]["drawing_scale"] == 50


def test_switching_options_is_refused_with_settings_not_versioned(versioned):
    assert call("create_option", "B")["ok"]
    assert call("set_project_settings", json.dumps({"sheet_paper": "A3"}))["ok"]
    r = call("switch_option", "main")
    assert not r["ok"] and "version" in r["error"]


def test_combining_options_merges_settings_by_key(versioned):
    assert call("create_option", "B")["ok"]
    assert call("set_project_settings", json.dumps({"sheet_paper": "A3", "drawing_scale": 200}))["ok"]
    call("set_name", json.dumps([versioned["wall"]]), "B wall")
    assert call("save_version", "B")["ok"]
    assert call("switch_option", "main")["ok"]
    assert call("set_project_settings", json.dumps({"plan_cut_height": 1.0, "drawing_scale": 50}))["ok"]
    t = call("wall_types")["types"][0]["guid"]
    level = call("storeys")["storeys"][0]["guid"]
    call("create_wall", level, t, 0, 4, 5, 4, 3.0, "", "")
    assert call("save_version", "main")["ok"]
    r = call("combine_options", "B", "{}")
    assert r["ok"] and r["status"] == "merge", r
    s = call("project_settings")["settings"]
    assert (s["sheet_paper"], s["plan_cut_height"], s["drawing_scale"]) == ("A3", 1.0, 50)
    assert any("drawing_scale" in w for w in r["warnings"])
    assert call("project_state")["unversioned"] is True
    assert call("save_version", "Combined")["ok"]
    assert call("project_settings")["settings"]["sheet_paper"] == "A3"


def test_old_projects_without_settings_open_with_the_defaults(versioned):
    from kimcad import versioning
    from kimcad.layout import SETTINGS_PATH

    project = versioning._project
    assert SETTINGS_PATH in project._head_entries()  # enable_versioning stores them
    assert project.settings_at("HEAD") is not None
