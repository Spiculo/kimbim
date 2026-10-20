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
derived cache  (.kimbim/cache, keyed by record hash + kernel version)
```

- **Reuse:** the IfcOpenShell geometry iterator already converts every IFC representation type (extrusions, booleans and openings, BReps, tessellations, mapped items/instancing) into meshes and/or OpenCASCADE shapes, in parallel. KimBim writes no IFC geometry interpretation of its own.
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

**Spike S2 (done, [11](11-spike-results.md#viewer-occt-ais-rendering-picking-and-memory)):** 110k elements run at 32 fps with picking under 20 ms and 232 MB on an integrated GPU, **if elements are batched**. One OCCT object per element gave 2.7 fps and 3.2 GB. So the viewport uses **batched presentations with one selection owner per element** (D42): about 1,000 elements per AIS object, grouped by storey and type. Picking, highlighting, hiding and isolating stay per element. OCCT must be the conda-forge `novtk` build (D43), or Windows falls back to software rendering through Mesa.

**In the app (Slice 2, D45):** the custom `ElementBatch` object draws a 100k-element model at **150 fps** on an integrated GPU (vsync off; 1.4M triangles, 100 batches). That's about 5× faster per frame than the spike's generic OCCT shapes, because each batch is one flat triangle array. Picking hits an element 100% of the time. Cut faces are filled (capping) with each element's own colour.

### Later renderer (only if S2 or real usage demands it)

- A KimBim renderer on **Qt RHI**, Qt's abstraction over Vulkan, Direct3D 11/12 and OpenGL. It would add GPU-driven instancing, LOD, occlusion culling and streaming for 1M+ object models (spec §21, §48).
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

KimBim drawing flow:

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
- **Porting source:** Bonsai's drawing and sheet subsystem (Python, GPL-3) is the most complete open implementation of this flow. KimBim is GPL-3 ([06](06-reuse-and-licensing.md)), so we can port its logic with attribution.
- PDF export uses SVG → PDF through Qt (`QPdfWriter`/`QSvgRenderer`) at first. Revisit if output quality is insufficient.

**As built (Slice 14, spike S6, D60/D61):**
- A drawing is an `IfcAnnotation` DRAWING (Bonsai's definition): placement = camera, `Body` = `IfcBlock` for the extent, `EPset_Drawing`; KimBim's settings in `KIMBIM_Drawing`. The marker line in plan is the camera's X axis over the block width, so moving the annotation moves the drawing. Infinite ranges (Archicad's default) are re-fitted to the model when generating.
- IfcOpenShell 0.9 has no `addDrawing()` from Python; drawings go through `elevation-ref-guid`, and the annotation itself must be among the elements given to the serializer. Openings, spaces and annotations are left out.
- Generation (`kimbim/drawgen.py`) runs in a **child process** from a snapshot of the model, because the serializer holds the GIL for its whole hidden-line pass. Polygon HLR (`svg-poly`) is used.
- Hidden-line removal grows with everything behind the cut, so the 3D view first renders element ids from the drawing's camera (the D52 pass) and only the visible elements are sent: an elevation of a 2,880-element model went from 52 s to about 4 s.
- The SVG is cropped to its content and cached per drawing and model state (the last four states, so undo returns to a cached drawing). It is never written into the model.

## Geometry editing

- Authoring operations change **parametric definitions** (wall axis and height, profile, extrusion depth) through `ifcopenshell.api`. They do not edit meshes.
- Computed values are snapped to the model resolution before they are written ([02](02-data-model-and-format.md#4-quantize-at-the-operation-boundary)).
- Booleans (openings) stay as IFC relationships (`IfcRelVoidsElement`) and are evaluated by the geometry iterator. They are never baked into geometry.
