# Slice 8 (M5, part 1) — Versioned projects in the app: save versions, history, compare, design options

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the versioning engine from Slice 1 (CLI) into the app. An architect can:
- turn on versioning for a model (or open a versioned project folder);
- **Save version** with a message and a summary of what changed;
- browse the **History**;
- **Compare** any version with the current model or with another version: changed elements are coloured in the 3D view (added green, modified orange) with a change list (removed elements listed);
- create and switch **design options** (branches).

**Architecture:** A new bridge module `python/kimbim/versioning.py` (re-exported by `app_bridge`) wraps `kimbim.project.Project`.
- **Working copy:** the open model is the working state. "Save version" writes it to `<project>/.kimbim/working.ifc` and commits it; opening a project or switching option exports HEAD to that file and opens it (doc 03: Plain vs Versioned modes; `.kimbim/` is local only).
- **Compare:** project diffs. Working vs a version uses the project's change computation on the written working copy.
- **C++:** `Viewport` gets per-element colour overrides (`ElementBatch` fixed colours); `MainWindow` gets the File-menu entries, a Save-version dialog, a History dock (versions list + change list), and an Options combo in a Project toolbar.

**Tech Stack:** existing Rust store (`kimbim._core`) + `kimbim.project`, ifcopenshell, Qt 6, OCCT, pytest, Qt Test.

**Spec:** docs/03-versioning.md (modes, working state, diff categories), docs/04-app-features.md §9 (Save version dialog, History, Compare with viewport colouring, Design options P0), docs/07-roadmap.md M5. Milestones (tags), object history and before/after are Slice 9; Combine options (merge) is Slice 10 (M5 exit).

## Global Constraints

- The working copy never auto-commits; "Save version" is explicit. Unsaved work is guarded on close/open/switch (Save version / Discard / Cancel).
- Element identity: GlobalIds survive commit → export → reopen (records are keyed by GlobalId), so compares match elements across versions.
- No network; projects are local folders. EN/ES UI, SPDX, DCO; headless CI.

## Review Focus

1. Switching options with unsaved changes must not lose them silently (refuse in the bridge; the UI asks).
2. Compare working vs HEAD right after an edit shows exactly the edited elements as modified (no noise from unrelated records like the owner history).
3. Enabling versioning in a folder that already holds a project or other files is refused (no overwrite).
4. After Save version, the model is not dirty and undo history still works for further edits.
5. Opening a versioned project shows the HEAD state with the same GlobalIds as committed.

---

### Task 1: Bridge — versioning module
- `project_state()`, `enable_versioning(folder, message)`, `open_project(folder)`, `version_changes()` (working vs HEAD summary), `save_version(message)`, `history(limit)`, `compare(rev_a, rev_b)` (`rev_b` may be `"WORKING"`), `options()`, `create_option(name)`, `switch_option(name)`, `discard_changes()`.
- Tests `tests/python/test_versioning_app.py`: Review Focus 1–5 plus the history order, two-version compare, option content differs after switching.

### Task 2: Viewport colour overrides
- `ElementBatch::setColorOverride(int, std::optional<Quantity_Color>)`; `Viewport::setElementColors(QHash<QString, QColor>)`, `clearElementColors()`, `coloredCount()`; overrides survive `replaceElements` for the same guid until cleared.
- Tests in `test_visibility.cpp`.

### Task 3: App — project menu, Save version, History & Compare dock, options
- File › Enable versioning…, Open project…, Save version… (Ctrl+Alt+S); Project toolbar with the option combo + New option…; History dock (versions; Compare with current / Compare two; change list; click selects); compare legend; guards on close/open/switch.
- Tests `test_main_window` (temp folder: enable, edit, save version, history 2, compare colours 1, new option, switch back reloads).

### Task 4: Docs and verification
- README, doc 04 §9 status, doc 03 notes (working copy location), roadmap M5 progress, decisions D56; full suites Windows + WSL; self-review; finish the branch.
