# SPDX-License-Identifier: GPL-3.0-or-later
"""D85: DXF, PDF and image underlays: DXF read to segments (units, exploded blocks, tessellated arcs),
PDF pages rendered, files kept in the project and its versions, placement in the settings."""
import json
import math
import struct
import time
import zipfile
import zlib

import ezdxf
import numpy as np
import pytest

from kimbim import app_bridge as b
from kimbim import underlays as U


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture(autouse=True)
def data_dir(tmp_path):
    """Per-test data folder (open .kim copies, the plain-IFC underlay store), cleared caches."""
    call("set_app_paths", str(tmp_path / "data"))
    U._segments_cache.clear()
    yield tmp_path / "data"
    call("close_document")
    call("set_app_paths", "")
    U._segments_cache.clear()


def survey_dxf(path, insunits=4, offset=(0.0, 0.0)):
    """A small survey in millimetres: a 10 x 6 m outline, a bulged polyline, an arc, a circle, a door
    block inserted twice (one turned and scaled, one nested in another block), text and an off layer."""
    doc = ezdxf.new("R2013")
    doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    ox, oy = offset
    doc.layers.add("WALLS", color=1)
    doc.layers.add("HIDDEN", color=3).off()
    msp.add_lwpolyline([(ox, oy), (ox + 10000, oy), (ox + 10000, oy + 6000), (ox, oy + 6000)], close=True,
                       dxfattribs={"layer": "WALLS"})
    # a semicircle as a bulged polyline: from (0, 8000) to (2000, 8000) around (1000, 8000)
    msp.add_lwpolyline([(ox, oy + 8000, 0, 0, 1.0), (ox + 2000, oy + 8000, 0, 0, 0)], format="xyseb")
    msp.add_arc((ox + 5000, oy + 3000), 1000, 0, 90)
    msp.add_circle((ox + 8000, oy + 3000), 500, dxfattribs={"color": 5})
    door = doc.blocks.new("DOOR")
    door.add_line((0, 0), (900, 0))
    door.add_line((0, 0), (0, 900))
    msp.add_blockref("DOOR", (ox + 1000, oy))
    msp.add_blockref("DOOR", (ox + 4000, oy + 6000), dxfattribs={"rotation": 90, "xscale": 2, "yscale": 2})
    pair = doc.blocks.new("PAIR")
    pair.add_blockref("DOOR", (0, 0))
    pair.add_blockref("DOOR", (2000, 0))
    msp.add_blockref("PAIR", (ox + 0, oy + 12000))
    msp.add_text("SURVEY", dxfattribs={"insert": (ox, oy - 500), "height": 250})
    msp.add_line((ox, oy - 1000), (ox + 1000, oy - 1000), dxfattribs={"layer": "HIDDEN"})
    doc.saveas(path)
    return path


def tiny_png(path, w=40, h=20, dpi=200):
    raw = b"".join(b"\x00" + bytes([200, 30, 30]) * w for _ in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ppm = round(dpi / 0.0254)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    path.write_bytes(png)
    return path


def a_pdf(path, pages=((595.0, 842.0), (842.0, 595.0))):
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    for w, h in pages:
        pdf.new_page(w, h)
    pdf.save(str(path))
    pdf.close()
    return path


def segments(d):
    return d["coords"].astype(np.float64) + np.array(d["origin"] * 2)


# ---------------------------------------------------------------- DXF reading

def test_dxf_units_lines_and_exploded_blocks(tmp_path):
    d = U.read_dxf(survey_dxf(tmp_path / "s.dxf"))
    assert d["units"] == 0.001
    seg = segments(d)
    rounded = {tuple(np.round(s, 3)) for s in seg}
    assert (0, 0, 10000, 0) in rounded and (0, 6000, 0, 0) in rounded  # the closed outline
    # the door block at (1000, 0), and turned 90 degrees and doubled at (4000, 6000)
    assert (1000, 0, 1900, 0) in rounded and (1000, 0, 1000, 900) in rounded
    assert (4000, 6000, 4000, 7800) in rounded and (4000, 6000, 2200, 6000) in rounded
    # nested: PAIR at (0, 12000) holds two doors
    assert (0, 12000, 900, 12000) in rounded and (2000, 12000, 2900, 12000) in rounded
    assert d["skipped"].get("TEXT") == 1
    assert not any(s[1] == -1000 for s in rounded)  # the off layer's line is left out
    walls = [i for i, s in enumerate(rounded) if s == (0, 0, 10000, 0)]
    assert walls
    i = next(i for i, s in enumerate(seg) if tuple(np.round(s, 3)) == (0, 0, 10000, 0))
    assert tuple(d["colours"][i]) == (255, 0, 0)  # BYLAYER: WALLS is red


def test_arcs_and_bulges_are_tessellated_to_2mm(tmp_path):
    d = U.read_dxf(survey_dxf(tmp_path / "s.dxf"))
    seg = segments(d)

    def near(cx, cy, r):  # chords with both ends on the circle (ezdxf flattens arcs as Beziers: 0.3 mm)
        return seg[(np.abs(np.hypot(seg[:, 0] - cx, seg[:, 1] - cy) - r) < 0.5)
                   & (np.abs(np.hypot(seg[:, 2] - cx, seg[:, 3] - cy) - r) < 0.5)]

    for cx, cy, r, sweep in ((5000, 3000, 1000, 90), (8000, 3000, 500, 360), (1000, 8000, 1000, 180)):
        on = near(cx, cy, r)
        assert len(on) >= 4, (cx, cy)
        # every chord stays within 2 mm (the sagitta) of the curve
        mid = (on[:, 0:2] + on[:, 2:4]) / 2
        sagitta = r - np.hypot(mid[:, 0] - cx, mid[:, 1] - cy)
        assert sagitta.max() <= 2.0 + 0.5
        chord_sweep = sum(2 * math.degrees(math.asin(min(1.0, np.hypot(*(s[2:4] - s[0:2])) / (2 * r)))) for s in on)
        assert chord_sweep == pytest.approx(sweep, abs=0.5)


def test_unitless_metres_and_far_survey_coordinates(tmp_path):
    assert U.read_dxf(survey_dxf(tmp_path / "u.dxf", insunits=0))["units"] is None
    probe = call("underlay_probe", str(tmp_path / "u.dxf"))
    assert probe["ok"] and probe["units"] is None and probe["unit_guess"] == 0.001  # 12 m+ in numbers > 2000
    assert U.read_dxf(survey_dxf(tmp_path / "m.dxf", insunits=6))["units"] == 1.0
    # a survey in map coordinates (metres): float32 alone would lose centimetres at 4 000 km
    doc = ezdxf.new("R2013")
    doc.header["$INSUNITS"] = 6
    doc.modelspace().add_line((512345.678, 4012345.432), (512355.678, 4012345.432))
    doc.saveas(tmp_path / "far.dxf")
    d = U.read_dxf(tmp_path / "far.dxf")
    assert d["origin"] == (512000.0, 4012000.0)
    assert segments(d)[0] == pytest.approx([512345.678, 4012345.432, 512355.678, 4012345.432], abs=1e-4)


def test_large_dxf_reads_in_reasonable_time(tmp_path):
    doc = ezdxf.new("R2013")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    n = 20_000
    for i in range(n):
        msp.add_line((i * 10.0, 0), (i * 10.0, 1000.0 + i % 7))
    doc.saveas(tmp_path / "big.dxf")
    t = time.perf_counter()
    d = U.read_dxf(tmp_path / "big.dxf")
    elapsed = time.perf_counter() - t
    assert len(d["coords"]) == n
    assert elapsed < 30, elapsed
    print(f"\n20 000-line DXF read in {elapsed:.2f} s")


# ---------------------------------------------------------------- PDF and images

def test_image_and_pdf_probe_and_render(tmp_path):
    png = tiny_png(tmp_path / "scan.png", 40, 20, dpi=200)
    assert U._image_size(png) == (40, 20, pytest.approx(200, abs=0.1))
    r = call("underlay_probe", str(png))
    assert r["ok"] and (r["width"], r["height"]) == (40, 20)
    pdf = a_pdf(tmp_path / "plan.pdf")
    r = call("underlay_probe", str(pdf))
    assert r["ok"] and len(r["pages"]) == 2 and r["pages"][1] == {"width": 842.0, "height": 595.0}
    assert not call("underlay_probe", str(tmp_path / "x.dwg"))["ok"]


def test_placing_a_pdf_page_renders_it(tmp_path):
    assert call("new_project", "Under")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    pdf = a_pdf(tmp_path / "plan.pdf")
    assert not call("add_underlay", str(pdf), json.dumps({"storey": storey, "page": 5}))["ok"]
    r = call("add_underlay", str(pdf), json.dumps({"storey": storey, "page": 1}))
    assert r["ok"], r
    u = r["underlay"]
    assert u["kind"] == "pdf" and u["size"] == [842.0, 595.0] and u["base"] == [0.0, 595.0]
    assert u["scale"] == pytest.approx(0.0254 / 72 * 100)  # 1:100
    raster = call("underlay_raster", u["id"])
    assert raster["ok"] and raster["format"] == "bgrx", raster
    assert abs(raster["width"] - 842 * 150 / 72) <= 1 and abs(raster["height"] - 595 * 150 / 72) <= 1
    data = open(raster["path"], "rb").read()
    assert len(data) == raster["stride"] * raster["height"]
    assert data[:4] == b"\xff\xff\xff\xff"  # a blank page renders white
    assert call("set_underlay", u["id"], json.dumps({"page": 0}))["underlay"]["size"] == [595.0, 842.0]


# ---------------------------------------------------------------- placing and settings

def test_place_dxf_on_a_level(tmp_path):
    assert call("new_project", "Under")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    entities = call("count_entities", "IfcRoot")
    r = call("add_underlay", str(survey_dxf(tmp_path / "s.dxf")), json.dumps({"storey": storey}))
    assert r["ok"], r
    u = r["underlay"]
    assert (u["kind"], u["scale"], u["base"], u["layer"], u["missing"]) == ("dxf", 0.001, [0.0, 0.0], "Underlays", False)
    assert u["file"] == U.blob_name((tmp_path / "s.dxf").read_bytes(), ".dxf")
    assert call("underlays", storey)["underlays"][0]["id"] == u["id"]
    assert call("underlays", "another")["underlays"] == []
    meta, coords, colours = b.underlay_lines(u["id"])
    meta = json.loads(meta)
    assert meta["count"] == len(coords) // 16 == len(colours) // 3 > 20
    # nothing goes into the IFC: export stays clean
    assert call("count_entities", "IfcRoot") == entities
    # its layer is listed (empty) so the layer's state can hide it
    assert "Underlays" in call("layer_members")["layers"]
    assert any(l["name"] == "Underlays" for l in call("layers")["layers"])
    # placement and display changes, checked
    r = call("set_underlay", u["id"], json.dumps({"x": 2.5, "y": -1, "rotation": 30, "opacity": 0.4, "greyscale": True}))
    assert r["ok"] and r["underlay"]["rotation"] == 30
    assert not call("set_underlay", u["id"], json.dumps({"opacity": 2}))["ok"]
    assert not call("set_underlay", u["id"], json.dumps({"scale": 0}))["ok"]
    assert not call("set_underlay", u["id"], json.dumps({"file": "x"}))["ok"]
    assert not call("set_underlay", u["id"], json.dumps({"tint": "red"}))["ok"]
    assert call("remove_underlay", u["id"])["ok"]
    assert call("underlays")["underlays"] == []


def test_unitless_dxf_needs_its_unit(tmp_path):
    assert call("new_project", "Under")["ok"]
    path = str(survey_dxf(tmp_path / "u.dxf", insunits=0))
    r = call("add_underlay", path, "{}")
    assert not r["ok"] and "unit" in r["error"]
    r = call("add_underlay", path, json.dumps({"units": 0.01}))
    assert r["ok"] and r["underlay"]["scale"] == 0.01


def test_far_survey_is_centred(tmp_path):
    assert call("new_project", "Under")["ok"]
    r = call("add_underlay", str(survey_dxf(tmp_path / "far.dxf", insunits=6, offset=(512000, 4012000))), "{}")
    assert r["ok"]
    bx, by = r["underlay"]["base"]
    assert 512000 < bx < 522000 and 4012000 < by < 4030000  # the drawing's middle lands on the origin


def test_underlay_placement_centred_or_survey(tmp_path):
    """D92: the placement option keeps the drawing's survey coordinates or centres it on the origin."""
    assert call("new_project", "Under")["ok"]
    far = str(survey_dxf(tmp_path / "far.dxf", insunits=6, offset=(512000, 4012000)))
    survey = call("add_underlay", far, json.dumps({"placement": "survey"}))
    assert survey["ok"] and survey["underlay"]["base"] == [0.0, 0.0]
    centred = call("add_underlay", survey_dxf(tmp_path / "far2.dxf", insunits=6, offset=(512000, 4012000)),
                   json.dumps({"placement": "centred"}))
    assert centred["ok"]
    bx, _by = centred["underlay"]["base"]
    assert 512000 < bx < 522000


def test_underlay_edits_are_undo_steps(tmp_path):
    """D92: placing, moving or removing an underlay is one undo step."""
    assert call("new_project", "Under")["ok"]
    assert call("add_underlay", str(survey_dxf(tmp_path / "s.dxf")), "{}")["ok"]
    u = call("underlays")["underlays"][0]["id"]
    assert call("set_underlay", u, json.dumps({"x": 3.0, "rotation": 30}))["ok"]
    assert call("underlays")["underlays"][0]["x"] == 3.0
    assert call("undo")["ok"]
    assert call("underlays")["underlays"][0]["x"] == 0.0
    assert call("redo")["ok"]
    assert call("underlays")["underlays"][0]["x"] == 3.0
    assert call("undo")["ok"] and call("undo")["ok"]  # the move, then the placement
    assert call("underlays")["underlays"] == []


def test_images_take_their_dpi_at_1_to_100(tmp_path):
    assert call("new_project", "Under")["ok"]
    r = call("add_underlay", str(tiny_png(tmp_path / "scan.png", dpi=200)), "{}")
    assert r["ok"]
    assert r["underlay"]["scale"] == pytest.approx(0.0254 / 200 * 100, rel=1e-4)
    assert call("underlay_raster", r["underlay"]["id"])["format"] == "image"


def test_settings_validation_and_merge():
    good = {"id": "a", "file": "0" * 40 + ".dxf", "kind": "dxf", "scale": 0.001}
    assert U.validate([good]) is None
    assert U.validate([good, dict(good)]) is not None  # same id twice
    assert U.validate([{**good, "file": "../evil.dxf"}]) is not None
    assert U.validate([{**good, "kind": "dwg"}]) is not None
    base = [good]
    ours = [{**good, "x": 1.0}]
    theirs = [good, {**good, "id": "b"}]
    merged, clash = U.merge_entries(base, ours, theirs)
    assert merged == [{**good, "x": 1.0}, {**good, "id": "b"}] and not clash
    merged, clash = U.merge_entries(base, [{**good, "x": 1.0}], [{**good, "x": 2.0}])
    assert merged == [{**good, "x": 1.0}] and clash
    merged, _ = U.merge_entries(base, [], [good])  # removed on our side
    assert merged == []


# ---------------------------------------------------------------- stored with the project and its versions

def _tree(project):
    return project._head_entries()


def test_underlay_files_are_versioned(tmp_path):
    from kimbim import versioning as V

    assert call("new_project", "Under")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    t = call("wall_types")["types"][0]["guid"]
    call("create_wall", storey, t, 0, 0, 5, 0, 3.0, "", "")
    assert call("enable_versioning", str(tmp_path / "p"), "First")["ok"]
    dxf_path = survey_dxf(tmp_path / "s.dxf")
    r = call("add_underlay", str(dxf_path), json.dumps({"storey": storey}))
    assert r["ok"], r
    u = r["underlay"]
    local = tmp_path / "p" / ".kimbim" / "underlays" / u["file"]
    assert local.is_file() and local.read_bytes() == dxf_path.read_bytes()
    assert call("version_changes")["settings"] == ["underlays"]
    assert call("save_version", "Survey")["ok"]
    tree = _tree(V._project)
    assert f"files/{u['file']}" in tree
    assert tree[f"files/{u['file']}"] == u["file"].split(".")[0]  # named by its blob id
    # records stay records: the file is not taken for one
    assert all(not k.startswith("files") for k in V._project._records("HEAD"))
    assert call("compare", call("history", 10)["versions"][-1]["id"], "HEAD")["ok"]
    # a version without it, then back: the file comes back from the history
    assert call("create_option", "B")["ok"]
    assert call("remove_underlay", u["id"])["ok"]
    assert call("save_version", "No survey")["ok"]
    assert f"files/{u['file']}" not in _tree(V._project)
    assert not local.exists()  # saving prunes what the settings no longer use
    assert call("switch_option", "main")["ok"]
    back = call("underlays", storey)["underlays"]
    assert [x["id"] for x in back] == [u["id"]] and not back[0]["missing"]
    assert local.read_bytes() == dxf_path.read_bytes()
    U._segments_cache.clear()
    meta, coords, _colours = b.underlay_lines(u["id"])
    assert json.loads(meta)["count"] == len(coords) // 16 > 0


def test_kim_round_trip_keeps_the_underlay(tmp_path, data_dir):
    assert call("new_project", "Under")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    png = tiny_png(tmp_path / "scan.png")
    r = call("add_underlay", str(png), json.dumps({"storey": storey, "x": 3.0, "rotation": 15.0, "opacity": 0.3}))
    assert r["ok"], r
    u = r["underlay"]
    kim = tmp_path / "p.kim"
    assert call("save_as_kim", str(kim), "First")["ok"]
    with zipfile.ZipFile(kim) as z:
        names = z.namelist()
    assert f".kimbim/underlays/{u['file']}" in names
    assert call("close_document")["ok"]
    assert call("new_project", "Other")["ok"]
    assert call("underlays")["underlays"] == []
    r = call("open_kim", str(kim))
    assert r["ok"], r
    assert call("open_model", r["path"])["ok"]
    got = call("underlays", storey)["underlays"]
    assert len(got) == 1 and (got[0]["x"], got[0]["rotation"], got[0]["opacity"]) == (3.0, 15.0, 0.3)
    assert not got[0]["missing"] and open(got[0]["path"], "rb").read() == png.read_bytes()
    assert call("close_document")["ok"]
