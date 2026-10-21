# SPDX-License-Identifier: GPL-3.0-or-later
"""Surfaces, building materials and composites (D96, Archicad's element attributes).

Stored where IFC keeps them, so other tools see them: a surface is an ``IfcSurfaceStyle`` with an
``IfcSurfaceStyleRendering``; a building material is an ``IfcMaterial`` whose surface is attached
through its ``IfcMaterialDefinitionRepresentation`` (what viewers and the geometry iterator read);
the cut fill, intersection priority, ID and manufacturer live in the ``KIMBIM_Material`` material
pset and the physical data in ``Pset_MaterialCommon`` / ``Pset_MaterialThermal``. A composite is an
``IfcMaterialLayerSet``; its core layers have ``Category = "LoadBearing"`` (IFC4).

The 3D view colours each triangle from these (``face_colours``): a layered wall shows its first and
last layers' surfaces on its two sides and the core's on its edges, other elements their IFC styles
or their material's surface.
"""
from __future__ import annotations

import json
import math

import ifcopenshell
import ifcopenshell.api.material
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.style
import ifcopenshell.api.type
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import numpy as np

from . import app_bridge as B

PSET = "KIMBIM_Material"
NO_COLOUR = 0xFFFF  # a face without a surface: the 3D view uses the element's class colour
REFLECTANCE = ("MATT", "PLASTIC", "METAL", "GLASS", "MIRROR", "PHONG", "FLAT", "NOTDEFINED")
CORE = "LoadBearing"  # IFC4's recommended IfcMaterialLayer.Category for a structural (core) layer
DEFAULT_PRIORITY = 500
SIDE = 0.7  # |cos| above which a face looks to a side of the layer stack (about 45 degrees)

# Archicad-like template, simplified. surface: (colour, transparency 0-1, shine 0-1, reflectance);
# pen: cut fill pen (role pens, so pen sets restyle them), bg: background pen; pattern: D84 table;
# density kg/m3, conductivity W/(m K), heat J/(kg K). The default wall and slab types use the first six.
CATALOGUE = {
    "Generic": dict(colour="#d9d4cc", pen=12, pattern="Solid", priority=500, density=1800, conductivity=1.0, heat=1000, category="Generic"),
    "Brick": dict(colour="#b5654a", pen=12, pattern="Brick", priority=600, density=1800, conductivity=0.77, heat=840, category="Masonry"),
    "Insulation": dict(colour="#f2e27a", pen=12, pattern="Insulation", priority=100, density=30, conductivity=0.035, heat=1030, category="Insulation"),
    "Block": dict(colour="#b7b4ad", pen=12, pattern="Crosshatch", priority=600, density=1400, conductivity=0.5, heat=1000, category="Masonry"),
    "Concrete": dict(colour="#a8a8a4", pen=15, pattern="Concrete", priority=800, density=2400, conductivity=2.0, heat=1000, category="Concrete"),
    "Screed": dict(colour="#c4c0b8", pen=15, pattern="Concrete", priority=400, density=2000, conductivity=1.4, heat=1000, category="Concrete"),
    "Plaster": dict(colour="#f0ede6", pen=12, pattern="Solid", priority=200, density=1300, conductivity=0.57, heat=1000, category="Finish"),
    "Gypsum board": dict(colour="#f4f2ee", pen=12, pattern="Diagonal", priority=300, density=900, conductivity=0.25, heat=1000, category="Finish"),
    "Insulation - rigid": dict(colour="#c8d8f0", pen=12, pattern="Zigzag", priority=100, density=30, conductivity=0.033, heat=1450, category="Insulation"),
    "Timber": dict(colour="#c49a6c", pen=12, pattern="Diagonal", priority=550, density=500, conductivity=0.13, heat=1600, category="Wood"),
    "Timber - finish": dict(colour="#d8b48a", shine=0.4, reflectance="PLASTIC", pen=12, pattern="Diagonal", priority=250, density=600, conductivity=0.15, heat=1600, category="Wood"),
    "Steel": dict(colour="#8a9099", shine=0.7, reflectance="METAL", pen=15, pattern="Solid", priority=900, density=7850, conductivity=50.0, heat=450, category="Metal"),
    "Aluminium": dict(colour="#c6cacf", shine=0.7, reflectance="METAL", pen=15, pattern="Solid", priority=850, density=2700, conductivity=160.0, heat=880, category="Metal"),
    "Glass": dict(colour="#a9cde0", transparency=0.6, shine=0.9, reflectance="GLASS", pen=12, pattern="Empty", priority=200, density=2500, conductivity=1.0, heat=750, category="Glass"),
    "Stone": dict(colour="#c9c1b0", pen=12, pattern="Crosshatch", priority=700, density=2600, conductivity=2.3, heat=1000, category="Masonry"),
    "Ceramic tiles": dict(colour="#e6e2da", shine=0.5, reflectance="PLASTIC", pen=12, pattern="Horizontal", priority=250, density=2300, conductivity=1.3, heat=840, category="Finish"),
    "Air gap": dict(colour="#ffffff", transparency=0.0, pen=12, pattern="Empty", priority=0, density=1.2, conductivity=0.025, heat=1000, category="Air"),
    "Membrane": dict(colour="#3c3c3c", pen=12, pattern="Solid", priority=150, density=1100, conductivity=0.2, heat=1000, category="Membrane"),
    "Soil": dict(colour="#8a6a4a", pen=12, pattern="Diagonal", priority=50, density=1600, conductivity=1.5, heat=1200, category="Earth"),
    "Roof tiles": dict(colour="#a8553a", pen=15, pattern="Diagonal", priority=650, density=1900, conductivity=1.0, heat=800, category="Roofing"),
    "Porcelain": dict(colour="#f6f6f3", shine=0.8, reflectance="PLASTIC", pen=12, pattern="Solid", priority=300, density=2400, conductivity=1.5, heat=1080, category="Ceramic"),
    "Fabric": dict(colour="#7d8a99", shine=0.0, reflectance="MATT", pen=12, pattern="Empty", priority=100, density=300, conductivity=0.05, heat=1300, category="Textile"),
    "Paint - white": dict(colour="#fbfbf8", pen=12, pattern="Solid", priority=100, density=1200, conductivity=0.2, heat=1000, category="Finish"),
}

_MATERIAL_FIELDS = {  # field -> (pset, property)
    "pen": (PSET, "CutFillPen"), "bg": (PSET, "CutBackgroundPen"), "pattern": (PSET, "CutFillPattern"),
    "priority": (PSET, "Priority"), "identifier": (PSET, "Identifier"), "manufacturer": (PSET, "Manufacturer"),
    "density": ("Pset_MaterialCommon", "MassDensity"),
    "conductivity": ("Pset_MaterialThermal", "ThermalConductivity"),
    "heat": ("Pset_MaterialThermal", "SpecificHeatCapacity"),
}
_INTS = {"pen", "bg", "priority"}
_FLOATS = {"density", "conductivity", "heat"}


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def _ifc4(f) -> bool:
    return f.schema != "IFC2X3"


# ---------------------------------------------------------------- colours

def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(float(c) * 255))) for c in rgb)


def _rgb(text: str) -> tuple:
    text = text.lstrip("#")
    return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _shading(style):
    """The surface style's shading/rendering item, or None."""
    for item in getattr(style, "Styles", None) or ():
        if item.is_a("IfcSurfaceStyleShading"):  # IfcSurfaceStyleRendering is a subtype
            return item
    return None


def surface_look(style) -> dict | None:
    """{colour, transparency, shine, reflectance} of an IfcSurfaceStyle, or None without a colour."""
    sh = _shading(style)
    if sh is None or sh.SurfaceColour is None:
        return None
    c = sh.SurfaceColour
    look = {"colour": _hex((c.Red, c.Green, c.Blue)), "transparency": 0.0, "shine": 0.0, "reflectance": "NOTDEFINED"}
    t = getattr(sh, "Transparency", None)
    if t is not None:
        look["transparency"] = float(t)
    if sh.is_a("IfcSurfaceStyleRendering"):
        if sh.Transparency is not None:
            look["transparency"] = float(sh.Transparency)
        hl = sh.SpecularHighlight
        if hl is not None and hl.is_a("IfcSpecularRoughness"):
            look["shine"] = max(0.0, min(1.0, 1.0 - float(hl.wrappedValue)))
        look["reflectance"] = sh.ReflectanceMethod or "NOTDEFINED"
    look.update(texture_of(style))
    return look


def texture_of(style) -> dict:
    """{texture (a project file name), texture_size [w, h] metres} of a surface's image texture, or {}."""
    for item in getattr(style, "Styles", None) or ():
        if not item.is_a("IfcSurfaceStyleWithTextures"):
            continue
        for tex in item.Textures or ():
            url = getattr(tex, "URLReference", None) or getattr(tex, "UrlReference", None) if tex.is_a("IfcImageTexture") else None
            if url:
                size = [1.0, 1.0]
                op = getattr(tex, "TextureTransform", None)
                if op is not None and op.Scale:
                    size = [float(op.Scale), float(getattr(op, "Scale2", None) or op.Scale)]
                return {"texture": url, "texture_size": size}
    return {}


def _write_texture(f, style, look: dict):
    """D96: the surface's image texture (Archicad's surface texture): an IfcSurfaceStyleWithTextures with
    an IfcImageTexture naming a file in the project's store, repeated every `texture_size` metres.
    `texture_path` (a picture to copy in), `texture` (a stored name) or neither (no texture)."""
    import pathlib
    import shutil

    from . import underlays

    name = look.get("texture") or ""
    src = look.get("texture_path") or ""
    if src:
        p = pathlib.Path(src)
        if not p.is_file():
            raise ValueError(f"no such picture: {src}")
        underlays._image_size(p)  # a PNG or JPEG, or it raises
        data = p.read_bytes()
        name = underlays.blob_name(data, ".png" if data[:4] == b"\x89PNG" else ".jpg")
        store = underlays.store_dir()
        store.mkdir(parents=True, exist_ok=True)
        if not (store / name).is_file():
            shutil.copyfile(p, store / name)
    for item in list(style.Styles or ()):
        if item.is_a("IfcSurfaceStyleWithTextures"):
            style.Styles = [s for s in style.Styles if s != item]
            for tex in item.Textures or ():
                if getattr(tex, "TextureTransform", None) is not None:
                    f.remove(tex.TextureTransform)
                f.remove(tex)
            f.remove(item)
    if not name:
        return
    w, h = (float(v) for v in (look.get("texture_size") or [1.0, 1.0])[:2])
    if w <= 0 or h <= 0:
        raise ValueError("a texture's size must be positive")
    op = f.createIfcCartesianTransformationOperator2DnonUniform(
        None, None, f.createIfcCartesianPoint((0.0, 0.0)), w, h)
    if f.schema == "IFC2X3":  # IFC2X3 spells it UrlReference and names the texture's use
        tex = f.create_entity("IfcImageTexture", RepeatS=True, RepeatT=True, TextureType="TEXTURE",
                              TextureTransform=op, UrlReference=name)
    else:
        tex = f.create_entity("IfcImageTexture", RepeatS=True, RepeatT=True, Mode="MODULATE",
                              TextureTransform=op, URLReference=name)
    style.Styles = list(style.Styles or ()) + [f.createIfcSurfaceStyleWithTextures([tex])]


def texture_files(f=None) -> list:
    """Every texture file the model's surfaces use (kept in the settings, so versions and .kim files carry them)."""
    f = B._model if f is None else f
    names = set()
    for st in f.by_type("IfcSurfaceStyle"):
        t = texture_of(st).get("texture")
        if t:
            names.add(t)
    return sorted(names)


def _sync_texture_files():
    from . import settings as S

    names = texture_files()
    if S.current().get("texture_files", []) != names:
        st = S.current()
        st["texture_files"] = names
        S.restore(st)


def _styles_of_item(item):
    """Surface styles of an IfcStyledItem (IFC4 direct, IFC2X3 through presentation style assignments)."""
    for s in item.Styles or ():
        if s.is_a("IfcSurfaceStyle"):
            yield s
        elif s.is_a("IfcPresentationStyleAssignment"):
            yield from (x for x in s.Styles or () if x.is_a("IfcSurfaceStyle"))


def surface_of(material):
    """The IfcSurfaceStyle attached to a material, or None."""
    for rep in getattr(material, "HasRepresentation", None) or ():
        for r in rep.Representations or ():
            for item in r.Items or ():
                if item.is_a("IfcStyledItem"):
                    for s in _styles_of_item(item):
                        return s
    return None


def core_layer(layer_set):
    """The core layer: the thickest LoadBearing one, else the thickest."""
    layers = list(layer_set.MaterialLayers or ())
    if not layers:
        return None
    core = [l for l in layers if getattr(l, "Category", None) == CORE]
    return max(core or layers, key=lambda l: float(l.LayerThickness or 0.0))


def main_material(element):
    """The element's building material for fills and the default surface: its single material, the
    core layer's, the first profile's or the first constituent's (None without one)."""
    m = ifcopenshell.util.element.get_material(element, should_skip_usage=True)
    if m is None:
        return None
    if m.is_a("IfcMaterial"):
        return m
    if m.is_a("IfcMaterialLayerSet"):
        core = core_layer(m)
        return core.Material if core is not None else None
    if m.is_a("IfcMaterialProfileSet"):
        return next((p.Material for p in m.MaterialProfiles or () if p.Material), None)
    if m.is_a("IfcMaterialConstituentSet"):
        return next((c.Material for c in m.MaterialConstituents or () if c.Material), None)
    if m.is_a("IfcMaterialList"):
        return next(iter(m.Materials or ()), None)
    return None


def properties(material) -> dict:
    """The material's KimBim fields read from its psets ({} when it has none)."""
    psets = ifcopenshell.util.element.get_psets(material)
    out = {}
    for field, (pset, prop) in _MATERIAL_FIELDS.items():
        v = psets.get(pset, {}).get(prop)
        if v is not None:
            out[field] = v
    return out


# ---------------------------------------------------------------- face colours (3D)

class Palette:
    """The colours of one mesh chunk: [r, g, b, transparency] rows (plus [texture path, width m, height m]
    for a textured surface, D96), deduplicated."""

    def __init__(self):
        self.rows: list = []
        self._index: dict = {}
        self._material: dict = {}  # material id -> palette index (or NO_COLOUR)

    def add(self, look: dict | None) -> int:
        if not look:
            return NO_COLOUR
        r, g, b = _rgb(look["colour"])
        row = [round(r, 4), round(g, 4), round(b, 4), round(float(look.get("transparency") or 0.0), 4)]
        if look.get("texture"):
            from . import underlays

            p = underlays.local_path(look["texture"])  # the meshing thread never reads the history
            if p is not None:
                w, h = (look.get("texture_size") or [1.0, 1.0])[:2]
                row += [str(p), float(w), float(h)]
        key = tuple(row)
        if key not in self._index:
            if len(self.rows) >= NO_COLOUR:
                return NO_COLOUR
            self._index[key] = len(self.rows)
            self.rows.append(row)
        return self._index[key]

    def of_material(self, material) -> int:
        if material is None:
            return NO_COLOUR
        hit = self._material.get(material.id())
        if hit is None:
            style = surface_of(material)
            hit = self.add(surface_look(style) if style is not None else None)
            self._material[material.id()] = hit
        return hit


def _normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    tri = verts.reshape(-1, 3)[faces.reshape(-1, 3)]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(n, axis=1)
    length[length == 0] = 1.0
    return n / length[:, None]


def _iterator_colours(geometry, palette: Palette, n: int):
    """Per-face palette indices from the iterator's styles, None where the file gives no style."""
    mats = list(geometry.materials)
    ids = np.asarray(geometry.material_ids, dtype=np.int64)
    if not mats or len(ids) != n:
        return None
    table = []
    for m in mats:
        styled = m.instance_id() != 0 if hasattr(m, "instance_id") else "-" in (m.name or "")
        if not styled:
            table.append(NO_COLOUR)
            continue
        d = m.diffuse.components
        t = m.transparency
        table.append(palette.add({"colour": _hex(d), "transparency": 0.0 if t is None or math.isnan(t) else float(t)}))
    table = np.asarray(table, dtype=np.uint32)
    out = np.full(n, NO_COLOUR, dtype=np.uint32)
    ok = (ids >= 0) & (ids < len(table))
    out[ok] = table[ids[ok]]
    return out


def _layer_axis(element, usage):
    """World direction the layers stack along (first layer at the most negative side), or None."""
    if element.ObjectPlacement is None:
        return None
    m = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
    column = {"AXIS1": 0, "AXIS2": 1, "AXIS3": 2}.get(usage.LayerSetDirection)
    if column is None:
        return None
    axis = np.asarray(m[:3, column], dtype=float)
    length = np.linalg.norm(axis)
    if length == 0:
        return None
    return axis / length * (-1.0 if usage.DirectionSense == "NEGATIVE" else 1.0)


def face_colours(element, geometry, verts: np.ndarray, faces: np.ndarray, palette: Palette, overrides=None) -> np.ndarray:
    """One palette index per triangle of `element` (D96). `verts`/`faces` are the iterator's arrays."""
    n = len(faces) // 3
    out = np.full(n, NO_COLOUR, dtype=np.uint32)
    if n == 0:
        return out
    usage = ifcopenshell.util.element.get_material(element, should_skip_usage=False)
    layer_set = usage.ForLayerSet if usage is not None and usage.is_a("IfcMaterialLayerSetUsage") else None
    if layer_set is not None and layer_set.MaterialLayers:
        axis = _layer_axis(element, usage)
        layers = list(layer_set.MaterialLayers)
        core = core_layer(layer_set)
        out[:] = palette.of_material(core.Material if core else None)
        if axis is not None:
            d = _normals(verts, faces) @ axis
            out[d < -SIDE] = palette.of_material(layers[0].Material)
            out[d > SIDE] = palette.of_material(layers[-1].Material)
    else:
        styled = _iterator_colours(geometry, palette, n) if geometry is not None else None
        if styled is not None:
            out = styled
        missing = out == NO_COLOUR
        if missing.any():
            out[missing] = palette.of_material(main_material(element))
    if overrides is None:
        from . import configure

        overrides = configure.apply_surface_overrides  # D97: per-side surface overrides
    overrides(element, verts, faces, out, palette)
    return out


def layer_bands(element) -> dict | None:
    """Where a layered element's layers are (D96, Archicad's composite cut): {origin (world metres),
    axis (unit, the local layer axis), bounds (metres along the axis from the origin: one more than
    the layers, in layer order), materials (one per layer)}, or None for fewer than two layers."""
    usage = ifcopenshell.util.element.get_material(element, should_skip_usage=False)
    if usage is None or not usage.is_a("IfcMaterialLayerSetUsage") or element.ObjectPlacement is None:
        return None
    layers = list(usage.ForLayerSet.MaterialLayers or ())
    column = {"AXIS1": 0, "AXIS2": 1, "AXIS3": 2}.get(usage.LayerSetDirection)
    if len(layers) < 2 or column is None:
        return None
    from . import authoring

    s = authoring._scale()
    m = ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement)
    axis = np.asarray(m[:3, column], dtype=float)
    length = np.linalg.norm(axis)
    if length == 0:
        return None
    sense = -1.0 if usage.DirectionSense == "NEGATIVE" else 1.0
    bound = float(usage.OffsetFromReferenceLine or 0.0) * s
    bounds = [bound]
    for layer in layers:
        bound += sense * float(layer.LayerThickness or 0.0) * s
        bounds.append(bound)
    return {"origin": [float(v) * s for v in m[:3, 3]], "axis": (axis / length).tolist(), "bounds": bounds,
            "materials": [l.Material for l in layers], "sense": usage.DirectionSense}


def _clip_scalar(poly, svals, lo, hi):
    """The part of a polygon (points with a scalar each) where lo <= s <= hi: (points, scalars)."""
    for bound, keep_above in ((lo, True), (hi, False)):
        out_p, out_s = [], []
        n = len(poly)
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            sa, sb = svals[i], svals[(i + 1) % n]
            ina = sa >= bound - 1e-9 if keep_above else sa <= bound + 1e-9
            inb = sb >= bound - 1e-9 if keep_above else sb <= bound + 1e-9
            if ina:
                out_p.append(a)
                out_s.append(sa)
            if ina != inb:
                t = (bound - sa) / (sb - sa)
                out_p.append(a + (b - a) * t)
                out_s.append(bound)
        poly, svals = out_p, out_s
        if len(poly) < 3:
            return [], []
    return poly, svals


def _area(poly) -> float:
    """Area of a planar 3D polygon."""
    total = np.zeros(3)
    for i in range(1, len(poly) - 1):
        total += np.cross(poly[i] - poly[0], poly[i + 1] - poly[0])
    return float(np.linalg.norm(total)) / 2


def layered_mesh(element, verts: np.ndarray, faces: np.ndarray, palette: "Palette"):
    """D96: a layered element's mesh with its ends, top, bottom and reveals cut at the layer boundaries,
    each piece in its layer's surface (Archicad shows the layers there), the sides as face_colours does.
    (verts, faces, colours), or None when the element has fewer than two layers."""
    from . import configure

    if configure.profile_of(element):  # a complex profile's section is not its composite's layers
        return None
    bands = layer_bands(element)
    if bands is None:
        return None
    sense = -1.0 if bands["sense"] == "NEGATIVE" else 1.0
    signed = np.asarray(bands["axis"]) * sense  # face_colours' _layer_axis, without a second placement
    layers = bands["materials"]
    colours_of = [palette.of_material(m) for m in layers]
    v = verts.reshape(-1, 3).astype(float)
    tri = faces.reshape(-1, 3)
    d = _normals(verts, faces) @ signed
    sides = np.abs(d) > SIDE
    # the sides: the first layer's surface on one, the last's on the other (face_colours' rule)
    side_tris = tri[sides]
    side_cols = np.where(d[sides] < 0, colours_of[0], colours_of[-1]).astype(np.uint32)
    origin, axis = np.asarray(bands["origin"]), np.asarray(bands["axis"])
    bounds = bands["bounds"]
    s_all = (v - origin) @ axis
    out_v, out_t, out_c = [v[side_tris.reshape(-1)]], [], [side_cols]
    count = len(side_tris) * 3
    extra_v, extra_t, extra_c = [], [], []
    core = core_layer(usage.ForLayerSet) if (usage := ifcopenshell.util.element.get_material(
        element, should_skip_usage=False)) is not None else None
    core_colour = palette.of_material(core.Material if core is not None else None)
    lo_all, hi_all = min(bounds), max(bounds)
    for a, b, c in tri[~sides]:  # ends, top, bottom, reveals: a few per wall
        pts, sv = [v[a], v[b], v[c]], [s_all[a], s_all[b], s_all[c]]
        outside = ()
        if min(sv) < lo_all - 1e-6 or max(sv) > hi_all + 1e-6:  # beyond the layers (odd bodies): the core
            outside = ((-1e9, lo_all), (hi_all, 1e9))
        for lo, hi in outside:
            piece, _ = _clip_scalar(pts, sv, lo, hi)
            if len(piece) >= 3 and _area(piece) > 1e-9:
                base = count + len(extra_v)
                extra_v += piece
                for j in range(1, len(piece) - 1):
                    extra_t.append((base, base + j, base + j + 1))
                    extra_c.append(core_colour)
        for k in range(len(layers)):
            lo, hi = sorted(bounds[k:k + 2])
            piece, _ = _clip_scalar(pts, sv, lo, hi)
            if len(piece) < 3:
                continue
            base = count + len(extra_v)
            extra_v += piece
            for j in range(1, len(piece) - 1):  # a convex piece: a fan
                extra_t.append((base, base + j, base + j + 1))
                extra_c.append(colours_of[k])
    nv = np.concatenate([out_v[0], np.asarray(extra_v, dtype=float).reshape(-1, 3)]) if extra_v else out_v[0]
    side_index = np.arange(count, dtype=np.uint32).reshape(-1, 3)
    nt = np.concatenate([side_index, np.asarray(extra_t, dtype=np.uint32).reshape(-1, 3)]) if extra_t else side_index
    nc = np.concatenate([side_cols, np.asarray(extra_c, dtype=np.uint32)]) if extra_c else side_cols
    nv = nv.astype(np.float32).reshape(-1)
    nt = nt.reshape(-1)
    from . import configure

    configure.apply_surface_overrides(element, nv, nt, nc, palette)  # D97: the sides' overrides win
    return nv, nt, nc


# ---------------------------------------------------------------- creating

def _context(f):
    ctx = ifcopenshell.util.representation.get_context(f, "Model", "Body", "MODEL_VIEW")
    if ctx is None:
        from . import authoring

        ctx = authoring._body_context()
    return ctx


def _surface_by_name(f, name: str):
    return next((s for s in f.by_type("IfcSurfaceStyle") if s.Name == name), None)


def _material_by_name(f, name: str):
    return next((m for m in f.by_type("IfcMaterial") if m.Name == name), None)


def _write_look(f, style, look: dict):
    """Set an IfcSurfaceStyle's rendering from a look dict (colour, transparency, shine, reflectance)."""
    sh = _shading(style)
    r, g, b = _rgb(look.get("colour") or "#cccccc")
    reflectance = look.get("reflectance") if look.get("reflectance") in REFLECTANCE else "NOTDEFINED"
    if sh is not None and not sh.is_a("IfcSurfaceStyleRendering"):
        ifcopenshell.api.style.remove_surface_style(f, style=sh)
        sh = None
    if sh is None:
        sh = ifcopenshell.api.style.add_surface_style(f, style=style, ifc_class="IfcSurfaceStyleRendering", attributes={
            "SurfaceColour": {"Name": None, "Red": r, "Green": g, "Blue": b}, "ReflectanceMethod": reflectance})
    sh.SurfaceColour.Red, sh.SurfaceColour.Green, sh.SurfaceColour.Blue = r, g, b
    sh.Transparency = max(0.0, min(1.0, float(look.get("transparency") or 0.0)))
    sh.ReflectanceMethod = reflectance
    sh.SpecularHighlight = f.createIfcSpecularRoughness(1.0 - max(0.0, min(1.0, float(look.get("shine") or 0.0))))
    if "texture" in look or "texture_path" in look:
        _write_texture(f, style, look)
    return style


def make_surface(f, name: str, look: dict):
    style = ifcopenshell.api.style.add_style(f, name=name)
    style.Side = "BOTH"
    return _write_look(f, style, look)


def attach_surface(f, material, style):
    """Make `style` the material's surface (replacing the one it had)."""
    for rep in list(getattr(material, "HasRepresentation", None) or ()):
        for r in list(rep.Representations or ()):
            for item in list(r.Items or ()):
                if item.is_a("IfcStyledItem"):
                    f.remove(item)
            f.remove(r)
        f.remove(rep)
    if style is not None:
        ifcopenshell.api.style.assign_material_style(f, material=material, style=style, context=_context(f),
                                                     should_use_presentation_style_assignment=f.schema == "IFC2X3")


def _write_properties(f, material, fields: dict):
    by_pset: dict = {}
    for field, value in fields.items():
        if field not in _MATERIAL_FIELDS:
            continue
        pset, prop = _MATERIAL_FIELDS[field]
        if value is not None and value != "":
            value = int(value) if field in _INTS else float(value) if field in _FLOATS else str(value)
        else:
            value = None
        by_pset.setdefault(pset, {})[prop] = value
    existing = ifcopenshell.util.element.get_psets(material)
    for pset, props in by_pset.items():
        if pset in existing:
            p = f.by_id(existing[pset]["id"])
        else:
            if all(v is None for v in props.values()):
                continue
            p = ifcopenshell.api.pset.add_pset(f, product=material, name=pset)
        ifcopenshell.api.pset.edit_pset(f, pset=p, properties=props)


def ensure(name: str, f=None):
    """The material named `name`, created (with the catalogue's surface and data when it lists it)."""
    f = B._model if f is None else f
    m = _material_by_name(f, name)
    if m is not None:
        return m
    spec = CATALOGUE.get(name)
    m = ifcopenshell.api.material.add_material(f, name=name, category=spec.get("category") if spec and _ifc4(f) else None)
    if spec:
        _apply_spec(f, m, name, spec)
    return m


# ---------------------------------------------------------------- default textures (D96)
# Pictures for the catalogue's surfaces, drawn here (no third-party assets): {surface: (painter, size m)}.

def _shade(rgb, k):
    return bytes(max(0, min(255, int(c * k))) for c in rgb)


def _brick_pixels(w, h):
    rows = []
    for y in range(h):
        row = bytearray()
        course = y // (h // 4)
        for x in range(w):
            mortar = y % (h // 4) < 2 or (x + (w // 4 if course % 2 else 0)) % (w // 2) < 2
            if mortar:
                row += bytes([222, 216, 205])
            else:
                brick = (x + (w // 4 if course % 2 else 0)) // (w // 2) + course * 7
                row += _shade((181, 101, 74), 0.88 + 0.12 * ((brick * 37) % 10) / 10 + ((x * 13 + y * 7) % 5) / 100)
        rows.append(row)
    return rows


def _timber_pixels(w, h):
    import math as m

    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            grain = 0.5 + 0.5 * m.sin(y * 0.55 + 2.0 * m.sin(x * 0.045) + 0.8 * m.sin(x * 0.011 + y * 0.03))
            row += _shade((216, 180, 138), 0.84 + 0.16 * grain)
        rows.append(row)
    return rows


def _tile_pixels(w, h):
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            joint = x % (w // 2) < 2 or y % (h // 2) < 2
            row += bytes([170, 168, 160]) if joint else _shade((230, 226, 218), 0.97 + ((x // (w // 2) + y // (h // 2)) % 2) * 0.03)
        rows.append(row)
    return rows


def _stone_pixels(w, h):
    rows = []
    for y in range(h):
        row = bytearray()
        course = y // (h // 2)
        for x in range(w):
            off = (w // 3) if course % 2 else 0
            joint = y % (h // 2) < 2 or (x + off) % (w // 2 + 8 * (course % 3)) < 2
            noise = ((x * 7919 + y * 104729) % 23) / 230
            row += bytes([150, 144, 132]) if joint else _shade((201, 193, 176), 0.9 + noise)
        rows.append(row)
    return rows


def _roof_tile_pixels(w, h):
    rows = []
    for y in range(h):
        row = bytearray()
        course = y // (h // 4)
        for x in range(w):
            xx = (x + (w // 8 if course % 2 else 0)) % (w // 4)
            edge = y % (h // 4) > h // 4 - 3 or xx < 2
            depth = 0.82 + 0.18 * (y % (h // 4)) / (h // 4)  # each tile darker at its lower edge
            row += _shade((168, 85, 58), 0.6 if edge else depth)
        rows.append(row)
    return rows


DEFAULT_TEXTURES = {"Roof tiles": (_roof_tile_pixels, (1.2, 0.4)), "Brick": (_brick_pixels, (0.5, 0.26)), "Timber - finish": (_timber_pixels, (1.0, 0.25)),
                    "Ceramic tiles": (_tile_pixels, (0.6, 0.6)), "Stone": (_stone_pixels, (1.2, 0.6))}


def _default_texture(f, style, name: str):
    """Give a catalogue surface its drawn picture (D96), written into the project's file store."""
    import tempfile
    import pathlib

    from . import underlays

    painter, size = DEFAULT_TEXTURES[name]
    data = underlays.png_bytes(128, 64, painter(128, 64))
    tmp = pathlib.Path(tempfile.mkdtemp()) / f"{name}.png"
    tmp.write_bytes(data)
    _write_texture(f, style, {"texture_path": str(tmp), "texture_size": list(size)})


def _apply_spec(f, material, name: str, spec: dict):
    style = _surface_by_name(f, name)
    if style is None:
        style = make_surface(f, name, {
            "colour": spec["colour"], "transparency": spec.get("transparency", 0.0), "shine": spec.get("shine", 0.1),
            "reflectance": spec.get("reflectance", "MATT")})
        if name in DEFAULT_TEXTURES:
            _default_texture(f, style, name)
    attach_surface(f, material, style)
    _write_properties(f, material, {k: spec.get(k) for k in ("pen", "pattern", "priority", "density", "conductivity", "heat")})


def layer_priority(material) -> int:
    """IfcMaterialLayer.Priority (IFC4: 0-100) from the material's Archicad priority (0-999)."""
    p = properties(material).get("priority", DEFAULT_PRIORITY) if material is not None else DEFAULT_PRIORITY
    try:
        return max(0, min(100, round(int(p) / 10)))
    except (TypeError, ValueError):
        return DEFAULT_PRIORITY // 10


def sync_priorities(layer_set) -> bool:
    """D96: the layers carry their materials' intersection priority, which ifcopenshell's wall
    regenerator uses at junctions (the higher layer runs through, Archicad's rule). True if changed."""
    if layer_set is None or B._model is None or not _ifc4(B._model):
        return False
    changed = False
    for layer in layer_set.MaterialLayers or ():
        p = layer_priority(layer.Material)
        if layer.Priority != p:
            layer.Priority = p
            changed = True
    return changed


# ---------------------------------------------------------------- doors, windows and roofs

FILLING_MATERIALS = {"door": {"Lining": "Timber - finish", "Panel": "Timber - finish"},
                     "window": {"Framing": "Aluminium", "Glazing": "Glass"}}
ROOF_MATERIAL = "Roof tiles"
GLASS_MAX = 0.015  # metres: a solid without holes this thin in a window is its glass


def _is_glass(item, scale: float) -> bool:
    area = getattr(item, "SweptArea", None)
    if area is None or not item.is_a("IfcExtrudedAreaSolid"):
        return False
    return not getattr(area, "InnerCurves", None) and float(item.Depth) * scale <= GLASS_MAX


def style_filling(kind: str, representation, element_type=None) -> None:
    """D96: a door or window body shows its materials in 3D (and in other viewers): each solid gets
    its material's surface as an item style, glass by its shape (thin, no hole). The type gets a
    constituent set naming the parts, unless it already has a material."""
    from . import authoring

    f = B._model
    parts = FILLING_MATERIALS.get(kind)
    if parts is None or representation is None:
        return
    scale = authoring._scale()
    mats = {part: ensure(name, f) for part, name in parts.items()}
    for item in representation.Items or ():
        if kind == "window":
            part = "Glazing" if _is_glass(item, scale) else "Framing"
        else:
            part = "Panel"
        style = surface_of(mats[part])
        if style is not None:
            ifcopenshell.api.style.assign_item_style(f, item=item, style=style)
    if element_type is not None and ifcopenshell.util.element.get_material(element_type) is None:
        if kind == "window" and _ifc4(f):
            cs = ifcopenshell.api.material.add_material_set(f, name=element_type.Name or "Window",
                                                            set_type="IfcMaterialConstituentSet")
            for part, m in mats.items():
                ifcopenshell.api.material.add_constituent(f, constituent_set=cs, material=m, name=part)
            ifcopenshell.api.material.assign_material(f, products=[element_type], material=cs)
        else:
            ifcopenshell.api.material.assign_material(f, products=[element_type], material=mats[next(iter(parts))])


def give_roof_material(roof) -> None:
    """A new roof is roof tiles (Archicad's default roof composite is tiled), shown in 3D and cut."""
    if ifcopenshell.util.element.get_material(roof) is None:
        ifcopenshell.api.material.assign_material(B._model, products=[roof], material=ensure(ROOF_MATERIAL))


# ---------------------------------------------------------------- state for the dialog

def _used_by(f) -> tuple[dict, dict, dict]:
    """Element counts per material id, per layer set id, and per surface id."""
    materials, sets, surfaces = {}, {}, {}
    for rel in f.by_type("IfcRelAssociatesMaterial"):
        mat = rel.RelatingMaterial
        count = sum(1 for o in rel.RelatedObjects or () if o.is_a("IfcProduct"))
        if mat.is_a("IfcMaterialLayerSetUsage"):
            mat = mat.ForLayerSet
        if mat.is_a("IfcMaterialLayerSet") and not count:
            # a type: its occurrences use it through the type
            for o in rel.RelatedObjects or ():
                if o.is_a("IfcTypeObject"):
                    count += len(ifcopenshell.util.element.get_types(o))
        if mat.is_a("IfcMaterialLayerSet"):
            sets[mat.id()] = sets.get(mat.id(), 0) + count
        for m in _materials_in(mat):
            materials[m.id()] = materials.get(m.id(), 0) + count
    for m in f.by_type("IfcMaterial"):
        s = surface_of(m)
        if s is not None:
            surfaces[s.id()] = surfaces.get(s.id(), 0) + materials.get(m.id(), 0)
    return materials, sets, surfaces


def _materials_in(mat) -> list:
    if mat.is_a("IfcMaterial"):
        return [mat]
    if mat.is_a("IfcMaterialLayerSetUsage"):
        mat = mat.ForLayerSet
    if mat.is_a("IfcMaterialLayerSet"):
        return [l.Material for l in mat.MaterialLayers or () if l.Material]
    if mat.is_a("IfcMaterialProfileSetUsage"):
        mat = mat.ForProfileSet
    if mat.is_a("IfcMaterialProfileSet"):
        return [p.Material for p in mat.MaterialProfiles or () if p.Material]
    if mat.is_a("IfcMaterialConstituentSet"):
        return [c.Material for c in mat.MaterialConstituents or () if c.Material]
    if mat.is_a("IfcMaterialList"):
        return list(mat.Materials or ())
    return []


def _composite_type(layer_set):
    """The wall/slab type that carries the layer set (KimBim's composites are types), or None."""
    for rel in getattr(layer_set, "AssociatedTo", None) or ():
        for o in rel.RelatedObjects or ():
            if o.is_a("IfcTypeObject"):
                return o
    return None


def state(f=None) -> dict:
    f = B._model if f is None else f
    from . import authoring

    s = authoring._scale()
    used_m, used_s, used_surf = _used_by(f)
    surfaces = []
    for st in f.by_type("IfcSurfaceStyle"):
        look = surface_look(st) or {"colour": "#cccccc", "transparency": 0.0, "shine": 0.0, "reflectance": "NOTDEFINED"}
        surfaces.append({"key": st.id(), "name": st.Name or "", **look, "used_by": used_surf.get(st.id(), 0)})
    materials = []
    for m in f.by_type("IfcMaterial"):
        surf = surface_of(m)
        props = properties(m)
        materials.append({"key": m.id(), "name": m.Name or "", "category": getattr(m, "Category", None) or "",
                          "description": getattr(m, "Description", None) or "",
                          "surface": surf.Name if surf is not None else "",
                          "colour": (surface_look(surf) or {}).get("colour", "") if surf is not None else "",
                          "pen": props.get("pen"), "bg": props.get("bg"), "pattern": props.get("pattern", ""),
                          "priority": props.get("priority", DEFAULT_PRIORITY), "identifier": props.get("identifier", ""),
                          "manufacturer": props.get("manufacturer", ""), "density": props.get("density"),
                          "conductivity": props.get("conductivity"), "heat": props.get("heat"),
                          "used_by": used_m.get(m.id(), 0)})
    composites = []
    for ls in f.by_type("IfcMaterialLayerSet"):
        t = _composite_type(ls)
        core = core_layer(ls)
        composites.append({"key": ls.id(), "name": ls.LayerSetName or (t.Name if t else "") or "",
                           "type": t.is_a() if t is not None else "",
                           "layers": [{"material": l.Material.Name if l.Material else "",
                                       "thickness": round(float(l.LayerThickness or 0.0) * s, 6),
                                       "core": l == core if getattr(l, "Category", None) != CORE else True}
                                      for l in ls.MaterialLayers or ()],
                           "used_by": used_s.get(ls.id(), 0)})
    from . import drafting

    return {"ok": True, "surfaces": surfaces, "materials": materials, "composites": composites,
            "patterns": list(drafting.patterns()), "schema": f.schema}


def materials_state() -> str:
    if B._model is None:
        return _fail("no model open")
    try:
        return B._dump(state())
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


# ---------------------------------------------------------------- applying the dialog's changes

def _users_of_material(f, material) -> list:
    out = []
    for rel in f.by_type("IfcRelAssociatesMaterial"):
        if material in _materials_in(rel.RelatingMaterial):
            for o in rel.RelatedObjects or ():
                if o.is_a("IfcProduct"):
                    out.append(o)
                elif o.is_a("IfcTypeObject"):
                    out.extend(ifcopenshell.util.element.get_types(o))
    return out


def _users_of_set(f, layer_set) -> list:
    out = []
    for rel in f.by_type("IfcRelAssociatesMaterial"):
        mat = rel.RelatingMaterial
        if mat == layer_set or (mat.is_a("IfcMaterialLayerSetUsage") and mat.ForLayerSet == layer_set):
            for o in rel.RelatedObjects or ():
                if o.is_a("IfcProduct"):
                    out.append(o)
                elif o.is_a("IfcTypeObject"):
                    out.extend(ifcopenshell.util.element.get_types(o))
    return list(dict.fromkeys(out))


def _by_key(f, key, cls):
    try:
        e = f.by_id(int(key))
    except (RuntimeError, TypeError, ValueError):
        return None
    return e if e.is_a(cls) else None


def _unique(f, cls, name, attr="Name", exclude=None) -> bool:
    return not any(getattr(e, attr) == name and e != exclude for e in f.by_type(cls))


def _apply_surface(f, item, touched: set):
    name = (item.get("name") or "").strip()
    if not name:
        raise ValueError("a surface needs a name")
    style = _by_key(f, item.get("key"), "IfcSurfaceStyle") if item.get("key") is not None else None
    if not _unique(f, "IfcSurfaceStyle", name, exclude=style):
        raise ValueError(f"there is already a surface named {name}")
    if style is None:
        make_surface(f, name, item)
        return
    style.Name = name
    _write_look(f, style, item)
    for m in f.by_type("IfcMaterial"):
        if surface_of(m) == style:
            touched.update(_users_of_material(f, m))


def _apply_material(f, item, touched: set):
    name = (item.get("name") or "").strip()
    if not name:
        raise ValueError("a building material needs a name")
    m = _by_key(f, item.get("key"), "IfcMaterial") if item.get("key") is not None else None
    if not _unique(f, "IfcMaterial", name, exclude=m):
        raise ValueError(f"there is already a building material named {name}")
    if m is None:
        m = ifcopenshell.api.material.add_material(f, name=name)
    m.Name = name
    if _ifc4(f):
        m.Category = item.get("category") or None
        m.Description = item.get("description") or None
    surface_name = item.get("surface") or ""
    style = _surface_by_name(f, surface_name) if surface_name else None
    if surface_name and style is None:
        raise ValueError(f"unknown surface {surface_name}")
    if style != surface_of(m):
        attach_surface(f, m, style)
    _write_properties(f, m, {k: item.get(k) for k in _MATERIAL_FIELDS if k in item})
    for ls in f.by_type("IfcMaterialLayerSet"):
        if any(l.Material == m for l in ls.MaterialLayers or ()) and sync_priorities(ls):
            _rejoin(f, _users_of_set(f, ls), touched)
    touched.update(_users_of_material(f, m))


def _reshape(f, element, touched: set):
    """Regenerate a wall or slab after its composite's thickness changed."""
    from . import authoring as A

    if element.is_a("IfcWall"):
        A._regenerate(f, element)
    elif element.is_a("IfcSlab"):
        _set_slab_depth(f, element)
    touched.add(element)


def _set_slab_depth(f, slab):
    """A KimBim slab keeps its top where it was and takes its composite's thickness."""
    from . import authoring as A

    ls = A._layer_set(slab)
    rep = ifcopenshell.util.representation.get_representation(slab, "Model", "Body", "MODEL_VIEW")
    if ls is None or rep is None:
        return
    solids = [e for e in f.traverse(rep) if e.is_a("IfcExtrudedAreaSolid")]
    if len(solids) != 1:
        return
    new = A._thickness(ls) / A._scale()
    old = float(solids[0].Depth)
    if abs(new - old) < 1e-9:
        return
    solids[0].Depth = new
    m = ifcopenshell.util.placement.get_local_placement(slab.ObjectPlacement)
    m[2][3] += (old - new)  # model units: the top stays at the level
    import ifcopenshell.api.geometry

    ifcopenshell.api.geometry.edit_object_placement(f, product=slab, matrix=m, is_si=False)


def _apply_composite(f, item, touched: set):
    from . import authoring as A

    name = (item.get("name") or "").strip()
    if not name:
        raise ValueError("a composite needs a name")
    layers = item.get("layers") or []
    if not layers:
        raise ValueError(f"the composite {name} needs at least one layer")
    for layer in layers:
        if float(layer.get("thickness") or 0.0) <= 0:
            raise ValueError(f"every layer of {name} needs a thickness")
        if not _material_by_name(f, layer.get("material") or ""):
            raise ValueError(f"unknown building material {layer.get('material')}")
    ls = _by_key(f, item.get("key"), "IfcMaterialLayerSet") if item.get("key") is not None else None
    if not _unique(f, "IfcMaterialLayerSet", name, attr="LayerSetName", exclude=ls):
        raise ValueError(f"there is already a composite named {name}")
    if ls is None:
        kind = item.get("type") or "IfcWallType"
        if kind not in ("IfcWallType", "IfcSlabType", "IfcCoveringType", "IfcRoofType"):
            raise ValueError(f"composites are for walls and slabs, not {kind}")
        t = ifcopenshell.api.root.create_entity(f, ifc_class=kind, name=name)
        ls = ifcopenshell.api.material.add_material_set(f, name=name, set_type="IfcMaterialLayerSet")
        ifcopenshell.api.material.assign_material(f, products=[t], material=ls)
    old_thickness = A._thickness(ls) if ls.MaterialLayers else 0.0
    ls.LayerSetName = name
    t = _composite_type(ls)
    if t is not None and t.Name != name:
        t.Name = name
    existing = list(ls.MaterialLayers or ())
    for i, layer in enumerate(layers):
        mat = _material_by_name(f, layer["material"])
        if i < len(existing):
            ml = existing[i]
            ml.Material = mat
        else:
            ml = ifcopenshell.api.material.add_layer(f, layer_set=ls, material=mat)
        ml.LayerThickness = float(layer["thickness"]) / A._scale()
        if _ifc4(f):
            ml.Category = CORE if layer.get("core") else None
    for ml in existing[len(layers):]:
        ifcopenshell.api.material.remove_layer(f, layer=ml)
    priorities_changed = sync_priorities(ls)
    users = _users_of_set(f, ls)
    new_thickness = A._thickness(ls)
    if abs(new_thickness - old_thickness) > 1e-9:
        for e in users:
            usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
            if e.is_a("IfcWall") and usage is not None and usage.is_a("IfcMaterialLayerSetUsage") and old_thickness > 0:
                from . import configure

                # the reference line keeps its place in the wall: the remembered location (D97), else
                # the same fraction of the thickness (centre stays centre)
                if not configure.reapply_reference(e):
                    usage.OffsetFromReferenceLine = float(usage.OffsetFromReferenceLine or 0.0) * new_thickness / old_thickness
            _reshape(f, e, touched)
    elif priorities_changed:
        _rejoin(f, users, touched)
    touched.update(users)


def _rejoin(f, elements, touched: set):
    """Regenerate walls (and the walls joined to them) after their junction priorities changed."""
    from . import authoring as A

    walls = [e for e in elements if e.is_a("IfcWall")]
    for w in walls:
        A._regenerate(f, w)
        touched.add(w)
    for w in walls:
        for n in A._connected_walls(w):
            if n not in touched:
                A._regenerate(f, n)
                touched.add(n)


def _delete_material(f, key, replace, touched: set):
    m = _by_key(f, key, "IfcMaterial")
    if m is None:
        return
    users = _users_of_material(f, m)
    in_sets = [l for l in f.by_type("IfcMaterialLayer") if l.Material == m]
    in_sets += [p for p in f.by_type("IfcMaterialProfile") if p.Material == m]
    if users or in_sets:
        r = _material_by_name(f, replace or "") if replace else None
        if r is None:
            r = ensure("Generic", f)
        if r == m:
            raise ValueError(f"{m.Name} cannot replace itself")
        for l in in_sets:
            l.Material = r
        for rel in list(f.by_type("IfcRelAssociatesMaterial")):
            if rel.RelatingMaterial == m:
                rel.RelatingMaterial = r
        for ml in f.by_type("IfcMaterialList"):
            if m in (ml.Materials or ()):
                ml.Materials = [r if x == m else x for x in ml.Materials]
        touched.update(users)
    attach_surface(f, m, None)
    for rel in list(getattr(m, "HasProperties", None) or ()):
        for p in list(rel.Properties or ()):
            f.remove(p)
        f.remove(rel)
    f.remove(m)


def _delete_surface(f, key, touched: set):
    style = _by_key(f, key, "IfcSurfaceStyle")
    if style is None:
        return
    for m in f.by_type("IfcMaterial"):
        if surface_of(m) == style:
            touched.update(_users_of_material(f, m))
            attach_surface(f, m, None)
    ifcopenshell.api.style.remove_style(f, style=style)


def _delete_composite(f, key, replace, touched: set):
    from . import authoring as A

    ls = _by_key(f, key, "IfcMaterialLayerSet")
    if ls is None:
        return
    users = _users_of_set(f, ls)
    t = _composite_type(ls)
    if users:
        r = next((x for x in f.by_type("IfcMaterialLayerSet") if x.LayerSetName == replace and x != ls), None)
        rt = _composite_type(r) if r is not None else None
        if rt is None or (t is not None and rt.is_a() != t.is_a()):
            raise ValueError(f"{ls.LayerSetName} is used: choose another {t.is_a()[3:-4].lower() if t else ''} composite to replace it")
        ifcopenshell.api.type.assign_type(f, related_objects=users, relating_type=rt)
        for e in users:
            _reshape(f, e, touched)
        touched.update(users)
    if t is not None:
        ifcopenshell.api.root.remove_product(f, product=t)
    if ls.id() and not ls.AssociatedTo:
        ifcopenshell.api.material.remove_material_set(f, material=ls)


def apply_materials(changes_json: str) -> str:
    """Apply the Materials dialog's changes as one undo step (D96)."""
    if B._model is None:
        return _fail("no model open")
    try:
        changes = json.loads(changes_json)
    except ValueError as ex:
        return _fail(str(ex))

    def action():
        f = B._model
        touched: set = set()
        deleted = changes.get("deleted") or {}
        for item in changes.get("surfaces") or ():
            _apply_surface(f, item, touched)
        for item in changes.get("materials") or ():
            _apply_material(f, item, touched)
        for item in changes.get("composites") or ():
            _apply_composite(f, item, touched)
        for d in deleted.get("composites") or ():
            _delete_composite(f, d.get("key"), d.get("replace"), touched)
        for d in deleted.get("materials") or ():
            _delete_material(f, d.get("key"), d.get("replace"), touched)
        for key in deleted.get("surfaces") or ():
            _delete_surface(f, key, touched)
        _sync_texture_files()  # D96
        guids = [e.GlobalId for e in touched if getattr(e, "GlobalId", None)]
        return max(1, len(guids)), guids, []

    try:
        r = B._run_settings(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}" if not isinstance(ex, ValueError) else str(ex))
    return B._dump(r)


def add_standard_materials() -> str:
    """The catalogue's building materials (and their surfaces) the model lacks, as one undo step."""
    if B._model is None:
        return _fail("no model open")

    def action():
        added = [n for n in CATALOGUE if _material_by_name(B._model, n) is None]
        for n in added:
            ensure(n)
        return len(added)

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def purge_materials() -> str:
    """Remove the surfaces, building materials and composites nothing uses (one undo step)."""
    if B._model is None:
        return _fail("no model open")

    def action():
        f = B._model
        used_m, used_s, _ = _used_by(f)
        removed = 0
        for ls in list(f.by_type("IfcMaterialLayerSet")):
            if not used_s.get(ls.id()):
                t = _composite_type(ls)
                if t is not None:
                    ifcopenshell.api.root.remove_product(f, product=t)
                if not ls.AssociatedTo:
                    ifcopenshell.api.material.remove_material_set(f, material=ls)
                removed += 1
        in_use = set()
        for rel in f.by_type("IfcRelAssociatesMaterial"):
            in_use.update(m.id() for m in _materials_in(rel.RelatingMaterial))
        for m in list(f.by_type("IfcMaterial")):
            if m.id() not in in_use and not any(l.Material == m for l in f.by_type("IfcMaterialLayer")) \
                    and not any(p.Material == m for p in f.by_type("IfcMaterialProfile")):
                _delete_material(f, m.id(), None, set())
                removed += 1
        attached = {surface_of(m).id() for m in f.by_type("IfcMaterial") if surface_of(m) is not None}
        for st in list(f.by_type("IfcSurfaceStyle")):
            if st.id() not in attached and not _style_on_items(f, st):
                ifcopenshell.api.style.remove_style(f, style=st)
                removed += 1
        return removed

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def _style_on_items(f, style) -> bool:
    """True when a representation item (not a material) is styled by `style`."""
    for item in f.by_type("IfcStyledItem"):
        if item.Item is not None and style in list(_styles_of_item(item)):
            return True
    return False


def _own_profile_set(f, e, current, material):
    """A column's or beam's own profile set (D97, Archicad: material per element): the type's profiles,
    `material` for each, used by this occurrence alone (the type and its other occurrences keep theirs)."""
    t = ifcopenshell.util.element.get_type(e)
    shared = t is not None and ifcopenshell.util.element.get_material(t, should_skip_usage=True) == current
    if not shared:  # already its own: change it in place
        for profile in current.MaterialProfiles or ():
            profile.Material = material
        return
    usage = ifcopenshell.util.element.get_material(e, should_skip_usage=False)
    cardinal = usage.CardinalPoint if usage is not None and usage.is_a("IfcMaterialProfileSetUsage") else None
    own = f.createIfcMaterialProfileSet(current.Name, current.Description, [
        f.createIfcMaterialProfile(p.Name, p.Description, material, p.Profile, p.Priority, p.Category)
        for p in current.MaterialProfiles or ()], current.CompositeProfile)
    ifcopenshell.api.material.unassign_material(f, products=[e])
    rel = ifcopenshell.api.material.assign_material(f, products=[e], type="IfcMaterialProfileSetUsage", material=own)
    new_usage = rel.RelatingMaterial if rel is not None else None
    if new_usage is not None and new_usage.is_a("IfcMaterialProfileSetUsage") and cardinal is not None:
        new_usage.CardinalPoint = cardinal


def assign_material(guids_json: str, kind: str, name: str, scope: str = "") -> str:
    """Give elements a building material (kind 'material') or a composite (kind 'composite': walls and
    slabs change to the composite's type, whose thickness they take). A column's or beam's material is
    its own (scope 'element', Archicad) or its type's, which all of the type's occurrences follow
    (scope 'type', Revit); without a scope, the project's member_material_scope decides."""
    if B._model is None:
        return _fail("no model open")
    try:
        guids = json.loads(guids_json)
    except ValueError as ex:
        return _fail(str(ex))
    f = B._model
    elements = []
    for g in guids:
        try:
            elements.append(f.by_guid(g))
        except RuntimeError:
            return _fail(f"unknown element {g}")
    if kind == "material":
        m = _material_by_name(f, name)
        if m is None:
            return _fail(f"unknown building material {name}")
    elif kind == "composite":
        ls = next((x for x in f.by_type("IfcMaterialLayerSet") if x.LayerSetName == name), None)
        t = _composite_type(ls) if ls is not None else None
        if t is None:
            return _fail(f"unknown composite {name}")
        allowed = {"IfcWallType": "IfcWall", "IfcSlabType": "IfcSlab", "IfcCoveringType": "IfcCovering", "IfcRoofType": "IfcRoof"}
        bad = [e for e in elements if not e.is_a(allowed.get(t.is_a(), "-"))]
        if bad:
            return _fail(f"the composite {name} is for {allowed.get(t.is_a(), '?')[3:].lower()}s only")
    else:
        return _fail(f"unknown kind {kind}")
    if not scope:
        from . import settings

        scope = settings.current().get("member_material_scope") or "element"
    if scope not in ("element", "type"):
        return _fail(f"unknown scope {scope}")

    def action():
        touched: set = set()
        if kind == "material":
            for e in elements:
                current = ifcopenshell.util.element.get_material(e, should_skip_usage=True)
                if current is not None and current.is_a("IfcMaterialProfileSet"):
                    if scope == "type":  # D97: the type's profiles: every occurrence of it follows
                        for profile in current.MaterialProfiles or ():
                            profile.Material = m
                        touched.update(_users_of_material(f, m))
                    else:
                        _own_profile_set(f, e, current, m)
                        touched.add(e)
                    continue
                ifcopenshell.api.material.unassign_material(f, products=[e])
                ifcopenshell.api.material.assign_material(f, products=[e], material=m)
                touched.add(e)
        else:
            ifcopenshell.api.type.assign_type(f, related_objects=elements, relating_type=t)
            for e in elements:
                _reshape(f, e, touched)
        guids = [e.GlobalId for e in touched]
        return len(guids), guids, []

    try:
        r = B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


_COMPOSITE_CLASSES = {"IfcWall": "IfcWallType", "IfcSlab": "IfcSlabType"}


def _info(e) -> dict:
    """What the Properties panel's Material row shows for one element: kind (composite or material),
    name, choices, editable, and the composite type class (`for`)."""
    f = B._model
    m = ifcopenshell.util.element.get_material(e, should_skip_usage=True)
    cc = next((v for k, v in _COMPOSITE_CLASSES.items() if e.is_a(k)), None)
    if cc is not None and (m is None or m.is_a("IfcMaterialLayerSet")):
        choices = [ls.LayerSetName for ls in f.by_type("IfcMaterialLayerSet")
                   if ls.LayerSetName and _composite_type(ls) is not None and _composite_type(ls).is_a(cc)]
        return {"kind": "composite", "name": (m.LayerSetName or "") if m is not None else "", "choices": choices,
                "editable": True, "for": cc}
    choices = [x.Name for x in f.by_type("IfcMaterial") if x.Name]
    if m is not None and m.is_a("IfcMaterial"):
        name = m.Name
    else:
        mm = main_material(e)
        name = mm.Name if mm is not None else ""
    return {"kind": "material", "name": name or "", "choices": choices,
            "editable": m is None or m.is_a("IfcMaterial") or m.is_a("IfcMaterialProfileSet"),
            "for": ""}


def merged(elements) -> dict | None:
    """The Material row for a selection: {kind, value, varies, choices, editable}, or None when the
    selection mixes kinds (walls with columns...) or has nothing that takes a material."""
    infos = [_info(e) for e in elements
             if e.is_a("IfcElement") and not e.is_a("IfcOpeningElement") and not e.is_a("IfcVirtualElement")]
    if not infos or len({(i["kind"], i["for"]) for i in infos}) != 1:
        return None
    names = {i["name"] for i in infos}
    return {"kind": infos[0]["kind"], "value": next(iter(names)) if len(names) == 1 else None, "varies": len(names) > 1,
            "choices": infos[0]["choices"], "editable": all(i["editable"] for i in infos)}


def element_material(guid: str) -> str:
    """{ok, kind, name, choices, editable}: the Material row for one element."""
    if B._model is None:
        return _fail("no model open")
    try:
        e = B._model.by_guid(guid)
    except RuntimeError:
        return _fail(f"unknown element {guid}")
    info = _info(e)
    info.pop("for")
    return B._dump({"ok": True, **info})
