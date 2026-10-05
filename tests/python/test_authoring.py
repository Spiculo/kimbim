# SPDX-License-Identifier: GPL-3.0-or-later
"""Modeling in the app bridge (M3, Slice 4): new project, levels, layered walls, joins, live geometry deltas."""
import json

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import ifcopenshell.util.unit
import numpy as np
import pytest

from kimcad import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def volume(guid):
    s = ifcopenshell.geom.settings()
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(s, b._model.by_guid(guid)).geometry)


def bbox(guid):
    meta, verts, _ = b.mesh_elements(json.dumps([guid]))
    v = np.frombuffer(verts, dtype="<f4").reshape(-1, 3)
    return v.min(axis=0), v.max(axis=0)


@pytest.fixture
def project():
    assert call("new_project", "Casa")["ok"]
    level1 = call("storeys")["storeys"][0]
    types = {t["name"]: t for t in call("wall_types")["types"]}
    return {"level": level1["guid"], "generic": types["Generic 200"]["guid"], "ext": types["Exterior 300"]["guid"]}


def wall(p, x1, y1, x2, y2, start="", end="", level=None, wtype=None, height=3.0):
    r = call("create_wall", level or p["level"], wtype or p["ext"], x1, y1, x2, y2, height, start, end)
    assert r["ok"], r
    return r


def test_new_project_is_ifc4_in_millimetres_with_one_level():
    assert call("new_project", "Casa")["ok"]
    assert b._model.schema == "IFC4"
    assert ifcopenshell.util.unit.calculate_unit_scale(b._model) == pytest.approx(0.001)
    assert [s["name"] for s in call("storeys")["storeys"]] == ["Level 1"]
    assert call("state") == {**call("state"), "dirty": False, "can_undo": False, "path": ""}
    assert b._model.by_type("IfcProject")[0].Name == "Casa"


def test_levels_are_sorted_by_elevation_and_undoable(project):
    assert call("add_storey", "Level 3", 6.0)["ok"]
    assert call("add_storey", "Level 2", 3.0)["ok"]
    s = call("storeys")["storeys"]
    assert [(x["name"], x["elevation"]) for x in s] == [("Level 1", 0.0), ("Level 2", 3.0), ("Level 3", 6.0)]
    call("undo")
    assert len(call("storeys")["storeys"]) == 2


def test_default_wall_types_are_created_once_with_layer_thickness(project):
    types = call("wall_types")["types"]
    assert {t["name"]: round(t["thickness"], 4) for t in types} == {"Generic 200": 0.2, "Exterior 300": 0.3}
    assert len(b._model.by_type("IfcWallType")) == 2
    assert not call("state")["can_undo"]  # creating the library defaults is not a user action


def test_wall_size_position_and_type(project):
    r = wall(project, 1.0, 2.0, 6.0, 2.0)
    lo, hi = bbox(r["guid"])
    assert hi - lo == pytest.approx([5.0, 0.3, 3.0], abs=1e-3)
    assert lo[0] == pytest.approx(1.0, abs=1e-3) and lo[2] == pytest.approx(0.0, abs=1e-3)
    w = b._model.by_guid(r["guid"])
    assert w.is_a("IfcWall") and ifcopenshell.util.element.get_type(w).Name == "Exterior 300"
    assert ifcopenshell.util.element.get_container(w).GlobalId == project["level"]


def test_walls_on_level_2_sit_at_its_elevation(project):
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    r = wall(project, 0, 0, 4, 0, level=l2)
    lo, hi = bbox(r["guid"])
    assert lo[2] == pytest.approx(3.0, abs=1e-3) and hi[2] == pytest.approx(6.0, abs=1e-3)
    assert ifcopenshell.util.element.get_container(b._model.by_guid(r["guid"])).GlobalId == l2


def test_metre_unit_files_get_the_same_wall(tmp_path):
    from kimcad.testing import build_model

    f = build_model(walls=0)
    import ifcopenshell.api.unit

    ifcopenshell.api.unit.assign_unit(f, length={"is_metric": True, "raw": "METRES"})
    assert ifcopenshell.util.unit.calculate_unit_scale(f) == pytest.approx(1.0)
    path = tmp_path / "m.ifc"
    f.write(str(path))
    call("open_model", str(path))
    level = call("storeys")["storeys"][0]["guid"]
    gen = next(t for t in call("wall_types")["types"] if t["name"] == "Generic 200")
    assert gen["thickness"] == pytest.approx(0.2)
    r = call("create_wall", level, gen["guid"], 0, 0, 3, 0, 2.5, "", "")
    lo, hi = bbox(r["guid"])
    assert hi - lo == pytest.approx([3.0, 0.2, 2.5], abs=1e-3)


def test_l_join_trims_the_corner(project):
    a = wall(project, 0, 0, 5, 0)
    b_ = wall(project, 5, 0, 5, 4, start=a["guid"])
    # Centred 300 mm walls: joined, the outer corner is filled and the inner overlap removed, so
    # the total is exactly 2 x 0.3 x 3 x (5 + 4) / 2 = 8.1 m3; unjoined, the outer corner is empty.
    assert volume(a["guid"]) + volume(b_["guid"]) == pytest.approx(8.1, abs=1e-3)
    (alo, ahi), (blo, bhi) = bbox(a["guid"]), bbox(b_["guid"])
    assert ahi[0] == pytest.approx(5.15, abs=1e-3) or blo[1] == pytest.approx(-0.15, abs=1e-3)
    rels = b._model.by_type("IfcRelConnectsPathElements")
    assert len(rels) == 1


def test_t_join_onto_the_middle_of_a_wall(project):
    a = wall(project, 0, 0, 6, 0)
    t = wall(project, 3, 4, 3, 0, end=a["guid"])
    rel = b._model.by_type("IfcRelConnectsPathElements")[0]
    assert "ATPATH" in (rel.RelatingConnectionType, rel.RelatedConnectionType)
    assert volume(a["guid"]) == pytest.approx(0.3 * 3 * 6, abs=1e-3)  # the through-wall is not cut
    assert volume(t["guid"]) == pytest.approx(0.3 * 3 * (4 - 0.15), abs=1e-3)  # the T stops at its face


def test_zero_length_wall_changes_nothing(project):
    r = call("create_wall", project["level"], project["ext"], 1, 1, 1, 1, 3.0, "", "")
    assert not r["ok"]
    assert not call("state")["can_undo"]


def test_geometry_deltas_for_create_undo_redo(project):
    a = wall(project, 0, 0, 5, 0)
    assert a["geometry"] == {"changed": [a["guid"]], "removed": []}
    b_ = wall(project, 5, 0, 5, 4, start=a["guid"])
    assert sorted(b_["geometry"]["changed"]) == sorted([a["guid"], b_["guid"]])  # the neighbour changed too
    u = call("undo")
    assert u["geometry"] == {"changed": [a["guid"]], "removed": [b_["guid"]]}
    assert volume(a["guid"]) == pytest.approx(4.5, abs=1e-3)
    r = call("redo")
    assert sorted(r["geometry"]["changed"]) == sorted([a["guid"], b_["guid"]]) and r["geometry"]["removed"] == []


def test_property_edits_report_no_geometry(project):
    a = wall(project, 0, 0, 5, 0)
    r = call("set_name", json.dumps([a["guid"]]), "Muro")
    assert r["geometry"] == {"changed": [], "removed": []}


def test_delete_regenerates_the_neighbour(project):
    a = wall(project, 0, 0, 5, 0)
    b_ = wall(project, 5, 0, 5, 4, start=a["guid"])
    r = call("delete_elements", json.dumps([b_["guid"]]))
    assert r["ok"] and r["removed"] == 1
    assert r["geometry"] == {"changed": [a["guid"]], "removed": [b_["guid"]]}
    assert volume(a["guid"]) == pytest.approx(4.5, abs=1e-3)
    assert not b._model.by_type("IfcRelConnectsPathElements")


def test_snap_data_lists_wall_axes_per_level(project):
    a = wall(project, 1, 1, 4, 1)
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    wall(project, 0, 0, 2, 0, level=l2)
    walls = call("snap_data", project["level"])["walls"]
    assert len(walls) == 1
    w = walls[0]
    assert w["guid"] == a["guid"] and w["thickness"] == pytest.approx(0.3)
    assert [w["x1"], w["y1"], w["x2"], w["y2"]] == pytest.approx([1, 1, 4, 1], abs=1e-6)


def test_mesh_elements_matches_the_chunk_format(project):
    a = wall(project, 0, 0, 5, 0)
    meta, verts, tris = b.mesh_elements(json.dumps([a["guid"], "not-a-guid"]))
    m = json.loads(meta)
    assert m["guids"] == [a["guid"]] and m["types"] == ["IfcWall"]
    assert m["voff"][-1] * 12 == len(verts) and m["toff"][-1] * 12 == len(tris)
    assert b.mesh_elements(json.dumps(["not-a-guid"])) is None
