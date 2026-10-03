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
| New project from template (units, site/building/storeys) | P0 | `ifcopenshell.api` `root`, `aggregate`, `unit` |
| Versioned project create / open | P0 | [03](03-versioning.md) |
| Recent projects, autosave, crash recovery | P0 | oplog ([03](03-versioning.md)) |
| Units: metric and imperial | P0 | IfcOpenShell unit utils |
| Georeferencing | P2 | `ifcopenshell.api.georeference` |

## 2. Viewport and navigation

| Feature | Pri | Notes / reuse |
|---------|-----|---------------|
| Orbit / pan / zoom, fit, standard views, perspective/ortho | P0 | |
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
| **Schedules**: table views of objects × properties, editable, CSV/XLSX export | P1 | Bonsai/IfcOpenShell `ifccsv` |
| Search and filter with a query language | P0 | `ifcopenshell.util.selector` syntax (e.g. `IfcWall, Pset_WallCommon.FireRating=EI60`) |
| Object history panel (versioned projects) | P0 | [03](03-versioning.md#object-history-blame) |

## 5. Modeling

All modeling goes through commands, with undo/redo ([01](01-architecture.md#engine-boundaries)).

| Feature | Pri | Notes / reuse |
|---------|-----|---------------|
| Levels (storeys) and grids | P0 | `ifcopenshell.api.spatial`, `grid` |
| Walls: layered (by type), draw by axis, join at corners/T, flip | P0 | `ifcopenshell.api.geometry` + Bonsai wall-joining logic (port) |
| Slabs / floors from outline or from walls | P0 | |
| Openings + doors + windows hosted in walls (parametric types) | P0 | IfcOpenShell parametric door/window representations (used by Bonsai) |
| Columns and beams from profile types | P0 | Profile sets |
| Roofs (flat; pitched later) | P1 | |
| Spaces / rooms (auto from boundaries), area | P1 | |
| Stairs and railings (basic parametric) | P1 | Bonsai parametric stair/railing (port) |
| Curtain walls | P2 | |
| Generic object (extrusion, mesh import) | P1 | |
| Snapping (endpoint, midpoint, perpendicular, grid, axis) and work planes | P0 | |
| Precise input (typed distances/angles) | P0 | |
| Edit geometry: move, rotate, stretch/extend wall, change height | P0 | |

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
| Generate plans, sections, elevations from the model | P1 | IfcOpenShell **SVG serializer** (hidden-line removal, cut fills), as used by Bonsai |
| Annotations: dimensions, text, tags (door/window/room tags), level marks | P1 | IFC annotation entities (`IfcAnnotation`), stored in the model |
| Sheets with title blocks; place drawings at scale | P1 | Bonsai's drawing/sheet approach (SVG-based) |
| Export PDF / SVG; DXF later | P1 | |
| Drawings update automatically when the model changes | P1 | |
| Show version/milestone on the title block (from repo) | P2 | Bonsai already does this with `git describe` |

## 9. Versioning UI (versioned projects)

| Feature | Pri | Notes |
|---------|-----|-------|
| "Save version" dialog: message, changed-objects summary | P0 | |
| History timeline (versions, milestones, design options) | P0 | |
| Compare any two versions: viewport coloring + change list + before/after | P0 | |
| Design options: create, switch, delete | P0 | Branches |
| Combine options with conflict resolution UI | P1 | [03](03-versioning.md#merge-combine-options) |
| Milestones | P0 | Tags |
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
| Python console with the model API | P1 | Embedded CPython + `ifcopenshell` |
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
- **Familiar patterns** from mainstream BIM tools: ribbon or toolbar with tools by discipline, properties on the right, project browser on the left, status bar with snapping.
- **Nothing blocks.** Long operations show progress and can be cancelled.
- **Every action can be undone.** Versioned projects add a second safety net: any saved version can be restored.
