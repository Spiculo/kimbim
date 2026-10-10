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
2. An element with no status counts as New. Opening an IFC with unmarked elements asks whether to mark
   them Existing (default answer: leave them). Should the default be Existing instead?
3. The built-in filters (Existing plan, Demolition plan, New plan, Planned) and their looks: demolished
   dashed yellow (black dashed in the Permit set), existing grey in the new plan. Do these match local
   permit conventions (Chile, Spain)?
4. A door placed in a wall to be demolished is New, as in Archicad. Is that what you'd expect?
5. The sheet legend lists only what the sheet's drawings actually use. Is that right, or should it list
   every rule of the purpose?

## For the architect: view cube, preset views, perspective (asked 2026-10-09, waiting)

Built as D76 (Revit's cube, since Archicad has none; Archicad's camera habits otherwise).

1. Preset views keep your target and zoom, and fit all only when the model would be off-screen; Revit's
   cube always zooms to fit. Which do you prefer?
2. Shortcuts: Alt+1 to Alt+6 for Top, Bottom, Front, Back, Left, Right; Alt+7 to Alt+0 for the SW, SE,
   NE, NW isometrics; Home for the home view; Shift+P for perspective. Would you use other keys?
3. The home view is the south-east isometric (what a new 3D view shows). Should it be south-west, or
   whatever view you set as home (Revit's "set current view as home")?
4. Plan views have no cube and no north arrow (north is always up). Do you want a north arrow on plans,
   e.g. once the project has a true north (georeferencing)?
5. Perspective uses a 45° vertical field of view (about 70° across a wide window). Should it be a
   setting, or a different default?
## For the architect: window chrome (asked 2026-10-09, waiting)

Built per D75; the owner may want an architect to confirm these.

1. The title bar holds the level drop-down, Plan cut and Section box. Archicad keeps levels in the
   Navigator and cuts in the View menu / 3D window. Are these the controls you want always in reach, or
   would you rather see others there (e.g. the zoom, the pen set, the renovation filter)?
2. Save version (Ctrl+Alt+S) moved from the File menu to the new Versions menu with the design options.
   Is Versions the place you'd look for it, or should File keep a copy?

## For the architect: schedules and quantities (asked 2026-10-09, waiting)

Built as D77 (Archicad's Interactive Schedule).

1. Wall length is measured on the reference line (axis), so corner overlaps count once per wall, as in
   Archicad's "reference line length". Do you need the inside/outside face lengths too?
2. Net side area takes out every opening at its full size (Archicad's default; some offices only deduct
   openings above a size, e.g. 0.5 m² in some measurement rules). Is a minimum needed?
3. Built-in schedules merge identical items by type (doors and windows by type, width and height). Is that
   the grouping you'd expect, or by level too?
4. Quantities are in metres, m² and m³ with 2 decimals (3 for volumes), whatever the project's length unit.
   Should schedules follow the project's length unit setting instead?
5. Room schedules list every space of the model, KIMCAD rooms and imported spaces alike. Right?

## For the architect: selection tools (asked 2026-10-09, waiting)

Built per D78 (Archicad's Find & Select; Revit's direction-dependent box).

1. Select similar on an element without a type takes the other untyped elements of its class and
   predefined type, not typed ones. Would you rather it took every element of the class?
2. Shortcuts: Ctrl+Shift+A for Select similar, Ctrl+F for Find & Select. Archicad selects all of the
   active tool's type with Ctrl+A; should KIMCAD do that too (Ctrl+A is free today)?
3. Box direction: right to left now takes everything the box touches (crossing), left to right only what
   is fully inside. Archicad sets this once in its preferences (partial or entire elements) rather than
   by direction. Keep the AutoCAD/Revit habit, or follow Archicad?
4. Find & Select leaves out elements on hidden or locked layers and elements hidden in the view. Should
   hidden ones be found (and shown) instead, as Revit's filters can?

## For the architect: measure and levels table (asked 2026-10-09, waiting)

Built to Archicad's model (D79); the owner will confirm these with an architect.

1. Measure shows areas in m² even when lengths are in mm or cm. Right, or follow the length unit?
2. Measure in 3D snaps to element surfaces and to plan snaps (wall ends, faces) at the surface's height, not to 3D
   vertices of arbitrary geometry (furniture corners). Is that enough, or are mesh vertex snaps needed?
3. Changing a level's elevation moves its elements; changing its height to next moves every level above. Is that
   what you'd expect, or should an elevation change also move the levels above?
4. Inserting a level pushes the levels above up by one level height (Archicad). Should it instead fit between
   existing levels without moving them (Revit)?
5. Deleting a level with elements offers "delete them too" (Archicad) or "move them to the next level down". Is
   moving useful, or should deleting simply delete (with a warning)?
## For the architect: split, trim, join (asked 2026-10-09, waiting)

Built per D80 (Revit's tools where Archicad has none; joined walls stay connected, D54).

1. A split wall's two pieces stay joined (they follow each other when one moves); Ctrl leaves them
   apart. Would you rather they were independent by default, as in Archicad?
2. Trimming a wall so that a door or window would fall off is refused. Should the door be deleted
   instead (with the trim), or moved to stay inside?
3. Merge needs the same type, level and height, and keeps the first wall's properties (the second's
   are dropped). Is that the right rule, or should differing properties block the merge?
4. Splitting, trimming or merging an imported wall (e.g. from Revit) replaces its exported shape with
   KIMCAD's own, rebuilt from its axis, layers and height. Is that acceptable, or should imported
   walls keep their shape and only be cut?
5. Shortcuts Shift+S (split), Shift+T (trim/extend), Shift+J (join). Revit uses two-letter keys (SL,
   TR); do you want those instead?

## For the architect: checks (asked 2026-10-09, waiting)

Built per D81 (Archicad's Model Check and Collision Detection, with Solibri-style model checks).

1. The sample house's floor slabs overlap the exterior walls under them by 200 mm, because walls run the
   full storey height. Archicad would resolve it with building-material priorities. Should walls stop
   under the slab above, the slab be cut by the walls, or is the overlap fine in your drawings?
2. Clash tolerance 2 mm and clearance 50 mm by default. Do your offices use other defaults?
3. A door or window never clashes with its host wall, and a stair never with its own flights. Should
   joined walls also be ignored (they never overlap today)?
4. Duplicates are the same class, type, place (to 1 mm) and shape. Should elements that only overlap
   partly (same class, same level) count too, as Archicad's "duplicates" do?
5. Doors and windows without an opening in a host are warnings. In curtain walls they are allowed. Any
   other case you would not want flagged?
6. IDS files are stored inside the project (so they are versioned with it), not linked from a shared
   folder. Do offices keep one IDS for all projects and expect edits to it to reach every project?
## For the owner: Python console (asked 2026-10-10, waiting)

1. Changes made in the console outside `with edit():` are not undoable. Should the console wrap every run in one
   undo step automatically (simpler, but a script that only reads would still add an empty step), or is `edit()` right?
2. The console lives under View › Panels (Archicad: Window › Palettes) with File › Run Python script.... Would you
   rather have a Scripting menu, or scripts that you can pin as commands (a P2 plugins feature)?
3. Should scripts be able to run without the window (`kimcad run script.py model.ifc`) for batch jobs?

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
