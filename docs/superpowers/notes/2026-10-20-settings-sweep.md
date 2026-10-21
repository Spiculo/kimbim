# Settings sweep (Track B, D92) — 2026-10-20

Branch `settings-sweep`. One commit per backlog item; tests were written with each change. The D92
list in `docs/open-questions.md`, "Resolved (2026-10-20)", is the backlog; this file records what is
built and what is deliberately left open.

## What is built

### 1. Python console — done (`6b7e803`, `380551c`)
- Every console run is one undo step: `console._execute_all` opens one step, bridge commands and
  direct edits join it, a run that changed nothing leaves no empty step
  (`app_bridge._end_step_without_change`), and a failed or stopped run rolls back. `edit()` joins
  the run's step (it still works stand-alone).
- A run with **no model open** opens no step (a script may build its own model, as `make_house.py`
  does): this was a round-2 fix found by `test_console`.
- Headless CLI: `kimbim run script.py model.ifc [-o OUT] [--select GUID]`.
- Tests: `tests/python/test_console.py`, `tests/python/test_cli.py`, `app/tests/test_console.cpp`.

### 2. View cube — done (`572b6f8`, `fffcbaa`, `0d5dc63`, `0453f4c`)
- Home view (`Viewport::useCurrentViewAsHome`, `home_view` preference, south-east iso default).
- Perspective field of view (`field_of_view`, 45° default).
- North arrow on plans (view option, shown once true north is set).
- Mesh-vertex snaps preference (off) and the engine's `snap_data(..., mesh_vertices)`.
- The Levels dialog and Measure readout offer the new options: move-above on an elevation change,
  insert fit-between (Levels dialog), and the project area unit.

### 3. Window chrome — done (`75005fa`)
- `title_bar_levels`, `title_bar_cut`, `title_bar_versions` preferences; Save version in File too.

### 4. Schedules — done (`659fc4e`)
- Inside/outside face length columns; per-schedule `min_opening_area` (0) and `unit` (m/cm/mm);
  group-by fields per schedule (already existed per scheme).

### 5. Selection — done (`3f218f2`)
- Select similar scope preference; Ctrl+A with a tool selects that tool's class, otherwise all;
  box mode (by direction or Archicad partial/entire); Find & Select "Include hidden".

### 6. Measure, levels and tags — done (`b861b0c`, `0d5dc63`, `0453f4c`, `cf54556`, `005c870`)
- Area unit project setting; mesh-vertex snaps; elevation moves levels above; fit-between insert;
  Levels dialog offers both insert policies.
- Level dimension reference: project zero (default), the level it is on, sea level (project zero's
  `sea_level` datum). Automatic level/spot dimensions follow it immediately, in plan views,
  drawings and DXF.
- North arrow (circle/needle/plain arrow) and scale bar (bar/line) symbols are project settings,
  settable in Project settings.
- Tag all asks for categories (defaults: doors, windows, walls; OK is disabled with none checked);
  orphan tags delete or keep with "?"; angle and radius decimals.
- Marker/tag templates themselves are Track A's.

### 7. Split, trim, join — done (`b8b6ff1`, `f63e5e6`)
- Trim that would drop an opening: refuse (default), delete or keep inside.
- Split/trim pieces joined unless the preference is off (Ctrl inverts).
- Merge keeps the first element's properties (default) or refuses when they differ.
- Imported walls: rebuild with KimBim's shape (default) or keep the imported body and cut it.

### 8. Checks — done (`0cc19df`, `47169bf`)
- Check tolerance (2 mm) and clearance (50 mm) in project settings; ignore joined walls (on).
- Partial-overlap duplicates (off); IDS embedded (default) or linked from a shared folder.

### 9. DXF export and underlays — done (`27027c6`, `aea239d`)
- Layer scheme: US NCS, ISO 13567 or one layer per pen; poché layer option; colour mode exact/ACI/
  lineweight; all in the export dialog.
- Underlay placement centred (default) or survey coordinates; opacity/grey/tint defaults in
  Preferences; a layer per underlay; underlay edits are undo steps.

### 10. 2D drafting — done (`5827451`)
- "Keep rectangles rectangular" preference (off): dragging a corner follows the two adjacent sides.
- A fill's outline pen can be its own pen or none (plan view, drawings and DXF); the fill keeps its
  pattern/background.
- Pattern scale per fill: paper (default) or model.

### 11. Object library — done (`56f838d`)
- Editing a parameter changes the selection (default) or asks when the object's type has other
  placements; `scope="type"` changes every placement.
- A library object can declare its own insertion origin (`library.define(..., origin=(x, y))`); the
  library default remains the left front corner.

### 12. Stairs — done (`3ba4508`)
- Project defaults: riser target, fixed tread or from 2R+G (625 mm minus twice the riser, never
  under the code minimum's tread).
- Flight split (risers in the first flight) and U-stair well width are per stair, readable and
  editable in Properties; `set_stair_params` accepts both.
- Floor opening: whole outline (default) or headroom only (the part of the footprint less than
  2.0 m below the upper floor).
- Drawing settings: plan arrow at the top (default), bottom or both; riser numbers on or off. They
  are kept in each stair's plan data and refreshed when the settings change.

### 13. Tracker and navigation — done (`cde5a36`)
- Tracker always (default), while typing, or off (off leaves the length field's old typing path).
- Angle input absolute from east (default), relative to the previous segment, or bearing clockwise
  from north (live and typed).
- Typed lengths in metres (default) or the project unit (tracker, length field and drafting's
  typed input such as `4<90` and `width;height`).
- Tab cycling reaches annotations and drafting shapes (on).
- Navigation presets: automatic, mouse, Mac trackpad, precision touchpad (the last pans more finely).

### 14. Tool palette — done (`1e7518d`)
- Split/Trim/Join and Slab/Slab opening share flyout buttons.
- Any side panel can be pinned from View > Panels as a permanent tab (no close button, cannot be
  hidden); pins are remembered in preferences.
- "Shrink the panels first on small screens" preference (off): below 1100 px the side panels step
  down to 168/220 px before the views take the space.

## What was skipped or left narrow

- **Tag/marker templates** (wall tag by property, stamp fields, marker styles) are Track A's.
- **Stair headroom opening** is a plan-footprint approximation (2.0 m clearance per flight and
  landing), not a swept 3D headroom volume.
- **North arrow/scale bar symbol choice** is project-wide; there is no per-view or per-symbol
  override yet.
- **Object origins** are a library-definition value: the bundled library stays left front, office
  Python objects can set one, but there is no UI to edit an origin.
- **Pinned panels** cover the side panels; the rare dialogs (Find & Select, Checks, Library,
  Schedules) are not dock panels, so they cannot be pinned.
- **Tab cycling** includes annotations for selection; the Tab highlight is still drawn for model
  elements only (annotations select correctly when clicked after cycling).
- **PDF/DXF underlay** display itself and explode/clip remain as before (explode/clip is backlog).

## Tests

- Full Python suite: `pixi run test` → **605 passed, 82 deselected**.
- Full Qt suite: `pixi run app-test` → **56/56 passed** (including the self-test screenshots).
- Translations: `pixi run cmake --build build/app --target update_translations`, then
  `python tools/fill_translations_es.py`; `python tools/check_translations.py` → translations OK.
- `test_console` (Qt) exposed a round-1 regression: with no model open the console tried to open an
  undo transaction; fixed in `380551c`.

## Environment note

`pixi install`, `pixi run build` and `pixi run app-build` succeed in this worktree. Qt tests run
through `pixi run ctest` (they need the pixi environment's DLLs).
