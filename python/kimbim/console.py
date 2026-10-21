# SPDX-License-Identifier: GPL-3.0-or-later
"""The Python console (D82, doc 14 section 20): code typed in the app's Console panel, or a script file, runs
in the embedded interpreter in one persistent namespace with the open model and a few helpers.

The app runs `console_run` on a worker thread while a modal "Running..." dialog keeps the window painting;
its Stop button calls `console_stop`, which makes the script raise KeyboardInterrupt at its next line of
user code (never inside KimBim's own code, so an undo step is never left half-recorded).
Same protocol as app_bridge for the bridge functions: strings in, JSON out, never raise.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import linecache
import threading
import traceback

from . import app_bridge as B

HELP = """KimBim Python console
  ifc               the open model (an ifcopenshell.file)
  ifcopenshell      IfcOpenShell (ifcopenshell.api, ifcopenshell.util.element, ...)
  kimbim, bridge    KimBim's modules; bridge = kimbim.app_bridge (the app's own commands, JSON in/out)
  selection()       the selected elements (entities)
  select(items)     select elements: GlobalIds, entities, or a list of them ([] clears)
  with edit():      join the run's undo step explicitly (the run is one step already)
  refresh()         redraw every element when the run ends
  help_kimbim()     this text
Enter runs, Shift+Enter adds a line, Up/Down recall earlier input; the value of a last expression is
printed. Stop (or Ctrl+C in the console) interrupts a script at its next line. Every run is one undo
step (Ctrl+Z) and a run that changes nothing leaves none."""

_ns: dict | None = None
_lock = threading.Lock()
_count = 0  # numbers the inputs: <console-1>, <console-2>, ...
_user_files: set[str] = set()  # code names whose lines Stop may interrupt
_worker: int | None = None  # thread running a script
_stop = False
_run: dict = {}  # this run's requests: selection, select, refresh


def help_kimbim() -> None:
    print(HELP)


def _guid(item) -> str:
    if isinstance(item, str):
        return item
    guid = getattr(item, "GlobalId", None)
    if not guid:
        raise TypeError(f"{item!r} has no GlobalId")
    return guid


def selection() -> list:
    """The selected elements, as entities of `ifc` (the selection when the run started, or set by select())."""
    out = []
    for g in _run.get("select") if _run.get("select") is not None else _run.get("selection", []):
        try:
            out.append(B._model.by_guid(g))
        except (RuntimeError, AttributeError):
            pass
    return out


def select(items) -> list:
    """Select elements in the app (applied when the run ends): GlobalIds, entities or a list of them."""
    if items is None:
        items = []
    elif isinstance(items, str) or hasattr(items, "GlobalId"):
        items = [items]
    guids = list(dict.fromkeys(_guid(i) for i in items))
    _run["select"] = guids
    return guids


def refresh() -> None:
    """Redraw every element and refresh the panels when the run ends."""
    _run["refresh"] = True


_HUBS = ("IfcRepresentationContext", "IfcOwnerHistory", "IfcUnitAssignment", "IfcNamedUnit", "IfcProject",
         "IfcRelationship", "IfcActor", "IfcPerson", "IfcOrganization", "IfcApplication", "IfcPresentationStyle",
         "IfcMaterialDefinition", "IfcMaterialList", "IfcMaterialUsageDefinition")
_LIMIT = 20000


def _is(e, classes) -> bool:
    return any(e.is_a(c) for c in classes)


def _touched(f, operations) -> tuple[list[str], list[str]] | None:
    """The elements whose shape a transaction may have changed (still there) and the ones it removed, from
    the entities it created, edited or deleted. None when it can't tell (redraw everything)."""
    removed, seeds = [], set()
    for op in operations:
        action = op.get("action")
        if action == "delete":
            value = op.get("value") or {}
            if value.get("GlobalId"):
                removed.append(value["GlobalId"])
            for ids in (op.get("inverses") or {}):
                seeds.add(ids)
        elif action == "create":
            seeds.add((op.get("value") or {}).get("id"))
        elif action == "edit":
            seeds.add(op.get("id"))
        elif action == "batch_delete":
            seeds.update(op.get("inverses") or {})
    changed, seen, todo = [], set(), [s for s in seeds if isinstance(s, int)]
    while todo:
        i = todo.pop()
        if i in seen:
            continue
        seen.add(i)
        if len(seen) > _LIMIT:
            return None
        try:
            e = f.by_id(i)
        except RuntimeError:
            continue
        if e.is_a("IfcProduct"):
            changed.append(e.GlobalId)
            for rel in getattr(e, "VoidsElements", None) or ():  # an opening changes its host's shape
                changed.append(rel.RelatingBuildingElement.GlobalId)
            continue
        if e.is_a("IfcRelVoidsElement"):
            changed += [e.RelatingBuildingElement.GlobalId, e.RelatedOpeningElement.GlobalId]
            continue
        if e.is_a("IfcRepresentationContext"):
            return None  # every shape may depend on it
        if _is(e, _HUBS):
            continue
        todo.extend(x.id() for x in f.get_inverse(e))
    return list(dict.fromkeys(changed)), list(dict.fromkeys(removed))


def _finish_step() -> bool:
    """Close the open step as one undo step, or drop it when it changed nothing (D92). Returns whether a
    step was kept."""
    operations = B._model.transaction.operations if B._model.transaction else None
    found = _touched(B._model, operations) if operations is not None else None
    if found is None:
        _run["refresh"] = True
        found = ([], [])
    changed, removed = found
    changed = [*changed, *B._step[0]]
    removed = [*removed, *B._step[1]]
    B._step = None
    if not changed and not removed and not operations:
        B._end_step_without_change()  # nothing happened: no empty undo step
        return False
    result = B._follow_ups(len(changed), changed, removed)
    B._commit(*result)
    return True


@contextlib.contextmanager
def edit():
    """`with edit(): ...`: the changes made in the block are one undo step, and the views update when the
    run ends. KimBim commands called inside (bridge.create_wall(...), ...) join the same step. Every run
    is already one undo step (D92), so edit() simply joins it; used stand-alone it opens its own."""
    if B._model is None:
        raise RuntimeError("no model open")
    if B._step is not None:  # already inside the run's own step: join it
        yield B._model
        return
    B._begin()
    B._step = ([], [])
    try:
        yield B._model
        _finish_step()
    except BaseException as failure:
        B._step = None
        B._abort(failure)
        raise


def namespace() -> dict:
    global _ns
    if _ns is None:
        import ifcopenshell
        import ifcopenshell.api
        import ifcopenshell.util.element

        import kimbim

        _ns = {"__name__": "__console__", "__builtins__": __builtins__, "ifcopenshell": ifcopenshell,
               "kimbim": kimbim, "bridge": B, "selection": selection, "select": select, "refresh": refresh,
               "edit": edit, "help_kimbim": help_kimbim}
    _ns["ifc"] = B._model
    return _ns


def reset() -> None:
    """A fresh namespace (tests; the app keeps one for the session)."""
    global _ns
    _ns = None


def _trace(frame, event, arg):
    if threading.get_ident() != _worker:
        return None
    if _stop and frame.f_code.co_filename in _user_files:
        raise KeyboardInterrupt
    return _trace


def console_stop() -> str:
    """Stop the running script at its next line of user code (KeyboardInterrupt). Called from another thread."""
    global _stop
    if _worker is None:
        return B._dump({"ok": False})
    _stop = True
    import sys

    threading.settrace_all_threads(_trace)
    frame = sys._current_frames().get(_worker)
    while frame is not None:  # frames already running get line events too
        frame.f_trace = _trace
        frame = frame.f_back
    return B._dump({"ok": True})


def _show_error(ex: BaseException) -> str:
    tb = ex.__traceback__
    while tb is not None and tb.tb_frame.f_code.co_filename == __file__:
        tb = tb.tb_next  # the console's own frames aren't the script's business
    return "".join(traceback.format_exception(type(ex), ex, tb))


def _execute(source: str, filename: str, ns: dict, echo: bool) -> None:
    tree = ast.parse(source, filename, "exec")
    last = None
    if echo and tree.body and isinstance(tree.body[-1], ast.Expr):
        last = ast.Expression(tree.body.pop().value)
    exec(compile(tree, filename, "exec"), ns)
    if last is not None:
        value = eval(compile(last, filename, "eval"), ns)
        if value is not None:
            ns["_"] = value
            print(repr(value))


def _execute_all(source: str, filename: str, selection_json: str, echo: bool, extra: dict | None = None) -> str:
    global _worker, _stop, _run
    if not _lock.acquire(blocking=False):
        return B._dump({"ok": False, "error": "a script is already running"})
    try:
        try:
            current = [g for g in json.loads(selection_json or "[]") if isinstance(g, str)]
        except ValueError:
            current = []
        _run = {"selection": current, "select": None, "refresh": False}
        before = list(B._ids)
        lines = source.splitlines(True)
        linecache.cache[filename] = (len(source), None, lines, filename)  # tracebacks show the lines
        _user_files.add(filename)
        ns = namespace()
        ns.update(extra or {})
        out = io.StringIO()
        error = ""
        implicit = B._step is None and B._model is not None  # the whole run is one undo step (D92)
        if implicit:
            B._begin()
            B._step = ([], [])
        _stop, _worker = False, threading.get_ident()
        failure: BaseException | None = None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                _execute(source, filename, ns, echo)
        except BaseException as ex:  # noqa: BLE001  (a script's SystemExit or Stop ends the run, not the app)
            failure = ex
            error = _show_error(ex)
        finally:
            _worker = None
            if _stop:
                threading.settrace_all_threads(None)
            _stop = False
        if implicit and B._step is not None:
            if failure is not None:
                B._step = None
                B._abort(failure)  # a run that failed rolls back, so no half-made step survives
            else:
                _finish_step()
        geometry = _geometry(before)
        return B._dump({"ok": True, "output": out.getvalue(), "error": bool(error),
                        "traceback": error, "geometry": geometry,
                        "edited": list(B._ids) != before or _run["refresh"], "select": _run["select"]})
    except Exception as ex:  # noqa: BLE001
        return B._dump({"ok": False, "error": f"{type(ex).__name__}: {ex}"})
    finally:
        _lock.release()


def _geometry(before: list) -> dict:
    """What the app redraws: the shapes touched by the run's new undo steps, or everything after refresh()."""
    if B._model is None:
        return {"changed": [], "removed": []}
    if _run.get("refresh"):
        return {"changed": [p.GlobalId for p in B._model.by_type("IfcProduct")], "removed": []}
    old = set(before)
    touched = [g for i, d in zip(B._ids, B._deltas) if i not in old for g in d]
    return B._geometry_now(touched)


# ---------------------------------------------------------------- bridge

def console_run(code: str, selection_json: str = "[]") -> str:
    """Run console input. Returns {ok, output, error, traceback, geometry, edited, select}."""
    global _count
    _count += 1
    return _execute_all(code, f"<console-{_count}>", selection_json, echo=True)


def console_run_file(path: str, selection_json: str = "[]") -> str:
    """Run a .py file in the console's namespace (as `__main__`-like, with __file__ set)."""
    try:
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
    except OSError as ex:
        return B._dump({"ok": False, "error": f"{type(ex).__name__}: {ex}"})
    return _execute_all(source, path, selection_json, echo=False, extra={"__file__": path})


def console_help() -> str:
    return B._dump({"ok": True, "help": HELP})
