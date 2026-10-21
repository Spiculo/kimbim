# SPDX-License-Identifier: GPL-3.0-or-later
"""Underlays (D85, doc 14 §12 and §18): a DXF, a PDF page or an image placed on a level, drawn under
the model in plan views, to trace over (Archicad's placed drawing with Trace & Reference, Revit's
linked CAD / import underlay).

The file itself is copied into the project: the working folder's `.kimbim/underlays/`, named by its
Git blob id (`<sha1>.<ext>`), so it travels inside the .kim and is stored once in the version history
however many versions or underlays use it (the `files/` folder of each version's tree, layout.py). Its
placement and display (level, insertion point, rotation, scale, page, opacity, greyscale/tint, shown,
locked, layer) are an entry of the project setting `underlays` (D72): versioned and merged with the
other settings, and nothing goes into the IFC, so IFC export stays clean.

Placement: a drawing point `base` (drawing units; DXF units, PDF points, image pixels with y down) goes
to the level point (x, y) metres, the drawing turned by `rotation` degrees, `scale` metres per drawing
unit. A DXF's scale comes from $INSUNITS (asked when unitless); a PDF or image is calibrated by two
points and their real distance (the app) or from a drawing scale (1:N, at 72 points or `dpi` pixels
per inch).

DXF linework is read with ezdxf (MIT): blocks exploded (nested INSERTs, MINSERT arrays), arcs, circles,
ellipses, splines and bulged polylines tessellated to 2 mm on site; text, hatches, points and entities
on DXF layers that are off or frozen are left out. The segments are cached per file in
`.kimbim/cache/underlays/` (not packed). PDF pages are rendered with pypdfium2 (Apache-2.0 / BSD-3),
also cached there.

Same protocol as app_bridge for the bridge functions (strings in, JSON out, never raise).
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import pathlib
import re
import shutil
import uuid

import numpy as np

KINDS = {".dxf": "dxf", ".pdf": "pdf", ".png": "image", ".jpg": "image", ".jpeg": "image"}
FILE_NAME = re.compile(r"[0-9a-f]{40}\.(dxf|pdf|png|jpg|jpeg)")
DEFAULT_LAYER = "Underlays"
TESSELLATION = 0.002  # metres on site: arcs and curves become chords this close to the curve
PDF_DPI = 150
MAX_PIXELS = 8192  # longest side of a rendered PDF page (graphics cards take 16k; memory is the limit)
CACHE_VERSION = 1
# $INSUNITS -> metres per drawing unit (0 = unitless: the app asks)
INSUNITS = {1: 0.0254, 2: 0.3048, 3: 1609.344, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0, 8: 0.0254e-6, 9: 0.0254e-3,
            10: 0.9144, 14: 0.1, 15: 10.0, 16: 100.0, 17: 1e9, 18: 1.495978707e11, 19: 9.4607e15, 20: 3.0857e16,
            21: 0.3048006096, 22: 0.0254000508, 23: 0.9144018288, 24: 1609.3472}
UNIT_NAMES = {0.001: "mm", 0.01: "cm", 0.1: "dm", 1.0: "m", 1000.0: "km", 0.0254: "in", 0.3048: "ft", 0.9144: "yd"}
SKIPPED_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF", "HATCH", "MPOLYGON", "POINT", "IMAGE", "WIPEOUT", "VIEWPORT",
                 "SOLID", "TRACE", "3DFACE", "MESH", "OLE2FRAME", "ACAD_TABLE", "XLINE", "RAY", "LEADER"}
FIELDS = {  # editable fields and their checks
    "name": str, "storey": str, "x": float, "y": float, "rotation": float, "scale": float, "base": list,
    "page": int, "opacity": float, "greyscale": bool, "tint": str, "visible": bool, "locked": bool,
    "layer": str, "show_3d": bool, "dpi": int,
}

_segments_cache: dict = {}  # file name -> (coords float32 (n, 4), colours uint8 (n, 3), origin (2,), info)


# ---------------------------------------------------------------- where the files are

def _work() -> pathlib.Path | None:
    """The open document's working folder: a .kim's unpacked copy, a project folder, or the folder of a
    model versioned in place (enable_versioning)."""
    from . import documents
    from . import versioning as V

    work = documents._doc.get("work")
    if work:
        return pathlib.Path(work)
    return pathlib.Path(V._project.path) if V._project is not None else None


def store_dir() -> pathlib.Path:
    """Where the open document keeps its underlay files: its working folder (packed into the .kim), or,
    for an IFC edited directly (no project settings are kept), a per-computer folder."""
    from . import documents
    from .layout import WORK_FILES_DIR

    work = _work()
    return work / WORK_FILES_DIR if work else documents.data_dir() / "underlays"


def _cache_dir() -> pathlib.Path:
    from . import documents

    work = _work()
    d = work / ".kimbim" / "cache" / "underlays" if work else documents.data_dir() / "cache" / "underlays"
    d.mkdir(parents=True, exist_ok=True)
    return d


def blob_name(data: bytes, ext: str) -> str:
    from .layout import blob_oid

    return f"{blob_oid(data)}{ext.lower()}"


def file_path(name: str) -> pathlib.Path | None:
    """The underlay file on disk, brought back from the version history (by its blob id) when the
    working folder lacks it (a version that had it, an option made elsewhere). None if nowhere."""
    from . import documents
    from . import versioning as V

    if not FILE_NAME.fullmatch(name or ""):
        return None
    p = store_dir() / name
    if p.is_file():
        return p
    for other in (documents.data_dir() / "underlays" / name,):  # placed before the IFC became a project
        if other.is_file():
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(other, p)
            return p
    if V._project is not None:
        try:
            data = V._project.repo.read_blobs([name.split(".")[0]])[0]
        except Exception:
            return None
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p
    return None


def referenced(settings: dict) -> list[str]:
    return sorted({u.get("file", "") for u in settings.get("underlays") or () if FILE_NAME.fullmatch(u.get("file", ""))})


def write_files(work: pathlib.Path) -> None:
    """Every underlay file the settings use, into a project folder (a new .kim or folder; saving):
    what the settings no longer use goes (older versions keep theirs in the history)."""
    from . import settings as S
    from .layout import WORK_FILES_DIR

    target = pathlib.Path(work) / WORK_FILES_DIR
    names = referenced(S.current())
    for name in names:
        if (target / name).is_file():
            continue
        src = file_path(name)
        if src is not None:
            target.mkdir(parents=True, exist_ok=True)
            if src.resolve() != (target / name).resolve():
                shutil.copyfile(src, target / name)
    if target.is_dir():
        for f in target.iterdir():
            if f.is_file() and f.name not in names:
                f.unlink(missing_ok=True)


# ---------------------------------------------------------------- DXF

def dxf_units(doc) -> float | None:
    """Metres per drawing unit from $INSUNITS (None: unitless)."""
    try:
        code = int(doc.header.get("$INSUNITS", 0))
    except (TypeError, ValueError):
        code = 0
    return INSUNITS.get(code)


def _rgb(entity, doc, layer_colours) -> tuple[int, int, int]:
    from ezdxf.colors import aci2rgb

    try:
        tc = entity.dxf.get("true_color")
        if tc is not None:
            r, g, b = (tc >> 16) & 255, (tc >> 8) & 255, tc & 255
            return (0, 0, 0) if (r, g, b) == (255, 255, 255) else (r, g, b)
        aci = entity.dxf.get("color", 256)
    except Exception:
        aci = 256
    if aci == 256:
        aci = layer_colours.get(entity.dxf.get("layer", "0"), 7)
    if aci in (0, 7) or not 1 <= aci <= 255:
        return (0, 0, 0)  # BYBLOCK and white/black follow the background: dark on KimBim's light plan
    return aci2rgb(aci)


def read_dxf(path, tolerance: float | None = None) -> dict:
    """A DXF's model space as 2D segments: {"coords": float32 (n, 4) x1 y1 x2 y2 relative to `origin`,
    "colours": uint8 (n, 3), "origin": (x, y) drawing units (float64), "units": metres per unit or
    None, "extents": [minx, miny, maxx, maxy], "skipped": {type: count}}. `tolerance`: chord error in
    drawing units (default TESSELLATION on site, or 1/5000 of the extents when unitless)."""
    import ezdxf
    from ezdxf import recover
    from ezdxf.disassemble import recursive_decompose
    from ezdxf.path import make_path

    try:
        doc = ezdxf.readfile(str(path))
    except ezdxf.DXFStructureError:
        doc, _auditor = recover.readfile(str(path))
    units = dxf_units(doc)
    msp = doc.modelspace()
    layer_colours, hidden = {}, set()
    for layer in doc.layers:
        name = layer.dxf.name
        layer_colours[name] = abs(layer.dxf.get("color", 7)) or 7
        if layer.is_off() or layer.is_frozen():
            hidden.add(name)
    if tolerance is None:
        if units:
            tolerance = TESSELLATION / units
        else:
            ext = _header_extents(doc)
            tolerance = max(ext[2] - ext[0], ext[3] - ext[1], 1.0) / 5000 if ext else 0.01
    xs: list[float] = []  # x1 y1 x2 y2 ... flat, float64 until the origin is taken off
    colours: list[tuple] = []
    skipped: dict[str, int] = {}

    def add_points(pts, colour, closed=False):
        n = len(pts)
        if n < 2:
            return
        last = n if closed else n - 1
        for i in range(last):
            a, b = pts[i], pts[(i + 1) % n]
            if a[0] == b[0] and a[1] == b[1]:
                continue
            xs.extend((a[0], a[1], b[0], b[1]))
            colours.append(colour)

    for e in recursive_decompose(msp):
        t = e.dxftype()
        layer = e.dxf.get("layer", "0")
        if layer in hidden:
            continue
        if t in SKIPPED_TYPES:
            skipped[t] = skipped.get(t, 0) + 1
            continue
        try:
            colour = _rgb(e, doc, layer_colours)
            if t == "LINE":
                s, f = e.dxf.start, e.dxf.end
                add_points([(s.x, s.y), (f.x, f.y)], colour)
            elif t == "LWPOLYLINE" and not any(b for *_xy, b in e.get_points("xyb")):
                add_points([(p[0], p[1]) for p in e.get_points("xy")], colour, e.closed)
            elif t in ("LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "HELIX"):
                if t == "POLYLINE" and (e.is_poly_face_mesh or e.is_polygon_mesh):
                    skipped[t] = skipped.get(t, 0) + 1
                    continue
                p = make_path(e)
                pts = [(v.x, v.y) for v in p.flattening(tolerance)]
                add_points(pts, colour)
            else:
                skipped[t] = skipped.get(t, 0) + 1
        except Exception:  # one broken entity never loses the drawing
            skipped[t] = skipped.get(t, 0) + 1
    arr = np.asarray(xs, dtype=np.float64).reshape(-1, 4)
    if len(arr):
        mins = np.minimum(arr[:, 0:2].min(axis=0), arr[:, 2:4].min(axis=0))
        maxs = np.maximum(arr[:, 0:2].max(axis=0), arr[:, 2:4].max(axis=0))
        extents = [float(mins[0]), float(mins[1]), float(maxs[0]), float(maxs[1])]
    else:
        extents = [0.0, 0.0, 0.0, 0.0]
    # Survey drawings sit far from 0,0 (map coordinates): float32 keeps ~7 digits, so the segments are
    # stored relative to a round point inside the drawing, which is kept in float64.
    origin = (_round_origin(extents[0]), _round_origin(extents[1]))
    rel = arr - np.array([origin[0], origin[1], origin[0], origin[1]])
    return {"coords": rel.astype(np.float32), "colours": np.asarray(colours, dtype=np.uint8).reshape(-1, 3),
            "origin": origin, "units": units, "extents": extents, "skipped": skipped}


def _round_origin(v: float) -> float:
    return float(math.floor(v / 1000.0) * 1000.0) if abs(v) > 1000 else 0.0


def _header_extents(doc):
    try:
        lo, hi = doc.header.get("$EXTMIN"), doc.header.get("$EXTMAX")
        if lo and hi and hi[0] > lo[0]:
            return [lo[0], lo[1], hi[0], hi[1]]
    except Exception:
        pass
    return None


def _segments(name: str, source: pathlib.Path | None = None):
    """(coords, colours, origin, info) for an underlay DXF, from memory, the cache folder or the file
    (`source`: read from there, a file about to be placed whose blob name is `name`)."""
    hit = _segments_cache.get(name)
    if hit is not None:
        return hit
    cache = _cache_dir() / f"{name}.v{CACHE_VERSION}.npz"
    if cache.is_file():
        try:
            with np.load(cache, allow_pickle=False) as z:
                info = json.loads(str(z["info"]))
                hit = (z["coords"], z["colours"], tuple(info["origin"]), info)
        except Exception:
            hit = None
    if hit is None:
        p = source or file_path(name)
        if p is None:
            raise FileNotFoundError(f"the underlay file {name} is missing")
        d = read_dxf(p)
        info = {"origin": list(d["origin"]), "units": d["units"], "extents": d["extents"], "skipped": d["skipped"]}
        hit = (d["coords"], d["colours"], d["origin"], info)
        try:
            tmp = cache.with_suffix(".tmp.npz")
            np.savez(tmp, coords=d["coords"], colours=d["colours"], info=np.array(json.dumps(info)))
            tmp.replace(cache)
        except OSError:
            pass
    _segments_cache[name] = hit
    return hit


# ---------------------------------------------------------------- PDF and images

def _pdf_pages(path) -> list[dict]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        return [{"width": float(pdf[i].get_size()[0]), "height": float(pdf[i].get_size()[1])} for i in range(len(pdf))]
    finally:
        pdf.close()


def _image_size(path) -> tuple[int, int, float]:
    """(width, height, dpi) of a PNG or JPEG from its header (no image library needed)."""
    data = pathlib.Path(path).read_bytes()[:256 * 1024]
    dpi = 96.0
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        i = data.find(b"pHYs")
        if i > 0:
            ppu, unit = int.from_bytes(data[i + 4:i + 8], "big"), data[i + 12]
            if unit == 1 and ppu > 0:
                dpi = ppu * 0.0254
        return w, h, dpi
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            length = int.from_bytes(data[i + 2:i + 4], "big")
            if marker == 0xE0 and data[i + 4:i + 9] == b"JFIF\x00":
                units, xd = data[i + 11], int.from_bytes(data[i + 12:i + 14], "big")
                if units == 1 and xd > 0:
                    dpi = float(xd)
                elif units == 2 and xd > 0:
                    dpi = xd * 2.54
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = int.from_bytes(data[i + 5:i + 7], "big"), int.from_bytes(data[i + 7:i + 9], "big")
                return w, h, dpi
            i += 2 + length
    raise ValueError("not a PNG or JPEG image")


def render_pdf(name: str, page: int, dpi: int) -> dict:
    """A PDF page rendered to raw 32-bit pixels (BGRX, the layout of QImage::Format_RGB32) in the cache
    folder: {"path", "width", "height", "stride", "dpi"} (dpi lowered for pages over MAX_PIXELS)."""
    import pypdfium2 as pdfium

    src = file_path(name)
    if src is None:
        raise FileNotFoundError(f"the underlay file {name} is missing")
    pdf = pdfium.PdfDocument(str(src))
    try:
        if not 0 <= page < len(pdf):
            raise ValueError(f"the PDF has {len(pdf)} page(s)")
        pg = pdf[page]
        w_pt, h_pt = pg.get_size()
        dpi = max(24, min(int(dpi or PDF_DPI), 600))
        if max(w_pt, h_pt) * dpi / 72 > MAX_PIXELS:
            dpi = int(MAX_PIXELS * 72 / max(w_pt, h_pt))
        out = _cache_dir() / f"{name}.p{page}.{dpi}.bgrx"
        meta = out.with_suffix(".json")
        if out.is_file() and meta.is_file():
            return {**json.loads(meta.read_text()), "path": str(out)}
        bitmap = pg.render(scale=dpi / 72, prefer_bgrx=True, fill_color=(255, 255, 255, 255))
        info = {"width": int(bitmap.width), "height": int(bitmap.height), "stride": int(bitmap.stride), "dpi": dpi,
                "channels": int(bitmap.n_channels)}
        if info["channels"] != 4:
            raise ValueError("unexpected PDF bitmap format")
        out.write_bytes(bytes(bitmap.buffer))
        meta.write_text(json.dumps(info))
        return {**info, "path": str(out)}
    finally:
        pdf.close()


# ---------------------------------------------------------------- the entries

def _entries() -> list[dict]:
    from . import settings as S

    return [u for u in S.current().get("underlays") or () if isinstance(u, dict)]


def _store(entries: list[dict]) -> dict:
    """Save the underlay list. It goes through one undoable transaction (D92: underlay edits are undo
    steps), unless a step is already open (a console edit block)."""
    from . import app_bridge as B
    from . import settings as S

    result: dict = {}

    def action():
        result.update(json.loads(S.set_project_settings(json.dumps({"underlays": entries}))))
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "could not save the underlays"))
        return 1, [], []

    try:
        if B._model is not None and B._step is None:
            B._run_settings(action)
        else:
            action()
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    return result


def validate(value) -> str | None:
    if not isinstance(value, list):
        return "underlays must be a list"
    ids = set()
    for u in value:
        if not isinstance(u, dict):
            return "an underlay must be an object"
        if not isinstance(u.get("id"), str) or not u["id"] or u["id"] in ids:
            return "every underlay needs its own id"
        ids.add(u["id"])
        if not FILE_NAME.fullmatch(u.get("file", "")):
            return f"underlay {u['id']}: bad file name"
        if u.get("kind") not in ("dxf", "pdf", "image"):
            return f"underlay {u['id']}: unknown kind"
        for k, v in u.items():
            err = _field_error(k, v)
            if err:
                return f"underlay {u['id']}: {err}"
    return None


def _field_error(k: str, v) -> str | None:
    t = FIELDS.get(k)
    if t is None:
        return None
    if t is float:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return f"{k} must be a number"
        if k == "scale" and v <= 0:
            return "the scale must be above 0"
        if k == "opacity" and not 0.05 <= v <= 1:
            return "the opacity must be between 5% and 100%"
    elif t is int:
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            return f"{k} must be a whole number"
    elif t is list:
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)):
            return f"{k} must be two numbers"
    elif not isinstance(v, t):
        return f"{k} has the wrong type"
    if k == "tint" and v and not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        return "the tint must be a colour like #3366cc"
    return None


def _public(u: dict) -> dict:
    """An entry as the app sees it: defaults filled in, its file's path, size and state."""
    out = {"page": 0, "opacity": 0.5, "greyscale": False, "tint": "", "visible": True, "locked": False,
           "layer": DEFAULT_LAYER, "show_3d": False, "rotation": 0.0, "x": 0.0, "y": 0.0, "scale": 1.0,
           "base": [0.0, 0.0], "dpi": PDF_DPI, **copy.deepcopy(u)}
    p = file_path(u.get("file", ""))
    out["missing"] = p is None
    out["path"] = str(p) if p else ""
    return out


def _fail(message: str) -> str:
    from . import app_bridge as B

    return B._dump({"ok": False, "error": message})


# ---------------------------------------------------------------- bridge

def underlay_probe(path: str) -> str:
    """What a file would be as an underlay, before placing it: kind; a DXF's units ($INSUNITS, None =
    ask), extents and segment count; a PDF's pages (points); an image's size and dpi."""
    from . import app_bridge as B

    p = pathlib.Path(path)
    kind = KINDS.get(p.suffix.lower())
    if kind is None:
        return _fail("choose a DXF, PDF, PNG or JPEG file")
    try:
        if kind == "dxf":
            coords, _colours, _origin, d = _segments(blob_name(p.read_bytes(), p.suffix), p)  # placing reuses it
            units = d["units"]
            ext = d["extents"]
            guess = units
            if guess is None:  # unitless: big numbers are usually millimetres
                size = max(ext[2] - ext[0], ext[3] - ext[1])
                guess = 0.001 if size > 2000 else 1.0
            return B._dump({"ok": True, "kind": kind, "units": units, "unit_guess": guess, "extents": ext,
                            "segments": int(len(coords)), "skipped": d["skipped"],
                            "unit_name": UNIT_NAMES.get(units, "") if units else ""})
        if kind == "pdf":
            return B._dump({"ok": True, "kind": kind, "pages": _pdf_pages(p)})
        w, h, dpi = _image_size(p)
        return B._dump({"ok": True, "kind": kind, "width": w, "height": h, "dpi": dpi})
    except Exception as ex:
        return _fail(f"could not read {p.name}: {ex}")


def add_underlay(path: str, options_json: str = "{}") -> str:
    """Copy a file into the project and place it (options: storey, x, y, rotation, scale, base, page,
    units for a unitless DXF, opacity, layer...). The default placement: a DXF at its units with its
    origin on the level's origin (its centre, when the drawing lies over 1 km away, as surveys in map
    coordinates do); a PDF page at 1:100, an image at 1:100 and its dpi, bottom left corner on the origin."""
    from . import app_bridge as B
    from . import settings as S

    if B._model is None:
        return _fail("no model open")
    p = pathlib.Path(path)
    kind = KINDS.get(p.suffix.lower())
    if kind is None:
        return _fail("choose a DXF, PDF, PNG or JPEG file")
    try:
        options = json.loads(options_json or "{}")
        data = p.read_bytes()
    except (ValueError, OSError) as ex:
        return _fail(str(ex))
    name = blob_name(data, p.suffix)
    target = store_dir() / name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
    except OSError as ex:
        return _fail(f"could not copy the file into the project: {ex}")
    entry = {"id": uuid.uuid4().hex[:12], "name": p.name, "file": name, "kind": kind,
             "storey": str(options.get("storey", "")), "x": 0.0, "y": 0.0, "rotation": 0.0,
             "opacity": 0.5 if kind == "dxf" else 0.6, "layer": DEFAULT_LAYER, "visible": True, "locked": False}
    try:
        if kind == "dxf":
            _c, _col, _o, info = _segments(name)
            units = info["units"] or options.get("units")
            if not units:
                return _fail("the DXF has no units: say which unit it was drawn in")
            entry["scale"] = float(units)
            ext = info["extents"]
            far = max(abs(v) for v in ext) * float(units) > 1000 if any(ext) else False
            entry["base"] = [(ext[0] + ext[2]) / 2, (ext[1] + ext[3]) / 2] if far else [0.0, 0.0]
            entry["opacity"] = 1.0
        elif kind == "pdf":
            pages = _pdf_pages(target)
            page = int(options.get("page", 0))
            if not 0 <= page < len(pages):
                return _fail(f"the PDF has {len(pages)} page(s)")
            entry["page"] = page
            entry["scale"] = 0.0254 / 72 * 100  # 1:100
            entry["base"] = [0.0, pages[page]["height"]]  # the page's bottom left (y runs down)
            entry["size"] = [pages[page]["width"], pages[page]["height"]]
        else:
            w, h, dpi = _image_size(target)
            entry["scale"] = 0.0254 / dpi * 100
            entry["base"] = [0.0, float(h)]
            entry["size"] = [float(w), float(h)]
            entry["dpi_image"] = dpi
        # D92: placement, centred (the drawing's centre on the level's origin) or survey coordinates
        # (the drawing's own origin kept, e.g. map/georeferenced drawings).
        placement = str(options.get("placement", ""))
        if placement == "centred":
            if kind == "dxf":
                ext = info["extents"]
                entry["base"] = [(ext[0] + ext[2]) / 2, (ext[1] + ext[3]) / 2]
            else:
                w, h = entry["size"]
                entry["base"] = [w / 2, h / 2]
        elif placement == "survey":
            entry["base"] = [0.0, 0.0]
    except Exception as ex:
        return _fail(f"could not read {p.name}: {ex}")
    for k in ("x", "y", "rotation", "scale", "base", "opacity", "layer", "greyscale", "tint", "show_3d", "name"):
        if k in options:
            entry[k] = options[k]
    for k, v in entry.items():
        if (err := _field_error(k, v)) is not None:
            return _fail(err)
    r = _store(_entries() + [entry])
    if not r.get("ok"):
        return B._dump(r)
    return B._dump({"ok": True, "underlay": _public(entry), "settings": r["settings"], "dirty": r.get("dirty")})


def underlays(storey: str = "") -> str:
    """The project's underlays (those on `storey` when given), as the app draws them."""
    from . import app_bridge as B

    out = [_public(u) for u in _entries() if not storey or u.get("storey") == storey]
    return B._dump({"ok": True, "underlays": out})


def set_underlay(id: str, changes_json: str) -> str:
    """Change an underlay's placement or display (any of FIELDS)."""
    from . import app_bridge as B

    try:
        changes = json.loads(changes_json)
    except ValueError as ex:
        return _fail(f"bad input: {ex}")
    if not isinstance(changes, dict):
        return _fail("bad input: expected an object")
    entries = _entries()
    found = next((u for u in entries if u.get("id") == id), None)
    if found is None:
        return _fail(f"no underlay {id}")
    for k, v in changes.items():
        if k not in FIELDS:
            return _fail(f"{k} cannot be changed")
        if (err := _field_error(k, v)) is not None:
            return _fail(err)
    if found["kind"] == "pdf" and "page" in changes and changes["page"] != found.get("page", 0):
        pages = _pdf_pages(file_path(found["file"]))
        if changes["page"] >= len(pages):
            return _fail(f"the PDF has {len(pages)} page(s)")
        found["size"] = [pages[changes["page"]]["width"], pages[changes["page"]]["height"]]
    found.update(copy.deepcopy(changes))
    r = _store(entries)
    if not r.get("ok"):
        return B._dump(r)
    return B._dump({"ok": True, "underlay": _public(found), "dirty": r.get("dirty")})


def remove_underlay(id: str) -> str:
    from . import app_bridge as B

    entries = _entries()
    left = [u for u in entries if u.get("id") != id]
    if len(left) == len(entries):
        return _fail(f"no underlay {id}")
    r = _store(left)
    return B._dump({"ok": bool(r.get("ok")), "dirty": r.get("dirty"), **({"error": r["error"]} if "error" in r else {})})


def underlay_lines(id: str):
    """A DXF underlay's linework: (meta JSON, coords float32 LE x1 y1 x2 y2 per segment in drawing units
    relative to meta["origin"], colours uint8 RGB per segment). None when unknown."""
    from . import app_bridge as B

    u = next((u for u in _entries() if u.get("id") == id), None)
    if u is None or u.get("kind") != "dxf":
        return None
    try:
        coords, colours, origin, info = _segments(u["file"])
    except Exception as ex:
        return (B._dump({"ok": False, "error": str(ex)}), b"", b"")
    meta = {"ok": True, "count": int(len(coords)), "origin": list(origin), "extents": info["extents"],
            "skipped": info["skipped"]}
    return (B._dump(meta), np.ascontiguousarray(coords, dtype="<f4").tobytes(), np.ascontiguousarray(colours).tobytes())


def underlay_raster(id: str) -> str:
    """Where a PDF underlay's page is rendered (raw BGRX pixels, see render_pdf), or an image's file."""
    from . import app_bridge as B

    u = next((u for u in _entries() if u.get("id") == id), None)
    if u is None or u.get("kind") == "dxf":
        return _fail(f"no PDF or image underlay {id}")
    try:
        if u["kind"] == "image":
            p = file_path(u["file"])
            if p is None:
                return _fail(f"the underlay file {u.get('name')} is missing")
            return B._dump({"ok": True, "format": "image", "path": str(p)})
        return B._dump({"ok": True, "format": "bgrx", **render_pdf(u["file"], int(u.get("page", 0)), int(u.get("dpi", PDF_DPI)))})
    except Exception as ex:
        return _fail(f"could not render {u.get('name')}: {ex}")


def underlay_layers() -> list[str]:
    return sorted({u.get("layer") or DEFAULT_LAYER for u in _entries()})


def merge_entries(base: list, ours: list, theirs: list) -> tuple[list, bool]:
    """Combine two options' underlays (settings.merge): underlay by underlay against the common version,
    as settings are key by key; one changed differently on both sides keeps ours (True: report it)."""
    b, o, t = ({u.get("id"): u for u in side if isinstance(u, dict)} for side in (base, ours, theirs))
    order = [u.get("id") for u in ours if isinstance(u, dict)]
    order += [u.get("id") for u in theirs if isinstance(u, dict) and u.get("id") not in o]
    out, clash = [], False
    for i in order:
        bu, ou, tu = b.get(i), o.get(i), t.get(i)
        if ou == tu or tu == bu:
            value = ou
        elif ou == bu:
            value = tu
        else:
            value, clash = ou, True
        if value is not None:
            out.append(value)
    return out, clash


# ---------------------------------------------------------------- figures (D98)
# On a worksheet, a picture placed as an underlay is a *figure* (Archicad's Figure tool): it prints.
# Its drawing embeds it as an SVG <image> mapped exactly as the view shows it (pixel -> level -> paper).

def png_bytes(width: int, height: int, rows_rgb) -> bytes:
    """A PNG (8-bit RGB) from `height` rows of 3*width bytes; zlib only, no image library."""
    import struct
    import zlib

    raw = b"".join(b"\x00" + bytes(r) for r in rows_rgb)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _figure_image(u: dict):
    """(mime, bytes, width px, height px, drawing units per pixel) of a figure, or None."""
    if u.get("kind") == "image":
        p = file_path(u.get("file", ""))
        if p is None:
            return None
        data = p.read_bytes()
        w, h, _dpi = _image_size(p)
        return ("image/png" if data[:4] == b"\x89PNG" else "image/jpeg"), data, w, h, 1.0
    if u.get("kind") == "pdf":
        r = render_pdf(u["file"], int(u.get("page", 0)), int(u.get("dpi", PDF_DPI)))
        w, h, stride = r["width"], r["height"], r["stride"]
        buf = pathlib.Path(r["path"]).read_bytes()
        rows = []
        for y in range(h):
            row = buf[y * stride:y * stride + 4 * w]
            rgb = bytearray(3 * w)
            rgb[0::3], rgb[1::3], rgb[2::3] = row[2::4], row[1::4], row[0::4]  # BGRX -> RGB
            rows.append(rgb)
        return "image/png", png_bytes(w, h, rows), w, h, 72.0 / r["dpi"]  # PDF points per pixel
    return None


def figures_svg(storey_guid: str, to_paper) -> list[str]:
    """SVG <image> elements, in paper millimetres, for the pictures placed on a level (D98)."""
    import base64
    import math

    out = []
    for u in _entries():
        if u.get("storey") != storey_guid or u.get("kind") not in ("image", "pdf"):
            continue
        u = _public(u)
        if not u.get("visible", True) or u.get("missing"):
            continue
        try:
            got = _figure_image(u)
        except Exception:  # an unreadable file leaves a gap, not a broken drawing
            got = None
        if got is None:
            continue
        mime, data, w, h, units = got
        bx, by = (float(v) for v in (u.get("base") or [0.0, 0.0]))
        s, r = float(u["scale"]), math.radians(float(u["rotation"]))
        c, sn = math.cos(r), math.sin(r)

        def world(px, py):  # pixel -> drawing units (y down) -> level metres
            lx, ly = (px * units - bx) * s, (by - py * units) * s
            return float(u["x"]) + lx * c - ly * sn, float(u["y"]) + lx * sn + ly * c

        p00, p10, p01 = (to_paper(*world(*q)) for q in ((0, 0), (1, 0), (0, 1)))
        a, b = p10[0] - p00[0], p10[1] - p00[1]
        cc, d = p01[0] - p00[0], p01[1] - p00[1]
        href = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
        out.append(f'<image data-figure="{u["id"]}" x="0" y="0" width="{w}" height="{h}" preserveAspectRatio="none" '
                   f'transform="matrix({a:.6g} {b:.6g} {cc:.6g} {d:.6g} {p00[0]:.4f} {p00[1]:.4f})" '
                   f'xlink:href="{href}" href="{href}"/>')
    return out
