# 07 — Roadmap

There is no timeline (owner decision). Milestones are ordered by dependency, and each one has an **exit criterion** that has to be demonstrably true before the milestone counts as done.

Two tracks run in parallel and meet at milestone M5:

```text
APP TRACK (C++/Qt, IfcOpenShell)          REPO TRACK (Rust)
M0 Foundations ─────────────────────────── R0 Workspace + CI
M1 Viewer                                  R1 Canonical records + round-trip
M2 Object data editor                      R2 Git-backed store, commit, log
M3 Modeler                                 R3 Diff
M4 Libraries + cloning + drawings          R4 Merge + reconciliation
          └──────────────┬──────────────────────┘
                 M5 Versioned projects in the app
                         │
                 M6 Checking (IDS, schema, clash)
                         │
                 Future (see 08): remotes UI, live collab, P2P, AI…
```

## Spikes (do first; each is small, throwaway, and documented)

| Id | Question | Status ([results](11-spike-results.md)) |
|----|----------|--------|
| S1 | Can C++ host and embedded `ifcopenshell` Python share one in-memory `IfcFile`? | ✅ Yes on Linux (conda-forge build). Windows run still to do |
| S2 | Can the OCCT AIS viewer handle 100k objects as mesh arrays? | ✅ Yes, batched: 110k elements at 32 fps, 232 MB on an integrated GPU; per-element objects fail (2.7 fps, 3.2 GB) (D42, D43) |
| S3 | Does the record decomposition round-trip the test corpus losslessly? | ✅ Yes: 77/77 valid files lossless, fixed point, deterministic export (D34–D36) |
| S4 | Do Windows and Linux produce identical record hashes? | ✅ Yes: 77/77 identical state hashes and IFC exports |
| S5 | How do `gix` writes perform at 1M blobs: commit time, repo size, checkout-to-model time? | ✅ Viable with packs only and no deltas (D39) |
| S6 | Is IfcOpenShell's SVG serializer good and fast enough for KimBim's drawings (Slice 14 risk check)? | ✅ Quality yes; speed needs visible elements only, polygon HLR and a child process (D60, proposed) |

The spike code lives in [`spikes/`](../spikes/README.md).

## App track

### M0 — Foundations ✅
Repo, LICENSE, CMake, pixi environment, CI (Windows + Linux), Qt 6 main window, IfcOpenShell through embedded Python, `kimbim-app --version`, i18n pipeline (English + Spanish, `tr()` + Qt Linguist, CI check for untranslated strings). Done in Slice 2 ([plan](superpowers/plans/2026-10-04-slice2-desktop-viewer.md)).

### M1 — Viewer ✅ (core)
Done in Slice 2:
- open IFC (File→Open or command line);
- background tessellation with progressive batches;
- OCCT 3D viewport (orbit, pan, zoom; batched elements with per-element picking, D42);
- model tree (spatial, with search by name, type or GlobalId);
- read-only properties panel;
- two-way selection sync;
- hide, isolate, show all (also per storey from the tree);
- plan cut with a height control, and a section box.

Measured (`kimbim-app --self-test`, integrated GPU): Duplex at 60 fps (vsync); a 100k-element model loads in about 35 s and renders at 150 fps with vsync off.

Not yet: colour by property, walk mode, measure, saved views, a "show spaces" toggle, section-box handles (the box is around the selection), and a fix for vsync double-waits in a bare top-level viewport.

### M2 — Object data editor ✅
Command/undo framework, property and pset editing, materials, types, classifications, bulk edit, schedules, save IFC (Plain mode).
**Exit:** edit → save → reopen preserves everything; round-trip tests pass on the saved file.

Done in Slice 3 ([plan](superpowers/plans/2026-10-05-slice3-navigation-and-data-editor.md)):
- edit names and property values for one or many elements (bulk edit), with values keeping their IFC type;
- add and remove properties and property sets (standard templates or custom);
- see whether a value comes from the element's type; edit the type value deliberately or reset an override (Slice 3b, D50);
- undo/redo, one step per action;
- Save / Save As with an unsaved-changes guard; the saved file round-trips;
- Revit/ArchiCAD navigation; multi-select by Ctrl/Shift-click, box and tree.

Done since: building materials, surfaces and composites (D96), schedules and quantities with CSV/XLSX (D77), object types from the library (D86), and the M2 leftovers in D106: **classifications** (Uniclass 2015, OmniClass and local systems; `IfcClassification`/`IfcClassificationReference`, assign and unassign) and a **type manager** (list types, make one from the selection, assign, edit name/description/tag and properties, *update all* removes occurrence overrides). Both have Model menu dialogs and CLI/agent tools; the Properties panel lists the selection's classifications. Tests: `test_classifications.py`, `test_types.py` and the app's `test_types`.

### M3 — Modeler ✅ (automatic exit checks pass; the owner's check in Bonsai + a commercial viewer is pending — [12](12-m3-exit.md))
Levels and grids, walls (layered, joins), slabs, openings, doors/windows, columns/beams, snapping, precise input, move/rotate/stretch.
**Exit:** an architect can model a small 2-storey house from scratch and export valid IFC that opens in at least two other tools (e.g. Bonsai, a commercial viewer).

Slices: **4 ✅ new project, levels, walls** ([plan](superpowers/plans/2026-10-05-slice4-walls-and-levels.md)) → **4b ✅ view quality** ([plan](superpowers/plans/2026-10-05-slice4b-view-quality.md)) → **5 ✅ slabs, openings, doors/windows** ([plan](superpowers/plans/2026-10-05-slice5-slabs-doors-windows.md)) → **6 ✅ columns/beams, grids, move/rotate/stretch** ([plan](superpowers/plans/2026-10-05-slice6-structure-grids-editing.md)) → **7 ✅ the exit test** ([plan](superpowers/plans/2026-10-06-slice7-m3-exit-two-storey-house.md), [12](12-m3-exit.md)).
Done in Slice 6: profile-based columns and beams, grid axes per level (auto tags, snapping), move/rotate with joined walls following (Ctrl detaches, D54), stretch wall ends, wall height, sliding and resizing doors/windows — all keeping GlobalIds.
Done in Slice 5: layered slab types, slabs by outline (concave too) or from a closed wall loop (outer faces), parametric doors and windows in walls with real openings, cascading deletes; a saved test house (walls, slab, door, window) validates against the IFC4 schema with 0 issues.
Done in Slice 4: new IFC4 project (mm), levels, plan view, layered wall types, wall tool (snapping, typed lengths, ortho), L/T joins, delete, live 3D updates with undo/redo.

### M4 — Libraries, cloning, drawings ✅ (the exit test passes in CI, `pixi run m4`)
Library browser and bundled library, copy/paste/duplicate/array/mirror/copy-to-storeys, plan/section/elevation generation, annotations, sheets, PDF export.
**Exit:** the M3 house produces a plan, a section and an elevation on a sheet with a title block, exported to PDF. CI checks this automatically, as it checks M3.

Slices (numbering continues after the architect-feedback track, Slices 9–13): **14 ✅ sections and elevations** → **15 ✅ plan drawings and annotation on drawings** ([plan](superpowers/plans/2026-10-07-slice15-plan-drawings-annotation.md)) → **16 ✅ sheets and PDF export (= M4 exit)** ([plan](superpowers/plans/2026-10-07-slice16-sheets-pdf.md)) → **17 ✅ everyday editing** (copy/paste, duplicate, Ctrl+drag copy, mirror, arrays, offset; [plan](superpowers/plans/2026-10-07-slice17-everyday-editing.md)).
Libraries: the Library panel, Object tool and a bundled parametric library (D86); authoring objects without code is done: the `.kimobj` engine (D99), saved versions (D100) and the Object Editor (D101) ([16](16-parametric-objects.md)).
M4 comes before the end of M5 (owner plan, 2026-10-07): drawings are what an architect hands to a client, and Combine options (Slice 22) needs the R4 merge engine, which is easier to judge once real projects with drawings exist.

### After M4: modeling gaps
Slices **18 ✅ rooms and areas** (`IfcSpace` from the surrounding walls, room stamps, room schedule with CSV; [plan](superpowers/plans/2026-10-07-slice18-rooms.md)) → **19 ✅ roofs** (flat, shed, gable, hip and per-edge slopes from a footprint; walls trimmed to the roof; [plan](superpowers/plans/2026-10-07-slice19-roofs.md)). Then M5 resumes.

## Repo track

### R0 — Workspace ✅
Cargo workspace, crates skeleton, `kimbim` CLI skeleton, CI. Done in Slice 1 ([plan](superpowers/plans/2026-10-04-slice1-cli-versioning.md)).

### R1 — Canonical records ✅ (Python)
Done in Slice 1 in Python (`kimbim.records`), byte-identical to the spike golden hashes. A Rust port waits until speed demands it.

Record decomposition, canonical JSON, BLAKE3 references, records → IFC export with deterministic step IDs.
**Exit:** corpus round-trip is a fixed point; golden hashes match on Windows and Linux.

### R2 — Store and history ✅
Done in Slice 1: `init / commit / status / log / show / export / branch / switch` through the Rust store; Slice 20 added `tag` (annotated tags = milestones) and `blame` (object history).

`kimbim init / import / commit / log / show / export / branch / switch / tag` on the gitoxide-backed store; local cache.
**Exit:** import 100k-object model, change one property, commit; the new commit adds only a handful of objects.

### R3 — Diff ✅
Record-level diff (added/modified/removed per object) was done in Slice 1. D105 adds the rest: `Project.diff_details` explains every modified element (attributes, including **Placement** and **Geometry** by name, and every property set's properties with old/new values), groups the change by IFC class and by level (the tree), and the CLI/agent `versions diff` prints it as text or JSON (`--detail`). The tree diff now works from Git tree ids, skips identical subtrees and reads only the changed records; the app also keeps the decomposed working model shared by `version_changes`, Compare with WORKING and Save version, so it is decomposed once instead of three times.

**Exit:** met. On one renamed wall (`Project.diff`), 50 walls took 0.053 s and 8,000 walls 0.074 s (not proportional to the model); property detail took 0.15 s and 1.5 s respectively (it indexes the object records for the property sets). `tests/python/test_diff.py` checks the detail, the CLI and a 20× model with a one-element diff; `test_versioning_app.py::test_compare_and_save_reuse_one_decomposition` checks the single decomposition. The D102 Clinic compare cost was the repeated full decomposition; it is now done once per working state (the remaining first decomposition is the R1/Python-decomposer limit).

### R4 — Merge and reconciliation ✅
Slice 21 ([plan](superpowers/plans/2026-10-07-slice21-merge-engine.md)): three-way record merge with the conflict model, integrity pass and IFC validation, `kimbim merge`, and ifcmerge's cases ported (fixtures in `tests/fixtures/ifcmerge`). D104 adds the reconciliation half: `kimbim versions import FILE -m MESSAGE [--accept-heuristic] [--dry-run]` matches the imported products by GlobalId, then class + Tag, then a heuristic (class, name, type, storey, nearby placement), gives matched objects the existing GlobalIds and commits the result as an ordinary version. `--dry-run` prints the report, `--accept-heuristic` applies the review matches, and `--report OUT` writes the JSON.

Three-way merge with conflict model, integrity pass, conflict serialization for the UI; GlobalId/Tag/heuristic reconciliation with report.
**Exit:** met: the merge suite (including the ported `ifcmerge` cases) passes; on the Duplex corpus pair with every GlobalId regenerated, reconciliation keeps **99.66%** of product identities (232 by Tag, 62 by heuristic, 1 new and 1 missing of 295 products), and `tests/python/test_reconcile.py::test_the_duplex_reimport_keeps_most_identities` checks it (`pytest -m slow`).

## M5 — Versioned projects in the app ✅ (exit test automated: `pixi run m5` + app test `m5ExitCombineOptions`)
Slices: **8 ✅ enable/open, Save version, History, Compare (colours + list), design options** → **20 ✅ milestones (tags), object history, before/after, delete option** ([plan](superpowers/plans/2026-10-07-slice20-milestones-history.md)) → **21 ✅ R4 merge engine** (repository side; [plan](superpowers/plans/2026-10-07-slice21-merge-engine.md)) → **22 ✅ Combine options** (conflict UI: this option or the other per element and property, the combined model as a 3D preview, commit with two parents; [plan](superpowers/plans/2026-10-07-slice22-combine-options.md)) = M5 exit. (These were called 9 and 10 before the architect-feedback track took Slices 9–13.)

Enable/disable versioning, Save version, history timeline, Compare (viewport coloring and before/after), design options, milestones, Combine options with conflict UI, object history panel, re-import with reconciliation review.
**Exit:** two design options of the house are created, edited separately, compared and combined with one conflict resolved in the UI.

## Archicad parity track ✅ (D74–D98, 2026-10-09 to 2026-10-22)
After M5 the owner asked for Archicad feature parity before checking. Done: renovation status (D74), one-row window chrome and the Versions menu (D75), view cube, preset views and perspective (D76), schedules (D77), selection tools (D78), measure and the levels table (D79), split/trim/join (D80), checks (D81), the Python console (D82), DXF export (D83), 2D drafting (D84), underlays (D85), the object library (D86), tags and more dimensions (D87), stairs, ramps and railings (D88), input aids and touchpad (D89), the compact palette (D90), the owner's answers and configurable behaviour (D91–D93), the rename to KimBim (D94), 3D cut planes (D95), materials (D96), wall and object configuration, curved walls (D97) and tooling (D98). Status per tool: [14](14-tool-inventory.md).

## M6 — Checking ✅ (D81 in-app checks; D103 pre-commit checks)
Schema validation, IDS checks with IfcTester, clash between selections, configurable local pre-commit checks.

Done in D81: the Checks panel runs schema validation (EXPRESS rules included), IDS files kept in the project, hard and clearance clashes between classes or Find & Select criteria, and model checks (duplicates, rooms, zero-length walls, elements not on a level, hostless openings), with HTML/JSON reports.
Done in D103 (M6 exit): *Before saving a version* in the Checks panel picks each check as Off, **Warn and save** or **Block the save** (project setting `precommit_checks`). A blocking check with any issue stops the save and lists the elements (in the app's dialog and in the bridge reply); a warning check saves and its result is recorded as `checks.json` in the version's tree and shown from History › Checks...
**Exit:** met by `tests/python/test_precommit.py` and the app test `test_checks`'s `precommitChecksBlockAndRecord`.

## After the MVP: full IFC4X3
New IFC4X3 projects, schema upgrade command, IFC4X3 test suites become release-blocking ([02](02-data-model-and-format.md#ifc-schema-version)).

## Next (2026-10-28)
Done since: the Object settings dialog and saved object versions (D100), the Object Editor (D101, parametric object authoring), agent tools (D102), **M6 pre-commit checks** (D103), **R4 reconciliation** (D104, re-import with regenerated GlobalIds; 99.66% identities kept on the Duplex pair), **R3 property-level diff and a change-sized diff** (D105) and the **M2 leftovers** (D106, classifications and the type manager). Git remote push/pull (D107), imperial units (D108) and the owner's four gaps (D109: DWG in/out through LibreDWG, curtain walls, sloped slabs and slab edges) are in. The remaining [14](14-tool-inventory.md#largest-gaps) items are detail views/markers, title block templates, schedules on sheets, terrain and BCF; curtain walls have a palette tool; slopes and edges are Model menu actions. The owner's M3 check in Bonsai and a commercial viewer is still open ([12](12-m3-exit.md)); [14](14-tool-inventory.md#largest-gaps) asks the owner to confirm or reorder the list.

## Then
See [08-future.md](08-future.md). Git remote push/pull is in (D107); a merge-aware pull and the remotes UI are the next remote steps. The owner reorders the remaining tool gaps in [14](14-tool-inventory.md#largest-gaps).
