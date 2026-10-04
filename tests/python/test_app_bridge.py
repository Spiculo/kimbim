# SPDX-License-Identifier: GPL-3.0-or-later
import json

from conftest import build_model

from kimcad import app_bridge


def _names(node, out):
    out.append(node["name"])
    for c in node["children"]:
        _names(c, out)
    return out


def test_open_tree_properties(tmp_path):
    f = build_model(walls=2)
    f.by_type("IfcWall")[0].Name = "Muro Ñandú 墙"
    p = tmp_path / "Proyecto ñ" / "modelo.ifc"
    p.parent.mkdir()
    f.write(str(p))
    info = json.loads(app_bridge.open_model(str(p)))
    assert info["ok"] and info["schema"] == "IFC4" and info["elements"] >= 2
    tree = json.loads(app_bridge.spatial_tree())
    assert tree["type"] == "IfcProject"
    names = _names(tree, [])
    assert "Muro Ñandú 墙" in names and "Level 1" in names
    wall = f.by_type("IfcWall")[0]
    props = json.loads(app_bridge.properties(wall.GlobalId))
    assert props["type"] == "IfcWall" and props["name"] == "Muro Ñandú 墙"
    assert props["psets"]["Pset_WallCommon"]["FireRating"] == "EI30"
    assert props["attributes"]["GlobalId"] == wall.GlobalId


def test_open_errors_are_reported_not_raised(tmp_path):
    bad = tmp_path / "bad.ifc"
    bad.write_text("not an ifc file")
    info = json.loads(app_bridge.open_model(str(bad)))
    assert info["ok"] is False and info["error"]
    missing = json.loads(app_bridge.open_model(str(tmp_path / "missing.ifc")))
    assert missing["ok"] is False
    assert json.loads(app_bridge.properties("nope"))["error"]


def test_write_test_model_helper(tmp_path):
    p = tmp_path / "fixture.ifc"
    assert json.loads(app_bridge._write_test_model(str(p)))["ok"]
    assert json.loads(app_bridge.open_model(str(p)))["elements"] >= 2
