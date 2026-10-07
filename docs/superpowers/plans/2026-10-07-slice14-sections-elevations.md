# Slice 14 (M4, part 1) — Sections and elevations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** ready. Task 0 (the risk check) is done; its results are below and in [11](../../11-spike-results.md#s6--drawings-svg-serializer-slice-14-risk-check). The owner answered the scope questions on 2026-10-07: **follow Archicad's conventions** (D61, see "Owner decisions" at the end).

**Goal:** an architect can draw a section line in plan, get the automatic North/South/East/West elevations, list the drawings, and open any of them in a 2D tab (pan, zoom) that regenerates when the model changes.

**M4 exit (the target of Slices 14–16):** the sample two-storey house produces a plan, a section and an elevation on a sheet with a title block, exported to PDF; CI checks it.

**Done when:**
- the house section shows cut walls and slabs filled (poché) and the rest in projection;
- editing a wall and regenerating shows the change;
- generation time on Clinic_Architectural is measured and written down in 11.

**Architecture:**
- **Drawing definition (D60):** an `IfcAnnotation` with `ObjectType = "DRAWING"`, Bonsai's approach. Its placement is the camera (local Z points back at the viewer; it looks along −Z, X is the drawing's right). Its `Body` representation (Model/Body/MODEL_VIEW) is an `IfcCsgSolid` of an `IfcBlock` giving width × height × depth: the box the drawing sees. `EPset_Drawing` holds `TargetView` (PLAN_VIEW / SECTION_VIEW / ELEVATION_VIEW) and `Scale` (`1/100`). KIMCAD-only settings go in `KIMCAD_Drawing` (kind, which levels, the section line's two plan points, auto-elevation side). The drawing is model data: versioned, undoable, kept by GlobalId.
- **Generation:** `kimcad/drawings.py` (bridge module, like `annotations.py`) runs IfcOpenShell's SVG serializer with `elevation-ref-guid = <drawing GlobalId>`. The iterator gets only the elements that can appear (the drawing's own annotation is required, openings/spaces/other annotations are left out, plan drawings are pre-filtered to their level, and sections/elevations to the elements visible from the camera), with all CPU threads. Settings come from the S6 spike: `svg-poly` (polygon HLR, 1.1–1.6× faster with the same output), `svg-prefilter`, no `svg-unify-inputs`, `door-arcs`, `svg-write-poly`, paper size from `bounds` and `scale`.
- **Cache:** generated SVG is derived data, never model data. Key: drawing GlobalId + the bridge's model edit counter (any edit makes every drawing stale; per-drawing staleness by bounding box is a later optimisation). Cache lives in memory, plus `.kimcad/drawings/` in versioned projects so reopening is instant.
- **Threading:** the serializer holds the GIL for the whole hidden-line pass (S6: a 4.7 s stall), so generating in the app's Python would freeze the GUI. The bridge takes a snapshot (`to_string`, 0.25 s for 5 MB) and a child process (`python -m kimcad.drawgen`) opens it, generates, and returns the SVG; the C++ side waits on it from a worker `QThread`. One child per generation at first; a long-lived worker fed with the edit deltas only if snapshots get slow on big files.
- **Visible elements (sections and elevations):** HLR time grows with everything behind the cut (S6: elevation 52 s with all elements, 3.4 s with the visible ones). Before generating, the viewport renders element IDs from the drawing's camera into an offscreen image, the same pass box selection uses (D52), and only the IDs seen (plus the elements the cut plane crosses) go to the serializer.
- **App:** a Section tool (two clicks in plan, then a click for the look direction), an Elevations command (creates the four, sized from the building's bounding box), a Drawings panel (list, rename, delete, open), and a 2D drawing tab (`QSvgRenderer` in a `QGraphicsView`: wheel zoom at the cursor, middle-drag pan, fit), with a "stale" badge and Regenerate.

**Tech Stack:** IfcOpenShell 0.9.0 (SVG serializer, `ifcopenshell.api`), Qt 6 (adds the `Svg` module: `QSvgRenderer`; it is in conda-forge `qt6-main`), pytest, Qt Test.

**Spec:** docs/05 "Drawings (2D)", docs/04 §8, docs/07 M4, docs/14 §11.

## What the risk check found (Task 0, done)

| Finding | Consequence for the slice |
|---------|---------------------------|
| 0.9.0 has no `addDrawing()` on the serializer, but `elevation-ref-guid` + a DRAWING annotation works, the same way `ifcopenshell.draw` and Bonsai do it | D60 as proposed; no custom C++ |
| The drawing annotation must be **in** the iterator's elements, or the output is empty | `drawings.py` always includes it |
| `IfcOpeningElement` must be excluded, or openings are drawn as solid cut fill across doors and windows | Exclude openings, spaces and other annotations |
| House: plan / section / elevation in 0.25–0.33 s each; walls and slabs cut with poché, windows and doors in projection; output is in paper millimetres at 1:100 | Quality is good enough to build on |
| No door swings in plan (`door-arcs` needs a swing in the door's representation) | Door symbols are Slice 15, as planned |
| Clinic_Architectural in CI: plan of First Floor 6.4 s; section 17–26 s and elevation 22–34 s with every element (geometry 7–11 s, HLR 9–21 s). Synthetic 2,880-product model: hidden-line removal dominates. plan 6.8 s (10.6 s with exact HLR); section 26 s; elevation 52 s, but 3.4 s when only the visible front row is given ([11](../../11-spike-results.md#s6--drawings-svg-serializer-slice-14-risk-check)) | Use `svg-poly`; pre-filter plans by level; a visible-element pass for sections and elevations; show the old drawing until the new one is ready |
| The serializer holds the GIL during `write` and `finalize` (4.7 s main-thread stall) | Generate in a child process from a model snapshot (0.25 s + 0.3 s for 5 MB) |
| The drawing's camera box is a `Body` representation, so the 3D view would mesh it as a large solid | Leave DRAWING annotations out of meshing and picking |
| The existing annotation listing reads `KIMCAD_Annotation`; drawings don't have it | No conflict, but add a test |

## Global Constraints

- Drawings are model data (D60); SVG is a cache and never written into the IFC.
- Stored hashes for the sample files must not change (golden tests): nothing is added to a model unless the user creates a drawing.
- Every edit is one undo step; GlobalIds are kept.
- EN/ES UI strings; SPDX; DCO; headless CI (generation tests run without a GPU).

## Review Focus

1. A model with drawings still validates (IFC4 schema + EXPRESS rules) and still opens in web-ifc (the M3 check, extended to a house with drawings).
2. The 3D view never shows a drawing's camera box; selection never picks it.
3. Editing a wall marks every drawing stale, and regenerating shows the change (SVG differs where the wall is).
4. Generation never blocks the UI thread for more than one frame on the house, and the UI stays usable during a long generation on a big model.
5. Deleting a drawing is undoable and leaves no orphan representation, context or property set.

---

### Task 0: Risk check ✅
Spike S6 (`spikes/s6_drawings/drawing_bench.py`), results in 11.

### Task 1: Bridge — drawing definitions and generation ✅
- [x] `kimcad/drawgen.py` (ifcopenshell + numpy only): camera from a marker line and a look point, infinite ranges fitted to the model, template markers, SVG cropped to its content; runs as `python drawgen.py SNAPSHOT.ifc GUID [INCLUDE.json]` in a child process (S6: the serializer holds the GIL).
- [x] `kimcad/drawings.py`: `create_section(x1, y1, x2, y2, look_x, look_y, depth)` (depth < 0 = Infinite, 0 = the cut only; no level, as in Archicad), `create_elevation(...)`, `create_template_elevations()` (N/S/E/W; called by `new_project`, outside the undo history), `drawings()` → `[{guid, name, kind, depth, auto, points, look, stale}]`, `rename_drawing`, `set_drawing_depth`, `delete_drawing`, `generate_drawing(guid, include_json)` → `{svg, cached, timing}`; the cache keeps the last 4 model states per drawing, so undo returns to a cached drawing.
- [x] Tests `tests/python/test_drawings.py` (9): template elevations in new projects only; section from two points and a look side (undoable, validates, not a plan annotation); cut walls and slabs + projection, openings not drawn, cropped at 1:100, cached; moving a wall → stale → different SVG, undo → the old one; template elevations follow the model; depth, rename, delete (no orphan representation or property sets), undo; bad input refused; drawings not meshed.

### Task 2: Keep drawings out of the 3D view ✅
- [x] `start_meshing` / `mesh_elements` skip `IfcAnnotation` (plan annotations are 2D and drawn by the overlay; the iterator cannot exclude single instances by class name and GlobalId together). Drawings are not in a level, so the model tree does not list them; the Drawings panel does (Task 4).
- [ ] Test: house + section → mesh count unchanged.

### Task 2b: Visible-element pass ✅
- [x] `Viewport::visibleElements(camera, box)`: render IDs from the drawing's camera offscreen (the D52 pass), return the GlobalIds seen; the bridge adds the elements the cut plane crosses and passes the union to `generate_drawing`.
- [x] GUI self-tests on the occlusion model (South sends 1 element, North 2); the synthetic grid model's South Elevation: 4.1 s in the app with 96 visible elements (52 s with all of them in S6).

### Task 3: App — Section and Elevation tools, template elevations ✅ (core)
- [x] Section tool (**V**): click, click for the line, then a third click on the side to look at. Infinite range by default.
- [x] Elevation tool (**Shift+V**): same three clicks.
- [x] New projects get **North, South, East and West elevations** (Archicad's template); their markers sit outside the building and follow the model's bounds when generated, until moved. Opening an IFC adds nothing; *View › Create elevations* adds the missing ones (one undo step).
- [x] Markers in plan view only (not in 3D, as in Archicad): sections as a line with end flags and arrows, elevations as a triangle with range ticks; selectable, movable, rotatable, deletable.
- [x] Tests in `test_main_window` (`sectionsAndElevations`, shortcuts) and Python tests updated deliberately (the template elevations are not plan annotations).
- [ ] Follow-up: rubber-band preview of the line and typed length; depth (Limited / Zero) and scale in a drawing settings dialog (the bridge has `set_drawing_depth`).

### Task 4: App — Drawings panel and 2D tab ✅
- [x] Drawings dock (next to Layers): list, double-click or *Open*, rename in place, delete.
- [x] The central area is tabbed: *Model* plus one tab per open drawing; `DrawingView` paints the SVG with `QSvgRenderer` (paper on a grey desk), wheel zoom at the cursor, drag to pan, fit on first show.
- [x] Generation on a worker thread; the old drawing stays until the new one arrives; an out-of-date bar with *Regenerate*; a stale drawing brought to the front regenerates; deleting a drawing closes its tab.
- [x] Self-test `--open-drawing NAME` (with `--create-drawings`, `--screenshot`) reports `drawing_shown`, `drawing_s`, `drawing_visible`, paper size.
- [ ] Follow-up: keep generated SVGs in `.kimcad/drawings/` for versioned projects, so reopening is instant.

### Task 5: Timing on Clinic in CI (informational)
- [x] Two non-blocking Linux CI steps: `pixi run drawing-bench` (S6, every element) and the app pipeline on Clinic (`--create-drawings --open-drawing "South Elevation"`, with the visible-element pass). **Clinic's South Elevation in the app: 5.1 s with 120 visible elements of 2,586** (22–34 s with every element in S6). Numbers in 11.

### Task 6: Docs and verification ✅
- [x] D60 (proposed), D61 (owner); doc 05 "As built"; doc 04 §8; doc 14 §11 and §13; roadmap M4; README.
- [x] EN/ES strings (`check-translations` OK); Python 151 passed; app 31/31 (20 non-GPU + 11 GUI self-tests under Xvfb) on Linux. Windows: CI.

## Owner decisions (2026-10-07): follow Archicad's conventions (D61)

1. **Look direction:** two clicks for the section line, a third click on the side to look at (Archicad's eye cursor).
2. **Depth:** horizontal range Infinite by default (Archicad's default); Limited and Zero depth are drawing settings.
3. **Shortcut:** Archicad has no default key for the Section tool. KIMCAD's single letters are all taken except **V** (`C` is the plan cut), so Section = **V**, Elevation = **Shift+V**.
4. **Elevations:** created automatically for every new project, like the four elevations in Archicad's default template.

The general rule for later slices: where the owner has not decided otherwise, a drawing or documentation behaviour copies Archicad's default.
