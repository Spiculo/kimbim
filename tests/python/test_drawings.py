# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice 14 (M4): sections and elevations (D60 drawing definitions, D61 Archicad conventions)."""
import json
import re
import sys
from pathlib import Path

import ifcopenshell.validate
import pytest

from kimcad import app_bridge as b

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


def test_new_project_has_the_four_template_elevations():
    assert call("new_project", "Casa")["ok"]
    listed = drawings()
    assert sorted(listed) == ["East Elevation", "North Elevation", "South Elevation", "West Elevation"]
    assert all(d["kind"] == "elevation" and d["auto"] and d["depth"] is None for d in listed.values())
    assert call("state")["dirty"] is False and call("state")["can_undo"] is False  # part of the new project


def test_opening_a_file_adds_no_drawings(tmp_path):
    assert call("new_project", "Casa")["ok"]
    for d in call("drawings")["drawings"]:
        assert call("delete_drawing", d["guid"])["ok"]
    assert call("save", str(tmp_path / "plain.ifc"))["ok"]
    assert call("open_model", str(tmp_path / "plain.ifc"))["ok"]
    assert call("drawings")["drawings"] == []


def test_section_from_two_points_and_a_look_side(house):
    r = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, -1)  # look north, infinite depth
    assert r["ok"], r
    d = drawings()["Section 1"]
    assert d["guid"] == r["guid"] and d["kind"] == "section" and d["depth"] is None and d["stale"]
    assert call("state")["can_undo"]
    drawing = b._model.by_guid(r["guid"])
    assert drawing.is_a("IfcAnnotation") and drawing.ObjectType == "DRAWING"
    assert drawing.Representation.Representations[0].Items[0].TreeRootExpression.is_a("IfcBlock")
    assert r["guid"] not in [a["guid"] for a in call("annotations", house)["annotations"]]  # not a plan annotation
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    assert logger.statements == []
    assert call("undo")["ok"] and sections() == {}


def test_section_shows_cut_walls_and_slabs_filled_and_the_rest_in_projection(house):
    guid = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, -1)["guid"]
    r = call("generate_drawing", guid, "")
    assert r["ok"], r
    svg = r["svg"]
    assert '<g ifc:name="Section 1" class="section"' in svg or 'class="section"' in svg
    cut = re.findall(r'class="(IfcWall|IfcSlab)"', svg)
    assert "IfcWall" in cut and "IfcSlab" in cut
    assert 'class="projection"' in svg
    assert "IfcOpeningElement" not in svg  # openings are voids, not cut fill
    w, h = (float(v) for v in re.search(r'width="([\d.]+)mm" height="([\d.]+)mm"', svg).groups())
    assert 100 < w < 140 and 60 < h < 110  # 1:100, cropped to the 10 m x ~7 m house section
    assert not drawings()["Section 1"]["stale"]
    again = call("generate_drawing", guid, "")
    assert again["cached"] and again["svg"] == svg


def test_editing_a_wall_makes_drawings_stale_and_regenerating_shows_it(house):
    guid = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, -1)["guid"]
    before = call("generate_drawing", guid, "")["svg"]
    wall = next(w for w in b._model.by_type("IfcWall") if abs(_x(w) - 10.0) < 1e-6)  # the east wall
    assert call("move_elements", json.dumps([wall.GlobalId]), 1.0, 0.0, 0.0)["ok"]
    assert drawings()["Section 1"]["stale"]
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
    projection = r["svg"].split('class="projection"', 1)[1]
    assert projection.count("<path") >= 1  # the wall's face (projection is merged, without classes)
    w = float(re.search(r'width="([\d.]+)mm"', r["svg"]).group(1))
    assert 95 < w < 125  # the 10 m wall at 1:100, cropped


def test_depth_and_delete(house):
    guid = call("create_section", -1.0, 4.5, 11.0, 4.5, 5.0, 8.0, 0.5)["guid"]
    assert drawings()["Section 1"]["depth"] == 0.5
    assert call("set_drawing_depth", guid, -1)["ok"] and drawings()["Section 1"]["depth"] is None
    assert call("rename_drawing", guid, "A-A")["ok"] and "A-A" in drawings()
    n = len(b._model.by_type("IfcShapeRepresentation"))
    psets = len([p for p in b._model.by_type("IfcPropertySet") if p.Name in ("KIMCAD_Drawing", "EPset_Drawing")])
    assert call("delete_drawing", guid)["ok"] and sections() == {}
    assert len(b._model.by_type("IfcShapeRepresentation")) == n - 1
    assert len([p for p in b._model.by_type("IfcPropertySet") if p.Name in ("KIMCAD_Drawing", "EPset_Drawing")]) == psets - 2
    assert call("undo")["ok"] and "A-A" in drawings()


def test_bad_section_input_is_refused(house):
    assert not call("create_section", 1, 1, 1, 1, 2, 2, -1)["ok"]  # zero length
    assert not call("create_section", 0, 0, 1, 0, "x", 1, -1)["ok"]
    assert not call("generate_drawing", "nope", "")["ok"]


def test_drawings_are_not_meshed_in_3d():
    assert call("new_project", "Casa")["ok"]
    guids = [d["guid"] for d in call("drawings")["drawings"]]
    assert b.mesh_elements(json.dumps(guids)) is None
