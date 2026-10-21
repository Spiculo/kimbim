# SPDX-License-Identifier: GPL-3.0-or-later
"""Worksheets (D98): 2D drawing spaces with their own drawing, kept away from the building."""
import json

import pytest

from kimbim import app_bridge as b
from kimbim import drawgen as G


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def project():
    assert call("new_project", "Casa")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    t = call("wall_types")["types"][0]["guid"]
    assert call("create_wall", level, t, 0, 0, 5, 0, 3.0)["ok"]
    return level


def test_a_worksheet_is_a_marked_storey_with_its_drawing(project):
    r = call("create_worksheet", "Details")
    assert r["ok"], r
    ws = call("worksheets")["worksheets"]
    assert [w["name"] for w in ws] == ["Details"] and ws[0]["drawing"] == r["drawing"]
    storeys = {s["name"]: s for s in call("storeys")["storeys"]}
    assert storeys["Details"]["worksheet"] and not storeys["Level 1"]["worksheet"]
    assert storeys["Details"]["elevation"] <= -1000
    assert "Details" in {d["name"] for d in call("drawings")["drawings"]}
    assert not call("create_worksheet", "Details")["ok"]  # names are unique
    assert not call("create_worksheet", "  ")["ok"]
    call("undo")
    assert call("worksheets")["worksheets"] == []


def test_worksheets_stay_out_of_levels_and_bounds(project):
    before = G.model_bounds(b._model)
    r = call("create_worksheet", "Sketch")
    assert call("add_drafting", r["guid"], "line", json.dumps([[0, 0], [100, 100]]))["ok"]
    after = G.model_bounds(b._model)
    assert [list(map(float, p)) for p in after] == [list(map(float, p)) for p in before]
    names = [l["name"] for l in call("levels_table")["levels"]]
    assert "Sketch" not in names
    assert call("create_worksheet", "Second")["elevation"] < r["elevation"]  # each its own place


def test_a_worksheet_drawing_shows_its_drafting_but_no_building_markers(project):
    r = call("create_worksheet", "Details")
    assert call("add_drafting", r["guid"], "line", json.dumps([[0, 0], [2, 1]]))["ok"]
    geometry = {"cut": [], "proj": [], "bounds": [0, 0, 2, 1]}
    svg = call("generate_plan_drawing", r["drawing"], json.dumps(geometry))["svg"]
    assert "kimbim-drafting" in svg
    assert "Elevation" not in svg and "North" not in svg


def _png(tmp_path, name="pic.png", w=4, h=2):
    from kimbim import underlays

    p = tmp_path / name
    p.write_bytes(underlays.png_bytes(w, h, [bytes([200, 30, 30] * w)] * h))
    return p


def test_pictures_on_a_worksheet_print_as_figures(project, tmp_path):
    import re

    ws = call("create_worksheet", "Pictures")
    pic = _png(tmp_path)
    r = call("add_underlay", str(pic), json.dumps({"storey": ws["guid"], "x": 1.0, "y": 2.0, "scale": 0.5}))
    assert r["ok"], r
    geometry = {"cut": [], "proj": [], "bounds": [0, 0, 3, 3]}
    svg = call("generate_plan_drawing", ws["drawing"], json.dumps(geometry))["svg"]
    m = re.search(r'<image data-figure="[^"]+" x="0" y="0" width="4" height="2"[^>]*transform="matrix\(([^)]*)\)"', svg)
    assert m, svg[:400]
    a, b2, c, d, e, f = (float(v) for v in m.group(1).split())
    assert a == pytest.approx(5.0) and d == pytest.approx(5.0)  # 0.5 m per pixel at 1:100 = 5 mm on paper
    assert b2 == pytest.approx(0) and c == pytest.approx(0)
    assert 'xmlns:xlink="http://www.w3.org/1999/xlink"' in svg
    # the same picture on a building level is a reference underlay: it does not print
    level = call("storeys")["storeys"][0]["guid"]
    plan = next(d for d in call("drawings")["drawings"] if d["name"] == "Level 1 Floor Plan")
    assert call("add_underlay", str(_png(tmp_path, "scan.png")), json.dumps({"storey": level}))["ok"]
    svg = call("generate_plan_drawing", plan["guid"], json.dumps(geometry))["svg"]
    assert "<image" not in svg


def test_png_writer_makes_a_valid_png(tmp_path):
    from kimbim import underlays

    p = _png(tmp_path, w=3, h=5)
    assert underlays._image_size(p)[:2] == (3, 5)
