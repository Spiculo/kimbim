# 02 — Data Model and Canonical Format

## Principle: IFC-schema native, not IFC-file native

- KIMCAD's data model **is the IFC schema**: IFC4 entities, attributes and relationships, through IfcOpenShell. We do not invent a parallel BIM schema. That would be an enormous amount of work, and every import and export would lose data.
- KIMCAD's **storage format is not the IFC file.** An `.ifc` (STEP) file is a poor unit for versioning:
  - Entity `#ids` are local to the file and get renumbered.
  - Ordering is arbitrary.
  - A one-property change can reshuffle the whole file.
- So the repository stores the IFC graph as **canonical records**. IFC files are produced on export, and step IDs are regenerated deterministically.

Prior art: Bonsai and FreeCAD edit IFC "natively" and use `ifcmerge`, which relies on preserving step IDs. KIMCAD removes that dependency on step IDs by storing records keyed by stable object identity.

## Decomposing the IFC graph into records

IFC entities fall into two kinds:

| Kind | Examples | Has GlobalId | KIMCAD treatment |
|------|----------|--------------|------------------|
| **Rooted** (`IfcRoot` subtypes) | `IfcWall`, `IfcDoor`, `IfcPropertySet`, `IfcRelContainedInSpatialStructure`, `IfcWallType` | yes | **Identity record.** It has a stable KIMCAD ID and changes over time. |
| **Non-rooted** | `IfcCartesianPoint`, `IfcLocalPlacement`, `IfcExtrudedAreaSolid`, `IfcPropertySingleValue`, `IfcMaterialLayerSet` | no | **Value.** It is immutable and embedded in its owner, or stored as a content-addressed shared value. |

Rules:

1. **One file per rooted entity.** Its non-rooted subgraph (placement, property values, and so on) is **embedded inline** as nested JSON.
2. **Shared values.** If more than one rooted entity references a non-rooted entity (a shared material layer set, a shared profile, a mapped representation), it becomes a **shared value record**. It is stored once and referenced by content hash.
3. **Heavy geometry.** Representation items above a size threshold (large tessellations from Revit exports, for example) are split into **geometry records** referenced by hash. A property-only change then never rewrites geometry. This is the spec's structural sharing (§10) done at the record level.
4. References to rooted entities use the **KIMCAD ID**. References to values use the **content hash**. Step `#ids` never appear.
5. **Owned-value references.** Some non-rooted entities are owned by a single rooted entity but referenced from others. The main case is a storey's `IfcLocalPlacement`, which every contained element references through `PlacementRelTo`. These are referenced by **owner path** (`{"owner": <id>, "path": "ObjectPlacement"}`), not by hash. If hash references were used here, moving a storey would change the hash and force a rewrite of every element on it. Rule 2 (shared values) applies only to non-rooted entities that have no single owner.
6. Inverse attributes are not stored, because they are derived. Relationships are stored once, as the rooted `IfcRel*` entities that IFC already defines.

This structure is naturally a Merkle DAG. Changing `FireRating` on a wall rewrites only that wall's `IfcPropertySet` record, plus the tree nodes above it (see [03](03-versioning.md)).

## IFC schema version

**Decided (D30): the architecture is compatible with both IFC4 and IFC4X3. The MVP ships IFC4.**

| | MVP | After MVP |
|---|---|---|
| New projects | IFC4 ADD2 TC1 only | IFC4 (default) or IFC4X3 ADD2, chosen per project |
| Open / edit / save IFC4 | Full support, release-blocking | Full support |
| Open / edit / save IFC4X3 | Works in its own schema, **best-effort** (tested, not release-blocking) | Full support, release-blocking |
| Import IFC2X3 | Yes (see [open questions](open-questions.md)) | Yes |

Compatibility rules, which apply from day one so that IFC4X3 support later is a matter of testing, not a rewrite:

- **No hard-coded schema assumptions.** Code goes through IfcOpenShell's schema-aware APIs (`ifcopenshell.api`, schema declarations). If something differs between schemas, it is handled through a schema check, never by assuming IFC4.
- **Every record and `kimcad.toml` carry the schema identifier.** Records of different schemas never mix in one project.
- **No silent conversion.** A file is saved in the schema it was opened in. Moving between schemas is an explicit "Upgrade/Downgrade schema" command (IfcOpenShell `ifcpatch` Migrate) that becomes its own version in history.
- **Both schemas are in the test corpus** from M1. IFC4X3 tests run in CI as non-blocking until after the MVP.

| | IFC4 ADD2 TC1 (2018) | IFC4X3 ADD2 (ISO 16739-1:2024) |
|---|---|---|
| Status | Previous ISO edition; the workhorse of current exchange | **Current ISO standard** |
| Buildings | Complete | Same building entities, plus some newer predefined types and fixes |
| Infrastructure | — | **Alignment, road, rail, bridge, ports & waterways**; better site/civil |
| Revit / ArchiCAD export | Yes, the de-facto default | Partial; most installations still exchange IFC4 (tools lag ISO by 1–3 years) |
| IfcOpenShell support | Full | Full |

For an architecture-focused tool, IFC4 has the widest **compatibility** today. IFC4X3's advantages are being the current standard and supporting infrastructure, which matters only for site, civil and infrastructure work.

Plan to make IFC4X3 the default for new projects once the major authoring tools import it reliably.

## Object identity

**Decided (spec §12, owner answer):** a repository-level identity is kept separately from the IFC GlobalId.

- **KIMCAD ID** is 128 bits. It is assigned when an object is created or first imported. By default it **equals the decoded IFC GlobalId at that moment**, so in the common case the two match and no lookup is needed.
- **GlobalId** is an ordinary attribute in the record. If an external tool regenerates GlobalIds on re-export, reconciliation (see [03](03-versioning.md#import-reconciliation)) maps the new GlobalId onto the existing KIMCAD ID and history is kept.
- If reconciliation cannot match an object, the import treats it as delete plus create. That object's history link is lost (owner answer 1), but the project stays valid.

## Canonical format

**Owner input:** use "XML or other friendly formats" and check the round trip.

**Decided: canonical JSON**, one document per record. Each document is human-readable, diffable, and inspectable with ordinary tools.

Why JSON over XML:

- **Canonicalization is standard and simple.** RFC 8785 (JSON Canonicalization Scheme) defines it. XML canonicalization (C14N) is notoriously complex, and that complexity is a source of hash mismatches.
- **First-class tooling** in Rust (`serde_json`) and Python.
- **It is where IFC is heading.** buildingSMART's IFC5 work (IFCX) is JSON-based. Staying close to its shape makes a future IFC5 import/export cheaper. IFC5 is still alpha, so we do *not* adopt it as our format today.
- `ifcXML` exists, but it is verbose, poorly supported, and file-oriented rather than object-oriented.

Example record (illustrative; the exact schema is decided during milestone R1):

```json
{
  "k": "kimcad/1",
  "id": "0f3a9c2e-...",
  "type": "IfcWall",
  "attr": {
    "GlobalId": "2O2Fr$t4X7Zf8NOew3FLOH",
    "Name": "W-183",
    "PredefinedType": "STANDARD",
    "ObjectPlacement": {
      "type": "IfcLocalPlacement",
      "PlacementRelTo": {"owner": "a91c...", "path": "ObjectPlacement"},
      "RelativePlacement": {
        "type": "IfcAxis2Placement3D",
        "Location": {"type": "IfcCartesianPoint", "Coordinates": [12.45, 4.1, 0.0]}
      }
    },
    "Representation": {"geom": "b3:5d1e..."}
  }
}
```

Canonicalization rules:

- Keys are sorted, there is no insignificant whitespace, and text is UTF-8 normalized to NFC.
- Enumerations are stored without the STEP dots.
- `$` (unset) attributes are omitted, never written as `null`.
- Numbers follow the [determinism](#determinism) rules.
- Every record carries its format version (`"k": "kimcad/1"`), and format changes come with migrations.

## Round-trip guarantee

**IFC → records → IFC must be lossless** for every entity, attribute and relationship in the IFC4 schema. Losslessness is checked with a semantic comparison, not a byte comparison. This is a release-blocking test suite (see [09](09-testing-and-quality.md)):

1. Import file A, export it as file B.
2. Compare A and B semantically using IfcOpenShell (`ifcdiff`-style graph comparison, ignoring step IDs and ordering).
3. Re-import B, and require **identical record hashes**. Records → IFC → records must be a fixed point.

## Determinism

**Owner question:** "How do we fix that?" The problem is that geometry kernels and floating-point math are not bit-identical across platforms, compilers and library versions. The answer has five parts.

### 1. Hash authored data only, never derived data

| Hashed (part of state) | Never hashed (derived caches) |
|------------------------|-------------------------------|
| Attributes, properties, relationships | Triangle meshes / tessellation |
| Placements (numbers as authored) | OpenCASCADE BReps |
| Parametric geometry *definitions* (profile, extrusion depth, direction) | Bounding boxes, BVH, spatial indexes |
| Explicit geometry *as stored in IFC* (e.g., `IfcTriangulatedFaceSet` coordinates) | Clash results, quantities computed on the fly, drawings |

Derived data lives in caches keyed by `(record hash, kernel version)` and can always be regenerated. If two machines tessellate the same record slightly differently, that is fine. Their **state hashes still agree**.

### 2. Replicate results, never re-execute operations

When someone rotates a wall by 30°, trigonometry runs **once, on their machine**. What is stored and shared is the resulting placement record, not "rotate 30°". Other machines receive the record and never recompute it. Merge works on records (pure data comparison), so it involves no floating-point math at all.

This rule also applies to future live collaboration: live operations carry resulting values (`SetPlacement(matrix)`), not commands (`Rotate(30°)`). See [08](08-future.md).

### 3. Canonical number encoding

- Numbers are IEEE-754 binary64. Each is serialized with the **shortest round-trip representation** (Ryu-style), so the same `f64` always produces the same text.
- `-0.0` is normalized to `0.0`. NaN and ±Inf are rejected, because IFC does not allow them.
- Imported values are kept exactly as parsed. Correctly-rounded decimal parsing is the same on all supported platforms, and golden tests verify this.

### 4. Quantize at the operation boundary

Values that KIMCAD **computes** during editing (placements after move/rotate, generated profile points) are snapped to a model resolution before they are written:

- Lengths: **0.01 mm (1e-5 m)** by default (Decided, D31). This is configurable per project and stored in `kimcad.toml`. Why this value:
  - It matches the IFC convention: `IfcGeometricRepresentationContext.Precision` is typically 1e-5 to 1e-8 in metre-based models, and IfcOpenShell defaults to 1e-5. KIMCAD writes the resolution into that attribute on export.
  - It is about 100× finer than construction tolerances (millimetres) and much finer than authoring-tool limits. Revit's minimum curve length is about 0.8 mm. So snapping never changes anything an architect can see or build.
  - 0.1 mm would also be safe for buildings. 0.01 mm leaves headroom for detailed elements (fixings, joinery) at no cost.
  - The resolution is always defined **in metres** and converted to the project unit. A literal 1e-5 in a millimetre-unit project would be far too tight.
  - IEEE-754 doubles keep 0.01 mm resolution even at coordinates thousands of kilometres from the origin, so georeferenced projects are fine.
- Direction / axis components: 1e-12.

Snapping makes rare one-ulp platform differences in `sin`/`cos` disappear. A tiny residual risk remains: a value that sits exactly on a rounding boundary. Rule 2 already makes that harmless, because only one machine ever computes a given value.

### 5. Verify continuously

- **Golden-hash tests:** CI on Windows and Linux imports the test corpus and asserts identical record and tree hashes on both.
- Every commit records the engine/format version that produced it.

## What is *not* in the canonical store

- The viewport state, camera and selection.
- UI settings.
- Caches (meshes, indexes, drawing renders).

Large binary assets (point clouds, scans, images) are a future concern. See [08](08-future.md#large-assets).
