# Slice 21 (R4) — Merge engine

**Goal:** combining two design options is a deterministic three-way merge of KimBim records with a conflict model the app can show (Slice 22), checked against ifcmerge's test cases.

## Rules (D68, docs/03)

| Level | Rule |
|---|---|
| Record | Unchanged on one side → the other; same change on both → taken; added on both with different content → `both_added`; deleted on one side, modified on the other → `delete_modify` |
| Attribute | Different attributes combine; same attribute, different values → `attribute` (the IFC class changing → `class`). Placement is one value: both sides moving one element conflicts |
| SET aggregates | Merge as sets: base + additions of either side − removals of either side (from the schema: `RelatedElements`, `HasProperties`…) |
| Property / quantity sets | Per property name; same property changed differently → `property` (`o/<pset>#HasProperties[FireRating]`) |
| Loose records (styles) | Same content: counts merge (ours + theirs − base) |
| Shared values (`n/`) | Never a conflict or dangling: restored from whichever side has them, dropped when unreferenced (a value may be a node on one side and inline on the other, depending on its referrers) |
| Integrity | `dangling`: a record refers to an object the other side deleted — *restore* it or *remove* the referring record (repeated until stable); `containment`: an element in two levels — choose the relationship to keep; new IFC schema problems → warnings |
| Determinism | Records are processed in key order; the same three versions give the same records and conflicts in either order of options |

Conflict ids are stable strings (`o/<GlobalId>`, `o/<GlobalId>#Name`, `dangling:<record>-><target>`, `containment:<GlobalId>`), so choices can be passed back (`resolutions = {id: choice}`) by the CLI and the app. Unresolved conflicts keep *ours* in the preview records.

## Repository

- Rust store: `merge_base`, `commit_merge` (fast-import `merge` lines: two parents), `fast_forward` (refuses when the branch is not contained).
- `Project.merge_preview(other)` → `up_to_date` / `fast_forward` / `merge` (+ `MergeResult`); `Project.merge(other, message, resolutions)` raises `MergeConflicts` until every conflict has a choice, checks the result composes to IFC, then commits.
- CLI: `kimbim merge OPTION [-m MSG] [--resolve ID=CHOICE ...] [--json]`.

## ifcmerge cases ported (tests/python/test_merge.py)

Fixtures copied from ifcmerge (GPL-3.0-or-later, attribution in `tests/fixtures/ifcmerge/README.md`). Results, with ifcmerge's numbering from `t/003.ifc.t`:

| Case | ifcmerge | KimBim |
|---|---|---|
| 1, 2, 3, 7, 10, 11, 14, 15, 17, 18, 19, 20 (additions, deletions, modifications of different elements) | merges | merges, no new IFC schema problems |
| 8 floor deleted + wall added | merges | merges (a shared direction the wall reuses is restored) |
| 9 overlapping STEP ids | merges after renumbering | merges (records are keyed by GlobalId: nothing to renumber) |
| 4, 5 delete vs modify | conflict | conflict (the wall and its path joins); keeping the wall merges cleanly |
| 6, 16 same name changed differently | conflict | conflict, the same in either order; resolving it is deterministic |
| 12 space boundary physical vs virtual | conflict | conflict on `PhysicalOrVirtualBoundary` |
| 13 both sides move one window | resolved automatically (one side wins) | **conflict** (docs/03: placements are absolute; silently picking one is rarely what an architect wants) |
| t/005 float re-saves | no conflict | no conflict |

Plus unit cases: per-property merge, SET merge, dangling reference (restore / remove), double containment; repository merge (clean merge commit with two parents, up-to-date, fast-forward of the other option, conflicts block the commit until resolved through the CLI).

## Not done (later)

- Import reconciliation (GlobalId → Tag → heuristic matching, the second half of R4) and its >95% identity exit test on a Revit pair.
- Coordination warnings (a clash check on the changed objects, docs/03 step 4).
- Merging in Rust for speed on very large models (the Python merge reads three full record sets).
