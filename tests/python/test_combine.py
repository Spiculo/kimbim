# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice 22: Combine options in the app (M5) — preview the conflicts, choose, load the combined model,
save it as a version with two parents (or discard it)."""
import json

import pytest

from kimcad import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


def names():
    return {w.GlobalId: w.Name for w in b._model.by_type("IfcWall")}


@pytest.fixture
def options(tmp_path):
    """main and "Scheme B" both renamed wall 1 (a conflict); B added a wall, main deleted wall 2."""
    assert call("new_project", "Opciones")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    t = call("wall_types")["types"][0]["guid"]
    w1 = call("create_wall", level, t, 0, 0, 5, 0, 3.0, "", "")["guid"]
    w2 = call("create_wall", level, t, 0, 3, 5, 3, 3.0, "", "")["guid"]
    assert call("enable_versioning", str(tmp_path / "p"), "Initial import")["ok"]
    assert call("create_option", "Scheme B")["ok"]
    call("set_name", g(w1), "Wall B")
    w3 = call("create_wall", level, t, 0, 6, 5, 6, 3.0, "", "")["guid"]
    assert call("save_version", "B: rename and a new wall")["ok"]
    assert call("switch_option", "main")["ok"]
    call("set_name", g(w1), "Wall A")
    assert call("delete_elements", g(w2))["ok"]
    assert call("save_version", "A: rename, delete wall 2")["ok"]
    return {"w1": w1, "w2": w2, "w3": w3}


def test_preview_lists_the_conflict(options):
    p = call("combine_preview", "Scheme B", "{}")
    assert p["ok"] and p["status"] == "merge", p
    (c,) = p["conflicts"]
    assert c["guid"] == options["w1"] and c["attribute"] == "Name"
    assert c["ours_text"] == "Wall A" and c["theirs_text"] == "Wall B" and c["choice"] is None
    assert options["w3"] in p["from_theirs"]  # what the other option brings
    assert p["unresolved"] == [c["id"]]
    chosen = call("combine_preview", "Scheme B", json.dumps({c["id"]: "theirs"}))
    assert chosen["unresolved"] == [] and chosen["conflicts"][0]["choice"] == "theirs"


def test_combine_then_save_a_version_with_two_parents(options):
    c = call("combine_preview", "Scheme B", "{}")["conflicts"][0]
    refused = call("combine_options", "Scheme B", "{}")
    assert not refused["ok"] and "conflict" in refused["error"]
    r = call("combine_options", "Scheme B", json.dumps({c["id"]: "theirs"}))
    assert r["ok"] and r["status"] == "merge", r
    # The combined model is open, not saved yet: both options' work is there.
    assert names() == {options["w1"]: "Wall B", options["w3"]: names()[options["w3"]]}
    st = call("project_state")
    assert st["dirty"] and st["combining"] == "Scheme B"
    assert options["w3"] in r["from_theirs"]
    s = call("save_version", "Combine Scheme B")
    assert s["ok"], s
    top = call("history", 5)["versions"][0]
    assert top["message"].strip() == "Combine Scheme B" and len(top["parents"]) == 2
    assert call("project_state")["combining"] == ""
    assert call("combine_preview", "Scheme B", "{}")["status"] == "up_to_date"
    # The other option catches up without a merge.
    assert call("switch_option", "Scheme B")["ok"]
    ff = call("combine_options", "main", "{}")
    assert ff["ok"] and ff["status"] == "fast_forward"
    assert call("history", 1)["versions"][0]["id"] == top["id"]
    assert not call("project_state")["dirty"]


def test_discarding_a_combination(options):
    head = call("history", 1)["versions"][0]["id"]
    c = call("combine_preview", "Scheme B", "{}")["conflicts"][0]
    assert call("combine_options", "Scheme B", json.dumps({c["id"]: "ours"}))["ok"]
    assert names()[options["w1"]] == "Wall A"
    assert call("discard_changes")["ok"]
    assert call("project_state")["combining"] == "" and call("history", 1)["versions"][0]["id"] == head
    assert options["w3"] not in names()


def test_combining_needs_saved_work(options):
    call("set_name", g(options["w1"]), "Unsaved")
    r = call("combine_options", "Scheme B", "{}")
    assert not r["ok"] and "save" in r["error"]
    assert not call("combine_preview", "Nope", "{}")["ok"]


def test_reopening_the_combined_model_keeps_it_unsaved(options):
    c = call("combine_preview", "Scheme B", "{}")["conflicts"][0]
    r = call("combine_options", "Scheme B", json.dumps({c["id"]: "theirs"}))
    assert call("open_model", r["path"])["ok"]  # what the app's loader does
    st = call("project_state")
    assert st["dirty"] and st["combining"] == "Scheme B"


def test_compare_two_options_by_name(options):
    r = call("compare", "Scheme B", "main")
    assert r["ok"], r
    assert options["w1"] in [x["guid"] for x in r["modified"]]
