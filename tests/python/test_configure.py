# SPDX-License-Identifier: GPL-3.0-or-later
"""Wall and element configuration (D97): reference line, flip, slant, surface overrides."""
import json

import numpy as np
import pytest

from kimbim import app_bridge as b
from kimbim import configure as C
from kimbim import materials as M


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def project():
    assert call("new_project", "Casa")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    types = {t["name"]: t["guid"] for t in call("wall_types")["types"]}
    return {"level": level, **types}


def wall(p, reference="", x2=5.0, wtype="Exterior 300"):
    r = call("create_wall", p["level"], p[wtype], 0, 0, x2, 0, 3.0, "", "", reference)
    assert r["ok"], r
    return r["guid"]


def mesh(guid):
    meta, verts, tris, cols = b.mesh_elements(json.dumps([guid]))
    return (json.loads(meta)["palette"], np.frombuffer(cols, dtype="<u2"),
            np.frombuffer(verts, dtype="<f4").reshape(-1, 3), np.frombuffer(tris, dtype="<u4").reshape(-1, 3))


def y_range(guid):
    _, _, v, _ = mesh(guid)
    return round(float(v[:, 1].min()), 4), round(float(v[:, 1].max()), 4)


def props(guid):
    return call("properties_multi", json.dumps([guid]))["psets"]


@pytest.mark.parametrize("reference,expected", [
    ("Outside face", (0.0, 0.3)), ("Centre", (-0.15, 0.15)), ("Inside face", (-0.3, 0.0)),
    ("Core outside", (-0.18, 0.12)), ("Core centre", (-0.24, 0.06)), ("Core inside", (-0.3, 0.0)),
])
def test_new_walls_sit_by_their_reference_line(project, reference, expected):
    # Exterior 300: brick 100 + insulation 80 + block 120 (the core: the thickest)
    g = wall(project, reference)
    assert y_range(g) == pytest.approx(expected, abs=1e-4)
    assert props(g)[C.GEOMETRY]["Reference line"]["value"] == reference


def test_no_reference_keeps_the_centre_and_is_recognised(project):
    g = wall(project)
    assert y_range(g) == pytest.approx((-0.15, 0.15), abs=1e-4)
    geometry = props(g)[C.GEOMETRY]
    assert geometry["Reference line"]["value"] == "Centre"
    assert geometry["Reference line"]["choices"][:3] == ["Outside face", "Centre", "Inside face"]
    assert geometry["Slant angle"]["value"] == pytest.approx(90.0)


def test_changing_the_reference_line_moves_the_body_and_undoes(project):
    g = wall(project, "Outside face")
    r = call("set_element_setting", json.dumps([g]), C.GEOMETRY, "Reference line", "Inside face")
    assert r["ok"], r
    assert y_range(g) == pytest.approx((-0.3, 0.0), abs=1e-4)
    call("undo")
    assert y_range(g) == pytest.approx((0.0, 0.3), abs=1e-4)


def test_flip_mirrors_the_layers_about_the_line(project):
    g = wall(project, "Outside face")
    palette, idx, v, t = mesh(g)
    brick = M.CATALOGUE["Brick"]["colour"]

    def brick_side():
        palette, idx, v, t = mesh(g)
        n = M._normals(v.reshape(-1), t.reshape(-1))
        faces = [i for i in range(len(idx)) if idx[i] != M.NO_COLOUR and M._hex(palette[idx[i]][:3]) == brick
                 and abs(n[i][1]) > 0.7]
        return {round(float(v[t[i]][:, 1].mean()), 3) for i in faces}

    assert brick_side() == {0.0}
    r = call("flip_walls", json.dumps([g]))
    assert r["ok"], r
    assert y_range(g) == pytest.approx((-0.3, 0.0), abs=1e-4)
    assert brick_side() == {0.0}  # the outside skin stays on the line, the body went to the other side
    assert props(g)[C.GEOMETRY]["Reference line"]["value"] == "Outside face"


def test_flipped_wall_layer_bands_and_cut_follow(project):
    from kimbim import graphics

    g = wall(project, "Outside face")
    call("flip_walls", json.dumps([g]))
    bands = graphics.resolve()["layers"][g]
    assert bands["bounds"] == pytest.approx([0.0, -0.1, -0.18, -0.3])


def test_composite_change_keeps_the_remembered_reference(project):
    g = wall(project, "Outside face")
    comp = next(c for c in call("materials_state")["composites"] if c["name"] == "Exterior 300")
    layers = [dict(l) for l in comp["layers"]]
    layers[1]["thickness"] = 0.18
    assert call("apply_materials", json.dumps({"composites": [{**comp, "layers": layers}]}))["ok"]
    assert y_range(g) == pytest.approx((0.0, 0.4), abs=1e-4)


def test_slanted_wall(project):
    g = wall(project, "Centre")
    r = call("set_element_setting", json.dumps([g]), C.GEOMETRY, "Slant angle", "80")
    assert r["ok"], r
    assert props(g)[C.GEOMETRY]["Slant angle"]["value"] == pytest.approx(80.0)
    _, _, v, _ = mesh(g)
    top = v[v[:, 2] > 2.99]
    lean = 3.0 * np.tan(np.radians(10))
    assert top[:, 1].min() == pytest.approx(-0.15 + lean, abs=0.02)  # the top leans to +Y
    assert v[:, 2].max() == pytest.approx(3.0, abs=1e-3)  # the height stays
    assert not call("set_element_setting", json.dumps([g]), C.GEOMETRY, "Slant angle", "20")["ok"]


def test_surface_overrides_paint_one_side(project):
    g = wall(project, "Outside face")
    st = props(g)[C.SURFACES]
    assert list(st) == list(C.WALL_SIDES) and st["Reference side"]["value"] == C.FROM_MATERIAL
    assert "Paint - white" in st["Edges"]["choices"]
    r = call("set_element_setting", json.dumps([g]), C.SURFACES, "Opposite side", "Paint - white")
    assert r["ok"], r
    palette, idx, v, t = mesh(g)
    n = M._normals(v.reshape(-1), t.reshape(-1))
    inside = idx[n[:, 1] > 0.7]
    assert {M._hex(palette[i][:3]) for i in inside} == {M.CATALOGUE["Paint - white"]["colour"]}
    outside = idx[n[:, 1] < -0.7]
    assert {M._hex(palette[i][:3]) for i in outside} == {M.CATALOGUE["Brick"]["colour"]}
    r = call("set_element_setting", json.dumps([g]), C.SURFACES, "Opposite side", C.FROM_MATERIAL)
    assert r["ok"]
    assert props(g)[C.SURFACES]["Opposite side"]["value"] == C.FROM_MATERIAL


def test_other_elements_override_all_faces(project):
    types = call("column_types")["types"]
    c = call("create_column", project["level"], types[0]["guid"], 1, 1, 3.0)["guid"]
    assert list(props(c)[C.SURFACES]) == ["All faces"]
    assert call("set_element_setting", json.dumps([c]), C.SURFACES, "All faces", "Steel")["ok"]
    palette, idx, _, _ = mesh(c)
    assert {M._hex(palette[i][:3]) for i in idx} == {M.CATALOGUE["Steel"]["colour"]}
    assert not call("set_element_setting", json.dumps([c]), C.SURFACES, "Top", "Steel")["ok"]
    assert not call("set_element_setting", json.dumps([c]), C.SURFACES, "All faces", "Nope")["ok"]


def test_wall_reference_setting_is_validated(project):
    from kimbim import settings

    assert settings._error("wall_reference_line", "Core centre") is None
    assert settings._error("wall_reference_line", "Middle")
    assert json.loads(b.wall_options())["default"] == "Outside face"
    assert not call("create_wall", project["level"], project["Generic 200"], 0, 0, 1, 0, 3.0, "", "", "Middle")["ok"]


def test_wall_types_tell_the_preview_where_the_body_is(project):
    t = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")
    assert t["centres"]["Outside face"] == pytest.approx(0.15)
    assert t["centres"]["Centre"] == pytest.approx(0.0)
    assert t["centres"]["Inside face"] == pytest.approx(-0.15)
    assert t["centres"]["Core centre"] == pytest.approx(-0.09)


def test_objects_fall_onto_the_slab_below_with_gravity(project):
    slab_type = call("slab_types")["types"][0]["guid"]
    r = call("create_slab", project["level"], slab_type, json.dumps([[0, 0], [4, 0], [4, 4], [0, 4]]), 0.45)
    assert r["ok"], r
    key = call("library_objects")["objects"][0]["id"]
    on = call("place_object", project["level"], key, "", 1.0, 1.0, 0.0, "1")
    off = call("place_object", project["level"], key, "", 1.0, 1.0, 0.0, "")
    outside = call("place_object", project["level"], key, "", 9.0, 9.0, 0.0, "1")
    assert on["ok"] and off["ok"] and outside["ok"]

    def z(guid):
        _, _, v, _ = mesh(guid)
        return round(float(v[:, 2].min()), 3)

    assert z(on["guid"]) == pytest.approx(0.45, abs=1e-3)
    assert z(off["guid"]) == pytest.approx(0.0, abs=1e-3)
    assert z(outside["guid"]) == pytest.approx(0.0, abs=1e-3)  # nothing under it: the level


def test_objects_have_materials_per_part(project):
    from kimbim import library

    table = call("place_object", project["level"], "table", "", 1.0, 1.0, 0.0, "")
    assert table["ok"], table
    palette, idx, v, t = mesh(table["guid"])
    looks = {M._hex(palette[i][:3]) for i in set(idx.tolist())}
    assert looks == {M.CATALOGUE["Timber - finish"]["colour"], M.CATALOGUE["Steel"]["colour"]}
    group = props(table["guid"])[library.PARAMETERS]
    assert group["Legs material"]["value"] == "Steel" and "Aluminium" in group["Legs material"]["choices"]
    r = call("set_object_parameter", json.dumps([table["guid"]]), "Legs material", "Aluminium", "")
    assert r["ok"], r
    palette, idx, _, _ = mesh(table["guid"])
    assert M.CATALOGUE["Aluminium"]["colour"] in {M._hex(palette[i][:3]) for i in set(idx.tolist())}
    assert not call("set_object_parameter", json.dumps([table["guid"]]), "Legs material", "Unobtainium", "")["ok"]
    wc = call("place_object", project["level"], "wc", "", 3.0, 1.0, 0.0, "")
    palette, idx, _, _ = mesh(wc["guid"])
    assert {M._hex(palette[i][:3]) for i in set(idx.tolist())} == {M.CATALOGUE["Porcelain"]["colour"]}
    listing = next(o for o in call("library_objects")["objects"] if o["id"] == "chair")
    kinds = {p["key"]: p["kind"] for p in listing["params"]}
    assert kinds["mat_frame"] == "material" and kinds["mat_seat"] == "material"
