# Slice 22 (M5 exit) — Combine options in the app

**Goal (M5 exit):** two design options of the house are created, edited separately, compared and combined with one conflict resolved in the UI.

## How it works (D69)

1. *Combine options…* (project toolbar) opens the **Combine** dialog: choose the option to bring into the current one. The dialog says what it brings and lists each conflict: the element (click selects it), what changed, the **common version**, **this option** and the **other option** values in words ("Wall A", "at 6.000, 4.000, 0.000"), and a *Keep* choice (This option / Other option; for semantic conflicts *Restore what it refers to* / *Remove it*, or the level to keep). Choices can raise new questions (deleting what a new element refers to); the list refreshes. *Combine* is enabled once every conflict has a choice.
2. Combining opens the **combined model as unsaved work** (the 3D preview): what the other option brought is green, the elements whose conflicts were chosen are orange. The architect can review and still edit it (doc 03's "manual edit").
3. *Save version* records it as a version with **two parents** (a Git merge commit); *Discard* drops it. When the current option has not changed since the other branched off, combining just takes the other's latest version (fast-forward); when it already contains everything, nothing happens.

Compare also accepts option names ("compare main with Scheme B").

## Valid IFC after a round trip (D70)

Checking the M5 result with EXPRESS rules found a problem older than this slice: records hash-cons identical values (D34), so a version opened from its records could share entities IFC wants owned once: three identical walls shared one axis `IfcShapeRepresentation` (WR11), two slab types shared one `IfcMaterialLayer` (`ToMaterialLayerSet`). `records.unshare()` now gives every owner its own copy when a version is written as IFC for use (the app opening or combining a version, `kimbim export`; `Project.export(one_owner=True)`). `Project.export()`'s default output stays exactly `compose()`'s, which the golden e2e test pins: it follows the schema's single-owner inverses plus WR11's representation rule. `compose()` itself is unchanged, so the golden reference hashes are untouched, and decomposing the copies hash-conses them back, so saving again records no change.

## Done

- [x] `versioning.py`: `combine_preview`, `combine_options` (pending combination, `save_version` writes the merge commit, `discard_changes`/switching ends it), `project_state.combining`; `Project.commit(merged=...)`.
- [x] `records.unshare` applied in `Project.export` and when combining.
- [x] App: `CombineDialog` (own class, testable), *Combine options…* action, colouring of the combined model; EN/ES strings ("Combinar opciones", "Versión común", "Esta opción", "Otra opción").
- [x] M5 exit: app test `m5ExitCombineOptions` (two options, edits, Compare, the dialog with one conflict chosen, the combined model shown and saved with two parents) on both OSes; `tools/check_m5.py` (`pixi run m5`, CI on both OSes) on the full sample house: one conflict on the south wall's name, every other edit of both options kept, two parents, IFC4 schema + EXPRESS rules clean.
- [x] Tests: Python `test_combine.py` (6), `test_versioning_app.py::test_versions_open_as_valid_ifc`.

## Not done (later)

- Side-by-side 3D of the two options before choosing (the preview is the combined model); per-conflict "edit by hand" inside the dialog; combining with unsaved work (save or discard first); coordination warnings (clash check on changed objects).
