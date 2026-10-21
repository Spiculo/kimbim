<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Archicad parity: materials, element configuration, tooling — design

Owner goal (2026-10-21): "keep working on parity to Archicad, particularly on materials, wall and object
configuration, how it reflects on the 3D, tooling (grids, snap to fit, worksheets, loading images,
drawing, etc.)". Per the standing instruction (Archicad default, Revit fallback, configurable where
offices differ, don't ask), the agent made the design calls below.

The work is three sub-projects, built and merged in this order. Each gets a decision row.

| Part | Decision | Scope |
|------|----------|-------|
| 1 | D96 | Surfaces, building materials, composites; material colours in 3D; material cut fills |
| 2 | D97 | Wall and object configuration: reference line, flip, per-side surface overrides, slanted walls, object surfaces, gravity |
| 3 | D98 | Tooling: snap grid, grid system tool, fit in window, worksheets, figures (images), more drafting |

---

## Part 1 — Materials (D96)

### What Archicad does (the reference)

- **Surfaces** (Options › Element Attributes › Surfaces): what a face looks like in 3D: colour,
  transparency, shine, texture.
- **Building materials**: a cut fill (pattern, foreground and background pen), a surface, an
  **intersection priority** (0–999: the stronger material runs through at junctions), physical data
  (density, thermal conductivity, heat capacity), an ID and a manufacturer.
- **Composites**: an ordered stack of building materials with thicknesses; each layer is *core* or
  *finish*. Walls and slabs use a composite.
- In 3D a composite wall shows the **outer layer's surface** on each side and the core on its edges.
  The wall can override the surface of each side (Part 2).
- Plans cut through the element show the building material's **cut fill**.

### Storage (IFC first, so other tools see it)

| KimBim | IFC | Notes |
|--------|-----|-------|
| Surface | `IfcSurfaceStyle` (Side BOTH) + `IfcSurfaceStyleRendering` | `SurfaceColour`, `Transparency` (0–1), `SpecularHighlight` (`IfcSpecularRoughness`, shine), `ReflectanceMethod` (MATT, PLASTIC, METAL, GLASS…). Named, unique by name |
| Building material | `IfcMaterial` (Name, Description, Category in IFC4) | Unique by name |
| Material's surface | `IfcMaterialDefinitionRepresentation` → `IfcStyledRepresentation` (Body context) → `IfcStyledItem` → the surface | `ifcopenshell.api.style.assign_material_style`; viewers (and the geometry iterator) use it |
| Cut fill, priority, ID, manufacturer | `KIMBIM_Material` material pset: `CutFillPen`, `CutBackgroundPen`, `CutFillPattern` (a name from the D84 pattern table), `Priority` (0–999, default 500), `Identifier`, `Manufacturer` | IFC has no cut fill on a material |
| Physical data | `Pset_MaterialCommon.MassDensity` (kg/m³), `Pset_MaterialThermal.ThermalConductivity` (W/m·K), `.SpecificHeatCapacity` (J/kg·K) | IFC standard psets |
| Composite | `IfcMaterialLayerSet` (exists today) | Core layer: `IfcMaterialLayer.Category = "LoadBearing"`; air gap: `IsVentilated` |

IFC2X3 has no `Category`/`Description` on materials or layers: those fields are skipped there (the
pset still holds the rest). In IFC2X3, and in any layer set without a LoadBearing layer, the thickest
layer is the core.

### Default catalogue

`kimbim/materials.py` holds a catalogue of ~20 building materials with their surfaces (Archicad's
template names, simplified): Generic, Concrete, Block, Brick, Plaster, Gypsum board, Insulation,
Insulation – rigid, Timber, Timber – finish, Steel, Aluminium, Glass, Stone, Ceramic tiles, Screed,
Air gap, Membrane, Soil, Paint – white. The names already used by the default wall and slab types
(Generic, Brick, Insulation, Block, Concrete, Screed) are in it, so new projects get coloured walls.

`materials.ensure(name)` returns the material, creating it from the catalogue (with its surface,
fill pen and physical data) when missing; authoring uses it instead of a bare `add_material`. Opened
models are never changed silently; the Materials dialog has **Add standard materials**.

### 3D colours ("how it reflects on the 3D")

Meshes carry a colour for each triangle. `next_mesh_chunk` / `mesh_elements` return a fourth part:
one `uint16` palette index per triangle (`0xFFFF`: no surface, the class colour as today), and the
metadata gains `palette: [[r, g, b, transparency], ...]` in sRGB.

Face colours, first match wins:

1. Part 2's per-element surface overrides (`KIMBIM_Surfaces`).
2. **Walls with a layer-set usage**: each triangle's normal is compared with the wall's local Y axis
   (the layer direction). Faces looking to −Y take the first layer's surface and faces looking to +Y
   take the last layer's (reversed for `DirectionSense` NEGATIVE). The rest (ends, top, bottom,
   opening reveals) take the core layer's surface. This is Archicad's default look.
3. The geometry iterator's style for that face, when the file styles it (IFC item or material
   styles, as other viewers show them).
4. The element's own material: a single material, the core layer of a layer set, or the first
   profile of a profile set.
5. Nothing: the class colour, as now.

Per-element graphic overrides (D73 rules, renovation looks) still replace every face's colour, as
today. Transparency is per triangle: the shaded pass groups triangles by transparency (an override's
transparency wins over the surface's).

Editing a surface or material re-meshes the elements that use it (they come back as `geometry.changed`
in the edit result), so the 3D updates at once and undo restores it.

### Cut fills in plans, sections and DXF

`graphics.resolve` takes an element's **fill** from its building material when the material sets
`CutFillPen` (the core layer for layered elements). The element style's fill becomes the fallback.
A new element-style field `fill_source` (`material` by default, as in Archicad, or `style`) lets an
office keep fills by element kind. Rules and renovation overrides still win. Because screen poché,
drawings and DXF all read `resolve`, they all follow.

Each layer drawn with its own fill and the layer lines in the cut (Archicad's composite cut) is
**Part 1b**: the plan cut splits a layered wall's cut loop into one loop per layer (offsets along
the wall's Y axis) and each loop takes its layer's fill.

### Editing (bridge and UI)

Python (`kimbim/materials.py`, exported by `app_bridge`):

- `materials_state()` → `{surfaces, materials, composites, patterns, pens}`. Each item has a `key` (the
  entity id: stable within the session), its fields and `used_by` (element count).
- `apply_materials(changes_json)`: one undo step. `changes = {surfaces: [...], materials: [...],
  composites: [...], deleted: {surfaces: [keys], materials: [{key, replace}], composites: [{key,
  replace}]}}`. An item with a `key` is updated, one without is created. Deleting a material that is
  in use needs a replacement (default Generic). Deleting a composite that is in use reassigns its
  elements' type. Changing a composite's thickness regenerates every wall and slab of that type.
  Returns the usual edit result with every affected element in `geometry.changed`.
- `assign_material(guids_json, kind, name)`: give elements a building material (`kind=material`) or a
  composite (`kind=composite`, walls and slabs: changes their type to the composite's type).
- `add_standard_materials()`: the catalogue items the model lacks.
- `purge_materials()`: removes unused surfaces, materials and composites (doc 14 §1, "Purge").

C++: a **Materials** dialog (Graphics › *Building materials…*, *Surfaces…*, *Composites…*, each opening
its tab), working on a local copy and applied on OK as one undo step (like the Levels dialog):

- *Building materials*: a searchable list (colour chip, name), New / Duplicate / Delete; a form with
  name, ID, category, manufacturer, description, surface (combo), cut fill pattern, fill pen and
  background pen (pen buttons), intersection priority, density, thermal conductivity, heat capacity,
  "Used by N elements".
- *Surfaces*: list; colour button, transparency (0–100 %), shine (0–100 %), reflectance (Matt,
  Plastic, Metal, Glass, Mirror).
- *Composites*: list; a layer table (building material, thickness, core), Add / Remove / Up / Down,
  total thickness, used by.

The Properties panel gets a **Material** row: the element's composite or building material with a
combo to change it (`assign_material`).

### Testing

- Python: catalogue `ensure`, state round-trip, apply (create, rename, delete with replacement, used_by),
  composite thickness regenerates walls, face colours (wall sides, iterator styles, fallback),
  `resolve` takes the material fill, IFC4 and IFC2X3, the schema stays valid (`ifcopenshell.validate`).
- C++: `MeshChunk::parse` with the palette part (sizes checked), `ElementBatch` uses per-face
  colours and an element override replaces them, the dialog builds the changes JSON.

---

## Part 2 — Wall and object configuration (D97)

- **Reference line** (Archicad's wall *Reference Line Location*): outside face, centre, inside face,
  core outside, core centre, core inside. Stored as the layer usage `OffsetFromReferenceLine` (IFC),
  chosen in the Wall tool's options bar (default: outside face, Archicad; a preference) and editable
  per wall in Properties. **Flip** (Archicad's mirror of the composite about the reference line):
  `DirectionSense` POSITIVE ↔ NEGATIVE, Model › Flip wall (Ctrl+Shift+F) and in the context menu.
- **Surface overrides** (Archicad's *Override surfaces*): walls: reference side, opposite side, edges;
  slabs: top, bottom, edges; other elements: all faces. Stored in `KIMBIM_Surfaces` (surface names);
  Properties shows a surface combo per side, with a "chain" to set all.
- **Slanted walls** (Archicad's *Slanted* geometry): one slant angle for the whole wall, an
  `IfcExtrudedAreaSolid` with an extrusion direction off vertical. Double-slanted and complex
  profiles stay open.
- **Object configuration**: library objects get the surface override (all faces) and per-part
  materials where the object generator names its parts; their elevation can follow **gravity**
  (Archicad: place onto the slab or roof below the cursor), a toggle in the options bar.

## Part 3 — Tooling (D98)

- **Snap grid** (Archicad's *Grids & Background*): a construction grid per view (spacing, rotation,
  origin, shown/hidden, snap on/off; defaults 1 m, 0°, shown, snap off), drawn under the model in plan
  tabs; snapping uses it when on. View › Grid options… and a toggle on the status strip.
- **Grid system tool** (Archicad's *Grid System*): a rectangular set of grid axes in one go (counts
  and spacings in X and Y, labels 1, 2, 3 / A, B, C), using the existing `add_grid_axis`.
- **Fit in window** (Archicad's zoom to fit): fit all, fit selection (Ctrl+Shift+W / Shift+W are
  Archicad's), already partly there: completed for plan tabs and drawings.
- **Worksheets** (Archicad's independent worksheet viewpoints): a 2D-only drawing (an
  `IfcAnnotation` DRAWING with kind `worksheet`) holding drafting, text, dimensions and figures,
  opened as a tab and placeable on sheets.
- **Figures** (Archicad's *Figure* tool: images in plans, worksheets and layouts): an image placed at
  a size on a worksheet or sheet, reusing the underlay storage (D85) without the calibration step.
- **Drawing**: splines (doc 14 §12) and the Archicad *Hotspot*.

The order inside Part 3 follows usefulness: snap grid, grid system, worksheets, figures, splines.
