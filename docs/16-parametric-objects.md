<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 16 — Parametric objects: customisable library objects as data

**Status: Proposed (D99, 2026-10-22).** Approved by the owner in conversation; the implementation plans come next.

## Why

Today's library (D86) is 21 Python functions in `python/kimbim/library.py`, each with a short, fixed list of
parameters. The chair has width, depth, height and seat height, and always four square legs at the corners
(`_legs()`). Offices add objects by writing Python files that call `define()`, which KimBim runs in-process.

Two problems:

1. **Too little to customise.** An architect cannot change how many legs a chair has, their angle, where they meet
   the seat or what the backrest is. Archicad's GDL objects and Revit's families can.
2. **Objects are code.** A shared object file can read, delete or send the user's files. Once objects are
   customised and passed around (sent by a consultant, downloaded, kept inside a project someone else opens),
   running them is not acceptable.

The fix for both: **an object is a data file that the app reads, never runs**, with enough parameters, formulas,
parts and patterns to describe furniture, fixtures and equipment, and an Object Editor in the app to make one
without code.

## Success

The owner opens the bundled chair, gives it three splayed legs at 8° set on a circle under a round seat, swaps the
back for slats, saves it to the office library, places it, and sees it right in 3D, in plan, in a schedule and in
the exported IFC (valid against the schema, opening in Bonsai). Nothing in the object file can execute.

## References

Archicad's library parts (GDL: parameters, macros, 2D and 3D scripts, hotspots) are the default model; Revit's
families (type and instance parameters, nested families, formulas) are the fallback where Archicad has nothing
(D61, D92). GDL is a language of its own with no file access; KimBim goes further and has no language at all,
only formulas.

## 1. The format

One JSON file per object, extension `.kimobj`, format id `kimbim-object/1` (no older format is kept: KimBim is
unreleased, so formats change outright). JSON because the store diffs and hashes it like settings, and the
Object Editor writes it, so nobody needs to type it by hand.

```json
{
  "format": "kimbim-object/1",
  "id": "chair",
  "name": "Chair",
  "category": "furniture",
  "ifc": {"IFC4": ["IfcFurnitureType", "CHAIR", null], "IFC2X3": ["IfcFurnitureType", null, "CHAIR"]},
  "origin": [0, 0],
  "params": [ ... ],
  "parts":  [ ... ],
  "symbol": [ ... ]
}
```

- `id` is unique within its source (bundled, office or project, §5). `name` and labels have an `es` entry for
  the Spanish UI (`{"en": "Chair", "es": "Silla"}`); a plain string is used for both.
- `ifc` maps schema families to (type class, predefined type, element type), as `Obj.ifc` does today.
- `origin` is the insertion point in object metres from the left front corner (D92). Front at y = 0 (Archicad).
- Lengths are metres, angles degrees, everywhere in the file.

### Parameters

| Kind | Value | UI in Properties and the editor |
|------|-------|----------------------------------|
| `length` | metres, `min`/`max` | length field in the project's unit |
| `angle` | degrees, `min`/`max` | number with ° |
| `count` | whole number, `min`/`max` | spin box |
| `bool` | true/false | check box |
| `choice` | one of `options` (ids with labels) | drop-down |
| `material` | a building material's name (D96) | drop-down of the model's materials |

```json
{"key": "legs",   "kind": "count",  "label": {"en": "Legs", "es": "Patas"}, "default": 4, "min": 1, "max": 8},
{"key": "layout", "kind": "choice", "label": "Leg layout", "default": "corners",
 "options": [{"id": "corners", "label": "At the corners"}, {"id": "circle", "label": "On a circle"}]},
{"key": "radius", "kind": "length", "label": "Leg circle radius", "default": 0.18, "min": 0.05, "max": 1,
 "show_when": "layout == 'circle'"},
{"key": "splay",  "kind": "angle",  "label": "Leg splay", "default": 0, "min": 0, "max": 20}
```

- `default`, `min` and `max` may be formulas over other parameters (`"max": "seat_h - 0.1"`); values are clamped
  as `Param.clean` does today, `count` rounded first.
- `show_when` hides a parameter whose condition is false (the backrest's settings when the back is *none*). Hidden
  parameters keep their values.
- `group` (optional) puts parameters under a heading in Properties (*Legs*, *Back*).
- `width`, `depth` and `height` keep their meaning: the type name (`Chair 450x520x850`) and the placement preview
  box use them, as today.

### Formulas

Any number in a part, and a parameter's `default`/`min`/`max`/`show_when`, may be a formula string. The evaluator
is written for KimBim (a small recursive-descent parser in `kimbim/objexpr.py`); **Python's `eval` is never used**.

- Literals: numbers, `'text'` (for comparing choices), `true`, `false`.
- Names: parameters; `pi`; inside a repeat, `i` (0-based index) and `n` (the count); anchor fields
  (`seat.top`, `seat.anchors.back_edge.x`).
- Operators: `+ - * / ^ %`, comparisons, `and or not`, unary minus.
- Functions: `if(c, a, b)`, `min`, `max`, `abs`, `sqrt`, `round`, `floor`, `ceil`, `clamp(x, lo, hi)`,
  `sin cos tan asin acos atan atan2` (degrees).
- No assignment, no loops, no attribute access beyond the names above, no strings other than literals.
- Limits: 500 characters per formula, nesting depth 32, **5,000 solids per object** after repeats, 50 parts deep
  through `use`. Going over is an error for that object (§7), never a hang.
- Errors name the field: `parts.leg.cylinder.h: unknown name "seat_hh"`.

## 2. Parts

`parts` is a list; each part has a unique `id` and one shape, or a `use` (below).

### Shapes

| Shape | Fields | IFC (§4) |
|-------|--------|----------|
| `box` | x, y, z, dx, dy, dz | IfcExtrudedAreaSolid, rectangle profile |
| `cylinder` | r, h (axis +z from the part origin) | IfcExtrudedAreaSolid, circle profile |
| `cone` | r1 (bottom), r2 (top), h; or `taper` on a box | IfcExtrudedAreaSolidTapered |
| `prism` | points (polygon in x, y), z, h | IfcExtrudedAreaSolid, arbitrary closed profile |
| `revolve` | profile (points in x, z), angle (360 default) | IfcRevolvedAreaSolid |
| `sweep` | profile (points) or `r` (a tube), path (points, optional fillet radius) | IfcFixedReferenceSweptAreaSolid; IfcSweptDiskSolid for tubes |

Points are lists of numbers or formulas. A shape too thin to exist (a size ≤ 0.1 mm) is skipped, as
`Shape.box` does today.

### Placement

```json
{"id": "leg", "material": "frame",
 "repeat": {"count": "legs", "on": "seat.anchors.{layout}"},
 "cone": {"r1": 0.015, "r2": 0.02, "h": "seat_h - 0.04"},
 "rotate": {"axis": "away_from_centre", "angle": "splay"}}
```

- `at: [x, y, z]` moves the part; `rotate: {axis, angle}` turns it about its own origin. `axis` is `x`, `y`,
  `z`, a vector, or `away_from_centre` (horizontal, pointing from the parent's centre to this copy: splayed legs).
- `attach: "seat.anchors.back_edge"` sets the part's origin and orientation on an anchor; `at` and `rotate` then
  apply in the anchor's frame.
- `when: "back != 'none'"` leaves the part out when false.
- `material: "frame"` is its material slot. Slots are declared in `materials` (`{"frame": {"label": "Frame",
  "default": "Timber - finish"}}`) and become `material` parameters, as D97's `mat_<part>` do today.

### Anchors

A part may declare named anchors: a point, an x direction and a z direction, in formulas.

```json
{"id": "seat", "box": {"x": 0, "y": 0, "z": "seat_h - 0.04", "dx": "width", "dy": "depth", "dz": 0.04},
 "anchors": {
   "corners": {"pattern": "rect_corners", "inset": 0.03, "z": "seat_h - 0.04", "dir": "down"},
   "circle":  {"pattern": "circle", "cx": "width/2", "cy": "depth/2", "r": "radius", "z": "seat_h - 0.04", "dir": "down"},
   "back_edge": {"x": "width/2", "y": "depth - 0.02", "z": "seat_h"}
 }}
```

- Every shape has built-in anchors: `centre`, `top`, `bottom`, and for boxes `front`, `back`, `left`, `right`
  (face centres, facing out).
- `pattern` anchors are a set of frames: `rect_corners` (the four corners, inset), `circle` (`count` spread
  evenly, from the repeat), `line` (from, to, count), `grid` (nx, ny, dx, dy). A repeat `on` a pattern anchor
  gets one copy per frame; `count` asks the pattern for that many.

### Repeats

`repeat` makes `count` copies (at most the 5,000-solid limit): `on` a pattern anchor, or `step: [dx, dy, dz]`
and `turn` (degrees about z per copy) for linear and polar arrays. Inside a repeated part, `i` and `n` are the
copy's index and the count (slat `k` at `x: "0.05 + i * (width - 0.1) / (n - 1)"`).

### Variants and nested objects (`use`)

```json
{"id": "back", "when": "back != 'none'", "attach": "seat.anchors.back_edge",
 "use": "back_{back}", "with": {"width": "width", "height": "height - seat_h"}}
```

- `use` names a **component** in the same file (`components: {"back_slats": {params, parts}, ...}`) or another
  library object (`"office:stool"`). `{name}` inside it is replaced by that choice parameter's value, so a
  choice picks a variant. `with` passes values (formulas over the caller's parameters); the rest keep the
  component's defaults.
- A component is an object without IFC class or origin of its own: Archicad's macros, Revit's nested families.
  Cycles (`a` uses `b` uses `a`) are an error.

## 3. The plan symbol

- `symbol` (optional) is 2D in object metres: `line`, `rect`, `circle`, `arc`, `polygon`, with formulas,
  `when` and `repeat` as parts have. The bundled objects keep their drawn symbols (the WC's bowl, the bed's
  pillows).
- Without `symbol`, the symbol is the **outline of the parts seen from above**: each solid's plan footprint,
  unioned (the chair's seat rectangle and the splayed feet sticking out past it), drawn as the projection lines.
- Floor plans, the Library panel's thumbnails and DXF use it exactly as D86's symbols today.

## 4. IFC

Unchanged from D86 except the geometry:

- One **IFC type per object and parameter set** (D50), with the Body and Plan representation maps; placements are
  occurrences with mapped items, so repeats share geometry and schedules count by type.
- Each shape is a native solid (table in §2), placed by an `IfcAxis2Placement3D` per copy; Body's
  representation type is `SweptSolid`, or `AdvancedSweptSolid` when it has tapered extrusions or sweeps.
  IFC2X3 has no `IfcExtrudedAreaSolidTapered` or fixed-reference sweep: cones become revolves, profiled sweeps
  become segments of extrusions.
- `KIMBIM_LibraryObject` on the type: `Object` (source and id, `office:chair`), `Parameters` (JSON, metres and
  degrees), `Library`, **`DefinitionHash`** (BLAKE3 of the definition's canonical JSON) and **`Definition`**
  (the full JSON as IfcText). So a plain IFC or a shared `.kim` holds everything needed to edit its objects
  again; the store keeps identical text once (records are content-addressed).
- Materials per part as D97 (the constituent set and styled items by slot).

## 5. Where definitions come from

| Source | Where | Notes |
|--------|-------|-------|
| **bundled** | `python/kimbim/objects/*.kimobj`, shipped | the 21 objects of D86, ported (§8) |
| **office** | the office library folder (preference, D86) | `.kimobj` files and IFC type files; **`.py` files are no longer read** |
| **project** | the definitions carried by the model's types (§4) | what placed objects were made from |

- A placed object's parameters always regenerate from **its own definition** (the one on its type), so
  changing a library file never changes a project silently.
- When the library has the same `source:id` with another hash, the Library panel and Properties show
  *Update from library*: it regenerates the selected objects' types from the library's definition, keeping
  parameter values whose key and kind still exist (one undo step). Archicad reloads library parts on open; KimBim
  asks, because a project is versioned and a silent change would show up as an unexplained diff.
- Library files that fail to load (bad JSON, unknown kind, formula error at the defaults) are listed in the Library
  panel with the error and left out; the rest load.

## 6. Editing

### In Properties (every placed object)

The *Parameters* group (D86) shows the new kinds (degrees, check boxes, drop-downs), groups and `show_when`.
A change works as today: the selected objects move to the type with the new values, or the type regenerates in
place when the selection is all its placements (D92's scope setting). One undo step.

### Object Editor

Library panel › *New object...*, *Edit...* (office or project objects; bundled ones open as a copy), or
right-click on a placed object › *Customise a copy...* (Archicad's *Save selection as...*).

- **Parameters** table: key, label (EN/ES), kind, default, min, max, group, show when; add, remove, reorder.
- **Parts** tree: each part with its shape and fields, placement, repeat, attach, when, material slot, anchors;
  add a part, a component, a `use`. Every field takes a number or a formula and shows its error beside it.
- **Preview**: live 3D (orbit) and plan symbol, redrawn 0.3 s after a change from the current parameter values;
  a *Try values* strip changes them without changing the defaults. A broken formula keeps the last good shape
  and marks the field red.
- **Save** to the project (the open model's types carry it) or to the office library (writes the `.kimobj`).
  Save is refused while any field has an error.
- The editor edits the JSON through `kimbim.objects`; nothing in it is C++-only, so the console and tests can do
  the same.

## 7. Errors and limits

- Loading validates the file against the format (kinds, required fields, ids unique, names known, no `use`
  cycles) and evaluates it once at its defaults. Any error leaves that object out with a message naming the field.
- Evaluating with given values that break a formula (division by zero, `sqrt` of a negative) fails that edit with
  the message; the model keeps the last good type. A placed object never loses its geometry because a value is bad.
- The limits of §1 stop a hostile file from freezing or exhausting the app. There is nothing to sandbox: no code
  runs.

## 8. Removing the Python path, and proving the format

- `define()`, `Obj.build`, the build functions and loading `.py` files from the office folder are **removed**
  (no compatibility kept). `library.py` keeps the type, placement and parameter-editing code; the format and
  evaluator go to `kimbim/objects.py` and `kimbim/objexpr.py`.
- All 21 bundled objects are ported to `.kimobj` first. A test builds each one both ways at its defaults and at
  two other value sets, and compares bounding box, volume (±0.5 %) and plan symbol; the Python builders are
  deleted only when every object matches.
- The **chair** is then extended as the showcase: 1–8 legs, corners or a circle, splay 0–20°, straight, tapered
  or sled legs, a slat, panel or upholstered back or none, arms on or off, round or square seat.
- The Python console (doc [15](15-scripting.md)) still automates everything, including writing `.kimobj` files,
  but cannot define a live object any other way.

## 9. Testing

- `objexpr`: every operator and function; precedence; errors with positions; hostile inputs (deep nesting, huge
  repeats, long formulas) fail fast.
- `objects`: loading, validation messages, anchors and patterns, repeats, `use` with `with`, cycles,
  `show_when`, clamping, the 5,000-solid limit.
- Geometry: the port comparison (§8); generated types validate against the IFC4 and IFC2X3 schemas with 0
  issues; a model with the showcase chair round-trips (save, reopen, edit a parameter, same GlobalIds).
- App self-tests: the Object Editor makes a 3-leg chair, saves it to the office library, places it, and the plan
  and 3D dumps show three legs; *Update from library* after editing the file.

## 10. Delivery

One spec, two implementation plans:

- **A. Engine:** format, evaluator, shapes and IFC, anchors, repeats, `use`, sources and *Update from library*,
  the new Properties kinds, the port of the 21 objects, removal of the Python path, the showcase chair.
- **B. Object Editor:** the dialog, preview, save to project or office, *Customise a copy*.

A is useful on its own (richer bundled objects, safe office files written by hand or by script); B makes them
authorable by architects.

## Not now

- Editable hotspots/grips on placed objects (Archicad's graphical hotspots, Revit's shape handles).
- Mesh import (OBJ, glTF) as a shape; free-form objects wait for it.
- A node editor (Grasshopper, Dynamo, Marionette).
- Doors and windows as `.kimobj` (they stay D97's parametric types for now).
- Online catalogues (🔮, doc [14](14-tool-inventory.md)).
