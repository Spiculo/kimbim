# Slice 4 (M3, part 1) — New project, levels, walls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An architect can start a new project, add levels, and draw layered walls in a plan view: click-click polylines with snapping, typed lengths, and corner/T joins. Edits update the 3D view live, and undo/redo and Delete work.

**Architecture:** Authoring stays in the Python bridge on top of ifcopenshell.api. Wall creation and joins reuse `geometry.create_2pt_wall`, `connect_wall` and `regenerate_wall_representation`, which are Bonsai's wall logic, now in ifcopenshell 0.9. Every action stays one transaction (D49) and also records which elements' geometry changed. Undo and redo report the same, so C++ re-meshes only those elements (`mesh_elements`). The viewport gets live-update support: replaced or removed elements are retired from their original batch, and new meshes go into small overlay batches. Drawing is pure C++ logic (`WallTool` state machine + `Snapper`) driven by points on the active level's work plane, so it is testable without a GPU. The viewport only feeds it mouse/plane points and draws the preview.

**Tech Stack:** ifcopenshell 0.9 api/geom, Qt 6 Widgets, OCCT 8 (AIS preview, view projection), Qt Test, pytest.

**Spec:** docs/04-app-features.md §5 Modeling (P0 rows: levels, walls layered by type/draw by axis/join corners+T, snapping endpoint/midpoint/perpendicular/grid/axis, precise input) and docs/07-roadmap.md M3. Owner order: M3, then in-app versioning.

M3 slices: **4 (this): new project, levels, walls** → 5: slabs, openings, doors/windows → 6: columns/beams, grids, move/rotate/stretch → 7: the M3 exit test (2-storey house, IFC opens in Bonsai + one more viewer).

## Global Constraints

- New projects are IFC4, millimetre length unit (architect norm; 0.01 mm resolution, D-model). The UI and bridge APIs take **metres** (SI) and convert with the unit scale; files from others keep their units.
- Every user action = one undoable step; invalid input changes nothing (D49). Undo/redo must update the 3D view.
- Walls are `IfcWall` + `IfcWallType` with `IfcMaterialLayerSet` (axis on the layer-set reference line); joins via `IfcRelConnectsPathElements` (standard IFC; other tools understand them).
- EN/ES UI strings (`check-translations`), SPDX headers, DCO sign-off.
- No GPU in CI: logic must be testable headlessly (Viewport functions degrade without a window, as in Slice 3).

## Review Focus

1. Undo/redo of a wall creation and of a join must re-mesh **both** walls (the neighbour's geometry changed too) and remove the undone wall from the view and tree.
2. Drawing on Level 2 (elevation 3 m) puts walls at that elevation and in that storey, not at 0.
3. Snapping to an existing wall's end makes an L join; snapping onto the middle of a wall makes a T join; zero-length segments (double click on the same point) create nothing.
4. Files with metre units (not mm) still get walls of the right size (unit scale applied).
5. Deleting a joined wall regenerates the neighbour (no leftover notch).

---

### Task 1: Bridge authoring core

**Files:** Create `python/kimbim/authoring.py` (modeling functions, kept out of `app_bridge.py`, which re-exports them); modify `app_bridge.py` (`_run` change tracking, undo/redo report geometry, `mesh_elements`); test `tests/python/test_authoring.py`.

**Produces (all return JSON strings; lengths in metres):**
- `new_project(name) -> {ok}`: in-memory IFC4 file: project, mm units, Model/Body + Plan/Annotation contexts, site, building, "Level 1" at 0. Resets history; `path` empty (Save asks).
- `storeys() -> {"storeys": [{"guid","name","elevation"}]}` sorted by elevation.
- `add_storey(name, elevation) -> {ok, guid}`.
- `wall_types() -> {"types": [{"guid","name","thickness"}]}`; the first call on a model with no wall types creates the defaults "Generic 200" (one layer, 200 mm) and "Exterior 300" (brick 100 / insulation 80 / block 120).
- `create_wall(storey_guid, type_guid, x1, y1, x2, y2, height, join_start_guid, join_end_guid) -> {ok, guid}`: wall from the type's layer set, in the storey at its elevation. Join guids (may be "") are walls to connect at that end: if the point is that wall's end → L (`connect_wall`), otherwise → T (`is_atpath=True`). Regenerates every wall involved. Zero length → `{ok: false}`, no transaction.
- `delete_elements(guids_json) -> {ok, removed}`: removes products; walls connected to removed walls are regenerated.
- `snap_data(storey_guid) -> {"walls": [{"guid","x1","y1","x2","y2","thickness"}]}`: wall axes on that storey (for the C++ snapper).
- Change tracking: `_run(action)` accepts an action returning `(count, changed_guids, removed_guids)`; each transaction stores its geometry delta. Every edit, `undo` and `redo` result carries `"geometry": {"changed": [...], "removed": [...]}` (undo of a creation reports the wall as removed; redo reports it changed). Property edits report empty lists.
- `mesh_elements(guids_json) -> (meta_json, verts, tris)` in the same format as `next_mesh_chunk` (world coords, same kernel), or None if nothing to mesh.

- [ ] Step 1: failing tests: new project units/structure; add storey; default wall types once; create wall size via mesh bbox (5 m × 0.3 m × 3 m) in mm and in a metre-unit file; L join volume (7.83 m³ for the 5+4 m L with 300 mm walls) and T join; Level 2 elevation; zero length; geometry delta for create/undo/redo/delete (neighbour included); delete regenerates neighbour volume back; `mesh_elements` returns parts for the guids.
- [ ] Step 2: run `pixi run python -m pytest tests/python/test_authoring.py -q` → FAIL (module missing).
- [ ] Step 3: implement.
- [ ] Step 4: file passes; `pixi run test-py` all pass.
- [ ] Step 5: commit.

### Task 2: Live geometry in the viewport, tree refresh, Delete

**Files:** `app/src/ElementBatch.{h,cpp}` (retire), `Viewport.{h,cpp}`, `MainWindow.{h,cpp}`, `ModelTreePanel` (rebuild keeping expansion/selection); tests `test_visibility.cpp` (or new `test_live_update.cpp`), `test_main_window.cpp`.

**Produces:**
- `ElementBatch::retire(int i)` / `isRetired(i)`: a retired element is hidden for good: not pickable, ignored by `showAll`/`isolate`/counts/bounds.
- `Viewport::replaceElements(const MeshChunk&)`: retires the old instances of those guids and adds the new ones as an overlay batch (re-pointing `m_locate`). `Viewport::removeElements(QStringList)` retires them.
- `MainWindow::applyGeometry(QJsonObject geometry)`: removes the removed ones, fetches `mesh_elements` for the changed ones, replaces them, refreshes the tree (new/removed elements), and keeps the selection minus the removed ones. Called after every edit, undo and redo.
- Edit › Delete (Del key, `actionDelete`) → `delete_elements(selection)`.

- [ ] Step 1: failing tests: viewport: replace keeps `elementCount`, a retired guid stays hidden after `showAll`, `guids()` contains the new one once; remove → count drops. MainWindow (fixture, quiet): select a wall, `actionDelete` → viewport count 1, tree without it; undo → 2 again.
- [ ] Step 2: build/ctest → FAIL.  - [ ] Step 3: implement.  - [ ] Step 4: `pixi run app-test` 100%.  - [ ] Step 5: commit.

### Task 3: New project, levels toolbar, plan view, work plane

**Files:** `MainWindow`, `Viewport` (`pointOnPlane`, `setPlanView`), new `LevelsBar.{h,cpp}` (combo of storeys + "Add level…"), translations; tests `test_main_window.cpp`, `test_levels_bar.cpp`.

**Produces:**
- File › New project (Ctrl+N, unsaved guard) → `new_project`, empty viewport, tree with Level 1.
- `LevelsBar`: `setStoreys(json)`, `activeStorey()`, signal `activeStoreyChanged(guid, elevation)`, `addLevelRequested()`; MainWindow dialog asks name + elevation (default: highest + 3 m).
- `Viewport::setPlanView(double elevation)`: top orthographic camera; MainWindow applies the plan cut at elevation + plan-cut height. View › Plan view (`actionPlanView`, key `P`) toggles it; `3` returns to 3D.
- `Viewport::pointOnPlane(int x, int y, double z, gp_Pnt* out) -> bool`: screen point → intersection with the horizontal plane z (false without a window or a parallel ray).

- [ ] Step 1: failing tests (LevelsBar sorting/active/signals; New project → 1 storey, not dirty, title "Untitled"; add level → 2 storeys, active is the new one; pointOnPlane false without a window).
- [ ] Step 2–5: as above; commit.

### Task 4: Wall tool (snapping, typed length, joins)

**Files:** new `app/src/Snapper.{h,cpp}`, `app/src/WallTool.{h,cpp}` (pure logic, no OCCT view); `Viewport` (tool hook: forwards plane points/clicks/keys while a tool is active, draws the rubber-band preview as an `AIS_Shape` box of the wall's thickness); `MainWindow` (Wall tool action `W`, wall-type combo in a Modeling toolbar, typed-length field); `main.cpp` + `SelfTest` (`--draw-walls "x,y;x,y;..."` drives `WallTool` with plane points, no mouse); tests `test_snapper.cpp`, `test_wall_tool.cpp`, gui self-test `draw_walls`.

**Produces:**
- `Snapper::snap(QPointF p, double tolerance, const QPointF* from, bool ortho) -> Snap{QPointF point; Kind kind (None, Endpoint, Midpoint, OnWall, Perpendicular, Grid, Angle); QString wallGuid}`, priority Endpoint > Midpoint > Perpendicular (from `from` to a wall) > OnWall > angle (15° steps; 90° with `ortho`) > grid (10 mm).
- `WallTool`: `setWalls(snap_data)`, `move(QPointF)`, `click(QPointF)`, `typeLength(double metres)`, `finish()`, `cancel()`; emits `wallRequested(WallSegment{p1, p2, joinStartGuid, joinEndGuid})`; consecutive segments join to the previous wall (the previous segment's guid is fed back with `setLastWall(guid)`); `preview() -> optional<pair<QPointF,QPointF>>`.
- Behaviour: click sets the start, each next click creates a segment and continues from its end; typing a number + Enter creates a segment of that length along the current direction; Esc/right-click/double-click ends; zero-length clicks are ignored.

- [ ] Step 1: failing tests: Snapper priorities and tolerance, ortho/angle; WallTool click sequence emits segments with joins (start snapped to an existing end → joinStart = that wall; continuing chain → joinStart = last wall), typed length, cancel, zero length ignored. Self-test `--draw-walls "0,0;5,0;5,4;0,4;0,0"` on a new project → 4 walls, closed loop joined (all 4 walls have 2 connections), JSON report.
- [ ] Step 2–4: implement, `pixi run app-test` 100%, screenshot check of the plan view and the 3D result.
- [ ] Step 5: commit.

### Task 5: Docs and verification

- README (new project, levels, wall tool keys), doc 04 §5 status, roadmap M3 progress, decisions D51 (new projects in mm, APIs in metres; walls by layered types with standard path connections; live update by retiring + overlay batches).
- Full suites on Windows, WSL Linux clean clone; self-review against the Review Focus; finish the branch (ask the owner).
