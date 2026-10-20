# 00 — Vision and Scope

## One sentence

**KimBim is a native, open-source BIM authoring application for architects. It treats a building model like a source-code repository: you can edit locally, commit, branch, compare and merge, all at the level of BIM objects instead of files.**

## Audience

- **Primary:** architects and architectural designers who model buildings and produce documentation. They want an open, vendor-neutral tool that runs on Windows and Linux.
- **Secondary:** BIM coordinators who need to know *what changed, who changed it, and why*.
- **Contributors:** OSS developers (Rust, C++/Qt, Python) and the OSArch / IfcOpenShell community.

Architects are not software engineers. Git concepts must show up in architect language:

| Git concept | KimBim UI term |
|-------------|----------------|
| commit | **Save version** |
| branch | **Design option** / **Variant** |
| tag | **Milestone** (Concept, Schematic, DD, Tender, …) |
| merge | **Combine options** |
| diff | **Compare** |
| blame | **Object history** |

The CLI and docs keep the Git terms.

## Product principles

1. **Local-first.** Everything in scope works without a network or a server.
2. **OpenBIM.** IFC is the data schema, and the app reads and writes standard IFC. IDS and BCF come later. No proprietary lock-in.
3. **Native.** Qt desktop app for Windows and Linux. No web UI.
4. **Semantic, not file-based.** Versioning tracks objects, properties and relationships, not whole files.
5. **Deterministic.** The same model state always gives the same hash on every machine. See [02](02-data-model-and-format.md#determinism).
6. **Evidence over inference.** Deterministic engines (geometry, validation, history) are authoritative. AI, when it arrives, only explains and proposes.
7. **Reuse before build.** See [06](06-reuse-and-licensing.md).

## Scope

### In scope now: the local app

Detailed in [04-app-features.md](04-app-features.md).

- Open, create, edit and save IFC models (IFC4 first; IFC2X3 import; IFC4X3 when the libraries support it).
- 3D viewport with navigation, selection, filtering, section boxes and clipping planes ("cuts").
- Object data: properties, quantities, classifications, materials, types, relationships.
- Modeling of core architectural elements: walls, slabs, roofs, openings, doors, windows, columns, beams, spaces, stairs (basic).
- Cloning: copy/paste, duplicate, array, mirror, copy to storeys.
- Libraries: reusable type libraries (walls, doors, windows, furniture…) shared between projects.
- 2D drawings: plans, sections, elevations, with annotation and PDF/SVG export.
- **Local versioning**: save version, history, compare, design options (branches), combine options (merge), object history. Versioning is **optional per project**.
- `kimbim` CLI for everything the versioning engine does.
- UI in **English and Spanish** (i18n from the start).

### Future: designed for, not built now

Summarized in [08-future.md](08-future.md).

- Synchronization between repositories (push/pull to remotes).
- Real-time (live) collaboration.
- P2P discovery, relays, optional host/super-peer.
- Security (identities, signing, encryption) and permissions. For now the only checks are local checks and push-time checks on a remote.
- IDS validation pipelines / "BIM CI", BCF issue management.
- AI assistance.
- Federation of linked models, partial replication, large assets (point clouds, scans).
- Large-scale (1M+ object) optimization.

### Non-goals

- A web application.
- macOS in the first releases. It is not excluded, just not targeted.
- Rewriting IFC parsing, geometry kernels or drawing generation that already exist.
- A CDE replacement.
- Reproducing Revit/ArchiCAD feature-for-feature. KimBim covers the core architectural workflow well.

## Project identity

- **Name:** KimBim
- **Model:** community open-source project, no fixed timeline
- **License:** strong copyleft, GPL-3.0-or-later (Decided, see [06](06-reuse-and-licensing.md#kimbim-license))
