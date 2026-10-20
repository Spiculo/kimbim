# SPDX-License-Identifier: GPL-3.0-or-later
"""The object library (D86): every object makes a valid IFC type with a body and a plan symbol,
placements share their type (mapped items), parameters re-generate it, plans draw the symbol, IFC2X3
gets its own classes, and the office library adds Python objects and IFC types."""
import json

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



def test_office_library_python_and_ifc_types(project, tmp_path):
    folder = tmp_path / "office"
    folder.mkdir()
    (folder / "stool.py").write_text(
        "def build(s, p):\n"
        "    s.cylinder(p['width'] / 2, p['width'] / 2, 0, p['width'] / 2, p['height'])\n"
        "    s.circle(p['width'] / 2, p['width'] / 2, p['width'] / 2)\n"
        "define('office_stool', 'Stool', 'office', FURNITURE('CHAIR'), [W(0.35), H(0.6)], build)\n",
        encoding="utf-8")
    # An IFC type library made from a placed bundled object.
    call("place_object", project, "desk", "", 0, 0, 0)
    b.save(str(folder / "types.ifc"))
    desk_type = b._model.by_type("IfcFurnitureType")[0].GlobalId
    assert call("new_project", "Other")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    r = call("set_library_paths", json.dumps({"folder": str(folder)}))
    assert r["ok"] and r["errors"] == [], r
    listed = {o["id"]: o for o in call("library_objects")["objects"]}
    assert listed["office_stool"]["category"] == "office" and listed["office_stool"]["symbol"]
    ifc_key = next(k for k in listed if k.startswith("ifc:") and k.endswith(desk_type))
    assert call("place_object", storey, "office_stool", "", 0, 0, 0)["ok"]
    first = call("place_object", storey, ifc_key, "", 2, 0, 0)
    second = call("place_object", storey, ifc_key, "", 4, 0, 0)
    assert first["ok"] and first["type"] == second["type"] == desk_type  # copied once, then reused
    assert validate(b._model) == []
    assert "office_stool" not in library.OBJECTS  # office objects stay out of the bundled list
