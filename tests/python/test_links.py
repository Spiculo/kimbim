# SPDX-License-Identifier: GPL-3.0-or-later
"""Linked models (hotlinks): one read-only proxy per linked IFC, its KIMBIM_Link properties,
triangles and bounds, update, transform, unlink (with undo) and the error paths."""
import hashlib
import json

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.util.element
import ifcopenshell.util.representation
import ifcopenshell.validate
import numpy as np
import pytest

from kimbim import app_bridge as B
from kimbim import links as L
from kimbim.testing import _reset_owner, build_model


def call(fn, *args):
    return json.loads(fn(*args))


def open_model(schema="IFC4", walls=2):
    f = build_model(schema=schema, walls=walls)
    B._model = f
    B._reset_history("")
    return f, f.by_type("IfcBuildingStorey")[0].GlobalId


def source(tmp_path, walls=2, name="source.ifc"):
    f = build_model(walls=walls)
    path = tmp_path / name
    f.write(str(path))
    return path


def issues(model=None):
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model or B._model, logger, express_rules=True)
    return logger.statements


def mesh(guid):
    import ifcopenshell.geom

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    shape = ifcopenshell.geom.create_shape(settings, B._model.by_guid(guid))
    return np.array(shape.geometry.verts).reshape(-1, 3), np.array(shape.geometry.faces).reshape(-1, 3)


def test_link_model(tmp_path):
    f, level = open_model()
    src = source(tmp_path)
    r = call(L.link_model, str(src), json.dumps({"name": "Reference house"}))
    assert r["ok"], r
    assert r["elements"] == 2
    assert r["triangles"] > 0

    element = f.by_guid(r["guid"])
    assert element.is_a("IfcBuildingElementProxy")
    assert element.ObjectType == "Linked model"
    assert element.Name == "Reference house"
    assert ifcopenshell.util.element.get_container(element).GlobalId == level

    data = ifcopenshell.util.element.get_pset(element, L.PSET)
    assert data["Path"] == str(src.resolve())
    assert data["Name"] == "Reference house"
    assert data["ElementCount"] == 2
    assert data["SourceHash"] == hashlib.sha1(src.read_bytes()).hexdigest()
    assert data["Updated"]
    assert json.loads(data["Transform"]) == {"x": 0.0, "y": 0.0, "z": 0.0, "rotation": 0.0,
                                             "scale": 1.0, "visible": True}

    verts, faces = mesh(r["guid"])
    assert len(faces) == r["triangles"]
    assert r["bounds"] == {"min": [round(float(verts[:, i].min()), 6) for i in range(3)],
                           "max": [round(float(verts[:, i].max()), 6) for i in range(3)]}
    assert issues() == []


def test_link_with_transform(tmp_path):
    f, _level = open_model()
    src = source(tmp_path)
    plain = call(L.link_model, str(src))
    call(L.unlink, plain["guid"])
    r = call(L.link_model, str(src), json.dumps({
        "x": 10, "y": 2, "z": 1, "rotation": 90, "scale": 2}))
    assert r["ok"], r
    plain_centre = [(plain["bounds"]["min"][i] + plain["bounds"]["max"][i]) / 2 for i in range(3)]
    centre = [(r["bounds"]["min"][i] + r["bounds"]["max"][i]) / 2 for i in range(3)]
    assert centre[0] == pytest.approx(10.0 - 2 * plain_centre[1], abs=1e-6)
    assert centre[1] == pytest.approx(2.0 + 2 * plain_centre[0], abs=1e-6)
    assert centre[2] == pytest.approx(1.0 + 2 * plain_centre[2], abs=1e-6)  # source z 0..3, scaled 2, raised 1
    assert r["bounds"]["max"][2] - r["bounds"]["min"][2] == pytest.approx(6.0)
    assert issues() == []


def test_update_after_the_source_changes(tmp_path):
    f, _level = open_model()
    src = source(tmp_path)
    r = call(L.link_model, str(src))
    assert r["ok"], r
    element = f.by_guid(r["guid"])
    old = ifcopenshell.util.element.get_pset(element, L.PSET)
    old_bounds = r["bounds"]

    changed = ifcopenshell.open(str(src))
    wall = changed.by_type("IfcWall")[0]
    matrix = np.eye(4)
    matrix[0][3] = 20.0
    ifcopenshell.api.geometry.edit_object_placement(changed, product=wall, matrix=matrix, is_si=True)
    changed.write(str(src))

    steps = len(B._ids)
    updated = call(L.update_link, r["guid"])
    assert updated["ok"], updated
    assert len(B._ids) == steps + 1  # one undo step
    assert f.by_guid(r["guid"]).GlobalId == r["guid"]
    data = ifcopenshell.util.element.get_pset(f.by_guid(r["guid"]), L.PSET)
    assert data["SourceHash"] == hashlib.sha1(src.read_bytes()).hexdigest()
    assert data["SourceHash"] != old["SourceHash"]
    assert data["ElementCount"] == 2
    assert updated["bounds"]["max"][0] > old_bounds["max"][0]
    assert issues() == []


def test_set_link_transform(tmp_path):
    f, _level = open_model()
    src = source(tmp_path)
    r = call(L.link_model, str(src))
    moved = call(L.set_link_transform, r["guid"], json.dumps({"x": 5, "scale": 2}))
    assert moved["ok"], moved
    data = ifcopenshell.util.element.get_pset(f.by_guid(r["guid"]), L.PSET)
    transform = json.loads(data["Transform"])
    assert transform["x"] == 5.0 and transform["scale"] == 2.0 and transform["rotation"] == 0.0
    assert moved["bounds"]["min"][0] == pytest.approx(5.0, abs=1e-6)
    assert moved["bounds"]["max"][2] == pytest.approx(6.0)
    assert issues() == []

    turned = call(L.set_link_transform, r["guid"], json.dumps({"rotation": 90}))
    assert turned["ok"], turned
    assert json.loads(ifcopenshell.util.element.get_pset(f.by_guid(r["guid"]), L.PSET)["Transform"])["rotation"] == 90.0
    moved_centre_y = (moved["bounds"]["min"][1] + moved["bounds"]["max"][1]) / 2
    centre = [(turned["bounds"]["min"][i] + turned["bounds"]["max"][i]) / 2 for i in range(3)]
    assert centre[0] == pytest.approx(5.0 - moved_centre_y, abs=1e-6)


def test_unlink_is_one_undo_step(tmp_path):
    f, _level = open_model()
    src = source(tmp_path)
    r = call(L.link_model, str(src))
    assert call(L.list_links)["links"][0]["guid"] == r["guid"]

    removed = call(L.unlink, r["guid"])
    assert removed["ok"], removed
    with pytest.raises(RuntimeError):
        f.by_guid(r["guid"])
    assert call(L.list_links)["links"] == []

    B.undo()
    assert f.by_guid(r["guid"]).is_a("IfcBuildingElementProxy")
    assert len(call(L.list_links)["links"]) == 1


def test_list_links(tmp_path):
    open_model()
    src = source(tmp_path, name="tower.ifc")
    r = call(L.link_model, str(src))
    links = call(L.list_links)["links"]
    assert len(links) == 1
    link = links[0]
    assert link["guid"] == r["guid"]
    assert link["name"] == "tower"  # the file stem
    assert link["path"] == str(src.resolve())
    assert link["elements"] == 2
    assert link["triangles"] == r["triangles"]
    assert link["transform"]["scale"] == 1.0
    assert link["updated"]


def test_ifc2x3_uses_a_surface_model(tmp_path):
    src = source(tmp_path)  # build the source first: build_model resets the global owner callbacks
    try:
        f, _level = open_model("IFC2X3", walls=0)
        r = call(L.link_model, str(src), json.dumps({"name": "Reference"}))
        assert r["ok"], r
        element = f.by_guid(r["guid"])
        assert element.is_a("IfcBuildingElementProxy") and element.ObjectType == "Linked model"
        representation = ifcopenshell.util.representation.get_representation(
            element, "Model", "Body", "MODEL_VIEW")
        assert representation is not None
        assert representation.RepresentationType == "SurfaceModel"
        assert issues() == []
    finally:
        _reset_owner()  # the IFC2X3 owner callbacks are global


def test_errors(tmp_path):
    open_model()
    src = source(tmp_path)
    missing = tmp_path / "missing.ifc"
    assert call(L.link_model, str(missing))["ok"] is False
    assert call(L.link_model, str(src), "not json")["ok"] is False
    assert call(L.link_model, str(src), "[]")["ok"] is False
    assert call(L.link_model, str(src), json.dumps({"level": "No such level"}))["ok"] is False
    assert call(L.link_model, str(src), json.dumps({"scale": 0}))["ok"] is False

    r = call(L.link_model, str(src))
    assert r["ok"], r
    assert call(L.update_link, "not-a-guid")["ok"] is False
    assert call(L.set_link_transform, r["guid"], "not json")["ok"] is False
    assert call(L.set_link_transform, r["guid"], json.dumps({"scale": 0}))["ok"] is False
    assert call(L.unlink, "not-a-guid")["ok"] is False


def test_no_model_open():
    B._model = None
    assert call(L.link_model, "x.ifc")["ok"] is False
    assert call(L.list_links) == {"ok": True, "links": []}

def test_the_bridge_wires_linked_models(tmp_path):
    _f, _level = open_model()
    src = source(tmp_path)
    made = call(B.link_model, str(src))
    assert made["ok"] and made["elements"] > 0
    assert len(call(B.list_links)["links"]) == 1
    assert call(B.update_link, made["guid"])["ok"]
    assert call(B.unlink, made["guid"])["ok"]
    assert call(B.list_links)["links"] == []
