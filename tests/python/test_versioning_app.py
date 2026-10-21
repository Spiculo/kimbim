# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned projects in the app (M5, Slice 8): enable, save versions, history, compare, options."""
import json

import pytest

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


@pytest.fixture
def versioned(tmp_path):
    """A new model with two walls, versioned in tmp/project ("Initial import")."""
    assert call("new_project", "Versionado")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    t = call("wall_types")["types"][0]["guid"]
    w1 = call("create_wall", level, t, 0, 0, 5, 0, 3.0, "", "")["guid"]
    w2 = call("create_wall", level, t, 0, 3, 5, 3, 3.0, "", "")["guid"]
    folder = tmp_path / "project"
    r = call("enable_versioning", str(folder), "Initial import")
    assert r["ok"], r
    return {"folder": folder, "level": level, "walls": [w1, w2], "type": t}


def test_enabling_versioning_makes_a_first_version(versioned):
    st = call("project_state")
    assert st["versioned"] is True and st["option"] == "main" and st["options"] == ["main"]
    assert st["dirty"] is False
    h = call("history", 10)["versions"]
    assert [v["message"] for v in h] == ["Initial import"]
    assert (versioned["folder"] / ".kimbim" / "working.ifc").exists()


def test_enabling_in_a_used_folder_is_refused(tmp_path):
    assert call("new_project", "x")["ok"]
    folder = tmp_path / "busy"
    folder.mkdir()
    (folder / "notes.txt").write_text("keep me")
    r = call("enable_versioning", str(folder), "Initial import")
    assert not r["ok"] and "empty" in r["error"]
    assert (folder / "notes.txt").read_text() == "keep me"


def test_save_version_summarises_and_clears_dirty(versioned):
    w1 = versioned["walls"][0]
    call("set_name", g(w1), "Muro sur")
    summary = call("version_changes")
    assert summary["modified"] == 1 and summary["added"] == 0 and summary["removed"] == 0
    assert summary["items"][0]["guid"] == w1
    r = call("save_version", "Rename the south wall")
    assert r["ok"], r
    assert call("project_state")["dirty"] is False
    assert [v["message"] for v in call("history", 10)["versions"]] == ["Rename the south wall", "Initial import"]
    assert not call("save_version", "again")["ok"]  # nothing changed
    call("set_name", g(w1), "Otra vez")  # undo/redo history keeps working after a save
    assert call("undo")["ok"]


def test_compare_working_and_two_versions(versioned):
    w1, w2 = versioned["walls"]
    first = call("history", 1)["versions"][0]["id"]
    call("set_name", g(w2), "Muro norte")
    new_wall = call("create_wall", versioned["level"], versioned["type"], 0, 6, 5, 6, 3.0, "", "")["guid"]
    c = call("compare", first, "WORKING")
    assert {x["guid"] for x in c["modified"]} == {w2}
    assert {x["guid"] for x in c["added"]} == {new_wall}
    assert c["removed"] == []
    call("save_version", "Second")
    call("delete_elements", g(w1))
    call("save_version", "Third")
    head = call("history", 1)["versions"][0]["id"]
    c2 = call("compare", first, head)
    assert {x["guid"] for x in c2["removed"]} == {w1} and {x["guid"] for x in c2["added"]} == {new_wall}
    assert c2["removed"][0]["type"] == "IfcWall"


def test_options_keep_their_own_content(versioned):
    w1 = versioned["walls"][0]
    r = call("create_option", "Option B")
    assert r["ok"], r
    assert call("project_state")["option"] == "Option B"
    call("delete_elements", g(w1))
    assert call("save_version", "B: no south wall")["ok"]
    r = call("switch_option", "main")
    assert r["ok"], r
    assert b._model.by_guid(w1)  # main still has it, same GlobalId after reopening
    assert call("project_state")["option"] == "main"
    call("switch_option", "Option B")
    with pytest.raises(RuntimeError):
        b._model.by_guid(w1)


def test_switching_with_unsaved_changes_is_refused_and_discard_works(versioned):
    w1 = versioned["walls"][0]
    call("create_option", "B")
    call("set_name", g(w1), "Cambio sin guardar")
    r = call("switch_option", "main")
    assert not r["ok"] and "unsaved" in r["error"]
    assert call("project_state")["option"] == "B"
    assert call("discard_changes")["ok"]
    assert b._model.by_guid(w1).Name != "Cambio sin guardar"
    assert call("switch_option", "main")["ok"]


def test_open_project_shows_the_head_state(versioned, tmp_path):
    w1 = versioned["walls"][0]
    call("set_name", g(w1), "Guardado")
    call("save_version", "Named")
    assert call("new_project", "something else")["ok"]
    assert call("project_state")["versioned"] is False
    r = call("open_project", str(versioned["folder"]))
    assert r["ok"], r
    assert b._model.by_guid(w1).Name == "Guardado"
    assert call("project_state")["versioned"] is True and not call("project_state")["dirty"]
    assert not call("open_project", str(tmp_path / "nothing-here"))["ok"]


def test_a_property_change_shows_the_element_that_uses_it(versioned):
    w1 = versioned["walls"][0]
    call("set_property", g(w1), "Pset_WallCommon", "FireRating", '"EI60"')
    c = call("compare", call("history", 1)["versions"][0]["id"], "WORKING")
    assert [x["guid"] for x in c["modified"]] == [w1]


def test_versions_open_as_valid_ifc(tmp_path):
    """Records share identical values (hash-consing); IFC wants some of them to have one owner (a
    representation per product shape, a material layer per layer set). Opening a version un-shares
    them, so the model stays valid, and saving it again records no change."""
    import ifcopenshell.validate

    assert call("new_project", "Valid")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    types = {t["name"]: t["guid"] for t in call("slab_types")["types"]}
    t = call("wall_types")["types"][0]["guid"]
    for y in (0, 3, 6):  # identical walls: identical axis representations
        call("create_wall", level, t, 0, y, 5, y, 3.0, "", "")
    for name in types:  # slab types share an identical material layer
        call("create_slab", level, types[name], json.dumps([[0, 0], [5, 0], [5, 6], [0, 6]]), 0.0)
    assert call("enable_versioning", str(tmp_path / "p"), "Initial import")["ok"]
    assert call("discard_changes")["ok"]  # reopen the version from its records
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, log, express_rules=True)
    assert log.statements == []
    assert call("version_changes")["modified"] == 0 and call("version_changes")["added"] == 0


def test_switching_options_keeps_the_project_settings(tmp_path):
    """Reopening the working copy (a switch) keeps the option's settings, not the defaults (D96 found it)."""
    import json as _json

    from kimbim import app_bridge as b
    from kimbim import settings as S

    call = lambda fn, *a: _json.loads(getattr(b, fn)(*a))  # noqa: E731
    assert call("new_project", "x")["ok"]
    assert call("set_project_settings", _json.dumps({"wall_reference_line": "Core centre"}))["ok"]
    assert call("save_as_folder", str(tmp_path / "p"), "Initial")["ok"]
    assert call("create_option", "B")["ok"]
    r = call("switch_option", "main")
    assert r["ok"], r
    assert call("open_model", r["path"])["ok"]  # what the app's loader does
    assert S.current()["wall_reference_line"] == "Core centre"
    assert call("project_state")["unversioned"] is False
