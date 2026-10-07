# 11 — Spike Results (S1–S6)

Run 2026-10-03/04 on Windows 11 (16 threads, 32 GB) and WSL Ubuntu, ifcopenshell 0.9.0, gix 0.88.
Code and instructions: [`spikes/`](../spikes/README.md). Test corpus: 80 buildingSMART sample files (IFC2X3, IFC4, IFC4X3), including real Revit/ArchiCAD exports (Duplex, Clinic, Schependomlaan, Esplanades).

## Summary

| Spike | Question | Verdict |
|-------|----------|---------|
| S1 | One in-memory model shared by C++ and embedded Python? | **Yes**, with conda-forge's shared-library build. Not possible with the pip wheel. |
| S2 | Can IfcOpenShell + the OCCT viewer handle 100k-element models? | **Yes, if elements are drawn in batches**: tessellation 110k elements in 28 s (hybrid kernel); viewer 32 fps and 232 MB on an integrated GPU with batches of 1,000 elements, but 2.7 fps and 3.2 GB with one object per element. |
| S3 | Lossless, deterministic IFC ↔ records round-trip? Local edits? | **Yes**, after three design rules found by the spike (below). |
| S4 | Identical hashes on Windows and Linux? | **Yes: 77/77 identical state hashes and byte-identical IFC exports.** |
| S5 | Git object DB for a 1M-record model? | **Yes, if records are written as packs (never loose objects) and packs avoid deltas.** |
| S6 | Can IfcOpenShell's SVG serializer make KIMCAD's drawings, fast enough? | **Yes for quality; speed needs**: sending only visible elements (the big win), polygon HLR (a smaller one), and generating in a child process (the serializer holds the GIL). |

---

## S1 — Shared in-memory model (C++ ↔ Python)

**Test:** a C++ host embeds CPython. Python opens an IFC file with `ifcopenshell`, then hands the raw `ifcopenshell::file*` (`file.file_pointer()`) to C++. C++ renames a wall, and Python must see it. Python then creates a wall through `ifcopenshell.api`, and C++ must see it.

**Result (Linux):** passes both ways.

```text
[c++] same model, walls: 4
[c++] renamed wall #158
[py ] sees C++ rename: True 158
[py ] created wall #373 via ifcopenshell.api
[c++] sees Python-created wall: walls now 5  -> SHARED MODEL OK
```

**Findings**
- This only works when the Python module **dynamically links** `libifcopenshell.parse`, as the conda-forge build does (verified on Linux `.so` and Windows `.dll`). The pip wheel is one statically linked module, so a C++ host cannot share its model. That confirms D25: dependencies come from **pixi + conda-forge**.
- The conda-forge package ships headers and `IfcOpenShellConfig.cmake`, so `find_package(IfcOpenShell)` works.
- IfcOpenShell 0.9's C++ API changed from 0.8: the namespace is `ifcopenshell::file` and entities are `express::base`. 0.9 also ships **RocksDB storage** and JSON/XML document modules, which are worth evaluating later for large-model loading.
- **Still to do:** run the same host on Windows. The package structure is confirmed, but the run isn't.

## S2 — Tessellation throughput (CPU side of the viewer)

The geometry iterator ran on 16 threads (machine shared with other spikes, so these are conservative).

| Kernel (Clinic_Architectural, 3,258 elements) | Time | Triangles |
|---|---|---|
| `opencascade` (default), 1 thread | 70.7 s | 191k |
| `opencascade`, 16 threads | 17.9 s | 191k |
| **`hybrid-cgal-simple-opencascade`**, 16 threads | **3.1 s** | 185k |
| `cgal-simple`, 16 threads | 1.2 s | 176k, but **drops 26 elements** |

Mesh deflection (1 mm vs. 1 cm) and deferring opening subtraction changed the time by less than 10%. **The kernel choice dominates.**

Hybrid kernel, 16 threads, machine otherwise idle:

| Model | Elements | Triangles | Open | Tessellate | Peak RAM |
|---|---|---|---|---|---|
| Duplex_A | 286 | 25k | 0.2 s | 0.3 s | 100 MB |
| Clinic_Architectural | 3,258 | 185k | 1.0 s | 1.6 s | 230 MB |
| Esplanades | 2,846 | 179k | 1.3 s | 9.4 s | 326 MB |
| Schependomlaan | 3,654 | 261k | 5.5 s | 1.7 s | 611 MB |
| **Synthetic: 100k walls + 10k openings** | **110,000** | **1.52M** | 11.4 s | **27.7 s** (3,965 elem/s) | **1.7 GB** |

(The first default-kernel pass over the same four real files took 3.2 / 18.3 / 34.2 / 32.3 s, but ran while other spikes loaded the machine. The 6× kernel factor comes from the side-by-side Clinic test above.)

**Reading:** a 100k-element model reaches full geometry in about 40 s cold on a 16-thread desktop. Esplanades shows that complex real geometry can cost more per element than simple walls, so a large real model may take a few minutes cold. Two consequences: the viewer must show geometry **progressively** as elements arrive, and the **tessellation cache** keyed by record hash ([05](05-geometry-rendering-drawings.md)) is essential, so later opens are fast.

**Decisions**
- Use `hybrid-cgal-simple-opencascade` (Bonsai's choice) for display tessellation. Exact OCCT stays available for precise operations (drawings, measuring, clash).
- Pure CGAL is out: it silently loses elements.
- Tessellation results are cached per record hash ([05](05-geometry-rendering-drawings.md)), so a model is only tessellated fully once.
- Frame rate and picking: see the viewer measurements below.

### Viewer: OCCT AIS rendering, picking and memory

**Setup:**
- Hardware: AMD Ryzen 7 5700U laptop with integrated Radeon graphics, the low end of what architects use. OpenGL 4.6.
- Software: OCCT 8.0.1 driven through pythonocc-core. Rendering, picking and memory all happen in OCCT's C++, as they would in the app.
- Code: `spikes/s2_viewer/`. Each element mesh (hybrid kernel, world coordinates) becomes a mesh-only face shown with `AIS_Shape`, so OCCT selection works.
- Run: 1280×800, camera orbiting over 120 frames, 100 random hover picks.

| Model | Layout | OCCT objects | Load | Frame median / p95 | FPS | Pick p95 | Memory |
|---|---|---|---|---|---|---|---|
| Duplex (286 el., 27k tris) | per element | 286 | 0.3 s | 16.6 / 17.2 ms | ≥ 60 (vsync) | 0.3 ms | 110 MB |
| Schependomlaan (3,589 el., 261k tris) | per element | 3,589 | 3.9 s | 16.8 / 32.4 ms | ≥ 60 (vsync) | 1.8 ms | 200 MB |
| Schependomlaan | batches of 1,000 | 4 | 3.5 s | 16.6 / 17.5 ms | ≥ 60 (vsync) | 10 ms | 117 MB |
| **Synthetic 110k el. (1.52M tris)** | per element | 110,000 | 33 s | **374 / 412 ms** | **2.7** | 0.4 ms | **3.2 GB** |
| **Synthetic 110k el. (1.52M tris)** | **batches of 1,000** | 110 | 22 s | **31.5 / 46 ms** | **31.7** | 18 ms | **232 MB** |

(pythonocc keeps vsync on, so anything under 16.7 ms reads as "≥ 60 fps". Load times include building meshes in Python; C++ will be faster.)

**Findings**
- **OCCT's cost is per interactive object, not per triangle.** 110,000 separate objects are unusable: 2.7 fps and 3.2 GB. The same geometry in 110 batches meets the targets (≥ 30 fps, pick under 100 ms) on integrated graphics.
- **Real single-discipline models (a few thousand elements) are fine either way**, at 60 fps.
- **The conda-forge "all" build of OCCT forces software rendering on Windows.** It pulls VTK, then viskores, then Mesa, whose `opengl32.dll` lands in the environment and is loaded before the GPU driver. The first measurements ran on Mesa llvmpipe (the CPU). Fix: pin OCCT's `novtk` build (D43). Without this, every KIMCAD user on Windows would have had CPU rendering.

**Decisions (D42, D43)**
- The viewport draws elements in **batches** (about 1,000 elements per OCCT object, grouped by storey and type). Each batch is a custom AIS object with **one selection owner per element**, so picking, highlighting, hiding and isolating stay per element.
- OCCT is pinned to the `novtk` build in `pixi.toml`, and CI checks the environment contains no `opengl32.dll`.

## S3 — Canonical records round-trip

**Test, per file:** IFC A → records R1 → IFC B → records R2 → IFC C. Checks:
- R1 = R2 (fixed point);
- text(B) = text(C) (deterministic export);
- A ≡ B under an **independent** semantic comparison that does not reuse the record code.

**Result: all 77 schema-valid files pass all three checks.** The 3 others are schema-invalid inputs (see below).

| Group | Files | Result |
|---|---|---|
| buildingSMART samples, IFC2X3 | 10 | 10 OK |
| buildingSMART samples, IFC4 ADD2 TC1 | 15 | 15 OK |
| buildingSMART samples, IFC4X3 ADD2 | 10 | 10 OK |
| ISO specification examples (IFC4) | 41 | 38 OK, 3 INVALID input |
| Real-world exports (Duplex, Clinic, Esplanades, Schependomlaan; IFC2X3) | 4 | 4 OK |

| Model | Entities | Rooted | Records | IFC size | Record size | Decompose (Python) |
|---|---|---|---|---|---|---|
| Duplex_A (Revit) | 38,898 | 3,893 | 9,996 | 2.4 MB | 3.6 MB | 13 s |
| Esplanades (ArchiCAD) | 189,422 | 29,012 | 43,615 | 12.1 MB | 13.6 MB | 54 s |
| Clinic_Architectural (Revit) | 209,259 | 41,068 | 79,250 | 13.0 MB | 29.3 MB | 263 s |
| Schependomlaan (ArchiCAD) | 714,485 | 46,302 | 118,176 | 49.3 MB | 47.4 MB | 183 s |

Record storage is roughly the same size as the IFC text before compression. Git compresses each blob, so packs are smaller. The Python decomposer is a prototype and slow by design; the Rust implementation (R1) is expected to be far faster, so these times are not targets.

**Three design rules the spike forced** (now reflected in [02](02-data-model-and-format.md)):

1. **Classify by content, never by instance.** Real exports contain duplicate identical entities (e.g. 60 identical representation maps in Esplanades). Counting references per *instance* made the encoding change after the first export merged the duplicates. Fix: hash-cons identical non-rooted entities into **content classes** first, then count reference edges between classes. After that, every valid file is a fixed point.
2. **Shared, mutable non-rooted entities need stable IDs, not content hashes.** `IfcOwnerHistory` is one entity referenced by every rooted entity in IFC2X3, and `ifcopenshell.api` updates its timestamp on every edit. With content-hash references, moving one wall changed **3,897 of 9,996 records**. With a stable ID (the content hash at first import, kept afterwards), the same move changes **4**.
3. **Loose entities keep multiplicity.** Entities with no referrers (e.g. `IfcStyledItem`) are stored with a count, so identical duplicates are not merged away.

**Other findings**
- **Invalid input:** 3 ISO example files use an IFC4 ADD1 attribute shape (`PnIndex` as a list of lists). ifcopenshell *reads* them but refuses to *write* them. KIMCAD needs an explicit policy: validate on import, report, and repair or reject. These files are classed INVALID, not as failures.
- **Duplicate GlobalIds** exist in real files (Schependomlaan). Import must detect them and assign new KIMCAD IDs deterministically, with a warning.
- **No Unicode normalization.** NFC-normalizing strings would break losslessness, so strings are stored exactly as parsed. Doc 02 is corrected.
- **INTEGER vs REAL must stay distinct.** Pure RFC 8785 would write `1.0` as `1`, so our canonical JSON keeps the IFC type distinction.

**Edit locality** (records changed per typical authoring edit, via `ifcopenshell.api`):

| Edit | Duplex (9,996 records) | Building-Architecture (139) |
|---|---|---|
| Set one property on one wall | **1** | 3 |
| Move one wall | **4** | 1 |
| Raise a storey, contents follow (129 elements) | **1** | — |
| Raise a storey, contents stay in place (API default) | 126 (correct: each element's local placement really changed) | 10 |

Same edits on **Clinic_Architectural (79,250 records)**: property → **1** record, wall move → **4**, raising a storey with **1,734 elements** on it (contents follow) → **1**. Edit cost does not grow with model size.

## S4 — Cross-platform determinism

The same S3 code ran on Windows 11 (CPython 3.12) and on Linux (WSL Ubuntu, CPython 3.10), both with ifcopenshell 0.9.0.

| Check | Result |
|---|---|
| State hash (all records) per file | **77 / 77 identical** |
| Exported IFC (DATA section) per file | **77 / 77 byte-identical** |

**What this proves:** IFC parsing, canonical float formatting (shortest round-trip), set ordering, hashing and deterministic export behave identically on both platforms for every valid file in the corpus, including the large real-world models.

**What it does not prove yet:**
- Different *ifcopenshell versions*. The engine/format version is recorded per commit for this reason ([02](02-data-model-and-format.md#5-verify-continuously)).
- Values *computed* by edit operations (rotations etc.). Those are covered by quantization and by "replicate results, not operations" ([02](02-data-model-and-format.md#determinism)).
- The Rust implementation. The golden-hash CI job ([09](09-testing-and-quality.md)) will compare it against these manifests.

## S5 — Git object database at scale

Synthetic ~700-byte canonical records, sharded `objects/<aa>/<bb>/<id>.json`, on a non-synced local disk.

| Operation | 10k | 100k | 1M |
|---|---|---|---|
| Import as **loose objects** (gix `write_blob`) | 140 s | — | (~4 h projected) |
| Import via **`git fast-import`** (one pack) | 2.9 s | 31 s | 391 s |
| One-record commit (gix tree editor) | 71 ms | 76–97 ms | 90 ms |
| Tree walk (list all records) | — | 0.34 s | 2.6 s |
| Read all records, delta pack, sequential / 16 threads | 5 s | 48 s / 4.6 s | (not measured: replaced by no-delta) |
| Read all records, **no-delta pack**, sequential / 16 threads | — | **1.7 s / 0.2 s** | **21.9 s / 2.0 s** |
| Pack size | 5.4 MB | 51 MB | 469 MB (478 MB without deltas) |
| `git repack -adf --window=0` | — | — | 636 s |

**Findings**
- **Never write records as loose objects.** On Windows each loose object costs about 7.6 ms (file creation plus antivirus scanning), which is unusable at scale. Bulk writes must produce a **packfile directly**.
- **Disable deltas for record blobs.** `fast-import` builds delta chains up to 50 deep, which makes random reads about 30× slower, and for small records they save almost no space (51.6 vs 50.6 MB).
- **Commit cost does not grow with model size:** about 90 ms for a one-record change at 1M records.
- **Determinism holds across write paths:** the loose and fast-import paths produced the identical root tree hash for the same records.
- **Sharding should adapt to model size.** With two fixed 256-way levels, a 10k-record model had 9,505 trees, almost one per record. Use one level below about 64k records and two above.
- The synthetic records are random numbers, so real records will compress better. Treat the pack sizes as an upper bound.

**Decisions**
- MVP import uses `git fast-import` followed by `git repack -adf --window=0`. The repack is slow (636 s at 1M records), so it should be a background step after import.
- Later, a native pack writer through `gix-pack`, with parallel compression and no deltas for records.
- Keep the local model cache (`.kimcad/cache`, keyed by tree hash) so opening a project normally skips the read-all path.

---

## S6 — Drawings: SVG serializer (Slice 14 risk check)

Run 2026-10-07 on Linux (4 threads), ifcopenshell 0.9.0 (PyPI wheel; same version as the conda-forge build), with
[`spikes/s6_drawings/drawing_bench.py`](../spikes/s6_drawings/drawing_bench.py).

**API.** In 0.9.0 the serializer has no `addDrawing()` from Python. Custom drawings work the way `ifcopenshell.draw` and
Bonsai do it: an `IfcAnnotation` with `ObjectType = "DRAWING"` whose placement is the camera (it looks along −Z) and
whose `Body` is an `IfcBlock` (width × height × depth), passed with the `elevation-ref-guid` setting. The annotation
itself must be among the iterator's elements, otherwise the output is empty. `IfcOpeningElement` must be left out,
otherwise openings are drawn as cut fill across doors and windows. Output is in paper millimetres (`bounds`, `scale`).

**Quality (the M4 house).** Plan, section and elevation are correct: walls and slabs cut with a solid fill (poché),
windows and doors in projection, storeys and slabs in the right places. Missing: door swings in plan (the doors have no
swing in their representation; Slice 15). Polygon HLR (`svg-poly`) gives the same drawings as exact HLR.

**Speed.**

| Model | Drawing | Elements given | Geometry | HLR | Total |
|-------|---------|----------------|----------|-----|-------|
| House (24 products) | plan / section / elevation | 18 / 33 / 33 | 0.07–0.14 s | 0.15–0.17 s | **0.25–0.33 s** |
| Synthetic, 2,880 products (12 × 12 rooms × 4 levels) | plan, level 1, exact HLR | 1,297 | 2.1 s | 7.3 s | 10.6 s |
| same | plan, level 1, `svg-poly` | 1,297 | 1.9 s | 4.6 s | **6.8 s** |
| same | section through the middle, exact / `svg-poly` | all | 9.9 / 8.0 s | 18.2 / 16.2 s | 32.5 / **25.6 s** |
| same | south elevation, exact / `svg-poly` | all | 8.4 / 8.8 s | 58.9 / 42.1 s | 72.1 / **52.1 s** |
| same | south elevation, only the visible front row | 240 products | 1.3 s | 1.9 s | **3.4 s** |
| Clinic_Architectural (2,586 products drawn), CI Linux runner | section through the middle, `svg-poly` | all | 11.1 s | 13.4 s | **25.9 s** |
| same | south elevation, `svg-poly` | all | 11.5 s | 21.4 s | **34.4 s** |
| same | plan | — | — | — | first CI run used the lowest storey (5 elements, 0.3 s), not a real plan; the bench now picks the fullest storey |

- Clinic confirms the synthetic results on a real Revit export: a section or elevation of the whole building takes
  26–34 s, and geometry (11 s) matters too, not only HLR. The visible-element pass cuts both.
- Hidden-line removal dominates, and it grows with everything behind the cut, not with what is visible. Sending only
  the elements the camera can see cut the elevation from 52 s to 3.4 s. KIMCAD already renders element IDs into an
  offscreen image for box selection (D52); the same pass from the drawing's camera gives the visible set.
- `svg-poly` (with `svg-prefilter` on and `svg-unify-inputs` off) makes HLR 1.1–1.6× faster with the same drawings,
  and `write` 3–4× faster. Worth having, but it is not the fix. (Earlier runs that showed a 4× gain were taken while
  other benchmarks shared the 4 cores; the table uses sequential runs only.)
- **The serializer holds the GIL** during `write` and `finalize`: a Python thread ticking every 10 ms stalled for
  4.7 s while a plan generated. Generating in-process would freeze the app, because the GUI calls Python. A snapshot
  for a child process is cheap: `to_string` 0.25 s and `from_string` 0.31 s for the 5 MB synthetic model.

**Decisions** (D60, proposed in the [Slice 14 plan](superpowers/plans/2026-10-07-slice14-sections-elevations.md)):
drawings are DRAWING annotations; generation runs in a child process from a snapshot; `svg-poly`; plans pre-filtered
to their level; sections and elevations get a visible-element pass first.

---

## Changes made to the design docs

- [02](02-data-model-and-format.md): content-class classification; stable IDs for shared mutable entities; loose-entity multiplicity; no NFC normalization; INTEGER/REAL distinction; invalid-input and duplicate-GlobalId policy.
- [03](03-versioning.md): pack-only writes, no-delta record packs, adaptive sharding.
- [05](05-geometry-rendering-drawings.md): hybrid CGAL/OCCT kernel for display tessellation.
- [07](07-roadmap.md): spike status.
- [decisions.md](decisions.md): D34–D39.
