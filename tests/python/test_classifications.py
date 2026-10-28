# SPDX-License-Identifier: GPL-3.0-or-later
"""M2: classification systems, references and assignments (Uniclass, OmniClass, local)."""
import json

import pytest

from kimbim import app_bridge as b
from kimbim import settings
from kimbim.testing import build_model


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


@pytest.fixture
def model():
    f = build_model(walls=2)
    b._model = f
    settings.load(None)
    yield f
    b._model = None
    settings.load(None)


def walls(f):
    return [e.GlobalId for e in f.by_type("IfcWall")]


def test_systems_references_and_assignment(model):
    walls_ = walls(model)
    assert call("create_system", "Uniclass 2015")["ok"]
    assert call("create_system", "Uniclass 2015")["ok"] is False  # already there
    assert call("create_system", "Local", "Office", "2026")["ok"]

    ref = call("add_reference", "Uniclass 2015", "Pr_20_93_85", "Wall products")
    assert ref["ok"], ref
    systems = call("systems")["systems"]
    uniclass = next(s for s in systems if s["name"] == "Uniclass 2015")
    assert uniclass["source"] == "NBS" and uniclass["edition"] == "2015"
    assert [r["identification"] for r in uniclass["references"]] == ["Pr_20_93_85"]
    key = uniclass["references"][0]["key"]

    assert call("assign_classification", g(*walls_), [key])["ok"]
    got = call("of_element", g(walls_[0]))["elements"][walls_[0]]
    assert [(r["system"], r["identification"], r["name"]) for r in got] == [
        ("Uniclass 2015", "Pr_20_93_85", "Wall products")]
    assert call("unassign_classification", g(walls_[0]), [key])["ok"]
    assert call("of_element", g(walls_[0]))["elements"][walls_[0]] == []
    assert call("of_element", g(walls_[1]))["elements"][walls_[1]]  # still assigned to the other

    assert call("remove_reference", key)["ok"]
    assert call("systems")["systems"][0]["references"] == []


def test_reference_validation(model):
    assert call("create_system", "OmniClass")["ok"]
    assert not call("add_reference", "OmniClass", "")["ok"]
    assert not call("add_reference", "nope", "X")["ok"]
    assert call("add_reference", "OmniClass", "21-02 10 10", "Walls")["ok"]
    assert not call("add_reference", "OmniClass", "21-02 10 10", "Again")["ok"]
