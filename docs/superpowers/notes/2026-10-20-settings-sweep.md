# Settings sweep (Track B, D92) — 2026-10-20

Branch `settings-sweep`. One commit per backlog item, tests first where they were practical. The
items below are in the order of the D92 list in `docs/open-questions.md`.

## What I built

### 1. Python console — done (`6b7e803`)
- Every console run is one undo step: `console._execute_all` opens one step, bridge commands and
  direct edits join it, a run that changed nothing leaves no empty step
  (`app_bridge._end_step_without_change`), and a failed or stopped run rolls back. `edit()` now
  simply joins the run's step (it still works stand-alone).
- Headless CLI: `kimbim run script.py model.ifc [-o OUT] [--select GUID]` opens the model, runs the
  script in the console namespace and writes the changed model back.
- Tests: `tests/python/test_console.py`, `tests/python/test_cli.py`.

### 2. View cube — partial (`572b6f8`)
- Home view: `Viewport::setHomeView`/`useCurrentViewAsHome`; a Views-menu action "Set current view
  as home" stores the direction in the `home_view` preference (default south-east iso).
- Perspective field of view: `field_of_view` preference (default 45°), `Viewport::setFieldOfView`,
  a Preferences row.
- Not done: the north arrow on plans (a per-view option, on once true north is set). It needs a
  view-option store and a viewport/drawing north indicator that do not exist yet.

### 3. Window chrome — done (`75005fa`)
- `title_bar_levels`, `title_bar_cut`, `title_bar_versions` preferences with Preferences
  checkboxes; `MainWindow::applyTitleBarPreferences` shows/hides the controls.
- Save version also in the File menu (`actionSaveVersionFile`; the shortcut stays on the Versions
  menu's action).

### 4. Schedules — done (`659fc4e`)
- Walls schedule gains inside/outside face length columns (the axis length for KimBim's straight
  walls; joins are not accounted for yet).
- Per-schedule `min_opening_area` (default 0: deduct every opening) and `unit` (m/cm/mm, default m),
  applied to values, headers and export; both editable in the schedule-scheme dialog.
- Group-by fields already existed per schedule.

### 5. Selection — done (`3f218f2`)
- `select_similar_scope` preference (default "class and predefined type"; also type object or class);
  `queries.similar` gained the `class_predefined` mode.
- Ctrl+A (`actionSelectAll`): with a creation tool active selects that tool's class, otherwise
  everything.
- `box_selection` preference (drag direction default, or Archicad's partial/entire).
- Find & Select "Include hidden" checkbox: the query drops the hidden/locked-layer filter.

### 6. Measure and levels — partial (`b861b0c`)
- `area_unit` project setting (m²/cm²/mm²) with `settings.format_area` and a Project settings row.
- A level's elevation change can move the levels above (`move_above`, off by default).
- Inserting a level can fit between two levels (`fit_between`) instead of pushing up.
- Not done: mesh-vertex snaps (a new Snapper kind), and the C++ LevelsDialog/measure wiring for the
  new options and the area unit (the engine + settings exist; the dialogs do not offer them yet).

### 7. Split, trim, join — partial (`b8b6ff1`)
- Trim that would leave a door, window or opening outside: `holes` = refuse (default), delete or
  keep, on `trim_extend` and `trim_corner`.
- `split_join` preference: split/trim pieces are joined unless the preference is off (Ctrl inverts).
- Not done: the merge keep-first/refuse option (`join_elements` still refuses on geometry mismatch)
  and imported walls "keep shape and cut" (`_adopt` still always rebuilds).

### 8. Checks — partial (`0cc19df`)
- `check_tolerance` (2 mm) and `check_clearance` (50 mm) project settings used when a clash set does
  not override them.
- `check_ignore_joined` (on): walls joined to each other are ignored in clashes.
- Not done: partial-overlap duplicates (only exact duplicates are found), IDS linked from a shared
  folder (only embedded XML is supported).

### 9. DXF export and underlays — partial (`27027c6`)
- DXF export options: `layers` "iso" (ISO 13567 names) besides by-KimBim-layer and NCS kind;
  `poche` (fills on the element layer instead of `-PATT`); `colour` "aci" or "lineweight" (exact by
  default).
- Not done: "per pen" layer naming, placement centred vs survey coordinates, the DXF export dialog
  rows for the new options, and the underlay preferences (opacity/grey/tint defaults, layer per
  underlay) and undoable underlay edits.

### 11. Tags and dimensions — partial (`dd54d84`)
- `orphan_tags` setting: a tag whose element is gone is deleted (default) or kept showing "?".
- `radius_decimals` (and `angle_decimals`) project settings used by radius/diameter and angle
  dimensions.
- Not done: Tag all asking for categories, the level-dimension reference (project zero/level/sea
  level), and the north-arrow/scale-bar symbol pickers.

## What I skipped (with reasons)

- **10. 2D drafting** — not started. "Keep rectangles rectangular" is a grip/edit change, and the
  fill outline pen and paper/model pattern scale need new annotation-extra fields threaded through
  `drafting.py`, the drawing generator and DXF; too big for the time left.
- **12. Object library** — not started. "Edit selection or ask about the type" is a preference plus
  a prompt in `set_object_parameter`; "origin per object" and per-object plan-symbol overrides need
  new per-object data.
- **13. Stairs** — not started. Extending `stair_rules` with a tread mode and riser target, the
  editable flight split/well width, the headroom-only floor opening and the plan arrow/riser-number
  drawing settings all touch `stairs.py` and the drawing generator.
- **14. Tracker and navigation** — not started (C++): tracker always/typing/off, angle
  absolute/relative/bearing, typed-length unit, Tab cycling to annotations, navigation presets.
- **15. Tool palette** — not started (C++): the Split/Trim/Join and Slab/Slab-opening flyouts,
  pinning a panel as a permanent tab, and the panels-shrink-first option.

## Tests

Ran the touched Python suites (`test_console`, `test_cli`, `test_schedules`, `test_queries`,
`test_levels`, `test_settings`, `test_modify`, `test_checks`, `test_dxf`, `test_tags`) and the
touched Qt tests (`test_navigation`, `test_preferences`, `test_selection_tools`, `test_modify_tool`,
`test_main_window`) as I went; all passed. Translations were refilled with
`tools/fill_translations_es.py` and `check-translations` passes.

## Environment note

`pixi install` / `pixi run build` / `pixi run app-build` all succeed on this worktree; the app test
binaries run under `pixi run ctest` (they need the pixi environment's DLLs).
