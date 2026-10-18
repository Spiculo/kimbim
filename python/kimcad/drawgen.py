# SPDX-License-Identifier: GPL-3.0-or-later
"""Drawing generation (M4, D60): plans, sections and elevations from IfcOpenShell's SVG serializer.

A drawing is an IfcAnnotation with ObjectType DRAWING, as in Bonsai: its placement is the camera
(it looks along its local -Z, X is the drawing's right, Y is up) and its Body is an IfcBlock giving
width x height x depth. The marker line in plan is the camera's X axis over the block's width, so
moving or rotating the annotation moves the drawing. KIMCAD_Drawing keeps the rest (kind, depth,
template elevation side), so infinite ranges (D61, Archicad's default) can follow the model.

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
import threading
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
KINDS = ("section", "elevation", "plan")
TARGET_VIEW = {"section": "SECTION_VIEW", "elevation": "ELEVATION_VIEW", "plan": "PLAN_VIEW"}
PLAN_CUT = 1.10  # metres above the story: Archicad's default floor plan cut plane
TEXT_SIZE = 2.5  # millimetres on paper, the default for annotation text
ANNOTATION_PSET = "KIMCAD_Annotation"
SCALE = 100  # 1:100 until drawings get a scale setting
MARGIN = 1.0  # metres added around the model for infinite ranges
EMPTY_BOUNDS = (np.array([0.0, 0.0, 0.0]), np.array([10.0, 10.0, 3.0]))  # a new project has no elements yet
NOT_DRAWN = ("IfcOpeningElement", "IfcSpace", "IfcAnnotation", "IfcGrid", "IfcVirtualElement")


def _svg_overrides() -> dict:
    """Serializer settings from the KIMCAD_SVG_OPTS environment (a JSON object), for tuning the
    hidden-line pass without a code change (e.g. {"svg-poly": false}). Empty when unset."""
    import os

    raw = os.environ.get("KIMCAD_SVG_OPTS")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def is_drawing(e) -> bool:
    return e.is_a("IfcAnnotation") and e.ObjectType == "DRAWING"


def drawn_products(f):
    """The elements a drawing can show: those with a shape, minus voids, rooms and annotations."""
    return [p for p in f.by_type("IfcProduct")
            if p.Representation is not None and not any(p.is_a(c) for c in NOT_DRAWN)]


def placement_cache():
    """get_local_placement with memory: the same matrices (same operations, in the same order),
    each placement and axis placement worked out once. Exporters share them (Revit: one axis
    placement for all), so a whole model costs a fraction (Clinic: 6 s -> well under 1 s)."""
    axes, worlds = {}, {}

    def axis(a):
        m = axes.get(a.id())
        if m is None:
            m = axes[a.id()] = ifcopenshell.util.placement.get_axis2placement(a)
        return m

    def world(placement):
        if placement is None:
            return np.eye(4)
        if not placement.is_a("IfcLocalPlacement"):
            return ifcopenshell.util.placement.get_local_placement(placement)
        m = worlds.get(placement.id())
        if m is None:
            parent = np.eye(4) if placement.PlacementRelTo is None else world(placement.PlacementRelTo)
            m = worlds[placement.id()] = np.dot(parent, axis(placement.RelativePlacement))
        return m

    return world


def building_products(f):
    """The drawn products inside the building (its storeys and the building itself), not the whole
    site. An imported model is georeferenced across the whole plot (terrain, roads, utilities), so the
    site's extent would make every drawing frame the plot instead of the building."""
    products = drawn_products(f)
    containers = {s.id() for s in f.by_type("IfcBuildingStorey")}
    containers |= {b.id() for b in f.by_type("IfcBuilding")}
    if not containers:
        return products
    contained = set()
    for rel in f.by_type("IfcRelContainedInSpatialStructure"):
        structure = rel.RelatingStructure
        if structure is not None and structure.id() in containers:
            for e in rel.RelatedElements:
                contained.add(e.id())
    inside = [p for p in products if p.id() in contained]
    return inside or products  # a model without containment falls back to every drawn element


def model_bounds(f):
    """World bounding box of the building's drawn elements in metres, from their placements and the
    points of their axis/footprint representations. Cheap (no tessellation); good enough for infinite
    ranges, which add a margin and get cropped to their content anyway."""
    unit = ifcopenshell.util.unit.calculate_unit_scale(f)
    points = []
    world = placement_cache()
    for p in building_products(f):
        if p.ObjectPlacement is None:
            continue
        m = world(p.ObjectPlacement)
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
    if len(points) >= 20:
        # A georeferenced model has a few far-flung elements (site furniture, markers): the 1st/99th
        # percentile ignores them so the drawing frames the building, not a stray element.
        lo, hi = np.percentile(points, 1, axis=0), np.percentile(points, 99, axis=0)
    else:
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


def marker(drawing):
    """The marker line (two world points, metres) and a point on the side looked at, from the
    camera placement and box; None without them."""
    block = _block(drawing)
    if block is None or drawing.ObjectPlacement is None:
        return None
    unit = ifcopenshell.util.unit.calculate_unit_scale(drawing.file)
    m = ifcopenshell.util.placement.get_local_placement(drawing.ObjectPlacement)
    o, x, z = m[:2, 3] * unit, m[:2, 0], m[:2, 2]
    half = float(block.XLength) * unit / 2
    p1, p2, look = o - x * half, o + x * half, o - z
    return [[round(float(c), 6) for c in p] for p in (p1, p2)], [round(float(c), 6) for c in look]


def _block(drawing):
    for rep in drawing.Representation.Representations if drawing.Representation else ():
        for item in rep.Items:
            if item.is_a("IfcCsgSolid") and item.TreeRootExpression.is_a("IfcBlock"):
                return item.TreeRootExpression
    return None


def settings_of(drawing) -> dict | None:
    data = ifcopenshell.util.element.get_pset(drawing, PSET) or {}
    if data.get("Kind") not in KINDS:
        return None
    if data["Kind"] == "plan":
        return {"kind": "plan", "points": [], "look": [], "depth": None, "auto": True, "side": "",
                "storey": data.get("Storey") or "", "cut": float(data.get("Cut") or PLAN_CUT)}
    points, look = marker(drawing) or ([], [])
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


def storey_elevation(storey) -> float:
    """A story's elevation in metres, from its placement (what geometry uses)."""
    unit = ifcopenshell.util.unit.calculate_unit_scale(storey.file)
    if storey.ObjectPlacement is not None:
        return float(ifcopenshell.util.placement.get_local_placement(storey.ObjectPlacement)[2][3]) * unit
    return float(storey.Elevation or 0.0) * unit


def plan_camera(storey, cut, bounds):
    """A floor plan (Archicad): looking down from the cut plane, `cut` metres above the story, to just
    below its floor, over the whole model's extent."""
    lo, hi = bounds
    z = storey_elevation(storey)
    m = np.eye(4)
    m[:3, 3] = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, z + cut]
    return m, (hi[0] - lo[0] + 2 * MARGIN, hi[1] - lo[1] + 2 * MARGIN, cut + 0.3)


def _storey(drawing, s):
    try:
        return drawing.file.by_guid(s["storey"]) if s.get("storey") else None
    except RuntimeError:
        return None


def place(f, drawing, s, bounds):
    """Write the camera placement and box of `drawing` from its marker settings `s`."""
    unit = ifcopenshell.util.unit.calculate_unit_scale(f)
    if s["auto"] and s.get("side"):
        s["points"], s["look"] = auto_marker(s["side"], bounds)
    if s["kind"] == "plan":
        storey = _storey(drawing, s)
        if storey is None:
            raise ValueError("the drawing's story no longer exists")
        m, (w, h, d) = plan_camera(storey, s["cut"], bounds)
    else:
        m, (w, h, d) = camera(s["points"], s["look"], bounds, s["depth"])
    ifcopenshell.api.geometry.edit_object_placement(f, product=drawing, matrix=m, is_si=True)
    w, h, d = (v / unit for v in (w, h, d))
    block = f.createIfcBlock(f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((-w / 2, -h / 2, -d))), w, h, d)
    rep = f.createIfcShapeRepresentation(_body_context(f), "Body", "CSG", [f.createIfcCsgSolid(block)])
    for old in list(drawing.Representation.Representations) if drawing.Representation else []:
        ifcopenshell.api.geometry.unassign_representation(f, product=drawing, representation=old)
        ifcopenshell.api.geometry.remove_representation(f, representation=old)
    ifcopenshell.api.geometry.assign_representation(f, product=drawing, representation=rep)


def release(f, drawing):
    """A template elevation the user moved stays where it was put (no longer follows the model)."""
    pset = ifcopenshell.util.element.get_pset(drawing, PSET)
    if pset and pset.get("Auto"):
        ifcopenshell.api.pset.edit_pset(f, pset=f.by_id(pset["id"]), properties={"Auto": False})


def write_settings(f, drawing, s):
    pset = ifcopenshell.util.element.get_pset(drawing, PSET)
    pset = f.by_id(pset["id"]) if pset else ifcopenshell.api.pset.add_pset(f, product=drawing, name=PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
        "Kind": s["kind"], "Depth": -1.0 if s["depth"] is None else float(s["depth"]), "Auto": bool(s["auto"]),
        **({"Side": s["side"]} if s.get("side") else {}),
        **({"Storey": s["storey"], "Cut": float(s["cut"])} if s["kind"] == "plan" else {})})
    epset = ifcopenshell.util.element.get_pset(drawing, "EPset_Drawing")
    epset = f.by_id(epset["id"]) if epset else ifcopenshell.api.pset.add_pset(f, product=drawing, name="EPset_Drawing")
    ifcopenshell.api.pset.edit_pset(f, pset=epset, properties={
        "TargetView": TARGET_VIEW[s["kind"]], "Scale": f"1/{SCALE}", "HumanScale": f"1:{SCALE}"})


# ---------------------------------------------------------------- overlay (Slice 15)
# What the serializer does not draw, drawn by KIMCAD on top, in paper millimetres: door swings and
# window glass lines in plans, plan annotations (text, dimension chains, marks, leaders), and the
# section and elevation markers in plans.

def paper_mapping(svg: str):
    """World metres -> paper millimetres for the drawing in `svg`, from the serializer's drawing
    group: ifc:plane (the drawing plane, local -> world) and ifc:matrix3 (plane 2D -> paper); the
    plane's 2D coordinates are (x, -y). None if the SVG has no drawing group."""
    m = re.search(r'class="section"[^>]*?ifc:plane="([^"]+)"[^>]*?ifc:matrix3="([^"]+)"', svg)
    if m is None:
        return None
    plane = np.array(json.loads(m.group(1)), dtype=float)
    m3 = np.array(json.loads(m.group(2)), dtype=float)
    inverse = np.linalg.inv(plane)
    unit_to_m = 1.0  # the serializer works in metres (setUnitNameAndMagnitude default)

    def to_paper(x, y, z=0.0):
        local = inverse @ np.array([x * unit_to_m, y * unit_to_m, z, 1.0])
        p = m3 @ np.array([local[0], -local[1], 1.0])
        return float(p[0]), float(p[1])

    return to_paper


def _f(v: float) -> str:
    return f"{v:.3f}"


def _path(points, closed=False) -> str:
    d = "M" + " L".join(f"{_f(x)},{_f(y)}" for x, y in points) + (" Z" if closed else "")
    return f'<path d="{d}"/>'


def _text(x, y, value, size, anchor="middle", angle=0.0, baseline="auto") -> str:
    value = (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    rotate = f' transform="rotate({_f(angle)} {_f(x)} {_f(y)})"' if abs(angle) > 1e-6 else ""
    return (f'<text x="{_f(x)}" y="{_f(y)}" font-size="{_f(size)}" text-anchor="{anchor}" '
            f'dominant-baseline="{baseline}"{rotate}>{value}</text>')


def _readable(angle: float) -> float:
    """Text along a line keeps reading left to right or bottom to top."""
    while angle > 90:
        angle -= 180
    while angle <= -90:
        angle += 180
    return angle


def _wall_thickness(element) -> float:
    """Thickness (metres) of the wall hosting a door/window, from its layer set; 0 if unknown."""
    unit = ifcopenshell.util.unit.calculate_unit_scale(element.file)
    for fill in getattr(element, "FillsVoids", ()) or ():
        for void in getattr(fill.RelatingOpeningElement, "VoidsElements", ()) or ():
            usage = ifcopenshell.util.element.get_material(void.RelatingBuildingElement)
            layers = getattr(getattr(usage, "ForLayerSet", None), "MaterialLayers", None) or \
                getattr(usage, "MaterialLayers", None) or ()
            total = sum(float(layer.LayerThickness or 0.0) for layer in layers)
            if total:
                return total * unit
    return 0.0


def _operation(door) -> str:
    op = getattr(door, "OperationType", None)
    if not op or op == "NOTDEFINED":
        door_type = ifcopenshell.util.element.get_type(door)
        op = getattr(door_type, "OperationType", None) or getattr(door_type, "OperationType", None)
    return op or "SINGLE_SWING_LEFT"


def door_swings(door, to_paper):
    """Plan symbol of a door: each leaf drawn open at 90 degrees with its swing arc, into the side
    the door's local +Y points to (KIMCAD places doors on the wall's outer face, +Y into the wall)."""
    unit = ifcopenshell.util.unit.calculate_unit_scale(door.file)
    m = ifcopenshell.util.placement.get_local_placement(door.ObjectPlacement)
    width = float(door.OverallWidth or 0.0) * unit
    if width <= 0:
        return []
    t = _wall_thickness(door)
    o, x, y = m[:3, 3] * unit, m[:3, 0], m[:3, 1]
    z = o[2]

    def world(lx, ly):
        p = o + x * lx + y * ly
        return to_paper(p[0], p[1], z)

    op = _operation(door)
    if op.startswith("DOUBLE_DOOR"):
        leaves = [(0.0, width / 2, 1), (width, width / 2, -1)]
    elif op.endswith("RIGHT"):
        leaves = [(width, width, -1)]
    else:
        leaves = [(0.0, width, 1)]
    out = []
    for hinge_x, leaf, direction in leaves:
        hinge = world(hinge_x, t)
        closed = world(hinge_x + direction * leaf, t)
        opened = world(hinge_x, t + leaf)
        out.append(_path([hinge, opened]))
        r = math.dist(hinge, opened)
        cross = (closed[0] - hinge[0]) * (opened[1] - hinge[1]) - (closed[1] - hinge[1]) * (opened[0] - hinge[0])
        sweep = 1 if cross > 0 else 0
        out.append(f'<path class="swing" d="M{_f(closed[0])},{_f(closed[1])} A{_f(r)},{_f(r)} 0 0 {sweep} '
                   f'{_f(opened[0])},{_f(opened[1])}"/>')
    return out


def window_symbol(window, to_paper):
    """Plan symbol of a window: the glass as a double line across the middle of the wall."""
    unit = ifcopenshell.util.unit.calculate_unit_scale(window.file)
    m = ifcopenshell.util.placement.get_local_placement(window.ObjectPlacement)
    width = float(window.OverallWidth or 0.0) * unit
    t = _wall_thickness(window)
    if width <= 0 or t <= 0:
        return []
    o, x, y = m[:3, 3] * unit, m[:3, 0], m[:3, 1]
    out = []
    for ly in (t / 2 - 0.02, t / 2 + 0.02):
        a, b = o + y * ly, o + x * width + y * ly
        out.append(_path([to_paper(a[0], a[1], o[2]), to_paper(b[0], b[1], o[2])]))
    return out


def plan_annotations(storey, to_paper, size_default=TEXT_SIZE):
    """The story's plan annotations (KIMCAD_Annotation): text, dimension chains, marks, leaders."""
    f = storey.file
    unit = ifcopenshell.util.unit.calculate_unit_scale(f)
    out = []
    for a in f.by_type("IfcAnnotation"):
        if a.ObjectPlacement is None or ifcopenshell.util.element.get_container(a) != storey:
            continue
        data = ifcopenshell.util.element.get_pset(a, ANNOTATION_PSET) or {}
        kind = data.get("Kind")
        if kind not in ("text", "mark", "leader", "dimension"):
            continue  # drafting shapes (D84) are added by drafting.add_to_drawing
        try:
            local = json.loads(data.get("Points") or "[]")
        except ValueError:
            continue
        if not local:
            continue
        m = ifcopenshell.util.placement.get_local_placement(a.ObjectPlacement)
        size = float(data.get("Size") or size_default)
        text = data.get("Text") or ""
        pen = data.get("Pen")
        pen_attr = f' data-pen="{int(pen)}"' if isinstance(pen, int) and not isinstance(pen, bool) else ""
        out.append(f'<g data-kind="annotation" ifc:guid="{a.GlobalId}"{pen_attr}>')
        pts = []
        for lx, ly in local:
            w = m @ np.array([lx / unit, ly / unit, 0.0, 1.0]) * unit
            pts.append(to_paper(w[0], w[1], w[2]))
        if kind == "text":
            out.append(_text(pts[0][0], pts[0][1], text, size, anchor="start"))
        elif kind == "mark":
            (cx, cy), r = pts[0], 0.4 * 1000 / SCALE
            out.append(f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}" fill="none"/>')
            out.append(_text(cx, cy, text, size, baseline="central"))
        elif kind == "leader" and len(pts) >= 2:
            out.append(_path(pts))
            (ax, ay), (bx, by) = pts[0], pts[1]
            ang = math.atan2(ay - by, ax - bx)
            head = 1.5
            out.append(_path([(ax - head * math.cos(ang - 0.35), ay - head * math.sin(ang - 0.35)), (ax, ay),
                              (ax - head * math.cos(ang + 0.35), ay - head * math.sin(ang + 0.35))]))
            end = pts[-1]
            out.append(_text(end[0] + 1.0, end[1], text, size, anchor="start", baseline="central"))
        elif kind == "dimension" and len(pts) >= 3:
            out += dimension_chain(pts[:-1], pts[-1], segment_labels(text, len(pts) - 2), size)
        out.append("</g>")
    return out


def _space_outline(space):
    """A room's outline in world metres from its extruded body, or []."""
    unit = ifcopenshell.util.unit.calculate_unit_scale(space.file)
    body = ifcopenshell.util.representation.get_representation(space, "Model", "Body", "MODEL_VIEW")
    solid = next((i for i in (body.Items if body else ()) if i.is_a("IfcExtrudedAreaSolid")), None)
    if solid is None or not solid.SweptArea.is_a("IfcArbitraryClosedProfileDef"):
        return []
    curve = solid.SweptArea.OuterCurve
    if curve.is_a("IfcPolyline"):
        pts = [p.Coordinates[:2] for p in curve.Points]
    elif curve.is_a("IfcIndexedPolyCurve"):
        pts = [p[:2] for p in curve.Points.CoordList]
    else:
        return []
    if len(pts) > 1 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    m = ifcopenshell.util.placement.get_local_placement(space.ObjectPlacement)
    if solid.Position is not None:
        m = m @ ifcopenshell.util.placement.get_axis2placement(solid.Position)
    return [tuple((m @ np.array([x, y, 0.0, 1.0]))[:3] * unit) for x, y in pts]


def _inside_2d(p, polygon) -> bool:
    inside = False
    n = len(polygon)
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
            inside = not inside
    return inside


def room_stamps(storey, to_paper, size=TEXT_SIZE):
    """Archicad's zone stamp for each room on the story: name, number and area at its reference point."""
    out = []
    for space in storey.file.by_type("IfcSpace"):
        if ifcopenshell.util.element.get_aggregate(space) != storey or space.ObjectPlacement is None:
            continue
        pts = _space_outline(space)
        if len(pts) < 3:
            continue
        xy = np.array([p[:2] for p in pts])
        x, y = np.roll(xy[:, 0], -1), np.roll(xy[:, 1], -1)
        cross = xy[:, 0] * y - x * xy[:, 1]
        area = cross.sum() / 2
        if abs(area) < 1e-9:
            continue
        cx = ((xy[:, 0] + x) * cross).sum() / (6 * area)
        cy = ((xy[:, 1] + y) * cross).sum() / (6 * area)
        qto = ifcopenshell.util.element.get_pset(space, "Qto_SpaceBaseQuantities") or {}
        value = float(qto.get("NetFloorArea") or abs(area))
        seed = ifcopenshell.util.element.get_pset(space, "KIMCAD_Room") or {}
        if "SeedX" in seed and _inside_2d((float(seed["SeedX"]), float(seed["SeedY"])), xy):
            cx, cy = float(seed["SeedX"]), float(seed["SeedY"])  # where it was clicked (Archicad's reference point)
        px, py = to_paper(cx, cy, pts[0][2])
        out.append(_text(px, py - 1.6 * size, space.LongName or "", size * 1.2, baseline="central"))
        out.append(_text(px, py, space.Name or "", size, baseline="central"))
        out.append(_text(px, py + 1.6 * size, f"{value:.2f} m²", size, baseline="central"))
    return out


def segment_labels(text: str, segments: int) -> list:
    """One label per dimension segment. A single segment shows its whole text ("2.50 m"); a chain's labels
    are separated by ";" ("a eje A; 3,50": the comma is a decimal separator in Spanish), or by spaces as
    measured ("4.00 3.50", older files)."""
    if segments <= 1:
        labels = [text.strip()]
    elif ";" in text:
        labels = [t.strip() for t in text.split(";")]
    else:
        labels = text.split()
    return (labels + [""] * segments)[:segments]


def dimension_chain(points, through, texts, size):
    """A chain of linear dimensions (paper mm): extension lines from each measured point to the
    dimension line (parallel to first-last, through `through`), ticks, one text per segment."""
    (ax, ay), (bx, by) = points[0], points[-1]
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return []
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    off = (through[0] - ax) * nx + (through[1] - ay) * ny
    on_line = [(px + nx * (off - ((px - ax) * nx + (py - ay) * ny)), py + ny * (off - ((px - ax) * nx + (py - ay) * ny)))
               for px, py in points]
    out = [_path([p, q]) for p, q in zip(points, on_line)]
    out.append(_path([on_line[0], on_line[-1]]))
    tick = 1.0
    for px, py in on_line:
        out.append(_path([(px - (ux + nx) * tick, py - (uy + ny) * tick), (px + (ux + nx) * tick, py + (uy + ny) * tick)]))
    angle = _readable(math.degrees(math.atan2(uy, ux)))
    side = 1 if off >= 0 else -1  # the text sits on the far side of the line from what it measures
    for i, (p, q) in enumerate(zip(on_line, on_line[1:])):
        label = texts[i] if i < len(texts) else ""
        mx, my = (p[0] + q[0]) / 2 + nx * side * size * 0.6, (p[1] + q[1]) / 2 + ny * side * size * 0.6
        out.append(_text(mx, my, label, size, angle=angle, baseline="central"))
    return out


def markers(f, to_paper, z):
    """Section and elevation markers in a plan drawing (Archicad style, as in the 3D view's plan)."""
    out = []
    for d in f.by_type("IfcAnnotation"):
        if not is_drawing(d):
            continue
        s = settings_of(d)
        if s is None or s["kind"] == "plan" or len(s["points"]) != 2:
            continue
        (x1, y1), (x2, y2) = s["points"]
        look = s["look"]
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 1e-9:
            continue
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        nx, ny = -uy, ux
        if (look[0] - x1) * nx + (look[1] - y1) * ny < 0:
            nx, ny = -nx, -ny
        P = lambda x, y: to_paper(x, y, z)  # noqa: E731
        if s["kind"] == "section":
            out.append(_path([P(x1, y1), P(x2, y2)]))
            for ex, ey in ((x1, y1), (x2, y2)):
                tx, ty = ex + nx * 0.8, ey + ny * 0.8
                out.append(_path([P(ex, ey), P(tx, ty)]))
                out.append(_path([P(tx - nx * 0.25 + ux * 0.15, ty - ny * 0.25 + uy * 0.15), P(tx, ty),
                                  P(tx - nx * 0.25 - ux * 0.15, ty - ny * 0.25 - uy * 0.15)]))
            lx, ly = P(x1 - ux * 0.6, y1 - uy * 0.6)
        else:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            out.append(_path([P(mx - ux * 0.4, my - uy * 0.4), P(mx + nx * 0.6, my + ny * 0.6),
                              P(mx + ux * 0.4, my + uy * 0.4)], closed=True))
            lx, ly = P(mx - nx * 0.6, my - ny * 0.6)
            tip = P(mx, my)
            anchor = "end" if lx < tip[0] - 1 else "start" if lx > tip[0] + 1 else "middle"
            out.append(_text(lx, ly, d.Name or "", TEXT_SIZE, anchor=anchor, baseline="central"))
            continue
        out.append(_text(lx, ly, d.Name or "", TEXT_SIZE, baseline="central"))
    return out


LIBRARY_PSET = "KIMCAD_LibraryObject"  # D86: library objects draw their plan symbol in plans


def _plan_symbol_map(t):
    """The type's plan symbol (Plan context, Annotation) representation map, or None."""
    for rep_map in getattr(t, "RepresentationMaps", None) or ():
        rep = rep_map.MappedRepresentation
        context = rep.ContextOfItems
        if rep.RepresentationIdentifier == "Annotation" and getattr(context, "ContextType", None) == "Plan":
            return rep_map
    return None


def symbol_objects(f) -> dict:
    """Library objects (D86) whose type has a plan symbol: GlobalId -> (element, representation map)."""
    out = {}
    for t in f.by_type("IfcTypeProduct"):
        if not any(getattr(ps, "Name", None) == LIBRARY_PSET for ps in (getattr(t, "HasPropertySets", None) or ())):
            continue
        rep_map = _plan_symbol_map(t)
        if rep_map is None:
            continue
        for e in ifcopenshell.util.element.get_types(t):
            if e.ObjectPlacement is not None:
                out[e.GlobalId] = (e, rep_map)
    return out


def _curves(item):
    """2D curves of a symbol item: ("poly", [(x, y)...]) or ("circle", cx, cy, r), map coordinates."""
    if item.is_a("IfcGeometricSet"):  # and IfcGeometricCurveSet
        for element in item.Elements:
            yield from _curves(element)
    elif item.is_a("IfcPolyline"):
        yield "poly", [tuple(float(c) for c in p.Coordinates[:2]) for p in item.Points]
    elif item.is_a("IfcIndexedPolyCurve"):
        pts = [tuple(float(c) for c in p[:2]) for p in item.Points.CoordList]
        yield "poly", pts
    elif item.is_a("IfcCircle"):
        loc = item.Position.Location.Coordinates
        yield "circle", float(loc[0]), float(loc[1]), float(item.Radius)
    elif item.is_a("IfcTrimmedCurve") and item.BasisCurve.is_a("IfcCircle"):
        trims = [next((t for t in trim if getattr(t, "is_a", None) and t.is_a("IfcCartesianPoint")), None)
                 for trim in (item.Trim1, item.Trim2)]
        if all(trims):
            yield "poly", [tuple(float(c) for c in t.Coordinates[:2]) for t in trims]


def object_symbols(storey, to_paper, include=None) -> list:
    """The plan symbols of the library objects on the story, one group per element (styled as its
    projection lines by graphics.style_svg)."""
    f = storey.file
    unit = ifcopenshell.util.unit.calculate_unit_scale(f)
    out = []
    for guid, (e, rep_map) in symbol_objects(f).items():
        if ifcopenshell.util.element.get_container(e) != storey or (include is not None and guid not in include):
            continue
        m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
        if rep_map.MappingOrigin is not None and rep_map.MappingOrigin.is_a("IfcAxis2Placement3D"):
            m = m @ ifcopenshell.util.placement.get_axis2placement(rep_map.MappingOrigin)
        z = m[2, 3] * unit

        def paper(x, y):
            w = m @ np.array([x, y, 0.0, 1.0])
            return to_paper(w[0] * unit, w[1] * unit, z)

        parts = []
        for item in rep_map.MappedRepresentation.Items:
            for c in _curves(item):
                if c[0] == "poly" and len(c[1]) >= 2:
                    parts.append(_path([paper(x, y) for x, y in c[1]]))
                elif c[0] == "circle":
                    cx, cy = paper(c[1], c[2])
                    ex, ey = paper(c[1] + c[3], c[2])
                    parts.append(f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(math.hypot(ex - cx, ey - cy))}" fill="none"/>')
        if parts:
            out += [f'<g class="projection" data-kind="object" ifc:guid="{guid}">', *parts, "</g>"]
    return out


def _tagged(kind: str, parts: list) -> list:
    """Overlay parts grouped by what they are, so graphics.style_svg can style them (D73)."""
    return [f'<g data-kind="{kind}">', *parts, "</g>"] if parts else []


def overlay(f, drawing, s, svg: str, include=None) -> str:
    to_paper = paper_mapping(svg)
    if to_paper is None:
        return svg
    parts = []
    if s["kind"] == "plan":
        storey = _storey(drawing, s)
        if storey is not None:
            for e in f.by_type("IfcDoor"):
                if ifcopenshell.util.element.get_container(e) == storey and e.ObjectPlacement is not None:
                    parts += _tagged("swing", door_swings(e, to_paper))
            for e in f.by_type("IfcWindow"):
                if ifcopenshell.util.element.get_container(e) == storey and e.ObjectPlacement is not None:
                    parts += _tagged("window", window_symbol(e, to_paper))
            parts += object_symbols(storey, to_paper, include)  # D86, tagged per element
            # Room stamps are drawn with the tags on every request (tags.add_to_drawing, D87): their text
            # is the room stamp tag style's, a project setting this process does not see.
            parts += plan_annotations(storey, to_paper)  # tags each annotation (guid, pen) itself
            parts += _tagged("marker", markers(f, to_paper, storey_elevation(storey)))
    if not parts:
        return svg
    group = ('<g class="kimcad-overlay" fill="none" stroke="#000000" stroke-width="0.18" '
             'font-family="sans-serif">\n' + "\n".join(parts) + "\n</g>\n")
    group = group.replace("<text ", '<text fill="#000000" stroke="none" ')
    return svg.replace("</svg>", group + "</svg>", 1)


_NUMBER_PAIR = re.compile(r"(-?\d+(?:\.\d+)?(?:e-?\d+)?),(-?\d+(?:\.\d+)?(?:e-?\d+)?)")


def crop(svg: str, margin: float = 5.0) -> str:
    """Tighten the SVG's viewBox (paper mm) to what was drawn: infinite ranges reach past the model."""
    xs, ys = [], []
    for d in re.findall(r'\sd="([^"]*)"', svg):
        for a, b in _NUMBER_PAIR.findall(d):
            xs.append(float(a))
            ys.append(float(b))
    # Overlay text and circles count too (their extent estimated from the font size or radius).
    for x, y, size, body in re.findall(r'<text [^>]*?x="([-\d.]+)" y="([-\d.]+)" font-size="([\d.]+)"[^>]*>([^<]*)<', svg):
        half = 0.3 * float(size) * max(len(body), 1)
        xs += [float(x) - half, float(x) + half]
        ys += [float(y) - float(size), float(y) + float(size)]
    for cx, cy, r in re.findall(r'<circle cx="([-\d.]+)" cy="([-\d.]+)" r="([\d.]+)"', svg):
        xs += [float(cx) - float(r), float(cx) + float(r)]
        ys += [float(cy) - float(r), float(cy) + float(r)]
    if not xs:
        return svg
    x0, y0, x1, y1 = min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin
    w, h = x1 - x0, y1 - y0
    return re.sub(r'<svg([^>]*?) width="[^"]*" height="[^"]*" viewBox="[^"]*"',
                  f'<svg\\1 width="{w:.2f}mm" height="{h:.2f}mm" viewBox="{x0:.3f} {y0:.3f} {w:.3f} {h:.3f}"',
                  svg, count=1)


def generate(f, drawing, include=None, bounds=None) -> tuple[str, dict]:
    """SVG of `drawing` (paper millimetres). `f` may be changed (a snapshot): infinite ranges and
    template elevations are re-fitted to the model first. `include`: GlobalIds of the elements to
    draw (the visible ones); default all drawn elements. `bounds`: the model's (lo, hi) in metres,
    already computed by the caller; when None it is worked out here (the child sizes a subset file,
    where the full model is not present, so the caller passes the bounds)."""
    t0 = time.perf_counter()
    s = settings_of(drawing)
    if s is not None:
        if s["auto"] or s["depth"] is None:
            place(f, drawing, s, bounds if bounds is not None else model_bounds(f))
    products = drawn_products(f)
    if s is not None and s["kind"] == "plan":
        storey = _storey(drawing, s)
        symbols = symbol_objects(f)  # D86: drawn from their plan symbol (overlay), not cut
        products = [p for p in products if ifcopenshell.util.element.get_container(p) == storey and p.GlobalId not in symbols]
    if include is not None:
        wanted = set(include)
        products = [p for p in products if p.GlobalId in wanted]
    gs = ifcopenshell.geom.settings(ELEMENT_HIERARCHY=True)
    opts = {
        "dimensionality": W.CURVES_SURFACES_AND_SOLIDS, "iterator-output": W.NATIVE,
        "apply-default-materials": True, "elevation-ref-guid": drawing.GlobalId,
        "svg-without-storeys": True, "svg-write-poly": True, "svg-xmlns": True,
        "svg-project": True, "bounds": "1189x841", "scale": str(1 / SCALE),
        "door-arcs": True, "svg-poly": False, "svg-prefilter": True, "svg-unify-inputs": False,
        # D73: projection lines grouped per element (styled by graphics.style_svg), no CSS
        "svg-segment-projection": True, "svg-no-css": True,
    }
    opts.update(_svg_overrides())  # KIMCAD_SVG_OPTS (JSON) for tuning the serializer's hidden-line pass
    for key, value in opts.items():
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
    svg = buffer.get_value()
    if s is not None:
        svg = overlay(f, drawing, s, svg, set(include) if include is not None else None)
    svg = crop(svg)
    return svg, {"elements": count, "prepare_s": round(t1 - t0, 3), "geometry_s": round(t2 - t1, 3),
                 "hlr_s": round(t3 - t2, 3), "total_s": round(time.perf_counter() - t0, 3)}


def _bounds_of(job) -> tuple | None:
    b = job.get("bounds") if isinstance(job, dict) else None
    return None if b is None else (np.array(b[0], dtype=float), np.array(b[1], dtype=float))


def _job(data) -> dict:
    """A generate request: {"drawing", "include", "bounds"}; a bare list is an older include-only job."""
    return data if isinstance(data, dict) else {"include": data}


def _one(f, job) -> dict:
    """Generate one drawing on the already-open model `f`; {ok, svg, timing} or {ok: false, error}."""
    try:
        drawing = f.by_guid(job["drawing"])
        svg, timing = _with_big_stack(lambda: generate(f, drawing, job.get("include"), _bounds_of(job)))
        return {"ok": True, "svg": svg, "timing": timing}
    except Exception as ex:  # report, never a traceback on the app's console
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}


# The SVG serializer recurses through the hidden-line pass; on a large storey it overflows the ~1 MB
# stack of the main thread (0xC00000FD: the child dies with no output). A thread with a large stack
# fixes it; the C++ geometry threads are unaffected (only Python threads take threading.stack_size).
_STACK = 64 * 1024 * 1024


def _with_big_stack(fn):
    try:
        threading.stack_size(_STACK)
    except (ValueError, RuntimeError):
        return fn()  # the platform refuses: run inline and hope the drawing is small
    box: dict = {}

    def run():
        try:
            box["v"] = fn()
        except BaseException as ex:  # noqa: BLE001 - re-raised on the caller's thread
            box["e"] = ex

    worker = threading.Thread(target=run)
    worker.start()
    worker.join()
    if "e" in box:
        raise box["e"]
    return box["v"]


def main(argv) -> int:
    if len(argv) > 1 and argv[1] == "--worker":  # one process, one open model, a request per line
        return worker(argv[2])
    try:
        f = ifcopenshell.open(argv[1])
        job = {"drawing": argv[2]}
        if len(argv) > 3:
            with open(argv[3], encoding="utf-8") as fh:
                job.update(_job(json.load(fh)))
        out = _one(f, job)
    except Exception as ex:  # report, never a traceback on the app's console
        out = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
    sys.stdout.write(json.dumps(out))
    return 0


def worker(path: str) -> int:
    """Long-lived generator (D60): open the snapshot once, then one drawing request per input line.
    Re-opening the model for every drawing cost seconds on real files; the process and the model stay."""
    try:
        f = ifcopenshell.open(path)
    except Exception as ex:
        sys.stdout.write(json.dumps({"ok": False, "error": f"{type(ex).__name__}: {ex}"}) + "\n")
        sys.stdout.flush()
        return 1
    sys.stdout.write(json.dumps({"ok": True, "ready": True}) + "\n")  # ack: the model is open
    sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
        except ValueError:
            continue
        if job.get("op") == "stop":
            break
        sys.stdout.write(json.dumps(_one(f, job)) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
