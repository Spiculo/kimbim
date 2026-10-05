# Slice 6 (M3, part 3) — Columns, beams, grids; move, rotate, stretch, height; edit doors/windows

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An architect can place columns and beams from profile types, draw grid axes, and edit what they drew:
- move and rotate the selection;
- stretch a wall's end;
- change wall heights;
- move a door or window along its wall, or resize it.

Every edit is one undo step with live 3D updates.

**Architecture:** Same split as Slices 4–5 (D51). The bridge (`authoring.py`) uses:
- **Columns and beams:** `geometry.add_profile_representation`; columns are anchored at the bottom centre, beams at the top centre so the top sits at the given height. Types carry an `IfcMaterialProfileSet`.
- **Grids:** `grid.create_grid_axis` / `create_axis_curve` on an `IfcGrid` per level.
- **Moves:** `geometry.edit_object_placement(..., should_transform_children=True)`, so openings and doors follow their wall (probe: openings are placed relative to the wall, doors relative to the opening). Joins to walls that don't move are disconnected (`disconnect_path`), then everything touched is regenerated.
- **Stretch:** rebuilds the wall's placement and axis; its doors keep their world position.

C++ gets three pure-logic tools fed with work-plane points:
- `TwoPointTool` (beams, grid axes, move);
- `RotateTool` (centre, reference, target; 15° snapping; typed angle);
- `GripTool` (wall-end grips of the selected walls).

**Tech Stack:** ifcopenshell 0.9 api, Qt 6, OCCT 8, Qt Test, pytest.

**Spec:** docs/04-app-features.md §5 P0 rows "Levels (storeys) and grids", "Columns and beams from profile types", "Edit geometry: move, rotate, stretch/extend wall, change height"; Slice 5 deferred minor "placed doors/windows can't be moved or resized". Probe (scratch `s6_probe.py`): 300×300 column, 200×400 beam, grid axis, wall move with/without children confirmed.

## Global Constraints

- IFC4, project units (mm for new projects), bridge APIs in metres/radians (D51); one action = one undo step + geometry delta (D49/D51); failed rollbacks reported (D53).
- Element identity is preserved by edits (GlobalIds never change on move/stretch/resize; versioning depends on it).
- EN/ES UI, SPDX, DCO; headless CI (logic unit-tested; rendering via GUI self-tests).

## Review Focus

1. Moving a wall moves its doors/windows with it; moving a door alone along its wall keeps it inside the wall.
2. Moving one wall of a joined room: the joins to walls that stay are removed and both regenerate cleanly (no stale notches); moving the whole room keeps its joins.
3. Rotating by 90° around a point keeps sizes (bbox swaps) and keeps GlobalIds.
4. Stretching a joined wall end: the other end's join is kept; the stretched end's old join is re-evaluated.
5. Resizing a door beyond its wall or above the wall height is refused; nothing changes.

---

### Task 1: Bridge — columns, beams, grids
- `column_types()` / `beam_types()`: defaults on first use ("Column 300x300" rectangle, "Column Ø300" circle, "Beam 200x400"), material profile sets; `{guid, name, width, depth}`.
- `create_column(storey, type, x, y, height, rotation)`; `create_beam(storey, type, x1, y1, x2, y2, top)` (top elevation absolute in m; default level + 3 m in the UI).
- `add_grid_axis(storey, x1, y1, x2, y2, tag)` (creates the level's `IfcGrid` on first use; axis tag auto "A, B, …" for axes closer to vertical, "1, 2, …" otherwise when tag is empty); `snap_data` adds `grid: [{guid, tag, x1, y1, x2, y2}]`.
- Tests: sizes/positions via mesh bbox; circle column area; beam top; grid tags auto-increment per direction; undo of each.

### Task 2: Bridge — move, rotate, stretch, height, opening edits
- `move_elements(guids, dx, dy, dz)`, `rotate_elements(guids, cx, cy, angle)`: rigid transform of the selection, plus hosted openings/fillings; joins between moved and unmoved walls are disconnected; delta = moved + regenerated neighbours.
- `set_wall_axis(wall, x1, y1, x2, y2)` (stretch; keeps GlobalId and the joins at ends that didn't move).
- `set_wall_height(guids, height)`; `edit_opening(guid, along, width, height, sill)` (move along the host wall / resize; refuses if it doesn't fit).
- Tests: Review Focus 1–5, undo of each, GlobalIds unchanged.

### Task 3: C++ — column, beam and grid tools; grid snapping
- Tools: Column **K** (click; Shift = rotate 90°), Beam **J** (two points, top = active level + wall height field), Grid **G** (two points per axis, auto tags); Model menu entries; `Snapper` snaps to grid-axis intersections and lines (new kinds `GridLine`, `GridCross`).
- Tests: `test_two_point_tool.cpp`, snapper grid kinds, `test_main_window` (column + beam + grid via the tools, undo).

### Task 4: C++ — move, rotate, stretch, height, opening edit
- Move **M** (base point, target point, snapped; typed distance), Rotate **R** (centre, reference, target; 15° snap; typed angle), Stretch: drag a grip at a selected wall's end (GripTool; also typed length), Model › "Wall height…" for selected walls, Model › "Door/window size…" for a selected door/window; moving a selected door/window with Move slides it along its wall.
- Tests: `test_rotate_tool.cpp`, `test_grip_tool.cpp`, `test_main_window` (move a wall with a door, rotate, stretch, height, undo). Self-test `--house` extended: move the house 1 m, rotate 90°, report ok.

### Task 5: Docs and verification
- README keys, doc 04 §5 status, roadmap, decisions D54 (move disconnects joins to unmoved walls; children follow hosts; stretch keeps doors in place).
- Full suites Windows + WSL; screenshots; self-review; finish the branch (owner decides merge).
