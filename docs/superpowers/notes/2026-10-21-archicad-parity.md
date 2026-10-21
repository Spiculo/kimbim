<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Archicad parity: materials, element configuration, tooling (D96–D98) — 2026-10-21

Branch `parity-materials`. Spec: [2026-10-21-archicad-parity-materials-design](../specs/2026-10-21-archicad-parity-materials-design.md).

## Built

### D96 materials
- `kimbim/materials.py`: surfaces (`IfcSurfaceStyleRendering`), building materials (`IfcMaterial` + material
  style + `KIMBIM_Material`, `Pset_MaterialCommon`, `Pset_MaterialThermal`), composites (layer sets); a
  20-material catalogue in new projects; `materials_state`, `apply_materials` (one undo step),
  `assign_material`, `add_standard_materials`, `purge_materials`, `element_material`.
- 3D: a palette index per triangle (4th mesh part); layered elements by face normal against the layer
  axis; iterator styles; the material's surface; class colour. Transparency per triangle.
- Cuts: fills from the material (`fill_source`), composites cut layer by layer on screen
  (`Viewport::rebuildSections`), in plan and section drawings (`drawings._cut_group`) and so in DXF/PDF.
- Doors and windows get styled items (aluminium frame, glass, timber leaf) and a constituent set; roofs
  get roof tiles.
- C++: `MaterialsDialog` (+ `MaterialsEdits`, testable without widgets), Properties' Material row.

### D97 element configuration
- `kimbim/configure.py`: reference line (six locations, remembered in `KIMBIM_Wall`), flip, slant angle,
  surface overrides (`KIMBIM_Surfaces`), the Geometry and Surfaces groups for Properties (drop-downs:
  entries with `choices`).
- Layer priorities follow the materials' priorities (`materials.sync_priorities`).
- Wall tool: reference line combo (project setting `wall_reference_line`, default outside face), preview
  offset (`wall_types` → `centres`). Model › Flip walls. Object tool: Gravity.

### D98 tooling
- Construction grid + grid snap (`Snapper::setSnapGrid`, `Viewport::setConstructionGrid`), Zoom to selection.
- Grid system (`authoring.add_grid_system`).
- Worksheets (`kimbim/worksheets.py`), figures embedded in worksheet drawings (`underlays.figures_svg`),
  pictures on sheets (`sheets.place_sheet_image`, `sheet_files` setting).
- Splines (`drafting.spline_points`, `DraftTool::splinePoints`).

## Follow-ups (not done)
- Textures are done (surface picture + size, `IfcSurfaceStyleWithTextures`, box-mapped in 3D, files in
  `texture_files`); the catalogue's brick, timber, tiles, stone and roof tiles come with drawn pictures; no render-style view.
- Cut fill patterns are hatched on screen, in printed drawings/PDF and in DXF (pattern HATCHes); the
  insulation loops have no line families, so DXF leaves those layers unhatched.
- **Layer-by-layer junctions** are the regenerator's (priority 0–100); no per-junction override UI.
- Double-slanted and complex-profile walls; per-layer surfaces on edges (the core's surface is used).
- Columns and beams change material through their type's profile set (every column of the type follows); no per-occurrence material yet.
- The construction grid's extent is computed when shown (it follows the model on the next refresh).
- Figures: File › Place picture (typed width, opaque) or Place underlay (calibrated). 
