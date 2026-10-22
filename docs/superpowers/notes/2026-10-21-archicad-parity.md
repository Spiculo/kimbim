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
  offset (`wall_types` → `centres`). Model › Flip walls. Object tool: Gravity, Fit to walls (an object dropped by a wall face turns its back to it and stands against it; on by default). Snap data carries each wall body's centre offset, so face snaps follow walls drawn by a face.

### D98 tooling
- Construction grid + grid snap (`Snapper::setSnapGrid`, `Viewport::setConstructionGrid`), Zoom to selection.
- Trace & Reference (View › Trace reference: off, level below, level above): the reference level's plan as exported to DXF (no annotations), tinted and faded under the active plan, rebuilt 0.6 s after edits (`underlays.trace_lines`); its ends, middles and crossings snap like a DXF underlay's. View › Level above/below (Ctrl+Up/Down).
- Automatic dimensioning (Model › Dimension selected walls...): a chain per straight wall along its first layer's face (ends, door and window edges), the line a typed distance outside it (`annotations.auto_dimension`).
- Special snap points (View › Special snap points...): walls' equal divisions and a distance from their ends (`Snapper::setSpecialPoints`, user preferences `snap_divisions`, `snap_distance`).
- Grid system (`authoring.add_grid_system`).
- Worksheets (`kimbim/worksheets.py`), figures embedded in worksheet drawings (`underlays.figures_svg`),
  pictures on sheets (`sheets.place_sheet_image`, `sheet_files` setting).
- Splines (`drafting.spline_points`, `DraftTool::splinePoints`).
- Outline points (Stretch tool, Archicad's pet palette): a slab's or a drafting shape's point moved, a point added at an edge's middle (picked up), Ctrl+click deletes one (`editing.set_slab_outline`, `slab_outlines`).
- Resize (Edit menu): the selection scaled about its middle (`editing.resize_elements`, or about a given point): walls, curved walls, slabs, 2D shapes and dimensions (re-measured) take new lengths, doors keep their size, others move.
- Fillet/Chamfer (Edit menu): two walls meeting at a corner (both pulled back, a tangent curved wall or a straight one between, its layers continuing the first wall's), slab outlines, polylines and fills (`editing.round_corners`; arcs as 10° segments, like splines).

## Follow-ups (not done)
- Textures are done (surface picture + size, `IfcSurfaceStyleWithTextures`, box-mapped in 3D, files in
  `texture_files`); the catalogue's brick, timber, tiles, stone and roof tiles come with drawn pictures. 3D styles: View › White model (study model, contours and glass kept) and Sun shadows (OCCT shadow map); View › Sun... places the sun by azimuth and altitude or by place, date and time (`sun.py`, NOAA's equations, turned by true north; project setting `sun`); no photorealistic rendering.
- Cut fill patterns are hatched on screen, in printed drawings/PDF and in DXF (pattern HATCHes; the
  insulation loops as short lines on the -PATT layer).
- Junctions: the layers' priorities decide (regenerator); Model › Wall junctions overrides per wall (run through / stop / by materials) via IfcRelConnectsPathElements priorities (KimBim patches the regenerator's override handling).
- Double-slanted walls (Opposite slant angle) and complex-profile walls (Model › Save shape as wall profile, then Properties › Profile) sweep their own section along the line, cut at their ends as the joins cut a plain wall (the regenerator's end lines as clipping planes); stretches rebuild it. (Wall and slab ends and tops now show each layer: the mesh is sliced at the layer boundaries, project setting `layers_in_3d`, about 1 ms per wall.)
- Columns and beams: a building material per element (Archicad: the occurrence gets its own profile set, the type's profiles with the new material) or per type (Revit), project setting `member_material_scope` (Project settings › Column and beam material).
- The construction grid covers the model plus a margin and is redrawn when the model grows past it.
- Pictures in 3D (File › Place picture in 3D...): a thin panel with its own building material carrying the picture once (`materials.place_picture_3d`); textures now map along each vertical face (angled walls no longer stretch them) from the element's middle.
- Figures: File › Place picture (typed width, opaque) or Place underlay (calibrated). 
- Curved walls (Wall tool › Geometry: Curved; start, end, a point on the arc; `curved_walls.py`): layered, any reference line, each face its layer's surface in 3D, cut as one fill; doors and windows (straight, square to the arc, the opening deepened by the arc's bulge; the door tool measures along the arc); stretching (grips, Length in Properties) moves an end round the circle, both ends alike move the wall; split into two arcs of the same circle (doors go with their piece); a straight wall drawn to or from a curved wall's end meets it in a mitre (`KIMBIM_Wall.ArcJoins` on both, recomputed on every rebuild: the straight footprint's end slides to the mitre line, the arc runs past and is clipped). A curved wall drawn from or to another wall's end (straight or curved) is mitred with it too (tangent meetings need no cut). Snapping: ends, the arc's middle, anywhere on it, divisions.
- Favourites (a button first in the tool's strip): the tool's fields and, for objects, the object and its parameters, saved by name in the project setting `favourites` and applied again (wall, slab, door, window, column, beam, roof, stair, railing, object).
- Wall top link (Properties › Geometry › Top link / Top offset): unlinked, the level above or two above; the height follows level edits (`configure.relink_tops` at the end of `levels._apply`); a typed height unlinks.
- Door and window variety: new projects get double, sliding and double sliding doors and two- and three-panel windows (IFC operation and partitioning types; equal panels); sliding doors are drawn in plan as overlapping panels.
- Pick Up / Inject (Edit menu, Ctrl+Alt+C / Ctrl+Alt+V): walls carry composite, reference line, slant, profile and surface overrides; slabs and others their composite or material and surfaces; library objects their parameters (one undo step per parameter).
