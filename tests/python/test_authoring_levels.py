# SPDX-License-Identifier: GPL-3.0-or-later
"""Modeling, Slice 7: copy to another level, stairs, slab openings (two-storey houses)."""
import json

import ifcopenshell.geom
import ifcopenshell.util.element
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
def house():
    """Level 1: 8 x 6 m joined walls, a door (south) and a window (north), a floor slab. Level 2 at 3 m."""
    assert call("new_project", "Dos plantas")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    ext = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")["guid"]
    pts = [(0, 0), (8, 0), (8, 6), (0, 6)]
    walls, last = [], ""
    for i in range(4):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % 4]
        r = call("create_wall", l1, ext, x1, y1, x2, y2, 3.0, last, walls[0] if i == 3 else "")
        walls.append(r["guid"])
        last = r["guid"]
    d = call("opening_types", "door")["types"][0]
    w = call("opening_types", "window")["types"][0]
    door = call("insert_opening", "door", walls[0], d["guid"], 4.0, 0.9, 2.1, 0.0)["guid"]
    win = call("insert_opening", "window", walls[2], w["guid"], 4.0, 1.2, 1.2, 0.9)["guid"]
    slab_type = call("slab_types")["types"][0]["guid"]
    outline = call("slab_outline_from_walls", g(*walls))["points"]
    slab = call("create_slab", l1, slab_type, json.dumps(outline), 0.0)["guid"]
    return {"l1": l1, "l2": l2, "walls": walls, "door": door, "window": win, "slab": slab, "slab_type": slab_type}


def joins():
    return [frozenset((r.RelatingElement.GlobalId, r.RelatedElement.GlobalId))
            for r in b._model.by_type("IfcRelConnectsPathElements")]


def test_copying_walls_with_openings_to_the_upper_level(house):
    r = call("copy_to_storey", g(*house["walls"]), house["l2"])
    assert r["ok"], r
    copies = r["guids"]
    assert len(copies) == 4 and not set(copies) & set(house["walls"])
    # Each copy is one level up and contained in Level 2.
    for original, copy in zip(house["walls"], copies):
        (lo, hi), (clo, chi) = bbox(original), bbox(copy)
        assert clo == pytest.approx(lo + [0, 0, 3.0], abs=2e-3) and chi == pytest.approx(hi + [0, 0, 3.0], abs=2e-3)
        assert ifcopenshell.util.element.get_container(b._model.by_guid(copy)).GlobalId == house["l2"]
    # Joined like the originals: 4 joins on each level.
    assert len(joins()) == 8
    # The door and window were copied into the copied walls' own openings.
    assert len(b._model.by_type("IfcDoor")) == 2 and len(b._model.by_type("IfcWindow")) == 2
    assert len(b._model.by_type("IfcOpeningElement")) == 4
    for door in b._model.by_type("IfcDoor"):
        host = door.FillsVoids[0].RelatingOpeningElement.VoidsElements[0].RelatingBuildingElement
        level = ifcopenshell.util.element.get_container(host).GlobalId
        assert ifcopenshell.util.element.get_container(door).GlobalId == level
    south_copy = copies[0]
    assert volume(south_copy) == pytest.approx(volume(house["walls"][0]), abs=1e-3)  # the hole is there too
    assert set(copies) <= set(r["geometry"]["changed"])
    call("undo")
    assert len(b._model.by_type("IfcWall")) == 4 and len(b._model.by_type("IfcDoor")) == 1


def test_copying_a_slab_and_a_column(house):
    col_type = call("column_types")["types"][0]["guid"]
    col = call("create_column", house["l1"], col_type, 4, 3, 3.0, 0.0)["guid"]
    r = call("copy_to_storey", g(house["slab"], col), house["l2"])
    assert r["ok"], r
    slab_copy, col_copy = r["guids"]
    assert bbox(slab_copy)[1][2] == pytest.approx(3.0, abs=2e-3)
    assert bbox(col_copy)[0][2] == pytest.approx(3.0, abs=2e-3)


def test_stair_reaches_the_upper_level(house):
    r = call("create_stair", house["l1"], 1.0, 1.0, 0.0, 1.0, 3.0)
    assert r["ok"], r
    stair = b._model.by_guid(r["guid"])
    assert stair.is_a("IfcStair") and stair.PredefinedType == "STRAIGHT_RUN_STAIR"
    pset = ifcopenshell.util.element.get_psets(stair)["Pset_StairCommon"]
    risers, riser = pset["NumberOfRiser"], pset["RiserHeight"]
    assert risers == 18 and riser * risers == pytest.approx(3000.0, abs=1e-6)  # mm in this project
    flight = stair.IsDecomposedBy[0].RelatedObjects[0]  # D88: the shape is the flight's
    assert flight.is_a("IfcStairFlight")
    lo, hi = bbox(flight.GlobalId)
    assert lo[2] == pytest.approx(0.0, abs=1e-3) and hi[2] == pytest.approx(3.0, abs=1e-3)
    assert lo[0] == pytest.approx(1.0, abs=1e-3) and hi[0] == pytest.approx(1.0 + 17 * 0.28, abs=1e-3)
    assert hi[1] - lo[1] == pytest.approx(1.0, abs=1e-3)
    assert not call("create_stair", house["l1"], 1, 1, 0, 0.0, 3.0)["ok"]
    assert not call("create_stair", house["l1"], 1, 1, 0, 1.0, 0.0)["ok"]


def test_slab_opening_cuts_its_outline(house):
    upper = call("create_slab", house["l2"], house["slab_type"], json.dumps([[0, 0], [8, 0], [8, 6], [0, 6]]), 0.0)["guid"]
    before = volume(upper)
    r = call("add_slab_opening", upper, json.dumps([[1, 1], [5, 1], [5, 2], [1, 2]]))
    assert r["ok"], r
    assert r["geometry"] == {"changed": [upper], "removed": []}
    assert volume(upper) == pytest.approx(before - 4 * 1 * 0.2, abs=1e-3)
    call("undo")
    assert volume(upper) == pytest.approx(before, abs=1e-3)
    assert not call("add_slab_opening", house["walls"][0], json.dumps([[1, 1], [2, 1], [2, 2]]))["ok"]  # not a slab
