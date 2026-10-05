# SPDX-License-Identifier: GPL-3.0-or-later
"""Modeling, Slice 6: columns, beams and grids."""
import json
import math

import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import numpy as np
import pytest

from kimcad import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def bbox(guid):
    _, verts, _ = b.mesh_elements(json.dumps([guid]))
    v = np.frombuffer(verts, dtype="<f4").reshape(-1, 3)
    return v.min(axis=0), v.max(axis=0)


def volume(guid):
    s = ifcopenshell.geom.settings()
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(s, b._model.by_guid(guid)).geometry)


@pytest.fixture
def project():
    assert call("new_project", "Estructura")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    level2 = call("add_storey", "Level 2", 3.0)["guid"]
    return {"level": level, "level2": level2}


def named(kind, name):
    return next(t for t in call(f"{kind}_types")["types"] if t["name"] == name)


def test_default_profile_types(project):
    steps = len(b._ids)
    cols = {t["name"]: (round(t["width"], 4), round(t["depth"], 4)) for t in call("column_types")["types"]}
    assert cols == {"Column 300x300": (0.3, 0.3), "Column D300": (0.3, 0.3)}
    beams = {t["name"]: (round(t["width"], 4), round(t["depth"], 4)) for t in call("beam_types")["types"]}
    assert beams == {"Beam 200x400": (0.2, 0.4)}
    assert len(b._ids) == steps  # library defaults are not user actions


def test_column_stands_on_its_level(project):
    t = named("column", "Column 300x300")
    r = call("create_column", project["level2"], t["guid"], 2.0, 1.0, 3.0, 0.0)
    assert r["ok"], r
    lo, hi = bbox(r["guid"])
    assert lo == pytest.approx([1.85, 0.85, 3.0], abs=1e-3) and hi == pytest.approx([2.15, 1.15, 6.0], abs=1e-3)
    c = b._model.by_guid(r["guid"])
    assert c.is_a("IfcColumn") and ifcopenshell.util.element.get_type(c).Name == "Column 300x300"
    assert ifcopenshell.util.element.get_container(c).GlobalId == project["level2"]
    assert r["geometry"] == {"changed": [r["guid"]], "removed": []}


def test_round_column_and_rotation(project):
    round_col = call("create_column", project["level"], named("column", "Column D300")["guid"], 0, 0, 3.0, 0.0)["guid"]
    assert volume(round_col) == pytest.approx(math.pi * 0.15 ** 2 * 3.0, rel=0.02)
    t = named("column", "Column 300x300")["guid"]
    turned = call("create_column", project["level"], t, 5, 5, 3.0, math.pi / 4)["guid"]
    lo, hi = bbox(turned)
    assert hi[0] - lo[0] == pytest.approx(0.3 * math.sqrt(2), abs=2e-3)  # a square turned 45 degrees


def test_beam_top_is_where_asked(project):
    t = named("beam", "Beam 200x400")["guid"]
    r = call("create_beam", project["level"], t, 0, 0, 5, 0, 3.0)
    assert r["ok"], r
    lo, hi = bbox(r["guid"])
    assert lo == pytest.approx([0, -0.1, 2.6], abs=1e-3) and hi == pytest.approx([5, 0.1, 3.0], abs=1e-3)
    diagonal = call("create_beam", project["level"], t, 0, 0, 3, 4, 3.0)["guid"]
    assert volume(diagonal) == pytest.approx(0.2 * 0.4 * 5.0, abs=1e-3)
    assert not call("create_beam", project["level"], t, 1, 1, 1, 1, 3.0)["ok"]  # no length


def test_grid_axes_get_tags_per_direction(project):
    tags = []
    for x1, y1, x2, y2 in ((0, -1, 0, 7), (5, -1, 5, 7), (-1, 0, 9, 0), (-1, 6, 9, 6)):
        r = call("add_grid_axis", project["level"], x1, y1, x2, y2, "")
        assert r["ok"], r
        tags.append(r["tag"])
    assert tags == ["A", "B", "1", "2"]
    assert call("add_grid_axis", project["level"], 9, -1, 9, 7, "Z")["tag"] == "Z"
    grid = call("snap_data", project["level"])["grid"]
    assert [g["tag"] for g in grid] == ["A", "B", "1", "2", "Z"]
    assert [grid[0][k] for k in ("x1", "y1", "x2", "y2")] == pytest.approx([0, -1, 0, 7], abs=1e-6)
    assert len(b._model.by_type("IfcGrid")) == 1
    call("undo")
    assert len(call("snap_data", project["level"])["grid"]) == 4


def test_grids_are_per_level(project):
    call("add_grid_axis", project["level"], 0, 0, 0, 5, "")
    r = call("add_grid_axis", project["level2"], 0, 0, 0, 5, "")
    assert r["tag"] == "A"
    assert len(b._model.by_type("IfcGrid")) == 2
