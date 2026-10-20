# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice 14 (M4): sections and elevations (D60 drawing definitions, D61 Archicad conventions)."""
import json
import math
import re
import sys
from pathlib import Path

import ifcopenshell.validate
import pytest

from kimbim import app_bridge as b

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import make_house  # noqa: E402


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


def drawings():
    return {d["name"]: d for d in call("drawings")["drawings"]}


def sections():
    return {n: d for n, d in drawings().items() if d["kind"] == "section"}


def drawing(guid):
    return next((d for d in call("drawings")["drawings"] if d["guid"] == guid), None)


def new_sections(before):
    return {n for n in sections() if n not in before}


def test_new_project_has_the_four_template_elevations():
    assert call("new_project", "Casa")["ok"]
    listed = {n: d for n, d in drawings().items() if d["kind"] == "elevation"}
    assert sorted(listed) == ["East Elevation", "North Elevation", "South Elevation", "West Elevation"]
    assert all(d["kind"] == "elevation" and d["auto"] and d["depth"] is None for d in listed.values())
    assert drawings()["Level 1 Floor Plan"]["kind"] == "plan"  # Archicad: every story has a floor plan
    assert call("state")["dirty"] is False and call("state")["can_undo"] is False  # part of the new project


def test_opening_a_file_adds_no_drawings(tmp_path):
    assert call("new_project", "Casa")["ok"]
    for d in call("drawings")["drawings"]:
        assert call("delete_drawing", d["guid"])["ok"]
    assert call("save", str(tmp_path / "plain.ifc"))["ok"]
    assert call("open_model", str(tmp_path / "plain.ifc"))["ok"]
    assert call("drawings")["drawings"] == []


def test_section_from_two_points_and_a_look_side(house):
    before = set(sections())  # the house already has its M4 section
    r = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, -1)  # look north, infinite depth
    assert r["ok"], r
    d = drawing(r["guid"])
    assert d["guid"] == r["guid"] and d["kind"] == "section" and d["depth"] is None and d["stale"]
    assert call("state")["can_undo"]
    entity = b._model.by_guid(r["guid"])
    assert entity.is_a("IfcAnnotation") and entity.ObjectType == "DRAWING"
    assert entity.Representation.Representations[0].Items[0].TreeRootExpression.is_a("IfcBlock")
    assert r["guid"] not in [a["guid"] for a in call("annotations", house)["annotations"]]  # not a plan annotation
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    assert logger.statements == []
    assert call("undo")["ok"] and new_sections(before) == set()


def test_section_shows_cut_walls_and_slabs_filled_and_the_rest_in_projection(house):
    guid = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, -1)["guid"]
    r = call("generate_drawing", guid, "")
    assert r["ok"], r
    svg = r["svg"]
    assert 'class="section"' in svg
    cut = re.findall(r'class="(IfcWall|IfcSlab)"', svg)
    assert "IfcWall" in cut and "IfcSlab" in cut
    assert 'class="projection' in svg
    assert "IfcOpeningElement" not in svg  # openings are voids, not cut fill
    w, h = (float(v) for v in re.search(r'width="([\d.]+)mm" height="([\d.]+)mm"', svg).groups())
    assert 100 < w < 140 and 60 < h < 110  # 1:100, cropped to the 10 m x ~7 m house section
    assert not drawing(guid)["stale"]
    again = call("generate_drawing", guid, "")
    assert again["cached"] and again["svg"] == svg


def test_editing_a_wall_makes_drawings_stale_and_regenerating_shows_it(house):
    guid = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, -1)["guid"]
    before = call("generate_drawing", guid, "")["svg"]
    wall = next(w for w in b._model.by_type("IfcWall") if abs(_x(w) - 10.0) < 1e-6)  # the east wall
    assert call("move_elements", json.dumps([wall.GlobalId]), 1.0, 0.0, 0.0)["ok"]
    assert drawing(guid)["stale"]
    after = call("generate_drawing", guid, "")
    assert not after["cached"] and after["svg"] != before
    assert call("undo")["ok"]
    assert call("generate_drawing", guid, "")["svg"] == before  # back to the cached state


def _x(e):
    return e.ObjectPlacement.RelativePlacement.Location.Coordinates[0] / 1000.0


def test_template_elevations_follow_the_model_and_show_the_facade():
    assert call("new_project", "Casa")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    ext = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")["guid"]
    assert call("create_wall", l1, ext, 20, 20, 30, 20, 3.0, "", "")["ok"]  # far from the template markers
    south = drawings()["South Elevation"]
    r = call("generate_drawing", south["guid"], "")
    assert r["ok"], r
    projection = r["svg"].split('class="projection IfcWall"', 1)[1]  # D73: projection grouped per element
    assert projection.count("<path") >= 1  # the wall's face
    w = float(re.search(r'width="([\d.]+)mm"', r["svg"]).group(1))
    assert 95 < w < 125  # the 10 m wall at 1:100, cropped


def test_depth_and_delete(house):
    guid = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, 0.5)["guid"]
    assert drawing(guid)["depth"] == 0.5
    assert call("set_drawing_depth", guid, -1)["ok"] and drawing(guid)["depth"] is None
    assert call("rename_drawing", guid, "A-A")["ok"] and "A-A" in drawings()
    n = len(b._model.by_type("IfcShapeRepresentation"))
    psets = len([p for p in b._model.by_type("IfcPropertySet") if p.Name in ("KIMBIM_Drawing", "EPset_Drawing")])
    assert call("delete_drawing", guid)["ok"] and drawing(guid) is None
    assert len(b._model.by_type("IfcShapeRepresentation")) == n - 1
    assert len([p for p in b._model.by_type("IfcPropertySet") if p.Name in ("KIMBIM_Drawing", "EPset_Drawing")]) == psets - 2
    assert call("undo")["ok"] and "A-A" in drawings()


def test_bad_section_input_is_refused(house):
    assert not call("create_section", 1, 1, 1, 1, 2, 2, -1)["ok"]  # zero length
    assert not call("create_section", 0, 0, 1, 0, "x", 1, -1)["ok"]
    assert not call("generate_drawing", "nope", "")["ok"]


def test_drawings_are_not_meshed_in_3d():
    assert call("new_project", "Casa")["ok"]
    guids = [d["guid"] for d in call("drawings")["drawings"]]
    assert b.mesh_elements(json.dumps(guids)) is None


def test_moving_or_rotating_a_marker_moves_the_drawing_and_keeps_it_there(house):
    guid = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, -1)["guid"]
    assert call("move_elements", json.dumps([guid]), 0.0, -2.0, 0.0)["ok"]
    d = drawing(guid)
    assert d["points"] == [[-1.0, 2.5], [11.0, 2.5]] and d["look"][1] > 2.5  # still looks north
    assert call("generate_drawing", guid, "")["ok"]  # refitting the infinite range keeps the move
    assert drawing(guid)["points"] == [[-1.0, 2.5], [11.0, 2.5]]
    assert call("rotate_elements", json.dumps([guid]), 5.0, 2.5, math.pi / 2)["ok"]
    d = drawing(guid)
    assert [[round(c, 6) for c in p] for p in d["points"]] == [[5.0, -3.5], [5.0, 8.5]] and d["look"][0] < 5.0


def test_a_moved_template_elevation_stays_where_it_was_put():
    assert call("new_project", "Casa")["ok"]
    south = drawings()["South Elevation"]
    assert call("move_elements", json.dumps([south["guid"]]), 0.0, -5.0, 0.0)["ok"]
    moved = drawings()["South Elevation"]
    assert not moved["auto"]
    assert call("generate_drawing", south["guid"], "")["ok"]
    assert drawings()["South Elevation"]["points"] == moved["points"]


def test_create_elevations_adds_the_missing_ones_to_an_opened_file(tmp_path):
    assert call("new_project", "Casa")["ok"]
    south = drawings()["South Elevation"]["guid"]
    assert call("delete_drawing", south)["ok"]
    r = call("create_elevations")
    assert r["ok"] and r["created"] == 1
    assert sorted(n for n in drawings() if "Elevation" in n) == ["East Elevation", "North Elevation", "South Elevation", "West Elevation"]
    assert call("create_elevations")["created"] == 0  # nothing missing
    assert call("undo")["ok"] and "South Elevation" not in drawings()  # one step; the no-op made none



# ---------------------------------------------------------------- Slice 15: floor plans

def test_every_level_gets_a_floor_plan_and_an_opened_file_can_add_them(tmp_path):
    assert call("new_project", "Casa")["ok"]
    assert call("add_storey", "Level 2", 3.0)["ok"]
    plans = [d["name"] for d in call("drawings")["drawings"] if d["kind"] == "plan"]
    assert plans == ["Level 1 Floor Plan", "Level 2 Floor Plan"]  # ordered by height, listed first
    assert call("undo")["ok"]
    assert [d["name"] for d in call("drawings")["drawings"] if d["kind"] == "plan"] == ["Level 1 Floor Plan"]
    for d in call("drawings")["drawings"]:
        assert call("delete_drawing", d["guid"])["ok"]
    assert call("create_drawings")["created"] == 5  # the plan and the four elevations
    assert call("create_drawings")["created"] == 0


def test_house_floor_plan_reads_like_a_permit_plan(house):
    assert call("create_drawings")["ok"]
    plan = drawings()["Level 1 Floor Plan"]
    r = call("generate_drawing", plan["guid"], "")
    assert r["ok"], r
    svg = r["svg"]
    assert 'class="IfcWall"' in svg and 'class="section"' in svg  # walls cut (poché)
    assert svg.count('class="swing"') >= 1  # the front door swings
    overlay = svg.split('class="kimbim-overlay"', 1)[1]
    assert ">Living room</text>" in overlay  # the plan's text label
    assert ">10.00</text>" in overlay  # the dimension, measured
    assert ">South Elevation</text>" in overlay and ">North Elevation</text>" in overlay  # markers
    upper = call("generate_drawing", drawings()["Level 2 Floor Plan"]["guid"], "")["svg"]
    assert ">Living room</text>" not in upper  # annotations belong to their level


def test_drawings_are_styled_by_the_purpose(house):
    from kimbim import settings as s
    guid = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, -1)["guid"]
    working = call("generate_drawing", guid, "")["svg"]
    assert 'stroke="#5a3a22"' in working  # Working: walls cut, dark brown
    assert call("set_purpose", "Permit")["ok"]
    permit = call("generate_drawing", guid, "")["svg"]
    assert 'stroke="#5a3a22"' not in permit and 'stroke="#000000"' in permit
    assert call("set_purpose", "Working")["ok"]
    s.load(None)


def test_hidden_kinds_are_left_out_of_drawings(house):
    from kimbim import settings as s
    guid = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, -1)["guid"]
    assert "IfcWall" in call("generate_drawing", guid, "")["svg"]
    vis = {**call("graphics_tables")["tables"]["visibility_sets"], "No walls": {"hidden_kinds": ["walls"], "rules": []}}
    purposes = {**call("graphics_tables")["tables"]["purposes"],
                "NW": {"pen_set": "Working", "visibility": "No walls", "overrides": "None", "layers": None}}
    assert call("set_graphics", json.dumps({"visibility_sets": vis, "purposes": purposes}))["ok"]
    assert call("set_purpose", "NW")["ok"]
    assert "IfcWall" not in call("generate_drawing", guid, "")["svg"]
    s.load(None)


def test_plan_drawing_from_mesh_geometry():
    """The plan is built from the app's meshes (cut + projection loops), not the serializer's slow
    hidden-line pass: the base SVG carries the elements and the plane/matrix3 the overlays need."""
    assert call("new_project", "Casa")["ok"]
    plan = drawings()["Level 1 Floor Plan"]
    geom = {"cut": [{"guid": plan["guid"], "loops": [[[0, 0], [4, 0], [4, 3], [0, 3]]]}],
            "proj": [{"guid": plan["guid"], "loops": [[[5, 0], [7, 0], [7, 2], [5, 2]]]}],
            "bounds": [0, 0, 7, 3]}
    r = call("generate_plan_drawing", plan["guid"], json.dumps(geom))
    assert r["ok"] and r["svg"].count("<path") >= 2
    assert f'ifc:guid="{plan["guid"]}"' in r["svg"]
    assert 'class="section"' in r["svg"] and "ifc:matrix3" in r["svg"]
    # the second call is served from the cache (the geometry is unchanged)
    assert call("generate_plan_drawing", plan["guid"], json.dumps(geom))["ok"]


def test_section_drawing_from_mesh_geometry():
    """A section is built from the app's meshes (projected edges + the cut), not the serializer."""
    assert call("new_project", "Casa")["ok"]
    guid = call("create_section", "0", "0", "5", "0", "0", "5", "-1")["guid"]
    geom = {"proj": [{"guid": guid, "lines": [[0, 0, 3, 0], [3, 0, 3, 2]]}],
            "cut": [{"guid": guid, "loops": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}],
            "view": [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1]}
    r = call("generate_view_drawing", guid, json.dumps(geom))
    assert r["ok"] and r["svg"].count("<path") >= 2
    assert f'ifc:guid="{guid}"' in r["svg"] and "ifc:matrix3" in r["svg"]


def test_drawing_bounds_lists_the_buildings_elements(house):
    """The app frames sections and elevations on the meshes of the building's elements, so the bounds
    carry their GlobalIds: the walls, the roof and the D86 tree inside the building, not the drawing
    markers. Cached per model state (the app asks for every drawing it generates)."""
    from kimbim import drawings as D

    r = call("drawing_bounds")
    assert r["ok"] and len(r["lo"]) == 3 and len(r["hi"]) == 3
    classes = {b._model.by_guid(g).is_a() for g in r["guids"]}
    assert {"IfcWall", "IfcRoof", "IfcSlab", "IfcGeographicElement"} <= classes
    assert "IfcAnnotation" not in classes
    assert D._building_cache, "cached for this model state"
    assert call("drawing_bounds")["guids"] == r["guids"]


def test_a_plan_view_sees_a_depth_below_the_level(house):
    from kimbim import drawgen, settings as S

    assert S.DEFAULTS["view_depth"] == 0.5 and S.DEFAULTS["view_depth_levels"] == {}
    plan = drawings()["Level 1 Floor Plan"]
    assert plan["view_depth"] == 0.5  # the project default
    # A view overrides it, then falls back to its level's override, then to the project's.
    assert call("set_view_depth", plan["guid"], 1.3)["ok"]
    assert drawing(plan["guid"])["view_depth"] == 1.3
    assert call("set_project_settings", json.dumps({"view_depth_levels": {house: 0.9}}))["ok"]
    assert call("set_view_depth", plan["guid"], -1)["ok"]
    assert drawing(plan["guid"])["view_depth"] == 0.9
    assert call("set_project_settings", json.dumps({"view_depth": 0.7}))["ok"]
    assert call("set_project_settings", json.dumps({"view_depth_levels": {}}))["ok"]
    assert drawing(plan["guid"])["view_depth"] == 0.7
    # The depth reaches below the level in the camera (cut above + depth below).
    storey = b._model.by_guid(house)
    _m, (_w, _h, depth) = drawgen.plan_camera(storey, 1.2, drawgen.EMPTY_BOUNDS, 0.7)
    assert depth == pytest.approx(1.2 + 0.7)


def test_an_element_can_override_the_view_depth_below(house):
    from kimbim import drawgen

    plan = drawings()["Level 1 Floor Plan"]
    guid = call("generate_drawing", plan["guid"], "")["svg"]
    wall = b._model.by_type("IfcWall")[0]
    assert f'ifc:guid="{wall.GlobalId}"' in guid
    assert call("set_element_view_depth", json.dumps([wall.GlobalId]), 1.4)["ok"]
    assert drawgen.element_view_depth(wall) == 1.4
    assert call("set_element_view_depth", json.dumps([wall.GlobalId]), -1)["ok"]
    assert drawgen.element_view_depth(wall) is None
    assert not call("set_element_view_depth", json.dumps([wall.GlobalId]), "deep")["ok"]
