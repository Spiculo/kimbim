# SPDX-License-Identifier: GPL-3.0-or-later
"""Modeling, Slice 6: move, rotate, stretch, wall height and door/window edits (identity is kept)."""
import json
import math

import ifcopenshell.geom
import ifcopenshell.util.shape
import numpy as np
import pytest

from kimcad import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def bbox(guid):
    _, verts, _ = b.mesh_elements(json.dumps([guid]))
    v = np.frombuffer(verts, dtype="<f4").reshape(-1, 3)
    return v.min(axis=0), v.max(axis=0)


def volume(guid):
    s = ifcopenshell.geom.settings()
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(s, b._model.by_guid(guid)).geometry)


def g(*guids):
    return json.dumps(list(guids))


@pytest.fixture
def room():
    """8 x 6 m room of joined 300 mm walls (3 m) with a door in the south wall at 4 m."""
    assert call("new_project", "Edit")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    ext = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")["guid"]
    pts = [(0, 0), (8, 0), (8, 6), (0, 6)]
    walls, last = [], ""
    for i in range(4):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % 4]
        r = call("create_wall", level, ext, x1, y1, x2, y2, 3.0, last, walls[0] if i == 3 else "")
        walls.append(r["guid"])
        last = r["guid"]
    d = call("opening_types", "door")["types"][0]
    door = call("insert_opening", "door", walls[0], d["guid"], 4.0, 0.9, 2.1, 0.0)["guid"]
    return {"level": level, "walls": walls, "door": door, "ext": ext}


def joins():
    return {frozenset((r.RelatingElement.GlobalId, r.RelatedElement.GlobalId))
            for r in b._model.by_type("IfcRelConnectsPathElements")}


def test_moving_a_wall_takes_its_door(room):
    south, door = room["walls"][0], room["door"]
    d_lo, _ = bbox(door)
    r = call("move_elements", g(south), 0, -1.0, 0)
    assert r["ok"], r
    assert {south, door} <= set(r["geometry"]["changed"])
    assert bbox(door)[0] == pytest.approx(d_lo + [0, -1.0, 0], abs=2e-3)
    assert b._model.by_guid(south) and b._model.by_guid(door)  # same GlobalIds


def test_moving_one_wall_drops_joins_to_walls_that_stay(room):
    south, east, north, west = room["walls"]
    r = call("move_elements", g(south), 0, -1.0, 0)
    assert frozenset((south, east)) not in joins() and frozenset((south, west)) not in joins()
    assert frozenset((east, north)) in joins()
    assert {east, west} <= set(r["geometry"]["changed"])  # the neighbours lost their mitre
    assert volume(east) == pytest.approx(0.3 * 3 * 6, abs=0.05)
    call("undo")
    assert frozenset((south, east)) in joins()


def test_moving_the_whole_room_keeps_its_joins(room):
    before = joins()
    vols = [volume(w) for w in room["walls"]]
    call("move_elements", g(*room["walls"]), 2.0, 3.0, 0)
    assert joins() == before
    assert [volume(w) for w in room["walls"]] == pytest.approx(vols, abs=1e-3)
    lo, _ = bbox(room["walls"][0])
    assert lo[0] == pytest.approx(2.0 - 0.15, abs=2e-3)


def test_rotating_a_column_90_degrees(room):
    t = call("column_types")["types"][0]["guid"]
    col = call("create_column", room["level"], t, 10, 0, 3.0, 0.0)["guid"]
    beam_t = call("beam_types")["types"][0]["guid"]
    beam = call("create_beam", room["level"], beam_t, 10, 0, 14, 0, 3.0)["guid"]
    r = call("rotate_elements", g(col, beam), 10, 0, math.pi / 2)
    assert r["ok"], r
    lo, hi = bbox(beam)
    assert lo[0] == pytest.approx(9.9, abs=2e-3) and hi[1] == pytest.approx(4.0, abs=2e-3)  # now along +Y
    assert b._model.by_guid(beam).GlobalId == beam


def test_stretching_a_wall_end_keeps_the_far_join(room):
    south, east, north, west = room["walls"]
    # Pull the north wall's west end out to x = -2 (it was joined to the west wall there).
    axis = next(w for w in call("snap_data", room["level"])["walls"] if w["guid"] == north)
    start_is_east = axis["x1"] > axis["x2"]
    x1, y1, x2, y2 = (8, 6, -2, 6) if start_is_east else (-2, 6, 8, 6)
    r = call("set_wall_axis", north, x1, y1, x2, y2)
    assert r["ok"], r
    lo, hi = bbox(north)
    assert lo[0] == pytest.approx(-2.0, abs=0.2) and hi[0] == pytest.approx(8.15, abs=2e-3)
    assert frozenset((east, north)) in joins()  # the end that didn't move stays joined
    assert b._model.by_guid(north).GlobalId == north


def test_wall_height(room):
    south = room["walls"][0]
    r = call("set_wall_height", g(south), 4.5)
    assert r["ok"], r
    assert bbox(south)[1][2] == pytest.approx(4.5, abs=2e-3)
    assert not call("set_wall_height", g(south), 0)["ok"]


def test_moving_and_resizing_a_door(room):
    south, door = room["walls"][0], room["door"]
    before = volume(south)
    r = call("edit_opening", door, 2.0, 1.2, 2.2, 0.0)
    assert r["ok"], r
    assert sorted(r["geometry"]["changed"]) == sorted([south, door])
    lo, hi = bbox(door)
    assert (lo[0] + hi[0]) / 2 == pytest.approx(2.0, abs=2e-3) and hi[0] - lo[0] == pytest.approx(1.25, abs=2e-3)
    assert volume(south) == pytest.approx(before + 0.3 * 0.9 * 2.1 - 0.3 * 1.2 * 2.2, abs=3e-3)
    assert b._model.by_guid(door).OverallWidth == pytest.approx(1200.0)
    call("undo")
    assert volume(south) == pytest.approx(before, abs=1e-3)


def test_door_edits_that_dont_fit_change_nothing(room):
    door = room["door"]
    for args in ((0.3, 0.9, 2.1, 0.0), (4.0, 0.9, 3.5, 0.0), (4.0, 9.0, 2.1, 0.0)):
        assert not call("edit_opening", door, *args)["ok"]
    assert b._model.by_guid(door).OverallWidth == pytest.approx(900.0)
