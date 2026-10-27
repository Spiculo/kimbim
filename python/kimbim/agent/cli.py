# SPDX-License-Identifier: GPL-3.0-or-later
"""The `kimbim` command line (D102, spec §7): one subcommand per agent tool, generated from the tool catalogue
(`kimbim <group> <verb> --param value ...`), plus the commands people use that agents never get (`project init`,
`versions save|show|merge|export-dxf|status|branch|switch|tag`, `script run FILE [MODEL]`, `serve`, `mcp`, `setup`)
and `help [--markdown]` (docs/17-agent-tools.md's tool table is its Markdown output).

A tool command goes to the project's background worker (started if needed) or, with `--no-worker`, runs in this
process: the project is opened, the tool runs, the task it started on its own is finished and the project is saved
and closed. Exit codes: 0 ok, 1 tool or engine error, 2 usage error."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

from .. import _core
from ..project import Changes, KimbimError, MergeConflicts, Project
from . import client as _client
from . import messages
from .catalogue import TOOLS, AgentError, call_tool
from .session import Session

SYMBOL = {"added": "+", "modified": "~", "removed": "-"}
MAX_LINES = 200
GROUP_HELP = {
    "project": "the project, its settings and levels", "versions": "saved versions, options, milestones",
    "task": "the task an agent's changes go in", "elements": "find, read and edit elements",
    "create": "create walls, slabs, openings, rooms...", "objects": "library objects", "drawings": "drawings",
    "sheets": "sheets", "schedules": "schedules", "checks": "model checks", "levels": "levels",
    "selection": "the app's selection", "script": "run Python scripts", "snapshot": "pictures of the model",
    "serve": "keep a project open for agent commands", "mcp": "MCP server for AI agents",
    "setup": "configure an AI client", "help": "this help, or the agent tools as a Markdown table",
}

_JSONISH = re.compile(r"^\s*([\[{]|-?\d+(\.\d+)?([eE][-+]?\d+)?\s*$|true\s*$|false\s*$|null\s*$)")


# ---------------------------------------------------------------- tool parameters on the command line

def _types(schema: dict) -> set[str]:
    out: set[str] = set()
    if "type" in schema:
        out |= {schema["type"]} if isinstance(schema["type"], str) else set(schema["type"])
    for option in schema.get("oneOf", ()):
        out |= _types(option)
    return out


def _words(schema: dict) -> set[str]:
    """Fixed words a parameter accepts as text (enum values), e.g. "selection"."""
    out = set(schema.get("enum", ()))
    for option in schema.get("oneOf", ()):
        out |= _words(option)
    return {w for w in out if isinstance(w, str)}


def parse_value(text: str, schema: dict):
    """A command line value as the tool wants it: JSON when it looks like JSON (list, object, number,
    true/false) unless the parameter is text only; an enum word ("selection") stays text; a parameter that
    takes a list also takes comma separated items (`--elements G1,G2`)."""
    types = _types(schema)
    if text in _words(schema):
        return text
    if types and types <= {"string"}:
        return text
    if _JSONISH.match(text):
        try:
            return json.loads(text)
        except ValueError:
            if text.lstrip()[:1] in ("[", "{"):
                raise ValueError(f"not valid JSON: {text}") from None
    if "array" in types and not types - {"array", "string", "object"}:
        return [p.strip() for p in text.split(",") if p.strip()]
    return text


def _option(name: str) -> str:
    return "--" + name.replace("_", "-")


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?(?<!\.\.)[.!?])(\s|$)", " ".join(text.split()))  # "wall... tables" goes on
    return m.group(1) if m else " ".join(text.split())


def _h(text: str) -> str:
    return text.replace("%", "%%")


def _add_globals(p: argparse.ArgumentParser, top: bool, skip: frozenset = frozenset(),
                 project_help: str = "") -> None:
    """The options every command takes: before the group on the top parser, and again after the verb (there
    they set a value only when given, so they never undo one given earlier)."""
    def d(v):
        return v if top else argparse.SUPPRESS

    for flag, kw in (
            ("project", dict(dest="g_project", default=d(None), metavar="P",
                             help=project_help or
                             "the project: a folder, .kim or .ifc (default: the current folder)")),
            ("json", dict(dest="g_json", action="store_true", default=d(False), help="print the result as JSON")),
            ("no-worker", dict(dest="g_no_worker", action="store_true", default=d(False),
                               help="run in this process instead of the project's background worker")),
            ("task", dict(dest="g_task", default=d(""), metavar="ID", help="the task to work in (default: $KIMBIM_TASK)")),
            ("client", dict(dest="g_client", default=d("cli"), metavar="NAME",
                            help="who is calling (names the author of agent versions)"))):
        if flag not in skip:
            p.add_argument("--" + flag, **kw)


def fix_negative_values(argv: list[str], parser: argparse.ArgumentParser) -> list[str]:
    """argparse takes `--width -10%` for a flag; a value after an option that takes one is joined to it
    (`--width=-10%`) unless it is itself one of the CLI's options."""
    takes: dict[str, bool] = {}
    known: set[str] = set()

    def walk(p: argparse.ArgumentParser) -> None:
        for a in p._actions:
            if isinstance(a, argparse._SubParsersAction):
                for sub in a.choices.values():
                    walk(sub)
            for o in a.option_strings:
                known.add(o)
                value = a.nargs is None and not isinstance(a, argparse._StoreTrueAction)
                takes[o] = takes.get(o, False) or value

    walk(parser)
    out, i = [], 0
    while i < len(argv):
        tok = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else ""
        if takes.get(tok) and tok.startswith("--") and nxt.startswith("-") and len(nxt) > 1 and nxt not in known \
                and not nxt.startswith("--"):
            out.append(f"{tok}={nxt}")
            i += 2
            continue
        out.append(tok)
        i += 1
    return out


def build_parser() -> argparse.ArgumentParser:
    from .. import agent  # noqa: F401  (importing the package fills the catalogue)

    p = argparse.ArgumentParser(
        prog="kimbim", description="KimBim: versioned IFC projects and agent tools.",
        epilog="`kimbim <group> --help` lists a group's commands, `kimbim <group> <verb> --help` one command.")
    _add_globals(p, True)
    top = p.add_subparsers(dest="group", metavar="<group>", required=True)
    verbs: dict[str, argparse._SubParsersAction] = {}

    def group(name: str) -> argparse._SubParsersAction:
        if name not in verbs:
            gp = top.add_parser(name, help=GROUP_HELP.get(name, name), description=GROUP_HELP.get(name, name))
            verbs[name] = gp.add_subparsers(dest="verb", metavar="<verb>", required=True)
        return verbs[name]

    for name, t in TOOLS.items():
        if name.startswith("_") or name == "script.run":  # `kimbim script run` below does both
            continue
        g, verb = name.split(".", 1)
        lp = group(g).add_parser(verb.replace("_", "-"), help=_h(_first_sentence(t.description)),
                                 description=t.description)
        props = t.params.get("properties", {})
        dests = {}
        for prop, schema in props.items():
            dests["p_" + prop] = prop
            boolean = _types(schema) == {"boolean"}
            lp.add_argument(_option(prop), dest="p_" + prop, default=argparse.SUPPRESS,
                            required=prop in t.params.get("required", ()), nargs="?" if boolean else None,
                            const="true" if boolean else None, metavar="true|false" if boolean else prop.upper(),
                            help=_h(schema.get("description", "")))
        _add_globals(lp, False, frozenset({"task"} if "task" in props else ()))
        lp.set_defaults(handler=_tool_command, tool=name, dests=dests)
    _people(group, top)
    return p


def tool_args(ns: argparse.Namespace) -> dict:
    """The tool's arguments from a parsed command line (only the parameters that were given)."""
    schema = TOOLS[ns.tool].params["properties"]
    try:
        return {prop: parse_value(getattr(ns, dest), schema[prop]) for dest, prop in ns.dests.items() if hasattr(ns, dest)}
    except ValueError as e:
        raise UsageError(str(e)) from None


# ---------------------------------------------------------------- running a tool

class UsageError(Exception):
    pass


def discover(project: str | None) -> str:
    """--project, else the current folder when it has `.kimbim` or exactly one `.kim`."""
    if project:
        return str(pathlib.Path(project))
    here = pathlib.Path.cwd()
    if (here / ".kimbim").is_dir():
        return str(here)
    kims = sorted(here.glob("*.kim"))
    if len(kims) == 1:
        return str(kims[0])
    raise UsageError(messages.text("cli_no_project"))


def _tool_command(ns) -> int:
    return _call(ns, ns.tool, tool_args(ns))


def _call(ns, name: str, args: dict) -> int:
    project = discover(ns.g_project)
    task = ns.g_task or os.environ.get("KIMBIM_TASK", "")
    if ns.g_no_worker:
        envelope = _run_in_process(project, name, args, ns.g_client, task)
    else:
        envelope = _client.request(project, name, args, client=ns.g_client, task=task)
    return _report(name, envelope, ns.g_json, args)


def _run_in_process(project: str, name: str, args: dict, client: str, task: str) -> dict:
    from .worker import _stop  # parks an open task, saves, closes: what the worker does when it ends

    try:
        session = Session.open(project, client)
    except AgentError as ex:
        return ex.envelope()
    except Exception as ex:  # noqa: BLE001  (an agent sees an error, not a traceback)
        return AgentError("bridge_error", hint=str(ex)).envelope()
    try:
        session.tasks.resume(client, task)
        envelope = call_tool(session, name, args, client=client, task_id=task)
        implicit = session.tasks.implicit_task()
        if envelope.get("ok") and implicit:  # a write that started its own task: finish it so it is saved
            done = call_tool(session, "task.finish", {"summary": f"kimbim {name.replace('.', ' ')}"},
                             client=client, task_id=implicit)
            if done.get("ok"):
                envelope.setdefault("changes", {})["task"] = done["result"]["task"]
            else:  # the write is made: the error says so, with the write's result
                error = dict(done["error"])
                error["details"] = {**error.get("details", {}), "write": {
                    k: envelope[k] for k in ("result", "changes") if k in envelope}}
                return {"ok": False, "error": error}
        return envelope
    finally:
        _stop(session)


# ---------------------------------------------------------------- output

def _t(code: str, **fmt) -> str:
    return messages.text(code, **fmt)


def _brief(v) -> str:
    if isinstance(v, list):
        return _t("sum_items", n=len(v))
    if isinstance(v, dict):
        return "{" + ", ".join(list(v)[:6]) + (", ..." if len(v) > 6 else "") + "}"
    return str(v)


def _kind_of(envelope: dict, n: int) -> str:
    """"windows" when n of the modified elements are labelled Window..."""
    words: dict[str, int] = {}
    for m in (envelope.get("changes") or {}).get("modified", ()):
        word = (m.get("label") or "").split(" ", 1)[0].lower()
        if word:
            words[word] = words.get(word, 0) + 1
    hit = next((w for w, c in words.items() if c == n), None)
    return hit + ("" if hit.endswith("s") else "s") if hit else "elements"


def _dry(envelope: dict) -> bool:
    return bool((envelope.get("changes") or {}).get("dry_run"))


def _sum_dimensions(envelope, args):
    n = envelope["result"]["changed"]
    what = ", ".join(f"{k} {args[k]}" for k in ("width", "height", "sill", "length") if k in args)
    return _t("sum_dims_would" if _dry(envelope) else "sum_dims", n=n, kind=_kind_of(envelope, n), what=what)


def _sum_count(code: str, key: str = "elements"):
    def summary(envelope, args):
        return _t(code + ("_would" if _dry(envelope) else ""), n=envelope["result"][key],
                  name=args.get("name", ""))
    return summary


def _sum_create(kind: str):
    def summary(envelope, args):
        if _dry(envelope):
            return _t("sum_created_would", kind=kind)
        return _t("sum_created", kind=kind, guid=envelope["result"]["guids"][0])
    return summary


def _sum_task_start(envelope, args):
    r = envelope["result"]
    return _t("sum_task_started", title=r["title"], id=r["id"], mode=r["mode"])


def _sum_task_finish(envelope, args):
    r = envelope["result"]["task"]
    return _t("sum_task_finished", title=r["title"], id=r["id"], status=r["status"])


# A one-line summary for the main tools: fn(envelope, args) -> text. Others use the generic line.
SUMMARIES = {
    "elements.set_dimensions": _sum_dimensions,
    "elements.rename": _sum_count("sum_renamed"),
    "elements.move": _sum_count("sum_moved"),
    "elements.delete": _sum_count("sum_deleted", "requested"),
    "task.start": _sum_task_start,
    "task.finish": _sum_task_finish,
    "snapshot.take": lambda envelope, args: _t("sum_snapshot", path=envelope["result"]["path"]),
    **{"create." + k: _sum_create(k) for k in ("wall", "slab", "column", "beam", "opening", "room")},
}


def summarize(name: str, envelope: dict, args: dict | None = None) -> str:
    """One line for a person: the tool's own summary, else the counts in `changes`, else the result's keys."""
    args = args or {}
    result, changes = envelope.get("result"), envelope.get("changes")
    if name == "versions.log" and isinstance(result, dict):
        return "\n".join(f"{v['short']}  {v['author']}  {(v['message'].strip().splitlines() or [''])[0]}"
                         for v in result["versions"]) or _t("cli_no_versions")
    if name in SUMMARIES:
        try:
            return SUMMARIES[name](envelope, args)
        except (KeyError, TypeError, IndexError):
            pass  # an unexpected result shape: the generic line
    if changes is not None:
        counts = [_t("sum_" + k, n=len(changes[k])) for k in ("added", "modified", "removed") if changes.get(k)]
        if not counts:
            return _t("sum_no_changes")
        what = ", ".join(counts)
        line = _t("sum_would", what=what) if changes.get("dry_run") else _t("sum_changed", what=what)
        task = changes.get("task")
        return line + (_t("sum_task", id=task["id"], status=task["status"]) if task else "")
    if isinstance(result, dict) and result:
        return ", ".join(f"{k}: {_brief(v)}" for k, v in result.items())
    if isinstance(result, list):
        return _t("sum_items", n=len(result))
    return _t("sum_ok") if result in (None, "", {}) else str(result)


def _error_lines(error: dict) -> None:
    print(_t("cli_error", message=error.get("message", "failed")), file=sys.stderr)
    if error.get("hint"):
        print(f"  {error['hint']}", file=sys.stderr)


def _report(name: str, envelope: dict, as_json: bool, args: dict | None = None) -> int:
    if as_json:
        print(json.dumps(envelope, ensure_ascii=False, indent=1, default=str))
        return 0 if envelope.get("ok") else 1
    if not envelope.get("ok"):
        error = envelope.get("error") or {}
        write = (error.get("details") or {}).get("write")
        if write:  # the write is made but its task did not finish: say what it did, then the error
            print(summarize(name, {"ok": True, **write}, args))
        _error_lines(error)
        return 1
    print(summarize(name, envelope, args))
    for w in envelope.get("warnings", ()):
        print(_t("cli_warning", message=w), file=sys.stderr)
    return 0


# ---------------------------------------------------------------- people commands (agents never get these)

def _print_changes(changes: Changes, as_json: bool = False):
    if as_json:
        data = {k: [vars(c) for c in changes.of(k)] for k in ("added", "modified", "removed")}
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return
    print(f"{len(changes.added)} added, {len(changes.modified)} modified, {len(changes.removed)} removed")
    for c in changes.items[:MAX_LINES]:
        name = f" {c.name!r}" if c.name else ""
        print(f"  {SYMBOL[c.kind]} {c.ifc_type}{name}  [{c.key}]")
    if len(changes.items) > MAX_LINES:
        print(f"  ... {len(changes.items) - MAX_LINES} more (use --json for all)")


def _people(group, top) -> None:
    def leaf(name_group: str, name: str, handler, **kw) -> argparse.ArgumentParser:
        lp = group(name_group).add_parser(name, **kw)
        _add_globals(lp, False)
        lp.set_defaults(handler=handler)
        return lp

    s = leaf("project", "init", _init, help="make a folder a KimBim project", description="Make a folder a KimBim project.")
    s.add_argument("dir", nargs="?")
    s = leaf("versions", "save", _save, help="save a new version (of an IFC file, or of the open project)",
             description="Save a new version. With FILE, that IFC file becomes the version; without, the project's "
                         "working model (the project must not be open in a worker or the app).")
    s.add_argument("file", nargs="?")
    s.add_argument("-m", "--message", required=True)
    s = leaf("versions", "status", _status, help="show what saving an IFC file would change")
    s.add_argument("file")
    s = leaf("versions", "show", _show, help="print one canonical record")
    s.add_argument("key")
    s.add_argument("--rev", default="HEAD")
    s = leaf("versions", "branch", _branch, help="list or create design options (branches)")
    s.add_argument("name", nargs="?")
    s.add_argument("--rev", default="HEAD")
    s = leaf("versions", "switch", _switch, help="switch to a design option (branch)")
    s.add_argument("name")
    s = leaf("versions", "tag", _tag, help="list, set or delete milestones (annotated tags)")
    s.add_argument("name", nargs="?")
    s.add_argument("-m", "--message", default="")
    s.add_argument("--rev", default="HEAD")
    s.add_argument("--delete", action="store_true")
    s = leaf("versions", "merge", _merge, help="combine another design option into the current one (people only)")
    s.add_argument("option")
    s.add_argument("-m", "--message", default="")
    s.add_argument("--resolve", action="append", default=[], metavar="CONFLICT=CHOICE",
                   help="a conflict's choice (ours, theirs, or one of its options); repeatable")
    s = leaf("versions", "export-dxf", _export_dxf, help="write a version's drawings and sheets as DXF")
    s.add_argument("out", help="a folder, or a .dxf file for one drawing or sheet")
    s.add_argument("--rev", default="HEAD")
    s.add_argument("--force", action="store_true")
    s.add_argument("--drawing", action="append", default=[], metavar="NAME",
                   help="a drawing to export, by name (repeatable; default every drawing and sheet)")
    s.add_argument("--sheet", action="append", default=[], metavar="NUMBER", help="a sheet to export, by number (repeatable)")
    s.add_argument("--layers", choices=("layer", "kind"), default="layer", help="layers by KimBim layer (default) or by element kind")
    s.add_argument("--purpose", default="", help="the purpose (pens, visibility) to draw with")
    s = leaf("script", "run", _script_run, help="run a Python script on the project, or on an IFC model offline (D92)",
             description="With MODEL: a batch job on that IFC file, offline: the script runs in the console's namespace "
                         "(ifc, selection(), bridge...) and the changed model is written back. Without MODEL: the "
                         "script runs on the project like the script.run tool (needs agent_scripts on; as a task).")
    s.add_argument("script", help="the Python script to run")
    s.add_argument("model", nargs="?", help="the IFC model it edits (omit to run on the project)")
    s.add_argument("-o", "--out", default="", help="write the changed model here (default: the model, in place)")
    s.add_argument("--select", action="append", default=[], metavar="GLOBALID",
                   help="elements the script sees as the selection (repeatable)")
    s.add_argument("--dry-run", action="store_true", help="on a project: report what would change, then roll it back")
    sp = top.add_parser("serve", help=GROUP_HELP["serve"], description=GROUP_HELP["serve"])
    sp.add_argument("project")
    sp.add_argument("--idle", type=float, default=None, help="seconds without a request before exiting")
    sp.set_defaults(handler=_serve)
    only_project = frozenset({"json", "no-worker", "task", "client"})
    mp = top.add_parser("mcp", help=GROUP_HELP["mcp"], description=GROUP_HELP["mcp"] + " (stdio). Without --project, "
                        "every tool call names its project.")
    _add_globals(mp, False, only_project,
                 project_help="the project: a folder, .kim or .ifc (default: none; every tool call names it)")
    mp.set_defaults(handler=_mcp)
    st = top.add_parser("setup", help=GROUP_HELP["setup"],
                        description="Write the AI client's configuration for `kimbim mcp` (merged into its file).")
    st.add_argument("client", choices=("claude-desktop", "claude-code", "opencode"))
    st.add_argument("--print", dest="print_only", action="store_true",
                    help="print the configuration (for claude-code, the `claude mcp add` line) instead of writing it")
    _add_globals(st, False, only_project)
    st.set_defaults(handler=_setup)
    hp = top.add_parser("help", help=GROUP_HELP["help"], description=GROUP_HELP["help"] + ".")
    hp.add_argument("--markdown", action="store_true", help="print the agent tools as a Markdown table")
    hp.set_defaults(handler=_help)


def _init(ns) -> int:
    target = pathlib.Path(ns.dir or ns.g_project or ".")
    Project.init(target)
    print(f"Initialized KimBim project in {target.resolve()}")
    return 0


def _save(ns) -> int:
    if ns.file:
        proj = Project.open(discover(ns.g_project))
        cid, changes = proj.commit(ns.file, ns.message)
        print(f"[{proj.current_branch()} {cid[:10]}] {ns.message}")
        _print_changes(changes)
        return 0
    from .. import versioning as V
    from .worker import _stop

    session = Session.open(discover(ns.g_project), ns.g_client)
    try:
        out = json.loads(V.save_version(ns.message))
        if not out.get("ok"):
            raise KimbimError(out.get("error", "could not save the version"))
        print(f"[{out.get('option', '')} {str(out.get('id', ''))[:10]}] {ns.message}".replace("[ ", "["))
    finally:
        _stop(session)
    return 0


def _status(ns) -> int:
    changes = Project.open(discover(ns.g_project)).status(ns.file)
    _print_changes(changes) if changes else print("no changes")
    return 0


def _show(ns) -> int:
    print(json.dumps(Project.open(discover(ns.g_project)).show(ns.key, ns.rev), ensure_ascii=False, indent=1, sort_keys=True))
    return 0


def _branch(ns) -> int:
    proj = Project.open(discover(ns.g_project))
    if ns.name:
        proj.create_branch(ns.name, ns.rev)
        print(f"created design option {ns.name}")
    else:
        current = proj.current_branch()
        for b in proj.branches():
            print(f"{'*' if b == current else ' '} {b}")
    return 0


def _switch(ns) -> int:
    Project.open(discover(ns.g_project)).switch(ns.name)
    print(f"switched to {ns.name}")
    return 0


def _tag(ns) -> int:
    proj = Project.open(discover(ns.g_project))
    if ns.name and ns.delete:
        proj.delete_tag(ns.name)
        print(f"deleted milestone {ns.name}")
    elif ns.name:
        proj.tag(ns.name, ns.message, ns.rev)
        print(f"milestone {ns.name} on {proj.repo.resolve(ns.rev)[:10]}")
    else:
        for t in proj.tags():
            first_line = (t.message.strip().splitlines() or [""])[0]
            print(f"{t.name}  {t.target[:10]}  {first_line}")
    return 0


def _merge(ns) -> int:
    proj = Project.open(discover(ns.g_project))
    resolutions = dict(r.rsplit("=", 1) for r in ns.resolve if "=" in r)
    message = ns.message or f"Combine {ns.option} into {proj.current_branch()}"
    try:
        cid = proj.merge(ns.option, message, resolutions)
    except MergeConflicts as e:
        conflicts = [c.to_dict() for c in e.result.conflicts if c.id in e.result.unresolved]
        if ns.g_json:
            print(json.dumps(conflicts, ensure_ascii=False, indent=1, default=str))
        else:
            print(f"{len(conflicts)} conflict(s); choose with --resolve ID=CHOICE:")
            for c in conflicts:
                what = c["attribute"] or ""
                if c["property"]:
                    what += f"[{c['property']}]"
                print(f"  {c['id']}  {c['kind']}  {c['ifc_type']} {c['name']!r} {what}  options: {', '.join(c['options'])}")
                if c["kind"] in ("attribute", "property", "class"):
                    print(f"      base {json.dumps(c['base'], default=str)[:80]}  ours {json.dumps(c['ours'], default=str)[:80]}"
                          f"  theirs {json.dumps(c['theirs'], default=str)[:80]}")
        return 1
    print(f"[{proj.current_branch()} {cid[:10]}] {message}")
    return 0


def _script_run(ns) -> int:
    if ns.model:
        return _run_script(ns)
    code = pathlib.Path(ns.script).read_text(encoding="utf-8")
    args = {"code": code, **({"dry_run": True} if ns.dry_run else {})}
    return _call(ns, "script.run", args)


def _run_script(ns) -> int:
    """A headless batch job (D92): the script runs in the console's namespace (ifc, selection(), bridge...)
    against the model and the changed model is written back. The person runs it, so there is no task gate."""
    from .. import app_bridge, console

    opened = json.loads(app_bridge.open_model(ns.model))
    if not opened.get("ok"):
        raise KimbimError(opened.get("error", "could not open the model"))
    console.reset()
    result = json.loads(console.console_run_file(ns.script, json.dumps(ns.select)))
    if not result.get("ok"):
        raise KimbimError(result.get("error", "the script could not run"))
    sys.stdout.write(result.get("output", ""))
    if result.get("traceback"):
        print(result["traceback"], file=sys.stderr)
        return 1
    if result.get("edited"):
        out = ns.out or ns.model
        saved = json.loads(app_bridge.save(out))
        if not saved.get("ok"):
            raise KimbimError(saved.get("error", "could not save the model"))
        print(f"wrote {out}")
    return 0


def _export_dxf(ns) -> int:
    """Drawings and sheets of a version as DXF files (D83): the version is written to a temporary IFC,
    opened the way the app opens it, and exported with the built-in graphics (or --purpose)."""
    import tempfile

    from .. import app_bridge, dxf

    proj = Project.open(discover(ns.g_project))
    with tempfile.TemporaryDirectory(prefix="kimbim-dxf-") as tmp:
        ifc = proj.export(pathlib.Path(tmp) / "version.ifc", ns.rev, overwrite=True, one_owner=True)
        opened = json.loads(app_bridge.open_model(str(ifc)))
    if not opened.get("ok"):
        raise KimbimError(opened.get("error", "could not open the version"))
    targets = json.loads(dxf.dxf_targets())
    by_name = {d["name"]: d["guid"] for d in targets["drawings"]}
    numbers = {s["number"] for s in targets["sheets"]}
    missing = [n for n in ns.drawing if n not in by_name] + [n for n in ns.sheet if n not in numbers]
    if missing:
        raise KimbimError(f"no drawing or sheet called {', '.join(missing)} in {ns.rev}")
    items = [{"drawing": by_name[n]} for n in ns.drawing] + [{"sheet": n} for n in ns.sheet]
    if not items:
        items = [{"drawing": d["guid"]} for d in targets["drawings"]] + [{"sheet": s["number"]} for s in targets["sheets"]]
    if not items:
        raise KimbimError(f"{ns.rev} has no drawings or sheets")
    options = json.dumps({"layers": ns.layers, "purpose": ns.purpose or None})
    out = pathlib.Path(ns.out)
    if out.suffix.lower() == ".dxf":
        if len(items) != 1:
            raise KimbimError("a .dxf file holds one drawing or sheet; give a folder for more")
        if out.exists() and not ns.force:
            raise KimbimError(f"{out} already exists (use --force to overwrite)")
        item = items[0]
        r = json.loads(dxf.export_drawing_dxf(item["drawing"], str(out), options) if "drawing" in item
                       else dxf.export_sheet_dxf(item["sheet"], str(out), options))
        files, errors = ([r["path"]], []) if r.get("ok") else ([], [{"item": str(out), "error": r.get("error")}])
    else:
        r = json.loads(dxf.export_dxf(json.dumps(items), str(out), options))
        if "files" not in r:
            raise KimbimError(r.get("error", "export failed"))
        files, errors = r["files"], r["errors"]
    for f in files:
        print(f"wrote {f}")
    for e in errors:
        print(_t("cli_error", message=f"{e['item']}: {e['error']}"), file=sys.stderr)
    return 1 if errors else 0


def _serve(ns) -> int:
    from .worker import main as serve_main

    return serve_main([ns.project] + ([] if ns.idle is None else ["--idle", str(ns.idle)]))


def _mcp(ns) -> int:
    from .mcp_server import serve

    return serve(ns.g_project)


def _setup(ns) -> int:
    from . import clients

    try:
        text, written = clients.setup(ns.client, ns.g_project, ns.print_only)
    except (clients.SetupError, OSError) as e:
        print(_t("cli_error", message=e), file=sys.stderr)
        return 1
    if text:
        print(text)
    for path in written:
        print(_t("setup_wrote", path=path))
    if written:
        print(_t("setup_restart", client=ns.client))
    return 0


def tools_markdown() -> str:
    """The agent tools as a Markdown table, in the groups' order: the MCP name, the command line, what it does and
    whether it changes the model (docs/17-agent-tools.md pastes it)."""
    from .. import agent  # noqa: F401  (importing the package fills the catalogue)

    order = list(GROUP_HELP)
    names = sorted((n for n in TOOLS if not n.startswith("_")),
                   key=lambda n: (order.index(n.split(".")[0]) if n.split(".")[0] in order else len(order), n))
    lines = ["| Tool (MCP) | Command line | What it does | Changes the model |", "|---|---|---|---|"]
    for name in names:
        group, verb = name.split(".", 1)
        what = _first_sentence(TOOLS[name].description).replace("|", "\\|")
        lines.append(f"| `{name.replace('.', '_')}` | `kimbim {group} {verb.replace('_', '-')}` | {what} | "
                     f"{'yes' if TOOLS[name].writes else ''} |")
    return "\n".join(lines)


def _help(ns) -> int:
    if ns.markdown:
        print(tools_markdown())
    else:
        build_parser().print_help()
    return 0


# ---------------------------------------------------------------- main

def _utf8_streams():
    """Names can be in any script; Windows pipes default to the legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    try:
        parser = build_parser()
        ns = parser.parse_args(fix_negative_values(list(sys.argv[1:] if argv is None else argv), parser))
    except SystemExit as e:  # --help is 0, a usage error 2
        return e.code if isinstance(e.code, int) else 2
    try:
        return ns.handler(ns)
    except UsageError as e:
        print(_t("cli_error", message=e), file=sys.stderr)
        return 2
    except AgentError as e:
        print(_t("cli_error", message=e), file=sys.stderr)
        return 1
    except KimbimError as e:
        print(_t("cli_error", message=e), file=sys.stderr)
        for m in getattr(e, "messages", [])[:20]:
            print(f"  {m}", file=sys.stderr)
        return 1
    except (OSError, _core.RepoError) as e:
        print(_t("cli_error", message=e), file=sys.stderr)
        return 1
