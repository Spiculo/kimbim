# SPDX-License-Identifier: GPL-3.0-or-later
"""Drawing generation (M4, D60): plans, sections and elevations from IfcOpenShell's SVG serializer.

A drawing is an IfcAnnotation with ObjectType DRAWING, as in Bonsai: its placement is the camera
(it looks along its local -Z, X is the drawing's right, Y is up) and its Body is an IfcBlock giving
width x height x depth. KIMCAD keeps the marker it was drawn from in the property set
KIMCAD_Drawing, so infinite ranges (D61, Archicad's default) can follow the model.

This module needs only ifcopenshell and numpy, so it also runs on its own in a child process:
the serializer holds the GIL for its whole hidden-line pass (spike S6), which would freeze the app.

    python drawgen.py SNAPSHOT.ifc DRAWING_GUID [INCLUDE.json]

prints {"ok": true, "svg": ..., "timing": {...}} (or {"ok": false, "error": ...}) as JSON on stdout.
"""
from __future__ import annotations

import json
import math
import multiprocessing
import re
import sys
import time

import ifcopenshell
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import ifcopenshell.util.unit
import numpy as np

W = ifcopenshell.ifcopenshell_wrapper
PSET = "KIMCAD_Drawing"
KINDS = ("section", "elevation")
TARGET_VIEW = {"section": "SECTION_VIEW", "elevation": "ELEVATION_VIEW"}
SCALE = 100  # 1:100 until drawings get a scale setting
MARGIN = 1.0  # metres added around the model for infinite ranges
EMPTY_BOUNDS = (np.array([0.0, 0.0, 0.0]), np.array([10.0, 10.0, 3.0]))  # a new project has no elements yet
NOT_DRAWN = ("IfcOpeningElement", "IfcSpace", "IfcAnnotation", "IfcGrid", "IfcVirtualElement")


def is_drawing(e) -> bool:
    return e.is_a("IfcAnnotation") and e.ObjectType == "DRAWING"


def drawn_products(f):
    """The elements a drawing can show: those with a shape, minus voids, rooms and annotations."""
    return [p for p in f.by_type("IfcProduct")
            if p.Representation is not None and not any(p.is_a(c) for c in NOT_DRAWN)]


def model_bounds(f):
    """World bounding box of the drawn elements in metres, from their placements and the points of
    their axis/footprint representations. Cheap (no tessellation); good enough for infinite ranges,
    which add a margin and get cropped to their content anyway."""
    unit = ifcopenshell.util.unit.calculate_unit_scale(f)
    points = []
    for p in drawn_products(f):
        if p.ObjectPlacement is None:
            continue
        m = ifcopenshell.util.placement.get_local_placement(p.ObjectPlacement)
        points.append(m[:3, 3] * unit)
        for rep in p.Representation.Representations:
            if rep.RepresentationIdentifier not in ("Axis", "FootPrint"):
                continue
            for item in rep.Items:
                for pt in _item_points(item):
                    local = np.array([*pt, 0.0][:3] + [1.0]) if len(pt) < 3 else np.array([*pt, 1.0])
                    points.append((m @ local)[:3] * unit)
    if not points:
        return EMPTY_BOUNDS
    points = np.array(points)
    lo, hi = points.min(axis=0), points.max(axis=0)
    hi[2] = max(hi[2], lo[2] + 3.0)  # placements sit at the bottom of elements: allow one storey up
    return lo, hi


def _item_points(item):
    if item.is_a("IfcPolyline"):
        return [tuple(float(c) for c in p.Coordinates) for p in item.Points]
    if item.is_a("IfcIndexedPolyCurve"):
        return [tuple(float(c) for c in p) for p in item.Points.CoordList]
    return []


def camera(points, look, bounds, depth=None):
    """Camera matrix (metres, world) and box size (w, h, d) for a marker line p1-p2 looking towards
    `look` (a point on the side the drawing looks at). Infinite depth (None) reaches past the model."""
    (x1, y1), (x2, y2) = points
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-6:
        raise ValueError("the marker line needs two different points")
    nx, ny = -dy / length, dx / length
    if (look[0] - x1) * nx + (look[1] - y1) * ny < 0:
        nx, ny = -nx, -ny  # the normal points to the side looked at
    lo, hi = bounds
    z0, z1 = lo[2] - MARGIN, hi[2] + MARGIN
    if depth is None:
        corners = [(x, y) for x in (lo[0], hi[0]) for y in (lo[1], hi[1])]
        depth = max(0.0, *((cx - x1) * nx + (cy - y1) * ny for cx, cy in corners)) + MARGIN
    depth = max(float(depth), 0.01)  # zero depth: the cut only
    z = np.array([-nx, -ny, 0.0])  # the camera looks along -z
    y = np.array([0.0, 0.0, 1.0])
    x = np.cross(y, z)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2] = x, y, z
    m[:3, 3] = [(x1 + x2) / 2, (y1 + y2) / 2, (z0 + z1) / 2]
    return m, (length, z1 - z0, depth)


def settings_of(drawing) -> dict | None:
    data = ifcopenshell.util.element.get_pset(drawing, PSET) or {}
    if data.get("Kind") not in KINDS:
        return None
    try:
        points = json.loads(data.get("Points") or "[]")
        look = json.loads(data.get("Look") or "[]")
    except ValueError:
        return None
    depth = data.get("Depth")
    return {"kind": data["Kind"], "points": points, "look": look,
            "depth": None if depth is None or depth < 0 else float(depth), "auto": bool(data.get("Auto")),
            "side": data.get("Side") or ""}


def auto_marker(side: str, bounds):
    """Points and look point of a template elevation marker (D61) outside the model's bounds.
    `side` is where the viewer stands: north looks south, and so on."""
    lo, hi = bounds
    gap = 3.0
    if side == "north":
        return [[hi[0] + gap, hi[1] + gap], [lo[0] - gap, hi[1] + gap]], [(lo[0] + hi[0]) / 2, lo[1]]
    if side == "south":
        return [[lo[0] - gap, lo[1] - gap], [hi[0] + gap, lo[1] - gap]], [(lo[0] + hi[0]) / 2, hi[1]]
    if side == "east":
        return [[hi[0] + gap, lo[1] - gap], [hi[0] + gap, hi[1] + gap]], [lo[0], (lo[1] + hi[1]) / 2]
    return [[lo[0] - gap, hi[1] + gap], [lo[0] - gap, lo[1] - gap]], [hi[0], (lo[1] + hi[1]) / 2]  # west


def _body_context(f):
    context = ifcopenshell.util.representation.get_context(f, "Model", "Body", "MODEL_VIEW")
    if context is None:
        model = ifcopenshell.util.representation.get_context(f, "Model") or \
            ifcopenshell.api.context.add_context(f, context_type="Model")
        context = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body",
                                                       target_view="MODEL_VIEW", parent=model)
    return context


def place(f, drawing, s, bounds):
    """Write the camera placement and box of `drawing` from its marker settings `s`."""
    unit = ifcopenshell.util.unit.calculate_unit_scale(f)
    if s["auto"] and s.get("side"):
        s["points"], s["look"] = auto_marker(s["side"], bounds)
    m, (w, h, d) = camera(s["points"], s["look"], bounds, s["depth"])
    ifcopenshell.api.geometry.edit_object_placement(f, product=drawing, matrix=m, is_si=True)
    w, h, d = (v / unit for v in (w, h, d))
    block = f.createIfcBlock(f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((-w / 2, -h / 2, -d))), w, h, d)
    rep = f.createIfcShapeRepresentation(_body_context(f), "Body", "CSG", [f.createIfcCsgSolid(block)])
    for old in list(drawing.Representation.Representations) if drawing.Representation else []:
        ifcopenshell.api.geometry.unassign_representation(f, product=drawing, representation=old)
        ifcopenshell.api.geometry.remove_representation(f, representation=old)
    ifcopenshell.api.geometry.assign_representation(f, product=drawing, representation=rep)


def write_settings(f, drawing, s):
    pset = ifcopenshell.util.element.get_pset(drawing, PSET)
    pset = f.by_id(pset["id"]) if pset else ifcopenshell.api.pset.add_pset(f, product=drawing, name=PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
        "Kind": s["kind"], "Points": json.dumps([[round(x, 6), round(y, 6)] for x, y in s["points"]]),
        "Look": json.dumps([round(s["look"][0], 6), round(s["look"][1], 6)]),
        "Depth": -1.0 if s["depth"] is None else float(s["depth"]), "Auto": bool(s["auto"]),
        **({"Side": s["side"]} if s.get("side") else {})})
    epset = ifcopenshell.util.element.get_pset(drawing, "EPset_Drawing")
    epset = f.by_id(epset["id"]) if epset else ifcopenshell.api.pset.add_pset(f, product=drawing, name="EPset_Drawing")
    ifcopenshell.api.pset.edit_pset(f, pset=epset, properties={
        "TargetView": TARGET_VIEW[s["kind"]], "Scale": f"1/{SCALE}", "HumanScale": f"1:{SCALE}"})


_NUMBER_PAIR = re.compile(r"(-?\d+(?:\.\d+)?(?:e-?\d+)?),(-?\d+(?:\.\d+)?(?:e-?\d+)?)")


def crop(svg: str, margin: float = 5.0) -> str:
    """Tighten the SVG's viewBox (paper mm) to what was drawn: infinite ranges reach past the model."""
    xs, ys = [], []
    for d in re.findall(r'\sd="([^"]*)"', svg):
        for a, b in _NUMBER_PAIR.findall(d):
            xs.append(float(a))
            ys.append(float(b))
    if not xs:
        return svg
    x0, y0, x1, y1 = min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin
    w, h = x1 - x0, y1 - y0
    return re.sub(r'<svg([^>]*?) width="[^"]*" height="[^"]*" viewBox="[^"]*"',
                  f'<svg\\1 width="{w:.2f}mm" height="{h:.2f}mm" viewBox="{x0:.3f} {y0:.3f} {w:.3f} {h:.3f}"',
                  svg, count=1)


def generate(f, drawing, include=None) -> tuple[str, dict]:
    """SVG of `drawing` (paper millimetres). `f` may be changed (a snapshot): infinite ranges and
    template elevations are re-fitted to the model first. `include`: GlobalIds of the elements to
    draw (the visible ones); default all drawn elements."""
    t0 = time.perf_counter()
    s = settings_of(drawing)
    if s is not None:
        if s["auto"] or s["depth"] is None:
            place(f, drawing, s, model_bounds(f))
    products = drawn_products(f)
    if include is not None:
        wanted = set(include)
        products = [p for p in products if p.GlobalId in wanted]
    gs = ifcopenshell.geom.settings(ELEMENT_HIERARCHY=True)
    for key, value in (("dimensionality", W.CURVES_SURFACES_AND_SOLIDS), ("iterator-output", W.NATIVE),
                       ("apply-default-materials", True), ("elevation-ref-guid", drawing.GlobalId),
                       ("svg-without-storeys", True), ("svg-write-poly", True), ("svg-xmlns", True),
                       ("svg-project", True), ("bounds", "1189x841"), ("scale", str(1 / SCALE)),
                       ("door-arcs", True), ("svg-poly", True), ("svg-prefilter", True), ("svg-unify-inputs", False)):
        gs.set(key, value)
    buffer = W.buffer()
    serializer = ifcopenshell.geom.serializers.svg(buffer, gs)
    serializer.setFile(f)
    t1 = time.perf_counter()
    it = ifcopenshell.geom.iterator(gs, f, multiprocessing.cpu_count(), include=products + [drawing])
    count = 0
    if it.initialize():
        while True:
            serializer.write(it.get())
            count += 1
            if not it.next():
                break
    t2 = time.perf_counter()
    serializer.finalize()
    t3 = time.perf_counter()
    svg = crop(buffer.get_value())
    return svg, {"elements": count, "prepare_s": round(t1 - t0, 3), "geometry_s": round(t2 - t1, 3),
                 "hlr_s": round(t3 - t2, 3), "total_s": round(time.perf_counter() - t0, 3)}


def main(argv) -> int:
    try:
        f = ifcopenshell.open(argv[1])
        drawing = f.by_guid(argv[2])
        include = None
        if len(argv) > 3:
            with open(argv[3], encoding="utf-8") as fh:
                include = json.load(fh)
        svg, timing = generate(f, drawing, include)
        out = {"ok": True, "svg": svg, "timing": timing}
    except Exception as ex:  # report, never a traceback on the app's console
        out = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
    sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
