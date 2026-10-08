# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 2: the open document — .kim, project folder or plain IFC (D72)."""
import json

import pytest

from kimcad import app_bridge as b
from kimcad import documents as D
from kimcad import kimfile as K


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture(autouse=True)
def data(tmp_path):
    D.set_app_paths(str(tmp_path / "data"))
    yield tmp_path / "data"
    D.close_document()


def house():
    assert call("new_project", "Casa")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    t = call("wall_types")["types"][0]["guid"]
    return call("create_wall", level, t, 0, 0, 5, 0, 3.0, "", "")["guid"]


def open_kim(path, read_only=""):
    r = call("open_kim", str(path), read_only)
    if r["ok"]:
        assert call("open_model", r["path"])["ok"]  # what the app's loader does next
    return r


def test_a_new_project_saved_as_kim_has_history_and_reopens(tmp_path, data):
    wall = house()
    assert call("set_project_settings", json.dumps({"plan_cut_height": 1.1}))["ok"]
    kim = tmp_path / "Casa ñ.kim"
    r = call("save_as_kim", str(kim), "")
    assert r["ok"], r
    assert [v["message"] for v in call("history", 10)["versions"]] == ["First version"]
    st = call("document_state")
    assert st["mode"] == "kim" and st["name"] == "Casa ñ.kim" and not st["untitled"] and st["kept"]
    assert K.lock_path(kim).exists() and call("state")["dirty"] is False
    assert call("close_document")["ok"]
    assert not K.lock_path(kim).exists() and not (data / "open" / K.path_hash(kim)).exists()
    assert open_kim(kim)["ok"]
    assert b._model.by_guid(wall) is not None
    assert call("project_settings")["settings"]["plan_cut_height"] == 1.1
    assert call("project_state")["versioned"] is True and call("state")["dirty"] is False


def test_ctrl_s_saves_without_a_version_and_reopening_keeps_unversioned_work(tmp_path):
    wall = house()
    kim = tmp_path / "a.kim"
    assert call("save_as_kim", str(kim), "")["ok"]
    call("set_name", json.dumps([wall]), "Muro guardado")
    assert call("save_document")["ok"]
    assert len(call("history", 10)["versions"]) == 1
    assert call("state")["dirty"] is False and call("project_state")["unversioned"] is True
    assert call("close_document")["ok"]
    assert open_kim(kim)["ok"]
    assert b._model.by_guid(wall).Name == "Muro guardado"
    assert call("state")["dirty"] is False and call("project_state")["unversioned"] is True
    assert call("create_option", "B")["ok"]
    assert not call("switch_option", "main")["ok"]  # still not a version: the app asks first
    assert call("save_version", "Rename")["ok"]
    assert call("project_state")["unversioned"] is False


def test_a_locked_kim_opens_read_only(tmp_path):
    house()
    kim = tmp_path / "a.kim"
    assert call("save_as_kim", str(kim), "")["ok"]
    assert call("close_document")["ok"]
    foreign = {"user": "Ana", "account": "ana", "machine": "OTHER-PC", "pid": 4, "since": "2026-10-08T10:42"}
    K.lock_path(kim).write_text(json.dumps(foreign))
    r = call("open_kim", str(kim), "")
    assert not r["ok"] and r["locked"]["user"] == "Ana" and "Ana" in r["error"]
    before = kim.read_bytes()
    assert open_kim(kim, "1")["ok"]
    assert call("document_state")["read_only"] is True
    assert call("project_state")["versioned"] is False
    assert not call("save_document")["ok"]
    assert call("close_document")["ok"]
    assert json.loads(K.lock_path(kim).read_text())["user"] == "Ana" and kim.read_bytes() == before


def test_opening_an_ifc_makes_a_kim_beside_it(tmp_path):
    house()
    ifc = tmp_path / "House.ifc"
    assert call("save", str(ifc))["ok"]
    before = ifc.read_bytes()
    beside = call("kim_beside", str(ifc))
    assert beside["kim"] == str(tmp_path / "House.kim") and beside["exists"] is False
    r = call("import_ifc", str(ifc), beside["kim"])
    assert r["ok"], r
    assert call("open_model", r["path"])["ok"]
    assert (tmp_path / "House.kim").exists() and ifc.read_bytes() == before
    assert [v["message"] for v in call("history", 5)["versions"]] == ["Imported from House.ifc"]
    assert call("document_state")["mode"] == "kim"
    again = call("kim_beside", str(ifc))
    assert again["exists"] is True and again["free"] == str(tmp_path / "House (2).kim")
    assert not call("import_ifc", str(ifc), again["kim"])["ok"]


def test_save_as_folder_and_back_to_a_kim(tmp_path):
    house()
    assert call("save_as_kim", str(tmp_path / "a.kim"), "")["ok"]
    folder = tmp_path / "carpeta"
    r = call("save_as_folder", str(folder), "")
    assert r["ok"], r
    assert (folder / ".git").is_dir() and (folder / ".kimcad" / "lock").exists()
    assert not K.lock_path(tmp_path / "a.kim").exists()
    assert call("document_state")["mode"] == "folder"
    assert call("set_project_settings", json.dumps({"sheet_paper": "A3"}))["ok"]
    assert call("save_document")["ok"]
    assert json.loads((folder / ".kimcad" / "settings.json").read_text())["sheet_paper"] == "A3"
    assert call("save_as_kim", str(tmp_path / "b.kim"), "")["ok"]
    assert not (folder / ".kimcad" / "lock").exists()
    assert call("close_document")["ok"]
    assert open_kim(tmp_path / "b.kim")["ok"]
    assert len(call("history", 10)["versions"]) == 1
    assert call("project_settings")["settings"]["sheet_paper"] == "A3"


def test_export_ifc_leaves_the_document_as_it_is(tmp_path):
    wall = house()
    assert call("save_as_kim", str(tmp_path / "a.kim"), "")["ok"]
    call("set_name", json.dumps([wall]), "Exportado")
    assert call("export_ifc", str(tmp_path / "out.ifc"))["ok"]
    assert b"Exportado" in (tmp_path / "out.ifc").read_bytes()
    assert call("document_state")["mode"] == "kim" and call("state")["dirty"] is True


def test_existing_project_folders_open_with_default_settings(tmp_path):
    from kimcad.project import Project

    house()
    plain = tmp_path / "old.ifc"
    assert call("save", str(plain))["ok"]
    project = Project.init(tmp_path / "old")
    project.commit(plain, "Made by an older KIMCAD")  # no settings.json in its tree
    r = call("open_folder", str(tmp_path / "old"), "")
    assert r["ok"], r
    assert call("open_model", r["path"])["ok"]
    assert call("project_settings")["settings"]["plan_cut_height"] == 1.2
    assert call("document_state")["mode"] == "folder" and call("project_state")["unversioned"] is False


def test_opening_another_model_releases_the_kim(tmp_path):
    house()
    kim = tmp_path / "a.kim"
    assert call("save_as_kim", str(kim), "")["ok"]
    assert call("new_project", "otra")["ok"]
    assert not K.lock_path(kim).exists()
    assert call("document_state")["mode"] == "plain" and call("document_state")["untitled"] is True


def test_the_author_from_preferences_signs_versions_and_the_lock(tmp_path):
    assert call("set_author", "Felipe Lecot", "felipe@example.com")["ok"]
    try:
        house()
        kim = tmp_path / "a.kim"
        assert call("save_as_kim", str(kim), "")["ok"]
        assert call("history", 1)["versions"][0]["author"] == "Felipe Lecot"
        assert json.loads(K.lock_path(kim).read_text())["user"] == "Felipe Lecot"
    finally:
        call("set_author", "", "")


def test_a_recovery_copy_is_offered_after_a_crash_and_cleared_by_saving(tmp_path):
    wall = house()
    call("set_name", json.dumps([wall]), "Sin guardar")
    assert call("set_project_settings", json.dumps({"drawing_scale": 20}))["ok"]
    assert call("write_recovery")["written"] is True
    assert call("recoveries")["items"] == []  # this session's own copy is not offered
    assert call("new_project", "otra")["ok"]  # a "restart": another model is open
    items = call("recoveries")["items"]
    assert len(items) == 1 and items[0]["source"] == "" and items[0]["mode"] == "plain"
    r = call("recover", items[0]["id"])
    assert r["ok"], r
    assert call("open_model", r["path"])["ok"]
    assert b._model.by_guid(wall).Name == "Sin guardar"
    assert call("project_settings")["settings"]["drawing_scale"] == 20
    assert call("state")["dirty"] is True and call("document_state")["untitled"] is True
    assert call("recoveries")["items"] == []


def test_a_recovered_kim_reopens_the_kim_with_the_recovered_work(tmp_path):
    wall = house()
    kim = tmp_path / "a.kim"
    assert call("save_as_kim", str(kim), "")["ok"]
    call("set_name", json.dumps([wall]), "Recuperado")
    assert call("write_recovery")["written"] is True
    D._doc = D._plain()  # a crash: nothing was closed; the lock, working folder and copy are left behind
    item = call("recoveries")["items"][0]
    assert item["source"] == str(kim) and item["name"] == "a.kim"
    r = call("recover", item["id"])
    assert r["ok"], r
    assert call("open_model", r["path"])["ok"]
    assert b._model.by_guid(wall).Name == "Recuperado" and call("document_state")["mode"] == "kim"
    assert call("state")["dirty"] is True and call("project_state")["unversioned"] is True
    assert call("save_document")["ok"] and call("recoveries")["items"] == []


def test_nothing_is_written_without_unsaved_work(tmp_path):
    house()
    assert call("save_as_kim", str(tmp_path / "a.kim"), "")["ok"]
    assert call("write_recovery")["written"] is False


def test_templates_list_save_and_make_new_projects(tmp_path):
    folder = tmp_path / "Plantillas"
    assert call("templates", str(folder)) == {"templates": [
        {"name": "KIMCAD default", "path": "builtin", "builtin": True, "modified": ""}], "folder_ok": False}
    house()
    assert call("set_project_info", json.dumps({"number": "2026-001", "name": "Casa"}))["ok"]
    sheet = call("add_sheet", "A1", "Plantas")["number"]
    plan = next(d["guid"] for d in call("drawings")["drawings"] if d["name"].endswith("Floor Plan"))
    assert call("place_drawing", sheet, plan, -1, -1, 100)["ok"]
    assert call("set_project_settings", json.dumps({"drawing_scale": 50}))["ok"]
    old_ids = {e.GlobalId for e in b._model.by_type("IfcRoot")}
    r = call("save_template", str(folder), "Oficina")
    assert r["ok"], r
    assert K.read_manifest(folder / "Oficina.kim")["kind"] == "template"
    assert not call("save_template", str(folder), "Oficina")["ok"]
    assert call("save_template", str(folder), "Oficina", "1")["ok"]
    assert not call("save_template", str(folder), "a/b")["ok"]
    listed = call("templates", str(folder))
    assert listed["folder_ok"] and [t["name"] for t in listed["templates"]] == ["KIMCAD default", "Oficina"]

    r = call("new_from_template", str(folder / "Oficina.kim"))
    assert r["ok"], r
    assert call("open_model", r["path"])["ok"]
    new_ids = {e.GlobalId for e in b._model.by_type("IfcRoot")}
    assert len(new_ids) == len(old_ids) and not (new_ids & old_ids)
    views = next(s for s in call("sheets")["sheets"] if s["number"] == sheet)["views"]
    assert len(views) == 1 and views[0]["drawing"] in new_ids  # the sheet still shows its drawing
    assert call("project_info")["number"] == "" and call("project_settings")["settings"]["drawing_scale"] == 50
    st = call("document_state")
    assert st["untitled"] is True and st["template"] == "Oficina" and call("state")["dirty"] is False
    assert call("save_as_kim", str(tmp_path / "nuevo.kim"), "")["ok"]
    assert [v["message"] for v in call("history", 5)["versions"]] == ["Created from Oficina"]


def test_the_built_in_template_is_a_new_project():
    r = call("new_from_template", "builtin")
    assert r["ok"] and r["path"] == ""
    assert call("storeys")["storeys"] and call("document_state")["template"] == "KIMCAD default"


def test_an_opened_template_saves_back_as_a_template(tmp_path):
    folder = tmp_path / "t"
    house()
    assert call("save_template", str(folder), "Base")["ok"]
    assert open_kim(folder / "Base.kim")["ok"]
    assert call("document_state")["mode"] == "template" and call("project_state")["versioned"] is False
    assert call("set_project_settings", json.dumps({"sheet_paper": "A3"}))["ok"]
    assert call("save_document")["ok"]
    assert K.read_manifest(folder / "Base.kim")["kind"] == "template"


def test_save_as_ifc_turns_the_document_into_that_ifc(tmp_path):
    house()
    kim = tmp_path / "a.kim"
    assert call("save_as_kim", str(kim), "")["ok"]
    r = call("save_as_ifc", str(tmp_path / "b.ifc"))
    assert r["ok"], r
    assert not K.lock_path(kim).exists() and (tmp_path / "b.ifc").exists()
    st = call("document_state")
    assert st["mode"] == "plain" and st["name"] == "b.ifc" and call("project_state")["versioned"] is False
