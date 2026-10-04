# 05 — Geometry, Rendering and Drawings

## Geometry pipeline

```text
IFC records / in-memory model
        │
        ▼
IfcOpenShell geometry iterator  (C++, multi-threaded, OpenCASCADE kernel)
        │
        ├──► triangle meshes  ──► renderer
        ├──► BReps (on demand) ──► precise ops: cuts, booleans, measuring, drawings
        └──► AABBs           ──► spatial tree (IfcGeom::tree) ──► picking, clash candidates
        │
        ▼
derived cache  (.kimcad/cache, keyed by record hash + kernel version)
```

- **Reuse:** the IfcOpenShell geometry iterator already converts every IFC representation type (extrusions, booleans and openings, BReps, tessellations, mapped items/instancing) into meshes and/or OpenCASCADE shapes, in parallel. KIMCAD writes no IFC geometry interpretation of its own.
- **Kernel (spike S2):** display tessellation uses IfcOpenShell's `hybrid-cgal-simple-opencascade` kernel, the same choice as Bonsai. On the Clinic model (3,258 elements) it took 3.1 s versus 17.9 s for pure OpenCASCADE, with no elements lost. Pure CGAL was faster still but silently dropped elements, so it is not used. Exact OpenCASCADE stays in use for precise work: drawings, measuring and clash.
- **Incremental:** a change set re-tessellates only the affected objects. When an opening changes, that includes its host wall.
- **Derived data is never part of the model state** ([02](02-data-model-and-format.md#determinism)).
- **Instancing:** mapped representations (`IfcMappedItem`, used for repeated types) stay instanced all the way to the GPU.

## Spatial queries

- The IfcOpenShell `IfcGeom::tree` (BVH over object boxes, with exact OCCT tests on candidates) handles picking, box selection, "what's inside this section box", clash candidates and snapping candidates.
- The rule from spec §19 applies: use the broad phase first and run exact tests only on candidates.

## Rendering

**Spec said:** a custom Vulkan-oriented renderer. **Proposed:** do not start there. A custom Vulkan renderer is a multi-year project on its own.

### Phase 1 renderer: OpenCASCADE visualization (AIS / V3d) inside Qt

- OCCT includes a full interactive 3D visualization module with Qt integration samples. It provides, out of the box:
  - selection and highlighting, including sub-shape picking;
  - **clipping planes with capping (section fill)**, which covers most of the "cuts" requirements in [04](04-app-features.md#3-cuts-sections-and-clipping);
  - shaded and wireframe display modes, transparency, edges and hidden lines;
  - frustum culling, and presentation of mesh primitive arrays for large counts.
- It is LGPL with the OCCT exception, which is already a dependency.

**Spike S2:** load 100k-object models (from the test corpus) as mesh-array presentations rather than BRep presentations, and measure frame rate, memory and selection latency on mid-range hardware. Acceptance targets: about 30 fps while orbiting, under 100 ms to pick.

### Later renderer (only if S2 or real usage demands it)

- A KIMCAD renderer on **Qt RHI**, Qt's abstraction over Vulkan, Direct3D 11/12 and OpenGL. It would add GPU-driven instancing, LOD, occlusion culling and streaming for 1M+ object models (spec §21, §48).
- The viewport talks to the renderer through a narrow interface (`Scene`: add/update/remove object meshes, set clipping, set colors, pick), so the backend can be swapped without touching panels or commands.

## Cuts in 3D

- **Section box** = 6 clipping planes, controlled with gizmo handles.
- **Capping** fills cut solids, colored or hatched per material ("fill style" comes from the IFC material's presentation style when present).
- Cuts are view state. They are saved in "saved views" but never in model history.

## Drawings (2D)

**Reuse:** the IfcOpenShell **SVG serializer** (used by IfcConvert and by Bonsai's drawing system) produces plans and sections with:

- hidden-line removal;
- cut lines vs projection lines;
- cut-face fills/hatches per material;
- storey-height plan cuts and arbitrary section planes.

KIMCAD drawing flow:

```text
drawing definition (camera/cut plane, scale, view range, filters)  ── stored in model as IfcAnnotation context
        │
        ▼
SVG serializer (background thread)  ──►  base linework SVG (cached by model state hash)
        │
        ▼
annotation layer (dimensions, tags, text — IFC annotation entities in the model)
        │
        ▼
sheet composition (title block, viewports at scale)  ──►  PDF / SVG export
```

- Drawing definitions and annotations are part of the model, so they are versioned. Generated linework is a derived cache.
- **Porting source:** Bonsai's drawing and sheet subsystem (Python, GPL-3) is the most complete open implementation of this flow. KIMCAD is GPL-3 ([06](06-reuse-and-licensing.md)), so we can port its logic with attribution.
- PDF export uses SVG → PDF through Qt (`QPdfWriter`/`QSvgRenderer`) at first. Revisit if output quality is insufficient.

## Geometry editing

- Authoring operations change **parametric definitions** (wall axis and height, profile, extrusion depth) through `ifcopenshell.api`. They do not edit meshes.
- Computed values are snapped to the model resolution before they are written ([02](02-data-model-and-format.md#4-quantize-at-the-operation-boundary)).
- Booleans (openings) stay as IFC relationships (`IfcRelVoidsElement`) and are evaluated by the geometry iterator. They are never baked into geometry.
