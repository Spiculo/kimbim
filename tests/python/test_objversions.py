# SPDX-License-Identifier: GPL-3.0-or-later
"""Saved versions of library objects (D100): named project types that stay when unused, never take
unsaved values, survive a save and reopen in IFC4 and IFC2X3, and still work when their object is gone
from the library."""
import json

import ifcopenshell
import ifcopenshell.api.owner.settings
import ifcopenshell.util.element
import ifcopenshell.validate
import numpy
import pytest

from kimbim import app_bridge as b
from kimbim import library, objects, objversions


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


def test_a_stale_last_used_version_means_default(project):
    v = call("save_object_version", "chair", "Dining", "")
    assert call("set_last_used", "chair", json.dumps({"version": v["id"]}))["ok"]
    assert call("delete_version", v["id"])["ok"]
    assert call("object_versions", "chair")["last"] == {}       # gone from the project: Default
    assert call("set_last_used", "chair", json.dumps({"values": {"width": 0.5}}))["ok"]
    assert call("object_versions", "chair")["last"] == {"values": {"width": 0.5}}


def test_modify_all_changes_every_placement_and_keeps_the_version(project):
    v = call("save_object_version", "chair", "Dining", "")
    a = call("place_object", project, "chair", "", 0, 0, 0, "", v["id"])["guid"]
    c = call("place_object", project, "chair", "", 1, 0, 0, "", v["id"])["guid"]
    s = call("object_settings_of", json.dumps([a]))
    assert s["version"] == v["id"] and s["uses"] == 2 and s["shared"]
    assert call("apply_object_settings", json.dumps([a]), json.dumps({"width": 0.55}), "auto")["shared"]
    assert call("apply_object_settings", json.dumps([a]), json.dumps({"width": 0.55}), "all")["ok"]
    for g in (a, c):
        t = ifcopenshell.util.element.get_type(b._model.by_guid(g))
        assert t.GlobalId == v["type"] and t.Name == "Dining"


def test_modify_all_never_merges_named_types(project):
    d = call("save_object_version", "chair", "Dining", json.dumps({"width": 0.5}))
    k = call("save_object_version", "chair", "Kitchen", json.dumps({"width": 0.6}))
    a = call("place_object", project, "chair", "", 0, 0, 0, "", k["id"])["guid"]
    assert call("apply_object_settings", json.dumps([a]), json.dumps({"width": 0.5}), "all")["ok"]
    assert ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId == k["type"]
    assert b._model.by_guid(d["type"])


def test_create_a_new_type_moves_only_the_selection(project):
    v = call("save_object_version", "chair", "Dining", "")
    a = call("place_object", project, "chair", "", 0, 0, 0, "", v["id"])["guid"]
    c = call("place_object", project, "chair", "", 1, 0, 0, "", v["id"])["guid"]
    r = call("apply_object_settings", json.dumps([a]), json.dumps({"arms": True}), "new", "Armchair")
    assert r["ok"]
    assert ifcopenshell.util.element.get_type(b._model.by_guid(a)).Name == "Armchair"
    assert ifcopenshell.util.element.get_type(b._model.by_guid(c)).Name == "Dining"
    assert call("undo")["ok"] and ifcopenshell.util.element.get_type(b._model.by_guid(a)).Name == "Dining"


def test_an_unshared_type_applies_directly_and_a_mixed_selection_fails(project):
    a = call("place_object", project, "chair", "", 0, 0, 0)["guid"]
    assert call("apply_object_settings", json.dumps([a]), json.dumps({"legs": 3, "layout": "circle"}), "auto")["ok"]
    t = call("place_object", project, "table", "", 2, 0, 0)["guid"]
    assert call("object_settings_of", json.dumps([a, t]))["ok"] is False


def test_assign_version(project):
    v = call("save_object_version", "chair", "Dining", "")
    a = call("place_object", project, "chair", "", 0, 0, 0)["guid"]
    old = ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId
    assert call("assign_version", json.dumps([a]), v["id"])["ok"]
    assert ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId == v["type"]
    with pytest.raises(RuntimeError):
        b._model.by_guid(old)                       # the unnamed type left unused is gone


def test_values_that_do_not_build_are_refused(project):        # Review Focus 5 (bridge)
    a = call("place_object", project, "chair", "", 0, 0, 0)["guid"]
    before = ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId
    r = call("apply_object_settings", json.dumps([a]), json.dumps({"width": -1}), "all")
    assert r["ok"] is False
    assert ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId == before


def test_settings_of_an_unnamed_type_and_the_edge_cases(project):
    a = call("place_object", project, "chair", json.dumps({"width": 0.5}), 0, 0, 0)["guid"]
    s = call("object_settings_of", json.dumps([a]))
    assert s["ok"] and s["key"] == "chair" and s["version"] is None and s["values"]["width"] == 0.5
    assert (s["selected"], s["uses"], s["shared"]) == (1, 1, False)
    assert call("object_settings_of", "[]")["ok"] is False
    v = call("save_object_version", "chair", "Dining", "")
    clash = call("apply_object_settings", json.dumps([a]), "{}", "new", " dining ")
    assert clash["ok"] is False and clash["exists"] == v["id"]
    assert call("apply_object_settings", json.dumps([a]), "{}", "sideways")["ok"] is False
    assert call("apply_object_settings", json.dumps([a]), json.dumps({"colour": "red"}), "all")["ok"] is False
    assert call("apply_object_settings", json.dumps([a]), json.dumps({"width": "nan"}), "all")["ok"] is False
    assert call("assign_version", json.dumps([a]), "nosuchid")["ok"] is False
    t = call("place_object", project, "table", "", 2, 0, 0)["guid"]
    assert call("assign_version", json.dumps([t]), v["id"])["ok"] is False   # a version of another object


def test_modify_all_of_an_unnamed_type_joins_an_identical_unnamed_one(project):
    a = call("place_object", project, "chair", "", 0, 0, 0)["guid"]
    c = call("place_object", project, "chair", json.dumps({"width": 0.5}), 1, 0, 0)["guid"]
    old = ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId
    assert call("apply_object_settings", json.dumps([a]), json.dumps({"width": 0.5}), "all")["ok"]
    ta = ifcopenshell.util.element.get_type(b._model.by_guid(a))
    assert ta == ifcopenshell.util.element.get_type(b._model.by_guid(c))
    with pytest.raises(RuntimeError):
        b._model.by_guid(old)
    assert call("undo")["ok"]
    assert ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId == old


def test_a_whole_type_parameter_edit_of_a_saved_version_regenerates_it(project):
    d = call("save_object_version", "chair", "Dining", json.dumps({"width": 0.5}))
    k = call("save_object_version", "chair", "Kitchen", json.dumps({"width": 0.6}))
    a = call("place_object", project, "chair", "", 0, 0, 0, "", k["id"])["guid"]
    loose = call("place_object", project, "chair", json.dumps({"width": 0.5}), 1, 0, 0)["type"]  # unnamed, same values
    assert call("set_object_parameter", json.dumps([a]), "Width", "0.5", "type")["ok"]
    assert b._model.by_guid(loose)
    t = ifcopenshell.util.element.get_type(b._model.by_guid(a))
    assert t.GlobalId == k["type"] and t.Name == "Kitchen" and b._model.by_guid(d["type"])


# ---------------------------------------------------------------- the office library (Task 3)

def test_move_to_library_and_use_in_another_project(project, tmp_path):
    library.load_office(str(tmp_path))
    v = call("save_object_version", "chair", "Café", json.dumps({"seat_shape": "round"}))
    assert call("move_version_to_library", v["id"])["ok"]
    assert (tmp_path / "kimbim-versions.ifc").exists()
    mine = call("object_versions", "chair")["versions"]
    assert len(mine) == 1 and mine[0]["source"] == "project"      # listed once
    assert call("new_project", "Other")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    office = [x for x in call("object_versions", "chair")["versions"] if x["source"] == "office"]
    assert office and office[0]["id"] == v["id"]
    p = call("place_object", storey, "chair", "", 0, 0, 0, "", v["id"])
    t = b._model.by_guid(p["type"])
    assert t.Name == "Café"
    assert call("place_object", storey, "chair", "", 1, 0, 0, "", v["id"])["type"] == p["type"]
    library.load_office()
    assert call("place_object", storey, "chair", "", 2, 0, 0, "", v["id"])["type"] == p["type"]  # self-contained


def test_office_copy_renamed_on_clash(project, tmp_path):
    library.load_office(str(tmp_path))
    v = call("save_object_version", "chair", "Café", "")
    call("move_version_to_library", v["id"])
    assert call("new_project", "Other")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    call("save_object_version", "chair", "Café", json.dumps({"width": 0.6}))
    p = call("place_object", storey, "chair", "", 0, 0, 0, "", v["id"])
    assert b._model.by_guid(p["type"]).Name == "Café (office)"


def test_replacing_an_office_version_asks(project, tmp_path):
    library.load_office(str(tmp_path))
    v = call("save_object_version", "chair", "Café", "")
    call("move_version_to_library", v["id"])
    assert call("move_version_to_library", v["id"])["exists"]
    assert call("move_version_to_library", v["id"], "1")["ok"]


def test_move_to_library_without_a_usable_folder_fails_cleanly(project, tmp_path):  # Review Focus 3
    v = call("save_object_version", "chair", "Café", "")
    library.load_office("")
    assert call("move_version_to_library", v["id"])["ok"] is False
    library.load_office(str(tmp_path / "missing"))
    assert call("move_version_to_library", v["id"])["ok"] is False
    assert call("object_versions", "chair")["versions"][0]["name"] == "Café"


def test_office_versions_file_details(project, tmp_path):
    library.load_office(str(tmp_path))
    v = call("save_object_version", "chair", "Café", json.dumps({"width": 0.55}))
    assert call("move_version_to_library", v["id"])["ok"]
    # the versions file is the office's own versions, not fixed ifc: types; a plain office IFC still loads
    assert not [k for k in library._office if k.startswith("ifc:")]
    entry = library._office_versions[v["id"]]
    assert entry["name"] == "Café" and entry["object"] == "chair" and entry["values"]["width"] == 0.55
    assert entry["hash"] and entry["path"].endswith("kimbim-versions.ifc")
    office = ifcopenshell.open(str(tmp_path / "kimbim-versions.ifc"))
    assert office.schema == b._model.schema and not validate(office)
    mine = call("object_versions", "chair")["versions"]
    assert mine[0]["office_id"] == v["id"]
    # another version of the same name and another id: "exists" too
    assert call("new_project", "Other")["ok"]
    w = call("save_object_version", "chair", "café", "")
    assert call("move_version_to_library", w["id"])["exists"] == v["id"]
    assert call("move_version_to_library", w["id"], "1")["ok"]
    assert list(library._office_versions) == [w["id"]]


def test_placing_an_office_version_is_one_undo_step(project, tmp_path):
    library.load_office(str(tmp_path))
    v = call("save_object_version", "chair", "Café", "")
    call("move_version_to_library", v["id"])
    assert call("new_project", "Other")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    p = call("place_object", storey, "chair", "", 0, 0, 0, "", v["id"])
    assert objversions.find_version(v["id"]).GlobalId == p["type"]
    assert call("place_object", storey, "table", "", 0, 0, 0, "", v["id"])["ok"] is False  # not a table version
    assert call("undo")["ok"]
    assert objversions.find_version(v["id"]) is None
    assert not validate(b._model)


def test_assigning_an_office_version_copies_it_in(project, tmp_path):
    """Edit mode lists the office's versions too: picking one moves the selection to a project copy of it."""
    library.load_office(str(tmp_path))
    v = call("save_object_version", "chair", "Café", json.dumps({"width": 0.55}))
    call("move_version_to_library", v["id"])
    assert call("new_project", "Other")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    a = call("place_object", storey, "chair", "", 0, 0, 0)["guid"]
    assert call("assign_version", json.dumps([a]), v["id"])["ok"]
    t = ifcopenshell.util.element.get_type(b._model.by_guid(a))
    assert objversions.find_version(v["id"]) == t and t.Name == "Café"
    assert json.loads(ifcopenshell.util.element.get_pset(t, library.PSET)["Parameters"])["width"] == 0.55
    assert call("assign_version", json.dumps([a]), "no-such-id")["ok"] is False
    assert call("undo")["ok"]                                # one step: the copy goes too
    assert objversions.find_version(v["id"]) is None
    assert not validate(b._model)


def test_plain_office_ifc_types_still_load(project, tmp_path):
    library.load_office(str(tmp_path))
    call("place_object", project, "chair", "", 0, 0, 0)
    b._model.write(str(tmp_path / "plain.ifc"))      # an unnamed library type: a fixed ifc: entry
    library.load_office(str(tmp_path))
    assert [k for k in library._office if k.startswith("ifc:")] and not library._office_versions


def test_office_versions_in_ifc2x3_and_a_schema_mismatch(tmp_path):
    from kimbim import testing

    try:
        f = testing.build_model("IFC2X3", walls=1)
        f.write(str(tmp_path / "x3.ifc"))
        office = tmp_path / "office"
        office.mkdir()
        library.load_office(str(office))
        assert call("open_model", str(tmp_path / "x3.ifc"))["ok"]
        storey = call("storeys")["storeys"][0]["guid"]
        v = call("save_object_version", "chair", "Café", json.dumps({"width": 0.55}))
        assert call("move_version_to_library", v["id"])["ok"]
        written = ifcopenshell.open(str(office / "kimbim-versions.ifc"))
        assert written.schema == "IFC2X3" and validate(written) == []
        assert call("delete_version", v["id"])["ok"]            # gone from the project: placed from the office
        p = call("place_object", storey, "chair", "", 0, 0, 0, "", v["id"])
        assert b._model.by_guid(p["type"]).Name == "Café" and validate(b._model) == []
        assert call("new_project", "Other")["ok"]                # an IFC4 project, an IFC2X3 versions file
        w = call("save_object_version", "chair", "Bar", "")
        r = call("move_version_to_library", w["id"])
        assert r["ok"] is False and "IFC2X3" in r["error"]
        assert [x["source"] for x in call("object_versions", "chair")["versions"]] == ["project", "office"]
    finally:
        testing._reset_owner()
        library.load_office()


def test_move_to_library_when_the_file_cannot_be_written(project, tmp_path):  # Review Focus 3
    library.load_office(str(tmp_path))
    (tmp_path / "kimbim-versions.ifc").mkdir()        # in the way: the versions file cannot be written
    v = call("save_object_version", "chair", "Café", "")
    r = call("move_version_to_library", v["id"])
    assert r["ok"] is False and "cannot write" in r["error"]
    assert not (tmp_path / "kimbim-versions.ifc.tmp").exists() and not library._office_versions
    assert call("object_versions", "chair")["versions"][0]["source"] == "project"


# ---------------------------------------------------------------- Update from library (Task 4)

def _ps(guid):
    return ifcopenshell.util.element.get_pset(b._model.by_guid(guid), library.PSET)


def test_an_outdated_saved_version_updates_in_place(project, tmp_path):
    folder = tmp_path / "office"
    folder.mkdir()
    (folder / "block.kimobj").write_text(json.dumps(BLOCK), encoding="utf-8")
    library.load_office(str(folder))
    x1 = call("save_object_version", "office:block", "X1", json.dumps({"width": 0.5}))           # unused
    x2 = call("save_object_version", "office:block", "X2", json.dumps({"height": 0.7}))          # placed
    loose = call("place_object", project, "office:block", "", 2, 0, 0)                            # unsaved
    p = call("place_object", project, "office:block", "", 0, 0, 0, "", x2["id"])
    assert call("library_updates", "") == {"ok": True, "outdated": 0, "versions": 0}
    v2 = json.loads(json.dumps(BLOCK))
    v2["params"][0]["default"] = 0.6                     # the office edits its block
    (folder / "block.kimobj").write_text(json.dumps(v2), encoding="utf-8")
    library.load_office(str(folder))
    u = call("library_updates", "")
    assert u["ok"] and u["versions"] == 2 and u["outdated"] == 2   # both placements count, as today
    assert call("library_updates", json.dumps([p["guid"]]))["versions"] == 1   # only the selection's types
    r = call("update_from_library", "")
    assert r["ok"], r
    assert set(r["geometry"]["changed"]) >= {p["guid"], loose["guid"]}
    new_hash = library._hash_of(library.get("office:block"))
    for v, name, values in ((x1, "X1", {"width": 0.5}), (x2, "X2", {"height": 0.7})):
        t = b._model.by_guid(v["type"])                  # same GlobalId
        ps = _ps(v["type"])
        assert t.Name == name and ps[objversions.VERSION_ID] == v["id"] and ps[objversions.VERSION_NAME] == name
        assert ps["DefinitionHash"] == new_hash
        assert all(json.loads(ps["Parameters"])[k] == pytest.approx(x) for k, x in values.items())
    assert ifcopenshell.util.element.get_type(b._model.by_guid(p["guid"])).GlobalId == x2["type"]
    assert _ps(ifcopenshell.util.element.get_type(b._model.by_guid(loose["guid"])).GlobalId)["DefinitionHash"] == new_hash
    assert call("library_updates", "") == {"ok": True, "outdated": 0, "versions": 0}
    assert not call("update_from_library", "")["ok"]
    assert call("undo")["ok"]                            # one step
    assert call("library_updates", "") == {"ok": True, "outdated": 2, "versions": 2}
    assert not validate(b._model)


def test_a_selection_updates_only_its_types(project, tmp_path):
    folder = tmp_path / "office"
    folder.mkdir()
    (folder / "block.kimobj").write_text(json.dumps(BLOCK), encoding="utf-8")
    library.load_office(str(folder))
    x1 = call("save_object_version", "office:block", "X1", "")
    x2 = call("save_object_version", "office:block", "X2", json.dumps({"height": 0.7}))
    p = call("place_object", project, "office:block", "", 0, 0, 0, "", x2["id"])
    v2 = json.loads(json.dumps(BLOCK))
    v2["params"][0]["default"] = 0.6
    (folder / "block.kimobj").write_text(json.dumps(v2), encoding="utf-8")
    library.load_office(str(folder))
    assert call("update_from_library", json.dumps([p["guid"]]))["ok"]
    assert call("library_updates", "")["versions"] == 1          # X1 is still outdated
    assert _ps(x1["type"])["DefinitionHash"] != _ps(x2["type"])["DefinitionHash"]


def test_an_office_copy_follows_its_office_version(project, tmp_path):
    library.load_office(str(tmp_path))
    v = call("save_object_version", "chair", "Café", "")
    assert call("move_version_to_library", v["id"])["ok"]
    assert call("library_updates", "")["versions"] == 0          # the original matches the office
    assert call("new_project", "Copying")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    p = call("place_object", storey, "chair", "", 0, 0, 0, "", v["id"])
    assert call("library_updates", "")["versions"] == 0
    copying = tmp_path / "copying.ifc"
    assert call("save", str(copying))["ok"]
    # a third project's "Café" (the same id) gets width 0.6 and replaces the office version
    assert call("new_project", "Third")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    q = call("place_object", storey, "chair", "", 0, 0, 0, "", v["id"])
    assert call("apply_object_settings", json.dumps([q["guid"]]), json.dumps({"width": 0.6}), "all")["ok"]
    assert call("move_version_to_library", v["id"], "1")["ok"]
    assert call("open_model", str(copying))["ok"]
    u = call("library_updates", "")
    assert u["versions"] == 1 and u["outdated"] == 1
    assert call("update_from_library", "")["ok"]
    t = ifcopenshell.util.element.get_type(b._model.by_guid(p["guid"]))
    ps = _ps(t.GlobalId)
    assert t.GlobalId == p["type"] and t.Name == "Café" and ps[objversions.VERSION_ID] == v["id"]
    assert json.loads(ps["Parameters"])["width"] == pytest.approx(0.6)
    assert call("library_updates", "") == {"ok": True, "outdated": 0, "versions": 0}


# ---------------------------------------------------------------- the dialog's preview (Task 5)

def _preview_meta(parts):
    return json.loads(parts[0])


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_object_preview_builds_in_a_scratch_model(tmp_path, schema):
    from kimbim import testing

    try:
        if schema == "IFC4":
            assert call("new_project", "Preview")["ok"]
        else:
            f = testing.build_model("IFC2X3", walls=1)
            f.write(str(tmp_path / "x3.ifc"))
            assert call("open_model", str(tmp_path / "x3.ifc"))["ok"]
            testing._reset_owner()  # the app's: no user set (the scratch model brings its own)
        model, history, count = b._model, len(b._model.history), len(list(b._model))
        get_user = ifcopenshell.api.owner.settings.get_user
        parts = b.object_preview("chair", "")
        assert parts is not None and len(parts) == 4
        assert len(parts[1]) > 0 and len(parts[2]) > 0           # vertices and triangles
        meta = _preview_meta(parts)
        assert meta["guids"] == [library.PREVIEW_GUID] and meta["palette"]  # one element, coloured parts
        assert b.object_preview("chair", '{"width": -1}') is None
        assert b._model is model and len(b._model.history) == history and len(list(b._model)) == count
        assert ifcopenshell.api.owner.settings.get_user is get_user
    finally:
        testing._reset_owner()


def test_object_preview_reports_why_values_do_not_build(project):
    assert call("object_preview_error", "chair", "") == {"ok": True}
    bad = call("object_preview_error", "chair", json.dumps({"width": 0}))
    assert bad["ok"] is False and "Width" in bad["error"]
    assert call("object_preview_error", "nothing", "")["ok"] is False


def test_object_preview_of_a_version_and_its_values(project):
    v = call("save_object_version", "chair", "Wide", json.dumps({"width": 0.8}))
    narrow = b.object_preview("chair", json.dumps({"width": 0.4}))
    wide = b.object_preview("chair", "", v["id"])
    span = lambda parts: max(numpy.frombuffer(parts[1], "<f4")[0::3]) - min(numpy.frombuffer(parts[1], "<f4")[0::3])  # noqa: E731
    assert span(wide) == pytest.approx(0.8, abs=1e-3) and span(narrow) == pytest.approx(0.4, abs=1e-3)
    assert b.object_preview("chair", "", "no-such-version") is None


def test_group_headings_have_a_spanish_form():
    obj = objects.ObjectDef({**BLOCK, "id": "grouped", "params": [
        {**BLOCK["params"][0], "group": {"en": "Size", "es": "Tamaño"}},
        {**BLOCK["params"][1], "group": "Legs"}, BLOCK["params"][2]]}, "office")
    listed = {p["key"]: p for p in library._param_listing(obj, obj.values())}
    assert (listed["width"]["group"], listed["width"]["group_es"]) == ("Size", "Tamaño")
    assert (listed["depth"]["group"], listed["depth"]["group_es"]) == ("Legs", "")   # the app translates it
    assert (listed["height"]["group"], listed["height"]["group_es"]) == (None, "")
    with pytest.raises(objects.ObjectError):
        objects.ObjectDef({**BLOCK, "id": "bad", "params": [{**BLOCK["params"][0], "group": {"es": "Tamaño"}}]}, "office")


def test_form_and_symbol_of_a_version_use_its_own_definition(project, tmp_path):
    folder = tmp_path / "office"
    folder.mkdir()
    (folder / "block.kimobj").write_text(json.dumps(BLOCK), encoding="utf-8")
    library.load_office(str(folder))
    v = call("save_object_version", "office:block", "Low", json.dumps({"height": 0.3}))
    newer = {**BLOCK, "params": BLOCK["params"] + [{"key": "top", "kind": "length", "label": "Top", "default": 0.02}]}
    (folder / "block.kimobj").write_text(json.dumps(newer), encoding="utf-8")
    library.load_office(str(folder))                          # the library's definition moved on
    keys = lambda form: [p["key"] for p in form["params"]]  # noqa: E731
    assert "top" in keys(call("object_form", "office:block", ""))
    mine = call("object_form", "office:block", "", v["id"])
    assert "top" not in keys(mine) and mine["values"]["height"] == 0.3
    assert call("object_form", "office:block", json.dumps({"height": 0.5}), v["id"])["values"]["height"] == 0.5
    library.load_office()                                     # gone from the library
    gone = call("object_form", "office:block", "", v["id"])
    assert keys(gone) == ["width", "depth", "height"] and gone["name"] == "Block"
    assert call("object_symbol", "office:block", "", v["id"])["width"] == pytest.approx(0.4)
    assert b.object_preview("office:block", json.dumps({"height": 0.6}), v["id"]) is not None
    assert call("object_preview_error", "office:block", json.dumps({"width": 0}), v["id"])["ok"] is False
    assert call("object_form", "office:block", "", "no-such-version")["params"] == []


# ---------------------------------------------------------------- D100 final review

def test_default_moves_the_selection_to_an_unnamed_type(project):
    """Edit mode's Default (objversions.DEFAULT) moves the selection to the unnamed type of the object's
    default values, found or made as placing finds it; the saved version stays untouched."""
    v = call("save_object_version", "chair", "Dining", json.dumps({"width": 0.5}))
    a = call("place_object", project, "chair", "", 0, 0, 0, "", v["id"])["guid"]
    c = call("place_object", project, "chair", "", 1, 0, 0, "", v["id"])["guid"]
    r = call("assign_version", json.dumps([a]), objversions.DEFAULT)
    assert r["ok"], r
    ta = ifcopenshell.util.element.get_type(b._model.by_guid(a))
    assert not objversions.is_saved(ta) and r["type"] == ta.GlobalId
    assert json.loads(_ps(ta.GlobalId)["Parameters"]) == library.get("chair").values()
    tv = b._model.by_guid(v["type"])                                  # the saved version: untouched
    assert json.loads(_ps(v["type"])["Parameters"])["width"] == 0.5 and tv.Name == "Dining"
    assert ifcopenshell.util.element.get_type(b._model.by_guid(c)) == tv
    d = call("place_object", project, "chair", "", 2, 0, 0)          # a plain Default placement: the same type
    assert d["type"] == ta.GlobalId
    assert call("assign_version", json.dumps([c]), objversions.DEFAULT)["type"] == ta.GlobalId
    assert b._model.by_guid(v["type"])                                # unused, still a saved version
    assert call("undo")["ok"] and ifcopenshell.util.element.get_type(b._model.by_guid(c)) == tv
    t = call("place_object", project, "table", "", 4, 0, 0)["guid"]
    assert call("assign_version", json.dumps([a, t]), objversions.DEFAULT)["ok"] is False  # two objects


def test_settings_of_an_outdated_unnamed_placement_use_its_type(project, tmp_path):
    """object_settings_of gives the type as the dialog's source ("type:<GlobalId>"): the form, symbol and
    preview use the definition stored on the type, as apply_object_settings does."""
    folder = tmp_path / "office"
    folder.mkdir()
    (folder / "block.kimobj").write_text(json.dumps(BLOCK), encoding="utf-8")
    library.load_office(str(folder))
    p = call("place_object", project, "office:block", json.dumps({"height": 0.3}), 0, 0, 0)
    newer = {**BLOCK, "params": BLOCK["params"] + [{"key": "top", "kind": "length", "label": "Top", "default": 0.02}]}
    (folder / "block.kimobj").write_text(json.dumps(newer), encoding="utf-8")
    library.load_office(str(folder))                       # the office definition moved on: outdated
    s = call("object_settings_of", json.dumps([p["guid"]]))
    assert s["source"] == "type:" + p["type"]
    form = call("object_form", "office:block", "", s["source"])
    assert [x["key"] for x in form["params"]] == ["width", "depth", "height"] and form["values"]["height"] == 0.3
    edited = {**form["values"], "height": 0.5}
    assert call("object_preview_error", "office:block", json.dumps(edited), s["source"]) == {"ok": True}
    assert b.object_preview("office:block", json.dumps(edited), s["source"]) is not None
    assert call("object_symbol", "office:block", "", s["source"])["width"] == pytest.approx(0.4)
    assert call("apply_object_settings", json.dumps([p["guid"]]), json.dumps(edited), "auto")["ok"]
    assert call("object_form", "office:block", "", "type:nosuchguid")["params"] == []
    assert call("object_preview_error", "office:block", "", "type:nosuchguid")["ok"] is False
    v = call("save_object_version", "office:block", "Low", "")
    q = call("place_object", project, "office:block", "", 1, 0, 0, "", v["id"])["guid"]
    assert call("object_settings_of", json.dumps([q]))["source"] == "type:" + v["type"]


def test_replacing_a_version_keeps_its_own_definition(project, tmp_path):
    folder = tmp_path / "office"
    folder.mkdir()
    (folder / "block.kimobj").write_text(json.dumps(BLOCK), encoding="utf-8")
    library.load_office(str(folder))
    v = call("save_object_version", "office:block", "Low", json.dumps({"height": 0.3}))
    old_hash = _ps(v["type"])["DefinitionHash"]
    newer = {**BLOCK, "params": BLOCK["params"] + [{"key": "top", "kind": "length", "label": "Top", "default": 0.02}]}
    (folder / "block.kimobj").write_text(json.dumps(newer), encoding="utf-8")
    library.load_office(str(folder))
    r = call("save_object_version", "office:block", "Low", json.dumps({"height": 0.35}), "1")
    assert r["ok"] and r["id"] == v["id"]
    ps = _ps(v["type"])
    assert ps["DefinitionHash"] == old_hash
    assert json.loads(ps["Parameters"]) == {"width": 0.4, "depth": 0.4, "height": 0.35}


def test_a_local_edit_of_an_office_version_is_not_outdated(project, tmp_path):
    """An office-linked project version keeps the office state it was copied or moved at (OfficeHash):
    a local edit is not outdated; a change of the office version since is."""
    folder = tmp_path / "office"  # projects are saved beside it: an IFC in the folder is office library
    folder.mkdir()
    library.load_office(str(folder))
    v = call("save_object_version", "chair", "Café", "")
    assert call("move_version_to_library", v["id"])["ok"]
    a = call("place_object", project, "chair", "", 0, 0, 0, "", v["id"])["guid"]
    assert call("apply_object_settings", json.dumps([a]), json.dumps({"width": 0.55}), "all")["ok"]  # local
    assert call("library_updates", "")["versions"] == 0
    mine = tmp_path / "mine.ifc"
    assert call("save", str(mine))["ok"]
    # another project copies the office version, changes it and replaces it in the office
    assert call("new_project", "Other")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    q = call("place_object", storey, "chair", "", 0, 0, 0, "", v["id"])["guid"]
    assert call("library_updates", "")["versions"] == 0                     # a fresh copy
    assert call("apply_object_settings", json.dumps([q]), json.dumps({"width": 0.6}), "all")["ok"]
    assert call("library_updates", "")["versions"] == 0
    assert call("move_version_to_library", v["id"], "1")["ok"]
    assert call("library_updates", "")["versions"] == 0                     # it is the office state now
    assert call("open_model", str(mine))["ok"]
    assert call("library_updates", "")["versions"] == 1
    assert call("update_from_library", "")["ok"]
    t = ifcopenshell.util.element.get_type(b._model.by_guid(a))
    assert json.loads(_ps(t.GlobalId)["Parameters"])["width"] == pytest.approx(0.6)
    assert call("library_updates", "")["versions"] == 0                     # the baseline follows the update
    office = ifcopenshell.open(str(folder / "kimbim-versions.ifc"))        # the office copy has no baseline
    assert all("OfficeHash" not in (ifcopenshell.util.element.get_pset(o, library.PSET) or {})
               for o in office.by_type("IfcTypeProduct"))
