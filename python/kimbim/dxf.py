# SPDX-License-Identifier: GPL-3.0-or-later
"""DXF export of drawings and sheets (D83, doc 14 §14), written with ezdxf (MIT).

A drawing goes to **model space at real size** in the project's length unit (mm, m...): plans in world
coordinates (they overlay the IFC), sections and elevations with X along the marker line and Y the true
elevation. A sheet goes to a **paper-space layout** (millimetres) named after it: frame, title block,
view titles and legend drawn there, each placed drawing a **block inserted at its scale** (not a
viewport, so the drawings' model coordinates need not share one model space); model space holds the
same blocks at real size, side by side.

Both start from the drawing's cached hidden-line SVG (drawings.raw_drawing, D60) and style it the way
graphics.style_svg does (D73), but into DXF: each pen's weight becomes a lineweight and its colour an
ACI colour plus the true colour (black stays ACI 7, which follows the CAD background); D73 line types
become linetypes (patterns in paper mm, $LTSCALE takes them to model units); a cut fill is a solid
HATCH (on the element layer's "-PATT" sublayer); text is TEXT; a dimension chain is real DIMENSION
entities (one per segment, sharing the dimension line), or exploded lines and text on request.

Layers: by KimBim layer (the IFC presentation layer; Archicad's translator default), with elements
without one on the layer of their kind; or by element kind (US National CAD Standard names, as Revit
exports). Same protocol as app_bridge for the bridge functions (strings in, JSON out, never raise).
"""
from __future__ import annotations

import json
import math
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import ezdxf
import ezdxf.bbox
import ezdxf.zoom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.unit
import numpy as np
from ezdxf.colors import DXF_DEFAULT_COLORS, int2rgb
from ezdxf.enums import TextEntityAlignment

from . import app_bridge as B
from . import authoring as A
from . import drawgen as G
from . import drawings as D

SVG = "{http://www.w3.org/2000/svg}"
IFC = "{http://www.ifcopenshell.org/ns}"
DXF_VERSION = "R2013"
LAYER_MODES = ("layer", "kind", "iso", "pen")
DIMENSION_MODES = ("native", "exploded")
COLOUR_MODES = ("exact", "aci", "lineweight")
LINEWEIGHTS = (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211)
# Element kind -> layer (US National CAD Standard, the names Revit's DWG export uses by default).
KIND_LAYERS = {
    "walls": "A-WALL", "columns": "S-COLS", "beams": "S-BEAM", "slabs": "S-SLAB", "roofs": "A-ROOF",
    "stairs": "A-FLOR-STRS", "railings": "A-FLOR-HRAL", "doors": "A-DOOR", "windows": "A-GLAZ",
    "coverings": "A-FLOR", "furniture": "I-FURN", "plumbing": "P-FIXT", "hvac": "M-HVAC",
    "electrical": "E-POWR", "structure_other": "S-MISC", "rooms": "A-AREA", "annotations": "A-ANNO-NOTE",
    "grids": "S-GRID", "other": "A-GENM",
}
OVERLAY_LAYERS = {"swing": "A-DOOR", "window": "A-GLAZ", "room": "A-AREA-IDEN", "marker": "A-ANNO-SYMB",
                  "stair": "A-FLOR-STRS"}
# ISO 13567-style names (D92: a layer-scheme preset).
ISO_LAYERS = {
    "walls": "A-WALL-FULL", "columns": "S-COLS", "beams": "S-BEAM", "slabs": "S-SLAB", "roofs": "A-ROOF",
    "stairs": "A-FLOR-STRS", "railings": "A-FLOR-HRAL", "doors": "A-DOOR", "windows": "A-GLAZ",
    "coverings": "A-FLOR", "furniture": "I-FURN", "plumbing": "P-FIXT", "hvac": "M-HVAC",
    "electrical": "E-POWR", "structure_other": "S-MISC", "rooms": "A-AREA", "annotations": "A-ANNO-NOTE",
    "grids": "S-GRID", "other": "A-GENM",
}
DIMENSION_LAYER = "A-ANNO-DIMS"
SHEET_LAYERS = {"frame": "A-ANNO-TTLB", "title": "A-ANNO-TITL", "legend": "A-ANNO-LGND"}
_INSUNITS = {0.001: 4, 0.01: 5, 1.0: 6, 0.0254: 1, 0.3048: 2}  # metres per unit -> $INSUNITS
_BAD_NAME = re.compile(r'[<>/\\":;?*|=`,]')
_BAD_FILE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ---------------------------------------------------------------- small helpers

def lineweight(mm: float) -> int:
    """A pen weight (mm) as the nearest standard DXF lineweight (1/100 mm)."""
    v = float(mm) * 100
    return min(LINEWEIGHTS, key=lambda w: (abs(w - v), w))


def _rgb(color: str):
    color = (color or "#000000").lstrip("#")
    try:
        return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    except (ValueError, IndexError):
        return 0, 0, 0


_aci_cache: dict = {}


def aci(color: str) -> int:
    """The nearest AutoCAD Color Index. Black (and near black) is 7, the colour that follows the
    background (black on white paper), as CAD offices expect."""
    if color in _aci_cache:
        return _aci_cache[color]
    r, g, b = _rgb(color)
    if max(r, g, b) < 24:
        best = 7
    else:
        def dist(i):
            c = int2rgb(DXF_DEFAULT_COLORS[i])
            return (c[0] - r) ** 2 + (c[1] - g) ** 2 + (c[2] - b) ** 2
        best = min(range(1, 256), key=dist)
    _aci_cache[color] = best
    return best


def layer_name(name: str) -> str:
    name = _BAD_NAME.sub("_", (name or "").strip())[:255]
    return name or "0"


def file_name(name: str) -> str:
    return _BAD_FILE.sub("_", (name or "").strip()).strip(". ") or "drawing"


def _unit_scale(f) -> float:
    return float(ifcopenshell.util.unit.calculate_unit_scale(f))


def _insunits(u: float) -> int:
    return next((code for m, code in _INSUNITS.items() if math.isclose(m, u, rel_tol=1e-6)), 4)


_COLOUR_MODE = "exact"  # D92: set from the export options before writing
_POCHE = True


def _set_options(opts: dict) -> None:
    global _COLOUR_MODE, _POCHE
    _COLOUR_MODE = opts.get("colour", "exact")
    _POCHE = bool(opts.get("poche", True))


def _options(options_json) -> dict:
    try:
        o = json.loads(options_json) if isinstance(options_json, str) and options_json.strip() else dict(options_json or {})
    except ValueError:
        o = {}
    if not isinstance(o, dict):
        o = {}
    return {"layers": o.get("layers") if o.get("layers") in LAYER_MODES else "layer",
            "dimensions": o.get("dimensions") if o.get("dimensions") in DIMENSION_MODES else "native",
            "colour": o.get("colour") if o.get("colour") in COLOUR_MODES else "exact",
            "poche": o.get("poche") if isinstance(o.get("poche"), bool) else True,
            "purpose": o.get("purpose") or None}


# ---------------------------------------------------------------- the DXF document

class Doc:
    """One DXF document being written: layers, linetypes, styles made as they are first used."""

    def __init__(self, u: float, line_types: dict):
        self.u = u  # metres per model unit
        self.doc = ezdxf.new(DXF_VERSION, setup=False)
        self.ltscale = G.SCALE * 0.001 / u  # paper mm -> model units at the drawings' 1:100
        h = self.doc.header
        h["$INSUNITS"] = _insunits(u)
        h["$MEASUREMENT"] = 1
        h["$LUNITS"] = 2
        h["$LTSCALE"] = self.ltscale
        h["$PSLTSCALE"] = 0
        h["$LWDISPLAY"] = 1
        self.doc.styles.add("KimBim", font="arial.ttf")
        self.line_types = {tuple(round(float(v), 4) for v in d): name for name, d in (line_types or {}).items()
                           if isinstance(d, list) and d}
        self.layers: dict[str, str] = {}
        self.dimstyle = None

    def layer(self, name: str) -> str:
        name = layer_name(name)
        if name not in self.layers:
            if name != "0" and name not in self.doc.layers:
                self.doc.layers.add(name, color=7)
            self.layers[name] = name
        return name

    def linetype(self, dash) -> str:
        if not dash:
            return "CONTINUOUS"
        key = tuple(round(float(v), 4) for v in dash)
        name = layer_name(self.line_types.get(key) or "KimBim-" + "-".join(f"{v:g}" for v in key)).upper()
        if name not in self.doc.linetypes:
            if len(key) % 2:
                key = key + key  # SVG repeats an odd dash list twice
            pattern = [sum(key)] + [v if i % 2 == 0 else -v for i, v in enumerate(key)]
            self.doc.linetypes.add(name, pattern=pattern, description=f"KimBim {name.title()}")
        return name

    def dimension_style(self) -> str:
        if self.dimstyle is None:
            self.dimstyle = "KimBim"
            self.doc.dimstyles.new(self.dimstyle, dxfattribs={
                "dimscale": self.ltscale, "dimtxt": G.TEXT_SIZE, "dimtsz": 1.0, "dimasz": 1.0, "dimexe": 1.0,
                "dimexo": 0.0, "dimgap": 0.6, "dimtad": 1, "dimjust": 0, "dimtih": 0, "dimtoh": 0,
                "dimtxsty": "KimBim", "dimlunit": 2, "dimdec": 0})
        return self.dimstyle


def _attribs(doc: Doc, ctx: dict, ltscale: float = 1.0) -> dict:
    color = _grey_for_weight(ctx["weight"]) if _COLOUR_MODE == "lineweight" else ctx["color"]
    out = {"layer": doc.layer(ctx["layer"]), "color": aci(color), "lineweight": lineweight(ctx["weight"])}
    lt = doc.linetype(ctx.get("dash"))
    if lt != "CONTINUOUS":
        out["linetype"] = lt
        if ltscale != 1.0:
            out["ltscale"] = ltscale
    return out


def _colour(entity, color: str):
    if _COLOUR_MODE in ("aci", "lineweight"):
        return  # the ACI set in _attribs is the colour (D92)
    if aci(color) != 7 or max(_rgb(color)) >= 24:
        entity.rgb = _rgb(color)


def _grey_for_weight(weight: float) -> str:
    """A grey ACI colour from a pen weight (heavier is darker), for the "lineweight" colour mode."""
    v = 255 - int(min(1.0, max(0.0, float(weight))) * 200)
    return f"#{v:02x}{v:02x}{v:02x}"


# ---------------------------------------------------------------- SVG geometry

_TOKEN = re.compile(r"[MmLlHhVvZzAaCcSsQqTt]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _bulge(p0, p1, r, large, sweep) -> float:
    """Bulge of a circular SVG arc (positive = counter-clockwise in the SVG's own axes)."""
    d = math.dist(p0, p1)
    if d < 1e-12 or r <= 0:
        return 0.0
    theta = 2 * math.asin(min(1.0, d / (2 * r)))
    if large:
        theta = 2 * math.pi - theta
    return math.tan(theta / 4) * (1 if sweep else -1)


def parse_path(d: str):
    """Sub-paths of an SVG path as ([(x, y, bulge)...], closed): bulge on a vertex is the arc to the next
    one. Lines and circular arcs (curves become their chords: the serializer writes none)."""
    tokens = _TOKEN.findall(d or "")
    out, pts, closed = [], [], False
    i, cmd = 0, "M"
    cur = start = (0.0, 0.0)

    def num():
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    def finish():
        nonlocal pts, closed
        if not closed and len(pts) > 2 and math.dist(pts[0][:2], pts[-1][:2]) < 1e-9:
            pts.pop()  # ends where it started: a closed loop (the serializer writes no Z)
            closed = True
        if len(pts) >= 2:
            out.append((pts, closed))
        pts, closed = [], False

    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if pts:
                    if math.dist(pts[0][:2], pts[-1][:2]) < 1e-9:
                        pts.pop()
                    closed = True
                cur = start
                finish()
                continue
        try:
            rel = cmd.islower()
            c = cmd.upper()
            if c == "M":
                x, y = num(), num()
                to = (cur[0] + x, cur[1] + y) if rel else (x, y)
                cmd = "l" if rel else "L"  # following pairs are line-tos
                if pts and not closed and math.dist(to, pts[-1][:2]) < 1e-9 and                         math.dist(pts[0][:2], pts[-1][:2]) >= 1e-9:
                    cur = to  # the serializer's segments chain end to start: one polyline
                    continue
                finish()
                cur = start = to
                pts = [[cur[0], cur[1], 0.0]]
            elif c in "LHVT":
                if c == "L" or c == "T":
                    x, y = num(), num()
                    cur = (cur[0] + x, cur[1] + y) if rel else (x, y)
                elif c == "H":
                    x = num()
                    cur = (cur[0] + x if rel else x, cur[1])
                else:
                    y = num()
                    cur = (cur[0], cur[1] + y if rel else y)
                if not pts:
                    pts = [[start[0], start[1], 0.0]]
                pts.append([cur[0], cur[1], 0.0])
            elif c == "A":
                rx, ry, _rot, large, sweep, x, y = (num() for _ in range(7))
                end = (cur[0] + x, cur[1] + y) if rel else (x, y)
                if not pts:
                    pts = [[cur[0], cur[1], 0.0]]
                pts[-1][2] = _bulge(cur, end, (abs(rx) + abs(ry)) / 2, int(large), int(sweep))
                cur = end
                pts.append([cur[0], cur[1], 0.0])
            elif c in "CSQ":
                n = {"C": 3, "S": 2, "Q": 2}[c]
                vals = [num() for _ in range(2 * n)]
                x, y = vals[-2], vals[-1]
                cur = (cur[0] + x, cur[1] + y) if rel else (x, y)
                pts.append([cur[0], cur[1], 0.0])
            else:
                i += 1
        except (IndexError, ValueError):
            break
    finish()
    return out


def chain(lines):
    """Open, straight polylines joined end to end where they meet (either direction): an element's edges
    become a few polylines instead of hundreds of LINEs. Returns sub-paths like parse_path."""
    def key(p):
        return round(p[0], 6), round(p[1], 6)

    ends: dict = {}
    for i, (pts, _) in enumerate(lines):
        ends.setdefault(key(pts[0]), []).append(i)
        ends.setdefault(key(pts[-1]), []).append(i)
    used = [False] * len(lines)

    def take(point):
        for j in ends.get(key(point), ()):
            if not used[j]:
                used[j] = True
                return lines[j][0]
        return None

    out = []
    for i, (pts, _) in enumerate(lines):
        if used[i]:
            continue
        used[i] = True
        run = [list(p) for p in pts]
        for forward in (True, False):
            while True:
                tip = run[-1] if forward else run[0]
                nxt = take(tip)
                if nxt is None:
                    break
                if key(nxt[0]) != key(tip):
                    nxt = nxt[::-1]
                if forward:
                    run += [list(p) for p in nxt[1:]]
                else:
                    run[:0] = [list(p) for p in nxt[:-1]]
                if key(run[0]) == key(run[-1]):
                    break
            if len(run) > 2 and key(run[0]) == key(run[-1]):
                break
        closed = len(run) > 3 and key(run[0]) == key(run[-1])
        out.append((run[:-1] if closed else run, closed))
    return out


_ROTATE = re.compile(r"rotate\(\s*([-\d.e]+)(?:[\s,]+([-\d.e]+)[\s,]+([-\d.e]+))?\s*\)")
_TRANSLATE = re.compile(r"translate\(\s*([-\d.e]+)[\s,]+([-\d.e]+)\s*\)")


class Mapping:
    """An affine map (3x3, homogeneous) from SVG paper millimetres (y down) to the target's units."""

    def __init__(self, m):
        self.m = np.asarray(m, dtype=float)
        lin = self.m[:2, :2]
        det = float(np.linalg.det(lin))
        self.size = math.sqrt(abs(det))  # target units per paper mm
        self.flip = det < 0

    def __call__(self, x, y):
        p = self.m @ (float(x), float(y), 1.0)
        return float(p[0]), float(p[1])

    def then(self, other: "Mapping") -> "Mapping":
        return Mapping(other.m @ self.m)

    def bulge(self, b: float) -> float:
        return -b if self.flip else b

    def angle(self, svg_degrees: float) -> float:
        """A rotation given in SVG (clockwise on screen) as a DXF angle (counter-clockwise)."""
        a = math.radians(svg_degrees)
        x0, y0 = self(0, 0)
        x1, y1 = self(math.cos(a), math.sin(a))
        return math.degrees(math.atan2(y1 - y0, x1 - x0))


def drawing_mapping(svg: str, kind: str, u: float) -> Mapping:
    """Paper mm -> model units for a drawing's SVG: plans to world X/Y, sections and elevations to
    (along the marker line, true elevation)."""
    m = re.search(r'class="section"[^>]*?ifc:plane="([^"]+)"[^>]*?ifc:matrix3="([^"]+)"', svg)
    if m is None:  # nothing drawn: paper at 1:100
        s = G.SCALE * 0.001 / u
        return Mapping([[s, 0, 0], [0, -s, 0], [0, 0, 1]])
    plane = np.array(json.loads(m.group(1)), dtype=float)
    m3 = np.array(json.loads(m.group(2)), dtype=float)
    to_local = np.diag([1.0, -1.0, 1.0]) @ np.linalg.inv(m3)  # paper -> (lx, ly) on the drawing plane, metres
    if kind == "plan":
        g = np.array([[plane[0, 0], plane[0, 1], plane[0, 3]], [plane[1, 0], plane[1, 1], plane[1, 3]], [0, 0, 1]])
    else:
        g = np.array([[1.0, 0.0, 0.0], [plane[2, 0], plane[2, 1], plane[2, 3]], [0, 0, 1]])
    return Mapping(np.diag([1 / u, 1 / u, 1.0]) @ g @ to_local)


# ---------------------------------------------------------------- SVG -> DXF

class Writer:
    """Walks an SVG and writes its lines, fills, text and circles into a DXF layout or block."""

    def __init__(self, doc: Doc, target, mapping: Mapping, style=None, ltscale: float = 1.0, dims=None,
                 poche: bool = True):
        self.doc, self.target, self.map = doc, target, mapping
        self.style = style  # (element, ctx) -> new ctx, or None to skip the element's subtree
        self.ltscale = ltscale
        self.dims = dims  # guid -> True when the group was written as DIMENSION entities
        self.poche = poche  # D92: fills go on the layer's "-PATT" sublayer
        self.count = 0
        self.lo = [math.inf, math.inf]
        self.hi = [-math.inf, -math.inf]

    def _grow(self, x, y):
        self.lo = [min(self.lo[0], x), min(self.lo[1], y)]
        self.hi = [max(self.hi[0], x), max(self.hi[1], y)]

    def walk(self, element, ctx: dict):
        tag = element.tag.replace(SVG, "")
        if tag in ("defs", "style", "marker", "title", "metadata"):
            return
        ctx = self._own_style(element, ctx)
        if tag == "g" or tag == "svg":
            if self.style is not None:
                ctx = self.style(element, ctx)
                if ctx is None:
                    return
            saved = self.map
            t = _TRANSLATE.search(element.get("transform") or "")
            if t:
                self.map = Mapping([[1, 0, float(t.group(1))], [0, 1, float(t.group(2))], [0, 0, 1]]).then(saved)
            fill = element.get("data-drafting") == "fill"
            if fill:  # D84: the fill as a HATCH (its pattern, or solid); its drawn hatch lines are skipped
                self.drafting_fill(element, ctx)
            loose = []  # the group's single segments (the serializer writes one path per edge)
            for child in element:
                if fill and (child.get("class") == "hatch" or child.get("data-fill") or child.get("data-fill-pen")
                             or child.get("data-outline") == "none"):
                    continue
                if child.tag == SVG + "path" and set(child.attrib) <= {"d", "class"}:
                    subpaths = parse_path(child.get("d", ""))
                    lines = [sp for sp in subpaths if not sp[1] and not any(v[2] for v in sp[0])]
                    if len(lines) == len(subpaths):
                        loose += lines
                        continue
                self.walk(child, ctx)
            if loose:
                self.path(chain(loose), {**ctx, "fill": None})
            self.map = saved
        elif tag == "path":
            self.path(parse_path(element.get("d", "")), ctx)
        elif tag == "rect":
            x, y = float(element.get("x", 0)), float(element.get("y", 0))
            w, h = element.get("width", "0"), element.get("height", "0")
            if w.endswith("%") or h.endswith("%"):
                return  # a background
            w, h = float(w), float(h)
            self.path([([[x, y, 0], [x + w, y, 0], [x + w, y + h, 0], [x, y + h, 0]], True)], ctx)
        elif tag in ("polygon", "polyline"):
            nums = [float(v) for v in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", element.get("points", ""))]
            pts = [[nums[i], nums[i + 1], 0.0] for i in range(0, len(nums) - 1, 2)]
            self.path([(pts, tag == "polygon")], ctx)
        elif tag == "line":
            pts = [[float(element.get(k, 0)) for k in ("x1", "y1")] + [0.0],
                   [float(element.get(k, 0)) for k in ("x2", "y2")] + [0.0]]
            self.path([(pts, False)], ctx)
        elif tag == "circle":
            self.circle(element, ctx)
        elif tag == "text":
            self.text(element, ctx)

    @staticmethod
    def _own_style(element, ctx):
        """stroke, stroke-width, stroke-dasharray and fill written on the element (sheet chrome, legends)."""
        stroke, width = element.get("stroke"), element.get("stroke-width")
        fill, dash = element.get("fill"), element.get("stroke-dasharray")
        if stroke is None and width is None and fill is None and dash is None:
            return ctx
        ctx = dict(ctx)
        if stroke and stroke != "none":
            ctx["color"] = "#000000" if stroke in ("#000", "black") else stroke
        if width:
            try:
                ctx["weight"] = float(width)
            except ValueError:
                pass
        if dash is not None:
            ctx["dash"] = [float(v) for v in re.split(r"[\s,]+", dash.strip()) if v] if dash != "none" else []
        if fill is not None and element.tag.replace(SVG, "") != "text":
            if fill == "none":
                ctx["fill"] = None
            elif fill.startswith("#") and element.tag.replace(SVG, "") in ("rect", "polygon", "path"):
                ctx["fill"] = "#000000" if fill == "#000" else fill
        if fill and fill.startswith("#") and not ctx.get("lock_text"):
            ctx["text_color"] = "#000000" if fill == "#000" else fill
        return ctx

    def path(self, subpaths, ctx):
        if not subpaths:
            return
        attribs = _attribs(self.doc, ctx, self.ltscale)
        mapped = []
        for pts, closed in subpaths:
            m = [(*self.map(x, y), self.map.bulge(b)) for x, y, b in pts]
            for x, y, _ in m:
                self._grow(x, y)
            mapped.append((m, closed))
        if ctx.get("fill"):
            loops = [m for m, closed in mapped if closed and len(m) >= 3]
            if loops:
                hatch_attribs = {"layer": self.doc.layer(ctx["layer"] + "-PATT" if self.poche else ctx["layer"])}
                hatch = self.target.add_hatch(color=aci(ctx["fill"]), dxfattribs=hatch_attribs)
                hatch.set_solid_fill(color=aci(ctx["fill"]), rgb=_rgb(ctx["fill"]) if aci(ctx["fill"]) != 7 or
                                     max(_rgb(ctx["fill"])) >= 24 else None)
                hatch.dxf.hatch_style = 0  # odd parity: holes stay open
                for loop in loops:
                    hatch.paths.add_polyline_path(loop, is_closed=True)
                self.count += 1
        for m, closed in mapped:
            if len(m) == 2 and not closed and m[0][2] == 0.0:
                e = self.target.add_line(m[0][:2], m[1][:2], dxfattribs=attribs)
            else:
                e = self.target.add_lwpolyline(m, format="xyb", close=closed, dxfattribs=attribs)
            _colour(e, ctx["color"])
            self.count += 1

    def drafting_fill(self, group, ctx):
        """A drafting fill (D84): a solid HATCH for its background pen or a solid pattern, and a
        pattern HATCH made from the fill pattern's line families (mm on paper, scaled like the drawing)."""
        from . import annotations as N
        from . import drafting

        outline = next((c for c in group.iter(SVG + "path") if not c.get("class") and not c.get("data-fill")
                        and not c.get("data-fill-pen")), None)
        subpaths = parse_path(outline.get("d", "")) if outline is not None else []
        if not subpaths:
            return
        loop = [(*self.map(x, y), 0.0) for x, y, _ in subpaths[0][0]]
        try:
            e = B._model.by_guid(group.get(IFC + "guid"))
        except (RuntimeError, AttributeError):
            e = None
        extra = N.extra_of(e) if e is not None else {}
        layer = {"layer": self.doc.layer(ctx.get("layer", "0") + ("-PATT" if self.poche else ""))}
        factor = 0.001 if extra.get("PatternScale") == "model" else None  # D92: model-scaled spacings
        pen_of = getattr(self.style, "pen", None)
        bg = int(extra.get("BackgroundPen") or 0)
        name = extra.get("Pattern") or "Solid"
        pattern = drafting.patterns().get(name) or {"solid": True}
        solids = []
        if pattern.get("solid"):
            solids.append(ctx["color"])
        elif bg and pen_of is not None:
            solids.append(pen_of(bg)["color"])
        for colour in solids:
            hatch = self.target.add_hatch(color=aci(colour), dxfattribs=layer)
            hatch.set_solid_fill(color=aci(colour), rgb=_rgb(colour))
            hatch.paths.add_polyline_path(loop, is_closed=True)
            self.count += 1
        families = [] if pattern.get("solid") else pattern.get("lines", []) or []
        k = factor if factor is not None else self.map.size  # model units per pattern mm
        definition = []
        for fam in families:
            a = math.radians(float(fam.get("angle", 0)))
            shift, spacing = float(fam.get("shift", 0)) * k, float(fam.get("spacing", 0)) * k
            ox, oy = (float(v) * k for v in (fam.get("origin") or (0, 0)))
            dash = []
            for i, v in enumerate(fam.get("dash") or []):
                dash.append(float(v) * k if i % 2 == 0 else -float(v) * k)  # DXF: gaps are negative
            definition.append([math.degrees(a), (ox, oy),
                               (shift * math.cos(a) - spacing * math.sin(a), shift * math.sin(a) + spacing * math.cos(a)), dash])
        if definition:
            hatch = self.target.add_hatch(color=aci(ctx["color"]), dxfattribs=layer)
            hatch.set_pattern_fill(layer_name(name).upper()[:31] or "KimBim", color=aci(ctx["color"]),
                                   definition=definition, scale=1.0)
            hatch.paths.add_polyline_path(loop, is_closed=True)
            self.count += 1

    def circle(self, element, ctx):
        x, y = self.map(float(element.get("cx", 0)), float(element.get("cy", 0)))
        r = float(element.get("r", 0)) * self.map.size
        if r <= 0:
            return
        e = self.target.add_circle((x, y), r, dxfattribs=_attribs(self.doc, ctx, self.ltscale))
        _colour(e, ctx["color"])
        self._grow(x - r, y - r)
        self._grow(x + r, y + r)
        self.count += 1

    def text(self, element, ctx):
        value = "".join(element.itertext()).strip()
        if not value:
            return
        x, y = float(element.get("x", 0)), float(element.get("y", 0))
        size = float(element.get("font-size", G.TEXT_SIZE))
        angle = 0.0
        r = _ROTATE.search(element.get("transform") or "")
        if r:
            angle = float(r.group(1))
        anchor = element.get("text-anchor", "start")
        middle = element.get("dominant-baseline") in ("central", "middle")
        align = {("start", False): TextEntityAlignment.LEFT, ("middle", False): TextEntityAlignment.CENTER,
                 ("end", False): TextEntityAlignment.RIGHT, ("start", True): TextEntityAlignment.MIDDLE_LEFT,
                 ("middle", True): TextEntityAlignment.MIDDLE_CENTER,
                 ("end", True): TextEntityAlignment.MIDDLE_RIGHT}.get((anchor, middle), TextEntityAlignment.LEFT)
        color = ctx.get("text_color") or ctx["color"]
        p = self.map(x, y)
        attribs = {"layer": self.doc.layer(ctx["layer"]), "color": aci(color), "style": "KimBim",
                   "height": size * self.map.size, "rotation": self.map.angle(angle)}
        e = self.target.add_text(value, dxfattribs=attribs)
        e.set_placement(p, align=align)
        _colour(e, color)
        h = size * self.map.size
        self._grow(p[0] - 0.3 * h * len(value), p[1] - h)
        self._grow(p[0] + 0.3 * h * len(value), p[1] + h)
        self.count += 1


# ---------------------------------------------------------------- styling a drawing

class Styler:
    """Element groups of a drawing's SVG -> layer, pen, line type and fill (the purpose's, D73)."""

    def __init__(self, resolved: dict, layers: str, dimensions: str):
        self.resolved = resolved
        self.layers = layers
        self.native_dims = dimensions == "native"
        self.hidden = set(resolved.get("hidden", []))
        self.elements = resolved.get("elements", {})
        self.styles = resolved.get("styles", [])
        self.pens = resolved.get("pens", {})
        self._layer_of: dict[str, str] = {}
        self.dimension_groups: list = []  # (guid, pen) written as DIMENSION entities by the caller

    def element(self, guid):
        try:
            return B._model.by_guid(guid)
        except RuntimeError:
            return None

    def pen_layer(self, n) -> str:
        """D92 "per pen" layer scheme: one layer per pen number, e.g. PEN-23."""
        return f"PEN-{int(n):02d}"

    def layer_of(self, guid: str, kind_layer: str | None = None, pen=None) -> str:
        key = (guid, int(pen)) if self.layers == "pen" and pen is not None else guid
        if key in self._layer_of:
            return self._layer_of[key]
        from . import graphics, layers

        e = self.element(guid)
        name = None
        if e is not None and self.layers == "layer":
            layer = layers.element_layer(e)
            name = layer.Name if layer is not None and layer.Name else None
        if name is None and self.layers == "pen" and pen is not None:
            name = self.pen_layer(pen)
        if name is None:
            kind = graphics.kind_of(e) if e is not None else "other"
            table = ISO_LAYERS if self.layers == "iso" else KIND_LAYERS
            name = kind_layer or table.get(kind, "A-GENM")
        self._layer_of[key] = name
        return name

    def pen(self, n) -> dict:
        from . import graphics

        return graphics.pen(self.pens, n)

    def __call__(self, element, ctx):
        guid = element.get(IFC + "guid")
        kind = element.get("data-kind")
        if guid:
            if guid in self.hidden:
                return None
            if kind == "annotation":
                pm = element.get("data-pen")
                n = int(pm) if pm and pm.isdigit() else int(self.resolved.get("annotation_pen", 23))
                p = self.pen(n)
                e = self.element(guid)
                data = ifcopenshell.util.element.get_pset(e, G.ANNOTATION_PSET) or {} if e is not None else {}
                is_dim = data.get("Kind") == "dimension"
                if is_dim and self.native_dims:
                    self.dimension_groups.append((guid, p, n))
                    return None
                layer = self.layer_of(guid, DIMENSION_LAYER if is_dim else None, pen=n)
                dash = [float(v) for v in (element.get("data-dash") or "").split()]  # D84: a drafting line type
                return {**ctx, "layer": layer, "color": p["color"], "weight": p["weight"], "dash": dash,
                        "fill": None, "text_color": p["color"], "lock_text": True}
            if guid in self.elements:
                st = self.styles[self.elements[guid]]
                cls = element.get("class") or ""
                if cls.split()[:1] == ["projection"]:
                    line, fill = st["projection"], None
                else:
                    line, fill = st["cut"], st["fill"]
                layer = self.layer_of(guid, pen=line.get("pen"))
                return {**ctx, "layer": layer, "color": line["color"], "weight": line["weight"],
                        "dash": line["dash"], "fill": fill}
            from . import graphics

            fb = graphics.FALLBACK_PEN
            layer = self.layer_of(guid)
            return {**ctx, "layer": layer, "color": fb["color"], "weight": fb["weight"], "dash": [], "fill": None}
        if kind in OVERLAY_LAYERS:
            return {**ctx, "layer": OVERLAY_LAYERS[kind]}
        return ctx


def write_dimensions(doc: Doc, target, styler: Styler, u: float, offset=None) -> int:
    """KimBim's dimension chains as DIMENSION entities: one rotated linear dimension per segment, all on
    the chain's dimension line, the segment's label as the text (empty: the measured value)."""
    count = 0
    style = doc.dimension_style() if styler.dimension_groups else None
    for guid, p, pen_no in styler.dimension_groups:
        a = styler.element(guid)
        if a is None or a.ObjectPlacement is None:
            continue
        data = ifcopenshell.util.element.get_pset(a, G.ANNOTATION_PSET) or {}
        try:
            local = json.loads(data.get("Points") or "[]")
        except ValueError:
            continue
        if len(local) < 3:
            continue
        unit = _unit_scale(a.file)
        m = ifcopenshell.util.placement.get_local_placement(a.ObjectPlacement)
        pts = []
        for lx, ly in local:
            w = m @ np.array([lx / unit, ly / unit, 0.0, 1.0]) * unit
            pts.append((w[0] / u, w[1] / u))
        measured, through = pts[:-1], pts[-1]
        (ax, ay), (bx, by) = measured[0], measured[-1]
        if math.hypot(bx - ax, by - ay) < 1e-9:
            continue
        angle = math.degrees(math.atan2(by - ay, bx - ax))
        labels = G.segment_labels(data.get("Text") or "", len(measured) - 1)
        size = float(data.get("Size") or G.TEXT_SIZE)
        layer = doc.layer(styler.layer_of(guid, DIMENSION_LAYER, pen=pen_no))
        color, lw = aci(p["color"]), lineweight(p["weight"])
        for (p1, p2), label in zip(zip(measured, measured[1:]), labels):
            dim = target.add_linear_dim(base=through, p1=p1, p2=p2, angle=angle, text=label or "<>", dimstyle=style,
                                        override={"dimtxt": size, "dimclrd": color, "dimclre": color,
                                                  "dimclrt": color, "dimlwd": lw, "dimlwe": lw},
                                        dxfattribs={"layer": layer, "color": color})
            dim.render()
            count += 1
    return count


# ---------------------------------------------------------------- drawings

def _resolved(purpose):
    from . import graphics

    return graphics.resolve(purpose)


def _new_doc(resolved) -> Doc:
    from . import graphics

    return Doc(_unit_scale(B._model), graphics.effective("line_types"))


def _write_drawing(doc: Doc, target, guid: str, resolved: dict, opts: dict, ltscale: float = 1.0):
    """Write drawing `guid` into `target` in model units. Returns (writer, mapping, svg) or an error string."""
    d = D._drawing(guid)
    if d is None:
        return "not a drawing"
    r = D.raw_drawing(guid, "", resolved["hidden"])
    if not r.get("ok"):
        return r.get("error", "could not generate the drawing")
    svg = r["svg"]
    kind = G.settings_of(d)["kind"]
    mapping = drawing_mapping(svg, kind, doc.u)
    styler = Styler(resolved, opts["layers"], opts["dimensions"])
    writer = Writer(doc, target, mapping, styler, ltscale, poche=_POCHE)
    root = ET.fromstring(svg)
    base = {"layer": "0", "color": "#000000", "weight": 0.18, "dash": [], "fill": None}
    writer.walk(root, base)
    writer.count += write_dimensions(doc, target, styler, doc.u)
    return writer, mapping, svg


def _zoom(layout, writer: Writer):
    """Open on what was drawn (from the writer's own extents: ezdxf's bounding box costs seconds)."""
    if writer.lo[0] < math.inf:
        ezdxf.zoom.window(layout, writer.lo, writer.hi)


def drawing_document(guid: str, opts: dict):
    """(ezdxf document, stats) of one drawing in model space, or (None, error)."""
    _set_options(opts)
    resolved = _resolved(opts["purpose"])
    doc = _new_doc(resolved)
    msp = doc.doc.modelspace()
    out = _write_drawing(doc, msp, guid, resolved, opts)
    if isinstance(out, str):
        return None, out
    writer = out[0]
    _zoom(msp, writer)
    return doc.doc, {"entities": writer.count, "layers": sorted(doc.layers)}


def export_drawing_dxf(guid: str, path: str, options_json: str = "") -> str:
    """{ok, path, entities, layers, seconds}: drawing `guid` as a DXF file (model space, real size)."""
    if B._model is None:
        return A._fail("no model open")
    t0 = time.perf_counter()
    try:
        doc, stats = drawing_document(guid, _options(options_json))
        if doc is None:
            return A._fail(stats)
        doc.saveas(path)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "path": path, **stats, "seconds": round(time.perf_counter() - t0, 3)})


# ---------------------------------------------------------------- sheets

def _block_name(doc, name: str) -> str:
    base = layer_name("VIEW-" + name)
    out, n = base, 2
    while out in doc.blocks:
        out, n = f"{base}-{n}", n + 1
    return out


def sheet_document(number: str, opts: dict):
    """(ezdxf document, stats) of a sheet as a paper-space layout, or (None, error)."""
    from . import graphics
    from . import sheets as S
    from . import settings as St

    sheet = S._sheet(number)
    if sheet is None:
        return None, "unknown sheet"
    _set_options(opts)
    width, height = S.PAPERS.get(sheet.Scope or "A1", S.PAPERS["A1"])
    purpose = opts["purpose"] or St.current().get("sheet_purposes", {}).get(number) or None
    resolved = graphics.resolve(purpose)
    doc = _new_doc(resolved)
    dxf = doc.doc
    title = f"{S._number(sheet)} {sheet.Name or ''}".strip()
    layout = dxf.layouts.new(layer_name(title)[:200])
    layout.page_setup(size=(width, height), margins=(0, 0, 0, 0), units="mm", scale=(1, 1), name="KimBim")
    if "Layout1" in dxf.layouts:
        dxf.layouts.delete("Layout1")
    paper = Mapping([[1, 0, 0], [0, -1, height], [0, 0, 1]])  # sheet mm, y down -> paper space, y up
    chrome = Writer(doc, layout, paper, ltscale=1.0 / doc.ltscale, poche=_POCHE)
    base = {"color": "#000000", "weight": 0.18, "dash": [], "fill": None}
    views, msp_x, msp_h, stats_entities = [], 0.0, 0.0, 0
    msp = dxf.modelspace()
    for ref in S._views(sheet):
        guid = S._link(ref)
        p = S._placement(ref)
        k = 100.0 / p["scale"]
        name = S._name(ref)
        block = dxf.blocks.new(_block_name(dxf, name or guid))
        out = _write_drawing(doc, block, guid, resolved, opts, ltscale=1.0 / k)
        if isinstance(out, str):
            return None, f"could not generate {name}: {out}"
        writer, mapping, svg = out
        stats_entities += writer.count
        vx, vy, vw, vh = (float(v) for v in re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', svg).groups())
        # block (model units) -> drawing paper -> sheet mm (y down) -> paper space
        sheet_of_paper = Mapping([[k, 0, p["x"] - vx * k], [0, k, p["y"] - vy * k], [0, 0, 1]])
        full = Mapping(np.linalg.inv(mapping.m)).then(sheet_of_paper).then(paper)
        scale = full.size
        rotation = math.degrees(math.atan2(full.m[1, 0], full.m[0, 0]))
        origin = full(0, 0)
        layout.add_blockref(block.name, origin, dxfattribs={"xscale": scale, "yscale": scale, "zscale": scale,
                                                             "rotation": rotation, "layer": doc.layer("0")})
        if writer.lo[0] < math.inf:  # model space: the same drawing at real size, left to right
            msp.add_blockref(block.name, (msp_x - writer.lo[0], -writer.lo[1]), dxfattribs={"layer": doc.layer("0")})
            msp_x += writer.hi[0] - writer.lo[0] + 5.0 / doc.u
            msp_h = max(msp_h, writer.hi[1] - writer.lo[1])
        views.append({"drawing": guid, "name": name, "block": block.name, "scale": p["scale"],
                      "insert": [round(origin[0], 3), round(origin[1], 3)], "insert_scale": round(scale, 6)})
        w, h = vw * k, vh * k
        tx, ty = p["x"], p["y"] + h + 6
        title_svg = (f'<g><path d="M{tx:.3f},{ty + 1.5:.3f} L{tx + w:.3f},{ty + 1.5:.3f}" stroke-width="0.35"/>'
                     f'<text x="{tx:.3f}" y="{ty:.3f}" font-size="4">{S._esc(name)}</text>'
                     f'<text x="{tx:.3f}" y="{ty + 6:.3f}" font-size="3">1:{p["scale"]}</text></g>')
        chrome.walk(ET.fromstring(title_svg), {**base, "layer": SHEET_LAYERS["title"]})
    legend_refs = S._legends(sheet)
    if legend_refs:
        body, _, _ = S._legend_content(sheet, resolved)
        for ref in legend_refs:
            p = S._placement(ref)
            chrome.walk(ET.fromstring(f'<g transform="translate({p["x"]:.3f} {p["y"]:.3f})">{body}</g>'),
                        {**base, "layer": SHEET_LAYERS["legend"]})
    for symbol in S.symbols_svg(sheet):  # D87: north arrows, scale bars, revision clouds
        chrome.walk(ET.fromstring(symbol), {**base, "layer": OVERLAY_LAYERS["marker"]})
    info = json.loads(S.project_info())
    frame = (f'<rect x="{S.MARGIN}" y="{S.MARGIN}" width="{width - 2 * S.MARGIN}" height="{height - 2 * S.MARGIN}" '
             f'fill="none" stroke="#000" stroke-width="0.7"/>')
    chrome.walk(ET.fromstring("<g>" + frame + "".join(S._title_block(sheet, width, height, info)) + "</g>"),
                {**base, "layer": SHEET_LAYERS["frame"]})
    try:
        ezdxf.zoom.window(layout, (0, 0), (width, height))
        if msp_x > 0:
            ezdxf.zoom.window(msp, (0, 0), (msp_x, msp_h))
    except Exception:
        pass
    dxf.layouts.set_active_layout(layout.name)
    return dxf, {"layout": layout.name, "paper": [width, height], "views": views,
                 "entities": stats_entities + chrome.count, "layers": sorted(doc.layers)}


def export_sheet_dxf(number: str, path: str, options_json: str = "") -> str:
    """{ok, path, layout, views, entities, layers, seconds}: sheet `number` as a DXF file (a paper-space
    layout, drawings as blocks inserted at their scale)."""
    if B._model is None:
        return A._fail("no model open")
    t0 = time.perf_counter()
    try:
        doc, stats = sheet_document(number, _options(options_json))
        if doc is None:
            return A._fail(stats)
        doc.saveas(path)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "path": path, **stats, "seconds": round(time.perf_counter() - t0, 3)})


# ---------------------------------------------------------------- batch (Publisher-lite)

def dxf_targets() -> str:
    """{drawings: [{guid, name, kind, file}], sheets: [{number, title, file}]}: what can be exported and
    the default file names."""
    if B._model is None:
        return B._dump({"ok": True, "drawings": [], "sheets": []})
    ds = json.loads(D.drawings())["drawings"]
    from . import sheets as S

    sh = json.loads(S.sheets())["sheets"]
    return B._dump({"ok": True,
                    "drawings": [{"guid": d["guid"], "name": d["name"], "kind": d["kind"],
                                  "file": file_name(d["name"]) + ".dxf"} for d in ds],
                    "sheets": [{"number": s["number"], "title": s["title"],
                                "file": file_name(f'{s["number"]} {s["title"]}') + ".dxf"} for s in sh]})


def export_dxf(items_json: str, folder: str, options_json: str = "") -> str:
    """Batch: items [{"drawing": guid} | {"sheet": number}] into `folder`, one DXF each, named as
    dxf_targets says. {ok, files: [path], errors: [{item, error}], seconds}."""
    if B._model is None:
        return A._fail("no model open")
    try:
        items = json.loads(items_json)
    except ValueError as ex:
        return A._fail(f"bad input: {ex}")
    t0 = time.perf_counter()
    targets = json.loads(dxf_targets())
    names = {**{d["guid"]: d["file"] for d in targets["drawings"]}, **{s["number"]: s["file"] for s in targets["sheets"]}}
    out_dir = Path(folder)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as ex:
        return A._fail(str(ex))
    files, errors = [], []
    for item in items:
        key = item.get("drawing") or item.get("sheet") or ""
        path = str(out_dir / names.get(key, file_name(key) + ".dxf"))
        r = json.loads(export_drawing_dxf(key, path, options_json) if "drawing" in item
                       else export_sheet_dxf(key, path, options_json))
        if r.get("ok"):
            files.append(path)
        else:
            errors.append({"item": key, "error": r.get("error", "")})
    return B._dump({"ok": not errors, "files": files, "errors": errors, "seconds": round(time.perf_counter() - t0, 3),
                    **({"error": errors[0]["error"]} if errors else {})})
