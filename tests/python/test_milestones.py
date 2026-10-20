# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice 20: milestones (annotated tags), object history, before/after, deleting a design option."""
import json

import pytest

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


@pytest.fixture
def project(tmp_path):
    """Versioned: two walls ("Initial import"), then the first renamed ("Rename"), then moved ("Move")."""
    assert call("new_project", "Hitos")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    t = call("wall_types")["types"][0]["guid"]
    w1 = call("create_wall", level, t, 0, 0, 5, 0, 3.0, "", "")["guid"]
    w2 = call("create_wall", level, t, 0, 3, 5, 3, 3.0, "", "")["guid"]
    assert call("enable_versioning", str(tmp_path / "p"), "Initial import")["ok"]
    call("set_name", g(w1), "South wall")
    assert call("save_version", "Rename")["ok"]
    call("move_elements", g(w1), 0, -1, 0)
    assert call("save_version", "Move")["ok"]
    return {"level": level, "w1": w1, "w2": w2}


def versions():
    return {v["message"]: v for v in call("history", 10)["versions"]}


def test_milestones_tag_versions(project):
    r = call("create_milestone", "Concept", "Concept design for the client")
    assert r["ok"], r
    m = call("milestones")["milestones"]
    assert [x["name"] for x in m] == ["Concept"] and m[0]["id"] == versions()["Move"]["id"]
    assert m[0]["message"] == "Concept design for the client"
    assert versions()["Move"]["milestones"] == ["Concept"] and versions()["Rename"]["milestones"] == []
    assert not call("create_milestone", "Concept", "")["ok"]  # names are unique
    assert not call("create_milestone", " ", "")["ok"]
    # A milestone marks a saved version: with unsaved changes it asks to save first.
    call("set_name", g(project["w2"]), "North wall")
    r = call("create_milestone", "Schematic design", "")
    assert not r["ok"] and "save" in r["error"]
    assert call("save_version", "North")["ok"]
    assert call("create_milestone", "Schematic design", "SD set")["ok"]
    assert [x["name"] for x in call("milestones")["milestones"]] == ["Concept", "Schematic design"]
    # Milestones can be compared like versions, by name.
    assert call("compare", "Concept", "Schematic design")["modified"][0]["guid"] == project["w2"]
    assert call("delete_milestone", "Concept")["ok"]
    assert [x["name"] for x in call("milestones")["milestones"]] == ["Schematic design"]


def test_object_history(project):
    h = call("element_history", project["w1"])
    assert h["ok"], h
    assert [(v["message"], v["change"]) for v in h["versions"]] == [
        ("Move", "modified"), ("Rename", "modified"), ("Initial import", "added")]
    h2 = call("element_history", project["w2"])
    assert [(v["message"], v["change"]) for v in h2["versions"]] == [("Initial import", "added")]
    # A property edit (its property set is a separate record) shows in the element's history.
    assert call("set_property", g(project["w2"]), "Pset_WallCommon", "FireRating", json.dumps("EI 60"))["ok"]
    assert call("save_version", "Fire rating")["ok"]
    assert call("element_history", project["w2"])["versions"][0]["message"] == "Fire rating"
    # Unsaved changes show as the first entry.
    call("set_name", g(project["w2"]), "North wall")
    assert call("element_history", project["w2"])["versions"][0]["change"] == "unsaved"


def test_before_after(project):
    v = versions()
    r = call("before_after", project["w1"], v["Initial import"]["id"], "WORKING")
    assert r["ok"], r
    rows = {row["field"]: row for row in r["rows"]}
    assert rows["Name"]["before"] != "South wall" and rows["Name"]["after"] == "South wall" and rows["Name"]["changed"]
    assert rows["Position"]["changed"] and rows["Position"]["after"].startswith("0.000, -1.000")
    assert not rows["Class"]["changed"] and rows["Class"]["after"] == "IfcWall"
    assert rows["Level"]["after"] == "Level 1"
    same = call("before_after", project["w2"], v["Rename"]["id"], v["Move"]["id"])
    assert same["ok"] and not any(row["changed"] for row in same["rows"])
    # An element that did not exist yet.
    t = call("wall_types")["types"][0]["guid"]
    w3 = call("create_wall", project["level"], t, 0, 6, 5, 6, 3.0, "", "")["guid"]
    new = call("before_after", w3, v["Move"]["id"], "WORKING")
    assert new["ok"] and new["before_exists"] is False and new["after_exists"] is True


def test_delete_option(project):
    assert call("create_option", "Scheme B")["ok"]
    assert not call("delete_option", "Scheme B")["ok"]  # the current one
    assert not call("delete_option", "main")["ok"]
    assert call("switch_option", "main")["ok"]
    r = call("delete_option", "Scheme B")
    assert r["ok"], r
    assert call("options")["options"] == ["main"]
    assert not call("delete_option", "Scheme B")["ok"]
