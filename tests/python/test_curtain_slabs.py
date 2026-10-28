# SPDX-License-Identifier: GPL-3.0-or-later
"""Owner gap 4: curtain walls, sloped slabs and slab edges."""
import json
import math

import ifcopenshell.util.placement
import pytest

from kimbim import app_bridge as b
from kimbim import settings


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def project():
    assert call("new_project", "Curtain")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    yield {"level": level, "slab_type": call("slab_types")["types"][0]["guid"]}
    b._model = None
    settings.load(None)


def test_a_curtain_wall_is_an_ifc_curtain_wall(project):
    r = call("create_curtain_wall", project["level"], 0, 0, 6, 0, 3.0, 1.5, 0.04)
    assert r["ok"], r
    wall = b._model.by_guid(r["guid"])
    assert wall.is_a("IfcCurtainWall") and wall.is_a("IfcElement")
    assert wall.Representation is not None
    info = call("curtain_wall_info", r["guid"])
    assert info["ok"] and info["height"] == 3.0 and info["spacing"] == 1.5
    # It is a product on the level and a type exists.
    assert wall.is_a("IfcProduct") and wall.ContainedInStructure[0].RelatingStructure.GlobalId == project["level"]
    assert any(t.Name == "Curtain Wall" for t in b._model.by_type("IfcCurtainWallType"))
    assert not call("create_curtain_wall", project["level"], 0, 0, 0, 0, 3.0)["ok"]


def test_slabs_tilt_and_return_flat(project):
    points = json.dumps([[0, 0], [4, 0], [4, 3], [0, 3]])
    guid = call("create_slab", project["level"], project["slab_type"], points)["guid"]
    base = ifcopenshell.util.placement.get_local_placement(b._model.by_guid(guid).ObjectPlacement)
    assert call("set_slab_slope", json.dumps([guid]), 0.1, 0.0)["ok"]
    tilted = ifcopenshell.util.placement.get_local_placement(b._model.by_guid(guid).ObjectPlacement)
    assert not math.isclose(float(tilted[0][2]), 0.0, abs_tol=1e-6)  # the placement gained a rotation
    assert call("slab_slope", guid)["slope_x"] == pytest.approx(0.1)
    assert call("set_slab_slope", json.dumps([guid]), 0.0, 0.0)["ok"]
    flat = ifcopenshell.util.placement.get_local_placement(b._model.by_guid(guid).ObjectPlacement)
    assert flat == pytest.approx(base, abs=1e-9)


def test_slab_edges_are_members_aggregated_to_the_slab(project):
    points = json.dumps([[0, 0], [4, 0], [4, 3], [0, 3]])
    slab = call("create_slab", project["level"], project["slab_type"], points)["guid"]
    r = call("add_slab_edge", slab, 0.02, 0.2)
    assert r["ok"] and len(r["edges"]) == 4, r
    members = [b._model.by_guid(g) for g in r["edges"]]
    assert all(m.is_a("IfcMember") for m in members)
    assert all(any(rel.RelatingObject.GlobalId == slab for rel in m.Decomposes) for m in members)
    assert all(ifcopenshell.util.element.get_pset(m, "KIMBIM_SlabEdge")["Slab"] == slab for m in members)
