# SPDX-License-Identifier: GPL-3.0-or-later
"""Saved versions of library objects (D100): named project types that stay when unused, never take
unsaved values, survive a save and reopen in IFC4 and IFC2X3, and still work when their object is gone
from the library."""
import json

import ifcopenshell
import ifcopenshell.validate
import pytest

from kimbim import app_bridge as b
from kimbim import library, objversions


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def project():
    assert call("new_project", "Versions")["ok"]
    yield call("storeys")["storeys"][0]["guid"]
    library.load_office()


def validate(f):
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, logger, express_rules=True)
    return [str(s["message"])[:200] for s in logger.statements]


BLOCK = {
    "format": "kimbim-object/1", "id": "block", "name": {"en": "Block", "es": "Bloque"}, "category": "furniture",
    "ifc": {"IFC4": ["IfcFurnitureType", "NOTDEFINED", None]},
    "params": [{"key": "width", "kind": "length", "label": "Width", "default": 0.4},
               {"key": "depth", "kind": "length", "label": "Depth", "default": 0.4},
               {"key": "height", "kind": "length", "label": "Height", "default": 0.45}],
    "parts": [{"id": "body", "box": {"dx": "width", "dy": "depth", "dz": "height"}}],
}


def test_save_place_and_list_a_version(project):
    r = call("save_object_version", "chair", "Dining", json.dumps({"width": 0.5, "back": "slats"}))
    assert r["ok"], r
    vs = call("object_versions", "chair")["versions"]
    assert [v["name"] for v in vs] == ["Dining"] and vs[0]["values"]["width"] == 0.5 and vs[0]["uses"] == 0
    assert vs[0]["id"] == r["id"] and vs[0]["type"] == r["type"] and vs[0]["source"] == "project"
    t = b._model.by_guid(r["type"])
    assert t.Name == "Dining"                         # schedules count by name
    assert objversions.is_saved(t) and objversions.find_version(r["id"]) == t
    p = call("place_object", project, "chair", "", 0, 0, 0, "", r["id"])
    assert p["type"] == r["type"]
    assert call("object_versions", "chair")["versions"][0]["uses"] == 1


def test_unsaved_values_never_join_a_named_version(project):
    v = call("save_object_version", "chair", "Dining", json.dumps({"width": 0.5}))
    p = call("place_object", project, "chair", json.dumps({"width": 0.5}), 0, 0, 0)
    assert p["type"] != v["type"]
    k = call("save_object_version", "chair", "Kitchen", json.dumps({"width": 0.5}))
    assert k["type"] not in (v["type"], p["type"])   # identical values, separate types


def test_an_unused_saved_version_stays(project):
    v = call("save_object_version", "chair", "Dining", "")
    p = call("place_object", project, "chair", "", 0, 0, 0, "", v["id"])
    assert call("delete_elements", json.dumps([p["guid"]]))["ok"]
    assert b._model.by_guid(v["type"])               # unnamed types go when unused; saved ones stay


def test_names_are_unique_per_object_and_validated(project):
    assert call("save_object_version", "chair", "Dining", "")["ok"]
    clash = call("save_object_version", "chair", " dining ", json.dumps({"width": 0.6}))
    assert clash["ok"] is False and clash["exists"]
    replaced = call("save_object_version", "chair", "Dining", json.dumps({"width": 0.6}), "1")
    assert replaced["ok"] and replaced["id"] == clash["exists"]
    assert call("object_versions", "chair")["versions"][0]["values"]["width"] == 0.6
    assert call("save_object_version", "table", "Dining", "")["ok"]   # another object may reuse the name
    assert call("save_object_version", "chair", "   ", "")["ok"] is False
    assert call("save_object_version", "chair", "x" * 256, "")["ok"] is False


def test_values_that_do_not_build_save_nothing(project, tmp_path):
    folder = tmp_path / "office"
    folder.mkdir()
    fragile = {**BLOCK, "id": "fragile", "parts": [{"id": "body", "box": {"dx": "width", "dy": "depth",
                                                                         "dz": "0.1 / (height - 0.5)"}}]}
    (folder / "fragile.kimobj").write_text(json.dumps(fragile), encoding="utf-8")
    library.load_office(str(folder))
    r = call("save_object_version", "office:fragile", "Bad", json.dumps({"height": 0.5}))  # divides by zero
    assert r["ok"] is False and "division by zero" in r["error"]
    assert call("object_versions", "office:fragile")["versions"] == []
    assert not b._model.by_type("IfcFurnitureType")


def test_rename_and_delete(project):
    v = call("save_object_version", "chair", "Dining", "")
    assert call("save_object_version", "chair", "Bar", "")["ok"]
    assert call("rename_version", v["id"], " bar ")["ok"] is False   # names stay unique
    assert call("rename_version", v["id"], "Dinner")["ok"]
    assert b._model.by_guid(v["type"]).Name == "Dinner"
    p = call("place_object", project, "chair", "", 0, 0, 0, "", v["id"])
    used = call("delete_version", v["id"])
    assert used["ok"] is False and used["used"] == 1
    call("delete_elements", json.dumps([p["guid"]]))
    assert call("delete_version", v["id"])["ok"]
    assert [x["name"] for x in call("object_versions", "chair")["versions"]] == ["Bar"]


def test_each_version_edit_is_one_undo_step(project):            # Review Focus 1
    v = call("save_object_version", "chair", "Dining", "")
    assert call("undo")["ok"] and call("object_versions", "chair")["versions"] == []
    assert call("redo")["ok"]
    assert call("rename_version", v["id"], "Dinner")["ok"]
    assert call("undo")["ok"] and call("object_versions", "chair")["versions"][0]["name"] == "Dining"
    assert b._model.by_guid(v["type"]).Name == "Dining"
    assert call("delete_version", v["id"])["ok"]
    assert call("undo")["ok"] and len(call("object_versions", "chair")["versions"]) == 1
    assert call("save_object_version", "chair", "Dining", json.dumps({"width": 0.6}), "1")["ok"]
    assert call("undo")["ok"] and call("object_versions", "chair")["versions"][0]["values"]["width"] != 0.6


def test_the_last_used_is_a_project_setting(project):
    assert call("object_versions", "chair")["last"] == {}
    v = call("save_object_version", "chair", "Dining", "")
    assert call("set_last_used", "chair", json.dumps({"version": v["id"]}))["ok"]
    assert call("set_last_used", "table", json.dumps({"values": {"width": 1.2}}))["ok"]
    assert call("object_versions", "chair")["last"] == {"version": v["id"]}
    assert call("project_settings")["settings"]["object_last_used"]["table"] == {"values": {"width": 1.2}}
    assert call("set_last_used", "chair", json.dumps({"colour": "red"}))["ok"] is False
    assert call("set_project_settings", json.dumps({"object_last_used": {"chair": 3}}))["ok"] is False


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_versions_survive_save_and_reopen(tmp_path, schema):    # Review Focus 2
    from kimbim import testing

    try:
        if schema == "IFC4":
            assert call("new_project", "Versions")["ok"]
        else:
            f = testing.build_model("IFC2X3", walls=1)
            f.write(str(tmp_path / "x3.ifc"))
            assert call("open_model", str(tmp_path / "x3.ifc"))["ok"]
        storey = call("storeys")["storeys"][0]["guid"]
        v = call("save_object_version", "chair", "Dining", json.dumps({"width": 0.5}))
        assert v["ok"], v
        assert call("place_object", storey, "chair", "", 0, 0, 0, "", v["id"])["ok"]
        path = tmp_path / f"versions-{schema}.ifc"
        assert call("save", str(path))["ok"]
        assert call("open_model", str(path))["ok"]
        [again] = call("object_versions", "chair")["versions"]
        assert (again["id"], again["name"], again["type"], again["uses"]) == (v["id"], "Dining", v["type"], 1)
        assert again["values"]["width"] == 0.5
        assert validate(b._model) == []
    finally:
        testing._reset_owner()


def test_a_version_of_an_object_gone_from_the_library_still_works(project, tmp_path):  # Review Focus 4
    folder = tmp_path / "office"
    folder.mkdir()
    (folder / "block.kimobj").write_text(json.dumps(BLOCK), encoding="utf-8")
    library.load_office(str(folder))
    v = call("save_object_version", "office:block", "Low", json.dumps({"height": 0.3}))
    assert v["ok"], v
    assert call("place_object", project, "office:block", "", 0, 0, 0, "", v["id"])["ok"]
    library.load_office()  # gone from the library
    listed = call("object_versions", "office:block")
    assert listed["ok"] and listed["default"]["height"] == 0.45
    assert [x["name"] for x in listed["versions"]] == ["Low"] and listed["versions"][0]["values"]["height"] == 0.3
    p = call("place_object", project, "office:block", "", 1, 0, 0, "", v["id"])
    assert p["ok"] and p["type"] == v["type"]
    assert call("save_object_version", "office:block", "Tall", json.dumps({"height": 0.9}))["ok"]
    assert call("object_versions", "nosuchobject")["ok"] is False
