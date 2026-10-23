# SPDX-License-Identifier: GPL-3.0-or-later
"""The object library (D86): every object makes a valid IFC type with a body and a plan symbol,
placements share their type (mapped items), parameters re-generate it, plans draw the symbol, IFC2X3
gets its own classes, and the office library adds .kimobj definitions and IFC types (D99). Types carry
their definition, so a project edits its objects without the library that made them."""
import json
import pathlib

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.validate
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
    group = call("properties_multi", json.dumps([a]))["psets"]["Parameters"]
    assert group["Width"]["value"] == 2.0 and group["Seats"]["value"] == 3
    # Only one of two placements: it moves to a new type, the other keeps its own.
    r = call("set_object_parameter", json.dumps([a]), "Width", "2.4")
    assert r["ok"], r
    ta = ifcopenshell.util.element.get_type(b._model.by_guid(a))
    tc = ifcopenshell.util.element.get_type(b._model.by_guid(c))
    assert ta != tc and "2400" in ta.Name and "2000" in tc.Name
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


def test_parameter_scope_can_change_every_placement_or_only_the_selection(project):
    """D92: editing a shared object's parameter asks (in the app) whether to change its type or the
    selection; the choice goes to set_object_parameter's `scope`."""
    a = call("place_object", project, "sofa", "", 0, 0, 0)["guid"]
    c = call("place_object", project, "sofa", "", 3, 0, 0)["guid"]
    usage = call("object_parameter_usage", json.dumps([a]), "Width")
    assert usage["elements"] == 2 and usage["selected"] == 1 and usage["shared"]
    # Only the selection: the other keeps its type.
    assert call("set_object_parameter", json.dumps([a]), "Width", "2.6", "selection")["ok"]
    ta = ifcopenshell.util.element.get_type(b._model.by_guid(a))
    tc = ifcopenshell.util.element.get_type(b._model.by_guid(c))
    assert ta != tc and "2600" in ta.Name and "2000" in tc.Name
    # Another sofa shares c's type; asking for the whole type changes both placements.
    d = call("place_object", project, "sofa", "", 6, 0, 0)["guid"]
    usage = call("object_parameter_usage", json.dumps([c]), "Seats")
    assert usage["elements"] == 2 and usage["shared"]
    assert call("set_object_parameter", json.dumps([c]), "Seats", "2", "type")["ok"]
    tc = ifcopenshell.util.element.get_type(b._model.by_guid(c))
    td = ifcopenshell.util.element.get_type(b._model.by_guid(d))
    assert tc == td and "Seats 2" in tc.Name
    assert ifcopenshell.util.element.get_type(b._model.by_guid(a)) != tc


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
    assert group["Foot"]["choices"] == ["Round", "Square"] and group["Foot"]["value"] == "Round"
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
