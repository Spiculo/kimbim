# 09 — Testing and Quality

## Test corpus (`tests/corpus/`)

A curated, license-clean set of IFC files, each with a manifest entry (source, license, schema, object count, what it exercises).

| Category | Examples / sources |
|----------|--------------------|
| Small / feature-specific | buildingSMART sample files and test cases; IfcOpenShell test files |
| Real-world exports | Files exported from Revit, ArchiCAD, Vectorworks, Allplan, Bonsai, FreeCAD; only openly licensed ones |
| Schemas | IFC2X3, IFC4 (ADD2 TC1), IFC4X3 ADD2 (non-blocking until after MVP) |
| Scale | ~10k, ~100k, ~500k objects; generated if needed |
| Edge cases | Mapped items, booleans/openings, complex BReps, large tessellations, non-ASCII strings, imperial units |
| Reconciliation pairs | The same model exported twice from one tool, with GlobalIds changed between the exports |

Large files are stored with Git LFS or downloaded by a script, so they are not committed directly.

## Test suites

| Suite | What it checks | Blocks release |
|-------|----------------|:--------------:|
| **Round-trip** | IFC → records → IFC is semantically equal; records → IFC → records is a fixed point (identical hashes) | Yes |
| **Determinism** | Golden record and tree hashes are identical on Windows and Linux CI | Yes |
| **Canonical format** | JSON canonicalization rules: sorting, numbers, NFC, unset omission | Yes |
| **Merge** | Three-way merge scenarios, including ported `ifcmerge` cases; merge is deterministic and commutative where expected | Yes |
| **Reconciliation** | Match rates and no false matches on the reconciliation pairs | Yes |
| **Commands** | Each authoring command: apply → expected change set → undo restores identical records | Yes |
| **Export validity** | Exported IFC passes `ifcopenshell.validate`; it opens in reference tools (manual checklist per release) | Yes |
| **GUI smoke** | App launches, opens a corpus file, selects, cuts, saves (Qt Test) | Yes |
| **Benchmarks** | Open time, frame rate, memory, commit time, diff time, merge time by model size | Tracks regressions |

## Benchmarks (tracked per release)

| Metric | Target on 100k objects (initial, revisit after S2/S5) |
|--------|--------------------------------------------------------|
| Open IFC to first frame | < 15 s, then progressive |
| Orbit frame rate | ≥ 30 fps |
| Pick latency | < 100 ms |
| Property edit to UI update | < 50 ms |
| Commit of one changed object | < 1 s |
| Diff between adjacent commits | < 1 s |
| Checkout (cached) | < 5 s |

## Engineering practices

- **Code review** on every change, plus a **DCO sign-off** on every commit ([06](06-reuse-and-licensing.md)).
- **Format versioning:** any change to the canonical record format bumps `kimcad/N` and ships a migration with tests.
- **Every bug fix adds a test.** If the bug involves a file, the file joins the corpus.
- **Decision log:** architectural changes are recorded in [decisions.md](decisions.md) before they are implemented.
