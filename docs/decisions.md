# Decision Log

Each entry: **ID · title · status · source**. Status values: Decided (owner), Proposed (recommended default, awaiting confirmation), Superseded.

To change a decision, add a new entry that supersedes the old one. Never edit history.

| ID | Decision | Status | Source / doc |
|----|----------|--------|--------------|
| D01 | Project name is **KIMCAD**; community OSS project for architects; no fixed timeline | Decided | Owner |
| D02 | Native desktop app, not web | Decided | Spec §54.1 |
| D03 | Windows and Linux first; macOS not targeted initially | Decided | Spec §54.2 |
| D04 | **KIMCAD-owned Qt 6 GUI + Rust repository engine**, not built on FreeCAD or Bonsai, but reusing their libraries and logic | Decided | Owner (review Q) · [01](01-architecture.md) |
| D05 | Focus on the local BIM app (modeling, cuts, object data, cloning, libraries, drawings, local versioning); networking is future | Decided | Owner answer 6 · [00](00-vision-and-scope.md), [04](04-app-features.md) |
| D06 | **Reuse before build:** integrate or port existing OSS rather than rewrite | Decided | Owner answer 7 · [06](06-reuse-and-licensing.md) |
| D07 | Copyleft, no-warranty open-source license | Decided | Owner answer 8 |
| D08 | License is **GPL-3.0-or-later**; future server components AGPL-3.0-or-later; DCO for contributions | Decided | [06](06-reuse-and-licensing.md#kimcad-license) |
| D09 | Data model **is the IFC schema** (via IfcOpenShell); no parallel KIMCAD BIM schema | Proposed | [02](02-data-model-and-format.md) |
| D10 | IFC files are import/export; repository stores **canonical records** (one per rooted entity, values inlined/shared, heavy geometry split) | Decided (spec §54.8–9), refined | [02](02-data-model-and-format.md#decomposing-the-ifc-graph-into-records) |
| D11 | Canonical record encoding is **canonical JSON (RFC 8785-style)**, not XML; shaped toward IFC5/IFCX | Decided | Owner answer 4 · [02](02-data-model-and-format.md#canonical-format) |
| D12 | Lossless round-trip is a release-blocking test | Decided | Owner answer 4 · [09](09-testing-and-quality.md) |
| D13 | Determinism: hash authored data only; replicate results, not operations; canonical floats; quantize computed values; cross-platform golden tests | Proposed | Owner Q3 · [02](02-data-model-and-format.md#determinism) |
| D14 | KIMCAD ID separate from GlobalId; defaults to the GlobalId at creation/import | Decided (spec §12), refined | [02](02-data-model-and-format.md#object-identity) |
| D15 | Import reconciliation (GlobalId → Tag → heuristic); unmatched objects lose history | Decided | Owner answer 1 · [03](03-versioning.md#import-reconciliation) |
| D16 | Versioning is **optional per project** (Plain vs Versioned) | Decided | Owner answer 1 · [03](03-versioning.md#project-modes-versioning-is-optional) |
| D17 | Git-style snapshots for storage; operations only for undo, recovery and future live collaboration | Decided | Owner answer 2 · [03](03-versioning.md) |
| D18 | **Repository is a Git repository** (records as blobs, sharded trees), accessed via gitoxide; records not checked out as files | Decided | [03](03-versioning.md#key-decision-the-kimcad-repository-is-a-git-repository) |
| D19 | Merge conflicts resolved by the user at merge time; placement is absolute (no auto-composition of moves) | Decided (owner answer 2), refined | [03](03-versioning.md#merge-combine-options) |
| D20 | Collaboration mode selectable: Branch & merge vs Live (auto-merge) | Decided, Future | Owner answer 2 · [08](08-future.md#collaboration-modes) |
| D21 | Security not a goal for now; "host cannot read data" dropped; permissions = local checks + push-time checks | Decided | Owner answer 5 · [08](08-future.md#security-and-permissions) |
| D22 | Working model = IfcOpenShell in-memory model; authoring via embedded `ifcopenshell.api` first, C++ for hot paths | Decided | [01](01-architecture.md) |
| D23 | Phase-1 renderer = OpenCASCADE AIS/V3d in Qt; Qt RHI renderer later if needed (replaces spec's custom Vulkan) | Proposed (pending S2) | [05](05-geometry-rendering-drawings.md#rendering) |
| D24 | Drawings via IfcOpenShell SVG serializer; port Bonsai drawing/sheet logic | Proposed | [05](05-geometry-rendering-drawings.md#drawings-2d) |
| D25 | Build: CMake + Corrosion + pixi/conda-forge | Proposed | [01](01-architecture.md#build-and-dependencies-proposed) |
| D26 | All edits are commands producing change sets of resulting values | Proposed | [01](01-architecture.md#engine-boundaries) |
| D27 | GUI is a client of the engines and never owns model state | Decided | Spec §54.25 |
| D28 | UI uses architect vocabulary (Save version, Design option, Combine, Milestone) | Decided | [00](00-vision-and-scope.md#audience) |
| D29 | UI internationalized from day one; **English and Spanish** at launch | Decided | Owner · [04](04-app-features.md#12-languages-i18n) |
| D30 | Architecture compatible with **IFC4 and IFC4X3** (schema-agnostic code, schema-tagged records, no silent conversion). **MVP ships IFC4**: new projects IFC4; IFC4X3 opens/saves best-effort; full IFC4X3 after MVP | Decided | [02](02-data-model-and-format.md#ifc-schema-version) |
| D31 | Model resolution default **0.01 mm (1e-5 m)**, matching IFC/IfcOpenShell precision conventions | Decided | [02](02-data-model-and-format.md#4-quantize-at-the-operation-boundary) |
| D32 | Source code hosted on **GitHub**; local repo initialized with `main` branch | Decided | Owner |
| D33 | Architect-oriented forge ("KIMCAD Hub"), post-MVP: add-on service on unmodified Forgejo first; fork Forgejo only if needed; **do not fork GitLab** | Decided | [10](10-forge-feasibility.md) |
| D34 | Records classified by **content class**, not instance; shared mutable non-rooted entities get **stable IDs**; loose entities keep multiplicity | Decided (spike S3) | [02](02-data-model-and-format.md#decomposing-the-ifc-graph-into-records), [11](11-spike-results.md) |
| D35 | Strings stored exactly as parsed (no NFC); INTEGER vs REAL kept distinct; SETs sorted | Decided (spike S3) | [02](02-data-model-and-format.md#canonical-format) |
| D36 | Import validates input and reports schema-invalid data and duplicate GlobalIds (repair / read-only / cancel) | Proposed (spike S3) | [02](02-data-model-and-format.md#import-policies-from-spike-s3) |
| D37 | Build dependencies (IfcOpenShell C++ + Python) come from **conda-forge** shared-library builds; pip wheels can't share a model with C++ | Decided (spike S1) | [01](01-architecture.md#python), [11](11-spike-results.md) |
| D38 | Display tessellation uses the **hybrid CGAL/OCCT kernel**; exact OCCT for precise ops | Decided (spike S2) | [05](05-geometry-rendering-drawings.md#geometry-pipeline) |
| D39 | Git storage: **packs only** (no loose objects), **no deltas** for record blobs, adaptive sharding, model cache for opening | Decided (spike S5) | [03](03-versioning.md#repository-layout) |
| D40 | Python ↔ Rust via **PyO3** (`kimcad._core`); C++ ↔ Rust via `cxx` later: two boundaries, for speed | Decided | Owner |
| D41 | Slice 1 CLI is Python (it needs ifcopenshell); Rust owns storage: writes via `git fast-import`, reads via gix; one shard level until adaptive sharding is needed | Decided | [plan](superpowers/plans/2026-10-04-slice1-cli-versioning.md) |
| D42 | Viewport draws elements in **batches** (~1,000 per OCCT AIS object, grouped by storey/type) with **one selection owner per element**; never one AIS object per element | Decided (spike S2) | [05](05-geometry-rendering-drawings.md#rendering), [11](11-spike-results.md#viewer-occt-ais-rendering-picking-and-memory) |
| D43 | OCCT pinned to the conda-forge **`novtk`** build: the default build pulls Mesa's `opengl32.dll`, forcing software rendering on Windows | Decided (spike S2) | [11](11-spike-results.md#viewer-occt-ais-rendering-picking-and-memory) |
| D44 | App ↔ model engine: embedded CPython running `kimcad.app_bridge`; protocol is JSON strings for structured data and raw little-endian arrays for meshes; the C++ side never parses IFC | Decided (Slice 2) | [01](01-architecture.md), [plan](superpowers/plans/2026-10-04-slice2-desktop-viewer.md) |
| D45 | Viewport = OCCT V3d/AIS in a native Qt widget, navigation and click-selection through `AIS_ViewController`; batches are a custom `ElementBatch` AIS object (flat triangle arrays, per-element owners, palette by IFC class) | Decided (Slice 2) | [05](05-geometry-rendering-drawings.md#rendering) |
| D46 | `IfcOpeningElement` and `IfcSpace` are not drawn by default (voids; room volumes hide walls); both stay in the tree and properties | Decided (Slice 2) | [plan](superpowers/plans/2026-10-04-slice2-desktop-viewer.md) |
| D47 | GUI language reconfirmed: C++ Qt app (not a PySide6 hybrid) after comparison on 2026-10-04 | Decided | Owner |
| D48 | Navigation = Revit/ArchiCAD preset (middle pan, Shift+middle orbit around the picked point, wheel zoom at cursor); selection click = replace, Ctrl = add, Shift = toggle, left-drag = box select | Decided (owner, 2026-10-05) | [04](04-app-features.md#2-viewport-and-navigation) |
| D49 | Edits go through `ifcopenshell.api` inside ifcopenshell file transactions: one transaction per user action (bulk edits included); values keep their IFC type, invalid input changes nothing; edits write the element's own property set (type-level values are overridden, not changed) | Decided (Slice 3) | [plan](superpowers/plans/2026-10-05-slice3-navigation-and-data-editor.md) |
| D50 | Type vs. element properties follow the Revit model: values inherited from the type are shown dimmed; a normal edit writes the element's own value (override); changing the type is a separate, confirmed action (*Edit type value…*, shows how many elements change); *Reset to type value* removes the override. Overridden elements keep their value when the type changes | Decided (owner, 2026-10-05) | [plan](superpowers/plans/2026-10-05-slice3b-type-properties.md) |
| D51 | Modeling (M3): new projects are IFC4 in millimetres; the app/bridge boundary uses metres. Walls are `IfcWall` + layered `IfcWallType`, drawn by their centre line, joined with `IfcRelConnectsPathElements` via ifcopenshell's wall API (no Bonsai port). Every modeling command reports the shapes it changed; the 3D view re-meshes only those (old instances retired, new ones in overlay batches), including after undo/redo | Decided (Slice 4) | [plan](superpowers/plans/2026-10-05-slice4-walls-and-levels.md) |
| D52 | Box selection takes only visible elements by default: the view is rendered once into an offscreen image with each element's id as a flat colour (colour space calibrated per render), and the box result is intersected with the ids seen; Alt+drag or a View setting selects through. Lines-only display is hidden-line (faces in the background colour + black border lines), and every element shows border lines (boundary + creases > 30°) | Decided (owner feedback, Slice 4b) | [plan](superpowers/plans/2026-10-05-slice4b-view-quality.md) |
| D53 | Doors/windows: the size lives on the occurrence (`OverallWidth/Height`); types carry KIMCAD defaults (Width, Height, SillHeight) in a custom pset `KIMCAD_OpeningDefaults` because IFC types have no size attributes. Each door/window fills its own `IfcOpeningElement` voiding the host wall; deleting a wall deletes its openings and fillings. Slabs: layered `IfcSlabType`, top of slab at the level, "from walls" uses the walls' outer faces. A failed rollback marks the model inconsistent (edits stop until the file is reopened) instead of continuing silently | Decided (Slice 5) | [plan](superpowers/plans/2026-10-05-slice5-slabs-doors-windows.md) |
| D54 | Editing keeps the model connected (owner, 2026-10-05): moving/rotating walls drags the walls joined to them along, so corners stay closed: a joined wall's end slides along its own line to meet the moved wall (it stays straight; it follows the full movement only when the two are parallel); Ctrl on the final click detaches instead (the joins to unmoved walls are dropped). Hosted openings, doors and windows move with their wall; stretching a wall end keeps its doors in place and drops only the join at the end that moved. Edits never change GlobalIds | Decided (owner) | [plan](superpowers/plans/2026-10-05-slice6-structure-grids-editing.md) |
