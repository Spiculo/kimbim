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
- Special snap points (View › Special snap points...): walls' equal divisions and a distance from their ends (`Snapper::setSpecialPoints`, user preferences `snap_divisions`, `snap_distance`).
- Grid system (`authoring.add_grid_system`).
- Worksheets (`kimbim/worksheets.py`), figures embedded in worksheet drawings (`underlays.figures_svg`),
  pictures on sheets (`sheets.place_sheet_image`, `sheet_files` setting).
- Splines (`drafting.spline_points`, `DraftTool::splinePoints`).
- Fillet/Chamfer (Edit menu): slab outlines, polylines and fills (`editing.round_corners`; arcs as 10° segments, like splines).

## Follow-ups (not done)
- Textures are done (surface picture + size, `IfcSurfaceStyleWithTextures`, box-mapped in 3D, files in
  `texture_files`); the catalogue's brick, timber, tiles, stone and roof tiles come with drawn pictures. 3D styles: View › White model (study model, contours and glass kept) and Sun shadows (OCCT shadow map from the fixed sun); no photorealistic rendering.
- Cut fill patterns are hatched on screen, in printed drawings/PDF and in DXF (pattern HATCHes; the
  insulation loops as short lines on the -PATT layer).
- Junctions: the layers' priorities decide (regenerator); Model › Wall junctions overrides per wall (run through / stop / by materials) via IfcRelConnectsPathElements priorities (KimBim patches the regenerator's override handling).
- Double-slanted walls (Opposite slant angle) and complex-profile walls (Model › Save shape as wall profile, then Properties › Profile) sweep their own section along the line, cut at their ends as the joins cut a plain wall (the regenerator's end lines as clipping planes); stretches rebuild it. (Wall and slab ends and tops now show each layer: the mesh is sliced at the layer boundaries, project setting `layers_in_3d`, about 1 ms per wall.)
- Columns and beams: a building material per element (Archicad: the occurrence gets its own profile set, the type's profiles with the new material) or per type (Revit), project setting `member_material_scope` (Project settings › Column and beam material).
- The construction grid's extent is computed when shown (it follows the model on the next refresh).
- Figures: File › Place picture (typed width, opaque) or Place underlay (calibrated). 
- Pick Up / Inject (Edit menu, Ctrl+Alt+C / Ctrl+Alt+V): walls carry composite, reference line, slant, profile and surface overrides; slabs and others their composite or material and surfaces; library objects their parameters (one undo step per parameter).
