# Slice 15 (M4, part 2) — Floor plan drawings and annotation on drawings

**Goal:** the house's ground floor plan drawing reads like a real permit plan: walls cut, doors swinging,
dimensioned, labelled, with the section and elevation markers.

**Owner rule (D61):** where in doubt, Archicad's defaults.

## Decisions

- **Every story has a floor plan** (Archicad's Project Map): a DRAWING annotation with `Kind=plan`,
  `Storey`, `Cut` in `KIMBIM_Drawing`, created with the story (new project, *Add level*) and named
  "<level> Floor Plan". An opened IFC adds nothing; *View › Create floor plans and elevations* adds
  what is missing (one undo step). Model storeys (D58) get none.
- **Cut plane 1.10 m** above the story (Archicad's default floor plan cut plane); the view reaches to
  0.3 m below the floor. Only the story's elements are drawn.
- **What the serializer does not draw, KimBim draws on top** (`kimbim-overlay` group, paper mm), mapped
  from world to paper with the serializer's own drawing plane (`ifc:plane`) and paper transform
  (`ifc:matrix3`): door swings (leaf at 90° and arc, from the operation type; doors open into the side
  their local +Y points to, which KimBim places away from the wall's outer face), window glass lines,
  the story's annotations, and section/elevation markers. IfcOpenShell 0.9 ignores Plan-context
  door swings, which is why they are drawn here.
- **Text size is in millimetres on paper** (`KIMBIM_Annotation.Size`, default 2.5 mm). Drawings
  print it at that size; the IFC text boxes are as high as the text at 1:100; the 3D view's plan shows
  it in proportion (2.5 mm → 15 px) so it stays readable at any zoom.
- **Dimension chains**: a dimension is the measured points then a point the dimension line passes
  through; each segment is measured. In the tool, Shift+click adds a point; a plain click after two
  points places the line (one click per point, like Archicad).
- **Snapping dimensions to wall faces**: the dimension tool's snapper also takes the faces' corners
  (after the axis ends) and any point along a face.
- **Leaders** (Shift+A): arrow tip, then where the text goes; the text is asked for.

## Done

- [x] Bridge: `create_plan`, `create_drawings`, plans in `drawings()` (ordered plans, sections,
  elevations, as Archicad's Project Map), generation per story, overlay (`drawgen.py`).
- [x] Annotations: chains, leaders, `set_annotation_size`; `annotations()` reports `size`.
- [x] App: Leader tool, chains with Shift+click, face snapping while dimensioning, chains/leaders drawn
  in the plan, size editable in Properties (KIMBIM_Annotation › Size), *Create floor plans and
  elevations*; floor plans open in tabs like sections.
- [x] Tests: Python (plans per level, create_drawings, the house plan has cut walls, a door swing, the
  label, the measured dimension, the elevation markers; chains, leaders, size), app (chain, leader,
  floor plan tab), Snapper (faces).

## Not done (later)

- Window symbols beyond the glass line (sills, frames by type); door swing side chosen by the user
  (flip) — today it follows the door's placement.
- Section/elevation drawings get no annotations of their own yet (level marks, dimensions).
- Plan text in the 3D view is screen-proportional, not zoomable with the plan.
