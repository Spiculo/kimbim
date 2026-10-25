<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Object settings modal and saved versions — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Customise library objects in a modal with a live preview, keep the results as named saved versions (project types, shareable to the office library), and place them fast with a quick switcher.

**Architecture:** Saved versions are D99 library types with two more fields in `KIMBIM_LibraryObject` (`VersionId`, `VersionName`). The version logic lives in a new Python module, `python/kimbim/objversions.py`, which `library.py` defers to for lookup, cleanup, regeneration and updates. The app gets a new `ObjectSettingsDialog` (layout A), which uses its own `Viewport` and `Scene` for the 3D preview and a painter widget for the plan symbol. The Library panel loses its inline form, and the Properties *Parameters* group becomes a summary with *Edit…*.

**Tech Stack:** Python 3.12, IfcOpenShell 0.9 (`ifcopenshell.api`), pytest; C++20/Qt 6, OCCT viewer, QtTest; pixi tasks.

**Spec:** `docs/superpowers/specs/2026-10-24-object-settings-modal-design.md` (read it before your task).

## Global Constraints

- Always run Python through pixi (`pixi run pytest ...`), never the bare `.pixi/envs/default/python.exe`, which crashes in numpy here.
- Bridge functions take strings and return JSON. They never raise: they return `A._fail(msg)` on error, and `B._dump({...})` with `"ok": True` on success. Each edit runs as one undo step through `B._run(action)`.
- Every new bridge function is listed in `app_bridge._EXPORTS` under its module. For `objversions`, add an `"objversions"` entry and import it the way `library` is imported (`from . import objversions as _objversions`).
- Every UI string is in English and Spanish. Add the Spanish to `app/translations/kimbim_es.ts` through `tools/fill_translations_es.py`, matching existing practice. The translations check must pass.
- Every new file starts with `SPDX-License-Identifier: GPL-3.0-or-later`. `pixi run check-spdx` must pass.
- No backward-compatibility shims (the project is unreleased). Removed UI and preferences go outright.
- IFC4 and IFC2X3 both work. `ifcopenshell.validate` stays clean on the touched models.
- Projects open and edit without the office library: everything a version needs is stored on its project type.
- Names: a version's name is stripped, not empty, at most 255 characters, and unique per object (case-insensitive) within the project.
- The office versions file is `<office folder>/kimbim-versions.ifc`. Builder's call, as the spec allows.
- The last version used is stored in the project setting `object_last_used`: `{object_ref: {"version": id}}` or `{object_ref: {"values": {...}}}`.

## Review Focus

1. **Undo of version edits:** undoing Save as, Rename, Delete or Move into the project must restore the exact previous state, one step each. Test in Task 1.
2. **Save, close and reopen:** versions survive a disk round trip in IFC4 and IFC2X3, with name, id and values intact. Test in Task 1.
3. **Office folder missing, read-only or not set:** *Move to library* fails cleanly with a message, and the project is untouched. Test in Task 3.
4. **A version whose object is no longer in the library:** it's still listed, placeable and editable from its stored definition. Test in Task 1.
5. **A saved or typed value that doesn't build:** the dialog shows the error, keeps the last good preview, and disables Place/Apply. It never crashes or places. Tests in Task 5 (dialog) and Task 2 (bridge refuses).

---

### Task 1: Saved versions in the project (Python)

**Files:**
- Create: `python/kimbim/objversions.py`
- Modify: `python/kimbim/library.py`
  - `_find_type`, `_remove_type_if_unused` and `_regenerate_type` learn about saved types.
  - `place_object` gets a `version` argument.
  - `_write_pset` keeps the version fields.
- Modify: `python/kimbim/app_bridge.py` (exports)
- Test: `tests/python/test_objversions.py`

**Interfaces:**
- Produces, in `objversions`:
  - `VERSION_ID = "VersionId"` and `VERSION_NAME = "VersionName"` (pset field names).
  - `is_saved(t) -> bool`: the type has a `VersionId`.
  - `version_of(t) -> dict | None`: `{"id", "name", "object", "values", "type": GlobalId, "uses": int, "source": "project", "office_id": str|None}`.
  - `project_versions(ref: str) -> list[dict]`: the project's saved types for that object ref, sorted by name.
  - `find_version(version_id: str)`: the project type, or None.
  - Bridge:
    - `object_versions(key: str) -> str`: `{"ok", "default": values, "versions": [version dicts], "last": {"version": id}|{"values": {}}|{}}`. Task 3 adds office entries with `"source": "office"`.
    - `save_version(key: str, name: str, params_json: str, replace: str = "") -> str`: `{"ok", "id", "type"}`. With a name clash and no `replace`: `{"ok": False, "error": ..., "exists": id}`. With `replace="1"`, the existing version is regenerated with the new values (same id).
    - `rename_version(version_id: str, name: str) -> str`
    - `delete_version(version_id: str) -> str`: fails with `"used": n` if anything uses it.
    - `set_last_used(key: str, data_json: str) -> str`: stores `{"version": id}` or `{"values": {...}}` in project setting `object_last_used`. It's a settings change, not a model edit.
- Produces, in `library`:
  - `place_object(storey_guid, key, params_json, x, y, angle=0.0, gravity="", version="") -> str`. When `version` is given, the placement uses that saved type and `params_json` is ignored. The result carries `"type"`. Task 3 extends `version` to office ids.

- [ ] **Step 1: Write the failing tests** in `tests/python/test_objversions.py`. Reuse the `project` fixture and the `call` helper pattern from `tests/python/test_library.py`.

```python
def test_save_place_and_list_a_version(project):
    r = call("save_version", "chair", "Dining", json.dumps({"width": 0.5, "back": "slats"}))
    assert r["ok"], r
    vs = call("object_versions", "chair")["versions"]
    assert [v["name"] for v in vs] == ["Dining"] and vs[0]["values"]["width"] == 0.5 and vs[0]["uses"] == 0
    t = b._model.by_guid(r["type"])
    assert t.Name == "Dining"                         # schedules count by name
    p = call("place_object", project, "chair", "", 0, 0, 0, "", r["id"])
    assert p["type"] == r["type"]
    assert call("object_versions", "chair")["versions"][0]["uses"] == 1

def test_unsaved_values_never_join_a_named_version(project):
    v = call("save_version", "chair", "Dining", json.dumps({"width": 0.5}))
    p = call("place_object", project, "chair", json.dumps({"width": 0.5}), 0, 0, 0)
    assert p["type"] != v["type"]
    k = call("save_version", "chair", "Kitchen", json.dumps({"width": 0.5}))
    assert k["type"] not in (v["type"], p["type"])   # identical values, separate types

def test_an_unused_saved_version_stays(project):
    v = call("save_version", "chair", "Dining", "")
    p = call("place_object", project, "chair", "", 0, 0, 0, "", v["id"])
    assert call("delete_elements", json.dumps([p["guid"]]))["ok"]
    assert b._model.by_guid(v["type"])               # unnamed types go when unused; saved ones stay

def test_names_are_unique_per_object_and_validated(project):
    assert call("save_version", "chair", "Dining", "")["ok"]
    clash = call("save_version", "chair", " dining ", json.dumps({"width": 0.6}))
    assert clash["ok"] is False and clash["exists"]
    assert call("save_version", "chair", "Dining", json.dumps({"width": 0.6}), "1")["ok"]
    assert call("object_versions", "chair")["versions"][0]["values"]["width"] == 0.6
    assert call("save_version", "table", "Dining", "")["ok"]   # another object may reuse the name
    assert call("save_version", "chair", "   ", "")["ok"] is False

def test_rename_and_delete(project):
    v = call("save_version", "chair", "Dining", "")
    assert call("rename_version", v["id"], "Dinner")["ok"]
    assert b._model.by_guid(v["type"]).Name == "Dinner"
    p = call("place_object", project, "chair", "", 0, 0, 0, "", v["id"])
    used = call("delete_version", v["id"])
    assert used["ok"] is False and used["used"] == 1
    call("delete_elements", json.dumps([p["guid"]]))
    assert call("delete_version", v["id"])["ok"]
    assert call("object_versions", "chair")["versions"] == []

def test_each_version_edit_is_one_undo_step(project):            # Review Focus 1
    v = call("save_version", "chair", "Dining", "")
    assert call("undo")["ok"] and call("object_versions", "chair")["versions"] == []
    assert call("redo")["ok"]
    assert call("rename_version", v["id"], "Dinner")["ok"]
    assert call("undo")["ok"] and call("object_versions", "chair")["versions"][0]["name"] == "Dining"
    assert call("delete_version", v["id"])["ok"]
    assert call("undo")["ok"] and len(call("object_versions", "chair")["versions"]) == 1

@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_versions_survive_save_and_reopen(tmp_path, schema):    # Review Focus 2
    # make a project in `schema` (see test_library.test_ifc2x3_classes for how), save a version,
    # place it, save to tmp_path, reopen: same id, name, values; validate(b._model) == []

def test_a_version_of_an_object_gone_from_the_library_still_works(project, tmp_path):  # Review Focus 4
    # make an office .kimobj, load_office(folder), save a version of it and place it,
    # library.load_office() (gone); object_versions(ref) still lists it and placing it works
```

- [ ] **Step 2: Run them and confirm they fail.**
Run `pixi run pytest tests/python/test_objversions.py -q`. Expect failures (no `save_version`).

- [ ] **Step 3: Implement `objversions.py` and the `library.py` hooks.**
  - `VersionId` is `uuid.uuid4().hex`, written as IfcIdentifier. `VersionName` is IfcLabel.
  - A saved type's `Name` is the version name. `_regenerate_type` keeps it for saved types.
  - `_find_type` skips saved types, so unsaved values never resolve to one.
  - `_remove_type_if_unused` never removes a saved type.
  - `_write_pset` must not clear the version fields when it rewrites the pset.
  - `save_version` builds with `_make_type` and then adds the version fields, all in one `B._run`. Values are cleaned through `obj.values()` and must build (`obj.shape`), or it fails.
  - `object_versions` for an unknown key that still has project versions uses the stored definition (`definition_of_type`) to report `default`.
  - `set_last_used` goes through `settings` like other project settings. Add `object_last_used: {}` to `settings.DEFAULTS`, with a `_error` rule that requires a dict of dicts.

- [ ] **Step 4: Run the new tests plus `tests/python/test_library.py`.** Expect both to pass. If an existing test assumed every type is unnamed, fix the test only when the spec changed that behaviour.

- [ ] **Step 5: Commit.** Message: `feat(library): saved versions are named project types (D100)`.

### Task 2: Applying dialog edits to placed objects (Python)

**Files:**
- Modify: `python/kimbim/objversions.py`
- Modify: `python/kimbim/library.py` (`set_object_parameter`: a whole-type edit of a saved type regenerates in place and never merges; remove `object_parameter_usage`)
- Modify: `python/kimbim/configure.py` only if its use of `set_object_parameter` breaks
- Test: `tests/python/test_objversions.py`

**Interfaces:**
- Consumes: Task 1.
- Produces (bridge, in `objversions`):
  - `object_settings_of(guids_json: str) -> str`:
    - `{"ok", "key", "values", "version": id|None, "name": type name, "selected": n, "uses": n, "shared": bool}`
    - fails when the selection holds objects of more than one type, or no library object
    - `"key"` is the object ref; the definition used is the type's stored one
  - `apply_object_settings(guids_json: str, params_json: str, mode: str, name: str = "") -> str`, one undo step. Modes:
    - `"all"`: regenerate the selection's type in place with these values. Its GlobalId, name and VersionId are kept. It never merges into another type. For an **unnamed** type, if an unnamed type with these values already exists, move everyone there (today's rule).
    - `"new"`: make a saved version called `name`. Name clash fails with `"exists"`. Only the selected objects move to it.
    - `"auto"`: `"all"` when the type isn't shared beyond the selection, else fail with `"shared": true` so the app asks.
  - `assign_version(guids_json: str, version_id: str) -> str`: move the selection to that version's type. One undo step. An unnamed type left unused goes.

- [ ] **Step 1: Write the failing tests.**

```python
def test_modify_all_changes_every_placement_and_keeps_the_version(project):
    v = call("save_version", "chair", "Dining", "")
    a = call("place_object", project, "chair", "", 0, 0, 0, "", v["id"])["guid"]
    c = call("place_object", project, "chair", "", 1, 0, 0, "", v["id"])["guid"]
    s = call("object_settings_of", json.dumps([a]))
    assert s["version"] == v["id"] and s["uses"] == 2 and s["shared"]
    assert call("apply_object_settings", json.dumps([a]), json.dumps({"width": 0.55}), "auto")["shared"]
    assert call("apply_object_settings", json.dumps([a]), json.dumps({"width": 0.55}), "all")["ok"]
    for g in (a, c):
        t = ifcopenshell.util.element.get_type(b._model.by_guid(g))
        assert t.GlobalId == v["type"] and t.Name == "Dining"

def test_modify_all_never_merges_named_types(project):
    d = call("save_version", "chair", "Dining", json.dumps({"width": 0.5}))
    k = call("save_version", "chair", "Kitchen", json.dumps({"width": 0.6}))
    a = call("place_object", project, "chair", "", 0, 0, 0, "", k["id"])["guid"]
    assert call("apply_object_settings", json.dumps([a]), json.dumps({"width": 0.5}), "all")["ok"]
    assert ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId == k["type"]
    assert b._model.by_guid(d["type"])

def test_create_a_new_type_moves_only_the_selection(project):
    v = call("save_version", "chair", "Dining", "")
    a = call("place_object", project, "chair", "", 0, 0, 0, "", v["id"])["guid"]
    c = call("place_object", project, "chair", "", 1, 0, 0, "", v["id"])["guid"]
    r = call("apply_object_settings", json.dumps([a]), json.dumps({"arms": True}), "new", "Armchair")
    assert r["ok"]
    assert ifcopenshell.util.element.get_type(b._model.by_guid(a)).Name == "Armchair"
    assert ifcopenshell.util.element.get_type(b._model.by_guid(c)).Name == "Dining"
    assert call("undo")["ok"] and ifcopenshell.util.element.get_type(b._model.by_guid(a)).Name == "Dining"

def test_an_unshared_type_applies_directly_and_a_mixed_selection_fails(project):
    a = call("place_object", project, "chair", "", 0, 0, 0)["guid"]
    assert call("apply_object_settings", json.dumps([a]), json.dumps({"legs": 3, "layout": "circle"}), "auto")["ok"]
    t = call("place_object", project, "table", "", 2, 0, 0)["guid"]
    assert call("object_settings_of", json.dumps([a, t]))["ok"] is False

def test_assign_version(project):
    v = call("save_version", "chair", "Dining", "")
    a = call("place_object", project, "chair", "", 0, 0, 0)["guid"]
    old = ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId
    assert call("assign_version", json.dumps([a]), v["id"])["ok"]
    assert ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId == v["type"]
    with pytest.raises(RuntimeError):
        b._model.by_guid(old)                       # the unnamed type left unused is gone

def test_values_that_do_not_build_are_refused(project):        # Review Focus 5 (bridge)
    a = call("place_object", project, "chair", "", 0, 0, 0)["guid"]
    before = ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId
    r = call("apply_object_settings", json.dumps([a]), json.dumps({"width": -1}), "all")
    assert r["ok"] is False
    assert ifcopenshell.util.element.get_type(b._model.by_guid(a)).GlobalId == before
```

- [ ] **Step 2: Run and confirm they fail.** `pixi run pytest tests/python/test_objversions.py -q`
- [ ] **Step 3: Implement.** Share the value-cleaning in `set_object_parameter` (`obj.values` then `obj.shape`) through one helper rather than copying it. Remove `object_parameter_usage` and its export, and the test that covers it (`test_parameter_scope_can_change_every_placement_or_only_the_selection`). Replace that test with the `"auto"` test above.
- [ ] **Step 4: Run `tests/python/test_objversions.py` and `tests/python/test_library.py`.** Expect them to pass.
- [ ] **Step 5: Commit.** Message: `feat(library): apply settings to placed objects: modify all or a new type (D100)`.

### Task 3: Sharing versions through the office library (Python)

**Files:**
- Modify: `python/kimbim/objversions.py`
- Modify: `python/kimbim/library.py`:
  - `load_office` reads office versions from `.ifc` files: types carrying `VersionId` become office versions, not fixed `ifc:` types;
  - `place_object` accepts an office version id.
- Test: `tests/python/test_objversions.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `library._office_versions: dict[str, dict]`, keyed by version id: `{"id", "name", "object", "values", "hash", "path", "guid"}`.
  - `object_versions(key)` also lists office versions with `"source": "office"`. A version the project already has (a project type whose `VersionId` equals the office id) is listed once, as the project's, with `"office_id"` set.
  - Bridge: `move_version_to_library(version_id: str, replace: str = "") -> str`.
    - Writes or updates `<office folder>/kimbim-versions.ifc`, creating it in the project's schema if missing (my call: IFC4 when the project is IFC4, otherwise IFC2X3).
    - Fails cleanly when no office folder is set, the folder is missing, or the file can't be written.
    - If an office version with the same id or name exists and `replace` is empty, it fails with `"exists"`.
    - Reloads the office library afterwards. Not an undo step: it changes no project data.
  - Placing an office version id the project doesn't have copies it in, as part of the placement's undo step.
    - The copy is built from the office type's stored definition and its values, and keeps the office `VersionId`.
    - On a name clash with another project version, the copy is named `"<name> (office)"`.
    - Later placements reuse the copy.

- [ ] **Step 1: Write the failing tests.**

```python
def test_move_to_library_and_use_in_another_project(project, tmp_path):
    library.load_office(str(tmp_path))
    v = call("save_version", "chair", "Café", json.dumps({"seat_shape": "round"}))
    assert call("move_version_to_library", v["id"])["ok"]
    assert (tmp_path / "kimbim-versions.ifc").exists()
    mine = call("object_versions", "chair")["versions"]
    assert len(mine) == 1 and mine[0]["source"] == "project"      # listed once
    assert call("new_project", "Other")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    office = [x for x in call("object_versions", "chair")["versions"] if x["source"] == "office"]
    assert office and office[0]["id"] == v["id"]
    p = call("place_object", storey, "chair", "", 0, 0, 0, "", v["id"])
    t = b._model.by_guid(p["type"])
    assert t.Name == "Café"
    assert call("place_object", storey, "chair", "", 1, 0, 0, "", v["id"])["type"] == p["type"]
    library.load_office()
    assert call("place_object", storey, "chair", "", 2, 0, 0, "", v["id"])["type"] == p["type"]  # self-contained

def test_office_copy_renamed_on_clash(project, tmp_path):
    library.load_office(str(tmp_path))
    v = call("save_version", "chair", "Café", "")
    call("move_version_to_library", v["id"])
    assert call("new_project", "Other")["ok"]
    storey = call("storeys")["storeys"][0]["guid"]
    call("save_version", "chair", "Café", json.dumps({"width": 0.6}))
    p = call("place_object", storey, "chair", "", 0, 0, 0, "", v["id"])
    assert b._model.by_guid(p["type"]).Name == "Café (office)"

def test_replacing_an_office_version_asks(project, tmp_path):
    library.load_office(str(tmp_path))
    v = call("save_version", "chair", "Café", "")
    call("move_version_to_library", v["id"])
    assert call("move_version_to_library", v["id"])["exists"]
    assert call("move_version_to_library", v["id"], "1")["ok"]

def test_move_to_library_without_a_usable_folder_fails_cleanly(project, tmp_path):  # Review Focus 3
    v = call("save_version", "chair", "Café", "")
    library.load_office("")
    assert call("move_version_to_library", v["id"])["ok"] is False
    library.load_office(str(tmp_path / "missing"))
    assert call("move_version_to_library", v["id"])["ok"] is False
    assert call("object_versions", "chair")["versions"][0]["name"] == "Café"
```

- [ ] **Step 2: Run and confirm they fail.**
- [ ] **Step 3: Implement.** Copy the project type into the office file with `ifcopenshell.api.project.append_asset`, with the project as the library and the office file as the target. Then set or keep its pset and write the file. `load_office` must keep loading plain office IFC types as before.
- [ ] **Step 4: Run `tests/python/test_objversions.py` and `tests/python/test_library.py`.** Expect them to pass.
- [ ] **Step 5: Commit.** Message: `feat(library): share saved versions through the office library (D100)`.

### Task 4: Saved versions in Update from library (Python)

**Files:**
- Modify: `python/kimbim/library.py` (`_outdated`, `library_updates`, `update_from_library`)
- Modify: `python/kimbim/objversions.py` (the outdated check per type)
- Test: `tests/python/test_objversions.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `objversions.outdated_versions() -> list[tuple[type, obj, values, current_def, new_values]]`. A saved type is outdated when either:
    - the live definition for its ref (bundled or office `.kimobj`) has a different `_hash_of`; or
    - it carries an office id that's in `_office_versions` and the office version's values or hash differ from the copy's.
  - Unused saved types count too.
  - `library_updates("")` counts placed objects as today, plus outdated saved versions, under a new `"versions"` key.
  - `update_from_library("")` regenerates outdated saved versions **in place**: same GlobalId, name and VersionId, with values kept as today, or the office version's values for an office copy. Every placement follows. Unsaved placements behave as before, all in one undo step.
  - With a guid selection, only those elements' types are updated.

- [ ] **Step 1: Write the failing tests.**

```python
def test_an_outdated_saved_version_updates_in_place(project, tmp_path):
    # office chair_x.kimobj v1; save version "X1" (unused) and "X2" (placed); rewrite the file
    # (v2, e.g. a changed default material); load_office(folder)
    u = call("library_updates", "")
    assert u["ok"] and u["versions"] == 2
    assert call("update_from_library", "")["ok"]
    # both types keep GlobalId and Name; their DefinitionHash is the new one; the placement keeps its type
    assert call("library_updates", "")["versions"] == 0
    assert call("undo")["ok"]                      # one step

def test_an_office_copy_follows_its_office_version(project, tmp_path):
    # save "Café", move to library, new project, place it (copy); in a third step overwrite the office
    # version from a project whose "Café" (same id) has width 0.6 via move_version_to_library(..., "1");
    # back in the copying project: library_updates("")["versions"] == 1; after update the copy's width is 0.6
```

- [ ] **Step 2: Run and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all Python tests.** Run `pixi run pytest -q`. Expect them to pass, including golden (`pixi run golden`) with unchanged hashes.
- [ ] **Step 5: Commit.** Message: `feat(library): saved versions take part in Update from library (D100)`.

### Task 5: The Object settings dialog with a live preview (C++)

**Files:**
- Create: `app/src/ObjectSettingsDialog.h`, `app/src/ObjectSettingsDialog.cpp` (and add them to `app/CMakeLists.txt`)
- Modify: `python/kimbim/library.py`, adding `object_preview(key, params_json, version="")`; `app_bridge` exports
- Modify: `app/src/MeshChunk.h/.cpp`, adding `fetchObjectPreview`
- Modify: `app/src/LibraryPanel.cpp/.h`. Move the parameter-form building out of the panel into a reusable `ParameterForm` inside `ObjectSettingsDialog.cpp`, which the panel no longer uses after Task 6.
- Test: `app/tests/test_object_settings.cpp` (register with `kimbim_test(test_object_settings)`), plus a Python test for `object_preview` in `tests/python/test_objversions.py`

**Interfaces:**
- Consumes:
  - `object_form`, `object_symbol`, `object_versions`, `save_version`, `rename_version`, `delete_version`, `move_version_to_library` (Tasks 1–3);
  - `Viewport(QWidget*)`, which owns a new Scene;
  - `Viewport::replaceElements`, `Viewport::fitAll`, `Viewport::homeView`.
- Produces:
  - Python: `object_preview(key: str, params_json: str, version: str = "")` returns mesh parts in the `mesh_elements` format (meta, verts, tris, colors) for one placement at the origin, or None when the values don't build.
    - It's built in a scratch in-memory model. `B._model` must be untouched afterwards, including the undo history.
    - It uses the same `_representations`/style code as real types, so it matches the model.
    - `object_preview_error(key, params_json) -> str` returns `{"ok", "error"?}` with the reason a value set doesn't build.
  - C++: `bool fetchObjectPreview(PythonEngine& py, const QString& key, const QJsonObject& params, MeshChunk* out, QString* error);`
  - C++ `ObjectSettingsDialog : QDialog`:
    - `enum class Mode { Place, Edit };`
    - `ObjectSettingsDialog(MainWindow* window, const QString& key, Mode mode, QWidget* parent = nullptr);`
    - `void selectVersion(const QString& id);`. An empty id means Default.
    - `void setValues(const QJsonObject& values);`
    - `QJsonObject values() const;` and `QString versionId() const;`. The id is empty when the values are unsaved or edited since the version was picked.
    - `bool valid() const;`
    - Object names for tests: `objectSettingsVersions` (QListWidget), `objectSettingsPreview` (Viewport), `objectSettingsPlan` (plan widget), `objectSettingsToggle3D`, `objectSettingsTogglePlan`, `objectSettingsSaveAs`, `objectSettingsAccept` (Place or Apply), `objectSettingsError` (QLabel). Each control is named `param_<key>`.
    - Layout A from the spec. The versions list has Default, the project versions, an "Office" separator item (not selectable), then the office versions. A right-click on a project version offers Rename, Delete and Move to library; Move is disabled with a tooltip when no office folder is set.
    - Preview updates are debounced through a single-shot `QTimer` (150 ms). A failing value set keeps the last mesh, shows the error, and disables Accept.
    - Office IFC types (`ifc:` keys) show the preview only: no controls and no Save as.

- [ ] **Step 1: Write the failing tests.** Python: `object_preview("chair", "")` returns 4 parts with non-empty vertices; `object_preview("chair", '{"width": -1}')` returns None; `b._model` and its history length are unchanged. C++ `test_object_settings.cpp`:

```cpp
void opensWithVersionsPreviewAndControls();   // MainWindow w(nullptr, true); newProject();
    // save_version via bridge; ObjectSettingsDialog d(&w, "chair", Place); versions list has
    // "Default" + "Dining"; preview Viewport has >0 elements after the debounce (QTRY_VERIFY);
    // param_legs hidden until param_layout is set to "circle"
void selectingAVersionLoadsItsValues();       // selectVersion(id) -> values()["width"] == 0.5, versionId()==id;
    // changing param_width clears versionId()
void badValueKeepsPreviewAndDisablesAccept(); // Review Focus 5: set param_width to 0 -> accept disabled,
    // error label non-empty, preview element count unchanged
void saveAsMakesAVersion();                   // a new "Bar stool" appears in the list and in object_versions
void planToggleShowsTheSymbol();              // objectSettingsTogglePlan -> objectSettingsPlan visible
```

- [ ] **Step 2: Build and run, and confirm they fail.** Run `pixi run app-build`, then `pixi run app-test -R test_object_settings`.
- [ ] **Step 3: Implement.** Put the Spanish for the new strings in `kimbim_es.ts` through `tools/fill_translations_es.py`.
- [ ] **Step 4: Run all app and Python tests.** Run `pixi run app-test` and `pixi run pytest tests/python/test_objversions.py -q`. Expect them to pass.
- [ ] **Step 5: Commit.** Message: `feat(app): object settings dialog with saved versions and live preview (D100)`.

### Task 6: Placing: the Library panel, last used, and the quick switcher (C++)

**Files:**
- Modify: `app/src/LibraryPanel.h/.cpp`.
  - Remove the inline form, `setParam`, `currentParams`, the Place button and the `m_form*` members.
  - Add per-entry version labels.
  - A click emits `placeRequested`.
  - A right-click emits `settingsRequested(QString id)`.
- Modify: `app/src/LibraryTools.cpp` and `app/src/MainWindow.h/.cpp`.
  - The current version per object comes from `object_versions`' `last`.
  - `placeObjectAt` passes the version id, or the custom values.
  - `chooseObject(id, params)` keeps working for tests and scripts, as custom values.
- Modify: `app/src/Viewport.h/.cpp`.
  - Add `void setRightClickMenu(bool on);`, which is off by default.
  - Add the signal `void drawingContextRequested(const QPoint& globalPos);`.
  - With it on, a right-click while drawing emits this signal instead of `drawingEnded`.
  - Esc still ends.
- Modify: the MainWindow tool options bar, adding a `QComboBox` named `objectVersionCombo`, shown only for `Tool::Object`.
- Test: `app/tests/test_library.cpp`, updating the existing tests that used the panel form.

**Interfaces:**
- Consumes:
  - `object_versions`, `set_last_used`, and `place_object(..., version)` (Tasks 1, 3);
  - `ObjectSettingsDialog` (Task 5).
- Produces:
  - `LibraryPanel::setVersionLabel(const QString& id, const QString& label)`, which shows "Chair · Dining" or "Chair · Custom".
  - `MainWindow::currentObjectVersion() const -> QString`, the current version id, empty for Default or Custom.
  - `MainWindow::setObjectVersion(const QString& key, const QString& versionId, const QJsonObject& customValues = {})`, which updates the panel label, the combo, and `set_last_used`.
- Behaviour:
  - Place in the dialog → `setObjectVersion`, then `setTool(Tool::Object)`.
  - Each placement records the last version used through `set_last_used` (a version id, or `{"values": ...}` for Custom). Editing placed objects (Task 7) never changes it.
  - The quick switcher menu lists Default, the project versions, the office versions, and *Settings…*.
  - The combo has the same items, except *Settings…*.

- [ ] **Step 1: Write the failing tests** (in `test_library.cpp`):

```cpp
void clickPlacesTheLastVersionUsed();   // save "Dining"; setObjectVersion("chair", id); place via
    // placeObjectAt -> the new element's type name is "Dining"; panel label contains "Dining"
void customValuesAreRememberedAsCustom(); // chooseObject("chair", {width 0.6}); place; reopen the
    // listing -> label contains "Custom"; next placement has width 0.6
void comboSwitchesTheVersion();          // objectVersionCombo visible in Object tool; choose "Dining";
    // currentObjectVersion()==id
void rightClickWhilePlacingOpensTheSwitcherNotEnd(); // viewport setRightClickMenu(true) in Object tool;
    // simulate a right press -> drawingContextRequested emitted, tool still Object; Esc ends
```

  Update the existing `panelListsAndSearches` and `objectToolPlacesTurnsAndUndoes`, which no longer have `currentParams`, to check through `object_versions` or the placed type.
- [ ] **Step 2: Build, run, and confirm they fail.**
- [ ] **Step 3: Implement.** Add the Spanish strings.
- [ ] **Step 4: Run `pixi run app-test`.** Expect everything to pass.
- [ ] **Step 5: Commit.** Message: `feat(app): click places the last version, quick switcher by right click and tool bar (D100)`.

### Task 7: Editing placed objects: the Properties summary and Edit… (C++)

**Files:**
- Modify: `python/kimbim/app_bridge.py`. `properties_multi`'s Parameters group becomes read-only:
  - every row has `"editable": False`;
  - the group gets a `"Type"` row with the type name first;
  - at most 6 visible parameters (the first ones);
  - the payload gets `"object_settings": {"enabled": bool}`, enabled only for a single library type.
- Modify: `app/src/PropertiesPanel.h/.cpp`. Add an **Edit…** button (`objectSettingsEdit`) under the Parameters group that emits `objectSettingsRequested()`.
- Modify: `app/src/MainWindow.cpp`.
  - Edit opens `ObjectSettingsDialog(…, Mode::Edit)` with `object_settings_of` values and version.
  - Accept runs the flow below.
  - Remove the `Parameters` branch from `applyPropertyEdit` and the `object_parameter_usage` dialog.
- Modify: `app/src/Preferences.h/.cpp` and `app/src/PreferencesDialog.cpp`, removing `objectEditScope` and its UI.
- Test: `app/tests/test_properties_panel.cpp`, `app/tests/test_library.cpp`, `tests/python/test_library.py` (the Parameters group shape)

**Interfaces:**
- Consumes: `object_settings_of`, `apply_object_settings`, `assign_version` (Task 2); `ObjectSettingsDialog` (Task 5).
- Produces: `MainWindow::editObjectSettings()` (public, for tests), which opens the dialog on the selection.
- Accept flow in Edit mode:
  - if `versionId()` is set and differs from the selection's version, call `assign_version`;
  - otherwise call `apply_object_settings(..., "auto")`;
  - on `"shared"`, ask with a QMessageBox:
    - **"Modify all %n objects of this type"**: `"all"`;
    - **"Create a new type…"**: ask for a name with `QInputDialog`, then `"new"`, retrying the name on `"exists"`;
    - Cancel: nothing.
- For tests, `MainWindow` exposes `setEditChoiceForTests(const QString& mode, const QString& name = {})`, which skips the message box. Mirror the existing `m_quiet` test pattern.

- [ ] **Step 1: Write the failing tests.**

```cpp
// test_properties_panel.cpp
void parametersAreASummaryWithEdit(); // select a placed chair: Parameters rows read-only, "Type" row first,
    // objectSettingsEdit enabled; select chair + table: disabled
// test_library.cpp
void editModifyAllChangesEveryPlacement();  // two placements of "Dining"; select one; editObjectSettings();
    // set param_width 0.55; setEditChoiceForTests("all"); accept -> both types are "Dining" with width 0.55
void editCreateNewTypeMovesOnlySelection(); // setEditChoiceForTests("new", "Wide") -> selected type "Wide",
    // the other stays "Dining"; undo restores in one step
void editPickingAnotherVersionAssignsIt();
```

  Python: update `test_parameters_show_in_properties_and_regenerate` so the group is read-only, and keep the regeneration checks through `set_object_parameter`.
- [ ] **Step 2: Build, run, and confirm they fail.**
- [ ] **Step 3: Implement.** Add the Spanish strings.
- [ ] **Step 4: Run all suites.** Run `pixi run app-test`, `pixi run pytest -q` and `pixi run check-spdx`, plus the translations check. Expect them all to pass.
- [ ] **Step 5: Commit.** Message: `feat(app): Properties summary with Edit…: modify all or create a new type (D100)`.

### Task 8: Docs

**Files:**
- Modify: `docs/decisions.md` (add D100: the summary of the spec's decisions, status "Decided (owner, 2026-10-24); built")
- Modify: `docs/16-parametric-objects.md` (a section on the settings dialog and saved versions, or a pointer to D100 where the doc describes the panel form and the Properties Parameters group)
- Modify: `docs/14-tool-inventory.md` (the object rows: saved versions, settings dialog with preview)
- Modify: `docs/07-roadmap.md` (Next: mark this done)
- Modify: D86/D92 rows where their text describes the inline Parameters editing or the `objectEditScope` preference, with "superseded in part by D100" in the house style used by D86 for D99.

- [ ] **Step 1: Write the docs.**
- [ ] **Step 2: Run `pixi run check-spdx`.** Expect it to pass.
- [ ] **Step 3: Commit.** Message: `docs: object settings dialog and saved versions (D100)`.
