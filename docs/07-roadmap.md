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

| Id | Question | Done when |
|----|----------|-----------|
| S1 | Can C++ host and embedded `ifcopenshell` Python share one in-memory `IfcFile`? | Working prototype or a documented alternative ([01](01-architecture.md#python)) |
| S2 | Can the OCCT AIS viewer handle 100k objects as mesh arrays? | Benchmark report ([05](05-geometry-rendering-drawings.md#phase-1-renderer-opencascade-visualization-ais--v3d-inside-qt)) |
| S3 | Does the record decomposition round-trip the test corpus losslessly? | Python prototype passes on corpus ([02](02-data-model-and-format.md#round-trip-guarantee)) |
| S4 | Do Windows and Linux produce identical record hashes? | Same hashes in CI on both ([02](02-data-model-and-format.md#determinism)) |
| S5 | How do `gix` writes perform at 1M blobs: commit time, repo size, checkout-to-model time? | Benchmark report ([03](03-versioning.md)) |

S3 and S4 can be prototyped in **Python with `ifcopenshell`** before any Rust is written. That is the cheapest way to validate the data model.

## App track

### M0 — Foundations
Repo, LICENSE, CMake + Corrosion, pixi environment, CI (Windows + Linux), Qt main window shell, IfcOpenShell linked, embedded Python, `kimcad --version`, i18n pipeline (English + Spanish, `tr()` + Qt Linguist, CI check for untranslated strings).
**Exit:** CI builds and launches an empty window on both OSs from a clean checkout with one command.

### M1 — Viewer
Open IFC, tessellate in the background, 3D viewport, model tree (spatial + class), property panel (read-only), selection, hide/isolate, section box, clipping planes, storey navigation, search/filter.
**Exit:** opens every file in the test corpus; the 100k-object file stays interactive.

### M2 — Object data editor
Command/undo framework, property and pset editing, materials, types, classifications, bulk edit, schedules, save IFC (Plain mode).
**Exit:** edit → save → reopen preserves everything; round-trip tests pass on the saved file.

### M3 — Modeler
Levels and grids, walls (layered, joins), slabs, openings, doors/windows, columns/beams, snapping, precise input, move/rotate/stretch.
**Exit:** an architect can model a small 2-storey house from scratch and export valid IFC that opens in at least two other tools (e.g. Bonsai, a commercial viewer).

### M4 — Libraries, cloning, drawings
Library browser and bundled library, copy/paste/duplicate/array/mirror/copy-to-storeys, plan/section/elevation generation, annotations, sheets, PDF export.
**Exit:** the M3 house produces a plan, a section and an elevation on a sheet, exported to PDF.

## Repo track

### R0 — Workspace
Cargo workspace, crates skeleton, `kimcad` CLI skeleton, CI.

### R1 — Canonical records
Record decomposition, canonical JSON, BLAKE3 references, records → IFC export with deterministic step IDs.
**Exit:** corpus round-trip is a fixed point; golden hashes match on Windows and Linux.

### R2 — Store and history
`kimcad init / import / commit / log / show / export / branch / switch / tag` on the gitoxide-backed store; local cache.
**Exit:** import 100k-object model, change one property, commit; the new commit adds only a handful of objects.

### R3 — Diff
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
