<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Agent tools, phase 1 (offline CLI + MCP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One tool catalogue (`kimbim.agent`) drives a reshaped `kimbim` CLI and a `kimbim mcp` server that read,
change and take snapshots of .kim / folder / IFC projects with the app closed, with agent changes going into
reviewable design options.

**Architecture:** Tools are Python functions registered in a catalogue with a JSON Schema and a model-facing
description; they call the existing bridge functions (`kimbim.app_bridge` and its modules). A `Session` holds one
open document the way the app opens it; a background **worker** process keeps a session alive between CLI calls
(stdlib `multiprocessing.connection`, authkey). Tasks wrap writes in a design option `agent/<slug>`. Snapshots are
rendered by the app binary in a new windowless `--snapshot-server` mode that the worker keeps running.

**Tech Stack:** Python 3.12 (pixi), ifcopenshell 0.9, official MCP Python SDK (`mcp`, MIT), C++/Qt 6 + OCCT for
the render helper, pytest, ctest.

**Spec:** `docs/superpowers/specs/2026-10-25-agent-tools-design.md` (D102). Read it first; this plan implements
its §4.1–4.3, §5, §6 (offline), §7 and the phase 1 parts of §10–11.

## Global Constraints

- Every source file starts with `SPDX-License-Identifier: GPL-3.0-or-later` in its first 5 lines.
- Commits: `git commit -s`, conventional prefix (`feat(agent): ...`). **No `Co-Authored-By` or any Claude
  attribution.**
- Run everything through pixi (`pixi run test-py`, `pixi run kimbim ...`); never the bare env python.
- Tools never re-implement modelling: they call bridge functions (anti-goal "second command layer").
- JSON keys, tool names, error `code`s: English. `message`/`hint` and CLI human text: EN/ES by app language.
- Tool output envelope: `{"ok": true, "result": ..., "changes"?: {...}, "warnings"?: [...]}` or
  `{"ok": false, "error": {"code", "message", "hint"?}}`.
- CLI exit codes: 0 ok, 1 tool error, 2 usage error.
- Lengths accept project-unit numbers or strings with units (`"50cm"`, `"500 mm"`, `"1.2m"`), angles `"90deg"`;
  relative `"+50cm"`, `"-10%"`. The bridge works in metres.
- MCP tool names are `group_verb` (dots replaced by `_`); CLI is `kimbim group verb-with-hyphens`.
- Agent option names: `agent/<slug>`, numeric suffix on a clash (`agent/widen-windows-2`).
- Before-agent version message: `Before agent: <title>`. Agent commit author: `("<client> (agent)", "agent@kimbim.local")`.
- Worker idle exit default **600 s** (`KIMBIM_AGENT_IDLE` env overrides, for tests).
- `project.set_settings` refuses keys `agent_changes` and `agent_scripts` (code `setting_reserved`).
- New dependency `mcp` goes in `pixi.toml` and `THIRD_PARTY.md`.
- No backward compatibility: the old CLI commands are replaced, not aliased.

**Phase 1 narrowing (my call, tell the owner):** one open task per project at a time (`task_busy` on a second
`task.start`). The spec's several concurrent tasks need several models per process (spec §9 risk 2) and arrive with
phase 2. Task state is still per client id so phase 2 only lifts the limit.

## Review Focus

1. A selector that matches nothing (e.g. no windows on that level) → `ok: false`, code `no_match`, never a silent
   success with 0 changes. Test in Task 4.
2. A relative change that would make a dimension ≤ 0 (`"-2m"` on a 1.2 m window) → the whole tool call is rolled
   back, nothing half-applied. Test in Task 6.
3. The worker crashes or is killed while a task is open → the next command restarts it, the task resumes on its
   agent option, the architect's base option is intact. Test in Task 9.
4. A .kim locked by the app (or another worker) → `project_locked` error with the holder, no worker left running.
   Test in Task 9.
5. Names in any script (ñ, accents) in titles, option slugs, CLI output on Windows pipes → round-trip intact; slug
   transliterates to ASCII (`"Ampliar ventanas ñ"` → `agent/ampliar-ventanas-n`). Test in Task 5.

---

## File structure

```
python/kimbim/agent/
  __init__.py        package doc; imports tool modules so the catalogue fills
  catalogue.py       Tool, @tool, TOOLS, AgentError, call_tool() (envelope, dry_run, task gate)
  messages.py        EN/ES texts by error code; language()
  units.py           parse_length / parse_angle / apply_change
  steps.py           one undo step per tool call; Changes summary; rollback for dry_run
  session.py         Session: open/save/close a document; selectors; labels
  tasks.py           Task store, start/finish/abandon/park/unpark, option and direct modes
  tools/__init__.py
  tools/project.py   project.*, levels.*
  tools/elements.py  elements.find/get + write tools
  tools/create.py    create.*
  tools/objects.py   objects.*
  tools/outputs.py   drawings.*, sheets.*, schedules.*, checks.*
  tools/versions.py  versions.*, task.*, selection.*, script.run
  tools/snapshot.py  snapshot.take
  render.py          client for the app's --snapshot-server
  worker.py          `kimbim serve`: Listener loop, idle exit, discovery file
  client.py          find/start a worker, send a request
  cli.py             argparse generated from the catalogue + people commands
  mcp_server.py      `kimbim mcp`
  clients.py         `kimbim setup <client>` config writers
python/kimbim/cli.py           → thin: `from .agent.cli import main`
python/kimbim/console.py       expose touched() for steps.py
python/kimbim/settings.py      new defaults agent_changes, agent_scripts
python/kimbim/kimfile.py       nothing if .kimbim/agent/ already packs (verify in Task 5)
app/src/SnapshotServer.{h,cpp} windowless render helper; main.cpp option; app/CMakeLists.txt
tests/python/test_agent_*.py   one file per task
tools/check_agent.py           exit check; pixi task `agent`
docs/17-agent-tools.md         user doc; docs/03 CLI section, docs/15 "Not yet", docs/README index
```

---

### Task 1: Units and messages

**Files:**
- Create: `python/kimbim/agent/__init__.py`, `python/kimbim/agent/units.py`, `python/kimbim/agent/messages.py`
- Test: `tests/python/test_agent_units.py`

**Interfaces:**
- Produces: `parse_length(v: float|int|str, unit: str = "m") -> float` (metres; `unit` = project `length_unit`
  for bare numbers: `"m"`, `"cm"`, `"mm"`); `parse_angle(v) -> float` (degrees; bare number = degrees, `"rad"`
  suffix allowed); `apply_change(current: float, v, unit="m") -> float` (absolute, `+`/`-` relative, `%`
  relative); all raise `ValueError` with the bad text. `language() -> "en"|"es"`: `KIMBIM_LANG` env, else the
  app preferences' `language` (same file as `Preferences::defaultPath()`, QStandardPaths AppConfigLocation), else
  the system locale (`es*` → es), else en. `text(code: str, **fmt) -> str` from a `MESSAGES = {code: {"en","es"}}`
  table; unknown code returns the code.

- [ ] **Step 1: Write failing tests** `test_parse_length_units` (`"50cm"→0.5`, `"500 mm"→0.5`, `"1,2m"→1.2`,
  `2`→2.0, `2` with unit `"mm"`→0.002), `test_apply_change` (`apply_change(1.2,"+50cm")==pytest.approx(1.7)`,
  `"-10%"` on 2.0 → 1.8, `"0.9"` → 0.9), `test_bad_length_raises` (`"5 parsecs"`), `test_angle`
  (`"90deg"`→90, `"3.14159rad"`≈180), `test_language_env` (monkeypatch `KIMBIM_LANG=es`, `text("no_match")` is
  the Spanish string).
- [ ] **Step 2:** `pixi run pytest tests/python/test_agent_units.py -v` → FAIL (module missing).
- [ ] **Step 3:** Implement. Seed `MESSAGES` with every code this plan names: `no_model`, `no_match`,
  `bad_input`, `bad_length`, `bridge_error`, `not_versioned`, `task_busy`, `no_task`, `ambiguous_task`,
  `unknown_task`, `project_locked`, `setting_reserved`, `scripts_off`, `needs_app`, `render_failed`,
  `unknown_tool`, `not_found`.
- [ ] **Step 4:** Tests pass.
- [ ] **Step 5:** Commit `feat(agent): units and EN/ES messages (D102)`.

### Task 2: Catalogue and one step per call

**Files:**
- Create: `python/kimbim/agent/catalogue.py`, `python/kimbim/agent/steps.py`
- Modify: `python/kimbim/console.py` (rename `_touched` → `touched`, keep callers working)
- Test: `tests/python/test_agent_catalogue.py`

**Interfaces:**
- Produces:
  - `class AgentError(Exception): code: str; hint: str = ""; extra: dict` — `AgentError("no_match", **fmt)`;
    message comes from `messages.text`.
  - `@dataclass Tool: name, description, params (JSON Schema object), writes: bool, fn, needs_task: bool = writes`.
  - `tool(name: str, params: dict, writes: bool = False)` decorator; description = the function docstring
    (required, ≥ 1 sentence, asserted at registration). `TOOLS: dict[str, Tool]`.
  - `call_tool(session, name: str, args: dict, *, client: str = "cli", task_id: str = "") -> dict` — validates
    `args` against `params` (required keys, types, `enum`; a small validator here, no new dependency), pops
    `dry_run`, for write tools asks `session.tasks.for_write(client, task_id, title=...)` (Task 5) and runs `fn`
    inside `steps.step(dry_run)`, returns the envelope. `AgentError` → error envelope; any other exception →
    `bridge_error` with `str(ex)`. A bridge result JSON with `ok: false` is turned into `bridge_error` by
    `bridge(fn, *args) -> dict` (helper here, used by every tool: calls, `json.loads`, raises on failure).
  - `steps.step(dry_run: bool) -> ContextManager[Changes]`: opens one undo step like `console.edit()` (joins bridge
    calls via `B._step`), on exit computes `Changes` from the transaction (`console.touched`): `added` = GlobalIds
    of IfcProducts in `create` operations, `modified` = touched − added, `removed`; then closes the step
    (`console._finish_step`) and, if `dry_run`, calls `B.undo()` and drops the redo entry. On exception: abort
    (`B._abort`) and re-raise, so a failing call leaves nothing.
  - `Changes.to_dict(labels) -> {"added": [{"guid","label"}], "modified": [...], "removed": [...], "counts": {...}}`.

- [ ] **Step 1: Tests.** Register two throwaway tools in a fixture (one read, one write that calls
  `bridge.set_name`). `test_envelope_ok`, `test_validation_error` (missing required → `bad_input`),
  `test_write_is_one_undo_step` (two bridge calls inside one tool → `B.undo()` once restores both names),
  `test_dry_run_rolls_back` (changes reported, model unchanged, `B._current_id()` back to before),
  `test_failure_rolls_back` (tool renames then raises `AgentError` → name unchanged), `test_docstring_required`.
  Use the `model` fixture opened via `B.open_model` on a temp file, and a stub session whose `tasks.for_write`
  returns `None`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. `pixi run pytest tests/python/test_console.py` must still pass after the rename.
- [ ] **Step 4:** Tests pass.
- [ ] **Step 5:** Commit `feat(agent): tool catalogue, one undo step per call, dry run (D102)`.

### Task 3: Session (open the way the app does)

**Files:**
- Create: `python/kimbim/agent/session.py`
- Test: `tests/python/test_agent_session.py`

**Interfaces:**
- Consumes: `documents.open_kim(path)`, `documents.open_folder(folder)`, `B.open_model(path)` (calls
  `documents.on_model_opened`), `documents.save_document()`, `documents.close_document()`, `kimfile.me()`.
- Produces: `class Session` with `Session.open(path: str, client: str = "cli") -> Session` (`.kim` →
  `open_kim`, folder with `.kimbim` → `open_folder`, `.ifc` → `B.open_model`; lock holder shown as
  `"KimBim agent"`: set `kimfile.display_user = "KimBim agent"` before acquiring); `kind: "kim"|"folder"|"ifc"`;
  `source: str`; `work: str` (documents `_doc["work"]`, "" for plain IFC); `save() -> None`; `close() -> None`;
  `unit: str` (project `length_unit`); `resolve(selector) -> list[str]` (Task 4 fills the query part);
  `label(guid) -> str` (`"Window W-12, Level 1"`: class short name, Name, storey name); `tasks` (Task 5).
  A locked file raises `AgentError("project_locked", holder=...)`.

- [ ] **Step 1: Tests.** Build a .kim from `build_model()` with `documents.import_ifc` in `tmp_path`.
  `test_open_kim_and_save` (rename a wall through a tool-less bridge call, `save()`, reopen, name kept),
  `test_open_plain_ifc`, `test_open_folder`, `test_locked_kim` (acquire the lock as another holder first →
  `project_locked` with holder user), `test_label`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Pass.
- [ ] **Step 5:** Commit `feat(agent): sessions open .kim, folders and IFC like the app (D102)`.

### Task 4: Read tools — project, levels, find, get

**Files:**
- Create: `python/kimbim/agent/tools/__init__.py`, `tools/project.py`, `tools/elements.py` (read part)
- Modify: `python/kimbim/agent/session.py` (`resolve`)
- Test: `tests/python/test_agent_read.py`

**Interfaces:**
- Consumes: `queries.find_elements(query_json)` (rows of `{"field","op","value"[, "property"]}`, fields
  `kind, ifc_class, type, name, property, layer, level, status, material`; kinds are `graphics.KINDS` plurals),
  `authoring.storeys()`, `levels.levels_table()`, `B.properties_multi`, `authoring.element_dimensions`,
  `settings.project_settings()`.
- Produces:
  - Selector (shared JSON Schema `SELECTOR` in `catalogue.py`): a list of GlobalIds, the string `"selection"`, or a
    find object `{"kind"?, "ifc_class"?, "level"?, "name"?, "type"?, "layer"?, "status"?, "where"?: [rows],
    "match"?: "all"|"any"}`. `kind` accepts singular or plural (`"window"`/`"windows"`). `level` accepts a name
    or GlobalId; unknown level → `not_found`. Empty result → `AgentError("no_match")`. `"selection"` offline →
    `needs_app`.
  - Tools: `project.info` → `{name, schema, kind, source, unit, levels:[{guid,name,elevation}], counts:{kind:n},
    option, options, versioned, unsaved, mode:"offline"}`; `project.settings {keys?: [str]}`; `levels.list`;
    `elements.find {elements: SELECTOR, limit=200, cursor=""}` → `{items:[{guid,label,kind,level}], total,
    next_cursor}`; `elements.get {elements, limit=50}` → per element: label, class, type, level, dimensions
    (from `element_dimensions`, metres + unit), properties (psets), host/openings GlobalIds.

- [ ] **Step 1: Tests** on the sample house (`tools/make_house.py`'s `build()` into a tmp IFC, then a .kim):
  `test_info_counts` (8 walls, 2 levels), `test_find_windows_level` (`{"kind":"window","level":"Level 1"}` → 4),
  `test_find_no_match` (`{"kind":"window","level":"Level 9"}` → `not_found`; `{"kind":"roof"}` with none →
  `no_match`), `test_get_dimensions` (a window: Width 1.2, unit `"m"`), `test_paging` (limit 3 + cursor walks all
  walls once).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Pass.
- [ ] **Step 5:** Commit `feat(agent): project, levels, find and get tools (D102)`.

### Task 5: Tasks — option and direct modes, stored on disk

**Files:**
- Create: `python/kimbim/agent/tasks.py`, `tools/versions.py` (task.* part)
- Modify: `python/kimbim/settings.py` (DEFAULTS `"agent_changes": "option"` with values
  `option|direct|agent_decides`, `"agent_scripts": False`; validation), `python/kimbim/versioning.py`
  (`save_version(message, author_json="")` passes `author` to `Project.commit`)
- Test: `tests/python/test_agent_tasks.py`

**Interfaces:**
- Consumes: `versioning._unversioned()`, `save_version`, `create_option`, `switch_option`, `delete_option`,
  `discard_changes`, `project_state()`; `documents.write_recovery()`, `save_document()`.
- Produces:
  - `@dataclass Task: id (8 hex), title, mode, client, status ("open"|"parked"|"ready"|"abandoned"), base_option,
    base_version, option, created, summary`. Stored as JSON in `<work>/.kimbim/agent/tasks/<id>.json` (travels in
    the .kim — verify `kimfile._entries` packs it, add a test), or for a plain IFC in
    `documents.data_dir()/agent/tasks/<kimfile.path_hash(source)>/<id>.json`.
  - `class Tasks` (on the session): `start(title, mode="", client) -> Task`; `finish(task_id, summary) -> dict`;
    `abandon(task_id)`; `status(task_id="") -> dict` (task + accumulated `Changes`); `open_task(client, task_id)
    -> Task|None` (rule: `task_id` → that one; else the client's open task; else the only open task on the
    project; several → `ambiguous_task`); `for_write(client, task_id, title)` → the open task, or starts an
    implicit task titled `title` (the tool's name + first selector words); `park()` / `unpark()`.
  - Mode: setting `option` → option; `direct` → direct; `agent_decides` → the `mode` argument, default option.
    Option mode on an unversioned project → `not_versioned` (hint: enable versioning or use direct).
  - **Option start:** if `_unversioned()`, `save_version("Before agent: <title>")`; record `base_option`,
    `base_version`; `create_option(agent/<slug>)` (slug: NFKD → ASCII, lowercase, non-alnum → `-`, max 40;
    suffix `-2`, `-3` on clash). **Finish:** `save_version("<title>\n\n<summary>", author)`, `switch_option(
    base_option)`, `save_document()`, status `ready`. **Abandon:** `switch_option(base_option)` (after
    `discard_changes`), `delete_option(option)`. **Park** (worker exit with a task open):
    `save_version("Work in progress: <title>", author)`, switch to base, save, status `parked`; **unpark** (next
    command): `switch_option(option)`, status `open`.
  - **Direct finish:** versioned → `save_version("<title> (agent)", author)`, then `save_document()`; unversioned
    .kim/folder → `save_document()`; plain IFC → `write_recovery()`, copy source to `<stem>.before-agent.ifc`
    (overwrite), then `save_document()`.
  - A second `start` while a task is open on the project → `task_busy` naming it (phase 1 narrowing).
  - Tools: `task.start {title, mode?}`, `task.finish {summary, task?}`, `task.abandon {task?}`, `task.status
    {task?}`.
  - `project.set_settings {changes}` lives in `tools/project.py`; refuses `agent_changes`/`agent_scripts` with
    `setting_reserved`.

- [ ] **Step 1: Tests** on a versioned sample-house .kim: `test_option_task_round_trip` (start, rename two walls
  via a write tool, finish → option `agent/<slug>` exists with one new version by author "test (agent)", current
  option back to `main`, `main`'s model unchanged), `test_before_agent_version` (unsaved rename first → history
  has "Before agent: …" and the agent option starts after it), `test_implicit_task` (write without start → one
  task, two writes → still one), `test_task_busy`, `test_abandon_deletes_option`, `test_direct_plain_ifc_backup`
  (`.before-agent.ifc` equals the original bytes; source has the change), `test_not_versioned`,
  `test_slug_unicode` (`"Ampliar ventanas ñ"` → `agent/ampliar-ventanas-n`, a second → `-2`),
  `test_reserved_settings`, `test_task_file_in_kim` (after finish, reopen the .kim on a fresh data dir → task
  `ready` is listed), `test_park_unpark`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Pass; `pixi run pytest tests/python/test_versioning_app.py tests/python/test_settings.py` still pass.
- [ ] **Step 5:** Commit `feat(agent): tasks in design options or direct, stored with the project (D102)`.

### Task 6: Element write tools

**Files:**
- Modify: `python/kimbim/agent/tools/elements.py`
- Test: `tests/python/test_agent_elements.py`

**Interfaces:**
- Consumes: `authoring.set_dimension(guids_json, name, value)` (names `Length`, `Height`, `Width`,
  `Sill height`), `authoring.edit_opening`, `B.set_property(guids_json, pset, prop, value_json)`,
  `B.remove_property`, `B.set_name`, `authoring.move_elements(guids, dx, dy, dz)`, `rotate_elements(guids, cx,
  cy, angle)`, `editing.copy_elements(guids, dx, dy, dz, storey_guid)`, `editing.mirror_elements`,
  `authoring.copy_to_storey`, `authoring.delete_elements`, `layers.assign_layer`, `renovation.set_status`
  (`graphics.STATUS_KEYS`).
- Produces (all `writes=True`, all take `elements: SELECTOR`):
  `elements.set_dimensions {elements, width?, height?, sill?, length?}` — values through `units.apply_change`
  against each element's current value (`element_dimensions`); elements with the same target value are grouped
  into one `set_dimension` call; an element lacking the dimension → warning, skipped; none applicable → `no_match`;
  a result ≤ 0 (sill < 0) → `bad_length` and the whole call rolls back.
  `elements.set_properties {elements, properties: {"Pset.Name": value}}`, `elements.remove_properties {elements,
  properties: [..]}`, `elements.rename {elements, name}`, `elements.move {elements, dx?, dy?, dz?}`,
  `elements.rotate {elements, angle, center?: [x,y]}` (default: selection bounding-box centre),
  `elements.copy {elements, dx?, dy?, dz?, level?}`, `elements.mirror {elements, line: [[x1,y1],[x2,y2]],
  copy=false}`, `elements.copy_to_level {elements, level}`, `elements.delete {elements}`,
  `elements.set_layer {elements, layer}`, `elements.set_status {elements, status}`.

- [ ] **Step 1: Tests** (each inside a direct task on the sample house): `test_widen_windows_relative` (Level 1
  windows `width: "+50cm"` → all 1.7 m, `changes.modified` contains the 4 windows), `test_mixed_widths_grouped`,
  `test_negative_result_rolls_back` (`width: "-2m"` → `bad_length`, all widths still 1.2),
  `test_move_and_rotate`, `test_set_properties_typed` (bool and number values), `test_delete_reports_removed`,
  `test_dry_run_widen` (reports 4 modified, widths unchanged), `test_set_status_unknown` (`bad_input` via enum).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Pass.
- [ ] **Step 5:** Commit `feat(agent): element edit tools (D102)`.

### Task 7: Create, levels and object tools

**Files:**
- Create: `python/kimbim/agent/tools/create.py`, `tools/objects.py`
- Modify: `tools/project.py` (levels write tools)
- Test: `tests/python/test_agent_create.py`

**Interfaces:**
- Consumes: `authoring.create_wall(storey, type, x1,y1,x2,y2, height, join_start, join_end)`,
  `create_slab(storey, type, points_json, offset)`, `slab_outline_from_walls(walls_json)`,
  `create_column(storey,type,x,y,height,rotation)`, `create_beam(storey,type,x1,y1,x2,y2,top)`,
  `insert_opening(kind, wall, type, along, width, height, sill)`, `rooms.create_room(storey, x, y, name)`,
  `wall_types/slab_types/column_types/beam_types/opening_types(kind)`, `authoring.add_storey(name, elevation)`,
  `levels.rename_storey`, `set_storey_elevation(guid, elevation, move_above)`, `delete_storey(guid, elements,
  move_to)`, `library.library_objects()`, `objversions.object_versions(key)`, `library.place_object(storey, key,
  params_json, x, y, angle, gravity, version)`, `library.set_object_parameter(guids, name, value, scope)`,
  `objversions.assign_version(guids, version_id)`, `library.update_from_library(guids)`.
- Produces: `create.types {kind: wall|slab|column|beam|door|window}` → `[{guid,name,...}]`; types are referenced
  by name or GlobalId in the create tools (`type` field; default the first listed). `create.wall {level, start:
  [x,y], end: [x,y], height?, type?, join?: bool}` (lengths through `units.parse_length`); `create.slab {level,
  points?: [[x,y],..], from_walls?: SELECTOR, type?, offset?}`; `create.column {level, at, height?, rotation?,
  type?}`; `create.beam {level, start, end, top?, type?}`; `create.opening {kind: door|window, wall: guid,
  along, width?, height?, sill?, type?}`; `create.room {level, at, name?}`. Each returns the new GlobalIds.
  `levels.add {name, elevation}`, `levels.edit {level, name?, elevation?, move_above=false}`, `levels.delete
  {level, elements: refuse|delete|move, move_to?}`. `objects.library`, `objects.versions {object}`,
  `objects.place {object, level, at, angle?, version?, parameters?}`, `objects.set_parameters {elements,
  parameters: {name: value}, scope?: all|selection}`, `objects.assign_version {elements, version}`,
  `objects.update_from_library {elements?}`.

- [ ] **Step 1: Tests**: `test_create_wall_with_units` (`end: ["5m","0"]`, height `"280cm"` → length 5, height
  2.8), `test_slab_from_walls`, `test_window_in_wall`, `test_type_by_name`, `test_add_level`,
  `test_place_bundled_chair` (place `chair`-like bundled object from `library_objects`, set a length parameter),
  `test_unknown_type` → `not_found`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Pass.
- [ ] **Step 5:** Commit `feat(agent): create, level and object tools (D102)`.

### Task 8: Outputs, versions, selection and script tools

**Files:**
- Create: `python/kimbim/agent/tools/outputs.py`
- Modify: `tools/versions.py`
- Test: `tests/python/test_agent_outputs.py`

**Interfaces:**
- Consumes: `drawings.drawings()`, `create_plan(storey)`, `create_section`, `create_elevations`,
  `sheets.sheets()`, `add_sheet(paper, title)`, `place_drawing(number, drawing, x, y, scale)`,
  `export_sheet_svg(number, path)`, `dxf.export_drawing_dxf / export_sheet_dxf`, `schedules.schedule_schemes()`,
  `schedule(scheme)`, `export_schedule`, `checks.run_check(name, options_json)`, `export_ids_report`,
  versioning `history`, `compare`, `options`, `milestones`, `element_history`, `documents.export_ifc`,
  `console.console_run(code, selection_json)`.
- Produces: `drawings.list`, `drawings.create {kind: plan|section|elevation, level?, line?: [[x,y],[x,y]],
  direction?}` (write), `drawings.export {drawing, format: svg|dxf|pdf, out}`; `sheets.list`, `sheets.create
  {title, paper="A1"}` (write), `sheets.place_drawing {sheet, drawing, at?, scale=100}` (write), `sheets.export
  {sheet, format: pdf|svg|dxf, out}` (PDF through the app binary's existing `--export-sheet NUMBER model.ifc
  out.pdf`, model written to a temp IFC); `schedules.list`, `schedules.get {schedule, limit=500}`,
  `schedules.export {schedule, out}` (CSV); `checks.run {checks: [schema|ids|clash|model], options?}`,
  `checks.ids_report {out}`; `versions.log {limit=50}`, `versions.diff {from, to="WORKING"}`, `versions.options`,
  `versions.milestones`, `versions.element_history {element}`, `versions.export {version="HEAD", out}`;
  `selection.get` / `selection.set {elements}` → `needs_app` offline; `script.run {code}` → `scripts_off` unless
  project setting `agent_scripts` is true, else runs `console_run` inside the task step and returns output.

- [ ] **Step 1: Tests**: `test_plan_and_sheet_export_svg` (create a plan of Level 1, a sheet, place, export SVG →
  file exists, contains `<svg`), `test_schedule_get_doors`, `test_checks_model`, `test_versions_log_after_task`,
  `test_selection_needs_app`, `test_script_gate` (off → `scripts_off`; setting on via the bridge, not the tool →
  runs and renames a wall in one undo step).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Pass.
- [ ] **Step 5:** Commit `feat(agent): drawings, sheets, schedules, checks, versions, script tools (D102)`.

### Task 9: Worker and client

**Files:**
- Create: `python/kimbim/agent/worker.py`, `python/kimbim/agent/client.py`
- Test: `tests/python/test_agent_worker.py`

**Interfaces:**
- Consumes: `Session.open`, `catalogue.call_tool`, `Tasks.park/unpark`.
- Produces:
  - `serve(project: str, idle: float) -> int`: opens the session (lock), listens on
    `multiprocessing.connection.Listener(family="AF_PIPE" on Windows else "AF_UNIX", authkey=os.urandom(32))`,
    writes the discovery file `documents.data_dir()/agent/sessions/<kimfile.path_hash(project)>.json` =
    `{"address", "authkey" (hex), "pid", "project", "kind": "worker", "started"}` (written atomically, removed on
    exit). Handles one request at a time: `{"tool", "args", "client", "task"}` → envelope; special tools
    `_ping`, `_shutdown`. After `idle` seconds without a request: park an open option task, save, release the lock,
    exit. On start, unpark a `parked` task of the project.
  - `request(project: str, tool: str, args: dict, *, client="cli", task="", start=True, timeout=120) -> dict`:
    reads the discovery file; if missing or its pid is dead (`kimfile.pid_alive`) and `start`, launches
    `[sys.executable, "-m", "kimbim", "serve", project]` detached (Windows `DETACHED_PROCESS |
    CREATE_NEW_PROCESS_GROUP`, else `start_new_session=True`), stdout/stderr to
    `data_dir()/agent/logs/<hash>.log`, waits ≤ 60 s for the file; a worker that exits during start with a lock
    error → returns its `project_locked` envelope (the worker writes it to the discovery path as
    `{"error": envelope}` before exiting).
  - Stale discovery file (dead pid) is removed before restarting.

- [ ] **Step 1: Tests** (`KIMBIM_DATA_DIR`=tmp, `KIMBIM_AGENT_IDLE=3`): `test_request_starts_worker` (two
  requests, same worker pid), `test_idle_exit_releases_lock`, `test_killed_worker_restarts_and_unparks` (start a
  task, write, kill pid, next request → task open on its option, `main` intact), `test_locked_project` (lock
  held by another holder → `project_locked`, no process left), `test_wrong_authkey_rejected`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Pass (mark slow tests `@pytest.mark.slow` only if
  over 10 s).
- [ ] **Step 5:** Commit `feat(agent): background worker keeps the project open between commands (D102)`.

### Task 10: Windowless snapshot renderer in the app

**Files:**
- Create: `app/src/SnapshotServer.h`, `app/src/SnapshotServer.cpp`
- Modify: `app/src/main.cpp` (option `--snapshot-server`), `app/CMakeLists.txt` (source + ctest
  `app_snapshot_server`, label `gui`)
- Test: ctest `app_snapshot_server` driving it from a Python script `app/tests/snapshot_server_test.py`
  (or the existing ctest pattern used for `--export-sheet`)

**Interfaces:**
- Produces: `kimbim-app --snapshot-server`: reads one JSON request per stdin line, writes one JSON line per
  request to stdout, exits on EOF. Requests:
  - `{"op":"load","model": ifc_path,"settings": settings_json_path}` → opens the model the way `MainWindow` does
    (meshes, materials, purposes from the settings) in a `MainWindow` that is never shown on screen
    (`Qt::WA_DontShowOnScreen`; if OCCT then cannot get a GL context, a frameless window at an off-screen
    position with `WA_ShowWithoutActivating`; it must never take focus or appear in the taskbar) → `{"ok":true,
    "elements": n}`.
  - `{"op":"render3d","out": png,"size":[w,h],"camera": preset|{eye,target,up,fov},"style":
    shaded|white|lines|textured,"purpose": name,"frame": [guids],"isolate": bool,"highlight": [guids],"colours":
    {guid: "#rrggbb"},"cut": metres|null}` → `{"ok":true,"out","camera":{eye,target,up,fov},"framed": n}`. Exact
    pixel size via `V3d_View::ToPixMap`. Presets are the D76 view-cube names (`top, bottom, front, back, left,
    right, iso-se, iso-sw, iso-ne, iso-nw`). `colours` uses the Compare colouring (`Viewport.h:262`); `isolate`
    uses `Viewport::isolate`.
  - `{"op":"svg2png","svg": path,"out": png,"size":[w,h]}` → rasterised with `QSvgRenderer` on white.
- [ ] **Step 1:** Write the ctest: start the helper, `load` the house IFC (`build/house.ifc` from `pixi run
  house`), render `iso-se` 800×600 and `top` with one wall highlighted; assert PNG sizes are exactly 800×600, the
  image is not uniform (≥ 100 distinct colours), the highlight colour appears in the `top` image; `svg2png` of a
  small SVG gives the size asked.
- [ ] **Step 2:** `pixi run app-build` then `ctest --test-dir build/app -R app_snapshot_server` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Pass; `pixi run app-test` still 60/60 + 1.
- [ ] **Step 5:** Commit `feat(app): windowless snapshot server for agent tools (D102)`.

### Task 11: `snapshot.take`

**Files:**
- Create: `python/kimbim/agent/render.py`, `python/kimbim/agent/tools/snapshot.py`
- Test: `tests/python/test_agent_snapshot.py` (marked `app`: skipped when the app binary isn't built)

**Interfaces:**
- Consumes: Task 10 protocol; `drawings.generate_plan_drawing`/`generate_drawing`, `sheets.sheet_svg`,
  `versioning.compare` (for `changes`), the app's Compare colours (added / modified / removed colours: read them
  from the same source the app uses; if they are C++-only, define them once in `render.py` and assert in a test
  that they match `MainWindow::compareWith`'s).
- Produces: `class Renderer` (one per worker): finds the app binary (`KIMBIM_APP` env, else next to the Python
  package's install — `build/app/kimbim-app[.exe]` in development), starts it lazily, re-`load`s only when
  `B._current_id()` or the settings changed since the last load (writes the model to
  `data_dir()/agent/render/<hash>.ifc`). `snapshot.take` with the spec §6 fields (all optional, defaults from the
  spec table): `view: 3d|plan|section|elevation|drawing|sheet`; 2D views generate SVG and use `svg2png` unless
  `format: "svg"`; `changes: "task"` colours the current task's changes against `base_version`; `out` optional
  (default `data_dir()/agent/snapshots/<timestamp>.png`). Result: `{"path", "format", "size", "camera", "framed",
  "legend": [{"colour","meaning"}]}`; the MCP layer (Task 13) also attaches the image. Missing binary or crash →
  `render_failed` with the log path.

- [ ] **Step 1: Tests**: `test_snapshot_3d_default`, `test_snapshot_plan_level1`, `test_snapshot_changes_task`
  (after widening windows in an option task, legend has "modified", 4 elements coloured — assert via `framed` and
  legend), `test_snapshot_svg_sheet`, `test_renderer_reuses_load` (two snapshots, one `load`).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Pass.
- [ ] **Step 5:** Commit `feat(agent): snapshots of the model, plans, drawings and sheets (D102)`.

### Task 12: Generated CLI

**Files:**
- Create: `python/kimbim/agent/cli.py`
- Modify: `python/kimbim/cli.py` (becomes `from .agent.cli import main`), `python/kimbim/__main__.py` if needed,
  `tests/python/test_cli.py` (rewrite for the new commands)
- Test: `tests/python/test_agent_cli.py`

**Interfaces:**
- Consumes: `TOOLS`, `client.request`, `Session` (for `--no-worker`), the old `cli.py` bodies for people commands.
- Produces: `main(argv) -> int`. `kimbim [--project P] [--json] [--no-worker] [--task ID] [--client NAME]
  <group> <verb> [--param value ...] [--dry-run]`. One `--param` per schema property (snake_case → kebab-case);
  values parse as JSON when they look like JSON (`[`, `{`, number, true/false), else text; `--elements` also
  accepts comma-separated GlobalIds or `selection`. `--task` falls back to `KIMBIM_TASK`. Help text from tool
  descriptions. Human output: a one-line summary per tool (`"Changed 4 windows (width 1.20 → 1.70 m)"`; generic
  fallback: counts of `changes`, or the result's top-level keys), `--json` prints the envelope.
  People commands (not tools): `project init [dir]`, `versions save -m MSG`, `versions show KEY`, `versions
  merge OPTION` (people only: agents never combine), `serve PROJECT`, `mcp`, `setup CLIENT`; `script run FILE
  MODEL` replaces `kimbim run` (offline batch, no gate: the person runs it). Project discovery: `--project`, else
  the current folder if it has `.kimbim` or exactly one `.kim`, else usage error.
- [ ] **Step 1: Tests**: `test_widen_windows_cli` (`--no-worker`, `elements set-dimensions --elements
  '{"kind":"window","level":"Level 1"}' --width +50cm --json` → ok, 4 modified), `test_help_lists_groups`,
  `test_exit_codes` (unknown option 2, `no_match` 1), `test_task_env` (`KIMBIM_TASK`), `test_versions_log`,
  `test_unicode_output` (title with ñ prints intact), port the still-meaningful parts of the old `test_cli.py`
  (init, save version, merge with `--resolve`).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Pass; `pixi run test-py` green.
- [ ] **Step 5:** Commit `feat(agent): kimbim CLI generated from the tool catalogue (D102)`.

### Task 13: MCP server and client setup

**Files:**
- Create: `python/kimbim/agent/mcp_server.py`, `python/kimbim/agent/clients.py`
- Modify: `pixi.toml` (`mcp` dependency: conda-forge if available, else `[pypi-dependencies]`), `THIRD_PARTY.md`
- Test: `tests/python/test_agent_mcp.py`, `tests/python/test_agent_setup.py`

**Interfaces:**
- Consumes: `TOOLS`, `client.request`.
- Produces: `kimbim mcp [--project P]` = stdio server (`mcp.server.lowlevel.Server` or `FastMCP`), name
  `kimbim`. Tools: one per catalogue entry, name `group_verb`, `inputSchema` = params plus optional `project`
  (required when the server has no `--project`) and `dry_run` for writes; descriptions = tool descriptions.
  Each MCP session is one `client` id (`"mcp-<clientInfo.name>"`); the server remembers the task it started.
  `snapshot_take` returns `ImageContent` (PNG base64) plus a text block with the JSON result. Resource
  `kimbim://project/info`. Server `instructions` (English, ≤ 25 lines): tasks and review, selectors, units,
  "take a snapshot to check your work", never accept your own option.
  `kimbim setup claude-desktop|claude-code|opencode [--project P] [--print]`: writes (or prints) the client's MCP
  config with command = the absolute path of the running interpreter + `-m kimbim mcp` (in development, the pixi
  env python with `PYTHONPATH`): Claude Desktop `claude_desktop_config.json` (`%APPDATA%/Claude` /
  `~/.config/Claude`) `mcpServers.kimbim`; Claude Code `.mcp.json` in the project's folder (or `--print` the
  `claude mcp add` line); opencode `opencode.json` `mcp.kimbim` (`{"type":"local","command":[...]}`) plus an
  `AGENTS.md` paragraph telling the agent the `kimbim` CLI exists. Existing files are merged, never replaced;
  other servers kept.
- [ ] **Step 1: Tests**: in-process MCP client (the SDK's memory transport) → `list_tools` includes
  `elements_set_dimensions` with `dry_run` in its schema; call `project_info`; call `snapshot_take` (skip without
  app) → one image block; `test_setup_merges_existing` for each client (existing other server kept, JSON valid).
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Pass.
- [ ] **Step 5:** Commit `feat(agent): kimbim mcp server and setup for Claude and opencode (D102)`.

### Task 14: Exit check, timings and docs

**Files:**
- Create: `tools/check_agent.py`, `docs/17-agent-tools.md`
- Modify: `pixi.toml` (task `agent = { cmd = "python tools/check_agent.py build/house.ifc build/agent",
  depends-on = ["house", "app-build", "build"] }`), `docs/03-versioning.md` (CLI section → new commands),
  `docs/15-scripting.md` ("Not yet" line), `docs/README.md` (index), `docs/decisions.md` (D102 status → "Decided;
  phase 1 built"), `README.md` / `CONTRIBUTING.md` CLI mentions

**Interfaces:**
- Consumes: everything above, through MCP only.
- [ ] **Step 1:** Write `check_agent.py`: make a versioned .kim from the house; through an in-process MCP client:
  `elements_find` windows on Level 1, `task_start` "Widen first-floor windows", `elements_set_dimensions`
  `+50cm`, `snapshot_take` `changes:"task"`, `task_finish`. Then assert with `Project`: option
  `agent/widen-first-floor-windows` has one version whose diff vs `main` is exactly those 4 windows (+ their wall
  openings) with width 1.7; `main` head unchanged; snapshot is a PNG with ≥ 100 colours. Print one JSON line
  with timings (`find`, `set_dimensions`, `snapshot` ms).
- [ ] **Step 2:** `pixi run agent` → passes.
- [ ] **Step 3:** Time on Clinic (`spikes/corpus/Clinic_Architectural.ifc` → .kim): run the same flow on any 10
  windows with `--project`; record find / write / snapshot ms in `docs/17-agent-tools.md` (targets: write < 2 s,
  snapshot < 3 s; record, don't block).
- [ ] **Step 4:** Write `docs/17-agent-tools.md` for architects: what agents can do, connecting (`kimbim setup`),
  tasks and review (accepting happens in the app — phase 2 adds the in-app Review bar; until then *Versions ›
  Combine options*), the tool list (generated table: add `kimbim help --markdown` and paste its output),
  snapshots, settings `agent_changes` / `agent_scripts`, limits of phase 1 (offline only, one task per project).
  Spanish texts: `pixi run check-translations` green for any new UI strings (none expected in phase 1).
- [ ] **Step 5:** Full verification: `pixi run test`, `pixi run golden`, `pixi run app-test`, `pixi run m5`,
  `pixi run agent` all green.
- [ ] **Step 6:** Commit `docs(agent): agent tools guide, CLI docs, exit check (D102 phase 1)`.

---

## Self-review notes

- Spec coverage: §4.1 → Tasks 2, 12, 13; §4.2 offline → 3, 9 (live = phase 2); §4.3 → 5 (Review bar = phase 2;
  offline proposals are listed by `versions.options` and `task.status`); §5 table → 4, 6, 7, 8; §5.1 → 1, 2, 4;
  §5.2 → 8; §6 → 10, 11; §7 → 12, 13; §11 → 14. Help › Connect an AI agent is a phase 2 app change.
- Deviation: tasks are stored under `<work>/.kimbim/agent/` or the data dir (spec said the working folder; same
  intent, and they travel with the .kim). One open task per project in phase 1.
