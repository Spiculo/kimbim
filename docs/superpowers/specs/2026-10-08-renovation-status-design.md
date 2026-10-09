# Renovation status, renovation filters and legends: design (BIM properties, part B)

Owner request, 2026-10-08: "we have properties but they do not show or affect the objects in the
layout". The owner chose three sub-projects, each with its own spec, plan and build:

- **B (this spec): properties drive appearance.** Renovation status and legends.
- **A: tags and labels.** Associative tags on plans and sheets.
- **C: properties drive geometry.** Parameters that rebuild elements.

Order: B → A → C. For B the owner picked Archicad-style renovation status over Revit phases. They
also picked a separate renovation filter that stacks with override rules (approach A), and a legend
both on screen and on sheets.

The owner then said: "use Archicad as default, Revit as fallback, design stuff around that; I'll check
with an architect". So the remaining choices below follow Archicad. Points for the architect to
confirm are listed in [open questions](../../open-questions.md).

This builds on D73 (pen sets, visibility sets, override sets, purposes; see its
[spec](2026-10-08-pen-sets-and-graphics-design.md)). Status is model data; filters are project
settings (D72), so both are versioned, merged by Combine and carried by office templates.

Out of scope:
- Revit phases (phase created/demolished, phase filters). Branches and design options (D56) already
  cover alternative states of the model.
- Archicad's "Show on renovation filter" (an element shown only in one filter).
- Legends for colour fills by property value (Revit colour schemes). Part A or later.
- Tags showing the status (part A).

## Renovation status (model data)

**Three statuses, as in Archicad:** *Existing*, *To be demolished*, *New*.

They are stored in IFC as the standard `Status` property, an `IfcPropertyEnumeratedValue` with IFC4's
`PEnum_ElementStatus`:

| KIMCAD | IFC `Status` written | Also read as this status |
|---|---|---|
| Existing | `EXISTING` | `Existing` (case-insensitive), Archicad's "Existing" |
| To be demolished | `DEMOLISH` | `DEMOLISHED`, "To Be Demolished" |
| New | `NEW` | `TEMPORARY`, `OTHER`, `NOTKNOWN`, `UNSET`, any other value, or none |

- **Where it is written.** The element's own `Pset_<Class>Common.Status` when the IFC4 (or IFC2X3)
  template for its class has `Status`. This covers walls, slabs, doors, windows, columns, beams,
  stairs, roofs, coverings, railings and proxies. For other classes (spaces, furniture, whose
  `Status` is only on the type, annotations, MEP), it goes in `KIMCAD_Renovation.Status`.
  An element's own value overrides its type's (D50 already behaves this way).
- **Where it is read.** Any pset's `Status` property, or `Renovation Status` (the name Archicad's IFC
  export uses), through the per-name property index in `graphics._property_index`. Own values win
  over type values. The index also learns to read `IfcPropertyEnumeratedValue` (the first
  enumeration value), because today it only reads single values and quantities.
- **No status means New** (Archicad's default for new elements). So:
  - an existing project looks unchanged under every built-in filter except *Existing plan*;
  - missing data never makes an element vanish from a *New plan*.
- **Writing `NEW` is explicit.** New elements are stamped with the status for new elements (see
  below), so the status survives export to tools with a different default.

## Renovation filters (project settings)

A new settings table, `renovation_filters`. As with the D73 tables, an empty table means the
built-ins, and the first edit writes the whole table. Each filter gives every status one of three
treatments:

```json
"Demolition plan": {
  "existing": {"show": "as_is"},
  "demolish": {"show": "override", "pen": 32, "line": "Dashed", "fill": 33, "surface": "#f0c020"},
  "new":      {"show": "hide"}
}
```

- **`as_is`**: drawn with its element style, as today.
- **`hide`**: hidden, in the same way a visibility set hides (see below).
- **`override`**: replaces any of `pen` (cut and projection), `cut_pen`, `projection_pen`, `line`,
  `fill` (cut fill pen), `surface` (3D colour) and `transparency`. Fields left out keep the element
  style.

Built-in filters follow Archicad's built-ins:

| Filter | Existing | To be demolished | New |
|---|---|---|---|
| **Everything** | as is | as is | as is |
| **Existing plan** | as is | as is | hide |
| **Demolition plan** | as is | override: pen 32 (demolition yellow), Dashed, fill pen 33, surface yellow | hide |
| **New plan** | override: pen 31 (grey), fill pen 31 | hide | as is |
| **Planned** | as is | hide | as is |

The built-in pen sets gain three named pens:
- **31**: existing, grey `#808080`, 0.18 mm;
- **32**: demolition, `#c09000`, 0.25 mm;
- **33**: demolition fill, light yellow `#f8e8a0`.

In the *Permit* set these are black, grey and white instead, because permit drawings print in
black and white. A project that has already written its pen sets keeps its own pens; a missing pen
falls back as D73 does (black 0.18).

**Purposes** gain `"renovation": "<filter name>"`. A missing or unknown name means *Everything*, so
current projects and templates look the same. Built-in purposes keep *Everything*, and three are
added:

- **Existing**: Permit pen set, Architectural visibility, no overrides, Existing plan filter.
- **Demolition**: the same, with the Demolition plan filter.
- **New construction**: the same, with the New plan filter.

## Resolution

`graphics.resolve` applies, for each element:

1. **Visibility**: hidden kinds and hide rules (as today).
2. **Renovation filter**: reads the element's status (one property-index lookup each for `Status`
   and `Renovation Status`, shared across the resolve). `hide` hides the element; `override`
   replaces the fields it sets.
3. **Override rules**: the first matching rule replaces the fields it sets, on top of step 2. So a
   *Fire rating* colour still shows on a demolished wall, and a rule's `hide` still hides.

- **Hidden by renovation** is the same "hidden by visibility" kind of hidden (D73). *Show all*
  doesn't reveal it, it can't be selected, and it is left out of drawings' hidden-line pass. The C++
  side needs no new state: these elements are in `hidden`.
- **The resolve output gains `legend`**, a list of entries for the active filter and override set.
  Only entries that applied to at least one element are listed:
  `{"label": "To be demolished", "source": "renovation"|"override", "style": <style index>}`.
  - Renovation entries come first, in the order Existing, To be demolished, New, and only for
    `override` treatments. The `as_is` entries are listed only when some other entry is shown, so the
    legend can say what plain lines mean.
  - Rule entries are labelled by the rule name.
  - The style is the element style of the first element that matched, after the entry's changes.
    It's a representative swatch, the way Archicad's and Revit's legends show one sample.
- **`renovation` and `status_for_new`** are added to the resolve cache key, through the settings
  keys `GRAPHICS_KEYS`.

## Setting the status

All edits are one undo step each, and model edits (versioned).

- **Properties panel.** A *Renovation status* drop-down (Existing / To be demolished / New) at the top,
  under Name. With several elements selected it shows "—" when the values differ, and picking a
  value sets every selected element (bulk edit, as Name does today). Bridge:
  `properties_multi` returns `"status": {"value", "varies"}`, and
  `renovation.set_status(guids_json, status)` writes it.
- **Model › Renovation status ▸ Existing / To be demolished / New** sets the selection's status
  (Archicad keeps renovation under a menu, Document › Renovation). The viewports have no context
  menu: right-drag navigates.
- **Status for new elements**, as in Archicad's *Renovation status for new elements*. A drop-down in
  the bottom bar sits left of the purpose drop-down and shows the three statuses; the default is
  **New**. It's stored in project settings (`status_for_new`), so it survives reopening and travels
  with the project.
  - Every creation path stamps it where it already calls `layers.assign_active(...)` (walls, slabs,
    doors/windows/openings, columns, beams, stairs, roofs, rooms). Annotations and drawing markers are
    not stamped: they are not building elements.
  - **Copies, mirrors, arrays and copy-to-level keep the source's status**, as they keep its layer
    (`layers.copy_layer` call sites).
  - **Hosted openings don't inherit their host's status.** A door or window placed in a wall to be
    demolished gets the status for new elements, as in Archicad. A door is only demolished when you
    mark it.

### Status on import (owner request, 2026-10-08)

A survey model from another tool usually has no statuses, so it would count as New, and *Existing
plan* would show almost nothing. So:

- **After an IFC is opened** (made into a new `.kim`, or edited directly; not when a `.kim` is
  reopened), if any building element has **no status at all**, the app asks: "*N* elements have no
  renovation status. Mark them as: **Existing** / **To be demolished** / **Leave them (they count as
  New)**". *Leave them* is the default button. A *Don't ask again* box sets the user preference
  `ask_import_status` to false. Quiet mode (tests, self-test) never asks.
- **Applied as one undoable edit** right after opening. The `.kim`'s first version stays the IFC
  exactly as it was (D72); the marking is the first change after it.
- **Model › Renovation status › Mark unmarked elements as… ▸ Existing / To be demolished** does the
  same at any time.
- **"Unmarked"** means no `Status` or `Renovation Status` value at all, own or from the type. An explicit
  `NEW` is marked and is left alone.
- Bridge: `renovation.unmarked()` returns `{"count", "guids"}`; `renovation.mark_unmarked(status)`
  writes them in one step.

## Editing filters

- **Graphics › Renovation filters…** is a dialog in the style of the D73 editors. It lists the filters
  (add, rename, duplicate, delete; built-ins can be edited, which writes the table). Each filter has
  three rows (Existing, To be demolished, New), each with *Show as is / Hide / Override*. *Override*
  enables the pen pickers (`PenGrid`) for line and fill, the line-type drop-down and a surface
  colour button.
  - Validation is in `graphics.validate("renovation_filters", ...)`: pens 1–255, line types are names,
    colours are `#rrggbb`, `show` is one of the three values, and only the three status keys are
    allowed.
- **The purpose editor and the bottom bar's graphics "…" popup** get a *Renovation filter*
  drop-down, next to visibility and overrides.

## Legends

**On screen.** The graphics "…" popup in the bottom bar gains a **Legend** section under the
drop-downs. It has one row per legend entry, each with a swatch (fill, line in its colour and dash)
and a label. It lists only what the current purpose actually changes in the model. When the purpose
changes nothing, it says "Everything is drawn with its element styles".

**On sheets** (Revit has legend views; Archicad legends are hand-drawn, so this follows Revit).

- **Sheets › right-click › Place legend** puts a legend on the sheet at a free spot, as
  `place_drawing` does. You can move it by dragging it like a placed drawing, and remove it from its
  context menu.
- It is drawn from the sheet's purpose (`sheet_purposes`, D73), so a *Demolition* sheet shows the
  demolition legend.
- **Content:** a title, *Legend*, then one row per entry: a swatch 10 × 5 mm (filled rectangle in the
  fill colour with an outline in the cut line), then the label at 3 mm text height. It is sized from
  its rows, at paper scale, unaffected by drawing scales. Weights print at their pen weight
  (k = 1).
  - Entries are computed against the elements of the drawings placed on that sheet, not the whole
    model. A legend for a ground-floor plan doesn't list a rule that only matched the roof.
  - If no drawing is placed, it uses the whole model.
- **Storage.** A legend is an `IfcDocumentReference` on the sheet, like a placed drawing, but with
  the location marker `kimcad:legend` and `{"x", "y"}` in the same data slot. IFC2X3 uses the same
  Location-marker fallback as placed drawings. Other tools see a reference they ignore. Legends are
  not drawings, so they have no scale and no title strip.
- `sheets()` returns `legends: [{id, x, y, w, h}]` per sheet. The id is the reference's
  `Identification`, a short generated id. `SheetsPanel` draws and drags them like views.

## How it is built

| Unit | Responsibility |
|---|---|
| `python/kimcad/renovation.py` (new) | Status names and IFC values; `status_of(element, facts)`; `write_status(element, status)` (Common pset with an enumerated value, or `KIMCAD_Renovation`); `stamp_new(*elements)`; `copy_status(source, target)`; bridge `set_status(guids_json, status)`, `set_status_for_new(status)`. |
| `graphics.py` | Built-in `renovation_filters`, the three new pens, the new purposes; `validate` for the table and the purposes' `renovation` field; enumerated values in `_property_index`; resolution step 2; `legend` in the output; `legend_svg(resolved, guids=None)`, the legend rows as SVG in mm. |
| `settings.py` | `renovation_filters` and `status_for_new` in DEFAULTS (empty / "new"); validation delegated. |
| `authoring.py`, `rooms.py`, `roofs.py` | Call `renovation.stamp_new` beside `layers.assign_active`, and `renovation.copy_status` beside `layers.copy_layer`. |
| `app_bridge.py` | `status` in `properties_multi`; exports `set_status`, `set_status_for_new`, `unmarked`, `mark_unmarked`. |
| `sheets.py` | Legend references: `place_legend`, `move_legend`, `remove_legend`; `legends` in `sheets()`; drawn in `sheet_svg` from the sheet's resolve, using the placed drawings' elements. |
| `drawings.py` | The elements a drawing shows (for the sheet legend). The include list it already builds is reused. |
| `PropertiesPanel` | The status drop-down. |
| `StatusStrip` | The *status for new elements* drop-down. |
| `Preferences` | `ask_import_status` (default true). |
| `MainWindow` | The Model › Renovation status submenu; Graphics › Renovation filters…; reloads graphics after a status edit, as after any model edit. |
| `GraphicsDialogs` / `PurposeDialogs` | The filter editor; the renovation drop-down in the purpose editor and the "…" popup; the legend section. |
| `SheetsPanel` | Place, draw, drag and remove legends. |
| `Translations` | Spanish for every new string. |

## Errors

- **Bad filter tables from the editor** are refused by `set_graphics` with a plain message, and
  nothing changes.
- **Unknown status values in a file** are read as New. A filter naming a missing pen or line type
  falls back as in D73.
- **Setting a status** on an element whose Common pset can't be written (another tool's odd data)
  falls back to `KIMCAD_Renovation`. If the write still fails, the whole action is rolled back, as
  other edits are, and the status bar shows the error.
- **A legend on a sheet whose purpose changes nothing** prints its title and the "Everything is drawn
  with its element styles" line, so it is never an empty box.

## Performance

- The status adds two property-index lookups per resolve; the D73 index made this cheap (Fire
  rating on the Clinic resolves in 0.2 s). Target: the Clinic resolves with *Demolition* in under
  0.5 s. This is measured and recorded in doc 11.
- A status edit changes the model, so it invalidates the resolve cache like any edit. Restyling stays
  a presentation update with no re-meshing (D73).

## Testing

- **Python:**
  - Status written to the Common pset (enumerated) or `KIMCAD_Renovation`, in IFC4 and IFC2X3.
  - Read back from either, from a type, from `Renovation Status`, and from odd values (as New).
  - Stamping on every creation path.
  - `unmarked` counts only elements without any status; `mark_unmarked` is one undo step and leaves
    explicit `NEW` alone.
  - Copies keep the status; hosted doors are New.
  - Built-in filters are valid, and validation refuses bad ones.
  - Resolution order: renovation hide, override fields, a rule on top, a rule hide.
  - Legend entries: only applied ones, order, labels, the `as_is` row.
  - `legend_svg`.
  - Sheet legends: place, move, remove, SVG content, entries limited to the placed drawings,
    IFC2X3 storage.
  - Undo and redo of a status edit.
  - Settings round-trip through a version and Combine.
- **C++:**
  - The Properties drop-down shows mixed values and sets them.
  - The Model › Renovation status menu sets them.
  - Opening an IFC with unmarked elements asks once (not in quiet mode, not with the preference off),
    and *Existing* marks them in one undo step.
  - The status-for-new drop-down stamps new walls.
  - The *Demolition* purpose hides new walls (not selectable, survive Show all).
  - The filter editor writes valid tables.
  - The legend section lists entries.
  - Sheet legends are drawn and dragged.
- **Exit check:** a test house with an existing wall, a demolished wall and a new wall exports one
  sheet per purpose (Existing, Demolition, New construction) with a legend, each showing the right
  walls. It runs in CI beside `pixi run m4`.

## Build order

One branch, in three parts that each work on their own:

- **B1:** status (`renovation.py`, stamping, copies, the Properties drop-down, the Model menu, status
  for new elements, status on import).
- **B2:** renovation filters, resolution, purposes, the editor, the popup drop-down.
- **B3:** legends on screen and on sheets; the exit check.

## Decision

Once this is built, it is recorded as D74 in [decisions](../../decisions.md).
