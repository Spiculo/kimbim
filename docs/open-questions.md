# Open Questions

Resolve these, then record the answer in [decisions.md](decisions.md).

## Resolved (2026-10-03)

| Question | Answer | Decision |
|----------|--------|----------|
| License | GPL-3.0-or-later (AGPL for future server parts) | D08 |
| Git as storage layer | Yes | D18 |
| Canonical JSON instead of XML | Yes | D11 |
| Embedded Python runtime | Yes | D22 |
| UI vocabulary | Yes; may change from user feedback. UI in English + Spanish | D28, D29 |
| IFC schema | Compatible with IFC4 and IFC4X3; MVP ships IFC4 | D30 |
| Model resolution | 0.01 mm | D31 |

## For the architect (asked 2026-10-07, waiting)

Plan tabs: the owner will discuss these with an architect. Until then plan tabs stay as they are
(D71: a cut at the 3D tab's slider height, with poché, and the cut slider beside the view).

The owner said a plan tab should be a standard floor plan: no ceiling, poché on walls, no slider, no
cut, and every element of that level seen from above (chairs top-down). Proposed answer, not built:

- **No slider and no cut controls** while a plan tab is active; Plan cut and Section box stay 3D tools.
- **Only that level**: nothing from the floors below or above. Furniture, slabs and stairs from above;
  walls and columns with poché. Ceilings (IfcCovering CEILING) never show; they belong in a reflected
  ceiling plan.
- **A hidden slice** at a fixed 1.20 m above the level, because poché needs the walls sliced
  somewhere. It's a project setting (step 2), not a control on screen. Elements entirely above it
  (wall cabinets, high windows) don't show; Archicad draws those dashed (overhead).
- **Plan symbols** (an element drawn in plan by its own 2D symbol, separate from its 3D body, like
  Archicad's 2D symbols or IFC's Plan/FootPrint representations) would be a later feature.

Questions:

1. Is a fixed slice height right, and is 1.20 m the usual value? Per project, per level, or per view?
2. Should elements above the slice show dashed (overhead), or not at all?
3. Ceilings: never in a floor plan, or shown dashed?
4. How much of the level below should show, if any (Revit's "view depth", Archicad's "show
   storeys below")?
5. Do we need plan symbols soon, or is the top-down view of the 3D body enough for now?

Likely cause of the ceiling the owner saw: a new plan tab takes its cut height from the 3D tab's
slider, so a high 3D cut gives a plan cut above the ceilings.

## For the architect: renovation status (asked 2026-10-08, waiting)

Built to Archicad's model ([spec](superpowers/specs/2026-10-08-renovation-status-design.md)); the owner will
confirm these with an architect.

1. Three statuses (Existing, To be demolished, New), as in Archicad. Is a fourth, *Temporary* (Revit), needed?
2. An element with no status counts as New. Should an imported survey model count as Existing instead?
3. The built-in filters (Existing plan, Demolition plan, New plan, Planned) and their looks: demolished
   dashed yellow (black dashed in the Permit set), existing grey in the new plan. Do these match local
   permit conventions (Chile, Spain)?
4. A door placed in a wall to be demolished is New, as in Archicad. Is that what you'd expect?
5. The sheet legend lists only what the sheet's drawings actually use. Is that right, or should it list
   every rule of the purpose?

## Needs a spike

These are listed in [07-roadmap.md](07-roadmap.md#spikes-do-first-each-is-small-throwaway-and-documented).

- S1: shared in-memory IFC between C++ and Python.
- S2: OCCT viewer performance at 100k objects.
- S3: lossless record decomposition on the corpus.
- S4: cross-platform hash equality.
- S5: gitoxide performance at 1M blobs.

## Design details to settle during implementation

- The exact canonical JSON schema: attribute naming, how SELECT types and typed values (`IfcLabel("x")`) are encoded, aggregates of aggregates.
- The size threshold that moves geometry into separate records.
- Ownership rules for non-rooted entities that are referenced by several roots without a clear owner.
- Representing IFC2X3 files: convert to IFC4 on import, or store natively by schema?
- Where saved views, drawing definitions and library references live (in-model IFC entities vs `kimcad.toml`).
- Undo across "Save version": can you undo past a commit, or does a commit reset the undo stack?
- Spanish terminology for UI and IFC display labels: pick one regional variant (neutral Latin American vs. Spain) or ship both?
- Community: where the project lives (Codeberg/GitHub), communication channel, and its relationship with the OSArch / IfcOpenShell communities. Upstreaming fixes to IfcOpenShell is strongly encouraged.
