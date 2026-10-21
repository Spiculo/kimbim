# SPDX-License-Identifier: GPL-3.0-or-later
"""Curved walls (D97, Archicad's Wall tool, Curved geometry method): a layered wall along an arc.

The arc is kept in the wall's own coordinates in `KIMBIM_Wall.Arc` (start, end and a point on it,
metres) with the wall's height; its axis is an IfcIndexedPolyCurve arc (start, end, middle: readers
that take an axis' first two points get the chord) and its body the band between the layers' outer
radii, as an arc-sided profile extruded up (IFC4; IFC2X3 gets arcs as short segments). The layers
stack across the arc as on a straight wall: a reference line or composite change rebuilds the body.
Curved walls are not joined or given openings (yet): ifcopenshell's regenerator only knows lines.
"""
from __future__ import annotations

import json
import math

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.type
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import numpy as np

from . import app_bridge as B

WALL_PSET = "KIMBIM_Wall"
ARC_STEP_DEGREES = 5.0  # IFC2X3: arcs as segments of at most this angle


def _fail(message: str) -> str:
    return json.dumps({"ok": False, "error": message})


def _pset(wall) -> dict:
    return ifcopenshell.util.element.get_pset(wall, WALL_PSET) or {}


def is_curved(wall) -> bool:
    return bool(_pset(wall).get("Arc"))


def arc_of(wall):
    """(start, end, through) in the wall's own coordinates (metres), or None."""
    raw = _pset(wall).get("Arc")
    if not raw:
        return None
    pts = json.loads(raw)
    return tuple(tuple(float(c) for c in p) for p in pts)


def frame(start, end, through):
    """(centre, radius, start angle, sweep) of the arc from `start` through `through` to `end`."""
    from . import drafting

    return drafting.arc_frame(start, through, end)


def length(wall) -> float:
    """The arc's length (metres)."""
    arc = arc_of(wall)
    fr = frame(*arc) if arc else None
    return abs(fr[1] * fr[3]) if fr else 0.0


def refusal(elements) -> str | None:
    """Why an edit that needs a straight axis can't touch these elements (a curved wall), or None."""
    for e in elements:
        if e.is_a("IfcWall") and is_curved(e):
            return f"{e.Name or 'the wall'} is curved: this works on straight walls only"
    return None


def refusal_of(*guids) -> str | None:
    """refusal() for elements given by GlobalId (unknown ones are left to the caller)."""
    if B._model is None:
        return None
    found = []
    for g in guids:
        try:
            found.append(B._model.by_guid(g))
        except (RuntimeError, TypeError):
            continue
    return refusal(found)


def _offsets(wall):
    """(y0, y1): the body's sides to the axis' left (metres), from the layer usage."""
    from . import authoring as A

    usage = ifcopenshell.util.element.get_material(wall, should_skip_usage=False)
    s = A._scale()
    total = sum(float(l.LayerThickness or 0.0) for l in usage.ForLayerSet.MaterialLayers) * s
    off = float(usage.OffsetFromReferenceLine or 0.0) * s
    return (off, off + total) if usage.DirectionSense != "NEGATIVE" else (off - total, off)


def _arc_points(centre, r, a0, sweep, n):
    return [(centre[0] + r * math.cos(a0 + sweep * i / n), centre[1] + r * math.sin(a0 + sweep * i / n))
            for i in range(n + 1)]


def _curve(f, centre, r, a0, sweep, reverse=False):
    """IFC4: (points, one arc segment); IFC2X3: points only (a polyline)."""
    if f.schema == "IFC2X3":
        n = max(2, math.ceil(abs(math.degrees(sweep)) / ARC_STEP_DEGREES))
        pts = _arc_points(centre, r, a0, sweep, n)
    else:
        pts = _arc_points(centre, r, a0, sweep, 2)  # start, middle, end
    return list(reversed(pts)) if reverse else pts


def rebuild(wall) -> bool:
    """The body and axis from the stored arc and the wall's layers (the regenerator's stand-in)."""
    from . import authoring as A

    arc = arc_of(wall)
    if arc is None:
        return False
    f = B._model
    start, end, through = arc
    fr = frame(start, end, through)
    if fr is None:
        raise ValueError("the arc's three points are in a line")
    centre, R, a0, sweep = fr
    left = 1.0 if sweep > 0 else -1.0  # counter-clockwise: the axis' left is towards the centre
    y0, y1 = _offsets(wall)
    ra, rb = R - left * y0, R - left * y1
    if min(ra, rb) <= 0.01:
        raise ValueError("the wall is thicker than its arc's radius")
    height = float(_pset(wall).get("Height") or 3.0)
    k = 1.0 / A._scale()
    outer = _curve(f, centre, ra, a0, sweep)
    inner = _curve(f, centre, rb, a0, sweep, reverse=True)
    pts = outer + inner
    if f.schema == "IFC2X3":
        curve = f.createIfcPolyline([f.createIfcCartesianPoint((x * k, y * k)) for x, y in pts + pts[:1]])
        axis_curve = f.createIfcPolyline([f.createIfcCartesianPoint((x * k, y * k))
                                          for x, y in _curve(f, centre, R, a0, sweep)])
    else:
        coords = f.createIfcCartesianPointList2D([(x * k, y * k) for x, y in pts])
        curve = f.createIfcIndexedPolyCurve(coords, [
            f.createIfcArcIndex((1, 2, 3)), f.createIfcLineIndex((3, 4)),
            f.createIfcArcIndex((4, 5, 6)), f.createIfcLineIndex((6, 1))], False)
        a_start, a_mid, a_end = _curve(f, centre, R, a0, sweep)
        axis_curve = f.createIfcIndexedPolyCurve(  # start, end, middle: the chord comes first
            f.createIfcCartesianPointList2D([(x * k, y * k) for x, y in (a_start, a_end, a_mid)]),
            [f.createIfcArcIndex((1, 3, 2))], False)
    profile = f.createIfcArbitraryClosedProfileDef("AREA", None, curve)
    solid = f.createIfcExtrudedAreaSolid(profile, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None),
                                         f.createIfcDirection((0.0, 0.0, 1.0)), height * k)
    A._replace_body(wall, f.createIfcShapeRepresentation(A._body_context(), "Body", "SweptSolid", [solid]))
    axis_rep = f.createIfcShapeRepresentation(_axis_context(), "Axis", "Curve2D", [axis_curve])
    old = ifcopenshell.util.representation.get_representation(wall, "Plan", "Axis", "GRAPH_VIEW")
    if old is not None:
        ifcopenshell.api.geometry.unassign_representation(f, product=wall, representation=old)
        ifcopenshell.api.geometry.remove_representation(f, representation=old)
    ifcopenshell.api.geometry.assign_representation(f, product=wall, representation=axis_rep)
    return True


def _axis_context():
    import ifcopenshell.api.context

    f = B._model
    ctx = ifcopenshell.util.representation.get_context(f, "Plan", "Axis", "GRAPH_VIEW")
    if ctx is None:
        plan = ifcopenshell.util.representation.get_context(f, "Plan")
        if plan is None:
            plan = ifcopenshell.api.context.add_context(f, context_type="Plan")
        ctx = ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="Axis",
                                                   target_view="GRAPH_VIEW", parent=plan)
    return ctx


def new_curved_wall(storey, wall_type, p1, p2, pm, height: float, reference: str = "", usage_from=None):
    """Inside an action: a curved wall from p1 through pm to p2 (world metres) on a level; its layers by
    `reference` ("" = centred) or `usage_from` ((offset metres, direction sense, reference name))."""
    from . import authoring as A
    from . import configure

    f = B._model
    wall = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name=wall_type.Name)
    ifcopenshell.api.type.assign_type(f, related_objects=[wall], relating_type=wall_type)
    if usage_from is not None:
        configure.set_usage(wall, *usage_from)
    elif reference:
        configure.apply_reference(wall, reference)
    else:
        A._centre_on_axis(wall, A._thickness(A._layer_set(wall_type)))
    matrix = np.eye(4)
    matrix[2, 3] = A._elevation(storey)
    ifcopenshell.api.geometry.edit_object_placement(f, product=wall, matrix=matrix, is_si=True)
    ifcopenshell.api.spatial.assign_container(f, products=[wall], relating_structure=storey)
    configure._write_pset(wall, WALL_PSET, {"Arc": json.dumps([list(map(float, p1)), list(map(float, p2)),
                                                               list(map(float, pm))]), "Height": float(height)})
    rebuild(wall)
    return wall


def create_curved_wall(storey_guid: str, type_guid: str, x1, y1, xm, ym, x2, y2, height, reference: str = "") -> str:
    """A curved wall of a layered type from (x1, y1) through (xm, ym) to (x2, y2) on a level (one undo
    step). `reference` (configure.REFERENCES): where the drawn arc is in the wall; "" = its centre."""
    from . import authoring as A
    from . import configure, layers, renovation

    if B._model is None:
        return _fail("no model open")
    try:
        p1, pm, p2 = (float(x1), float(y1)), (float(xm), float(ym)), (float(x2), float(y2))
        height = float(height)
    except (TypeError, ValueError) as ex:
        return _fail(str(ex))
    storey, wall_type = A._by_guid(storey_guid), A._by_guid(type_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return _fail("unknown level")
    if wall_type is None or A._layer_set(wall_type) is None:
        return _fail("unknown or non-layered wall type")
    if height <= 0:
        return _fail("the wall height must be positive")
    if reference and reference not in configure.REFERENCES:
        return _fail(f"unknown reference line {reference}")
    if frame(p1, p2, pm) is None or min(math.dist(p1, pm), math.dist(pm, p2)) < A.MIN_WALL_LENGTH:
        return _fail("the three points of a curved wall must not be in a line")
    made = {}

    def action():
        wall = new_curved_wall(storey, wall_type, p1, p2, pm, height, reference)
        layers.assign_active(wall)
        renovation.stamp_new(wall)
        made["wall"] = wall
        return 1, [wall.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(str(ex) if isinstance(ex, ValueError) else f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["wall"].GlobalId})
