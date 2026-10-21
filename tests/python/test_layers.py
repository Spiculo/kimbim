# SPDX-License-Identifier: GPL-3.0-or-later
"""Owner feedback: layers as boundaries, views as collections of layers (Slice 11)."""
import json

import pytest

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


@pytest.fixture
def model(tmp_path):
    assert call("new_project", "Capas")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    t = call("wall_types")["types"][0]["guid"]
    w1 = call("create_wall", level, t, 0, 0, 5, 0, 3.0, "", "")["guid"]
    w2 = call("create_wall", level, t, 0, 3, 5, 3, 3.0, "", "")["guid"]
    col = call("create_column", level, call("column_types")["types"][0]["guid"], 8, 0, 3.0, 0.0)["guid"]
    return {"level": level, "walls": [w1, w2], "column": col, "type": t, "tmp": tmp_path}


def members():
    return {k: set(v) for k, v in call("layer_members")["layers"].items()}


def test_layers_are_ifc_presentation_layers(model):
    assert call("create_layer", "A-WALL")["ok"]
    assert call("assign_layer", g(*model["walls"]), "A-WALL")["ok"]
    assert members() == {"A-WALL": set(model["walls"])}
    layer = b._model.by_type("IfcPresentationLayerAssignment")[0]
    assert layer.Name == "A-WALL"
    assert {i.is_a() for i in layer.AssignedItems} == {"IfcShapeRepresentation"}
    listing = call("layers")["layers"]
    assert [(x["name"], x["count"]) for x in listing] == [("A-WALL", 2)]
    assert not call("create_layer", "A-WALL")["ok"]  # names are unique


def test_moving_to_another_layer_and_deleting(model):
    call("create_layer", "A-WALL")
    call("create_layer", "S-COLS")
    call("assign_layer", g(*model["walls"], model["column"]), "A-WALL")
    call("assign_layer", g(model["column"]), "S-COLS")  # an element is on one layer
    assert members() == {"A-WALL": set(model["walls"]), "S-COLS": {model["column"]}}
    assert call("rename_layer", "S-COLS", "S-COLUMNS")["ok"]
    assert call("delete_layer", "A-WALL")["ok"]
    assert members() == {"S-COLUMNS": {model["column"]}}
    call("undo")
    assert "A-WALL" in members()


def test_new_elements_go_on_the_active_layer(model):
    call("create_layer", "A-WALL")
    assert call("set_active_layer", "A-WALL")["ok"]
    w = call("create_wall", model["level"], model["type"], 0, 6, 5, 6, 3.0, "", "")["guid"]
    d = call("opening_types", "door")["types"][0]
    door = call("insert_opening", "door", w, d["guid"], 2.5, 0.9, 2.1, 0.0)["guid"]
    assert {w, door} <= members()["A-WALL"]
    assert call("layers")["active"] == "A-WALL"


def test_geometry_edits_and_copies_keep_the_layer(model):
    call("create_layer", "S-COLS")
    call("assign_layer", g(model["column"]), "S-COLS")
    call("set_dimension", g(model["column"]), "Height", "3.5")  # replaces the body representation
    assert model["column"] in members()["S-COLS"]
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    copy = call("copy_to_storey", g(model["column"]), l2)["guids"][0]
    assert copy in members()["S-COLS"]


def test_views_are_saved_in_the_model(model):
    call("create_layer", "A-WALL")
    view = {"hidden": ["A-WALL"], "locked": [], "plan": True, "cut": 1.2}
    assert call("save_view", "Structure only", json.dumps(view))["ok"]
    assert call("views")["views"] == [{"name": "Structure only", "data": view}]
    path = model["tmp"] / "views.ifc"
    call("save", str(path))
    call("open_model", str(path))
    assert call("views")["views"][0]["data"]["hidden"] == ["A-WALL"]
    assert call("delete_view", "Structure only")["ok"]
    assert call("views")["views"] == []


def test_saved_views_keep_cut_planes(model):
    """D95: cut planes are view state; they travel in a saved view's data unchanged."""
    plane = {"name": "Vertical cut 1", "enabled": True, "kind": "vertical",
             "point": [0.0, 1.0, 2.5], "normal": [1.0, 0.0, 0.0],
             "direction": [0.0, 1.0, 0.0], "angle": 0.0}
    view = {"plan": False, "planes": [plane]}
    assert call("save_view", "Cutaway", json.dumps(view))["ok"]
    path = model["tmp"] / "cut-planes.ifc"
    call("save", str(path))
    call("open_model", str(path))
    assert call("views")["views"][0]["data"]["planes"] == [plane]
