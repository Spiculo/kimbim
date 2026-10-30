<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 18 — Agent tools: full scope, parity and sessions

This is the reference for the agent side: what the agent can do today, what the user can do that it cannot, what to
add for full *user -> agent* parity, and how sessions should be stored. The day-to-day guide is
[17](17-agent-tools.md); the tool table there is generated from the catalogue and is the authoritative list.

## 1. What the agent has today

64 tools, all from one catalogue (`kimbim.agent.catalogue`), available over MCP, the `kimbim` CLI and the in-app
Assistant. Every write is one undo step; every change goes through a task and (by default) a reviewable design
option. `dry_run` reports without changing.

| Group | Tools | Covers |
|---|---|---|
| `project` | `info`, `settings`, `set_settings` | Read the project; settings are read, and the two agent settings are reserved to the owner |
| `versions` | `log`, `diff`, `options`, `milestones`, `element_history`, `export` | Read history and options, compare versions, export IFC |
| `task` | `start`, `finish`, `abandon`, `status` | The task/review protocol |
| `elements` | `find`, `get`, `set_dimensions`, `set_properties`, `remove_properties`, `rename`, `move`, `rotate`, `copy`, `copy_to_level`, `mirror`, `delete`, `set_layer`, `set_status`, `set_slab_slope`, `get_slab_slope` | Select and edit existing elements |
| `create` | `wall`, `slab`, `slab_edge`, `column`, `beam`, `curtain_wall`, `opening`, `room`, `types` | Basic construction and doors/windows |
| `levels` | `list`, `add`, `edit`, `delete` | The level table |
| `objects` | `library`, `versions`, `place`, `set_parameters`, `assign_version`, `update_from_library` | Library objects and their parameters |
| `drawings` | `list`, `create`, `export` | Plans, sections/elevations, SVG/DXF |
| `sheets` | `list`, `create`, `place_drawing`, `export` | Sheets, one placed drawing, PDF/SVG/DXF |
| `schedules` | `list`, `get`, `export` | Read and export schedules |
| `checks` | `run`, `ids_report` | Schema, IDS, clash and model checks |
| `selection` | `get`, `set` | Live selection only |
| `snapshot` | `take` | 3D, plan, section, elevation, drawing or sheet, with changes coloured |
| `script` | `run` | Python in the session, gated by the owner |

## 2. Parity: what the user can do that the agent cannot

The principle stays: **agents do not drive the GUI**. They use the same modelling and document operations the
GUI calls, so they never click, never depend on a screen, and never bypass review. Parity means a tool for the
*operation*, not for the widget.

The table below is the gap list for a full "what the user can do, the agent can do" promise. *Now* is a working
tool; *gap* is missing; *gated* is deliberate.

### Model and geometry

| User action | Agent today | Needed |
|---|---|---|
| Draw walls, slabs, columns, beams, curtain walls, doors/windows, rooms | yes | — |
| Wall settings: reference line, height, type, slant, double slant, top link, flip | partial (type/height on create) | `elements.set_wall_settings` (reference, slant, top link) and `walls.flip` |
| Complex profiles / profile manager | gap | `profiles.list`, `profiles.create_from_shape`, `walls.set_profile` |
| Split, trim/extend, join/unjoin, merge | gap | `elements.split`, `elements.trim`, `elements.join` |
| Move/rotate/copy/mirror/delete | yes | — |
| Array/multiply, offset, fillet/chamfer, resize, stretch | gap | `elements.array`, `elements.offset`, `elements.fillet`, `elements.resize`, `elements.stretch` |
| Slab outline, slab opening, slab edge | partial (slab edge; no opening/outline edit) | `elements.set_slab_outline`, `create.slab_opening` |
| Roofs, stairs, railings, ramps, slab openings | gap | `create.roof`, `create.stair`, `create.railing`, `create.slab_opening` |
| Grid lines, grid systems | gap | `create.grid`, `grids.create_system`, `grids.edit` |
| 2D drafting: line, polyline, spline, arc/circle, rectangle, fill, hatch | gap | `draft.*` with layer/pen and closed/open shapes |
| Text, dimensions, marks, leaders, tags, angle/radial/level dimensions | gap | `annotations.*` |
| Revision clouds, north arrows, scale bars | gap | `annotations.revision_cloud`, `annotations.north_arrow`, `annotations.scale_bar` |
| Object placements and parameters | yes | Placement settings (gravity, fit to walls) and object editor drafts |
| Rooms: name, number, area, boundary | partial (`create.room`, `set_properties`) | `rooms.set_boundary`, room tag tools |
| Materials, surfaces, composites | read-only through properties | `materials.list`, `materials.create`, `elements.assign_material`, `surfaces.*`, `composites.*` |
| Classifications, types, type manager | types read via `create.types`; no write | `classifications.*`, `types.create/edit/delete`, `types.assign` |
| Layers: create, rename, delete, visibility, lock, active | read/set element layer only | `layers.list/create/rename/delete/set_visible/set_locked` |
| Visibility sets, overrides, pen sets, purposes | gap | `graphics.*` (owner-level settings, probably gated) |
| Renovation status and filters | `elements.set_status` | `renovation.filters.*` |
| Groups, zones, spaces | gap | `groups.*`, `zones.*` |
| Library object editor, object drafts | library/place/parameters | `objects.create_draft`, `objects.save_version` |
| Place model, worksheets | gap | `models.place`, `worksheets.*` |
| Underlays, pictures in 3D | gap | `underlays.*`, `pictures.place` |
| Measure, snaps, trace reference | gap (no measurement tool) | `measure.distance/area` (read-only), `view.trace_reference` |

### Documents and output

| User action | Agent today | Needed |
|---|---|---|
| Drawing settings: path, bend/curve, tilt, base, depth, hidden-line mode | gap (only create/export) | `drawings.set_path`, `drawings.set_tilt`, `drawings.set_depth`, `drawings.regenerate` |
| Rename/delete drawings | gap | `drawings.rename`, `drawings.delete` (with the sheet warning) |
| Sheet data: title, number, paper, background | gap | `sheets.update` |
| Place/remove/move/scale drawings on a sheet | `place_drawing` only | `sheets.move_placement`, `sheets.set_placement_scale`, `sheets.remove_placement` |
| Title block: move and edit its fields | gap | `sheets.set_title_block` |
| Legends, north arrows, scale bars, revision clouds, sheet text, pictures | gap | `sheets.place_legend`, `sheets.place_symbol`, `sheets.set_symbol`, `sheets.remove_symbol` |
| Sheet purpose | gap | `sheets.set_purpose` |
| Export PDF/SVG/DXF/DWG | `drawings.export`, `sheets.export` (SVG/DXF/PDF?) | Explicit formats and `versions.export_dwg` |
| Schedules: create/edit schemes, place on sheets | read/export only | `schedules.create/edit`, `sheets.place_schedule` |
| Checks: choose checks, save IDS/clash sets | `checks.run`, `checks.ids_report` | `checks.save_ids`, `checks.clash_sets`, `checks.report` |
| BCF / issue export | gap | `issues.export_bcf` |

### Project, history and application

| User action | Agent today | Needed |
|---|---|---|
| New/open/save/save as, recovery | gap | `project.new/open/save` (gated: opening another file is owner-only) |
| Save a version, milestone, branch/option | task saves; no explicit version/milestone/option write | `versions.save`, `versions.milestone`, `options.create/delete/combine` (**gated**: agents never accept their own work) |
| Combine options / resolve conflicts | gap (owner only) | Review dialog already gives the owner the merge view; agents stay out |
| Remotes: fetch/push/clone | gap | `remotes.*` (gated, owner only) |
| Project settings | read; two reserved | `settings.set` for safe keys only |
| Undo/redo, selection sets, clipboard | gap | `history.undo/redo` (probably owner-only), `selection.sets`, `clipboard.*` |
| Saved views (camera, cut planes, section box, style) | gap | `views.list/save/apply`, `cuts.*` |
| Hide/isolate/show all, zoom, view modes | selection only | `view.hide/isolate/show_all/zoom`, `view.style` |
| Panels, dialogs, menus, drag and drop | out of scope | none: agents never drive the GUI |
| Preferences, API keys, scripts switch | out of scope | owner-only settings |
| Accept/reject proposals | out of scope | owner-only by design |

### The short list for "full control"

If the goal is the smallest set that lets an agent do almost anything an architect does, build these first:

1. **Editing operations**: split, trim/extend, join, array, offset, fillet/chamfer, resize, stretch, slab outline.
2. **Construction**: roof, stair, railing, grid/grid system, slab opening, wall settings and profiles.
3. **Drafting and annotations**: line/polyline/spline/arc/rectangle/fill, text, dimensions, marks, leaders, tags,
   revision cloud, north arrow, scale bar.
4. **Documentation**: drawing settings/rename/delete, sheet data/title block/placements/legends/symbols/purpose,
   schedule definitions, PDF/DWG export.
5. **Attributes and graphics**: materials, surfaces, composites, classifications, types, layers, renovation filters,
   visibility/overrides/pen sets (some gated).
6. **Project control**: save version/milestone, option create (not accept), saved views, cut planes, hide/isolate.
7. **Context and sessions**: the state delta described below, persistent sessions with branches/worktrees, and a
   session picker in the Assistant.

Gated (owner-only) by design: accepting/rejecting/combining an agent's work, deleting options, the agent settings
(`agent_changes`, `agent_scripts`), remotes/credentials, opening another project, and anything that changes the
review rules.

## 3. Project-change context

The Assistant now receives, every turn:

- the current option, whether it has unsaved changes, and its level count;
- its element counts by kind (walls, windows, doors, ...);
- the five most recent versions (id, message);
- a **delta since the previous turn**: option changes, a newer version, saved/discarded unsaved work, and each
  element kind whose count changed (for example `windows 12 -> 15`).

The prompt tells the model not to read its earlier answer as a mistake when the model changed, but to say what
changed and re-read with `elements.find`, `versions.diff` or `versions.log` when it needs detail. This is the
answer to "how many windows?" then "add some" then "how many now?": the second answer sees the delta and does not
call the first one wrong.

The same context is available to CLI/MCP agents through `project.info`, `versions.log` and `versions.diff`; the
Assistant simply gets it without spending a tool round on it.

Future: a `session.status` tool that returns the full `git status`-equivalent (working tree vs HEAD, untracked
drawings/tasks, recent commits), and an explicit event when another window or the owner edits the project.

## 4. Sessions

The Assistant conversation used to live in the panel's memory only, and the agent's task lived in the project's
task file. A **stored session** makes a conversation resumable and binds it to the branch/worktree it works on.
Built 2026-10-30 (D111): `kimbim.agent.sessions` is the store; `kimbim sessions …` lists and manages it; the
Assistant panel has the picker; `kimbim <group> <verb> --session ID` (or `$KIMBIM_SESSION`) runs a command in a
session; `kimbim mcp --session ID` does the same for MCP.

### Local store (app data, not the project)

```
<data dir>/agent/sessions/<session-id>/
  session.json        id, project path/hash, title, created/updated, provider/model, base option/version,
                      status (open, parked, ready, merged, rejected, archived), branch/worktree, task ids
  transcript.jsonl    append-only: user, assistant, tool call, tool result, progress/status, snapshot paths
  attachments/        snapshots or files the session refers to (optional, content-addressed)
```

- One session is one conversation and one task/design option (`agent/<slug>`); its task file stays in the project
  so it travels with the `.kim`. The transcript stays in app data, so it is not versioned with the model.
- The Assistant panel gets a **session picker** (new, resume, rename, archive, delete, fork). `Clear` starts a new
  session instead of losing the old one.
- Sessions are listed per project (path hash) and per user. A session can be resumed after the app restarts; its
  task is resumed from the task file.
- Writes from two sessions must not share a working tree: each session gets its own **worktree** of the project
  repository, under the data dir (not OneDrive), checked out on its branch. The app's project window stays on the
  owner's option; a session's worktree is opened by its background worker or the live host on demand. Built: the
  Rust `Repo::open_worktree` keeps a per-worktree `.kimbim/HEAD` over the project's object store, and a stored
  **folder** session gets `<data dir>/agent/worktrees/<project hash>/<session id>/`. A `.kim` or a plain IFC has
  nowhere to check out a second copy; those sessions record `worktree: ""` and use the D102 open/lock/worker path
  (one at a time). The Assistant routes a folder session's tool calls to its background worker, so the app's
  model and the session's worktree never touch; it saves the architect's unsaved work as "Before agent: <title>"
  on the live host first.
- Branches are the model equivalent of opencode sessions: one branch per session, the base option/version recorded,
  and accepting a proposal is the merge. A session's branch is `agent/<slug>` and stays stable when the title
  changes.
- Deleting a session deletes its transcript and worktree; its branch only when the owner also asks for that, so a
  proposal under review is never lost silently (a `ready` session needs an explicit confirmation).

### Remote (future, opt-in)

- The same `session.json` + `transcript.jsonl` shape, synced to a server; the model history goes through the Git
  remote (or a server-side repository), the transcript through the session API.
- The server stores session metadata and a content-addressed transcript; attachments by hash. Push/pull is explicit
  (no automatic upload of a project without the owner's opt-in).
- Remote sessions can be resumed on another machine when the project is cloned and the branch is fetched; the
  transcript identifies the branch and base version so the worktree can be recreated.
- Security: a transcript can contain project data, prompts and tool results. It is opt-in per project, encrypted at
  rest on the server, and never sent with a normal model call. Keys stay in the OS credential store.

### Session lifecycle

| State | Meaning |
|---|---|
| `open` | the conversation is active; its task/branch is open |
| `parked` | the worker/app closed; work-in-progress version saved on the branch |
| `ready` | the task finished; the proposal is waiting for review |
| `merged` | the owner accepted it; the branch is combined |
| `rejected` | the owner rejected it; the branch is deleted |
| `archived` | the conversation is kept but cannot write |

### What the store does

- `Store.create|all|get|rename|archive|restore|delete|fork`, `transcript`, `messages`, `record_tool`,
  `attachment` and `ensure_worktree`; `session.json` is written atomically and a damaged file is skipped, not fatal.
- The transcript is append-only JSONL: `user`, `assistant`, `tool` (compact summary, snapshot path),
  `tool_result` (the envelope, truncated) and `status`. Resume rebuilds the model history from the user/assistant
  text only; the tool lines stay in the panel. Attachments are content-addressed by SHA-256.
- A session's branch is `agent/<slug>` and is reused by its tasks and its worktree. `session.json` keeps its
  task ids, so accepting or rejecting a proposal ends the session (`merged`/`rejected`) and `session.for_task`
  finds it from the review bar.
- Deleting a session removes its transcript and worktree; a `ready` proposal refuses unless `confirm` is given,
  and the branch is only deleted with `branch` (the picker keeps it, because the review bar still needs it).
- The Assistant's `Clear` starts a new session; `New`, `Rename…`, `Fork`, `Archive` and `Delete…` are in the picker.
  A fork copies the transcript and starts clean on the base (no branch), for "try another answer".

### Limits (now)

- Worktree isolation is for **versioned folder** projects. A `.kim`/IFC session falls back to the shared
  open/lock path, so two of them cannot write at once; the app's live document is still the only model for those.
- The Assistant in a folder session gets the session's view (its worktree/base), not the architect's unsaved
  model; "Before agent" saves that unsaved work first, and the review bar shows the finished proposal.
- Remote sync, encryption and resuming on another machine are designed in *Remote (future, opt-in)* but not built.

## 5. Deliberate limits

- Agents never accept, combine or delete their own work, and never change the review rules.
- Agents never open another project, change credentials, or turn scripts on.
- Agents never drive menus, docks, dialogs or drag and drop; UI-only actions are either exposed as an operation
  tool or stay owner-only.
- A write always belongs to a task; a task always has a way back (a design option or a saved version).
