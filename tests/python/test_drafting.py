# SPDX-License-Identifier: GPL-3.0-or-later
"""D84: 2D drafting (doc 14 §12): lines, polylines, arcs, circles, rectangles and fills on a plan,
stored as IFC annotations on the level, drawn in plan drawings."""
import json
import math

import ifcopenshell.validate
import pytest

from kimbim import app_bridge as b
from kimbim import drafting
from kimbim import settings as s


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


def pts(*p):
    return json.dumps([list(x) for x in p])


@pytest.fixture
def plan():
    s.load(None)
    assert call("new_project", "Dibujo")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    yield {"l1": l1, "l2": l2}
    s.load(None)


def listed(storey):
    return {a["guid"]: a for a in call("annotations", storey)["annotations"]}


def valid():
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    return logger.statements


def test_each_shape_is_an_ifc_annotation_on_the_level(plan):
    line = call("add_drafting", plan["l1"], "line", pts((0, 0), (4, 0)), "")
    poly = call("add_drafting", plan["l1"], "polyline", pts((0, 1), (2, 1), (2, 3)), json.dumps({"line_type": "Dashed"}))
    arc = call("add_drafting", plan["l1"], "arc", pts((0, 0), (1, 1), (2, 0)), "")
    circle = call("add_drafting", plan["l1"], "circle", pts((5, 5), (6, 5)), "")
    rect = call("add_drafting", plan["l1"], "rectangle", pts((10, 0), (13, 2)), "")
    fill = call("add_drafting", plan["l1"], "fill", pts((0, 0), (4, 0), (4, 3), (0, 3)),
                json.dumps({"pattern": "Crosshatch", "background_pen": 5, "show_area": True}))
    for r in (line, poly, arc, circle, rect, fill):
        assert r["ok"], r
    shown = listed(plan["l1"])
    assert shown[line["guid"]]["kind"] == "line" and shown[line["guid"]]["points"] == [[0.0, 0.0], [4.0, 0.0]]
    assert shown[poly["guid"]]["line_type"] == "Dashed" and shown[poly["guid"]]["dash"] == [3.0, 1.5]
    assert shown[rect["guid"]]["kind"] == "polyline" and shown[rect["guid"]]["closed"]
    assert len(shown[rect["guid"]]["points"]) == 4 and len(shown[rect["guid"]]["curves"][0]) == 5
    a = shown[arc["guid"]]["curves"][0]
    assert a[0] == pytest.approx([0, 0]) and a[-1] == pytest.approx([2, 0], abs=1e-9)
    assert max(p[1] for p in a) == pytest.approx(1.0, abs=1e-3)  # through the top of the half circle
    f = shown[fill["guid"]]
    assert f["pattern"] == "Crosshatch" and f["background_pen"] == 5 and f["hatch"] and not f["solid"]
    assert f["area_text"] == "12.00 m²" and f["label_at"] == pytest.approx([2.0, 1.5])
    assert listed(plan["l2"]) == {}
    types = {b._model.by_guid(r["guid"]).ObjectType for r in (line, poly, arc, circle, fill)}
    assert types == {"LINE", "POLYLINE", "ARC", "CIRCLE", "FILL"}
    rep = b._model.by_guid(fill["guid"]).Representation.Representations[0]
    assert rep.ContextOfItems.ContextType == "Plan" and rep.RepresentationType == "Annotation2D"
    area = next(i for i in rep.Items if i.is_a("IfcAnnotationFillArea"))
    style = area.StyledByItem[0].Styles[0]
    assert style.is_a("IfcFillAreaStyle") and style.Name == "Crosshatch"
    assert sum(1 for x in style.FillStyles if x.is_a("IfcFillAreaStyleHatching")) == 2
    assert sum(1 for x in style.FillStyles if x.is_a("IfcColourRgb")) == 1  # the background pen
    trimmed = next(i for i in b._model.by_guid(arc["guid"]).Representation.Representations[0].Items)
    assert trimmed.is_a("IfcTrimmedCurve") and trimmed.SenseAgreement is False  # clockwise over the top
    assert valid() == []


def test_fill_outline_pen_pattern_scale_and_rectangle_marker(plan):
    """D92: a fill's outline can take its own pen or none; its pattern spacings can be paper or
    model; a rectangle is marked so a grip can keep it rectangular."""
    rect = call("add_drafting", plan["l1"], "rectangle", pts((0, 0), (4, 2)), "")["guid"]
    assert listed(plan["l1"])[rect]["rect"] is True
    none = call("add_drafting", plan["l1"], "fill", pts((0, 0), (4, 0), (4, 3), (0, 3)),
                json.dumps({"pattern": "Diagonal", "outline_pen": 0, "pattern_scale": "paper"}))["guid"]
    own = call("add_drafting", plan["l1"], "fill", pts((5, 0), (9, 0), (9, 3), (5, 3)),
               json.dumps({"pattern": "Diagonal", "outline_pen": 12, "pattern_scale": "model"}))["guid"]
    shown = listed(plan["l1"])
    assert shown[none]["outline_pen"] == 0 and shown[own]["outline_pen"] == 12
    assert len(shown[own]["hatch"]) > len(shown[none]["hatch"])  # model spacings are finer on paper
    assert not call("add_drafting", plan["l1"], "fill", pts((0, 0), (2, 0), (2, 2)),
                    json.dumps({"outline_pen": 300}))["ok"]
    assert not call("add_drafting", plan["l1"], "fill", pts((0, 0), (2, 0), (2, 2)),
                    json.dumps({"pattern_scale": "screen"}))["ok"]


def test_every_built_in_pattern_is_schema_valid(plan):
    for name in drafting.patterns():
        r = call("add_drafting", plan["l1"], "fill", pts((0, 0), (3, 0), (3, 2)),
                 json.dumps({"pattern": name, "background_pen": 0}))
        assert r["ok"], (name, r)
    assert valid() == []


def test_bad_shapes_are_refused(plan):
    assert not call("add_drafting", plan["l1"], "line", pts((1, 1), (1, 1)), "")["ok"]
    assert not call("add_drafting", plan["l1"], "arc", pts((0, 0), (1, 0), (2, 0)), "")["ok"]  # in a line
    assert not call("add_drafting", plan["l1"], "fill", pts((0, 0), (2, 2), (2, 0), (0, 2)), "")["ok"]  # crossing
    assert not call("add_drafting", plan["l1"], "rectangle", pts((0, 0), (2, 0)), "")["ok"]
    assert not call("add_drafting", plan["l1"], "spline", pts((0, 0), (2, 0)), "")["ok"]
    assert not call("add_drafting", plan["l1"], "line", pts((0, 0), (2, 0)), json.dumps({"line_type": "Nope"}))["ok"]
    assert not call("add_drafting", plan["l1"], "fill", pts((0, 0), (2, 0), (2, 2)), json.dumps({"pattern": "Nope"}))["ok"]
    assert not call("add_annotation", plan["l1"], "line", pts((0, 0), (2, 0)), "x")["ok"]  # not through add_annotation


def test_shapes_take_the_current_pen_and_layer_and_change_style_in_one_step(plan):
    assert json.loads(s.set_project_settings(json.dumps({"current_pen": 26})))["ok"]
    call("create_layer", "A-DETL")
    call("set_active_layer", "A-DETL")
    line = call("add_drafting", plan["l1"], "line", pts((0, 0), (4, 0)), "")["guid"]
    fill = call("add_drafting", plan["l1"], "fill", pts((0, 0), (4, 0), (4, 3)), "")["guid"]
    assert listed(plan["l1"])[line]["pen"] == 26 and listed(plan["l1"])[fill]["pattern"] == "Solid"
    assert {line, fill} <= set(call("layer_members")["layers"]["A-DETL"])
    r = call("set_drafting_style", g(line, fill), json.dumps({"line_type": "Dotted", "pattern": "Brick", "pen": 5}))
    assert r["ok"], r
    shown = listed(plan["l1"])
    assert shown[line]["line_type"] == "Dotted" and shown[line]["pen"] == 5 and "pattern" not in shown[line]
    assert shown[fill]["pattern"] == "Brick" and shown[fill]["pen"] == 5
    assert {line, fill} <= set(call("layer_members")["layers"]["A-DETL"])  # restyling keeps the layer
    call("undo")
    shown = listed(plan["l1"])
    assert shown[line]["line_type"] == "Solid" and shown[fill]["pattern"] == "Solid" and shown[line]["pen"] == 26


def test_move_rotate_mirror_copy_delete(plan):
    line = call("add_drafting", plan["l1"], "line", pts((0, 0), (2, 0)), "")["guid"]
    arc = call("add_drafting", plan["l1"], "arc", pts((0, 0), (1, 1), (2, 0)), "")["guid"]
    assert call("move_elements", g(line, arc), 1, 1, 0)["ok"]
    assert listed(plan["l1"])[line]["points"] == [[1.0, 1.0], [3.0, 1.0]]
    assert call("rotate_elements", g(line), 1, 1, math.pi / 2)["ok"]
    assert listed(plan["l1"])[line]["points"][1] == pytest.approx([1.0, 3.0])
    assert call("mirror_elements", g(arc), 0, 0, 10, 0)["ok"]  # across the x axis: the arc bulges down
    curve = listed(plan["l1"])[arc]["curves"][0]
    assert min(p[1] for p in curve) == pytest.approx(-2.0, abs=1e-3)
    copied = call("copy_elements", g(arc), 5, 0)
    assert copied["ok"], copied
    c = copied["guids"][0]
    assert listed(plan["l1"])[c]["points"][0] == pytest.approx([6.0, -1.0])
    assert b._model.by_guid(c).Representation is not None  # the copy has its own shape
    assert call("copy_to_storey", g(line), plan["l2"])["ok"]
    assert len(listed(plan["l2"])) == 1
    assert call("delete_elements", g(line))["ok"]
    assert line not in listed(plan["l1"])
    assert valid() == []


def test_grips_move_a_point_and_fill_from_a_closed_shape(plan):
    poly = call("add_drafting", plan["l1"], "polyline", pts((0, 0), (4, 0), (4, 4), (0, 4)), json.dumps({"closed": True}))["guid"]
    assert call("set_annotation_points", poly, pts((0, 0), (5, 0), (4, 4), (0, 4)))["ok"]
    assert listed(plan["l1"])[poly]["points"][1] == [5.0, 0.0] and listed(plan["l1"])[poly]["closed"]
    assert not call("set_annotation_points", poly, pts((0, 0), (0, 0)))["ok"]
    r = call("fill_from_shape", poly, json.dumps({"pattern": "Diagonal"}))
    assert r["ok"], r
    assert listed(plan["l1"])[r["guid"]]["points"] == [[0.0, 0.0], [5.0, 0.0], [4.0, 4.0], [0.0, 4.0]]
    circle = call("add_drafting", plan["l1"], "circle", pts((20, 0), (21, 0)), "")["guid"]
    w = call("fill_at", plan["l1"], 20.2, 0.1, json.dumps({"pattern": "Concrete"}))
    assert w["ok"], w
    assert len(listed(plan["l1"])[w["guid"]]["points"]) == drafting.CIRCLE_SEGMENTS
    assert not call("fill_at", plan["l1"], 50, 50, "")["ok"]
    line = call("add_drafting", plan["l1"], "line", pts((0, 0), (1, 0)), "")["guid"]
    assert not call("fill_from_shape", line, "")["ok"]
    assert circle


def test_fill_patterns_are_a_project_settings_table(plan):
    assert "Brick" in call("fill_patterns")["names"]
    mine = {"Solid": {"solid": True, "lines": []}, "Tiles": {"lines": [{"angle": 0, "spacing": 3}, {"angle": 90, "spacing": 3}]}}
    assert call("set_graphics", json.dumps({"fill_patterns": mine}))["ok"]
    assert call("fill_patterns")["names"] == ["Solid", "Tiles"]
    r = call("add_drafting", plan["l1"], "fill", pts((0, 0), (3, 0), (3, 3), (0, 3)), json.dumps({"pattern": "Tiles"}))
    assert r["ok"], r
    assert not call("set_graphics", json.dumps({"fill_patterns": {"Bad": {"lines": [{"angle": 0, "spacing": 0}]}}}))["ok"]
    assert not call("set_graphics", json.dumps({"fill_patterns": {"Bad": {"lines": [{"spacing": 1, "dash": [1]}]}}}))["ok"]


def test_hatch_geometry():
    square = [[0, 0], [1, 0], [1, 1], [0, 1]]
    lines = drafting.hatch(square, {"lines": [{"angle": 0, "spacing": 1.0}]}, 0.1)  # every 0.1 m
    assert len(lines) == 9 and all(seg[0] == pytest.approx(0) and seg[2] == pytest.approx(1) for seg in lines)
    brick = drafting.hatch(square, drafting.patterns()["Brick"], 0.1)
    vertical = [x for x in brick if abs(x[0] - x[2]) < 1e-9]
    assert vertical and all(abs(x[3] - x[1]) == pytest.approx(0.2) for x in vertical if 0 < x[1] < 0.8)
    assert drafting.hatch(square, {"lines": [{"angle": 0, "spacing": 0.0001}]}, 0.1) == []  # too fine: left out
    assert drafting.hatch(square, {"solid": True, "lines": []}, 0.1) == []


def test_insulation_defaults_to_loops_and_zigzag_is_available():
    square = [[0, 0], [2, 0], [2, 2], [0, 2]]
    loops = drafting.hatch(square, drafting.patterns()["Insulation"], 0.1)
    assert loops and all(abs(seg[0] - seg[2]) < 0.3 for seg in loops)  # short arc segments (D93)
    zigzag = drafting.hatch(square, drafting.patterns()["Zigzag"], 0.1)
    assert zigzag and zigzag != loops  # the zigzag is still there
    assert not call("set_graphics", json.dumps({"fill_patterns": {"Bad": {"loops": True, "radius": 0}}}))["ok"]


def test_saved_versions_round_trip_and_compare(plan, tmp_path):
    folder = tmp_path / "proj"
    assert call("enable_versioning", str(folder), "Start")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    fill = call("add_drafting", storey, "fill", pts((0, 0), (4, 0), (4, 3), (0, 3)),
                json.dumps({"pattern": "Insulation", "background_pen": 31, "show_area": True}))["guid"]
    arc = call("add_drafting", storey, "arc", pts((0, 0), (1, 1), (2, 0)), json.dumps({"line_type": "Dashed"}))["guid"]
    first = call("history", 1)["versions"][0]["id"]
    c = call("compare", first, "WORKING")
    assert {fill, arc} <= {x["guid"] for x in c["added"]}
    r = call("save_version", "Drafting")
    assert r["ok"], r
    assert call("set_drafting_style", g(arc), json.dumps({"line_type": "Dotted"}))["ok"]
    head = call("history", 1)["versions"][0]["id"]
    assert arc in {x["guid"] for x in call("compare", head, "WORKING")["modified"]}
    call("undo")
    before = listed(storey)
    assert call("open_project", str(folder))["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    after = listed(storey)
    assert after[fill] == before[fill] and after[arc] == before[arc]
    assert valid() == []


def test_plan_drawing_and_sheet_include_the_shapes(plan):
    from kimbim import graphics

    t = call("wall_types")["types"][0]["guid"]
    assert call("create_wall", plan["l1"], t, -1, 5, 6, 5, 3.0, "", "")["ok"]  # an empty plan has no drawing
    fill = call("add_drafting", plan["l1"], "fill", pts((0, 0), (4, 0), (4, 3), (0, 3)),
                json.dumps({"pattern": "Diagonal", "background_pen": 33, "show_area": True}))["guid"]
    line = call("add_drafting", plan["l1"], "line", pts((0, -1), (4, -1)), json.dumps({"line_type": "Dashed"}))["guid"]
    plan_drawing = call("create_plan", plan["l1"])
    assert plan_drawing["ok"], plan_drawing
    r = call("generate_drawing", plan_drawing["guid"], "")
    assert r["ok"], r
    svg = r["svg"]
    assert f'ifc:guid="{fill}"' in svg and f'ifc:guid="{line}"' in svg
    assert 'class="hatch"' in svg and "12.00 m²" in svg
    pens = graphics.resolve()["pens"]
    assert f'fill="{pens["33"]["color"]}"' in svg  # the background pen
    assert 'stroke-dasharray="3 1.5"' in svg  # the dashed line type, 1:1 on paper
    sheet = call("add_sheet", "A1", "Plans")
    assert sheet["ok"], sheet
    assert call("place_drawing", sheet["number"], plan_drawing["guid"], 20, 20)["ok"]
    sheet_svg = call("sheet_svg", sheet["number"])
    assert sheet_svg.get("ok", True) and f'ifc:guid="{fill}"' in sheet_svg["svg"]


def test_dxf_export_has_the_lines_arcs_and_pattern_hatches(plan, tmp_path):
    """D83 + D84: drafting reaches DXF: lines with their line type, fills as HATCH with the pattern."""
    import ezdxf

    t = call("wall_types")["types"][0]["guid"]
    assert call("create_wall", plan["l1"], t, -1, 5, 6, 5, 3.0, "", "")["ok"]
    call("add_drafting", plan["l1"], "fill", pts((0, 0), (4, 0), (4, 3), (0, 3)),
         json.dumps({"pattern": "Crosshatch", "background_pen": 33}))
    call("add_drafting", plan["l1"], "fill", pts((5, 0), (7, 0), (7, 2)), json.dumps({"pattern": "Solid"}))
    call("add_drafting", plan["l1"], "line", pts((0, -1), (4, -1)), json.dumps({"line_type": "Dashed"}))
    call("add_drafting", plan["l1"], "arc", pts((0, 0), (1, 1), (2, 0)), "")
    guid = call("create_plan", plan["l1"])["guid"]
    r = call("export_drawing_dxf", guid, str(tmp_path / "plan.dxf"), "")
    assert r["ok"], r
    doc = ezdxf.readfile(r["path"])
    assert not doc.audit().has_errors
    msp = doc.modelspace()
    hatches = list(msp.query("HATCH"))
    patterned = [h for h in hatches if not h.dxf.solid_fill]
    assert patterned and patterned[0].dxf.pattern_name == "CROSSHATCH"
    assert len(patterned[0].pattern.lines) == 2
    assert sum(1 for h in hatches if h.dxf.solid_fill) >= 2  # the background pen and the solid fill
    assert "DASHED" in doc.linetypes
    assert any(e.dxf.get("linetype") == "DASHED" for e in msp.query("LINE LWPOLYLINE"))
    assert len(msp.query("LINE")) < 200  # the hatch lines are not also written one by one


# ---------------------------------------------------------------- splines (D98)

def test_spline_passes_through_its_points_smoothly():
    p = [(0, 0), (2, 1), (4, 0), (6, 1)]
    curve = drafting.spline_points(p)
    for q in p:  # it passes through every point
        assert min(math.dist(q, c) for c in curve) < 1e-9
    assert len(curve) == 1 + 3 * drafting.SPLINE_STEPS
    assert max(c[1] for c in curve) < 1.2  # centripetal: no wild overshoot
    closed = drafting.spline_points(p, closed=True)
    assert closed[-1] == pytest.approx(list(p[0]))  # back to the start
    assert drafting.spline_points([(0, 0), (1, 0)]) == [[0, 0], [1, 0]]  # two points: a straight line


def test_spline_drafting_shape(plan):
    level = plan["l1"]
    r = call("add_drafting", level, "spline", pts((0, 0), (2, 1), (4, 0)), json.dumps({"closed": False}))
    assert r["ok"], r
    shape = next(a for a in listed(level).values() if a["kind"] == "spline")
    assert len(shape["curves"][0]) == 1 + 2 * drafting.SPLINE_STEPS
    snaps = {(round(p["x"], 6), round(p["y"], 6)) for p in call("snap_data", level)["points"]}
    assert {(0, 0), (2, 1), (4, 0)} <= snaps
    r = call("add_drafting", level, "spline", pts((0, 0), (2, 1), (4, 0)), json.dumps({"closed": True}))
    assert r["ok"], r
    assert not call("add_drafting", level, "spline", pts((0, 0)), "")["ok"]
    assert not call("add_drafting", level, "spline", pts((0, 0), (1, 1)), json.dumps({"closed": True}))["ok"]
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger)
    assert [x for x in logger.statements if x.get("level") == "error"] == []
