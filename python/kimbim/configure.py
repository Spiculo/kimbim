# SPDX-License-Identifier: GPL-3.0-or-later
"""Wall and element configuration (D97, Archicad's Wall Settings "Geometry and Positioning" and
"Model" panels): reference line location, flip, slant angle and surface overrides.

The reference line is the wall's axis (IFC's reference line); where the layers sit relative to it is
the layer usage's ``OffsetFromReferenceLine`` and ``DirectionSense`` (IFC), and the chosen location is
remembered in ``KIMBIM_Wall.ReferenceLine`` so a composite change keeps it. Changing the location of
an existing wall keeps its line (and its joins) and moves the body, like flipping, which mirrors the
composite about the line.

Surface overrides live in ``KIMBIM_Surfaces`` (surface names per side): walls "Reference side" (the
first layer's side), "Opposite side" and "Edges"; slabs "Top", "Bottom" and "Edges"; other elements
"All faces". The 3D view applies them over the materials' surfaces (``materials.face_colours``).
"""
from __future__ import annotations

import json
import math
import sys

import ifcopenshell
import ifcopenshell.api.material
import ifcopenshell.api.pset
import ifcopenshell.api.type
import ifcopenshell.util.element
import ifcopenshell.util.representation
import numpy as np

from . import app_bridge as B

GEOMETRY = "Geometry"
SURFACES = "Surfaces"
WALL_PSET = "KIMBIM_Wall"
SURFACE_PSET = "KIMBIM_Surfaces"
REFERENCES = ("Outside face", "Centre", "Inside face", "Core outside", "Core centre", "Core inside")
CUSTOM = "Custom"
FROM_MATERIAL = "(material)"  # no override: the building material's surface
WALL_SIDES = ("Reference side", "Opposite side", "Edges")
SLAB_SIDES = ("Top", "Bottom", "Edges")
ALL_SIDES = ("All faces",)
SLANT_MIN, SLANT_MAX = 45.0, 135.0  # degrees from the floor (90 = vertical), Archicad's slant angle


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def _usage(element):
    u = ifcopenshell.util.element.get_material(element, should_skip_usage=False)
    return u if u is not None and u.is_a("IfcMaterialLayerSetUsage") else None


def _pset(element, name: str) -> dict:
    return ifcopenshell.util.element.get_psets(element).get(name, {})


def _write_pset(element, name: str, props: dict):
    f = B._model
    existing = ifcopenshell.util.element.get_psets(element).get(name)
    pset = f.by_id(existing["id"]) if existing else ifcopenshell.api.pset.add_pset(f, product=element, name=name)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties=props)


# ---------------------------------------------------------------- reference line

def _offsets(usage) -> dict:
    """OffsetFromReferenceLine (model units) for each reference location of this usage's layers."""
    from . import materials

    layers = list(usage.ForLayerSet.MaterialLayers or ())
    t = [float(l.LayerThickness or 0.0) for l in layers]
    total = sum(t)
    core = materials.core_layer(usage.ForLayerSet)
    c = layers.index(core) if core in layers else 0
    before = sum(t[:c])
    positive = {"Outside face": 0.0, "Centre": -total / 2, "Inside face": -total, "Core outside": -before,
                "Core centre": -(before + t[c] / 2), "Core inside": -(before + t[c])}
    sign = 1.0 if usage.DirectionSense != "NEGATIVE" else -1.0
    return {k: v * sign for k, v in positive.items()}


def centres(layer_set) -> dict:
    """{reference: metres from the drawn line to the body's centre, to the line's left} for a new wall
    of this composite (the Wall tool's preview, D97)."""
    from . import authoring

    class _Usage:  # a positive usage of the layer set, as create_wall makes
        ForLayerSet = layer_set
        DirectionSense = "POSITIVE"

    total = sum(float(l.LayerThickness or 0.0) for l in layer_set.MaterialLayers or ())
    s = authoring._scale()
    return {k: round((v + total / 2) * s, 9) for k, v in _offsets(_Usage).items()}


def reference_of(wall) -> str:
    usage = _usage(wall)
    if usage is None:
        return ""
    stored = _pset(wall, WALL_PSET).get("ReferenceLine")
    if stored in REFERENCES:
        return stored
    off = float(usage.OffsetFromReferenceLine or 0.0)
    for name, v in _offsets(usage).items():
        if abs(v - off) < 1e-6 * max(1.0, abs(off)):
            return name
    return CUSTOM


def apply_reference(wall, reference: str):
    """Put the layers where `reference` says (the line stays); the caller regenerates."""
    usage = _usage(wall)
    if usage is None or reference not in REFERENCES:
        return
    usage.OffsetFromReferenceLine = _offsets(usage)[reference]
    _write_pset(wall, WALL_PSET, {"ReferenceLine": reference})


def set_usage(wall, offset: float, sense: str, reference: str = ""):
    """Give a wall layers placed like another's (D97, a wall continuing it): the direction sense, then
    the named reference line (or the raw offset, metres, when it has none)."""
    from . import authoring as A

    usage = _usage(wall)
    if usage is None:
        return
    usage.DirectionSense = "NEGATIVE" if sense == "NEGATIVE" else "POSITIVE"
    if reference in REFERENCES:
        apply_reference(wall, reference)
    else:
        usage.OffsetFromReferenceLine = float(offset) / A._scale()


def usage_of(wall, reversed_: bool = False):
    """(offset metres, direction sense, reference name) of a wall's layers, for set_usage; `reversed_`:
    as seen walking its axis backwards (the same faces on the same sides)."""
    from . import authoring as A

    usage = _usage(wall)
    if usage is None:
        return None
    offset = float(usage.OffsetFromReferenceLine or 0.0) * A._scale()
    sense = usage.DirectionSense or "POSITIVE"
    if reversed_:
        offset, sense = -offset, ("POSITIVE" if sense == "NEGATIVE" else "NEGATIVE")
    return offset, sense, reference_of(wall) if reference_of(wall) in REFERENCES else ""


def reapply_reference(wall) -> bool:
    """After a composite change: keep the remembered location. False when none is remembered."""
    stored = _pset(wall, WALL_PSET).get("ReferenceLine")
    if stored not in REFERENCES or _usage(wall) is None:
        return False
    _usage(wall).OffsetFromReferenceLine = _offsets(_usage(wall))[stored]
    return True


def flip(wall):
    """Mirror the composite about the reference line (Archicad's Flip): the first layer changes side."""
    usage = _usage(wall)
    if usage is None:
        return
    reference = reference_of(wall)
    usage.DirectionSense = "NEGATIVE" if usage.DirectionSense != "NEGATIVE" else "POSITIVE"
    if reference in REFERENCES:
        usage.OffsetFromReferenceLine = _offsets(usage)[reference]
    else:
        usage.OffsetFromReferenceLine = -float(usage.OffsetFromReferenceLine or 0.0)


def _regenerate_with_neighbours(walls) -> list:
    from . import authoring as A

    f = B._model
    touched = []
    for w in walls:
        A._regenerate(f, w)
        touched.append(w)
    for w in walls:  # joined walls re-trim against the new faces
        for n in A._connected_walls(w):
            if n not in touched:
                A._regenerate(f, n)
                touched.append(n)
    return touched


# ---------------------------------------------------------------- slant

def _body_solids(wall) -> list:
    rep = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
    if rep is None:
        return []
    out = []
    for item in ifcopenshell.util.representation.resolve_representation(rep).Items:
        while item.is_a("IfcBooleanResult"):
            item = item.FirstOperand
        if item.is_a("IfcExtrudedAreaSolid"):
            out.append(item)
    return out


def is_double_slanted(wall) -> bool:
    """A wall with its own swept section (double slanted or a complex profile), not the regenerator's."""
    p = _pset(wall, WALL_PSET)
    return bool(p.get("DoubleSlant") or p.get("Profile"))


# ---------------------------------------------------------------- complex profiles (D97)
# Archicad's Profile Manager: a section drawn once (a closed shape in 2D), named, and given to walls,
# which sweep it along their reference line (x across from the line, y up from the base).

NO_PROFILE = "(none)"


def profiles_error(value) -> str | None:
    if not isinstance(value, dict):
        return "wall profiles are a table by name"
    for name, pts in value.items():
        if not isinstance(name, str) or not name.strip():
            return "a wall profile needs a name"
        if not (isinstance(pts, list) and len(pts) >= 3 and all(
                isinstance(p, list) and len(p) == 2 and all(isinstance(c, (int, float)) for c in p) for p in pts)):
            return f"the profile {name} needs at least three [across, up] points"
    return None


def profiles() -> dict:
    from . import settings

    return dict(settings.current().get("wall_profiles") or {})


def profile_of(wall) -> str:
    return str(_pset(wall, WALL_PSET).get("Profile") or "")


def set_profile(wall, name: str, height: float | None = None):
    """Sweep the named section along the wall (the line stays, joins and stretches keep the section)."""
    from . import authoring as A

    pts = profiles().get(name)
    if pts is None:
        raise ValueError(f"unknown wall profile {name}")
    if A._axis_world(wall) is None:
        raise ValueError(f"{wall.Name or 'the wall'} has no axis line")
    _sweep(wall, [(float(y), float(z)) for y, z in pts], float(max(z for _, z in pts)))
    _write_pset(wall, WALL_PSET, {"Profile": name, "Height": float(max(z for _, z in pts))})


def save_wall_profile(guid: str, name: str) -> str:
    """A closed polyline, rectangle or fill (D84) as a named wall profile: its lowest left corner is the
    wall's base on its reference line, x across the wall, y up (one undo step, a settings change)."""
    from . import annotations as N
    from . import settings

    if B._model is None:
        return _fail("no model open")
    name = (name or "").strip()
    if not name:
        return _fail("a wall profile needs a name")
    try:
        a = B._model.by_guid(guid)
    except RuntimeError:
        return _fail("select a closed shape")
    data = N._read(a) if a.is_a("IfcAnnotation") else None
    kind = data[0] if data else ""
    closed = kind == "fill" or (kind == "polyline" and N.extra_of(a).get("Closed"))
    if not closed:
        return _fail("draw the section as a closed polyline, a rectangle or a fill")
    world = [(float(p[0]), float(p[1])) for p in N.world_points(a)]
    x0, y0 = min(p[0] for p in world), min(p[1] for p in world)
    pts = [[round(x - x0, 6), round(y - y0, 6)] for x, y in world]

    def action():
        table = profiles()
        table[name] = pts
        r = json.loads(settings.set_project_settings(json.dumps({"wall_profiles": table})))
        if not r.get("ok"):
            raise ValueError(r.get("error"))
        return 1

    try:
        r = B._run_settings(action)
    except Exception as ex:
        return _fail(str(ex))
    return B._dump({**r, "name": name, "points": pts})


def opposite_slant_of(wall) -> float:
    """The opposite face's angle (D97): its own for a double-slanted wall, else the wall's slant."""
    p = _pset(wall, WALL_PSET)
    return float(p["SlantOpposite"]) if p.get("DoubleSlant") else slant_of(wall)


def _plain_body(wall, height: float):
    """A plain vertical box body (the composite's thickness, the axis' length, `height` metres), what the
    regenerator expects to rebuild from."""
    from . import authoring as A

    f = B._model
    usage = _usage(wall)
    s = A._scale()
    length = math.dist(*A._axis_world(wall))
    total = sum(float(l.LayerThickness or 0.0) for l in usage.ForLayerSet.MaterialLayers) * s
    off = float(usage.OffsetFromReferenceLine or 0.0) * s
    y0 = off if usage.DirectionSense != "NEGATIVE" else off - total
    k = 1.0 / s
    profile = f.createIfcRectangleProfileDef("AREA", None, f.createIfcAxis2Placement2D(
        f.createIfcCartesianPoint((length / 2 * k, (y0 + total / 2) * k)), None), length * k, total * k)
    solid = f.createIfcExtrudedAreaSolid(profile, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None),
                                         f.createIfcDirection((0.0, 0.0, 1.0)), height * k)
    A._replace_body(wall, f.createIfcShapeRepresentation(A._body_context(), "Body", "SweptSolid", [solid]))


def _join_ends(wall, height: float):
    """The wall's start and end lines after its joins, in its own plan coordinates (metres): ifcopenshell's
    regenerator builds a plain wall first (mitres, butts, the axis trimmed and the origin moved to its start)."""
    import importlib

    from . import authoring as A

    _plain_body(wall, height)
    A._body_context()
    A._patch_regenerator()
    importlib.import_module("ifcopenshell.api.geometry.regenerate_wall_representation")
    R = sys.modules["ifcopenshell.api.geometry.regenerate_wall_representation"]
    r = R.Regenerator(B._model)
    r.regenerate(wall, length=math.dist(*A._axis_world(wall)), height=height)
    s = A._scale()
    p1 = np.asarray(r.reference_p1, dtype=float)
    start = [(np.asarray(p, dtype=float) - p1) * s for p in r.start_points]
    end = [(np.asarray(p, dtype=float) - p1) * s for p in r.end_points]
    return start, end


def _sweep(wall, section, height: float):
    """Sweep a section ([(across, up)], metres) along the wall (D97), cut at its ends as the joins cut a
    plain wall: the solid runs past both ends and is clipped by vertical planes through the end lines."""
    from . import authoring as A

    f = B._model
    start, end = _join_ends(wall, height)
    k = 1.0 / A._scale()
    margin = max(abs(y) for y, _ in section) + 1.0
    x0 = min(p[0] for p in start + end) - margin
    x1 = max(p[0] for p in start + end) + margin
    profile = f.createIfcArbitraryClosedProfileDef("AREA", None, f.createIfcPolyline(
        [f.createIfcCartesianPoint((float(y) * k, float(z) * k)) for y, z in list(section) + [section[0]]]))
    position = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((x0 * k, 0.0, 0.0)),
                                           f.createIfcDirection((1.0, 0.0, 0.0)), f.createIfcDirection((0.0, 1.0, 0.0)))
    item = f.createIfcExtrudedAreaSolid(profile, position, f.createIfcDirection((0.0, 0.0, 1.0)), (x1 - x0) * k)
    for line, outwards in ((start, -1.0), (end, 1.0)):
        a, b = line[0], line[-1]
        d = b - a
        if np.linalg.norm(d) < 1e-9:
            continue
        n = np.array([d[1], -d[0]]) / np.linalg.norm(d)
        if n[0] * outwards < 0:
            n = -n
        plane = f.createIfcPlane(f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint((float(a[0]) * k, float(a[1]) * k, 0.0)),
            f.createIfcDirection((float(n[0]), float(n[1]), 0.0)), f.createIfcDirection((0.0, 0.0, 1.0))))
        # AgreementFlag false: the half space lies on the normal's side, beyond the end, and is cut away
        item = f.createIfcBooleanClippingResult("DIFFERENCE", item, f.createIfcHalfSpaceSolid(plane, False))
    A._replace_body(wall, f.createIfcShapeRepresentation(A._body_context(), "Body", "Clipping", [item]))


def set_double_slant(wall, reference: float, opposite: float):
    """Archicad's double-slanted wall (D97): the reference side leans at `reference` degrees from the floor,
    the opposite side at `opposite`; the body is the trapezoid section swept along the wall (joins keep it)."""
    from . import authoring as A

    usage = _usage(wall)
    axis = A._axis_world(wall)
    if usage is None or axis is None:
        raise ValueError(f"{wall.Name or 'the wall'} is not a layered wall drawn by KimBim")
    p = _pset(wall, WALL_PSET)
    if p.get("DoubleSlant"):
        height = float(p["Height"])
    else:  # the extrusion's rise (a slanted wall's depth is longer than its height)
        solids = _body_solids(wall)
        z = np.asarray(solids[0].ExtrudedDirection.DirectionRatios, dtype=float) if solids else np.array([0, 0, 1.0])
        height = A._wall_height(wall) * float(z[2] / np.linalg.norm(z))
    s = A._scale()
    total = sum(float(l.LayerThickness or 0.0) for l in usage.ForLayerSet.MaterialLayers) * s
    off = float(usage.OffsetFromReferenceLine or 0.0) * s
    y0, y1 = (off, off + total) if usage.DirectionSense != "NEGATIVE" else (off - total, off)
    top0 = y0 + height / math.tan(math.radians(reference))   # the -y face leans in for angles under 90
    top1 = y1 - height / math.tan(math.radians(opposite))
    if top1 - top0 < 0.005:
        raise ValueError("the two faces would cross below the top: choose angles nearer 90 degrees")
    _sweep(wall, [(y0, 0.0), (y1, 0.0), (top1, height), (top0, height)], height)
    _write_pset(wall, WALL_PSET, {"DoubleSlant": True, "SlantReference": float(reference),
                                  "SlantOpposite": float(opposite), "Height": float(height)})


def rebuild_double_slant(wall, length=None):  # also a complex-profile wall
    """A double-slanted wall after a stretch or a move (D97): its axis line takes `length` (metres) when
    given and its section is swept again along it, the angles and height kept."""
    from . import authoring as A

    if length is not None:
        rep = ifcopenshell.util.representation.get_representation(wall, "Plan", "Axis", "GRAPH_VIEW")
        k = 1.0 / A._scale()
        for item in (rep.Items if rep is not None else ()):
            if item.is_a("IfcPolyline") and len(item.Points) >= 2:
                first = item.Points[0].Coordinates
                item.Points[-1].Coordinates = (float(first[0]) + float(length) * k, float(first[1]))
    p = _pset(wall, WALL_PSET)
    if p.get("Profile"):
        set_profile(wall, str(p["Profile"]))
    else:
        set_double_slant(wall, float(p["SlantReference"]), float(p["SlantOpposite"]))
    return True


def clear_double_slant(wall):
    """Back to a wall the regenerator builds: a plain vertical body of the same height, then regenerated."""
    from . import authoring as A

    p = _pset(wall, WALL_PSET)
    if not p.get("DoubleSlant"):
        return
    height = float(p.get("Height") or 3.0)
    _plain_body(wall, height)
    _write_pset(wall, WALL_PSET, {"DoubleSlant": None, "SlantReference": None, "SlantOpposite": None, "Height": None})
    A._regenerate(B._model, wall, length=math.dist(*A._axis_world(wall)), height=height)


def slant_of(wall) -> float:
    """Archicad's slant angle in degrees: 90 for a vertical wall, less when it leans to its +Y side."""
    p = _pset(wall, WALL_PSET)
    if p.get("DoubleSlant"):
        return float(p["SlantReference"])
    solids = _body_solids(wall)
    if not solids:
        return 90.0
    z = np.asarray(solids[0].ExtrudedDirection.DirectionRatios, dtype=float)
    z /= np.linalg.norm(z)
    return round(90.0 - math.degrees(math.atan2(z[1], z[2])), 6)


def set_slant(wall, degrees: float):
    """Lean the wall about its reference line keeping its height (the regenerator then rebuilds it)."""
    solids = _body_solids(wall)
    if not solids:
        raise ValueError(f"{wall.Name or 'the wall'} has no body to slant")
    a = math.radians(90.0 - degrees)
    for s in solids:
        z = np.asarray(s.ExtrudedDirection.DirectionRatios, dtype=float)
        height = float(s.Depth) * (z[2] / np.linalg.norm(z))
        s.ExtrudedDirection = B._model.createIfcDirection((0.0, math.sin(a), math.cos(a)))
        s.Depth = height / math.cos(a)


# ---------------------------------------------------------------- surfaces

def sides_of(element) -> tuple:
    usage = _usage(element)
    if element.is_a("IfcWall") and usage is not None:
        return WALL_SIDES
    if element.is_a("IfcSlab") or element.is_a("IfcRoof") or (usage is not None and usage.LayerSetDirection == "AXIS3"):
        return SLAB_SIDES
    return ALL_SIDES


def surface_overrides(element) -> dict:
    """{side: surface name} for the element's overridden sides."""
    p = _pset(element, SURFACE_PSET)
    return {k: v for k, v in p.items() if k != "id" and isinstance(v, str) and v}


def apply_surface_overrides(element, verts, faces, out, palette):
    """materials.face_colours hook: paint the overridden sides (D97)."""
    from . import materials

    over = surface_overrides(element)
    if not over:
        return
    f = B._model
    looks = {}
    for side, name in over.items():
        style = materials._surface_by_name(f, name)
        if style is not None:
            looks[side] = palette.add(materials.surface_look(style))
    if not looks:
        return
    sides = sides_of(element)
    if sides == ALL_SIDES:
        if "All faces" in looks:
            out[:] = looks["All faces"]
        return
    n = materials._normals(verts, faces)
    if sides == WALL_SIDES:
        usage = _usage(element)
        axis = materials._layer_axis(element, usage) if usage is not None else None
        if axis is None:
            return
        d = n @ axis
        masks = {"Reference side": d < -materials.SIDE, "Opposite side": d > materials.SIDE}
    else:
        d = n[:, 2]
        masks = {"Top": d > materials.SIDE, "Bottom": d < -materials.SIDE}
    masks["Edges"] = ~np.logical_or.reduce([m for m in masks.values()])
    for side, index in looks.items():
        if side in masks:
            out[masks[side]] = index


# ---------------------------------------------------------------- the Properties panel's groups

def groups(elements) -> dict:
    """{group: {name: entry}} for properties_multi: Geometry (walls) and Surfaces (every element)."""
    from . import materials

    out = {}
    walls = [e for e in elements if e.is_a("IfcWall") and _usage(e) is not None]
    if walls and len(walls) == len(elements):
        refs = {reference_of(w) for w in walls}
        slants = {round(slant_of(w), 3) for w in walls}
        opposite = {round(opposite_slant_of(w), 3) for w in walls}
        out[GEOMETRY] = {
            "Reference line": _entry(refs, list(REFERENCES) + ([CUSTOM] if CUSTOM in refs else []), "IfcLabel"),
            "Slant angle": _entry(slants, None, "IfcPlaneAngleMeasure"),
            "Opposite slant angle": _entry(opposite, None, "IfcPlaneAngleMeasure"),  # D97: double slanted
            "Profile": _entry({profile_of(w) or NO_PROFILE for w in walls}, [NO_PROFILE, *profiles()], "IfcLabel"),
        }
    things = [e for e in elements if e.is_a("IfcElement") and not e.is_a("IfcOpeningElement")]
    if things and len(things) == len(elements):
        kinds = {sides_of(e) for e in things}
        if len(kinds) == 1:
            names = [FROM_MATERIAL] + [s.Name for s in B._model.by_type("IfcSurfaceStyle") if s.Name]
            group = {}
            for side in next(iter(kinds)):
                values = {surface_overrides(e).get(side, FROM_MATERIAL) for e in things}
                group[side] = _entry(values, names, "IfcLabel")
            out[SURFACES] = group
    return out


def _entry(values: set, choices, ifc_type) -> dict:
    varies = len(values) > 1
    e = {"value": None if varies else next(iter(values)), "varies": varies, "ifc_type": ifc_type,
         "editable": True, "source": "dimension", "type_value": None}
    if choices is not None:
        e["choices"] = choices
    return e


def set_element_setting(guids_json: str, group: str, name: str, value) -> str:
    """Edit a Geometry or Surfaces entry for the selection as one undo step."""
    if B._model is None:
        return _fail("no model open")
    elements = B._elements(guids_json)
    if not elements:
        return _fail("nothing selected")
    if group == GEOMETRY and name == "Reference line":
        if value not in REFERENCES:
            return _fail(f"unknown reference line {value}")
        walls = [e for e in elements if e.is_a("IfcWall") and _usage(e) is not None]

        def action():
            for w in walls:
                apply_reference(w, value)
            touched = _regenerate_with_neighbours(walls)
            return len(walls), [w.GlobalId for w in touched], []
    elif group == GEOMETRY and name in ("Slant angle", "Opposite slant angle"):
        try:
            degrees = float(str(value).replace(",", "."))
        except ValueError:
            return _fail(f"not a number: {value}")
        if not SLANT_MIN <= degrees <= SLANT_MAX:
            return _fail(f"the slant angle must be between {SLANT_MIN:g} and {SLANT_MAX:g} degrees")
        walls = [e for e in elements if e.is_a("IfcWall") and _usage(e) is not None
                 and not _pset(e, WALL_PSET).get("Arc")]  # curved walls stay upright, on their arc

        def action():
            for w in walls:
                if name == "Slant angle":  # the whole wall leans (or a double-slanted wall's reference face)
                    if is_double_slanted(w):
                        set_double_slant(w, degrees, opposite_slant_of(w))
                    else:
                        set_slant(w, degrees)
                    continue
                ref = slant_of(w)  # the opposite face: its own angle makes the wall double slanted
                if abs(degrees - ref) < 1e-6:
                    if is_double_slanted(w):
                        clear_double_slant(w)
                        if abs(ref - 90.0) > 1e-6:
                            set_slant(w, ref)
                else:
                    set_double_slant(w, ref, degrees)
            touched = _regenerate_with_neighbours(walls)
            return len(walls), [w.GlobalId for w in touched], []
    elif group == GEOMETRY and name == "Profile":
        if value != NO_PROFILE and value not in profiles():
            return _fail(f"unknown wall profile {value}")
        walls = [e for e in elements if e.is_a("IfcWall") and _usage(e) is not None
                 and not _pset(e, WALL_PSET).get("Arc")]  # curved walls stay upright, on their arc

        def action():
            for w in walls:
                if value == NO_PROFILE:
                    if profile_of(w):
                        height = float(_pset(w, WALL_PSET).get("Height") or 3.0)
                        _write_pset(w, WALL_PSET, {"Profile": None, "DoubleSlant": True, "Height": height,
                                                   "SlantReference": 90.0, "SlantOpposite": 90.0})
                        clear_double_slant(w)  # a plain wall again, the profile's height kept
                else:
                    if is_double_slanted(w) and not profile_of(w):
                        _write_pset(w, WALL_PSET, {"DoubleSlant": None, "SlantReference": None, "SlantOpposite": None})
                    set_profile(w, value)
            touched = _regenerate_with_neighbours(walls)
            return len(walls), [w.GlobalId for w in touched], []
    elif group == SURFACES:
        from . import materials

        surface = "" if value in (None, "", FROM_MATERIAL) else str(value)
        if surface and materials._surface_by_name(B._model, surface) is None:
            return _fail(f"unknown surface {surface}")
        bad = [e for e in elements if name not in sides_of(e)]
        if bad:
            return _fail(f"{name} is not a side of {bad[0].Name or bad[0].is_a()}")

        def action():
            for e in elements:
                _write_pset(e, SURFACE_PSET, {name: surface or None})
            return len(elements), [e.GlobalId for e in elements], []
    else:
        return _fail(f"unknown setting {group} / {name}")
    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(str(ex) if isinstance(ex, ValueError) else f"{type(ex).__name__}: {ex}")
    return B._dump(r)


JUNCTIONS = ("through", "butt", "materials")  # D97: at its joins a wall runs through, stops, or its layers decide


def set_junctions(guids_json: str, mode: str) -> str:
    """Archicad's junction override, per wall (D97): at every join of the selected walls, "through" makes
    all their layers win (priority 100), "butt" makes them give way (0), "materials" goes back to the
    layers' own priorities (D96). Stored on IfcRelConnectsPathElements' Relating/RelatedPriorities."""
    if B._model is None:
        return _fail("no model open")
    if mode not in JUNCTIONS:
        return _fail(f"unknown junction {mode}")
    walls = [e for e in B._elements(guids_json) if e.is_a("IfcWall") and _usage(e) is not None]
    if not walls:
        return _fail("select layered walls")

    def action():
        rels = set()
        for w in walls:
            n = len(_usage(w).ForLayerSet.MaterialLayers or ())
            value = None if mode == "materials" else [100 if mode == "through" else 0] * n
            for rel in list(w.ConnectedTo or ()) + list(w.ConnectedFrom or ()):
                if not rel.is_a("IfcRelConnectsPathElements"):
                    continue
                if rel.RelatingElement == w:
                    rel.RelatingPriorities = value or []
                else:
                    rel.RelatedPriorities = value or []
                rels.add(rel)
        touched = _regenerate_with_neighbours(walls)
        return len(rels), [w.GlobalId for w in touched], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def flip_walls(guids_json: str) -> str:
    """Model > Flip: mirror the selected walls' composites about their reference lines (one undo step)."""
    if B._model is None:
        return _fail("no model open")
    walls = [e for e in B._elements(guids_json) if e.is_a("IfcWall") and _usage(e) is not None]
    if not walls:
        return _fail("select layered walls to flip")

    def action():
        for w in walls:
            flip(w)
        touched = _regenerate_with_neighbours(walls)
        return len(walls), [w.GlobalId for w in touched], []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def wall_options() -> str:
    """The Wall tool's reference line choices and the project's default (D97)."""
    from . import settings

    st = settings.current()
    return B._dump({"ok": True, "references": list(REFERENCES),
                    "default": st.get("wall_reference_line", "Outside face")})


# ---------------------------------------------------------------- pick up and inject (D97)
# Archicad's Pick Up / Inject Parameters (the eyedropper and the syringe): one element's settings,
# applied to others of the same kind in one undo step.

def _kind(e) -> str:
    from . import library

    if e.is_a("IfcWall"):
        return "wall"
    if e.is_a("IfcSlab"):
        return "slab"
    if library.is_object(e):
        return "object"
    return "element"


def pick_up(guid: str) -> str:
    """{ok, kind, settings}: what Inject gives other elements of this kind."""
    from . import library, materials

    if B._model is None:
        return _fail("no model open")
    try:
        e = B._model.by_guid(guid)
    except RuntimeError:
        return _fail(f"unknown element {guid}")
    kind = _kind(e)
    st = {"surfaces": surface_overrides(e)}
    info = materials._info(e)
    if info["kind"] == "composite":
        st["composite"] = info["name"]
    elif info["editable"] and info["name"]:
        st["material"] = info["name"]
    if kind == "wall" and _usage(e) is not None:
        st.update(reference=reference_of(e), slant=slant_of(e), opposite=opposite_slant_of(e), profile=profile_of(e))
    if kind == "object":
        obj, values, _t = library._object_of(e)
        st.update(object=obj.key, parameters=values)
    return B._dump({"ok": True, "kind": kind, "name": e.Name or e.is_a(), "settings": st})


def inject(guids_json: str, picked_json: str) -> str:
    """Give the picked-up settings to the selected elements of the same kind: one undo step (library
    objects: one per parameter, through set_object_parameter, so their types follow)."""
    from . import library, materials

    if B._model is None:
        return _fail("no model open")
    try:
        picked = json.loads(picked_json)
        st, kind = picked["settings"], picked["kind"]
    except (ValueError, KeyError, TypeError):
        return _fail("nothing picked up")
    targets = [e for e in B._elements(guids_json) if _kind(e) == kind]
    if not targets:
        return _fail(f"select {kind}s to inject into")
    f = B._model

    def action():
        touched = set(targets)
        for e in targets:
            if st.get("composite") and materials._info(e).get("kind") == "composite":
                ls = next((x for x in f.by_type("IfcMaterialLayerSet") if x.LayerSetName == st["composite"]), None)
                t = materials._composite_type(ls) if ls is not None else None
                if t is not None and ifcopenshell.util.element.get_type(e) != t:
                    ifcopenshell.api.type.assign_type(f, related_objects=[e], relating_type=t)
                    materials._reshape(f, e, touched)
            if st.get("material") and kind not in ("wall", "slab", "object"):
                m = materials._material_by_name(f, st["material"])
                if m is not None:
                    ifcopenshell.api.material.unassign_material(f, products=[e])
                    ifcopenshell.api.material.assign_material(f, products=[e], material=m)
            if kind == "wall" and _usage(e) is not None:
                if st.get("profile") and st["profile"] in profiles():
                    set_profile(e, st["profile"])
                else:
                    if st.get("reference") in REFERENCES:
                        apply_reference(e, st["reference"])
                    if abs(float(st.get("opposite", 90)) - float(st.get("slant", 90))) > 1e-6:
                        set_double_slant(e, float(st["slant"]), float(st["opposite"]))
                    else:
                        if is_double_slanted(e):
                            clear_double_slant(e)
                        if st.get("slant") is not None:
                            set_slant(e, float(st["slant"]))
            sides = sides_of(e)
            over = {side: st.get("surfaces", {}).get(side) for side in sides}
            _write_pset(e, SURFACE_PSET, {side: (name or None) for side, name in over.items()})
        if kind == "wall":
            touched.update(_regenerate_with_neighbours([e for e in targets if _usage(e) is not None]))
        return len(targets), [e.GlobalId for e in touched], []

    try:
        if kind == "object":  # the parameters (sizes, part materials): the object's own command per value
            obj_key = st.get("object")
            same = [e for e in targets if library._object_of(e) and library._object_of(e)[0].key == obj_key]
            if not same:
                return _fail("select objects of the same kind to inject into")
            for name, value in (st.get("parameters") or {}).items():
                r = json.loads(library.set_object_parameter(json.dumps([e.GlobalId for e in same]), name, value, "selection"))
                if not r.get("ok"):
                    return B._dump(r)
            return B._dump({"ok": True, "changed": len(same), "geometry": {"changed": [e.GlobalId for e in same], "removed": []}})
        r = B._run(action)
    except Exception as ex:
        return _fail(str(ex) if isinstance(ex, ValueError) else f"{type(ex).__name__}: {ex}")
    return B._dump(r)
