# OpenBIM Native Collaboration Platform

## Project Specification — v0.1

**Status:** Architecture / Product Definition
**Target platforms:** Windows and Linux
**Primary application:** Native desktop GUI
**Core architecture:** Local-first, decentralized, Git-like BIM repository
**Primary languages:** Rust + C++ + C ABI
**Domain:** OpenBIM / BIM collaboration / version control / real-time coordination

---

# 1. Executive Summary

The project is an open-source, native BIM platform designed around a fundamental idea:

> **A BIM project should behave like a distributed version-controlled repository rather than a collection of large files managed by a centralized CDE.**

Every workstation can contain a BIM repository. Users work locally, create semantic model changes, commit revisions, create branches, review changes, and synchronize with other repositories.

Collaboration can occur:

* locally;
* over a LAN;
* directly between peers;
* through an optional host/super-peer;
* through a hybrid architecture.

The network is therefore an optimization and collaboration mechanism, not a fundamental dependency.

The platform combines:

* openBIM interoperability;
* native Windows/Linux GUI;
* Git-like version control;
* BIM-aware semantic diff and merge;
* real-time collaboration;
* P2P synchronization;
* local-first operation;
* deterministic BIM validation;
* geometry analysis;
* BCF/IDS integration;
* cryptographic identity and auditability;
* optional AI assistance.

The central architectural decision is that **IFC is not the repository's native versioning format**.

Instead:

```text
IFC
 ↓
Canonical BIM Object Graph
 ↓
Semantic Operations
 ↓
Repository / Commit Graph
 ↓
Sync / Merge / Validation
 ↓
IFC export when required
```

This allows the system to version BIM objects and their relationships rather than repeatedly storing and comparing enormous IFC files.

---

# 2. Product Vision

The product is conceptually:

> **Git + Google-Docs-style collaboration + BIM-native semantic modeling + openBIM + local-first architecture.**

However, the system is not intended to reproduce Git literally.

Git provides the conceptual model:

* repositories;
* commits;
* branches;
* tags;
* history;
* diffs;
* merge;
* provenance.

BIM requires additional semantics:

* objects;
* properties;
* relationships;
* geometry;
* spatial structure;
* requirements;
* coordination;
* validation;
* model identity.

The platform therefore extends the version-control model specifically for BIM.

---

# 3. Product Principles

## 3.1 Local-first

The application must work without a network.

A user should be able to:

* open a project;
* inspect models;
* modify objects;
* create branches;
* commit changes;
* inspect history;
* run validation;

without requiring a server.

Networking adds collaboration and persistence, but is not required for basic operation.

---

## 3.2 OpenBIM

The platform must remain vendor-neutral.

Important standards and technologies include:

* IFC;
* IDS;
* BCF;
* bSDD;
* openCDE-compatible concepts;
* standard BIM classifications and property structures.

The repository itself should not become dependent on one proprietary authoring system.

---

## 3.3 Native

The primary application is a native desktop application.

Target platforms:

* Windows;
* Linux.

The project explicitly does **not** use a Web UI as the primary interface.

The GUI should have direct access to:

* GPU resources;
* filesystem;
* local repositories;
* native networking;
* background processes;
* native BIM/geometry libraries.

---

## 3.4 Semantic rather than file-oriented

The system should not treat an IFC file as a giant opaque binary/text blob.

A modification such as:

```text
Wall.FireRating:
    EI30 → EI60
```

should be represented as a semantic object/property change.

It should not require storing a completely new multi-gigabyte model.

---

## 3.5 Deterministic

Whenever possible:

```text
same input
+
same operations
+
same engine version
=
same state
```

Repository states should have deterministic hashes.

This allows different machines to verify that they reconstructed the same BIM state.

---

## 3.6 Evidence over inference

For BIM facts, deterministic engines are authoritative.

AI may interpret and explain information, but should not become the source of truth.

For example:

```text
AI:
"These walls appear to conflict."

Geometry engine:
"Wall A and Wall B intersect by 87 mm."

IDS:
"Wall A fails requirement IDS-023."

Repository:
"Wall A was modified in commit 8f91c2."
```

AI can combine these facts into an explanation.

---

# 4. High-Level Architecture

```text
                    NATIVE DESKTOP APPLICATION
                    ┌─────────────────────────┐
                    │        Qt 6 GUI         │
                    │                         │
                    │  3D View                │
                    │  Model Tree             │
                    │  Properties             │
                    │  History / Diff         │
                    │  Branches / Commits     │
                    │  Collaboration          │
                    │  Issues / Validation    │
                    │  AI Tools               │
                    └────────────┬────────────┘
                                 │
                          Native API / ABI
                                 │
                    ┌────────────▼────────────┐
                    │       BIM ENGINE        │
                    │          Rust           │
                    │                         │
                    │ Repository              │
                    │ Version Control         │
                    │ Operations              │
                    │ Merge                   │
                    │ Synchronization         │
                    │ P2P                     │
                    │ Crypto                  │
                    │ Validation              │
                    │ AI Tool Interface       │
                    └──────┬─────────┬────────┘
                           │         │
                     C/C++ FFI       │
                           │         │
             ┌─────────────▼───┐     │
             │  IFC / Geometry │     │
             │                 │     │
             │ IfcOpenShell    │     │
             │ OpenCASCADE     │     │
             └─────────────────┘     │
                                     │
                           ┌─────────▼─────────┐
                           │ Network / P2P     │
                           │                   │
                           │ Peers             │
                           │ Host              │
                           │ Relay             │
                           │ Workers           │
                           └───────────────────┘
```

---

# 5. Technology Stack

| Layer        | Technology                             | Purpose                                           |
| ------------ | -------------------------------------- | ------------------------------------------------- |
| Desktop GUI  | Qt 6 / C++                             | Native Windows/Linux application                  |
| Core engine  | Rust                                   | Repository, concurrency, networking, transactions |
| Stable ABI   | C                                      | Plugin and language integration boundary          |
| IFC          | IfcOpenShell / C++                     | IFC parsing, semantics and import/export          |
| Geometry     | OpenCASCADE and specialized libraries  | Exact geometry / BRep                             |
| Rendering    | Vulkan-oriented native renderer        | Large-model visualization                         |
| Storage      | Filesystem + embedded database/indexes | Repository and metadata                           |
| Networking   | QUIC-oriented transport                | Low-latency synchronization                       |
| Cryptography | Native Rust crypto stack               | Identity, signatures, encryption                  |
| Validation   | Native rule engine                     | IDS and BIM validation                            |
| AI           | Pluggable local/remote inference       | Interpretation and orchestration                  |

---

# 6. Language Strategy

## Rust

Rust should form the core of the platform.

Responsibilities:

* repository;
* object storage;
* commit graph;
* operations;
* transactions;
* synchronization;
* P2P;
* cryptography;
* permissions;
* indexing;
* concurrency;
* event processing;
* CLI;
* validation orchestration;
* AI tool API.

Rust is particularly appropriate for the distributed and concurrent parts of the system.

---

## C++

C++ should be used where the BIM/geometry ecosystem provides mature capabilities.

Responsibilities include:

* Qt GUI;
* IfcOpenShell integration;
* OpenCASCADE;
* geometry algorithms;
* selected rendering integrations;
* existing BIM/CAD interoperability.

The project should avoid rewriting mature BIM infrastructure merely to use one language.

---

## C ABI

A C-compatible API should provide a stable boundary.

Conceptually:

```text
libopenbim.so
openbim.dll
libopenbim.dylib
```

This allows:

* C++;
* Rust;
* Python;
* plugins;
* future language bindings;

to communicate with the engine without depending on Rust's unstable ABI.

---

# 7. Native GUI

The GUI is a first-class component.

It is not a web application wrapped in a desktop shell.

Qt 6 is the proposed framework.

The GUI should expose the repository model directly.

---

# 8. Main GUI Areas

## 8.1 3D Viewport

Capabilities:

* model navigation;
* selection;
* visibility;
* sectioning;
* clipping;
* spatial navigation;
* object highlighting;
* issue visualization;
* conflict visualization;
* geometry comparison;
* branch/revision comparison.

---

## 8.2 Repository Panel

Shows:

```text
Project
 ├── Models
 │   ├── Architecture
 │   ├── Structure
 │   └── MEP
 │
 ├── Branches
 │   ├── main
 │   ├── structural
 │   └── mep
 │
 ├── Tags
 │   ├── schematic
 │   ├── DD
 │   └── tender
 │
 └── History
```

---

## 8.3 Model Tree

The model tree should expose:

* spatial hierarchy;
* object types;
* classifications;
* relationships;
* linked models;
* object identity.

---

## 8.4 Properties

The property panel should expose:

* properties;
* quantities;
* materials;
* classifications;
* relationships;
* provenance;
* change history.

---

## 8.5 History / Diff

A BIM-native diff should show:

```text
Commit 8f91c2

+ 14 objects
~ 37 objects
- 2 objects

Geometry:
  12 moved
   3 modified

Properties:
  19 changed

IDS:
  2 failures

Spatial:
  3 new intersections
```

Selecting an object can show:

```text
Wall W-183

BEFORE
Location: (12.20, 4.10, 0)
FireRating: EI30

AFTER
Location: (12.45, 4.10, 0)
FireRating: EI60

Author: Felipe
Commit: 8f91c2
```

---

# 9. Repository Architecture

Each project is a repository.

Conceptually:

```text
project/
└── .bim/
    ├── objects/
    ├── packs/
    ├── commits/
    ├── operations/
    ├── refs/
    ├── indexes/
    ├── snapshots/
    ├── assets/
    └── config
```

The repository is content-addressed.

Conceptually:

```text
canonical object encoding
        ↓
      BLAKE3
        ↓
    object ID
```

Objects are immutable.

---

# 10. Structural Sharing

A BIM object should not necessarily be stored as one enormous serialized structure.

For example:

```text
Wall
 ├── Identity
 ├── Placement
 ├── Geometry
 ├── Properties
 ├── Material
 └── Relationships
```

If only the FireRating changes, the system should reuse:

```text
Identity
Placement
Geometry
Material
Relationships
```

and create a new property state.

This minimizes:

* storage;
* network traffic;
* memory usage;
* synchronization cost.

---

# 11. IFC as an Interchange Boundary

IFC is not the primary repository representation.

The pipeline is:

```text
IFC
 ↓
IfcOpenShell
 ↓
Canonical BIM Object Graph
 ↓
Repository
 ↓
Semantic operations
 ↓
Commit
```

Export:

```text
Repository state
 ↓
Canonical BIM graph
 ↓
IfcOpenShell
 ↓
IFC
```

This avoids depending on unstable IFC serialization for version control.

---

# 12. Object Identity

IFC GlobalId is insufficient as the sole repository identity.

The platform should maintain a repository-level object identity.

Conceptually:

```text
BIM Object
 ├── Repository Object ID
 ├── IFC GlobalId
 ├── Authoring-system ID
 ├── Source application
 └── Identity history
```

This permits an object to retain its repository identity even if an external authoring system changes its IFC GlobalId.

Identity reconciliation becomes an important subsystem.

---

# 13. Version Control

The repository follows a Git-like model.

### Repository

The BIM project.

### Branch

An independent development line.

Examples:

```text
main
architecture
structure
mep
coordination
proposal/fire-rating
```

### Commit

An immutable semantic revision.

### Tag

A named milestone.

Examples:

```text
concept
schematic
DD
tender
construction
as-built
```

### Diff

Comparison of two BIM states.

### Merge

Integration of semantic changes.

### Pull Request

Proposed BIM integration.

### Blame

Object/property provenance.

---

# 14. Semantic Operations

Changes should be represented as typed operations.

Initial operation vocabulary:

```text
CREATE_OBJECT
DELETE_OBJECT
SET_PROPERTY
SET_PLACEMENT
SET_GEOMETRY
ADD_RELATIONSHIP
REMOVE_RELATIONSHIP
CHANGE_TYPE
```

Operations are applied transactionally.

Example:

```text
SET_PROPERTY(
    object = Wall-183,
    property = FireRating,
    value = EI60
)
```

---

# 15. Working State and Commits

Editing should not necessarily create a commit for every mouse movement.

Instead:

```text
LIVE EDITS
    ↓
operations
    ↓
working state
    ↓
coalescing
    ↓
meaningful commit
```

For example, dragging a wall 300 times should not necessarily create 300 commits.

The final transaction could become:

```text
Move Wall-183
(12.20, 4.10)
→
(12.50, 4.10)
```

The lower-level operation stream can remain available for collaboration/recovery if needed.

---

# 16. BIM-Native Diff

There should be several kinds of diff.

### Semantic diff

Object creation/deletion/type changes.

### Property diff

Property and quantity changes.

### Relationship diff

Changes to aggregation, containment, connections and associations.

### Spatial diff

Changes to spatial placement and relationships.

### Geometry diff

Changes in actual geometry.

### Requirement diff

Changes affecting IDS or other validation rules.

A single commit may therefore contain multiple categories of changes.

---

# 17. BIM-Native Merge

Generic text merging is insufficient.

The merge engine must understand BIM semantics.

Example:

```text
Branch A:
MOVE Wall +100mm

Branch B:
MOVE Wall +200mm
```

Depending on operation semantics, these may potentially compose.

But:

```text
Branch A:
FireRating = EI30

Branch B:
FireRating = EI60
```

is a property conflict.

Another example:

```text
Branch A:
move duct north

Branch B:
move beam south
```

may merge cleanly at the data level while creating a new geometric collision.

Therefore:

> **Successful data merge does not imply successful BIM coordination.**

---

# 18. Conflict Classes

| Conflict    | Description                                       |
| ----------- | ------------------------------------------------- |
| Property    | Incompatible values assigned to the same property |
| Semantic    | Result violates a BIM relationship or rule        |
| Geometric   | Resulting geometry conflicts                      |
| Spatial     | Coordination issue between elements               |
| Ownership   | Change violates ownership policy                  |
| Requirement | Result violates IDS or another requirement        |

The system should identify conflicts and present evidence.

AI may explain them but should not silently choose a solution.

---

# 19. Geometry Architecture

Geometry is separated from semantic state.

An object may have:

```text
Wall
 ├── Exact BRep
 ├── Mesh
 ├── AABB
 └── BVH references
```

This allows different subsystems to use the appropriate representation.

For example:

```text
AABB / spatial index
        ↓
candidate objects
        ↓
exact geometry test
```

The system should never perform expensive exact geometry tests against every object in a large model.

---

# 20. Spatial Processing

Potential spatial structures:

* R-tree;
* BVH;
* IFC spatial hierarchy;
* specialized broad-phase indexes.

Geometry processing must be asynchronous.

A local edit should not wait for:

* complete clash detection;
* complete tessellation;
* full model validation;
* AI analysis.

---

# 21. Rendering Architecture

The renderer should be separated from the Qt application logic.

Conceptually:

```text
Qt
 │
 └── Native View
       │
       ▼
    Renderer
       │
       ├── Vulkan
       └── platform-specific integration
```

The renderer should support:

* GPU instancing;
* batching;
* frustum culling;
* occlusion culling;
* level of detail;
* incremental scene updates;
* asynchronous geometry loading;
* spatial partitioning.

The target is large BIM models without rebuilding the entire scene after small edits.

---

# 22. Real-Time Collaboration

Collaboration consists of two separate systems.

## BIM/Sync

Durable repository synchronization.

Handles:

* commits;
* branches;
* refs;
* objects;
* packs;
* repository state;
* replication.

## BIM/Live

Ephemeral collaboration.

Handles:

* presence;
* selections;
* camera;
* cursors;
* live operations;
* comments;
* optional locks.

Presence and camera information must not pollute durable Git-like history.

---

# 23. Collaboration Topologies

### Solo

```text
User
 ↓
Local repository
```

### LAN P2P

```text
User A ←────→ User B
   ↕             ↕
        User C
```

### Internet P2P

```text
Peer A ←────────→ Peer B
       secure connection
```

### Hosted

```text
Peer A ──┐
Peer B ──┼── Host
Peer C ──┘
```

### Hybrid

```text
Local repositories
        ↕
      Peers
        ↕
Optional persistent host
```

The host is not the canonical source of truth.

---

# 24. Host / Super-Peer

An optional host can provide:

* peer discovery;
* relay;
* persistent storage;
* backup;
* repository availability;
* access control;
* indexing;
* CI;
* validation;
* AI workers.

This gives organizations a server when they want one without making the architecture inherently centralized.

---

# 25. Network Architecture

The system should be network-independent.

```text
No network
    ↓
Local editing works

LAN
    ↓
Fast peer synchronization

Internet
    ↓
Remote synchronization

Host
    ↓
Persistent infrastructure

Cloud
    ↓
Optional acceleration
```

Networking should never be required merely to open or edit a local project.

---

# 26. Synchronization

Synchronization exchanges objects and operations, not complete IFC files.

Conceptually:

```text
Peer A:
commit A

Peer B:
commit B

A asks:
"What objects reachable from B do I not have?"

B sends:
missing objects / operations / packs

A:
reconstructs B
merges
```

This follows the general content-addressed synchronization model used by distributed version-control systems.

---

# 27. Offline Collaboration

Users can continue editing without connectivity.

When connectivity returns:

```text
Local branch A
       \
        merge
       /
Local branch B
```

Causal metadata is required to distinguish:

* sequential edits;
* concurrent edits;
* stale edits.

Potential mechanisms include:

* Lamport clocks;
* hybrid logical clocks;
* vector-style causal metadata.

The actual merge remains BIM-domain-specific.

---

# 28. P2P Discovery

Potential mechanisms:

### LAN

mDNS/local discovery.

### Internet

Rendezvous service or DHT-style discovery.

### Explicit host

User enters host address.

### NAT traversal

Direct connection where possible, relay otherwise.

The relay should ideally transport encrypted traffic without requiring access to project contents.

---

# 29. Security

Security is part of the architecture rather than an afterthought.

Capabilities:

* cryptographic user identities;
* device identities;
* signed commits;
* encrypted peer connections;
* optional repository-at-rest encryption;
* ACLs;
* capability-based permissions;
* key rotation;
* device revocation;
* audit logs.

A host should not automatically be able to read encrypted project data.

---

# 30. Repository Permissions

The system may eventually support permissions at multiple levels:

```text
Organization
    ↓
Repository
    ↓
Model
    ↓
Discipline
    ↓
Object
    ↓
Property
```

However, fine-grained permissions should not be implemented prematurely if they create excessive synchronization complexity.

The initial architecture should establish the capability model so it can evolve toward finer granularity.

---

# 31. Linked Models / Federation

Large projects will often contain multiple models.

The repository should support linked models conceptually similar to:

```text
Project
 ├── Architecture repository
 ├── Structure repository
 ├── MEP repository
 ├── Site repository
 └── Infrastructure repository
```

Federation should avoid unnecessarily copying all model data into every repository.

This points toward:

* linked repositories;
* partial replication;
* dependency references;
* federation manifests.

---

# 32. Large Assets

Not everything should be treated as a normal small BIM object.

Large assets may include:

* point clouds;
* textures;
* large meshes;
* documents;
* raw IFC files;
* images;
* scans.

These should use an asset/content-addressed subsystem analogous to Git LFS-style concepts.

The repository should reference them rather than repeatedly duplicating them.

---

# 33. Repository Storage

A practical initial implementation can use:

```text
Filesystem
+
Content-addressed objects
+
Pack files
+
Embedded database/index
```

The embedded database should primarily serve indexing/search rather than become the authoritative BIM state.

Potential future alternatives can be benchmarked against:

* SQLite;
* RocksDB;
* redb;
* custom append-only storage.

The correct choice should be benchmark-driven.

---

# 34. Snapshots and History

An operation/event history alone can eventually become expensive to replay.

Therefore the repository should periodically create snapshots/checkpoints.

Conceptually:

```text
Snapshot 1000
   ↓
operations 1001...1200
   ↓
Snapshot 1200
```

Historical inspection can then use the nearest checkpoint instead of replaying the entire project history.

---

# 35. Deterministic State

Every repository state should ideally have a deterministic state hash.

Conceptually:

```text
Object hashes
      ↓
Merkle structure
      ↓
Commit hash
      ↓
Repository state hash
```

Two machines can therefore verify:

```text
State A == State B
```

without comparing entire model files.

---

# 36. AI Architecture

AI is not the BIM database.

AI is an interface over deterministic BIM tools.

Possible tools:

```text
query_bim()
run_ids()
inspect_geometry()
get_history()
search_documents()
search_objects()
create_bcf()
propose_operations()
```

Example:

User:

> Why did this wall become non-compliant?

AI:

1. Finds the wall.
2. Gets its current state.
3. Gets history.
4. Finds the relevant IDS requirement.
5. Compares the previous revision.
6. Runs validation.
7. Explains the result.

The AI answer should be grounded in repository evidence.

---

# 37. AI Modifications

AI must not directly mutate arbitrary repository memory.

The flow should be:

```text
AI request
    ↓
Tool call
    ↓
Proposed operation
    ↓
Validation
    ↓
Transaction
    ↓
Commit
    ↓
Audit record
```

This makes AI-generated changes:

* reviewable;
* reversible;
* attributable;
* testable.

---

# 38. Local AI

Local AI is desirable because BIM projects can contain sensitive information.

The platform should eventually support policy-controlled AI execution:

```text
LOCAL ONLY
COMPANY MODEL
EXTERNAL MODEL
DISABLED
```

The policy determines what data may leave the workstation.

---

# 39. Documents and Non-BIM Data

A future repository should not contain only geometry.

A project may eventually include:

```text
BIM models
Documents
Requirements
Specifications
Issues
Approvals
Contracts
Schedules
Images
Point clouds
Reports
```

The architecture should therefore be extensible beyond IFC while keeping BIM as its central domain.

---

# 40. Validation / CI

The repository can eventually support BIM CI pipelines.

For example:

```text
commit
  ↓
IFC/schema validation
  ↓
IDS validation
  ↓
property checks
  ↓
geometry checks
  ↓
spatial coordination
  ↓
quantity checks
  ↓
report
```

A commit can receive validation results.

A branch can therefore have:

```text
Build:
PASS

IDS:
143 / 145

Geometry:
PASS

Coordination:
3 issues
```

The exact policy of whether a failure blocks merging should remain configurable.

---

# 41. BCF Integration

BCF should represent issues and coordination findings.

A BCF issue can reference:

* BIM Object ID;
* IFC GlobalId;
* repository revision;
* branch;
* viewpoint;
* geometry;
* responsible party.

This creates a direct connection:

```text
Issue
 ↓
Object
 ↓
Revision
 ↓
Commit
 ↓
Author
```

---

# 42. Provenance

Every important model state should be traceable.

For an object:

```text
Object
 ↓
Created in commit
 ↓
Modified in commit
 ↓
Modified by user
 ↓
Related issue
 ↓
Validation
 ↓
Approved/tagged state
```

This becomes the BIM equivalent of `git blame`.

---

# 43. Branching Strategy

Traditional BIM software can create excessive parallel copies.

The platform should support lightweight branches, including ephemeral proposal branches.

Example:

```text
main
 │
 ├── structural
 │
 ├── mep
 │
 └── proposal/fire-rating
```

A proposal can be created, reviewed, merged or discarded without copying an entire model.

---

# 44. Pull Requests

A BIM pull request should show:

```text
Source branch
Target branch

Objects:
+ 24
~ 102
- 4

Property changes:
18

Geometry changes:
7

IDS:
2 failures

Spatial conflicts:
3

BCF:
4 related issues

AI review:
available
```

Reviewers can inspect actual BIM changes rather than textual IFC changes.

---

# 45. Native Process Architecture

Initially:

```text
bim-gui
   │
   └── embedded BIM engine
```

The architecture should nevertheless define an engine boundary:

```text
bim-gui
    │
    ▼
bim-engine API
```

Later it can become:

```text
bim-gui
    │ IPC
    ▼
bim-engine process
```

This enables:

* crash isolation;
* worker processes;
* multiple clients;
* background validation;
* AI workers;
* headless execution.

---

# 46. Proposed Module Structure

```text
openbim/
│
├── bim-core
│   ├── object
│   ├── property
│   ├── relationship
│   ├── identity
│   └── schema
│
├── bim-ifc
│
├── bim-store
│   ├── object store
│   ├── packs
│   ├── indexes
│   └── snapshots
│
├── bim-version
│   ├── commit
│   ├── branch
│   ├── diff
│   └── merge
│
├── bim-ops
│   ├── operations
│   ├── transactions
│   └── semantic merge
│
├── bim-geometry
│   ├── mesh
│   ├── brep
│   ├── bvh
│   └── spatial
│
├── bim-render
│
├── bim-sync
│   ├── protocol
│   ├── packs
│   └── replication
│
├── bim-p2p
│   ├── discovery
│   ├── relay
│   └── identity
│
├── bim-crypto
│
├── bim-rules
│   └── IDS
│
├── bim-ai
│
├── bim-cli
│
└── bim-gui
```

---

# 47. Performance Architecture

The critical rule is:

> **Never make the user wait for work that can be performed asynchronously.**

A local edit should follow approximately:

```text
User action
    ↓
Local operation
    ↓
Immediate semantic state update
    ↓
Incremental viewport update
    ↓
Async:
    ├── peer synchronization
    ├── geometry processing
    ├── IDS validation
    ├── spatial analysis
    └── AI analysis
```

---

# 48. Large Model Strategy

The architecture should explicitly target large models.

Potential benchmark sizes:

* 100,000 objects;
* 500,000 objects;
* 1,000,000+ objects.

The renderer and engine should use:

* incremental loading;
* memory mapping where useful;
* spatial indexes;
* object-level caching;
* GPU instancing;
* visibility culling;
* asynchronous processing;
* structural sharing.

---

# 49. Important Technical Risks

## IFC serialization

IFC is not stable enough as a textual diff representation.

**Decision:** canonical internal graph.

---

## Object identity

External identifiers can change.

**Decision:** repository-level identity.

---

## Geometry diff

Geometry changes can be expensive.

**Decision:** semantic and geometry diffs are separate.

---

## Real-time computation

50+ users can generate enormous event volumes.

**Decision:** asynchronous processing and operation coalescing.

---

## Network latency

Remote edits cannot block local interaction.

**Decision:** optimistic local operations.

---

## Offline merges

Concurrent work will happen without a server.

**Decision:** causal metadata + domain-specific merge.

---

## Conflict complexity

BIM conflicts are not simply textual.

**Decision:** semantic merge + geometric validation.

---

## Branch explosion

Traditional branch behavior can become cumbersome.

**Decision:** lightweight/ephemeral branches and proposal workflows.

---

## AI reliability

AI can generate incorrect conclusions.

**Decision:** AI uses deterministic tools and produces evidence-backed actions.

---

# 50. First Prototype

The first prototype should not attempt to build the complete application.

The initial proof should be:

```text
Machine A
    │
    │ local repository
    │
    ▼
BIM model
    │
    ├── edit
    ├── commit
    └── branch

Machine B
    │
    │ local repository
    │
    ▼
same BIM model
    │
    ├── edit
    ├── commit
    └── branch

        ↓

      QUIC

        ↓

Semantic synchronization
        ↓
Deterministic merge
        ↓
Conflict detection
        ↓
Identical resulting state
```

The GUI can initially be minimal.

---

# 51. Initial CLI

Even though the product has a GUI, the engine should have a CLI.

```bash
bim init
bim import model.ifc
bim status
bim diff
bim commit
bim log
bim branch
bim merge
bim validate
bim serve
bim sync
```

This makes the engine testable without the GUI.

---

# 52. MVP Definition

The MVP should prove these capabilities:

### Repository

* create repository;
* import IFC;
* canonicalize BIM objects;
* content-address objects;
* commit state;
* branch;
* inspect history.

### Semantic editing

* modify properties;
* move objects;
* create/delete objects;
* modify relationships;
* calculate semantic diff.

### Collaboration

* two repositories;
* direct synchronization;
* offline edits;
* concurrent modifications;
* deterministic merge.

### Conflict handling

* property conflicts;
* semantic conflicts;
* basic spatial conflicts.

### Geometry

* render imported model;
* incremental object updates;
* basic spatial index.

### GUI

* native Windows/Linux application;
* repository explorer;
* 3D viewer;
* properties;
* history;
* diff.

---

# 53. Development Phases

## Phase 1 — Repository Core

Implement:

* object model;
* identity;
* canonical serialization;
* content addressing;
* commits;
* refs;
* snapshots.

---

## Phase 2 — IFC

Implement:

* IfcOpenShell integration;
* IFC import;
* canonical mapping;
* IFC export.

---

## Phase 3 — Semantic Operations

Implement:

* transactions;
* object operations;
* semantic diff;
* merge engine;
* conflict representation.

---

## Phase 4 — Geometry

Implement:

* tessellation;
* exact geometry integration;
* spatial indexes;
* BVH;
* collision detection.

---

## Phase 5 — Native GUI

Implement:

* Qt shell;
* repository browser;
* model tree;
* property editor;
* history;
* initial 3D viewport.

---

## Phase 6 — Synchronization

Implement:

* repository negotiation;
* object transfer;
* pack transfer;
* commit synchronization;
* conflict exchange.

---

## Phase 7 — P2P

Implement:

* discovery;
* peer identities;
* secure channels;
* relay;
* host/super-peer.

---

## Phase 8 — BIM Validation

Implement:

* IDS;
* BCF;
* automated validation;
* coordination checks.

---

## Phase 9 — AI

Implement:

* tool API;
* local inference;
* repository queries;
* history analysis;
* evidence-backed proposals.

---

## Phase 10 — Scale

Implement:

* large-model optimization;
* partial replication;
* large assets;
* worker processes;
* enterprise host;
* advanced permissions.

---

# 54. Architectural Decisions Already Established

The following decisions define the direction of the project:

1. **Native GUI rather than Web UI.**
2. **Windows and Linux are the initial desktop targets.**
3. **Qt 6 is the primary GUI framework.**
4. **Rust is the primary core-engine language.**
5. **C++ is used for GUI and mature BIM/geometry integrations.**
6. **A C ABI provides a stable integration boundary.**
7. **IfcOpenShell should be integrated rather than rewritten.**
8. **IFC is an import/export boundary, not the primary repository representation.**
9. **The repository stores a canonical BIM object graph.**
10. **Objects are content-addressed and immutable.**
11. **Structural sharing minimizes duplication.**
12. **Version control is Git-like but BIM-native.**
13. **Semantic operations are the fundamental unit of editing.**
14. **Merge is domain-specific rather than generic text merging.**
15. **Geometry conflicts are evaluated separately from semantic conflicts.**
16. **Live collaboration and durable synchronization are separate systems.**
17. **Every user can own a complete local repository.**
18. **P2P is first-class.**
19. **A host/super-peer is optional infrastructure, not the source of truth.**
20. **Offline operation is fundamental.**
21. **Cryptographic identity and auditability are part of the architecture.**
22. **Deterministic state hashes are important for distributed consistency.**
23. **AI operates through tools and validated transactions.**
24. **Deterministic BIM engines remain authoritative over AI.**
25. **The GUI should be a client of the BIM engine rather than the owner of model state.**

---

# 55. Long-Term Architectural Goal

The mature system should look approximately like:

```text
                       OPENBIM NETWORK

        ┌───────────────────────────────────────┐
        │             User A                    │
        │                                       │
        │  Native GUI                           │
        │      │                                │
        │  Local BIM Repository                 │
        └──────┼────────────────────────────────┘
               │
               │ P2P
               │
        ┌──────▼────────────────────────────────┐
        │             User B                    │
        │                                       │
        │  Native GUI                           │
        │      │                                │
        │  Local BIM Repository                 │
        └──────┼────────────────────────────────┘
               │
               │
       ┌───────▼────────┐
       │ Optional Host  │
       │                │
       │ Relay          │
       │ Backup         │
       │ CI             │
       │ Indexing       │
       │ AI Workers     │
       └────────────────┘
```

Every participant can possess an authoritative copy of the repository state relevant to them.

The system does not fundamentally depend on:

* a centralized CDE;
* a browser;
* a permanent internet connection;
* a single vendor;
* a single BIM authoring application.

---

# 56. Core Concept

The most important architectural idea can be reduced to:

```text
              TRADITIONAL BIM

     Authoring Tool
            │
            ▼
        Large IFC
            │
            ▼
          CDE
            │
            ▼
        Large IFC


              THIS PROJECT

      ┌───────────────┐
      │ Local BIM Repo│
      └───────┬───────┘
              │
      Semantic Object Graph
              │
        Operations
              │
           Commits
              │
      ┌───────┴───────┐
      │               │
    Peer A          Peer B
      │               │
      └───────┬───────┘
              │
       Semantic Merge
              │
      BIM Validation
              │
        Shared State
```

The objective is therefore not simply to build another BIM viewer, another IFC editor, or another CDE.

The objective is to build a **distributed native BIM repository and collaboration engine**, with the desktop GUI acting as the primary human interface.

Its fundamental unit is not the IFC file.

Its fundamental unit is:

> **a versioned, addressable, semantically meaningful BIM object and its relationships.**
