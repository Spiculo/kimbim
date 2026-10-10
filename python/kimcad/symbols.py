# SPDX-License-Identifier: GPL-3.0-or-later
"""The annotation pack (doc 14 §13, D87): tags, north arrows, scale bars, revision clouds and the
angle, radius, diameter, level and spot-elevation dimensions.

They are plan annotations (D59): an IfcAnnotation on the level, ObjectType TAG / NORTH / SCALEBAR /
CLOUD / ANGLE / RADIUS / DIAMETER / LEVEL / SPOT, with an Annotation2D representation (polylines, fill
areas, text literals) and KIMCAD's own data in the KIMCAD_Annotation property set: points relative to
the placement, the text, the pen and the values in EXTRA. Moving, rotating, copying, deleting, layers
and undo are the annotations' (so every element's). Tags are kimcad.tags'.

Every kind is drawn from one description (`geometry`, world metres): polylines, filled polygons and
text labels, so the plan view, the drawings, the sheets, the DXF and the IFC representation agree.
Sizes are millimetres on paper at the drawing scale (1:100), like D59's text.

This module's geometry is pure (no model); the bridge functions import app_bridge when called.
"""
from __future__ import annotations

import json
import math

KINDS = ("tag", "north", "scalebar", "cloud", "angle", "radius", "diameter", "level", "spot")
# Kind -> (fewest points, most points). A tag: where its text sits, then the element's anchor. An
# angle: the vertex, a point on each ray, a point the arc passes through. A radius or diameter: the
# centre, a point on the circle, where the text sits. A spot elevation: the point, where the text sits.
POINTS = {"tag": (2, 2), "north": (1, 1), "scalebar": (1, 1), "cloud": (3, None), "angle": (4, 4),
          "radius": (3, 3), "diameter": (3, 3), "level": (1, 1), "spot": (2, 2)}
# Pset keys beside Kind/Text/Points/Size/Pen: a tag's style, its template and shape (empty: the
# style's), whether it has a leader, its element (a copy of the IfcRelAssignsToProduct, for copies),
# where its element's anchor and its text were when last updated (world metres, JSON); Auto: a level
# or spot elevation measures itself; Scale: the scale bar's drawing scale (1:n).
EXTRA = ("Style", "Template", "Shape", "Leader", "Element", "Anchor", "At", "Auto", "Scale")
SHAPES = ("none", "circle", "box", "hexagon")
NAMES = {"tag": "Tag", "north": "North arrow", "scalebar": "Scale bar", "cloud": "Revision cloud",
         "angle": "Angle dimension", "radius": "Radius dimension", "diameter": "Diameter dimension",
         "level": "Level dimension", "spot": "Spot elevation"}
NORTH_RADIUS = 6.0  # mm on paper
CLOUD_ARC = 6.0  # mm on paper: the length of each arc of a revision cloud
SCALEBAR_LENGTH = 50.0  # mm on paper, about


# ---------------------------------------------------------------- geometry (world metres)

def _add(p, v, k=1.0):
    return [p[0] + v[0] * k, p[1] + v[1] * k]


def _unit(v):
    length = math.hypot(v[0], v[1])
    return (v[0] / length, v[1] / length) if length > 1e-12 else (1.0, 0.0)


def _polygon(centre, r, n=36, start=0.0):
    return [[centre[0] + r * math.cos(start + 2 * math.pi * i / n), centre[1] + r * math.sin(start + 2 * math.pi * i / n)]
            for i in range(n)]


def _label(text, at, size, anchor="middle", angle=0.0):
    return {"text": text, "at": [float(at[0]), float(at[1])], "size": float(size), "anchor": anchor, "angle": float(angle)}


def _readable(degrees: float) -> float:
    while degrees > 90:
        degrees -= 180
    while degrees <= -90:
        degrees += 180
    return degrees


def _tick(p, u, n, half):
    """An architectural tick (45 degrees) through p: u along the line, n across it."""
    d = ((u[0] + n[0]) * half, (u[1] + n[1]) * half)
    return [[p[0] - d[0], p[1] - d[1]], [p[0] + d[0], p[1] + d[1]]]


def _arrow(tip, towards, length, half_width):
    """An open arrowhead at `tip`, its two strokes going back along `towards` (a unit vector)."""
    bx, by = tip[0] - towards[0] * length, tip[1] - towards[1] * length
    nx, ny = -towards[1], towards[0]
    return [[bx + nx * half_width, by + ny * half_width], list(tip), [bx - nx * half_width, by - ny * half_width]]


def _segment_hit(a, b, c, d):
    """t along a->b where it crosses c->d, or None."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    den = rx * sy - ry * sx
    if abs(den) < 1e-15:
        return None
    t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / den
    u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / den
    return t if 0 <= t <= 1 and 0 <= u <= 1 else None


def _inside(p, polygon) -> bool:
    hit = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y0 > p[1]) != (y1 > p[1]) and p[0] < x0 + (p[1] - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def text_box(lines, h):
    """(width, height) of text lines `h` metres high (an estimate: 0.6 h per character)."""
    step = 1.5 * h
    width = max((0.6 * h * max(len(line), 1) for line in lines), default=0.6 * h)
    return width, (len(lines) - 1) * step + h


def tag_outline(shape, centre, lines, h):
    """The tag's frame (a closed polygon, world metres) and the boundary its leader stops at."""
    w, height = text_box(lines, h)
    pad = 0.4 * h
    cx, cy = centre
    hw, hh = w / 2 + pad, height / 2 + pad
    if shape == "box":
        frame = [[cx - hw, cy - hh], [cx + hw, cy - hh], [cx + hw, cy + hh], [cx - hw, cy + hh]]
    elif shape == "circle":
        frame = _polygon(centre, max(math.hypot(w / 2, height / 2) + pad * 0.5, 1.1 * h))
    elif shape == "hexagon":
        slope = hh * 0.577
        frame = [[cx - hw - slope, cy], [cx - hw, cy - hh], [cx + hw, cy - hh], [cx + hw + slope, cy],
                 [cx + hw, cy + hh], [cx - hw, cy + hh]]
    else:
        g = 0.2 * h
        return None, [[cx - w / 2 - g, cy - height / 2 - g], [cx + w / 2 + g, cy - height / 2 - g],
                      [cx + w / 2 + g, cy + height / 2 + g], [cx - w / 2 - g, cy + height / 2 + g]]
    return frame, frame


def nice_length(target: float) -> tuple[float, int]:
    """A round total length not over `target` (1, 2, 2.5 or 5 times a power of ten) and its segments."""
    if target <= 0:
        return 1.0, 5
    k = 10 ** math.floor(math.log10(target))
    for lead, segments in ((5, 5), (2.5, 5), (2, 4), (1, 5)):
        if lead * k <= target * (1 + 1e-9):
            return lead * k, segments
    return k, 5


def scale_bar(left, scale: float, metres_per_mm: float) -> dict:
    """A scale bar for a drawing at 1:`scale`, its left end at `left`; sizes are paper mm ×
    `metres_per_mm` (the drawing's own: the bar's metres are model metres)."""
    total, segments = nice_length(SCALEBAR_LENGTH * scale / 1000.0)
    length = total * metres_per_mm * 1000.0 / scale  # model metres drawn for `total` metres
    bar = 1.5 * metres_per_mm
    x0, y0 = left
    out = {"curves": [[[x0, y0], [x0 + length, y0], [x0 + length, y0 + bar], [x0, y0 + bar], [x0, y0]]],
           "solids": [], "labels": []}
    step = length / segments
    for i in range(segments):
        if i % 2 == 0:
            out["solids"].append([[x0 + i * step, y0], [x0 + (i + 1) * step, y0], [x0 + (i + 1) * step, y0 + bar],
                                  [x0 + i * step, y0 + bar]])
    for i in range(segments + 1):
        value = f"{total * i / segments:g}" + (" m" if i == segments else "")
        out["labels"].append(_label(value, (x0 + i * step, y0 - 2.5 * metres_per_mm), 2.0))
    out["labels"].append(_label(f"1:{int(scale)}", (x0, y0 + bar + 2.5 * metres_per_mm), 2.0, "start"))
    return out


def north_arrow(centre, north, metres_per_mm: float) -> dict:
    """A north arrow: a circle and an arrow pointing north (half filled), N beyond its tip."""
    n = _unit(north)
    e = (n[1], -n[0])  # east: north turned clockwise
    r = NORTH_RADIUS * metres_per_mm
    c = centre
    tip, notch = _add(c, n, r), _add(c, n, -0.25 * r)
    left = _add(_add(c, n, -0.6 * r), e, -0.42 * r)
    right = _add(_add(c, n, -0.6 * r), e, 0.42 * r)
    circle = _polygon(c, r, 48)
    return {"curves": [circle + [circle[0]], [tip, right, notch, left, tip]], "solids": [[tip, right, notch]],
            "labels": [_label("N", _add(c, n, r + 3.0 * metres_per_mm), 3.5)]}


def revision_cloud(points, text, size, metres_per_mm: float) -> dict:
    """A closed outline drawn as arcs bulging outwards, with a triangle holding the revision tag."""
    pts = [list(p) for p in points]
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2
    outward = 1.0 if area > 0 else -1.0  # counter-clockwise: outwards is to the right of each edge
    chord = CLOUD_ARC * metres_per_mm
    curve = []
    for p, q in zip(pts, pts[1:] + pts[:1]):
        length = math.dist(p, q)
        if length < 1e-9:
            continue
        n = max(1, round(length / chord))
        ux, uy = (q[0] - p[0]) / length, (q[1] - p[1]) / length
        nx, ny = uy * outward, -ux * outward
        for j in range(n):
            a = [p[0] + (q[0] - p[0]) * j / n, p[1] + (q[1] - p[1]) * j / n]
            b = [p[0] + (q[0] - p[0]) * (j + 1) / n, p[1] + (q[1] - p[1]) * (j + 1) / n]
            sag = 0.35 * length / n
            m = [(a[0] + b[0]) / 2 + nx * sag, (a[1] + b[1]) / 2 + ny * sag]
            arc = _arc(a, m, b, 8)
            curve += arc if not curve else arc[1:]
    out = {"curves": [curve] if curve else [], "solids": [], "labels": []}
    if text:
        h = size * metres_per_mm
        side = max(2.6 * h, 0.6 * h * len(text) + 1.6 * h)
        c = pts[0]
        tri = [[c[0] - side / 2, c[1] - side * 0.29], [c[0] + side / 2, c[1] - side * 0.29], [c[0], c[1] + side * 0.58]]
        out["curves"].append(tri + [tri[0]])
        out["labels"].append(_label(text, (c[0], c[1] - side * 0.05), size))
    return out


def _arc(a, m, b, n):
    """Points of the arc from a through m to b."""
    from .drafting import arc_frame

    frame = arc_frame(a, m, b)
    if frame is None:
        return [list(a), list(b)]
    (ux, uy), r, a0, sweep = frame
    return [[ux + r * math.cos(a0 + sweep * i / n), uy + r * math.sin(a0 + sweep * i / n)] for i in range(n + 1)]


def angle_frame(v, a, b, r_point):
    """(start angle, sweep, radius) of an angle dimension: the arc between the rays v->a and v->b on
    the side `r_point` is (counter-clockwise from start)."""
    a0 = math.atan2(a[1] - v[1], a[0] - v[0])
    a1 = math.atan2(b[1] - v[1], b[0] - v[0])
    ar = math.atan2(r_point[1] - v[1], r_point[0] - v[0])
    ccw = (a1 - a0) % (2 * math.pi)
    radius = math.dist(v, r_point)
    if (ar - a0) % (2 * math.pi) <= ccw:
        return a0, ccw, radius
    return a1, 2 * math.pi - ccw, radius


def angle_text(points) -> str:
    _start, sweep, _r = angle_frame(*points[:4])
    return f"{math.degrees(sweep):.2f}°"


def _length(metres: float) -> str:
    from .settings import format_length

    return format_length(metres, unit=False)


def radial_text(kind, points) -> str:
    r = math.dist(points[0], points[1])
    return ("R " + _length(r)) if kind == "radius" else ("Ø " + _length(2 * r))


def elevation_text(z: float) -> str:
    if abs(z) < 5e-4:
        return "±" + _length(0.0)
    return ("+" if z > 0 else "-") + _length(abs(z))


def geometry(kind, pts, text, size, data, metres_per_mm, north=(0.0, 1.0)) -> dict:
    """What to draw (world metres, or local: any frame without rotation): {curves, solids, labels}.
    Labels are {text, at, size (mm on paper), anchor (start/middle/end), angle (degrees, counter-clockwise)}."""
    pts = [list(map(float, p)) for p in pts]
    h = size * metres_per_mm
    out = {"curves": [], "solids": [], "labels": []}
    if kind == "tag" and len(pts) >= 2:
        p, anchor = pts[0], pts[1]
        lines = [line for line in (text or "?").split("\n")] or ["?"]
        step = 1.5 * h
        for i, line in enumerate(lines):
            out["labels"].append(_label(line, (p[0], p[1] + (len(lines) - 1) / 2 * step - i * step), size))
        frame, boundary = tag_outline(data.get("Shape") or "none", p, lines, h)
        if frame is not None:
            out["curves"].append(frame + [frame[0]])
        if data.get("Leader") and not _inside(anchor, boundary):
            hits = [t for i in range(len(boundary))
                    if (t := _segment_hit(anchor, p, boundary[i], boundary[(i + 1) % len(boundary)])) is not None]
            t = min(hits) if hits else 1.0
            end = [anchor[0] + (p[0] - anchor[0]) * t, anchor[1] + (p[1] - anchor[1]) * t]
            if math.dist(anchor, end) > 1e-6:
                out["curves"].append([anchor, end])
                out["solids"].append(_polygon(anchor, 0.5 * metres_per_mm, 8))
    elif kind == "north" and pts:
        out = north_arrow(pts[0], north, metres_per_mm)
    elif kind == "scalebar" and pts:
        out = scale_bar(pts[0], float(data.get("Scale") or 100), metres_per_mm)
    elif kind == "cloud" and len(pts) >= 3:
        out = revision_cloud(pts, text, size, metres_per_mm)
    elif kind == "angle" and len(pts) >= 4:
        v, a, b, _r = pts[:4]
        start, sweep, r = angle_frame(*pts[:4])
        n = max(8, int(math.ceil(sweep / (2 * math.pi) * 72)))
        arc = [[v[0] + r * math.cos(start + sweep * i / n), v[1] + r * math.sin(start + sweep * i / n)] for i in range(n + 1)]
        out["curves"].append(arc)
        ends = (a, b) if math.isclose(start, math.atan2(a[1] - v[1], a[0] - v[0])) else (b, a)
        for t, clicked in ((start, ends[0]), (start + sweep, ends[1])):
            u = (math.cos(t), math.sin(t))
            on_arc = _add(v, u, r)
            if math.dist(v, clicked) < r:  # an extension line from the clicked point to just past the arc
                out["curves"].append([clicked, _add(v, u, r + 1.5 * metres_per_mm)])
            else:
                out["curves"].append([_add(v, u, max(r - 1.5 * metres_per_mm, 0.0)), clicked])
            out["curves"].append(_tick(on_arc, (-u[1], u[0]), u, 1.0 * metres_per_mm))
        mid = start + sweep / 2
        at = _add(v, (math.cos(mid), math.sin(mid)), r + 0.9 * h)
        out["labels"].append(_label(text or angle_text(pts), at, size, angle=_readable(math.degrees(mid) - 90)))
    elif kind in ("radius", "diameter") and len(pts) >= 3:
        c, on, at = pts[:3]
        u = _unit((on[0] - c[0], on[1] - c[1]))
        start = c if kind == "radius" else [2 * c[0] - on[0], 2 * c[1] - on[1]]
        out["curves"].append([start, on])
        out["curves"].append(_arrow(on, u, 2.0 * metres_per_mm, 0.6 * metres_per_mm))
        if kind == "diameter":
            out["curves"].append(_arrow(start, (-u[0], -u[1]), 2.0 * metres_per_mm, 0.6 * metres_per_mm))
        if math.dist(on, at) > h:
            out["curves"].append([on, at])
        anchor = "start" if at[0] >= on[0] - 1e-9 else "end"
        shift = 0.6 * h if anchor == "start" else -0.6 * h
        out["labels"].append(_label(text or radial_text(kind, pts), (at[0] + shift, at[1]), size, anchor))
    elif kind == "level" and pts:
        p = pts[0]
        r = 1.5 * metres_per_mm
        circle = _polygon(p, r, 24)
        out["curves"] += [circle + [circle[0]], [[p[0] - 1.6 * r, p[1]], [p[0] + 1.6 * r, p[1]]],
                          [[p[0], p[1] - 1.6 * r], [p[0], p[1] + 1.6 * r]]]
        out["solids"].append([p] + [[p[0] + r * math.cos(t * math.pi / 12), p[1] + r * math.sin(t * math.pi / 12)]
                                    for t in range(7)])
        out["labels"].append(_label(text, (p[0] + 2.2 * r, p[1] + 0.9 * h), size, "start"))
    elif kind == "spot" and len(pts) >= 2:
        p, at = pts[:2]
        w = 1.2 * metres_per_mm
        tri = [list(p), [p[0] - w, p[1] + 2 * w], [p[0] + w, p[1] + 2 * w]]
        out["curves"].append(tri + [tri[0]])
        out["solids"].append(tri)
        top = [p[0], p[1] + 2 * w]
        if math.dist(top, at) > 1e-6:
            out["curves"].append([top, at])
        width = 0.6 * h * max(len(text or ""), 1)
        anchor = "start" if at[0] >= p[0] - 1e-9 else "end"
        out["curves"].append([at, [at[0] + (width if anchor == "start" else -width), at[1]]])
        out["labels"].append(_label(text, (at[0], at[1] + 0.7 * h), size, anchor))
    return out


def measured_text(kind, pts) -> str:
    """The text a dimension shows when it has none of its own."""
    if kind == "angle" and len(pts) >= 4:
        return angle_text(pts)
    if kind in ("radius", "diameter") and len(pts) >= 3:
        return radial_text(kind, pts)
    return ""


# ---------------------------------------------------------------- IFC items and SVG

def ifc_items(f, geom: dict, pt, literal) -> list:
    """IFC 2D items for a geometry in local metres: IfcPolyline per curve, an IfcAnnotationFillArea per
    filled polygon, a text literal per label (`literal(at, text)` makes one)."""
    items = []
    for curve in geom["curves"]:
        if len(curve) >= 2:
            items.append(f.createIfcPolyline([pt(p) for p in curve]))
    for solid in geom["solids"]:
        if len(solid) >= 3:
            items.append(f.createIfcAnnotationFillArea(f.createIfcPolyline([pt(p) for p in solid] + [pt(solid[0])]), None))
    for label in geom["labels"]:
        if label["text"]:
            items.append(literal(label["at"], label["text"]))
    return items


def _xml(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def svg_parts(geom: dict, to_paper) -> list:
    """SVG (paper mm) of a geometry: `to_paper` maps world metres (x, y) to paper mm. Filled polygons
    are `data-fill="pen"` (graphics.style_svg fills them with the pen's colour)."""
    def f3(v):
        return f"{v:.3f}"

    out = []
    for solid in geom["solids"]:
        pts = [to_paper(p) for p in solid]
        out.append('<path d="M' + " L".join(f"{f3(x)},{f3(y)}" for x, y in pts) + ' Z" data-fill="pen" stroke="none"/>')
    for curve in geom["curves"]:
        pts = [to_paper(p) for p in curve]
        if len(pts) >= 2:
            out.append('<path d="M' + " L".join(f"{f3(x)},{f3(y)}" for x, y in pts) + '"/>')
    for label in geom["labels"]:
        if not label["text"]:
            continue
        x, y = to_paper(label["at"])
        rotate = ""
        if abs(label["angle"]) > 1e-6:  # the angle on paper, from the world angle through the mapping
            t = math.radians(label["angle"])
            qx, qy = to_paper((label["at"][0] + math.cos(t), label["at"][1] + math.sin(t)))
            rotate = f' transform="rotate({f3(math.degrees(math.atan2(qy - y, qx - x)))} {f3(x)} {f3(y)})"'
        out.append(f'<text x="{f3(x)}" y="{f3(y)}" font-size="{f3(label["size"])}" text-anchor="{label["anchor"]}" '
                   f'dominant-baseline="central"{rotate}>{_xml(label["text"])}</text>')
    return out


def round_geometry(geom: dict) -> dict:
    """The geometry for the app's listing (6 decimals)."""
    def r(p):
        return [round(float(p[0]), 6), round(float(p[1]), 6)]

    return {"curves": [[r(p) for p in c] for c in geom["curves"]], "solids": [[r(p) for p in s] for s in geom["solids"]],
            "labels": [{**lab, "at": r(lab["at"])} for lab in geom["labels"]]}


# ---------------------------------------------------------------- the model

def true_north(f=None):
    """The direction of true north in the model's plan (x, y), from the model context's TrueNorth
    (IfcGeometricRepresentationContext); (0, 1) when none is stored."""
    from . import app_bridge as B

    f = f or B._model
    if f is None:
        return (0.0, 1.0)
    for context in f.by_type("IfcGeometricRepresentationContext"):
        if context.is_a("IfcGeometricRepresentationSubContext") or context.ContextType != "Model":
            continue
        d = getattr(context, "TrueNorth", None)
        if d is not None and len(d.DirectionRatios) >= 2:
            x, y = float(d.DirectionRatios[0]), float(d.DirectionRatios[1])
            if math.hypot(x, y) > 1e-12:
                return _unit((x, y))
    return (0.0, 1.0)


def true_north_angle(f=None) -> float:
    """Degrees true north is turned from the plan's +Y, counter-clockwise (Archicad's project north)."""
    x, y = true_north(f)
    return round(math.degrees(math.atan2(-x, y)), 6)


def _slab_top(storey, p):
    """The elevation (metres) of the top of the highest slab on the level under p, or None."""
    import ifcopenshell.util.element
    import ifcopenshell.util.placement
    import ifcopenshell.util.representation
    import numpy as np

    from . import authoring as A

    s = A._scale()
    best = None
    for rel in getattr(storey, "ContainsElements", None) or ():
        for e in rel.RelatedElements:
            if not e.is_a("IfcSlab") or e.ObjectPlacement is None:
                continue
            body = ifcopenshell.util.representation.get_representation(e, "Model", "Body", "MODEL_VIEW")
            for item in (body.Items if body else ()):
                if not item.is_a("IfcExtrudedAreaSolid") or not item.SweptArea.is_a("IfcArbitraryClosedProfileDef"):
                    continue
                curve = item.SweptArea.OuterCurve
                if curve.is_a("IfcPolyline"):
                    local = [c.Coordinates[:2] for c in curve.Points]
                elif curve.is_a("IfcIndexedPolyCurve"):
                    local = [c[:2] for c in curve.Points.CoordList]
                else:
                    continue
                m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
                if item.Position is not None:
                    m = m @ ifcopenshell.util.placement.get_axis2placement(item.Position)
                world = [(m @ np.array([x, y, 0.0, 1.0]))[:3] * s for x, y in local]
                if not _inside(p, [list(w[:2]) for w in world]):
                    continue
                d = item.ExtrudedDirection.DirectionRatios
                top = (m @ np.array([d[0] * item.Depth, d[1] * item.Depth, d[2] * item.Depth, 1.0]))[2] * s
                z = max(float(world[0][2]), float(top))
                best = z if best is None else max(best, z)
    return best


def elevation_at(storey, p) -> float:
    """What a level or spot elevation at p measures: the top of the slab under it, else the level."""
    from . import authoring as A

    top = _slab_top(storey, p)
    return top if top is not None else A._elevation(storey)


def _options(options_json):
    try:
        o = json.loads(options_json) if options_json else {}
    except ValueError:
        return None
    return o if isinstance(o, dict) else None


def add_symbol(storey_guid: str, kind: str, points_json: str, options_json: str = "") -> str:
    """A north arrow (its centre), a scale bar (its left end), a revision cloud (its outline; text: the
    revision), an angle (vertex, a point on each ray, a point on the arc), a radius or diameter
    (centre, a point on the circle, the text position), a level dimension (the point) or a spot
    elevation (the point, the text position) on a level. Points in world metres. options: {text,
    scale (scale bars), pen}. A dimension without text measures itself (levels and spots keep measuring)."""
    from . import annotations as N
    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    if kind not in KINDS or kind == "tag":  # tags: tags.add_tag
        return A._fail(f"unknown symbol {kind}")
    o = _options(options_json)
    if o is None:
        return A._fail("bad options")
    try:
        points = [(float(x), float(y)) for x, y in json.loads(points_json)]
    except (TypeError, ValueError) as ex:
        return A._fail(f"bad points: {ex}")
    fewest, most = POINTS[kind]
    if len(points) < fewest or (most is not None and len(points) > most):
        return A._fail(f"a {NAMES[kind].lower()} needs {fewest} point(s)" if fewest == most
                       else f"a {NAMES[kind].lower()} needs at least {fewest} points")
    if kind == "cloud":
        from . import drafting

        if not drafting.is_simple(points):
            return A._fail("the cloud's outline crosses itself")
    if kind in ("radius", "diameter") and math.dist(points[0], points[1]) < 1e-6:
        return A._fail("click a point on the circle, away from its centre")
    if kind == "angle" and (math.dist(points[0], points[1]) < 1e-6 or math.dist(points[0], points[2]) < 1e-6):
        return A._fail("click a point on each side of the angle, away from its vertex")
    text = str(o.get("text") or "").strip()
    extra = {}
    if kind == "scalebar":
        try:
            extra["Scale"] = int(o.get("scale") or N.DRAWING_SCALE)
        except (TypeError, ValueError):
            return A._fail("bad scale")
        if extra["Scale"] <= 0:
            return A._fail("bad scale")
    if kind in ("level", "spot"):
        extra["Auto"] = not text
        if not text:
            text = elevation_text(elevation_at(storey, points[0]))
    pen = o.get("pen")
    return N.add_shape(storey, kind, points, extra, pen=pen if isinstance(pen, int) else None, text=text,
                       name=NAMES[kind])


def set_true_north(degrees) -> str:
    """Turn true north `degrees` counter-clockwise from the plan's +Y (the model context's TrueNorth;
    0 clears it). North arrows follow."""
    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    try:
        a = math.radians(float(degrees))
    except (TypeError, ValueError):
        return A._fail("bad angle")
    contexts = [c for c in B._model.by_type("IfcGeometricRepresentationContext")
                if not c.is_a("IfcGeometricRepresentationSubContext") and c.ContextType == "Model"]
    if not contexts:
        return A._fail("the model has no 3D context")

    def action():
        f = B._model
        for c in contexts:
            old = c.TrueNorth
            c.TrueNorth = None if abs(a) < 1e-12 else f.createIfcDirection((round(-math.sin(a), 12), round(math.cos(a), 12)))
            if old is not None and f.get_total_inverses(old) == 0:
                f.remove(old)
        return 1

    return B._dump(B._run(action))


def get_true_north() -> str:
    from . import app_bridge as B

    return B._dump({"ok": True, "degrees": true_north_angle(), "direction": list(true_north())})


# ---------------------------------------------------------------- plan drawings

def drawing_parts(storey, to_paper, metres_per_mm, settings: dict | None = None) -> list:
    """SVG (paper mm) of the level's tags, north arrows, scale bars, clouds and dimensions, each a
    group graphics.style_svg styles like an annotation (data-pen: its pen)."""
    from . import annotations as N
    from . import drawgen as G

    z = G.storey_elevation(storey)
    north = true_north(storey.file)
    out = []
    for a in N.on_level(storey.GlobalId):
        data = N._read(a)
        if data is None or data[0] not in KINDS:
            continue
        kind, text, _local, size, pen = data
        geom = geometry(kind, N.world_points(a), text, size, N.extra_of(a, effective=True), metres_per_mm, north)
        attrs = f' data-pen="{int(pen)}"' if pen else ""
        out.append(f'<g data-kind="annotation" data-symbol="{kind}" ifc:guid="{a.GlobalId}"{attrs}>')
        out += svg_parts(geom, lambda p: to_paper(p[0], p[1], z))
        out.append("</g>")
    return out


def level_markers(f, drawing, s, svg: str, to_paper) -> list:
    """Section and elevation drawings: each level's line and its elevation at the drawing's right edge
    (Archicad's story levels), in paper mm."""
    import re

    from . import authoring as A
    from . import drawgen as G

    m = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', svg)
    if m is None or len(s.get("points") or []) != 2:
        return []
    vx, vw = float(m.group(1)), float(m.group(3))
    x0, y0 = s["points"][0]
    right = vx + vw - 2.0
    out = []
    for storey in f.by_type("IfcBuildingStorey"):
        if A._is_model(storey):
            continue
        z = G.storey_elevation(storey)
        _px, py = to_paper(x0, y0, z)
        left = right - 22.0
        out.append(f'<path d="M{left:.3f},{py:.3f} L{right:.3f},{py:.3f}" stroke-dasharray="2 1"/>')
        out.append(f'<path d="M{right - 1.5:.3f},{py - 2.0:.3f} L{right:.3f},{py:.3f} L{right + 1.5:.3f},{py - 2.0:.3f} Z"/>')
        out.append(f'<text x="{right:.3f}" y="{py - 3.0:.3f}" font-size="2.000" text-anchor="end" '
                   f'dominant-baseline="auto">{_xml((storey.Name or "") + " " + elevation_text(z))}</text>')
    return out
