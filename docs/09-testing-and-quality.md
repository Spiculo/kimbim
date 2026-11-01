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
| **Canonical format** | JSON canonicalization rules: key sorting, SET ordering, numbers (INTEGER vs REAL), exact strings, unset omission | Yes |
| **Merge** | Three-way merge scenarios, including ported `ifcmerge` cases; merge is deterministic and commutative where expected | Yes |
| **Reconciliation** | Match rates and no false matches on the reconciliation pairs | Yes |
| **Commands** | Each authoring command: apply → expected change set → undo restores identical records | Yes |
| **Export validity** | Exported IFC passes `ifcopenshell.validate`, opens in web-ifc and in xBIM (independent parsers; `pixi run interop`, `pixi run interop-xbim`) | Yes |
| **100k release gate** | First frame under 15 s and warm decomposition under 15 s on a 100k-object model (`pixi run bench-100k`); full load and cold decomposition are reported and gated at 240 s/150 s | Yes (tags and manual runs) |
| **GUI smoke** | App launches, opens a corpus file, selects, cuts, saves (Qt Test) | Yes |
| **Portable package** | `dist/KimBim` starts with `CONDA_PREFIX`, `PIXI_*` and `PYTHON*` removed, then exports the sample house's A01 sheet to PDF (`tools/check_package.py`) | Yes (Windows CI) |
| **Benchmarks** | Open time, frame rate, memory, commit time, diff time, merge time by model size | Tracks regressions |

## Benchmarks (tracked per release)

| Metric | Target on 100k objects (initial, revisit after S2/S5) |
|--------|--------------------------------------------------------|
| Open IFC to first frame | < 15 s is the goal; **met: 10.9 s** on the 100k benchmark (full geometry ~158 s), then progressive |
| Orbit frame rate | ≥ 30 fps |
| Pick latency | < 100 ms |
| Property edit to UI update | < 50 ms |
| Commit of one changed object | < 1 s |
| Diff between adjacent commits | < 1 s |
| Checkout (cached) | < 5 s |

### Measured 100k benchmark (2026-11-01)

`pixi run bench-model`, then `pixi run bench-100k`, on the 100,000-wall synthetic model (110k products, 1.4M triangles):

| Metric | Result | Gate |
|--------|--------|------|
| First frame (first mesh batch on screen) | **12.6 s** | < 15 s |
| Full geometry | **178.7 s** (139–179 s across runs) | < 240 s (regression guard) |
| Wall tool activation | **0.28 s** | < 2 s |
| First plan-cut/poché paint after activation | **0.02 s** | < 180 s |
| Snap-data dispatch on Wall tool activation | **0.2 ms** (background worker) | < 1 s |
| Cold working decomposition (`Project.status`) | **107.9 s** | < 150 s (regression gate; Rust decomposer) |
| Warm working decomposition (on-disk cache) | **3.3 s** | < 15 s |

The first frame is met by loading the mesh chunks before filling the levels, model tree and graphics panels (`finishOpen`), and by chunks of 500 elements. The panel fills and snap data run in background workers; `PythonEngine` serializes every Python call and exposes `busy()`, so periodic recovery timers skip their bridge calls instead of blocking behind a long worker. The agent poll also skips while snap data is loading; that poll waiting on the Python lock was the real 111 s plan-paint freeze. Poché is capped at 20,000 visible elements: larger cuts keep the clip planes but omit the filled cut outlines. The decomposition cache is `.kimbim/cache/decompose` (three newest files per project, keyed by the IFC bytes and HEAD). Cold decomposition goes through the C++ `tools/ifcdump` bridge and the Rust decomposer (`kimbim.ifcdump` + `kimbim._core.decompose_dump`); the Python decomposer remains the fallback and the byte-identical reference (`tests/python/test_rust_decompose.py`). The benchmark job runs on tags and on `workflow_dispatch`.

## Engineering practices

- **Code review** on every change, plus a **DCO sign-off** on every commit ([06](06-reuse-and-licensing.md)).
- **Format versioning:** any change to the canonical record format bumps `kimbim/N` and ships a migration with tests.
- **Every bug fix adds a test.** If the bug involves a file, the file joins the corpus.
- **Decision log:** architectural changes are recorded in [decisions.md](decisions.md) before they are implemented.
