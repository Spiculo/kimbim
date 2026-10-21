# SPDX-License-Identifier: GPL-3.0-or-later
"""D97: curved walls (Archicad's Wall tool, Curved geometry method)."""
import json
import math

import ifcopenshell.validate
import numpy as np
import pytest

from kimbim import app_bridge as b
from kimbim import configure as C


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def project():
    assert call("new_project", "Curved")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    types = {t["name"]: t["guid"] for t in call("wall_types")["types"]}
    return {"level": level, **types}


def mesh(guid):
    meta, verts, tris, cols = b.mesh_elements(json.dumps([guid]))
    return (json.loads(meta)["palette"], np.frombuffer(cols, dtype="<u2"),
            np.frombuffer(verts, dtype="<f4").reshape(-1, 3), np.frombuffer(tris, dtype="<u4").reshape(-1, 3))


def radii(guid, centre=(0.0, 0.0)):
    _, _, v, _ = mesh(guid)
    r = np.hypot(v[:, 0] - centre[0], v[:, 1] - centre[1])
    return float(r.min()), float(r.max()), v


def test_a_curved_wall_follows_its_arc(project):
    # a half circle of radius 5 about the origin, counter-clockwise from (5, 0) through (0, 5) to (-5, 0)
    r = call("create_curved_wall", project["level"], project["Exterior 300"], 5, 0, 0, 5, -5, 0, 3.0, "")
    assert r["ok"], r
    lo, hi, v = radii(r["guid"])
    assert lo == pytest.approx(4.85, abs=0.01) and hi == pytest.approx(5.15, abs=0.01)  # centred on the arc
    assert v[:, 1].min() == pytest.approx(0.0, abs=1e-3) and v[:, 1].max() == pytest.approx(5.15, abs=0.02)
    assert v[:, 2].max() == pytest.approx(3.0, abs=1e-3)
    assert not call("create_curved_wall", project["level"], project["Exterior 300"], 0, 0, 1, 0, 2, 0, 3.0, "")["ok"]


def test_the_reference_line_and_the_sides(project):
    # drawn by its outside face: counter-clockwise, the axis' left is towards the centre, so the body
    # lies inside the drawn arc
    r = call("create_curved_wall", project["level"], project["Exterior 300"], 5, 0, 0, 5, -5, 0, 3.0, "Outside face")
    assert r["ok"], r
    lo, hi, _ = radii(r["guid"])
    assert lo == pytest.approx(4.7, abs=0.01) and hi == pytest.approx(5.0, abs=0.01)
    palette, idx, v, tris = mesh(r["guid"])
    rad = np.hypot(*v[tris].mean(axis=1)[:, :2].T)
    outer = {tuple(palette[i][:3]) for i in idx[rad > 4.99]}
    inner = {tuple(palette[i][:3]) for i in idx[rad < 4.71]}
    assert outer and inner and outer != inner  # each face its own layer's surface
    # a reference change moves the body about the line, as on a straight wall
    assert call("set_element_setting", json.dumps([r["guid"]]), C.GEOMETRY, "Reference line", "Inside face")["ok"]
    lo, hi, _ = radii(r["guid"])
    assert lo == pytest.approx(5.0, abs=0.01) and hi == pytest.approx(5.3, abs=0.01)
    call("undo")
    lo, hi, _ = radii(r["guid"])
    assert hi == pytest.approx(5.0, abs=0.01)


def test_curved_walls_are_valid_ifc_and_move(project):
    r = call("create_curved_wall", project["level"], project["Exterior 300"], 0, 0, 2, 2, 4, 0, 3.0, "")
    assert r["ok"], r
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    assert not logger.statements
    assert call("move_elements", json.dumps([r["guid"]]), 10, 0)["ok"]
    _, _, v = radii(r["guid"])
    assert v[:, 0].min() > 9.5  # the arc went with its placement
    assert call("set_element_setting", json.dumps([r["guid"]]), C.SURFACES, "Reference side", "Steel")["ok"]


def test_straight_only_edits_refuse_curved_walls(project):
    r = call("create_curved_wall", project["level"], project["Exterior 300"], 0, 0, 2, 2, 4, 0, 3.0, "")
    g = r["guid"]
    assert call("set_dimension", json.dumps([g]), "Length", "5")["ok"]  # the end goes round its circle
    dims = {k: e["value"] for k, e in call("properties_multi", json.dumps([g]))["psets"]["Dimensions"].items()}
    assert dims["Length"] == pytest.approx(5.0, abs=1e-6)
    assert call("set_dimension", json.dumps([g]), "Length", str(math.pi * 2))["ok"]
    assert not call("set_dimension", json.dumps([g]), "Length", "13")["ok"]  # more than the whole circle
    assert not call("split_element", g, 2, 2)["ok"]
    # height works, and the length shown is the arc's (a half circle of radius 2)
    assert call("set_dimension", json.dumps([g]), "Height", "4.5")["ok"]
    _, _, v = radii(g, (2.0, 0.0))
    assert v[:, 2].max() == pytest.approx(4.5, abs=1e-3)
    dims = {k: e["value"] for k, e in call("properties_multi", json.dumps([g]))["psets"]["Dimensions"].items()}
    assert dims["Length"] == pytest.approx(math.pi * 2, abs=1e-3)
    # a straight wall drawn to its end does not join it (the joins are straight)
    w = call("create_wall", project["level"], project["Exterior 300"], 4, 0, 8, 0, 3.0, g, "")
    assert w["ok"], w
    # slanting skips it
    r = call("set_element_setting", json.dumps([g]), C.GEOMETRY, "Slant angle", "80")
    _, _, v = radii(g, (2.0, 0.0))
    assert v[:, 2].max() == pytest.approx(4.5, abs=1e-3)


def test_a_double_slanted_walls_height_changes(project):
    w = call("create_wall", project["level"], project["Exterior 300"], 0, 0, 5, 0, 3.0, "", "", "Outside face")["guid"]
    assert call("set_element_setting", json.dumps([w]), C.GEOMETRY, "Opposite slant angle", "88")["ok"]
    assert call("set_dimension", json.dumps([w]), "Height", "4")["ok"]  # 4 m at 88 degrees: still apart
    _, _, v, _ = mesh(w)
    assert v[:, 2].max() == pytest.approx(4.0, abs=1e-3)
    assert v[:, 0].max() - v[:, 0].min() == pytest.approx(5.0, abs=1e-3)  # still 5 m long


def corner(project, reference="Outside face"):
    t = project["Exterior 300"]
    a = call("create_wall", project["level"], t, 0, 0, 6, 0, 3.0, "", "", reference)["guid"]
    b2 = call("create_wall", project["level"], t, 6, 0, 6, 5, 3.0, a, "", reference)["guid"]
    return a, b2


def test_filleting_a_wall_corner(project):
    """D97: Archicad's Fillet on two walls: both pulled back, a tangent curved wall between them."""
    a, b2 = corner(project)
    r = call("fillet_corners", json.dumps([a, b2]), 2.0, "fillet")
    assert r["ok"], r
    from kimbim import authoring

    assert [list(map(lambda v: round(v, 6), p)) for p in authoring._axis_world(b._model.by_guid(a))] == [[0, 0], [4, 0]]
    assert [round(v, 6) for v in authoring._axis_world(b._model.by_guid(b2))[0]] in ([6, 2], [6, 5])
    arc = r["guid"]
    dims = {k: e["value"] for k, e in call("properties_multi", json.dumps([arc]))["psets"]["Dimensions"].items()}
    assert dims["Length"] == pytest.approx(math.pi, abs=1e-3)  # a quarter circle of radius 2
    lo, hi, _ = radii(arc, (4.0, 2.0))
    # drawn by the outside face (the corner's outside), the body is inside the arc: radii 1.7 to 2.0
    assert lo == pytest.approx(1.7, abs=0.01) and hi == pytest.approx(2.0, abs=0.01)
    call("undo")
    assert [round(v, 6) for v in authoring._axis_world(b._model.by_guid(a))[1]] == [6, 0]
    assert len([e for e in b._model.by_type("IfcWall")]) == 2


def test_chamfering_a_wall_corner(project):
    a, b2 = corner(project)
    r = call("fillet_corners", json.dumps([a, b2]), 1.0, "chamfer")
    assert r["ok"], r
    from kimbim import authoring

    new = authoring._axis_world(b._model.by_guid(r["guid"]))
    assert sorted(tuple(round(v, 6) for v in p) for p in new) == [(5.0, 0.0), (6.0, 1.0)]
    assert not call("fillet_corners", json.dumps([a, b2]), 50.0, "fillet")["ok"]  # too big
    assert not call("fillet_corners", json.dumps([a]), 1.0, "fillet")["ok"]  # one wall


def _radial_hits(guid, centre, angle, z=1.0):
    """Where a ray from the arc's centre outwards at `angle` meets the wall's faces (radius, metres)."""
    _, _, v, t = mesh(guid)
    p = np.array([centre[0], centre[1], z])
    d = np.array([math.cos(angle), math.sin(angle), 0.0])
    out = []
    for a, b_, c_ in v[t]:
        e1, e2 = b_ - a, c_ - a
        h = np.cross(d, e2)
        det = e1 @ h
        if abs(det) < 1e-12:
            continue
        f = 1 / det
        s = p - a
        u = f * (s @ h)
        q = np.cross(s, e1)
        w = f * (d @ q)
        if u < 0 or w < 0 or u + w > 1:
            continue
        if f * (e2 @ q) > 1e-6:
            out.append(round(float(f * (e2 @ q)), 3))
    return sorted(set(out))


@pytest.mark.parametrize("reference", ["Outside face", "Centre", "Inside face"])
def test_doors_and_windows_in_curved_walls(project, reference):
    """D97: a straight door or window square to the arc, its opening through the curved body."""
    r = call("create_curved_wall", project["level"], project["Exterior 300"], 5, 0, 0, 5, -5, 0, 3.0, reference)
    g = r["guid"]
    door = call("opening_types", "door")["types"][0]
    along = math.pi * 5 / 2  # the middle of the half circle: the top, at (0, 5)
    d = call("insert_opening", "door", g, door["guid"], along, door["width"], door["height"], door["sill"])
    assert d["ok"], d
    assert _radial_hits(g, (0, 0), math.pi / 2) == []  # nothing left in the doorway
    for edge in (-1, 1):  # nor at its sides, where the arc bends away from the straight door
        # (rays from the centre spread: within the straight door's width out to the outer face, 5.3 m)
        assert _radial_hits(g, (0, 0), math.pi / 2 + edge * math.asin((door["width"] / 2 - 0.02) / 5.3)) == []
    assert len(_radial_hits(g, (0, 0), math.pi / 4)) == 2  # the wall beside it is solid
    from kimbim import authoring

    info = authoring._opening_info(b._model.by_guid(d["guid"]))
    assert info[2] == pytest.approx(along, abs=1e-6)
    assert call("edit_opening", d["guid"], 3.0, door["width"], door["height"], door["sill"])["ok"]
    assert authoring._opening_info(b._model.by_guid(d["guid"]))[2] == pytest.approx(3.0, abs=1e-6)
    assert not call("insert_opening", "door", g, door["guid"], 0.1, door["width"], door["height"], door["sill"])["ok"]
    w = call("opening_types", "window")["types"][0]
    assert call("insert_opening", "window", g, w["guid"], 12.0, w["width"], w["height"], w["sill"])["ok"]
    # a reference change takes them along
    assert call("set_element_setting", json.dumps([g]), C.GEOMETRY, "Reference line", "Core centre")["ok"]
    assert _radial_hits(g, (0, 0), 3.0 / 5) == []


def test_snap_data_describes_the_arc(project):
    r = call("create_curved_wall", project["level"], project["Exterior 300"], 5, 0, 0, 5, -5, 0, 3.0, "")
    w = next(x for x in call("snap_data", project["level"])["walls"] if x["guid"] == r["guid"])
    assert w["arc"]["cx"] == pytest.approx(0) and w["arc"]["cy"] == pytest.approx(0) and w["arc"]["r"] == pytest.approx(5)
    assert w["arc"]["a0"] == pytest.approx(0) and w["arc"]["sweep"] == pytest.approx(math.pi)


def test_stretching_a_curved_wall_keeps_its_circle(project):
    """D97: an end dragged goes round the wall's circle (Archicad); doors stay where they were."""
    from kimbim import authoring

    r = call("create_curved_wall", project["level"], project["Exterior 300"], 5, 0, 0, 5, -5, 0, 3.0, "")
    g = r["guid"]
    door = call("opening_types", "door")["types"][0]
    d = call("insert_opening", "door", g, door["guid"], math.pi * 2.5, door["width"], door["height"], door["sill"])["guid"]
    # the end at (-5, 0) dragged towards (-3, -6): it goes round to the circle's point that way
    s = call("set_wall_axis", g, 5, 0, -3, -6)
    assert s["ok"], s
    lo, hi, v = radii(g)
    assert lo == pytest.approx(4.85, abs=0.01) and hi == pytest.approx(5.15, abs=0.01)
    assert v[:, 1].min() < -3.5  # it now runs on past (-5, 0) and round underneath
    dims = {k: e["value"] for k, e in call("properties_multi", json.dumps([g]))["psets"]["Dimensions"].items()}
    expected = 5 * (math.pi + math.atan2(6, 3))  # counter-clockwise from (5, 0) round to the direction (-3, -6)
    assert dims["Length"] == pytest.approx(expected, abs=1e-3)
    assert authoring._opening_info(b._model.by_guid(d))[2] == pytest.approx(math.pi * 2.5, abs=1e-6)  # same place
    # the start dragged past the door: refused, the wall unchanged
    assert not call("set_wall_axis", g, 0, 5.5, -3, -6)["ok"]
    # both ends moved alike: the wall moves
    from kimbim import curved_walls

    a, e = curved_walls.ends_world(b._model.by_guid(g))
    assert call("set_wall_axis", g, a[0] + 1, a[1], e[0] + 1, e[1])["ok"]
    _, _, v = radii(g, (1, 0))
    assert np.hypot(v[:, 0] - 1, v[:, 1]).max() == pytest.approx(5.15, abs=0.01)
