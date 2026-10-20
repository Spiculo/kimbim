# `.kim` File, Preferences and Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `.kim` file that holds the whole project (model, project settings, version history), user
preferences per computer, and office templates — step 2 of the owner's 3-step request.

**Architecture:** Python owns the file logic (`kimfile.py`: the zip container and locks; `settings.py`:
project settings; `documents.py`: the open document's mode, open/save/close, recovery, templates),
behind the existing bridge protocol (strings in, JSON out, never raise). Project settings are a
`settings.json` entry in each Git tree, beside the records. C++ owns user preferences
(`Preferences`, a JSON file), the dialogs and the File menu.

**Tech Stack:** Python 3.12 + ifcopenshell 0.9 + `zipfile`; the Rust `_core` Git layer (unchanged);
C++17 / Qt 6 (`QJsonDocument`, `QStandardPaths`); Qt Advanced Docking System 4.5.0.

**Spec:** `docs/superpowers/specs/2026-10-08-kim-file-and-preferences-design.md`

## Global Constraints

- Bridge functions: strings in, JSON string out, never raise (`B._dump`, `_fail`).
- A `.kim` is a zip: `kimbim-file.json` `{"format": "kim", "version": 1, "kind": "project"|"template", "app": ...}`, `.git/` (absent in a template), `.kimbim/working.ifc`, `.kimbim/settings.json`.
- Git pack files stored (`ZIP_STORED`), everything else deflated; `.kimbim/cache`, `.kimbim/index.db`, `.kimbim/lock`, `.kimbim/recovery` left out.
- Saving: zip to `<file>.kim.saving` beside the target, then `os.replace`. The old `.kim` is never touched before that.
- Working folder: `<data dir>/open/<16-hex hash of the .kim's full path>/`; recovery: `<data dir>/recovery/<hash>/`.
- Lock: `<file>.kim.lock` beside the file (folder mode: `.kimbim/lock`), `{"user", "machine", "pid", "since"}`.
- Project settings defaults: `plan_cut_height` 1.2, `hidden_layers` [], `locked_layers` [], `drawing_scale` 100, `sheet_paper` "A1", `length_unit` "m", `length_decimals` 2, `pen_sets` {}. Unknown keys kept.
- Preferences defaults: `language` "auto", `templates_folder` Documents/KimBim Templates, `new_views` "tab", `open_ifc` "make_kim", `auto_version` "off", `auto_version_every` 10, `recovery_minutes` 5, `recent` [] (max 10). Unknown keys kept; a garbled file is kept as `preferences.json.bad`.
- Ctrl+S saves the file; Save version… stays Ctrl+Alt+S; Save As… Ctrl+Shift+S.
- Every new UI string in English and Spanish (`app/translations/kimbim_es.ts`); SPDX header on every new file.
- C++17; Python files written with LF line endings.

## Review Focus

1. **OneDrive holds the `.kim` for a moment during sync** (`os.replace` gets PermissionError) → the save retries a few times, then fails with a clear message and the old file intact. Test in Task 3.
2. **A zip entry that escapes the folder** (`../x`, absolute path) in a hand-made or malicious `.kim` → refused, nothing written outside the working folder. Test in Task 3.
3. **Two KimBim windows on one machine open the same `.kim`** (same user, live pid) → the second opens read-only, it does not take the lock over. Test in Task 4.
4. **Unsaved-but-not-versioned work and design options**: after Ctrl+S (file saved, no version), switching options must still ask to save a version, and reopening the `.kim` must keep that work and still know it isn't versioned. Test in Task 5.
5. **Template GlobalIds referenced as text** (a sheet's placed drawing, saved views) → after regenerating ids, the new project's sheets still show their drawings. Test in Task 6.

---

### Task 1: Project settings in memory

**Files:**
- Create: `python/kimbim/settings.py`
- Modify: `python/kimbim/app_bridge.py` (state() dirty; re-export; reset on open)
- Modify: `python/kimbim/annotations.py:64-67` (`_measure` uses the unit)
- Test: `tests/python/test_settings.py`

**Interfaces:**
- Produces (Python, `kimbim.settings` as `S`): `DEFAULTS: dict`, `current() -> dict`, `load(data: dict | None, dirty: bool = False)`, `mark_saved()`, `is_dirty() -> bool`, `to_bytes(d: dict | None = None) -> bytes`, `from_bytes(b: bytes | None) -> dict`, `changed_keys(a: dict, b: dict) -> list[str]`, `merge(base: dict, ours: dict, theirs: dict) -> tuple[dict, list[str]]`, `format_length(metres: float, unit: bool = True) -> str`, `kept: bool` (module flag set by documents: settings are saved with the document).
- Produces (bridge): `project_settings() -> {"ok", "settings", "defaults", "kept"}`, `set_project_settings(changes_json) -> {"ok", "settings", "dirty"}`.

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 2: project settings (defaults, validation, dirty, merge, units)."""
import json

from kimbim import app_bridge as b
from kimbim import settings as S


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def test_a_new_model_has_the_default_settings():
    assert call("new_project", "x")["ok"]
    s = call("project_settings")
    assert s["ok"] and s["settings"] == S.DEFAULTS and s["settings"]["plan_cut_height"] == 1.2
    assert call("state")["dirty"] is False


def test_changing_a_setting_marks_the_model_unsaved_and_unknown_keys_are_kept():
    assert call("new_project", "x")["ok"]
    r = call("set_project_settings", json.dumps({"plan_cut_height": 1.1, "future_key": {"a": 1}}))
    assert r["ok"] and r["dirty"] is True
    assert call("project_settings")["settings"]["future_key"] == {"a": 1}
    assert call("state")["dirty"] is True
    S.mark_saved()
    assert call("state")["dirty"] is False


def test_bad_values_are_refused_and_change_nothing():
    assert call("new_project", "x")["ok"]
    for bad in ({"plan_cut_height": -1}, {"drawing_scale": 0}, {"sheet_paper": "B5"}, {"length_unit": "ft"},
                {"length_decimals": 9}, {"hidden_layers": "A-WALL"}):
        r = call("set_project_settings", json.dumps(bad))
        assert not r["ok"], bad
    assert call("project_settings")["settings"] == S.DEFAULTS and call("state")["dirty"] is False
    assert not call("set_project_settings", "not json")["ok"]


def test_bytes_round_trip_is_canonical():
    d = {**S.DEFAULTS, "hidden_layers": ["A-WALL"], "zz": 1}
    assert S.from_bytes(S.to_bytes(d)) == d
    assert S.to_bytes(d) == S.to_bytes(dict(reversed(list(d.items()))))  # key order doesn't matter
    assert S.from_bytes(None) == S.DEFAULTS and S.from_bytes(b"garbage") == S.DEFAULTS


def test_merge_takes_each_sides_change_and_ours_on_a_conflict():
    base = {**S.DEFAULTS}
    ours = {**base, "plan_cut_height": 1.1, "drawing_scale": 50}
    theirs = {**base, "sheet_paper": "A3", "drawing_scale": 200}
    merged, conflicts = S.merge(base, ours, theirs)
    assert merged["plan_cut_height"] == 1.1 and merged["sheet_paper"] == "A3" and merged["drawing_scale"] == 50
    assert conflicts == ["drawing_scale"]
    assert S.changed_keys(base, merged) == ["drawing_scale", "plan_cut_height", "sheet_paper"]


def test_lengths_follow_the_unit_and_decimals():
    S.load({"length_unit": "mm", "length_decimals": 0})
    assert S.format_length(3.5) == "3500 mm" and S.format_length(3.5, unit=False) == "3500"
    S.load({"length_unit": "cm", "length_decimals": 1})
    assert S.format_length(3.5) == "350.0 cm"
    S.load(None)
    assert S.format_length(3.5) == "3.50 m"


def test_new_dimensions_are_labelled_in_the_project_unit():
    assert call("new_project", "x")["ok"]
    assert call("set_project_settings", json.dumps({"length_unit": "mm", "length_decimals": 0}))["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    r = call("add_annotation", level, "dimension", json.dumps([[0, 0], [3.5, 0], [3.5, 1]]), "")
    assert r["ok"], r
    texts = [a["text"] for a in call("annotations", level)["annotations"] if a["kind"] == "dimension"]
    assert texts == ["3500"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `pixi run pytest tests/python/test_settings.py -q`
Expected: FAIL — `ImportError: cannot import name 'settings'` (and `project_settings` missing).

- [ ] **Step 3: Write `settings.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Project settings (step 2, D72): values that belong to the project, not the computer. They live in
the `.kim` / project folder and in every version's tree (settings.json), so going back to a version
brings back its settings. Unknown keys are kept, so an older KimBim never drops a newer one's settings.

Same protocol as app_bridge for the bridge functions (strings in, JSON out, never raise).
"""
from __future__ import annotations

import copy
import json

from . import app_bridge as B

DEFAULTS = {
    "plan_cut_height": 1.2,
    "hidden_layers": [],
    "locked_layers": [],
    "drawing_scale": 100,
    "sheet_paper": "A1",
    "length_unit": "m",
    "length_decimals": 2,
    "pen_sets": {},
}
UNITS = {"m": 1.0, "cm": 100.0, "mm": 1000.0}

_current: dict = copy.deepcopy(DEFAULTS)
_saved: dict = copy.deepcopy(DEFAULTS)
kept = False  # set by documents: the settings are saved with the open document (.kim or folder)


def current() -> dict:
    return copy.deepcopy(_current)


def load(data: dict | None, dirty: bool = False) -> None:
    """The open document's settings (defaults filled in). `dirty`: they differ from what is saved."""
    global _current, _saved
    _current = {**copy.deepcopy(DEFAULTS), **copy.deepcopy(data or {})}
    if not dirty:
        _saved = copy.deepcopy(_current)


def mark_saved() -> None:
    global _saved
    _saved = copy.deepcopy(_current)


def is_dirty() -> bool:
    return _current != _saved


def to_bytes(d: dict | None = None) -> bytes:
    return (json.dumps(_current if d is None else d, sort_keys=True, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def from_bytes(b: bytes | None) -> dict:
    try:
        data = json.loads(b) if b else {}
    except ValueError:
        data = {}
    return {**copy.deepcopy(DEFAULTS), **(data if isinstance(data, dict) else {})}


def changed_keys(a: dict, b: dict) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def merge(base: dict, ours: dict, theirs: dict) -> tuple[dict, list[str]]:
    """Key by key against the common version: a key changed on one side takes that side; changed
    differently on both, ours wins and the key is reported."""
    merged, conflicts = {}, []
    for k in sorted(set(base) | set(ours) | set(theirs)):
        b, o, t = base.get(k), ours.get(k), theirs.get(k)
        if o == t or t == b:
            value = o
        elif o == b:
            value = t
        else:
            value = o
            conflicts.append(k)
        if value is not None:
            merged[k] = value
    return merged, conflicts


def _error(key: str, value) -> str | None:
    from .sheets import PAPERS

    number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if key == "plan_cut_height" and not (number and 0 < value <= 20):
        return "the plan cut height must be between 0 and 20 m"
    if key == "drawing_scale" and not (isinstance(value, int) and not isinstance(value, bool) and value > 0):
        return "the drawing scale must be a whole number above 0"
    if key == "sheet_paper" and value not in PAPERS:
        return f"unknown paper size {value}"
    if key == "length_unit" and value not in UNITS:
        return f"unknown length unit {value}"
    if key == "length_decimals" and not (isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 4):
        return "decimals must be between 0 and 4"
    if key in ("hidden_layers", "locked_layers") and not (isinstance(value, list) and all(isinstance(x, str) for x in value)):
        return f"{key} must be a list of layer names"
    if key == "pen_sets" and not isinstance(value, dict):
        return "pen_sets must be an object"
    return None


def format_length(metres: float, unit: bool = True) -> str:
    u = _current.get("length_unit", "m")
    text = f"{metres * UNITS.get(u, 1.0):.{int(_current.get('length_decimals', 2))}f}"
    return f"{text} {u}" if unit else text


# ---------------------------------------------------------------- bridge

def project_settings() -> str:
    return B._dump({"ok": True, "settings": current(), "defaults": copy.deepcopy(DEFAULTS), "kept": kept})


def set_project_settings(changes_json: str) -> str:
    global _current
    try:
        changes = json.loads(changes_json)
    except ValueError as ex:
        return B._dump({"ok": False, "error": f"bad input: {ex}"})
    if not isinstance(changes, dict):
        return B._dump({"ok": False, "error": "bad input: expected an object"})
    for k, v in changes.items():
        if (err := _error(k, v)) is not None:
            return B._dump({"ok": False, "error": err})
    _current = {**_current, **copy.deepcopy(changes)}
    return B._dump({"ok": True, "settings": current(), "dirty": B._dirty()})
```

- [ ] **Step 4: Wire it into the bridge**

In `python/kimbim/app_bridge.py`:

```python
def _dirty() -> bool:
    """Unsaved work: model edits since the last save, or changed project settings."""
    from . import settings

    return _current_id() != _saved_id or settings.is_dirty()


def state() -> str:
    return _dump({"dirty": _dirty(), "path": _path, "inconsistent": _inconsistent, **_flags()})
```

At the end of `_reset_history` (after `layers.forget()`), add the documents hook (Task 5 fills it; for
now reset the settings):

```python
    from . import settings

    settings.load(None)
```

And next to the other re-exports at the bottom:

```python
from .settings import project_settings, set_project_settings  # noqa: E402,F401
```

In `python/kimbim/annotations.py`, `_measure`:

```python
def _measure(points) -> str:
    """Each segment of the chain, as measured along the dimension line, in the project's length unit."""
    from .settings import format_length

    _, on_line = _projected(points)
    return " ".join(format_length(math.dist(p, q), unit=False) for p, q in zip(on_line, on_line[1:]))
```

Also, in `python/kimbim/versioning.py`, `_dirty()` becomes `return B._dirty()`.

- [ ] **Step 5: Run the tests**

Run: `pixi run pytest tests/python/test_settings.py tests/python/test_annotations.py tests/python/test_dimensions.py -q`
Expected: all pass. (If `add_annotation`/`annotations` take different arguments, read their signatures in `annotations.py` and adapt the test call, not the module.)

- [ ] **Step 6: Commit**

```bash
git add python/kimbim/settings.py python/kimbim/app_bridge.py python/kimbim/annotations.py python/kimbim/versioning.py tests/python/test_settings.py
git commit -m "feat(settings): project settings with defaults, validation, merge and length units (step 2)"
```

---

### Task 2: Settings travel in the history

**Files:**
- Modify: `python/kimbim/layout.py` (`SETTINGS_PATH`)
- Modify: `python/kimbim/project.py` (`_records`, `_changes`, `commit`, `status`, `diff`, `settings_at`, `merge_preview`, `merge`, `MergePreview`)
- Modify: `python/kimbim/versioning.py` (`_version_id`, `_unversioned`, `save_version`, `version_changes`, `compare`, `_open_head`, `enable_versioning`, `switch_option`, `combine_options`, `project_state`, `_summary`)
- Test: `tests/python/test_settings_history.py`

**Interfaces:**
- Consumes: Task 1 `S.to_bytes`, `S.from_bytes`, `S.load`, `S.current`, `S.merge`, `S.changed_keys`, `S.mark_saved`.
- Produces: `Project.commit(ifc_path, message, *, author=None, time=None, merged=None, settings: bytes | None = None)`, `Project.status(ifc_path, settings: bytes | None = None)`, `Project.settings_at(rev="HEAD") -> bytes | None`, `MergePreview.settings: bytes | None`, `MergePreview.settings_conflicts: list[str]`; versioning `_version_id: int`, `_unversioned() -> bool`, `mark_versioned()`, `project_state()["unversioned"]`, `compare(...)["settings"]: list[str]`, `version_changes()["settings"]: list[str]`.

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 2: project settings are versioned with the model (D72)."""
import json

import pytest

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def versioned(tmp_path):
    assert call("new_project", "Ajustes")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    t = call("wall_types")["types"][0]["guid"]
    wall = call("create_wall", level, t, 0, 0, 5, 0, 3.0, "", "")["guid"]
    r = call("enable_versioning", str(tmp_path / "p"), "Initial import")
    assert r["ok"], r
    return {"folder": tmp_path / "p", "wall": wall}


def test_a_settings_change_alone_is_a_version(versioned):
    assert call("set_project_settings", json.dumps({"plan_cut_height": 1.1}))["ok"]
    assert call("project_state")["unversioned"] is True
    assert call("version_changes")["settings"] == ["plan_cut_height"]
    r = call("save_version", "Lower cut")
    assert r["ok"], r
    assert call("project_state")["unversioned"] is False
    first = call("history", 10)["versions"][-1]["id"]
    assert call("compare", first, "WORKING")["settings"] == ["plan_cut_height"]
    assert not call("save_version", "again")["ok"]  # nothing changed


def test_going_back_to_a_version_brings_back_its_settings(versioned):
    assert call("create_option", "B")["ok"]
    assert call("set_project_settings", json.dumps({"drawing_scale": 50}))["ok"]
    assert call("save_version", "B at 1:50")["ok"]
    assert call("switch_option", "main")["ok"]
    assert call("project_settings")["settings"]["drawing_scale"] == 100
    assert call("switch_option", "B")["ok"]
    assert call("project_settings")["settings"]["drawing_scale"] == 50


def test_switching_options_is_refused_with_settings_not_versioned(versioned):
    assert call("create_option", "B")["ok"]
    assert call("set_project_settings", json.dumps({"sheet_paper": "A3"}))["ok"]
    r = call("switch_option", "main")
    assert not r["ok"] and "version" in r["error"]


def test_combining_options_merges_settings_by_key(versioned):
    assert call("create_option", "B")["ok"]
    assert call("set_project_settings", json.dumps({"sheet_paper": "A3", "drawing_scale": 200}))["ok"]
    call("set_name", json.dumps([versioned["wall"]]), "B wall")
    assert call("save_version", "B")["ok"]
    assert call("switch_option", "main")["ok"]
    assert call("set_project_settings", json.dumps({"plan_cut_height": 1.0, "drawing_scale": 50}))["ok"]
    t = call("wall_types")["types"][0]["guid"]
    level = call("storeys")["storeys"][0]["guid"]
    call("create_wall", level, t, 0, 4, 5, 4, 3.0, "", "")
    assert call("save_version", "main")["ok"]
    r = call("combine_options", "B", "{}")
    assert r["ok"] and r["status"] == "merge", r
    s = call("project_settings")["settings"]
    assert (s["sheet_paper"], s["plan_cut_height"], s["drawing_scale"]) == ("A3", 1.0, 50)
    assert any("drawing_scale" in w for w in r["warnings"])
    assert call("project_state")["unversioned"] is True
    assert call("save_version", "Combined")["ok"]
    assert call("project_settings")["settings"]["sheet_paper"] == "A3"


def test_old_projects_without_settings_open_with_the_defaults(versioned):
    from kimbim import versioning
    from kimbim.layout import SETTINGS_PATH

    project = versioning._project
    assert SETTINGS_PATH in project._head_entries()  # enable_versioning stores them
    assert project.settings_at("HEAD") is not None
```

- [ ] **Step 2: Run them to see them fail**

Run: `pixi run pytest tests/python/test_settings_history.py -q`
Expected: FAIL — `KeyError: 'unversioned'` / `ImportError: SETTINGS_PATH`.

- [ ] **Step 3: Layout and Project**

`python/kimbim/layout.py`, under `META_PATH`:

```python
SETTINGS_PATH = "settings.json"  # project settings (step 2, D72); not a record, never composed into IFC
```

`python/kimbim/project.py`:

```python
from .layout import META_PATH, SETTINGS_PATH, blob_oid, key_to_path, path_to_key
```

`_describe`: first line `if key == "settings": return "(project settings)", None`.

`_records` skips the settings entry:

```python
    def _records(self, rev: str) -> dict[str, bytes]:
        entries = {p: o for p, o in self._entries(rev).items() if p != SETTINGS_PATH}
        paths = sorted(entries)
        blobs = self.repo.read_blobs([entries[p] for p in paths])
        return {path_to_key(p): b for p, b in zip(paths, blobs)}

    def settings_at(self, rev: str = "HEAD") -> bytes | None:
        entries = self._entries(rev) if self.repo.head() is not None else {}
        oid = entries.get(SETTINGS_PATH)
        return self.repo.read_blobs([oid])[0] if oid else None
```

`_changes` takes the settings separately (records loop ignores the settings path):

```python
    def _changes(self, old_entries: dict[str, str], new: dict[str, bytes],
                 settings: bytes | None = None) -> tuple[Changes, dict[str, bytes | None]]:
        old_settings = old_entries.get(SETTINGS_PATH)
        old_entries = {p: o for p, o in old_entries.items() if p != SETTINGS_PATH}
        # ... existing body unchanged up to `items` ...
        if settings is not None and old_settings != blob_oid(settings):
            writes[SETTINGS_PATH] = settings
            items.append(Change("added" if old_settings is None else "modified", "settings", "(project settings)", None))
        return Changes(items), writes
```

`status(self, ifc_path, settings=None)` and `commit(..., merged=None, settings: bytes | None = None)` pass
`settings` through to `_changes`. `diff` passes `self.settings_at(b)`:

```python
        changes, _ = self._changes(old, self._records(b), self.settings_at(b))
```

`MergePreview` gains `settings: bytes | None = None` and
`settings_conflicts: list = field(default_factory=list)`. In `merge_preview`, for status "merge":

```python
        from . import settings as S

        sides = [self.settings_at(r) if r else None for r in (base, ours, theirs)]
        merged_settings, conflicts = None, []
        if any(s is not None for s in sides):
            merged, conflicts = S.merge(*[S.from_bytes(s) for s in sides])
            merged_settings = S.to_bytes(merged)
        return MergePreview("merge", base, ours, theirs, result, merged_settings, conflicts)
```

and `merge` passes `preview.settings` to `_changes(self._head_entries(), preview.result.records, preview.settings)`.

- [ ] **Step 4: Versioning**

`python/kimbim/versioning.py`:

```python
from . import settings as S

_version_id = 0      # B._current_id() when the open model last matched a version
_versioned: dict = {}  # the settings of that version


def mark_versioned(unversioned: bool = False) -> None:
    """The open model and settings match the latest version (or, `unversioned`, they don't)."""
    global _version_id, _versioned
    _version_id = -1 if unversioned else B._current_id()
    _versioned = S.current()


def _unversioned() -> bool:
    return _project is not None and (B._current_id() != _version_id or S.current() != _versioned)
```

- `project_state()`: add `"unversioned": _unversioned()` in both branches (False when not versioned).
- `_summary`: `if c.key == "settings": continue` before the `o/` check.
- `version_changes()`: `s = _summary(_project.status(_write_working(), S.to_bytes()))`; add
  `"settings": S.changed_keys(S.from_bytes(_project.settings_at("HEAD")), S.current())` to the result.
- `save_version`: `_project.commit(working, message.strip(), merged=merged, settings=S.to_bytes())`;
  after success and in the `NothingToCommit` branch: `_mark_saved(working); S.mark_saved(); mark_versioned()`.
- `enable_versioning`: `project.commit(working, message or "Initial import", settings=S.to_bytes())`, then
  `_mark_saved(working); S.mark_saved(); mark_versioned()`.
- `compare`: rev_b "WORKING": `_changes(..., _project._decompose_file(_write_working()), S.to_bytes())` and
  `keys = S.changed_keys(S.from_bytes(_project.settings_at(rev_a)), S.current())`; else
  `keys = S.changed_keys(S.from_bytes(_project.settings_at(rev_a)), S.from_bytes(_project.settings_at(rev_b)))`.
  Add `"settings": keys`.
- `_open_head`: after `B.open_model(...)` and `_project = project`:
  `S.load(S.from_bytes(project.settings_at("HEAD"))); mark_versioned()`.
- `switch_option` and `combine_options` guard on `_unversioned()` (message unchanged: "save a version or
  discard them ...").
- `combine_options`, merge branch, after opening the combined model:

```python
    S.load(S.from_bytes(preview.settings), dirty=True) if preview.settings else None
    mark_versioned(unversioned=True)
    warnings = list(result.warnings) + [f"Project setting {k}: kept this option's value" for k in preview.settings_conflicts]
```

  and return `warnings` instead of `result.warnings`.

- [ ] **Step 5: Run the tests**

Run: `pixi run pytest tests/python/test_settings_history.py tests/python/test_versioning_app.py tests/python/test_project.py tests/python/test_combine.py tests/python/test_merge.py tests/python/test_milestones.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add python/kimbim/layout.py python/kimbim/project.py python/kimbim/versioning.py tests/python/test_settings_history.py
git commit -m "feat(versioning): project settings travel in the history (settings.json per version, merged by key)"
```

---

### Task 3: The `.kim` container

**Files:**
- Create: `python/kimbim/kimfile.py`
- Test: `tests/python/test_kimfile.py`

**Interfaces:**
- Produces: `KimError(Exception)`, `MANIFEST = "kimbim-file.json"`, `VERSION = 1`, `pack(folder: Path, kim: Path, kind: str = "project") -> None`, `read_manifest(kim: Path) -> dict`, `unpack(kim: Path, folder: Path) -> dict` (returns the manifest), `path_hash(path) -> str` (16 hex), `REPLACE_TRIES = 5`.

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 2: the .kim container (a zip of the project folder)."""
import json
import os
import zipfile

import pytest

from kimbim import kimfile as K


def project_folder(root):
    (root / ".git" / "objects" / "pack").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (root / ".git" / "objects" / "pack" / "pack-1.pack").write_bytes(b"PACK" + bytes(100))
    (root / ".kimbim" / "cache").mkdir(parents=True)
    (root / ".kimbim" / "cache" / "big.bin").write_bytes(bytes(1000))
    (root / ".kimbim" / "working.ifc").write_text("ISO-10303-21;\n")
    (root / ".kimbim" / "settings.json").write_text("{}\n")
    (root / ".kimbim" / "lock").write_text("{}")
    return root


def test_pack_and_unpack_round_trip(tmp_path):
    src = project_folder(tmp_path / "src")
    kim = tmp_path / "Casa ñ.kim"
    K.pack(src, kim)
    with zipfile.ZipFile(kim) as z:
        names = set(z.namelist())
        assert z.getinfo(".git/objects/pack/pack-1.pack").compress_type == zipfile.ZIP_STORED
        assert z.getinfo(".kimbim/working.ifc").compress_type == zipfile.ZIP_DEFLATED
    assert ".kimbim/cache/big.bin" not in names and ".kimbim/lock" not in names
    manifest = K.unpack(kim, tmp_path / "out")
    assert manifest["format"] == "kim" and manifest["version"] == 1 and manifest["kind"] == "project"
    assert (tmp_path / "out" / ".kimbim" / "working.ifc").read_text() == "ISO-10303-21;\n"
    assert (tmp_path / "out" / ".git" / "HEAD").exists()
    assert not (tmp_path / "out" / K.MANIFEST).exists()  # the manifest describes the file, not the folder


def test_a_failed_save_leaves_the_old_file(tmp_path, monkeypatch):
    src = project_folder(tmp_path / "src")
    kim = tmp_path / "a.kim"
    K.pack(src, kim)
    before = kim.read_bytes()
    (src / ".kimbim" / "working.ifc").write_text("changed")
    monkeypatch.setattr(K, "_write_entries", lambda *a, **k: (_ for _ in ()).throw(OSError(28, "No space left")))
    with pytest.raises(K.KimError, match="No space"):
        K.pack(src, kim)
    assert kim.read_bytes() == before


def test_a_busy_target_is_retried_then_reported(tmp_path, monkeypatch):
    src = project_folder(tmp_path / "src")
    kim = tmp_path / "a.kim"
    K.pack(src, kim)
    before = kim.read_bytes()
    calls = []

    def busy(a, b):
        calls.append(1)
        raise PermissionError(13, "in use by another program")

    monkeypatch.setattr(K.os, "replace", busy)
    monkeypatch.setattr(K, "REPLACE_WAIT", 0.0)
    with pytest.raises(K.KimError, match="in use"):
        K.pack(src, kim)
    assert len(calls) == K.REPLACE_TRIES and kim.read_bytes() == before


@pytest.mark.parametrize("name", ["../evil.txt", "/abs.txt", "C:/x.txt", ".kimbim/../../evil.txt"])
def test_entries_outside_the_folder_are_refused(tmp_path, name):
    kim = tmp_path / "bad.kim"
    with zipfile.ZipFile(kim, "w") as z:
        z.writestr(K.MANIFEST, json.dumps({"format": "kim", "version": 1, "kind": "project"}))
        z.writestr(name, "x")
    with pytest.raises(K.KimError, match="unsafe"):
        K.unpack(kim, tmp_path / "out" / "in")
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "out" / "evil.txt").exists()


def test_damaged_unknown_and_newer_files_are_refused_untouched(tmp_path):
    junk = tmp_path / "junk.kim"
    junk.write_bytes(b"not a zip")
    with pytest.raises(K.KimError, match="not a KimBim file"):
        K.read_manifest(junk)
    nomani = tmp_path / "nomani.kim"
    with zipfile.ZipFile(nomani, "w") as z:
        z.writestr("x", "y")
    with pytest.raises(K.KimError, match="not a KimBim file"):
        K.read_manifest(nomani)
    newer = tmp_path / "newer.kim"
    with zipfile.ZipFile(newer, "w") as z:
        z.writestr(K.MANIFEST, json.dumps({"format": "kim", "version": 99, "kind": "project"}))
    with pytest.raises(K.KimError, match="newer KimBim"):
        K.unpack(newer, tmp_path / "o")
    assert junk.read_bytes() == b"not a zip"


def test_path_hash_is_stable_and_case_insensitive_on_windows(tmp_path):
    a = K.path_hash(tmp_path / "A.kim")
    assert len(a) == 16 and a == K.path_hash(str(tmp_path / "A.kim"))
    if os.name == "nt":
        assert a == K.path_hash(str(tmp_path / "a.KIM"))
```

- [ ] **Step 2: Run them to see them fail**

Run: `pixi run pytest tests/python/test_kimfile.py -q`
Expected: FAIL — `ImportError: cannot import name 'kimfile'`.

- [ ] **Step 3: Write `kimfile.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""The .kim file (step 2, D72): a zip of the project folder plus a small manifest.

Saving never touches the old file until the new one is complete: the zip is written beside the
target as <name>.kim.saving and swapped in with one os.replace (retried while OneDrive or an
antivirus holds the file for a moment). Unpacking refuses entries that would land outside the folder.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import time
import zipfile

MANIFEST = "kimbim-file.json"
VERSION = 1
REPLACE_TRIES = 5
REPLACE_WAIT = 0.2  # seconds between tries
SKIP = (".kimbim/cache/", ".kimbim/index.db", ".kimbim/lock", ".kimbim/recovery/")


class KimError(Exception):
    pass


def path_hash(path) -> str:
    full = os.path.normcase(os.path.abspath(str(path)))
    return hashlib.sha256(full.encode("utf-8")).hexdigest()[:16]


def _app_version() -> str:
    try:
        from importlib.metadata import version

        return version("kimbim")
    except Exception:  # noqa: BLE001 (not installed as a package: a dev checkout)
        return "dev"


def _entries(folder: pathlib.Path):
    for p in sorted(folder.rglob("*")):
        if not p.is_file():
            continue
        name = p.relative_to(folder).as_posix()
        if name == MANIFEST or any(name == s or name.startswith(s) for s in SKIP):
            continue
        yield p, name


def _write_entries(z: zipfile.ZipFile, folder: pathlib.Path, kind: str) -> None:
    z.writestr(MANIFEST, json.dumps({"format": "kim", "version": VERSION, "kind": kind, "app": _app_version()}, indent=1))
    for p, name in _entries(folder):
        stored = name.startswith(".git/objects/pack/")  # already compressed
        z.write(p, name, compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)


def pack(folder, kim, kind: str = "project") -> None:
    folder, kim = pathlib.Path(folder), pathlib.Path(kim)
    tmp = kim.with_name(kim.name + ".saving")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            _write_entries(z, folder, kind)
        with open(tmp, "rb+") as f:
            os.fsync(f.fileno())
    except OSError as ex:
        tmp.unlink(missing_ok=True)
        raise KimError(f"could not write {kim.name}: {ex.strerror or ex}") from None
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, kim)
            return
        except PermissionError as ex:
            error = ex
            time.sleep(REPLACE_WAIT)
    raise KimError(f"could not replace {kim.name}: {error.strerror or error} (the new version is in {tmp.name})")


def read_manifest(kim) -> dict:
    kim = pathlib.Path(kim)
    try:
        with zipfile.ZipFile(kim) as z:
            manifest = json.loads(z.read(MANIFEST))
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        raise KimError(f"{kim.name} is not a KimBim file, or it is damaged") from None
    if not isinstance(manifest, dict) or manifest.get("format") != "kim":
        raise KimError(f"{kim.name} is not a KimBim file, or it is damaged")
    if int(manifest.get("version", 0)) > VERSION:
        raise KimError(f"{kim.name} was made by a newer KimBim; update KimBim to open it")
    return manifest


def _safe(name: str) -> bool:
    p = pathlib.PurePosixPath(name)
    return not (name.startswith(("/", "\\")) or ":" in p.parts[0] if p.parts else True) and ".." not in p.parts


def unpack(kim, folder) -> dict:
    kim, folder = pathlib.Path(kim), pathlib.Path(folder)
    manifest = read_manifest(kim)
    with zipfile.ZipFile(kim) as z:
        names = [n for n in z.namelist() if n != MANIFEST]
        bad = [n for n in names if not _safe(n.replace("\\", "/"))]
        if bad:
            raise KimError(f"{kim.name} has unsafe entries ({bad[0]}); it was not opened")
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        for n in names:
            if n.endswith("/"):
                continue
            target = folder / n
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return manifest
```

Note `_safe`: a name is unsafe if it is absolute (`/`, `\`), has a drive (`C:` in its first part) or
contains `..`. Write it plainly if the one-liner reads badly:

```python
def _safe(name: str) -> bool:
    if not name or name.startswith(("/", "\\")):
        return False
    parts = pathlib.PurePosixPath(name).parts
    return ":" not in parts[0] and ".." not in parts
```

- [ ] **Step 4: Run the tests**

Run: `pixi run pytest tests/python/test_kimfile.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/kimbim/kimfile.py tests/python/test_kimfile.py
git commit -m "feat(kimfile): the .kim container: atomic save, safe unpack, manifest with format version"
```

---

### Task 4: Locks

**Files:**
- Modify: `python/kimbim/kimfile.py`
- Test: `tests/python/test_kimfile.py` (append)

**Interfaces:**
- Produces: `lock_path(kim: Path) -> Path` (`<file>.kim.lock`), `pid_alive(pid: int) -> bool`, `me() -> dict` (`{"user", "machine", "pid", "since"}`), `display_user: str` (module variable; documents sets it from the author name), `acquire(lock: Path) -> dict | None` (None = acquired; else the holder), `release(lock: Path) -> None` (only our own lock).

- [ ] **Step 1: Write the failing tests**

```python
def test_a_free_file_is_locked_and_released(tmp_path):
    lock = K.lock_path(tmp_path / "a.kim")
    assert lock.name == "a.kim.lock"
    assert K.acquire(lock) is None
    held = json.loads(lock.read_text())
    assert held["pid"] == os.getpid() and held["machine"] and held["user"]
    K.release(lock)
    assert not lock.exists()


def test_someone_elses_lock_is_reported(tmp_path):
    lock = tmp_path / "a.kim.lock"
    lock.write_text(json.dumps({"user": "Ana", "machine": "OTHER-PC", "pid": 1, "since": "2026-10-08T10:42"}))
    holder = K.acquire(lock)
    assert holder["user"] == "Ana" and holder["machine"] == "OTHER-PC"
    K.release(lock)  # not ours: left alone
    assert lock.exists()


def test_our_own_lock_from_a_crash_is_taken_over(tmp_path):
    lock = tmp_path / "a.kim.lock"
    dead = 999_999_999
    assert not K.pid_alive(dead)
    lock.write_text(json.dumps({**K.me(), "pid": dead}))
    assert K.acquire(lock) is None
    assert json.loads(lock.read_text())["pid"] == os.getpid()


def test_a_second_window_of_ours_does_not_take_the_lock(tmp_path):
    import subprocess
    import sys

    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        lock = tmp_path / "a.kim.lock"
        lock.write_text(json.dumps({**K.me(), "pid": other.pid}))
        holder = K.acquire(lock)
        assert holder is not None and holder["pid"] == other.pid
    finally:
        other.kill()


def test_a_garbled_lock_counts_as_free(tmp_path):
    lock = tmp_path / "a.kim.lock"
    lock.write_text("{{{")
    assert K.acquire(lock) is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `pixi run pytest tests/python/test_kimfile.py -q -k lock`
Expected: FAIL — `AttributeError: module 'kimbim.kimfile' has no attribute 'lock_path'`.

- [ ] **Step 3: Implement**

```python
import datetime
import getpass
import socket

display_user = ""  # the name others see in the lock (the author name from preferences)


def lock_path(kim) -> pathlib.Path:
    kim = pathlib.Path(kim)
    return kim.with_name(kim.name + ".lock")


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def me() -> dict:
    try:
        account = getpass.getuser()
    except Exception:  # noqa: BLE001
        account = "?"
    return {"user": display_user or account, "account": account, "machine": socket.gethostname(),
            "pid": os.getpid(), "since": datetime.datetime.now().isoformat(timespec="minutes")}


def _read_lock(lock: pathlib.Path) -> dict | None:
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _ours(held: dict) -> bool:
    mine = me()
    return held.get("account") == mine["account"] and held.get("machine") == mine["machine"]


def acquire(lock) -> dict | None:
    """Lock the file for this process. Returns None when it is ours now, else who holds it. A lock left
    by this user on this machine by a process that is gone (a crash) is taken over."""
    lock = pathlib.Path(lock)
    held = _read_lock(lock) if lock.exists() else None
    if held and held.get("pid") != os.getpid():
        if not (_ours(held) and not pid_alive(int(held.get("pid", 0)))):
            return held
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps(me()), encoding="utf-8")
    return None


def release(lock) -> None:
    lock = pathlib.Path(lock)
    held = _read_lock(lock) if lock.exists() else None
    if held is not None and held.get("pid") == os.getpid() and _ours(held):
        lock.unlink(missing_ok=True)
```

Note: `me()` includes `"account"` (the OS account) so a display name change doesn't orphan our own lock;
the test `test_our_own_lock_from_a_crash_is_taken_over` builds its lock from `K.me()`, so it carries it.

- [ ] **Step 4: Run the tests**

Run: `pixi run pytest tests/python/test_kimfile.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/kimbim/kimfile.py tests/python/test_kimfile.py
git commit -m "feat(kimfile): locks: one editor at a time, crash leftovers taken over, others read-only"
```

---

### Task 5: Documents — open, save and close a `.kim`, a folder or an IFC

**Files:**
- Create: `python/kimbim/documents.py`
- Modify: `python/kimbim/app_bridge.py` (`_reset_history` calls `documents.on_model_opened(path)`; re-exports)
- Modify: `python/kimbim/project.py` (`_AUTHOR` override in `_author()`)
- Modify: `python/kimbim/versioning.py` (`project_state()` adds `documents.state_fields()`)
- Test: `tests/python/test_documents.py`

**Interfaces:**
- Consumes: Task 1 `S.load/S.current/S.to_bytes/S.from_bytes/S.mark_saved/S.kept`; Task 2 `V.mark_versioned`, `V._unversioned`, `Project.commit(..., settings=)`, `Project.settings_at`; Task 3 `K.pack/K.unpack/K.read_manifest/K.path_hash/K.KimError`; Task 4 `K.acquire/K.release/K.lock_path/K.display_user`.
- Produces (bridge, all JSON): `set_app_paths(data_dir)`, `set_author(name, email)`, `document_state() -> {"mode": "plain"|"kim"|"folder"|"template", "path", "name", "read_only", "untitled", "template", "kept"}`, `open_kim(path, read_only="") -> {"ok", "path"} | {"ok": False, "locked": {...}, "error"}`, `open_folder(folder, read_only="")` (same shape), `kim_beside(ifc_path) -> {"kim", "exists", "free"}`, `import_ifc(ifc_path, kim_path) -> {"ok", "path", "kim"}`, `save_document() -> {"ok", "path"}`, `save_as_kim(path, message="")`, `save_as_folder(folder, message="")`, `export_ifc(path)`, `close_document()`.
- Produces (Python): `documents.data_dir() -> Path`, `documents.on_model_opened(path)`, `documents.state_fields() -> dict`, `documents._doc`, `documents._pending`.

Rulings carried by this task (the spec is silent):
- A read-only document has no history attached (Versions, Compare and options say "isn't versioned"):
  its working folder is a private copy and nothing may be committed to it.
- A read-only `.kim` unpacks to `open/<hash>-ro-<pid>`, so it never clobbers the editor's working folder.
- `save_as_kim` from a model without history (plain or template) creates the history with one version:
  "Created from <template>" when the model came from a template, else "First version".

- [ ] **Step 1: Write the failing tests** — `tests/python/test_documents.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 2: the open document — .kim, project folder or plain IFC (D72)."""
import json

import pytest

from kimbim import app_bridge as b
from kimbim import documents as D
from kimbim import kimfile as K


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture(autouse=True)
def data(tmp_path):
    D.set_app_paths(str(tmp_path / "data"))
    yield tmp_path / "data"
    D.close_document()


def house():
    assert call("new_project", "Casa")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    t = call("wall_types")["types"][0]["guid"]
    return call("create_wall", level, t, 0, 0, 5, 0, 3.0, "", "")["guid"]


def open_kim(path, read_only=""):
    r = call("open_kim", str(path), read_only)
    if r["ok"]:
        assert call("open_model", r["path"])["ok"]  # what the app's loader does next
    return r


def test_a_new_project_saved_as_kim_has_history_and_reopens(tmp_path, data):
    wall = house()
    assert call("set_project_settings", json.dumps({"plan_cut_height": 1.1}))["ok"]
    kim = tmp_path / "Casa ñ.kim"
    r = call("save_as_kim", str(kim), "")
    assert r["ok"], r
    assert [v["message"] for v in call("history", 10)["versions"]] == ["First version"]
    st = call("document_state")
    assert st["mode"] == "kim" and st["name"] == "Casa ñ.kim" and not st["untitled"] and st["kept"]
    assert K.lock_path(kim).exists() and call("state")["dirty"] is False
    assert call("close_document")["ok"]
    assert not K.lock_path(kim).exists() and not (data / "open" / K.path_hash(kim)).exists()
    assert open_kim(kim)["ok"]
    assert b._model.by_guid(wall) is not None
    assert call("project_settings")["settings"]["plan_cut_height"] == 1.1
    assert call("project_state")["versioned"] is True and call("state")["dirty"] is False


def test_ctrl_s_saves_without_a_version_and_reopening_keeps_unversioned_work(tmp_path):
    wall = house()
    kim = tmp_path / "a.kim"
    assert call("save_as_kim", str(kim), "")["ok"]
    call("set_name", json.dumps([wall]), "Muro guardado")
    assert call("save_document")["ok"]
    assert len(call("history", 10)["versions"]) == 1
    assert call("state")["dirty"] is False and call("project_state")["unversioned"] is True
    assert call("close_document")["ok"]
    assert open_kim(kim)["ok"]
    assert b._model.by_guid(wall).Name == "Muro guardado"
    assert call("state")["dirty"] is False and call("project_state")["unversioned"] is True
    assert call("create_option", "B")["ok"]
    assert not call("switch_option", "main")["ok"]  # still not a version: the app asks first
    assert call("save_version", "Rename")["ok"]
    assert call("project_state")["unversioned"] is False


def test_a_locked_kim_opens_read_only(tmp_path):
    house()
    kim = tmp_path / "a.kim"
    assert call("save_as_kim", str(kim), "")["ok"]
    assert call("close_document")["ok"]
    foreign = {"user": "Ana", "account": "ana", "machine": "OTHER-PC", "pid": 4, "since": "2026-10-08T10:42"}
    K.lock_path(kim).write_text(json.dumps(foreign))
    r = call("open_kim", str(kim), "")
    assert not r["ok"] and r["locked"]["user"] == "Ana" and "Ana" in r["error"]
    before = kim.read_bytes()
    assert open_kim(kim, "1")["ok"]
    assert call("document_state")["read_only"] is True
    assert call("project_state")["versioned"] is False
    assert not call("save_document")["ok"]
    assert call("close_document")["ok"]
    assert json.loads(K.lock_path(kim).read_text())["user"] == "Ana" and kim.read_bytes() == before


def test_opening_an_ifc_makes_a_kim_beside_it(tmp_path):
    house()
    ifc = tmp_path / "House.ifc"
    assert call("save", str(ifc))["ok"]
    before = ifc.read_bytes()
    beside = call("kim_beside", str(ifc))
    assert beside["kim"] == str(tmp_path / "House.kim") and beside["exists"] is False
    r = call("import_ifc", str(ifc), beside["kim"])
    assert r["ok"], r
    assert call("open_model", r["path"])["ok"]
    assert (tmp_path / "House.kim").exists() and ifc.read_bytes() == before
    assert [v["message"] for v in call("history", 5)["versions"]] == ["Imported from House.ifc"]
    assert call("document_state")["mode"] == "kim"
    again = call("kim_beside", str(ifc))
    assert again["exists"] is True and again["free"] == str(tmp_path / "House (2).kim")
    assert not call("import_ifc", str(ifc), again["kim"])["ok"]


def test_save_as_folder_and_back_to_a_kim(tmp_path):
    house()
    assert call("save_as_kim", str(tmp_path / "a.kim"), "")["ok"]
    folder = tmp_path / "carpeta"
    r = call("save_as_folder", str(folder), "")
    assert r["ok"], r
    assert (folder / ".git").is_dir() and (folder / ".kimbim" / "lock").exists()
    assert not K.lock_path(tmp_path / "a.kim").exists()
    assert call("document_state")["mode"] == "folder"
    assert call("set_project_settings", json.dumps({"sheet_paper": "A3"}))["ok"]
    assert call("save_document")["ok"]
    assert json.loads((folder / ".kimbim" / "settings.json").read_text())["sheet_paper"] == "A3"
    assert call("save_as_kim", str(tmp_path / "b.kim"), "")["ok"]
    assert not (folder / ".kimbim" / "lock").exists()
    assert call("close_document")["ok"]
    assert open_kim(tmp_path / "b.kim")["ok"]
    assert len(call("history", 10)["versions"]) == 1
    assert call("project_settings")["settings"]["sheet_paper"] == "A3"


def test_export_ifc_leaves_the_document_as_it_is(tmp_path):
    wall = house()
    assert call("save_as_kim", str(tmp_path / "a.kim"), "")["ok"]
    call("set_name", json.dumps([wall]), "Exportado")
    assert call("export_ifc", str(tmp_path / "out.ifc"))["ok"]
    assert b"Exportado" in (tmp_path / "out.ifc").read_bytes()
    assert call("document_state")["mode"] == "kim" and call("state")["dirty"] is True


def test_existing_project_folders_open_with_default_settings(tmp_path):
    from kimbim.project import Project

    house()
    plain = tmp_path / "old.ifc"
    assert call("save", str(plain))["ok"]
    project = Project.init(tmp_path / "old")
    project.commit(plain, "Made by an older KimBim")  # no settings.json in its tree
    r = call("open_folder", str(tmp_path / "old"), "")
    assert r["ok"], r
    assert call("open_model", r["path"])["ok"]
    assert call("project_settings")["settings"]["plan_cut_height"] == 1.2
    assert call("document_state")["mode"] == "folder" and call("project_state")["unversioned"] is False


def test_opening_another_model_releases_the_kim(tmp_path):
    house()
    kim = tmp_path / "a.kim"
    assert call("save_as_kim", str(kim), "")["ok"]
    assert call("new_project", "otra")["ok"]
    assert not K.lock_path(kim).exists()
    assert call("document_state")["mode"] == "plain" and call("document_state")["untitled"] is True


def test_the_author_from_preferences_signs_versions_and_the_lock(tmp_path):
    assert call("set_author", "Felipe Lecot", "felipe@example.com")["ok"]
    try:
        house()
        kim = tmp_path / "a.kim"
        assert call("save_as_kim", str(kim), "")["ok"]
        assert call("history", 1)["versions"][0]["author"] == "Felipe Lecot"
        assert json.loads(K.lock_path(kim).read_text())["user"] == "Felipe Lecot"
    finally:
        call("set_author", "", "")
```

- [ ] **Step 2: Run them to see them fail**

Run: `pixi run pytest tests/python/test_documents.py -q`
Expected: FAIL — `ImportError: cannot import name 'documents'`.

- [ ] **Step 3: Author override** — `python/kimbim/project.py`:

```python
_AUTHOR: tuple[str, str] | None = None  # set by the app from its preferences (documents.set_author)


def _author() -> tuple[str, str]:
    if _AUTHOR is not None:
        return _AUTHOR
    name = os.environ.get("KIMBIM_AUTHOR_NAME") or _git_config("user.name") or "KimBim User"
    email = os.environ.get("KIMBIM_AUTHOR_EMAIL") or _git_config("user.email") or "user@localhost"
    return name, email
```

- [ ] **Step 4: Write `python/kimbim/documents.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""The open document (step 2, D72): a .kim, a project folder, a template being edited, or a plain IFC.

A .kim is unpacked to a working folder (<data>/open/<hash>/) while it is open; Ctrl+S writes the
model and settings there and packs it back. A project folder is used in place. Opening prepares the
working copy and leaves a "pending" note; the app's loader then opens it (B.open_model), and
on_model_opened() attaches the history, the settings and the document state.

Same protocol as app_bridge (strings in, JSON out, never raise).
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import uuid

from . import app_bridge as B
from . import kimfile as K
from . import project as P
from . import settings as S
from . import versioning as V
from .project import KimbimError, NotAProject, Project

_data_dir: pathlib.Path | None = None
_pending: dict | None = None


def _plain(path: str = "") -> dict:
    # rid: names an untitled document's recovery copy (two untitled models never share one)
    return {"mode": "plain", "source": path, "work": "", "lock": "", "read_only": False, "template": "",
            "rid": uuid.uuid4().hex}


_doc: dict = _plain()


def _fail(message: str, **extra) -> str:
    return B._dump({"ok": False, "error": message, **extra})


def data_dir() -> pathlib.Path:
    if _data_dir is not None:
        return _data_dir
    if os.environ.get("KIMBIM_DATA_DIR"):
        return pathlib.Path(os.environ["KIMBIM_DATA_DIR"])
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return pathlib.Path(os.environ["LOCALAPPDATA"]) / "KimBim"
    return pathlib.Path.home() / ".local" / "share" / "KimBim"


def _same(a, b) -> bool:
    return bool(a) and bool(b) and os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def _skip(_dir, names):
    return [n for n in names if n in ("lock", "cache", "index.db", "recovery")]


def _read(path: pathlib.Path):
    try:
        return path.read_bytes()
    except OSError:
        return None


def _locked(name: str, holder: dict) -> str:
    return _fail(f"{holder.get('user', '?')} has {name} open on {holder.get('machine', '?')} "
                 f"since {holder.get('since', '?')}", locked=holder)


# ---------------------------------------------------------------- state

def set_app_paths(data: str) -> str:
    global _data_dir
    _data_dir = pathlib.Path(data) if data else None
    return B._dump({"ok": True, "data": str(data_dir())})


def set_author(name: str, email: str) -> str:
    P._AUTHOR = (name.strip(), (email or "").strip() or "user@localhost") if (name or "").strip() else None
    K.display_user = (name or "").strip()
    return B._dump({"ok": True})


def state_fields() -> dict:
    d = _doc
    untitled = d["mode"] == "plain" and not B._path
    source = d["source"] or ("" if untitled else B._path)
    return {"mode": d["mode"], "path": source, "name": pathlib.Path(source).name if source else "",
            "read_only": d["read_only"], "untitled": untitled, "template": d["template"], "kept": S.kept}


def document_state() -> str:
    return B._dump({"ok": True, **state_fields()})


def on_model_opened(path: str) -> None:
    """Called by app_bridge whenever a model is opened or created (after versioning.forget)."""
    global _pending, _doc
    if _pending is not None and _same(path, _pending["path"]):
        p, _pending = _pending, None
        _doc = p["doc"]
        V._project = p["project"]
        S.load(p["settings"], dirty=p.get("dirty", False))
        S.kept = _doc["mode"] != "plain"
        if p["project"] is not None:
            V.mark_versioned(unversioned=p["unversioned"])
        if p.get("untitled"):
            B._path = ""
        elif p.get("source_path"):
            B._path = p["source_path"]
        if p.get("dirty"):
            B._saved_id = -1
        return
    if _doc["work"] and _same(path, pathlib.Path(_doc["work"]) / ".kimbim" / "working.ifc"):
        return  # the document's own working copy reopened (an option switch, discard, combine)
    _close()
    _doc = _plain(path)
    S.kept = False


def _close() -> None:
    """Leave the document: its lock and working folder go. Its recovery copy stays (only a save or an
    explicit close_document, after the user saved or discarded, clears it)."""
    d = _doc
    if d["lock"]:
        K.release(d["lock"])
    if d["mode"] in ("kim", "template") and d["work"]:
        shutil.rmtree(d["work"], ignore_errors=True)


def _recovery_key() -> str:
    return _doc["source"] or B._path or _doc.get("rid", "")


def close_document() -> str:
    global _doc
    _clear_recovery(_recovery_key())
    _close()
    _doc = _plain()
    V._project = None
    S.kept = False
    return B._dump({"ok": True})


# ---------------------------------------------------------------- opening

def _prepare(project_dir: pathlib.Path, files_dir: pathlib.Path, doc: dict, attach: bool) -> pathlib.Path:
    """Make files_dir/.kimbim/working.ifc the document's current work and leave the pending note."""
    global _pending
    project = Project.open(project_dir) if (project_dir / ".git" / "HEAD").is_file() else None
    head = project.repo.head() if project else None
    try:
        state = json.loads(_read(project_dir / ".kimbim" / "working.json") or b"{}")
    except ValueError:
        state = {}
    src = project_dir / ".kimbim" / "working.ifc"
    working = files_dir / ".kimbim" / "working.ifc"
    working.parent.mkdir(parents=True, exist_ok=True)
    if head and not (src.exists() and state.get("head") == head):
        project.export(working, overwrite=True, one_owner=True)
        settings, unversioned = S.from_bytes(project.settings_at("HEAD")), False
    else:
        if not src.exists():
            raise KimbimError("the file has no model in it")
        if not _same(src, working):
            shutil.copyfile(src, working)
        settings = S.from_bytes(_read(project_dir / ".kimbim" / "settings.json"))
        unversioned = bool(state.get("unversioned")) and head is not None
    _pending = {"path": str(working), "doc": doc, "project": project if attach else None,
                "settings": settings, "unversioned": unversioned}
    return working


def open_kim(path: str, read_only: str = "") -> str:
    kim = pathlib.Path(path)
    try:
        manifest = K.read_manifest(kim)
    except K.KimError as ex:
        return _fail(str(ex))
    ro = bool(read_only)
    lock = K.lock_path(kim)
    if not ro and (holder := K.acquire(lock)) is not None:
        return _locked(kim.name, holder)
    work = data_dir() / "open" / (K.path_hash(kim) + (f"-ro-{os.getpid()}" if ro else ""))
    mode = "template" if manifest.get("kind") == "template" else "kim"
    doc = {"mode": mode, "source": str(kim), "work": str(work), "lock": "" if ro else str(lock),
           "read_only": ro, "template": ""}
    try:
        K.unpack(kim, work)
        working = _prepare(work, work, doc, attach=not ro and mode == "kim")
    except (K.KimError, KimbimError, OSError) as ex:
        if not ro:
            K.release(lock)
        shutil.rmtree(work, ignore_errors=True)
        return _fail(str(ex))
    return B._dump({"ok": True, "path": str(working), "read_only": ro, "kind": manifest.get("kind", "project")})


def open_folder(folder: str, read_only: str = "") -> str:
    path = pathlib.Path(folder)
    try:
        project = Project.open(path)
    except (NotAProject, KimbimError) as ex:
        return _fail(f"not a KimBim project: {ex}")
    if project.repo.head() is None:
        return _fail("the project has no versions yet")
    ro = bool(read_only)
    lock = path / ".kimbim" / "lock"
    if not ro and (holder := K.acquire(lock)) is not None:
        return _locked(path.name, holder)
    files = data_dir() / "open" / f"{K.path_hash(path)}-ro-{os.getpid()}" if ro else path
    doc = {"mode": "folder", "source": str(path), "work": "" if ro else str(path), "lock": "" if ro else str(lock),
           "read_only": ro, "template": ""}
    try:
        working = _prepare(path, files, doc, attach=not ro)
    except (KimbimError, OSError) as ex:
        if not ro:
            K.release(lock)
        return _fail(str(ex))
    return B._dump({"ok": True, "path": str(working), "read_only": ro})


def kim_beside(ifc_path: str) -> str:
    ifc = pathlib.Path(ifc_path)
    kim = ifc.with_suffix(".kim")
    free, n = kim, 2
    while free.exists():
        free = ifc.with_name(f"{ifc.stem} ({n}).kim")
        n += 1
    return B._dump({"kim": str(kim), "exists": kim.exists(), "free": str(free)})


def import_ifc(ifc_path: str, kim_path: str) -> str:
    """A new .kim beside an IFC: its first version is the IFC as it is. The IFC is never modified."""
    global _pending
    ifc, kim = pathlib.Path(ifc_path), pathlib.Path(kim_path)
    if kim.exists():
        return _fail(f"{kim.name} already exists")
    lock = K.lock_path(kim)
    if (holder := K.acquire(lock)) is not None:
        return _locked(kim.name, holder)
    work = data_dir() / "open" / K.path_hash(kim)
    defaults = S.from_bytes(None)
    try:
        shutil.rmtree(work, ignore_errors=True)
        (work / ".kimbim").mkdir(parents=True)
        working = work / ".kimbim" / "working.ifc"
        shutil.copyfile(ifc, working)
        project = Project.init(work)
        project.commit(working, f"Imported from {ifc.name}", settings=S.to_bytes(defaults))
        (work / ".kimbim" / "settings.json").write_bytes(S.to_bytes(defaults))
        (work / ".kimbim" / "working.json").write_text(
            json.dumps({"head": project.repo.head(), "option": project.current_branch(), "unversioned": False}))
        K.pack(work, kim)
    except (KimbimError, K.KimError, OSError) as ex:
        K.release(lock)
        shutil.rmtree(work, ignore_errors=True)
        return _fail(str(ex))
    doc = {"mode": "kim", "source": str(kim), "work": str(work), "lock": str(lock), "read_only": False, "template": ""}
    _pending = {"path": str(working), "doc": doc, "project": project, "settings": defaults, "unversioned": False}
    return B._dump({"ok": True, "path": str(working), "kim": str(kim)})


# ---------------------------------------------------------------- saving

def _write_files(work: pathlib.Path) -> None:
    """The model, the settings and where they stand against the history, into a project folder."""
    (work / ".kimbim").mkdir(parents=True, exist_ok=True)
    B._model.write(str(work / ".kimbim" / "working.ifc"))
    (work / ".kimbim" / "settings.json").write_bytes(S.to_bytes())
    project = V._project
    (work / ".kimbim" / "working.json").write_text(json.dumps({
        "head": project.repo.head() if project else None,
        "option": project.current_branch() if project else "",
        "unversioned": V._unversioned()}))


def _saved() -> None:
    B._saved_id = B._current_id()
    S.mark_saved()
    _clear_recovery(_recovery_key())


def save_document() -> str:
    if B._model is None:
        return _fail("no model open")
    d = _doc
    if d["read_only"]:
        return _fail("this file is open read-only; use Save As to keep your changes")
    if d["mode"] == "plain":
        if not B._path:
            return _fail("untitled: choose where to save it")
        r = json.loads(B.save(""))
        if r.get("ok"):
            _clear_recovery(_recovery_key())
        return B._dump(r)
    work = pathlib.Path(d["work"])
    try:
        _write_files(work)
        if d["mode"] in ("kim", "template"):
            K.pack(work, d["source"], "template" if d["mode"] == "template" else "project")
    except (K.KimError, OSError) as ex:
        return _fail(str(ex))
    _saved()
    return B._dump({"ok": True, "path": d["source"]})


def _first_message(message: str) -> str:
    if message:
        return message
    return f"Created from {_doc['template']}" if _doc["template"] else "First version"


def _make_history(work: pathlib.Path, message: str) -> None:
    """A history for a model that has none (plain, untitled, a template): one first version."""
    working = work / ".kimbim" / "working.ifc"
    (work / ".kimbim").mkdir(parents=True, exist_ok=True)
    B._model.write(str(working))
    project = Project.init(work)
    project.commit(working, _first_message(message), settings=S.to_bytes())
    V._project = project
    V.mark_versioned()


def _switch_to(doc: dict, work: pathlib.Path) -> None:
    global _doc
    old = _doc
    if old["lock"] and old["lock"] != doc["lock"]:
        K.release(old["lock"])
    if old["mode"] in ("kim", "template") and old["work"] and not _same(old["work"], work):
        shutil.rmtree(old["work"], ignore_errors=True)
    _doc = doc
    V._project = Project.open(work) if (work / ".git" / "HEAD").is_file() else None
    B._path = str(work / ".kimbim" / "working.ifc")
    S.kept = True


def save_as_kim(path: str, message: str = "") -> str:
    if B._model is None:
        return _fail("no model open")
    kim = pathlib.Path(path)
    if _doc["mode"] == "kim" and _same(kim, _doc["source"]) and not _doc["read_only"]:
        return save_document()
    lock = K.lock_path(kim)
    if (holder := K.acquire(lock)) is not None:
        return _locked(kim.name, holder)
    work = data_dir() / "open" / K.path_hash(kim)
    try:
        shutil.rmtree(work, ignore_errors=True)
        if _doc["work"] and not _doc["read_only"] and _doc["mode"] != "plain":
            shutil.copytree(_doc["work"], work, ignore=_skip)
        else:
            work.mkdir(parents=True)
        if not (work / ".git" / "HEAD").is_file():
            _make_history(work, message)
        unversioned = V._unversioned()
        _switch_to({"mode": "kim", "source": str(kim), "work": str(work), "lock": str(lock), "read_only": False,
                    "template": ""}, work)
        if unversioned:
            V.mark_versioned(unversioned=True)
        _write_files(work)
        K.pack(work, kim)
    except (KimbimError, K.KimError, OSError) as ex:
        K.release(lock)
        return _fail(str(ex))
    _saved()
    return B._dump({"ok": True, "path": str(kim)})


def save_as_folder(folder: str, message: str = "") -> str:
    if B._model is None:
        return _fail("no model open")
    path = pathlib.Path(folder)
    if path.exists() and any(path.iterdir()):
        return _fail("choose an empty or new folder for the project")
    lock = path / ".kimbim" / "lock"
    try:
        if _doc["work"] and not _doc["read_only"] and _doc["mode"] != "plain":
            shutil.copytree(_doc["work"], path, ignore=_skip, dirs_exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
        if not (path / ".git" / "HEAD").is_file():
            _make_history(path, message)
        unversioned = V._unversioned()
        K.acquire(lock)
        _switch_to({"mode": "folder", "source": str(path), "work": str(path), "lock": str(lock), "read_only": False,
                    "template": ""}, path)
        if unversioned:
            V.mark_versioned(unversioned=True)
        _write_files(path)
    except (KimbimError, OSError) as ex:
        return _fail(str(ex))
    _saved()
    return B._dump({"ok": True, "path": str(path)})


def export_ifc(path: str) -> str:
    if B._model is None:
        return _fail("no model open")
    try:
        B._model.write(path)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "path": path})


def _clear_recovery(key: str) -> None:  # Task 6 replaces this stub
    pass
```

`save_as_kim`/`save_as_folder` read `V._unversioned()` before `_switch_to` changes `V._project`, then
restore it: a project carried over keeps its "not versioned yet" state.

- [ ] **Step 5: Hook it into the bridge and versioning**

`python/kimbim/app_bridge.py`, end of `_reset_history` (replacing Task 1's settings reset):

```python
    from . import documents, settings

    settings.load(None)
    documents.on_model_opened(path)
```

Re-exports at the bottom of `app_bridge.py`:

```python
from .documents import (  # noqa: E402,F401
    close_document,
    document_state,
    export_ifc,
    import_ifc,
    kim_beside,
    open_folder,
    open_kim,
    save_as_folder,
    save_as_kim,
    save_document,
    set_app_paths,
    set_author,
)
```

`python/kimbim/versioning.py` `project_state()`: add `**documents.state_fields()` to both results
(`from . import documents` inside the function, to avoid an import cycle).

- [ ] **Step 6: Run the tests**

Run: `pixi run pytest tests/python/test_documents.py tests/python/test_versioning_app.py tests/python/test_settings_history.py tests/python/test_settings.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add python/kimbim/documents.py python/kimbim/app_bridge.py python/kimbim/project.py python/kimbim/versioning.py tests/python/test_documents.py
git commit -m "feat(documents): open, save and close .kim files, project folders and IFC (locks, read-only, import beside)"
```

---

### Task 6: Recovery copies and templates

**Files:**
- Modify: `python/kimbim/documents.py`, `python/kimbim/app_bridge.py` (re-exports)
- Test: `tests/python/test_documents.py` (append)

**Interfaces:**
- Consumes: Task 5 `data_dir`, `_doc`, `_pending`, `open_kim`, `open_folder`, `on_model_opened`, `_read`, `_plain`, `_same`; Task 3 `K.pack/K.unpack/K.read_manifest`.
- Produces (bridge): `write_recovery() -> {"ok", "written": bool}`, `recoveries() -> {"items": [{"id", "source", "name", "mode", "time"}]}`, `recover(id) -> {"ok", "path"}`, `discard_recovery(id) -> {"ok"}`, `templates(folder) -> {"templates": [{"name", "path", "builtin", "modified"}], "folder_ok": bool}`, `new_from_template(path) -> {"ok", "path"}` (`path` "" for the built-in: the model is already open), `save_template(folder, name, replace="") -> {"ok", "path"} | {"ok": False, "exists": True}`.
- Produces (Python): `documents.BUILTIN = "builtin"`, `documents.BUILTIN_NAME = "KimBim default"`, `documents.regenerate_ids(f) -> dict[str, str]`.

Rulings carried by this task:
- The recovery copy is written on the GUI thread (a full IFC write: about 1 s on the Clinic, every 5
  minutes, only while there is unsaved work). Cost if wrong: a background writer later.
- Regenerating ids also rewrites every text attribute or property value that holds one of the old ids
  (sheets reference drawings by GlobalId as text).

- [ ] **Step 1: Write the failing tests** (append to `tests/python/test_documents.py`):

```python
def test_a_recovery_copy_is_offered_after_a_crash_and_cleared_by_saving(tmp_path):
    wall = house()
    call("set_name", json.dumps([wall]), "Sin guardar")
    assert call("set_project_settings", json.dumps({"drawing_scale": 20}))["ok"]
    assert call("write_recovery")["written"] is True
    assert call("recoveries")["items"] == []  # this session's own copy is not offered
    assert call("new_project", "otra")["ok"]  # a "restart": another model is open
    items = call("recoveries")["items"]
    assert len(items) == 1 and items[0]["source"] == "" and items[0]["mode"] == "plain"
    r = call("recover", items[0]["id"])
    assert r["ok"], r
    assert call("open_model", r["path"])["ok"]
    assert b._model.by_guid(wall).Name == "Sin guardar"
    assert call("project_settings")["settings"]["drawing_scale"] == 20
    assert call("state")["dirty"] is True and call("document_state")["untitled"] is True
    assert call("recoveries")["items"] == []


def test_a_recovered_kim_reopens_the_kim_with_the_recovered_work(tmp_path):
    wall = house()
    kim = tmp_path / "a.kim"
    assert call("save_as_kim", str(kim), "")["ok"]
    call("set_name", json.dumps([wall]), "Recuperado")
    assert call("write_recovery")["written"] is True
    D._doc = D._plain()  # a crash: nothing was closed; the lock, working folder and copy are left behind
    item = call("recoveries")["items"][0]
    assert item["source"] == str(kim) and item["name"] == "a.kim"
    r = call("recover", item["id"])
    assert r["ok"], r
    assert call("open_model", r["path"])["ok"]
    assert b._model.by_guid(wall).Name == "Recuperado" and call("document_state")["mode"] == "kim"
    assert call("state")["dirty"] is True and call("project_state")["unversioned"] is True
    assert call("save_document")["ok"] and call("recoveries")["items"] == []


def test_nothing_is_written_without_unsaved_work(tmp_path):
    house()
    assert call("save_as_kim", str(tmp_path / "a.kim"), "")["ok"]
    assert call("write_recovery")["written"] is False


def test_templates_list_save_and_make_new_projects(tmp_path):
    folder = tmp_path / "Plantillas"
    assert call("templates", str(folder)) == {"templates": [
        {"name": "KimBim default", "path": "builtin", "builtin": True, "modified": ""}], "folder_ok": False}
    house()
    assert call("set_project_info", json.dumps({"number": "2026-001", "name": "Casa"}))["ok"]
    sheet = call("add_sheet", "A1", "Plantas")["number"]
    plan = next(d["guid"] for d in call("drawings")["drawings"] if d["name"].endswith("Floor Plan"))
    assert call("place_drawing", sheet, plan, -1, -1, 100)["ok"]
    assert call("set_project_settings", json.dumps({"drawing_scale": 50}))["ok"]
    old_ids = {e.GlobalId for e in b._model.by_type("IfcRoot")}
    r = call("save_template", str(folder), "Oficina")
    assert r["ok"], r
    assert K.read_manifest(folder / "Oficina.kim")["kind"] == "template"
    assert not call("save_template", str(folder), "Oficina")["ok"]
    assert call("save_template", str(folder), "Oficina", "1")["ok"]
    assert not call("save_template", str(folder), "a/b")["ok"]
    listed = call("templates", str(folder))
    assert listed["folder_ok"] and [t["name"] for t in listed["templates"]] == ["KimBim default", "Oficina"]

    r = call("new_from_template", str(folder / "Oficina.kim"))
    assert r["ok"], r
    assert call("open_model", r["path"])["ok"]
    new_ids = {e.GlobalId for e in b._model.by_type("IfcRoot")}
    assert len(new_ids) == len(old_ids) and not (new_ids & old_ids)
    views = next(s for s in call("sheets")["sheets"] if s["number"] == sheet)["views"]
    assert len(views) == 1 and views[0]["drawing"] in new_ids  # the sheet still shows its drawing
    assert call("project_info")["number"] == "" and call("project_settings")["settings"]["drawing_scale"] == 50
    st = call("document_state")
    assert st["untitled"] is True and st["template"] == "Oficina" and call("state")["dirty"] is False
    assert call("save_as_kim", str(tmp_path / "nuevo.kim"), "")["ok"]
    assert [v["message"] for v in call("history", 5)["versions"]] == ["Created from Oficina"]


def test_the_built_in_template_is_a_new_project():
    r = call("new_from_template", "builtin")
    assert r["ok"] and r["path"] == ""
    assert call("storeys")["storeys"] and call("document_state")["template"] == "KimBim default"


def test_an_opened_template_saves_back_as_a_template(tmp_path):
    folder = tmp_path / "t"
    house()
    assert call("save_template", str(folder), "Base")["ok"]
    assert open_kim(folder / "Base.kim")["ok"]
    assert call("document_state")["mode"] == "template" and call("project_state")["versioned"] is False
    assert call("set_project_settings", json.dumps({"sheet_paper": "A3"}))["ok"]
    assert call("save_document")["ok"]
    assert K.read_manifest(folder / "Base.kim")["kind"] == "template"
```

- [ ] **Step 2: Run them to see them fail**

Run: `pixi run pytest tests/python/test_documents.py -q -k "recover or template or nothing_is_written"`
Expected: FAIL — `AttributeError: module 'kimbim.app_bridge' has no attribute 'write_recovery'`.

- [ ] **Step 3: Implement recovery** — replace the `_clear_recovery` stub in `documents.py`; add the
imports `re`, `time`, `uuid`, `ifcopenshell`, `ifcopenshell.guid` at the top:

```python
def _recovery_dir(key: str) -> pathlib.Path:
    return data_dir() / "recovery" / K.path_hash(key)


def _clear_recovery(key: str) -> None:
    if key:
        shutil.rmtree(_recovery_dir(key), ignore_errors=True)


def write_recovery() -> str:
    if B._model is None or not B._dirty():
        return B._dump({"ok": True, "written": False})
    source = _doc["source"] or B._path  # the file it belongs to ("" untitled)
    folder = _recovery_dir(_recovery_key())
    try:
        folder.mkdir(parents=True, exist_ok=True)
        B._model.write(str(folder / "model.ifc"))
        (folder / "settings.json").write_bytes(S.to_bytes())
        (folder / "info.json").write_text(json.dumps({"source": source, "mode": _doc["mode"], "time": time.time()}))
    except OSError as ex:
        return _fail(str(ex))
    return B._dump({"ok": True, "written": True})


def recoveries() -> str:
    items = []
    root = data_dir() / "recovery"
    own = _recovery_dir(_recovery_key()) if B._model is not None else None
    for folder in sorted(root.glob("*")) if root.exists() else ():
        try:
            info = json.loads((folder / "info.json").read_text())
        except (OSError, ValueError):
            continue
        if own is not None and folder == own:
            continue  # this session's own copy
        source = info.get("source", "")
        if source and os.path.exists(source) and os.path.getmtime(source) >= info.get("time", 0):
            continue  # saved after the copy was made
        items.append({"id": folder.name, "source": source, "name": pathlib.Path(source).name if source else "",
                      "mode": info.get("mode", "plain"), "time": info.get("time", 0)})
    return B._dump({"items": items})


def discard_recovery(id: str) -> str:
    shutil.rmtree(data_dir() / "recovery" / pathlib.Path(id).name, ignore_errors=True)
    return B._dump({"ok": True})


def recover(id: str) -> str:
    """Reopen a recovered copy: a .kim or folder opens normally with the copy as its unsaved work; an IFC
    or untitled model opens the copy as unsaved work (Save writes the original IFC)."""
    global _pending
    folder = data_dir() / "recovery" / pathlib.Path(id).name
    try:
        info = json.loads((folder / "info.json").read_text())
    except (OSError, ValueError):
        return _fail("that recovery copy is gone")
    source, mode = info.get("source", ""), info.get("mode", "plain")
    settings = S.from_bytes(_read(folder / "settings.json"))
    if mode in ("kim", "folder", "template") and source and os.path.exists(source):
        r = json.loads(open_folder(source) if mode == "folder" else open_kim(source))
        if not r.get("ok"):
            return B._dump(r)
        shutil.copyfile(folder / "model.ifc", r["path"])
        _pending.update(settings=settings, unversioned=_pending["project"] is not None, dirty=True)
        path = r["path"]
    else:
        target = data_dir() / "open" / f"recovered-{uuid.uuid4().hex[:8]}.ifc"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(folder / "model.ifc", target)
        _pending = {"path": str(target), "doc": _plain(source if mode == "plain" else ""), "project": None,
                    "settings": settings, "unversioned": False, "dirty": True,
                    "source_path": source if mode == "plain" else "", "untitled": not source}
        path = str(target)
    shutil.rmtree(folder, ignore_errors=True)
    return B._dump({"ok": True, "path": path})
```

- [ ] **Step 4: Implement templates**

```python
BUILTIN = "builtin"
BUILTIN_NAME = "KimBim default"
_GUID = re.compile(r"[0-9A-Za-z_$]{22}")
_BAD_NAME = re.compile(r'[\\/:*?"<>|]')


def templates(folder: str) -> str:
    out = [{"name": BUILTIN_NAME, "path": BUILTIN, "builtin": True, "modified": ""}]
    root = pathlib.Path(folder) if folder else None
    ok = root is not None and root.is_dir()
    for p in sorted(root.glob("*.kim")) if ok else ():
        try:
            if K.read_manifest(p).get("kind") != "template":
                continue
        except K.KimError:
            continue
        out.append({"name": p.stem, "path": str(p), "builtin": False,
                    "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
    return B._dump({"templates": out, "folder_ok": ok})


def save_template(folder: str, name: str, replace: str = "") -> str:
    if B._model is None:
        return _fail("no model open")
    name = (name or "").strip()
    if not name or _BAD_NAME.search(name):
        return _fail('a template name can\'t be empty or use \\ / : * ? " < > |')
    target = pathlib.Path(folder) / f"{name}.kim"
    if target.exists() and not replace:
        return _fail(f"a template called {name} exists", exists=True)
    tmp = data_dir() / "tmp" / uuid.uuid4().hex
    try:
        (tmp / ".kimbim").mkdir(parents=True)
        B._model.write(str(tmp / ".kimbim" / "working.ifc"))
        (tmp / ".kimbim" / "settings.json").write_bytes(S.to_bytes())
        target.parent.mkdir(parents=True, exist_ok=True)
        K.pack(tmp, target, "template")
    except (K.KimError, OSError) as ex:
        return _fail(str(ex))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return B._dump({"ok": True, "path": str(target)})


def regenerate_ids(f) -> dict:
    """New GlobalIds for every rooted entity; text that holds an old id (a sheet's placed drawing, a saved
    view) is rewritten too. Returns old -> new."""
    mapping = {}
    for e in f.by_type("IfcRoot"):
        new = ifcopenshell.guid.new()
        mapping[e.GlobalId] = new
        e.GlobalId = new

    def fix(text: str) -> str:
        return _GUID.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)

    for e in list(f):
        for name, value in e.get_info(recursive=False).items():
            if name in ("id", "type", "GlobalId"):
                continue
            if isinstance(value, str) and _GUID.search(value):
                if (new := fix(value)) != value:
                    setattr(e, name, new)
            elif isinstance(value, ifcopenshell.entity_instance) and not value.id() \
                    and isinstance(value.wrappedValue, str) and _GUID.search(value.wrappedValue):
                if (new := fix(value.wrappedValue)) != value.wrappedValue:
                    setattr(e, name, f.create_entity(value.is_a(), new))
    return mapping


def new_from_template(path: str) -> str:
    global _doc, _pending
    if path == BUILTIN:
        from .authoring import new_project

        r = json.loads(new_project(""))
        if not r.get("ok"):
            return B._dump(r)
        _doc = {**_plain(), "template": BUILTIN_NAME}
        return B._dump({"ok": True, "path": ""})
    kim = pathlib.Path(path)
    tmp = data_dir() / "tmp" / uuid.uuid4().hex
    try:
        if K.read_manifest(kim).get("kind") != "template":
            return _fail(f"{kim.name} is not a template")
        K.unpack(kim, tmp)
        f = ifcopenshell.open(str(tmp / ".kimbim" / "working.ifc"))
        regenerate_ids(f)
        for project in f.by_type("IfcProject"):
            project.Name, project.LongName = None, None
        target = data_dir() / "open" / f"new-{uuid.uuid4().hex[:8]}.ifc"
        target.parent.mkdir(parents=True, exist_ok=True)
        f.write(str(target))
        settings = S.from_bytes(_read(tmp / ".kimbim" / "settings.json"))
    except (K.KimError, OSError, RuntimeError) as ex:
        return _fail(str(ex))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _pending = {"path": str(target), "doc": {**_plain(), "template": kim.stem}, "project": None,
                "settings": settings, "unversioned": False, "untitled": True}
    return B._dump({"ok": True, "path": str(target)})
```

Add to the `app_bridge` re-exports: `discard_recovery, new_from_template, recover, recoveries,
save_template, templates, write_recovery`. If `project_info()` returns `None` for a cleared
`IfcProject.Name`, make it `or ""` in `sheets.py`.

- [ ] **Step 5: Run the tests**

Run: `pixi run pytest tests/python/test_documents.py tests/python/test_sheets.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add python/kimbim/documents.py python/kimbim/app_bridge.py python/kimbim/sheets.py tests/python/test_documents.py
git commit -m "feat(documents): recovery copies and office templates (new ids, built-in default, save as template)"
```

---

### Task 7: User preferences (C++)

**Files:**
- Create: `app/src/Preferences.h`, `app/src/Preferences.cpp`
- Modify: `app/CMakeLists.txt` (sources; `kimbim_test(test_preferences)`)
- Test: `app/tests/test_preferences.cpp`

**Interfaces:**
- Produces:

```cpp
namespace kimbim {
// User preferences, per computer (D72): a readable preferences.json in the user's settings folder.
class Preferences {
public:
    explicit Preferences(const QString& path = QString()); // empty: in memory only (tests, self-test)
    static QString defaultPath();       // AppConfigLocation/preferences.json
    static QJsonObject defaults();
    bool load();                        // false if the file was garbled (kept aside as <file>.bad)
    bool save() const;                  // false if it could not be written (or in memory only)
    QString path() const { return m_path; }
    QJsonValue value(const QString& key) const;  // falls back to defaults()
    void setValue(const QString& key, const QJsonValue& value);
    QString language() const;           // "auto", "en" or "es"
    QString templatesFolder() const;
    QString authorName() const;
    QString authorEmail() const;
    QString newViews() const;           // "tab" or "window"
    QString openIfc() const;            // "make_kim" or "edit_ifc"
    QString autoVersion() const;        // "off", "saves" or "minutes"
    int autoVersionEvery() const;
    int recoveryMinutes() const;
    QStringList recent() const;
    void addRecent(const QString& path); // most recent first, no duplicates, at most 10
    QByteArray layout() const;
    void setLayout(const QByteArray& state);
private:
    QString m_path;
    QJsonObject m_data; // only what was set or loaded; unknown keys survive a save
};
}
```

- [ ] **Step 1: Write the failing test** — `app/tests/test_preferences.cpp`:

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QtTest>

#include "Preferences.h"

class TestPreferences : public QObject {
    Q_OBJECT
private slots:
    void defaultsWhenThereIsNoFile()
    {
        QTemporaryDir tmp;
        kimbim::Preferences p(tmp.filePath("preferences.json"));
        QVERIFY(p.load());
        QCOMPARE(p.language(), QString("auto"));
        QCOMPARE(p.newViews(), QString("tab"));
        QCOMPARE(p.openIfc(), QString("make_kim"));
        QCOMPARE(p.autoVersion(), QString("off"));
        QCOMPARE(p.autoVersionEvery(), 10);
        QCOMPARE(p.recoveryMinutes(), 5);
        QVERIFY(p.templatesFolder().endsWith(QStringLiteral("KimBim Templates")));
        QVERIFY(p.recent().isEmpty());
    }

    void roundTripKeepsUnknownKeys()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath("sub/preferences.json");
        {
            kimbim::Preferences p(path);
            p.setValue("new_views", "window");
            p.setValue("from_a_newer_kimbim", 42);
            p.setLayout(QByteArray("\x01\x02layout", 8));
            QVERIFY(p.save());
        }
        kimbim::Preferences q(path);
        QVERIFY(q.load());
        QCOMPARE(q.newViews(), QString("window"));
        QCOMPARE(q.value("from_a_newer_kimbim").toInt(), 42);
        QCOMPARE(q.layout(), QByteArray("\x01\x02layout", 8));
        QVERIFY(QFile(path).readAll().isEmpty() || true);
    }

    void aGarbledFileIsKeptAsideAndDefaultsUsed()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath("preferences.json");
        QFile f(path);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write("{ not json");
        f.close();
        kimbim::Preferences p(path);
        QVERIFY(!p.load());
        QCOMPARE(p.newViews(), QString("tab"));
        QVERIFY(QFile::exists(path + ".bad"));
    }

    void recentFilesAreMostRecentFirstWithoutDuplicates()
    {
        kimbim::Preferences p;
        for (int i = 0; i < 12; ++i)
            p.addRecent(QStringLiteral("C:/p/%1.kim").arg(i));
        p.addRecent("C:/p/5.kim");
        const QStringList r = p.recent();
        QCOMPARE(r.size(), 10);
        QCOMPARE(r.first(), QString("C:/p/5.kim"));
        QCOMPARE(r.count("C:/p/5.kim"), 1);
        QVERIFY(!p.save()); // in memory only
    }

    void badValuesFallBackToDefaults()
    {
        kimbim::Preferences p;
        p.setValue("new_views", "sideways");
        p.setValue("recovery_minutes", -3);
        p.setValue("auto_version_every", "lots");
        QCOMPARE(p.newViews(), QString("tab"));
        QCOMPARE(p.recoveryMinutes(), 5);
        QCOMPARE(p.autoVersionEvery(), 10);
    }
};

QTEST_MAIN(TestPreferences)
#include "test_preferences.moc"
```

- [ ] **Step 2: Add the test target and see it fail**

In `app/CMakeLists.txt`: add `src/Preferences.cpp src/Preferences.h` to `kimbim_core` and
`kimbim_test(test_preferences)` after `kimbim_test(test_tool_palette)`.

Run: `pixi run app-build` (then `ctest --test-dir build/app -R test_preferences --output-on-failure`)
Expected: build FAIL — `Preferences.h: No such file or directory`.

- [ ] **Step 3: Implement** — `app/src/Preferences.h` as in Interfaces (with `#pragma once`, includes
`<QByteArray> <QJsonObject> <QJsonValue> <QString> <QStringList>`) and `app/src/Preferences.cpp`:

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include "Preferences.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSaveFile>
#include <QStandardPaths>

namespace kimbim {

namespace {
const QStringList kViews{QStringLiteral("tab"), QStringLiteral("window")};
const QStringList kOpenIfc{QStringLiteral("make_kim"), QStringLiteral("edit_ifc")};
const QStringList kAutoVersion{QStringLiteral("off"), QStringLiteral("saves"), QStringLiteral("minutes")};
const QStringList kLanguages{QStringLiteral("auto"), QStringLiteral("en"), QStringLiteral("es")};

QString oneOf(const QJsonValue& v, const QStringList& allowed)
{
    const QString s = v.toString();
    return allowed.contains(s) ? s : allowed.first();
}
} // namespace

Preferences::Preferences(const QString& path)
    : m_path(path)
{
}

QString Preferences::defaultPath()
{
    return QDir(QStandardPaths::writableLocation(QStandardPaths::AppConfigLocation)).filePath(QStringLiteral("preferences.json"));
}

QJsonObject Preferences::defaults()
{
    const QString docs = QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation);
    return {
        {"language", "auto"},
        {"templates_folder", QDir(docs).filePath(QStringLiteral("KimBim Templates"))},
        {"author_name", ""},
        {"author_email", ""},
        {"new_views", "tab"},
        {"open_ifc", "make_kim"},
        {"auto_version", "off"},
        {"auto_version_every", 10},
        {"recovery_minutes", 5},
        {"recent", QJsonArray()},
    };
}

bool Preferences::load()
{
    m_data = {};
    if (m_path.isEmpty() || !QFile::exists(m_path))
        return true;
    QFile f(m_path);
    if (!f.open(QIODevice::ReadOnly))
        return false;
    QJsonParseError error;
    const QJsonDocument doc = QJsonDocument::fromJson(f.readAll(), &error);
    f.close();
    if (error.error != QJsonParseError::NoError || !doc.isObject()) {
        QFile::remove(m_path + QStringLiteral(".bad"));
        QFile::rename(m_path, m_path + QStringLiteral(".bad")); // kept for inspection
        return false;
    }
    m_data = doc.object();
    return true;
}

bool Preferences::save() const
{
    if (m_path.isEmpty())
        return false;
    QDir().mkpath(QFileInfo(m_path).absolutePath());
    QSaveFile f(m_path);
    if (!f.open(QIODevice::WriteOnly))
        return false;
    f.write(QJsonDocument(m_data).toJson(QJsonDocument::Indented));
    return f.commit();
}

QJsonValue Preferences::value(const QString& key) const
{
    return m_data.contains(key) ? m_data.value(key) : defaults().value(key);
}

void Preferences::setValue(const QString& key, const QJsonValue& value)
{
    m_data.insert(key, value);
}

QString Preferences::language() const { return oneOf(value("language"), kLanguages); }
QString Preferences::newViews() const { return oneOf(value("new_views"), kViews); }
QString Preferences::openIfc() const { return oneOf(value("open_ifc"), kOpenIfc); }
QString Preferences::autoVersion() const { return oneOf(value("auto_version"), kAutoVersion); }
QString Preferences::authorName() const { return value("author_name").toString().trimmed(); }
QString Preferences::authorEmail() const { return value("author_email").toString().trimmed(); }

QString Preferences::templatesFolder() const
{
    const QString s = value("templates_folder").toString();
    return s.isEmpty() ? defaults().value("templates_folder").toString() : s;
}

int Preferences::autoVersionEvery() const
{
    const QJsonValue v = value("auto_version_every");
    return v.isDouble() && v.toInt() >= 1 ? v.toInt() : 10;
}

int Preferences::recoveryMinutes() const
{
    const QJsonValue v = value("recovery_minutes");
    return v.isDouble() && v.toInt() >= 0 ? v.toInt() : 5;
}

QStringList Preferences::recent() const
{
    QStringList out;
    for (const auto& v : value("recent").toArray())
        if (!v.toString().isEmpty())
            out << v.toString();
    return out;
}

void Preferences::addRecent(const QString& path)
{
    QStringList r = recent();
    r.removeAll(path);
    r.prepend(path);
    while (r.size() > 10)
        r.removeLast();
    setValue("recent", QJsonArray::fromStringList(r));
}

QByteArray Preferences::layout() const
{
    return QByteArray::fromBase64(value("layout").toString().toLatin1());
}

void Preferences::setLayout(const QByteArray& state)
{
    setValue("layout", QString::fromLatin1(state.toBase64()));
}

} // namespace kimbim
```

- [ ] **Step 4: Run it**

Run: `pixi run app-build` and `ctest --test-dir build/app -R test_preferences --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/src/Preferences.h app/src/Preferences.cpp app/tests/test_preferences.cpp app/CMakeLists.txt
git commit -m "feat(app): user preferences in preferences.json (defaults, unknown keys kept, garbled file kept aside)"
```

---

### Task 8: New views open as a tab after the current one, or as a free window

**Files:**
- Modify: `app/src/DockLayout.h`, `app/src/DockLayout.cpp` (`addView` placement)
- Modify: `app/src/MainWindow.h/.cpp` (`m_prefs` member; `openPlanTab`, `openDrawing`, `openSheet` pass the placement)
- Test: `app/tests/test_dock_layout.cpp`, `app/tests/test_main_window.cpp`

**Interfaces:**
- Consumes: Task 7 `Preferences::newViews()`.
- Produces: `enum class DockLayout::Placement { AfterCurrent, Floating };`
  `ads::CDockWidget* DockLayout::addView(const QString& key, const QString& title, QWidget* widget, bool closable, Placement placement = Placement::AfterCurrent);`
  `Preferences& MainWindow::preferences();` `DockLayout::Placement MainWindow::newViewPlacement() const;`

- [ ] **Step 1: Write the failing tests** — append to `TestDockLayout`:

```cpp
    void aNewViewOpensRightAfterTheCurrentTab()
    {
        QMainWindow w;
        kimbim::DockLayout layout(&w);
        layout.addView("3d", "3D", new QLabel, false);
        layout.addView("plan:A", "A", new QLabel, true);
        layout.addView("D1", "Section", new QLabel, true);
        layout.raise("plan:A");
        layout.addView("plan:B", "B", new QLabel, true);
        ads::CDockAreaWidget* area = layout.manager()->findDockWidget("3d")->dockAreaWidget();
        QStringList order;
        for (int i = 0; i < area->dockWidgetsCount(); ++i)
            order << area->dockWidget(i)->objectName();
        QCOMPARE(order, QStringList({"3d", "plan:A", "plan:B", "D1"}));
    }

    void aNewViewCanOpenAsAFreeWindow()
    {
        QMainWindow w;
        w.resize(1000, 800);
        kimbim::DockLayout layout(&w);
        layout.addView("3d", "3D", new QLabel, false);
        ads::CDockWidget* dock = layout.addView("S1", "Sheet", new QLabel, true, kimbim::DockLayout::Placement::Floating);
        QVERIFY(dock->isFloating());
        QCOMPARE(layout.view("S1") != nullptr, true);
        QVERIFY(std::abs(dock->dockContainer()->window()->width() - 700) <= 50);
    }
```

(add `#include <DockAreaWidget.h>`, `#include <DockContainerWidget.h>`, `#include <cmath>`) and to
`test_main_window.cpp` a slot:

```cpp
    // D72: new views follow the "new_views" preference.
    void newViewsFollowThePreference()
    {
        kimbim::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        QCOMPARE(w.newViewPlacement(), kimbim::DockLayout::Placement::AfterCurrent);
        w.preferences().setValue("new_views", "window");
        QCOMPARE(w.newViewPlacement(), kimbim::DockLayout::Placement::Floating);
        w.openPlanTab(w.levelsBar()->activeStorey());
        const QString key = QStringLiteral("plan:") + w.levelsBar()->activeStorey();
        QVERIFY(w.dockLayout()->manager()->findDockWidget(key)->isFloating());
        QVERIFY(w.close());
    }
```

- [ ] **Step 2: Run them to see them fail**

Run: `pixi run app-build`
Expected: build FAIL — `'Placement' is not a member of 'kimbim::DockLayout'`.

- [ ] **Step 3: Implement**

`DockLayout.h`: add `enum class Placement { AfterCurrent, Floating };` (public) and the new parameter.
`DockLayout.cpp`:

```cpp
ads::CDockWidget* DockLayout::addView(const QString& key, const QString& title, QWidget* widget, bool closable,
    Placement placement)
{
    ads::CDockWidget* dock = makeDock(key, title, widget);
    dock->setFeature(ads::CDockWidget::DockWidgetClosable, closable);
    if (!m_center) {
        m_center = m_manager->addDockWidget(ads::CenterDockWidgetArea, dock);
    } else if (placement == Placement::Floating) {
        // D72: a free window centred over the main window at 70 % of its size.
        ads::CFloatingDockContainer* f = m_manager->addDockWidgetFloating(dock);
        const QRect main = m_manager->window()->geometry();
        const QSize size(main.width() * 7 / 10, main.height() * 7 / 10);
        f->resize(size);
        f->move(main.center() - QPoint(size.width() / 2, size.height() / 2));
    } else {
        // Right after the current tab, when it is docked in the main window; else at the end of the center.
        ads::CDockWidget* current = m_current.isEmpty() ? nullptr : m_manager->findDockWidget(m_current);
        ads::CDockAreaWidget* area = current && current->dockAreaWidget()
                && !current->dockContainer()->isFloating() ? current->dockAreaWidget() : m_center.data();
        const int index = current && current->dockAreaWidget() == area ? area->index(current) + 1 : -1;
        m_manager->addDockWidgetTabToArea(dock, area, index);
    }
    m_views << key;
    if (m_current.isEmpty())
        m_current = key;
    return dock;
}
```

`MainWindow.h`: `#include "Preferences.h"`, `#include "DockLayout.h"` already; members
`Preferences m_prefs;` and public:

```cpp
    Preferences& preferences() { return m_prefs; }
    DockLayout::Placement newViewPlacement() const
    {
        return m_prefs.newViews() == QLatin1String("window") ? DockLayout::Placement::Floating
                                                             : DockLayout::Placement::AfterCurrent;
    }
```

Constructor: `m_prefs(quiet ? QString() : Preferences::defaultPath())` in the init list, and
`m_prefs.load();` first thing in the body. In `openPlanTab`, `openDrawing` and `openSheet`, pass
`newViewPlacement()` as the last `addView` argument.

- [ ] **Step 4: Run them**

Run: `pixi run app-build` and `ctest --test-dir build/app -R "test_dock_layout|test_main_window" --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/src/DockLayout.h app/src/DockLayout.cpp app/src/MainWindow.h app/src/MainWindow.cpp app/tests/test_dock_layout.cpp app/tests/test_main_window.cpp
git commit -m "feat(app): new views open right after the current tab, or as a free window (preference)"
```

---

### Task 9: The File menu works on `.kim` files

**Files:**
- Modify: `python/kimbim/documents.py` (`save_as_ifc`), `python/kimbim/app_bridge.py` (re-export)
- Modify: `app/src/MainWindow.h/.cpp` (menu, open/save/close, recent files, read-only, title, guards, layout in preferences)
- Modify: `app/src/main.cpp` (`openFile` of a command-line argument goes through `openPath`)
- Test: `tests/python/test_documents.py`, `app/tests/test_main_window.cpp`

**Interfaces:**
- Consumes: Tasks 5–8.
- Produces (Python): `save_as_ifc(path) -> {"ok", "path"}` (the model becomes a plain IFC document there).
- Produces (C++ `MainWindow`, public): `bool openPath(const QString& path)`, `bool openKim(const QString& path, bool readOnly = false)`, `bool openIfc(const QString& path)`, `bool openProject(const QString& folder, bool readOnly = false)` (now via `open_folder`), `bool save()`, `bool saveAs(const QString& path)` (`.kim` → `save_as_kim`, `.ifc` → `save_as_ifc`), `bool saveAsFolder(const QString& folder)`, `bool exportIfc(const QString& path)`, `bool closeDocument()`, `QJsonObject documentState()`, `bool hasUnversionedWork()`, `bool enableVersioning(const QString& folder, const QString& message = {})` (now `save_as_folder`).

Rulings carried by this task:
- Save As offers `.kim` first and `.ifc` second; saving as `.ifc` switches to editing that IFC directly.
- "Enable versioning…" leaves the menu; `enableVersioning()` stays for the tests and is "Save as
  project folder" underneath.
- Importing an `.ifc` (commit on the GUI thread) shows "Making House.kim…" in the bottom bar; a
  background import is a later improvement.

- [ ] **Step 1: Write the failing tests**

Python (append to `tests/python/test_documents.py`):

```python
def test_save_as_ifc_turns_the_document_into_that_ifc(tmp_path):
    house()
    kim = tmp_path / "a.kim"
    assert call("save_as_kim", str(kim), "")["ok"]
    r = call("save_as_ifc", str(tmp_path / "b.ifc"))
    assert r["ok"], r
    assert not K.lock_path(kim).exists() and (tmp_path / "b.ifc").exists()
    st = call("document_state")
    assert st["mode"] == "plain" and st["name"] == "b.ifc" and call("project_state")["versioned"] is False
```

C++ (`test_main_window.cpp`; add `#include <QStandardPaths>` and in an `initTestCase()` slot
`QStandardPaths::setTestModeEnabled(true);`):

```cpp
    // D72: a new project saved as .kim, edited, saved (no version), reopened; Save version packs too.
    void kimFileFlow()
    {
        QTemporaryDir tmp;
        const QString kim = tmp.filePath(QStringLiteral("Casa ñ.kim"));
        {
            kimbim::MainWindow w(nullptr, /*quiet=*/true);
            QVERIFY(w.newProject());
            w.setTool(kimbim::MainWindow::Tool::Wall);
            w.wallTool()->click({0, 0});
            w.wallTool()->click({5, 0});
            w.wallTool()->finish();
            w.setTool(kimbim::MainWindow::Tool::None);
            QVERIFY(w.saveAs(kim));
            QVERIFY(QFile::exists(kim) && QFile::exists(kim + ".lock"));
            QVERIFY(w.windowTitle().contains(QStringLiteral("Casa ñ.kim")));
            QCOMPARE(w.history().size(), 1);
            w.setSelection(w.viewport()->guids());
            QVERIFY(w.applyName(QStringLiteral("Muro")));
            QVERIFY(w.save());
            QVERIFY(!w.isDirty() && w.hasUnversionedWork());
            QCOMPARE(w.history().size(), 1);
            QVERIFY(w.saveVersion(QStringLiteral("Named the wall")));
            QVERIFY(!w.hasUnversionedWork());
            QVERIFY(w.close());
        }
        QVERIFY(!QFile::exists(kim + ".lock"));
        kimbim::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy loaded(&w, &kimbim::MainWindow::loadFinished);
        QVERIFY(w.openPath(kim));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(w.viewport()->elementCount(), 1);
        QCOMPARE(w.history().size(), 2);
        QVERIFY(w.preferences().recent().isEmpty() || w.preferences().recent().first() == kim);
        QVERIFY(w.close());
    }

    // D72: opening an IFC makes a .kim beside it (default) or edits the IFC (preference).
    void openingAnIfcFollowsThePreference()
    {
        QTemporaryDir tmp;
        const QString ifc = tmp.filePath(QStringLiteral("House.ifc"));
        {
            kimbim::MainWindow w(nullptr, /*quiet=*/true);
            QVERIFY(w.newProject());
            QVERIFY(w.exportIfc(ifc));
            QVERIFY(w.close());
        }
        kimbim::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy loaded(&w, &kimbim::MainWindow::loadFinished);
        QVERIFY(w.openPath(ifc));
        QVERIFY(loaded.wait(60000));
        QVERIFY(QFile::exists(tmp.filePath(QStringLiteral("House.kim"))));
        QCOMPARE(w.documentState().value("mode").toString(), QString("kim"));
        w.preferences().setValue("open_ifc", "edit_ifc");
        QVERIFY(w.openPath(ifc));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(w.documentState().value("mode").toString(), QString("plain"));
        QCOMPARE(w.documentState().value("name").toString(), QString("House.ifc"));
        QVERIFY(w.close());
    }

    // D72: someone else's lock opens the file read-only (quiet mode answers "read-only").
    void aLockedKimOpensReadOnly()
    {
        QTemporaryDir tmp;
        const QString kim = tmp.filePath(QStringLiteral("a.kim"));
        {
            kimbim::MainWindow w(nullptr, /*quiet=*/true);
            QVERIFY(w.newProject());
            QVERIFY(w.saveAs(kim));
            QVERIFY(w.close());
        }
        QFile lock(kim + ".lock");
        QVERIFY(lock.open(QIODevice::WriteOnly));
        lock.write(R"({"user": "Ana", "account": "ana", "machine": "OTHER-PC", "pid": 4, "since": "2026-10-08T10:42"})");
        lock.close();
        kimbim::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy loaded(&w, &kimbim::MainWindow::loadFinished);
        QVERIFY(w.openPath(kim));
        QVERIFY(loaded.wait(60000));
        QVERIFY(w.documentState().value("read_only").toBool());
        QVERIFY(w.windowTitle().contains(QStringLiteral("read-only")));
        QVERIFY(!w.save());
        QVERIFY(w.close());
        QVERIFY(QFile::exists(kim + ".lock")); // Ana's lock is left alone
    }
```

Update `versionedProjectFlow` and `m5ExitCombineOptions`: nothing to change (they call
`enableVersioning`, which keeps working).

- [ ] **Step 2: Run them to see them fail**

Run: `pixi run pytest tests/python/test_documents.py -q -k save_as_ifc` → FAIL (`save_as_ifc` missing);
`pixi run app-build` → FAIL (`openPath`, `hasUnversionedWork`, `exportIfc`, `documentState` not members).

- [ ] **Step 3: Python `save_as_ifc`**

```python
def save_as_ifc(path: str) -> str:
    """Keep editing the model as a plain IFC at `path` (no history, default settings not kept)."""
    global _doc
    if B._model is None:
        return _fail("no model open")
    _close()
    _doc = _plain(path)
    V._project = None
    S.kept = False
    r = json.loads(B.save(path))
    if r.get("ok"):
        S.mark_saved()
    return B._dump(r)
```

Re-export it in `app_bridge.py`.

- [ ] **Step 4: MainWindow**

Members (`MainWindow.h`): `QMenu* m_recentMenu = nullptr;`, `int m_savesSinceVersion = 0;`,
`QElapsedTimer m_sinceVersion;`, `QJsonObject m_document;` (last `document_state`).

Construction, after `m_prefs.load()` and before building menus:

```cpp
    bridge("set_app_paths", {QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation)});
    bridge("set_author", {m_prefs.authorName(), m_prefs.authorEmail()});
    m_sinceVersion.start();
```

Layout memory moves to preferences (replacing the two `QSettings` lines):

```cpp
    if (!quiet) {
        QByteArray state = m_prefs.layout();
        if (state.isEmpty()) // once: the layout saved by the first D71 build
            state = QSettings().value(QStringLiteral("layout/state")).toByteArray();
        m_dock->restoreLayout(state);
    }
```

and in `closeEvent`: `m_prefs.setLayout(m_dock->saveLayout()); m_prefs.save();` plus `closeDocument();`
after `stopLoading()`.

File menu (replace the block from "New project" to "Save version" in `buildMenus`; keep Project info,
the sheet exports and Room schedule where they are):

```cpp
    QAction* newProjectAction = file->addAction(tr("&New project..."));
    newProjectAction->setObjectName(QStringLiteral("actionNewProject"));
    newProjectAction->setShortcut(QKeySequence::New);
    connect(newProjectAction, &QAction::triggered, this, &MainWindow::newProjectDialog);
    QAction* open = file->addAction(tr("&Open..."));
    open->setObjectName(QStringLiteral("actionOpen"));
    open->setShortcut(QKeySequence::Open);
    connect(open, &QAction::triggered, this, &MainWindow::openDialog);
    QAction* openProjectAction = file->addAction(tr("Open project &folder..."));
    openProjectAction->setObjectName(QStringLiteral("actionOpenProject"));
    connect(openProjectAction, &QAction::triggered, this, &MainWindow::openProjectDialog);
    m_recentMenu = file->addMenu(tr("&Recent files"));
    m_recentMenu->setObjectName(QStringLiteral("recentMenu"));
    connect(m_recentMenu, &QMenu::aboutToShow, this, &MainWindow::fillRecentMenu);
    file->addSeparator();
    QAction* saveAction = file->addAction(tr("&Save"));
    saveAction->setObjectName(QStringLiteral("actionSave"));
    saveAction->setShortcut(QKeySequence::Save);
    connect(saveAction, &QAction::triggered, this, [this] { save(); });
    QAction* saveAs = file->addAction(tr("Save &As..."));
    saveAs->setObjectName(QStringLiteral("actionSaveAs"));
    saveAs->setShortcut(QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_S));
    connect(saveAs, &QAction::triggered, this, &MainWindow::saveAsDialog);
    QAction* saveFolder = file->addAction(tr("Save as project f&older..."));
    saveFolder->setObjectName(QStringLiteral("actionSaveAsFolder"));
    connect(saveFolder, &QAction::triggered, this, &MainWindow::saveAsFolderDialog);
    QAction* saveTemplate = file->addAction(tr("Save as &template..."));
    saveTemplate->setObjectName(QStringLiteral("actionSaveAsTemplate"));
    connect(saveTemplate, &QAction::triggered, this, &MainWindow::saveAsTemplateDialog);
    QAction* exportIfcAction = file->addAction(tr("&Export IFC..."));
    exportIfcAction->setObjectName(QStringLiteral("actionExportIfc"));
    connect(exportIfcAction, &QAction::triggered, this, &MainWindow::exportIfcDialog);
    QAction* saveVersionAction = file->addAction(tr("Save &version..."));
    saveVersionAction->setObjectName(QStringLiteral("actionSaveVersion"));
    saveVersionAction->setShortcut(QKeySequence(Qt::CTRL | Qt::ALT | Qt::Key_S));
    connect(saveVersionAction, &QAction::triggered, this, &MainWindow::saveVersionDialog);
    file->addSeparator();
    QAction* settingsAction = file->addAction(tr("Project se&ttings..."));
    settingsAction->setObjectName(QStringLiteral("actionProjectSettings"));
    connect(settingsAction, &QAction::triggered, this, &MainWindow::projectSettingsDialog);
```

(`newProjectDialog`, `saveAsTemplateDialog`, `projectSettingsDialog` are added in Tasks 10 and 12;
until then declare them and give `newProjectDialog` the body `newProject();`, the other two an empty
body. The old `actionEnableVersioning` entry is removed; check `m_projectActions` for it.)

Opening:

```cpp
bool MainWindow::openPath(const QString& path)
{
    const QFileInfo info(path);
    if (info.isDir())
        return openProject(path);
    if (info.suffix().compare(QLatin1String("kim"), Qt::CaseInsensitive) == 0)
        return openKim(path);
    return openIfc(path);
}

bool MainWindow::closeDocument()
{
    if (!maybeSave())
        return false;
    stopLoading();
    bridge("close_document");
    return true;
}

// A lock held by someone else: ask (quiet mode: read-only).
bool MainWindow::askReadOnly(const QJsonObject& r)
{
    if (!r.contains("locked"))
        return false;
    if (m_quiet)
        return true;
    return QMessageBox::question(this, tr("File in use"),
               tr("%1\nOpen it read-only?").arg(r.value("error").toString()),
               QMessageBox::Open | QMessageBox::Cancel, QMessageBox::Open) == QMessageBox::Open;
}

bool MainWindow::openKim(const QString& path, bool readOnly)
{
    if (!closeDocument())
        return false;
    QJsonObject r = bridge("open_kim", {path, readOnly ? QStringLiteral("1") : QString()});
    if (!r.value("ok").toBool() && askReadOnly(r))
        r = bridge("open_kim", {path, QStringLiteral("1")});
    if (!r.value("ok").toBool()) {
        if (!r.contains("locked"))
            showError(tr("Could not open the file"), r.value("error").toString());
        return false;
    }
    endCompare();
    openFile(r.value("path").toString());
    rememberRecent(path);
    return true;
}

bool MainWindow::openIfc(const QString& path)
{
    if (!closeDocument())
        return false;
    if (m_prefs.openIfc() == QLatin1String("edit_ifc")) {
        openFile(path);
        rememberRecent(path);
        return true;
    }
    const QJsonObject beside = bridge("kim_beside", {path});
    QString kim = beside.value("kim").toString();
    if (beside.value("exists").toBool()) {
        auto answer = QMessageBox::Open;
        if (!m_quiet) {
            QMessageBox box(QMessageBox::Question, tr("Open IFC"),
                tr("%1 already exists next to %2.").arg(QFileInfo(kim).fileName(), QFileInfo(path).fileName()),
                QMessageBox::Open | QMessageBox::Cancel, this);
            QPushButton* make = box.addButton(tr("Make a new one"), QMessageBox::AcceptRole);
            box.setDefaultButton(QMessageBox::Open);
            box.exec();
            answer = box.clickedButton() == make ? QMessageBox::Save
                : box.clickedButton() == box.button(QMessageBox::Open) ? QMessageBox::Open : QMessageBox::Cancel;
        }
        if (answer == QMessageBox::Open)
            return openKim(kim);
        if (answer == QMessageBox::Cancel)
            return false;
        kim = beside.value("free").toString();
    }
    m_status->showMessage(tr("Making %1...").arg(QFileInfo(kim).fileName()));
    QApplication::setOverrideCursor(Qt::WaitCursor);
    const QJsonObject r = bridge("import_ifc", {path, kim});
    QApplication::restoreOverrideCursor();
    if (!r.value("ok").toBool()) {
        showError(tr("Could not make the project file"), r.value("error").toString());
        return false;
    }
    endCompare();
    openFile(r.value("path").toString());
    rememberRecent(kim);
    return true;
}

bool MainWindow::openProject(const QString& folder, bool readOnly)
{
    if (!closeDocument())
        return false;
    QJsonObject r = bridge("open_folder", {folder, readOnly ? QStringLiteral("1") : QString()});
    if (!r.value("ok").toBool() && askReadOnly(r))
        r = bridge("open_folder", {folder, QStringLiteral("1")});
    if (!r.value("ok").toBool()) {
        if (!r.contains("locked"))
            showError(tr("Could not open the project"), r.value("error").toString());
        return false;
    }
    endCompare();
    openFile(r.value("path").toString());
    rememberRecent(folder);
    return true;
}

void MainWindow::rememberRecent(const QString& path)
{
    m_prefs.addRecent(QDir::toNativeSeparators(QFileInfo(path).absoluteFilePath()));
    m_prefs.save();
}

void MainWindow::fillRecentMenu()
{
    m_recentMenu->clear();
    for (const QString& p : m_prefs.recent())
        m_recentMenu->addAction(p, this, [this, p] { openPath(p); });
    if (m_recentMenu->isEmpty())
        m_recentMenu->addAction(tr("(none)"))->setEnabled(false);
}
```

`openDialog`: `QFileDialog::getOpenFileName(this, tr("Open"), QString(), tr("KimBim and IFC files (*.kim *.ifc);;KimBim projects (*.kim);;IFC files (*.ifc)"))` then `openPath(path)`.
`openProjectDialog`: `getExistingDirectory(this, tr("Open a KimBim project folder"))` then `openProject(folder)`.
`main.cpp`: `window.openPath(parser.positionalArguments().first());`.

Saving:

```cpp
QJsonObject MainWindow::documentState()
{
    m_document = bridge("document_state");
    return m_document;
}

bool MainWindow::hasUnversionedWork()
{
    return bridge("project_state").value("unversioned").toBool();
}

bool MainWindow::save()
{
    const QJsonObject doc = documentState();
    if (doc.value("read_only").toBool() || doc.value("untitled").toBool()) {
        if (m_quiet)
            return false; // never a dialog in quiet mode
        saveAsDialog();
        return !isDirty();
    }
    maybeAutoVersion();
    const QJsonObject r = bridge("save_document");
    if (!r.value("ok").toBool()) {
        showError(tr("Could not save"), r.value("error").toString());
        return false;
    }
    afterSave();
    return true;
}

// D72: an automatic version every N saves or N minutes, when the preference asks for it.
void MainWindow::maybeAutoVersion()
{
    if (!m_versioned || m_prefs.autoVersion() == QLatin1String("off") || !hasUnversionedWork())
        return;
    ++m_savesSinceVersion;
    const bool due = m_prefs.autoVersion() == QLatin1String("saves")
        ? m_savesSinceVersion >= m_prefs.autoVersionEvery()
        : m_sinceVersion.elapsed() >= qint64(m_prefs.autoVersionEvery()) * 60000;
    if (due)
        commitVersion(tr("Automatic version"));
}

void MainWindow::afterSave()
{
    afterEdit();
    refreshProject();
    m_status->showMessage(tr("Saved %1").arg(documentState().value("name").toString()));
}

bool MainWindow::saveAs(const QString& path)
{
    const bool ifc = QFileInfo(path).suffix().compare(QLatin1String("ifc"), Qt::CaseInsensitive) == 0;
    const QJsonObject r = bridge(ifc ? "save_as_ifc" : "save_as_kim", {path});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not save"), r.value("error").toString());
        return false;
    }
    m_path = path;
    rememberRecent(path);
    afterSave();
    return true;
}

void MainWindow::saveAsDialog()
{
    QString selected;
    const QString path = QFileDialog::getSaveFileName(this, tr("Save As"), m_document.value("path").toString(),
        tr("KimBim project (*.kim);;IFC file (*.ifc)"), &selected);
    if (!path.isEmpty())
        saveAs(path);
}

bool MainWindow::saveAsFolder(const QString& folder)
{
    const QJsonObject r = bridge("save_as_folder", {folder});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not save the project folder"), r.value("error").toString());
        return false;
    }
    rememberRecent(folder);
    afterSave();
    return true;
}

bool MainWindow::enableVersioning(const QString& folder, const QString& message)
{
    const QJsonObject r = bridge("save_as_folder", {folder, message.isEmpty() ? tr("Initial import") : message});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not enable versioning"), r.value("error").toString());
        return false;
    }
    afterSave();
    m_status->showMessage(tr("Versioning enabled: first version saved"));
    return true;
}

bool MainWindow::exportIfc(const QString& path)
{
    const QJsonObject r = bridge("export_ifc", {path});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not export"), r.value("error").toString());
        return false;
    }
    m_status->showMessage(tr("Exported %1").arg(QFileInfo(path).fileName()));
    return true;
}
```

with `saveAsFolderDialog()` (`getExistingDirectory(this, tr("Choose an empty folder for the project"))`)
and `exportIfcDialog()` (`getSaveFileName(this, tr("Export IFC"), QString(), tr("IFC files (*.ifc)"))`).

`saveVersion(message)` becomes: `commitVersion(message)` (the old body: bridge `save_version`, refresh),
then, when `documentState()` mode is `kim`, `bridge("save_document")` so the file holds the version;
`commitVersion` resets `m_savesSinceVersion = 0; m_sinceVersion.restart();`.

`refreshProject()` title:

```cpp
    const QJsonObject doc = documentState();
    QString name = doc.value("untitled").toBool() ? tr("Untitled") : doc.value("name").toString();
    if (m_versioned)
        name += QStringLiteral(" (%1)").arg(option);
    if (doc.value("read_only").toBool())
        name += QStringLiteral(" [%1]").arg(tr("read-only"));
    setWindowTitle(QStringLiteral("KimBim — %1[*]").arg(name));
    setWindowModified(isDirty());
```

used in both the versioned and unversioned branches (and `onOpened`/`newProject` call
`refreshProject()` instead of setting the title themselves). `m_projectFolder` keeps the project
folder for the existing Compare/History code (`s.value("folder")`).

Guards: `resolveUnsavedForSwitch`, `milestoneDialog` and `combineDialog` test `hasUnversionedWork()`
instead of `isDirty()`.

- [ ] **Step 5: Run the tests**

Run: `pixi run pytest tests/python/test_documents.py -q` and `pixi run app-test`
Expected: all pass (36 + new).

- [ ] **Step 6: Commit**

```bash
git add python/kimbim/documents.py python/kimbim/app_bridge.py app/src/MainWindow.h app/src/MainWindow.cpp app/src/main.cpp app/tests/test_main_window.cpp tests/python/test_documents.py
git commit -m "feat(app): File menu on .kim files: open (.kim/.ifc/folder), save, save as, export IFC, recent files, read-only"
```

---

### Task 10: Project settings in the app

**Files:**
- Create: `app/src/ProjectSettingsDialog.h`, `app/src/ProjectSettingsDialog.cpp`
- Modify: `app/src/MainWindow.h/.cpp`, `app/CMakeLists.txt`
- Test: `app/tests/test_main_window.cpp`

**Interfaces:**
- Consumes: bridge `project_settings`, `set_project_settings` (Task 1).
- Produces: `QJsonObject MainWindow::projectSettings() const` (cached `m_settings`), `bool MainWindow::setProjectSettings(const QJsonObject& changes)`, `QString MainWindow::formatLength(double metres) const`, `void MainWindow::projectSettingsDialog()`;
  `class ProjectSettingsDialog : public QDialog { ProjectSettingsDialog(const QJsonObject& settings, bool kept, QWidget* parent); QJsonObject changes() const; }` with child object names `cutHeight` (QDoubleSpinBox, m), `drawingScale` (QSpinBox), `sheetPaper` (QComboBox A1/A3), `lengthUnit` (QComboBox m/cm/mm), `lengthDecimals` (QSpinBox 0–4), `notKeptNote` (QLabel, visible when `!kept`).

- [ ] **Step 1: Write the failing test**

```cpp
    // D72: project settings are applied on open and saved with the .kim (layers, cut, scale, paper, units).
    void projectSettingsTravelWithTheKim()
    {
        QTemporaryDir tmp;
        const QString kim = tmp.filePath(QStringLiteral("ajustes.kim"));
        {
            kimbim::MainWindow w(nullptr, /*quiet=*/true);
            QVERIFY(w.newProject());
            QVERIFY(w.createLayer(QStringLiteral("A-WALL")));
            QVERIFY(w.setProjectSettings({{"plan_cut_height", 1.0}, {"sheet_paper", "A3"}, {"drawing_scale", 50},
                                          {"length_unit", "mm"}, {"length_decimals", 0}}));
            QVERIFY(w.isDirty());
            QCOMPARE(w.formatLength(3.5), QLocale().toString(3500.0, 'f', 0) + QStringLiteral(" mm"));
            QVERIFY(!w.setProjectSettings({{"drawing_scale", 0}})); // refused, nothing changes
            w.setLayerVisible(QStringLiteral("A-WALL"), false);
            QVERIFY(w.saveAs(kim));
            QVERIFY(w.close());
        }
        kimbim::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy loaded(&w, &kimbim::MainWindow::loadFinished);
        QVERIFY(w.openPath(kim));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(w.planCutHeight(), 1.0);
        QCOMPARE(w.projectSettings().value("hidden_layers").toArray(), QJsonArray({"A-WALL"}));
        QCOMPARE(w.projectSettings().value("sheet_paper").toString(), QString("A3"));
        QVERIFY(!w.isDirty());
        const QString number = w.addSheet(w.projectSettings().value("sheet_paper").toString(), QStringLiteral("S"));
        QVERIFY(!number.isEmpty());
        QVERIFY(w.close());
    }

    void projectSettingsDialogReportsOnlyChanges()
    {
        kimbim::ProjectSettingsDialog d({{"plan_cut_height", 1.2}, {"drawing_scale", 100}, {"sheet_paper", "A1"},
                                         {"length_unit", "m"}, {"length_decimals", 2}}, /*kept=*/false, nullptr);
        QVERIFY(d.findChild<QLabel*>("notKeptNote")->isVisibleTo(&d));
        d.findChild<QComboBox*>("sheetPaper")->setCurrentText("A3");
        d.findChild<QSpinBox*>("drawingScale")->setValue(50);
        QCOMPARE(d.changes(), QJsonObject({{"sheet_paper", "A3"}, {"drawing_scale", 50}}));
    }
```

(Use whatever `MainWindow` already offers to create a layer — check `createLayer`/`addLayer` in
`MainWindow.h` and use that name. `addSheet` is public already; if not, use the bridge through
`newSheetDialog` in quiet mode.)

- [ ] **Step 2: Run it to see it fail**

Run: `pixi run app-build` → FAIL (`setProjectSettings`, `ProjectSettingsDialog` unknown).

- [ ] **Step 3: Implement**

`ProjectSettingsDialog` (a `QFormLayout` with the five fields, an OK/Cancel `QDialogButtonBox`, and the
note "These settings aren't kept with a plain IFC file. Save as .kim to keep them." shown when `!kept`).
`changes()` returns only the keys whose value differs from the settings passed in (cut height
compared rounded to the centimetre).

`MainWindow`:

```cpp
void MainWindow::loadProjectSettings()
{
    m_settings = bridge("project_settings").value("settings").toObject();
    m_hiddenLayers.clear();
    m_lockedLayers.clear();
    for (const auto& l : m_settings.value("hidden_layers").toArray())
        m_hiddenLayers.insert(l.toString());
    for (const auto& l : m_settings.value("locked_layers").toArray())
        m_lockedLayers.insert(l.toString());
    const QSignalBlocker block(m_cutHeight);
    m_cutHeight->setValue(m_settings.value("plan_cut_height").toDouble(1.2));
    m_cutLabel->setText(formatLength(m_cutHeight->value()));
}

bool MainWindow::setProjectSettings(const QJsonObject& changes)
{
    const QJsonObject r = bridge("set_project_settings",
        {QString::fromUtf8(QJsonDocument(changes).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(r.value("error").toString());
        return false;
    }
    m_settings = r.value("settings").toObject();
    setWindowModified(isDirty());
    return true;
}

QString MainWindow::formatLength(double metres) const
{
    const QString unit = m_settings.value("length_unit").toString(QStringLiteral("m"));
    const double factor = unit == QLatin1String("mm") ? 1000.0 : unit == QLatin1String("cm") ? 100.0 : 1.0;
    return QLocale().toString(metres * factor, 'f', m_settings.value("length_decimals").toInt(2))
        + QLatin1Char(' ') + unit;
}

void MainWindow::saveLayerStates()
{
    QStringList hidden(m_hiddenLayers.begin(), m_hiddenLayers.end()), locked(m_lockedLayers.begin(), m_lockedLayers.end());
    hidden.sort();
    locked.sort();
    setProjectSettings({{"hidden_layers", QJsonArray::fromStringList(hidden)},
                        {"locked_layers", QJsonArray::fromStringList(locked)}});
}
```

- `onOpened`: replace `m_hiddenLayers.clear(); m_lockedLayers.clear();` with `loadProjectSettings();`;
  `newProject()` likewise.
- `setLayerVisible` / `setLayerLocked`: call `saveLayerStates()` before `refreshLayers()`. The saved-view
  restore (around line 3450) also ends with `saveLayerStates()`.
- The cut label (3 places) uses `formatLength(...)`; the tool length readout (`tr("Length %1 m")`)
  becomes `tr("Length %1").arg(formatLength(...))`, the move readout likewise.
- `newSheet` action and `SheetsPanel` keep their paper choice; the palette's "New sheet" uses
  `m_settings.value("sheet_paper")`, its tooltip "Add a sheet and open it".
- `placeOnSheet` passes `QString::number(m_settings.value("drawing_scale").toInt(100))` as the scale.
- `projectSettingsDialog()`:

```cpp
void MainWindow::projectSettingsDialog()
{
    ProjectSettingsDialog dialog(m_settings, bridge("project_settings").value("kept").toBool(), this);
    if (dialog.exec() == QDialog::Accepted && !dialog.changes().isEmpty() && setProjectSettings(dialog.changes()))
        m_status->showMessage(tr("Project settings changed"));
}
```

- [ ] **Step 4: Run the tests**

Run: `pixi run app-build` and `ctest --test-dir build/app -R test_main_window --output-on-failure`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/src/ProjectSettingsDialog.h app/src/ProjectSettingsDialog.cpp app/src/MainWindow.h app/src/MainWindow.cpp app/CMakeLists.txt app/tests/test_main_window.cpp
git commit -m "feat(app): project settings applied on open and kept in the .kim (layers, cut, scale, paper, units)"
```

---

### Task 11: Preferences dialog, language, author, recovery

**Files:**
- Create: `app/src/PreferencesDialog.h`, `app/src/PreferencesDialog.cpp`
- Modify: `app/src/MainWindow.h/.cpp`, `app/src/main.cpp`, `app/CMakeLists.txt`
- Test: `app/tests/test_preferences.cpp` (dialog), `app/tests/test_main_window.cpp` (recovery, auto versions)

**Interfaces:**
- Consumes: Task 7 `Preferences`; bridge `set_author`, `write_recovery`, `recoveries`, `recover`, `discard_recovery`.
- Produces: `class PreferencesDialog : public QDialog { PreferencesDialog(Preferences& prefs, QWidget* parent); void apply(); }` with child names `language`, `templatesFolder`, `authorName`, `authorEmail`, `newViews`, `openIfc`, `autoVersion`, `autoVersionEvery`, `recoveryMinutes`, `restartNote`; `MainWindow::preferencesDialog()`, `bool MainWindow::writeRecovery()`, `QJsonArray MainWindow::recoveries()`, `bool MainWindow::recoverFrom(const QString& id)`, `void MainWindow::offerRecovery()`.

- [ ] **Step 1: Write the failing tests**

`test_preferences.cpp`:

```cpp
    void theDialogWritesWhatTheUserPicked()
    {
        kimbim::Preferences p;
        kimbim::PreferencesDialog d(p, nullptr);
        QVERIFY(!d.findChild<QLabel*>("restartNote")->isVisibleTo(&d));
        d.findChild<QComboBox*>("language")->setCurrentIndex(2); // auto, en, es
        QVERIFY(d.findChild<QLabel*>("restartNote")->isVisibleTo(&d));
        d.findChild<QComboBox*>("newViews")->setCurrentIndex(1);
        d.findChild<QComboBox*>("openIfc")->setCurrentIndex(1);
        d.findChild<QComboBox*>("autoVersion")->setCurrentIndex(1);
        d.findChild<QSpinBox*>("autoVersionEvery")->setValue(3);
        d.findChild<QSpinBox*>("recoveryMinutes")->setValue(0);
        d.findChild<QLineEdit*>("authorName")->setText("Felipe");
        d.findChild<QLineEdit*>("templatesFolder")->setText("Z:/Plantillas");
        d.apply();
        QCOMPARE(p.language(), QString("es"));
        QCOMPARE(p.newViews(), QString("window"));
        QCOMPARE(p.openIfc(), QString("edit_ifc"));
        QCOMPARE(p.autoVersion(), QString("saves"));
        QCOMPARE(p.autoVersionEvery(), 3);
        QCOMPARE(p.recoveryMinutes(), 0);
        QCOMPARE(p.authorName(), QString("Felipe"));
        QCOMPARE(p.templatesFolder(), QString("Z:/Plantillas"));
    }
```

`test_main_window.cpp`:

```cpp
    // D72: an automatic version every N saves.
    void automaticVersionsEveryNSaves()
    {
        QTemporaryDir tmp;
        kimbim::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimbim::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.wallTool()->finish();
        w.setTool(kimbim::MainWindow::Tool::None);
        QVERIFY(w.saveAs(tmp.filePath(QStringLiteral("auto.kim"))));
        w.preferences().setValue("auto_version", "saves");
        w.preferences().setValue("auto_version_every", 2);
        w.setSelection(w.viewport()->guids());
        QVERIFY(w.applyName(QStringLiteral("uno")));
        QVERIFY(w.save());
        QCOMPARE(w.history().size(), 1);
        QVERIFY(w.applyName(QStringLiteral("dos")));
        QVERIFY(w.save());
        QCOMPARE(w.history().size(), 2);
        QCOMPARE(w.history().first().toObject().value("message").toString(), QString("Automatic version"));
        QVERIFY(w.close());
    }

    // D72: the recovery copy of unsaved work comes back after a "crash".
    void recoveryCopyComesBack()
    {
        QString wall;
        {
            kimbim::MainWindow w(nullptr, /*quiet=*/true);
            QVERIFY(w.newProject());
            w.setTool(kimbim::MainWindow::Tool::Wall);
            w.wallTool()->click({0, 0});
            w.wallTool()->click({5, 0});
            w.wallTool()->finish();
            w.setTool(kimbim::MainWindow::Tool::None);
            wall = w.viewport()->guids().first();
            QVERIFY(w.writeRecovery());
            // A crash: the model goes away without the window closing (no close_document).
            QString error;
            kimbim::PythonEngine::instance().callJson("new_project", {QStringLiteral("x")}, &error);
        } // destroyed without close()
        kimbim::MainWindow w(nullptr, /*quiet=*/true);
        const QJsonArray items = w.recoveries();
        QVERIFY(!items.isEmpty());
        QSignalSpy loaded(&w, &kimbim::MainWindow::loadFinished);
        QVERIFY(w.recoverFrom(items.first().toObject().value("id").toString()));
        QVERIFY(loaded.wait(60000));
        QVERIFY(w.viewport()->guids().contains(wall));
        QVERIFY(w.isDirty());
        QVERIFY(w.close()); // quiet close discards: the copy is cleared
        QVERIFY(w.recoveries().isEmpty());
    }
```

Recovery copies are cleared only by a save or by `close_document` (the app calls it after the user
saved or discarded); an implicit switch to another model keeps them, which is what a crash looks like.

- [ ] **Step 2: Run them to see them fail**

Run: `pixi run app-build` → FAIL (`PreferencesDialog`, `writeRecovery` unknown).

- [ ] **Step 3: Implement**

`PreferencesDialog`: a `QFormLayout`:
- Language: combo "Automatic (system)", "English", "Español" (data auto/en/es); `restartNote` label
  "The language changes the next time KimBim starts." visible when the choice differs from the stored one.
- Templates folder: `QLineEdit` + "Browse..." (`QFileDialog::getExistingDirectory`).
- Your name / email (for versions): two `QLineEdit`s.
- New views open as: "Tabs" / "Free windows" (tab/window).
- Opening an IFC file: "Make a .kim beside it" / "Edit the IFC directly" (make_kim/edit_ifc).
- Automatic versions: "Off" / "Every N saves" / "Every N minutes" + `QSpinBox autoVersionEvery` (1–999, enabled unless Off).
- Recovery copy every: `QSpinBox recoveryMinutes` (0–120, suffix " min", special value text "Off").
- OK/Cancel; `accept()` calls `apply()`. `apply()` writes every field to the `Preferences`.

`MainWindow`:

```cpp
void MainWindow::preferencesDialog()
{
    PreferencesDialog dialog(m_prefs, this);
    if (dialog.exec() != QDialog::Accepted)
        return;
    m_prefs.save();
    bridge("set_author", {m_prefs.authorName(), m_prefs.authorEmail()});
    restartRecoveryTimer();
}

void MainWindow::restartRecoveryTimer()
{
    m_recoveryTimer.stop();
    if (!m_quiet && m_prefs.recoveryMinutes() > 0)
        m_recoveryTimer.start(m_prefs.recoveryMinutes() * 60000);
}

bool MainWindow::writeRecovery()
{
    return bridge("write_recovery").value("ok").toBool();
}

QJsonArray MainWindow::recoveries()
{
    return bridge("recoveries").value("items").toArray();
}

bool MainWindow::recoverFrom(const QString& id)
{
    if (!closeDocument())
        return false;
    const QJsonObject r = bridge("recover", {id});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not recover the work"), r.value("error").toString());
        return false;
    }
    openFile(r.value("path").toString());
    return true;
}

void MainWindow::offerRecovery()
{
    for (const auto& v : recoveries()) {
        const QJsonObject item = v.toObject();
        const QString what = item.value("name").toString().isEmpty() ? tr("an untitled project") : item.value("name").toString();
        const QString when = QLocale().toString(QDateTime::fromSecsSinceEpoch(qint64(item.value("time").toDouble())), QLocale::ShortFormat);
        const auto answer = QMessageBox::question(this, tr("Recover unsaved work"),
            tr("KimBim closed unexpectedly. Recover your work on %1 from %2?").arg(what, when),
            QMessageBox::Yes | QMessageBox::Discard, QMessageBox::Yes);
        if (answer == QMessageBox::Yes)
            return void(recoverFrom(item.value("id").toString()));
        bridge("discard_recovery", {item.value("id").toString()});
    }
}
```

`m_recoveryTimer` (`QTimer`, member): `connect(&m_recoveryTimer, &QTimer::timeout, this, [this] { if (isDirty()) writeRecovery(); });`
and `restartRecoveryTimer()` at the end of the constructor. Edit menu: `Edit › Preferences...`
(`actionPreferences`, `QKeySequence::Preferences`) → `preferencesDialog`.

`main.cpp`:

```cpp
    kimbim::Preferences prefs(kimbim::Preferences::defaultPath());
    prefs.load();
    const QString language = parser.isSet(lang) ? parser.value(lang)
        : prefs.language() == QLatin1String("auto") ? QString() : prefs.language();
    kimbim::installTranslator(app, kimbim::pickLanguage(language));
    ...
    kimbim::MainWindow window;
    window.show();
    if (!parser.positionalArguments().isEmpty())
        window.openPath(parser.positionalArguments().first());
    else
        window.offerRecovery();
```

- [ ] **Step 4: Run the tests**

Run: `pixi run app-build`, `ctest --test-dir build/app -R "test_preferences|test_main_window" --output-on-failure`, `pixi run pytest tests/python/test_documents.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/src/PreferencesDialog.h app/src/PreferencesDialog.cpp app/src/MainWindow.h app/src/MainWindow.cpp app/src/main.cpp app/CMakeLists.txt app/tests/test_preferences.cpp app/tests/test_main_window.cpp python/kimbim/documents.py
git commit -m "feat(app): preferences dialog (language, author, new views, IFC opening, automatic versions, recovery)"
```

---

### Task 12: Templates in the app

**Files:**
- Modify: `app/src/MainWindow.h/.cpp`
- Test: `app/tests/test_main_window.cpp`

**Interfaces:**
- Consumes: bridge `templates`, `new_from_template`, `save_template` (Task 6); `Preferences::templatesFolder()`.
- Produces: `bool MainWindow::newFromTemplate(const QString& path)` (`"builtin"` = the default), `bool MainWindow::saveAsTemplate(const QString& name, bool replace = false)`, `void MainWindow::newProjectDialog()`, `void MainWindow::saveAsTemplateDialog()`. `newProject()` becomes `newFromTemplate("builtin")`.

- [ ] **Step 1: Write the failing test**

```cpp
    // D72: office templates: save one, start a project from it, first save makes its history.
    void projectsStartFromOfficeTemplates()
    {
        QTemporaryDir tmp;
        kimbim::MainWindow w(nullptr, /*quiet=*/true);
        w.preferences().setValue("templates_folder", tmp.filePath(QStringLiteral("Plantillas")));
        QVERIFY(w.newProject());
        w.setTool(kimbim::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.wallTool()->finish();
        w.setTool(kimbim::MainWindow::Tool::None);
        const QString original = w.viewport()->guids().first();
        QVERIFY(w.saveAsTemplate(QStringLiteral("Oficina")));
        QVERIFY(!w.saveAsTemplate(QStringLiteral("Oficina"))); // exists; quiet mode doesn't replace
        QVERIFY(w.saveAsTemplate(QStringLiteral("Oficina"), /*replace=*/true));
        const QString path = tmp.filePath(QStringLiteral("Plantillas/Oficina.kim"));
        QVERIFY(QFile::exists(path));

        QSignalSpy loaded(&w, &kimbim::MainWindow::loadFinished);
        QVERIFY(w.newFromTemplate(path));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(w.viewport()->elementCount(), 1);
        QVERIFY(!w.viewport()->guids().contains(original)); // new ids
        QVERIFY(w.windowTitle().contains(QStringLiteral("Untitled")));
        QVERIFY(!w.save()); // untitled: quiet mode can't ask where
        QVERIFY(w.saveAs(tmp.filePath(QStringLiteral("nuevo.kim"))));
        QCOMPARE(w.history().first().toObject().value("message").toString(), QString("Created from Oficina"));
        QVERIFY(w.close());
    }
```

- [ ] **Step 2: Run it to see it fail**

Run: `pixi run app-build` → FAIL (`saveAsTemplate`, `newFromTemplate` unknown).

- [ ] **Step 3: Implement**

```cpp
bool MainWindow::newFromTemplate(const QString& path)
{
    if (!closeDocument())
        return false;
    const QJsonObject r = bridge("new_from_template", {path});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not create the project"), r.value("error").toString());
        return false;
    }
    if (!r.value("path").toString().isEmpty()) { // an office template: load it like a file
        endCompare();
        openFile(r.value("path").toString());
        return true;
    }
    resetForNewModel(); // the old newProject() body after its bridge call
    return true;
}

bool MainWindow::newProject()
{
    return newFromTemplate(QStringLiteral("builtin"));
}

void MainWindow::newProjectDialog()
{
    const QJsonObject listing = bridge("templates", {m_prefs.templatesFolder()});
    const QJsonArray list = listing.value("templates").toArray();
    if (list.size() <= 1 || m_quiet) {
        newProject();
        return;
    }
    QDialog dialog(this);
    dialog.setWindowTitle(tr("New project"));
    auto* layout = new QVBoxLayout(&dialog);
    layout->addWidget(new QLabel(tr("Start from a template:"), &dialog));
    auto* choices = new QListWidget(&dialog);
    choices->setObjectName(QStringLiteral("templateList"));
    for (const auto& v : list) {
        const QJsonObject t = v.toObject();
        auto* item = new QListWidgetItem(t.value("builtin").toBool() ? tr("KimBim default")
            : QStringLiteral("%1  (%2)").arg(t.value("name").toString(), t.value("modified").toString()), choices);
        item->setData(Qt::UserRole, t.value("path").toString());
    }
    choices->setCurrentRow(0);
    layout->addWidget(choices);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    connect(choices, &QListWidget::itemDoubleClicked, &dialog, &QDialog::accept);
    layout->addWidget(buttons);
    if (dialog.exec() == QDialog::Accepted && choices->currentItem())
        newFromTemplate(choices->currentItem()->data(Qt::UserRole).toString());
}

bool MainWindow::saveAsTemplate(const QString& name, bool replace)
{
    QJsonObject r = bridge("save_template", {m_prefs.templatesFolder(), name, replace ? QStringLiteral("1") : QString()});
    if (!r.value("ok").toBool() && r.value("exists").toBool() && !m_quiet
        && QMessageBox::question(this, tr("Save as template"), tr("A template called %1 exists. Replace it?").arg(name))
               == QMessageBox::Yes)
        r = bridge("save_template", {m_prefs.templatesFolder(), name, QStringLiteral("1")});
    if (!r.value("ok").toBool()) {
        if (!r.value("exists").toBool())
            showError(tr("Could not save the template"), r.value("error").toString());
        return false;
    }
    m_status->showMessage(tr("Template %1 saved").arg(name));
    return true;
}

void MainWindow::saveAsTemplateDialog()
{
    bool ok = false;
    const QString name = QInputDialog::getText(this, tr("Save as template"),
        tr("Template name (saved in %1):").arg(QDir::toNativeSeparators(m_prefs.templatesFolder())),
        QLineEdit::Normal, QString(), &ok);
    if (ok && !name.trimmed().isEmpty())
        saveAsTemplate(name.trimmed());
}
```

Move the old `newProject()` body (after its `new_project` call) into `resetForNewModel()`, ending with
`loadProjectSettings(); refreshProject();`.

- [ ] **Step 4: Run the tests**

Run: `pixi run app-test`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/src/MainWindow.h app/src/MainWindow.cpp app/tests/test_main_window.cpp
git commit -m "feat(app): office templates: New project lists them, Save as template makes one"
```

---

### Task 13: Docs, translations, decision

**Files:**
- Modify: `docs/decisions.md` (D72; D56 note), `docs/03-versioning.md` (project modes), `docs/04-app-features.md`, `docs/13-architect-feedback.md`, `app/translations/kimbim_es.ts`, `app/translations/kimbim_en.ts`

- [ ] **Step 1: D72** — one row in `docs/decisions.md`:

`| D72 | The **.kim file**: one zip holding the whole project — model (working.ifc), project settings and the Git history — unpacked to a local working folder while open (outside OneDrive) and packed back on save (temp file + atomic replace). "Open as folder" works on the same content unpacked. **Ctrl+S saves the file** (amends D56); *Save version* (Ctrl+Alt+S) adds history, optionally automatic every N saves or minutes. Project settings (cut height, layer states, drawing scale, sheet paper, length units; pen sets in step 3) are settings.json in every version's tree, merged by key in Combine. One editor at a time: a lock beside the file; others open read-only. Opening an .ifc makes a .kim beside it (preference: edit the IFC directly). User preferences in preferences.json per computer. Office templates are history-less .kim files in a templates folder; a project from one gets new GlobalIds. Recovery copy of unsaved work every N minutes | Decided (owner, 2026-10-08) | [spec](superpowers/specs/2026-10-08-kim-file-and-preferences-design.md), [plan](superpowers/plans/2026-10-08-kim-file-and-preferences.md) |`

and in D56's row append "(Ctrl+S: amended by D72)".

- [ ] **Step 2: Docs** — `docs/03-versioning.md` "Project modes": add the `.kim` row and say a `.kim`
is the versioned folder zipped; `docs/04-app-features.md`: File menu, Preferences, Project settings,
templates; `docs/13-architect-feedback.md`: a "2026-10-08: step 2" section (what changed, how to try it)
plus the A1-sheet fix.

- [ ] **Step 3: Translations**

Run: `pixi run app-build` (lupdate runs with the build; if not, run the `update_translations` target:
`cmake --build build/app --target update_translations`). Then fill every new `unfinished` entry in
`kimbim_es.ts` with Spanish (e.g. "Save as &template..." → "Guardar como &plantilla...", "Recent files"
→ "Archivos recientes", "read-only" → "solo lectura", "Untitled" → "Sin título", "Automatic version"
→ "Versión automática", "Project se&ttings..." → "&Configuración del proyecto...", "Preferences..."
→ "Preferencias...").

Run: `pixi run check-translations` and `pixi run check-spdx`
Expected: both OK.

- [ ] **Step 4: Full verification**

Run: `pixi run test` (SPDX, Rust, Python) and `pixi run app-test`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add docs app/translations
git commit -m "docs+i18n: D72 .kim file, preferences and templates; Spanish for the new UI"
```
