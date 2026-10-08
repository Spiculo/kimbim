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


def test_changing_the_client_or_address_leaves_no_orphans():
    """Replacing the client removed the actor but left its organization and role behind (loose records
    that showed up in Compare); clearing the address left the postal address."""
    assert call("new_project", "Casa")["ok"]
    f = b._model
    before = {t: len(f.by_type(t)) for t in ("IfcOrganization", "IfcActorRole", "IfcPostalAddress")}
    for client in ("Ana", "Beto", ""):
        assert call("set_project_info", json.dumps({"client": client, "address": "Calle 1"}))["ok"]
    assert call("set_project_info", json.dumps({"address": ""}))["ok"]
    assert {t: len(f.by_type(t)) for t in before} == before
    assert call("project_info")["client"] == "" and call("project_info")["address"] == ""


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


def test_listing_sheets_after_an_edit_never_generates_drawings(house, monkeypatch):
    """sheets() runs on the GUI thread after every edit. It measured each placed drawing at the new model
    state by generating it (52 s for a real elevation); it now reuses the last size until the background
    generation of the sheet brings the new one."""
    from kimcad import drawings as D

    sizes = {v["drawing"]: (v["w"], v["h"]) for s in call("sheets")["sheets"] for v in s["views"]}
    assert sizes
    first = next(iter(sizes))
    assert call("move_placed", "A01", first, 40, 50)["ok"]  # an edit: a new model state

    def generate(*_):
        raise AssertionError("sheets() generated a drawing on the GUI thread")

    with monkeypatch.context() as m:
        m.setattr(D, "generate_drawing", generate)
        after = {v["drawing"]: (v["w"], v["h"]) for s in call("sheets")["sheets"] for v in s["views"]}
    assert after == sizes
    assert call("sheet_svg", "A01")["ok"]  # the background generation of the sheet...
    with monkeypatch.context() as m:
        m.setattr(D, "generate_drawing", generate)
        assert {v["drawing"] for s in call("sheets")["sheets"] for v in s["views"]} == set(sizes)  # ...is reused


def test_every_reference_on_a_composed_sheet_resolves(house):
    """The drawings' <defs> (the serializer's dimension arrow markers) were dropped while their style,
    which points at them with url(#...), was kept."""
    import re

    svg = call("sheet_svg", "A01")["svg"]
    refs = set(re.findall(r"url\(#([^)]+)\)", svg)) | set(re.findall(r'href="#([^"]+)"', svg))
    ids = re.findall(r' id="([^"]+)"', svg)
    assert refs <= set(ids), refs - set(ids)
    assert "<style" not in svg  # D73: drawings are styled by attributes (graphics.style_svg), not CSS


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


def test_sheets_work_on_ifc2x3_models(tmp_path):
    """IFC2X3 names the sheet number DocumentId and the drawing link ItemReference, and its references
    have no Description: adding an A1 sheet to the Clinic (IFC2X3) failed outright."""
    from kimcad.testing import _reset_owner, build_model
    path = tmp_path / "x3.ifc"
    try:
        build_model(schema="IFC2X3", walls=2).write(str(path))
        _check_ifc2x3_sheets(path)
    finally:
        _reset_owner()  # the IFC2X3 owner callbacks are global: later IFC4 models must not get them


def _check_ifc2x3_sheets(path):
    assert call("open_model", str(path))["ok"]
    storey = b._model.by_type("IfcBuildingStorey")[0].GlobalId
    assert call("create_plan", storey)["ok"]
    plan = drawing("Level 1 Floor Plan")
    a1 = call("add_sheet", "A1", "Plans")
    assert a1["ok"], a1
    r = call("place_drawing", a1["number"], plan, -1, -1, 100)
    assert r["ok"], r
    assert call("move_placed", a1["number"], plan, 40, 50)["ok"]
    sheet = next(s for s in call("sheets")["sheets"] if s["number"] == a1["number"])
    assert sheet["paper"] == "A1" and sheet["title"] == "Plans"
    assert [(v["drawing"], v["x"], v["y"]) for v in sheet["views"]] == [(plan, 40, 50)]
    assert call("edit_sheet", a1["number"], json.dumps({"number": "B01", "paper": "A3"}))["ok"]
    assert [s["number"] for s in call("sheets")["sheets"]] == ["B01"]
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    # (the test model's own CSG wall bodies break an IFC2X3 rule; only the sheet records matter here)
    assert [x for x in logger.statements if "Document" in str(x.get("instance"))] == []
    assert call("remove_placed", "B01", plan)["ok"]
    assert call("delete_sheet", "B01")["ok"] and call("sheets")["sheets"] == []


def test_sheet_weights_do_not_scale(house):
    """A pen prints at its weight whatever the scale: the sheet divides weights by its scaling (D73)."""
    from kimcad import settings as s
    number = call("add_sheet", "A1", "Weights")["number"]
    assert call("place_drawing", number, drawing("Level 1 Floor Plan"), -1, -1, 50)["ok"]
    svg = call("sheet_svg", number)["svg"]
    view = svg.split('class="kimcad-view"', 1)[1]
    widths = {float(w) for w in re.findall(r'<g [^>]*class="IfcWall"[^>]*stroke-width="([\d.]+)"', view)}
    assert widths == {0.25}  # 0.50 mm pen / k (k = 100/50 = 2): prints 0.50 mm on paper
    assert 'stroke="#5a3a22"' in svg  # the current purpose (Working)
    assert call("set_sheet_purpose", number, "Permit")["ok"]
    assert 'stroke="#5a3a22"' not in call("sheet_svg", number)["svg"]
    assert call("set_sheet_purpose", number, "")["ok"]
    assert not call("set_sheet_purpose", number, "Nope")["ok"]
    s.load(None)
