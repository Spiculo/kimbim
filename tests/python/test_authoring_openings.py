# SPDX-License-Identifier: GPL-3.0-or-later
"""Modeling, Slice 5: slabs, doors, windows, openings and cascading deletes."""
import json

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import numpy as np
import pytest

from kimcad import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def volume(guid):
    s = ifcopenshell.geom.settings()
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(s, b._model.by_guid(guid)).geometry)


def bbox(guid):
    _, verts, _ = b.mesh_elements(json.dumps([guid]))
    v = np.frombuffer(verts, dtype="<f4").reshape(-1, 3)
    return v.min(axis=0), v.max(axis=0)


@pytest.fixture
def house():
    """New project, 8 x 6 m loop of 300 mm walls (3 m high) on Level 1, plus Level 2 at 3 m."""
    assert call("new_project", "Casa")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    ext = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")["guid"]
    pts = [(0, 0), (8, 0), (8, 6), (0, 6)]
    walls, last = [], ""
    for i in range(4):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % 4]
        end = walls[0] if i == 3 else ""
        r = call("create_wall", level, ext, x1, y1, x2, y2, 3.0, last, end)
        assert r["ok"], r
        walls.append(r["guid"])
        last = r["guid"]
    level2 = call("add_storey", "Level 2", 3.0)["guid"]
    return {"level": level, "level2": level2, "walls": walls}


def types(kind):
    return {t["name"]: t for t in call("opening_types", kind)["types"]}


# ---------------------------------------------------------------- slabs

def test_default_slab_types(house):
    ts = {t["name"]: round(t["thickness"], 4) for t in call("slab_types")["types"]}
    assert ts == {"Floor 200": 0.2, "Floor 300": 0.3}


def test_slab_top_is_at_the_level(house):
    t = next(t for t in call("slab_types")["types"] if t["name"] == "Floor 200")["guid"]
    r = call("create_slab", house["level2"], t, json.dumps([[0, 0], [4, 0], [4, 3], [0, 3]]), 0.0)
    assert r["ok"], r
    lo, hi = bbox(r["guid"])
    assert lo == pytest.approx([0, 0, 2.8], abs=1e-3) and hi == pytest.approx([4, 3, 3.0], abs=1e-3)
    assert r["geometry"] == {"changed": [r["guid"]], "removed": []}
    s = b._model.by_guid(r["guid"])
    assert s.is_a("IfcSlab") and ifcopenshell.util.element.get_type(s).Name == "Floor 200"
    assert ifcopenshell.util.element.get_container(s).GlobalId == house["level2"]


def test_l_shaped_slab_volume(house):
    t = call("slab_types")["types"][0]["guid"]
    pts = [[0, 0], [4, 0], [4, 2], [2, 2], [2, 4], [0, 4]]  # 12 m2
    r = call("create_slab", house["level"], t, json.dumps(pts), 0.0)
    assert volume(r["guid"]) == pytest.approx(12 * 0.2, abs=1e-3)


def test_bad_outlines_change_nothing(house):
    t = call("slab_types")["types"][0]["guid"]
    for pts in ([[0, 0], [1, 0]], [[0, 0], [2, 2], [2, 0], [0, 2]]):  # too few; self-intersecting (bow tie)
        assert not call("create_slab", house["level"], t, json.dumps(pts), 0.0)["ok"]
    assert len(b._model.by_type("IfcSlab")) == 0


def test_outline_from_a_wall_loop_is_at_the_outer_faces(house):
    r = call("slab_outline_from_walls", json.dumps(house["walls"]))
    assert r["ok"], r
    xs = sorted({round(p[0], 4) for p in r["points"]})
    ys = sorted({round(p[1], 4) for p in r["points"]})
    assert len(r["points"]) == 4 and xs == [-0.15, 8.15] and ys == [-0.15, 6.15]
    assert not call("slab_outline_from_walls", json.dumps(house["walls"][:3]))["ok"]  # open chain


# ---------------------------------------------------------------- doors and windows

def test_default_opening_types():
    assert call("new_project", "x")["ok"]
    d = types("door")["Door 900x2100"]
    assert (d["width"], d["height"], d["sill"]) == pytest.approx((0.9, 2.1, 0.0))
    w = types("window")["Window 1200x1200"]
    assert (w["width"], w["height"], w["sill"]) == pytest.approx((1.2, 1.2, 0.9))


def test_door_cuts_the_wall_and_undo_restores_it(house):
    wall = house["walls"][0]
    before = volume(wall)
    d = types("door")["Door 900x2100"]
    r = call("insert_opening", "door", wall, d["guid"], 3.0, 0.9, 2.1, 0.0)
    assert r["ok"], r
    assert sorted(r["geometry"]["changed"]) == sorted([wall, r["guid"]])
    assert volume(wall) == pytest.approx(before - 0.3 * 0.9 * 2.1, abs=2e-3)
    door = b._model.by_guid(r["guid"])
    assert door.is_a("IfcDoor") and door.OverallWidth == pytest.approx(900.0)
    assert ifcopenshell.util.element.get_container(door).GlobalId == house["level"]
    assert door.FillsVoids[0].RelatingOpeningElement.VoidsElements[0].RelatingBuildingElement.GlobalId == wall
    lo, hi = bbox(r["guid"])
    # The parametric frame's casing overlaps the wall face by 25 mm around the 0.9 x 2.1 m hole.
    assert lo[0] == pytest.approx(3.0 - 0.45 - 0.025, abs=2e-3) and hi[0] == pytest.approx(3.0 + 0.45 + 0.025, abs=2e-3)
    assert hi[2] <= 2.1 + 0.03 and lo[2] == pytest.approx(0.0, abs=1e-3)
    u = call("undo")
    assert u["geometry"] == {"changed": [wall], "removed": [r["guid"]]}
    assert volume(wall) == pytest.approx(before, abs=1e-3)


def test_window_sits_on_its_sill(house):
    w = types("window")["Window 1200x1200"]
    r = call("insert_opening", "window", house["walls"][2], w["guid"], 4.0, 1.2, 1.2, 0.9)
    assert r["ok"], r
    lo, hi = bbox(r["guid"])
    assert lo[2] == pytest.approx(0.9, abs=1e-2) and hi[2] == pytest.approx(2.1, abs=1e-2)
    assert b._model.by_guid(r["guid"]).is_a("IfcWindow")


def test_openings_must_fit_in_the_wall(house):
    d = types("door")["Door 900x2100"]
    for along in (0.2, 7.9):  # would stick out past the wall's ends
        assert not call("insert_opening", "door", house["walls"][0], d["guid"], along, 0.9, 2.1, 0.0)["ok"]
    assert not call("insert_opening", "door", house["walls"][0], d["guid"], 4.0, 0.9, 3.5, 0.0)["ok"]  # taller
    assert not b._model.by_type("IfcOpeningElement")


def test_deleting_a_door_closes_the_hole(house):
    wall = house["walls"][0]
    before = volume(wall)
    d = types("door")["Door 900x2100"]
    door = call("insert_opening", "door", wall, d["guid"], 3.0, 0.9, 2.1, 0.0)["guid"]
    r = call("delete_elements", json.dumps([door]))
    assert r["ok"] and r["geometry"] == {"changed": [wall], "removed": [door]}
    assert volume(wall) == pytest.approx(before, abs=1e-3)
    assert not b._model.by_type("IfcOpeningElement")


def test_deleting_a_wall_takes_its_doors_and_windows(house):
    wall = house["walls"][0]
    d = types("door")["Door 900x2100"]
    w = types("window")["Window 1200x1200"]
    door = call("insert_opening", "door", wall, d["guid"], 2.0, 0.9, 2.1, 0.0)["guid"]
    win = call("insert_opening", "window", wall, w["guid"], 6.0, 1.2, 1.2, 0.9)["guid"]
    r = call("delete_elements", json.dumps([wall]))
    assert r["ok"]
    assert set(r["geometry"]["removed"]) == {wall, door, win}
    assert not b._model.by_type("IfcOpeningElement") and not b._model.by_type("IfcDoor") and not b._model.by_type("IfcWindow")
    call("undo")
    assert len(b._model.by_type("IfcDoor")) == 1 and len(b._model.by_type("IfcOpeningElement")) == 2


def test_snap_data_lists_openings(house):
    d = types("door")["Door 900x2100"]
    door = call("insert_opening", "door", house["walls"][0], d["guid"], 3.0, 0.9, 2.1, 0.0)["guid"]
    ops = call("snap_data", house["level"])["openings"]
    assert ops == [{"guid": door, "wall": house["walls"][0], "along": pytest.approx(3.0, abs=1e-6), "width": pytest.approx(0.9)}]
