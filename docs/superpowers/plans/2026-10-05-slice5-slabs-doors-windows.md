# Slice 5 (M3, part 2) — Slabs, openings, doors and windows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An architect can draw floor slabs (by outline, or from a closed loop of selected walls) and place doors and windows in walls. Openings cut the wall, deleting a door or window closes the hole, and every action is one undo step with live 3D updates.

**Architecture:** Same split as Slice 4 (D51). The Python bridge (`authoring.py`) does the modeling with ifcopenshell.api:
- `geometry.add_slab_representation` for slabs;
- `geometry.add_door_representation` / `add_window_representation` for parametric doors and windows (what Bonsai uses);
- `feature.add_feature` / `add_filling` for opening + filling.

Each command reports its geometry delta (the wall changes when an opening is added or removed). C++ adds two pure-logic tools fed with work-plane points:
- `PolygonTool` (closed outlines, reusing `Snapper`);
- `HostTool` (finds the wall under the cursor and the opening's position along it, kept inside the wall).

Previews reuse the unselectable preview batch.

**Tech Stack:** ifcopenshell 0.9 api, Qt 6, OCCT 8, Qt Test, pytest.

**Spec:** docs/04-app-features.md §5 P0 rows "Slabs / floors from outline or from walls" and "Openings + doors + windows hosted in walls (parametric types)"; roadmap M3; owner order (M3 then in-app versioning). Probe (scratch `door_probe.py`): opening of 0.9×2.1 m in a 0.3 m wall removes exactly 0.567 m³; door/window/slab representations build; door insert ≈100 ms.

## Global Constraints

- IFC4, project units (new projects mm); bridge APIs in metres (D51). One action = one undo step with a geometry delta (D49/D51).
- Standard IFC relations: `IfcRelVoidsElement` (wall → opening), `IfcRelFillsElement` (opening → door/window), `IfcRelDefinesByType`; slabs `IfcSlab` + layered `IfcSlabType` (`IfcMaterialLayerSet`, layer usage on the slab); doors/windows `IfcDoor`/`IfcWindow` + `IfcDoorType`/`IfcWindowType`.
- Opening sizes live on the occurrence (`OverallWidth`/`OverallHeight`, standard attributes); the type carries KIMCAD defaults in a custom pset `KIMCAD_OpeningDefaults` (Width, Height, SillHeight), since IFC types have no size attributes.
- EN/ES UI, SPDX, DCO; headless CI (pure logic unit-tested; rendering via GUI self-tests).

## Review Focus

1. Deleting a wall that hosts doors/windows must remove its openings and fillings too (no orphan doors floating in space); deleting a door must remove its opening and restore the wall volume.
2. Undo/redo of a door insert must re-mesh the wall (the hole appears/disappears) and add/remove the door.
3. Doors near a wall end are kept inside the wall; a door wider than the wall is refused (nothing changes).
4. Slab from walls on a level above 0: slab top at that level's elevation; outline at the walls' outer faces for a closed loop; open chains or non-loops are refused with a clear message.
5. Concave outlines (L-shaped slabs) must triangulate and display correctly; self-intersecting outlines are refused.

---

### Task 1: Bridge — slabs, doors, windows, openings, cascade delete
**Files:** `python/kimcad/authoring.py`, `app_bridge.py` (re-exports), tests `tests/python/test_authoring_openings.py`.
**Produces (JSON, metres):**
- `slab_types()`: library defaults on first use: "Floor 200" (concrete 200), "Floor 300" (screed 50 / insulation 50 / concrete 200).
- `create_slab(storey, type, points_json, offset)`: polygon in plan (≥3 points, not self-intersecting); top of slab at storey elevation + offset (default 0); returns `{ok, guid, geometry}`.
- `slab_outline_from_walls(walls_json)`: `{ok, points}` — ordered closed loop of wall axes offset outward by half thickness (outer faces); error if the walls don't form one closed loop.
- `opening_types(kind)`: kind "door"|"window"; defaults on first use: "Door 900×2100", "Door 800×2100", "Window 1200×1200 (sill 900)", "Window 600×600 (sill 1500)"; each `{guid, name, width, height, sill}`.
- `insert_opening(kind, wall, type, along, width, height, sill)`: `along` = distance in m from the wall's axis start to the opening's centre; creates opening (through the wall thickness + 20 mm), door/window (parametric representation, OverallWidth/Height), voids/fills relations, same container as the wall; refused if it doesn't fit inside the wall; delta `[wall, filling]`.
- `delete_elements` cascade: a wall takes its openings and their fillings; a door/window takes its opening (delta: wall changed).
- `snap_data` adds `openings: [{guid, wall, along, width}]` (for the host tool to avoid overlaps later).

### Task 2: C++ tools — PolygonTool, HostTool, previews, UI
**Files:** new `app/src/PolygonTool.{h,cpp}`, `app/src/HostTool.{h,cpp}`; `Viewport` (polygon preview prism with ear-clipping triangulation, opening preview box), `MainWindow` (Slab tool **S**, Door tool **D**, Window tool **N**, "Slab from selected walls", type combos per tool); tests `test_polygon_tool.cpp`, `test_host_tool.cpp`, `test_main_window.cpp`.
- `PolygonTool`: click points (snapped), closing by clicking the first point (within tolerance) or Enter/double-click (≥3 points); Esc cancels; emits `polygonFinished(QVector<QPointF>)`; refuses self-intersection (status message).
- `HostTool::locate(QPointF p, double width, double tolerance) -> optional<Host{wallGuid, along, centre, angle}>`: the wall whose axis is within (thickness/2 + tolerance) of p; `along` = projection clamped to [width/2, length − width/2]; nullopt if the wall is shorter than the width.
- `triangulate(QVector<QPointF>) -> std::vector<uint32_t>` (ear clipping, either winding) for the slab preview; tests on square (2 triangles) and L-shape (4).
- Self-test `--house`: new project → walls loop 8×6 → slab from walls → a door on the south wall and a window on the north wall → report `{walls 4, slabs 1, doors 1, windows 1, openings 2, ok}`; screenshot.

### Task 3: Docs and verification
- README keys (S, D, N, slab from walls), doc 04 §5 status, roadmap M3 progress, decisions D53 (opening sizes on occurrences + KIMCAD_OpeningDefaults pset on types; slab top at level; outline at outer faces).
- Full suites Windows + WSL; screenshots; self-review; finish the branch (owner decides merge).
