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
# Kind -> (fewest points, most points); None = no limit. A dimension is a chain: the measured points,
# then a point the dimension line passes through. A leader: arrow tip, bends, then where the text sits.
KINDS = {"text": (1, 1), "dimension": (3, None), "mark": (1, 1), "leader": (2, None)}
TEXT_SIZE = 2.5  # millimetres on paper (Slice 15: text size in paper units, doc 13)
DRAWING_SCALE = 100  # 1:100 until drawings get a scale setting
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


def _projected(points):
    """A dimension chain's measured points projected on its dimension line (parallel to first-last,
    through the last point given), local metres."""
    *measured, (ox, oy) = points
    (ax, ay), (bx, by) = measured[0], measured[-1]
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    off = (ox - ax) * nx + (oy - ay) * ny
    return measured, [(px + nx * (off - ((px - ax) * nx + (py - ay) * ny)), py + ny * (off - ((px - ax) * nx + (py - ay) * ny)))
                      for px, py in measured]


def _measure(points) -> str:
    """Each segment of the chain, as measured along the dimension line, in metres."""
    _, on_line = _projected(points)
    return " ".join(f"{math.dist(p, q):.2f}" for p, q in zip(on_line, on_line[1:]))


def _dimension_lines(points):
    """Local metres: the extension lines, the dimension line, and the middle of each segment."""
    measured, on_line = _projected(points)
    lines = [[p, q] for p, q in zip(measured, on_line)] + [[on_line[0], on_line[-1]]]
    middles = [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) for p, q in zip(on_line, on_line[1:])]
    return lines, middles


def _representation(kind, text, points, size=TEXT_SIZE):
    """The IFC 2D representation (project units), points in local metres. Text boxes are as high as
    the text prints at the drawing scale (size mm on paper)."""
    f = B._model
    s = A._scale()
    height = size * DRAWING_SCALE / 1000.0  # metres in the model

    def pt(p):
        return f.createIfcCartesianPoint((float(p[0] / s), float(p[1] / s)))

    def literal(at, value):
        placement = f.createIfcAxis2Placement2D(pt(at), None)
        extent = f.createIfcPlanarExtent(height * max(len(value), 1) * 0.6 / s, height / s)
        return f.createIfcTextLiteralWithExtent(value, placement, "RIGHT", extent, "bottom-left")

    items = []
    if kind == "text":
        items.append(literal(points[0], text))
    elif kind == "dimension":
        lines, middles = _dimension_lines(points)
        items += [f.createIfcPolyline([pt(a), pt(b)]) for a, b in lines]
        labels = text.split()
        for i, middle in enumerate(middles):
            items.append(literal(middle, labels[i] if i < len(labels) else ""))
    elif kind == "leader":
        items.append(f.createIfcPolyline([pt(p) for p in points]))
        items.append(literal(points[-1], text))
    else:  # mark
        items.append(f.createIfcCircle(f.createIfcAxis2Placement2D(pt(points[0]), None), MARK_RADIUS / s))
        items.append(literal(points[0], text))
    return f.createIfcShapeRepresentation(_context(), "Annotation", "Annotation2D", items)


def _set(annotation, kind, text, local, size=None):
    f = B._model
    if size is None:
        size = float((ifcopenshell.util.element.get_pset(annotation, PSET) or {}).get("Size") or TEXT_SIZE)
    old = list(annotation.Representation.Representations) if annotation.Representation else []
    new = _representation(kind, text, local, size)
    for rep in old:
        layers.carry_layers(rep, new)
        ifcopenshell.api.geometry.unassign_representation(f, product=annotation, representation=rep)
        ifcopenshell.api.geometry.remove_representation(f, representation=rep)
    ifcopenshell.api.geometry.assign_representation(f, product=annotation, representation=new)
    pset = ifcopenshell.util.element.get_pset(annotation, PSET)
    pset = f.by_id(pset["id"]) if pset else ifcopenshell.api.pset.add_pset(f, product=annotation, name=PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
        "Kind": kind, "Text": text, "Points": json.dumps([[round(x, 6), round(y, 6)] for x, y in local]),
        "Size": float(size)})


def _read(annotation):
    data = ifcopenshell.util.element.get_pset(annotation, PSET) or {}
    if data.get("Kind") not in KINDS:
        return None
    try:
        local = json.loads(data.get("Points") or "[]")
    except ValueError:
        return None
    return data["Kind"], data.get("Text") or "", local, float(data.get("Size") or TEXT_SIZE)


def add_annotation(storey_guid: str, kind: str, points_json: str, text: str) -> str:
    """Add a text label (1 point), a dimension chain (the points to measure, then a point the
    dimension line passes through; it measures itself), a mark (centre + tag) or a leader (arrow tip,
    bends, text position) on a level. Points in world metres."""
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
    fewest, most = KINDS[kind]
    if len(points) < fewest or (most is not None and len(points) > most):
        return A._fail(f"a {kind} needs {fewest} point(s)" if fewest == most else f"a {kind} needs at least {fewest} points")
    text = (text or "").strip()
    if kind == "dimension":
        if math.dist(points[0], points[-2]) < 1e-6:
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
        for a in B._model.by_type("IfcAnnotation"):  # few; a level can hold 100k elements
            if a.ObjectPlacement is None or ifcopenshell.util.element.get_container(a) != storey:
                continue
            data = _read(a)
            if data is None:
                continue
            kind, text, local, size = data
            m = ifcopenshell.util.placement.get_local_placement(a.ObjectPlacement)
            points = []
            for x, y in local:
                w = m @ np.array([x / s, y / s, 0.0, 1.0])
                points.append([round(float(w[0] * s), 6), round(float(w[1] * s), 6)])
            out.append({"guid": a.GlobalId, "kind": kind, "text": text, "points": points, "size": size})
    return B._dump({"annotations": out})


def set_annotation_text(guid: str, text: str) -> str:
    a = A._by_guid(guid) if B._model is not None else None
    data = _read(a) if a is not None and a.is_a("IfcAnnotation") else None
    if data is None:
        return A._fail("not an annotation")
    kind, _, local, _size = data
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


def set_annotation_size(guid: str, size) -> str:
    """Text size in millimetres on paper (the printed height at the drawing scale)."""
    a = A._by_guid(guid) if B._model is not None else None
    data = _read(a) if a is not None and a.is_a("IfcAnnotation") else None
    if data is None:
        return A._fail("not an annotation")
    try:
        size = float(size)
    except (TypeError, ValueError):
        return A._fail("bad size")
    if not 0.5 <= size <= 50:
        return A._fail("the size must be between 0.5 and 50 mm")
    kind, text, local, _ = data

    def action():
        _set(a, kind, text, local, size)
        return 1, [a.GlobalId], []

    return B._dump(B._run(action))
