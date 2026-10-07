# Slice 14 (M4, part 1) — Sections and elevations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** draft for the owner's review. Task 0 (the risk check) is done; its results are below and in [11](../../11-spike-results.md#s6--drawings-svg-serializer-slice-14-risk-check). Tasks 1–6 wait for the scope questions at the end.

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
| Clinic_Architectural in CI: section 25.9 s, elevation 34.4 s with every element (geometry 11 s, HLR 13–21 s). Synthetic 2,880-product model: hidden-line removal dominates. plan 6.8 s (10.6 s with exact HLR); section 26 s; elevation 52 s, but 3.4 s when only the visible front row is given ([11](../../11-spike-results.md#s6--drawings-svg-serializer-slice-14-risk-check)) | Use `svg-poly`; pre-filter plans by level; a visible-element pass for sections and elevations; show the old drawing until the new one is ready |
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

### Task 1: Bridge — drawing definitions and generation
- [ ] `python -m kimcad.drawgen SNAPSHOT.ifc GUID [GUID...]` child process: generates and prints `{guid: svg}` JSON; `generate_drawing` snapshots the model and runs it (S6: the serializer holds the GIL).
- [ ] `kimcad/drawings.py`: `create_section(storey_guid, x1, y1, x2, y2, look_side, depth, height)`, `create_elevations()` (four, from the building box; idempotent: re-running updates them), `drawings()` → `[{guid, name, kind, scale, stale}]`, `rename_drawing`, `delete_drawing`, `edit_drawing` (scale, depth), `generate_drawing(guid)` → `{svg, seconds}` (cached).
- [ ] Tests `tests/python/test_drawings.py`: the house section has cut groups for walls and slabs (`class="cut"` paths with fill) and projection groups; elevations exist for N/S/E/W; edit a wall → stale → regenerated SVG differs; delete is undoable; a model with drawings validates; `annotations()` ignores drawings; golden hashes unchanged.

### Task 2: Keep drawings out of the 3D view
- [ ] `start_meshing` / `mesh_elements` skip `IfcAnnotation` with ObjectType DRAWING; the model tree lists drawings under a Drawings node instead of the level.
- [ ] Test: house + section → mesh count unchanged.

### Task 2b: Visible-element pass
- [ ] `Viewport::visibleElements(camera, box)`: render IDs from the drawing's camera offscreen (the D52 pass), return the GlobalIds seen; the bridge adds the elements the cut plane crosses and passes the union to `generate_drawing`.
- [ ] Test: the synthetic grid model's south elevation is generated from the front row only; timing written in 11.

### Task 3: App — Section tool and elevations
- [ ] Section tool (shortcut to agree): click, click, click for the look side; preview line with direction arrows; typed length like the wall tool. Section and elevation markers drawn in plan (overlay, like annotations).
- [ ] View › Create elevations.
- [ ] Tests in `test_main_window`: draw a section on the house → one drawing listed; create elevations → four listed.

### Task 4: App — Drawings panel and 2D tab
- [ ] Drawings dock: list (kind icon, name, scale), double-click opens; rename, delete.
- [ ] Drawing tab: `QSvgRenderer` in a `QGraphicsView`; wheel zoom at cursor, middle pan, fit; "out of date" bar with Regenerate (and automatic regenerate when the tab is visible, debounced).
- [ ] Generation on a worker thread with progress in the status bar; the old SVG stays visible until the new one is ready.
- [ ] Tests: open the house section tab → SVG item present; edit a wall → stale bar → regenerate → content changes.

### Task 5: Timing on Clinic in CI
- [ ] `tests/python/test_drawings.py::test_clinic_timing` (marked `slow` and `golden`, needs the corpus): plan, section and elevation of Clinic_Architectural; prints the timings, fails only above a generous ceiling. Record the numbers in 11 and in the slice notes.

### Task 6: Docs and verification
- [ ] D60 in decisions.md; doc 05 drawing flow updated (no `addDrawing`, `svg-poly`, the cache key); doc 04 §8 status; doc 14 §11 rows; roadmap M4 progress; README "try it".
- [ ] EN/ES strings (`pixi run check-translations`); full `pixi run test`, `golden`, `app-test` on Windows and Linux.

## Questions for the owner before Task 1

1. **Section look direction:** after the two clicks, a third click picks the side it looks at (Archicad), or the direction is always to the left of the line and a Flip button reverses it (Revit)?
2. **Section depth:** unlimited by default (everything behind the cut, as Revit's default far clip is "no clip" for sections), or a default depth such as 10 m?
3. **Shortcut** for the Section tool: Archicad has none by default; KIMCAD uses single letters. Is `C` (cut) acceptable, or something else?
4. **Automatic elevations:** create them once on demand (View › Create elevations), or create them automatically for every new project?
