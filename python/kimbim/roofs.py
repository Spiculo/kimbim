# SPDX-License-Identifier: GPL-3.0-or-later
"""Roofs (Slice 19), after Archicad's Roof tool: a footprint (the eaves outline) with one slope per edge,
as Archicad's multi-plane roof; an edge without a slope is a gable end. Presets: flat, shed (the
longest edge slopes), gable (the edges parallel to the longest slope), hip (every edge slopes).

The roof surface is the lower envelope of the edge planes (each rises from its edge at its own angle),
which for a convex footprint is the classic hipped/gabled shape. The body is a plate of constant
vertical thickness (`IfcPolygonalFaceSet`); flat roofs are an extruded outline. The roof is an `IfcRoof`
with its own body (as Bonsai makes them), contained in the level; KimBim keeps its definition in
`KIMBIM_Roof` (outline relative to the roof's placement, slopes, thickness) so moved roofs stay right.

Walls attach to a roof (Archicad: Trim to Roof): they are raised to reach its underside and clipped by
its planes (`IfcBooleanClippingResult`, registered in ifcopenshell's `BBIM_Boolean` so wall rebuilds
keep them). `KIMBIM_RoofAttach` names the roof; after any edit that moves the roof or the wall, the
wall is trimmed again in the same undo step. Same protocol as app_bridge.
"""
from __future__ import annotations

import json
import math

import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import ifcopenshell.util.shape_builder
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import layers
from . import materials
from . import renovation

PSET = "KIMBIM_Roof"
ATTACH = "KIMBIM_RoofAttach"
KINDS = {"flat": "FLAT_ROOF", "shed": "SHED_ROOF", "gable": "GABLE_ROOF", "hip": "HIP_ROOF", "custom": "FREEFORM"}
MAX_PITCH = 85.0  # degrees; steeper planes are walls
_EPS = 1e-9


# ---------------------------------------------------------------- geometry (metres, roof-local)

def _signed_area(points) -> float:
    n = len(points)
    return sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1] for i in range(n)) / 2


def _convex(points) -> bool:
    n = len(points)
    for i in range(n):
        a, b, c = np.array(points[i - 1]), np.array(points[i]), np.array(points[(i + 1) % n])
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) < -1e-9:
            return False
    return True


def preset_slopes(points, kind: str, pitch: float):
    """Per-edge slopes (degrees, None = gable end) for a preset roof kind."""
    n = len(points)
    if kind == "flat":
        return [None] * n
    if kind == "hip":
        return [pitch] * n
    lengths = [math.dist(points[i], points[(i + 1) % n]) for i in range(n)]
    longest = max(range(n), key=lambda i: (round(lengths[i], 9), -i))
    if kind == "shed":
        return [pitch if i == longest else None for i in range(n)]
    d0 = np.subtract(points[(longest + 1) % n], points[longest]) / lengths[longest]
    out = []
    for i in range(n):
        d = np.subtract(points[(i + 1) % n], points[i]) / max(lengths[i], _EPS)
        out.append(pitch if abs(d0[0] * d[1] - d0[1] * d[0]) < 1e-6 else None)
    return out


def _planes(points, slopes):
    """Sloped edges as (a, inward unit normal, tan): height above the eaves = tan * n.(p - a)."""
    out = []
    n = len(points)
    for i, slope in enumerate(slopes):
        if slope is None:
            continue
        a, b = np.array(points[i], dtype=float), np.array(points[(i + 1) % n], dtype=float)
        d = (b - a) / np.linalg.norm(b - a)
        out.append((a, np.array([-d[1], d[0]]), math.tan(math.radians(slope))))
    return out


def _height(planes, p) -> float:
    """Underside height above the eaves at p (roof-local metres): the lowest plane."""
    return min((t * float(np.dot(n, np.asarray(p) - a)) for a, n, t in planes), default=0.0)


def _clip(polygon, k, c):
    """The part of a convex polygon where k.p <= c."""
    out = []
    m = len(polygon)
    for i in range(m):
        p, q = polygon[i], polygon[(i + 1) % m]
        fp, fq = float(np.dot(k, p)) - c, float(np.dot(k, q)) - c
        if fp <= 1e-12:
            out.append(p)
        if (fp < -1e-12 < fq) or (fq < -1e-12 < fp):
            out.append(p + (q - p) * (fp / (fp - fq)))
    return out


def _dedupe(polygon):
    out = []
    for p in polygon:
        if not out or np.linalg.norm(p - out[-1]) > 1e-9:
            out.append(p)
    if len(out) > 1 and np.linalg.norm(out[0] - out[-1]) < 1e-9:
        out.pop()
    return out


def _faces(points, slopes):
    """The roof's planar faces in plan: [(polygon, plane index)]; one face for a flat or shed roof."""
    footprint = [np.array(p, dtype=float) for p in points]
    planes = _planes(points, slopes)
    if len(planes) <= 1:
        return [(footprint, 0)], planes
    faces = []
    for i, (a, n, t) in enumerate(planes):
        poly = footprint
        for j, (b, m, u) in enumerate(planes):
            if i == j:
                continue
            # t n.(p - a) <= u m.(p - b)
            k = t * n - u * m
            c = t * float(np.dot(n, a)) - u * float(np.dot(m, b))
            if np.linalg.norm(k) < 1e-12:
                if c < 0 or (abs(c) < 1e-12 and j < i):  # the same plane: the first one keeps the face
                    poly = []
                continue
            poly = _clip(poly, k, c)
            if len(poly) < 3:
                break
        poly = _dedupe(poly)
        if len(poly) >= 3 and abs(_signed_area(poly)) > 1e-9:
            faces.append((poly, i))
    return faces, planes


def _mesh(points, slopes, thickness):
    """A closed plate: (vertices [(x, y, z)], faces [[indices]]) in roof-local metres, outward faces."""
    faces, planes = _faces(points, slopes)
    keys, verts = {}, []

    def vid(p, z):
        key = (round(float(p[0]), 7), round(float(p[1]), 7), round(z, 7))
        if key not in keys:
            keys[key] = len(verts)
            verts.append((float(p[0]), float(p[1]), float(z)))
        return keys[key]

    plan_points = {}
    for poly, _ in faces:
        for p in poly:
            plan_points[(round(float(p[0]), 7), round(float(p[1]), 7))] = p

    def with_points_on_edges(poly):
        """Insert other faces' corners lying on this polygon's edges (no T-junctions)."""
        out = []
        for i in range(len(poly)):
            p, q = poly[i], poly[(i + 1) % len(poly)]
            out.append(p)
            d = q - p
            length2 = float(np.dot(d, d))
            between = []
            for r in plan_points.values():
                t = float(np.dot(r - p, d)) / length2 if length2 > 0 else 0
                if 1e-7 < t < 1 - 1e-7 and np.linalg.norm(p + d * t - r) < 1e-7:
                    between.append((t, r))
            out += [r for _, r in sorted(between, key=lambda x: x[0])]
        return out

    polys = []
    for poly, _ in faces:
        poly = with_points_on_edges(poly)
        polys.append([vid(p, _height(planes, p) + thickness) for p in poly])  # top, counter-clockwise
        polys.append([vid(p, _height(planes, p)) for p in reversed(poly)])  # underside
    footprint = [np.array(p, dtype=float) for p in points]
    for i in range(len(footprint)):  # the edges: eaves strips and gable ends
        a, b = footprint[i], footprint[(i + 1) % len(footprint)]
        d = b - a
        length2 = float(np.dot(d, d))
        on = [(0.0, a), (1.0, b)]
        for r in plan_points.values():
            t = float(np.dot(r - a, d)) / length2
            if 1e-7 < t < 1 - 1e-7 and np.linalg.norm(a + d * t - r) < 1e-7:
                on.append((t, r))
        on = [r for _, r in sorted(on, key=lambda x: x[0])]
        bottom = [vid(p, _height(planes, p)) for p in on]
        top = [vid(p, _height(planes, p) + thickness) for p in reversed(on)]
        polys.append(bottom + top)
    return verts, polys


# ---------------------------------------------------------------- roofs in the model

def _parse(points_json, slopes_json):
    points = [(float(x), float(y)) for x, y in json.loads(points_json)]
    slopes = json.loads(slopes_json) if slopes_json else None
    return points, slopes


def _definition(roof):
    data = ifcopenshell.util.element.get_pset(roof, PSET) or {}
    try:
        return json.loads(data["Points"]), json.loads(data["Slopes"]), float(data["Thickness"]), data.get("Kind", "custom")
    except (KeyError, ValueError, TypeError):
        return None


def _body(roof, points, slopes, thickness):
    """Inside an action: the roof's body from its definition (roof-local metres)."""
    f = B._model
    s = A._scale()
    if all(sl is None for sl in slopes):
        representation = ifcopenshell.api.geometry.add_slab_representation(
            f, context=A._body_context(), depth=thickness, polyline=[tuple(p) for p in points])
    else:
        verts, polys = _mesh(points, slopes, thickness)
        builder = ifcopenshell.util.shape_builder.ShapeBuilder(f)
        item = builder.polygonal_face_set([tuple(c / s for c in v) for v in verts], polys)
        item.Closed = True
        representation = builder.get_representation(A._body_context(), [item])
    A._replace_body(roof, representation)


def create_roof(storey_guid: str, points_json: str, kind: str, pitch, thickness, offset, slopes_json: str = "") -> str:
    """A roof over `points` (world metres, the eaves outline) with its underside at the eaves `offset`
    metres above the level. `kind`: flat, shed, gable, hip, or custom with `slopes_json` (degrees per
    edge, null for a gable end)."""
    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    if kind not in KINDS:
        return A._fail(f"unknown roof kind {kind}")
    try:
        points, slopes = _parse(points_json, slopes_json)
        pitch, thickness, offset = float(pitch or 0), float(thickness), float(offset or 0)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    if len(points) < 3 or abs(_signed_area(points)) < 1e-6:
        return A._fail("a roof needs an outline of at least three points")
    if thickness <= 0:
        return A._fail("the roof thickness must be positive")
    if slopes is None:
        if kind == "custom":
            return A._fail("a custom roof needs a slope for each edge")
        if kind != "flat" and not 0 < pitch <= MAX_PITCH:
            return A._fail(f"the pitch must be between 0 and {MAX_PITCH:g} degrees")
        slopes = preset_slopes(points, kind, pitch)
    if len(slopes) != len(points):
        return A._fail("one slope per edge")
    slopes = [None if s is None or float(s) == 0 else float(s) for s in slopes]
    if any(s is not None and not 0 < s <= MAX_PITCH for s in slopes):
        return A._fail(f"slopes must be between 0 and {MAX_PITCH:g} degrees")
    if _signed_area(points) < 0:  # counter-clockwise, slopes staying with their edges
        n = len(points)
        points, slopes = points[::-1], [slopes[(n - 2 - j) % n] for j in range(n)]
    if any(s is not None for s in slopes) and not _convex(points):
        return A._fail("pitched roofs need a convex outline (draw an L-shaped house as two roofs)")
    origin = np.array(points[0])
    local = [(round(x - origin[0], 9), round(y - origin[1], 9)) for x, y in points]
    predefined = KINDS[kind]
    made = {}

    def action():
        f = B._model
        roof = ifcopenshell.api.root.create_entity(f, ifc_class="IfcRoof", name="Roof", predefined_type=predefined)
        ifcopenshell.api.spatial.assign_container(f, products=[roof], relating_structure=storey)
        matrix = np.eye(4)
        matrix[:3, 3] = [origin[0], origin[1], A._elevation(storey) + offset]
        ifcopenshell.api.geometry.edit_object_placement(f, product=roof, matrix=matrix, is_si=True)
        pset = ifcopenshell.api.pset.add_pset(f, product=roof, name=PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={
            "Kind": kind, "Points": json.dumps(local), "Slopes": json.dumps(slopes), "Thickness": thickness})
        _body(roof, local, slopes, thickness)
        materials.give_roof_material(roof)  # D96
        layers.assign_active(roof)
        renovation.stamp_new(roof)
        made["guid"] = roof.GlobalId
        return 1, [roof.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["guid"]})


def roof_info(guid: str) -> str:
    """{kind, points (world metres), slopes, thickness, eaves (world height)}."""
    roof = A._by_guid(guid) if B._model is not None else None
    definition = _definition(roof) if roof is not None and roof.is_a("IfcRoof") else None
    if definition is None:
        return A._fail("not a KimBim roof")
    points, slopes, thickness, kind = definition
    m = _matrix_si(roof)
    world = [(m @ np.array([x, y, 0.0, 1.0]))[:3] for x, y in points]
    return B._dump({"ok": True, "kind": kind, "slopes": slopes, "thickness": thickness,
                    "points": [[round(float(p[0]), 6), round(float(p[1]), 6)] for p in world],
                    "eaves": round(float(world[0][2]), 6)})


def _matrix_si(product):
    m = ifcopenshell.util.placement.get_local_placement(product.ObjectPlacement).copy()
    m[:3, 3] *= A._scale()
    return m


def _world_planes(roof):
    """The roof underside as world planes [(point, upward normal)] (metres); the region under the roof
    is below all of them."""
    definition = _definition(roof)
    if definition is None:
        return []
    points, slopes, _thickness, _kind = definition
    m = _matrix_si(roof)
    out = []
    planes = _planes(points, slopes)
    for a, n, t in planes:
        local_normal = np.array([-t * n[0], -t * n[1], 1.0])
        out.append(((m @ np.array([a[0], a[1], 0.0, 1.0]))[:3], m[:3, :3] @ (local_normal / np.linalg.norm(local_normal))))
    if not planes:  # flat: its underside
        out.append(((m @ np.array([0.0, 0.0, 0.0, 1.0]))[:3], m[:3, :3] @ np.array([0.0, 0.0, 1.0])))
    return out


def _underside(planes, x, y) -> float:
    zs = []
    for p, n in planes:
        if abs(n[2]) > 1e-9:
            zs.append(p[2] - (n[0] * (x - p[0]) + n[1] * (y - p[1])) / n[2])
    return min(zs) if zs else -math.inf


# ---------------------------------------------------------------- walls trimmed to roofs

def _wall_base(wall) -> float:
    return float(ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)[2][3]) * A._scale()


def _needed_height(wall, planes) -> float:
    """Wall height (metres) that reaches the roof underside everywhere over the wall's footprint."""
    axis = A._axis_world(wall)
    layer_set = A._layer_set(wall)
    if axis is None:
        return 0.0
    t = A._thickness(layer_set) if layer_set is not None else 0.3
    p1, p2 = np.array(axis[0], dtype=float), np.array(axis[1], dtype=float)
    d = p2 - p1
    length = float(np.linalg.norm(d))
    if length < 1e-9:
        return 0.0
    d /= length
    n = np.array([-d[1], d[0]])
    top = -math.inf
    for s in np.linspace(-t, length + t, 61):
        for w in np.linspace(-t / 2, t / 2, 5):
            p = p1 + d * s + n * w
            top = max(top, _underside(planes, p[0], p[1]))
    return top - _wall_base(wall)


def _clear_booleans(wall):
    data = ifcopenshell.util.element.get_pset(wall, "BBIM_Boolean")
    if data:
        ifcopenshell.api.pset.remove_pset(B._model, product=wall, pset=B._model.by_id(data["id"]))


def _set_height(wall, height):
    f = B._model
    body = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
    for solid in (f.traverse(body) if body is not None else ()):
        if solid.is_a("IfcExtrudedAreaSolid"):
            solid.Depth = height / A._scale()


def _trim(wall, roof):
    """Inside an action: raise the wall to the roof and clip it by the roof's underside planes."""
    f = B._model
    planes = _world_planes(roof)
    _clear_booleans(wall)
    needed = _needed_height(wall, planes) + 0.01
    if needed > A._wall_height(wall):
        _set_height(wall, needed)
    A._regenerate(f, wall)
    body = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
    if body is None or not body.Items:
        return
    s = A._scale()
    inverse = np.linalg.inv(ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement))
    item = body.Items[0]
    for point, normal in planes:
        location = (inverse @ np.array([*(point / s), 1.0]))[:3] * s  # clip_solid takes metres
        local_normal = inverse[:3, :3] @ normal
        item = ifcopenshell.api.geometry.clip_solid(f, item=item, location=[float(c) for c in location],
                                                    normal=[float(c) for c in local_normal], element=wall)
    body.Items = [item] + list(body.Items[1:])
    body.RepresentationType = "Clipping"


def _release(wall):
    """Inside an action: a plain wall again, at the height it had before it was attached."""
    data = ifcopenshell.util.element.get_pset(wall, ATTACH) or {}
    _clear_booleans(wall)
    if data.get("Height"):
        _set_height(wall, float(data["Height"]))
    if data:
        ifcopenshell.api.pset.remove_pset(B._model, product=wall, pset=B._model.by_id(data["id"]))
    A._regenerate(B._model, wall)


def attach_walls_to_roof(roof_guid: str, walls_json: str) -> str:
    """Trim walls to a roof (Archicad: Trim to Roof): they reach up to its underside and stop there."""
    roof = A._by_guid(roof_guid) if B._model is not None else None
    if roof is None or not roof.is_a("IfcRoof") or _definition(roof) is None:
        return A._fail("not a KimBim roof")
    walls = [w for w in B._elements(walls_json) if w.is_a("IfcWall") and A._layer_set(w) is not None]
    if not walls:
        return A._fail("no walls selected")

    def action():
        f = B._model
        for w in walls:
            data = ifcopenshell.util.element.get_pset(w, ATTACH)
            pset = f.by_id(data["id"]) if data else ifcopenshell.api.pset.add_pset(f, product=w, name=ATTACH)
            height = float(data["Height"]) if data and data.get("Height") else A._wall_height(w)
            ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"Roof": roof.GlobalId, "Height": height})
        return len(walls), [w.GlobalId for w in walls], []  # the after-action hook trims them

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def detach_walls_from_roof(walls_json: str) -> str:
    """Walls no longer trimmed to a roof go back to their own height."""
    if B._model is None:
        return A._fail("no model open")
    walls = [w for w in B._elements(walls_json) if w.is_a("IfcWall") and ifcopenshell.util.element.get_pset(w, ATTACH)]
    if not walls:
        return A._fail("none of these walls is trimmed to a roof")

    def action():
        for w in walls:
            _release(w)
        return len(walls), [w.GlobalId for w in walls], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def _attached():
    """(wall, roof GlobalId) for every wall trimmed to a roof, from the property set definitions."""
    out = []
    for pset in B._model.by_type("IfcPropertySet"):
        if pset.Name != ATTACH:
            continue
        roof = next((p.NominalValue.wrappedValue for p in pset.HasProperties
                     if p.Name == "Roof" and p.is_a("IfcPropertySingleValue") and p.NominalValue), None)
        for wall in B._pset_users(pset):
            out.append((wall, roof))
    return out


def _retrim(changed, removed):
    """After an edit: walls trimmed to a roof follow it (or their own move); walls whose roof was
    deleted are released."""
    if B._model is None or (not removed and not B._model.by_type("IfcRoof")):
        return []  # nothing can be trimmed to a roof (cheap check for every edit)
    attached = _attached()
    if not attached:
        return []
    changed, removed = set(changed), set(removed)
    out = []
    for wall, roof_guid in attached:
        try:
            roof = B._model.by_guid(roof_guid)
        except RuntimeError:
            roof = None
        if roof is None or roof_guid in removed:
            _release(wall)
            out.append(wall.GlobalId)
        elif wall.GlobalId in changed or roof_guid in changed:
            _trim(wall, roof)
            out.append(wall.GlobalId)
    return out


B.AFTER_ACTION.append(_retrim)
