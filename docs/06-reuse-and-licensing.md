# 06 — Reuse and Licensing

> **Rule (owner answer 7):** reduce work as much as possible. If an open-source project already does part of what KimBim needs, KimBim uses it.

> Not legal advice. Licenses below were checked against project pages as of 2026-10. Entries marked *verify* must be re-checked before the dependency is added.

## KimBim license

**Owner requirements (answer 8):** open source, no warranty or liability, and anyone who builds on top of it must also be open source.

**Decided: GPL-3.0-or-later** for the application, engines and CLI.

- **Copyleft:** anyone who distributes KimBim or a derivative must release the source under the GPL.
- **No responsibility:** sections 15–16 of the GPL disclaim all warranty and liability.
- **Compatibility:** it is the license of **Bonsai** and **ifcmerge**, so we can port their code and logic directly (with attribution).
- It is compatible with every LGPL, MIT, BSD, Apache-2.0 and MPL-2.0 dependency listed below.

**Open point:** GPL does not require source release when someone runs a modified KimBim *as a hosted service* without distributing it. When a server component exists (a future host/super-peer, [08](08-future.md)), license *that component* **AGPL-3.0-or-later** so hosted forks must share their changes too. GPL-3 explicitly allows combining with AGPL-3.

**Contributions:** use the **DCO** (Developer Certificate of Origin, a `Signed-off-by` line on each commit) rather than a CLA. Contributors keep their copyright, and no single party can later relicense the project as proprietary.

**To do:** add `LICENSE` (full GPL-3.0 text) and SPDX headers (`SPDX-License-Identifier: GPL-3.0-or-later`) to every source file.

## Projects that already do parts of KimBim

| Project | License | What it already does | How KimBim uses it |
|---------|---------|----------------------|--------------------|
| **IfcOpenShell** (C++ core, Python `ifcopenshell`, IfcConvert, IfcTester, ifcclash, ifccsv, bcf, ifc5d…) | LGPL-3.0-or-later | IFC parse/write, all schemas, geometry iterator (OCCT/CGAL), spatial tree, SVG drawings, authoring API, IDS, BCF, quantities | **Core dependency.** Model engine, geometry, drawings, IDS, BCF |
| **Bonsai** (Blender add-on) | GPL-3.0-or-later | Complete native-IFC authoring: walls and joins, parametric doors/windows/stairs/railings, arrays, drawings and sheets, libraries, **IfcGit** (Git UI for IFC) | **Port logic** (Python → our ops / C++). Reference UX for IFC authoring |
| **ifcmerge** | GPL-3.0 | Three-way merge of IFC files (Rust), conflict rules | **Prior art and test cases** for `kimbim-merge`; port rules |
| **FreeCAD** (BIM workbench, NativeIFC) | LGPL-2.1-or-later | Qt + OpenCASCADE + IfcOpenShell in one native desktop app on Windows/Linux; native IFC editing | **Reference integration** for build system (pixi/conda-forge), Qt↔OCCT↔IfcOpenShell wiring |
| **Open CASCADE Technology** | LGPL-2.1 + OCCT exception | BRep kernel, booleans, HLR, **interactive 3D visualization (AIS/V3d) with clipping and capping** | Geometry kernel (through IfcOpenShell) and **phase-1 renderer** |
| **Qt 6** | LGPL-3.0 (most modules), GPL-3.0 (some) | Native GUI, RHI (Vulkan/D3D/GL), SVG, PDF | GUI framework |
| **Git** / **gitoxide** (`gix`) | GPL-2.0 (git CLI, used as a separate program) / MIT OR Apache-2.0 | Content-addressed storage, packs, refs, transport, remotes | **Repository storage and sync** ([03](03-versioning.md)) |
| **Speckle** | Apache-2.0 | Object-level, content-addressed BIM data with decomposition of large objects and hashing | Prior art for record decomposition ([02](02-data-model-and-format.md)) |
| **IFC5 development** (buildingSMART) | MIT (viewer); schema *verify* | JSON-based IFC (IFCX) with composition/layers, still alpha | Shape our canonical JSON so future IFC5 support is cheap |
| **web-ifc** (That Open Company) | MPL-2.0 | Fast C++ IFC parser and tessellator (compiled to WASM, usable natively) | **Fallback option** if IfcOpenShell geometry is too slow for very large models |
| **BIMserver** | AGPL-3.0 *verify* | Server-side, object-level IFC versioning (Java) | Lessons only; do not link |
| **xeokit** | AGPL-3.0 | Web BIM viewer | Not needed (we are native) |

### Rust crates (Proposed)

| Crate | License | Use |
|-------|---------|-----|
| `serde`, `serde_json` | MIT OR Apache-2.0 | Records |
| `blake3` | CC0-1.0 OR Apache-2.0 | Value / geometry hashes |
| `ryu` | Apache-2.0 OR BSL-1.0 | Shortest round-trip float formatting |
| `gix` (gitoxide) | MIT OR Apache-2.0 | Git object DB / refs |
| `cxx` | MIT OR Apache-2.0 | Rust ↔ C++ bridge |
| `cbindgen` | MPL-2.0 (build tool only) | C header generation |
| `rusqlite` (SQLite) | MIT (SQLite: public domain) | Local index |
| `clap` | MIT OR Apache-2.0 | CLI |
| `zstd` | MIT / BSD | Cache compression |

### Build tooling

| Tool | License | Use |
|------|---------|-----|
| CMake | BSD-3-Clause | Top-level build |
| Corrosion | MIT | Rust crates in CMake |
| pixi + conda-forge | BSD-3-Clause / per-package | Reproducible Win/Linux deps |

### Future (see [08](08-future.md))

| Project | License | Use |
|---------|---------|-----|
| Loro or Automerge | MIT | CRDT for live collaboration |
| iroh / quinn | MIT OR Apache-2.0 | QUIC P2P, NAT traversal, relays |
| Forgejo / Gitea | GPL-3.0-or-later (Forgejo) / MIT (Gitea) *verify* | Self-hosted remote with server hooks |
| `ed25519-dalek` | BSD-3-Clause | Signing (later) |

## Compatibility rules for new dependencies

1. **OK:** MIT, BSD, ISC, Zlib, Apache-2.0, MPL-2.0, LGPL-2.1/3.0, GPL-3.0, CC0, public domain.
2. **Careful:**
   - LGPL libraries are linked **dynamically** and stay replaceable.
   - GPL-2.0-*only* code cannot be combined with GPL-3. Using it as a *separate program* (like the `git` CLI) is fine.
3. **Avoid:**
   - AGPL code inside the desktop app.
   - Non-commercial, "source-available" or proprietary libraries.
   - Anything without a license.
4. Every new dependency is added to a `THIRD_PARTY.md` with its license and how it is linked.
