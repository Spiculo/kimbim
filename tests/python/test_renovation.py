# SPDX-License-Identifier: GPL-3.0-or-later
"""Renovation status (part B of BIM properties): read and write."""
import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.type
import ifcopenshell.util.element
import pytest

from kimbim import graphics as g
from kimbim import renovation as r
from kimbim.testing import _reset_owner, _set_owner


def _model(schema="IFC4"):
    f = ifcopenshell.file(schema=schema)
    if schema == "IFC2X3":
        _set_owner(f)
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    return f


def _el(f, cls, **psets):
    e = ifcopenshell.api.root.create_entity(f, ifc_class=cls)
    for pset_name, props in psets.items():
        p = ifcopenshell.api.pset.add_pset(f, product=e, name=pset_name)
        ifcopenshell.api.pset.edit_pset(f, pset=p, properties=props)
    return e


@pytest.mark.parametrize("value,expected", [
    ("EXISTING", "existing"), ("existing", "existing"), (["EXISTING"], "existing"),
    ("DEMOLISH", "demolish"), ("Demolished", "demolish"), ("To Be Demolished", "demolish"),
    ("NEW", "new"), ("OTHER", "new"), ("", "new"), (None, "new"), ("garbage", "new"),
    ("TEMPORARY", "temporary"), ("Temporary", "temporary"),
    ("AUXILIARY", "auxiliary"), ("Auxiliary", "auxiliary"),
])
def test_normalize(value, expected):
    assert r.normalize(value) == expected


def test_no_status_is_new():
    f = _model()
    assert r.status_of(_el(f, "IfcWall")) == "new"


def test_write_to_the_common_pset_as_enumerated_ifc4():
    f = _model()
    w = _el(f, "IfcWall")
    r.write_status(w, "demolish")
    prop = next(p for p in f.by_type("IfcPropertyEnumeratedValue") if p.Name == "Status")
    assert [v.wrappedValue for v in prop.EnumerationValues] == ["DEMOLISH"]
    assert r.status_of(w) == "demolish"
    r.write_status(w, "existing")  # rewrites, never duplicates
    assert r.status_of(w) == "existing"
    assert len([p for p in f.by_type("IfcPropertyEnumeratedValue") if p.Name == "Status"]) == 1


def test_classes_without_a_status_template_use_kimbim_renovation():
    f = _model()
    space = _el(f, "IfcSpace")
    r.write_status(space, "existing")
    assert ifcopenshell.util.element.get_pset(space, "KIMBIM_Renovation")["Status"] == "EXISTING"
    assert r.status_of(space) == "existing"


def test_ifc2x3_uses_kimbim_renovation():
    try:
        f = _model("IFC2X3")
        w = _el(f, "IfcWall")
        r.write_status(w, "demolish")
        assert ifcopenshell.util.element.get_pset(w, "KIMBIM_Renovation")["Status"] == "DEMOLISH"
        assert r.status_of(w) == "demolish"
    finally:
        _reset_owner()


def test_writing_clears_the_other_place():
    f = _model()
    w = _el(f, "IfcWall", KIMBIM_Renovation={"Status": "DEMOLISH"})
    r.write_status(w, "existing")  # goes to Pset_WallCommon; the KimBim one must not contradict it
    assert "Status" not in (ifcopenshell.util.element.get_pset(w, "KIMBIM_Renovation") or {})
    assert r.status_of(w) == "existing"


def test_temporary_uses_ifc_value_where_the_class_has_one():
    f = _model()
    w = _el(f, "IfcWall")
    r.write_status(w, "temporary")
    prop = next(p for p in f.by_type("IfcPropertyEnumeratedValue") if p.Name == "Status")
    assert [v.wrappedValue for v in prop.EnumerationValues] == ["TEMPORARY"]
    assert r.status_of(w) == "temporary"


def test_auxiliary_has_no_ifc_value_so_it_lives_in_kimbims_pset():
    f = _model()
    w = _el(f, "IfcWall")
    r.write_status(w, "auxiliary")
    assert ifcopenshell.util.element.get_pset(w, "KIMBIM_Renovation")["Status"] == "AUXILIARY"
    assert not [p for p in f.by_type("IfcPropertyEnumeratedValue") if p.Name == "Status"]
    assert r.status_of(w) == "auxiliary"
    r.write_status(w, "new")  # switching back clears KimBim's pset
    assert "Status" not in (ifcopenshell.util.element.get_pset(w, "KIMBIM_Renovation") or {})
    assert r.status_of(w) == "new"


def test_read_from_archicad_name_and_from_the_type():
    f = _model()
    a = _el(f, "IfcWall", AC_Pset_RenovationAndPhasing={"Renovation Status": "To Be Demolished"})
    assert r.status_of(a) == "demolish"
    w = _el(f, "IfcFurniture")
    t = ifcopenshell.api.root.create_entity(f, ifc_class="IfcFurnitureType")
    p = ifcopenshell.api.pset.add_pset(f, product=t, name="Pset_FurnitureTypeCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=p, properties={"Status": ["EXISTING"]})
    ifcopenshell.api.type.assign_type(f, related_objects=[w], relating_type=t)
    assert r.status_of(w) == "existing"
    r.write_status(w, "demolish")  # the element's own value overrides the type's
    assert r.status_of(w) == "demolish"


def test_property_index_reads_enumerated_values():
    f = _model()
    w = _el(f, "IfcWall", Pset_WallCommon={"Status": ["NEW"]})
    assert g._property_index(f, "Status")[w.id()] == "NEW"


# ---------------------------------------------------------------- setting the status (bridge)

import json  # noqa: E402
import pathlib  # noqa: E402
import tempfile  # noqa: E402

from kimbim import app_bridge as b  # noqa: E402  (first: annotations imports it)
from kimbim import annotations  # noqa: E402
from kimbim import authoring as A  # noqa: E402
from kimbim import settings as s  # noqa: E402


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def _house():
    s.load(None)
    assert call("new_project", "Reno")["ok"]
    level = json.loads(A.storeys())["storeys"][0]["guid"]
    wall_type = json.loads(A.wall_types())["types"][0]["guid"]
    w1 = json.loads(A.create_wall(level, wall_type, 0, 0, 5, 0, 3.0))["geometry"]["changed"][0]
    w2 = json.loads(A.create_wall(level, wall_type, 0, 3, 5, 3, 3.0))["geometry"]["changed"][0]
    return level, wall_type, w1, w2


def test_set_status_is_one_undo_step():
    _, _, w1, w2 = _house()
    assert call("set_status", json.dumps([w1, w2]), "demolish")["ok"]
    assert call("properties_multi", json.dumps([w1, w2]))["status"] == {"value": "demolish", "varies": False}
    assert call("undo")["ok"]
    assert call("properties_multi", json.dumps([w1, w2]))["status"] == {"value": "new", "varies": False}


def test_mixed_status_varies():
    _, _, w1, w2 = _house()
    call("set_status", json.dumps([w1]), "existing")
    assert call("properties_multi", json.dumps([w1, w2]))["status"] == {"value": None, "varies": True}


def test_set_status_refuses_unknown_status():
    _, _, w1, _ = _house()
    out = call("set_status", json.dumps([w1]), "ruined")
    assert not out["ok"] and "ruined" in out["error"]


def test_new_elements_get_the_status_for_new():
    level, wall_type, w1, _ = _house()
    assert ifcopenshell.util.element.get_pset(b._model.by_guid(w1), "Pset_WallCommon")["Status"] == ["NEW"]
    assert call("set_status_for_new", "existing")["ok"]
    assert s.current()["status_for_new"] == "existing"
    w3 = json.loads(A.create_wall(level, wall_type, 0, 6, 5, 6, 3.0))["geometry"]["changed"][0]
    assert r.status_of(b._model.by_guid(w3)) == "existing"
    assert not call("set_status_for_new", "ruined")["ok"]


def test_doors_take_their_host_walls_status_and_follow_it():
    _, _, w1, _ = _house()
    call("set_status", json.dumps([w1]), "existing")
    door_type = json.loads(A.opening_types("door"))["types"][0]["guid"]
    door = json.loads(A.insert_opening("door", w1, door_type, 2.0, 0.9, 2.1, 0.0))["guid"]
    assert r.status_of(b._model.by_guid(door)) == "existing"  # D91: the host wall's status
    # It has no status of its own: it inherits, so it follows the wall when the wall changes.
    assert ifcopenshell.util.element.get_pset(b._model.by_guid(door), "Pset_DoorCommon") is None
    call("set_status", json.dumps([w1]), "demolish")
    assert r.status_of(b._model.by_guid(door)) == "demolish"
    # Set explicitly on the door, it stops following the wall.
    call("set_status", json.dumps([door]), "temporary")
    call("set_status", json.dumps([w1]), "new")
    assert r.status_of(b._model.by_guid(door)) == "temporary"


def test_copies_keep_the_source_status():
    _, _, w1, _ = _house()
    call("set_status", json.dumps([w1]), "existing")
    out = call("copy_elements", json.dumps([w1]), 0, 10, 0)
    assert r.status_of(b._model.by_guid(out["guids"][0])) == "existing"


def test_annotations_are_not_stamped():
    level, _, _, _ = _house()
    out = json.loads(annotations.add_annotation(level, "text", json.dumps([[0, 0]]), "Hi"))
    note = b._model.by_guid(out["guid"])
    assert ifcopenshell.util.element.get_pset(note, "KIMBIM_Renovation") is None


def test_unmarked_and_mark_unmarked():
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    bare = [ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall") for _ in range(2)]
    explicit = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall")
    p = ifcopenshell.api.pset.add_pset(f, product=explicit, name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=p, properties={"Status": ["NEW"]})
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcAnnotation")  # never counted
    path = str(pathlib.Path(tempfile.mkdtemp()) / "survey.ifc")
    f.write(path)
    assert call("open_model", path)["ok"]
    u = call("unmarked")
    assert u["count"] == 2 and set(u["guids"]) == {w.GlobalId for w in bare}
    assert call("mark_unmarked", "existing")["ok"]
    assert call("unmarked")["count"] == 0
    assert r.status_of(b._model.by_guid(explicit.GlobalId)) == "new"  # explicit NEW left alone
    assert all(r.status_of(b._model.by_guid(w.GlobalId)) == "existing" for w in bare)
    assert call("undo")["ok"]  # one step
    assert call("unmarked")["count"] == 2
    assert not call("mark_unmarked", "new")["ok"]  # New is what unmarked already means


def test_one_elements_status_reads_only_that_element(monkeypatch):
    """Properties and copies ask one element at a time: no file-wide property index per element."""
    f = _model()
    w = _el(f, "IfcWall", Pset_WallCommon={"Status": ["EXISTING"]})
    a = _el(f, "IfcWall", AC_Pset_RenovationAndPhasing={"Renovation Status": "To Be Demolished"})
    furniture = _el(f, "IfcFurniture")
    t = ifcopenshell.api.root.create_entity(f, ifc_class="IfcFurnitureType")
    p = ifcopenshell.api.pset.add_pset(f, product=t, name="Pset_FurnitureTypeCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=p, properties={"Status": ["EXISTING"]})
    ifcopenshell.api.type.assign_type(f, related_objects=[furniture], relating_type=t)

    def no_scan(*args):
        raise AssertionError("file-wide scan")

    monkeypatch.setattr(g, "_property_index", no_scan)
    assert r.status_of(w) == "existing"
    assert r.status_of(a) == "demolish"
    assert r.status_of(furniture) == "existing"
    r.write_status(furniture, "demolish")  # own value over the type's
    assert r.status_of(furniture) == "demolish"
    assert r.status_of(_el(f, "IfcWall")) == "new"
