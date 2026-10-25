# SPDX-License-Identifier: GPL-3.0-or-later
"""The Object Editor (D101): objects made in the project, kept only on their types, are listed in the
Library and placed from the definition stored with them."""
import json
import time

import ifcopenshell.util.element
import pytest
from kimbim import app_bridge as b
from kimbim import library, objects


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def project():
    assert call("new_project", "Editor")["ok"]
    yield call("storeys")["storeys"][0]["guid"]
    library.load_office()


BLOCK = {
    "format": "kimbim-object/1", "id": "block", "name": {"en": "Block", "es": "Bloque"}, "category": "furniture",
    "ifc": {"IFC4": ["IfcFurnitureType", "NOTDEFINED", None]},
    "params": [{"key": "width", "kind": "length", "label": "Width", "default": 0.4},
               {"key": "depth", "kind": "length", "label": "Depth", "default": 0.4},
               {"key": "height", "kind": "length", "label": "Height", "default": 0.45}],
    "parts": [{"id": "body", "box": {"dx": "width", "dy": "depth", "dz": "height"}}],
}


def test_a_project_object_lists_and_places(project):
    data = json.loads((library.BUNDLED / "table.kimobj").read_text(encoding="utf-8"))
    defn = objects.load({**data, "id": "stool"}, "project")
    assert defn.ref == "project:stool" and library.get("project:stool") is None
    b._run(lambda: (library._make_type(defn, defn.values()), 1)[1])
    listed = [o for o in call("library_objects")["objects"] if o["id"] == "project:stool"]
    assert len(listed) == 1 and listed[0]["category"] == "project" and listed[0]["library"] == "project"
    assert ("project", "Project") in [(c["id"], c["name"]) for c in call("library_objects")["categories"]]
    p = call("place_object", project, "project:stool", '{"width": 0.7}', 0, 0)
    assert p["ok"], p
    t = b._model.by_guid(p["type"])
    assert ifcopenshell.util.element.get_pset(t, library.PSET, "Object") == "project:stool"
    assert json.loads(ifcopenshell.util.element.get_pset(t, library.PSET, "Parameters"))["width"] == 0.7
    assert call("place_object", project, "project:nothing", "", 0, 0)["ok"] is False


def test_an_object_gone_from_the_library_still_places(project, tmp_path):
    (tmp_path / "block.kimobj").write_text(json.dumps(BLOCK), encoding="utf-8")
    library.load_office(str(tmp_path))
    assert call("place_object", project, "office:block", "", 0, 0)["ok"]
    library.load_office()
    p = call("place_object", project, "office:block", '{"height": 0.9}', 1, 0)
    assert p["ok"], p
    t = b._model.by_guid(p["type"])
    assert json.loads(ifcopenshell.util.element.get_pset(t, library.PSET, "Parameters"))["height"] == 0.9


# ---------------------------------------------------------------- drafts (Task 3)


def _draft(source):
    r = call("object_draft", source)
    assert r["ok"], r
    return r["draft"]


def _text(d):
    return json.dumps(d)


def test_new_draft_checks_and_previews(project):
    r = call("object_draft", "new")
    assert r["ok"] and r["target"] == "" and r["copy"] is False and r["draft"]["id"] == "new_object"
    assert call("check_draft", _text(r["draft"])) == {"ok": True, "errors": []}
    assert b.draft_preview(_text(r["draft"]), "{}") is not None
    assert json.loads(b.draft_preview_error(_text(r["draft"]), "{}"))["ok"]
    assert "new_object" not in library.OBJECTS and "project:new_object" not in library.OBJECTS


def test_a_bundled_object_opens_as_a_copy(project, tmp_path):
    r = call("object_draft", "chair")
    assert r["copy"] is True and r["target"] == "" and r["draft"]["id"] == "chair_copy"
    assert r["draft"]["name"] == {"en": "Chair (copy)", "es": "Silla (copia)"}
    (tmp_path / "chair_copy.kimobj").write_text(json.dumps(r["draft"]), encoding="utf-8")
    library.load_office(str(tmp_path))
    assert "office:chair_copy" in library._office
    assert call("object_draft", "chair")["draft"]["id"] == "chair_copy2"
    edit = call("object_draft", "office:chair_copy")
    assert edit["target"] == "office" and edit["copy"] is False and edit["draft"]["id"] == "chair_copy"
    assert call("object_draft", "nothing")["ok"] is False
    assert call("object_draft", "project:nothing")["ok"] is False


def test_customise_a_copy_takes_the_type_values(project):
    p = call("place_object", project, "chair", '{"legs": 3, "layout": "circle"}', 0, 0)
    assert p["ok"], p
    r = call("object_draft", "type:" + p["type"])
    assert r["ok"] and r["copy"] is True and r["draft"]["id"] == "chair_copy"
    params = {q["key"]: q for q in r["draft"]["params"]}
    assert params["legs"]["default"] == 3 and params["layout"]["default"] == "circle"
    assert call("check_draft", _text(r["draft"]))["ok"]
    assert call("object_draft", "type:nothing")["ok"] is False


def test_a_project_object_opens_for_editing(project):
    data = json.loads((library.BUNDLED / "table.kimobj").read_text(encoding="utf-8"))
    defn = objects.load({**data, "id": "stool"}, "project")
    b._run(lambda: (library._make_type(defn, defn.values()), 1)[1])
    r = call("object_draft", "project:stool")
    assert r["ok"] and r["target"] == "project" and r["copy"] is False and r["draft"]["id"] == "stool"
    assert call("object_draft", "table")["draft"]["id"] == "table_copy"
    assert call("object_draft", "project:stool")["ok"]
    data2 = {**data, "id": "table_copy"}
    d2 = objects.load(data2, "project")
    b._run(lambda: (library._make_type(d2, d2.values()), 1)[1])
    assert call("object_draft", "table")["draft"]["id"] == "table_copy2"


def test_errors_name_their_fields(project):
    chair = _draft("chair")
    chair["params"] = [{**q, "key": "legz"} if q["key"] == "legs" else q for q in chair["params"]]
    r = call("check_draft", _text(chair))
    assert not r["ok"]
    assert any(e["path"].startswith("parts.leg") and "unknown name" in e["message"] for e in r["errors"]), r
    chair = _draft("chair")
    chair["params"][3]["max"] = "seat_h -"
    chair["parts"][1]["use"] = "leg_{leg_style}"
    chair["components"]["leg_square"]["parts"][0]["box"]["dx"] = "size /"
    r = call("check_draft", _text(chair))
    paths = [e["path"] for e in r["errors"]]
    assert not r["ok"] and "params[3].max" in paths
    assert "components.leg_square.parts.post.box.dx" in paths and len(r["errors"]) == 2, r
    bad = call("check_draft", "{nope")
    assert bad["ok"] is False and len(bad["errors"]) == 1 and bad["errors"][0]["path"] == ""
    assert "Expecting" in bad["errors"][0]["message"] or "line" in bad["errors"][0]["message"]


def test_labels_and_ids_are_not_formulas(project):
    chair = _draft("chair")
    chair["name"] = {"en": "A + (b", "es": "- ("}
    chair["params"][3]["label"] = {"en": "Seat height (", "es": "x ("}
    chair["params"][0]["group"] = "Size + ("
    assert call("check_draft", _text(chair))["ok"]


def test_try_values_form(project):
    chair = _text(_draft("chair"))
    f = call("draft_form", chair, '{"legs": 3}')
    assert f["values"]["legs"] == 3 and f["name"] == "Chair (copy)" and f["visible"]
    assert f == {**f, "params": f["params"]} and {"key", "label", "kind", "min", "max", "visible"} <= set(f["params"][0])
    s = call("draft_symbol", chair, '{"width": 0.5}')
    assert s["symbol"] and s["width"] == 0.5 and s["params"]["width"] == 0.5
    broken = call("draft_form", "{}", "{}")
    assert broken["ok"] is False and broken["error"]
    assert b.draft_preview("{}", "{}") is None
    assert json.loads(b.draft_preview_error("{}", "{}"))["ok"] is False
    assert b.draft_preview(chair, '{"width": 0.6}') is not None


def test_part_templates_build(project):
    for shape in ("box", "cylinder", "cone", "prism", "revolve", "sweep"):
        part = call("object_part_template", shape)["part"]
        assert part["id"] == "part" and shape in part
        d = _draft("new")
        d["parts"] = [part]
        r = call("check_draft", _text(d))
        assert r["ok"], (shape, r)
    for shape in ("use", "anchors"):
        assert call("object_part_template", shape)["part"]["id"] == "part"
    assert call("object_part_template", "blob")["ok"] is False


def test_a_hostile_draft_fails_fast(project):
    d = _draft("new")
    d["parts"][0]["repeat"] = {"count": 100000, "step": [0.1, 0, 0]}
    t0 = time.time()
    r = call("check_draft", _text(d))
    assert time.time() - t0 < 5 and not r["ok"]
    assert "5000" in " ".join(e["message"] for e in r["errors"])


def test_every_bundled_object_checks_ok(project):
    for path in sorted(library.BUNDLED.glob("*.kimobj")):
        r = call("check_draft", path.read_text(encoding="utf-8"))
        assert r["ok"], (path.name, r["errors"])


def test_unknown_names_in_branches_not_taken(project):
    d = _draft("new")
    d["parts"][0]["when"] = "nothing > 1"
    d["params"].append({"key": "c", "kind": "bool", "label": "C", "default": False, "show_when": "gone"})
    d["components"] = {"box2": {"params": [{"key": "s", "kind": "length", "label": "S", "default": 0.1}],
                               "parts": [{"id": "p", "box": {"dx": "s", "dy": "width", "dz": "s"}}]}}
    d["symbol"] = [{"rect": {"x": 0, "y": 0, "dx": "wdth", "dy": "depth"}}]
    r = call("check_draft", _text(d))
    got = {(e["path"], e["message"]) for e in r["errors"]}
    assert ("parts.body.when", "unknown name 'nothing'") in got
    assert ("params[3].show_when", "unknown name 'gone'") in got
    assert ("components.box2.parts.p.box.dy", "unknown name 'width'") in got
    assert ("symbol[0].rect.dx", "unknown name 'wdth'") in got
    d = _draft("new")  # part anchors and material slots are names too
    d["parts"].append({"id": "lid", "box": {"z": "body.top.z", "dx": "width", "dy": "depth", "dz": "i + n + pi"}})
    assert call("check_draft", _text(d))["ok"]


def test_a_hostile_draft_never_raises(project):
    assert call("check_draft", "[" * 100000)["ok"] is False
    d = _draft("new")
    nested = 1
    for _ in range(2000):
        nested = [nested]
    d["parts"][0]["box"]["dx"] = nested
    r = call("check_draft", _text(d))
    assert r["ok"] is False and r["errors"]
    assert call("draft_form", "[" * 100000, "{}")["ok"] is False


# ---------------------------------------------------------------- saving a draft (Task 4)


def _chair_copy(legs=3):
    d = _draft("chair")
    for q in d["params"]:
        if q["key"] == "legs":
            q["default"] = legs
    return d


def test_save_to_office_writes_and_lists(project, tmp_path):
    d = _chair_copy()
    assert call("save_draft", _text(d), "office")["error"].startswith("no office library folder")
    library.load_office(str(tmp_path))
    r = call("save_draft", _text(d), "office")
    assert r["ok"] and r["ref"] == "office:chair_copy" and r["outdated"] == 0, r
    path = tmp_path / "chair_copy.kimobj"
    assert r["path"] == str(path) and path.read_text(encoding="utf-8").endswith("}\n")
    assert json.loads(path.read_text(encoding="utf-8")) == d and list(json.loads(path.read_text(encoding="utf-8"))) == list(d)
    assert library.get("office:chair_copy").values()["legs"] == 3
    assert call("save_draft", _text(d), "office") == {"ok": False, "exists": "chair_copy"}
    assert call("save_draft", _text(d), "office", "chair_copy")["ok"]
    other = {**d, "id": "other"}  # a file with another name holding the same id is replaced in place
    (tmp_path / "elsewhere.kimobj").write_text(json.dumps({**d, "id": "stool_x"}), encoding="utf-8")
    library.load_office(str(tmp_path))
    assert call("save_draft", _text({**d, "id": "stool_x"}), "office")["exists"] == "stool_x"
    assert call("save_draft", _text({**d, "id": "stool_x"}), "office", "stool_x")["path"] == str(tmp_path / "elsewhere.kimobj")
    assert not (tmp_path / "stool_x.kimobj").exists() and call("save_draft", _text(other), "office")["ok"]
    assert call("save_draft", _text(d), "elsewhere")["ok"] is False


def test_saving_a_bundled_id_is_refused(project, tmp_path):
    library.load_office(str(tmp_path))
    d = _draft("chair")
    d["id"] = "chair"
    for target in ("office", "project"):
        r = call("save_draft", _text(d), target)
        assert r == {"ok": False, "error": "chair is a bundled object: give the copy another id"}
    assert not list(tmp_path.iterdir())


def test_save_with_errors_is_refused(project, tmp_path):
    library.load_office(str(tmp_path))
    d = _draft("new")
    d["parts"][0]["box"]["dx"] = "nothing"
    n = len(b._model.by_type("IfcTypeProduct"))
    for target in ("office", "project"):
        r = call("save_draft", _text(d), target)
        assert r["ok"] is False and r["error"] == "the object has errors" and r["errors"]
    assert not list(tmp_path.iterdir()) and len(b._model.by_type("IfcTypeProduct")) == n
    assert call("save_draft", "{nope", "project")["ok"] is False


def test_save_to_project_keeps_the_object_and_undoes(project):
    d = _text(_draft("new"))
    r = call("save_draft", d, "project")
    assert r == {"ok": True, "ref": "project:new_object", "types": 1}, r

    def listed():
        return [o["id"] for o in call("library_objects")["objects"]]
    assert "project:new_object" in listed()
    assert call("save_draft", d, "project")["types"] == 1  # saving again regenerates, it adds no type
    assert call("undo")["ok"] and "project:new_object" in listed()
    assert call("undo")["ok"] and "project:new_object" not in listed()
    assert call("redo")["ok"] and "project:new_object" in listed()


def _height(t, values):
    return library.definition_of_type(t).shape(values).metrics()["bbox"][5]


def test_saving_a_project_object_regenerates_its_types(project):
    d = _draft("new")
    assert call("save_draft", _text(d), "project")["ok"]
    p1 = call("place_object", project, "project:new_object", '{"width": 0.7}', 0, 0)
    p2 = call("place_object", project, "project:new_object", '{"width": 0.7}', 2, 0)
    assert p1["ok"] and p2["ok"] and p1["type"] == p2["type"]
    t = b._model.by_guid(p1["type"])
    assert _height(t, library._params_of_type(t)[1]) == pytest.approx(0.75)
    d["parts"][0]["box"]["dz"] = "height / 2"
    r = call("save_draft", _text(d), "project")
    assert r["ok"] and r["types"] == 2, r  # the saved version anchor and the placed type
    t = b._model.by_guid(p1["type"])
    assert b._model.by_guid(p2["type"]) == t
    values = library._params_of_type(t)[1]
    assert values["width"] == 0.7 and _height(t, values) == pytest.approx(0.375)


def test_a_failing_type_changes_nothing(project):
    d = _draft("new")
    assert call("save_draft", _text(d), "project")["ok"]
    p = call("place_object", project, "project:new_object", '{"width": 0.7}', 0, 0)
    t = b._model.by_guid(p["type"])
    before = ifcopenshell.util.element.get_pset(t, library.PSET, "Definition")
    d["parts"][0]["box"]["dz"] = "1 / (width - 0.7)"  # builds at the defaults, not at width 0.7
    r = call("save_draft", _text(d), "project")
    assert r["ok"] is False and t.Name in r["error"], r
    assert ifcopenshell.util.element.get_pset(t, library.PSET, "Definition") == before


def test_an_edited_office_file_offers_an_update(project, tmp_path):
    library.load_office(str(tmp_path))
    d = _chair_copy()
    assert call("save_draft", _text(d), "office")["ok"]
    assert call("place_object", project, "office:chair_copy", "", 0, 0)["ok"]
    assert call("library_updates", "")["outdated"] == 0
    for q in d["params"]:
        if q["key"] == "seat":
            q["default"] = 0.5
    r = call("save_draft", _text(d), "office", "chair_copy")
    assert r["ok"] and r["outdated"] == 1, r
    assert call("library_updates", "")["outdated"] == 1


def test_an_office_save_names_its_outdated_placements(project, tmp_path):
    """D101 review: the update the editor offers covers only this object's placements, so the save
    gives their GUIDs; another outdated office object's placements are not among them."""
    library.load_office(str(tmp_path))
    d = _chair_copy()
    other = _chair_copy()
    other["id"] = "stool"
    for draft in (d, other):
        assert call("save_draft", _text(draft), "office")["ok"]
    chair = call("place_object", project, "office:chair_copy", "", 0, 0)
    stool = call("place_object", project, "office:stool", "", 2, 0)
    assert chair["ok"] and stool["ok"]
    for draft in (d, other):
        for q in draft["params"]:
            if q["key"] == "seat":
                q["default"] = 0.5
    assert call("save_draft", _text(other), "office", "stool")["guids"] == [stool["guid"]]
    r = call("save_draft", _text(d), "office", "chair_copy")
    assert r["ok"] and r["outdated"] == 1 and r["guids"] == [chair["guid"]], r
    assert call("library_updates", "")["outdated"] == 2
    assert call("update_from_library", json.dumps(r["guids"]))["ok"]
    assert call("library_updates", "")["outdated"] == 1  # the stool is still outdated
