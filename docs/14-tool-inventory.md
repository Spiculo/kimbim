<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 14 — Tool inventory: what architects get elsewhere, and what KimBim still lacks

A checklist of the tools that mainstream BIM and CAD apps give architects, with KimBim's status for each.
Use it to pick the next slices. [04](04-app-features.md) stays the source of decided priorities; this document is
wider and lists tools 04 does not mention yet.

**Status as of branch `slice-9` (commit 619f876, 2026-10-06).**

## How to read it

**Has** shows which apps have the tool:

| Code | App | Notes |
|------|-----|-------|
| **AC** | Graphisoft Archicad (28/29) | Main reference: the owner's background |
| **RV** | Autodesk Revit (2025/2026) | |
| **VW** | Vectorworks Architect (2025/2026) | |
| **BB** | Bonsai (BlenderBIM) / IfcOpenShell | Open source, IFC-native, so code may be reusable ([06](06-reuse-and-licensing.md)) |
| **AL** | Allplan | Listed only where it adds something |
| **SU** | SketchUp | Listed only where it adds something |

**KimBim**: ✅ done · 🟡 partly done · ⬜ not started · 🔮 deliberately left for later ([08](08-future.md)).
**Pri** is the priority from [04](04-app-features.md) where 04 gives one. `new` means 04 does not list the tool yet, so it needs a priority.

The **Has** column comes from general knowledge of each product. It was not checked against each vendor's current
release notes, so check before relying on a single cell.

---

## 1. Project and files

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Open / save IFC | AC RV VW BB | ✅ | P0 | IFC4; IFC2X3 import through IfcOpenShell (not tested yet) |
| New project | all | ✅ | P0 | IFC4 in mm, levels |
| Project templates (units, levels, types, views, title blocks) | AC RV VW | ⬜ | P0 | |
| Autosave, crash recovery | AC RV VW | ⬜ | P0 | oplog ([03](03-versioning.md)) |
| Recent projects | all | ⬜ | P0 | |
| Imperial units, unit preferences | all | ⬜ | P0 | Metric only today |
| Project info (address, client, number) used in title blocks | AC RV VW | ✅ | new | Slice 16: *File › Project info…*, in IFC fields (D63) |
| Survey point, project base point, georeferencing | AC RV VW BB | ⬜ | P2 | `ifcopenshell.api.georeference` |
| Story settings (levels table: edit heights, insert/delete) | AC RV | ✅ | P0 | D79: Model › Levels..., one undo step; elements follow |
| Purge unused types/materials | RV VW BB | 🟡 | new | D96: Graphics › Purge unused materials (surfaces, materials, composites); not types yet |

## 2. Viewing and navigation

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Orbit, pan, zoom, fit all | all | ✅ | P0 | D48 preset |
| Plan view and 3D view | all | ✅ | P0 | P / 3 |
| View cube | RV VW BB | ✅ | P0 | D76: OCCT AIS_ViewCube, home button, drag to turn |
| Preset views (front, back, sides, isometric) | all | ✅ | P0 | D76: View › Views, Alt+1…Alt+0 |
| Perspective camera | all | ✅ | P0 | D76: View › Perspective (Shift+P), per view |
| Touchpad navigation | all | ✅ | P0 | D89: two-finger scroll pans, Shift orbits, pinch zooms; scroll preference |
| Walk / fly mode | AC RV VW SU | ⬜ | P2 | |
| Hide, isolate, show all (per element, per level) | all | ✅ | P0 | |
| Hide / isolate by class or type | all | ⬜ | P0 | |
| Plan cut height | AC RV VW BB | ✅ | P1 | Slider beside the view |
| Poché on cut elements | AC RV VW | ✅ | P1 | D96: fill from the building material; composites cut layer by layer |
| Section box | AC RV VW BB | 🟡 | P0 | Around the selection; no drag handles |
| Free clipping planes, several at once | AC RV BB | ⬜ | P0 | |
| Saved views (layers, level, plan/3D, cut) | AC RV VW BB | ✅ | P1 | D57 |
| Lines-only / hidden-line display | all | ✅ | — | L |
| Visual styles: shaded, textured, sketch, X-ray | all | 🟡 | new | Shaded and lines only |
| Shadows and sun position | AC RV VW SU | 🟡 | new | D96: View › Sun shadows (a fixed sun), White model; no sun position yet |
| Hover info (name, type, level) | AC RV VW | ✅ | — | |
| Colour by property, class or type | AC RV VW BB | ✅ | P1 | D73 override rules (property, class, kind, layer, material) |
| Show multiple levels at once (ghost story / underlay) | AC RV VW | ✅ | new | D98: View › Trace reference (level below or above, snappable); Level above/below Ctrl+Up/Down |
| Split views / several windows side by side | AC RV VW | ⬜ | new | |
| Navigator / project browser (tree of views, sheets) | AC RV VW | 🟡 | new | Model tree, levels, views; no sheets |

## 3. Selection

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Click, Ctrl/Shift add and toggle | all | ✅ | P0 | |
| Box selection (visible only; Alt goes through) | all | ✅ | P0 | D52 |
| Crossing vs window box (direction decides) | RV VW SU | ✅ | new | D78: right to left crosses (dashed band) |
| Select similar (same type or class) | AC RV VW BB | ✅ | P0 | D78: Ctrl+Shift+A (type), Select all of this class |
| Find & Select / query (by property values) | AC RV VW BB | ✅ | P0 | D78: Ctrl+F panel; class, kind, type, property, layer, level, status, material; AND/OR; saved criteria |
| Selection sets (saved selections) | AC VW BB | ✅ | new | D78: in the project settings (versioned) |
| Marquee (area selection for 2D export or editing) | AC | ⬜ | new | |
| Magic wand (pick a shape from existing lines or edges) | AC VW | 🟡 | new | D84: fill from a closed shape or the area clicked in (fill_at) |
| Tab cycling through overlapping elements | RV AC | ✅ | new | D89: Tab / Shift+Tab, the click selects the highlighted one |

## 4. Editing tools (general)

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Undo / redo | all | ✅ | P0 | |
| Move, drag to move | all | ✅ | P0 | Joined walls follow; Ctrl detaches (D54) |
| Rotate | all | ✅ | P0 | |
| Stretch / extend a wall end | all | ✅ | P0 | |
| Copy / paste in the project | all | ✅ | P0 | Slice 17 (Ctrl+C / Ctrl+V onto the active level) |
| Duplicate, drag a copy (Ctrl+drag) | all | ✅ | P0 | Slice 17 (Ctrl+D, Ctrl+drag) |
| Copy to another level | AC RV | ✅ | P0 | |
| Mirror | all | ✅ | P1 | Slice 17 (Ctrl+M; Ctrl mirrors a copy) |
| Array: linear, rectangular, polar | all | 🟡 | P1 | Slice 17: linear and polar (Ctrl+U); rectangular = two linear |
| Offset (parallel copy) | all | ✅ | new | Slice 17: walls (parallel copy), slabs (grow/shrink) |
| Trim, extend to boundary, split, join | all | 🟡 | new | D80: walls and beams (split, trim/extend to an element, a grid line or a corner, join/merge, unjoin; Shift+S, Shift+T, Shift+J). Not yet: 2D lines, curved walls |
| Align (to an edge or face) | RV VW | ⬜ | new | |
| Elevate (change vertical position) | AC RV | 🟡 | new | Wall height; no general elevate |
| Resize / scale | AC VW SU | ⬜ | new | |
| Pick up and inject settings (eyedropper / match properties) | AC RV VW | ✅ | new | D97: Edit › Pick up / Inject settings (Ctrl+Alt+C / V) |
| Edit by polygon points (add, move, delete vertices; curve an edge) | AC RV VW | ⬜ | new | Archicad pet palette |
| Solid element operations (subtract, intersect, add) | AC RV VW | ⬜ | new | |
| Lock / pin elements | AC RV VW | 🟡 | new | Layers can be locked; elements cannot |
| Group / ungroup | AC VW SU | 🟡 | P1 | Models (D58) do the repeated-unit job; no plain groups |

## 5. Input aids

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Snapping (endpoint, midpoint, on element, grid) | all | ✅ | P0 | |
| Ortho / angle steps | all | ✅ | P0 | 15° steps, Shift = ortho |
| Typed lengths | all | ✅ | P0 | |
| Typed angles | all | ✅ | P0 | D89: the tracker's angle box (`<`), locks the direction |
| Coordinate input (absolute and relative x, y; polar) | AC VW | ✅ | new | D89: tracker beside the cursor in every point tool; Tab between boxes, `a`/`#` absolute |
| Guide lines, temporary references, inference lines | AC VW SU | 🟡 | new | D89: temporary guides (rest 0.5 s on a snap point), extensions and parallels; no dragged or permanent guide lines |
| Snap to perpendicular, tangent, intersection, wall faces | all | 🟡 | P0 | D89: intersections and parallels added; no tangent |
| Work planes (custom drawing planes) | AC RV VW SU | 🟡 | P0 | The active level only; D98 construction grid (spacing, angle, origin, grid snap) |
| Tool presets / favourites (saved tool settings) | AC VW | ✅ | new | D97: the Favourites button in the tool strip, kept in the project |

## 6. Building elements

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Walls: straight, layered, L/T joins | all | ✅ | P0 | |
| Walls: curved | all | 🟡 | new | D97: Wall tool › Curved (3 points), layered, doors/windows, stretch, split, fillet; no angled joins yet |
| Walls: slanted, trapezoid, custom profile | AC RV VW | 🟡 | new | D97: slant angle; no double-slanted or complex profiles yet |
| Wall flip, reference line (core / face) | all | ✅ | P0 | D97: six reference lines (outside face default), Model › Flip walls |
| Junction priorities (which layers run through) | AC RV | ✅ | new | D97: building-material priority → `IfcMaterialLayer.Priority`, used by the wall regenerator |
| Wall attached to a slab or roof above | AC RV | ⬜ | new | |
| Slabs by outline or from walls | all | ✅ | P0 | |
| Slab openings | all | ✅ | P0 | |
| Sloped slabs, slab edges | AC RV VW | ⬜ | new | |
| Doors and windows in walls (parametric) | all | ✅ | P0 | Basic types |
| Door/window variety: sliding, double, corner window, skylight, storefront | all | ⬜ | new | |
| Door swing and window symbols in plan | all | ⬜ | new | Check what the plan draws today |
| Generic opening (wall or slab hole without a filling) | AC RV VW | 🟡 | new | Slab openings only |
| Columns, beams from profiles | all | ✅ | P0 | |
| Slanted, tapered, segmented columns and beams | AC RV | ⬜ | new | |
| Grids | all | ✅ | P0 | D98: Grid system (numbered and lettered axes at once) |
| Stairs: straight flight | all | ✅ | P1 | |
| Stairs: landings, L/U shapes, spiral, by sketch | all | 🟡 | P1 | D88: L, U, by sketch with landings, risers from the height, code warnings, floor opening, plan symbol; no winders or spiral yet |
| Railings | all | ✅ | P1 | D88: on a stair or ramp's sides (they follow it) or by path; posts, top rail, balusters |
| Ramps | AC RV VW | ✅ | new | D88: straight and L, slope with a 1:12 warning, plan arrow |
| Roofs: flat | all | ⬜ | P1 | |
| Roofs: pitched, hip, gable, multi-plane, by footprint | all | ⬜ | P1 | |
| Shell / free-form roof | AC RV | ⬜ | new | |
| Curtain walls (grids, mullions, panels) | AC RV VW | ⬜ | P2 | |
| Ceilings | RV VW | ⬜ | new | Archicad uses slabs |
| Zones / rooms / spaces (auto from walls, area, name, number) | all | ⬜ | P1 | Needed for area schedules and room tags |
| Area plans (gross, rentable) | RV VW | ⬜ | new | |
| Generic object (extrusion, revolve, mesh import) | all | ⬜ | P1 | |
| Morph / free-form modelling, push/pull | AC SU VW | ⬜ | new | Massing and odd shapes |
| Conceptual massing with floor areas | RV VW | ⬜ | new | |
| Models / modules placed on several levels | AC RV VW | ✅ | — | D58 (Archicad Hotlinked Modules, Revit Groups) |

## 7. Site

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Terrain from survey points or contours | AC RV VW BB | ⬜ | new | Archicad Mesh, Revit Toposolid, Vectorworks Site Model |
| Building pad / cut-and-fill | RV VW | ⬜ | new | |
| Hardscape, paths, parking | VW RV | ⬜ | new | |
| Plants and landscape | VW AC | ⬜ | new | |
| North direction, sun study | all | ⬜ | new | |

## 8. Objects and libraries

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Library browser (thumbnails, search, categories) | all | ✅ | P0 | D86: Library panel |
| Bundled library: furniture, sanitary, kitchen, lighting, people, trees, cars | all | 🟡 | P0 | D86: 21 parametric objects generated in code; no lighting yet |
| Place a library object | all | ✅ | P0 | D86: Object tool (Shift+O), Tab turns |
| Parametric object authoring | AC RV VW | ⬜ | new | Archicad GDL, Revit Family Editor, Vectorworks plug-in objects. Bonsai uses IFC types plus Python |
| Office libraries (shared folder or repo) | AC RV VW | 🟡 | P1 | D86: a folder of Python objects and IFC type files |
| Online object catalogues (BIMobject and others) | AC RV VW | 🔮 | new | |
| Paste between projects (with types and materials) | all | ⬜ | P1 | |

## 9. Organising the model

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Layers (shown, locked, active) | AC VW | ✅ | — | D57 |
| Layer combinations / view templates | AC RV VW | 🟡 | new | Saved views store layer states; no reusable templates |
| Graphic overrides / view filters (rules by property) | AC RV VW | ⬜ | new | Doc 13 lists per-view overrides as open |
| Classifications (Uniclass, OmniClass, local) | AC RV VW BB | ⬜ | P1 | |
| Element types: assign, edit type, update all | all | 🟡 | P0 | Type values and overrides ✅ (D50); no type manager |
| Property editing, psets, bulk edit | all | ✅ | P0 | |
| Dimensions group (length, height… edits the shape) | AC RV | ✅ | — | |
| Expression / calculated properties | AC RV VW | ⬜ | new | Archicad expression-based properties, Revit formulas |
| Renovation status (existing / demolish / new) and filters | AC RV VW | ✅ | new | D74: Archicad statuses, renovation filters in purposes, legends; Revit phases not done |
| Design options | AC RV VW | ✅ | P0 | KimBim uses branches (D56); Archicad and Revit store options inside one file |

## 10. Attributes and graphics standards

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Layered (composite) wall and slab types | all | ✅ | P0 | |
| Material editor (cut fill, surface, physical data) | all | ✅ | P0 | D96: Graphics › Building materials / Surfaces / Composites; IFC materials, styles and psets |
| Pen sets / line weights by scale | AC RV VW | 🟡 | new | D73: pen sets (255 pens), element styles, purposes; weights don't change with the scale yet |
| Graphic overrides and model view options (visibility by kind, rules) | AC RV VW | ✅ | new | D73: visibility sets, override rules (property, layer, material), layer combinations in purposes |
| Line types and fill patterns (hatches) | all | 🟡 | new | D73: line types (dash patterns in mm); cut fills are solid, no hatches yet |
| Surfaces / textures for 3D and rendering | all | ✅ | new | D96: surfaces (colour, transparency, shine, picture texture, box-mapped) per face in 3D, per-side overrides (D97); no rendering |
| Attribute manager (import/export standards between projects) | AC RV VW | ⬜ | new | |

## 11. Drawings (views made from the model)

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Floor plan drawings (one per story, cut plane, symbols) | all | ✅ | P1 | Slice 15: cut at 1.10 m (Archicad), door swings, window glass, annotations and markers drawn on |
| Section views (marker in plan, linked view) | all | 🟡 | P1 | Slice 14: Section tool (V), Archicad's three clicks; SVG from IfcOpenShell's serializer, in a tab (D60, D61). Not yet: scale setting, detail level, cropping by hand |
| Elevations (building, interior) | all | 🟡 | P1 | Slice 14: template N/S/E/W elevations in new projects, *Create elevations*, Elevation tool (Shift+V). Interior elevations: an elevation with a limited depth |
| Detail views (enlarged, cropped, with extra 2D) | all | 🟡 | P1 | D98: worksheets (independent 2D, figures, on sheets); no linked details/callouts yet |
| Drafting views (2D only) | all | ✅ | new | D98: worksheets |
| 3D documents / axonometric drawings | AC RV VW | ⬜ | new | |
| Crop regions, view range, depth | AC RV VW | 🟡 | new | Depth: infinite / limited / zero (D61), in the bridge; no UI yet |
| Model view options (detail level by scale) | AC RV VW | ⬜ | new | |
| Drawings update when the model changes | all | 🟡 | P1 | Out-of-date bar + Regenerate; regenerated when brought to the front |

## 12. 2D drafting

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Lines, polylines, arcs, circles, splines | all | ✅ | new | D84: line, polyline, arc/circle, rectangle; D98: splines; snaps, typed lengths, grips; in plans, drawings, sheets, DXF |
| Fills / hatches (regions) | all | ✅ | new | D84: IfcAnnotationFillArea + IfcFillAreaStyleHatching; pattern table in project settings; pens fg/bg; area label; magic wand (Alt+click) |
| 2D symbols / blocks | AC VW | ⬜ | new | |
| Detail components (repeating patterns such as insulation, brick) | RV VW | ⬜ | new | |
| Image and PDF underlays (trace over a scan) | all | ✅ | new | D85: PDF page (pypdfium2) or PNG/JPEG on a level at 1:N, calibrated by two points; opacity, greyscale, tint, layer, lock, also in 3D; stored in the project and its versions |

## 13. Annotation

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Text labels | all | ✅ | P1 | Screen-sized; paper-unit size is open (doc 13) |
| Linear dimension (two points) | all | ✅ | P1 | |
| Marks (circle with a tag) | AC | ✅ | P1 | |
| Dimension chains, overall dimensions | all | 🟡 | P1 | Slice 15: chains (Shift+click); no overall dimension yet |
| Snap dimensions to wall faces, openings and layers | all | 🟡 | P1 | Slice 15: wall faces; openings and layer lines later |
| Automatic dimensioning of walls and openings | AC RV VW | 🟡 | new | D98: Model › Dimension selected walls (a chain per straight wall: ends and openings); no overall or grid chains yet |
| Angle, radius, arc-length, level and spot-elevation dimensions | all | 🟡 | P1 | D87: angle, radius, diameter, level (plan: slab top or level; sections: story levels) and spot elevation; no arc length yet |
| Associative labels and tags (show a property, follow the element) | all | ✅ | P1 | D87: Tag tool and Tag all; templates of schedule fields; styles (door/window marker, wall tag, room stamp, mark, label) in project settings; IfcRelAssignsToProduct |
| Leaders and arrows | all | ✅ | P1 | Slice 15: Leader tool (Shift+A) |
| Revision clouds | AC RV VW | ✅ | new | D87: on plans and sheets, revision in a triangle; no revision schedule yet |
| Section, elevation and detail markers | all | 🟡 | P1 | Section and elevation markers in plan (Slice 14); detail markers later |
| North arrow, scale bar | all | ✅ | new | D87: on plans and sheets; north follows IFC TrueNorth; the sheet's bar shows its drawing's scale |
| Keynotes | RV VW AC | ⬜ | new | |
| Room / zone stamps (name, number, area) | all | ✅ | P1 | Slice 18; D87: their text is the Room stamp tag style |

## 14. Sheets and output

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Sheets / layouts with drawings placed at scale | all | ✅ | P1 | Slice 16 (M4 exit): A1/A3, numbered, drag to place (D62) |
| Title blocks filled from project data | all | 🟡 | P1 | Slice 16: one built-in title block; custom templates later |
| Drawing and sheet lists (auto-numbered) | AC RV VW | ⬜ | new | |
| Revisions / issue management | AC RV VW | ⬜ | new | Could use versions and milestones (P2 item in 04) |
| Print, PDF export | all | ✅ | P1 | Slice 16: PDF and SVG per sheet (Qt, vector) |
| Batch publishing (sets of sheets to PDF/DWG) | AC RV VW | 🟡 | new | D83: File › Export DXF... exports ticked drawings and sheets to a folder (DXF; PDF stays one sheet at a time) |
| DWG/DXF export | AC RV VW BB | 🟡 | P1 | D83: DXF (ezdxf): drawings in model space at real size, sheets as paper-space layouts; lineweights, colours, linetypes from pens; poché hatches; real dimensions; layers by KimBim layer or kind. DWG not yet (open question) |

## 15. Schedules and quantities

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Element schedules (doors, windows, walls), editable | all | ✅ | P1 | D77: built-in and custom schemes, rows select elements, Name/Mark/property cells edit the model (one undo step) |
| Room / area schedules | all | ✅ | P1 | D77: the Rooms schedule (every IfcSpace) |
| Material take-off, quantities (area, volume, length) | all | 🟡 | P1 | D77: length, height, areas (net/gross side, openings), volume, count from Qto_ sets, parameters or shape; merge identical items + totals. Take-off by material layer later |
| Schedule on a sheet | all | ⬜ | new | |
| Export to CSV / XLSX | all | ✅ | P1 | D77 (openpyxl) |
| Cost estimating (5D) | BB AL | ⬜ | new | Bonsai has it |
| Construction sequencing (4D) | BB | ⬜ | new | Bonsai has it |

## 16. Visualisation

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Real-time textured 3D | all | ✅ | new | D96: surface pictures box-mapped; drawn defaults for brick, timber, tiles, stone, roof tiles |
| Photorealistic rendering | AC RV VW | ⬜ | new | Archicad CineRender, Revit cloud render, Twinmotion link. Could export to Blender |
| AI visualiser (sketch to image) | AC VW | 🔮 | new | |
| Sun / shadow studies, animations | all | ⬜ | new | |
| Walkthrough video, VR | AC RV VW | ⬜ | P2 | |

## 17. Collaboration and versions

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Save version, History, Compare (colours and list) | — | ✅ | P0 | KimBim's own feature (Slice 8). Competitors have backups and Revit compare add-ins at most |
| Milestones, object history, before/after | — | ✅ | P0 | Slice 20 (M5) |
| Combine options with conflict UI | — | ⬜ | P1 | M5 exit |
| Several people on one project (Teamwork, Worksharing, Project Sharing) | AC RV VW | 🔮 | P2 | Git remotes first ([08](08-future.md)) |
| External references (link another IFC/project, hotlinks, xrefs) | all | ⬜ | new | Models (D58) cover models inside one project only |
| Copy / monitor linked elements | RV | ⬜ | new | |
| BCF issues (import, export, viewpoints) | AC RV VW BB | ⬜ | new | |
| Markups and comments in the model | AC RV VW | ⬜ | new | |
| Cloud sharing with clients (web viewer) | AC RV VW | 🔮 | — | [08](08-future.md) |

## 18. Interoperability

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| IFC export, valid against the schema | all | ✅ | P0 | Checked in CI |
| IFC export settings (what to export, property mapping) | AC RV VW | ⬜ | new | |
| Re-import with reconciliation report | — | ⬜ | P1 | |
| DWG/DXF import (underlay and convert) | all | 🟡 | new | D85: DXF as an underlay (units, exploded blocks, snapping to ends, midpoints, crossings). No DWG yet, no convert to 2D elements. Architects receive most survey and consultant data as DWG |
| PDF import | AC RV VW | ⬜ | new | |
| SketchUp, Rhino, OBJ, FBX import | AC RV VW | ⬜ | new | |
| Point clouds | AC RV VW | ⬜ | new | |
| Rhino / Grasshopper live link | AC RV VW | ⬜ | new | |

## 19. Analysis and checking

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Measure distance, angle, area | all | ✅ | P1 | D79: Shift+M, snaps, 3D surfaces, copy to clipboard |
| IFC schema validation in the app | BB | ✅ | P1 | Checks panel, EXPRESS rules included (D81) |
| IDS checks | AC BB | ✅ | P1 | IfcTester; IDS files kept in the project; HTML/JSON report (D81) |
| Clash detection | AC RV VW BB | ✅ | P2 | Hard and clearance between classes or Find & Select criteria (D81); no BCF yet |
| Model checks (duplicates, overlaps, rooms without a number) | AC RV | ✅ | P2 | Duplicates, rooms, zero-length walls, not on a level, hostless openings (D81) |
| Energy evaluation, daylight | AC RV VW | ⬜ | new | |
| Structural analytical model | AC RV | ⬜ | new | Probably out of scope for architects |

## 20. Automation and customisation

| Tool | Has | KimBim | Pri | Notes |
|------|-----|--------|-----|-------|
| Python console with the model API | RV(pyRevit) BB | ✅ | P1 | D82: Console panel, `edit()` as one undo step, Stop; [15](15-scripting.md) |
| Visual programming | AC RV VW | ⬜ | new | Grasshopper, Dynamo, Marionette |
| Plugins / add-ons | all | ⬜ | P2 | |
| Customisable shortcuts, toolbars and workspaces | all | ⬜ | new | |
| UI languages | all | ✅ | P0 | English and Spanish |
| AI assistant | AC RV VW | 🔮 | — | [08](08-future.md) |

---

## Largest gaps

These are the gaps that most often stop an architect from finishing a real project in KimBim, roughly in the order
they would come up:

1. **Drawings and sheets** (§11, §13, §14): sections, elevations, sheets with title blocks and PDF export. This is the M4 exit and the deliverable clients pay for.
2. **Rooms / zones with areas**, plus tags and room schedules (§6, §13, §15).
3. **Roofs** (§6). Almost every house has one.
4. **Everyday editing**: copy/paste, duplicate, mirror, array, offset, trim/extend (§4).
5. **Library objects and furniture** (§8).
6. **DWG import as an underlay** (§18, §12). Most projects start from a survey in DWG.
7. **2D drafting and fills** for details (§12).
8. **Pen sets, line types and material cut fills** (§10), so printed drawings look professional.
9. **Navigation backlog**: ~~view cube, preset views, perspective~~ done (D76); touchpad (§2).
10. ~~**Renovation status** (§9), needed for refurbishment projects.~~ Done (D74).

Next step: the owner confirms or reorders this list, and gives priorities to the `new` rows. 04 is then updated to match.
