# SPDX-License-Identifier: GPL-3.0-or-later
"""Terrain (site mesh): survey points and contour polylines, IFC4 tessellation and the IFC2X3
shell fallback, building pads, listing, deleting and a saved-model validation."""
import json
import math

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.representation
import ifcopenshell.validate
import numpy as np
import pytest

from kimbim import app_bridge as B
from kimbim import terrain as T
from kimbim.testing import _reset_owner, build_model

RECT = [[0, 0, 0], [10, 0, 0], [10, 8, 5], [0, 8, 5]]
GRID = [[float(x), float(y), x * 0.5 + y * 0.25] for y in range(4) for x in range(4)]  # 4 x 4
PAD = [[0.5, 0.5], [2.5, 0.5], [2.5, 2.5], [0.5, 2.5]]
CONTOURS = [
    [[0, 0, 0], [10, 0, 0], [10, 8, 0], [0, 8, 0], [0, 0, 0]],
    [[3, 3, 5], [7, 3, 5], [7, 5, 5], [3, 5, 5], [3, 3, 5]],
]


def call(fn, *args):
    return json.loads(fn(*args))


def open_model(schema="IFC4"):
    f = build_model(schema=schema, walls=0)
    B._model = f
    B._reset_history("")
    return f, f.by_type("IfcBuildingStorey")[0].GlobalId


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


def test_terrain_from_points():
    f, level = open_model()
    r = call(T.create_terrain, level, json.dumps(RECT), json.dumps({"name": "Site"}))
    assert r["ok"], r
    assert r["triangles"] == 2
    assert r["bounds"] == {"min": [0.0, 0.0, 0.0], "max": [10.0, 8.0, 5.0]}
    element = f.by_guid(r["guid"])
    assert element.is_a("IfcGeographicElement")
    assert element.PredefinedType == "USERDEFINED" and element.ObjectType == "Terrain"
    assert element.Name == "Site"
    assert ifcopenshell.util.element.get_container(element).GlobalId == level
    data = ifcopenshell.util.element.get_pset(element, T.PSET)
    assert data["Source"] == "points"
    assert data["PointCount"] == 4
    assert data["MinElevation"] == pytest.approx(0.0)
    assert data["MaxElevation"] == pytest.approx(5.0)
    verts, faces = mesh(r["guid"])
    assert len(faces) == 2
    assert verts[:, 2].min() == pytest.approx(0.0) and verts[:, 2].max() == pytest.approx(5.0)
    assert issues() == []


def test_terrain_from_contours():
    f, level = open_model()
    r = call(T.create_terrain_from_contours, level, json.dumps(CONTOURS),
             json.dumps({"name": "Hills", "spacing": 1.5}))
    assert r["ok"], r
    assert r["triangles"] > 0
    assert r["bounds"] == {"min": [0.0, 0.0, 0.0], "max": [10.0, 8.0, 5.0]}
    element = f.by_guid(r["guid"])
    data = ifcopenshell.util.element.get_pset(element, T.PSET)
    assert data["Source"] == "contours"
    assert data["PointCount"] > len(CONTOURS[0]) + len(CONTOURS[1])  # sampled, not just the vertices
    assert data["Spacing"] == pytest.approx(1.5)
    listed = call(T.list_terrains)
    assert listed["ok"] and len(listed["terrains"]) == 1
    assert listed["terrains"][0]["guid"] == r["guid"]
    assert listed["terrains"][0]["name"] == "Hills"
    assert listed["terrains"][0]["triangles"] == r["triangles"]
    assert listed["terrains"][0]["bounds"] == r["bounds"]
    assert issues() == []


def test_ifc2x3_uses_a_surface_model():
    try:
        f, level = open_model("IFC2X3")
        r = call(T.create_terrain, level, json.dumps([[0, 0, 0], [5, 0, 1], [5, 4, 2], [0, 4, 0]]))
        assert r["ok"], r
        element = f.by_guid(r["guid"])
        assert element.is_a("IfcBuildingElementProxy") and element.ObjectType == "Terrain"
        representation = ifcopenshell.util.representation.get_representation(
            element, "Model", "Body", "MODEL_VIEW")
        assert representation is not None
        assert representation.RepresentationType == "SurfaceModel"
        assert any(item.is_a("IfcShellBasedSurfaceModel") for item in representation.Items)
        assert issues() == []
    finally:
        _reset_owner()  # the IFC2X3 owner callbacks are global


@pytest.mark.parametrize("points_json", [
    json.dumps([[0, 0, 0], [1, 0, 0]]),  # fewer than three
    json.dumps([[0, 0, 0], [1, 0, 0], [2, 0, 0]]),  # collinear
    json.dumps([[0, 0, 0], [1, 0, 0], [1, 1]]),  # not [x, y, z]
    "not json",
    json.dumps({"x": 0}),
])
def test_bad_points_are_reported_not_raised(points_json):
    f, level = open_model()
    r = call(T.create_terrain, level, points_json)
    assert r["ok"] is False and r["error"]
    assert not f.by_type("IfcGeographicElement")


def test_bad_level_and_contours_are_reported_not_raised():
    f, level = open_model()
    assert call(T.create_terrain, "no-such-level", json.dumps(RECT))["ok"] is False
    assert call(T.create_terrain_from_contours, level, json.dumps([[[0, 0, 0], [1, 0, 0]]]))["ok"] is False
    assert call(T.create_terrain_from_contours, level, json.dumps([]))["ok"] is False
    assert call(T.create_terrain_from_contours, level, "{}")["ok"] is False
    assert call(T.create_terrain_from_contours, level, json.dumps(CONTOURS),
                json.dumps({"spacing": 0}))["ok"] is False
    assert not f.by_type("IfcGeographicElement")


def test_delete_terrain():
    f, level = open_model()
    r = call(T.create_terrain, level, json.dumps(RECT))
    assert call(T.list_terrains)["terrains"][0]["guid"] == r["guid"]
    deleted = call(T.delete_terrain, r["guid"])
    assert deleted["ok"], deleted
    assert not f.by_type("IfcGeographicElement")
    assert call(T.list_terrains)["terrains"] == []
    assert call(T.delete_terrain, r["guid"])["ok"] is False


def test_building_pad_flattens_inside_and_keeps_outside():
    f, level = open_model()
    r = call(T.create_terrain, level, json.dumps(GRID))
    assert r["ok"], r
    element = f.by_guid(r["guid"])
    before, _ = T._mesh_data(element)
    z_before = {(round(x, 6), round(y, 6)): z for x, y, z in before}
    pad = call(T.set_building_pad, r["guid"], json.dumps(PAD), 10.0)
    assert pad["ok"], pad
    assert pad["pads"] == 1 and pad["triangles"] > 0
    after, _ = T._mesh_data(element)
    inside = {(1.0, 1.0), (2.0, 1.0), (1.0, 2.0), (2.0, 2.0)}
    for x, y, z in after:
        if (round(x, 6), round(y, 6)) in inside:
            assert z == pytest.approx(10.0)
        else:
            assert z == pytest.approx(z_before[(round(x, 6), round(y, 6))])
    data = ifcopenshell.util.element.get_pset(element, T.PSET)
    stored = json.loads(data["Pads"])
    assert len(stored) == 1 and stored[0]["elevation"] == pytest.approx(10.0)
    assert stored[0]["points"] == PAD
    listed = call(T.list_building_pads, r["guid"])
    assert listed["ok"] and listed["pads"] == stored
    assert data["MinElevation"] == pytest.approx(min(z for _x, _y, z in after))
    assert issues() == []


def test_building_pads_accumulate():
    f, level = open_model()
    r = call(T.create_terrain, level, json.dumps(GRID))
    assert call(T.set_building_pad, r["guid"], json.dumps(PAD), 5.0)["pads"] == 1
    second = [[2.5, 2.5], [3.5, 2.5], [3.5, 3.5], [2.5, 3.5]]
    assert call(T.set_building_pad, r["guid"], json.dumps(second), 7.0)["pads"] == 2
    assert len(call(T.list_building_pads, r["guid"])["pads"]) == 2
    points, _ = T._mesh_data(f.by_guid(r["guid"]))
    z = {(round(x, 6), round(y, 6)): v for x, y, v in points}
    assert z[(3.0, 3.0)] == pytest.approx(7.0)  # the second pad
    assert z[(1.0, 1.0)] == pytest.approx(5.0)  # the first pad still holds
    assert issues() == []


def test_clear_building_pads_restores_the_base_mesh():
    f, level = open_model()
    r = call(T.create_terrain, level, json.dumps(GRID))
    element = f.by_guid(r["guid"])
    before, before_faces = T._mesh_data(element)
    assert call(T.set_building_pad, r["guid"], json.dumps(PAD), 10.0)["ok"]
    assert call(T.list_building_pads, r["guid"])["pads"]
    cleared = call(T.clear_building_pads, r["guid"])
    assert cleared["ok"], cleared
    after, after_faces = T._mesh_data(element)
    key = lambda p: (round(p[0], 6), round(p[1], 6), round(p[2], 6))
    assert sorted(map(key, after)) == sorted(map(key, before))
    assert len(after_faces) == len(before_faces)
    assert call(T.list_building_pads, r["guid"])["pads"] == []
    data = ifcopenshell.util.element.get_pset(element, T.PSET)
    assert "Pads" not in data and "BasePoints" not in data and "BaseFaces" not in data
    assert issues() == []


@pytest.mark.parametrize("points_json", [
    json.dumps([[0, 0], [1, 0]]),  # fewer than three
    json.dumps([[0, 0], [1, 1], [1, 0], [0, 1]]),  # crosses itself
    json.dumps([[0, 0], [1, 0], ["x", 1]]),  # not a number
    "not json",
    json.dumps({"x": 0}),
])
def test_bad_building_pads_are_reported_not_raised(points_json):
    f, level = open_model()
    r = call(T.create_terrain, level, json.dumps(GRID))
    before = T._mesh_data(f.by_guid(r["guid"]))
    bad = call(T.set_building_pad, r["guid"], points_json, 1.0)
    assert bad["ok"] is False and bad["error"]
    assert call(T.list_building_pads, r["guid"])["pads"] == []
    assert T._mesh_data(f.by_guid(r["guid"])) == before


def test_building_pad_errors_are_reported():
    f, level = open_model()
    r = call(T.create_terrain, level, json.dumps(GRID))
    assert call(T.set_building_pad, "no-such-terrain", json.dumps(PAD), 1.0)["ok"] is False
    assert call(T.set_building_pad, r["guid"], json.dumps(PAD), "high")["ok"] is False
    assert call(T.set_building_pad, r["guid"], json.dumps(PAD), 1.0, "not json")["ok"] is False
    assert call(T.list_building_pads, "no-such-terrain")["ok"] is False
    assert call(T.clear_building_pads, "no-such-terrain")["ok"] is False


def test_saved_model_validates(tmp_path):
    f, level = open_model()
    assert call(T.create_terrain_from_contours, level, json.dumps(CONTOURS), json.dumps({"spacing": 2}))["ok"]
    path = tmp_path / "terrain.ifc"
    f.write(str(path))
    written = ifcopenshell.open(str(path))
    assert written.schema_identifier == "IFC4"
    assert len(written.by_type("IfcGeographicElement")) == 1
    assert issues(written) == []
