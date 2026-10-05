# SPDX-License-Identifier: GPL-3.0-or-later
"""Object data editing in the app bridge (M2): bulk edit, typed values, undo/redo, save."""
import json

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import pytest
from conftest import build_model

from kimcad import app_bridge
from kimcad.records import decompose


def call(fn, *args):
    return json.loads(getattr(app_bridge, fn)(*args))


@pytest.fixture
def opened(tmp_path):
    """3 walls (Pset_WallCommon.FireRating = EI30) + 1 slab; wall 0 has a real-typed custom property."""
    f = build_model(walls=3)
    storey = f.by_type("IfcBuildingStorey")[0]
    slab = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlab", name="Losa")
    ifcopenshell.api.spatial.assign_container(f, products=[slab], relating_structure=storey)
    w0 = f.by_type("IfcWall")[0]
    custom = ifcopenshell.api.pset.add_pset(f, product=w0, name="KIMCAD_Test")
    ifcopenshell.api.pset.edit_pset(f, pset=custom, properties={"Width": f.createIfcReal(0.2)})
    path = tmp_path / "Proyecto ñ.ifc"
    f.write(str(path))
    assert call("open_model", str(path))["ok"]
    walls = [w.GlobalId for w in f.by_type("IfcWall")]
    return {"path": path, "walls": walls, "slab": slab.GlobalId, "tmp": tmp_path}


def multi(guids):
    return call("properties_multi", json.dumps(guids))


def fire(guids):
    return multi(guids)["psets"]["Pset_WallCommon"]["FireRating"]


def test_merged_view_marks_differences(opened):
    w = opened["walls"]
    same = fire(w[:2])
    assert same == {"value": "EI30", "varies": False, "ifc_type": "IfcLabel", "editable": True}
    mixed = fire([w[0], opened["slab"]])  # the slab has no Pset_WallCommon
    assert mixed["varies"] is True
    m = multi(w)
    assert m["count"] == 3 and m["types"] == ["IfcWall"]
    assert m["name"]["varies"] is True


def test_bulk_edit_is_one_undo_step(opened):
    w = opened["walls"][:2]
    r = call("set_property", json.dumps(w), "Pset_WallCommon", "FireRating", json.dumps("EI90"))
    assert r == {"ok": True, "changed": 2}
    assert fire(w)["value"] == "EI90"
    s = call("undo")
    assert s["ok"] and not s["can_undo"] and s["can_redo"]
    assert fire(w)["value"] == "EI30"
    assert call("redo")["ok"]
    assert fire(w)["value"] == "EI90"


def test_new_edit_after_undo_drops_redo(opened):
    w = opened["walls"][:1]
    call("set_property", json.dumps(w), "Pset_WallCommon", "FireRating", json.dumps("EI60"))
    call("undo")
    call("set_property", json.dumps(w), "Pset_WallCommon", "FireRating", json.dumps("EI120"))
    assert call("state")["can_redo"] is False
    assert call("redo")["ok"] is False


def test_values_keep_their_ifc_type_and_bad_input_changes_nothing(opened):
    w0 = opened["walls"][:1]
    ok = call("set_property", json.dumps(w0), "KIMCAD_Test", "Width", json.dumps("0.25"))  # text that is a number
    assert ok["ok"]
    width = multi(w0)["psets"]["KIMCAD_Test"]["Width"]
    assert width["value"] == 0.25 and width["ifc_type"] == "IfcReal"
    state_before = call("state")
    bad = call("set_property", json.dumps(w0), "KIMCAD_Test", "Width", json.dumps("abc"))
    assert bad["ok"] is False and "abc" in bad["error"]
    assert multi(w0)["psets"]["KIMCAD_Test"]["Width"]["value"] == 0.25
    assert call("state") == state_before  # no new undo step, dirty unchanged


def test_elements_lacking_the_pset_gain_it(opened):
    targets = [opened["walls"][0], opened["slab"]]
    r = call("set_property", json.dumps(targets), "Pset_WallCommon", "FireRating", json.dumps("EI60"))
    assert r["ok"] and r["changed"] == 2
    slab_view = multi([opened["slab"]])["psets"]["Pset_WallCommon"]["FireRating"]
    assert slab_view["value"] == "EI60" and slab_view["ifc_type"] == "IfcLabel"
    psets = [r.RelatingPropertyDefinition.Name for r in app_bridge._model.by_guid(opened["slab"]).IsDefinedBy]
    assert psets.count("Pset_WallCommon") == 1  # never duplicated


def test_dirty_follows_edits_undo_and_save(opened):
    assert call("state")["dirty"] is False
    call("set_name", json.dumps(opened["walls"][:1]), "Muro Ñandú")
    assert call("state")["dirty"] is True
    call("undo")
    assert call("state")["dirty"] is False  # back to the saved state
    call("redo")
    assert call("state")["dirty"] is True
    out = opened["tmp"] / "saved.ifc"
    assert call("save", str(out))["ok"]
    s = call("state")
    assert s["dirty"] is False and s["path"] == str(out)
    call("undo")  # undoing past the save makes it dirty again
    assert call("state")["dirty"] is True


def test_save_persists_and_round_trips(opened):
    w = opened["walls"]
    call("set_property", json.dumps(w), "Pset_WallCommon", "FireRating", json.dumps("EI90"))
    call("set_name", json.dumps(w[:1]), "Muro Ñandú 墙")
    out = opened["tmp"] / "out.ifc"
    assert call("save", str(out))["ok"]
    reopened = ifcopenshell.open(str(out))
    assert reopened.by_guid(w[0]).Name == "Muro Ñandú 墙"
    for g in w:
        rels = reopened.by_guid(g).IsDefinedBy
        values = [p.NominalValue.wrappedValue for r in rels if r.RelatingPropertyDefinition.Name == "Pset_WallCommon"
                  for p in r.RelatingPropertyDefinition.HasProperties if p.Name == "FireRating"]
        assert values == ["EI90"]
    assert decompose(reopened)[0] == decompose(app_bridge._model)[0]  # saved file == edited model


def test_remove_property_and_templates(opened):
    w0 = opened["walls"][:1]
    assert call("remove_property", json.dumps(w0), "Pset_WallCommon", "FireRating")["ok"]
    assert "FireRating" not in multi(w0)["psets"].get("Pset_WallCommon", {})
    assert call("undo")["ok"]
    assert fire(w0)["value"] == "EI30"
    assert "Pset_WallCommon" in call("pset_templates", "IfcWall")["names"]


def test_editing_without_a_model_is_an_error():
    app_bridge._model = None
    assert call("set_property", "[]", "P", "x", '"1"')["ok"] is False
    assert call("undo")["ok"] is False


def test_a_failure_midway_through_a_bulk_edit_rolls_back_everything(opened, monkeypatch):
    real = ifcopenshell.api.pset.edit_pset
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(ifcopenshell.api.pset, "edit_pset", flaky)
    r = call("set_property", json.dumps(opened["walls"]), "Pset_WallCommon", "FireRating", '"EI90"')
    assert not r["ok"] and "boom" in r["error"]
    monkeypatch.setattr(ifcopenshell.api.pset, "edit_pset", real)

    p = multi(opened["walls"])["psets"]["Pset_WallCommon"]["FireRating"]
    assert p == {**p, "value": "EI30", "varies": False}  # the first wall was rolled back too
    assert call("state") == {**call("state"), "dirty": False, "can_undo": False, "can_redo": False}
    # The next edit and its undo still line up with ifcopenshell's history.
    assert call("set_name", json.dumps(opened["walls"][:1]), "Nuevo")["ok"]
    assert call("undo")["ok"] and not call("state")["dirty"]
