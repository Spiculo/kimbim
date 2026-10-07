# KIMCAD

**Open-source native BIM for architects, with version control built in.**

KIMCAD is a desktop BIM application for Windows and Linux built on open standards (IFC). Model your building, cut through it, manage object data, reuse libraries and produce drawings. Then save versions, explore design options, compare them and combine them, the way software developers use Git, but for buildings.

> Status: **early development.** Slice 1 works: versioned IFC projects from the command line. The desktop app comes next. Design docs: [docs/README.md](docs/README.md).

## Try the desktop app

```bash
pixi install
pixi run app                      # opens KIMCAD (English or Spanish, following your system)
pixi run app -- model.ifc --lang es
pixi run app -- --self-test model.ifc --screenshot shot.png   # load, measure fps/picking, print JSON
pixi run app -- --self-test model.ifc --create-drawings --open-drawing "South Elevation"   # time a drawing
```

Open an IFC file. It appears progressively in the 3D view, with the spatial tree on the left and properties on the right.

| Action | How |
|---|---|
| Pan / orbit / zoom | Middle-drag / **Shift**+middle-drag (around the point under the mouse) / wheel (toward the cursor) |
| Select / add / toggle | Click / **Ctrl**+click / **Shift**+click; left-drag draws a selection box (only visible elements; **Alt**+drag also takes hidden ones) |
| Edit | Double-click a value in Properties (applies to every selected element); right-click to add or remove properties, edit a value on the type, or reset to the type value (dimmed values come from the type) |
| Undo / redo / save | **Ctrl+Z** / **Ctrl+Y** / **Ctrl+S** (**Ctrl+Shift+S** to save as) |
| Hide / isolate / show all | **H** / **I** / **Shift+H** |
| Plan cut / section box / fit | **C** (height above the active level, in the Cuts toolbar) / **B** / **F** |
| New project / add a level | **Ctrl+N** / *Add level…* in the Levels toolbar (the active level is where you draw) |
| Plan view / 3D view / lines only | **P** / **3** / **L** (line drawing, hidden lines removed) |
| Draw walls | **W**, then click points (snaps to wall ends, midpoints, perpendiculars, 15° angles; **Shift** for right angles), type a length + **Enter**, **Esc** to finish. Walls join at corners and T's |
| Draw slabs | **S**, click the outline's points, click the first point or **Enter** to close; or select a closed loop of walls and use *Model › Slab from selected walls* |
| Place doors / windows | **D** / **N**, then click on a wall (the type sets the size and sill) |
| Columns / beams / grid lines | **K** (click; **Shift** turns it 90°) / **J** (two clicks; top = level + height field) / **G** (two clicks; tags A, B… and 1, 2… are automatic; points snap to grid crossings) |
| Move / rotate | Select, then **M** (base point, target) or **R** (centre, reference, new direction; or type degrees). Walls joined to what you move stretch along their own line to stay joined (they stay straight); hold **Ctrl** on the last click to detach them. Doors/windows alone slide along their wall |
| Stretch a wall | **E**, click near a wall end, click its new position (or type the length) |
| Wall height / door size | *Model › Wall height…* / *Model › Door/window size…* for the selection |
| Upper floors | *Model › Copy to level…* (walls bring their doors, windows and corner joins), **T** stair to the next level (two clicks), **O** hole in the selected slab |
| Delete | **Del** (deleting a wall also deletes its doors and windows) |
| Sections / elevations | **V** section, **Shift+V** elevation: click the line's two ends, then the side it looks at (as in Archicad). New projects come with North/South/East/West elevations; *View › Create elevations* adds them to an opened IFC. Markers show in plan view; select, move, rotate or delete them like elements |
| Floor plans | Every level has a floor plan drawing (cut at 1.10 m, as in Archicad): walls cut, door swings, window glass, your labels, dimensions and marks, and the section/elevation markers. *View › Create floor plans and elevations* adds them to an opened IFC |
| Annotation | **A** text, **Q** dimension (Shift+click adds points to a chain; snaps to wall faces), **X** mark, **Shift+A** leader. Text size is in millimetres on paper (*Properties › KIMCAD_Annotation › Size*) |
| Drawings | The *Drawings* tab (left) lists them; double-click opens one in a tab next to *Model* (wheel zoom, drag to pan). It is generated in the background and shows *Regenerate* when the model has changed |

## Try it (command line)

Requires [pixi](https://pixi.sh). Works on Windows and Linux.

```bash
pixi install                      # environment from conda-forge (IfcOpenShell, Rust, Git, ...)
pixi run build                    # build the Rust engine (kimcad._core)

pixi run kimcad init my-house                       # create a project
pixi run kimcad -C my-house commit model.ifc -m "Import from Revit"
pixi run kimcad -C my-house status edited.ifc       # what would change
pixi run kimcad -C my-house commit edited.ifc -m "Fire ratings"
pixi run kimcad -C my-house log
pixi run kimcad -C my-house diff                    # last version vs its parent
pixi run kimcad -C my-house export v1.ifc --rev HEAD~1
pixi run kimcad -C my-house branch option-b         # a design option
```

Each version stores the model as canonical, object-level records in a standard Git repository (`my-house/.git`). A one-property edit on a 10,000-object Revit model is stored as **one changed record**. Exports are lossless and byte-identical on Windows and Linux. See [docs/11](docs/11-spike-results.md) for how that was validated.

Development: see [CONTRIBUTING.md](CONTRIBUTING.md).

- Built on [IfcOpenShell](https://ifcopenshell.org), [OpenCASCADE](https://dev.opencascade.org), [Qt](https://www.qt.io) and Rust.
- Local-first: no server, no account, no network required.
- License: GPL-3.0-or-later.
- Languages: English and Spanish.

The original specification (v0.1) is kept in [doc.md](doc.md). The `docs/` folder supersedes it.

**Sample two-storey house:** `pixi run house` writes `build/house.ifc`; `pixi run interop` validates it (IFC4 schema + EXPRESS rules) and opens it with web-ifc. See [docs/12-m3-exit.md](docs/12-m3-exit.md).

**Versioned projects:** *File › Enable versioning…* turns a model into a project folder with history. *Save version* (**Ctrl+Alt+S**, or **Ctrl+S** in a project) asks for a message and shows what changed. The **History** panel lists versions; *Compare with current* or *Compare the two selected* colours the 3D view (added green, modified orange) and lists the changes. Design options are in the **Option** toolbar (*New option…*, switch with the list). *File › Open project…* reopens a project folder.
