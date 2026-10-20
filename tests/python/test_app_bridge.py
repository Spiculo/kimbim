# SPDX-License-Identifier: GPL-3.0-or-later
import json

from conftest import build_model

from kimbim import app_bridge


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


def _model_with_space(tmp_path):
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.root

    f = build_model(walls=3)
    space = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSpace", name="Room without body")
    # IFC4: spaces are spatial elements, aggregated under the storey (not contained in it)
    ifcopenshell.api.aggregate.assign_object(f, products=[space], relating_object=f.by_type("IfcBuildingStorey")[0])
    p = tmp_path / "m.ifc"
    f.write(str(p))
    return f, p


def _chunks(max_elements):
    import struct

    out = []
    while (c := app_bridge.next_mesh_chunk(max_elements)) is not None:
        meta, verts, tris = c
        meta = json.loads(meta)
        nv, nt = len(verts) // 12, len(tris) // 12
        assert meta["voff"][-1] == nv and meta["toff"][-1] == nt
        assert len(meta["guids"]) == len(meta["types"]) == len(meta["voff"]) - 1 == len(meta["toff"]) - 1
        idx = struct.unpack(f"<{nt * 3}I", tris)
        assert max(idx) < nv
        out.append(meta)
    return out


def test_mesh_chunks_cover_all_elements_with_geometry(tmp_path):
    f, p = _model_with_space(tmp_path)
    assert json.loads(app_bridge.open_model(str(p)))["ok"]
    started = json.loads(app_bridge.start_meshing(0))
    assert started["ok"]
    chunks = _chunks(2)
    guids = [g for c in chunks for g in c["guids"]]
    assert sorted(guids) == sorted(w.GlobalId for w in f.by_type("IfcWall"))  # the space has no body
    assert [len(c["guids"]) for c in chunks] == [2, 1]
    # elements without geometry are still in the tree
    tree = json.loads(app_bridge.spatial_tree())
    assert "Room without body" in _names(tree, [])


def test_meshing_without_open_model_reports_error():
    app_bridge._model = None
    assert json.loads(app_bridge.start_meshing(0))["ok"] is False
    assert app_bridge.next_mesh_chunk(10) is None
