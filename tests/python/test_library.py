# SPDX-License-Identifier: GPL-3.0-or-later
"""The object library (D86): every object makes a valid IFC type with a body and a plan symbol,
placements share their type (mapped items), parameters re-generate it, plans draw the symbol, IFC2X3
gets its own classes, and the office library adds .kimobj definitions and IFC types (D99). Types carry
their definition, so a project edits its objects without the library that made them."""
import json
import math
import pathlib

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.validate
import numpy as np
import pytest

from kimbim import app_bridge as b
from kimbim import library


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def project():
    assert call("new_project", "Library")["ok"]
    yield call("storeys")["storeys"][0]["guid"]
    library.load_office()


def validate(f):
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, logger, express_rules=True)
    return [str(s["message"])[:200] for s in logger.statements]


def test_the_library_lists_every_category():
    listing = call("library_objects")
    ids = {o["id"] for o in listing["objects"]}
    for wanted in ("table", "chair", "sofa", "bed_single", "bed_double", "wardrobe", "desk", "shelf", "wc",
                   "washbasin", "bathtub", "shower_tray", "bidet", "base_cabinets", "wall_cabinets", "sink_unit",
                   "fridge", "cooker", "person", "tree", "car"):
        assert wanted in ids
    for o in listing["objects"]:
        assert o["symbol"] and o["params"], o["id"]  # a thumbnail and parameters for every bundled object
        assert {"width", "height"} <= {p["key"] for p in o["params"]}


@pytest.mark.parametrize("key", sorted(library.OBJECTS))
def test_each_object_is_a_valid_type_with_body_and_plan_symbol(project, key, tmp_path):
    r = call("place_object", project, key, "", 1.0, 2.0, 0.5)
    assert r["ok"], r
    f = b._model
    element, t = f.by_guid(r["guid"]), f.by_guid(r["type"])
    assert ifcopenshell.util.element.get_type(element) == t
    assert t.is_a().endswith("Type") and t.Name.startswith(library.OBJECTS[key].name)
    maps = {m.MappedRepresentation.RepresentationIdentifier for m in t.RepresentationMaps}
    assert maps == {"Body", "Annotation"}
    reps = element.Representation.Representations
    assert all(rep.Items[0].is_a("IfcMappedItem") for rep in reps)
    assert ifcopenshell.util.element.get_container(element).GlobalId == project
    assert ifcopenshell.util.element.get_pset(element, "Pset_" + element.is_a()[3:] + "Common") is not None or \
        ifcopenshell.util.element.get_pset(element, "KIMBIM_Renovation") is not None  # D74 status
    path = tmp_path / f"{key}.ifc"
    b.save(str(path))
    assert validate(ifcopenshell.open(str(path))) == []
    s = ifcopenshell.geom.settings()
    shape = ifcopenshell.geom.create_shape(s, element)
    assert 0 < len(shape.geometry.faces) // 3 < 2000  # low-poly


def test_two_placements_share_one_type(project):
    a = call("place_object", project, "chair", "", 0, 0, 0)
    c = call("place_object", project, "chair", "", 1, 0, 1.57)
    assert a["type"] == c["type"]
    assert len(b._model.by_type("IfcFurnitureType")) == 1
    other = call("place_object", project, "chair", json.dumps({"width": 0.5}), 2, 0, 0)
    assert other["type"] != a["type"]
    assert len(b._model.by_type("IfcFurnitureType")) == 2


def test_one_placement_is_one_undo_step(project):
    before = len(b._model.by_type("IfcFurniture"))
    assert call("place_object", project, "table", "", 0, 0, 0)["ok"]
    assert call("undo")["ok"]
    assert len(b._model.by_type("IfcFurniture")) == before
    assert not b._model.by_type("IfcFurnitureType")


def test_parameters_show_in_properties_and_regenerate(project):
    a = call("place_object", project, "sofa", "", 0, 0, 0)["guid"]
    c = call("place_object", project, "sofa", "", 3, 0, 0)["guid"]
    props = call("properties_multi", json.dumps([a]))
    group = props["psets"]["Parameters"]
    assert group["Width"]["value"] == 2.0 and group["Seats"]["value"] == 3
    # D100: a read-only summary (the type name first, at most 6 parameters); Edit... opens the dialog.
    assert list(group)[0] == "Type" and group["Type"]["value"] == ifcopenshell.util.element.get_type(b._model.by_guid(a)).Name
    assert len(group) <= 7 and not any(row["editable"] for row in group.values())
    assert props["object_settings"] == {"enabled": True}
    both = call("properties_multi", json.dumps([a, c]))
    assert both["object_settings"] == {"enabled": True}  # one type
    # Regeneration (set_object_parameter, the Python API).
    # Only one of two placements: it moves to a new type, the other keeps its own.
    r = call("set_object_parameter", json.dumps([a]), "Width", "2.4")
    assert r["ok"], r
    ta = ifcopenshell.util.element.get_type(b._model.by_guid(a))
    tc = ifcopenshell.util.element.get_type(b._model.by_guid(c))
    assert ta != tc and "2400" in ta.Name and "2000" in tc.Name
    split = call("properties_multi", json.dumps([a, c]))
    assert split["object_settings"] == {"enabled": False}  # two types: Edit... is off
    assert split["psets"]["Parameters"]["Type"]["varies"] is True
    wall_type = call("wall_types")["types"][0]["guid"]
    wall = call("create_wall", project, wall_type, 0, 5, 4, 5, 3.0, "", "")["guid"]
    mixed = call("properties_multi", json.dumps([a, wall]))
    assert "object_settings" not in mixed and "Parameters" not in mixed["psets"]
    # Every placement of the type: it changes in place, keeping its GlobalId.
    guid = tc.GlobalId
    assert call("set_object_parameter", json.dumps([c]), "Seats", "2")["ok"]
    assert ifcopenshell.util.element.get_type(b._model.by_guid(c)).GlobalId == guid
    assert "Seats 2" in b._model.by_guid(guid).Name
    # Back to the other's values: they share a type again and the spare one goes.
    assert call("set_object_parameter", json.dumps([a]), "Width", "2.0")["ok"]
    assert call("set_object_parameter", json.dumps([a]), "Seats", "2")["ok"]
    assert ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId == guid
    assert len(b._model.by_type("IfcFurnitureType")) == 1
    assert call("set_object_parameter", json.dumps([a]), "Width", "-1")["ok"] is False
    assert validate(b._model) == []


def test_an_object_can_have_its_own_origin(project, tmp_path):
    """D92: the library keeps the left front corner, but an object may set another insertion point."""
    box = {"format": "kimbim-object/1", "id": "origin_box", "name": "Origin box", "category": "furniture",
           "ifc": {"IFC4": ["IfcFurnitureType", "USERDEFINED", None]}, "origin": [0.3, 0.2],
           "params": [{"key": "width", "kind": "length", "label": "Width", "default": 0.6},
                      {"key": "depth", "kind": "length", "label": "Depth", "default": 0.4},
                      {"key": "height", "kind": "length", "label": "Height", "default": 0.5}],
           "parts": [{"id": "body", "box": {"dx": "width", "dy": "depth", "dz": "height"}}],
           "symbol": [{"rect": {"x": 0, "y": 0, "dx": "width", "dy": "depth"}}]}
    write_office(tmp_path / "office", box, "origin_box.kimobj")
    assert call("set_library_paths", json.dumps({"folder": str(tmp_path / "office")}))["errors"] == []
    r = call("place_object", project, "office:origin_box", "", 1.0, 2.0, 0)
    assert r["ok"], r
    e = b._model.by_guid(r["guid"])
    settings = ifcopenshell.geom.settings()
    shape = ifcopenshell.geom.create_shape(settings, e)
    verts = shape.geometry.verts
    xs, ys = verts[0::3], verts[1::3]
    # The object's own origin (the middle of its footprint) is at (0, 0) in its geometry.
    assert min(xs) == pytest.approx(-0.3, abs=1e-6) and max(xs) == pytest.approx(0.3, abs=1e-6)
    assert min(ys) == pytest.approx(-0.2, abs=1e-6) and max(ys) == pytest.approx(0.2, abs=1e-6)


def test_floor_plan_drawing_shows_the_symbol_not_the_cut(project):
    wall_type = call("wall_types")["types"][0]["guid"]
    call("create_wall", project, wall_type, -1, -1, 8, -1, 3.0, "", "")
    table = call("place_object", project, "table", "", 0, 0, 0)["guid"]
    wardrobe = call("place_object", project, "wardrobe", "", 3, 0, 0)["guid"]  # taller than the plan cut
    plan = next(d for d in call("drawings")["drawings"] if d["kind"] == "plan")
    svg = call("generate_drawing", plan["guid"], "")["svg"]
    for guid in (table, wardrobe):
        assert f'data-kind="object" ifc:guid="{guid}"' in svg
        assert svg.count(f'ifc:guid="{guid}"') == 1  # the symbol only, not a cut of the body too


def test_plan_symbol_or_3d_body_per_project_and_per_object(project):
    wall_type = call("wall_types")["types"][0]["guid"]
    call("create_wall", project, wall_type, -1, -1, 8, -1, 3.0, "", "")
    table = call("place_object", project, "table", "", 0, 0, 0)["guid"]
    chair = call("place_object", project, "chair", "", 3, 0, 0)["guid"]
    plan = next(d for d in call("drawings")["drawings"] if d["kind"] == "plan")
    svg = call("generate_drawing", plan["guid"], "")["svg"]
    assert f'data-kind="object" ifc:guid="{table}"' in svg  # default: the plan symbol (D91)
    # Per object: the chair shows its 3D body seen from above instead.
    assert call("set_plan_display", json.dumps([chair]), "body")["ok"]
    svg = call("generate_drawing", plan["guid"], "")["svg"]
    assert f'data-kind="object" ifc:guid="{table}"' in svg
    assert f'data-kind="object" ifc:guid="{chair}"' not in svg
    assert f'ifc:guid="{chair}"' in svg  # drawn as the body instead
    # Per project: turning plan symbols off shows every object's body.
    assert call("set_project_settings", json.dumps({"plan_symbols": False}))["ok"]
    svg = call("generate_drawing", plan["guid"], "")["svg"]
    assert f'data-kind="object" ifc:guid="{table}"' not in svg


def test_ifc2x3_classes(tmp_path):
    from kimbim import testing

    try:
        f = testing.build_model("IFC2X3", walls=1)
        storey = f.by_type("IfcBuildingStorey")[0]
        path = tmp_path / "x3.ifc"
        f.write(str(path))
        assert call("open_model", str(path))["ok"]
        expected = {"table": "IfcFurnishingElement", "wc": "IfcFlowTerminal", "fridge": "IfcFlowTerminal",
                    "tree": "IfcBuildingElementProxy", "car": "IfcBuildingElementProxy"}
        for key, cls in expected.items():
            r = call("place_object", storey.GlobalId, key, "", 0, 0, 0)
            assert r["ok"], r
            assert b._model.by_guid(r["guid"]).is_a() == cls
        assert b._model.by_type("IfcFurnitureType")[0].ElementType == "Table"
        assert validate(b._model) == []
    finally:
        testing._reset_owner()



STOOL = {
    "format": "kimbim-object/1", "id": "stool", "name": {"en": "Stool", "es": "Taburete"}, "category": "furniture",
    "ifc": {"IFC4": ["IfcFurnitureType", "CHAIR", None]},
    "params": [{"key": "width", "kind": "length", "label": "Width", "default": 0.35},
               {"key": "height", "kind": "length", "label": "Height", "default": 0.6},
               {"key": "legs", "kind": "count", "label": "Legs", "default": 3, "min": 3, "max": 6},
               {"key": "foot", "kind": "choice", "label": "Foot", "default": "round",
                "options": [{"id": "round", "label": "Round"}, {"id": "square", "label": "Square"}]},
               {"key": "ring", "kind": "bool", "label": "Foot ring", "default": False},
               {"key": "splay", "kind": "angle", "label": "Splay", "default": 0, "max": 15}],
    "parts": [
        {"id": "seat", "cylinder": {"cx": "width / 2", "cy": "width / 2", "z": "height - 0.03", "r": "width / 2", "h": 0.03},
         "anchors": {"ring": {"pattern": "circle", "cx": "width / 2", "cy": "width / 2", "r": "width / 2 - 0.04",
                              "z": "height - 0.03", "dir": "down"}}},
        {"id": "leg", "repeat": {"on": "seat.anchors.ring", "count": "legs"},
         "rotate": {"axis": "away_from_centre", "angle": "splay"}, "use": "leg_{foot}", "with": {"h": "height - 0.03"}},
        {"id": "hoop", "when": "ring", "sweep": {"r": 0.008, "path": [
            ["width / 2 + 0.12", "width / 2", 0.2], ["width / 2", "width / 2 + 0.12", 0.2], ["width / 2 - 0.12", "width / 2", 0.2],
            ["width / 2", "width / 2 - 0.12", 0.2], ["width / 2 + 0.12", "width / 2", 0.2]]}}],
    "components": {
        "leg_round": {"params": [{"key": "h", "kind": "length", "label": "H", "default": 0.5}],
                      "parts": [{"id": "p", "cone": {"r1": 0.015, "r2": 0.011, "h": "h"}}]},
        "leg_square": {"params": [{"key": "h", "kind": "length", "label": "H", "default": 0.5}],
                       "parts": [{"id": "p", "box": {"x": -0.015, "y": -0.015, "dx": 0.03, "dy": 0.03, "dz": "h", "taper": 0.7}}]}},
}


def write_office(folder, data=STOOL, name="stool.kimobj"):
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(json.dumps(data), encoding="utf-8")


def test_office_library_kimobj_and_ifc_types(project, tmp_path):
    folder = tmp_path / "office"
    write_office(folder)
    (folder / "old.py").write_text("raise SystemExit('must never run')\n", encoding="utf-8")
    # An IFC type library made from a placed bundled object.
    call("place_object", project, "desk", "", 0, 0, 0)
    b.save(str(folder / "types.ifc"))
    desk_type = b._model.by_type("IfcFurnitureType")[0].GlobalId
    assert call("new_project", "Other")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    r = call("set_library_paths", json.dumps({"folder": str(folder)}))
    assert r["ok"] and r["errors"] == [], r
    listed = {o["id"]: o for o in call("library_objects")["objects"]}
    assert "office:stool" in listed and listed["office:stool"]["category"] == "office"
    assert listed["office:stool"]["name_es"] == "Taburete" and listed["office:stool"]["symbol"]
    assert listed["office:stool"]["library"] == str(folder / "stool.kimobj")
    assert listed["chair"]["library"] == "bundled"
    assert not any("old" in key for key in listed)  # .py files are not read
    assert call("place_object", storey, "office:stool", "", 0, 0, 0)["ok"]
    ifc_key = next(k for k in listed if k.startswith("ifc:") and k.endswith(desk_type))
    first = call("place_object", storey, ifc_key, "", 2, 0, 0)
    second = call("place_object", storey, ifc_key, "", 4, 0, 0)
    assert first["ok"] and first["type"] == second["type"] == desk_type  # copied once, then reused
    assert validate(b._model) == []
    assert "office:stool" not in library.OBJECTS  # office objects stay out of the bundled list


def test_types_carry_their_definition(project):
    r = call("place_object", project, "chair", "", 0, 0, 0)
    t = b._model.by_guid(r["type"])
    ps = ifcopenshell.util.element.get_pset(t, library.PSET)
    assert ps["Object"] == "chair" and ps["DefinitionHash"] == library.OBJECTS["chair"].hash
    assert ps["Library"] == "bundled"
    assert json.loads(ps["Definition"])["id"] == "chair"


def test_project_objects_edit_without_the_library(project, tmp_path):
    folder = tmp_path / "office"
    write_office(folder)
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    guid = call("place_object", project, "office:stool", "", 0, 0, 0)["guid"]
    path = tmp_path / "with_stool.ifc"
    b.save(str(path))
    library.load_office()  # the consultant has no office library
    assert call("open_model", str(path))["ok"]
    r = call("set_object_parameter", json.dumps([guid]), "Legs", "5", "")
    assert r["ok"], r
    t = ifcopenshell.util.element.get_type(b._model.by_guid(guid))
    assert json.loads(ifcopenshell.util.element.get_pset(t, library.PSET)["Parameters"])["legs"] == 5
    assert "Legs 5" in t.Name


def test_new_kinds_in_properties(project, tmp_path):
    folder = tmp_path / "office"
    write_office(folder)
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    guid = call("place_object", project, "office:stool", "", 0, 0, 0)["guid"]
    group = call("properties_multi", json.dumps([guid]))["psets"]["Parameters"]
    assert group["Foot"]["value"] == "Round" and "choices" not in group["Foot"]  # read-only (D100)
    assert group["Foot ring"]["ifc_type"] == "IfcBoolean" and group["Foot ring"]["value"] is False
    assert group["Splay"]["ifc_type"] == "IfcPlaneAngleMeasure"
    for name, value in (("Foot", "Square"), ("Foot ring", "true"), ("Splay", "8")):
        assert call("set_object_parameter", json.dumps([guid]), name, value, "")["ok"]
    t = ifcopenshell.util.element.get_type(b._model.by_guid(guid))
    values = json.loads(ifcopenshell.util.element.get_pset(t, library.PSET)["Parameters"])
    assert values["foot"] == "square" and values["ring"] is True and values["splay"] == 8


def test_bad_value_keeps_the_old_type(project, tmp_path):
    data = json.loads(json.dumps(STOOL))
    data["parts"][0]["cylinder"]["h"] = "sqrt(height - 0.5) * 0.1"  # breaks below 0.5 m
    folder = tmp_path / "office"
    write_office(folder, data)
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    r = call("place_object", project, "office:stool", "", 0, 0, 0)
    before = ifcopenshell.util.element.get_type(b._model.by_guid(r["guid"])).GlobalId
    bad = call("set_object_parameter", json.dumps([r["guid"]]), "Height", "0.3", "")
    assert not bad["ok"] and "parts.seat" in bad["error"]
    assert ifcopenshell.util.element.get_type(b._model.by_guid(r["guid"])).GlobalId == before


def test_broken_office_files_are_listed_not_loaded(tmp_path):
    folder = tmp_path / "office"
    write_office(folder)
    (folder / "big.kimobj").write_text(json.dumps({**STOOL, "id": "big", "parts": [
        {"id": "b", "repeat": {"count": 1e9}, "box": {"dx": 1, "dy": 1, "dz": 1}}]}), encoding="utf-8")
    (folder / "cycle.kimobj").write_text(json.dumps({**STOOL, "id": "cyc", "parts": [{"id": "a", "use": "x"}],
                                                     "components": {"x": {"parts": [{"id": "b", "use": "x"}]}}}), encoding="utf-8")
    (folder / "junk.kimobj").write_text("{", encoding="utf-8")
    r = call("set_library_paths", json.dumps({"folder": str(folder)}))
    assert sorted(pathlib.Path(e["file"]).name for e in r["errors"]) == ["big.kimobj", "cycle.kimobj", "junk.kimobj"]
    assert r["objects"] == 1
    library.load_office()


def test_object_form_follows_the_values():
    form = call("object_form", "chair", "")
    assert form["params"] and set(form["visible"]) <= {p["key"] for p in form["params"]}
    assert all({"key", "label", "label_es", "value", "kind", "min", "max", "group"} <= set(p) for p in form["params"])
    assert call("object_form", "no_such_object", "")["params"] == []


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_every_shape_kind_is_valid_ifc(tmp_path, schema):
    from kimbim import testing

    try:
        f = testing.build_model(schema, walls=1)
        storey = f.by_type("IfcBuildingStorey")[0].GlobalId
        model = tmp_path / f"base-{schema}.ifc"
        f.write(str(model))
        assert call("open_model", str(model))["ok"]
        folder = tmp_path / "office"
        write_office(folder)
        call("set_library_paths", json.dumps({"folder": str(folder)}))
        for given in ({}, {"foot": "square", "ring": True, "splay": 10}):
            r = call("place_object", storey, "office:stool", json.dumps(given), 0, 0, 0)
            assert r["ok"], r
            settings = ifcopenshell.geom.settings()
            settings.set("use-world-coords", True)
            shape = ifcopenshell.geom.create_shape(settings, b._model.by_guid(r["guid"]))
            zs = shape.geometry.verts[2::3]
            assert len(shape.geometry.faces) > 0
            assert max(zs) - min(zs) == pytest.approx(0.6, abs=0.01)  # a cone on its side would not be 0.6 m tall
        path = tmp_path / f"shapes-{schema}.ifc"
        b.save(str(path))
        assert validate(ifcopenshell.open(str(path))) == []
    finally:
        testing._reset_owner()
        library.load_office()


LEG = {"format": "kimbim-object/1", "id": "leg", "name": {"en": "Leg", "es": "Pata"}, "category": "furniture",
       "ifc": {"IFC4": ["IfcFurnitureType", "NOTDEFINED", None]},
       "params": [{"key": "h", "kind": "length", "label": "H", "default": 0.5}],
       "parts": [{"id": "p", "box": {"dx": 0.05, "dy": 0.05, "dz": "h"}}]}
TOP = {"format": "kimbim-object/1", "id": "top", "name": {"en": "Top", "es": "Top"}, "category": "furniture",
       "ifc": {"IFC4": ["IfcFurnitureType", "NOTDEFINED", None]},
       "params": [{"key": "height", "kind": "length", "label": "Height", "default": 0.7}],
       "parts": [{"id": "l", "use": "office:leg", "with": {"h": "height"}}]}


def _width(guid):
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), b._model.by_guid(guid))
    xs = shape.geometry.verts[0::3]
    return max(xs) - min(xs)


def test_types_keep_the_objects_they_use(project, tmp_path):
    """D99: a type stores the library objects its definition uses (Uses), so the project edits without
    the library, and a changed library object does not change the project (until Update)."""
    folder = tmp_path / "office"
    write_office(folder, LEG, "leg.kimobj")
    write_office(folder, TOP, "top.kimobj")
    assert call("set_library_paths", json.dumps({"folder": str(folder)}))["errors"] == []
    r = call("place_object", project, "office:top", "", 0, 0, 0)
    assert r["ok"], r
    ps = ifcopenshell.util.element.get_pset(b._model.by_guid(r["type"]), library.PSET)
    assert list(json.loads(ps["Uses"])) == ["office:leg"]
    path = tmp_path / "with_top.ifc"
    b.save(str(path))
    library.load_office()  # no office library
    assert call("open_model", str(path))["ok"]
    edit = call("set_object_parameter", json.dumps([r["guid"]]), "Height", "0.9", "")
    assert edit["ok"], edit
    # The office changes its leg: the project's top keeps the leg it was made with.
    write_office(folder, {**LEG, "parts": [{"id": "p", "box": {"dx": 0.5, "dy": 0.05, "dz": "h"}}]}, "leg.kimobj")
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    assert call("set_object_parameter", json.dumps([r["guid"]]), "Height", "0.8", "")["ok"]
    assert _width(r["guid"]) == pytest.approx(0.05, abs=1e-6)
    t = ifcopenshell.util.element.get_type(b._model.by_guid(r["guid"]))
    fresh = call("place_object", project, "office:top", json.dumps({"height": 0.8}), 2, 0, 0)
    assert fresh["ok"] and fresh["type"] != t.GlobalId  # same values, another definition: another type
    assert _width(fresh["guid"]) == pytest.approx(0.5, abs=1e-6)
    old_hash = ifcopenshell.util.element.get_pset(t, library.PSET)["DefinitionHash"]
    new_hash = ifcopenshell.util.element.get_pset(b._model.by_guid(fresh["type"]), library.PSET)["DefinitionHash"]
    assert old_hash != new_hash


def test_unreadable_choice_or_bool_fails_the_edit(project, tmp_path):
    write_office(tmp_path / "office")
    call("set_library_paths", json.dumps({"folder": str(tmp_path / "office")}))
    guid = call("place_object", project, "office:stool", "", 0, 0, 0)["guid"]
    before = ifcopenshell.util.element.get_type(b._model.by_guid(guid)).GlobalId
    bad = call("set_object_parameter", json.dumps([guid]), "Foot", "Bogus", "")
    assert not bad["ok"] and bad["error"] == "unknown option Bogus for Foot"
    bad = call("set_object_parameter", json.dumps([guid]), "Foot ring", "maybe", "")
    assert not bad["ok"] and bad["error"] == "Foot ring: not on or off"
    assert ifcopenshell.util.element.get_type(b._model.by_guid(guid)).GlobalId == before
    assert call("set_object_parameter", json.dumps([guid]), "Foot", "cuadrado", "")["ok"] is False  # no es label given
    assert call("set_object_parameter", json.dumps([guid]), "Foot", "square", "")["ok"]


def test_objects_using_a_broken_office_object_go_too(tmp_path):
    """The office checks repeat until nothing more goes: a uses b, b (later in the order) fails."""
    folder = tmp_path / "office"
    write_office(folder)
    write_office(folder, {**TOP, "id": "a", "parts": [{"id": "l", "use": "office:b", "with": {"h": "height"}}]}, "a.kimobj")
    write_office(folder, {**LEG, "id": "b", "symbol": [{"circle": {"cx": "nosuchname", "cy": 0, "r": 1}}]}, "b.kimobj")
    r = call("set_library_paths", json.dumps({"folder": str(folder)}))
    assert sorted(pathlib.Path(e["file"]).name for e in r["errors"]) == ["a.kimobj", "b.kimobj"]
    assert r["objects"] == 1
    library.load_office()


def test_place_fails_cleanly_when_the_values_do_not_build(project, tmp_path):
    data = json.loads(json.dumps(STOOL))
    data["parts"][0]["cylinder"]["h"] = "sqrt(height - 0.5) * 0.1"  # breaks below 0.5 m
    write_office(tmp_path / "office", data)
    call("set_library_paths", json.dumps({"folder": str(tmp_path / "office")}))
    types = len(b._model.by_type("IfcFurnitureType"))
    r = call("place_object", project, "office:stool", json.dumps({"height": 0.3}), 0, 0, 0)
    assert not r["ok"] and "parts.seat" in r["error"] and not r["error"].startswith("ObjectError")
    assert len(b._model.by_type("IfcFurnitureType")) == types


def test_update_from_library_keeps_values_and_is_one_undo_step(project, tmp_path):
    folder = tmp_path / "office"
    write_office(folder)
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    guid = call("place_object", project, "office:stool", json.dumps({"legs": 5}), 0, 0, 0)["guid"]
    assert call("library_updates", json.dumps([guid]))["outdated"] == 0
    assert "library_update" not in call("properties_multi", json.dumps([guid]))
    changed = json.loads(json.dumps(STOOL))
    changed["params"][1]["default"] = 0.75  # the office edits its stool
    changed["params"].append({"key": "glides", "kind": "bool", "label": "Glides", "default": True})
    write_office(folder, changed)
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    assert call("library_updates", json.dumps([guid]))["outdated"] == 1
    assert call("properties_multi", json.dumps([guid]))["library_update"] == 1
    r = call("update_from_library", json.dumps([guid]))
    assert r["ok"], r
    t = ifcopenshell.util.element.get_type(b._model.by_guid(guid))
    ps = ifcopenshell.util.element.get_pset(t, library.PSET)
    values = json.loads(ps["Parameters"])
    assert values["legs"] == 5 and values["height"] == pytest.approx(0.6) and values["glides"] is True
    assert ps["DefinitionHash"] == library._hash_of(library.get("office:stool"))
    assert call("library_updates", "")["outdated"] == 0
    assert not call("update_from_library", "")["ok"]
    assert call("undo")["ok"]
    assert call("library_updates", "")["outdated"] == 1
    library.load_office()


def test_a_changed_used_object_makes_the_user_outdated(project, tmp_path):
    folder = tmp_path / "office"
    write_office(folder, LEG, "leg.kimobj")
    write_office(folder, TOP, "top.kimobj")
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    guid = call("place_object", project, "office:top", "", 0, 0, 0)["guid"]
    assert call("library_updates", "")["outdated"] == 0
    wider = json.loads(json.dumps(LEG))
    wider["parts"][0]["box"]["dx"] = 0.08
    write_office(folder, wider, "leg.kimobj")
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    assert call("library_updates", json.dumps([guid]))["outdated"] == 1
    assert call("update_from_library", json.dumps([guid]))["ok"]
    assert call("library_updates", "")["outdated"] == 0
    library.load_office()


def chair(**given):
    d = library.OBJECTS["chair"]
    return d, d.shape(d.values(given))


def test_chair_defaults_are_the_old_chair():
    d, s = chair()
    assert len(s.solids) == 6  # 4 legs, seat, back
    assert d.visible(d.values()) == [k for k in (p.key for p in d.params) if k not in ("legs", "radius", "slats", "arm_height")]


def test_chair_three_splayed_tapered_legs_on_a_circle():
    d, s = chair(layout="circle", legs=3, splay=8, leg_style="tapered", seat_shape="round")
    legs = [x for x in s.solids if x["part"] == "frame"]
    assert len(legs) == 3 and all(x["kind"] == "cone" for x in legs)
    assert s.metrics()["bbox"][2] == pytest.approx(0, abs=0.01)  # feet on the floor (within the splay's lift)
    feet = [np.array(x["matrix"]) @ [0, 0, x["h"], 1] for x in legs]
    assert all(math.dist(f[:2], (0.225, 0.25)) > 0.2 for f in feet)  # out past the 0.18 m leg circle


def test_chair_backs_and_arms():
    _, slats = chair(back="slats", slats=5)
    _, none = chair(back="none")
    _, arms = chair(arms=True)
    _, sled = chair(leg_style="sled")
    assert len(slats.solids) == 4 + 1 + 2 + 1 + 5  # legs, seat, two posts, top rail, slats
    assert len(none.solids) == 5
    assert len(arms.solids) == 6 + 4
    assert sum(1 for x in sled.solids if x["kind"] == "sweep") == 2


@pytest.mark.parametrize("given", [
    {"layout": "circle", "legs": 3, "splay": 8, "leg_style": "tapered", "seat_shape": "round", "back": "slats"},
    {"leg_style": "sled", "back": "upholstered", "arms": True},
    {"layout": "circle", "legs": 1, "radius": 0.05, "leg_style": "round", "back": "none"},
])
def test_chair_variants_are_valid_ifc(project, tmp_path, given):
    r = call("place_object", project, "chair", json.dumps(given), 0, 0, 0)
    assert r["ok"], r
    path = tmp_path / "chair.ifc"
    b.save(str(path))
    assert validate(ifcopenshell.open(str(path))) == []
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    shape = ifcopenshell.geom.create_shape(settings, b._model.by_guid(r["guid"]))
    zs = shape.geometry.verts[2::3]  # metres
    assert len(shape.geometry.faces) > 0
    top = 0.85 if given.get("back") != "none" else 0.45
    assert max(zs) - min(zs) == pytest.approx(top, rel=0.02)


@pytest.mark.parametrize("leg_style", ["square", "sled"])
@pytest.mark.parametrize("back", ["panel", "slats", "upholstered"])
def test_chair_round_seat_keeps_legs_back_and_arms_on_it(leg_style, back):
    d, s = chair(seat_shape="round", leg_style=leg_style, back=back, arms=True)
    v = d.values({"seat_shape": "round", "leg_style": leg_style, "back": back, "arms": True})
    w, dp = v["width"], v["depth"]
    cx, cy, r = w / 2, dp / 2, min(w, dp) / 2
    for x in s.solids:
        if x["part"] == "seat" and x["kind"] == "cylinder":
            continue
        m = np.array(x["matrix"])
        if x["kind"] == "box":
            pts = [m @ [x["x"] + a * x["dx"], x["y"] + b * x["dy"], 0, 1] for a in (0, 1) for b in (0, 1)]
        elif x["kind"] == "sweep":
            pts = [m @ [*q, 1] for q in x["path"]]
        else:
            pts = [m @ [0, 0, 0, 1]]
        for p in pts:  # in plan, inside the seat circle (the inscribed square's corners touch it)
            assert math.dist(p[:2], (cx, cy)) <= r + 1e-6, (x["part"], p)


def test_geometry_that_goes_degenerate_fails_the_edit_not_the_model(project, tmp_path):
    """A value that makes a zero direction or a sweep path with two points in one place fails the edit
    with the field's name, before the model's transaction: the model stays consistent."""
    folder = tmp_path / "office"
    profile = [[0, 0], [0.02, 0], [0.02, 0.02], [0, 0.02]]
    rail = {**LEG, "id": "rail", "params": [{"key": "gap", "kind": "count", "label": "Gap", "default": 1, "min": 0, "max": 5}],
            "parts": [{"id": "r", "sweep": {"profile": profile, "path": [[0, 0, 0], [0, 0, "gap * 0.1"], [0, 0, 1]]}}]}
    lean = {**LEG, "id": "lean", "params": [{"key": "up", "kind": "count", "label": "Up", "default": 1, "min": 0, "max": 5}],
            "parts": [{"id": "a", "box": {"dx": 0.1, "dy": 0.1, "dz": 0.1}, "anchors": {"p": {"z": 0.1, "dir": [0, 0, "up"]}}},
                      {"id": "b", "attach": "a.p", "box": {"dx": 0.1, "dy": 0.1, "dz": 0.1}}]}
    write_office(folder, rail, "rail.kimobj")
    write_office(folder, lean, "lean.kimobj")
    assert call("set_library_paths", json.dumps({"folder": str(folder)}))["errors"] == []
    for key, label, field in (("office:rail", "Gap", "parts.r.sweep.path"), ("office:lean", "Up", "parts.a.anchors.p.dir")):
        r = call("place_object", project, key, "", 0, 0, 0)
        assert r["ok"], r
        bad = call("set_object_parameter", json.dumps([r["guid"]]), label, "0", "")
        assert not bad["ok"] and bad["error"].startswith(field), bad
        placed = call("place_object", project, key, json.dumps({label.lower(): 0}), 1, 0, 0)
        assert not placed["ok"] and placed["error"].startswith(field), placed
        assert not b._inconsistent
        assert call("set_object_parameter", json.dumps([r["guid"]]), label, "2", "")["ok"]  # a normal edit still works
    chair = call("place_object", project, "chair", "", 3, 0, 0)
    assert chair["ok"] and call("set_object_parameter", json.dumps([chair["guid"]]), "Width", "0.5", "")["ok"]
    library.load_office()


def test_an_office_object_named_like_a_template_leaves_the_chair_alone(project, tmp_path):
    """The chair's `use` "leg_{leg_style}" names its own components (the choice's options): an office
    object called leg_rest is not part of it, so the chair's hash and placed chairs do not change."""
    chair = library.OBJECTS["chair"]
    before = library._hash_of(chair)
    guid = call("place_object", project, "chair", "", 0, 0, 0)["guid"]
    write_office(tmp_path / "office", {**LEG, "id": "leg_rest"}, "leg_rest.kimobj")
    assert call("set_library_paths", json.dumps({"folder": str(tmp_path / "office")}))["errors"] == []
    assert library._hash_of(chair) == before == chair.hash
    assert call("library_updates", "")["outdated"] == 0
    fresh = call("place_object", project, "chair", json.dumps({"width": 0.5}), 2, 0, 0)
    ps = ifcopenshell.util.element.get_pset(b._model.by_guid(fresh["type"]), library.PSET)
    assert json.loads(ps["Uses"]) == {}
    assert call("set_object_parameter", json.dumps([guid]), "Width", "0.5", "")["ok"]
    # a choice whose options name library objects takes exactly those
    picker = {**TOP, "id": "picker", "params": [
        *TOP["params"], {"key": "which", "kind": "choice", "label": "Which", "default": "leg",
                         "options": [{"id": "leg", "label": "Leg"}]}],
        "parts": [{"id": "l", "use": "office:{which}", "with": {"h": "height"}}]}
    write_office(tmp_path / "office", LEG, "leg.kimobj")
    write_office(tmp_path / "office", picker, "picker.kimobj")
    assert call("set_library_paths", json.dumps({"folder": str(tmp_path / "office")}))["errors"] == []
    assert list(library._uses_of(library.get("office:picker"))) == ["office:leg"]
    library.load_office()


def test_long_texts_are_ifc_text_and_round_trip(project, tmp_path):
    """Definition, Uses and Parameters are IfcText (IfcLabel holds 255 characters): a 10 kB definition
    survives a save and reopen and still edits."""
    big = json.loads(json.dumps(STOOL))
    big["symbol"] = [{"line": {"points": [[round(k * 0.001, 3), round((k % 7) * 0.01, 3)] for k in range(1500)]}}]
    write_office(tmp_path / "office", big)
    call("set_library_paths", json.dumps({"folder": str(tmp_path / "office")}))
    obj = library.get("office:stool")
    assert len(obj.text) >= 10_000
    r = call("place_object", project, "office:stool", "", 0, 0, 0)
    t = b._model.by_guid(r["type"])
    pset = next(p for p in t.HasPropertySets if p.Name == library.PSET)
    kinds = {p.Name: p.NominalValue.is_a() for p in pset.HasProperties}
    assert kinds["Definition"] == kinds["Uses"] == kinds["Parameters"] == "IfcText"
    assert kinds["Object"] == "IfcLabel"
    path = tmp_path / "long.ifc"
    b.save(str(path))
    library.load_office()
    assert call("open_model", str(path))["ok"]
    t = ifcopenshell.util.element.get_type(b._model.by_guid(r["guid"]))
    assert ifcopenshell.util.element.get_pset(t, library.PSET)["Definition"] == obj.text
    assert call("set_object_parameter", json.dumps([r["guid"]]), "Legs", "5", "")["ok"]


def test_a_tampered_stored_definition_is_not_an_object(project):
    import ifcopenshell.api.pset

    r = call("place_object", project, "chair", "", 0, 0, 0)
    t = b._model.by_guid(r["type"])
    data = json.loads(ifcopenshell.util.element.get_pset(t, library.PSET)["Definition"])
    data["parts"][0]["repeat"] = {}
    pset = next(p for p in t.HasPropertySets if p.Name == library.PSET)
    ifcopenshell.api.pset.edit_pset(b._model, pset=pset, properties={"Definition": b._model.createIfcText(json.dumps(data))})
    assert library.definition_of_type(t) is None
    bad = call("set_object_parameter", json.dumps([r["guid"]]), "Width", "0.5", "")
    assert not bad["ok"] and "no selected object" in bad["error"]


def test_a_parameter_labelled_type_keeps_the_summary_type_row(project, tmp_path):
    """D100: the Parameters summary's Type row is the type's name; a parameter labelled "Type" shows too,
    under another row name."""
    block = {
        "format": "kimbim-object/1", "id": "typed", "name": "Typed", "category": "furniture",
        "ifc": {"IFC4": ["IfcFurnitureType", "NOTDEFINED", None]},
        "params": [{"key": "width", "kind": "length", "label": "Width", "default": 0.4},
                   {"key": "kind", "kind": "choice", "label": "Type", "default": "a",
                    "options": [{"id": "a", "label": "Plain"}, {"id": "b", "label": "Fancy"}]}],
        "parts": [{"id": "body", "box": {"dx": "width", "dy": 0.4, "dz": 0.4}}],
    }
    (tmp_path / "typed.kimobj").write_text(json.dumps(block), encoding="utf-8")
    library.load_office(str(tmp_path))
    assert library.get("office:typed") is not None, library._office_errors
    p = call("place_object", project, "office:typed", "", 0, 0, 0)
    group = call("properties_multi", json.dumps([p["guid"]]))["psets"]["Parameters"]
    assert group["Type"]["value"] == b._model.by_guid(p["type"]).Name
    assert [row["value"] for name, row in group.items() if name != "Type"] == [0.4, "Plain"]
