# SPDX-License-Identifier: GPL-3.0-or-later
"""Small IFC models built with ifcopenshell.api, for tests and the app self-test (no corpus needed)."""
import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.owner
import ifcopenshell.api.owner.settings
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import numpy as np


_DEFAULT_GET_USER = ifcopenshell.api.owner.settings.get_user
_DEFAULT_GET_APPLICATION = ifcopenshell.api.owner.settings.get_application


def _reset_owner():
    ifcopenshell.api.owner.settings.get_user = _DEFAULT_GET_USER
    ifcopenshell.api.owner.settings.get_application = _DEFAULT_GET_APPLICATION


def _set_owner(f):
    """IFC2X3 requires an IfcOwnerHistory on every rooted entity; ifcopenshell.api needs a user/app."""
    person = ifcopenshell.api.owner.add_person(f, identification="kimbim", family_name="Test", given_name="KimBim")
    org = ifcopenshell.api.owner.add_organisation(f, identification="KimBim", name="KimBim")
    user = ifcopenshell.api.owner.add_person_and_organisation(f, person=person, organisation=org)
    app = ifcopenshell.api.owner.add_application(f)
    ifcopenshell.api.owner.settings.get_user = lambda ifc: user
    ifcopenshell.api.owner.settings.get_application = lambda ifc: app


def build_model(schema="IFC4", walls=2):
    f = ifcopenshell.file(schema=schema)
    _reset_owner()  # owner callbacks are global in ifcopenshell.api; never leak them across files
    if schema == "IFC2X3":
        _set_owner(f)
    project =ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="Test")
    ifcopenshell.api.unit.assign_unit(f)
    model = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model
    )
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Building")
    storey = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Level 1")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(f, products=[storey], relating_object=building)
    ifcopenshell.api.geometry.edit_object_placement(f, product=storey)
    made = []
    for i in range(walls):
        w = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name=f"Wall {i}")
        rep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=4.0, height=3.0, thickness=0.2)
        ifcopenshell.api.geometry.assign_representation(f, product=w, representation=rep)
        m = np.eye(4)
        m[0][3] = 5.0 * i
        ifcopenshell.api.geometry.edit_object_placement(f, product=w, matrix=m, is_si=True)
        pset = ifcopenshell.api.pset.add_pset(f, product=w, name="Pset_WallCommon")
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"FireRating": "EI30", "IsExternal": True})
        made.append(w)
    ifcopenshell.api.spatial.assign_container(f, products=made, relating_structure=storey)
    return f
