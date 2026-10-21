# Track A notes: plans, renovation, annotation (2026-10-20)

Worktree `plans-renovation`; branch `plans-renovation`. This is the finished round 2 of the track
(the first run stopped when the provider ran out of credit).

## Built

1. **Preset views zoom to fit** — view cube faces and Alt+1…0 fit the whole model (D91).
2. **Temporary and Auxiliary renovation statuses** — added to Existing / To be demolished / New,
   including the filters, the Model › Renovation status UI and their default looks (Temporary cyan
   dashed, Auxiliary magenta dashed; D93).
3. **Unmarked IFC elements default to Existing** — the open-IFC offer defaults to marking them, and
   `ifc_status_default` is the project setting (leave, existing or demolish).
4. **Doors and windows take their host wall's status** — when placed and when the wall changes,
   unless the opening's status was set explicitly.
5. **Renovation looks as named style presets** — pen, colour, line type and fill per status, edited in
   project settings, with the `Uruguay` region preset as the default (D93).
6. **Sheet legends list every rule of the purpose when they fit**, else only the rules used;
   `legend_mode` chooses auto / all / used.
7. **Plan slice at 1.20 m** — project setting, per-level override and per-view override; the plan tab
   has no cut slider (D91).
8. **Show on levels** — `KIMBIM_ShowOn.Levels` stores `home`, `up[:N]`, `down[:N]`, `all`,
   `range:LO..HI` or an expression over `d`. Plans honour it. **View depth below** is now complete:
   `view_depth` defaults to 0.5 m, `view_depth_levels` overrides it per level, a plan drawing can
   override it (`set_view_depth`) and an element can override it with
   `KIMBIM_ShowOn.DepthBelow` (`set_element_view_depth`). The app's mesh plan pass opens the camera to
   the deepest override and the new `visible_on` bridge filters the visible set by the level rules.
   The project-settings dialog edits the project default.
9. **Plan symbol or 3D body** — project setting and per-object `KIMBIM_LibraryObject.PlanDisplay`
   (D91).
10. **Marker and tag templates with `$keywords$`** — `$mark$`, sizes, sill, type, level and any
    `$Pset.Name$`; the default door/window marker is the code alone (D93).
11. **Insulation fill defaults to loops** — zigzag is still available.
12. **Scales** — 1:500, 1:100, 1:50, 1:20 built in; users add scales in project settings.
13. **Sheets fully editable** — free texts were finished in the first run. In this run the **title
    block is a placed item**: it is dragged like a drawing and its fields (project, project number,
    client, address, sheet title, sheet number, scale, date, issued by) are edited from its right-click
    menu. Both its position and the field overrides are stored in the sheet's `Description` JSON, so
    they travel with the sheet/IFC and undo. A field equal to its derived value is not stored as an
    override, so later project-info edits still show. The legend was already movable (D74); it stays
    that way and the title block is excluded from "Remove from sheet".

## Skipped / limits

- Per-level and per-element view depth have no dedicated UI yet: they are project settings/psets and
  bridge calls (`set_view_depth`, `set_element_view_depth`). The project default is in Project
  settings.
- The app's mesh plan pass applies the element depth override by opening the camera to the deepest
  override and then filtering by `visible_on`; it does not re-clip each element at its own depth, so a
  deeper element with an override can make the hidden-line pass slightly larger than strictly needed.
- Legends can be moved but their rows are still generated from the purpose (the request for this
  round was moving them, not editing their rows).
- No new region presets beyond Uruguay.

## Tests

Final full runs, one at a time:

- `pixi run test`: **598 passed, 82 deselected** (12 min 7 s). Includes SPDX, Rust and Python. No
  failures.
- `pixi run app-test`: **56/56 passed** (6 min 32 s). No failures.
- `pixi run python tools/check_translations.py`: **translations OK**.

One environmental detail: running `build/app/test_main_window.exe` directly (without the pixi task)
reports two window-exposure failures on this headless session:

```
FAIL!  : TestMainWindow::narrowTitleBarCollapsesTheMenus() 'QTest::qWaitForWindowExposed(&w)' returned FALSE.
FAIL!  : TestMainWindow::titleBarShowsTheDocument() 'QTest::qWaitForWindowExposed(&w)' returned FALSE.
```

`pixi run app-test` sets up the Qt environment and both pass there, so this is not a code failure.
