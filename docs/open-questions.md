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

## For the architect: DXF export (asked 2026-10-10, waiting)

Built per D83 (Archicad's DWG/DXF translator as the reference).

1. **DWG**: KIMCAD writes DXF only. Do your consultants accept DXF, or is DWG a must? (DWG means either
   LibreDWG, whose writer is still experimental, or asking users to install the free ODA File Converter.)
2. Layers default to the KIMCAD layer (elements without one: by kind, e.g. A-WALL). Is the US National CAD
   Standard naming right for your offices, or do you use another standard (ISO 13567, a local one)? Do you
   need Archicad's third option, a layer per pen?
3. Poché goes on a separate `-PATT` layer (A-WALL-PATT) so it can be frozen. Useful, or should it share the
   element's layer?
4. A sheet is a paper-space layout with each drawing as a block inserted at scale (not a viewport onto
   model space). Do the people receiving it expect viewports instead?
5. Black pens are exported as colour 7 (black on white, white on a dark CAD background); other pens keep
   their exact colour. Would you rather everything printed by colour (ACI only) or by lineweight only?

## For the architect: 2D drafting (asked 2026-10-10, waiting)

Built per D84 (Archicad's Line, Arc/Circle, Polyline and Fill tools as the reference).

1. **Rectangles** become closed polylines (Archicad's rectangle polyline). Do you need a rectangle to
   stay a rectangle (keep its right angles when a corner is dragged)?
2. **Fills** draw their outline in the fill's pen and are drawn under the model's lines in drawings
   (Archicad's default stacking). Do you want fills without outline, or a separate outline pen?
3. **Fill patterns** are in millimetres on paper (they print at the same density at any scale), anchored
   at the project origin, like Archicad's drafting fills. Do you also need model-scale patterns (a real
   brick size, Archicad's "link to project origin / fill orientation" options)?
4. The built-in patterns are Solid, Empty, Diagonal, Crosshatch, Horizontal, Brick, Insulation (zigzag)
   and Concrete (dots). Which patterns does your office use most (and what should "Insulation" look like:
   zigzag or loops)?
5. A fill's area label uses the length decimals and m²; Archicad also offers a placeable, styleable
   label. Is the centred area text enough?
6. Shortcuts: Line Shift+L, Polyline Shift+Y, Arc/circle Shift+C, Rectangle Shift+E, Fill Shift+F (single
   letters were taken). Acceptable?

## For the architect: underlays (asked 2026-10-10, waiting)

Built per D85 (Archicad's placed drawing and Trace & Reference as the reference).

1. **DWG**: surveys mostly arrive as DWG; KIMCAD reads DXF only (save as DXF in the CAD program). Is that
   workable for now, or is DWG the first thing you need (it needs the ODA libraries or LibreDWG)?
2. **Text in DXF underlays** (levels, room names in a survey) is left out for now; only linework is drawn.
   How much do you rely on reading the survey's text while tracing?
3. A DXF far from the origin (map coordinates) is placed with its **middle on the project origin**. Do
   you prefer to keep survey coordinates (move the project to the survey, Archicad's "Survey Point")?
4. **Opacity, greyscale, tint**: DXF underlays keep their CAD colours at full opacity by default, PDFs
   and images are placed at 60%. Would you rather have every underlay greyed (Archicad's Trace &
   Reference default)?
5. **Default layer** *Underlays* for every underlay. One layer per underlay (named after the file)?
6. Underlays are **not undoable** (they are project settings, like layer states). Should placing,
   moving and calibrating be undo steps?
7. Do you need to **convert** DXF linework into KIMCAD 2D drafting lines (Archicad's *explode*), or to
   clip an underlay to a region?

## For the architect: tags, north arrow, scale bar, revision clouds, more dimensions (asked 2026-10-10, waiting)

Built per D87 (BIM part A; Archicad's Label tool with autotext, door/window markers and zone stamps as
the reference, Revit's Tag by category for Tag all).

1. **Door and window markers** show the Mark (ID) and the size, "D1 / 0.90×2.10" in the project's length
   unit, without a frame, half a metre outside the wall. Archicad offers many marker styles; which do you
   use (size in cm "90/210", sill height, a hexagon with the ID only)?
2. **Wall tags** show the wall type in a box, inside the room. Do you tag walls by type, or by a
   construction code (a property)?
3. **Room stamps** stay the room's own (as Archicad's zone stamp); their text is the *Room stamp* tag
   style (name, number, area by default). Should the stamp also show the perimeter, height or finishes?
4. **Tag all** tags the untagged doors, windows and walls of the level that the view shows. Should it
   also tag columns, furniture, or let you pick the categories (Revit's dialog)?
5. A tag whose element is deleted is deleted with it (Archicad). Would you rather keep it, showing "?"?
6. **Level dimensions** in plan measure the top of the slab under the point, else the level, from project
   zero ("+3.00", "±0.00"). Do you need them relative to the level, or to sea level (Archicad's options)?
7. The **north arrow** follows the project's true north (IFC TrueNorth; set from the console with
   `set_true_north`, no dialog yet) and is a circle with a half-filled arrow. Your office's symbol?
8. The **scale bar** is about 5 cm on paper (5 m at 1:100) in 5 alternating segments, in metres. Is that
   your convention?
9. **Revision clouds** carry the revision in a triangle at their first corner; there is no revision
   schedule on the sheet yet (Revit lists revisions in the title block). Needed soon?
10. Angle dimensions show two decimals of a degree ("45.00°"); radii "R 1.50" and diameters "Ø 3.00".
    Acceptable?

## For the architect: object library (asked 2026-10-10, waiting)

Built per D86 (Archicad's Library and Object tool as the reference; objects generated in code like GDL).

1. **Editing a placed object's parameter** changes only the selected objects (Archicad); if they are every
   placement of their type, the type changes in place. Revit would instead ask whether to edit the type
   (all placements) or duplicate it. Is changing only the selection what you expect?
2. **Origin and front**: an object's origin is its left front corner, its front at the side you face in
   plan (Archicad's convention). Would a centre origin suit tables and beds better?
3. **Plan symbols** are drawn in the object's projection pen; wall cabinets (above the cut) are crossed,
   not dashed. Which symbols does your office draw differently (WC, washbasin, wardrobe, beds)?
4. **Live plan view**: the plan tab shows the objects' 3D bodies seen from above; floor plan drawings and
   sheets show the 2D symbol. Do you need the symbol in the plan tab too?
5. **Shortcut** Shift+O for the Object tool, Tab to turn 90 degrees while placing. Acceptable?
6. Which objects are missing for a first release (lighting, doors' furniture, office desks, parking
   spaces, plants in pots)?

## For the architect: stairs, ramps and railings (asked 2026-10-11, waiting)

Built per D88 (Archicad's Stair and Railing tools as the reference).

1. **Riser count**: rounded up from the height and a target riser of 175 mm (3.00 m: 18 risers of 167 mm), tread 280 mm.
   Your office's defaults? Should the tread instead follow from 2R+G = 630 mm?
2. **Code checks** are warnings (riser over 180 mm, tread under 250 mm, 2R+G outside 600–650 mm, ramp over 1:12),
   editable in the project settings (`stair_rules`). Which code do you work to (headroom, maximum flight length,
   landings every N risers, handrail extensions)?
3. An **L or U stair** splits the risers half and half; the U's well is 100 mm. Do you want to choose the landing's
   position (risers per flight) and the well width?
4. The **opening in the floor above** is the stair's whole outline. Archicad can also cut only where headroom needs it;
   which do you draw?
5. **Railings** are 0.9 m on stairs and 1.1 m along paths, posts at most 1.2 m apart, balusters 120 mm apart; the inner
   railing of a U crosses the well at the landing. Your usual railing? Do you want a handrail on walls instead
   (Archicad's wall handrail)?
6. The **plan symbol** breaks at the plan cut, dashes the part above and writes UP at the start; the upper level shows the
   part above the cut with DN (drawings). Do you draw the arrow at the top (Archicad) or the bottom, and the riser
   numbers?
7. **Winders and spiral stairs** are not there yet. How often do you use them?

## For the architect: tracker, guides, Tab cycling, touchpad (asked 2026-10-11, waiting)

Built per D89 (Archicad's Tracker and temporary guides as the reference).

1. The **tracker** shows length, angle, dx and dy beside the cursor while placing points and takes typing
   at once (no click). Archicad can show it always or only once you type. Always shown is the current
   choice; do you want a way to hide it?
2. Typed **x/y are relative** to the previous point by default; `a` or `#` makes them absolute (project
   origin). Is relative what you expect, and do you need a user origin?
3. **Angles** are degrees counter-clockwise from east (Archicad, AutoCAD). Do you ever type bearings or
   angles relative to the previous segment?
4. Lengths are typed in **metres** (as the options bar's length field) whatever the project's unit. Should
   a project in millimetres read "3500" as 3.5 m?
5. **Temporary guides** appear after resting 0.5 s on a snap point (AutoCAD's object tracking); at most 4.
   Archicad also has guide lines dragged out of guide handles, and permanent guides. Which do you use?
6. **Tab cycling** steps through the elements under the cursor before clicking (Revit). Should it also
   reach plan annotations and drafting shapes?
7. On a laptop, two-finger scroll **pans** and pinch zooms; Shift+two-finger scroll orbits. Does that
   match the touchpads you use (Windows precision touchpads, Mac trackpads)?

## For the owner: tool palette and panels (asked 2026-10-17, waiting)

Built per D90 (Archicad's Toolbox as the reference).

1. The palette opens as **icons and labels in two columns** (216 px). Archicad users often run it icons
   only in one or two narrow columns: right-click the palette for *Icons only* or *List*. Which should be
   the default?
2. **Flyouts**: Dimension (linear, angle, radius/diameter, level), Line (line, polyline, arc/circle,
   rectangle), North arrow (scale bar, revision cloud) and Section (elevation). Others worth folding, e.g.
   Text with Leader, Slab with Slab opening, Split / Trim / Join?
3. Panel tabs on the right are **icons only**; the current panel shows its title when there is room.
   Is the icon alone enough, or would you rather have a vertical icon strip at the window's right edge
   (VS Code style) with full panel titles?
4. Find & Select, Checks, Library, Schedules and the Python console have **no tab until opened** (Panels
   button, View › Panels, their own commands). Should any of them be a permanent tab?
5. When the window is resized the tool palette and the panels keep their width and the view takes the
   change. On a small laptop screen, would you prefer the panels to shrink first?

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
