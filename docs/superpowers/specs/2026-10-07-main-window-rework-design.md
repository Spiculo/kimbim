# Main window rework — design (step 1 of 3)

Owner request, 2026-10-07: more room for the model. Tools on the left grouped by category, the object
tree on the right and less noisy, properties on double-click, a bottom bar, and 3D and plan views as tabs
that pop out of the center and dock back.

This is **step 1 of 3**. Each step has its own spec, plan and approval:

1. **Main window rework** (this spec). The app only; no file-format change, no bridge change.
2. **`.kim` file and preferences.** One file by default, with an "open as folder" mode. Project settings
   live in the file and user preferences per computer; office templates for new projects.
3. **Pen sets.** Archicad-like numbered pens (colour, line weight) in named sets; the current pen is
   editable in the bottom bar. They are stored in the project, so this step needs step 2.

Out of scope: several separate models open together (linked models). See
[08 — Federation and linked models](../../08-future.md#federation-and-linked-models).

## What the architect sees

```
┌ File  Edit  View  Model  Help ─────────────────────────────────────────┐
│ [Option: main ▾][Save version]  Level: [Level 1 ▾]  Cut ▭  …           │ one slim top bar
├────────┬──────────────────────────────────────────────┬────────────────┤
│ TOOLS  │ [3D] [Level 1 plan] [Section 1] [Sheet A01]   │ Model │Props│… │
│ ▾ 3D   │ ┌ tool options (active tool only) ──────────┐ │ ▸ Level 1      │
│  Wall  │ │ Type [Ext 300▾]  Height [3.00]            │ │   ▸ Walls (12) │
│  …     │ └───────────────────────────────────────────┘ │   ▸ Doors (3)  │
│ ▾ Plane│          3D / plan / drawing / sheet           │ ▸ Level 2      │
│ ▾ View │                                               │                │
│ ▾ Edit │                                               │                │
├────────┴──────────────────────────────────────────────┴────────────────┤
│ Pen [—] │ Layer [A-WALL▾] │ Layers 12/15 ▸ │ 100% │ 2 walls │ message   │
└────────────────────────────────────────────────────────────────────────┘
```

### Left: tool palette

A narrow column of collapsible groups. Each tool is an icon with its label, and the column can shrink to
icons only. The groups:

| Group | Tools |
|---|---|
| 3D | Wall, Slab, Column, Beam, Door, Window, Stair, Roof, Room, Slab opening, Place model |
| Plane | Text label, Dimension, Leader, Mark, Grid line |
| View | Section, Elevation, New plan tab, New sheet |
| Edit | Move, Rotate, Stretch wall, Mirror, Copy to level |

The tools are the existing `QAction`s, so shortcuts, hover hints and translations don't change. The
Model menu keeps every tool. Commands that aren't drawing tools (Wall height…, Trim walls to roof,
Update model instances, …) stay in the menus and the right-click menu.

### Tool options strip

The per-tool fields that sit in today's always-visible Modeling toolbar move into a strip at the top of
the active view. It shows only while a tool is active, and only that tool's fields: wall type and
height, beam height, roof shape and pitch, and so on.

### Center: views as tabs

- Tabs: **3D**, one **plan tab per level** that is opened, sections, elevations and sheets.
- Any tab can be dragged out into its own window (for example onto a second monitor), docked back, or
  placed side by side with another tab.
- The 3D tab can't be closed. A plan tab closes when its level is deleted, and a drawing tab when its
  drawing is (as today).
- New plan tab: from the View group, the level bar, or by double-clicking a level in the tree.

### Right: panels

The model tree, Properties, Layers, History, Drawings and Sheets are tabs in one panel area. The area
can auto-hide to a strip at the window edge, and any panel can be dragged elsewhere or floated.

**Properties on double-click:** double-clicking an element (in a view or in the tree) selects it and
brings the Properties panel forward. If it's auto-hidden, it slides out; if it's floating, it's raised.
It follows the selection while open.

### Bottom bar

Left to right:
- **Pen:** a placeholder that is disabled until step 3.
- **Active layer:** a drop-down.
- **Visible layers:** a count and a quick toggle list.
- **Zoom** of the current tab.
- **Selection:** count and kind, for example "2 walls".
- **Status messages:** these replace today's status bar.

### Model tree, tidied

- Rows show plain names: "Wall", not `IfcWallStandardCase`. The Type column is removed; the IFC type
  shows on hover.
- A row with exactly one child is merged into it, so Project › Site › Building becomes one "Building"
  row. A project with two buildings still shows both.
- Under a level, elements are grouped by category with a count: `Walls (12)`, `Doors (3)`.
- Search still matches name, type and GlobalId, and Isolate / Hide / Show all work as today.

### Top

One slim bar replaces the Project, Levels and Cuts toolbars: design option and Save version, the active
level, and the cut controls.

### Layout memory

The window layout (panel places, floating windows, open tabs) is saved on close and restored on start
with `QSettings`. In step 2 this moves into the user preferences. A layout that doesn't fit the
screens any more (an unplugged monitor) falls back to the default layout. Unknown tabs in a saved
layout (a drawing deleted since) are skipped.

## How it is built

### Docking library

The **Qt Advanced Docking System** (ADS; LGPL-2.1, compatible with GPL-3.0-or-later). It gives
detachable and dockable tabs, floating windows, auto-hide side bars, and saving/restoring the layout.
conda-forge only packages it for Qt 5, so it is built from source with CMake `FetchContent`, pinned to a
release tag and its commit hash. It's added to `THIRD_PARTY.md`.

### Scene and views

Today `Viewport` holds both the OCCT scene and the single view. It is split:

- **`Scene`** (new) owns the `V3d_Viewer`, the `AIS_InteractiveContext`, the element meshes and
  colours, the selection, hidden and isolated elements, layer visibility and the cut planes.
- **`Viewport`** becomes one `V3d_View` on a `Scene`. It owns the camera, navigation, snapping, the
  active tool, and plan or 3D mode.

The 3D tab and every plan tab are `Viewport`s on the same `Scene`, so the model is loaded once. Selecting
in one tab selects in all of them. After an edit, `afterEdit` updates the `Scene` once and every open
view redraws. The active tool belongs to the tab it was started in; switching tabs cancels a tool in
progress, the same as Esc.

### MainWindow split

`MainWindow.cpp` (3,600 lines) becomes:

| Unit | Does |
|---|---|
| `DockLayout` | ADS setup, center tabs, panel areas, saving and restoring the layout |
| `ToolPalette` | the left column (built from the existing tool actions) |
| `ToolOptionsBar` | the active tool's fields above the view |
| `StatusStrip` | the bottom bar |
| `ModelTreePanel` | the tidied tree |
| `MainWindow` | wiring between these and the Python bridge |

The bridge (`python/kimcad`) doesn't change.

## Testing

- The existing app tests (`pixi run app-test`) are updated to the new layout and keep passing.
- New tests:
  - Two `Viewport`s on one `Scene`: selecting and editing in one updates the other.
  - A plan tab popped out and docked back keeps its camera and level.
  - The tree tidying on the house model and on Clinic: merged single-child rows, category groups and
    counts.
  - Double-clicking an element shows Properties.
  - The layout is restored after a restart; a missing screen falls back to the default layout.
  - Every tool is in exactly one palette group and in the Model menu.
- Performance: the refresh after an edit is still timed on `Clinic_Architectural.ifc`, now with a 3D
  tab and a plan tab open. Edits must stay as fast as today.
- Translations: the new strings are in English and Spanish (`pixi run check-translations`).

## Decision

D71 (to add to `docs/decisions.md` with the plan): the main window uses the Qt Advanced Docking System.
The 3D and plan views are views of one shared OCCT scene; tools are grouped 3D / Plane / View / Edit on
the left, panels are tabbed on the right, and a bottom bar holds the pen, layers, zoom and selection.
