# SPDX-License-Identifier: GPL-3.0-or-later
"""Detail views: an enlarged, cropped plan of a level with its plan marker (callout).

A detail is a drawing (KIMBIM_Drawing Kind "detail") over a polygonal region of a source level, at
its own scale (1:20 by default), plus an IfcAnnotation DETAIL on that level whose KIMBIM_Annotation
property set links the drawing. Its SVG is the level's plan at the detail's scale, framed by the
region's bounding box in metres.
"""
import json
import re
import sys
from pathlib import Path

import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.validate
import pytest

from kimbim import app_bridge as b
from kimbim import drawings as D

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import make_house  # noqa: E402

# A rectangle over the house's south-west corner: two walls, the front door and the stair.
REGION = [[-1.0, -1.0], [6.0, -1.0], [6.0, 4.5], [-1.0, 4.5]]


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture(scope="module")
def house_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("house") / "house.ifc"
    make_house.build(str(path))
    return str(path)


@pytest.fixture
def house(house_file):
    assert call("open_model", house_file)["ok"]
    return call("storeys")["storeys"][0]["guid"]


def detail(guid):
    return next((d for d in call("drawings")["drawings"] if d["guid"] == guid), None)


def markers(level_guid, drawing_guid):
    """The detail markers on a level that link `drawing_guid`."""
    out = []
    for a in b._model.by_type("IfcAnnotation"):
        if a.ObjectType != "DETAIL":
            continue
        data = ifcopenshell.util.element.get_pset(a, "KIMBIM_Annotation") or {}
        container = ifcopenshell.util.element.get_container(a)
        if data.get("Drawing") == drawing_guid and container is not None and container.GlobalId == level_guid:
            out.append(a)
    return out


def svg_header(svg):
    m = re.search(r'width="([\d.]+)mm" height="([\d.]+)mm" viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', svg)
    assert m, svg[:400]
    return (float(m.group(1)), float(m.group(2)),
            [float(m.group(3)), float(m.group(4)), float(m.group(5)), float(m.group(6))])


def test_a_detail_is_a_cropped_plan_with_a_marker_on_its_level(house):
    r = json.loads(D.create_detail(house, json.dumps(REGION), 20, "Stair detail"))
    assert r["ok"], r
    guid, marker = r["guid"], r["marker"]
    info = json.loads(D.detail_info(guid))
    assert info["ok"] and info["kind"] == "detail"
    assert info["source_level"] == house
    assert info["scale"] == 20
    assert info["name"] == "Stair detail"
    assert [[round(x, 6), round(y, 6)] for x, y in info["region"]] == REGION
    # the drawing is listed with kind "detail" (Project Map) and its own scale and region
    listed = detail(guid)
    assert listed is not None and listed["kind"] == "detail"
    assert listed["scale"] == 20 and listed["source_level"] == house
    assert len(listed["region"]) == 4
    # the plan marker is on the source level and links the drawing
    found = markers(house, guid)
    assert len(found) == 1 and found[0].GlobalId == marker
    assert found[0].Name == "1" and found[0].ObjectType == "DETAIL"
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    assert logger.statements == []
    # ... and it shows on the level's plan, with its bubble, leader and region outline
    plan = next(d for d in call("drawings")["drawings"] if d["kind"] == "plan")
    plan_svg = call("generate_drawing", plan["guid"], "")["svg"]
    assert f'data-detail="{marker}"' in plan_svg
    assert ">1</text>" in plan_svg
    assert call("state")["can_undo"]  # one undo step
    assert json.loads(D.delete_detail(guid))["ok"]
    assert detail(guid) is None and markers(house, guid) == []
    assert call("undo")["ok"]  # the drawing and its marker come back together
    assert detail(guid) is not None and len(markers(house, guid)) == 1


def test_the_detail_svg_is_the_region_at_its_scale(house):
    guid = json.loads(D.create_detail(house, json.dumps(REGION), 20, "Corner detail"))["guid"]
    r = call("generate_drawing", guid, "")
    assert r["ok"], r
    svg = r["svg"]
    width, height, box = svg_header(svg)
    # 7 m x 5.5 m at 1:20: 350 mm x 275 mm, its viewBox the region's bbox in metres (y negated: SVG's
    # y grows downward), so the content keeps the plan's coordinate system.
    assert width == pytest.approx(7.0 * 1000 / 20, abs=0.02)
    assert height == pytest.approx(5.5 * 1000 / 20, abs=0.02)
    assert box[0] == pytest.approx(-1.0, abs=0.001)
    assert box[1] == pytest.approx(-4.5, abs=0.001)
    assert box[2] == pytest.approx(7.0, abs=0.001)
    assert box[3] == pytest.approx(5.5, abs=0.001)
    # the cropped plan is not empty: the walls inside the region are drawn, and it is clipped to it
    assert svg.count("<path") >= 2
    assert 'class="IfcWall"' in svg
    wall = next(w for w in b._model.by_type("IfcWall")
                if ifcopenshell.util.element.get_container(w).GlobalId == house and abs(_axis_y(w)) < 1e-6)
    assert f'ifc:guid="{wall.GlobalId}"' in svg  # the south wall, cut by the region
    assert ">Living room</text>" in svg  # the level's plan annotation inside the region
    assert "clipPath" in svg and "<polygon" in svg
    # generated once per model state
    assert not detail(guid)["stale"]
    assert call("generate_drawing", guid, "")["cached"]


def _axis_y(wall):
    return wall.ObjectPlacement.RelativePlacement.Location.Coordinates[1] / 1000.0


def test_a_detail_updates_its_name_scale_region_and_marker(house):
    guid = json.loads(D.create_detail(house, json.dumps(REGION), 20, "First"))["guid"]
    smaller = [[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]]
    r = json.loads(D.update_detail(guid, json.dumps({"name": "Door detail", "scale": 50, "region": smaller})))
    assert r["ok"], r
    info = json.loads(D.detail_info(guid))
    assert info["name"] == "Door detail" and info["scale"] == 50
    assert [[round(x, 6), round(y, 6)] for x, y in info["region"]] == smaller
    assert detail(guid)["name"] == "Door detail" and detail(guid)["scale"] == 50
    # the marker's bubble and leader follow the new region (bubble just above it)
    marker = markers(house, guid)[0]
    at = ifcopenshell.util.placement.get_local_placement(marker.ObjectPlacement)
    assert at[0][3] / 1000.0 == pytest.approx(2.0, abs=1e-6)  # centred over the 0..4 m region
    assert at[1][3] / 1000.0 == pytest.approx(4.5, abs=1e-6)  # 1.5 m above its top edge
    # the drawing follows: 4 m x 3 m at 1:50
    width, height, box = svg_header(call("generate_drawing", guid, "")["svg"])
    assert width == pytest.approx(4.0 * 1000 / 50, abs=0.02)
    assert height == pytest.approx(3.0 * 1000 / 50, abs=0.02)
    assert box[:2] == [pytest.approx(0.0, abs=0.001), pytest.approx(-3.0, abs=0.001)]
    assert call("undo")["ok"]  # one undo step: the whole update
    assert json.loads(D.detail_info(guid))["scale"] == 20
    assert detail(guid)["name"] == "First"


def test_a_detail_can_be_deleted_with_its_marker(house):
    guid = json.loads(D.create_detail(house, json.dumps(REGION)))["guid"]
    assert len(markers(house, guid)) == 1
    r = json.loads(D.delete_detail(guid))
    assert r["ok"], r
    assert detail(guid) is None
    assert markers(house, guid) == []
    assert json.loads(D.detail_info(guid))["ok"] is False
    # deleting the drawing through the generic path leaves no orphan marker either
    guid = json.loads(D.create_detail(house, json.dumps(REGION)))["guid"]
    assert call("delete_drawing", guid)["ok"]
    assert markers(house, guid) == []


def test_a_detail_can_be_built_from_the_apps_mesh_geometry(house):
    """The app's plan path (mesh cut + projection, no hidden-line pass) frames a detail the same way."""
    guid = json.loads(D.create_detail(house, json.dumps([[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]]), 20))["guid"]
    geom = {"cut": [{"guid": guid, "loops": [[[0, 0], [4, 0], [4, 3], [0, 3]]]}],
            "proj": [{"guid": guid, "loops": [[[1, 1], [3, 1], [3, 2], [1, 2]]]}],
            "bounds": [0, 0, 4, 3]}
    r = call("generate_plan_drawing", guid, json.dumps(geom))
    assert r["ok"], r
    width, height, box = svg_header(r["svg"])
    assert width == pytest.approx(4.0 * 1000 / 20, abs=0.02)
    assert height == pytest.approx(3.0 * 1000 / 20, abs=0.02)
    assert box == [pytest.approx(0.0, abs=0.001), pytest.approx(-3.0, abs=0.001),
                   pytest.approx(4.0, abs=0.001), pytest.approx(3.0, abs=0.001)]
    assert r["svg"].count("<path") >= 2 and f'ifc:guid="{guid}"' in r["svg"]


def test_a_bad_region_or_scale_is_refused(house):
    for points in ("[]", "[[0, 0], [1, 0]]", "not json", "[[0, 0], [2, 2], [2, 0], [0, 2]]",  # crossing
                  "[[0, 0], [0, 0], [1, 0]]"):  # a repeated point
        r = json.loads(D.create_detail(house, points))
        assert r["ok"] is False, points
    assert json.loads(D.create_detail(house, json.dumps(REGION), "big"))["ok"] is False
    assert json.loads(D.create_detail(house, json.dumps(REGION), 0))["ok"] is False
    assert json.loads(D.create_detail("nope", json.dumps(REGION)))["ok"] is False
    assert json.loads(D.create_detail(house, json.dumps(REGION)))["ok"]  # the valid one still works
    guid = next(d["guid"] for d in call("drawings")["drawings"] if d["kind"] == "detail")
    assert json.loads(D.update_detail(guid, "{}"))["ok"]  # nothing to change is not an error
    assert json.loads(D.update_detail(guid, json.dumps({"region": [[0, 0], [1, 1]]})))["ok"] is False
    assert json.loads(D.update_detail(guid, json.dumps({"scale": -2})))["ok"] is False
    assert json.loads(D.update_detail(guid, "nope"))["ok"] is False
    assert json.loads(D.detail_info(guid))["ok"]

def test_a_detail_goes_on_a_sheet_at_its_own_scale(house):
    made = json.loads(D.create_detail(house, json.dumps(REGION), 20, "Stair detail"))
    assert made["ok"], made
    number = call("add_sheet", "A3", "Details")["number"]
    assert call("place_drawing", number, made["guid"], -1, -1, 100)["ok"]
    sheet = next(s for s in call("sheets")["sheets"] if s["number"] == number)
    view = next(v for v in sheet["views"] if v["drawing"] == made["guid"])
    assert view["scale"] == 20  # a detail defaults to its own 1:20
    assert view["w"] == pytest.approx((6.0 - (-1.0)) * 1000 / 20, rel=0.02)
    svg = call("sheet_svg", number)["svg"]
    assert "scale(50)" in svg  # 1000 mm per metre at 1:20
    assert 'class="kimbim-view"' in svg
