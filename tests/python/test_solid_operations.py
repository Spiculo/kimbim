# SPDX-License-Identifier: GPL-3.0-or-later
"""Solid element operations through the bridge: cut a wall with another wall, as one undo step."""
import json

import ifcopenshell.geom

from kimbim import app_bridge
from kimbim.testing import build_model


def _body(element):
    return next(s for s in element.Representation.Representations
                if s.RepresentationIdentifier == "Body")


def _wall(guid):
    return app_bridge._model.by_guid(guid)


def test_cut_two_walls_and_undo(tmp_path):
    model = build_model(walls=2)
    path = tmp_path / "cut.ifc"
    model.write(str(path))
    assert json.loads(app_bridge.open_model(str(path)))["ok"]
    first, second = app_bridge._model.by_type("IfcWall")[:2]
    target, tool = first.GlobalId, second.GlobalId

    result = json.loads(app_bridge.cut_elements(target, tool))
    assert result["ok"], result
    item = _body(_wall(target)).Items[0]
    assert item.is_a("IfcBooleanResult") and item.Operator == "DIFFERENCE"
    assert item.SecondOperand == _body(_wall(tool)).Items[0]
    assert item.FirstOperand.is_a("IfcSolidModel")
    assert _body(_wall(tool)).Items[0].is_a("IfcSolidModel")

    # Every IFC engine can still build the cut geometry.
    settings = ifcopenshell.geom.settings()
    iterator = ifcopenshell.geom.iterator(settings, app_bridge._model, 1, include=[_wall(target)])
    assert iterator.initialize()

    assert json.loads(app_bridge.undo())["ok"]
    assert not _body(_wall(target)).Items[0].is_a("IfcBooleanResult")


def test_cut_reports_an_element_without_a_body(tmp_path):
    model = build_model(walls=1)
    project = model.by_type("IfcProject")[0]
    path = tmp_path / "nobody.ifc"
    model.write(str(path))
    assert json.loads(app_bridge.open_model(str(path)))["ok"]
    wall = app_bridge._model.by_type("IfcWall")[0]
    result = json.loads(app_bridge.cut_elements(wall.GlobalId, project.GlobalId))
    assert not result["ok"] and "Body representation" in result["error"]


def test_intersection_and_multi_tool_union(tmp_path):
    model = build_model(walls=3)
    path = tmp_path / "ops.ifc"
    model.write(str(path))
    assert json.loads(app_bridge.open_model(str(path)))["ok"]
    target, tool, third = (w.GlobalId for w in app_bridge._model.by_type("IfcWall")[:3])

    result = json.loads(app_bridge.boolean_elements(target, json.dumps([tool]), "INTERSECTION"))
    assert result["ok"], result
    item = _body(_wall(target)).Items[0]
    assert item.Operator == "INTERSECTION" and item.SecondOperand == _body(_wall(tool)).Items[0]
    assert json.loads(app_bridge.undo())["ok"]

    result = json.loads(app_bridge.boolean_elements(target, json.dumps([tool, third]), "UNION"))
    assert result["ok"] and result["operator"] == "UNION", result
    item = _body(_wall(target)).Items[0]
    depth = 0
    while item.is_a("IfcBooleanResult"):
        assert item.Operator == "UNION"
        depth += 1
        item = item.FirstOperand
    assert depth == 2  # target + two tools, folded left to right

    assert not json.loads(app_bridge.boolean_elements(target, json.dumps([tool]), "FUSE"))["ok"]


def test_batch_cuts_several_targets_in_one_undo_step(tmp_path):
    model = build_model(walls=3)
    path = tmp_path / "batch.ifc"
    model.write(str(path))
    assert json.loads(app_bridge.open_model(str(path)))["ok"]
    first, second, tool = (w.GlobalId for w in app_bridge._model.by_type("IfcWall")[:3])

    result = json.loads(app_bridge.boolean_batch(json.dumps([first, second]), json.dumps([tool]), "DIFFERENCE"))
    assert result["ok"] and result["changed"] == 2, result
    for guid in (first, second):
        assert _body(_wall(guid)).Items[0].Operator == "DIFFERENCE"

    assert json.loads(app_bridge.undo())["ok"]  # one step restores both targets
    for guid in (first, second):
        assert not _body(_wall(guid)).Items[0].is_a("IfcBooleanResult")
