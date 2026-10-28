# SPDX-License-Identifier: GPL-3.0-or-later
"""M2: the type manager - list, create from an element, assign, edit and update all occurrences."""
import json

import ifcopenshell.api.pset
import ifcopenshell.util.element
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
    f = build_model(walls=3)
    # The occurrence property sets exist; the manager makes a type from them.
    b._model = f
    settings.load(None)
    yield f
    b._model = None
    settings.load(None)


def walls(f):
    return list(f.by_type("IfcWall"))


def test_create_assign_edit_and_update_all(model):
    items = walls(model)
    assert call("assign_type", g(items[0].GlobalId), "")["ok"] is False

    made = call("create_type", g(items[0].GlobalId, items[1].GlobalId), "Basic Wall 200")
    assert made["ok"], made
    type_guid = made["type"]["guid"]
    assert call("type_of", g(items[0].GlobalId))["types"][0]["count"] == 2
    assert call("type_of", g(items[2].GlobalId))["untyped"] == [items[2].GlobalId]

    listed = call("list_types")["types"]
    assert listed == [{**listed[0], "guid": type_guid, "name": "Basic Wall 200", "class": "IfcWallType",
                       "count": 2}]

    # Edit the type's property: both occurrences inherit it.
    assert call("edit_type", type_guid, json.dumps({"Name": "Wall 200", "Description": "Masonry",
                                                    "psets": {"Pset_WallCommon": {"FireRating": "EI60"}}}))["ok"]
    for w in items[:2]:
        assert ifcopenshell.util.element.get_pset(w, "Pset_WallCommon")["FireRating"] == "EI60"
    assert call("type_details", type_guid)["type"]["name"] == "Wall 200"

    # An occurrence override blocks the type; update all removes it.
    own = ifcopenshell.api.pset.add_pset(model, product=items[0], name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(model, pset=own, properties={"FireRating": "EI30"})
    assert ifcopenshell.util.element.get_pset(items[0], "Pset_WallCommon")["FireRating"] == "EI30"
    updated = call("update_type_all", type_guid)
    assert updated["ok"] and updated["removed"] >= 1 and updated["occurrences"] == 2
    assert ifcopenshell.util.element.get_pset(items[0], "Pset_WallCommon")["FireRating"] == "EI60"

    # Assign the same type to the third wall.
    assert call("assign_type", g(items[2].GlobalId), type_guid)["ok"]
    assert call("type_of", g(items[2].GlobalId))["types"][0]["count"] == 3


def test_a_class_without_a_type_class_is_refused(model):
    space = model.by_type("IfcSite")[0]
    assert "has no IFC type class" in call("create_type", g(space.GlobalId), "Site")["error"]
