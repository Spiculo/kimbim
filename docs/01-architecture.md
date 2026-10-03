# 01 — Architecture

## Overview

```text
┌───────────────────────────────────────────────────────────────┐
│                     kimcad (Qt 6 desktop app, C++)            │
│  Viewport · Model tree · Properties · Libraries · Drawings     │
│  History / Compare · Design options · Commands / Undo         │
└───────────────┬───────────────────────────────┬───────────────┘
                │ C++ API                       │ C ABI (cxx / cbindgen)
┌───────────────▼──────────────┐   ┌────────────▼───────────────┐
│  MODEL ENGINE (C++ / Python) │   │  REPOSITORY ENGINE (Rust)  │
│                              │   │                            │
│  IfcOpenShell in-memory model│◄─►│  Canonical records + hashes│
│  Authoring operations        │   │  Git-backed object store   │
│   (ifcopenshell.api, C++)    │   │  Commits, refs, history    │
│  Geometry iterator (OCCT)    │   │  Diff, three-way merge     │
│  Spatial tree / clash        │   │  Import reconciliation     │
│  Drawing (SVG serializer)    │   │  CLI: `kimcad`             │
└──────────────────────────────┘   └────────────────────────────┘
```

Two engines, with one rule each:

- **The model engine owns the working state.** This is the model being edited right now. It is an IfcOpenShell in-memory IFC model, and all authoring logic reuses IfcOpenShell.
- **The repository engine owns history.** It turns working state into canonical, content-addressed records, then commits, diffs and merges them. It never needs a GUI.

The GUI is a client of both engines and never owns model state (spec decision 25).

## Why this split

The original spec put almost everything in Rust. That would mean re-implementing the IFC schema, the authoring logic (wall joins, openings, layer sets, types, property sets) and the geometry handling that IfcOpenShell already provides. Bonsai, the most complete open-source IFC authoring tool, is built on exactly that IfcOpenShell layer.

So the split follows **where mature code already exists**:

| Concern | Owner | Language | Reused from |
|---------|-------|----------|-------------|
| IFC schema, parsing, writing | Model engine | C++ | IfcOpenShell |
| Authoring operations | Model engine | Python, then C++ for hot paths | `ifcopenshell.api` (LGPL), Bonsai logic (GPL, porting allowed because KIMCAD is GPL) |
| Geometry / tessellation | Model engine | C++ | IfcOpenShell geometry iterator + OpenCASCADE |
| Spatial index / clash | Model engine | C++ | IfcOpenShell `IfcGeom::tree`, `ifcclash` |
| 2D drawings | Model engine | C++ | IfcOpenShell SVG serializer (used by Bonsai) |
| Canonical records, hashing | Repository engine | Rust | `serde`, `blake3` |
| Object store, commits, refs, packs | Repository engine | Rust | **Git object format** via `gitoxide` (see [03](03-versioning.md)) |
| Diff / merge | Repository engine | Rust | Own code; `ifcmerge` (GPL, Rust) as prior art |
| GUI | App | C++ | Qt 6 |

Rust keeps the parts where it is strongest and where nothing BIM-specific exists yet: deterministic serialization, hashing, storage, merge and, later, networking.

## Process model

**Phase 1 (now):** a single process.

```text
kimcad.exe
 ├── Qt GUI thread
 ├── Model engine (in-process, worker threads for geometry)
 ├── Embedded CPython (ifcopenshell.api, scripting, plugins)
 └── Repository engine (in-process Rust library)
```

**Later:** the repository engine can run as its own process (`kimcad serve`) for background work, headless CI and sync. The engine API is designed as message-style calls (request → result, with no shared pointers across the boundary), so moving it out of process means changing the transport, not redesigning the API.

## Engine boundaries

### GUI ↔ Model engine

- C++ API.
- **All edits are commands.** The GUI never changes the IFC model directly. It issues a command such as `SetProperty`, `MoveObjects` or `CreateWall`. The command runs as a transaction, emits a change set and records an undo entry.
- The change set (objects created, modified or deleted) drives viewport updates, panel refreshes and the repository's dirty tracking.

### Model engine ↔ Repository engine

- C ABI, generated with `cxx` (Rust ↔ C++) and a `cbindgen` header for third parties.
- Data crossing the boundary is **canonical records** (bytes). See [02](02-data-model-and-format.md).
- **Commit:** the model engine exports the records for dirty objects, and the repository writes blobs, trees and the commit.
- **Checkout:** the repository streams records, and the model engine rebuilds the IFC model. A local cache, keyed by tree hash, makes this fast.

### Python

- Embedded CPython runs `ifcopenshell.api` for authoring operations. It also gives architects scripting and a plugin system for free.
- **Spike S1:** can the C++ host and embedded `ifcopenshell` Python share one `IfcParse::IfcFile` instance without copying? If not, the Python layer owns the file and C++ reads it through the same SWIG-wrapped object. Either way there is exactly one in-memory model.

## Threading rules

1. The GUI thread never blocks on geometry, validation, hashing or I/O.
2. Model edits are serialized on a single model thread (a transaction queue). Reads during geometry processing use the change set and immutable snapshots.
3. Tessellation, spatial indexing, drawing generation and diff computation run on worker pools, and their results are posted back.

## Proposed source layout

```text
kimcad/
├── app/                 # Qt 6 C++ application (kimcad GUI)
│   ├── viewport/
│   ├── panels/          # tree, properties, libraries, history…
│   ├── commands/        # command definitions, undo stack
│   └── drawings/
├── engine/              # C++ model engine (wraps IfcOpenShell)
│   ├── model/
│   ├── geometry/
│   └── bridge/          # cxx bridge to Rust
├── crates/              # Rust workspace
│   ├── kimcad-format/   # canonical records, canonical JSON, hashing
│   ├── kimcad-repo/     # git-backed store, commits, refs
│   ├── kimcad-diff/
│   ├── kimcad-merge/
│   ├── kimcad-reconcile/# import identity reconciliation
│   ├── kimcad-ffi/      # C ABI
│   └── kimcad-cli/      # `kimcad` binary
├── python/kimcad/       # ops, scripting API, plugins
├── libraries/           # bundled default type libraries (.ifc)
├── tests/corpus/        # IFC test files (see 09)
└── docs/
```

## Build and dependencies (Proposed)

- **CMake** is the top-level build. **Corrosion** builds the Rust crates from CMake.
- **pixi + conda-forge** provide one reproducible dependency environment on Windows and Linux. conda-forge ships Qt 6, OpenCASCADE, IfcOpenShell and Python, which avoids building IfcOpenShell and OCCT from source. FreeCAD uses the same approach.
- CI runs on Windows and Linux and includes the cross-platform determinism tests (see [09](09-testing-and-quality.md)).
