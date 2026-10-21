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

import ifcopenshell
import ifcopenshell.api.pset
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
    return bool(_pset(wall, WALL_PSET).get("DoubleSlant"))


def opposite_slant_of(wall) -> float:
    """The opposite face's angle (D97): its own for a double-slanted wall, else the wall's slant."""
    p = _pset(wall, WALL_PSET)
    return float(p["SlantOpposite"]) if p.get("DoubleSlant") else slant_of(wall)


def set_double_slant(wall, reference: float, opposite: float):
    """Archicad's double-slanted wall (D97): the reference side leans at `reference` degrees from the floor,
    the opposite side at `opposite`; the body is the trapezoid section swept along the wall (joins keep it)."""
    from . import authoring as A

    import ifcopenshell.api.geometry

    f = B._model
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
    length = math.dist(*axis)
    s = A._scale()
    total = sum(float(l.LayerThickness or 0.0) for l in usage.ForLayerSet.MaterialLayers) * s
    off = float(usage.OffsetFromReferenceLine or 0.0) * s
    y0, y1 = (off, off + total) if usage.DirectionSense != "NEGATIVE" else (off - total, off)
    top0 = y0 + height / math.tan(math.radians(reference))   # the -y face leans in for angles under 90
    top1 = y1 - height / math.tan(math.radians(opposite))
    if top1 - top0 < 0.005:
        raise ValueError("the two faces would cross below the top: choose angles nearer 90 degrees")
    k = 1.0 / s
    pts = [(y0, 0.0), (y1, 0.0), (top1, height), (top0, height)]
    profile = f.createIfcArbitraryClosedProfileDef("AREA", None, f.createIfcPolyline(
        [f.createIfcCartesianPoint((y * k, z * k)) for y, z in pts + pts[:1]]))
    position = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)),
                                           f.createIfcDirection((1.0, 0.0, 0.0)), f.createIfcDirection((0.0, 1.0, 0.0)))
    solid = f.createIfcExtrudedAreaSolid(profile, position, f.createIfcDirection((0.0, 0.0, 1.0)), length * k)
    rep = f.createIfcShapeRepresentation(A._body_context(), "Body", "SweptSolid", [solid])
    A._replace_body(wall, rep)
    _write_pset(wall, WALL_PSET, {"DoubleSlant": True, "SlantReference": float(reference),
                                  "SlantOpposite": float(opposite), "Height": float(height)})


def clear_double_slant(wall):
    """Back to a wall the regenerator builds: a plain vertical body of the same height, then regenerated."""
    from . import authoring as A

    p = _pset(wall, WALL_PSET)
    if not p.get("DoubleSlant"):
        return
    f = B._model
    height = float(p.get("Height") or 3.0)
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
    _write_pset(wall, WALL_PSET, {"DoubleSlant": None, "SlantReference": None, "SlantOpposite": None, "Height": None})
    A._regenerate(f, wall, length=length, height=height)


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
        walls = [e for e in elements if e.is_a("IfcWall") and _usage(e) is not None]

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
