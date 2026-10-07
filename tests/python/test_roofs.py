# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice 19: roofs after Archicad's Roof tool — flat, or pitched from a footprint with a slope per edge
(shed, gable, hip); walls trimmed to the roof (Archicad: Trim to Roof), following it when it moves."""
import json
import math

import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.validate
import numpy as np
import pytest

from kimcad import app_bridge as b

RECT = [[0, 0], [10, 0], [10, 8], [0, 8]]
PITCH = 30.0
RISE = math.tan(math.radians(PITCH)) * 4  # from the eaves to the ridge across 8 m


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def valid():
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    return logger.statements


def mesh(guid):
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    shape = ifcopenshell.geom.create_shape(s, b._model.by_guid(guid))
    v = np.array(shape.geometry.verts).reshape(-1, 3)
    f = np.array(shape.geometry.faces).reshape(-1, 3)
    return v, f


def volume(guid):
    v, f = mesh(guid)
    return abs(sum(np.dot(v[a], np.cross(v[b_], v[c])) for a, b_, c in f) / 6)


@pytest.fixture
def level():
    assert call("new_project", "Roofs")["ok"]
    return call("storeys")["storeys"][0]["guid"]


def test_flat_roof(level):
    r = call("create_roof", level, json.dumps(RECT), "flat", 0, 0.25, 3.0, "")
    assert r["ok"], r
    roof = b._model.by_guid(r["guid"])
    assert roof.is_a("IfcRoof") and roof.PredefinedType == "FLAT_ROOF"
    assert ifcopenshell.util.element.get_container(roof).GlobalId == level
    assert volume(r["guid"]) == pytest.approx(80 * 0.25, rel=1e-4)
    v, _ = mesh(r["guid"])
    assert v[:, 2].min() == pytest.approx(3.0, abs=1e-6) and v[:, 2].max() == pytest.approx(3.25, abs=1e-6)
    assert valid() == []


@pytest.mark.parametrize("kind,predefined,rise", [("hip", "HIP_ROOF", RISE), ("gable", "GABLE_ROOF", RISE),
                                                  ("shed", "SHED_ROOF", 2 * RISE)])
def test_pitched_roofs(level, kind, predefined, rise):
    r = call("create_roof", level, json.dumps(RECT), kind, PITCH, 0.25, 3.0, "")
    assert r["ok"], r
    assert b._model.by_guid(r["guid"]).PredefinedType == predefined
    # A plate of constant vertical thickness: its volume is the footprint area times the thickness.
    assert volume(r["guid"]) == pytest.approx(80 * 0.25, rel=1e-3)
    v, _ = mesh(r["guid"])
    assert v[:, 2].min() == pytest.approx(3.0, abs=1e-4)
    assert v[:, 2].max() == pytest.approx(3.0 + rise + 0.25, abs=1e-4)
    top = v[np.isclose(v[:, 2], v[:, 2].max(), atol=1e-4)]
    ridge = top[:, 0].max() - top[:, 0].min()
    assert ridge == pytest.approx({"hip": 2.0, "gable": 10.0, "shed": 10.0}[kind], abs=1e-4)
    assert valid() == []


def test_slopes_per_edge_and_refusals(level):
    # Archicad's multi-plane roof: one angle per edge, None for a gable end.
    r = call("create_roof", level, json.dumps(RECT), "custom", 0, 0.2, 3.0, json.dumps([30, None, 30, 45]))
    assert r["ok"], r
    assert call("roof_info", r["guid"])["slopes"] == [30, None, 30, 45]
    l_shape = [[0, 0], [10, 0], [10, 4], [4, 4], [4, 8], [0, 8]]
    assert not call("create_roof", level, json.dumps(l_shape), "hip", 30, 0.2, 3.0, "")["ok"]  # pitched: convex outlines
    assert call("create_roof", level, json.dumps(l_shape), "flat", 0, 0.2, 3.0, "")["ok"]
    assert not call("create_roof", level, json.dumps(RECT), "hip", 90, 0.2, 3.0, "")["ok"]  # no vertical planes
    assert not call("create_roof", level, json.dumps(RECT[:2]), "flat", 0, 0.2, 3.0, "")["ok"]


@pytest.fixture
def box(level):
    ext = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")["guid"]
    walls, last = [], ""
    for i in range(4):
        (x1, y1), (x2, y2) = RECT[i], RECT[(i + 1) % 4]
        walls.append(call("create_wall", level, ext, x1, y1, x2, y2, 3.0, last, walls[0] if i == 3 else "")["guid"])
        last = walls[-1]
    eaves = [[-0.5, -0.5], [10.5, -0.5], [10.5, 8.5], [-0.5, 8.5]]  # 0.5 m overhang
    roof = call("create_roof", level, json.dumps(eaves), "gable", PITCH, 0.25, 3.0, "")["guid"]
    return {"level": level, "walls": walls, "roof": roof}


def top(guid):
    return mesh(guid)[0][:, 2].max()


def test_walls_trimmed_to_the_roof(box):
    gable_wall = box["walls"][1]  # x = 10, under the gable end
    eave_wall = box["walls"][0]  # y = 0, under the eaves
    r = call("attach_walls_to_roof", box["roof"], json.dumps(box["walls"]))
    assert r["ok"], r
    # The underside rises from 3 m at the eaves line (y = -0.5) at 30 degrees: at the ridge (y = 4) and at the
    # inner face of the eave wall (y = 0.15).
    slope = math.tan(math.radians(PITCH))
    assert top(gable_wall) == pytest.approx(3.0 + slope * 4.5, abs=1e-3)
    assert top(eave_wall) == pytest.approx(3.0 + slope * (0.15 + 0.5), abs=1e-3)
    assert valid() == []
    # Moving the roof up 1 m: the walls follow in the same undo step.
    assert call("move_elements", json.dumps([box["roof"]]), 0.0, 0.0, 1.0)["ok"]
    assert top(gable_wall) == pytest.approx(4.0 + slope * 4.5, abs=1e-3)
    assert call("undo")["ok"]
    assert top(gable_wall) == pytest.approx(3.0 + slope * 4.5, abs=1e-3)
    # Moving a wall keeps it trimmed to the roof where it now stands.
    assert call("move_elements", json.dumps([gable_wall]), -2.0, 0.0, 0.0)["ok"]
    assert top(gable_wall) == pytest.approx(3.0 + slope * 4.5, abs=1e-3)
    # Detaching (or deleting the roof) leaves plain walls.
    assert call("detach_walls_from_roof", json.dumps([eave_wall]))["ok"]
    assert "BBIM_Boolean" not in ifcopenshell.util.element.get_psets(b._model.by_guid(eave_wall))
    assert call("delete_elements", json.dumps([box["roof"]]))["ok"]
    w = b._model.by_guid(gable_wall)
    assert "KIMCAD_RoofAttach" not in ifcopenshell.util.element.get_psets(w)
    assert valid() == []


def test_roof_in_a_section(box):
    s = call("create_section", -2.0, 4.0, 12.0, 4.0, 5.0, 8.0, -1)["guid"]
    svg = call("generate_drawing", s, "")["svg"]
    assert "IfcRoof" in svg  # the serializer draws the roof
