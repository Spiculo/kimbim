<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Agent tools: `kimbim` CLI, MCP server and in-app assistant — design

Status: draft for the owner's review (2026-10-25). Decision row to add on approval: **D102**.

## 1. Intent

An architect is working on a project and is asked to *make every window on the first floor 50 cm wider*. They can
do it in the UI, but asking an agent is quicker: the change happens in seconds, they check it in the app, and they
ship it.

This work makes that possible. Architects and the AI agents working for them get one set of **project commands**
to read, look at and change a KimBim project (.kim, a project folder, or IFC). The same commands are available:

- as a **command-line tool**, `kimbim`, installed with the app, for people and for agents that run shell commands
  (opencode, Claude Code);
- as an **MCP server**, `kimbim mcp`, for any MCP client (Claude Desktop, Claude Code, opencode first);
- inside the app as an **Assistant panel** where the architect chats with a model using their own API key.

Agents work **with the project open in the app (live)** or **with the app closed (offline)**. They never drive the
GUI: no clicks, no dialogs, no mouse. They do get pictures: an agent can take **snapshots** of the model, a level,
a drawing, a sheet or single objects whenever it needs to see something.

Agent changes go into a **design option**, like a branch or worktree in software. The architect looks at the
proposal in the app and **accepts** it (it is combined into the option it came from) or **rejects** it. This review
step is configurable, because some changes are too small to be worth it.

## 2. Goals, non-goals, anti-goals

**Goals**

1. One catalogue of tools that is the single source for the CLI, the MCP server and the Assistant panel.
2. The first set of tools (§5) covers the everyday requests: find elements, read them, change dimensions,
   properties, position and status, create the main elements, place objects, levels, rooms, drawings, sheets,
   schedules, checks, selection and snapshots.
3. Live and offline both work, with the same tools and the same results.
4. Every agent change can be reviewed and undone: an option to accept or reject, or (direct mode) one undo step
   per change.
5. Setup takes one command per client (`kimbim setup claude-desktop` and so on).

**Non-goals (now)**

- An installer. Separate work. This work only makes `kimbim` sit next to `kimbim-app` and run the same bundled
  Python, so an installer can ship both.
- Driving the GUI, opening dialogs, or moving the architect's camera.
- Tools for drafting, dimensions, pen sets and graphics settings, stairs, roofs, materials editing and the Object
  Editor. They come in later sets.
- A hosted service or account. Everything runs on the architect's machine. The only network traffic is the
  Assistant panel's calls to the provider the architect configured.

**Anti-goals: a failure even if it works**

- An agent quietly damages a project with no way back.
- Snapshots that don't look like the app.
- A second command layer that drifts away from what the app itself does. Tools must call the same Python functions
  the app uses (`kimbim.app_bridge` and the modules behind it), never re-implement them.

## 3. Owner's decisions

- Audience: architects and agents working on **projects**, not on KimBim's source code.
- Live and offline both supported.
- Review by design option is the default and is configurable. The option is approved by the architect before it is
  combined.
- First set of tools only (§5).
- Snapshots: every parameter optional; the agent picks what it needs.
- Bring your own: any MCP client, and the in-app chat uses the architect's own AI key. Start with opencode, Claude
  Desktop and Claude Code.
- Agents may read and set the app's selection (live).
- Installer is separate.
- Text for people in EN/ES (the app's language). Field names and JSON keys always in English.
- The existing `kimbim` CLI may be reshaped freely (nothing released).

## 4. How it fits together

```
 opencode / Claude Code ──shell──▶ kimbim <group> <verb>  ─┐
 Claude Desktop / any MCP ──stdio─▶ kimbim mcp             ├─▶ tool catalogue (kimbim.agent)
 KimBim Assistant panel ──in process────────────────────────┘          │
                                                                        ▼
                                        a session for the project: live (inside the app) or offline (worker)
                                                                        │
                                                                        ▼
                                                 kimbim.app_bridge and its modules (the app's own functions)
```

### 4.1 Tool catalogue (`kimbim.agent`)

A Python package that defines each tool once: its name, a description written for a model, its input as JSON
Schema, its output shape, whether it changes the model, and the bridge function(s) it calls. The CLI's subcommands
and options, the MCP tool list and the Assistant's tool list are all **generated from it**. Adding a tool means
adding one catalogue entry and its test.

Tools are written for agents, not a one-to-one copy of the ~300 bridge functions. One tool may call several bridge
functions. For example, `elements.set_dimensions` takes a selector and `{"width": "+50cm"}` and handles windows,
doors, walls and slabs through the right bridge calls (`edit_opening`, `set_dimension`, `set_wall_height`, ...).

### 4.2 Sessions: where a command runs

A command always runs in a **session** that has the project open. `kimbim` finds or starts it:

1. **Live.** If the app has the project open, the app hosts the session. When it opens a project, the app starts a
   local server (named pipe on Windows, Unix socket on Linux; Qt's `QLocalServer` fits) and writes a small
   discovery file into the project's working folder, next to the existing lock: socket name, a random token, and
   the app's process id. The CLI and the MCP server connect with the token. Commands run on the app's Python side
   through the same path the Python console uses (`kimbim.console`): each write tool call is **one undo step**
   (the `edit()` machinery), the views redraw the touched elements, and the unsaved-changes mark appears.
   Commands queue behind whatever the architect is doing, the same way console runs do.
2. **Offline.** If no app has the project open, `kimbim` starts a **headless worker** (`kimbim serve`, a
   background process) that opens the project, takes the existing lock (holder "KimBim agent"), and stays alive so
   later commands are fast on big models (opening Clinic takes seconds; per command would be too slow). It exits
   after an idle timeout (default 10 minutes, preference) and saves on `project.save` or when a task finishes.
   If the architect opens the project in the app while a worker holds it, the app asks the worker to save and hand
   over, then opens it. *My call.*

`--project PATH` picks the project. Without it, `kimbim` looks for one in the current folder, then for the one
project open in a running app (if exactly one).

Live connections are on by default (preference *Allow agents to work on open projects*). While an agent is
connected the status bar shows it, with a *Disconnect* action. *My call:* any local program could already edit
the files, so a per-connection prompt would only add friction. The token keeps other users on the machine out.

### 4.3 Tasks: agent changes go into an option

A **task** is one request ("widen the first-floor windows"). It is how review works:

- `task.start {"title": "Widen first-floor windows", "mode"?: "option"|"direct"}` starts a task.
- **Option mode** (default). If the architect's working state has unsaved changes, `task.start` first saves a
  version on the architect's current option, named "Before agent: <title>" (owner, 2026-10-25), so the agent sees
  everything on screen and accepting is a clean combine. The task then creates a design option
  `agent/<slug-of-title>` from that version (the *base*). The agent's tools work on that option in **its own working copy** of the
  project's repository, like a Git worktree, so the architect keeps working undisturbed in the app. `task.finish
  {"summary"}` saves a version on the agent option (author "<client name> (agent)", message = title + summary)
  and marks it *ready for review*.
  - Live: the app shows the proposal (a bar or a Versions-panel entry: *"Agent: Widen first-floor windows — 12
    changed. Review"*). *Review* switches to the option with Compare colours against the base. *Accept* combines
    it into the base option with the existing Combine flow (conflicts handled by the existing UI) and deletes the
    agent option. *Reject* deletes it. Both are architect actions in the GUI. Agents cannot accept.
  - Offline: the option stays in the project and the app shows the same proposal the next time it opens it.
    `kimbim versions options` lists it too.
- **Direct mode.** Tools change the working model directly: live, one undo step per tool call; offline, saved on
  `task.finish`. No option.
- Project setting `agent_changes`: `option` (default), `direct`, or `agent_decides` (the task's `mode` is used,
  defaulting to option). *My call on the third value*, so "option overkill for small changes" can be left to the
  agent when the architect wants that.
- A **write tool called outside a task** starts an implicit task titled from the tool call, so nothing bypasses
  review. It stays open like any task (below), so ten calls make one proposal, not ten. *My call.*
- **Several tasks at once.** Each client (an MCP connection, the Assistant, a CLI shell) has at most one open task;
  different clients may have tasks open on the same project at the same time, each with its own option and working
  copy. Option names get a numeric suffix on a clash (`agent/widen-windows-2`). *My call.*
- **Which task a CLI command belongs to.** `task.start` prints a task id. A command uses `--task ID`, else the
  `KIMBIM_TASK` environment variable, else the only open task on the project. With several open and none named, it
  fails with `ambiguous_task`. The MCP server and the Assistant track their own task. *My call.*
- **Tasks last.** A task's state (id, title, mode, base, option, client) is stored on disk in the project's working
  folder, so it survives an MCP server restart or the worker's idle exit; the worker reopens it on the next
  command. Open tasks are listed in `task.status` and in the app; the architect can abandon one there. *My call.*
- **Agents cannot change the review rules.** `project.set_settings` refuses `agent_changes` and the script gate;
  only the architect changes them in the app. *My call.*
- Option mode needs a versioned project. On an unversioned one (plain IFC, or a .kim with versioning off),
  `task.start` fails with a clear error that says to enable versioning or use direct mode. *My call.*
- **Offline direct mode keeps a way back.** On a versioned project, `task.finish` saves a version ("<title>
  (agent)") before writing. On a plain IFC, it first writes the existing recovery copy (`documents.write_recovery`)
  and keeps the previous file as `<name>.before-agent.ifc` beside it, overwritten by the next task. *My call.*

The repository store must support a second working copy for this (see §9, risk 1).

## 5. First set of tools

Names are `group.verb`. On the CLI they become `kimbim group verb`. On MCP they become `group_verb`, since some
clients reject dots. Every write tool supports `dry_run`: it makes the change in a transaction, reports what would
change, and rolls back.

| Group | Tools | Notes |
|-------|-------|-------|
| `project` | `info`, `open`, `save`, `settings`, `set_settings` | info: name, schema, units, levels, element counts by kind, current option, unsaved state, live/offline |
| `levels` | `list`, `add`, `edit` (rename, elevation, height), `delete` | bridge `levels`/`authoring` |
| `elements` | `find`, `get`, `set_dimensions`, `set_properties`, `remove_properties`, `rename`, `move`, `rotate`, `copy`, `mirror`, `copy_to_level`, `delete`, `set_layer`, `set_status` (renovation) | `find` takes Find & Select criteria (`queries.find_elements`) plus friendly shortcuts (`kind`, `level`, `name`, `type`, `layer`, property tests); `get` returns properties, quantities, level, type, host/openings |
| `create` | `wall`, `slab`, `slab_from_walls`, `column`, `beam`, `opening` (door/window in a wall), `room` | types listed by `create.types {kind}` |
| `objects` | `library`, `versions`, `place`, `set_parameters`, `assign_version`, `update_from_library` | D99–D101 |
| `drawings` | `list`, `create` (plan, section, elevation), `export` (SVG, DXF, PDF) | |
| `sheets` | `list`, `create`, `place_drawing`, `export` (PDF, SVG, DXF) | |
| `schedules` | `list`, `get`, `export` (CSV) | read-only in this set |
| `checks` | `run` (schema, IDS, clash, model checks), `ids_report` | |
| `selection` | `get`, `set` | live only; offline returns a clear "no app" error |
| `snapshot` | `take` | §6 |
| `versions` | `log`, `diff`, `options`, `milestones`, `element_history`, `export` | read-only for agents; creating and combining options is the task's job |
| `task` | `start`, `status`, `finish`, `abandon` | §4.3 |

`task.status` lists what changed so far (added / modified / removed with names and GlobalIds). It is the same
summary each write tool returns for its own call.

### 5.1 Conventions

- **Selectors.** Any tool that acts on elements takes `elements`: a list of GlobalIds, **or** a `find` query
  (run in the same session), **or** `"selection"` (live). Results always give GlobalIds plus a readable label
  ("Window W-12, Level 1").
- **Lengths and angles** accept numbers in project units or strings with units: `"50cm"`, `"500 mm"`, `"1.2m"`,
  `"90deg"`. Changes may be relative: `"+50cm"`, `"-10%"`. Outputs give numbers in project units plus the unit
  name.
- **Output.** Every tool returns JSON:
  `{"ok": true, "result": ..., "changes"?: {...}, "warnings"?: [...]}` or
  `{"ok": false, "error": {"code", "message", "hint"?}}`. `code` is a stable English identifier;
  `message` and `hint` are in the app language. Long lists are paged (`limit`, `cursor`).
- **CLI output** is a short human summary by default and the JSON with `--json`. Exit code 0 on ok, 1 on a tool
  error, 2 on a usage error.
- **No eval of agent strings** except in the gated script tool below.

### 5.2 Escape hatch: scripts (gated)

`script.run {"code"}` runs Python in the session like the console (D82), inside a task and one undo step. It is
how an agent does what the first set can't. Off by default. Preference *Let agents run Python scripts*. *My call:*
it is arbitrary code on the architect's machine, so the architect turns it on.

## 6. Snapshots

`snapshot.take` returns an image. Every field is optional; the agent picks what it needs:

| Field | Values | Default |
|-------|--------|---------|
| `view` | `3d`, `plan`, `section`, `elevation`, `drawing`, `sheet` | `3d` |
| `level` | level name or id (plan) | active / lowest |
| `drawing`, `sheet` | name / number | — |
| `elements` | selector to frame on | whole model |
| `isolate` | show only `elements` | false |
| `highlight` | selector drawn in a highlight colour | none |
| `changes` | `none`, `task` (Compare colours of the current task against its base), or `{rev_a, rev_b}` | none |
| `camera` | preset (`top`, `front`, `iso-se`, ... as the view cube) or `{eye, target, up, fov}` | `iso-se` framed on the target |
| `style` | `shaded`, `white`, `lines`, `textured` | the app's current 3D style |
| `purpose` | a purpose (pen set, visibility) | the project's current |
| `cut` | level cut height / cut plane | the app's |
| `size` | `[w, h]` in pixels | `[1024, 768]` |
| `format` | `png`, `svg` (drawings and sheets only) | `png` |

- **It must look like the app**, with the same materials, textures, pens and poché. 3D snapshots come from the
  app's own renderer (OCCT `Scene`) and 2D ones from the same drawing generator the app uses.
  - Live: the app renders off-screen with the snapshot's camera. The architect's view, camera and selection don't
    change.
  - Offline: the worker uses the app's renderer with no window (for example `kimbim-app` started as a windowless
    render helper by the worker). How is the builder's call; the requirement is the same pixels as live.
- CLI: writes the file (`--out`, default a temp file) and prints its path. MCP: returns MCP image content (and the
  path). Assistant: passes it to the model as an image.
- Snapshots also return what is in the picture: framed element count, camera used, and the legend of `changes`
  colours, so the agent can describe it.

## 7. CLI and MCP shape

- `kimbim <group> <verb> [args] [--project P] [--json] [--dry-run]`, generated from the catalogue. `kimbim help
  <group>` and `kimbim <group> <verb> --help` are generated from the descriptions.
- The current versioning commands move under `versions` (`kimbim versions log|diff|show|export|blame|...`).
  Making a project versioned stays (`kimbim project init`, `kimbim versions save -m`) for people. `kimbim run
  script.py model.ifc` (D92) becomes `kimbim script run`, under the same gate when it targets an open project.
- `kimbim mcp [--project P]` runs an MCP server over stdio with the official Python `mcp` SDK (MIT; add to
  THIRD_PARTY.md and pixi). Tools = catalogue. The server also offers the project summary (`project.info`) as an
  MCP resource, and a short **instructions** text: how tasks and review work, selectors and units, and "take a
  snapshot to check your work".
- `kimbim setup claude-desktop | claude-code | opencode [--project P]` writes or prints the client's
  configuration for `kimbim mcp` (and for opencode/Claude Code, a short instructions file telling the agent the
  CLI exists). The app gets **Help › Connect an AI agent...**, which shows the same snippets with a Copy button.
- The `kimbim` launcher is installed next to `kimbim-app` and uses the app's bundled Python and `KIMBIM_*` paths,
  so the CLI and the app always run the same code. In development it stays `pixi run kimbim`.

## 8. In-app Assistant panel (phase 3)

- A dockable **Assistant** panel (View › Panels): a chat with the model, the tool calls shown as compact lines
  ("Found 12 windows on Level 1", "Changed width of 12 windows"), snapshots inline, and the task's *Review* button
  when it finishes.
- **Bring your own key.** Providers: Anthropic, and any OpenAI-compatible endpoint (base URL + model name), which
  covers OpenRouter, DeepSeek, local Ollama and similar. Settings in Preferences › Assistant. Keys are stored in the
  OS credential store, never in project files or preferences JSON. *My call.*
- It uses the same catalogue in-process (live session), the same tasks and the same review. One conversation per
  project window; history is kept per user (not in the project), cleared on request. *My call.*
- It can pass the current selection and the visible view as context when the architect asks ("these windows").

## 9. Risks and open points for the builder

1. **Second working copy.** Option-mode tasks need the agent's option checked out apart from the architect's
   working state (the repository's working folder is unpacked from the .kim). Check the Rust store and
   `documents`/`versioning` for what a second working copy needs (a separate working folder over the same object
   store, its own index). If it turns out impractical, the fallback is that the task's session does its work in
   memory on a copy of the base model and writes a version onto the new option without checking it out. Either
   way, the architect's working state is never switched or changed by a task (the "Before agent" version in §4.3
   only records it).
2. **The bridge holds one global model** (`app_bridge._model`). The live app has one, the offline worker has one,
   and an option-mode task needs a second one beside the architect's (live). The catalogue must not assume one
   global; it may need a small "model context" around bridge calls. Changing the bridge is fine (no backward
   compatibility).
3. **Off-screen rendering offline** on machines without a GPU (software OpenGL). Measure it.
4. **Concurrency live:** an agent command arriving mid-gesture (the architect is dragging a wall) waits until the
   app is idle, like console runs.
5. **Timing on real files.** Find, edit and snapshot on Clinic_Architectural.ifc should feel instant to an agent:
   target under 2 s per write tool call and under 3 s per snapshot. Measure; don't block on the target.

## 10. Phases

1. **Catalogue + CLI + MCP, offline.** `kimbim.agent`, worker sessions, tasks (option and direct), first tool set,
   snapshots via the windowless renderer, `kimbim mcp`, `kimbim setup`, the reshaped CLI.
2. **Live.** The app's local server and discovery file, tool calls as undo steps, selection tools, live
   snapshots, proposal bar and Review / Accept / Reject, the status-bar indicator, Help › Connect an AI agent.
3. **Assistant panel.** Providers, keys, chat UI, inline snapshots.

Each phase ends with its exit check (§11) green.

## 11. How we know it works

- Unit tests per catalogue tool against the sample house (`tools/make_house.py`), including `dry_run` and error
  codes; CLI tests through `main()`; an MCP test with an in-process MCP client listing tools and calling a few.
- **Exit check `pixi run agent`** (phases 1–2): on the sample house, through MCP only: find the windows on the
  first floor, `task.start`, widen them by 50 cm, take a `changes: task` snapshot, `task.finish`; then check the
  option exists with exactly those windows changed by 0.5 m, the base option untouched, and the snapshot is a
  non-empty PNG. Phase 2 runs the same against the live app (ctest self-test) and accepts the proposal with the
  Combine flow.
- Manual check by the owner: Claude Desktop and opencode connected with `kimbim setup`, the window request from §1
  done end to end and reviewed in the app.

## 12. Left to the builder

The local-socket protocol framing, the worker's process management and idle handling, the exact catalogue module
layout, how snapshots render offline, the CLI's human-readable formatting, the proposal UI's exact look (follow
the app's existing bars and the Versions panel), and the Spanish texts (follow `check-translations`).
