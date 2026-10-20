# Slice 20 (M5) — Milestones, object history, before/after, delete option

**Goal:** an architect names the versions that matter (Concept, Schematic design, Tender…), sees how one element evolved, compares it field by field between two versions, and removes design options that went nowhere.

## Decisions (D67)

| Topic | KimBim |
|---|---|
| Milestone | An annotated Git tag on the latest saved version of the current option (docs/03: "Milestone = annotated tag"). Name percent-encoded like option names; the note is the tag message; tagger and time recorded. Unsaved changes: the bridge refuses, the app offers *Save version* first. Unique names. A milestone can be used wherever a version id can (Compare, before/after, `kimbim diff Concept HEAD`) |
| History panel | Versions carrying milestones show `◆ Name — message` in bold |
| Object history | Versions (first-parent chain of the current option) whose record of the element, or of the property sets the element uses in the open model, changed: added / modified / removed; unsaved changes to it show first. CLI: `kimbim blame <GlobalId>` |
| Before/after | One element at two versions (or a version and the open model), field by field: class, name, description, tag, predefined type, level, type, position + heading, every property and quantity. Older versions are composed from their records in memory (the last three are cached). In the app: from a Compare (select a change → *Before/after…*) or from *Object history…* (a version vs the current model); *Only what changed* is on by default |
| Delete option | Deletes the option's Git branch. Never `main`, never the current option (switch first); milestones on it keep their versions reachable |

## Done

- [x] Rust store: `create_tag`, `tags`, `delete_tag`, `delete_branch` (+ PyO3 bindings); tests in `crates/kimbim-repo/tests/repo.rs`.
- [x] `project.py`: `tag`, `tags`, `delete_tag`, `delete_branch`, `history_of`; CLI `kimbim tag [NAME] [-m] [--delete]`, `kimbim blame GUID`.
- [x] `versioning.py`: `milestones`, `create_milestone`, `delete_milestone`, `element_history`, `before_after`, `delete_option`; `history` lists milestones per version; `compare` accepts milestone names.
- [x] App: project toolbar *Delete option…*, *Milestone…* (preset names Concept → Construction, editable), *Object history…*; History panel milestones and *Before/after…*; EN/ES strings ("Hito", "Historial del objeto", "Antes/después").
- [x] Tests: Python `test_milestones.py` (4), `test_cli.py::test_tags_and_blame`, Rust 2 new, app `milestonesHistoryAndDeleteOption`.

## Not done (later)

- An object-history index (`.kimbim/index.db`) for very long histories; property-level blame ("who changed FireRating"); history across options (merge commits are walked by first parent only); showing the milestone on the title block (P2).
