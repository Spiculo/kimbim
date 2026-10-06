# SPDX-License-Identifier: GPL-3.0-or-later
"""Owner feedback, Slice 12: "models" — a unit (e.g. an apartment) drawn once in a model container
below the building and placed on many levels; every placement points to it and follows its edits."""
import json
import math

import ifcopenshell.util.element
import numpy as np
import pytest

from kimcad import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


def bbox(guid):
    _, verts, _ = b.mesh_elements(json.dumps([guid]))
    v = np.frombuffer(verts, dtype="<f4").reshape(-1, 3)
    return v.min(axis=0), v.max(axis=0)


def contained(storey_guid):
    s = b._model.by_guid(storey_guid)
    return [e for rel in s.ContainsElements or () for e in rel.RelatedElements]


@pytest.fixture
def apartment():
    """Levels at 0 and 3 m; model "Apartment A" with an L of two joined walls and a door."""
    assert call("new_project", "Torre")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    m = call("create_model", "Apartment A")
    assert m["ok"], m
    model = m["guid"]
    t = next(x for x in call("wall_types")["types"] if x["name"] == "Exterior 300")["guid"]
    a = call("create_wall", model, t, 0, 0, 6, 0, 3.0, "", "")["guid"]
    w = call("create_wall", model, t, 6, 0, 6, 4, 3.0, a, "")["guid"]
    d = call("opening_types", "door")["types"][0]
    door = call("insert_opening", "door", a, d["guid"], 3.0, 0.9, 2.1, 0.0)["guid"]
    return {"l1": l1, "l2": l2, "model": model, "walls": [a, w], "door": door, "type": t}


def test_models_are_a_separate_section_of_levels(apartment):
    storeys = call("storeys")["storeys"]
    model = next(s for s in storeys if s["guid"] == apartment["model"])
    assert model["model"] is True and model["elevation"] <= -10.0
    assert [s["model"] for s in storeys if s["guid"] != apartment["model"]] == [False, False]
    assert call("models")["models"] == [{"guid": apartment["model"], "name": "Apartment A",
                                         "elevation": model["elevation"], "instances": 0}]


def test_placing_a_model_copies_its_elements_linked_to_it(apartment):
    r1 = call("place_model", apartment["model"], apartment["l1"], 10, 0, 0)
    assert r1["ok"], r1
    r2 = call("place_model", apartment["model"], apartment["l2"], 10, 0, math.pi / 2)
    assert r2["ok"] and r1["instance"] != r2["instance"]
    on_l1 = contained(apartment["l1"])
    assert sorted(e.is_a() for e in on_l1) == ["IfcDoor", "IfcWall", "IfcWall"]
    first_wall = next(e for e in on_l1 if e.is_a("IfcWall") and
                      ifcopenshell.util.element.get_psets(e)["KIMCAD_ModelInstance"]["Source"] == apartment["walls"][0])
    lo, hi = bbox(first_wall.GlobalId)
    assert lo[0] == pytest.approx(10.0, abs=0.2) and hi[0] == pytest.approx(16.15, abs=0.2) and lo[2] == pytest.approx(0.0, abs=1e-3)
    on_l2 = contained(apartment["l2"])
    turned = next(e for e in on_l2 if e.is_a("IfcWall") and
                  ifcopenshell.util.element.get_psets(e)["KIMCAD_ModelInstance"]["Source"] == apartment["walls"][0])
    lo, hi = bbox(turned.GlobalId)
    assert hi[1] - lo[1] == pytest.approx(6.15, abs=0.2) and lo[2] == pytest.approx(3.0, abs=1e-3)  # along Y now
    joins = b._model.by_type("IfcRelConnectsPathElements")
    assert len(joins) == 3  # the model's and each placement's corner
    assert call("models")["models"][0]["instances"] == 2


def test_updating_instances_follows_the_model_and_keeps_identity(apartment):
    call("place_model", apartment["model"], apartment["l1"], 10, 0, 0)
    before = {e.GlobalId for e in contained(apartment["l1"])}
    call("set_name", g(apartment["walls"][1]), "Muro medianero")
    extra = call("create_wall", apartment["model"], apartment["type"], 0, 4, 6, 4, 3.0, "", "")["guid"]
    r = call("update_model_instances", apartment["model"])
    assert r["ok"], r
    after = contained(apartment["l1"])
    assert before <= {e.GlobalId for e in after}  # existing instance elements kept their GlobalIds
    assert len([e for e in after if e.is_a("IfcWall")]) == 3
    assert "Muro medianero" in {e.Name for e in after}
    call("delete_elements", g(extra))
    call("update_model_instances", apartment["model"])
    assert len([e for e in contained(apartment["l1"]) if e.is_a("IfcWall")]) == 2


def test_explode_unlinks_an_instance(apartment):
    r = call("place_model", apartment["model"], apartment["l1"], 10, 0, 0)
    assert call("explode_instance", r["instance"])["ok"]
    for e in contained(apartment["l1"]):
        assert "KIMCAD_ModelInstance" not in ifcopenshell.util.element.get_psets(e)
    assert call("models")["models"][0]["instances"] == 0
    assert call("instance_members")["instances"] == {}


def test_instance_members_for_locking(apartment):
    r = call("place_model", apartment["model"], apartment["l1"], 10, 0, 0)
    members = call("instance_members")["instances"]
    assert set(members) == {r["instance"]} and len(members[r["instance"]]) == 3
    call("undo")
    assert call("instance_members")["instances"] == {}


def test_a_moved_instance_stays_where_it_was_moved(apartment):
    r = call("place_model", apartment["model"], apartment["l1"], 10, 0, 0)
    assert call("move_elements", g(*r["guids"]), 0, 5, 0)["ok"]
    call("update_model_instances", apartment["model"])
    wall = next(e for e in contained(apartment["l1"]) if e.is_a("IfcWall") and
                ifcopenshell.util.element.get_psets(e)["KIMCAD_ModelInstance"]["Source"] == apartment["walls"][0])
    lo, hi = bbox(wall.GlobalId)
    assert lo[0] == pytest.approx(10.0, abs=0.2) and (lo[1] + hi[1]) / 2 == pytest.approx(5.0, abs=0.05)


def test_model_elements_lists_what_is_drawn_in_models(apartment):
    call("place_model", apartment["model"], apartment["l1"], 10, 0, 0)
    inside = set(call("model_elements")["guids"])
    assert inside == {*apartment["walls"], apartment["door"]}
