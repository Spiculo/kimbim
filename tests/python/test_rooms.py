# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice 18: rooms (Archicad zones) — IfcSpace from the walls around a clicked point, stamps, schedule."""
import csv
import json

import ifcopenshell.util.element
import ifcopenshell.validate
import pytest

from kimcad import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def flat():
    """A 10 x 6 m box of 300 mm walls (axes) split by a 200 mm wall at x = 4: two rooms."""
    assert call("new_project", "Flat")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    types = {t["name"]: t["guid"] for t in call("wall_types")["types"]}
    ext = types["Exterior 300"]
    inner = next(g for n, g in types.items() if n != "Exterior 300")
    walls, last = [], ""
    corners = [(0, 0), (10, 0), (10, 6), (0, 6)]
    for i in range(4):
        (x1, y1), (x2, y2) = corners[i], corners[(i + 1) % 4]
        walls.append(call("create_wall", l1, ext, x1, y1, x2, y2, 3.0, last, walls[0] if i == 3 else "")["guid"])
        last = walls[-1]
    partition = call("create_wall", l1, inner, 4, 0, 4, 6, 3.0, "", "")["guid"]
    return {"l1": l1, "walls": walls, "partition": partition,
            "inner_t": next(t["thickness"] for t in call("wall_types")["types"] if t["guid"] == inner)}


def area(points):
    n = len(points)
    return abs(sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1] for i in range(n))) / 2


def test_room_from_a_click_inside_walls(flat):
    r = call("create_room", flat["l1"], 2.0, 3.0, "Living room")
    assert r["ok"], r
    room = next(x for x in call("rooms", flat["l1"])["rooms"] if x["guid"] == r["guid"])
    # Inside faces: x from 0.15 to 4 - t/2, y from 0.15 to 5.85.
    expected = (4 - flat["inner_t"] / 2 - 0.15) * 5.7
    assert abs(room["area"] - expected) < 1e-3 and abs(area(room["points"]) - expected) < 1e-3
    assert room["name"] == "Living room" and room["number"] == "101"  # Level 1, first room
    space = b._model.by_guid(r["guid"])
    assert space.is_a("IfcSpace") and space.LongName == "Living room" and space.Name == "101"
    qto = ifcopenshell.util.element.get_psets(space)["Qto_SpaceBaseQuantities"]
    assert abs(qto["NetFloorArea"] - expected) < 1e-3
    assert ifcopenshell.util.element.get_aggregate(space).GlobalId == flat["l1"]  # part of the level
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    assert logger.statements == []
    second = call("create_room", flat["l1"], 7.0, 3.0, "Kitchen")
    assert second["ok"] and next(x for x in call("rooms", flat["l1"])["rooms"] if x["guid"] == second["guid"])["number"] == "102"


def test_clicking_outside_or_twice_is_refused(flat):
    assert not call("create_room", flat["l1"], 20.0, 3.0, "Garden")["ok"]  # not enclosed
    assert call("create_room", flat["l1"], 2.0, 3.0, "A")["ok"]
    assert not call("create_room", flat["l1"], 2.5, 2.0, "B")["ok"]  # already a room there


def test_room_follows_its_walls(flat):
    r = call("create_room", flat["l1"], 2.0, 3.0, "Living room")["guid"]
    before = next(x for x in call("rooms", flat["l1"])["rooms"] if x["guid"] == r)["area"]
    assert call("move_elements", json.dumps([flat["partition"]]), 1.0, 0.0, 0.0)["ok"]
    after = next(x for x in call("rooms", flat["l1"])["rooms"] if x["guid"] == r)["area"]
    assert abs(after - before - 5.7) < 1e-3  # 1 m wider over the 5.7 m depth
    assert call("undo")["ok"]
    assert abs(next(x for x in call("rooms", flat["l1"])["rooms"] if x["guid"] == r)["area"] - before) < 1e-6


def test_room_schedule_and_csv(flat, tmp_path):
    call("create_room", flat["l1"], 2.0, 3.0, "Living room")
    call("create_room", flat["l1"], 7.0, 3.0, "Kitchen")
    assert call("edit_room", call("rooms", flat["l1"])["rooms"][0]["guid"], json.dumps({"name": "Lounge", "number": "1.01"}))["ok"]
    rows = call("room_schedule")["rows"]
    assert [r["number"] for r in rows] == ["1.01", "102"]
    assert rows[0]["name"] == "Lounge" and rows[0]["level"] == "Level 1" and rows[0]["area"] > 20
    out = tmp_path / "rooms.csv"
    assert call("export_room_schedule", str(out))["ok"]
    with open(out, newline="", encoding="utf-8") as fh:
        table = list(csv.reader(fh))
    assert table[0] == ["Number", "Name", "Level", "Area (m²)", "Perimeter (m)", "Height (m)"]
    assert table[1][:3] == ["1.01", "Lounge", "Level 1"] and len(table) == 4  # header, 2 rooms, total
    assert table[-1][0] == "Total"


def test_room_stamps_on_the_floor_plan(flat):
    call("create_room", flat["l1"], 2.0, 3.0, "Living room")
    plan = next(d for d in call("drawings")["drawings"] if d["name"] == "Level 1 Floor Plan")
    svg = call("generate_drawing", plan["guid"], "")["svg"]
    overlay = svg.split('class="kimcad-overlay"', 1)[1]
    assert ">Living room</text>" in overlay and ">101</text>" in overlay and " m²</text>" in overlay
