# Glossary

| Term | Meaning |
|------|---------|
| **AABB** | Axis-aligned bounding box; a cheap box used to find candidate objects before exact geometry tests |
| **AIS / V3d** | OpenCASCADE's interactive visualization modules |
| **BCF** | BIM Collaboration Format; a standard for issues and viewpoints that reference IFC objects |
| **Bonsai** | Open-source native-IFC authoring add-on for Blender (formerly BlenderBIM), built on IfcOpenShell |
| **BRep** | Boundary representation; exact solid geometry (faces, edges, vertices) |
| **bSDD** | buildingSMART Data Dictionary; online classifications and property definitions |
| **BVH** | Bounding volume hierarchy; a tree of bounding boxes for fast spatial queries |
| **Canonical record** | KIMCAD's deterministic JSON serialization of one rooted IFC entity (and its owned values) |
| **Change set** | The list of objects created, modified or deleted by one command/transaction |
| **Commit / Save version** | An immutable snapshot of the whole model state, with author and message |
| **Content addressing** | Identifying data by the hash of its contents |
| **CRDT** | Conflict-free replicated data type; a data structure that merges concurrent edits automatically |
| **Design option / branch** | An independent line of model versions |
| **DCO** | Developer Certificate of Origin; a per-commit sign-off certifying the right to contribute |
| **GlobalId** | The 22-character IFC identifier of a rooted entity |
| **gitoxide (`gix`)** | Pure-Rust implementation of Git |
| **IDS** | Information Delivery Specification; a machine-readable standard for model requirements |
| **IFC** | Industry Foundation Classes; the open BIM data schema (ISO 16739) |
| **IFC-SPF / STEP** | The `.ifc` text file format, with `#123=IFCWALL(...)` lines |
| **IFC5 / IFCX** | The next-generation, JSON-based IFC under development by buildingSMART (alpha) |
| **ifcmerge** | Tool that three-way merges IFC files by step ID (Bruno Postle) |
| **IfcOpenShell** | Open-source IFC toolkit (C++/Python): parsing, geometry, authoring API, drawings, IDS, BCF |
| **KIMCAD ID** | The repository-level 128-bit identity of an object; stable even if its GlobalId changes |
| **Merkle tree/DAG** | Structure where each node's hash covers its children; equal hashes mean equal content |
| **Milestone / tag** | A named version (Concept, Schematic, DD, Tender…) |
| **Native IFC** | Editing IFC data directly instead of converting to and from a proprietary model |
| **OCCT** | Open CASCADE Technology; the open-source geometry kernel |
| **Oplog** | Local journal of uncommitted transactions, used for undo and crash recovery |
| **Plain / Versioned project** | A project without / with KIMCAD version history |
| **Qt RHI** | Qt's rendering hardware interface over Vulkan, Direct3D and OpenGL |
| **Reconciliation** | Matching objects in a re-imported IFC to existing repository objects |
| **Rooted entity** | An IFC entity deriving from `IfcRoot` (has a GlobalId): products, types, property sets, relationships |
| **Step ID** | The `#123` number of an entity in an IFC-SPF file; local to that file |
| **Structural sharing** | Reusing unchanged records between versions instead of copying them |
