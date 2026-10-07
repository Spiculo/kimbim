# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice 16 (M4 exit): project info, sheets with a title block, drawings placed at scale, SVG export."""
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


def drawing(name):
    return next(d["guid"] for d in call("drawings")["drawings"] if d["name"] == name)


def test_project_info_lives_in_ifc_fields():
    assert call("new_project", "Casa")["ok"]
    info = {"number": "2026-014", "name": "Casa Lecot", "client": "Familia Lecot",
            "address": "Av. Siempreviva 742, Montevideo"}
    assert call("set_project_info", json.dumps(info))["ok"]
    assert call("project_info")["number"] == "2026-014"
    assert call("project_info")["client"] == "Familia Lecot"
    project = b._model.by_type("IfcProject")[0]
    assert project.Name == "2026-014" and project.LongName == "Casa Lecot"
    assert b._model.by_type("IfcBuilding")[0].BuildingAddress.AddressLines[0] == "Av. Siempreviva 742, Montevideo"
    actor = next(a for a in b._model.by_type("IfcActor"))
    assert actor.TheActor.Name == "Familia Lecot"
    assert call("undo")["ok"] and call("project_info")["client"] == ""


def test_sheets_are_numbered_and_hold_drawings_at_scale(house):
    a1 = call("add_sheet", "A1", "Plans")
    a3 = call("add_sheet", "A3", "Details")
    assert a1["ok"] and a1["number"] == "A02" and a3["number"] == "A03"  # after the house's A01
    plan = drawing("Level 2 Floor Plan")
    r = call("place_drawing", "A02", plan, -1, -1, 100)
    assert r["ok"], r

    def view_of(number):
        return next(s for s in call("sheets")["sheets"] if s["number"] == number)["views"][0]

    sheet = next(s for s in call("sheets")["sheets"] if s["number"] == "A02")
    assert sheet["paper"] == "A1" and (sheet["width"], sheet["height"]) == (841, 594)
    view = view_of("A02")
    assert view["drawing"] == plan and view["scale"] == 100 and view["w"] > 50
    assert call("move_placed", "A02", plan, 40, 50)["ok"]
    view = view_of("A02")
    assert (view["x"], view["y"]) == (40, 50)
    assert call("set_placed_scale", "A02", plan, 50)["ok"]  # 1:50 doubles its size on the sheet
    assert abs(view_of("A02")["w"] - 2 * view["w"]) < 0.5
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    assert logger.statements == []
    assert call("delete_sheet", "A03")["ok"]
    assert [s["number"] for s in call("sheets")["sheets"]] == ["A01", "A02"]
    assert call("undo")["ok"] and len(call("sheets")["sheets"]) == 3


def test_m4_exit_sheet_has_plan_section_elevation_and_title_block(house, tmp_path):
    # make_house builds the M4 exit sheet: the ground floor plan, a section and the south elevation.
    sheet = next(s for s in call("sheets")["sheets"] if s["number"] == "A01")
    names = sorted(v["name"] for v in sheet["views"])
    assert names == ["Level 1 Floor Plan", "Section 1", "South Elevation"]
    r = call("sheet_svg", "A01")
    assert r["ok"], r
    svg = r["svg"]
    assert re.search(r'<svg[^>]*width="420mm" height="297mm" viewBox="0 0 420 297"', svg)  # A3
    assert svg.count('class="kimcad-view"') == 3
    for text in ("KIMCAD two-storey house", "A01", "1:100", "Level 1 Floor Plan", "Section 1", "South Elevation"):
        assert f">{text}<" in svg, text
    out = tmp_path / "A01.svg"
    assert call("export_sheet_svg", "A01", str(out))["ok"] and out.read_text(encoding="utf-8") == svg
