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
    # legs count the circle's legs: at the corners layout nothing evaluates it, so default to the circle
    chair["params"] = [{**q, "key": "legz"} if q["key"] == "legs" else {**q, "default": "circle"} if q["key"] == "layout" else q
                       for q in chair["params"]]
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
