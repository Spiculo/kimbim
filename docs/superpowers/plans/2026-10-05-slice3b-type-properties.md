# Slice 3b — Type vs. element properties Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The properties panel shows where each value comes from (the element's type or the element itself), edits stay per element by default, and the user can deliberately change a value on the type (all elements of that type) or reset an override back to the type value.

**Architecture:** The bridge (`python/kimbim/app_bridge.py`) adds the source of each value to `properties_multi` and three functions: `type_usage`, `set_type_property`, `reset_to_type`. Each edit is one ifcopenshell transaction, so undo/redo and the dirty state work unchanged. The C++ `PropertiesPanel` draws inherited values in grey with a tooltip, and its context menu offers "Edit type value…" and "Reset to type value". `MainWindow` confirms type edits with the number of affected elements.

**Tech Stack:** Python + ifcopenshell.api (pset, util.element), Qt 6 Widgets, Qt Test, pytest.

**Spec:** Owner decision 2026-10-05 (Revit model: instance edits by default, type edits deliberate, show the source, reset to type) — recorded as D50. Builds on D49.

## Global Constraints

- Every user action = exactly one undoable step; invalid input changes nothing (D49).
- Type edits never happen implicitly; a type edit says how many elements it affects before applying (GUI).
- IFC names and values are not translated; all new UI strings in EN and ES (`check-translations` must pass).
- IFC4 and IFC2X3 files (type psets: `HasPropertySets` on the type object).

## Review Focus

1. Element with an override + type edit: the override wins, so the element does not change; the confirmation must count only elements that will actually change.
2. Selection mixing typed and untyped elements: type edit applies to the types present; untyped elements are reported, not edited.
3. A type with no pset of that name yet (prop only overridden on elements): "Edit type value" creates the pset on the type.
4. Reset to type on an element whose type doesn't define the property must not delete the property (that's "Remove property").
5. Undo of a type edit restores every element's displayed value in one step.

---

### Task 1: Bridge — value source, type usage, type edit, reset to type

**Files:**
- Modify: `python/kimbim/app_bridge.py` (`_element_values`, `properties_multi`, new `type_usage`, `set_type_property`, `reset_to_type`, `_write_test_model` gets a wall type)
- Test: `tests/python/test_app_bridge_types.py`

**Interfaces — Produces:**
- `properties_multi(guids_json)` per property adds `"source"`: `"type"` | `"element"` | `"override"` | `"mixed"`, and `"type_value"` (the type's value when all selected elements share it, else null).
- `type_usage(guids_json, pset, prop) -> {"types": [{"guid","name","count"}], "elements": int, "untyped": int}` — `elements` counts elements of those types that will show the new value (no override).
- `set_type_property(guids_json, pset, prop, value_json) -> {"ok", "types": int, "elements": int}`.
- `reset_to_type(guids_json, pset, prop) -> {"ok", "changed": int}`.
- `_write_test_model(path)`: both walls typed by `IfcWallType` "Basic Wall 200" with `Pset_WallCommon.ThermalTransmittance = 0.35` (IfcThermalTransmittanceMeasure).

- [ ] Step 1: write failing tests (source per property; type edit reaches unselected elements of the type; override elements not counted and not changed; untyped elements reported; new type pset created when missing; reset only where the type defines the property; each action is one undo step).
- [ ] Step 2: run `pixi run python -m pytest tests/python/test_app_bridge_types.py -q` — Expected: FAIL (functions missing).
- [ ] Step 3: implement.
- [ ] Step 4: run the file, then `pixi run test-py` — Expected: all pass.
- [ ] Step 5: commit.

### Task 2: Panel source display, context actions, MainWindow type edit + confirmation

**Files:**
- Modify: `app/src/PropertiesPanel.{h,cpp}`, `app/src/MainWindow.{h,cpp}`, translations
- Test: `app/tests/test_properties_panel.cpp`, `app/tests/test_main_window.cpp`

**Interfaces — Consumes:** Task 1 JSON. **Produces:**
- `PropertiesPanel` signals `typeEditRequested(pset, prop)`, `resetToTypeRequested(pset, prop)`; `QList<QAction*> actionsFor(QTreeWidgetItem*)` (the context-menu actions, testable).
- `MainWindow::applyTypeEdit(pset, prop, QJsonValue) -> bool` (no dialog), `MainWindow::resetToType(pset, prop) -> bool`.

- [ ] Step 1: failing tests — panel: type-sourced item grey + tooltip names the type value, override tooltip; `actionsFor` offers edit-type on type/override items and reset only on override/mixed. MainWindow (fixture): select wall 0, `applyTypeEdit("Pset_WallCommon","ThermalTransmittance",0.5)` changes wall 1 too; undo restores both; edit wall 0 then `resetToType` restores the type value.
- [ ] Step 2: build + `ctest` — Expected: FAIL (compile errors for missing API).
- [ ] Step 3: implement (confirmation `QMessageBox` lists element count and type names; skipped in quiet mode).
- [ ] Step 4: `pixi run app-test` 100%, `pixi run check-translations` OK.
- [ ] Step 5: commit.

### Task 3: Docs + verification

- Doc 04 (properties: source display, instance vs type edits), decisions D50, roadmap M2 bullet.
- Full suites on Windows, WSL Linux clean clone, self-review, then finish the branch.
