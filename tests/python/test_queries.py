# SPDX-License-Identifier: GPL-3.0-or-later
"""Selection tools (D78): select similar, Find & Select queries, saved criteria and selection sets."""
import json
import pathlib
import time

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.layer
import ifcopenshell.api.material
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.type
import pytest

from kimbim import app_bridge as b
from kimbim import queries as q
from kimbim import renovation
from kimbim import settings as s

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLINIC = ROOT / "tests" / "corpus" / "files" / "community" / "IFC 2.3.0.1 (IFC 2x3)" / "Medical-Dental Clinic" / "Clinic_Architectural.ifc"


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def _house():
    """Two levels; typed walls (W200 x3, W100 x1) and untyped ones (2 STANDARD, 1 PARTITIONING); a slab,
    a door filling an opening in W200 wall 0; layers, materials, psets and renovation statuses."""
    f = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="B")
    l1 = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Level 1")
    l2 = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Level 2")
    l2.Elevation = 3.0
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(f, products=[l1, l2], relating_object=building)
    w200 = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWallType", name="W200 Brick")
    w100 = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWallType", name="W100 Plaster")
    tp = ifcopenshell.api.pset.add_pset(f, product=w200, name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=tp, properties={"FireRating": "EI60"})
    brick = ifcopenshell.api.material.add_material(f, name="Brick")
    plaster = ifcopenshell.api.material.add_material(f, name="Plaster board")
    outer = ifcopenshell.api.layer.add_layer(f, name="A-Wall-Outer")
    inner = ifcopenshell.api.layer.add_layer(f, name="A-Wall-Inner")
    ctx = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body",
                                                target_view="MODEL_VIEW", parent=ctx)
    el = {}

    def wall(name, storey, wtype=None, predefined=None, length=4.0, layer=None, material=None, status=None):
        w = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name=name, predefined_type=predefined)
        if wtype is not None:
            ifcopenshell.api.type.assign_type(f, related_objects=[w], relating_type=wtype)
        rep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=length, height=3.0, thickness=0.2)
        ifcopenshell.api.geometry.assign_representation(f, product=w, representation=rep)
        if layer is not None:
            ifcopenshell.api.layer.assign_layer(f, items=[rep], layer=layer)
        if material is not None:
            ifcopenshell.api.material.assign_material(f, products=[w], material=material)
        p = ifcopenshell.api.pset.add_qto(f, product=w, name="Qto_WallBaseQuantities")
        ifcopenshell.api.pset.edit_qto(f, qto=p, properties={"Length": length})
        ifcopenshell.api.spatial.assign_container(f, products=[w], relating_structure=storey)
        if status is not None:
            renovation.write_status(w, status)
        el[name] = w
        return w

    wall("A", l1, w200, length=4.0, layer=outer, material=brick, status="existing")
    wall("B", l1, w200, length=6.0, layer=outer, material=brick, status="demolish")
    wall("C", l2, w200, length=8.0, layer=outer, material=brick)
    wall("D", l1, w100, length=2.0, layer=inner, material=plaster, status="existing")
    wall("E", l1, predefined="STANDARD", length=3.0)
    wall("F", l2, predefined="STANDARD", length=3.5)
    wall("G", l2, predefined="PARTITIONING", length=1.0, layer=inner)
    own = ifcopenshell.api.pset.add_pset(f, product=el["B"], name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=own, properties={"FireRating": "EI90", "IsExternal": True})
    slab = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlab", name="Floor", predefined_type="FLOOR")
    ifcopenshell.api.spatial.assign_container(f, products=[slab], relating_structure=l1)
    el["slab"] = slab
    opening = ifcopenshell.api.root.create_entity(f, ifc_class="IfcOpeningElement")
    ifcopenshell.api.feature.add_feature(f, feature=opening, element=el["A"])
    door = ifcopenshell.api.root.create_entity(f, ifc_class="IfcDoor", name="Front door")
    ifcopenshell.api.feature.add_filling(f, opening=opening, element=door)  # not contained: its wall's level
    el["door"] = door
    return f, el, l1, l2


@pytest.fixture
def house():
    s.load(None)
    f, el, l1, l2 = _house()
    b._model = f
    yield f, el, l1, l2
    b._model = None
    s.load(None)


def names(f, guids):
    return sorted(f.by_guid(g).Name for g in guids)


def find(rows, match="all", **extra):
    r = call("find_elements", json.dumps({"match": match, "rows": rows, **extra}))
    assert r["ok"], r
    return r["guids"]


def test_select_similar_by_type_and_untyped_fallback(house):
    f, el, *_ = house
    r = call("similar_elements", json.dumps([el["A"].GlobalId]), "type")
    assert r["ok"] and names(f, r["guids"]) == ["A", "B", "C"]
    # untyped: the other untyped walls of the same predefined type, not typed walls nor partitions
    r = call("similar_elements", json.dumps([el["E"].GlobalId]), "type")
    assert names(f, r["guids"]) == ["E", "F"]
    r = call("similar_elements", json.dumps([el["A"].GlobalId, el["G"].GlobalId]), "type")
    assert names(f, r["guids"]) == ["A", "B", "C", "G"]
    r = call("similar_elements", json.dumps([el["D"].GlobalId]), "class")
    assert names(f, r["guids"]) == ["A", "B", "C", "D", "E", "F", "G"]
    r = call("similar_elements", json.dumps([el["A"].GlobalId]), "type", json.dumps(["a-wall-outer"]))
    assert r["guids"] == []  # elements on hidden or locked layers can't be selected
    assert not call("similar_elements", "[]", "colour")["ok"]


def test_class_kind_type_and_name(house):
    f, el, *_ = house
    assert names(f, find([{"field": "ifc_class", "op": "equals", "value": "IfcSlab"}])) == ["Floor"]
    assert names(f, find([{"field": "kind", "op": "equals", "value": "doors"}])) == ["Front door"]
    assert len(find([{"field": "kind", "op": "not_equals", "value": "walls"}])) == 2
    assert names(f, find([{"field": "type", "op": "contains", "value": "brick"}])) == ["A", "B", "C"]
    assert names(f, find([{"field": "type", "op": "equals", "value": "W100 Plaster"}])) == ["D"]
    assert names(f, find([{"field": "type", "op": "missing"}, {"field": "kind", "op": "equals", "value": "walls"}])) == ["E", "F", "G"]
    assert names(f, find([{"field": "name", "op": "contains", "value": "door"}])) == ["Front door"]


def test_properties_with_every_operator(house):
    f, *_ = house
    fire = {"field": "property", "property": "Pset_WallCommon.FireRating"}
    assert names(f, find([{**fire, "op": "equals", "value": "ei60"}])) == ["A", "C"]  # from the type; B's own wins
    assert names(f, find([{**fire, "op": "not_equals", "value": "EI60"}])) == ["B"]
    assert names(f, find([{**fire, "op": "contains", "value": "EI"}])) == ["A", "B", "C"]
    assert len(find([{**fire, "op": "missing"}])) == 6
    length = {"field": "property", "property": "Length"}
    assert names(f, find([{**length, "op": "more", "value": 3.5}])) == ["A", "B", "C"]
    assert names(f, find([{**length, "op": "less", "value": "3"}])) == ["D", "G"]
    assert names(f, find([{"field": "property", "property": "IsExternal", "op": "true"}])) == ["B"]


def test_layer_material_level_and_status(house):
    f, el, l1, l2 = house
    assert names(f, find([{"field": "layer", "op": "equals", "value": "A-Wall-Inner"}])) == ["D", "G"]
    assert names(f, find([{"field": "layer", "op": "missing"}, {"field": "kind", "op": "equals", "value": "walls"}])) == ["E", "F"]
    assert names(f, find([{"field": "material", "op": "contains", "value": "plaster"}])) == ["D"]
    assert names(f, find([{"field": "level", "op": "equals", "value": "Level 2"}])) == ["C", "F", "G"]
    # the door has no container: it is on its wall's level
    assert names(f, find([{"field": "level", "op": "equals", "value": l1.GlobalId}])) == ["A", "B", "D", "E", "Floor", "Front door"]
    assert names(f, find([{"field": "status", "op": "equals", "value": "existing"}])) == ["A", "D", "Front door"]  # D91: the door follows its wall
    assert names(f, find([{"field": "status", "op": "equals", "value": "demolish"}])) == ["B"]
    assert "Floor" in names(f, find([{"field": "status", "op": "equals", "value": "new"}]))


def test_and_or_and_scopes(house):
    f, el, l1, l2 = house
    rows = [{"field": "status", "op": "equals", "value": "demolish"},
            {"field": "type", "op": "equals", "value": "W100 Plaster"}]
    assert find(rows, "all") == []
    assert names(f, find(rows, "any")) == ["B", "D"]
    walls = [{"field": "kind", "op": "equals", "value": "walls"}]
    assert names(f, find(walls, scope="level", level=l2.GlobalId)) == ["C", "F", "G"]
    sel = [el["A"].GlobalId, el["slab"].GlobalId, "nope"]
    assert names(f, find(walls, scope="selection", selection=sel)) == ["A"]
    assert names(f, find([], scope="selection", selection=sel)) == ["A", "Floor"]  # no rows: everything in scope
    assert names(f, find(walls, skip_layers=["A-Wall-Outer", "A-Wall-Inner"])) == ["E", "F"]
    assert not call("find_elements", json.dumps({"rows": [], "scope": "level"}))["ok"]  # no active level


def test_bad_criteria_are_refused(house):
    for bad, message in [
        ({"rows": [{"field": "colour", "op": "equals"}]}, "unknown criteria field colour"),
        ({"rows": [{"field": "level", "op": "contains", "value": "x"}]}, "level: unknown operator contains"),
        ({"rows": [{"field": "property", "op": "equals", "value": "x"}]}, "a property row needs a property name (Name or Pset.Name)"),
        ({"rows": [{"field": "status", "op": "equals", "value": "ruined"}]}, "unknown renovation status ruined"),
        ({"rows": [], "match": "some"}, "unknown match some (all or any)"),
    ]:
        r = call("find_elements", json.dumps(bad))
        assert not r["ok"] and r["error"] == message


def test_criteria_and_sets_are_project_settings(house):
    f, el, *_ = house
    crit = {"match": "all", "rows": [{"field": "kind", "op": "equals", "value": "walls"}]}
    r = call("set_project_settings", json.dumps({"selection_criteria": {"Walls": crit},
                                                 "selection_sets": {"Front": [el["A"].GlobalId, "gone"]}}))
    assert r["ok"] and s.current()["selection_criteria"]["Walls"] == crit
    r = call("selection_set_members", "Front")
    assert r["ok"] and r["guids"] == [el["A"].GlobalId] and r["missing"] == 1
    assert not call("selection_set_members", "Nope")["ok"]
    r = call("set_project_settings", json.dumps({"selection_criteria": {"Bad": {"rows": [{"field": "x"}]}}}))
    assert not r["ok"] and r["error"] == "criteria Bad: unknown criteria field x"
    r = call("set_project_settings", json.dumps({"selection_sets": {"S": [1, 2]}}))
    assert not r["ok"] and r["error"] == "selection set S must be a list of GlobalIds"
    assert s.DEFAULTS["selection_criteria"] == {} and s.DEFAULTS["selection_sets"] == {}


def test_choices_list_what_the_model_has(house):
    r = call("query_choices")
    assert r["ok"]
    assert r["classes"] == ["IfcDoor", "IfcSlab", "IfcWall"]
    assert r["types"] == ["W100 Plaster", "W200 Brick"]
    assert r["layers"] == ["A-Wall-Inner", "A-Wall-Outer"]
    assert [lv["name"] for lv in r["levels"]] == ["Level 1", "Level 2"]
    assert r["materials"] == ["Brick", "Plaster board"]
    assert "Pset_WallCommon.FireRating" in r["properties"]
    assert r["statuses"] == ["existing", "demolish", "new", "temporary", "auxiliary"]


@pytest.mark.slow
def test_queries_are_fast_on_the_clinic():
    if not CLINIC.exists():
        pytest.skip("corpus not downloaded (pixi run fetch-corpus)")
    from kimbim.testing import _reset_owner

    try:
        b._model = ifcopenshell.open(str(CLINIC))
        s.load(None)
        timings = {}
        cases = {
            "class": [{"field": "ifc_class", "op": "equals", "value": "IfcWall"}],
            "property": [{"field": "property", "property": "IsExternal", "op": "true"}],
            "level": [{"field": "level", "op": "equals", "value": b._model.by_type("IfcBuildingStorey")[0].Name}],
            "status": [{"field": "status", "op": "equals", "value": "new"}],
            "type+layer+material": [{"field": "type", "op": "contains", "value": "a"},
                                    {"field": "layer", "op": "exists"}, {"field": "material", "op": "exists"}],
        }
        for label, rows in cases.items():
            t0 = time.perf_counter()
            r = call("find_elements", json.dumps({"match": "any" if "+" in label else "all", "rows": rows}))
            timings[label] = (time.perf_counter() - t0) * 1000
            assert r["ok"] and r["guids"], (label, r)
        wall = b._model.by_type("IfcWall")[0].GlobalId
        t0 = time.perf_counter()
        r = call("similar_elements", json.dumps([wall]), "type")
        timings["similar"] = (time.perf_counter() - t0) * 1000
        assert r["ok"] and wall in r["guids"]
        t0 = time.perf_counter()
        assert call("query_choices")["ok"]
        timings["choices"] = (time.perf_counter() - t0) * 1000
        print("\nClinic query timings (ms): " + ", ".join(f"{k} {v:.0f}" for k, v in timings.items()))
        assert max(timings.values()) < 3000, timings
    finally:
        b._model = None
        _reset_owner()
