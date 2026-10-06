# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the M3 exit-test house through the app's modeling commands and save it as IFC.

Two storeys (Level 1 at 0, Level 2 at 3 m, Roof at 6 m): a 10 x 8 m loop of exterior walls per
floor, a front door and windows, floor slabs, a roof slab, a stair from Level 1 to Level 2 with its
hole in the Level 2 floor, columns and a beam. This is the same modeling path the GUI uses
(app_bridge), without the GUI, so CI can produce the file on any machine.

Usage: python tools/make_house.py OUT.ifc   (prints a JSON summary)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from kimcad import app_bridge as b  # noqa: E402


def call(fn, *args):
    result = json.loads(getattr(b, fn)(*args))
    if isinstance(result, dict) and result.get("ok") is False:
        raise SystemExit(f"{fn} failed: {result.get('error')}")
    return result


def named(listing, name):
    return next(t for t in listing["types"] if t["name"] == name)


def build(out: str) -> dict:
    call("new_project", "KIMCAD two-storey house")
    l1 = call("storeys")["storeys"][0]["guid"]
    ext = named(call("wall_types"), "Exterior 300")["guid"]
    corners = [(0, 0), (10, 0), (10, 8), (0, 8)]
    walls, last = [], ""
    for i in range(4):
        (x1, y1), (x2, y2) = corners[i], corners[(i + 1) % 4]
        walls.append(call("create_wall", l1, ext, x1, y1, x2, y2, 3.0, last, walls[0] if i == 3 else "")["guid"])
        last = walls[-1]
    door = named(call("opening_types", "door"), "Door 900x2100")
    window = named(call("opening_types", "window"), "Window 1200x1200")
    call("insert_opening", "door", walls[0], door["guid"], 5.0, door["width"], door["height"], door["sill"])
    for wall, along in ((walls[0], 8.0), (walls[1], 4.0), (walls[2], 5.0), (walls[3], 4.0)):
        call("insert_opening", "window", wall, window["guid"], along, window["width"], window["height"], window["sill"])
    floor = named(call("slab_types"), "Floor 200")["guid"]
    outline = call("slab_outline_from_walls", json.dumps(walls))["points"]
    slab1 = call("create_slab", l1, floor, json.dumps(outline), 0.0)["guid"]
    column = named(call("column_types"), "Column 300x300")["guid"]
    for x, y in ((5.0, 4.0),):
        call("create_column", l1, column, x, y, 3.0, 0.0)
    beam = named(call("beam_types"), "Beam 200x400")["guid"]
    call("create_beam", l1, beam, 0.15, 4.0, 9.85, 4.0, 3.0 - 0.2)  # under the Level 2 floor slab

    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    upper = call("copy_to_storey", json.dumps(walls + [slab1]), l2)["guids"]
    slab2 = upper[-1]
    call("create_stair", l1, 1.0, 1.2, 0.0, 1.0, 3.0)
    call("add_slab_opening", slab2, json.dumps([[0.9, 0.6], [6.0, 0.6], [6.0, 1.8], [0.9, 1.8]]))

    roof = call("add_storey", "Roof", 6.0)["guid"]
    call("copy_to_storey", json.dumps([slab1]), roof)

    saved = json.loads(b.save(out))
    if not saved.get("ok"):
        raise SystemExit(f"save failed: {saved.get('error')}")
    count = lambda cls: len(b._model.by_type(cls))  # noqa: E731
    return {"file": out, "storeys": count("IfcBuildingStorey"), "walls": count("IfcWall"), "slabs": count("IfcSlab"),
            "doors": count("IfcDoor"), "windows": count("IfcWindow"), "stairs": count("IfcStair"),
            "columns": count("IfcColumn"), "beams": count("IfcBeam"), "openings": count("IfcOpeningElement")}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tools/make_house.py OUT.ifc")
    Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps(build(sys.argv[1])))
