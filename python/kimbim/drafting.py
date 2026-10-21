# SPDX-License-Identifier: GPL-3.0-or-later
"""2D drafting (doc 14 §12, D84): lines, polylines, arcs, circles and fills on a level's plan.

They are plan annotations (D59): an IfcAnnotation on the level, ObjectType LINE / POLYLINE / ARC /
CIRCLE / FILL, with an Annotation2D representation (polylines, a trimmed circle, a circle, an
IfcAnnotationFillArea styled with an IfcFillAreaStyle and its hatchings), and KimBim's own data in
the KIMBIM_Annotation property set (points relative to the placement, pen, line type, fill pattern,
background pen, whether the area is shown). Moving, rotating, copying, deleting, layers and undo are
the annotations' (so every element's).

Fill patterns are a project settings table (`fill_patterns`, D73's way: an empty table means the
built-ins) of hatch-line families in millimetres on paper, AutoCAD .pat style: each family is lines
at `angle` degrees through `origin`, `spacing` apart, each next line's dashes shifted by `shift`
along it, with an optional `dash` pattern (dash, gap, ...; like the line types). `solid` fills with
the pen's colour.

This module's geometry is pure (no model); the bridge functions import app_bridge when called.
"""
from __future__ import annotations

import json
import math

KINDS = ("line", "polyline", "arc", "circle", "fill")
EXTRA = ("Closed", "LineType", "Pattern", "BackgroundPen", "ShowArea", "OutlinePen", "PatternScale",
         "Rect")  # pset keys beside Kind/Points/...
CIRCLE_SEGMENTS = 72  # tessellation of a full circle on screen and in drawings
MAX_HATCH_SEGMENTS = 40000  # a finer hatch is not drawn (the fill and its outline still are)


# ---------------------------------------------------------------- geometry (metres)

def circumcircle(a, b, c):
    """Centre and radius of the circle through three points, or None if they are in a line."""
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def arc_frame(start, through, end):
    """(centre, radius, start angle, sweep) of the arc from `start` through `through` to `end`;
    the sweep is positive counter-clockwise. None if the points are in a line."""
    cc = circumcircle(start, through, end)
    if cc is None:
        return None
    (ux, uy), r = cc
    a0 = math.atan2(start[1] - uy, start[0] - ux)
    a2 = math.atan2(end[1] - uy, end[0] - ux)
    cross = (through[0] - start[0]) * (end[1] - start[1]) - (through[1] - start[1]) * (end[0] - start[0])
    if cross > 0:  # through is to the right of start->end: counter-clockwise
        sweep = (a2 - a0) % (2 * math.pi)
    else:
        sweep = -((a0 - a2) % (2 * math.pi))
    return (ux, uy), r, a0, sweep


def arc_points(start, through, end):
    frame = arc_frame(start, through, end)
    if frame is None:
        return [list(start), list(end)]
    (ux, uy), r, a0, sweep = frame
    n = max(4, int(math.ceil(abs(sweep) / (2 * math.pi) * CIRCLE_SEGMENTS)))
    return [[ux + r * math.cos(a0 + sweep * i / n), uy + r * math.sin(a0 + sweep * i / n)] for i in range(n + 1)]


def circle_points(centre, on):
    r = math.dist(centre, on)
    a0 = math.atan2(on[1] - centre[1], on[0] - centre[0])
    return [[centre[0] + r * math.cos(a0 + 2 * math.pi * i / CIRCLE_SEGMENTS),
             centre[1] + r * math.sin(a0 + 2 * math.pi * i / CIRCLE_SEGMENTS)] for i in range(CIRCLE_SEGMENTS + 1)]


def area(polygon) -> float:
    a = 0.0
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        a += x0 * y1 - x1 * y0
    return a / 2


def centroid(polygon):
    a = area(polygon)
    if abs(a) < 1e-12:
        n = max(len(polygon), 1)
        return [sum(p[0] for p in polygon) / n, sum(p[1] for p in polygon) / n]
    cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        w = x0 * y1 - x1 * y0
        cx += (x0 + x1) * w
        cy += (y0 + y1) * w
    return [cx / (6 * a), cy / (6 * a)]


def inside(p, polygon) -> bool:
    x, y = p
    hit = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def is_simple(polygon) -> bool:
    """No two edges cross and the area is not zero (either winding)."""
    n = len(polygon)
    if n < 3 or abs(area(polygon)) < 1e-9:
        return False

    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)

    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            a, b, c, d = polygon[i], polygon[(i + 1) % n], polygon[j], polygon[(j + 1) % n]
            if orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0:
                return False
    return True


def outline(kind: str, points, closed=False):
    """The shape's drawn polylines (metres): a list of point lists."""
    pts = [list(p) for p in points]
    if kind == "line" and len(pts) >= 2:
        return [pts[:2]]
    if kind == "polyline" and len(pts) >= 2:
        return [pts + [pts[0]] if closed else pts]
    if kind == "arc" and len(pts) == 3:
        return [arc_points(*pts)]
    if kind == "circle" and len(pts) == 2:
        return [circle_points(*pts)]
    if kind == "fill" and len(pts) >= 3:
        return [pts + [pts[0]]]
    return []


def closed_polygon(kind: str, points, closed=False):
    """The area a shape encloses (metres), or None: closed polylines, circles and fills."""
    if kind == "circle" and len(points) == 2:
        return circle_points(*points)[:-1]
    if (kind == "polyline" and closed and len(points) >= 3) or (kind == "fill" and len(points) >= 3):
        return [list(p) for p in points]
    return None


def _dash_intervals(t0: float, t1: float, phase: float, dash):
    """Visible parts of [t0, t1] along a line whose dash pattern starts at `phase`."""
    if not dash:
        return [(t0, t1)]
    period = sum(dash)
    out = []
    k = math.floor((t0 - phase) / period)
    start = phase + k * period
    while start < t1:
        pos = start
        for i, length in enumerate(dash):
            if i % 2 == 0:
                a, b = max(pos, t0), min(pos + length, t1)
                if b > a or (length == 0 and t0 <= pos <= t1):
                    out.append((a, max(a, b)))
            pos += length
        start += period
    return out


def _point_in_polygon(x: float, y: float, poly) -> bool:
    inside = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def _loops_hatch(poly, pattern, metres_per_mm: float, limit: int):
    """A row of tangent loops (D93's insulation style), flattened to segments and clipped by their
    midpoints. [[]] when it would need more than `limit` segments."""
    radius = float(pattern.get("radius", 1.0)) * metres_per_mm
    spacing = float(pattern.get("spacing", 3.0)) * metres_per_mm
    if radius <= 0 or spacing <= 0:
        return []
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    n = 10  # segments per loop
    out = []
    row = 0
    y = y0 + spacing / 2
    while y < y1 + radius:
        x = x0 + (spacing / 2 if row % 2 else 0.0)
        while x < x1 + radius:
            for k in range(n):
                a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
                p0 = (x + radius * math.cos(a0), y + radius * math.sin(a0))
                p1 = (x + radius * math.cos(a1), y + radius * math.sin(a1))
                if _point_in_polygon((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, poly):
                    out.append([p0[0], p0[1], p1[0], p1[1]])
                    if len(out) > limit:
                        return []
            x += spacing
        y += spacing
        row += 1
    return out


def hatch(polygon, pattern: dict, metres_per_mm: float, limit: int = MAX_HATCH_SEGMENTS):
    """Hatch segments [[x1, y1, x2, y2], ...] (metres) of `pattern` clipped to `polygon`, anchored at
    the project origin so neighbouring fills line up. [] for solid or empty patterns, or when the
    hatch would need more than `limit` segments."""
    out = []
    poly = [tuple(p) for p in polygon]
    if len(poly) < 3:
        return out
    if (pattern or {}).get("loops"):
        return [[round(v, 6) for v in s] for s in _loops_hatch(poly, pattern, metres_per_mm, limit)]
    for family in (pattern or {}).get("lines", []) or []:
        spacing = float(family.get("spacing", 0)) * metres_per_mm
        if spacing <= 0:
            continue
        angle = math.radians(float(family.get("angle", 0)))
        d = (math.cos(angle), math.sin(angle))
        n = (-d[1], d[0])
        ox, oy = (float(v) * metres_per_mm for v in (family.get("origin") or (0, 0)))
        shift = float(family.get("shift", 0)) * metres_per_mm
        dash = [float(v) * metres_per_mm for v in family.get("dash") or []]
        offsets = [(x - ox) * n[0] + (y - oy) * n[1] for x, y in poly]
        i0, i1 = math.ceil(min(offsets) / spacing), math.floor(max(offsets) / spacing)
        if (i1 - i0 + 1) * (1 if not dash else 4) > limit:
            return []
        lo, hi = min(offsets) + 1e-9, max(offsets) - 1e-9
        for i in range(i0, i1 + 1):
            off = i * spacing
            if not lo < off < hi:
                continue  # along an edge or through a corner only
            base = (ox + n[0] * off, oy + n[1] * off)  # where line i crosses the family's normal
            ts = []
            for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
                s0 = (x0 - ox) * n[0] + (y0 - oy) * n[1] - off
                s1 = (x1 - ox) * n[0] + (y1 - oy) * n[1] - off
                if (s0 > 0) != (s1 > 0):
                    u = s0 / (s0 - s1)
                    px, py = x0 + (x1 - x0) * u, y0 + (y1 - y0) * u
                    ts.append((px - base[0]) * d[0] + (py - base[1]) * d[1])
            ts.sort()
            for a, b in zip(ts[0::2], ts[1::2]):
                for t0, t1 in _dash_intervals(a, b, i * shift, dash):
                    out.append([base[0] + d[0] * t0, base[1] + d[1] * t0, base[0] + d[0] * t1, base[1] + d[1] * t1])
                    if len(out) > limit:
                        return []
    return [[round(v, 6) for v in s] for s in out]


# ---------------------------------------------------------------- styles (settings tables)

def patterns(settings: dict | None = None) -> dict:
    from . import graphics

    return graphics.effective("fill_patterns", settings)


def current_pens(settings: dict | None = None) -> dict:
    """The pens of the current purpose's pen set (D73), without resolving every element's style."""
    from . import graphics

    st = graphics._settings(settings)
    purposes = graphics.effective("purposes", st)
    sets = graphics.effective("pen_sets", st)
    name = purposes[graphics.current_purpose(st)].get("pen_set")
    return (sets.get(name) or next(iter(sets.values()))).get("pens", {})


def line_dash(name, settings: dict | None = None) -> list:
    from . import graphics

    return graphics.dash(graphics.effective("line_types", settings), name or "Solid")


def area_text(square_metres: float) -> str:
    from .settings import current

    decimals = int(current().get("length_decimals", 2))
    return f"{abs(square_metres):.{decimals}f} m²"


def shape_data(kind: str, world, data: dict, metres_per_mm: float, settings: dict | None = None) -> dict:
    """What a view or a drawing needs to draw a drafting shape (world metres): its polylines, line
    dash (mm on paper), and for fills the outline to fill, the hatch, whether solid, the background
    pen and the area label."""
    closed = bool(data.get("Closed"))
    out = {"curves": outline(kind, world, closed), "line_type": data.get("LineType") or "Solid",
           "dash": line_dash(data.get("LineType"), settings), "closed": closed}
    if kind == "fill" and len(world) >= 3:
        name = data.get("Pattern") or "Solid"
        pattern = patterns(settings).get(name) or {"solid": True}
        # D92: paper-scaled (default: the same printed spacing at every scale) or model-scaled.
        factor = 0.001 if data.get("PatternScale") == "model" else metres_per_mm
        out.update({"pattern": name, "solid": bool(pattern.get("solid")), "area": [list(p) for p in world],
                    "hatch": hatch(world, pattern, factor), "background_pen": int(data.get("BackgroundPen") or 0),
                    "outline_pen": int(data["OutlinePen"]) if "OutlinePen" in data else -1,
                    "show_area": bool(data.get("ShowArea"))})
        if out["show_area"]:
            out["area_text"] = area_text(area(world))
            out["label_at"] = [round(v, 6) for v in centroid(world)]
    return out


# ---------------------------------------------------------------- IFC

def _angle_unit(f) -> float:
    """Project plane-angle units per radian (degrees: 57.3; radians: 1)."""
    import ifcopenshell.util.unit

    unit = ifcopenshell.util.unit.get_project_unit(f, "PLANEANGLEUNIT")
    if unit is not None and unit.is_a("IfcConversionBasedUnit") and "DEGREE" in (unit.Name or "").upper():
        return 180.0 / math.pi
    return 1.0


def _colour(f, hex_colour: str):
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    return f.createIfcColourRgb(None, r, g, b)


def fill_style(f, name: str, pattern: dict, fg: dict, bg: dict | None, metres_per_mm: float, scale: float):
    """An IfcFillAreaStyle for `pattern`: the background colour (or the pen's colour when solid) and
    one IfcFillAreaStyleHatching per line family (model sizes in project units)."""
    styles = []
    if pattern.get("solid"):
        styles.append(_colour(f, fg["color"]))
    elif bg is not None:
        styles.append(_colour(f, bg["color"]))
    per_radian = _angle_unit(f)
    if not pattern.get("solid"):
        for family in pattern.get("lines", []) or []:
            spacing = float(family.get("spacing", 0)) * metres_per_mm / scale
            if spacing <= 0:
                continue
            shift = float(family.get("shift", 0)) * metres_per_mm / scale
            dash = [float(v) * metres_per_mm / scale for v in family.get("dash") or []]
            font = None
            if dash:
                font = f.createIfcCurveStyleFont(None, [f.createIfcCurveStyleFontPattern(max(dash[i], 0.0), max(dash[i + 1], 1e-6))
                                                        for i in range(0, len(dash) - 1, 2)])
            curve = f.createIfcCurveStyle(None, font, f.create_entity("IfcPositiveLengthMeasure", fg["weight"] * metres_per_mm / scale),
                                          _colour(f, fg["color"]), True)
            length = math.hypot(shift, spacing)
            vector = f.createIfcVector(f.createIfcDirection((shift / length, spacing / length)), length)
            ox, oy = (float(v) * metres_per_mm / scale for v in (family.get("origin") or (0, 0)))
            styles.append(f.createIfcFillAreaStyleHatching(
                curve, vector, f.createIfcCartesianPoint((ox, oy)), None,
                math.radians(float(family.get("angle", 0))) * per_radian))
    if not styles:  # an empty pattern without a background: nothing to fill (other tools draw the outline)
        return None
    return f.createIfcFillAreaStyle(name, styles, True)


def ifc_items(f, kind: str, local, data: dict, pt, scale: float, metres_per_mm: float, pens: dict):
    """IFC items for a drafting shape (`pt` makes a 2D point from local metres)."""
    from . import graphics

    items = []
    closed = bool(data.get("Closed"))
    if kind in ("line", "polyline"):
        pts = [pt(p) for p in (local[:2] if kind == "line" else local)]
        if kind == "polyline" and closed:
            pts.append(pts[0])
        items.append(f.createIfcPolyline(pts))
    elif kind == "arc":
        frame = arc_frame(*local[:3])
        if frame is None:
            items.append(f.createIfcPolyline([pt(local[0]), pt(local[2])]))
        else:
            (ux, uy), r, _a0, sweep = frame
            circle = f.createIfcCircle(f.createIfcAxis2Placement2D(pt((ux, uy)), None), r / scale)
            items.append(f.createIfcTrimmedCurve(circle, [pt(local[0])], [pt(local[2])], sweep > 0, "CARTESIAN"))
    elif kind == "circle":
        items.append(f.createIfcCircle(f.createIfcAxis2Placement2D(pt(local[0]), None), math.dist(local[0], local[1]) / scale))
    elif kind == "fill":
        boundary = f.createIfcPolyline([pt(p) for p in local] + [pt(local[0])])
        fill_area = f.createIfcAnnotationFillArea(boundary, None)
        name = data.get("Pattern") or "Solid"
        pattern = patterns().get(name) or {"solid": True}
        fg = graphics.pen(pens, data.get("Pen") or 23)
        bg_no = int(data.get("BackgroundPen") or 0)
        bg = graphics.pen(pens, bg_no) if bg_no else None
        style = fill_style(f, name, pattern, fg, bg, metres_per_mm, scale)
        if style is not None:
            f.createIfcStyledItem(fill_area, [style], None)
        items.append(fill_area)
    return items


# ---------------------------------------------------------------- bridge

def _options(options_json):
    try:
        o = json.loads(options_json) if options_json else {}
    except ValueError:
        return None
    return o if isinstance(o, dict) else None


def _style_error(o: dict) -> str | None:
    from . import graphics
    from . import settings

    st = settings.current()
    if "line_type" in o and o["line_type"] not in graphics.effective("line_types", st):
        return f"unknown line type {o['line_type']}"
    if "pattern" in o and o["pattern"] not in patterns(st):
        return f"unknown fill pattern {o['pattern']}"
    for k in ("pen", "background_pen", "outline_pen"):
        if k in o:
            v = o[k]
            low = 0 if k in ("background_pen", "outline_pen") else 1
            if not (isinstance(v, int) and not isinstance(v, bool) and low <= v <= 255):
                return "pens are 1-255" if k == "pen" else f"the {k.replace('_', ' ')} is 0 (none) or 1-255"
    if "pattern_scale" in o and o["pattern_scale"] not in ("paper", "model"):
        return f"unknown pattern scale {o['pattern_scale']}"
    return None


def _extra(kind: str, o: dict) -> dict:
    extra = {}
    if "line_type" in o:
        extra["LineType"] = o["line_type"]
    if kind == "polyline" and "closed" in o:
        extra["Closed"] = bool(o["closed"])
    if kind == "fill":
        if "pattern" in o:
            extra["Pattern"] = o["pattern"]
        if "background_pen" in o:
            extra["BackgroundPen"] = int(o["background_pen"])
        if "show_area" in o:
            extra["ShowArea"] = bool(o["show_area"])
        if "outline_pen" in o:  # D92: the outline's pen (0: no outline; absent: the fill's pen)
            extra["OutlinePen"] = int(o["outline_pen"])
        if "pattern_scale" in o:  # D92: the pattern's spacings are paper mm (default) or model mm
            extra["PatternScale"] = o["pattern_scale"]
    return extra


def _shape(kind: str, points, o: dict):
    """(stored kind, points, extra) for a tool's input, or an error string."""
    if kind == "rectangle":  # two opposite corners -> a closed polyline (Archicad's rectangle polyline)
        if len(points) != 2:
            return "a rectangle needs two corners"
        (x0, y0), (x1, y1) = points
        if abs(x1 - x0) < 1e-6 or abs(y1 - y0) < 1e-6:
            return "the rectangle has no area"
        return "polyline", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], {**_extra("polyline", o), "Closed": True,
                                                                      "Rect": True}
    if kind == "line":
        if len(points) != 2 or math.dist(*points) < 1e-6:
            return "a line needs two different points"
    elif kind == "polyline":
        cleaned = [p for i, p in enumerate(points) if i == 0 or math.dist(p, points[i - 1]) > 1e-6]
        if len(cleaned) < 2:
            return "a polyline needs at least two points"
        if o.get("closed") and len(cleaned) > 2 and math.dist(cleaned[0], cleaned[-1]) < 1e-6:
            cleaned.pop()
        if o.get("closed") and len(cleaned) < 3:
            return "a closed polyline needs at least three points"
        points = cleaned
    elif kind == "arc":
        if len(points) != 3 or circumcircle(*points) is None:
            return "an arc needs three points not in a line"
    elif kind == "circle":
        if len(points) != 2 or math.dist(*points) < 1e-6:
            return "a circle needs its centre and a point on it"
    elif kind == "fill":
        if len(points) > 3 and math.dist(points[0], points[-1]) < 1e-6:
            points = points[:-1]
        if not is_simple(points):
            return "the fill's outline must be closed and not cross itself"
    else:
        return f"unknown drafting kind {kind}"
    return kind, points, _extra(kind, o)


def add_drafting(storey_guid: str, kind: str, points_json: str, options_json: str = "") -> str:
    """Draw a line (2 points), polyline (points; option `closed`), arc (start, a point on it, end),
    circle (centre, a point on it), rectangle (two corners: a closed polyline) or fill (its outline)
    on a level, in world metres. Options: `line_type`, `pen`, and for fills `pattern`,
    `background_pen` (0: none) and `show_area`. Pen and line type default to the current ones."""
    from . import annotations as N
    from . import authoring as A
    from . import app_bridge as B

    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    o = _options(options_json)
    if o is None:
        return A._fail("bad options")
    if (err := _style_error(o)) is not None:
        return A._fail(err)
    try:
        points = [(float(x), float(y)) for x, y in json.loads(points_json)]
    except (TypeError, ValueError) as ex:
        return A._fail(f"bad points: {ex}")
    shape = _shape(kind, points, o)
    if isinstance(shape, str):
        return A._fail(shape)
    kind, points, extra = shape
    if kind == "fill":
        extra.setdefault("Pattern", "Solid")
        extra.setdefault("BackgroundPen", 0)
        extra.setdefault("ShowArea", False)
    extra.setdefault("LineType", "Solid")
    return N.add_shape(storey, kind, points, extra, o.get("pen"))


def fill_from_shape(guid: str, options_json: str = "") -> str:
    """A fill with the outline of a closed polyline, circle or fill (Archicad's magic wand on a
    picked shape), on the same level."""
    from . import annotations as N
    from . import authoring as A
    from . import app_bridge as B

    a = A._by_guid(guid) if B._model is not None else None
    data = N._read(a) if a is not None and a.is_a("IfcAnnotation") else None
    world = N.world_points(a) if data is not None else None
    polygon = closed_polygon(data[0], world, N.extra_of(a).get("Closed")) if data is not None else None
    if polygon is None:
        return A._fail("pick a closed polyline, a rectangle, a circle or a fill")
    import ifcopenshell.util.element

    storey = ifcopenshell.util.element.get_container(a)
    return add_drafting(storey.GlobalId, "fill", json.dumps(polygon), options_json)


def fill_at(storey_guid: str, x, y, options_json: str = "") -> str:
    """A fill of the smallest closed drafting shape on the level around (x, y) metres."""
    from . import annotations as N
    from . import authoring as A
    from . import app_bridge as B

    if B._model is None:
        return A._fail("no model open")
    try:
        p = (float(x), float(y))
    except (TypeError, ValueError):
        return A._fail("bad point")
    best = None
    for a in N.on_level(storey_guid):
        data = N._read(a)
        if data is None or data[0] not in ("polyline", "circle", "fill"):
            continue
        polygon = closed_polygon(data[0], N.world_points(a), N.extra_of(a).get("Closed"))
        if polygon and inside(p, polygon) and (best is None or abs(area(polygon)) < abs(area(best))):
            best = polygon
    if best is None:
        return A._fail("click inside a closed polyline, rectangle or circle")
    return add_drafting(storey_guid, "fill", json.dumps(best), options_json)


def set_drafting_style(guids_json: str, options_json: str) -> str:
    """Change the line type, pen, fill pattern, background pen or area label of drafting shapes
    (one undo step); options that don't apply to a shape are skipped."""
    from . import annotations as N
    from . import authoring as A
    from . import app_bridge as B

    if B._model is None:
        return A._fail("no model open")
    o = _options(options_json)
    if o is None or not o:
        return A._fail("bad options")
    if (err := _style_error(o)) is not None:
        return A._fail(err)
    targets = []
    for a in B._elements(guids_json):
        data = N._read(a) if a.is_a("IfcAnnotation") else None
        if data is not None and data[0] in KINDS:
            targets.append((a, data))
    if not targets:
        return A._fail("select lines, arcs, circles, polylines or fills")

    def action():
        for a, (kind, text, local, size, pen) in targets:
            N._set(a, kind, text, local, size, o.get("pen", pen), extra=_extra(kind, o))
        return len(targets), [a.GlobalId for a, _ in targets], []

    return B._dump(B._run(action))


def set_annotation_points(guid: str, points_json: str) -> str:
    """New points (world metres) for a drafting shape (grips: an end or a corner moved), keeping its
    style. Validated like a new shape."""
    from . import annotations as N
    from . import authoring as A
    from . import app_bridge as B

    a = A._by_guid(guid) if B._model is not None else None
    data = N._read(a) if a is not None and a.is_a("IfcAnnotation") else None
    if data is None or data[0] not in KINDS:
        return A._fail("not a drafting shape")
    try:
        points = [(float(x), float(y)) for x, y in json.loads(points_json)]
    except (TypeError, ValueError) as ex:
        return A._fail(f"bad points: {ex}")
    extra = N.extra_of(a)
    shape = _shape(data[0], points, {"closed": bool(extra.get("Closed"))})
    if isinstance(shape, str):
        return A._fail(shape)
    _kind, points, _ = shape

    def action():
        N.replace_points(a, points)
        return 1, [a.GlobalId], []

    return B._dump(B._run(action))


def fill_patterns() -> str:
    """The fill patterns (the project's table or the built-ins), names in order."""
    from . import app_bridge as B

    table = patterns()
    return B._dump({"ok": True, "patterns": table, "names": list(table)})


def snap_points(storey) -> list:
    """Snap targets of the level's drafting shapes (world metres): ends and corners, the middles of
    straight segments and of arcs, and the centres of circles and arcs."""
    from . import annotations as N

    out = []

    def add(p, kind, guid):
        out.append({"x": round(float(p[0]), 6), "y": round(float(p[1]), 6), "kind": kind, "guid": guid})

    for a in N.on_level(storey.GlobalId):
        data = N._read(a)
        if data is None or data[0] not in KINDS:
            continue
        kind, guid, world = data[0], a.GlobalId, N.world_points(a)
        if kind in ("line", "polyline", "fill"):
            pts = world[:2] if kind == "line" else world
            closed = kind == "fill" or (kind == "polyline" and bool(N.extra_of(a).get("Closed")))
            for p in pts:
                add(p, "endpoint", guid)
            for p, q in zip(pts, pts[1:] + (pts[:1] if closed else [])):
                add(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2), "midpoint", guid)
        elif kind == "arc" and len(world) == 3:
            add(world[0], "endpoint", guid)
            add(world[2], "endpoint", guid)
            curve = arc_points(*world)
            add(curve[len(curve) // 2], "midpoint", guid)
            if (cc := circumcircle(*world)) is not None:
                add(cc[0], "centre", guid)
        elif kind == "circle" and len(world) == 2:
            add(world[0], "centre", guid)
            r = math.dist(world[0], world[1])
            for dx, dy in ((r, 0), (0, r), (-r, 0), (0, -r)):  # the quadrant points
                add((world[0][0] + dx, world[0][1] + dy), "endpoint", guid)
    return out


# ---------------------------------------------------------------- drawings (plan views only)

def _xml(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def drawing_parts(storey, to_paper, settings: dict | None = None) -> list:
    """SVG (paper mm) of the level's drafting shapes. Each is a group graphics.style_svg styles like
    an annotation (data-pen: its pen; data-dash: its line type in mm on paper); a fill's area is
    `data-fill="pen"` (solid: the pen's colour) or `data-fill-pen` (its background pen)."""
    from . import annotations as N
    from . import drawgen as G

    def fmt(v):
        return f"{v:.3f}"

    out = []
    z = G.storey_elevation(storey)
    for a in N.on_level(storey.GlobalId):
        data = N._read(a)
        if data is None or data[0] not in KINDS:
            continue
        kind, _text, _local, size, pen = data
        world = N.world_points(a)
        sd = shape_data(kind, world, N.extra_of(a), G.SCALE / 1000.0, settings)

        def paper(p):
            return to_paper(p[0], p[1], z)

        attrs = f' data-pen="{int(pen)}"' if pen else ""
        if sd["dash"]:
            attrs += f' data-dash="{" ".join(f"{v:g}" for v in sd["dash"])}"'
        out.append(f'<g data-kind="annotation" data-drafting="{kind}" ifc:guid="{a.GlobalId}"{attrs}>')
        if kind == "fill":
            ring = [paper(p) for p in sd["area"]]
            d = "M" + " L".join(f"{fmt(x)},{fmt(y)}" for x, y in ring) + " Z"
            if sd["solid"]:
                out.append(f'<path d="{d}" data-fill="pen" stroke="none"/>')
            elif sd["background_pen"]:
                out.append(f'<path d="{d}" data-fill-pen="{sd["background_pen"]}" stroke="none"/>')
            if sd["hatch"]:
                parts = []
                for x1, y1, x2, y2 in sd["hatch"]:
                    (px, py), (qx, qy) = paper((x1, y1)), paper((x2, y2))
                    parts.append(f"M{fmt(px)},{fmt(py)} L{fmt(qx)},{fmt(qy)}")
                out.append(f'<path class="hatch" d="{" ".join(parts)}" stroke-dasharray="none"/>')
            if sd.get("outline_pen", -1) != 0:  # D92: the fill's outline, in its own pen when one is set
                if sd.get("outline_pen", -1) > 0:
                    out.append(f'<g data-kind="annotation" data-pen="{sd["outline_pen"]}"><path d="{d}"/></g>')
                else:
                    out.append(f'<path d="{d}"/>')
            else:  # no outline: the loop is still there for the DXF hatch
                out.append(f'<path d="{d}" data-outline="none" stroke="none"/>')
            if sd.get("show_area"):
                x, y = paper(sd["label_at"])
                out.append(f'<text x="{fmt(x)}" y="{fmt(y)}" font-size="{fmt(size)}" text-anchor="middle" '
                           f'dominant-baseline="central">{_xml(sd["area_text"])}</text>')
        else:
            for curve in sd["curves"]:
                pts = [paper(p) for p in curve]
                out.append('<path d="M' + " L".join(f"{fmt(x)},{fmt(y)}" for x, y in pts) + '"/>')
        out.append("</g>")
    return out


def add_to_drawing(svg: str, drawing, settings: dict | None = None) -> str:
    """A plan drawing's SVG with the level's drafting shapes, under the model's lines (as fills are in
    Archicad's default stacking), the viewBox grown to include them. Other drawings are unchanged."""
    from . import drawgen as G

    s = G.settings_of(drawing)
    if s is None or s.get("kind") != "plan":
        return svg
    storey = G._storey(drawing, s)
    to_paper = G.paper_mapping(svg)
    if storey is None or to_paper is None:
        return svg
    parts = drawing_parts(storey, to_paper, settings)
    from . import underlays
    from .worksheets import is_worksheet

    if is_worksheet(storey):  # D98: pictures on a worksheet are figures: they print, under the drafting
        figures = underlays.figures_svg(storey.GlobalId, to_paper)
        if figures:
            parts = figures + parts
            if "xmlns:xlink" not in svg[:500]:
                svg = svg.replace("<svg ", '<svg xmlns:xlink="http://www.w3.org/1999/xlink" ', 1)
    if not parts:
        return svg
    group = ('<g class="kimbim-drafting" fill="none" stroke="#000000" stroke-width="0.18" font-family="sans-serif">\n'
             + "\n".join(parts) + "\n</g>\n")
    group = group.replace("<text ", '<text fill="#000000" stroke="none" ')
    at = svg.find('<g class="section"')
    if at < 0:
        at = svg.find("<g ")
    svg = svg[:at] + group + svg[at:] if at >= 0 else svg.replace("</svg>", group + "</svg>", 1)
    return G.crop(svg)
