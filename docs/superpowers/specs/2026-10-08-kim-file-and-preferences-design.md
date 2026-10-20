# `.kim` file, preferences and templates — design (step 2 of 3)

Owner request, 2026-10-07: save and load user and project preferences, and a KimBim file format for
what a plain IFC can't hold. Step 1 (main window rework, D71) is merged. Step 3 (pen sets) comes next
and stores its sets in the project settings defined here.

Owner decisions (2026-10-07/08):

- A `.kim` is **one file holding the whole project**: the model, the project settings and the full
  version history. "Open as folder" works on the same content unpacked.
- The `.kim` is a **zip of the project folder** (not a Git bundle, not SQLite).
- **Settings travel in the history**: going back to a version brings back that version's settings.
- **One person edits at a time**: a lock beside the file; anyone else opens it read-only.
- **Ctrl+S saves the `.kim`** (no new version). "Save version…" adds a history entry. A preference can
  add automatic versions every N saves or N minutes.
- **Opening an `.ifc` makes a `.kim` beside it** by default; a preference edits the `.ifc` directly.
- **New views open as docked tabs** by default (next to the current tab, brought to the front); a
  preference opens them as free windows.
- **Templates** are `.kim` files without history in a templates folder (can be an office drive).
  File › New lists them; "Save as template…" makes one.

Out of scope: pen sets themselves (step 3, a reserved settings slot here), the plan-tab redesign (on
hold, [open questions](../../open-questions.md#for-the-architect-asked-2026-10-07-waiting)), several
models open together ([08](../../08-future.md#federation-and-linked-models)), two people editing one
`.kim` at once.

## What the architect sees

**File menu** (new or changed items in bold):

```
New project...            Ctrl+N   → template picker (skipped when only the built-in exists)
Open...                   Ctrl+O   → .kim or .ifc
**Open project folder...**
**Recent files              ▸**
Save                      Ctrl+S   → saves the .kim (or the .ifc in direct-IFC mode)
Save As...                Ctrl+Shift+S → a .kim
**Save as project folder...**
**Save as template...**
**Export IFC...**
Save version...           Ctrl+Alt+S
...
```

"Enable versioning…" goes away: every `.kim` has history. "Open project…" becomes "Open project
folder…".

**Edit › Preferences…** opens one dialog with the user preferences (below). **File › Project
settings…** opens the project settings. Both apply at once (OK/Cancel); the language takes effect at the
next start, and the dialog says so.

The window title shows the file name, `[read-only]` when someone else has it open, and `*` when unsaved.

## Where things live

### User preferences — per computer

A readable `preferences.json` in the user's settings folder (`QStandardPaths::AppConfigLocation`).
A missing, unreadable or garbled file means defaults (and the bad file is kept as
`preferences.json.bad` for inspection); unknown keys are kept on save, so an older KimBim doesn't drop
a newer one's settings.

| Key | Default | Meaning |
|-----|---------|---------|
| `language` | `auto` | `auto`, `en` or `es`; `--lang` still overrides |
| `layout` | — | the window layout (moved from `QSettings`; the old value is read once) |
| `recent` | `[]` | up to 10 recent `.kim`, `.ifc` and project folders |
| `templates_folder` | `Documents/KimBim Templates` | may point to an office drive |
| `author_name`, `author_email` | Git's `user.name`/`user.email`, else empty | the name on versions |
| `new_views` | `tab` | `tab` (docked next to the current tab, raised) or `window` (a free window) |
| `open_ifc` | `make_kim` | `make_kim` or `edit_ifc` |
| `auto_version` | `off` | `off`, `saves` or `minutes` |
| `auto_version_every` | `10` | N for `auto_version` |
| `recovery_minutes` | `5` | 0 turns the recovery copy off |

### Project settings — in the `.kim`, versioned

`settings.json` in each version's tree, beside the records (`kimbim.json` is the manifest; this is a
new tree entry, key `settings`). Its own record so Compare and Combine can see it.

| Key | Default | Used by |
|-----|---------|---------|
| `plan_cut_height` | `1.2` | the cut height a new view starts with (today 1.20 m, hard-coded) |
| `hidden_layers`, `locked_layers` | `[]` | layer states, restored on open (today they reset) |
| `drawing_scale` | `100` | the scale a drawing is placed at on a sheet (1:n) |
| `sheet_paper` | `A1` | the paper of a new sheet |
| `length_unit` | `m` | `m`, `cm` or `mm`, for new dimension labels and on-screen length readouts |
| `length_decimals` | `2` | decimals for the same |
| `pen_sets` | `{}` | reserved for step 3 |

Unknown keys are kept. Changing a setting marks the project unsaved; settings changes are not on the
undo stack (Ruling: they're preferences of the project, not model edits; cost if wrong: an undo entry
per change, added later). Existing dimension labels keep their text when the unit changes (they're
text in the IFC); only new ones and on-screen readouts follow.

In direct-IFC mode the project settings are the defaults and are not saved; the Project settings
dialog says "Save as .kim to keep these".

### Stays in the IFC, as today

Project info (number, name, client, address), levels, grids, sheets, drawings, layers and saved views.

## The `.kim` file

A zip. Its root holds the project folder exactly as it is unpacked:

```
House.kim
├── kimbim-file.json          {"format": "kim", "version": 1, "kind": "project"|"template", "app": "0.x"}
├── .git/                     the history (absent in a template)
├── .kimbim/working.ifc       the current work (what Ctrl+S saved)
└── .kimbim/settings.json     the current project settings (Ctrl+S state; versions hold their own)
```

- Git pack files are stored, not compressed again (they already are); everything else is deflated.
- Local caches (`.kimbim/cache`, `index.db`) are left out; they rebuild.
- A `version` higher than this KimBim knows is refused with "made by a newer KimBim".
- A `.kim` that isn't a valid zip or lacks `kimbim-file.json` is refused with a clear message; the file
  is never modified.

### Opening

1. **Lock.** `House.kim.lock` beside the file: `{"user", "machine", "pid", "since"}`.
   - No lock: create it, open for editing.
   - A lock from this user on this machine whose process is gone: a crash; take it over silently.
   - Any other lock: "Felipe has House.kim open on DESKTOP-1 since 10:42." → **Open read-only** /
     Cancel. Read-only means Save is disabled and Save As works (a new file).
2. **Unpack** to a working folder: `AppLocalDataLocation/open/<16-hex hash of the .kim's full path>/`,
   outside OneDrive so sync never fights the working files. An existing folder from the same file is
   reused only for recovery (below); otherwise it is cleared first.
3. **Open** `.kimbim/working.ifc` and `.kimbim/settings.json` as the model and project settings, on the
   current design option.

### Saving (Ctrl+S)

1. Write the model to `working.ifc` and the settings to `settings.json` in the working folder.
2. Zip the working folder to `House.kim.saving` beside the target, flush it, then replace `House.kim`
   with it in one step (`os.replace`). A crash or full disk mid-save leaves the old `.kim` untouched and
   a `.saving` file that the next save overwrites.
3. If automatic versions are on and due, save a version first ("Automatic version", the same as Save
   version… with that note) so it is in the zip.

### Save version… (Ctrl+Alt+S)

As today (D56), plus the settings: the commit writes the decomposed `working.ifc` records **and**
`settings.json`. Then a normal Ctrl+S, so the `.kim` holds the new version. A version whose model and
settings both match the last one is refused as today ("nothing to save").

### Closing

Unsaved work is guarded as today (save / discard / cancel). Then the lock is removed and the working
folder deleted.

### Recovery copy

Every `recovery_minutes` while there is unsaved work, the model and settings are written to
`AppLocalDataLocation/recovery/<hash>/` with the source path (`.kim`, `.ifc` or untitled). This works
in every mode. On the next start, a recovery copy newer than its source's last save is offered:
"KimBim closed unexpectedly. Recover your work on House.kim from 10:58?" → **Recover** / Discard. A
clean close or a save deletes the copy.

### Folder mode

"Open project folder…" opens an unpacked project folder in place (no zip, no copy): the lock is
`.kimbim/lock` inside it, Ctrl+S writes `working.ifc` and `settings.json` there, and versions go to its
`.git`. This is today's versioned project, so existing project folders open unchanged (a folder without
`settings.json` gets the defaults). "Save as project folder…" writes the open project out as a folder
(from a `.kim`: the unpacked content) and switches to it; "Save As…" from a folder writes a `.kim`.

### Opening an `.ifc`

With `open_ifc = make_kim` (default): opening `House.ifc` creates `House.kim` beside it with a first
version "Imported from House.ifc", locks it and opens it. The `.ifc` is never modified.

- `House.kim` already exists: "House.kim already exists next to House.ifc." → **Open House.kim** /
  **Make a new one** (`House (2).kim`) / Cancel.
- The folder isn't writable: Save As asks where to put the `.kim`.

With `open_ifc = edit_ifc`: today's plain mode — Save writes the `.ifc`, no history, default settings.

**Export IFC…** writes the current model as a plain `.ifc` in any mode.

## Templates

A template is a `.kim` with `"kind": "template"`, no `.git`, the model content (levels, grids, sheets
with title block, elevation markers…) and project settings. They live in `templates_folder`; KimBim's
own default template is built in (what "New project" makes today) and always listed first.

- **File › New project…** lists the built-in template and every `.kim` template in the folder (name and
  file date). Choosing one opens an untitled project with that content and settings. All GlobalIds are
  regenerated (Ruling: two projects from one template must not share element ids; cost if wrong: none
  known, ids carry no meaning across projects) and the project number and name are cleared. The first
  Ctrl+S asks where to save, creates the history and saves a first version "Created from
  \<template name\>".
- **File › Save as template…** asks for a name and writes `<templates_folder>/<name>.kim` from the open
  model and settings, without history. A name that exists asks to replace.
- A missing or unreachable templates folder lists only the built-in template, with a note.

## Compare and Combine

- **Compare** lists a settings change as one row, "Project settings", with the keys that changed.
- **Combine options** merges settings key by key against the common version: a key changed on one side
  takes that side; changed differently on both, the current option's value wins and the Combine dialog
  lists it as a resolved conflict (Ruling: settings conflicts are rare and cheap to redo; cost if wrong:
  a per-key choice UI later).

## New views: docked tab or free window

`new_views = tab`: a new plan, drawing or sheet tab is inserted right after the current tab and brought
to the front. `new_views = window`: it opens as a free window centred over the main window at 70 % of
its size; drag it into the tabs to dock it. Reopening a view that is already open just raises it, where
it is.

## How it is built

- **Python** (`python/kimbim/kimfile.py`): pack/unpack, the manifest, locks, the working folder,
  recovery copies, templates (write, list, instantiate with new GlobalIds). Project settings in
  `python/kimbim/settings.py`: defaults, get/set, read from and written to the working folder, committed
  with versions (`Project.commit(..., extra={"settings": bytes})`). Bridge functions follow the existing
  protocol (strings in, JSON out, never raise).
- **C++**: `Preferences` (load/save `preferences.json`, defaults, keep unknown keys) and a
  `PreferencesDialog`; a `ProjectSettingsDialog`; `MainWindow` file actions route through the bridge;
  `DockLayout::addView` takes "after the current tab" and "floating" placement.
- The author name/email from preferences is passed to the bridge, which uses it for commits (today it
  reads Git's config).

## Errors

Every failure leaves the user's files as they were and says what happened in plain words: a locked
file, a newer format, a damaged zip, a read-only folder, a full disk mid-save, a missing templates
folder. Nothing is silently dropped: an unreadable preferences file is kept aside, unknown keys in
preferences and settings survive a save.

## Testing

- Python: pack/unpack round trip (model, settings, history, options all survive); a save that fails
  mid-way leaves the old `.kim` intact; locks (free, stale from a dead process, held by another
  user → read-only); settings follow a version (save two versions with different cut heights, open the
  older one); Compare shows a settings row; Combine merges settings by key; templates (save, list,
  new project gets new GlobalIds and no history; a missing folder lists only the built-in); opening an
  `.ifc` makes the `.kim` beside it (and the "already exists" case); a newer `version` and a damaged zip
  are refused without touching the file; recovery copy written, offered and cleared.
- C++: `Preferences` defaults, round trip, garbled file kept aside, unknown keys kept; new views open
  after the current tab / floating per the preference; the File menu actions exist and Save in a `.kim`
  writes the file; layer states and cut height restored after reopening a `.kim`.
- Translations: Spanish for every new string; SPDX headers.

## Decision

D72 records this. It amends D56: Ctrl+S in a versioned project now saves the file, not a version.
