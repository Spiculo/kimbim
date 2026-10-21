# SPDX-License-Identifier: GPL-3.0-or-later
"""The levels table (D79, Archicad's Story Settings): rename, change elevations (elements follow),
insert, delete, show in the level list; one undo step per table edit."""
import json
import pathlib
import shutil
import time

import ifcopenshell.api.geometry
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np
import pytest

from kimbim import app_bridge as b
from kimbim import authoring, levels

CLINIC = (pathlib.Path(__file__).resolve().parents[1] / "corpus" / "files" / "community" / "IFC 2.3.0.1 (IFC 2x3)"
          / "Medical-Dental Clinic" / "Clinic_Architectural.ifc")


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def world_z(guid):
    e = b._model.by_guid(guid)
    return float(ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)[2][3]) * authoring._scale()


def bbox(guid):
    _, verts, _, _ = b.mesh_elements(json.dumps([guid]))
    v = np.frombuffer(verts, dtype="<f4").reshape(-1, 3)
    return v.min(axis=0), v.max(axis=0)


def table():
    return call("levels_table")["levels"]


@pytest.fixture
def house():
    """Level 1 at 0 with a wall (and a door in it) and a slab; Level 2 at 3 m with a wall; Level 3 at 6 m, empty."""
    assert call("new_project", "Niveles")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    l3 = call("add_storey", "Level 3", 6.0)["guid"]
    wt = call("wall_types")["types"][0]["guid"]
    w1 = call("create_wall", l1, wt, 0, 0, 5, 0, 3.0)["guid"]
    door = call("insert_opening", "door", w1, call("opening_types", "door")["types"][0]["guid"], 2.0, 0.9, 2.1, 0.0)["guid"]
    slab = call("create_slab", l1, call("slab_types")["types"][0]["guid"], json.dumps([[0, 0], [5, 0], [5, 4], [0, 4]]), 0.0)["guid"]
    w2 = call("create_wall", l2, wt, 0, 0, 0, 4, 3.0)["guid"]
    return {"l1": l1, "l2": l2, "l3": l3, "w1": w1, "door": door, "slab": slab, "w2": w2}


def test_the_table_lists_levels_with_heights_to_the_next(house):
    rows = table()
    assert [r["name"] for r in rows] == ["Level 1", "Level 2", "Level 3"]
    assert [r["elevation"] for r in rows] == [0.0, 3.0, 6.0]
    assert [r["height"] for r in rows] == [3.0, 3.0, None]
    assert [r["elements"] for r in rows] == [3, 1, 0]  # wall, door, slab (the opening comes with the wall)
    assert all(r["show"] for r in rows)


def test_show_on_levels(house):
    from kimbim import drawgen

    s1, s2, s3 = (b._model.by_guid(house[k]) for k in ("l1", "l2", "l3"))
    order = sorted(b._model.by_type("IfcBuildingStorey"), key=drawgen.storey_elevation)
    wall = b._model.by_guid(house["w1"])
    assert drawgen.shows_on(wall, s1, order) and not drawgen.shows_on(wall, s2, order)  # home only (D91)
    # One up: the Level 1 wall also shows on the Level 2 plan.
    assert call("set_show_on", json.dumps([house["w1"]]), "up")["ok"]
    assert drawgen.shows_on(wall, s2, order)
    plan2 = next(d for d in call("drawings")["drawings"] if d["name"].startswith("Level 2"))
    assert f'ifc:guid="{house["w1"]}"' in call("generate_drawing", plan2["guid"], "")["svg"]
    # Back home: the wall leaves the Level 2 plan.
    assert call("set_show_on", json.dumps([house["w1"]]), "home")["ok"]
    assert f'ifc:guid="{house["w1"]}"' not in call("generate_drawing", plan2["guid"], "")["svg"]
    # A range and an expression both resolve; the expression keeps it off Level 3.
    assert call("set_show_on", json.dumps([house["w1"]]), "range:0..2")["ok"]
    assert drawgen.shows_on(wall, s2, order)
    assert call("set_show_on", json.dumps([house["w1"]]), "d >= -1 and d <= 1")["ok"]
    assert drawgen.shows_on(wall, s2, order) and not drawgen.shows_on(wall, s3, order)


def test_rename_keeps_the_floor_plan_named_after_the_level(house):
    r = call("rename_storey", house["l2"], "First floor")
    assert r["ok"] and r["changed"] == 1
    assert b._model.by_guid(house["l2"]).Name == "First floor"
    assert "First floor Floor Plan" in [d["name"] for d in call("drawings")["drawings"]]
    assert call("undo")["ok"]
    assert b._model.by_guid(house["l2"]).Name == "Level 2"


def test_changing_an_elevation_moves_the_level_and_its_elements(house):
    before = {k: world_z(house[k]) for k in ("w1", "door", "slab", "w2")}
    lo, hi = bbox(house["w1"])
    r = call("set_storey_elevation", house["l1"], -0.5)
    assert r["ok"], r
    assert set(r["geometry"]["changed"]) >= {house["w1"], house["door"], house["slab"]}
    assert house["w2"] not in r["geometry"]["changed"]
    assert world_z(house["w1"]) == pytest.approx(before["w1"] - 0.5)
    assert world_z(house["door"]) == pytest.approx(before["door"] - 0.5)
    assert world_z(house["slab"]) == pytest.approx(before["slab"] - 0.5)
    assert world_z(house["w2"]) == pytest.approx(before["w2"])  # other levels stay
    lo2, hi2 = bbox(house["w1"])
    assert lo2 == pytest.approx(lo - [0, 0, 0.5], abs=1e-3) and hi2 == pytest.approx(hi - [0, 0, 0.5], abs=1e-3)
    storey = b._model.by_guid(house["l1"])
    assert storey.Elevation * authoring._scale() == pytest.approx(-0.5)
    assert [row["elevation"] for row in table()] == [-0.5, 3.0, 6.0]
    # One undo step puts everything back.
    assert call("undo")["ok"]
    assert world_z(house["w1"]) == pytest.approx(before["w1"]) and table()[0]["elevation"] == 0.0


def test_an_elevation_change_can_move_the_levels_above(house):
    # D92: off by default; with the option the levels above follow the edited one.
    r = call("set_storey_elevation", house["l1"], 1.0, "true")
    assert r["ok"], r
    assert [row["elevation"] for row in table()] == pytest.approx([1.0, 4.0, 7.0])
    assert world_z(house["w2"]) == pytest.approx(4.0)
    assert call("undo")["ok"]
    assert [row["elevation"] for row in table()] == pytest.approx([0.0, 3.0, 6.0])


def test_elements_placed_absolutely_move_too_and_strangers_stay(house):
    """Imported files may place elements absolutely, or chain other things to a storey's placement."""
    wall, other = b._model.by_guid(house["w1"]), b._model.by_guid(house["w2"])
    z_wall, z_other = world_z(house["w1"]), world_z(house["w2"])
    world = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
    wall.ObjectPlacement.PlacementRelTo = None  # absolute now, same place
    ifcopenshell.api.geometry.edit_object_placement(b._model, product=wall, matrix=world, is_si=False)
    other_world = ifcopenshell.util.placement.get_local_placement(other.ObjectPlacement)
    other.ObjectPlacement.PlacementRelTo = b._model.by_guid(house["l1"]).ObjectPlacement  # Level 2's wall hangs off Level 1
    ifcopenshell.api.geometry.edit_object_placement(b._model, product=other, matrix=other_world, is_si=False)
    assert world_z(house["w1"]) == pytest.approx(z_wall) and world_z(house["w2"]) == pytest.approx(z_other)
    assert call("set_storey_elevation", house["l1"], 1.0)["ok"]
    assert world_z(house["w1"]) == pytest.approx(z_wall + 1.0)
    assert world_z(house["door"]) == pytest.approx(1.0, abs=1e-6)  # follows its wall
    assert world_z(house["w2"]) == pytest.approx(z_other)


def test_insert_adds_a_level_with_its_floor_plan(house):
    r = call("insert_storey", "Mezzanine", 1.5)
    assert r["ok"], r
    guid = r["created"][0]
    assert [row["name"] for row in table()] == ["Level 1", "Mezzanine", "Level 2", "Level 3"]
    assert "Mezzanine Floor Plan" in [d["name"] for d in call("drawings")["drawings"]]
    assert world_z(guid) == pytest.approx(1.5)
    assert call("undo")["ok"] and len(table()) == 3


def test_insert_can_fit_between_two_levels(house):
    # D92: fit between (Revit): the new level goes in the middle of the gap; the levels stay.
    r = call("insert_storey", "Mezzanine", 2.0, "true")
    assert r["ok"], r
    guid = r["created"][0]
    assert world_z(guid) == pytest.approx(1.5)
    assert [row["elevation"] for row in table()] == pytest.approx([0.0, 1.5, 3.0, 6.0])


def test_deleting_an_empty_level(house):
    r = call("delete_storey", house["l3"])
    assert r["ok"], r
    assert [row["name"] for row in table()] == ["Level 1", "Level 2"]
    assert "Level 3 Floor Plan" not in [d["name"] for d in call("drawings")["drawings"]]
    assert call("undo")["ok"] and len(table()) == 3


def test_deleting_a_level_with_elements_is_refused_by_default(house):
    r = call("delete_storey", house["l2"])
    assert not r["ok"] and "1 elements" in r["error"]
    assert len(table()) == 3 and b._model.by_guid(house["w2"])
    assert not call("state")["can_undo"] or call("state")  # nothing was recorded for the refusal


def test_deleting_a_level_with_its_elements_or_moving_them(house):
    z = world_z(house["w2"])
    r = call("delete_storey", house["l2"], "move", house["l3"])
    assert r["ok"], r
    w2 = b._model.by_guid(house["w2"])
    assert ifcopenshell.util.element.get_container(w2).GlobalId == house["l3"]
    assert world_z(house["w2"]) == pytest.approx(z)  # moved to the level, not in space
    assert call("undo")["ok"]
    r = call("delete_storey", house["l1"], "delete")
    assert r["ok"], r
    assert set(r["geometry"]["removed"]) >= {house["w1"], house["door"], house["slab"]}
    assert not b._model.by_type("IfcDoor") and len(b._model.by_type("IfcWall")) == 1


def test_the_last_level_cannot_go(house):
    r = call("edit_storeys", json.dumps({"deleted": [house["l1"], house["l2"], house["l3"]]}))
    assert not r["ok"]


def test_a_table_edit_is_one_undo_step(house):
    """The dialog sends the whole table: rename, raise Level 3 (Archicad: height to next), hide
    Level 2, insert a roof level and delete nothing; one undo puts it all back."""
    rows = table()
    changes = {"levels": [
        {**rows[0], "name": "Ground"},
        {**rows[1], "show": False},
        {**rows[2], "elevation": 7.0},
        {"guid": "", "name": "Roof", "elevation": 10.0, "show": True},
    ]}
    r = call("edit_storeys", json.dumps(changes))
    assert r["ok"], r
    after = table()
    assert [(x["name"], x["elevation"], x["show"]) for x in after] == [
        ("Ground", 0.0, True), ("Level 2", 3.0, False), ("Level 3", 7.0, True), ("Roof", 10.0, True)]
    assert [s["show"] for s in call("storeys")["storeys"]] == [True, False, True, True]
    assert call("undo")["ok"]
    assert [(x["name"], x["elevation"], x["show"]) for x in table()] == [
        ("Level 1", 0.0, True), ("Level 2", 3.0, True), ("Level 3", 6.0, True)]


def test_bad_input_changes_nothing(house):
    for changes in ({"levels": [{"guid": house["l1"], "name": "", "elevation": 0}]},
                    {"levels": [{"guid": house["l1"], "name": "A", "elevation": "x"}]},
                    {"levels": [{"guid": "nope", "name": "A", "elevation": 0}]},
                    {"deleted": [{"guid": house["l2"], "elements": "move"}], "move_to": house["l2"]}):
        r = call("edit_storeys", json.dumps(changes))
        assert not r["ok"], changes
    assert [x["name"] for x in table()] == ["Level 1", "Level 2", "Level 3"]


@pytest.mark.slow
def test_clinic_level_edits_timing(tmp_path):
    """The large corpus model (IFC2X3, Revit export): raise a level with its elements, rename, insert
    and delete, timed. Needs `pixi run fetch-corpus`."""
    if not CLINIC.exists():
        pytest.skip("corpus not downloaded (pixi run fetch-corpus)")
    copy = tmp_path / "clinic.ifc"
    shutil.copy(CLINIC, copy)
    assert call("open_model", str(copy))["ok"]
    t = time.perf_counter()
    rows = table()
    timings = {"table": time.perf_counter() - t}
    busiest = max(rows, key=lambda r: r["elements"])
    members = [e for e in levels._members(b._model.by_guid(busiest["guid"]))
               if getattr(e, "ObjectPlacement", None) is not None]
    sample = members[: 200]
    before = {e.GlobalId: world_z(e.GlobalId) for e in sample}
    t = time.perf_counter()
    r = call("set_storey_elevation", busiest["guid"], busiest["elevation"] + 0.25)
    timings["elevation"] = time.perf_counter() - t
    assert r["ok"], r
    for g, z in before.items():
        assert world_z(g) == pytest.approx(z + 0.25, abs=1e-6), g
    t = time.perf_counter()
    assert call("rename_storey", busiest["guid"], "Renamed")["ok"]
    timings["rename"] = time.perf_counter() - t
    t = time.perf_counter()
    made = call("insert_storey", "Extra", 100.0)
    timings["insert"] = time.perf_counter() - t
    t = time.perf_counter()
    assert call("delete_storey", made["created"][0])["ok"]
    timings["delete"] = time.perf_counter() - t
    t = time.perf_counter()
    assert call("undo")["ok"]
    timings["undo"] = time.perf_counter() - t
    print("clinic levels:", busiest["elements"], "elements on", busiest["name"],
          {k: round(v, 3) for k, v in timings.items()})
    assert timings["elevation"] < 30


def test_an_element_depth_override_shows_it_below(house):
    from kimbim import drawgen

    s1, s2 = (b._model.by_guid(house[k]) for k in ("l1", "l2"))
    order = sorted(b._model.by_type("IfcBuildingStorey"), key=drawgen.storey_elevation)
    wall = b._model.by_guid(house["w1"])
    assert not drawgen.shows_on(wall, s2, order)  # home only
    assert call("set_element_view_depth", json.dumps([house["w1"]]), 4.0)["ok"]
    assert drawgen.shows_in_view(wall, s2, order)
    assert house["w1"] in call("visible_on", house["l2"])["guids"]
    assert call("visible_on", house["l2"])["max_depth"] == 4.0
    assert call("set_element_view_depth", json.dumps([house["w1"]]), 2.0)["ok"]  # 3 m below: out of reach
    assert not drawgen.shows_in_view(wall, s2, order)
    assert house["w1"] not in call("visible_on", house["l2"])["guids"]
