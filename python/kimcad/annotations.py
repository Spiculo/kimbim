# SPDX-License-Identifier: GPL-3.0-or-later
"""Plan annotations (owner feedback, Slice 13): text labels, linear dimensions and marks.

Each is an IfcAnnotation on a level with a 2D representation in the Plan/Annotation/PLAN_VIEW
context (text literals, polylines, a circle), so other IFC tools see them. KIMCAD also keeps what
it needs to draw and edit them in a property set (kind, text, points relative to the annotation's
placement), so moving the annotation is the generic placement move. Same protocol as app_bridge.
"""
from __future__ import annotations

import json
import math

import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import layers

PSET = "KIMCAD_Annotation"
KINDS = {"text": 1, "dimension": 3, "mark": 1}
TEXT_HEIGHT = 0.25  # metres, for the IFC text box
MARK_RADIUS = 0.4  # metres


def _context():
    f = B._model
    context = ifcopenshell.util.representation.get_context(f, "Plan", "Annotation", "PLAN_VIEW")
    if context is None:
        plan = ifcopenshell.util.representation.get_context(f, "Plan") or \
            ifcopenshell.api.context.add_context(f, context_type="Plan")
        context = ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="Annotation",
                                                       target_view="PLAN_VIEW", parent=plan)
    return context


def _measure(points) -> str:
    (ax, ay), (bx, by) = points[0], points[1]
    return f"{math.hypot(bx - ax, by - ay):.2f}"


def _dimension_lines(points):
    """Local metres: the dimension line (parallel to a-b, through the offset point) and the two
    extension lines."""
    (ax, ay), (bx, by), (ox, oy) = points
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    nx, ny = -dy / length, dx / length
    off = (ox - ax) * nx + (oy - ay) * ny
    a2, b2 = (ax + nx * off, ay + ny * off), (bx + nx * off, by + ny * off)
    return [[(ax, ay), a2], [(bx, by), b2], [a2, b2]], ((a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2)


def _representation(kind, text, points):
    """The IFC 2D representation (project units), points in local metres."""
    f = B._model
    s = A._scale()

    def pt(p):
        return f.createIfcCartesianPoint((float(p[0] / s), float(p[1] / s)))

    def literal(at, value):
        placement = f.createIfcAxis2Placement2D(pt(at), None)
        extent = f.createIfcPlanarExtent(TEXT_HEIGHT * max(len(value), 1) * 0.6 / s, TEXT_HEIGHT / s)
        return f.createIfcTextLiteralWithExtent(value, placement, "RIGHT", extent, "bottom-left")

    items = []
    if kind == "text":
        items.append(literal(points[0], text))
    elif kind == "dimension":
        lines, middle = _dimension_lines(points)
        items += [f.createIfcPolyline([pt(a), pt(b)]) for a, b in lines]
        items.append(literal(middle, text))
    else:  # mark
        items.append(f.createIfcCircle(f.createIfcAxis2Placement2D(pt(points[0]), None), MARK_RADIUS / s))
        items.append(literal(points[0], text))
    return f.createIfcShapeRepresentation(_context(), "Annotation", "Annotation2D", items)


def _set(annotation, kind, text, local):
    f = B._model
    old = list(annotation.Representation.Representations) if annotation.Representation else []
    new = _representation(kind, text, local)
    for rep in old:
        layers.carry_layers(rep, new)
        ifcopenshell.api.geometry.unassign_representation(f, product=annotation, representation=rep)
        ifcopenshell.api.geometry.remove_representation(f, representation=rep)
    ifcopenshell.api.geometry.assign_representation(f, product=annotation, representation=new)
    pset = ifcopenshell.util.element.get_pset(annotation, PSET)
    pset = f.by_id(pset["id"]) if pset else ifcopenshell.api.pset.add_pset(f, product=annotation, name=PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
        "Kind": kind, "Text": text, "Points": json.dumps([[round(x, 6), round(y, 6)] for x, y in local])})


def _read(annotation):
    data = ifcopenshell.util.element.get_pset(annotation, PSET) or {}
    if data.get("Kind") not in KINDS:
        return None
    try:
        local = json.loads(data.get("Points") or "[]")
    except ValueError:
        return None
    return data["Kind"], data.get("Text") or "", local


def add_annotation(storey_guid: str, kind: str, points_json: str, text: str) -> str:
    """Add a text label (1 point), a dimension (a, b and a point the dimension line passes
    through; it measures itself) or a mark (centre + tag) on a level. Points in world metres."""
    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    if kind not in KINDS:
        return A._fail(f"unknown annotation kind {kind}")
    try:
        points = [(float(x), float(y)) for x, y in json.loads(points_json)]
    except (TypeError, ValueError) as ex:
        return A._fail(f"bad points: {ex}")
    if len(points) != KINDS[kind]:
        return A._fail(f"a {kind} needs {KINDS[kind]} point(s)")
    text = (text or "").strip()
    if kind == "dimension":
        if math.dist(points[0], points[1]) < 1e-6:
            return A._fail("a dimension needs two different points")
        text = text or None
    elif not text:
        return A._fail("type the text")
    origin = points[0]
    local = [(x - origin[0], y - origin[1]) for x, y in points]
    if kind == "dimension" and text is None:
        text = _measure(local)
    made = {}

    def action():
        f = B._model
        annotation = ifcopenshell.api.root.create_entity(f, ifc_class="IfcAnnotation", name=text[:60])
        annotation.ObjectType = kind.upper()
        ifcopenshell.api.spatial.assign_container(f, products=[annotation], relating_structure=storey)
        matrix = np.eye(4)
        matrix[0][3], matrix[1][3], matrix[2][3] = origin[0], origin[1], A._elevation(storey)
        ifcopenshell.api.geometry.edit_object_placement(f, product=annotation, matrix=matrix, is_si=True)
        _set(annotation, kind, text, local)
        layers.assign_active(annotation)
        made["guid"] = annotation.GlobalId
        return 1, [annotation.GlobalId], []

    r = B._run(action)
    return B._dump({**r, "guid": made["guid"]})


def annotations(storey_guid: str) -> str:
    """The annotations on a level, in world metres: [{guid, kind, text, points}]."""
    storey = A._by_guid(storey_guid) if B._model is not None else None
    out = []
    if storey is not None:
        s = A._scale()
        for rel in getattr(storey, "ContainsElements", ()) or ():
            for a in rel.RelatedElements:
                if not a.is_a("IfcAnnotation") or a.ObjectPlacement is None:
                    continue
                data = _read(a)
                if data is None:
                    continue
                kind, text, local = data
                m = ifcopenshell.util.placement.get_local_placement(a.ObjectPlacement)
                points = []
                for x, y in local:
                    w = m @ np.array([x / s, y / s, 0.0, 1.0])
                    points.append([round(float(w[0] * s), 6), round(float(w[1] * s), 6)])
                out.append({"guid": a.GlobalId, "kind": kind, "text": text, "points": points})
    return B._dump({"annotations": out})


def set_annotation_text(guid: str, text: str) -> str:
    a = A._by_guid(guid) if B._model is not None else None
    data = _read(a) if a is not None and a.is_a("IfcAnnotation") else None
    if data is None:
        return A._fail("not an annotation")
    kind, _, local = data
    text = (text or "").strip()
    if kind == "dimension" and not text:
        text = _measure(local)  # an emptied dimension text measures again
    if not text:
        return A._fail("type the text")

    def action():
        _set(a, kind, text, local)
        a.Name = text[:60]
        return 1, [a.GlobalId], []

    return B._dump(B._run(action))
