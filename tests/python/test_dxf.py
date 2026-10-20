# SPDX-License-Identifier: GPL-3.0-or-later
"""D83: drawings and sheets exported to DXF (ezdxf), re-read and audited."""
import json
import math
import pathlib
import re
import shutil
import sys
import time
from collections import Counter

import ezdxf
import ezdxf.bbox
import ifcopenshell.geom
import ifcopenshell.util.element
import numpy as np
import pytest

from kimbim import app_bridge as b
from kimbim import drawgen, drawings, dxf, graphics

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402

CLINIC = ROOT / "tests" / "corpus" / "files" / "community" / "IFC 2.3.0.1 (IFC 2x3)" / "Medical-Dental Clinic" / "Clinic_Architectural.ifc"


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture(scope="module")
def house_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("house") / "house.ifc"
    make_house.build(str(path))
    return str(path)


@pytest.fixture
def house(house_file):
    assert call("open_model", house_file)["ok"]


def drawing(name):
    return next(d["guid"] for d in call("drawings")["drawings"] if d["name"] == name)


def read(path):
    doc = ezdxf.readfile(path)
    auditor = doc.audit()
    assert not auditor.has_errors, [str(e.message) for e in auditor.errors]
    return doc


def walls_extent(storey_name):
    """World XY extent (mm) of a level's walls from their tessellated bodies."""
    f = b._model
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    pts = []
    for w in f.by_type("IfcWall"):
        if ifcopenshell.util.element.get_container(w).Name != storey_name:
            continue
        shape = ifcopenshell.geom.create_shape(settings, w)
        v = np.array(shape.geometry.verts).reshape(-1, 3)
        pts.append(v[:, :2])
    pts = np.vstack(pts) * 1000.0
    return pts.min(axis=0), pts.max(axis=0)


# ---------------------------------------------------------------- pieces

def test_pen_weights_become_standard_lineweights():
    assert [dxf.lineweight(w) for w in (0.13, 0.18, 0.25, 0.35, 0.5, 0.7, 1.0, 2.5)] == [13, 18, 25, 35, 50, 70, 100, 211]
    assert dxf.lineweight(0.0) == 0


def test_colours_map_to_aci_black_follows_the_background():
    assert dxf.aci("#000000") == 7
    assert dxf.aci("#ff0000") == 1 and dxf.aci("#0000ff") == 5
    assert 1 <= dxf.aci("#5a3a22") <= 255


def test_svg_paths_close_and_keep_arcs():
    (loop, closed), = dxf.parse_path("M0,0 L10,0 L10,5 L0,5 L0,0")
    assert closed and len(loop) == 4
    (open_, closed2), = dxf.parse_path("M0,0 L1,1")
    assert not closed2
    (arc, _), = dxf.parse_path("M10,0 A10,10 0 0 1 0,10")
    assert math.isclose(abs(arc[0][2]), math.tan(math.pi / 8), rel_tol=1e-9)  # a quarter circle
    assert len(dxf.parse_path("M0,0 L1,0 L1,1 L0,0 M5,5 L6,5 L6,6 L5,5")) == 2
    assert dxf.parse_path("M0,0 l10,0 v5 h-10 z")[0][1]


def test_units_and_linetype_scale_follow_the_project_unit():
    mm, m = dxf.Doc(0.001, {}), dxf.Doc(1.0, {})
    assert (mm.doc.header["$INSUNITS"], mm.ltscale) == (4, pytest.approx(100.0))
    assert (m.doc.header["$INSUNITS"], m.ltscale) == (6, pytest.approx(0.1))
    svg = ('<svg><g class="section" ifc:plane="[[1,0,0,0],[0,1,0,0],[0,0,1,1.1],[0,0,0,1]]" '
           'ifc:matrix3="[[10,0,15],[0,10,91.5],[0,0,1]]"></g></svg>')
    in_m, in_mm = dxf.drawing_mapping(svg, "plan", 1.0), dxf.drawing_mapping(svg, "plan", 0.001)
    assert in_m(25, 81.5) == pytest.approx((1.0, 1.0)) and in_mm(25, 81.5) == pytest.approx((1000.0, 1000.0))
    assert in_m.flip and in_m.size == pytest.approx(0.1)


def test_layer_and_file_names_are_made_safe():
    assert dxf.layer_name("Walls: <load/bearing>") == "Walls_ _load_bearing_"
    assert dxf.file_name('Plan 1/2 "draft"') == "Plan 1_2 _draft_"


# ---------------------------------------------------------------- drawings

def test_house_plan_to_dxf_at_real_size_with_pens(house, tmp_path):
    plan = drawing("Level 1 Floor Plan")
    r = call("export_drawing_dxf", plan, str(tmp_path / "plan.dxf"), "")
    assert r["ok"], r
    doc = read(r["path"])
    assert doc.header["$INSUNITS"] == 4  # the house is in millimetres
    msp = doc.modelspace()
    kinds = Counter(e.dxftype() for e in msp)
    assert kinds["HATCH"] >= 5  # the four walls' poché and the column
    assert kinds["DIMENSION"] >= 1 and kinds["TEXT"] >= 5 and kinds["CIRCLE"] >= 1
    assert kinds["LINE"] + kinds["LWPOLYLINE"] > 50  # edges chained into polylines
    layers = {layer.dxf.name for layer in doc.layers}
    for name in ("A-WALL", "A-WALL-PATT", "A-DOOR", "A-GLAZ", "S-COLS", "A-AREA-IDEN", "A-ANNO-SYMB", "A-ANNO-DIMS"):
        assert name in layers, name
    # Plans are in world coordinates at 1:1: the walls' extent is the building's.
    lo, hi = walls_extent("Level 1")
    walls = ezdxf.bbox.extents(msp.query('*[layer=="A-WALL"]'))
    assert np.allclose([walls.extmin.x, walls.extmin.y], lo, atol=2.0), (walls.extmin, lo)
    assert np.allclose([walls.extmax.x, walls.extmax.y], hi, atol=2.0), (walls.extmax, hi)
    # Lineweights and colours from the purpose's pens (Working set: walls cut pen 10, fill pen 12).
    pens = graphics.resolve()["pens"]
    lines = [e for e in msp if e.dxf.layer == "A-WALL" and e.dxftype() in ("LINE", "LWPOLYLINE")]
    looks = {(e.dxf.lineweight, e.rgb) for e in lines}
    cut, projection = (dxf.lineweight(pens["10"]["weight"]), dxf._rgb(pens["10"]["color"])), \
        (dxf.lineweight(pens["11"]["weight"]), dxf._rgb(pens["11"]["color"]))
    assert looks == {cut, projection}, looks
    assert cut[0] == 50 and projection[0] == 18
    hatch = msp.query('HATCH[layer=="A-WALL-PATT"]').first
    assert hatch.dxf.solid_fill == 1 and hatch.rgb == dxf._rgb(pens["12"]["color"])
    dim = msp.query("DIMENSION").first
    assert dim.dxf.layer == "A-ANNO-DIMS" and dim.dxf.dimstyle == "KimBim"
    assert dim.get_measurement() == pytest.approx(10000.0, abs=1.0)  # the house's 10 m chain


def test_line_types_become_linetypes(house, tmp_path):
    styles = graphics.effective("element_styles")
    styles["walls"]["projection"]["line"] = "Dashed"
    assert call("set_graphics", json.dumps({"element_styles": styles}))["ok"]
    r = call("export_drawing_dxf", drawing("Section 1"), str(tmp_path / "s.dxf"), "")
    assert r["ok"], r
    doc = read(r["path"])
    assert "DASHED" in doc.linetypes
    assert doc.linetypes.get("DASHED").pattern_tags.tags  # a real pattern
    assert any(e.dxf.get("linetype") == "DASHED" for e in doc.modelspace().query('*[layer=="A-WALL"]'))
    assert doc.header["$LTSCALE"] == pytest.approx(100.0)  # paper mm at 1:100 in a millimetre model


def test_section_uses_true_elevations(house, tmp_path):
    r = call("export_drawing_dxf", drawing("Section 1"), str(tmp_path / "s.dxf"), "")
    doc = read(r["path"])
    slabs = ezdxf.bbox.extents(doc.modelspace().query('*[layer=="S-SLAB"]'))
    assert slabs.extmin.y == pytest.approx(-200.0, abs=5)  # the ground slab's underside, 0.2 m below level 1
    assert slabs.extmax.y > 5800  # the level 3 slab, above 6 m


def test_layers_by_kimbim_layer_or_by_kind(house, tmp_path):
    wall = next(e.GlobalId for e in b._model.by_type("IfcWall"))
    assert call("create_layer", "Bearing walls")["ok"]
    assert call("assign_layer", json.dumps([wall]), "Bearing walls")["ok"]
    plan = drawing("Level 1 Floor Plan")
    by_layer = read(call("export_drawing_dxf", plan, str(tmp_path / "a.dxf"), "")["path"])
    names = {e.dxf.layer for e in by_layer.modelspace()}
    assert "Bearing walls" in names and "Bearing walls-PATT" in names and "A-WALL" in names
    by_kind = read(call("export_drawing_dxf", plan, str(tmp_path / "b.dxf"), json.dumps({"layers": "kind"}))["path"])
    assert "Bearing walls" not in {e.dxf.layer for e in by_kind.modelspace()}


def test_dxf_layer_scheme_poche_and_colour_modes(house, tmp_path):
    # D92: an ISO 13567 layer scheme, poché off, and an ACI-only colour mode.
    plan = drawing("Level 1 Floor Plan")
    iso = read(call("export_drawing_dxf", plan, str(tmp_path / "iso.dxf"), json.dumps({"layers": "iso"}))["path"])
    assert "A-WALL-FULL" in {e.dxf.layer for e in iso.modelspace()}
    no_poche = read(call("export_drawing_dxf", plan, str(tmp_path / "np.dxf"), json.dumps({"poche": False}))["path"])
    assert not any(name.endswith("-PATT") for name in {e.dxf.layer for e in no_poche.modelspace()})
    aci = read(call("export_drawing_dxf", plan, str(tmp_path / "aci.dxf"), json.dumps({"colour": "aci"}))["path"])
    assert all(not e.dxf.hasattr("true_color") for e in aci.modelspace() if e.dxftype() in ("LINE", "LWPOLYLINE"))


def test_dimensions_can_be_exploded(house, tmp_path):
    plan = drawing("Level 1 Floor Plan")
    r = call("export_drawing_dxf", plan, str(tmp_path / "x.dxf"), json.dumps({"dimensions": "exploded"}))
    doc = read(r["path"])
    assert not doc.modelspace().query("DIMENSION")
    assert doc.modelspace().query('TEXT[layer=="A-ANNO-DIMS"]')


def test_hidden_elements_stay_out(house, tmp_path):
    def door_pen_lines(doc):  # the doors' own lines (pen 16, 0.25 mm); swings are overlay lines (0.18)
        return [e for e in doc.modelspace() if e.dxf.layer == "A-DOOR" and e.dxf.get("lineweight") == 25]

    plan = drawing("Level 1 Floor Plan")
    assert door_pen_lines(read(call("export_drawing_dxf", plan, str(tmp_path / "v.dxf"), "")["path"]))
    vis = graphics.effective("visibility_sets")
    vis["Everything"]["hidden_kinds"] = ["doors"]
    assert call("set_graphics", json.dumps({"visibility_sets": vis}))["ok"]
    assert call("set_purpose", "Working")["ok"]
    doc = read(call("export_drawing_dxf", drawing("Level 1 Floor Plan"), str(tmp_path / "h.dxf"), "")["path"])
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert "A-WALL" in layers
    assert not door_pen_lines(doc)  # gone; the swing (overlay) stays on A-DOOR, as in the PDF


# ---------------------------------------------------------------- sheets

def test_sheet_a01_is_a_paper_space_layout(house, tmp_path):
    sheet = next(s for s in call("sheets")["sheets"] if s["number"] == "A01")
    r = call("export_sheet_dxf", "A01", str(tmp_path / "A01.dxf"), "")
    assert r["ok"], r
    doc = read(r["path"])
    layout = doc.layouts.get(r["layout"])
    assert r["layout"].startswith("A01")
    assert "Layout1" not in doc.layout_names()
    assert (layout.dxf.paper_width, layout.dxf.paper_height) == (420, 297)
    inserts = layout.query("INSERT")
    assert len(inserts) == 3 and {i.dxf.name for i in inserts} == {
        "VIEW-Level 1 Floor Plan", "VIEW-Section 1", "VIEW-South Elevation"}
    assert all(i.dxf.xscale == pytest.approx(0.01) for i in inserts)  # mm drawings at 1:100 on paper mm
    # The plan sits where the sheet's SVG puts it: a wall corner (world) lands on the same sheet point.
    view = next(v for v in sheet["views"] if v["name"] == "Level 1 Floor Plan")
    svg = drawings.raw_drawing(view["drawing"])["svg"]
    to_paper = drawgen.paper_mapping(svg)
    vx, vy = (float(v) for v in re.search(r'viewBox="([-\d.]+) ([-\d.]+)', svg).groups())
    lo, _ = walls_extent("Level 1")
    px, py = to_paper(lo[0] / 1000, lo[1] / 1000, 0.0)
    k = 100.0 / view["scale"]
    expected = (view["x"] + (px - vx) * k, 297 - (view["y"] + (py - vy) * k))
    ins = next(i for i in inserts if i.dxf.name == "VIEW-Level 1 Floor Plan")
    got = ins.matrix44().transform((lo[0], lo[1], 0.0))
    assert (got.x, got.y) == pytest.approx(expected, abs=0.01)
    for view in sheet["views"]:  # every drawing's lines inside its box on the sheet
        ins = next(i for i in inserts if i.dxf.name == "VIEW-" + view["name"])
        box = ezdxf.bbox.extents(e for e in ins.virtual_entities() if e.dxftype() != "TEXT")
        assert box.extmin.x >= view["x"] - 0.5 and box.extmax.x <= view["x"] + view["w"] + 0.5, view["name"]
        assert box.extmax.y <= 297 - view["y"] + 0.5 and box.extmin.y >= 297 - view["y"] - view["h"] - 0.5, view["name"]
    texts = [t.dxf.text for t in layout.query("TEXT")]
    assert "A01" in texts and "Level 1 Floor Plan" in texts and "1:100" in texts
    assert "KimBim two-storey house" in texts or any("M4-01" in t for t in texts)
    frame = layout.query('LWPOLYLINE[layer=="A-ANNO-TTLB"]')
    assert any(e.dxf.lineweight == 70 for e in frame)  # the 0.7 mm border
    # Model space has the same drawings at real size.
    assert len(doc.modelspace().query("INSERT")) == 3
    assert all(i.dxf.xscale == 1 for i in doc.modelspace().query("INSERT"))


def test_batch_export_to_a_folder(house, tmp_path):
    targets = call("dxf_targets")
    assert {"Level 1 Floor Plan.dxf", "Section 1.dxf"} <= {d["file"] for d in targets["drawings"]}
    assert targets["sheets"][0]["file"] == "A01 Plan, section and elevation.dxf"
    items = [{"drawing": drawing("Level 1 Floor Plan")}, {"drawing": drawing("North Elevation")}, {"sheet": "A01"}]
    r = call("export_dxf", json.dumps(items), str(tmp_path / "out"), "")
    assert r["ok"], r
    assert sorted(pathlib.Path(p).name for p in r["files"]) == [
        "A01 Plan, section and elevation.dxf", "Level 1 Floor Plan.dxf", "North Elevation.dxf"]
    for p in r["files"]:
        read(p)
    bad = call("export_dxf", json.dumps([{"sheet": "Z99"}]), str(tmp_path / "out"), "")
    assert not bad["ok"] and bad["errors"][0]["item"] == "Z99"


def test_no_model_fails_cleanly(tmp_path):
    b._model = None
    assert not call("export_drawing_dxf", "x", str(tmp_path / "a.dxf"), "")["ok"]
    assert call("dxf_targets")["drawings"] == []


# ---------------------------------------------------------------- the Clinic (timed)

@pytest.mark.golden
def test_clinic_plan_export_timed(tmp_path):
    if not CLINIC.exists():
        pytest.skip("corpus not downloaded (pixi run fetch-corpus)")
    copy = tmp_path / "clinic.ifc"  # never open the corpus file itself (D72 saves can write beside it)
    shutil.copyfile(CLINIC, copy)
    assert call("open_model", str(copy))["ok"]
    assert call("create_drawings")["ok"]
    plans = [d for d in call("drawings")["drawings"] if d["name"] == "First Floor Floor Plan"]
    t0 = time.perf_counter()
    r = call("export_drawing_dxf", plans[0]["guid"], str(tmp_path / "clinic.dxf"), "")
    seconds = time.perf_counter() - t0
    assert r["ok"], r
    t1 = time.perf_counter()
    again = call("export_drawing_dxf", plans[0]["guid"], str(tmp_path / "clinic2.dxf"), "")
    cached = time.perf_counter() - t1
    doc = read(r["path"])
    print(f"\nClinic {plans[0]['name']}: {r['entities']} entities, {len(r['layers'])} layers, "
          f"{seconds:.2f} s (hidden-line pass included), {cached:.2f} s from the cached drawing")
    assert r["entities"] > 1000 and again["ok"]
    assert len(doc.modelspace()) > 1000


# ---------------------------------------------------------------- command line

def test_cli_exports_a_version_to_dxf(house_file, tmp_path, capsys):
    from kimbim.cli import main

    proj = tmp_path / "proj"
    assert main(["init", str(proj)]) == 0
    assert main(["-C", str(proj), "commit", house_file, "-m", "house"]) == 0
    capsys.readouterr()
    one = tmp_path / "plan.dxf"
    assert main(["-C", str(proj), "export", str(one), "--drawing", "Level 1 Floor Plan", "--layers", "kind"]) == 0
    assert "A-WALL" in {layer.dxf.name for layer in read(str(one)).layers}
    assert main(["-C", str(proj), "export", str(one), "--drawing", "Level 1 Floor Plan"]) == 1
    assert "--force" in capsys.readouterr().err
    folder = tmp_path / "set"
    assert main(["-C", str(proj), "export", str(folder), "--format", "dxf", "--sheet", "A01",
                 "--drawing", "Section 1"]) == 0
    assert sorted(p.name for p in folder.iterdir()) == ["A01 Plan, section and elevation.dxf", "Section 1.dxf"]
    assert main(["-C", str(proj), "export", str(folder), "--format", "dxf", "--sheet", "Z9"]) == 1
    assert "Z9" in capsys.readouterr().err
