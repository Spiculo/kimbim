# 12 — M3 exit: the two-storey house

The M3 (modeler) exit criterion ([07](07-roadmap.md)): *an architect can model a small 2-storey house from scratch and export valid IFC that opens in at least two other tools.*

## The sample house

`pixi run house` builds it through the same modeling commands the app uses and writes `build/house.ifc`. The script is [`tools/make_house.py`](../tools/make_house.py).

| | |
|---|---|
| Levels | Level 1 (0 m), Level 2 (3 m), Roof (6 m) |
| Walls | 10 × 8 m loop of 300 mm layered exterior walls per floor, joined at the corners (Level 2 copied from Level 1) |
| Openings | a front door and 4 windows per floor, in real openings |
| Slabs | floor slabs on Levels 1 and 2 (outer faces of the walls), roof slab; stair hole in the Level 2 floor |
| Structure | a 300 × 300 column and a 200 × 400 beam under the Level 2 floor |
| Stair | straight flight from Level 1 to Level 2: 18 risers of 167 mm, 280 mm goings |

The same things can be drawn by hand in the app with the Wall (W), Door (D), Window (N), Slab (S), Column (K), Beam (J), Stair (T) and Slab opening (O) tools. Use *Model › Copy to level…* for the upper floor and *Model › Slab from selected walls* for slabs. The app's window-level tests drive exactly these tools.

## Automatic checks (CI, Windows and Linux)

`pixi run interop` builds the house and runs [`tools/check_interop.py`](../tools/check_interop.py):

1. **IFC4 validation:** IfcOpenShell's validator, covering the schema (types, cardinalities, inverse attributes) **and the EXPRESS WHERE rules and functions**. Result: 0 issues.
2. **A second, independent engine:** [web-ifc](https://github.com/ThatOpen/engine_web-ifc) 0.0.78, the parser and geometry kernel behind That Open / IFC.js viewers, which shares no code with IfcOpenShell. It opens the file and must produce geometry for every building element. Result: 24/24 elements meshed, no warnings.

The first web-ifc run found one real interoperability issue: profiles without an explicit `Position` (optional in IFC4). KIMCAD now always writes it.

## Manual check (owner)

The automatic checks cover "valid" and "opens in another engine". The criterion asks for **two other tools** people actually use, so please open `build/house.ifc` in:

- **A commercial viewer: this is the check that counts.** It reads IFC with its own code, independent of KIMCAD. Examples: BIMvision (free), Solibri Anywhere, Revit's IFC import, or Autodesk Viewer (online, so the file gets uploaded).
- **Bonsai** (Blender + Bonsai add-on, free): *File › Open IFC Project*. Bonsai reads files with **IfcOpenShell, the same library KIMCAD writes them with**, so a pass there shows the file works in a real architect's tool, but says little about compatibility.
- If you can, **a second tool that doesn't use IfcOpenShell**, for example xBIM Xplorer (free, .NET), so two independent engines besides web-ifc have opened the file.

and check:

1. The file opens without errors or warnings about the file itself.
2. Three storeys are listed: Level 1, Level 2, Roof.
3. The element counts match: 8 walls, 3 slabs, 2 doors, 8 windows, 1 stair, 1 column, 1 beam.
4. Doors and windows sit in holes in the walls, and the stair hole shows in the Level 2 floor.
5. Wall corners are closed (mitred), with no overlaps or gaps.
6. Selecting a wall shows its type (Exterior 300) and layered material (Brick / Insulation / Block).
7. A door shows its type, `OverallWidth`/`OverallHeight`, and the `KIMCAD_OpeningDefaults` pset on its type.

Note anything odd in an issue. When the commercial viewer passes (and Bonsai), M3 is done.
