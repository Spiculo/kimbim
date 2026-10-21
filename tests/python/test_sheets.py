# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice 16 (M4 exit): project info, sheets with a title block, drawings placed at scale, SVG export."""
import json
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
    from kimbim import drawings as D

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
    assert svg.count('class="kimbim-view"') == 3
    for text in ("KimBim two-storey house", "A01", "1:100", "Level 1 Floor Plan", "Section 1", "South Elevation"):
        assert f">{text}<" in svg, text
    out = tmp_path / "A01.svg"
    assert call("export_sheet_svg", "A01", str(out))["ok"] and out.read_text(encoding="utf-8") == svg


def test_sheets_work_on_ifc2x3_models(tmp_path):
    """IFC2X3 names the sheet number DocumentId and the drawing link ItemReference, and its references
    have no Description: adding an A1 sheet to the Clinic (IFC2X3) failed outright."""
    from kimbim.testing import _reset_owner, build_model
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
    leg = call("place_legend", "B01")  # D74: legends use the same IFC2X3 fallback as placed drawings
    assert leg["ok"], leg
    assert call("move_legend", "B01", leg["id"], 200, 100)["ok"]
    assert [(x["x"], x["y"]) for x in next(s for s in call("sheets")["sheets"] if s["number"] == "B01")["legends"]] == [(200, 100)]
    assert 'class="kimbim-legend"' in call("sheet_svg", "B01")["svg"]
    assert call("remove_legend", "B01", leg["id"])["ok"]
    assert call("remove_placed", "B01", plan)["ok"]
    assert call("delete_sheet", "B01")["ok"] and call("sheets")["sheets"] == []


def test_sheet_weights_do_not_scale(house):
    """A pen prints at its weight whatever the scale: the sheet divides weights by its scaling (D73)."""
    from kimbim import settings as s
    number = call("add_sheet", "A1", "Weights")["number"]
    assert call("place_drawing", number, drawing("Level 1 Floor Plan"), -1, -1, 50)["ok"]
    svg = call("sheet_svg", number)["svg"]
    view = svg.split('class="kimbim-view"', 1)[1]
    widths = {float(w) for w in re.findall(r'<g [^>]*class="IfcWall"[^>]*stroke-width="([\d.]+)"', view)}
    assert widths == {0.25}  # 0.50 mm pen / k (k = 100/50 = 2): prints 0.50 mm on paper
    assert 'stroke="#5a3a22"' in svg  # the current purpose (Working)
    assert call("set_sheet_purpose", number, "Permit")["ok"]
    assert 'stroke="#5a3a22"' not in call("sheet_svg", number)["svg"]
    assert call("set_sheet_purpose", number, "")["ok"]
    assert not call("set_sheet_purpose", number, "Nope")["ok"]
    s.load(None)


# ---------------------------------------------------------------- legends (D74)

def _level1_wall():
    import ifcopenshell.util.element as U
    return next(w for w in b._model.by_type("IfcWall") if (U.get_container(w).Name or "") == "Level 1")


def _sheet_of(number):
    return next(s_ for s_ in call("sheets")["sheets"] if s_["number"] == number)


def test_a_legend_is_placed_moved_drawn_and_removed(house):
    wall = _level1_wall()
    assert call("set_status", json.dumps([wall.GlobalId]), "demolish")["ok"]
    number = call("add_sheet", "A3", "Demolition")["number"]
    assert call("place_drawing", number, drawing("Level 1 Floor Plan"), 10, 10, 100)["ok"]
    assert call("set_sheet_purpose", number, "Demolition")["ok"]
    r = call("place_legend", number)
    assert r["ok"], r
    (leg,) = _sheet_of(number)["legends"]
    assert leg["id"] == r["id"] and leg["w"] > 0 and leg["h"] > 0
    assert call("move_legend", number, leg["id"], 300, 200)["ok"]
    assert (_sheet_of(number)["legends"][0]["x"], _sheet_of(number)["legends"][0]["y"]) == (300, 200)
    svg = call("sheet_svg", number)["svg"]
    assert 'class="kimbim-legend" transform="translate(300.000 200.000)"' in svg and "To be demolished" in svg
    assert call("undo")["ok"]  # the move is one step
    assert _sheet_of(number)["legends"][0]["x"] == leg["x"]
    assert call("remove_legend", number, leg["id"])["ok"]
    assert _sheet_of(number)["legends"] == []
    assert not call("remove_legend", number, leg["id"])["ok"]


def test_the_legend_only_lists_what_the_sheet_shows(house):
    # D91: "used" lists only the rules the sheet's drawings use; the default "auto" lists them all.
    assert call("set_project_settings", json.dumps({"legend_mode": "used"}))["ok"]
    number = call("add_sheet", "A3", "Demolition")["number"]  # nothing demolished
    assert call("place_drawing", number, drawing("Level 1 Floor Plan"), 10, 10, 100)["ok"]
    assert call("set_sheet_purpose", number, "Demolition")["ok"]
    assert call("place_legend", number)["ok"]
    svg = call("sheet_svg", number)["svg"]
    assert "To be demolished" not in svg and "Everything is drawn with its element styles" in svg


def test_the_legend_lists_every_rule_when_it_fits(house):
    number = call("add_sheet", "A3", "Demolition")["number"]  # nothing demolished
    assert call("place_drawing", number, drawing("Level 1 Floor Plan"), 10, 10, 100)["ok"]
    assert call("set_sheet_purpose", number, "Demolition")["ok"]
    assert call("place_legend", number)["ok"]
    svg = call("sheet_svg", number)["svg"]  # the default "auto": the full legend fits on an A3
    assert "To be demolished" in svg and "Temporary" in svg and "Auxiliary" in svg


def test_a_sheet_text_can_be_placed_moved_edited_and_removed(house):
    number = call("add_sheet", "A3", "Working")["number"]
    r = call("place_sheet_symbol", number, "text", json.dumps({"text": "Hello", "x": 20, "y": 30}))
    assert r["ok"], r
    (sym,) = _sheet_of(number)["symbols"]
    assert sym["kind"] == "text" and sym["text"] == "Hello" and (sym["x"], sym["y"]) == (20, 30)
    assert "Hello" in call("sheet_svg", number)["svg"]
    assert call("set_sheet_symbol", number, sym["id"], json.dumps({"text": "Bye", "x": 40}))["ok"]
    svg = call("sheet_svg", number)["svg"]
    assert "Bye" in svg and "Hello" not in svg  # D91: sheet texts are editable
    assert call("move_sheet_symbol", number, sym["id"], 10, 10)["ok"]
    assert _sheet_of(number)["symbols"][0]["x"] == 10
    assert call("remove_sheet_symbol", number, sym["id"])["ok"]
    assert _sheet_of(number)["symbols"] == []
    assert not call("place_sheet_symbol", number, "text", json.dumps({"text": "  "}))["ok"]


def test_legends_are_not_drawings(house):
    number = call("add_sheet", "A3", "L")["number"]
    assert call("place_legend", number)["ok"]
    sheet = _sheet_of(number)
    assert sheet["views"] == [] and len(sheet["legends"]) == 1


def test_the_title_block_is_moved_and_its_fields_edited(house):
    number = call("add_sheet", "A3", "Plans")["number"]
    tb = _sheet_of(number)["title_block"]
    assert (tb["w"], tb["h"]) == (180, 50)
    assert (tb["x"], tb["y"]) == (420 - 10 - 180, 297 - 10 - 50)
    assert tb["fields"]["title"] == "Plans" and tb["fields"]["sheet_number"] == number
    assert call("move_title_block", number, 30, 40)["ok"]
    assert (_sheet_of(number)["title_block"]["x"], _sheet_of(number)["title_block"]["y"]) == (30, 40)
    fields = {"project": "Casa Lecot", "project_number": "2026-014", "client": "Familia Lecot",
              "title": "Planta baja", "date": "2026-10-20", "issued": "Estudio"}
    assert call("set_title_block", number, json.dumps({"fields": fields}))["ok"]
    svg = call("sheet_svg", number)["svg"]
    for value in fields.values():
        assert f">{value}<" in svg, value
    assert 'class="kimbim-title-block"' in svg
    # Saved with the sheet, not with the project info.
    assert "Casa Lecot" not in json.dumps(call("project_info"))
    assert call("undo")["ok"]
    assert "Planta baja" not in call("sheet_svg", number)["svg"]
    # A field equal to the derived default is not an override, so project info changes still show.
    assert call("set_title_block", number, json.dumps({"fields": {"title": "Plans"}}))["ok"]
    assert call("set_title_block", number, json.dumps({"fields": {"title": ""}}))["ok"]
    assert ">Plans<" not in call("sheet_svg", number)["svg"]


def test_a_title_block_never_overlaps_a_drawing_placed_on_a_free_spot(house):
    number = call("add_sheet", "A3", "Full")["number"]
    assert call("move_title_block", number, 0, 0)["ok"]
    spot = call("place_drawing", number, drawing("Level 1 Floor Plan"), -1, -1, 100)
    assert spot["ok"], spot
    (view,) = _sheet_of(number)["views"]
    tb = _sheet_of(number)["title_block"]
    assert not (view["x"] < tb["x"] + tb["w"] and tb["x"] < view["x"] + view["w"]
                and view["y"] < tb["y"] + tb["h"] and tb["y"] < view["y"] + view["h"])
