# SPDX-License-Identifier: GPL-3.0-or-later
"""Surfaces, building materials and composites (D96): storage, the dialog's edits, 3D face colours."""
import json
import struct

import ifcopenshell
import ifcopenshell.api.material
import ifcopenshell.api.root
import ifcopenshell.util.element
import ifcopenshell.validate
import numpy as np
import pytest

from kimbim import app_bridge as b
from kimbim import materials as M
from kimbim.testing import _set_owner


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def project():
    assert call("new_project", "Casa")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    types = {t["name"]: t["guid"] for t in call("wall_types")["types"]}
    return {"level": level, **types}


def wall(p, wtype="Exterior 300", x2=5.0):
    r = call("create_wall", p["level"], p[wtype], 0, 0, x2, 0, 3.0)
    assert r["ok"], r
    return r["guid"]


def colours(guid):
    meta, verts, tris, cols = b.mesh_elements(json.dumps([guid]))
    meta = json.loads(meta)
    idx = np.frombuffer(cols, dtype="<u2")
    v = np.frombuffer(verts, dtype="<f4").reshape(-1, 3)
    t = np.frombuffer(tris, dtype="<u4").reshape(-1, 3)
    return meta["palette"], idx, v, t


def hexes(palette, idx):
    return {M._hex(palette[i][:3]) if i != M.NO_COLOUR else None for i in idx}


def state():
    return call("materials_state")


def by_name(items, name):
    return next(i for i in items if i["name"] == name)


# ---------------------------------------------------------------- catalogue and storage

def test_default_wall_types_use_catalogue_materials_with_surfaces(project):
    st = state()
    brick = by_name(st["materials"], "Brick")
    assert brick["surface"] == "Brick" and brick["colour"] == M.CATALOGUE["Brick"]["colour"]
    assert brick["pen"] == 12 and brick["pattern"] == "Brick" and brick["priority"] == 600
    assert brick["density"] == pytest.approx(1800)
    comp = by_name(st["composites"], "Exterior 300")
    assert [l["material"] for l in comp["layers"]] == ["Brick", "Insulation", "Block"]
    assert [l["thickness"] for l in comp["layers"]] == pytest.approx([0.1, 0.08, 0.12])


def test_ensure_reuses_and_creates():
    f = ifcopenshell.file(schema="IFC4")
    a = M.ensure("Concrete", f)
    assert M.ensure("Concrete", f) == a
    assert M.surface_look(M.surface_of(a))["colour"] == M.CATALOGUE["Concrete"]["colour"]
    odd = M.ensure("Unobtainium", f)  # not in the catalogue: a bare material
    assert M.surface_of(odd) is None


def test_ifc2x3_materials_get_surfaces_through_style_assignments():
    f = ifcopenshell.file(schema="IFC2X3")
    _set_owner(f)
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    m = M.ensure("Glass", f)
    look = M.surface_look(M.surface_of(m))
    assert look["colour"] == M.CATALOGUE["Glass"]["colour"] and look["transparency"] == pytest.approx(0.6)
    assert M.properties(m)["pen"] == 12


def test_surface_look_reads_shine_and_reflectance():
    f = ifcopenshell.file(schema="IFC4")
    s = M.make_surface(f, "Chrome", {"colour": "#c0c0c0", "transparency": 0.25, "shine": 0.8, "reflectance": "METAL"})
    look = M.surface_look(s)
    assert look == {"colour": "#c0c0c0", "transparency": pytest.approx(0.25), "shine": pytest.approx(0.8),
                    "reflectance": "METAL"}


def test_core_layer_prefers_load_bearing_else_thickest():
    f = ifcopenshell.file(schema="IFC4")
    ls = ifcopenshell.api.material.add_material_set(f, name="X", set_type="IfcMaterialLayerSet")
    thin = ifcopenshell.api.material.add_layer(f, layer_set=ls, material=M.ensure("Concrete", f))
    thick = ifcopenshell.api.material.add_layer(f, layer_set=ls, material=M.ensure("Insulation", f))
    thin.LayerThickness, thick.LayerThickness = 100.0, 200.0
    assert M.core_layer(ls) == thick
    thin.Category = M.CORE
    assert M.core_layer(ls) == thin


# ---------------------------------------------------------------- 3D colours

def test_layered_wall_sides_show_outer_layers_and_edges_the_core(project):
    g = wall(project)
    palette, idx, v, t = colours(g)
    w = b._model.by_guid(g)
    usage = ifcopenshell.util.element.get_material(w, should_skip_usage=False)
    axis = M._layer_axis(w, usage)
    n = M._normals(v.reshape(-1), t.reshape(-1)) @ axis
    first, last = M.CATALOGUE["Brick"]["colour"], M.CATALOGUE["Block"]["colour"]
    core = M.CATALOGUE[M.core_layer(usage.ForLayerSet).Material.Name]["colour"]
    assert hexes(palette, idx[n < -0.7]) == {first}
    assert hexes(palette, idx[n > 0.7]) == {last}
    assert hexes(palette, idx[np.abs(n) <= 0.7]) == {core}


def test_iterator_styles_win_for_non_layered_elements(model, tmp_path):
    # build_model's walls have no materials: their faces have no colour (class colour in the app)
    p = tmp_path / "m.ifc"
    model.write(str(p))
    assert json.loads(b.open_model(str(p)))["ok"]
    g = model.by_type("IfcWall")[0].GlobalId
    palette, idx, _, _ = colours(g)
    assert set(idx.tolist()) == {M.NO_COLOUR}
    # a building material with a surface colours every face
    f = b._model
    w = f.by_guid(g)
    ifcopenshell.api.material.assign_material(f, products=[w], material=M.ensure("Timber", f))
    palette, idx, _, _ = colours(g)
    assert hexes(palette, idx) == {M.CATALOGUE["Timber"]["colour"]}


def test_glass_carries_its_transparency(project):
    f = b._model
    w = f.by_guid(wall(project, "Generic 200"))
    ifcopenshell.api.material.unassign_material(f, products=[w])
    ifcopenshell.api.material.assign_material(f, products=[w], material=M.ensure("Glass", f))
    palette, idx, _, _ = colours(w.GlobalId)
    assert {palette[i][3] for i in idx} == {0.6}


# ---------------------------------------------------------------- the dialog's edits

def test_editing_a_surface_recolours_its_users_and_undoes(project):
    g = wall(project)
    brick = by_name(state()["surfaces"], "Brick")
    r = call("apply_materials", json.dumps({"surfaces": [{**brick, "colour": "#102030"}]}))
    assert r["ok"], r
    assert g in r["geometry"]["changed"]
    palette, idx, _, _ = colours(g)
    assert "#102030" in hexes(palette, idx)
    call("undo")
    palette, idx, _, _ = colours(g)
    assert "#102030" not in hexes(palette, idx)


def test_new_material_with_fields_and_rename(project):
    r = call("apply_materials", json.dumps({"materials": [{
        "name": "Rammed earth", "surface": "Soil", "pen": 15, "bg": 1, "pattern": "Diagonal", "priority": 700,
        "identifier": "RE-1", "manufacturer": "Local", "category": "Earth", "description": "Pisé",
        "density": 1900, "conductivity": 1.1, "heat": 900}]}))
    assert r["ok"], r
    m = by_name(state()["materials"], "Rammed earth")
    assert (m["surface"], m["pen"], m["bg"], m["pattern"], m["priority"], m["identifier"], m["manufacturer"],
            m["category"], m["description"]) == ("Soil", 15, 1, "Diagonal", 700, "RE-1", "Local", "Earth", "Pisé")
    assert (m["density"], m["conductivity"], m["heat"]) == pytest.approx((1900, 1.1, 900))
    r = call("apply_materials", json.dumps({"materials": [{**m, "name": "Pisé"}]}))
    assert r["ok"], r
    assert by_name(state()["materials"], "Pisé")["key"] == m["key"]


def test_names_must_be_unique(project):
    st = state()
    brick = by_name(st["materials"], "Brick")
    r = call("apply_materials", json.dumps({"materials": [{**brick, "name": "Concrete"}]}))
    assert not r["ok"] and "already" in r["error"]
    assert by_name(state()["materials"], "Brick")  # nothing changed


def test_deleting_a_used_material_replaces_it(project):
    g = wall(project)
    brick = by_name(state()["materials"], "Brick")
    r = call("apply_materials", json.dumps({"deleted": {"materials": [{"key": brick["key"], "replace": "Stone"}]}}))
    assert r["ok"], r
    assert g in r["geometry"]["changed"]
    comp = by_name(state()["composites"], "Exterior 300")
    assert comp["layers"][0]["material"] == "Stone"
    assert not any(m["name"] == "Brick" for m in state()["materials"])


def test_composite_thickness_change_regenerates_walls_and_keeps_centre(project):
    g = wall(project)
    comp = by_name(state()["composites"], "Exterior 300")
    layers = [dict(l) for l in comp["layers"]]
    layers[1]["thickness"] = 0.18  # 300 -> 400 mm
    r = call("apply_materials", json.dumps({"composites": [{**comp, "layers": layers}]}))
    assert r["ok"], r
    assert g in r["geometry"]["changed"]
    _, _, v, _ = colours(g)
    assert v[:, 1].max() - v[:, 1].min() == pytest.approx(0.4, abs=1e-4)
    assert v[:, 1].max() == pytest.approx(0.2, abs=1e-4)  # still centred on the axis


def test_new_composite_and_assign_to_wall(project):
    g = wall(project, "Generic 200")
    r = call("apply_materials", json.dumps({"composites": [{
        "name": "Timber frame", "type": "IfcWallType",
        "layers": [{"material": "Gypsum board", "thickness": 0.015}, {"material": "Timber", "thickness": 0.1, "core": True},
                   {"material": "Gypsum board", "thickness": 0.015}]}]}))
    assert r["ok"], r
    em = call("element_material", g)
    assert em["kind"] == "composite" and "Timber frame" in em["choices"]
    r = call("assign_material", json.dumps([g]), "composite", "Timber frame")
    assert r["ok"], r
    assert call("element_material", g)["name"] == "Timber frame"
    _, _, v, _ = colours(g)
    assert v[:, 1].max() - v[:, 1].min() == pytest.approx(0.13, abs=1e-4)
    assert [t["name"] for t in call("wall_types")["types"]].count("Timber frame") == 1


def test_composite_for_the_wrong_class_is_refused(project):
    g = wall(project)
    slab_comp = next(c for c in state()["composites"] if c["type"] == "IfcSlabType") if any(
        c["type"] == "IfcSlabType" for c in state()["composites"]) else None
    if slab_comp is None:
        call("slab_types")
        slab_comp = next(c for c in state()["composites"] if c["type"] == "IfcSlabType")
    r = call("assign_material", json.dumps([g]), "composite", slab_comp["name"])
    assert not r["ok"]


def test_assign_building_material_to_a_column(project):
    types = call("column_types")["types"]
    c = call("create_column", project["level"], types[0]["guid"], 1, 1, 3.0)
    assert c["ok"], c
    em = call("element_material", c["guid"])
    assert em["kind"] == "material" and em["name"] in ("Concrete", "Steel") and not em["editable"]


def test_assign_material_to_furniture_like_element(project):
    f = b._model
    e = ifcopenshell.api.root.create_entity(f, ifc_class="IfcFurniture", name="Table")
    r = call("assign_material", json.dumps([e.GlobalId]), "material", "Timber - finish")
    assert r["ok"], r
    assert call("element_material", e.GlobalId) == {**call("element_material", e.GlobalId), "name": "Timber - finish", "editable": True}


def test_deleting_a_used_composite_needs_a_replacement(project):
    g = wall(project)
    comp = by_name(state()["composites"], "Exterior 300")
    r = call("apply_materials", json.dumps({"deleted": {"composites": [{"key": comp["key"]}]}}))
    assert not r["ok"]
    r = call("apply_materials", json.dumps({"deleted": {"composites": [{"key": comp["key"], "replace": "Generic 200"}]}}))
    assert r["ok"], r
    assert call("element_material", g)["name"] == "Generic 200"
    assert "Exterior 300" not in [t["name"] for t in call("wall_types")["types"]]


def test_add_standard_and_purge(project):
    r = call("add_standard_materials")
    assert r["ok"]
    names = {m["name"] for m in state()["materials"]}
    assert set(M.CATALOGUE) <= names
    wall(project)  # uses Exterior 300
    r = call("purge_materials")
    assert r["ok"]
    st = state()
    names = {m["name"] for m in st["materials"]}
    assert {"Brick", "Insulation", "Block"} <= names
    assert "Glass" not in names and "Glass" not in {s["name"] for s in st["surfaces"]}
    assert "Exterior 300" in {c["name"] for c in st["composites"]}
    call("undo")
    assert "Glass" in {m["name"] for m in state()["materials"]}


def test_model_stays_valid_after_edits(project, tmp_path):
    wall(project)
    call("add_standard_materials")
    comp = by_name(state()["composites"], "Exterior 300")
    call("apply_materials", json.dumps({"composites": [{**comp, "layers": comp["layers"][:2]}]}))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger)
    assert [s for s in logger.statements if s.get("level") == "error"] == []


def test_cut_fill_comes_from_the_core_material_unless_the_style_says_otherwise(project):
    from kimbim import graphics, settings

    g = wall(project)  # Exterior 300: core Block (pen 12); give Block another pen
    block = by_name(state()["materials"], "Block")
    assert call("apply_materials", json.dumps({"materials": [{**block, "pen": 40}]}))["ok"]
    r = graphics.resolve()
    pens = r["pens"]
    assert r["styles"][r["elements"][g]]["fill"] == pens["40"]["color"]
    styles = json.loads(json.dumps(graphics.effective("element_styles")))
    styles["walls"]["fill_source"] = "style"
    assert graphics.validate("element_styles", styles) is None
    assert graphics.validate("element_styles", {**styles, "walls": {**styles["walls"], "fill_source": "x"}})
    r = graphics.resolve(settings={**settings.current(), "element_styles": styles})
    assert r["styles"][r["elements"][g]]["fill"] == pens[str(styles["walls"]["fill"])]["color"]


def test_properties_show_a_material_row(project):
    a, c = wall(project), wall(project, "Generic 200")
    m = call("properties_multi", json.dumps([a]))["material"]
    assert m["kind"] == "composite" and m["value"] == "Exterior 300" and "Generic 200" in m["choices"]
    m = call("properties_multi", json.dumps([a, c]))["material"]
    assert m["varies"] and m["value"] is None
    col = call("create_column", project["level"], call("column_types")["types"][0]["guid"], 1, 1, 3.0)["guid"]
    assert call("properties_multi", json.dumps([a, col]))["material"] is None  # mixed kinds


def test_layered_walls_send_their_layer_bands(project):
    from kimbim import graphics

    g = wall(project)  # along +X, centred: layers stack along local Y from -0.15 m
    r = graphics.resolve()
    bands = r["layers"][g]
    assert bands["axis"] == pytest.approx([0, 1, 0])
    assert bands["bounds"] == pytest.approx([-0.15, -0.05, 0.03, 0.15])
    pens = r["pens"]
    assert bands["fills"] == [pens["12"]["color"]] * 3
    single = wall(project, "Generic 200")
    assert single not in r["layers"] or True  # one layer: no bands
    assert single not in graphics.resolve()["layers"]


def test_plan_drawings_cut_composites_layer_by_layer(project):
    import re

    from kimbim import drawings

    g = wall(project)
    plan = next(d for d in call("drawings")["drawings"] if d["name"] == "Level 1 Floor Plan")
    loop = [[0, -0.15], [5, -0.15], [5, 0.15], [0, 0.15]]
    geometry = {"cut": [{"guid": g, "loops": [loop]}], "proj": [], "bounds": [0, -0.15, 5, 0.15]}
    r = json.loads(drawings.generate_plan_drawing(plan["guid"], json.dumps(geometry)))
    assert r["ok"], r
    group = re.search(rf'<g ifc:guid="{re.escape(g)}"[^>]*>(.*?)</g>', r["svg"], re.S).group(1)
    fills = re.findall(r'<path fill="([^"]+)" stroke-width="[^"]+" d=', group)
    assert len(fills) == 3  # brick, insulation, block
    assert group.count('fill="none"') == 1  # the outline over them
