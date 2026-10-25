<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Object Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An Object Editor dialog that makes and edits `.kimobj` library objects without code: parameters, materials, parts, a live preview, and saving to the project or to the office library (D99 part B).

**Architecture:** All editing logic lives in a new Python module `kimbim/objedit.py`. It takes a *draft* (the definition JSON being edited), checks it with field paths, builds the try-values form, previews it in the scratch model D100 already uses, and saves it. The C++ `ObjectEditorDialog` only edits the draft JSON and shows what Python returns. It reuses the Object settings dialog's preview `Viewport`, `PlanSymbolView` and `ParameterForm`. **Project objects** (`project:<id>`) are definitions that live only on the model's types. They are listed in the Library panel and placeable, and they never need a file.

**Tech Stack:** Python 3 / IfcOpenShell 0.9 (`python/kimbim`), C++20 / Qt 6 (`app/src`), pytest, Qt Test (ctest), pixi.

**Spec:** `docs/16-parametric-objects.md` §6 *Object Editor*, §9 *Testing* (app self-test), §10 part B. Context: D100 in `docs/decisions.md` and `docs/superpowers/specs/2026-10-24-object-settings-modal-design.md`.

## Global Constraints

- Objects are data, never code. Python `eval` is never used; formulas go through `kimbim.objexpr` (D99).
- The editor edits the JSON through `kimbim.objects` / `kimbim.objedit`. Nothing about drafts is C++-only, so the console and tests can do the same (doc 16 §6).
- Preview redraw happens 0.3 s after a change, from the current try values. A broken formula keeps the last good shape and marks its field red (doc 16 §6).
- Save is refused while any field has an error (doc 16 §6).
- Bundled objects open as a copy. Office and project objects open for editing (doc 16 §6).
- Projects stay self-contained. A project object builds only from what its types store (D99 §4/§5).
- UI strings are in English and Spanish (`app/translations/kimbim_es.ts`, `pixi run check-translations`). Every new file has an SPDX header (`pixi run check-spdx`).
- No backward compatibility shims. KimBim is unreleased.
- Bridge functions follow the app_bridge protocol: strings in, JSON out, never raise. Register them in `app_bridge._EXPORTS`.
- Run Python only through `pixi run`. The bare `.pixi` python.exe crashes in numpy.
- Golden hashes must not change (`pixi run golden`: 76 pass, same hashes).

## Rulings in this plan (my calls, record in D101)

1. **Customise a copy** is a button beside *Edit...* in the Properties *Parameters* summary, plus *Model › Customise a copy of the object...*. The viewport has no right-click menu outside drawing, and adding one is a wider change.
2. **Save to project** stores a project object on a saved version (D100) named after the object. That keeps the object in the project while nothing is placed. Saving a project object again regenerates every type of that ref from the new definition, keeping values whose key and kind still exist. All of this is one undo step.
3. **Placing by key falls back to the definition stored on a type** (`objversions._definition`). This makes project objects placeable, and also objects that are gone from the library. It reverses D100 ruling 8.
4. **Office versions are read only from `kimbim-versions.ifc`.** Other IFC files in the office folder still give fixed IFC types (D86), but never versions. This fixes the D100 shadowing follow-up.
5. The parts, components and symbol are edited in one generic JSON tree with three columns: key, value, error. A per-shape form would be more work for no gain, because every field takes a number or a formula anyway.
6. Choice options are typed in the parameter table as `id: Label, id2: Label 2`. Spanish option labels are not editable in the editor yet. They survive a round trip if the file has them.

## Review Focus

1. **Saving over an existing file or id.** Saving to the office when `<id>.kimobj` exists, or another office object has that id, must ask to replace and never overwrite silently. An id equal to a bundled id is refused. Tested in Task 4.
2. **Renaming a parameter key that formulas still use.** The formula's field turns red with the unknown-name message, and Save stays disabled. It must never save or crash. Tested in Task 3 (`check_draft`) and Task 6 (dialog).
3. **Undo after Save to project.** One undo removes the project object and its regenerated types, and the Library panel listing follows. Tested in Task 4 and Task 7.
4. **Cancel with unsaved edits.** Ask "Discard the changes to this object?". Cancel with no edits closes at once. Tested in Task 5.
5. **No office folder set.** *Save to office library* is disabled, and its tooltip points to Preferences › Office library. Tested in Task 5.

---

### Task 1: Office versions only from kimbim-versions.ifc

**Files:**
- Modify: `python/kimbim/library.py` (`_load_ifc_types`)
- Modify: `tests/python/test_objversions.py` (`test_an_office_copy_follows_its_office_version`: save the copying project outside the office folder)
- Test: `tests/python/test_objversions.py`

**Interfaces:**
- Produces: `_load_ifc_types(path, category)` registers `_office_versions` entries only when `os.path.basename(path).lower() == objversions.VERSIONS_FILE.lower()`. Typed products carrying a `VersionId` in any other file are skipped entirely: no version, and no fixed `ifc:` entry.

- [ ] **Step 1: Write the failing test** `test_versions_come_only_from_the_versions_file(project, tmp_path)`. Save a version "Café" and move it to the office (`tmp_path`). Then `call("save", str(tmp_path / "old.ifc"))` a project whose copy of "Café" has width 0.6, edited via `apply_object_settings`. Call `library.load_office(str(tmp_path))`. Assert the office version's `values["width"]` equals the moved value, not 0.6. Assert `len([e for e in library._office_versions.values() if e["name"] == "Café"]) == 1`.
- [ ] **Step 2:** Run `pixi run pytest tests/python/test_objversions.py -k versions_come_only -v`. Expected: FAIL. `old.ifc` sorts after `kimbim-versions.ifc` and overwrites the entry.
- [ ] **Step 3:** Implement the rule in `_load_ifc_types`. Update its docstring.
- [ ] **Step 4:** Make `test_an_office_copy_follows_its_office_version` save its projects into a sibling `tmp_path / "projects"` folder.
- [ ] **Step 5:** Run `pixi run pytest tests/python/test_objversions.py tests/python/test_library*.py -q`. Expected: all pass.
- [ ] **Step 6:** Commit `fix(library): office versions only from kimbim-versions.ifc (D100 follow-up)`.

### Task 2: Project objects: listed and placeable from their stored definition

**Files:**
- Modify: `python/kimbim/library.py` (`CATEGORIES`, `library_objects`, `place_object`, `_preview_definition`)
- Test: `tests/python/test_objedit.py` (create; same `call` / `project` fixture style as `test_objversions.py`)

**Interfaces:**
- Consumes: `objversions._definition(key)` (library, else the definition stored on a type of `key`, else an office version's).
- Produces:
  - `library.CATEGORIES` gains `("project", "Project")`, after `"office"`.
  - `library_objects()` lists every object ref found on the model's library types whose ref starts with `project:`, built from `objversions._definition(ref)`. Each is listed with `category: "project"` and `library: "project"`, once per ref, and never when the library has that ref.
  - `place_object(storey, key, params, ...)` with no `version`: `obj = get(key)`, else `objversions._definition(key)`. Fail only when both are None.
  - `_preview_definition` uses the same fallback.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_project_object_lists_and_places(project)`. Write a type for a `project:stool` definition by loading `objects.load(data, "project")` (data: the bundled table's JSON with `"id": "stool"`). Call `library._make_type(defn, defn.values())` inside `b._run`. Assert `library_objects` lists `"project:stool"` with category `"project"`. Assert `place_object(storey, "project:stool", '{"width": 0.7}', 0, 0)["ok"]`, and that the new type's Parameters width == 0.7.
  - `test_an_object_gone_from_the_library_still_places(project, tmp_path)`. Write an office `.kimobj`, place it, then `library.load_office()` with no folder. Assert placing `"office:<id>"` with new values still succeeds.
- [ ] **Step 2:** Run `pixi run pytest tests/python/test_objedit.py -v`. Expected: FAIL ("no library object project:stool").
- [ ] **Step 3:** Implement the interfaces above.
- [ ] **Step 4:** Run `pixi run pytest tests/python/test_objedit.py tests/python/test_objversions.py -q`. Expected: pass. The D100 test that expected "unsupported" for unsaved settings of a gone object (search `test_objversions.py` for it) now expects success. Update it, and say so in the commit message.
- [ ] **Step 5:** Commit `feat(library): project objects list and place from their stored definition (D101)`.

### Task 3: Drafts: open, check, form, symbol, preview

**Files:**
- Create: `python/kimbim/objedit.py`
- Modify: `python/kimbim/app_bridge.py` (`_EXPORTS["objedit"]`, import `objedit as _objedit`)
- Test: `tests/python/test_objedit.py`

**Interfaces:**
- Produces, all bridge-protocol functions:
  - `object_draft(source: str) -> str` returns `{"ok": true, "draft": {...}, "target": "project"|"office"|"", "copy": bool}`. `source` is one of the following:
    - `"new"`: a template. id `"new_object"`, name `{"en": "New object", "es": "Objeto nuevo"}`, category `"furniture"`, ifc `{"IFC4": ["IfcFurnitureType", "NOTDEFINED", null], "IFC2X3": ["IfcFurnitureType", null, null]}`, params width 0.6 / depth 0.6 / height 0.75 (lengths, EN/ES labels as the chair's), materials `{"body": {"label": {"en": "Material", "es": "Material"}, "default": "Timber - finish"}}`, and one part `{"id": "body", "material": "body", "box": {"x": 0, "y": 0, "z": 0, "dx": "width", "dy": "depth", "dz": "height"}}`.
    - A bundled id: a copy.
    - `"office:<id>"`: opens for editing, target office.
    - `"project:<id>"`: opens for editing, target project.
    - `"type:<GlobalId>"`: Customise a copy, from that type's stored definition, with each parameter's `default` set to the type's value.
    - A copy gets id `<id>_copy`, then `<id>_copy2` and so on, unique against bundled, office and project refs, and name `"<Name> (copy)"` / `"<Nombre> (copia)"`.
  - `check_draft(draft_json: str) -> str` returns `{"ok": bool, "errors": [{"path": str, "message": str}]}`.
    - It first compiles every formula string anywhere in the draft with `objexpr.compile_formula` and collects every syntax error, with paths written the way objects/objbuild write them: `params[3].max`, `parts.leg.cone.h`, `components.back_slats.parts.slat.box.dx`.
    - Then it loads the draft with `objects.load(data, "project", check=True)` and adds its `ObjectError`. That error's path is the text before the first `": "`, or `""` when there is none.
    - `ok` is true only when `errors` is empty.
  - `draft_form(draft_json: str, values_json: str) -> str`: the same JSON as `library.object_form`, for the draft. Fails with the check's first message when it does not load.
  - `draft_symbol(draft_json: str, values_json: str) -> str`: the same JSON as `library.object_symbol`.
  - `draft_preview(draft_json: str, values_json: str)`: meshes like `library.object_preview`, or None. Built via `library._preview_meshes(defn, values)` with the values cleaned by `library._edited_values`.
  - `draft_preview_error(draft_json: str, values_json: str) -> str`: like `library.object_preview_error`.
  - `object_part_template(shape: str) -> str` returns `{"ok": true, "part": {...}}`. The part has a fresh id `part`, and every required field of `objbuild._FIELDS[shape]` set to `0.1`, or to the shape's point list for `prism`, `revolve` and `sweep`. `shape` may also be `"use"` (`{"id": "part", "use": ""}`) or `"anchors"` (`{"id": "part", "anchors": {}}`). Anything else fails.
- A draft never touches `library.OBJECTS`, `_office` or the model.

- [ ] **Step 1: Write the failing tests:**
  - `test_new_draft_checks_and_previews`: `check_draft(new draft)["ok"]`, and `draft_preview(...)` is not None.
  - `test_a_bundled_object_opens_as_a_copy`: `object_draft("chair")`: `copy` is true, id `chair_copy`, name en `"Chair (copy)"`. Opening it a second time while an office `chair_copy` exists gives `chair_copy2`.
  - `test_customise_a_copy_takes_the_type_values`: place a chair with legs 3, then `object_draft("type:<its type guid>")`. The legs param default is 3.
  - `test_errors_name_their_fields`: rename the chair copy's `legs` key to `legz`. `check_draft` is not ok, and one error has `path == "parts.leg"` or starts with `"parts.leg"` with `"unknown name"` in its message. A draft with `"max": "seat_h -"` on param 3 has an error with path `params[3].max`, together with any other syntax error in the same draft (two broken formulas give two errors).
  - `test_try_values_form`: `draft_form(chair copy, '{"legs": 3}')["values"]["legs"] == 3`.
  - `test_part_templates_build`: for each of box, cylinder, cone, prism, revolve, sweep, put the template part into the new draft in place of `body`. `check_draft` is ok.
  - `test_a_hostile_draft_fails_fast`: a part with `"repeat": {"count": 100000, "step": [0.1, 0, 0]}`. `check_draft` is not ok within 5 s, and the message names the 5,000-solid limit.
- [ ] **Step 2:** Run `pixi run pytest tests/python/test_objedit.py -v`. Expected: FAIL (no module).
- [ ] **Step 3:** Implement `objedit.py`. The module docstring states the draft protocol.
- [ ] **Step 4:** Run `pixi run pytest tests/python/test_objedit.py -q`. Expected: pass.
- [ ] **Step 5:** Commit `feat(objedit): drafts: open, check with field paths, try values, preview (D101)`.

### Task 4: Saving a draft to the office library or the project

**Files:**
- Modify: `python/kimbim/objedit.py`, `python/kimbim/app_bridge.py`
- Test: `tests/python/test_objedit.py`

**Interfaces:**
- Produces: `save_draft(draft_json: str, target: str, replace: str = "") -> str`, where `target` is `"office"` or `"project"`.
  - Every target refuses with `{"ok": false, "error": "the object has errors", "errors": [...]}` when `check_draft` is not ok.
  - Every target refuses an id that is a bundled id: `"error": "chair is a bundled object: give the copy another id"`.
  - **office:**
    - Fails when no office folder is set: `"error": "no office library folder (Preferences › Office library)"`.
    - Writes `<folder>/<id>.kimobj` as indented JSON (2 spaces, UTF-8, keys in the draft's order).
    - If that file exists, or another loaded office object has the id, it returns `{"ok": false, "exists": "<id>"}` unless `replace == id`.
    - Then it reloads the office library (`library.load_office(folder, files)` with the current `_office_paths`).
    - Returns `{"ok": true, "ref": "office:<id>", "path": ..., "outdated": n}`, where `n` is `len(library._outdated(all placed objects of that ref))`, so the app can offer *Update from library*.
  - **project:** one undo step (`B._run`).
    - The ref is `project:<id>`.
    - If the model has no type of that ref, it makes a saved version named after the object (en name) at the draft's defaults, through `objversions`' writer (`_write_version` with a new uuid4 hex id).
    - If types of that ref exist, each is regenerated from the new definition with `library._regenerate_type(t, defn, library._kept_values(old_defn, values, defn))`. A type whose kept values do not build fails the whole save, with that type's name in the message, and nothing changes.
    - Returns `{"ok": true, "ref": "project:<id>", "types": n}`.
    - A `project:` id that clashes with a different object's ref is impossible by construction (same prefix, same id = the same object).

- [ ] **Step 1: Write the failing tests:**
  - `test_save_to_office_writes_and_lists`: save the chair copy with legs default 3 to `tmp_path`. The file exists, `library.get("office:chair_copy")` builds with 3 legs, and saving again returns `exists`. With `replace="chair_copy"` it is ok.
  - `test_saving_a_bundled_id_is_refused`.
  - `test_save_with_errors_is_refused`: nothing is written, nothing changes in the model (`len(b._model.by_type("IfcTypeProduct"))` is unchanged).
  - `test_save_to_project_keeps_the_object_and_undoes`: save the new draft to the project. `library_objects` lists `project:new_object`. `call("undo")` and it is gone. `call("redo")` and it is back.
  - `test_saving_a_project_object_regenerates_its_types`: place `project:new_object` twice with width 0.7, change the draft's box `dz` to `"height / 2"`, and save. Both placements share one type, its GlobalId is unchanged, its Parameters width is still 0.7, and its body height halves (compare `objbuild` shape bounding box z from `library.definition_of_type(t).shape(values)`).
  - `test_an_edited_office_file_offers_an_update`: place `office:chair_copy`, change the draft's seat height default, and save with replace. `outdated == 1`, and `call("library_updates", "")` counts it.
- [ ] **Step 2:** Run `pixi run pytest tests/python/test_objedit.py -k save -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `save_draft`.
- [ ] **Step 4:** Run `pixi run pytest tests/python/test_objedit.py tests/python/test_objversions.py -q`, then `pixi run golden`. Expected: pass, hashes unchanged.
- [ ] **Step 5:** Commit `feat(objedit): save a draft to the office library or the project (D101)`.

### Task 5: ObjectEditorDialog: object, parameters, materials, preview, save

**Files:**
- Create: `app/src/ObjectEditorDialog.h`, `app/src/ObjectEditorDialog.cpp`
- Modify: `app/src/MeshChunk.h/.cpp` (add `fetchDraftPreview`), `app/src/ObjectSettingsDialog.h/.cpp` (`ParameterForm::setDraft`), `app/CMakeLists.txt` (sources, `kimbim_test(test_object_editor)`)
- Test: `app/tests/test_object_editor.cpp` (create; copy the office-folder and engine setup helpers' style from `test_object_settings.cpp`)

**Interfaces:**
- Consumes: Task 3 and 4 bridge functions.
- Produces:
  - `bool fetchDraftPreview(PythonEngine&, const QJsonObject& draft, const QJsonObject& values, MeshChunk* out, QString* error)` calls `draft_preview` / `draft_preview_error`, like `fetchObjectPreview`.
  - `void ParameterForm::setDraft(const QJsonObject& draft, const QJsonObject& values = {})`: the form comes from `draft_form` instead of `object_form`. After it, `setValues` / `values()` work the same.
  - `class ObjectEditorDialog : public QDialog`, `objectName "objectEditorDialog"`:
    - `ObjectEditorDialog(MainWindow* window, const QString& source, QWidget* parent = nullptr)`, where `source` is as in `object_draft`.
    - `QJsonObject draft() const;` / `void setDraft(const QJsonObject&);`
    - `QStringList errorPaths() const;` (the last check's paths)
    - `bool saveTo(const QString& target, bool replace = false);` asks to replace on `exists` (a QMessageBox, unless `replace`). On success it accepts the dialog, and for the office it calls `MainWindow::offerLibraryUpdate(n)` when `outdated > 0` (see Task 7; until then a no-op hook).
    - `bool isDirty() const;`
  - Layout:
    - Left: a `QTabWidget` named `editorTabs` with three tabs:
      - **Object**: `editorId`, `editorName`, `editorNameEs`, `editorCategory` (furniture, sanitary, kitchen, site), `editorIfcClass` (editable combo: IfcFurnitureType, IfcSanitaryTerminalType, IfcElectricApplianceType, IfcBuildingElementProxyType, IfcGeographicElementType), `editorPredefined`.
      - **Parameters**: `editorParams`, a QTableWidget with columns Key, Label, Label (ES), Kind, Default, Min, Max, Group, Show when, Options; buttons `editorParamAdd`, `editorParamRemove`, `editorParamUp`, `editorParamDown`.
      - **Materials**: `editorMaterials`, columns Slot, Label, Default material, with add and remove.
    - The Parts tab comes in Task 6.
    - Middle: the preview `Viewport` and `PlanSymbolView` with a 3D / Plan toggle, as in `ObjectSettingsDialog`.
    - Right: a *Try values* `ParameterForm` (`editorTryValues`). It changes the preview, never the defaults.
    - Bottom: `editorError` (QLabel listing the errors, one per line, `path: message`), then *Cancel*, `editorSaveProject` ("Save to project"), `editorSaveOffice` ("Save to office library").
  - Behaviour:
    - Any edit restarts a 300 ms single-shot timer. On timeout the dialog rebuilds the draft from the widgets, calls `check_draft`, and marks the cells and fields whose path matches red with the message as tooltip (`params[k]...` → row k, Object-tab fields by their key). It then updates the preview and try-values form.
    - On errors the preview keeps the last good mesh, and both save buttons are disabled.
    - `editorSaveOffice` is disabled with the tooltip "Set an office library folder in Preferences › Office library" when none is set.
    - Cancel or Esc with `isDirty()` asks "Discard the changes to this object?".
    - Window title: "Object editor — <name>". A copy gets the suffix " (copy)" via the draft name.

- [ ] **Step 1: Write the failing tests** in `test_object_editor.cpp`:
  - `newObjectPreviews`: a "new" source. After the timer (`QTRY_VERIFY`) the preview has a mesh, `errorPaths()` is empty, and both save buttons are enabled when an office folder is set.
  - `renamedKeyMarksTheFormula`: open `"chair"`, set the `legs` key cell to `legz`. `QTRY_VERIFY` that some `errorPaths()` entry starts with `"parts.leg"`, `editorSaveProject` is disabled, and the preview still has its mesh.
  - `tryValuesDoNotChangeDefaults`: set legs 3 in `editorTryValues`. `draft()` params legs default is still 4.
  - `noOfficeFolderDisablesOfficeSave`.
  - `cancelAsksOnlyWhenDirty`: no edits → `reject()` closes. After an edit, the discard question appears (auto-answered via a `QTimer::singleShot` that finds the QMessageBox and clicks No → the dialog stays open).
  - `saveToOfficeWritesTheFile`: chair copy, legs default 3, `saveTo("office")` → the file exists and `py.callJson("library_objects")` lists `office:chair_copy`.
- [ ] **Step 2:** Run `pixi run app-build` then `ctest --test-dir build/app -R test_object_editor --output-on-failure` (with `KIMBIM_PYTHON_PATH` set as in the `app-test` task). Expected: FAIL (no target / tests fail).
- [ ] **Step 3:** Implement the interfaces above. Add the Spanish translations of every new string to `app/translations/kimbim_es.ts`.
- [ ] **Step 4:** Run the test again, then `pixi run check-translations` and `pixi run check-spdx`. Expected: pass.
- [ ] **Step 5:** Commit `feat(app): Object Editor dialog: object, parameters, materials, preview, save (D101)`.

### Task 6: Parts tree: parts, components, symbol with per-field errors

**Files:**
- Create: `app/src/JsonTreeEditor.h`, `app/src/JsonTreeEditor.cpp`
- Modify: `app/src/ObjectEditorDialog.h/.cpp` (a fourth tab *Parts*), `app/CMakeLists.txt`, `app/translations/kimbim_es.ts`
- Test: `app/tests/test_object_editor.cpp`

**Interfaces:**
- Produces: `class JsonTreeEditor : public QWidget` (`objectName "editorParts"`):
  - `void setRoots(const QJsonObject& roots)` with keys `parts` (array), `components` (object) and `symbol` (array or absent); `QJsonObject roots() const`.
  - `void markErrors(const QList<QPair<QString, QString>>& pathMessages)`.
  - `QString pathOf(QTreeWidgetItem*) const`. Array items that are parts or components are addressed by their `id` or name, as the error paths are (`parts.leg.cone.h`). Other array items use `[i]`.
  - `signals: void changed()`.
- Tree columns: Key, Value, Error. Value cells are editable for leaves. Typed text is parsed as JSON when it parses to a number, bool, null, array or object, else kept as a string (a formula).
- Buttons:
  - `partsAddPart`: a menu of Box, Cylinder, Cone, Prism, Revolve, Sweep, Anchors only, Use; each from `object_part_template`, with the id made unique (`part`, `part2`, …).
  - `partsAddComponent`: asks for a name, then adds `{params: [], parts: []}`.
  - `partsAddField`: asks for key and value on the selected object node.
  - `partsRemove`, `partsUp`, `partsDown`.
- An error whose path has no node of its own marks the nearest existing ancestor. The Error column shows the message, and the row is red.

- [ ] **Step 1: Write the failing tests:**
  - `jsonTreeRoundTrips`: `setRoots(chair parts, components, symbol)` then `roots()` gives the same JSON (`QCOMPARE` on the documents).
  - `editingAFieldUpdatesThePreview`: open `"chair"` and set `parts.seat.box.dz`'s value to `0.2`. `QTRY_VERIFY` that the draft holds `0.2` and the preview's bounding box z grew.
  - `badFormulaMarksItsRow`: set a cone `h` to `"seat_h -"`. That row's Error column is non-empty, and save is disabled.
  - `addPartFromTemplate`: Add part › Cylinder gives a node `part` with `cylinder.r`, `cylinder.h`, and the draft checks ok.
- [ ] **Step 2:** Run the test as in Task 5. Expected: FAIL.
- [ ] **Step 3:** Implement, and wire the tab into the dialog's draft and error marking.
- [ ] **Step 4:** Run the test, then `pixi run check-translations`. Expected: pass.
- [ ] **Step 5:** Commit `feat(app): Object Editor parts tree with per-field errors (D101)`.

### Task 7: Wiring, the §9 self-test, docs

**Files:**
- Modify: `app/src/LibraryPanel.h/.cpp`, `app/src/LibraryTools.cpp`, `app/src/MainWindow.h/.cpp`, `app/src/PropertiesPanel.h/.cpp`, `app/translations/kimbim_es.ts`
- Modify: `docs/16-parametric-objects.md` (status: part B built; §6 Object Editor reflects rulings 1–6), `docs/14-tool-inventory.md`, `docs/07-roadmap.md` (Object Editor done), `docs/decisions.md` (new row **D101 Object Editor** with rulings 1–6, link to doc 16 §6; D99 row: "part B built")
- Test: `app/tests/test_object_editor.cpp`, `app/tests/test_library.cpp`

**Interfaces:**
- Produces:
  - **LibraryPanel**:
    - A button `libraryNewObject` ("New object...").
    - The right-click on an object becomes a menu `libraryObjectMenu`: *Settings...* (D100 behaviour, `settingsRequested`), then *Edit object...* for office and project objects or *Customise a copy...* for bundled ones (`editorRequested(const QString& source)`), and none of these for office IFC types.
    - Signals: `void newObjectRequested();` and `void editorRequested(const QString& source);`.
    - Project objects show under the *Project* category.
  - **PropertiesPanel**: a button `objectCustomiseCopy` ("Customise a copy...") beside `objectSettingsEdit`, enabled under the same condition, emitting `customiseCopyRequested()`.
  - **MainWindow**:
    - `bool openObjectEditor(const QString& source)` opens `ObjectEditorDialog` modally. On accept it refreshes the library listing, the Object tool's cached form and thumbnails.
    - `void offerLibraryUpdate(int outdated)` asks "N placed objects use an older version of this object. Update them now?" and runs the existing `updateFromLibrary` on yes.
    - *Model › Customise a copy of the object...* uses the selection's type: `"type:<GlobalId>"` from `object_settings_of`.
    - The library listing is refreshed after undo and redo too, so project objects follow.

- [ ] **Step 1: Write the failing tests:**
  - In `test_library.cpp`: `rightClickOffersEditOrCopy`: the menu for `chair` holds *Customise a copy...*, the menu for an office object holds *Edit object...*, and the menu for an `ifc:` entry holds neither.
  - In `test_object_editor.cpp`: `threeLegChairEndToEnd`, the §9 self-test:
    1. Set the office folder to a temp dir and open a new project.
    2. `openObjectEditor("chair")` (driven with `QTimer::singleShot`): set the legs default to 3 in `editorParams` and `saveTo("office")`.
    3. Place `office:chair_copy` with the Object tool via `placeObjectAt`.
    4. Check the 3D dump (`py.callJson("mesh_elements", ...)` or the existing scene dump helper `test_library.cpp` uses) shows 3 leg solids, by counting `KIMBIM` part names or the chair's leg material's mesh parts. Check the plan symbol of the placed type (`object_symbol` with the type source) has 3 leg outlines past the seat when splayed (set splay 8° in the same step).
    5. Edit the `.kimobj` on disk (width default 0.5) and call `library_updates`. `updateFromLibrary` offers 1, and after it the type's width is 0.5.
  - `projectObjectUndo`: save the new draft to the project. The Library panel lists it under *Project*. `undo` and the panel no longer lists it.
- [ ] **Step 2:** Run `pixi run app-test`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement the wiring and translations. Update the docs.
- [ ] **Step 4:** Full verification:
  - `pixi run test-py`: all pass.
  - `pixi run app-test`: all pass.
  - `pixi run golden`: 76 pass, hashes unchanged.
  - `pixi run check-spdx` and `pixi run check-translations`: OK.
- [ ] **Step 5:** Commit `feat(app): Object Editor in the Library panel and Properties; docs (D101)`.
