# SPDX-License-Identifier: GPL-3.0-or-later
"""D87: the annotation pack (doc 14 §13). Associative tags that follow their element and show its
values, tag styles, Tag all; north arrows, scale bars, revision clouds; angle, radius, diameter,
level and spot-elevation dimensions; on plans, drawings, sheets and in DXF."""
import json
import math

import ezdxf
import ifcopenshell.validate
import pytest

from kimbim import app_bridge as b
from kimbim import settings as s
from kimbim import symbols, tags


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


@pytest.fixture
def flat():
    """A 10 x 6 m box of 300 mm walls with a door in the south wall and a room."""
    s.load(None)
    assert call("new_project", "Etiquetas")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    ext = next(t["guid"] for t in call("wall_types")["types"] if t["name"] == "Exterior 300")
    walls, last = [], ""
    corners = [(0, 0), (10, 0), (10, 6), (0, 6)]
    for i in range(4):
        (x1, y1), (x2, y2) = corners[i], corners[(i + 1) % 4]
        walls.append(call("create_wall", l1, ext, x1, y1, x2, y2, 3.0, last, walls[0] if i == 3 else "")["guid"])
        last = walls[-1]
    door_type = call("opening_types", "door")["types"][0]["guid"]
    door = call("insert_opening", "door", walls[0], door_type, 4.0, 0.9, 2.1, 0.0)["guid"]
    room = call("create_room", l1, 2.0, 3.0, "Living room")["guid"]
    yield {"l1": l1, "walls": walls, "door": door, "room": room}
    s.load(None)


def listed(storey):
    return {a["guid"]: a for a in call("annotations", storey)["annotations"]}


def valid():
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    return logger.statements


def plan_svg(storey_name="Level 1"):
    plan = next(d for d in call("drawings")["drawings"] if d["name"] == f"{storey_name} Floor Plan")
    r = call("generate_drawing", plan["guid"], "")
    assert r["ok"], r
    return r["svg"]


# ---------------------------------------------------------------- text

def test_template_text_from_attributes_quantities_and_properties(flat):
    door = b._model.by_guid(flat["door"])
    assert tags.text_of(door, "$width$×$height$") == "0.90×2.10"
    assert tags.text_of(door, "$mark$\n$width$") == "0.90"  # a line whose fields are all empty goes
    assert tags.text_of(door, "$mark|class$") == "IfcDoor"  # the first with a value
    assert tags.text_of(door, "$level$") == "Level 1"
    assert tags.text_of(door, "$sill$") == "0.00"  # D93: the sill height above the wall base
    assert tags.text_of(door, "$mark$") == "?"  # nothing at all: the tag still shows
    assert call("set_property", g(flat["door"]), "Pset_DoorCommon", "FireRating", json.dumps("EI2 30"))["ok"]
    assert tags.text_of(door, "Fire $Pset_DoorCommon.FireRating$") == "Fire EI2 30"
    room = b._model.by_guid(flat["room"])
    stamp = tags.text_of(room, tags.BUILTIN["room"]["template"]).split("\n")
    assert stamp[0] == "Living room" and stamp[-1].endswith(" m²")
    assert tags.template_fields("$gross area$ $mark|name$") == [
        {"source": "quantity", "name": "gross_area"}, {"source": "attribute", "name": "Tag"},
        {"source": "attribute", "name": "Name"}]


# ---------------------------------------------------------------- association

def test_a_tag_follows_its_element_and_shows_its_values(flat):
    assert call("tag_target", flat["l1"], 4.1, 0.05)["guid"] == flat["door"]  # a click on the door
    t = call("add_tag", flat["door"], json.dumps({"template": "$mark$\n$width$×$height$"}))
    assert t["ok"], t
    tag = b._model.by_guid(t["guid"])
    assert tag.ObjectType == "TAG" and tags.element_of(tag).GlobalId == flat["door"]
    rel = next(r for r in tag.HasAssignments if r.is_a("IfcRelAssignsToProduct"))
    assert rel.RelatingProduct.GlobalId == flat["door"]  # IFC's association, not only KimBim's pset
    first = listed(flat["l1"])[t["guid"]]
    assert first["text"] == "0.90×2.10" and first["labels"][0]["text"] == "0.90×2.10"
    # The wall (and its door) move: the tag follows, keeping its place relative to the door.
    assert call("move_elements", g(flat["walls"][0]), 0, -1, 0)["ok"]
    moved = listed(flat["l1"])[t["guid"]]
    assert moved["points"][0] == pytest.approx([first["points"][0][0], first["points"][0][1] - 1])
    assert moved["points"][1] == pytest.approx([first["points"][1][0], first["points"][1][1] - 1])
    # Its values change: the tag's text follows, in the same undo step as the edit.
    r = call("set_schedule_value", g(flat["door"]), json.dumps({"source": "attribute", "name": "Tag"}), json.dumps("D1"))
    assert r["ok"]
    assert listed(flat["l1"])[t["guid"]]["text"] == "D1\n0.90×2.10"
    call("undo")
    assert listed(flat["l1"])[t["guid"]]["text"] == "0.90×2.10"
    # The tag moved by hand keeps its new place; the next element move carries it from there.
    assert call("move_elements", g(t["guid"]), 1, 0, 0)["ok"]
    here = listed(flat["l1"])[t["guid"]]["points"][0]
    assert here == pytest.approx([moved["points"][0][0] + 1, moved["points"][0][1]])
    assert call("move_elements", g(flat["walls"][0]), 0, 0.5, 0)["ok"]
    assert listed(flat["l1"])[t["guid"]]["points"][0] == pytest.approx([here[0], here[1] + 0.5])
    # Both moved together: the tag moves once.
    assert call("move_elements", g(flat["walls"][0], t["guid"]), 0, 0.5, 0)["ok"]
    assert listed(flat["l1"])[t["guid"]]["points"][0] == pytest.approx([here[0], here[1] + 1.0])
    assert valid() == []


def test_a_tag_goes_with_its_element_and_comes_back_with_undo(flat):
    t = call("add_tag", flat["door"], json.dumps({"style": "mark", "leader": True}))["guid"]
    assert call("delete_elements", g(flat["door"]))["ok"]
    assert t not in listed(flat["l1"])
    call("undo")
    assert t in listed(flat["l1"]) and tags.element_of(b._model.by_guid(t)).GlobalId == flat["door"]


def test_a_copied_tag_annotates_the_same_element(flat):
    t = call("add_tag", flat["walls"][1], "")["guid"]
    r = call("copy_elements", g(t), 0, 2, 0)
    assert r["ok"], r
    copies = [a for a in tags.all_tags() if a.GlobalId != t]
    assert len(copies) == 1 and tags.element_of(copies[0]).GlobalId == flat["walls"][1]
    assert any(x.is_a("IfcRelAssignsToProduct") for x in copies[0].HasAssignments)  # re-linked
    assert valid() == []


def test_tag_options_shapes_and_leader(flat):
    t = call("add_tag", flat["door"], json.dumps({"template": "$class$", "shape": "hexagon", "leader": True,
                                                   "at": [5.5, -2.0]}))
    assert t["ok"], t
    a = listed(flat["l1"])[t["guid"]]
    assert a["text"] == "IfcDoor" and a["points"][0] == [5.5, -2.0]
    assert len(a["curves"]) == 2 and len(a["curves"][0]) == 7  # the hexagon (closed) and the leader
    assert a["curves"][1][0] == pytest.approx(a["points"][1])  # the leader starts at the door
    assert a["solids"]  # the leader's dot
    assert call("set_tag", t["guid"], json.dumps({"shape": "circle", "leader": False}))["ok"]
    a = listed(flat["l1"])[t["guid"]]
    assert len(a["curves"]) == 1 and len(a["curves"][0]) == 37
    assert not call("add_tag", flat["door"], json.dumps({"shape": "star"}))["ok"]
    assert not call("add_tag", flat["l1"], "")["ok"]  # a level is not something to tag


# ---------------------------------------------------------------- styles and Tag all

def test_tag_all_tags_each_untagged_door_window_and_wall_once(flat):
    call("add_tag", flat["door"], "")
    r = call("tag_all", flat["l1"], "", "")
    assert r["ok"] and r["tagged"] == 4  # the four walls; the door had one; the room has its stamp
    assert call("tag_all", flat["l1"], "", "")["tagged"] == 0
    assert len(tags.tagged_elements()) == 5
    call("undo")
    assert len(tags.tagged_elements()) == 1  # one undo step
    only = call("tag_all", flat["l1"], g(flat["walls"][2]), "")
    assert only["tagged"] == 1 and tags.element_of(b._model.by_guid(only["guids"][0])).GlobalId == flat["walls"][2]
    shown = listed(flat["l1"])[only["guids"][0]]
    assert shown["text"] == "Exterior 300" and len(shown["curves"][0]) == 5  # the wall tag: type in a box
    assert valid() == []


def test_tag_styles_are_project_settings_and_restyle_their_tags(flat):
    t = call("add_tag", flat["door"], "")["guid"]
    styles = call("tag_styles")
    assert set(tags.AUTO_STYLES) <= set(styles["styles"]) and "room" in styles["styles"]
    r = call("save_tag_style", json.dumps({"id": "door", "name": "Door marker", "classes": ["IfcDoor"],
                                           "template": "P-$width$", "shape": "circle"}))
    assert r["ok"] and r["updated"] == 1, r
    assert listed(flat["l1"])[t]["text"] == "P-0.90"
    assert s.current()["tag_styles"]["door"]["template"] == "P-$width$"
    assert not call("save_tag_style", json.dumps({"name": "Bad", "shape": "star"}))["ok"]
    assert not call("set_project_settings", json.dumps({"tag_styles": {"x": {"name": "X", "size": 0}}}))["ok"]
    # The room stamp style is every room's stamp.
    call("save_tag_style", json.dumps({"id": "room", "name": "Room stamp", "template": "$name$ $longname$"}))
    room = call("rooms", flat["l1"])["rooms"][0]
    assert room["stamp"] == f"{room['number']} Living room"
    assert f">{room['number']} Living room</text>" in plan_svg()
    assert call("delete_tag_style", "door")["ok"]
    assert listed(flat["l1"])[t]["text"] == "?"  # the default door marker is the code alone; no Mark here


# ---------------------------------------------------------------- symbols

def test_north_arrow_follows_true_north(flat):
    n = call("add_symbol", flat["l1"], "north", json.dumps([[15, 3]]), "")
    assert n["ok"], n
    tip = listed(flat["l1"])[n["guid"]]["curves"][1][0]
    assert tip == pytest.approx([15, 3 + 0.6])  # 6 mm at 1:100, up
    assert call("set_true_north", 90)["ok"]  # north turned 90 degrees counter-clockwise: to the west
    assert call("get_true_north")["degrees"] == pytest.approx(90)
    tip = listed(flat["l1"])[n["guid"]]["curves"][1][0]
    assert tip == pytest.approx([15 - 0.6, 3])
    ctx = next(c for c in b._model.by_type("IfcGeometricRepresentationContext") if c.ContextType == "Model")
    assert ctx.TrueNorth.DirectionRatios == pytest.approx((-1.0, 0.0))
    call("undo")
    assert symbols.true_north() == (0.0, 1.0)
    assert valid() == []


def test_scale_bar_cloud_and_dimensions(flat):
    l1 = flat["l1"]
    bar = call("add_symbol", l1, "scalebar", json.dumps([[0, -3]]), "")["guid"]
    cloud = call("add_symbol", l1, "cloud", json.dumps([[1, 1], [3, 1], [3, 2], [1, 2]]), json.dumps({"text": "2"}))["guid"]
    angle = call("add_symbol", l1, "angle", json.dumps([[0, 0], [2, 0], [0, 2], [1, 1]]), "")["guid"]
    obtuse = call("add_symbol", l1, "angle", json.dumps([[0, 0], [2, 0], [0, 2], [-1, -1]]), "")["guid"]
    radius = call("add_symbol", l1, "radius", json.dumps([[5, 3], [6.5, 3], [7, 4]]), "")["guid"]
    diameter = call("add_symbol", l1, "diameter", json.dumps([[5, 3], [6.5, 3], [7, 2]]), "")["guid"]
    shown = listed(l1)
    assert [lab["text"] for lab in shown[bar]["labels"]] == ["0", "1", "2", "3", "4", "5 m", "1:100"]
    assert shown[bar]["curves"][0][1] == pytest.approx([5.0, -3.0]) and len(shown[bar]["solids"]) == 3
    c = shown[cloud]["curves"][0]
    assert c[0] == pytest.approx(c[-1]) and len(c) > 40  # closed, made of arcs
    assert min(p[1] for p in c) < 1 - 0.05  # bulging outwards
    assert shown[cloud]["labels"][0]["text"] == "2"
    assert shown[angle]["labels"][0]["text"] == "90.00°" and shown[obtuse]["labels"][0]["text"] == "270.00°"
    assert shown[radius]["labels"][0]["text"] == "R 1.50" and shown[diameter]["labels"][0]["text"] == "Ø 3.00"
    assert call("set_annotation_text", radius, "R var.")["ok"] and listed(l1)[radius]["text"] == "R var."
    assert call("set_annotation_text", radius, "")["ok"] and listed(l1)[radius]["labels"][0]["text"] == "R 1.50"
    assert not call("add_symbol", l1, "angle", json.dumps([[0, 0], [0, 0], [0, 2], [1, 1]]), "")["ok"]
    assert not call("add_symbol", l1, "cloud", json.dumps([[0, 0], [2, 2], [2, 0], [0, 2]]), "")["ok"]
    assert not call("add_symbol", l1, "tag", json.dumps([[0, 0], [1, 1]]), "")["ok"]
    types = {b._model.by_guid(x).ObjectType for x in (bar, cloud, angle, radius, diameter)}
    assert types == {"SCALEBAR", "CLOUD", "ANGLE", "RADIUS", "DIAMETER"}
    rep = b._model.by_guid(cloud).Representation.Representations[0]
    assert rep.RepresentationType == "Annotation2D" and any(i.is_a("IfcTextLiteralWithExtent") for i in rep.Items)
    assert valid() == []


def test_level_and_spot_elevations_measure_the_slab_below(flat):
    slab_type = call("slab_types")["types"][0]["guid"]
    slab = call("create_slab", flat["l1"], slab_type, json.dumps([[0, 0], [10, 0], [10, 6], [0, 6]]), 0.0)
    assert slab["ok"], slab
    level = call("add_symbol", flat["l1"], "level", json.dumps([[2, 3]]), "")["guid"]
    spot = call("add_symbol", flat["l1"], "spot", json.dumps([[12, 3], [13, 4]]), "")["guid"]  # off the slab
    shown = listed(flat["l1"])
    assert shown[level]["text"] == "±0.00" and shown[spot]["text"] == "±0.00"
    assert call("move_elements", g(slab["guid"]), 0, 0, 0.15)["ok"]  # the slab goes up: the level follows
    assert listed(flat["l1"])[level]["text"] == "+0.15"
    assert call("set_annotation_text", spot, "+0.30 FFL")["ok"]
    assert listed(flat["l1"])[spot]["text"] == "+0.30 FFL"  # its own text stays
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    up = call("add_symbol", l2, "level", json.dumps([[20, 20]]), "")["guid"]
    assert listed(l2)[up]["text"] == "+3.00"  # no slab: the level's elevation


# ---------------------------------------------------------------- drawings, sheets, DXF

def test_plan_drawing_has_tags_stamps_and_symbols(flat, tmp_path):
    t = call("add_tag", flat["door"], json.dumps({"template": "$width$×$height$"}))["guid"]
    call("add_symbol", flat["l1"], "north", json.dumps([[15, 3]]), "")
    call("add_symbol", flat["l1"], "cloud", json.dumps([[1, 1], [3, 1], [3, 2]]), json.dumps({"text": "A"}))
    call("add_symbol", flat["l1"], "angle", json.dumps([[0, 0], [2, 0], [0, 2], [1, 1]]), "")
    svg = plan_svg()
    marks = svg.split('class="kimbim-marks"', 1)[1]
    assert f'ifc:guid="{t}"' in marks and ">0.90×2.10</text>" in marks
    assert 'data-symbol="north"' in marks and ">N</text>" in marks and ">A</text>" in marks
    assert ">90.00°</text>" in marks and ">Living room</text>" in marks  # the room stamp
    assert 'data-fill="pen"' not in svg  # styled: filled with the pen's colour
    plan = next(d["guid"] for d in call("drawings")["drawings"] if d["name"] == "Level 1 Floor Plan")
    r = call("export_drawing_dxf", plan, str(tmp_path / "plan.dxf"), "")
    assert r["ok"], r
    texts = {e.dxf.text for e in ezdxf.readfile(r["path"]).modelspace().query("TEXT")}
    assert {"0.90×2.10", "N", "A", "90.00°", "Living room"} <= texts


def test_sections_show_the_levels(flat):
    call("add_storey", "Level 2", 3.0)
    sec = call("create_section", -1, 3, 11, 3, 5, 10, -1)["guid"]
    svg = call("generate_drawing", sec, "")["svg"]
    assert ">Level 1 ±0.00</text>" in svg and ">Level 2 +3.00</text>" in svg


def test_sheet_north_arrow_scale_bar_and_cloud(flat, tmp_path):
    number = call("add_sheet", "A3", "Plans")["number"]
    plan = next(d["guid"] for d in call("drawings")["drawings"] if d["name"] == "Level 1 Floor Plan")
    assert call("place_drawing", number, plan, -1, -1, 50)["ok"]
    north = call("place_sheet_symbol", number, "north", "")
    bar = call("place_sheet_symbol", number, "scalebar", "")
    cloud = call("place_sheet_symbol", number, "cloud", json.dumps({"text": "3", "x": 30, "y": 30, "w": 40, "h": 20}))
    assert north["ok"] and bar["ok"] and cloud["ok"], (north, bar, cloud)
    sheet = next(x for x in call("sheets")["sheets"] if x["number"] == number)
    kinds = {x["kind"]: x for x in sheet["symbols"]}
    assert set(kinds) == {"north", "scalebar", "cloud"} and kinds["cloud"]["x"] == 30 and kinds["cloud"]["w"] == 40
    svg = call("sheet_svg", number)["svg"]
    assert svg.count('class="kimbim-sheet-symbol"') == 3
    assert ">1:50</text>" in svg and ">2.5 m</text>" in svg  # the bar shows the drawing's scale (50 mm of paper)
    assert call("move_sheet_symbol", number, north["id"], 100, 50)["ok"]
    sheet = next(x for x in call("sheets")["sheets"] if x["number"] == number)
    assert next(x for x in sheet["symbols"] if x["kind"] == "north")["x"] == 100
    r = call("export_sheet_dxf", number, str(tmp_path / "sheet.dxf"), "")
    assert r["ok"], r
    doc = ezdxf.readfile(r["path"])
    texts = {e.dxf.text for e in doc.layouts.get(r["layout"]).query("TEXT")}
    assert {"N", "3", "1:50"} <= texts
    assert call("remove_sheet_symbol", number, cloud["id"])["ok"]
    assert len(next(x for x in call("sheets")["sheets"] if x["number"] == number)["symbols"]) == 2
    assert not call("place_sheet_symbol", number, "compass", "")["ok"]
    assert valid() == []


def test_symbol_geometry_is_pure():
    assert symbols.nice_length(5.0) == (5.0, 5) and symbols.nice_length(2.6) == (2.5, 5)
    assert symbols.nice_length(23) == (20, 4) and symbols.nice_length(0.13) == pytest.approx((0.1, 5))
    start, sweep, r = symbols.angle_frame((0, 0), (1, 0), (0, 1), (-1, 0))
    assert math.degrees(sweep) == pytest.approx(270) and r == pytest.approx(1)
    frame, boundary = symbols.tag_outline("none", (0, 0), ["AB"], 0.25)
    assert frame is None and len(boundary) == 4
