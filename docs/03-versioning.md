# 03 — Versioning

## Key decision: the KIMCAD repository *is* a Git repository

**Decided.** The owner said: "reduce all work as much as possible" and "the git style is for storing". So KIMCAD does not build its own object store, pack format, refs and transfer protocol. It stores its canonical records **as Git objects**:

| KIMCAD concept | Git object |
|----------------|-----------|
| Canonical record (object / shared value / geometry) | blob |
| Model state (all records) | tree, sharded by ID prefix |
| Version ("commit") | commit |
| Design option ("branch") | branch ref |
| Milestone ("tag") | annotated tag |

What this gives us for free:

- Content addressing, a Merkle structure, deterministic state hashes (the root tree hash), packfiles, delta compression and garbage collection.
- **Remotes and sync today**: push/pull to any Git host (Gitea, GitLab, GitHub, a bare repo on a NAS) with no KIMCAD server. That covers most of "future sync" with zero code. See [08](08-future.md).
- **Push-time checks**: server-side hooks on a Git host can enforce permissions and validation (owner answer 5).
- Inspectability: `git log` works, and records can be read as JSON.

What it costs:

- Git uses SHA-1 (or SHA-256) for storage. KIMCAD still uses BLAKE3 for its own content keys (loose and geometry records, and the initial IDs of shared nodes), so the two hash spaces are independent.
- We must use a custom **merge** (Git's text merge is never used on records) and keep Git from checking out 1M files (see below).

**Library:** `gitoxide` (`gix`, pure Rust, MIT/Apache-2.0) for object and ref access. For network operations where `gix` is still incomplete, call the `git` CLI as a fallback. Bonsai's IfcGit does exactly this.

### Repository layout

```text
my-project/
├── .git/                     # standard Git object database (no working-tree checkout of records)
├── kimcad.toml               # project manifest: format version, IFC schema, units, model resolution
├── .kimcad/                  # local only, never committed
│   ├── cache/                # model snapshot per tree hash, meshes, spatial indexes
│   ├── oplog/                # crash-recovery log of uncommitted operations
│   └── index.db              # search index (SQLite)
└── exports/                  # optional: IFC exports for people without KIMCAD
```

Tree structure inside each commit:

```text
kimcad.toml
objects/<aa>/<bb>/<kimcad-id>.json      # rooted entity records          (o/)
nodes/<aa>/<bb>/<node-id>.json           # shared nodes, stable ids       (n/)
loose/<aa>/<hash>.json                   # unreferenced entities + count  (l/)
geometry/<aa>/<hash>.json                # heavy geometry records
```

**Adaptive sharding** (spike S5): use one 256-way level below about 64k records and two levels above. With two fixed levels, a 10k-record model produced 9,505 tree objects, almost one per record. At 1M records, two levels give about 15 records per leaf tree, so a one-record commit rewrites only a handful of small trees.

**Storage rules** (spike S5, see [11](11-spike-results.md#s5--git-object-database-at-scale)):

- **Records are written into the object database as packs, never as loose objects.** On Windows each loose object costs about 7.6 ms, so a 10k-record import took 140 s loose versus 2.9 s as a pack. A 1M-record import as one pack takes about 6.5 minutes. MVP uses `git fast-import`; a native `gix-pack` writer with parallel compression comes later.
- **Record blobs are packed without deltas** (`repack --window=0`). Deep delta chains made random reads about 30× slower and saved under 2% of space for small records. Without deltas, 100k records read back in 1.7 s sequentially and 0.2 s on 16 threads.
- **Commit cost does not depend on model size.** A one-record commit takes about 90 ms at 1M records.
- Records are never checked out as files, so Windows/Linux filesystems never see a million JSON files. `kimcad export-tree <dir>` materializes them for debugging. Opening a project normally reads the local model cache (`.kimcad/cache`, keyed by tree hash), not every record.

## Project modes: versioning is optional

**Decided (owner answer 1):** versioning can be enabled or disabled per project.

| Mode | Storage | What you get |
|------|---------|--------------|
| **Plain** | A single `.ifc` file | Open → edit → save IFC. Undo/redo only. Works like any IFC editor. |
| **Versioned** | A project folder (Git repo + `kimcad.toml`) | Full history, design options, compare, combine, object history. |

- **Enable versioning:** creates the repository from the current model. The first commit is "Initial import".
- **Disable versioning:** exports the current state to `.ifc` and reverts to Plain mode. History stays in the folder unless the user deletes it.

## Working state, operations and commits

```text
user command ──► transaction ──► IFC model updated ──► change set
                      │                                     │
                      ▼                                     ▼
               undo stack + oplog                 dirty object set
                                                          │
                                         "Save version" ──┘
                                                          ▼
                                 records for dirty objects → blobs → trees → commit
```

- Every edit goes through a **command/transaction** that produces a change set (spec §14 operation vocabulary: create/delete object, set attribute/property/placement/geometry, add/remove relationship, change type).
- The **oplog** is a local, append-only journal of uncommitted transactions. It is used for crash recovery and undo. It is not history (spec §15 coalescing): dragging a wall 300 times produces one dirty object and one record change at commit time.
- A **commit** serializes only dirty objects. Unchanged records are reused by hash, which is structural sharing.
- **Snapshots** (spec §34) come with this design for free. Each commit tree is a complete state, so no replay is ever needed.

## Diff ("Compare")

A diff compares two root trees. Unchanged subtrees are skipped by hash, so the cost depends on the size of the change, not the size of the model.

Diff categories (spec §16), all derived from record changes:

| Category | Derived from |
|----------|--------------|
| Semantic | Rooted records added / removed / IFC class changed |
| Property | `IfcPropertySet` / `IfcElementQuantity` records changed, at the property level |
| Relationship | `IfcRel*` records added / removed / changed |
| Spatial / placement | `ObjectPlacement` value changed |
| Geometry | `Representation` reference changed (hash differs). The visual overlay is computed from meshes on demand |
| Requirement | Future (IDS); see [08](08-future.md) |

In the UI, Compare colors the viewport (added / modified / removed) and shows a per-object before/after panel (spec §8.5).

## Merge ("Combine options")

**Decided (owner answer 2):** in Git-style collaboration, conflicts are resolved **at merge time** by the user. Real-time auto-merge is a separate, future mode (see [08](08-future.md#collaboration-modes)).

The merge is a three-way merge on records (base, ours, theirs):

1. **Per record:**
   - Unchanged on one side: take the other side.
   - Identical change on both sides: take it.
   - Created on both sides with the same ID: this cannot happen unless the IDs collided, so it is reported as an error.
   - **Deleted on one side, modified on the other: conflict.**
2. **Inside a record changed on both sides, per attribute:**
   - Different attributes changed: combine them automatically.
   - The same attribute changed to different values: **conflict**.
   - Property sets merge **per property**, not per set.
   - Placement merges as one value. Both sides moving the same object is a conflict.
3. **Integrity pass after the merge:**
   - Dangling references (to a deleted object) cause a **semantic conflict**.
   - Duplicate containment (an element contained in two storeys) causes a **semantic conflict**.
   - IFC schema rules (WHERE rules) are checked through IfcOpenShell validation.
4. **Coordination warnings (non-blocking):** a quick clash check on the changed objects only (spec §17: "a successful data merge does not imply successful coordination").

Conflicts are presented in the UI with both values and the base value, and the user picks ours, theirs or a manual edit. Nothing is resolved silently.

**Changed from spec §17:** the spec said "MOVE +100 and MOVE +200 may compose". With state-based records, placements are absolute, so both sides moving the same wall is a conflict. This is deliberate. Silently combining moves is rarely what an architect wants.

Merging is pure data comparison, so it is deterministic: any machine merging the same three commits gets the same tree hash.

**Prior art:** `ifcmerge` (Bruno Postle, GPL-3, Rust) implements three-way IFC merge on step IDs. Its conflict rules and test cases should be studied and, where they apply, ported.

## Import reconciliation

**Decided (owner answer 1):** re-importing an IFC exported from another tool (Revit, ArchiCAD…) into a versioned project tries to reconcile identities. Objects that cannot be matched lose their history link.

Matching cascade, from strongest to weakest:

1. **GlobalId** equals the GlobalId of an existing object.
2. **Authoring-tool ID**, for example `IfcElement.Tag` (Revit element ID) or an application-specific property, together with the same IFC class.
3. **Heuristic:** same class and type, same storey, similar name, nearby placement or centroid. The match gets a confidence score.

The result is a **reconciliation report** that the user reviews before committing:

```text
Matched by GlobalId     12,840
Matched by Tag             312   (GlobalId changed → updated)
Heuristic (review)          41
Unmatched → new            105
Missing → deleted           88
```

Heuristic matches require confirmation. The import then becomes an ordinary commit, and its diff is a normal Compare.

## Object history ("blame")

For any object or property, walk the commits that changed its record. Each step is cheap because the path is known (`objects/<aa>/<bb>/<id>.json`). The index (`.kimcad/index.db`) caches object → commits for speed.

## CLI

The engine is fully usable without the GUI:

```bash
kimcad init [--from model.ifc]
kimcad import model.ifc          # with reconciliation report
kimcad export -o model.ifc [rev]
kimcad status
kimcad commit -m "message"
kimcad log [--object <id>]
kimcad diff [rev] [rev]
kimcad branch / switch / tag
kimcad merge <branch>
kimcad blame <id> [property]
kimcad show <id> [rev]           # canonical JSON
kimcad export-tree <dir>
kimcad push / pull               # thin wrappers over git remotes
```
