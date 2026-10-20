# SPDX-License-Identifier: GPL-3.0-or-later
"""Type vs. element properties (D50): source of each value, deliberate type edits, reset to type."""
import json

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.type
import ifcopenshell.util.element
import pytest
from conftest import build_model

from kimbim import app_bridge

PSET = "Pset_WallCommon"
U = "ThermalTransmittance"


def call(fn, *args):
    return json.loads(getattr(app_bridge, fn)(*args))


@pytest.fixture
def typed(tmp_path):
    """4 walls: w0..w2 typed by "Basic Wall 200" (U = 0.35 on the type), w3 untyped; plus a 2nd type with no pset."""
    f = build_model(walls=4)
    walls = f.by_type("IfcWall")
    wt = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWallType", name="Basic Wall 200")
    ps = ifcopenshell.api.pset.add_pset(f, product=wt, name=PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={U: f.createIfcThermalTransmittanceMeasure(0.35)})
    ifcopenshell.api.type.assign_type(f, related_objects=walls[:3], relating_type=wt)
    bare = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWallType", name="Bare type")
    extra = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name="Wall bare")
    ifcopenshell.api.spatial.assign_container(f, products=[extra], relating_structure=f.by_type("IfcBuildingStorey")[0])
    ifcopenshell.api.type.assign_type(f, related_objects=[extra], relating_type=bare)
    path = tmp_path / "tipos.ifc"
    f.write(str(path))
    assert call("open_model", str(path))["ok"]
    return {"w": [w.GlobalId for w in walls], "bare": extra.GlobalId, "path": path}


def g(*guids):
    return json.dumps(list(guids))


def prop(guids, pset=PSET, name=U):
    return call("properties_multi", g(*guids))["psets"][pset][name]


def test_source_of_each_value(typed):
    w = typed["w"]
    p = prop([w[0]])
    assert p["source"] == "type" and p["value"] == pytest.approx(0.35) and p["type_value"] == pytest.approx(0.35)
    assert prop([w[0]], name="FireRating")["source"] == "element"
    assert call("set_property", g(w[1]), PSET, U, "0.5")["ok"]
    over = prop([w[1]])
    assert over["source"] == "override" and over["value"] == pytest.approx(0.5) and over["type_value"] == pytest.approx(0.35)
    assert prop([w[0], w[1]])["source"] == "mixed"


def test_type_edit_reaches_unselected_elements_of_the_type_in_one_undo_step(typed):
    w = typed["w"]
    usage = call("type_usage", g(w[0]), PSET, U)
    assert usage["elements"] == 3 and usage["untyped"] == 0
    assert usage["types"] == [{"guid": usage["types"][0]["guid"], "name": "Basic Wall 200", "count": 3}]
    r = call("set_type_property", g(w[0]), PSET, U, "0.28")
    assert r == {**r, "ok": True, "types": 1, "elements": 3}
    assert prop(w[:3])["value"] == pytest.approx(0.28)  # w1, w2 were not selected
    assert prop(w[:3])["ifc_type"] == "IfcThermalTransmittanceMeasure"
    assert call("state")["dirty"]
    assert call("undo")["ok"]
    assert prop(w[:3])["value"] == pytest.approx(0.35)
    assert not call("state")["dirty"]


def test_overrides_win_and_are_not_counted(typed):
    w = typed["w"]
    assert call("set_property", g(w[2]), PSET, U, "0.9")["ok"]
    assert call("type_usage", g(w[0]), PSET, U)["elements"] == 2
    assert call("set_type_property", g(w[0]), PSET, U, "0.3")["elements"] == 2
    assert prop([w[2]])["value"] == pytest.approx(0.9)
    assert prop([w[2]])["type_value"] == pytest.approx(0.3)


def test_untyped_elements_are_reported_not_edited(typed):
    w = typed["w"]
    usage = call("type_usage", g(w[0], w[3]), PSET, U)
    assert usage["untyped"] == 1 and usage["elements"] == 3
    call("set_type_property", g(w[0], w[3]), PSET, U, "0.4")
    assert prop([w[3]], name="FireRating")["source"] == "element"
    assert U not in call("properties_multi", g(w[3]))["psets"][PSET]


def test_type_without_the_pset_gets_one(typed):
    r = call("set_type_property", g(typed["bare"]), PSET, U, "0.6")
    assert r["ok"] and r["types"] == 1
    p = prop([typed["bare"]])
    assert p["source"] == "type" and p["value"] == pytest.approx(0.6)


def test_invalid_type_value_changes_nothing(typed):
    r = call("set_type_property", g(typed["w"][0]), PSET, U, '"abc"')
    assert not r["ok"]
    assert not call("state")["can_undo"]


def test_reset_to_type_only_where_the_type_defines_it(typed):
    w = typed["w"]
    call("set_property", g(w[0], w[3]), PSET, U, "0.7")
    r = call("reset_to_type", g(w[0], w[3]), PSET, U)
    assert r["ok"] and r["changed"] == 1
    assert prop([w[0]])["source"] == "type" and prop([w[0]])["value"] == pytest.approx(0.35)
    assert prop([w[3]])["value"] == pytest.approx(0.7)  # no type value: the override stays
    assert call("undo")["ok"]
    assert prop([w[0]])["source"] == "override"


def test_fixture_model_for_the_app_is_typed(tmp_path):
    path = tmp_path / "f.ifc"
    call("_write_test_model", str(path))
    f = ifcopenshell.open(str(path))
    t = f.by_type("IfcWallType")[0]
    assert t.Name == "Basic Wall 200"
    assert all(ifcopenshell.util.element.get_type(w) == t for w in f.by_type("IfcWall"))
