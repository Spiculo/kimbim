# SPDX-License-Identifier: GPL-3.0-or-later
"""Configurable IFC export: scopes (all, selection, level, class), annotation/space/opening flags,
property renames, and validation of the written file."""
import json

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.util.element
import ifcopenshell.validate
import pytest

from kimbim import app_bridge as B
from kimbim import ifcexport as E
from kimbim.testing import build_model


def call(fn, *args):
    return json.loads(fn(*args))


def open_model(walls=4):
    f = build_model(walls=walls)
    B._model = f
    B._reset_history("")
    return f


def add_extras(f):
    """An annotation, a space and an opening (one of each class the include_* flags control)."""
    storey = f.by_type("IfcBuildingStorey")[0]
    wall = f.by_type("IfcWall")[0]
    annotation = ifcopenshell.api.root.create_entity(f, ifc_class="IfcAnnotation", name="Note")
    space = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSpace", name="Room")
    opening = ifcopenshell.api.root.create_entity(f, ifc_class="IfcOpeningElement", name="Void")
    ifcopenshell.api.spatial.assign_container(f, products=[annotation], relating_structure=storey)
    ifcopenshell.api.aggregate.assign_object(f, products=[space], relating_object=storey)
    ifcopenshell.api.feature.add_feature(f, feature=opening, element=wall)
    return annotation, space, opening


def issues(model):
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    return logger.statements


def test_export_options():
    f = open_model()
    add_extras(f)
    r = call(E.export_options)
    assert r["ok"], r
    assert r["scopes"] == ["all", "selection", "level", "class"]
    classes = {c["name"]: c["count"] for c in r["classes"]}
    assert classes["IfcWall"] == 4
    assert classes["IfcAnnotation"] == 1 and classes["IfcSpace"] == 1 and classes["IfcOpeningElement"] == 1
    assert r["levels"] == [{"guid": f.by_type("IfcBuildingStorey")[0].GlobalId, "name": "Level 1"}]
    assert r["defaults"]["scope"] == "all"
    assert r["defaults"]["include_annotations"] is True
    assert r["defaults"]["property_map"] == {}


def test_export_all_validates(tmp_path):
    f = open_model()
    add_extras(f)
    out = tmp_path / "all.ifc"
    r = call(E.export_ifc, str(out))
    assert r["ok"], r
    assert r["products"] == 7  # four walls + annotation + space + opening
    assert r["removed"] == 0
    assert r["bytes"] == out.stat().st_size
    assert {c["name"]: c["count"] for c in r["classes"]}["IfcWall"] == 4

    written = ifcopenshell.open(str(out))
    assert written.schema_identifier == "IFC4"
    assert len(written.by_type("IfcWall")) == 4
    assert len(written.by_type("IfcAnnotation")) == 1
    assert len(written.by_type("IfcSpace")) == 1
    assert len(written.by_type("IfcOpeningElement")) == 1
    assert len(written.by_type("IfcBuildingStorey")) == 1
    assert issues(written) == []


def test_export_selection_keeps_the_container(tmp_path):
    f = open_model()
    add_extras(f)
    wall = f.by_type("IfcWall")[2]
    out = tmp_path / "selection.ifc"
    r = call(E.export_ifc, str(out), json.dumps({"scope": "selection", "guids": [wall.GlobalId]}))
    assert r["ok"], r
    assert r["products"] == 1
    assert r["removed"] == 6

    written = ifcopenshell.open(str(out))
    assert [w.GlobalId for w in written.by_type("IfcWall")] == [wall.GlobalId]
    assert written.by_type("IfcBuildingStorey") and written.by_type("IfcBuilding")
    assert issues(written) == []


def test_export_level(tmp_path):
    f = open_model()
    storey = f.by_type("IfcBuildingStorey")[0]
    building = f.by_type("IfcBuilding")[0]
    upper = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Level 2")
    ifcopenshell.api.aggregate.assign_object(f, products=[upper], relating_object=building)
    ifcopenshell.api.geometry.edit_object_placement(f, product=upper)
    ifcopenshell.api.spatial.assign_container(f, products=f.by_type("IfcWall")[2:], relating_structure=upper)
    add_extras(f)  # on Level 1

    out = tmp_path / "level.ifc"
    r = call(E.export_ifc, str(out), json.dumps({"scope": "level", "levels": [storey.GlobalId]}))
    assert r["ok"], r
    written = ifcopenshell.open(str(out))
    assert {w.GlobalId for w in written.by_type("IfcWall")} == {w.GlobalId for w in f.by_type("IfcWall")[:2]}
    assert len(written.by_type("IfcBuildingStorey")) == 2  # the spatial structure stays
    assert issues(written) == []


def test_export_class(tmp_path):
    f = open_model()
    add_extras(f)
    out = tmp_path / "class.ifc"
    r = call(E.export_ifc, str(out), json.dumps({"scope": "class", "classes": ["IfcWall"]}))
    assert r["ok"], r
    assert r["products"] == 4
    written = ifcopenshell.open(str(out))
    assert len(written.by_type("IfcWall")) == 4
    assert not written.by_type("IfcAnnotation")
    assert not written.by_type("IfcSpace")
    assert not written.by_type("IfcOpeningElement")
    assert issues(written) == []


def test_flags_exclude_annotations_spaces_openings(tmp_path):
    f = open_model()
    add_extras(f)
    out = tmp_path / "clean.ifc"
    r = call(E.export_ifc, str(out), json.dumps({
        "include_annotations": False, "include_spaces": False, "include_openings": False}))
    assert r["ok"], r
    assert r["products"] == 4
    written = ifcopenshell.open(str(out))
    assert not written.by_type("IfcAnnotation")
    assert not written.by_type("IfcSpace")
    assert not written.by_type("IfcOpeningElement")
    assert len(written.by_type("IfcWall")) == 4
    assert issues(written) == []


def test_property_rename(tmp_path):
    f = open_model()
    out = tmp_path / "renamed.ifc"
    r = call(E.export_ifc, str(out), json.dumps({
        "property_map": {"Pset_WallCommon": {"FireRating": "FireRatingNew"}}}))
    assert r["ok"], r
    written = ifcopenshell.open(str(out))
    for wall in written.by_type("IfcWall"):
        props = ifcopenshell.util.element.get_pset(wall, "Pset_WallCommon")
        assert "FireRatingNew" in props and "FireRating" not in props
        assert props["FireRatingNew"] == "EI30"
    # The open model is untouched.
    for wall in f.by_type("IfcWall"):
        props = ifcopenshell.util.element.get_pset(wall, "Pset_WallCommon")
        assert "FireRating" in props and "FireRatingNew" not in props


@pytest.mark.parametrize("options,path", [
    ({"scope": "nope"}, "out.ifc"),
    ({"scope": "selection", "guids": ["not-a-guid"]}, "out.ifc"),
    ({"scope": "class", "classes": ["IfcDoor"]}, "out.ifc"),
    ({"scope": "class", "classes": []}, "out.ifc"),
    ({}, ""),
])
def test_invalid_options(tmp_path, options, path):
    open_model()
    r = call(E.export_ifc, path or "", json.dumps(options))
    assert r["ok"] is False and r["error"]


def test_invalid_path_and_json(tmp_path):
    open_model()
    assert call(E.export_ifc, str(tmp_path))["ok"] is False  # a directory
    assert call(E.export_ifc, str(tmp_path / "x.ifc"), "not json")["ok"] is False
    assert call(E.export_ifc, str(tmp_path / "x.ifc"), "[]")["ok"] is False


def test_no_model_open():
    B._model = None
    assert call(E.export_options)["ok"] is False
    assert call(E.export_ifc, "out.ifc")["ok"] is False

def test_the_bridge_wires_export_options_and_ifc_export(tmp_path):
    open_model(2)
    out = call(B.export_options)
    assert out["ok"] and out["scopes"] == ["all", "selection", "level", "class"]
    path = tmp_path / "bridge.ifc"
    made = call(B.ifc_export, str(path), json.dumps({"scope": "all"}))
    assert made["ok"] and path.exists() and made["products"] > 0
