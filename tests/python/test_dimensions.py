# SPDX-License-Identifier: GPL-3.0-or-later
"""Owner feedback: editing a length in the Properties panel must change the element. A "Dimensions"
group (metres, computed from the model) is shown and edited like a property set."""
import json

import numpy as np
import pytest

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


def bbox(guid):
    _, verts, _, _ = b.mesh_elements(json.dumps([guid]))
    v = np.frombuffer(verts, dtype="<f4").reshape(-1, 3)
    return v.min(axis=0), v.max(axis=0)


@pytest.fixture
def model():
    assert call("new_project", "Dimensiones")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    t = next(x for x in call("wall_types")["types"] if x["name"] == "Exterior 300")["guid"]
    wall = call("create_wall", level, t, 0, 0, 5, 0, 3.0, "", "")["guid"]
    wall2 = call("create_wall", level, t, 0, 4, 6, 4, 2.5, "", "")["guid"]
    d = call("opening_types", "door")["types"][0]
    door = call("insert_opening", "door", wall, d["guid"], 2.5, 0.9, 2.1, 0.0)["guid"]
    col = call("create_column", level, call("column_types")["types"][0]["guid"], 8, 0, 3.0, 0.0)["guid"]
    beam = call("create_beam", level, call("beam_types")["types"][0]["guid"], 8, 0, 12, 0, 3.0)["guid"]
    return {"level": level, "wall": wall, "wall2": wall2, "door": door, "column": col, "beam": beam}


def dims(*guids):
    return call("properties_multi", g(*guids))["psets"]["Dimensions"]


def test_dimensions_are_shown_per_kind(model):
    w = dims(model["wall"])
    assert w["Length"]["value"] == pytest.approx(5.0) and w["Height"]["value"] == pytest.approx(3.0)
    assert w["Thickness"]["value"] == pytest.approx(0.3) and not w["Thickness"]["editable"]
    assert w["Length"]["editable"] and w["Length"]["source"] == "dimension"
    d = dims(model["door"])
    assert (d["Width"]["value"], d["Height"]["value"], d["Sill height"]["value"]) == pytest.approx((0.9, 2.1, 0.0))
    assert dims(model["column"])["Height"]["value"] == pytest.approx(3.0)
    assert dims(model["beam"])["Length"]["value"] == pytest.approx(4.0)
    both = dims(model["wall"], model["wall2"])
    assert both["Length"]["varies"] and both["Height"]["varies"] and not both["Thickness"]["varies"]


def test_editing_wall_length_and_height(model):
    r = call("set_dimension", g(model["wall"]), "Length", "6.5")
    assert r["ok"], r
    lo, hi = bbox(model["wall"])
    assert hi[0] - lo[0] == pytest.approx(6.5, abs=2e-3)
    assert call("set_dimension", g(model["wall"], model["wall2"]), "Height", "4")["ok"]
    assert bbox(model["wall2"])[1][2] == pytest.approx(4.0, abs=2e-3)
    assert dims(model["wall"])["Length"]["value"] == pytest.approx(6.5)
    call("undo")
    assert bbox(model["wall2"])[1][2] == pytest.approx(2.5, abs=2e-3)


def test_editing_door_column_and_beam(model):
    assert call("set_dimension", g(model["door"]), "Width", "1.1")["ok"]
    assert dims(model["door"])["Width"]["value"] == pytest.approx(1.1)
    assert call("set_dimension", g(model["column"]), "Height", "3,5")["ok"]  # Spanish decimal comma
    assert bbox(model["column"])[1][2] == pytest.approx(3.5, abs=2e-3)
    assert call("set_dimension", g(model["beam"]), "Length", "5")["ok"]
    lo, hi = bbox(model["beam"])
    assert hi[0] - lo[0] == pytest.approx(5.0, abs=2e-3) and lo[0] == pytest.approx(8.0, abs=2e-3)


def test_bad_dimension_values_change_nothing(model):
    steps = len(b._ids)
    for name, value in (("Length", "0"), ("Length", "abc"), ("Thickness", "0.5")):
        assert not call("set_dimension", g(model["wall"]), name, value)["ok"]
    assert not call("set_dimension", g(model["door"]), "Width", "9")["ok"]  # wider than the wall
    assert len(b._ids) == steps  # no undo step: nothing was applied
    assert dims(model["wall"])["Length"]["value"] == pytest.approx(5.0)
