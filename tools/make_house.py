# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the M3 exit-test house through the app's modeling commands and save it as IFC.

Two storeys (Level 1 at 0, Level 2 at 3 m, Roof at 6 m): a 10 x 8 m loop of exterior walls per
floor, a front door and windows, floor slabs, a roof slab, a U stair from Level 1 to Level 2 with its
railings and its automatic hole in the Level 2 floor, a ramp with a railing (D88), columns and a beam. Plus the M4 exit: floor plans, a section, elevations
and sheet A01 holding the ground floor plan, the section and the south elevation. This is the same modeling path the GUI uses
(app_bridge), without the GUI, so CI can produce the file on any machine.

Usage: python tools/make_house.py OUT.ifc   (prints a JSON summary)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from kimbim import app_bridge as b  # noqa: E402


def call(fn, *args):
    result = json.loads(getattr(b, fn)(*args))
    if isinstance(result, dict) and result.get("ok") is False:
        raise SystemExit(f"{fn} failed: {result.get('error')}")
    return result


def named(listing, name):
    return next(t for t in listing["types"] if t["name"] == name)


def build(out: str) -> dict:
    call("new_project", "KimBim two-storey house")
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
    # D88: a U stair with its half landing and railings; its hole in the Level 2 floor is automatic.
    stair = call("create_stair", l1, 1.0, 1.2, 0.0, 1.0, 3.0, json.dumps({"shape": "U"}))["guid"]
    call("add_stair_railings", stair, "0.9", "both")
    # and a ramp up to a raised floor in the living room, with a railing by path
    call("create_ramp", l1, 6.0, 2.7, 0.0, 1.0, 0.2, json.dumps({"slope": 8}))
    call("create_railing", l1, json.dumps([[6.0, 2.1], [8.5, 2.1]]), "1.1")

    # Plan annotations (Slice 13): a label, a dimension and a mark on Level 1.
    call("add_annotation", l1, "text", json.dumps([[3.0, 2.0]]), "Living room")
    call("add_annotation", l1, "dimension", json.dumps([[0.0, 0.0], [10.0, 0.0], [0.0, -1.0]]), "")
    call("add_annotation", l1, "mark", json.dumps([[8.0, 6.0]]), "A")
    # Rooms (Slice 18): one per level, from the walls around a point.
    call("create_room", l1, 2.0, 6.0, "Living room")
    call("create_room", l2, 5.0, 6.0, "Bedroom")
    # Library objects (D86): furniture, a kitchen run, a bathroom and a bedroom, a tree and a car outside.
    for storey, key, x, y, angle in ((l1, "sofa", 6.5, 6.9, 0.0), (l1, "table", 2.0, 4.6, 0.0),
                                     (l1, "chair", 3.0, 4.5, math.pi), (l1, "chair", 2.5, 5.6, 0.0),
                                     (l1, "base_cabinets", 9.8, 0.75, math.pi), (l1, "fridge", 6.9, 0.8, math.pi),
                                     (l1, "tree", 12.0, 3.0, 0.0), (l1, "car", -3.0, 1.0, 0.0),
                                     (l2, "bed_double", 6.0, 5.75, 0.0), (l2, "wardrobe", 8.6, 2.5, math.pi / 2),
                                     (l2, "wc", 1.0, 7.1, 0.0), (l2, "washbasin", 1.6, 7.35, 0.0),
                                     (l2, "bathtub", 2.6, 7.05, 0.0)):
        call("place_object", storey, key, "", x, y, angle)
    roof = call("add_storey", "Roof", 6.0)["guid"]
    call("copy_to_storey", json.dumps([slab1]), roof)
    # Roof (Slice 19): a 30-degree gable roof with 0.5 m eaves; the upper walls are trimmed to it.
    pitched = call("create_roof", roof, json.dumps([[-0.5, -0.5], [10.5, -0.5], [10.5, 8.5], [-0.5, 8.5]]), "gable",
                   30, 0.25, 0.0, "")["guid"]
    call("attach_walls_to_roof", pitched, json.dumps(upper[:4]))

    # M4 exit (Slices 14-16): a section across the house and sheet A01 with the ground floor plan, the
    # section and the south elevation, under a title block filled from the project info.
    call("set_project_info", json.dumps({"number": "M4-01", "name": "KimBim two-storey house",
                                         "client": "KimBim test client", "address": "1 Sample Street"}))
    section = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, -1)["guid"]
    drawing = {d["name"]: d["guid"] for d in call("drawings")["drawings"]}
    sheet = call("add_sheet", "A3", "Plan, section and elevation")["number"]
    for guid in (drawing["Level 1 Floor Plan"], section, drawing["South Elevation"]):
        call("place_drawing", sheet, guid, -1, -1, 100)

    saved = json.loads(b.save(out))
    if not saved.get("ok"):
        raise SystemExit(f"save failed: {saved.get('error')}")
    count = lambda cls: len(b._model.by_type(cls))  # noqa: E731
    return {"file": out, "storeys": count("IfcBuildingStorey"), "walls": count("IfcWall"), "slabs": count("IfcSlab"),
            "doors": count("IfcDoor"), "windows": count("IfcWindow"), "stairs": count("IfcStair"), "ramps": count("IfcRamp"), "railings": count("IfcRailing"),
            "columns": count("IfcColumn"), "rooms": count("IfcSpace"), "roofs": count("IfcRoof"), "beams": count("IfcBeam"), "openings": count("IfcOpeningElement"),
            "objects": count("IfcFurniture") + count("IfcSanitaryTerminal") + count("IfcElectricAppliance")
            + count("IfcGeographicElement") + count("IfcBuildingElementProxy"),
            "drawings": len(call("drawings")["drawings"]), "sheets": len(call("sheets")["sheets"])}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tools/make_house.py OUT.ifc")
    Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps(build(sys.argv[1])))
