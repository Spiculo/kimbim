# SPDX-License-Identifier: GPL-3.0-or-later
"""Georeferencing (doc 14 §1): survey point, rotation, projected CRS and true north."""
import json

import ifcopenshell
import pytest

from kimbim import app_bridge as b
from kimbim import settings
from kimbim.testing import build_model


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def model():
    f = build_model()
    b._model = f
    settings.load(None)
    yield f
    b._model = None
    settings.load(None)


def test_set_read_update_and_clear(model, tmp_path):
    assert call("georef_state")["georeferenced"] is False

    r = call("set_georeferencing", json.dumps({
        "eastings": 500000.0, "northings": 6100000.0, "height": 35.0, "rotation": 30.0,
        "scale": 1.0, "crs_name": "EPSG:32721", "geodetic_datum": "WGS 84",
        "map_projection": "UTM", "map_zone": "21S", "true_north": 15.0}))
    assert r["ok"], r
    state = call("georef_state")
    assert state["georeferenced"] is True
    assert (state["eastings"], state["northings"], state["height"]) == (500000.0, 6100000.0, 35.0)
    assert state["rotation"] == pytest.approx(30.0)
    assert state["scale"] == pytest.approx(1.0)
    assert state["true_north"] == pytest.approx(15.0)
    assert state["crs"]["name"] == "EPSG:32721"
    assert state["crs"]["map_zone"] == "21S"
    assert model.by_type("IfcMapConversion") and model.by_type("IfcProjectedCRS")

    # A later edit changes only what it names.
    assert call("set_georeferencing", json.dumps({"height": 40.0}))["ok"]
    state = call("georef_state")
    assert state["height"] == pytest.approx(40.0)
    assert state["eastings"] == pytest.approx(500000.0)
    assert state["rotation"] == pytest.approx(30.0)

    # The values survive a save and reopen.
    path = tmp_path / "georef.ifc"
    model.write(path)
    b._model = ifcopenshell.open(path)
    state = call("georef_state")
    assert state["eastings"] == pytest.approx(500000.0)
    assert state["crs"]["name"] == "EPSG:32721"

    cleared = call("clear_georeferencing")
    assert cleared["ok"] and cleared["removed"] == 1
    assert not b._model.by_type("IfcMapConversion")
    assert call("georef_state")["georeferenced"] is False


def test_bad_input_is_reported(model):
    assert call("set_georeferencing", "{not json")["ok"] is False
    assert call("set_georeferencing", json.dumps({"eastings": "far away"}))["ok"] is False
    assert call("georef_state")["ok"] is True
