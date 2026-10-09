# SPDX-License-Identifier: GPL-3.0-or-later
"""Renovation status (part B of BIM properties): read and write."""
import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.type
import ifcopenshell.util.element
import pytest

from kimcad import graphics as g
from kimcad import renovation as r
from kimcad.testing import _reset_owner, _set_owner


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
    ("NEW", "new"), ("TEMPORARY", "new"), ("OTHER", "new"), ("", "new"), (None, "new"), ("garbage", "new"),
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


def test_classes_without_a_status_template_use_kimcad_renovation():
    f = _model()
    space = _el(f, "IfcSpace")
    r.write_status(space, "existing")
    assert ifcopenshell.util.element.get_pset(space, "KIMCAD_Renovation")["Status"] == "EXISTING"
    assert r.status_of(space) == "existing"


def test_ifc2x3_uses_kimcad_renovation():
    try:
        f = _model("IFC2X3")
        w = _el(f, "IfcWall")
        r.write_status(w, "demolish")
        assert ifcopenshell.util.element.get_pset(w, "KIMCAD_Renovation")["Status"] == "DEMOLISH"
        assert r.status_of(w) == "demolish"
    finally:
        _reset_owner()


def test_writing_clears_the_other_place():
    f = _model()
    w = _el(f, "IfcWall", KIMCAD_Renovation={"Status": "DEMOLISH"})
    r.write_status(w, "existing")  # goes to Pset_WallCommon; the KIMCAD one must not contradict it
    assert "Status" not in (ifcopenshell.util.element.get_pset(w, "KIMCAD_Renovation") or {})
    assert r.status_of(w) == "existing"


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
