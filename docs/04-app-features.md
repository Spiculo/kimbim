# 04 — Application Features (the local BIM app)

**Decided (owner answer 6):** the focus is the **local app**: a capable BIM tool for architects, with cuts, object data, cloning and libraries. Everything network-related is future work.

Each feature notes **what we reuse**. Priorities: **P0** is needed for first usable release, **P1** follows soon after, **P2** comes later.

## 1. Project and files

| Feature | Pri | Notes / reuse |
|---------|-----|---------------|
| Open / edit / save IFC4 | P0 | IfcOpenShell; MVP schema (D30) |
| Open / edit / save IFC4X3 in its own schema | P0 best-effort, P1 full | Same code path; schema-agnostic ([02](02-data-model-and-format.md#ifc-schema-version)) |
| Import IFC2X3 | P0 | |
| New IFC4X3 projects; explicit schema upgrade command | P1 | `ifcpatch` Migrate |
| Save / Save As IFC (Plain mode) | P0 | IfcOpenShell writer; deterministic step IDs |
| New project from template (units, site/building/storeys) | P0 | `ifcopenshell.api` `root`, `aggregate`, `unit`; office templates (D72) |
| Versioned project create / open | P0 | [03](03-versioning.md) |
| Recent projects, autosave, crash recovery | P0 | Done (D72): File › Recent files; a recovery copy of unsaved work every N minutes, offered after a crash |
| `.kim` project file (one file, or "open as folder") | P0 | Done (D72): model, settings and history in one zip; locks; read-only for a second editor |
| User preferences | P0 | Done (D72): Edit › Preferences (language, templates folder, your name, new views as tabs or windows, IFC opening, the size above which opening an IFC asks first, automatic versions, recovery) |
| Project settings | P0 | Done (D72): File › Project settings (plan cut height, drawing scale, sheet paper, length units); layer states kept; versioned |
| Office templates | P0 | Done (D72): File › New project lists the templates folder; File › Save as template |
| Units: metric and imperial | P0 | IfcOpenShell unit utils |
| Georeferencing | P2 | `ifcopenshell.api.georeference` |

## 2. Viewport and navigation

Navigation preset (D48, owner choice): middle-drag pans, Shift+middle-drag orbits around the point under the mouse, the wheel zooms toward the cursor; a drag ends when its button is released. Selection: click replaces, Ctrl+click adds (Revit), Shift+click toggles (ArchiCAD), left-drag draws a box. The box takes the elements fully inside it **that you can see** (D52); hold **Alt** while dragging (or turn on View › Select hidden elements too) to also take elements hidden behind others.

Display (Slice 4b): every element has border lines (outline and creases); View › **Lines only** (L) shows a line drawing with hidden lines removed, meant for plans. Plan view (P) and 3D view (3) exist.

**View cube, preset views, perspective (D76).** Each 3D view has a view cube in its top-right corner: click a face, edge or corner to turn there (a quick 250 ms turn), drag it to turn the view, and click the house beside it to go home (the default south-east isometric, fitted). **View › Views** has Top, Bottom, Front, Back, Left, Right (Alt+1 to Alt+6) and the south-west, south-east, north-east and north-west isometrics (Alt+7 to Alt+0), and Home view (Home). A preset keeps your target and zoom unless the model would be off-screen, then it fits all. **View › Perspective** (Shift+P) switches the active 3D view between parallel and perspective; navigation is the same in both. Plan views stay parallel, looking down with north up, and have no cube.

**Window layout (D71).** The center holds tabs: **3D**, a **plan tab per level** (P opens the active level's, or double-click a level in the tree; View › New plan tab), sections, elevations and sheets. Any tab can be dragged out to its own window (a second monitor) and docked back, or placed beside another. The 3D and plan tabs show one loaded model: selecting in one selects in all; each has its own camera and cut (a plan tab is cut at its level). Switching tabs ends a tool in progress, like Esc.
- **Left:** the tools, in collapsible groups **3D** (wall, slab, column, beam, door, window, stair, roof, room, slab opening, place model), **Plane** (text, dimension, leader, mark, grid line), **View** (section, elevation, new plan tab, new sheet) and **Edit** (move, rotate, stretch, mirror, copy to level). Shortcuts and the Model menu are unchanged.
- **Above the active view:** the active tool's fields (type, height, roof shape and pitch, typed length), only while a tool is active.
- **Right:** the model tree, Properties, Layers, History, Drawings and Sheets as tabs; the area can auto-hide or float. **Double-click** an element (in a view or the tree) to bring Properties forward.
- **Bottom:** the **purpose** (D73: Working, Highlight, Permit, Presentation, Demo, or your own; "…" changes its pen set, visibility, overrides and layers), the current pen (click: a 16×16 grid), the active layer, the visible layers, the zoom, the selection ("2 Walls") and messages.
- **Graphics menu** (D73): pen sets, line types, element styles, visibility sets, graphic overrides, renovation filters (D74), layer combinations, purposes. View › True line weights draws lines as thick as their pens.
- **Renovation** (D74): each element is Existing, To be demolished or New (Properties panel, Model › Renovation status; new elements take the bottom bar's status for new elements). The purposes Existing, Demolition and New construction show the matching plans; the purpose popup shows their legend, and a sheet's right-click menu places one. Opening an IFC with unmarked elements offers to mark them.
- **Top:** one bar with the design option (versioned projects), the active level and the cut controls.
- The layout is remembered between sessions; a window left on a missing monitor comes back to the default layout.

**Model tree:** one row for Project › Site › Building when there is only one of each; plain names ("Wall"); a level's elements grouped by category with a count ("Walls (12)"); the IFC class shows on hover and the search still matches it.

**Navigation backlog** (owner, 2026-10-05: "we need those, document them for now"):
- ~~View cube, preset views~~ Done (D76).
- ~~**Touchpad navigation**: two-finger drag pans, pinch zooms, and a way to orbit without a middle button~~ Done (D89: Shift+two-finger scroll orbits; Edit › Preferences › Scroll and touchpad).
- ~~Perspective toggle~~ Done (D76).

| Feature | Pri | Notes / reuse |
|---------|-----|---------------|
| Orbit / pan / zoom, fit, standard views, perspective/ortho | P0 | Done (D48, D76) |
| Selection: click, box, add/remove, select similar (same type/class) | P0 | |
| Hide / isolate / show all, by object, class or storey | P0 | |
| Color by property / class / type / storey | P1 | |
| Storey navigation (jump to level, show only this level) | P0 | |
| Walk mode | P2 | |
| Measure distance / angle / area | P1 | |

## 3. Cuts (sections and clipping)

| Feature | Pri | Notes / reuse |
|---------|-----|---------------|
| **Section box** with draggable faces | P0 | Renderer clipping planes ([05](05-geometry-rendering-drawings.md)) |
| **Clipping planes** (any orientation, multiple) | P0 | |
| **Section fill (capping)** on cut faces, colored by material | P1 | OpenCASCADE visualization supports capping |
| Saved views (camera + cut + visibility), stored in the project | P1 | Can map to BCF viewpoints later |
| Plan cut at storey height (live plan view in 3D) | P1 | |

## 4. Object data

| Feature | Pri | Notes / reuse |
|---------|-----|---------------|
| Property panel: attributes, property sets, quantities | P0 | `ifcopenshell.util.element` |
| Edit properties, add/remove property sets, custom psets | P0 | `ifcopenshell.api.pset` |
| Standard pset templates (Pset_WallCommon…) with validation of types/enums | P0 | IfcOpenShell bundled pset templates |
| Classifications (Uniclass, OmniClass, local systems) | P1 | `ifcopenshell.api.classification`; bSDD lookup in P2 |
| Materials: single, layer sets, profile sets, constituents | P0 | `ifcopenshell.api.material` |
| Type / instance: assign type, edit type to update all instances | P0 | `ifcopenshell.api.type` |
| Quantity take-off (auto-calculated quantities) | P1 | IfcOpenShell `ifc5d` / qto utilities |
| **Bulk edit**: set a property on a selection | P0 | |
| **Type vs. element values** (D50): values inherited from the element's type are dimmed; editing writes the element's own value (an override); *Edit type value…* changes the type for every element of it, after a confirmation with the count; *Reset to type value* drops the override | P0 | `ifcopenshell.util.element.get_type` |
| **Schedules**: table views of objects × properties, editable, CSV/XLSX export | P1 | Bonsai/IfcOpenShell `ifccsv` |
| Search and filter with a query language | P0 | `ifcopenshell.util.selector` syntax (e.g. `IfcWall, Pset_WallCommon.FireRating=EI60`) |
| Object history panel (versioned projects) | P0 | ✅ Slice 20: *Object history…* dialog ([03](03-versioning.md#object-history-blame)) |

## 5. Modeling

All modeling goes through commands, with undo/redo ([01](01-architecture.md#engine-boundaries)).

| Feature | Pri | Notes / reuse |
|---------|-----|---------------|
| Levels (storeys) and grids | P0 | `ifcopenshell.api.spatial`, `grid` — levels ✅ (Slice 4), grids ✅ (Slice 6) |
| Walls: layered (by type), draw by axis, join at corners/T, flip | P0 | ✅ Slice 4 (flip: later). `geometry.create_2pt_wall`, `connect_wall`, `regenerate_wall_representation` — Bonsai's wall logic, already in ifcopenshell 0.9, no port needed |
| Slabs / floors from outline or from walls | P0 | ✅ Slice 5 (top of slab at the level; from walls = outer faces of a closed loop); slab openings ✅ Slice 7 |
| Copy to another level | P0 | ✅ Slice 7 (walls with their openings, doors/windows and joins; slabs, columns, beams) |
| Openings + doors + windows hosted in walls (parametric types) | P0 | ✅ Slice 5: `geometry.add_door/window_representation` + `feature.add_feature/add_filling`; moving/resizing placed doors: Slice 6 |
| Columns and beams from profile types | P0 | ✅ Slice 6 (`geometry.add_profile_representation`, material profile sets) |
| Roofs (flat; pitched later) | P1 | |
| Spaces / rooms (auto from boundaries), area | P1 | |
| Stairs and railings (basic parametric) | P1 | Straight-flight stair ✅ Slice 7 (own generator: ifcopenshell has none outside Bonsai); landings, other shapes and railings: later |
| Curtain walls | P2 | |
| Generic object (extrusion, mesh import) | P1 | |
| Snapping (endpoint, midpoint, perpendicular, grid, axis) and work planes | P0 | ✅ Slice 4 (on wall, 15° angles, ortho with Shift; work plane = active level) |
| Precise input (typed distances/angles) | P0 | Typed lengths ✅ Slice 4; typed angles: later |
| Edit geometry: move, rotate, stretch/extend wall, change height | P0 | ✅ Slice 6. Joined walls follow a moved wall (Revit-like, owner decision D54); Ctrl detaches |

## 6. Cloning

| Feature | Pri | Notes / reuse |
|---------|-----|---------------|
| Copy / paste (within project, keeping types) | P0 | `ifcopenshell.api.root.copy_class` |
| Duplicate in place / with offset | P0 | |
| Array: linear, rectangular, polar | P1 | Bonsai array support (port) |
| Mirror | P1 | |
| Copy to other storeys | P1 | |
| Paste between projects (brings types/materials along) | P1 | `ifcopenshell.api.project.append_asset` |
| Groups / assemblies (copy as one) | P1 | `IfcElementAssembly`, `IfcGroup` |

Clones get **new KIMCAD IDs and GlobalIds**. They never share identity with the source.

## 7. Libraries

| Feature | Pri | Notes / reuse |
|---------|-----|---------------|
| Library = an IFC file (or versioned KIMCAD repo) containing types, materials, profiles and their psets | P0 | Same approach as Bonsai asset libraries |
| Library browser panel: thumbnails, search, categories | P0 | |
| Drag a type from the library into the project | P0 | `ifcopenshell.api.project.append_asset` |
| Bundled default library (walls, slabs, doors, windows, furniture, profiles) | P0 | Seed from IfcOpenShell/Bonsai demo libraries where licenses allow |
| Office libraries: shared folder or Git repo of libraries | P1 | Versioned libraries are just KIMCAD repos |
| Update project types from a newer library version | P2 | Diff/merge of type records |

## 8. Drawings (2D documentation)

| Feature | Pri | Notes / reuse |
|---------|-----|---------------|
| Generate plans, sections, elevations from the model | P1 | IfcOpenShell **SVG serializer** (hidden-line removal, cut fills), as used by Bonsai. ✅ Sections and elevations (Slice 14, D60/D61); plans: Slice 15 |
| Annotations: dimensions, text, tags (door/window/room tags), level marks | P1 | IFC annotation entities (`IfcAnnotation`), stored in the model |
| Sheets with title blocks; place drawings at scale | P1 | Bonsai's drawing/sheet approach (SVG-based) |
| Export PDF / SVG; DXF (D83) | P1 | |
| Drawings update automatically when the model changes | P1 | 🟡 Slice 14: marked out of date, regenerated in the background when shown or on Regenerate |
| Show version/milestone on the title block (from repo) | P2 | Bonsai already does this with `git describe` |

## 9. Versioning UI (versioned projects)

| Feature | Pri | Notes |
|---------|-----|-------|
| "Save version" dialog: message, changed-objects summary | P0 | ✅ Slice 8 (Ctrl+Alt+S; Ctrl+S in a versioned project) |
| History timeline (versions, milestones, design options) | P0 | ✅ Slice 8: History dock per option; ✅ Slice 20: milestones shown in bold with ◆ |
| Compare any two versions: viewport coloring + change list + before/after | P0 | ✅ Slice 8: version vs current or two versions, added green / modified orange, change list (click selects); ✅ Slice 20: before/after per element (field by field) |
| Design options: create, switch, delete | P0 | Branches. ✅ Slice 8: create, switch (with an unsaved-changes guard); delete: Slice 20 |
| Combine options with conflict resolution UI | P1 | ✅ Slice 22 (M5 exit): dialog, combined model as preview, two-parent version ([03](03-versioning.md#merge-combine-options)) |
| Milestones | P0 | ✅ Slice 20: annotated tags (D67) |
| Re-import from external tool with reconciliation report | P1 | [03](03-versioning.md#import-reconciliation) |
| Remotes: push/pull to a Git host | P2 | [08](08-future.md) |

## 10. Checking (local)

| Feature | Pri | Notes / reuse |
|---------|-----|---------------|
| IFC schema validation | P1 | `ifcopenshell.validate` |
| IDS check (local, on demand) | P1 | IfcTester (IfcOpenShell, LGPL) |
| Clash detection between selections | P2 | `ifcclash` / `IfcGeom::tree` |
| Local pre-commit checks (configurable rules that block or warn on "Save version") | P2 | Owner answer 5 |

## 11. Scripting and extensibility

| Feature | Pri | Notes |
|---------|-----|-------|
| Python console with the model API | P1 | Done (D82): Console panel (View › Panels, Ctrl+Alt+P), Run Python script...; see [15](15-scripting.md) |
| Plugins (Python) that add commands and panels | P2 | |
| C ABI for native plugins / other languages | P2 | `kimcad-ffi` |

## 12. Languages (i18n)

**Decided (D29):** the UI is internationalized from the first line of code. It launches in **English and Spanish**.

| Feature | Pri | Notes / reuse |
|---------|-----|---------------|
| All C++ UI strings through `tr()`; translations with Qt Linguist (`.ts` → `.qm`) | P0 | Qt i18n |
| Python strings (commands, plugins) through `gettext` | P0 | |
| Language switch in preferences (defaults to the OS language) | P0 | |
| Locale-aware number, date and unit formatting (decimal comma in Spanish locales) | P0 | `QLocale` |
| Translated IFC class and property labels (e.g. "Muro" for `IfcWall`, "Resistencia al fuego" for `FireRating`) | P1 | Display labels only; data stays standard IFC. bSDD provides multilingual names (P2) |
| Translated docs and default library names | P2 | |
| Community translation workflow (e.g. Weblate) for more languages | P2 | |

Rules:

- **Model data is never translated.** IFC class names, pset/property names and enumerations are stored exactly as the standard defines them. Translation happens only at display time.
- No hard-coded user-visible strings, and no sentences assembled from fragments, because word order differs between languages.
- CI fails on untranslated strings in English or Spanish.

## UX principles

- **Architect vocabulary in the UI** ([00](00-vision-and-scope.md#audience)). Show IFC class names as secondary information, not as the primary label.
- **Familiar patterns** from mainstream BIM tools: tools grouped by category on the left, the model tree and properties on the right (D71), a bottom bar with layers, zoom and selection.
- **Room for the model.** Panels are tabbed and can auto-hide; views are tabs that can move to another window.
- **Nothing blocks.** Long operations show progress and can be cancelled.
- **Every action can be undone.** Versioned projects add a second safety net: any saved version can be restored.
