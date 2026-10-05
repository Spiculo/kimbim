# Slice 3: Navigation, Multi-Select and Object Data Editor (M2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fix the two quirks the owner reported in Slice 2, then deliver M2 on top:
- **Revit/ArchiCAD navigation:** middle-drag pans, Shift+middle-drag orbits around the point under the mouse, the wheel zooms toward the cursor.
- **Multi-select:** Ctrl+click adds, Shift+click toggles, left-drag box-selects.
- **M2:** edit properties and names of one or many elements (bulk edit), add and remove properties, undo/redo, Save / Save As IFC with an unsaved-changes guard.

**Architecture:**
- Navigation and selection are configured on OCCT's `AIS_ViewController` (gesture map, selection schemes, rotation mode). There is no custom mouse code.
- Edits run in Python (`kimcad.app_bridge`) through `ifcopenshell.api` inside ifcopenshell file transactions, which gives undo/redo for free. The C++ side sends JSON commands and refreshes the panels.
- M2 edits never change geometry, so the viewport isn't re-meshed. Geometry-changing edits arrive with M3.

**Tech Stack:** as Slice 2 (C++17, Qt 6, OCCT 8 `novtk`, embedded CPython, ifcopenshell 0.9), plus `ifcopenshell.api.pset` / `attribute` and ifcopenshell file transactions.

**Spec:** `docs/04-app-features.md` §2 (selection), §4 (object data: properties, psets, bulk edit), §1 (save, undo); roadmap M2; owner answers 2026-10-05: navigation preset "Revit / ArchiCAD", quirk "can't multi-select".

## Global Constraints

- Everything in Slice 2's constraints still applies: SPDX headers, English and Spanish via `tr()`, never one AIS object per element, the GUI thread never tessellates, pixi-only builds.
- Model data is never translated: IFC property names and values are shown and stored exactly.
- **No silent type changes:** an edited property keeps its IFC value type (`IfcLabel`, `IfcBoolean`, `IfcReal`, …). If the input can't be converted, show an error and change nothing.
- Every edit is one undoable step, even when it touches many elements (bulk edit = one step).
- Saving writes standard IFC in the file's own schema (D30).

## Review Focus

1. **Bulk edit across elements that lack the property set:** they gain it. Elements of a different IFC class still get a custom property set; one property set per element, never duplicates. Test: Task 3.
2. **Undo after save, and edits after undo:** redo history is dropped on a new edit; the "unsaved" marker follows the real state. Test: Task 3 and Task 4.
3. **Closing with unsaved changes:** a prompt appears; Cancel keeps the app open. In quiet/self-test mode there is never a modal dialog. Test: Task 4.
4. **Typed input errors:** text into a real-number property is refused with a message, and the model is untouched. Test: Task 3.
5. **Box selection over a hidden element:** it never selects the hidden element. Test: Task 2.

---

### Task 1: Revit/ArchiCAD navigation preset

**Files:** modify `app/src/Viewport.{h,cpp}`; create `app/tests/test_navigation.cpp`.

**Interfaces:**
- `void Viewport::applyNavigationPreset()` is called from the constructor.
  - Gestures: middle → `Pan`, Shift+middle → `RotateOrbit`, left → `SelectRectangle`. No left-drag orbit.
  - Rotation mode: `AIS_RotationMode_PickLast` (orbit around the picked point).
  - Zoom: zoom at the cursor, sticking to the ray.
- `AIS_MouseGesture Viewport::gestureFor(Aspect_VKeyMouse, Aspect_VKeyFlags) const`, for tests.

- [ ] Test: `test_navigation.cpp`
  - `gestureFor(Middle, None) == Pan`
  - `gestureFor(Middle, Shift) == RotateOrbit`
  - `gestureFor(Left, None) == SelectRectangle`
  - `gestureFor(Right, None) == NONE` (the right button is reserved for context menus)
  - the rotation mode is `PickLast`

  Run it, see it fail, implement, see it pass, commit `feat(app): Revit/ArchiCAD navigation preset`.

### Task 2: Multi-select (Ctrl/Shift-click, box select) and multi-element panels

**Files:** modify `Viewport`, `MainWindow` (selection → properties for many), `ModelTreePanel` (`selectGuids(QStringList)`, extended selection mode), `app/tests/test_visibility.cpp`; create `app/tests/test_selection.cpp`.

**Interfaces:**
- Selection schemes: plain click → `Replace`, Ctrl → `Add`, Shift → `XOR`; also for box selection.
- `int Viewport::selectInRectangle(int x0, int y0, int x1, int y1, AIS_SelectionScheme)` returns the selected count (used by the self-test and by the controller path).
- `ModelTreePanel::selectGuids(const QStringList&)`: programmatic multi-selection, no echo.
- `selectionChanged` from the viewport selects all those GUIDs in the tree. The properties panel shows the merged view (Task 3).

- [ ] Tests (`test_selection.cpp`, no window): the scheme map has Ctrl → Add and Shift → XOR; `selectGuids({a, b})` then `selectedGuids()` gives both; a hidden element in the guid list is revealed and selected; after `setHidden`, `selectedGuids()` excludes it.
- [ ] Self-test `--box-select`: after loading, select a rectangle covering the central 60% of the viewport and report `box_selected` (> 1 on the fixture and Duplex). Add a gui ctest.

  Commit `feat(app): multi-select with Ctrl/Shift-click and box selection`.

### Task 3: Bridge commands: merged properties, edit, add/remove, undo/redo, save

**Files:** modify `python/kimcad/app_bridge.py`, `tests/python/test_app_bridge.py`.

**Interfaces** (all return JSON and never raise):
- `properties_multi(guids_json) -> {"count", "types": [...], "name": {"value"|"varies"}, "psets": {pset: {prop: {"value": v, "varies": bool, "ifc_type": "IfcLabel"}}}}`
  A pset or property appears if any selected element has it; `varies` is true when values differ or some elements lack it.
- `set_property(guids_json, pset, prop, value_json) -> {"ok", "changed": n}`
  - One transaction.
  - Keeps the existing IFC value type, otherwise uses the pset template type, otherwise infers from JSON (str → IfcLabel, bool → IfcBoolean, int → IfcInteger, float → IfcReal).
  - Elements lacking the pset get it.
  - A value that can't be converted gives `{"ok": false, "error"}` and changes nothing.
- `remove_property(guids_json, pset, prop) -> {"ok", "changed"}`, one transaction.
- `set_name(guids_json, name) -> {"ok", "changed"}`, one transaction.
- `undo() / redo() -> {"ok", "can_undo", "can_redo"}`
- `state() -> {"dirty", "can_undo", "can_redo", "path"}`
- `save(path_or_empty) -> {"ok", "path"}`. Empty means the opened path. Clears `dirty`.
- `pset_templates(ifc_class) -> {"names": [...]}`: standard psets applicable to the class (for the "Add property set" menu).

- [ ] Tests (pytest, model with 3 walls and 1 slab):
  - merged view marks `varies`;
  - bulk-set FireRating on 2 walls → 1 undo step;
  - undo restores, redo reapplies;
  - a new edit after undo drops redo;
  - setting a real property to "abc" fails with nothing changed;
  - a slab without `Pset_WallCommon` gains a custom pset when edited together with walls;
  - save → reopen → value persisted, and the reopened file's records equal the edited model (fixed point);
  - `dirty` follows edits, undo-to-clean and save;
  - names edit;
  - `remove_property`.

  Commit `feat: property editing with undo/redo and save in the app bridge`.

### Task 4: Editable properties panel, Edit menu, Save, unsaved-changes guard

**Files:** modify `PropertiesPanel` (editable values, `(varies)`, bool checkboxes, add property / add property set / remove property context menu), `MainWindow` (Edit menu Undo Ctrl+Z / Redo Ctrl+Y and Ctrl+Shift+Z; File Save Ctrl+S, Save As Ctrl+Shift+S; window title `*` when dirty; close guard; tree label refresh on rename); create `app/tests/test_properties_panel.cpp`; extend `app/tests/test_main_window.cpp`.

**Interfaces:**
- `PropertiesPanel` signals: `propertyEdited(pset, prop, QJsonValue)`, `propertyRemoved(pset, prop)`, `nameEdited(QString)`, `addPropertyRequested(pset)`.
- `MainWindow::applyPropertyEdit(pset, prop, QJsonValue) -> bool` (also used by tests).
- `MainWindow::isDirty() const`

- [ ] Tests:
  - `test_properties_panel`: editing a value item emits `propertyEdited` with the right JSON type (number stays number, text stays text, toggling a bool emits a bool); an item shown as `(varies)` edits to a concrete value.
  - `test_main_window` (real engine with the fixture, via the loader and `QSignalSpy`):
    - select both walls, `applyPropertyEdit("Pset_WallCommon", "FireRating", "EI90")` → the bridge shows EI90 on both;
    - trigger `actionUndo` → EI30 is back;
    - trigger `actionRedo` → EI90;
    - `isDirty()` is true; Save As to a temp path → the file contains `EI90` and `isDirty()` is false;
    - in quiet mode, closing while dirty returns without a dialog.
- [ ] Translations (`fill_translations_es.py`).

  Commit `feat(app): edit properties and names, undo/redo, save`.

### Task 5: Docs, CI, verification

- `docs/07-roadmap.md`: M2 status (done: property and pset editing, bulk edit, undo/redo, save; not yet: materials, types, classifications, schedules, quantities).
- `docs/04-app-features.md`: navigation preset and selection modifiers.
- README key table.
- Decisions:
  - **D48:** navigation = Revit/ArchiCAD preset (middle pan, Shift+middle orbit around the picked point, zoom at cursor), click Replace / Ctrl Add / Shift XOR, left-drag box select.
  - **D49:** edits through `ifcopenshell.api` inside ifcopenshell file transactions; one transaction per user action; values keep their IFC type.
- Verification: full test suites on Windows, the Linux run in WSL, a clean-clone build.
