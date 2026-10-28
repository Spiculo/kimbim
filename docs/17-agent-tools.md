<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 17 — Agent tools: the `kimbim` command line and MCP server

An AI agent (Claude, opencode, or any program that speaks MCP) can read, picture and change a KimBim project for
you. You ask *"make every window on the first floor 50 cm wider"*, the agent does it in seconds, and you review the
result in KimBim before anything reaches your model (decision D102,
[spec](superpowers/specs/2026-10-25-agent-tools-design.md)).

The same set of tools is available three ways:

- **`kimbim mcp`**, an MCP server. Claude Desktop, Claude Code and opencode connect to it and see the tools.
- **`kimbim`**, a command line, for agents that run shell commands and for you. `kimbim elements find --elements
  '{"kind": "window"}'` is the same call as the MCP tool `elements_find`.
- **The Assistant panel** inside the app (View › Panels › Assistant), using your own model provider and API key.

Agents work **live**, while the project is open in KimBim, or **offline**, with the app closed. In live mode the
app hosts a local session: each write is one undo step, the views redraw, and a review bar lists finished agent
proposals. In offline mode a background worker keeps the project open between commands.

## What an agent can do

- **Read** the project: levels, element counts, settings, any element's type, dimensions, properties, host and
  openings, the drawings, sheets and schedules, the saved versions and design options.
- **Look** at it: a picture of the model in 3D, a floor plan, a section or elevation, any drawing or a sheet, drawn
  by KimBim itself, so it looks like what you see in the app. The picture can colour what the agent changed.
- **Change** it: resize doors and windows, move, rotate, copy, mirror, rename and delete elements, set properties,
  layers and renovation status, add walls, slabs, columns, beams, doors, windows and rooms, place and adjust library
  objects, add levels, drawings and sheets.
- **Produce** outputs: export drawings (SVG, DXF), sheets (PDF, SVG, DXF), schedules (CSV) and versions (IFC), and
  run the model checks (schema, IDS, clash, model).

Agents never click in the app and never see your screen. Everything goes through these tools.

## Connecting an agent

`kimbim setup` writes the agent's configuration for you. It merges its entry into the existing file and keeps your
other servers and settings. In development, run it as `pixi run kimbim ...`.

| Agent | Command | What it writes |
|-------|---------|----------------|
| Claude Desktop | `kimbim setup claude-desktop` | `claude_desktop_config.json` (in `%APPDATA%\Claude` on Windows) |
| Claude Code | `kimbim setup claude-code --project house.kim` | `.mcp.json` and a short KimBim section in `CLAUDE.md`, in the project's folder |
| opencode | `kimbim setup opencode --project house.kim` | `opencode.json` and a short KimBim section in `AGENTS.md`, in the project's folder |

- With `--project`, the server always works on that project. Without it, the agent names the project in every call.
- `--print` shows the configuration instead of writing it. For Claude Code it prints the `claude mcp add` line.
- The section in `CLAUDE.md` or `AGENTS.md` tells the agent that the `kimbim` command line exists and how to use
  tasks. It sits between `<!-- kimbim:start -->` and `<!-- kimbim:end -->`, and running setup again replaces it
  instead of adding a second copy. Your own text in the file is kept.
- Restart the agent (or reload its MCP servers) after running setup.
- In the app, *Help › Connect an AI agent...* shows the same configuration with a Copy button.

The app starts its live server when a project finishes loading. While it runs, the status bar shows
*Agent: live* with a *Disconnect* button; disconnecting stops accepting commands for that window. The server is
not started for the windowless snapshot helper.

## Tasks and review

Every change an agent makes belongs to a **task**, such as *"Widen first-floor windows"*.

1. The agent starts the task (`task_start` with a title). KimBim creates a **design option** named
   `agent/widen-first-floor-windows` from your latest version. If your project has unsaved changes, KimBim first
   saves them as a version called *Before agent: Widen first-floor windows*, so the agent starts from what you see.
2. The agent makes its changes. They go into the option, never into your option.
3. The agent finishes the task (`task_finish` with a summary). The option gets one new version, authored by
   *"<agent> (agent)"*, with the title and the summary as its message. The task is now *ready for review*.

A write tool called without a task starts one on its own, so nothing skips review.

**Reviewing.** The app lists finished proposals in a bar above the views: *"Agent proposal: Widen first-floor
windows (4 changed)"* with **Review**, **Accept** and **Reject**.

| To | Do this |
|----|---------|
| See the proposal | **Review** switches to the `agent/...` option and compares it with the version the task started from; Compare colours what changed (added, modified, removed) |
| Accept it | **Accept** combines the option into its base option, saves the combined version and deletes the agent option. If both sides changed the same property, the existing Combine dialog asks which value to keep |
| Reject it | **Reject** deletes the agent option and leaves your model unchanged |

The same review works offline: open the project and the proposal appears. You can also use *Versions › Design
options*, *Combine options...* and *Delete option...* by hand. Agents cannot accept, combine or delete options, and
they cannot change the review rules below.

Compare reports only the elements whose content changed (since the fix of 2026-10-26, see
[03](03-versioning.md#diff-compare)). Widening four windows shows those four windows and their wall openings, not
every element that shares a placement with them.

## Settings only you can change

Two project settings decide how much freedom agents have. Agents can read them, but `project_set_settings` refuses
to change them.

| Setting | Values | Default |
|---------|--------|---------|
| `agent_changes` | `option`: changes go into a design option for review. `direct`: changes go straight into your model, and finishing the task saves them as a version *"<title> (agent)"*, so the version before it is your way back. `agent_decides`: the agent picks per task, option unless it asks for direct | `option` |
| `agent_scripts` | `true` lets agents run Python scripts in the project (`script_run`), like the [console](15-scripting.md) | `false` |

There is no dialog for them yet. Set them in the Python console, then save the project (Ctrl+S):

```python
import kimbim.settings
kimbim.settings.set_project_settings('{"agent_scripts": true}')
```

## Snapshots

`snapshot_take` returns a picture (PNG) to the agent, and the file's path. Over MCP the picture is part of the
answer, so the agent sees it right away. Every field is optional:

| Field | What it does | Default |
|-------|--------------|---------|
| `view` | `3d`, `plan`, `section`, `elevation`, `drawing` or `sheet` | `3d` |
| `level`, `drawing`, `sheet` | Which plan, drawing or sheet | The lowest level, the first drawing or sheet |
| `elements`, `isolate`, `highlight` | Frame on some elements, show only them, or draw some in a highlight colour | The whole model |
| `changes` | `task` colours what the open task changed, like Compare. `{rev_a, rev_b}` compares two versions | None |
| `camera`, `style`, `purpose`, `cut` | 3D camera (a view cube preset or eye and target), style (`shaded`, `white`, `lines`, `textured`), pen set, horizontal cut height | `iso-se` framed on the target, `shaded`, the project's pen set, no cut |
| `size` | Picture size in pixels | 1024 × 768 |
| `format` | `png`, or `svg` for drawings and sheets | `png` |

3D pictures come from the app's own renderer, started without a window. Plans, sections, elevations and sheets
come from the same drawing generator as the *Drawings* tab. The first 3D picture of a session takes a few seconds
longer while the renderer starts. An SVG snapshot is returned as text, not as an image, because many MCP clients do
not display `image/svg+xml`.

## The Assistant panel

*View › Panels › Assistant* docks a chat with the model. It uses the same tools and the same live session as an
external agent, so its changes are undo steps and its tasks appear in the review bar.

Set the provider in *Edit › Preferences › Assistant*: **Anthropic**, or **OpenAI-compatible** (a base URL and a
model name, which covers OpenRouter, DeepSeek, Ollama and similar). The API key is stored in the operating system's
credential store, never in `preferences.json` or the project. The panel sends the current selection and view as
context; tool calls appear as compact lines and snapshots inline. *Clear* forgets the conversation; history is per
window and is not saved in the project.

## The tools

Tools are named `group_verb` over MCP and `kimbim group verb` on the command line (underscores become hyphens).
`kimbim <group> <verb> --help` lists a tool's parameters. Every write tool also takes `dry_run`: it reports what
would change and changes nothing. This table is the output of `kimbim help --markdown`.

<!-- tools:start -->
| Tool (MCP) | Command line | What it does | Changes the model |
|---|---|---|---|
| `project_info` | `kimbim project info` | Describe the open project: name, schema, levels, element counts per kind, the current option and whether there are unsaved changes. |  |
| `project_set_settings` | `kimbim project set-settings` | Change project settings (units, decimals, display options...) as one undo step. | yes |
| `project_settings` | `kimbim project settings` | Read the project settings (units, decimals, display options...), all or just the named keys. |  |
| `versions_diff` | `kimbim versions diff` | Compare two versions: the elements added, modified and removed from one to the other (WORKING is the open model with its unsaved changes). |  |
| `versions_element_history` | `kimbim versions element-history` | List the saved versions that changed an element, newest first. |  |
| `versions_export` | `kimbim versions export` | Write a version of the model as an IFC file (HEAD, the latest saved one, by default). |  |
| `versions_log` | `kimbim versions log` | List the saved versions of the current option, newest first: id, message, author, time, milestones. |  |
| `versions_milestones` | `kimbim versions milestones` | List the milestones (named versions such as Concept or Schematic design). |  |
| `versions_options` | `kimbim versions options` | List the design options of the project and the current one. |  |
| `task_abandon` | `kimbim task abandon` | Abandon the task: its changes are thrown away (its design option is deleted). |  |
| `task_finish` | `kimbim task finish` | Finish the task: save its changes as a version (on its option, ready for review, or in place in direct mode) and return what changed. |  |
| `task_start` | `kimbim task start` | Start a task: the changes that follow go in a design option agent/<title> for the architect to review (or straight into the model in direct mode). |  |
| `task_status` | `kimbim task status` | Show the open task (or the named one) with what it changed so far, and every task of the project. |  |
| `elements_copy` | `kimbim elements copy` | Copy elements, shifted by dx, dy, dz, optionally onto another level. | yes |
| `elements_copy_to_level` | `kimbim elements copy-to-level` | Copy elements to another level at the same plan position (walls bring their doors and windows). | yes |
| `elements_delete` | `kimbim elements delete` | Delete elements (and the doors/windows they host). | yes |
| `elements_find` | `kimbim elements find` | Find elements and list them: GlobalId, label, kind and level, a page at a time. |  |
| `elements_get` | `kimbim elements get` | Describe elements in full: class, type, level, dimensions (metres), property sets, host and openings. |  |
| `elements_mirror` | `kimbim elements mirror` | Mirror elements across a line on the plan. | yes |
| `elements_move` | `kimbim elements move` | Move elements by dx, dy, dz. | yes |
| `elements_remove_properties` | `kimbim elements remove-properties` | Remove properties from elements. | yes |
| `elements_rename` | `kimbim elements rename` | Give elements a name. | yes |
| `elements_rotate` | `kimbim elements rotate` | Rotate elements around a point on the plan; joined walls follow. | yes |
| `elements_set_dimensions` | `kimbim elements set-dimensions` | Change dimensions of elements: width, height and sill of doors/windows, height or length of walls, columns and beams. | yes |
| `elements_set_layer` | `kimbim elements set-layer` | Move elements to a layer. | yes |
| `elements_set_properties` | `kimbim elements set-properties` | Set property values on elements, creating the property set when needed. | yes |
| `elements_set_status` | `kimbim elements set-status` | Set the renovation status of elements: existing, demolish, new, temporary or auxiliary. | yes |
| `create_beam` | `kimbim create beam` | Create a beam between two points on a level. | yes |
| `create_column` | `kimbim create column` | Create a column standing on a level. | yes |
| `create_opening` | `kimbim create opening` | Put a door or window in a wall. | yes |
| `create_room` | `kimbim create room` | Create a room filling the walled-in space around a point. | yes |
| `create_slab` | `kimbim create slab` | Create a slab on a level from an outline or from a closed loop of walls (the outline follows their outer faces). | yes |
| `create_types` | `kimbim create types` | List the types you can create of a kind: GlobalId, name and size (wall thickness, default door/window sizes). |  |
| `create_wall` | `kimbim create wall` | Create a straight wall on a level. | yes |
| `objects_assign_version` | `kimbim objects assign-version` | Move placed library objects to a saved version. | yes |
| `objects_library` | `kimbim objects library` | List the library objects (furniture, sanitary, kitchen...): id, name, category, IFC class, size (metres) and parameters with their kind, default and limits. |  |
| `objects_place` | `kimbim objects place` | Place a library object on a level. | yes |
| `objects_set_parameters` | `kimbim objects set-parameters` | Change parameters of placed library objects. | yes |
| `objects_update_from_library` | `kimbim objects update-from-library` | Regenerate placed objects from the library's current definition (all of them when no elements are given). | yes |
| `objects_versions` | `kimbim objects versions` | List the saved versions of a library object (the project's and the office's) and its default values. |  |
| `drawings_create` | `kimbim drawings create` | Create a drawing. | yes |
| `drawings_export` | `kimbim drawings export` | Export a drawing as SVG or DXF (pdf: put it on a sheet and use sheets.export). |  |
| `drawings_list` | `kimbim drawings list` | List the project's drawings: floor plans, sections and elevations with GlobalId, name, kind and level. |  |
| `sheets_create` | `kimbim sheets create` | Create an empty sheet; it gets the next number (A01, A02...). | yes |
| `sheets_export` | `kimbim sheets export` | Export a sheet as PDF, SVG or DXF. |  |
| `sheets_list` | `kimbim sheets list` | List the sheets: number, title, paper size and the drawings placed on each. |  |
| `sheets_place_drawing` | `kimbim sheets place-drawing` | Put a drawing on a sheet at a scale (1:100 by default). | yes |
| `schedules_export` | `kimbim schedules export` | Export a schedule as a CSV file. |  |
| `schedules_get` | `kimbim schedules get` | Compute a schedule: its columns, rows (with the GlobalIds each row stands for), totals and count. |  |
| `schedules_list` | `kimbim schedules list` | List the schedules (door, window, wall... tables) with the classes and fields of each. |  |
| `checks_ids_report` | `kimbim checks ids-report` | Write the report of the last IDS check as a file. |  |
| `checks_run` | `kimbim checks run` | Run model checks: schema (IFC validation), ids (information requirements), clash (collisions) and model (duplicates, rooms, zero-length walls...). |  |
| `levels_add` | `kimbim levels add` | Add a level at an elevation. | yes |
| `levels_delete` | `kimbim levels delete` | Delete a level. | yes |
| `levels_edit` | `kimbim levels edit` | Rename a level or move it to a new elevation. | yes |
| `levels_list` | `kimbim levels list` | List the levels from the lowest: GlobalId, name, elevation, height to the next level and element count. |  |
| `selection_get` | `kimbim selection get` | Read the app's current selection. |  |
| `selection_set` | `kimbim selection set` | Select elements in the app's window. |  |
| `script_run` | `kimbim script run` | Run a Python script in the project's console (the model is `ifc`, KimBim commands are in `bridge`). | yes |
| `snapshot_take` | `kimbim snapshot take` | Take a picture of the model to check your work: a 3D view (optionally framed on elements, with what your task changed coloured as the app's Compare shows it), a floor plan, a section or elevation, any drawing, or a sheet. |  |
<!-- tools:end -->

Every answer has the same shape: `{"ok": true, "result": ..., "changes": ..., "warnings": [...]}`, or
`{"ok": false, "error": {"code", "message", "hint"}}`. The `code` is in English; the message and the hint follow
the app's language (English or Spanish). On the command line the answer is a one-line summary, or the full JSON with
`--json`. Exit code 0 means it worked, 1 a tool error, 2 a mistake in the command.

## Commands for people

These commands are on the command line only. Agents don't get them.

| Command | What it does |
|---------|--------------|
| `kimbim project init [DIR]` | Makes a folder a KimBim project |
| `kimbim versions save [FILE.ifc] -m MESSAGE` | Saves a version: of an IFC file, or of the project's working model |
| `kimbim versions status FILE.ifc` | What saving that IFC file would change |
| `kimbim versions branch [NAME]`, `switch NAME` | Lists or creates design options, switches to one |
| `kimbim versions tag [NAME] [-m NOTE] [--delete]` | Lists, sets or deletes milestones |
| `kimbim versions merge OPTION [--resolve ID=CHOICE]` | Combines another option into the current one |
| `kimbim versions show KEY [--rev REV]` | Prints one stored record |
| `kimbim versions export-dxf OUT` | Writes a version's drawings and sheets as DXF |
| `kimbim script run FILE [MODEL.ifc]` | Runs a Python script on an IFC file (a batch job), or on the project as the agent tool does |
| `kimbim serve PROJECT` | Keeps a project open for agent commands (started for you when needed) |
| `kimbim mcp [--project P]` | The MCP server (agents start it from their configuration) |
| `kimbim setup CLIENT` | Connects an agent (above) |
| `kimbim help [--markdown]` | The help, or the tool table above |

Every command takes `--project P` (a project folder, a `.kim` or an `.ifc`). Without it, `kimbim` uses the current
folder when it is a project or holds exactly one `.kim`.

## How it runs

When the project is open in KimBim, the app hosts the **live** session: it writes its discovery file next to the
project (`.kim` files get `<name>.kim.agent-live.json`; folders get `.kimbim/agent-live.json`) and runs each call
on its own thread. The CLI and MCP server find it there first, so the same commands work with no worker. The
status bar shows *Agent: live* and a *Disconnect* button.

When no app has the project open, the first command starts a **background worker** (`kimbim serve`). It opens the
project once and keeps it open, so later commands are fast even on large models. While it runs it holds the
project's lock as *KimBim agent*, so the app opens the project read-only. The worker saves and lets go of the
project 10 minutes after the last command (`KIMBIM_AGENT_IDLE` sets other seconds), and it saves when a task
finishes.

Timings on Windows, 2026-10-26. The sample house is the exit check below (`tools/check_agent.py`, each step one
MCP call including the round trip to the worker). The Clinic (13 MB, IFC 2x3, 41,068 elements) was timed with the
same tools called in the worker's process, because two of its steps take longer than the client waits (see the
limits below).

| Step | Sample house (4 windows) | Clinic (10 windows) | Target |
|------|-------------------------:|--------------------:|--------|
| Open (the first call starts the worker) | 1.3 s | 42 s the first time, 1 to 3 s once its cache exists | |
| `elements_find` (windows) | 12 ms | 0.15 to 0.3 s | |
| Write: `elements_set_dimensions` +50 cm | 0.3 s | refused (below) | under 2 s |
| Write: `elements_rename` | | 50 to 75 ms | under 2 s |
| `snapshot_take`, 3D, first picture (starts the renderer) | 6.6 s with `changes: "task"` | 37 s | under 3 s |
| `snapshot_take`, 3D, next pictures | | 3.9 s | under 3 s |
| `snapshot_take`, 3D, `changes: "task"` | | 227 s (the compare alone: 204 s) | under 3 s |
| `task_finish` (saves the version and the .kim) | 3.6 s | 247 s | |

What these show:

- **Writes are fast** on both models. The Clinic's windows can't be resized: all 58 of its Revit windows answer
  *"the opening doesn't fit in the wall"*, even for 1 cm. KimBim measures where a window sits in its wall from the
  opening's placement, as its own windows are built, and Revit's openings are placed differently. The write was
  timed as a rename instead.
- **Pictures** are within a few seconds once the renderer has the model; its first load of a large model takes
  about half a minute.
- **Comparing is the slow part on large models.** Since compare works on content (see [03](03-versioning.md)), a
  compare on the Clinic takes about 200 s. `task_finish` and a snapshot with `changes` both compare, so they take
  minutes there. This is the next thing to speed up.

## Limits

- **Live needs the app open.** The app hosts the session when a project finishes loading; close it and later
  commands use an offline worker instead. `selection_get` and `selection_set` work live and answer `needs_app`
  offline.
- **One open task per client.** A second `task_start` from the same client answers `task_busy`; another client may
  have its own task and option. Live tasks share the app's one working model: each call switches to its task's
  option, so the architect's view follows the agent at work. Separate working copies per client (undisturbed views)
  are not built yet.
- **Review is a bar, not a dialog.** A proposal with conflicting property edits opens the existing Combine dialog;
  otherwise Accept combines and saves in one step.
- **Long calls on large models.** The command line and the MCP server wait 120 s for an answer. On the Clinic,
  `task_finish` and a snapshot with `changes` take longer (above), so the agent is told `worker_failed`. The
  worker still completes the call, so the task does finish.
- **Resizing imported doors and windows** works for openings placed the way KimBim places them. Revit's (the
  Clinic's) are refused.
- **Option mode needs versions.** On a plain IFC file or a project without versions, `task_start` says to enable
  versioning or to use direct mode.

## The exit check

`pixi run agent` runs the request from the start of this page against the sample house, through MCP only. It finds
the Level 1 windows, starts *Widen first-floor windows*, makes them 50 cm wider, takes a snapshot of the task's
changes and finishes the task. It then reads the project's history and checks three things. The option
`agent/widen-first-floor-windows` holds one new version, and its difference from `main` is exactly the 4 windows at
1.7 m wide (their wall openings may also appear). `main` has not moved. The snapshot is a real picture (a PNG with
at least 100 colours). It prints one JSON line with the timings.

`test_agent_live` (part of `pixi run app-test`) runs the same request against the app's **live** session: it opens
the sample house, calls the CLI through the live discovery file, finishes a task, finds it in the proposal bar and
clicks **Accept**. It then checks that the combined model holds the change.
