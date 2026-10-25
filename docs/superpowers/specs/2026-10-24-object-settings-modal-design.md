<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Object settings modal and saved versions — design

Date: 2026-10-24. Status: agreed with the owner in brainstorming; awaiting review of this document.
Builds on D99 part A ([doc 16](../../16-parametric-objects.md)), which is merged on `main`.

## Why

Today a library object's parameters are edited in two narrow places: an inline form in the Library
panel and the *Parameters* group in Properties. The owner wants customising an object, the chair being
the showcase, to happen in one roomy dialog where you can **see** the object while you change it, and
to keep the results as named, reusable versions ("Dining chair", "Bar stool") instead of re-entering
values each time.

The moment the owner described: *"I went to place it, and when I right-clicked on the chair it opened
a modal to customise it or select from the saved models I have already made; if I just click, it
places the last one I used."*

## Goals

1. A modal **Object settings** dialog (layout A below) with a live preview, used both to place and to
   edit placed objects.
2. **Saved versions**: named types in the project (the *project library*), listed in the dialog,
   placeable, editable, and shareable to the office library.
3. Fast placing: a click places the last version used; a **quick switcher** changes it without the
   dialog.
4. Editing a type changes every placed object of that type, with an explicit choice on save between
   *modify all* and *create a new type*.

## Non-goals

- The Object Editor (authoring new `.kimobj` files). That is D99 part B, still next.
- Two-way sync between a project's saved versions and the office library (changes flowing back).
- Putting the office library folder under version history. Saved versions in the project are tracked
  because they are IFC types inside the project, which the Git-backed store already versions.

## Anti-goals (a failure even if it works)

- The preview disagrees with what lands in the model (different geometry, materials or symbol).
- An edit silently changes objects the user didn't mean to touch, or silently doesn't change ones
  they did.
- A project that uses saved versions needs the office library to open or edit (D99 rule: projects
  stay self-contained).
- Typing in the dialog feels laggy, or a bad value throws the dialog away.

## Decided by the owner

- **Layout A**: three columns. Left: saved versions. Middle: big preview. Right: the controls.
  Buttons at the bottom right.
- **Clicks in the Library panel**: a normal click places the last version used of that object; a
  right click opens the dialog.
- **Quick switcher in both places**: a right click while the Object tool is placing lists that
  object's versions; the bottom tool options bar shows the current version as a dropdown while the
  Object tool is active. Both change what a plain click places.
- **The dialog is reused for edits** of placed objects.
- **Saved versions live in the project** as a project library and can be **moved to the office
  library** to share and reuse.
- **Editing a type changes every object of that type.** When saving an edit, the user is offered
  *Confirm: modify all N objects of this type* or *Create a new type*.
- **Tracking means git**: saved versions are part of the project's history (nothing extra for the
  office library).

## The design

### The dialog

```
┌ Chair — settings ─────────────────────────────────────────────────────────┐
│ Saved        │                                   │ Size                   │
│ ▸ Default    │                                   │  Width   450           │
│   Dining     │          3D preview               │  Depth   500           │
│   Bar stool  │       (orbit with the mouse)      │  Height  850           │
│   ─ Office ─ │                                   │ Legs                   │
│   Café       │                                   │  Layout  [corners ▾]   │
│              │                                   │  Style   [square  ▾]   │
│ Save as…     │          [ 3D ] [ Plan ]          │  ...                   │
│              │                                   │ Back / Arms / Materials│
│                                                  [ Cancel ] [ Place ]    │
└───────────────────────────────────────────────────────────────────────────┘
```

- **Left column, saved versions**: *Default* (the object as its definition ships) first, then the
  project's named versions of this object, then a separate *Office* section with the office
  library's versions of it. Choosing one loads its values into the controls and the preview.
  *Save as…* names the current values as a new project version. A right click on a project version
  offers Rename, Delete and *Move to library*. (Rename, Delete and the right-click menu are my call.)
- **Middle, preview**: drawn by the app's own 3D rendering, so it matches the model exactly,
  materials included. Orbit with the mouse; a *3D / Plan* toggle shows the plan symbol. It updates
  shortly after each change (my call: debounced, aim for under ~300 ms for the chair).
- **Right, controls**: one control per parameter kind as the Library panel has today (lengths,
  angles, counts, on/off, choices, materials), grouped under the definition's `group` headings, with
  `show_when` hiding controls that don't apply. Labels in English or Spanish per the UI language.
- **A value that breaks the object**: the field turns red with the reason, the preview keeps the
  last good shape, and Place / Apply is disabled until it's fixed (my call).
- **Buttons**: *Cancel* and *Place* when opened from the Library panel; *Cancel* and *Apply* when
  opened to edit placed objects.
- **Office IFC types** (types with fixed geometry, no parameters): a right click opens the dialog
  with the preview and no controls and no *Save as…* (my call).

### Placing

- A click on an object in the Library panel starts the Object tool with that object's **current
  version**: the last one used, or *Default* if none yet. The panel shows it next to the name
  ("Chair · Dining") so the user knows what a click places (my call).
- *Place* in the dialog starts the Object tool with the chosen version, or with the current
  unsaved values if the user changed things without saving. Unsaved values place as an unnamed type
  as today (one type per value set, D99).
- The last version used is remembered **per object, per project** (my call; stored with the
  project's settings). It is whatever was last placed, including unsaved values: those show as
  "Custom" in the panel, the quick switcher and the *Version* dropdown, and are replaced by the next
  placement. Editing placed objects does not change it (my call).
- While placing, a right click opens the quick switcher instead of ending the tool; Esc ends the
  tool (builder to keep this consistent with the other tools).
- **Quick switcher**: while the Object tool is active, a right click in the view opens a menu of the
  object's versions (project and office) plus *Settings…* to open the dialog. The tool options bar
  shows a *Version* dropdown with the same list. Choosing one switches what the next click places.

### Saved versions are named types

- A saved version is an IFC type in the project, the same kind of type D99 already makes for each
  value set, with a user name and a marker that it is saved. It **stays in the project even when no
  object uses it**; unnamed types keep today's rule (removed when unused).
- Placing a saved version uses that type, so schedules count all "Dining chair" placements together.
- **Named versions have their own identity** (owner): a type is a saved version by its id, not by
  its values.
  - Unsaved values never join a named version, even when they are identical; they use an unnamed
    type, found or made by values as today.
  - Two saved versions may have identical values and stay separate types, counted separately in
    schedules.
  - *Modify all* regenerates the type in place and never merges it into another type, named or not.
    Today's "move everyone to an existing type with these values" applies only between unnamed types.
- Names are unique per object within the project; *Save as…* with an existing name asks to replace
  or rename (my call).
- Delete is allowed only for a version nothing uses; otherwise the menu says how many objects use it
  (my call).
- **Moving to the office library** copies the version into the office library, where every project
  sees it in the dialog's *Office* section. The project keeps its own copy, so it never depends on
  the office library. Placing an office version copies it into the project as a project version
  (once; later placements reuse it). If no office folder is set, *Move to library* is disabled with
  a hint pointing at Preferences › Office library.
- The office copy carries everything needed to rebuild it: the object reference, the parameter
  values and the definition text with its hash (as D99 types already do).
- **Identity of a version** (my call): every saved version has a stable version id (kept when it is
  renamed, edited or moved to the library). A project copy of an office version keeps the office
  version's id, which is how it is found again (later placements reuse it) and how the dialog avoids
  listing it twice: a version present in both shows once, in the project section, marked as from the
  office. If the project already has a different version with the same name, the copy is named
  "Café (office)".
- **Updates** (my call, the D99 rule "never silently, always offered"): *Update from library* works
  per type as well as per element.
  - A project version is outdated when its object's live definition (bundled or office `.kimobj`)
    has a different hash, or, for a copy of an office version, when the office version's values or
    definition differ from the copy's.
  - Outdated saved versions are listed even when nothing uses them, and are regenerated **in place**,
    keeping their name, id and GlobalId; every placement follows.
  - Nothing flows from the project back to the office except an explicit *Move to library*, which
    asks before replacing an office version with the same id or name.

### Editing placed objects

- **Properties**: the *Parameters* group becomes a short read-only summary (the type name and a few
  values) with an **Edit…** button that opens the dialog in edit mode. The inline parameter editors
  in Properties go. Edit is disabled when the selection holds objects of more than one type.
- **Edit mode** opens on the selected objects' type, highlighted in the versions list.
  - Changing values and pressing *Apply*:
    - if the type is used only by the selected objects, apply directly;
    - otherwise ask: **Confirm: modify all N objects of this type** (the type changes in place and
      every placement follows) or **Create a new type** (asks for a name; only the selected objects
      move to the new type).
  - Choosing a different version in the list and pressing *Apply* moves the selected objects to that
    version's type.
  - Each *Apply* is one undo step.
- Today's selection-versus-type behaviour (`set_object_parameter` with `scope`, D92) is the
  mechanism; the dialog makes the choice explicit instead of inferring it.

### The Library panel

The inline parameter form goes. The panel keeps categories, search, thumbnails and the office
library buttons; a click places, a right click opens the dialog, and each entry shows its current
version.

## Constraints

- KimBim: C++/Qt app over the Python `kimbim` package; library logic lives in
  `python/kimbim/library.py` and the bridge in `app_bridge.py`. UI strings in English and Spanish
  (`app/translations/kimbim_es.ts`).
- Types and placements follow D86/D99 storage: one IFC type per value set, `KIMBIM_LibraryObject`
  pset with the definition, its uses and hash; IFC4 and IFC2X3.
- Projects must open and edit without the office library.
- No backward compatibility shims: the project is unreleased; old inline forms and Properties
  editors are removed outright.
- New decision recorded as **D100** in `docs/decisions.md`; doc 16 and doc 14 updated.

## Left to the builder

- How the preview reuses the 3D view (a second `Viewport` with its own scene, an offscreen render,
  or similar), as long as it matches the model's rendering.
- The exact pset fields for the saved-version name and marker, and where the per-project "last
  used" lives in the project settings.
- The office file format for shared versions (e.g. a KimBim-managed IFC file of types in the office
  folder, read like the office IFC types but kept parametric), provided it carries the definition
  and stays readable by `load_office`.
- Dialog sizing, keyboard focus and shortcuts, and how the summary in Properties picks its values.
