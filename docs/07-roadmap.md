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

The spike code lives in [`spikes/`](../spikes/README.md).

## App track

### M0 — Foundations ✅
Repo, LICENSE, CMake, pixi environment, CI (Windows + Linux), Qt 6 main window, IfcOpenShell through embedded Python, `kimcad-app --version`, i18n pipeline (English + Spanish, `tr()` + Qt Linguist, CI check for untranslated strings). Done in Slice 2 ([plan](superpowers/plans/2026-10-04-slice2-desktop-viewer.md)).

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

Measured (`kimcad-app --self-test`, integrated GPU): Duplex at 60 fps (vsync); a 100k-element model loads in about 35 s and renders at 150 fps with vsync off.

Not yet: colour by property, walk mode, measure, saved views, a "show spaces" toggle, section-box handles (the box is around the selection), and a fix for vsync double-waits in a bare top-level viewport.

### M2 — Object data editor 🟡 (core done)
Command/undo framework, property and pset editing, materials, types, classifications, bulk edit, schedules, save IFC (Plain mode).
**Exit:** edit → save → reopen preserves everything; round-trip tests pass on the saved file.

Done in Slice 3 ([plan](superpowers/plans/2026-10-05-slice3-navigation-and-data-editor.md)):
- edit names and property values for one or many elements (bulk edit), with values keeping their IFC type;
- add and remove properties and property sets (standard templates or custom);
- see whether a value comes from the element's type; edit the type value deliberately or reset an override (Slice 3b, D50);
- undo/redo, one step per action;
- Save / Save As with an unsaved-changes guard; the saved file round-trips;
- Revit/ArchiCAD navigation; multi-select by Ctrl/Shift-click, box and tree.

Not yet: materials, types (assign/edit), classifications, schedules, quantity take-off.

### M3 — Modeler 🟡 (in progress)
Levels and grids, walls (layered, joins), slabs, openings, doors/windows, columns/beams, snapping, precise input, move/rotate/stretch.
**Exit:** an architect can model a small 2-storey house from scratch and export valid IFC that opens in at least two other tools (e.g. Bonsai, a commercial viewer).

Slices: **4 ✅ new project, levels, walls** ([plan](superpowers/plans/2026-10-05-slice4-walls-and-levels.md)) → 5 slabs, openings, doors/windows → 6 columns/beams, grids, move/rotate/stretch → 7 the exit test.
Done in Slice 4: new IFC4 project (mm), levels, plan view, layered wall types, wall tool (snapping, typed lengths, ortho), L/T joins, delete, live 3D updates with undo/redo.

### M4 — Libraries, cloning, drawings
Library browser and bundled library, copy/paste/duplicate/array/mirror/copy-to-storeys, plan/section/elevation generation, annotations, sheets, PDF export.
**Exit:** the M3 house produces a plan, a section and an elevation on a sheet, exported to PDF.

## Repo track

### R0 — Workspace ✅
Cargo workspace, crates skeleton, `kimcad` CLI skeleton, CI. Done in Slice 1 ([plan](superpowers/plans/2026-10-04-slice1-cli-versioning.md)).

### R1 — Canonical records ✅ (Python)
Done in Slice 1 in Python (`kimcad.records`), byte-identical to the spike golden hashes. A Rust port waits until speed demands it.

Record decomposition, canonical JSON, BLAKE3 references, records → IFC export with deterministic step IDs.
**Exit:** corpus round-trip is a fixed point; golden hashes match on Windows and Linux.

### R2 — Store and history ✅ (except tags)
Done in Slice 1: `init / commit / status / log / show / export / branch / switch` through the Rust store. Tags come next.

`kimcad init / import / commit / log / show / export / branch / switch / tag` on the gitoxide-backed store; local cache.
**Exit:** import 100k-object model, change one property, commit; the new commit adds only a handful of objects.

### R3 — Diff 🟡
Record-level diff (added/modified/removed per object) done in Slice 1. Property-level detail and speed work remain.

Tree diff, per-category classification, property-level changes, JSON and human output.
**Exit:** diff time depends on the size of the change, not the size of the model (benchmark).

### R4 — Merge and reconciliation
Three-way merge with conflict model, integrity pass, conflict serialization for the UI; GlobalId/Tag/heuristic reconciliation with report.
**Exit:** merge test suite (including ported `ifcmerge` cases) passes; re-importing a Revit-exported file with regenerated GlobalIds keeps more than 95% of identities on the corpus pair.

## M5 — Versioned projects in the app
Enable/disable versioning, Save version, history timeline, Compare (viewport coloring and before/after), design options, milestones, Combine options with conflict UI, object history panel, re-import with reconciliation review.
**Exit:** two design options of the house are created, edited separately, compared and combined with one conflict resolved in the UI.

## M6 — Checking
Schema validation, IDS checks with IfcTester, clash between selections, configurable local pre-commit checks.

## After the MVP: full IFC4X3
New IFC4X3 projects, schema upgrade command, IFC4X3 test suites become release-blocking ([02](02-data-model-and-format.md#ifc-schema-version)).

## Then
See [08-future.md](08-future.md). Push/pull to Git remotes is the cheapest next step, because the storage is already Git.
