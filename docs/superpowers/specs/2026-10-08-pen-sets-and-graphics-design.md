# Pen sets, line types, visibility and purposes: design (step 3 of 3)

Owner request, 2026-10-07: the pen button in the bottom bar is greyed out. The owner wants an
Archicad-style palette: pick which things get which colours, and switch quickly between uses (regular
work, highlight, permit submission, presentation, demo). On 2026-10-08 they added line styles and
visibility ("which lines are shown: hide furniture, piping, non-structural…"), asked for every option
offered (per-kind visibility, rule overrides, layer combinations tied to the switch), and approved the
proposal below. They will check it with an architect after it is built.

Steps 1 (main window, D71) and 2 (`.kim`, project settings, templates, D72) are merged. This step
stores everything in the project settings from step 2, so it is versioned, merged by Combine and
carried by office templates.

Out of scope: a pen on each element by hand (rules by property or layer do it), line weights that
change with the drawing scale, fill patterns and hatches (cut fills are solid), material
surfaces and textures, the plan-tab redesign (on hold for the architect).

## The six pieces

| Piece | What it is | Settings key |
|---|---|---|
| Pen set | 255 numbered pens, each a colour, a weight (mm on paper) and an optional name | `pen_sets` |
| Line types | Named dash patterns in mm on paper | `line_types` |
| Element styles | For each element kind: pens and line types for cut lines, projection lines and the cut fill | `element_styles` |
| Visibility set | Element kinds shown or hidden, plus "hide" rules | `visibility_sets` |
| Override set | An ordered list of rules: condition, then effect | `override_sets` |
| Layer combination | Hidden and locked layers, by name | `layer_combinations` |
| **Purpose** | One of each above (layer combination optional), chosen in one drop-down | `purposes`, `purpose` |

Also stored: `current_pen` (the pen for new annotations) and `sheet_purposes` (`{sheet number:
purpose}`, the purpose a sheet prints with; missing means the current purpose).

### Built-ins and storage

Each key starts empty in the settings, which means **the built-ins**. The first edit writes the whole
table (built-ins included) into the settings, so a project or a template carries its own complete
standard from then on. `graphics.effective(key)` returns the stored table, or the built-ins when it is
empty. Unknown fields inside entries are kept (an older KimBim never drops a newer one's data).

The settings stay JSON (`settings.json`, D72). The current purpose, current pen and the sets travel with
each version like the other settings, and Combine merges them key by key (D72).

## Pens and pen sets

```json
"pen_sets": {
  "Working": {"pens": {"1": {"color": "#000000", "weight": 0.13, "name": "Fine"}, ...}},
  "Permit":  {"pens": {...}}
}
```

- Pens are numbered **1–255**. A missing pen falls back to black, 0.18 mm.
- Colours are `#rrggbb`. Weights are mm on paper, from 0.05 to 5.0.
- **Built-in sets:** Working, Permit, Presentation, Highlight, Demo. Every set uses the same pen *roles*,
  so switching the set restyles everything:

| Pen | Role | Working | Permit | Presentation | Highlight | Demo |
|---|---|---|---|---|---|---|
| 1–7 | Generic black weights 0.13, 0.18, 0.25, 0.35, 0.50, 0.70, 1.00 | black | black | black | black | black |
| 10 | Walls, cut | dark brown 0.50 | black 0.50 | black 0.50 | grey 0.25 | dark red 0.50 |
| 11 | Walls, projection | brown 0.18 | black 0.18 | grey 0.18 | light grey 0.13 | red 0.18 |
| 12 | Walls, cut fill | brown grey | dark grey | mid grey | light grey | red-grey |
| 13 | Structure, cut (columns, beams, slabs, roofs, footings) | dark blue 0.50 | black 0.50 | black 0.50 | grey 0.25 | blue 0.50 |
| 14 | Structure, projection | blue 0.18 | black 0.18 | grey 0.18 | light grey 0.13 | blue 0.18 |
| 15 | Structure, cut fill | blue grey | dark grey | mid grey | light grey | blue-grey |
| 16 | Doors and windows | dark green 0.25 | black 0.25 | grey 0.18 | light grey 0.13 | green 0.25 |
| 17 | Stairs and railings | purple 0.18 | black 0.18 | grey 0.18 | light grey 0.13 | purple 0.25 |
| 18 | Furniture | olive 0.13 | black 0.13 | light grey 0.13 | light grey 0.13 | olive 0.18 |
| 19 | Plumbing and piping | cyan 0.18 | black 0.18 | grey 0.13 | light grey 0.13 | cyan 0.25 |
| 20 | HVAC | orange 0.18 | black 0.18 | grey 0.13 | light grey 0.13 | orange 0.25 |
| 21 | Electrical | magenta 0.18 | black 0.18 | grey 0.13 | light grey 0.13 | magenta 0.25 |
| 22 | Rooms | green 0.13 | black 0.13 | grey 0.13 | light grey 0.13 | green 0.13 |
| 23 | Annotations (text, dimensions, marks) | black 0.18 | black 0.18 | black 0.18 | grey 0.18 | black 0.18 |
| 24 | Grids | red 0.13 | black 0.13 | grey 0.13 | light grey 0.13 | red 0.13 |
| 25 | Other elements | grey 0.18 | black 0.18 | grey 0.18 | light grey 0.13 | grey 0.18 |
| 26 | Highlight (for overrides) | red 0.50 | red 0.50 | red 0.50 | red 0.50 | red 0.50 |
| 27 | Highlight 2 | blue 0.50 | blue 0.50 | blue 0.50 | blue 0.50 | blue 0.50 |
| 28 | Highlight 3 | orange 0.50 | orange 0.50 | orange 0.50 | orange 0.50 | orange 0.50 |
| 30–255 | Free | a 16×16 colour ramp, 0.18 | same | same | same | same |

Exact RGB values live in `graphics.py`; the table gives the intent.

### The pen-set editor (Graphics › Pen sets…)

- A set drop-down with New, Copy, Rename and Delete. At least one set must remain.
- A **16×16 grid** of swatches, numbered 1–255 like Archicad. Clicking a swatch shows its colour
  (button with a colour picker), weight (mm spin box) and name.
- OK applies; Cancel discards.

### The pen button (bottom bar)

The button shows the **current pen**: a swatch with its number and weight, e.g. "■ 23 · 0.18". Clicking
it opens the same 16×16 grid as a popup; picking a pen sets `current_pen`. New text, dimensions and
marks take the current pen. Default: 23.

## Line types

```json
"line_types": {"Solid": [], "Dashed": [3.0, 1.5], "Dotted": [0.3, 1.0], "Dash-dot": [4.0, 1.0, 0.5, 1.0],
               "Centre": [8.0, 1.5, 1.5, 1.5], "Hidden": [1.5, 1.0]}
```

- A line type is a list of dash and gap lengths in mm on paper. An empty list is solid.
- Lengths must be above 0, with an even count (dash, gap, dash, gap, …).
- **Editor (Graphics › Line types…):** a table of name and pattern ("3 1.5"), with a
  preview. Add, rename and delete. "Solid" can't be deleted.
- An unknown line type falls back to Solid.

## Element styles

```json
"element_styles": {
  "walls": {"cut": {"pen": 10, "line": "Solid"}, "projection": {"pen": 11, "line": "Solid"}, "fill": 12},
  ...
}
```

**Element kinds** (`graphics.KINDS`, in this order): walls, columns, beams, slabs, roofs, stairs,
railings, doors, windows, coverings, furniture, plumbing, hvac, electrical, structure_other, rooms,
annotations, grids, other.

**How an element gets its kind** (`graphics.kind_of(element)`), first match wins:

| Kind | IFC classes (and subclasses) |
|---|---|
| walls | IfcWall, IfcCurtainWall |
| columns | IfcColumn |
| beams | IfcBeam |
| slabs | IfcSlab |
| roofs | IfcRoof |
| stairs | IfcStair, IfcStairFlight, IfcRamp, IfcRampFlight |
| railings | IfcRailing |
| doors | IfcDoor |
| windows | IfcWindow |
| coverings | IfcCovering |
| furniture | IfcFurnishingElement (IfcFurniture, IfcSystemFurnitureElement) |
| plumbing | IfcPipeSegment, IfcPipeFitting, IfcSanitaryTerminal, IfcValve, IfcPump, IfcTank, IfcWasteTerminal, IfcFireSuppressionTerminal; in IFC2X3, an IfcFlow… element whose type is one of the matching …Type classes |
| hvac | IfcDuctSegment, IfcDuctFitting, IfcAirTerminal, IfcFan, IfcUnitaryEquipment, IfcCoil, IfcBoiler, IfcChiller, IfcDamper; in IFC2X3, by type as above |
| electrical | IfcCableSegment, IfcCableCarrierSegment, IfcCableFitting, IfcCableCarrierFitting, IfcLightFixture, IfcLamp, IfcOutlet, IfcSwitchingDevice, IfcElectricAppliance, IfcElectricDistributionBoard; in IFC2X3, by type as above |
| structure_other | IfcFooting, IfcPile, IfcMember, IfcPlate |
| rooms | IfcSpace |
| annotations | IfcAnnotation (not drawings) |
| grids | IfcGrid |
| other | anything else, including IfcBuildingElementProxy and any other IfcDistributionElement |

Defaults: walls 10/11/12; columns, beams, slabs, roofs and structure_other 13/14/15; doors and windows 16;
stairs and railings 17; furniture 18; plumbing 19; hvac 20; electrical 21; rooms 22 (line Dotted);
annotations 23; grids 24 (line Centre); coverings and other 25. Projection lines are Solid, except
rooms (Dotted) and grids (Centre).

**Editor (Graphics › Element styles…):** one row per kind. Columns: cut pen, cut line type,
projection pen, projection line type, fill pen. Pens are picked from the grid popup. "Reset to
defaults" restores the table.

## Visibility sets

```json
"visibility_sets": {"Everything": {"hidden_kinds": [], "rules": []},
                    "No furniture": {"hidden_kinds": ["furniture"], "rules": []}}
```

- `hidden_kinds` lists element kinds to hide.
- `rules` uses the override rule format (below). Every matching rule hides the element, whatever
  effect it names.
- **Built-ins:**
  - **Everything**
  - **Architectural:** hides plumbing, hvac and electrical.
  - **No furniture**
  - **Structure only:** hides doors, windows, furniture, plumbing, hvac, electrical, coverings,
    railings and rooms, plus a rule that hides elements whose `LoadBearing` property is false.
- **Editor (Graphics › Visibility sets…):** the set drop-down with New, Copy, Rename and
  Delete; a checklist of kinds; and a list of hide rules using the rule editor.

**Hidden by visibility** is a third kind of hidden, beside hidden by the user (H, isolate) and hidden by
a layer (D57). *Show all* doesn't reveal it, and hidden elements can't be selected. Drawings leave
hidden elements out of the hidden-line pass (the include list), so they don't hide what's behind them.

## Override sets

```json
"override_sets": {
  "Fire rating": {"rules": [
    {"name": "30 min", "when": {"property": "FireRating", "op": "equals", "value": "30"},
     "then": {"pen": 26, "surface": "#e05040"}}, ...]}
}
```

**Rule.** `{"name", "when", "then", "enabled": true}`. In each override set, **the first rule that matches
an element wins**.

**Conditions** (`when`): all keys given must match.

| Key | Matches |
|---|---|
| `kind` | the element kind (list or single) |
| `ifc_class` | `is_a()` of that class or a subclass |
| `property`, `op`, `value` | any property (in any property or quantity set) by name, or `Pset.Name`. Operators: `equals`, `not_equals`, `contains`, `exists`, `missing`, `true`, `false`, `less`, `more`. Values compare as text, case-insensitive, or as numbers for `less` and `more`. |
| `layer` | the element's presentation layer name |
| `material` | a material name the element uses (contains, case-insensitive) |

**Effects** (`then`): any of the following.

| Key | Effect |
|---|---|
| `pen` | the pen for cut and projection lines |
| `cut_pen`, `projection_pen` | the pen for one kind of line only |
| `line` | the line type for both kinds of line |
| `fill` | the pen for the cut fill |
| `surface` | `#rrggbb`, the 3D surface colour |
| `transparency` | 0–1 in 3D |
| `hide` | true hides the element |

**Built-ins:**
- **None:** no rules.
- **Fire rating:** FireRating contains "30", "60", "90" and "120", using pens 28, 27, 26 and 26 with
  matching surfaces.
- **Load-bearing walls:** walls with LoadBearing true get pen 26 and a red surface.
- **External walls:** walls with IsExternal true get pen 27 and a blue surface.
- **Highlight selection by layer:** a disabled example rule, layer = "A-Highlight", pen 26.

**Editor (Graphics › Overrides…):** the set drop-down with New, Copy, Rename and Delete. A
rule list with Up, Down, Add, Delete and an enabled tick. The rule form has the condition fields and
the effect fields, with pen pickers and a colour button.

## Layer combinations

```json
"layer_combinations": {"All visible": {"hidden": [], "locked": []}}
```

- **Editor (Graphics › Layer combinations…):** a set drop-down; a table of all layers with
  Shown and Locked ticks; "From current layers" copies the current layer states.
- Applying a combination sets `hidden_layers` and `locked_layers` (D72), as if each layer had been
  ticked by hand. Layer names not in the model are ignored.

## Purposes

```json
"purposes": {"Working": {"pen_set": "Working", "visibility": "Everything", "overrides": "None",
                         "layers": null}, ...},
"purpose": "Working"
```

- **Built-ins:**

| Purpose | Pen set | Visibility | Overrides |
|---|---|---|---|
| Working | Working | Everything | None |
| Highlight | Highlight | Everything | Fire rating |
| Permit | Permit | Architectural | None |
| Presentation | Presentation | No furniture | None |
| Demo | Demo | Everything | External walls |

  None of the built-ins sets a layer combination.

- **Purpose drop-down in the bottom bar**, left of the pen button. Picking a purpose:
  - restyles the 3D view, plan tabs, open drawings and sheets;
  - applies its layer combination, if it has one;
  - marks the settings changed (Ctrl+S saves them).
- **Graphics popup.** A small "…" button beside the drop-down opens a popup with four drop-downs: pen
  set, visibility, overrides and layer combination. They change the current purpose's pieces. If the
  current purpose is a built-in, a copy named "<name> (modified)" is made and selected first, so the
  built-ins stay as they are.
- **Editor (Graphics › Purposes…):** a list of purposes, each with the four drop-downs.
  New, Copy, Rename and Delete; one purpose must remain.
- **Saved views (D57)** gain a `purpose` field. Saving a view stores the current purpose; opening a view
  switches to it. Older views have no purpose and leave the current one unchanged.
- **Sheets:** right-clicking a sheet in the Sheets panel has a "Purpose" submenu: "Current" or a named
  purpose (ticked). It is stored in `sheet_purposes`. The sheet, its PDF and its SVG export are drawn with that purpose, so the
  permit set prints black while you work in colour.

## Where it shows

### Drawings and sheets (SVG and PDF)

- **Generation.** `drawgen` sets `svg-segment-projection` (projection lines grouped per element with
  `ifc:guid`) and `svg-no-css`. It writes no colours or weights: the SVG is geometry tagged by element.
  The overlay (door swings, window symbols, room stamps, annotations, markers) is tagged too, with
  `data-kind` and, for annotations, `ifc:guid`.
- **Styling** is a separate, cheap step (`graphics.style_svg(svg, resolved, k)`), run whenever a drawing
  is shown or placed on a sheet:
  - Cut groups get the stroke, width and dash pattern of their cut line, and the fill colour of their
    fill pen.
  - Projection groups get their projection line.
  - Weights and dashes are divided by `k`, the sheet's scaling of that view (`100 / scale`; 1 in a
    drawing tab), so **a 0.50 mm pen prints 0.50 mm at any scale**.
  - Hidden elements' groups are removed (they are also left out of generation).
  - Switching the pen set, line types or overrides only restyles. Changing visibility regenerates,
    because the hidden-line pass must not see hidden elements.
- The drawing cache keeps the unstyled SVG; the style step runs on every request (milliseconds).

### Plan tabs and the 3D view (OCCT)

- **Lines.** Each element's border lines use its projection pen colour and line type. Plan tabs' cut
  outlines use the cut pen. Line types map to OCCT line patterns (screen-space).
- **Weights.** The default is thin lines: 1 px, as today. **View › True line weights** (saved in the
  user preferences) draws `clamp(round(weight_mm × 4), 1, 6)` px.
- **Poché.** Plan-tab cut fills use each element's fill pen colour, not one dark grey.
- **Surfaces.** In 3D, surfaces keep the calm palette by IFC class (as today), unless an override sets
  `surface` or `transparency`. Compare's added and modified colours still win over everything.
- **Hidden by visibility** works as described under Visibility sets.
- **Annotations** use their pen (their own, or the annotations kind's pen) for lines and text.

### Annotations

`KIMBIM_Annotation` gains an optional `Pen` (integer). New annotations take `current_pen`. The
annotations kind's style is used when `Pen` is missing (older files, other tools).

## How it is built

| Unit | Responsibility |
|---|---|
| `python/kimbim/graphics.py` (new) | Built-ins; `effective(key)`; validation of the graphics keys; `kind_of(element)`; rule matching; `resolve(purpose=None, model=None)` → `{"styles": [...], "elements": {guid: style index}, "hidden": [guids]}`, cached by model state and settings; `style_svg(svg, resolved, k)`; bridge functions `graphics_state()`, `set_purpose(name)`, `set_current_pen(n)`, `graphics_tables()` and `set_graphics(json)` (editor writes, validated). |
| `settings.py` | DEFAULTS gains the new keys (empty means built-in); `_error` delegates the graphics keys to `graphics.validate`. |
| `drawgen.py` | Segment projection, no CSS, overlay tags. |
| `drawings.py`, `sheets.py` | Apply `style_svg` (k = 1 in a drawing tab, `100 / scale` on a sheet); the sheet purpose; regenerate when visibility changes (the include list already does this: hidden elements are not in it). |
| `layers.py` | Views store and return `purpose`. |
| `annotations.py` | The `Pen` field. |
| `app/src/Graphics.{h,cpp}` (new) | The C++ model of a resolved purpose: styles (colours, weights, line patterns, fill, surface, transparency), element → style, hidden set; parsed from `graphics_state`. Used by Scene and Viewport. |
| `ElementBatch` | Per-element style index and a "hidden by visibility" flag. Lines are drawn in one group per (colour, width, pattern); surfaces use the override colour. |
| `Viewport` | Section (poché) per fill colour and cut pen; annotations by pen. |
| `PenGrid` widget (new) | The 16×16 swatch grid, used by the pen button popup, the pen-set editor and pen pickers. |
| `GraphicsDialogs.{h,cpp}` (new) | Pen sets, line types, element styles, visibility sets, overrides, layer combinations and purposes editors. |
| `StatusStrip` | Purpose drop-down, graphics "…" popup, live pen button. |
| `MainWindow`, `SheetsPanel` | The Graphics menu (between View and Model) with the seven editors; View › True line weights; reloading graphics on open, purpose and settings change; the sheet's Purpose submenu. |

**Data flow.**
- A model opens or the settings change → C++ calls `graphics_state` → `Graphics` → Scene restyles its
  batches and views.
- A drawing tab or sheet asks Python for its SVG, already styled.

## Errors

- **Bad tables from an editor** are refused by `set_graphics`, with a plain message (e.g. "pen 300 is
  out of range (1–255)"), and nothing changes.
- **Bad data in a file** (another tool, a hand edit): unknown pens, line types or kinds fall back
  (black 0.18, Solid, "other"). A purpose naming a missing set uses the first set of that kind. Nothing
  fails to open.
- **A rule on a missing property** simply doesn't match.

## Performance

- **Resolution** reads properties only for rules that need them. It is cached on the model state and
  the settings.
- **Target:** the Clinic (3,258 elements) resolves in under 1 s with the Fire rating set, and in under
  0.2 s without property rules.
- **Restyling the 3D view** recomputes presentations without re-meshing.

## Testing

- **Python:**
  - Built-ins are valid, and `effective` works.
  - Validation refuses bad pens, weights, patterns and names.
  - `kind_of` on IFC4 and IFC2X3 classes, including IFC2X3 flow elements by type.
  - Rule operators, first-match order and visibility hide rules.
  - `resolve` on the house and on a small IFC2X3 model.
  - `style_svg`: weights divided by k, dashes, fills, hidden groups removed.
  - Drawings are styled through `generate_drawing` and `sheet_svg`; the sheet purpose; views keep
    their purpose; the annotation `Pen`.
  - Settings round-trip through a version and Combine.
- **C++:**
  - `Graphics` parsing and fallbacks.
  - ElementBatch draws one line group per style.
  - Hidden by visibility isn't selectable and survives Show all.
  - The pen button shows and sets the current pen.
  - Picking a purpose restyles and applies its layer combination.
  - Editors write only valid tables.
  - True line weights.
  - The sheet purpose drives the PDF.
- **Performance check:** resolving the Clinic with Fire rating is timed and recorded in doc 11.

## Build order

Built as one branch in three parts, each usable on its own:

- **3a:** pens, pen sets, line types, element styles, the pen button and annotation pens. Applied to
  drawings, sheets, plan tabs and 3D.
- **3b:** visibility sets and override sets.
- **3c:** layer combinations, purposes, the bottom-bar switch, the graphics popup, views and sheet
  purposes.

## Decision

D73 in [decisions](../../decisions.md) records this design once it is built.
