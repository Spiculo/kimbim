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
from kimbim.testing import _reset_owner, _set_owner


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
    try:
        ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
        m = M.ensure("Glass", f)
        look = M.surface_look(M.surface_of(m))
        assert look["colour"] == M.CATALOGUE["Glass"]["colour"] and look["transparency"] == pytest.approx(0.6)
        assert M.properties(m)["pen"] == 12
    finally:
        _reset_owner()


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
    assert core in hexes(palette, idx[np.abs(n) <= 0.7])  # the edges show every layer (sliced), the core among them


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
    assert em["kind"] == "material" and em["name"] in ("Concrete", "Steel") and em["editable"]
    r = call("assign_material", json.dumps([c["guid"]]), "material", "Timber")  # D97: through its profile
    assert r["ok"], r
    assert call("element_material", c["guid"])["name"] == "Timber"
    palette, idx, _, _ = colours(c["guid"])
    assert hexes(palette, idx) == {M.CATALOGUE["Timber"]["colour"]}


def test_column_material_is_per_element_or_per_type(project):
    t = call("column_types")["types"][0]["guid"]
    a = call("create_column", project["level"], t, 1, 1, 3.0)["guid"]
    b2 = call("create_column", project["level"], t, 4, 1, 3.0)["guid"]
    before = call("element_material", b2)["name"]
    assert call("assign_material", json.dumps([a]), "material", "Timber")["ok"]  # Archicad: this one only
    assert call("element_material", a)["name"] == "Timber" and call("element_material", b2)["name"] == before
    assert call("assign_material", json.dumps([a]), "material", "Steel")["ok"]  # its own set, changed in place
    assert call("element_material", a)["name"] == "Steel"
    assert call("element_material", b2)["name"] == before
    assert call("assign_material", json.dumps([b2]), "material", "Stone", "type")["ok"]  # Revit: the type
    assert call("element_material", b2)["name"] == "Stone"
    c3 = call("create_column", project["level"], t, 7, 1, 3.0)["guid"]
    assert call("element_material", c3)["name"] == "Stone" and call("element_material", a)["name"] == "Steel"
    palette, idx, _, _ = colours(a)
    assert hexes(palette, idx) == {M.CATALOGUE["Steel"]["colour"]}
    assert not call("assign_material", json.dumps([a]), "material", "Steel", "nope")["ok"]
    call("undo"); call("undo"); call("undo"); call("undo")
    assert call("element_material", a)["name"] == before
    from kimbim import settings

    assert json.loads(settings.set_project_settings(json.dumps({"member_material_scope": "type"})))["ok"]
    assert call("assign_material", json.dumps([a]), "material", "Timber")["ok"]  # the setting: the type
    assert call("element_material", b2)["name"] == "Timber"
    assert not json.loads(settings.set_project_settings(json.dumps({"member_material_scope": "x"})))["ok"]


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
    assert len(fills) == 3  # brick, insulation, block: their backgrounds (white: the patterns have none)
    hatches = re.findall(r'<path d="[^"]*" fill="none" stroke="([^"]+)"', group)
    assert len(hatches) == 3  # each layer's pattern in its fill pen
    assert group.count('<path fill="none" d=') == 1  # the outline over them


def test_windows_show_aluminium_frames_and_glass(project):
    g = wall(project)
    t = call("opening_types", "window")["types"][0]
    r = call("insert_opening", "window", g, t["guid"], 2.0, 1.2, 1.2, 0.9)
    assert r["ok"], r
    palette, idx, _, _ = colours(r["guid"])
    looks = {(M._hex(palette[i][:3]), palette[i][3]) for i in set(idx.tolist())}
    assert looks == {(M.CATALOGUE["Aluminium"]["colour"], 0.0), (M.CATALOGUE["Glass"]["colour"], 0.6)}
    wtype = ifcopenshell.util.element.get_type(b._model.by_guid(r["guid"]))
    cs = ifcopenshell.util.element.get_material(wtype)
    assert cs.is_a("IfcMaterialConstituentSet") and {c.Name for c in cs.MaterialConstituents} == {"Framing", "Glazing"}


def test_doors_are_timber_and_roofs_tiled(project):
    g = wall(project)
    t = call("opening_types", "door")["types"][0]
    d = call("insert_opening", "door", g, t["guid"], 2.0, 0.9, 2.1, 0.0)
    assert d["ok"], d
    palette, idx, _, _ = colours(d["guid"])
    assert hexes(palette, idx) == {M.CATALOGUE["Timber - finish"]["colour"]}
    roof = call("create_roof", project["level"], json.dumps([[0, 0], [5, 0], [5, 4], [0, 4]]), "flat", 0, 0.2, 3.0)
    assert roof["ok"], roof
    palette, idx, _, _ = colours(roof["guid"])
    assert hexes(palette, idx) == {M.CATALOGUE["Roof tiles"]["colour"]}


def test_cut_patterns_and_backgrounds_come_with_the_state(project):
    from kimbim import graphics

    g = wall(project)
    r = graphics.resolve()
    bands = r["layers"][g]
    assert bands["patterns"] == ["Brick", "Insulation", "Crosshatch"]
    assert bands["backgrounds"] == [None, None, None]
    assert "Brick" in r["fill_patterns"]
    col = call("create_column", project["level"], call("column_types")["types"][0]["guid"], 1, 1, 3.0)["guid"]
    style = r and graphics.resolve()["styles"][graphics.resolve()["elements"][col]]
    assert style.get("pattern") in ("Concrete", "Solid", None)


def test_surface_textures(project, tmp_path):
    from kimbim import settings, underlays

    pic = tmp_path / "bricks.png"
    pic.write_bytes(underlays.png_bytes(8, 4, [bytes([180, 80, 60] * 8)] * 4))
    g = wall(project)
    brick = by_name(state()["surfaces"], "Brick")
    r = call("apply_materials", json.dumps({"surfaces": [{**brick, "texture_path": str(pic), "texture_size": [0.5, 0.25]}]}))
    assert r["ok"], r
    s = by_name(state()["surfaces"], "Brick")
    assert s["texture"].endswith(".png") and s["texture_size"] == [0.5, 0.25]
    assert s["texture"] in settings.current()["texture_files"]
    palette, idx, _, _ = colours(g)
    textured = [row for row in palette if len(row) == 7]
    assert textured and textured[0][5:] == [0.5, 0.25] and textured[0][4].endswith(s["texture"])
    r = call("apply_materials", json.dumps({"surfaces": [{**s, "texture": ""}]}))
    assert r["ok"], r
    assert "texture" not in by_name(state()["surfaces"], "Brick")
    assert s["texture"] not in settings.current()["texture_files"]
    call("undo")
    assert by_name(state()["surfaces"], "Brick")["texture"] == s["texture"]
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger)
    assert [x for x in logger.statements if x.get("level") == "error"] == []


def test_dxf_exports_composite_cuts_with_pattern_hatches(project, tmp_path):
    import ezdxf

    from kimbim import drawings, dxf

    g = wall(project)
    plan = next(d for d in call("drawings")["drawings"] if d["name"] == "Level 1 Floor Plan")
    loop = [[0, -0.15], [5, -0.15], [5, 0.15], [0, 0.15]]
    geometry = {"cut": [{"guid": g, "loops": [loop]}], "proj": [], "bounds": [0, -0.15, 5, 0.15]}
    assert json.loads(drawings.generate_plan_drawing(plan["guid"], json.dumps(geometry)))["ok"]
    out = tmp_path / "plan.dxf"
    r = json.loads(dxf.export_drawing_dxf(plan["guid"], str(out)))
    assert r["ok"], r
    doc = ezdxf.readfile(str(out))
    names = {h.dxf.pattern_name for h in doc.modelspace().query("HATCH") if not h.dxf.solid_fill}
    assert {"BRICK", "CROSSHATCH"} <= names  # brick and block layers
    insulation = [e for e in doc.modelspace().query("LINE") if e.dxf.layer.endswith("-PATT")]
    assert insulation  # the insulation's loops, as short lines


def test_catalogue_surfaces_come_with_pictures(project):
    from kimbim import settings, underlays

    st = state()
    brick = by_name(st["surfaces"], "Brick")
    assert brick["texture"].endswith(".png") and brick["texture_size"] == [0.5, 0.26]
    assert underlays.file_path(brick["texture"]) is not None
    assert by_name(st["surfaces"], "Timber - finish")["texture"]
    assert "texture" not in by_name(st["surfaces"], "Concrete")
    assert set(settings.current()["texture_files"]) == {s["texture"] for s in st["surfaces"] if s.get("texture")}
    assert call("state")["dirty"] is False  # part of the empty project


def test_material_takeoff_schedule(project):
    from kimbim import schedules

    wall(project, x2=5.0)  # Exterior 300: brick 0.1, insulation 0.08, block 0.12; 5 x 3 m
    r = schedules.compute("materials", merge=True)
    assert r["ok"], r
    keys = [c["key"] for c in r["columns"]]
    rows = {row["values"][keys.index("info:material")]: row for row in r["rows"]}
    volume = keys.index("quantity:volume")
    assert rows["Brick"]["values"][volume] == pytest.approx(15.0 * 0.1, rel=0.05)
    assert rows["Insulation"]["values"][volume] == pytest.approx(15.0 * 0.08, rel=0.05)
    assert rows["Block"]["values"][volume] == pytest.approx(15.0 * 0.12, rel=0.05)
    # any schedule can show an element's building material
    walls = schedules.compute({"id": "x", "name": "x", "classes": ["IfcWall"],
                               "fields": [{"source": "info", "name": "material"}]})
    assert walls["rows"][0]["values"] == ["Block"]  # the core


def test_ifc2x3_catalogue_textures():
    f = ifcopenshell.file(schema="IFC2X3")
    _set_owner(f)
    try:
        ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
        m = M.ensure("Brick", f)
        look = M.surface_look(M.surface_of(m))
        assert look["texture"].endswith(".png") and look["texture_size"] == [0.5, 0.26]
    finally:
        _reset_owner()


def test_wall_ends_and_tops_show_each_layer(project):
    g = wall(project)  # Exterior 300: brick, insulation, block
    palette, idx, v, t = colours(g)
    w = b._model.by_guid(g)
    usage = ifcopenshell.util.element.get_material(w, should_skip_usage=False)
    n = M._normals(v.reshape(-1), t.reshape(-1)) @ M._layer_axis(w, usage)
    ends = idx[np.abs(n) <= 0.7]
    assert hexes(palette, ends) == {M.CATALOGUE[k]["colour"] for k in ("Brick", "Insulation", "Block")}
    top = [i for i in range(len(t)) if v[t[i]][:, 2].min() > 2.999]
    y = {M._hex(palette[idx[i]][:3]): sorted({round(float(v[t[i]][:, 1].mean()), 2)}) for i in top}
    assert y[M.CATALOGUE["Brick"]["colour"]][0] < y[M.CATALOGUE["Block"]["colour"]][0]  # brick on the -y side
    # the mesh still closes: the area of the top is the wall's 5 x 0.3
    area = sum(np.linalg.norm(np.cross(v[t[i]][1] - v[t[i]][0], v[t[i]][2] - v[t[i]][0])) / 2 for i in top)
    assert area == pytest.approx(5 * 0.3, rel=1e-3)


def test_layers_in_3d_can_be_turned_off(project):
    g = wall(project)
    sliced = len(colours(g)[1])
    assert call("set_project_settings", json.dumps({"layers_in_3d": False}))["ok"]
    assert len(colours(g)[1]) < sliced  # the ends and top are whole again
    assert not call("set_project_settings", json.dumps({"layers_in_3d": "yes"}))["ok"]


def test_a_picture_standing_in_the_model(project, tmp_path):
    """D98: Archicad's Picture object: an image on a thin panel, its own material carrying it."""
    from kimbim import underlays

    png = tmp_path / "person.png"
    png.write_bytes(underlays.png_bytes(40, 80, [bytes([200, 100, 50]) * 40 for _ in range(80)]))
    r = call("place_picture_3d", project["level"], str(png), 0.9, 2.0, 3.0, 0, 0)
    assert r["ok"], r
    assert r["height"] == pytest.approx(1.8)  # 0.9 wide, twice as tall
    palette, idx, v, _ = colours(r["guid"])
    assert v[:, 0].max() - v[:, 0].min() == pytest.approx(0.9, abs=1e-3)
    assert v[:, 2].max() - v[:, 2].min() == pytest.approx(1.8, abs=1e-3)
    textured = [palette[i] for i in set(idx.tolist()) if len(palette[i]) > 4]
    assert textured and textured[0][5:7] == [0.9, 1.8]  # the picture once across its face
    assert call("element_material", r["guid"])["name"].startswith("Picture: person")
    assert not call("place_picture_3d", project["level"], str(tmp_path / "x.txt"), 1, 0, 0, 0, 0)["ok"]
