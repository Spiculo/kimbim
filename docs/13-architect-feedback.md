<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 13 — Owner feedback round 1: what changed and how to try it

The owner's ten notes from the first hands-on session, and where each one landed
([plan](superpowers/plans/2026-10-06-architect-feedback.md)).

| # | Note | What KimBim does now | Try it |
|---|------|----------------------|--------|
| 1 | Placing walls/objects is slow | The 3D view no longer waits for the display's refresh (vsync) on every redraw; a wall now lands in ~50 ms and the mouse preview in ~2 ms (measured with `--bench-tools`). `KIMBIM_VSYNC=1` brings vsync back | Draw walls (W) quickly |
| 2 | Plan cut as a slider on the right | A vertical slider beside the 3D view sets the cut height for the active level | Drag the slider |
| 3 | Editing length in the panel does nothing | Properties shows a **Dimensions** group (length, height, width, thickness, depth...) that really changes the shape | Select a wall, edit Length |
| 4 | Layers as boundaries, views as collections of layers | **Layers** tab (next to Model): new, rename, delete, shown, locked, active layer, "Move selection here". **Views**: save the layer states + level + plan/3D + cut as a named view and switch between them. Stored in the IFC ([D57](decisions.md)) | Layers tab |
| 5 | "Models" for repeated apartments | **New model...** next to the levels; draw the apartment in it; **Place model (U)** on any level (Shift: turned 90°); a click selects the whole instance; **Model › Update model instances** applies the model's changes everywhere; **Explode** unlinks one ([D58](decisions.md)) | New model... |
| 6 | Labels, dimensions, marks on the plan | **Text label (A)**, **Dimension (Q)**: click two points then where the line goes, measures itself; **Mark (X)**: circle with a tag. They're IFC annotations: select, move (M), delete, undo, layers; edit the text in Properties ([D59](decisions.md)) | Plan view, A / Q / X |
| 7 | Cut walls have no borders | The plan cut draws sections: dark fill and bold outline (poché) where elements are cut | Plan view with the cut on |
| 8 | Drag to move | Press on a selected element and drag; snaps; joined walls follow (Ctrl: detach) | Select, drag |
| 9 | Selection flashes the background | Redraws now repaint the whole view in one pass; please confirm on your screen | Click around |
| 10 | Icons and hints | Element icons in the model tree; hovering an element in the 3D view shows its name, type and level | Hover |

## 2026-10-07: main window rework (step 1 of 3)

The owner's UI notes after Slices 14–22 ([spec](superpowers/specs/2026-10-07-main-window-rework-design.md), D71):

| Note | What KimBim does now | Try it |
|------|----------------------|--------|
| Tools on the left, by category | Left column with **3D / Plane / View / Edit** groups (collapsible); the tool's fields appear above the view only while it's active | Pick Wall in the 3D group |
| Properties on double-click | Double-click an element (view or tree): Properties comes forward in the right panels; a level opens its plan | Double-click a wall |
| Less noise in the object tree, on the right | Tree on the right; one row for Project/Site/Building; plain names; elements grouped by category under each level | Model tab on the right |
| A bottom bar with ink set, zoom, layers | Bottom bar: pen (placeholder until pen sets, step 3), active and visible layers, zoom, selection, messages | Look at the bottom |
| 3D and plan views as tabs that pop out | 3D tab plus a plan tab per level, drawings and sheets; drag a tab out to its own window and back | P, then drag the plan tab out |

Next: **step 2**, the `.kim` file (one file, or open as a folder) with project and user preferences and office templates; **step 3**, pen sets. Several models open together is future research ([08](08-future.md#federation-and-linked-models)).

## 2026-10-08: `.kim` file, preferences and templates (step 2 of 3)

([spec](superpowers/specs/2026-10-08-kim-file-and-preferences-design.md), D72)

| Note | What KimBim does now | Try it |
|------|----------------------|--------|
| A file format beyond plain IFC | A `.kim` holds the model, the project settings and the whole version history in one file | File › Save As… › `.kim` |
| Saving | Ctrl+S saves the file; Save version… (Ctrl+Alt+S) adds a history entry; optional automatic versions | Edit › Preferences › Automatic versions |
| Opening an IFC | Makes a `.kim` beside it (the IFC is left untouched); a preference edits the IFC directly. An IFC over 5 MB asks first (the Clinic takes about 6 minutes to convert): make a `.kim`, edit the IFC directly, or cancel. The conversion runs behind a progress window | File › Open… an `.ifc` |
| Open as folder | File › Open project folder… / Save as project folder… | |
| One person at a time | A second person (or window) opens the file read-only, with who has it and since when | Open a `.kim` that's open elsewhere |
| User preferences | Edit › Preferences: language, templates folder, your name, new views as tabs or free windows, IFC opening, automatic versions, recovery copy | |
| Project settings | File › Project settings: plan cut height, drawing scale on sheets, sheet paper, length units; layer show/lock states are kept too | |
| Office templates | File › Save as template… saves into the templates folder; File › New project… lists them | |
| New views | Open as a tab right after the current one (default) or as a free window (preference) | P, or open a sheet |
| Crash recovery | A recovery copy of unsaved work every 5 minutes, offered at the next start | |
| A1 sheet could not be created | Fixed: sheets work on IFC2X3 files such as the Clinic | View › New sheet on the Clinic |

Plan tabs (a standard floor plan without the cut slider) are on hold for the architect's answers ([open questions](open-questions.md#for-the-architect-asked-2026-10-07-waiting)). Next: **step 3**, pen sets (the colour palettes switched per purpose).

## 2026-10-08 (later): pen sets, line types, visibility and purposes (step 3 of 3)

([spec](superpowers/specs/2026-10-08-pen-sets-and-graphics-design.md), D73)

| Note | What KimBim does now | Try it |
|------|----------------------|--------|
| The pen button was greyed out | It shows the current pen; click it for a 16×16 grid of pens. New text, dimensions and marks take it, and so do the selected ones | Bottom bar |
| A colour palette like Archicad's, switched per use | **Purposes**: Working (colours by kind), Highlight (pale grey, fire ratings in colour), Permit (black, printed weights), Presentation (greys, no furniture), Demo. One drop-down restyles the 3D view, plans, drawings and sheets | Bottom bar, left |
| Pens are line styles | Pen sets (255 pens: colour, weight in mm, name) and **element styles** (which pens and line types walls, doors, furniture… use for cut and projection lines and the cut fill) | Graphics › Pen sets…, Element styles… |
| Line styles | Line types: dash patterns in mm on paper (Dashed, Dotted, Dash-dot, Centre, Hidden, your own) | Graphics › Line types… |
| Which lines are shown (hide furniture, piping, non-structural…) | **Visibility sets** hide element kinds and match hide rules (e.g. LoadBearing = false); built-ins: Everything, Architectural (no MEP), No furniture, Structure only | Graphics › Visibility sets… |
| Highlights by property | **Graphic overrides**: rules by kind, IFC class, property, layer or material that change pens, line type, fill or the 3D colour; the first that matches wins (Fire rating, Load-bearing walls, External walls built in) | Graphics › Graphic overrides… |
| Layers per use | **Layer combinations**; a purpose can switch to one | Graphics › Layer combinations…, Purposes… |
| Printed sheets | A sheet can print with its own purpose (right-click it in the Sheets panel › Purpose); a 0.50 mm pen prints 0.50 mm at any scale | Sheets panel |
| Thick lines on screen | View › True line weights | View menu |

Everything is saved in the project (and in office templates), so an office standard travels with every new project. Not yet: a pen per individual element, weights that change with the scale, hatches.

## Shortcuts added

Place model **U** · Text label **A** · Dimension **Q** · Mark **X** (with the earlier W, S, D, N, K, J, G, M, R, E, T, O).

## Still open for the next session

- Confirm 9 (flash) and the feel of 1 and 8 on your screen; tests can't see either.
- Annotations: revision clouds. (Leaders, text size in paper units, dimension chains and snapping to wall faces: done in Slice 15.)
- Models: editing an instance in place (today: edit the model, then Update), nested models, a model library across projects.
- Views: weights that change with the scale, hatches and a pen per element (pen sets, overrides and purposes: done in step 3, D73).
