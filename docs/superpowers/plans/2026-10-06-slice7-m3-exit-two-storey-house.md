# Slice 7 (M3 exit) — Two-storey house: copy to level, stairs, slab openings, export checks

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Meet the M3 exit criterion: "an architect can model a small 2-storey house from scratch and export valid IFC that opens in at least two other tools".
- **Fill the gaps a two-storey house exposes:** copying the ground floor to the upper level, a stair between levels, and the stair's hole in the upper floor.
- **Prove it automatically:** a self-test models the house through the app's tools and saves it. The file then passes the IFC4 schema and the EXPRESS rules (ifcopenshell.validate). It is also opened, and every element meshed, by **web-ifc**, an independent IFC engine (That Open / IFC.js viewers), in CI on Windows and Linux.
- **Manual check by the owner:** a short checklist for Bonsai (Blender) and one commercial viewer.

**Architecture:**
- **Bridge (`authoring.py`), copy to level:** `copy_to_storey` uses `root.copy_class` + `geometry.copy_representation`, then rebuilds what copy_class leaves out: fillings in the duplicated openings, and path joins between copied walls.
- **Bridge, stairs:** a straight-flight stair is generated as a saw-tooth profile extruded across the stair width (ifcopenshell has no stair generator; Bonsai's lives in the Blender add-on). Riser count comes from the floor-to-floor height (≤ 175 mm risers, 280 mm goings).
- **Bridge, slab openings:** `IfcOpeningElement` voiding the slab.
- **C++ tools:** Stair (two clicks: start and direction), Slab opening (polygon on the selected slab), Model › Copy to level….
- **Interop check:** `tools/check_interop.py` runs ifcopenshell.validate with EXPRESS rules and `tools/webifc_check.mjs` (Node + `web-ifc` from npm, in a pixi feature `interop`).

**Tech Stack:** ifcopenshell 0.9 api, Qt 6, OCCT 8, Node.js (conda-forge) + web-ifc (npm), pytest, Qt Test.

**Spec:** docs/07-roadmap.md M3 exit; docs/04-app-features.md §5 (stairs are P1 there, but a two-storey house needs one).

## Global Constraints

- IFC4; one action = one undo step + geometry delta; GlobalIds of originals untouched; copies get new GlobalIds.
- No network at app runtime; npm install happens only in the interop check environment.
- EN/ES UI, SPDX, DCO; headless CI.

## Review Focus

1. Copying walls with doors/windows to the upper level: each copied door sits in a copied opening of the copied wall (no door shared between floors) and the copied walls are joined like the originals.
2. Copies go to the target level's elevation (not stacked at the source height) and are contained in the target level.
3. A stair's top step meets the upper level exactly (risers × count = floor-to-floor height).
4. A slab opening cuts exactly its outline (volume check) and undo restores the slab.
5. The exported house passes EXPRESS rules (not just the schema) and web-ifc meshes every product with geometry.

---

### Task 1: Bridge — copy to level, stairs, slab openings
- `copy_to_storey(guids, storey)`: copies walls (+ openings + fillings + joins among copies), slabs, columns, beams, doors/windows (with their wall), keeping relative positions, shifted by the elevation difference, contained in the target; returns `{ok, guids: [copies], geometry}`.
- `create_stair(storey, x, y, angle, width, height)`: straight flight up from the level, `height` = floor-to-floor (m); `IfcStair` (STRAIGHT_RUN_STAIR) with `Pset_StairCommon` NumberOfRiser/RiserHeight/TreadLength; refuses height ≤ 0 or width ≤ 0.
- `add_slab_opening(slab, points)`: polygon (metres, plan) through the slab; delta `[slab]`.
- Tests: Review Focus 1–4, undo of each.

### Task 2: C++ — Stair tool, Slab opening tool, Copy to level
- Stair **T** (two clicks: start point, direction; height = next level's elevation − active level's, else the height field), Slab opening **O** (PolygonTool on the one selected slab), Model › "Copy to level…" (choose a level).
- Tests: `test_main_window` (copy walls with a door up a level, stair to the next level, hole in a slab, undo).

### Task 3: Exit test and interop checks
- Self-test `--two-storey PATH`: through the tools: Level 1 walls (loop) + door + windows + floor slab; Level 2 at 3 m; copy walls with openings to Level 2; floor slab on Level 2 with a stair hole; stair from Level 1 to Level 2; roof slab on a Level "Roof" at 6 m; save to PATH; report counts.
- `tools/check_interop.py FILE`: schema + EXPRESS validation (0 errors), then `node tools/webifc_check.mjs FILE` (all products with representations mesh; counts per class); exit code. Pixi feature `interop` (nodejs) + task `interop`; CI job step on both OSes.
- Screenshot of the house (3D + lines-only plan of Level 2).

### Task 4: Docs and owner checklist
- `docs/12-m3-exit.md`: what was checked automatically, the manual checklist for Bonsai and a commercial viewer (open, element count, storeys, door/window in walls, properties), where the sample file is produced (`pixi run house`).
- README, doc 04 (stairs, copy to level, slab openings), roadmap (M3 ✅ pending the owner's manual check), decisions D55.
- Full suites Windows + WSL; self-review; finish the branch (owner decides merge).
