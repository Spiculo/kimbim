# Drawing subset extractor — hand the serializer only what a drawing needs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** proposed. Grounded in the profiling and the spike findings below (2026-10-14).

**Goal:** generating a drawing must not pay to serialize the whole model. Today the child process opens a full IFC snapshot; on `ENTREGA-GOES - Centro Educativo.ifc` (95 MB, 1.66 M entities) writing that snapshot is ~20–31 s and opening it is ~9 s. The subset extractor writes a small, valid IFC containing only the drawing, the elements it shows and the structure they hang from, so the child opens it in milliseconds.

**Non-goals:** changing how a drawing looks (the SVG must be byte-identical on the corpus); changing the visible-element pass; the app-facing API.

**Done when:**
- every drawing kind (plan, section, elevation) generated from a subset is **byte-identical** to the same drawing generated from the full snapshot, on the house fixture and on the corpus (`golden`-style comparison in CI);
- the subset for the corpus South Elevation is < ~1 MB and the child opens + generates it in < 1 s (versus ~30 s today);
- the full-snapshot path stays behind a flag and remains the fallback.

---

## What profiling and the spike found (ground truth)

| Fact | Measurement / source |
|---|---|
| Snapshot write dominates | `model.write` 27–31 s; `to_string` + write ~19.6 s, for 95 MB / 1.66 M entities |
| Child open dominates the rest | `ifcopenshell.open(snapshot)` ~9 s |
| HLR itself is cheap once filtered | `generate()` internals 0.1–2 s for a filtered include |
| The persistent worker already removes the per-drawing open | `drawings.py` worker keeps the model; 2nd+ drawing at the same state < 1 s |
| **A naive subset changes the drawing** | `out.add(product)` on the house: SVG 21 297 chars vs 27 972 from the full model; `ifc:matrix3` sheet origin `(557, 463.74)` vs `(60, 70)` |
| Why | `file.add` copies **forward** references only. It does not copy: the reverse spatial containment (`IfcRelContainedInSpatialStructure`), decomposition (`IfcRelAggregates`, `IfcBuildingElementPart`), or type-driven geometry (`IfcRelDefinesByType`); the serializer places the drawing on the sheet from the spatial hierarchy, so a subset without it lands elsewhere. `IfcMappedItem`/`MappingSource` *are* copied (26/26 in the house). |
| Entity bloat is geometry | 456 k `IfcCartesianPoint`, 372 k `IfcPolyLoop`, 370 k `IfcFace` of 1.66 M — almost all belongs to products **not** in a given drawing's include |

## Architecture

Two ways to build the subset. **Recommend A2** — it reuses code that already round-trips.

### A1 — explicit reference closure over `file.add`
Walk a whitelist of reference attributes (representations, placements, materials, styles, contexts, units) plus the inverse relationships above, copying into a fresh `ifcopenshell.file`; reconstruct filtered `IfcRelContainedInSpatialStructure` / `IfcRelAggregates` / `IfcRelDefinesByType` so the products (and the drawing) sit where the serializer expects. More control, more edge cases to enumerate by hand.

### A2 — reuse `records.decompose` / `records.compose` (chosen)
`python/kimcad/records.py` already turns an `ifcopenshell.file` into canonical per-entity records (`decompose(f) -> (records, decomposer)`) and back (`compose(records) -> file`), deterministically, and `decompose(compose(records))` is a tested fixed point (`tests/python/test_records.py`). Build the subset as: decompose the model — **cached per drawing state** — then compose only the transitively-closed set of records the drawing needs.

- **Closure roots:** the drawing; the include set (`visibleFrom`); `IfcProject` (pulls units + representation contexts); the drawing's storey and its ancestors.
- **Closure edges:** records already carry resolved node references (`Decomposer` resolves them), so the closure is a graph walk over record references, not IFC attributes. A record is pulled when its node id is referenced by a kept record; inverse relationships (containment, aggregates, type assignment) are added as an explicit edge set for the spatial/decomposition/type rels.
- **Plan drawings** additionally pull the storey's `IfcAnnotation`, `IfcSpace`, `IfcGrid`, and the `IfcTypeProduct`s behind symbol objects, plus their containment/aggregation rels.
- **Validity:** `compose` output is parsed by `ifcopenshell.validate` in tests, so the subset is always a legal file.

If A2's per-record closure proves too slow to compute per state, fall back to A1 for the spatial rels only (they are the part `add` gets wrong) while keeping `add` for the rest.

### Where it plugs in
`python/kimcad/drawings.py::_snapshot()` becomes `_snapshot(guid, include_json)`:
- if the subset path is enabled **and** the include is non-empty, build/invalidate a subset keyed by `(state, include)`;
- otherwise keep writing the full snapshot (current behaviour, fallback).
The worker (`drawgen.py --worker`) is unchanged: it opens whatever path it is given and can be restarted with a new subset. `model_bounds` is already passed in, so the child never needs the full model for placement.

### Inputs inventory (must be enumerated and unit-tested)
Everything `drawgen` reads from the file, so the closure is provably complete:

- `settings_of(drawing)`, `_block(drawing)`, `marker(drawing)` — drawing pset + CSG block.
- `drawn_products(f)` — the include, minus `NOT_DRAWN`.
- `_storey(drawing, s)`, `storey_elevation(storey)`, `plan_camera` — storey entity/placement.
- `overlay` for plans: `door_swings`, `window_symbol` (need the host wall's layer set), `object_symbols` (type RepresentationMaps), `plan_annotations`, `room_stamps` (`_space_outline`, `Qto_SpaceBaseQuantities`, `KIMCAD_Room`), `markers`.
- serializer: representation contexts (Model/Body/MODEL_VIEW), units, `elevation-ref-guid`.

## Global Constraints

- The SVG from a subset must be **byte-identical** to the full-snapshot SVG (guarded by the harness below). If a case cannot match, that case keeps the full snapshot and is listed.
- Drawings stay model data (D60); the subset is derived data and never written into the IFC.
- Golden hashes of the sample files must not change.
- EN/ES strings; SPDX; DCO; headless CI (no GPU).
- The existing persistent worker and full-snapshot path remain the fallback and must keep working.

## Review Focus

1. The SVG-equality harness runs in CI on the house and one corpus file for plan, section and elevation.
2. The subset parses and validates (`ifcopenshell.validate`) for every drawing kind.
3. An "inputs inventory" test fails if `drawgen` reads a file attribute the closure does not pull (fuzz: build a subset, then assert generation does not raise).
4. Kill switch: `KIMCAD_DRAWING_SUBSET=0` (or a settings key) forces the full snapshot; the app behaves as today.

---

### Task 0: SVG-equality harness (do this first)
- [ ] `tests/python/test_drawgen_subset.py`: a `drawing_svg(kind)` helper that generates a drawing from the **full** model; a `subset_of(f, guids)` helper; assert `full_svg == subset_svg` for plan, section, elevation on `tools/make_house.py`.
- [ ] A `slow`/`golden` mark for the corpus variant (`ENTREGA-GOES`, `PARQUE BATLLE`): generate the full SVG once with `include` (never all elements — the serializer stack-overflows on this file with no include, and that is expected), then the subset SVG, compare.
- [ ] Record the two failure modes seen today (missing type/parts geometry; shifted `ifc:matrix3`) as `xfail` cases until fixed, so progress is visible.

### Task 1: Subset builder — spatial closure
- [ ] `records.py`: a `closure(records, roots, edges)` helper (or a new `subset.py`) that returns the kept node ids; unit-test on the house (a wall pulls its storey, building, site, project, units, contexts).
- [ ] Reconstruct filtered containment/aggregation/type rels in the subset (Chapter: `IfcRelContainedInSpatialStructure`, `IfcRelAggregates` for `IfcBuildingElementPart` and spaces, `IfcRelDefinesByType`).
- [ ] Make the section and elevation cases match first (no overlay), then plans.

### Task 2: Subset builder — geometry closure
- [ ] Follow `IfcMappedItem.MappingSource` (already copied by `add`, but the records walk must too) and type-driven geometry (`IfcTypeProduct.RepresentationMaps`).
- [ ] Follow `IfcStyledItem`/`IfcPresentationStyleAssignment`/materials (`IfcMaterialLayerSetUsage`, `IfcMaterialLayerSet`) so poché and projection styling match.
- [ ] Follow boolean/CSG operands (`IfcBooleanClippingResult`, `IfcCsgSolid`).

### Task 3: Plan overlays in the subset
- [ ] Pull the storey's `IfcAnnotation` (`KIMCAD_Annotation`), `IfcSpace` (+ `Qto_SpaceBaseQuantities`, `KIMCAD_Room`), `IfcGrid`, and library-object types (`KIMCAD_LibraryObject` + plan `RepresentationMap`).
- [ ] Match `door_swings`/`window_symbol`, which need the door/window's host wall layer set: pull the host wall and its material.
- [ ] Assert `overlay` produced no empty group where the full model had one.

### Task 4: Wire into `drawings.py` with cache + kill switch
- [ ] `_snapshot(guid, include_json)` builds a subset keyed by `(state, include)`, cached and evicted like the full snapshot; full snapshot stays the fallback (empty include, disabled flag, or builder failure).
- [ ] Cache the decomposed records per state (the decomposition is the expensive part of A2); drop them with `forget_snapshots`.
- [ ] Measure: subset size and child open+generate time for the corpus South Elevation; write the numbers in `docs/11-spike-results.md`.

### Task 5: App + verification
- [ ] End-to-end self-test on the corpus: `--create-drawings --open-drawing "South Elevation"` reports `drawing_s` and a new `drawing_snapshot_bytes`; assert the first drawing at a state drops from ~40 s to < ~3 s.
- [ ] `ifcopenshell.validate` the subset of every kind in tests; EN/ES strings if any UI text appears (should be none).
- [ ] Docs: doc 05 "As built"; a D-number; spike results; this plan's results section.

## Risks

| Risk | Mitigation |
|---|---|
| The serializer's paper placement depends on hierarchy/context in ways not yet mapped | Task 0's `xfail` cases; iterate until byte-identical; keep the full-snapshot fallback |
| `decompose` of 1.66 M entities is itself slow/memory-heavy | Cache per state; if too heavy, decompose lazily (roots + closure only) or fall back to A1 for the spatial part |
| Plans carry far more inputs (rooms, annotations, symbols, host walls) | Do sections/elevations first; gate plans behind equality tests; full snapshot for plans until they pass |
| A missed reference produces a subtly wrong drawing | Byte-equality harness + validate; never ship a subset that does not match |
| Nodes resolve differently after `compose` renumbers ids | `records` already guarantees a deterministic fixed point; assert `state_hash(decompose(subset)[0]) == state_hash(kept_records)` |

## Effort (rough)

- Task 0 (harness): ~0.5 day. Task 1 (spatial closure): ~1–1.5 days. Task 2 (geometry closure): ~1–1.5 days. Task 3 (plan overlays): ~1–1.5 days. Task 4 (wiring/cache/flag): ~1 day. Task 5 (verification/docs): ~0.5 day.
- Do the sections/elevations (Tasks 1–2) first: they give most of the win (plans are the harder overlay case).

## Open questions (owner)

1. **Accept byte-identical (slower to get right) or visually-equal (faster, riskier)?** Recommend byte-identical.
2. **Should the subset be persisted** (`.kimcad/drawings/<guid>/model.ifc`) so reopening a versioned project is instant, as slice 14's cache note proposed? Recommend yes, as a follow-up task.
3. Any corpus files beyond the two present that should be added to the CI matrix?
