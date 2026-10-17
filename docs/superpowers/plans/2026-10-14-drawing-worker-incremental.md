# Drawing worker — incremental edit stream

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** proposed. Grounded in the 2026-10-14 profiling.

**Goal:** after the first drawing, editing the model must not re-serialize or re-open anything. Today any edit that reaches the drawings writes a fresh full-model snapshot (~20–31 s on a 95 MB / 1.66 M-entity file) and restarts the worker (open ~9 s), so every edit costs ~30 s before the next drawing can be generated. With an incremental stream the worker keeps its model open and applies only what changed.

**Non-goals:** the subset extractor (separate plan); the visible-element pass; sheet composition.

**Done when:**
- moving one wall, then opening a drawing, costs well under a second on the house and a few seconds at most on the corpus (no snapshot write, no worker restart);
- after an edit (and after undo/redo), the worker's model is provably the same as the app's (a state hash matches) and any drawing generated from it is **byte-identical** to a drawing generated from a full snapshot;
- on any divergence the worker falls back to a full reload, so the app is never wrong.

---

## What profiling found (ground truth)

| Fact | Source |
|---|---|
| A worker already survives across drawings at one state | `drawings.py` `_worker`, `_worker_generate` |
| But every **new state** writes a snapshot and restarts the worker | `_snapshot()` + `_state_key()` today |
| The app already knows exactly what an edit changed | `app_bridge._deltas` / `_future_deltas`: per-transaction GlobalIds whose shape changed or that were removed; cascades included (joins, openings, rooms via `AFTER_ACTION`) |
| Canonical, reference-resolved records already exist | `python/kimcad/records.py` (`decompose`/`compose`, `state_hash`) — used by versioning, tested for round-trip |
| Drawings depend on geometry + annotations, not on UI state | `drawgen` inputs inventory (see the subset plan) |

## Architecture

Phased, each phase shippable and reversible.

### Phase 0 — don't rewrite the snapshot when nothing it depends on changed
The worker is currently restarted whenever `_state_key()` (drawing revision) changes. Key the snapshot/worker on a **content key** for the drawing inputs instead: `(id(model), geometry_revision, drawings_revision)` where `geometry_revision` advances only when a transaction's `_deltas` is non-empty and `drawings_revision` only when drawings/annotations change. A pure sheet-placement move already does not advance the drawing revision (done); this removes more spurious rewrites (e.g., a property edit). Small change, immediate benefit for metadata-only edits.

### Phase 1 — keep the worker alive across states
Today a state change stops and restarts the worker. Instead, tell the running worker to **reload** from the new path when the app decides a full rewrite is still needed, and keep a **one-deep snapshot history** so undo can point the worker back at the previous file without rewriting it. (Undo/redo then toggles between two cached snapshots rather than re-serializing.)

### Phase 2 — apply a delta (the core)
The worker holds its `ifcopenshell.file`. On each edit the app already computes `{changed, removed}` GlobalIds (plus cascades). The app builds a **delta file** — a small valid IFC containing only the changed objects' records — and sends `{op: "apply", changed: <path>, removed: [GlobalId…], key: <content key>}`.

The worker:
1. `ifcopenshell.open(changed_path)`, and for each changed object find its existing entity by GlobalId, `f.remove(...)` it (and its now-orphaned owned records, reusing `records`' owner logic), then `f.add(new_entity)`;
2. removes objects whose GlobalIds are in `removed`;
3. reuses the same id-renumbering guarantees `records.compose` already provides;
4. replies `{ok, hash}` with a hash of its drawing inputs.

Building the delta reuses the **records closure** from the subset plan: a changed product pulls its representations, placements, materials and display styles; a removed product is just dropped. The delta is therefore the same closure walk with a different root set — build one module, use it in both plans.

### Phase 3 — verify and gate
- After each `apply`, the app compares the worker's `hash` with its own `geometry_revision`-derived hash (or a `records.state_hash` of the affected subtrees). On mismatch, the app sends `{op: "reload", path}` with a freshly written full snapshot and marks the delta path as unreliable for that session (telemetry).
- Everything sits behind a flag (`KIMCAD_DRAWING_DELTA`, default on once green; off restores today's behaviour exactly).

### Where it plugs in
- `python/kimcad/drawings.py`: `_worker_generate` grows `apply`/`reload`; `raw_drawing` decides write-full vs send-delta.
- `python/kimcad/app_bridge.py`: expose the last transaction's `{changed, removed}` (already kept in `_deltas`); expose a stable content key.
- `python/kimcad/drawgen.py`: `worker()` handles `apply`/`reload` in addition to `generate`.
- New `python/kimcad/subset.py` (shared with the subset plan): the closure + delta builder.

## Global Constraints

- Never show a drawing made from a divergent model: verify before use, else full reload.
- The full-snapshot path is always available and unchanged; a flag and a failure mode restore it.
- Model memory: the worker already keeps a second copy; deltas must not keep unbounded history (bound the snapshot cache to 2, the record cache to 1 state).
- Golden hashes of sample files do not change; drawings stay model data (D60).
- EN/ES strings; SPDX; DCO; headless CI.

## Review Focus

1. A drawing generated after a sequence of random edits (add wall, move wall, split, undo, redo, delete) is byte-identical to one generated from a full snapshot of the same state.
2. `hash(worker model) == hash(app model)` after every edit in a randomized test.
3. A deliberately corrupted delta (drop a referenced style) is detected by the hash check and recovered by a full reload.
4. No snapshot is written on a metadata-only edit or a sheet-placement move (assert the temp dir stays empty).

---

### Task 0: Content key + telemetry
- [ ] `app_bridge`: `_geometry_revision()` (advances only when `_deltas` non-empty) alongside `_drawing_rev()`; expose the last transaction's `{changed, removed}`.
- [ ] `drawings`: key `_snapshot`/`_bounds`/worker on the content key; a test asserts no rewrite on a rename/placement edit.
- [ ] Count snapshot writes and worker restarts (a debug counter in `timings()` or the self-test).

### Task 1: Shared closure/delta builder
- [ ] Land the subset plan's `subset.py` closure first; add `delta(f, changed_guids, removed_guids) -> (mini_ifc_path, removed_global_ids)` reusing it.
- [ ] Unit-test on the house: moving a wall yields a delta containing the wall, its openings, its material/display and the regenerated neighbours.

### Task 2: Worker apply/reload protocol
- [ ] `drawgen.worker`: handle `{"op":"apply", ...}` and `{"op":"reload", ...}`; keep the model between requests; return `{ok, hash, timing}`.
- [ ] `drawings._worker_generate`: send `apply` when a delta exists, `reload` otherwise; verify the hash and, on mismatch, reload once and retry.

### Task 3: Undo/redo and snapshot history
- [ ] Keep the last two snapshots (already `_SNAP_CACHE = 2`); on undo, if the previous content key is cached, point the worker at it (`reload`) instead of rewriting.
- [ ] Randomized test: interleave edits and undo/redo; assert drawings match the full-snapshot reference each time.

### Task 4: Corpus timing
- [ ] `--bench-edit --open-drawing` self-test variant: move one wall six times and regenerate the South Elevation after each; report per-edit seconds (before: ~30 s; target: < 3 s).
- [ ] Write the numbers in `docs/11-spike-results.md`.

### Task 5: Hardening and docs
- [ ] Divergence/telemetry, feature flag, kill switch; ensure a worker crash falls back to `_generate_once` (already exists).
- [ ] Docs: doc 05; a D-number; spike results; memory note (two copies of the model + one state of records).

## Risks

| Risk | Mitigation |
|---|---|
| Applying a delta diverges from the app model (missed cascade, stale reference, id contention) | Hash check after every apply; full reload on mismatch; deltas behind a flag |
| `_deltas` under-reports what a drawing sees (e.g., a host wall's material changed indirectly) | The closure pulls dependents of each changed object; randomized equality tests against a full snapshot catch gaps |
| Memory grows with delta history | Bound to the last two snapshots and one record state; clear on model change |
| Entity id renumbering breaks references inside the worker | Reuse `records`' compose/renumber guarantees; validate the worker file after each apply in tests |
| Worker crash mid-apply leaves it inconsistent | The worker rebuilds from a snapshot on any error; the app detects a dead pipe and restarts (fallback path already present) |
| Windows path/lock and process plumbing | Delta passed as a temp file path, not stdin; worker never holds the saved file (snapshot copy) |

## Effort (rough)

- Phase 0: ~0.5 day. Phase 1: ~1 day. Phase 2: ~3–4 days. Phase 3 + hardening: ~1–2 days.
- Depends on the subset plan's closure module (Task 1 there) for the delta builder.

## Open questions (owner)

1. **Flag default:** ship the delta stream on once green, or opt-in for a release? Recommend on once the randomized equality tests are green.
2. **Hash strength:** a fast structural hash (e.g., `records.state_hash` of the affected subtree) vs a full hash of the worker model per edit. Recommend the subtree hash, with a full hash in tests only.
3. Is a 2-deep snapshot history enough for undo, or should undo always trigger a full reload (simpler, still avoids the write only when redo revisits)? Recommend 2-deep.
