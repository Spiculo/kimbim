# SPDX-License-Identifier: GPL-3.0-or-later
"""Task tools (D102, spec §4.3): start, finish, abandon and status of the task an agent's changes go in."""
from __future__ import annotations

from ... import console
from ... import documents as D
from ... import settings as S
from ... import versioning as V
from ..catalogue import AgentError, bridge, tool

_TASK = {"type": "string", "description": "The task id task.start printed (default: your open task)."}


@tool("task.start", {"required": ["title"], "properties": {
    "title": {"type": "string", "description": "What the task does, e.g. \"Widen first-floor windows\"."},
    "mode": {"type": "string", "enum": ["option", "direct"],
             "description": "option: the changes go in a design option for review; direct: into the model. "
                            "Used only when the project lets the agent decide."}}})
def start(session, title, mode="", client="cli"):
    """Start a task: the changes that follow go in a design option agent/<title> for the architect to review
    (or straight into the model in direct mode). Returns the task and its id."""
    return session.tasks.start(title, mode, client=client).to_dict()


@tool("task.finish", {"required": ["summary"], "properties": {
    "summary": {"type": "string", "description": "What was changed and why, for the architect."},
    "task": _TASK}})
def finish(session, summary, task="", client="cli", task_id=""):
    """Finish the task: save its changes as a version (on its option, ready for review, or in place in direct
    mode) and return what changed."""
    return session.tasks.finish(task or task_id, summary, client=client)


@tool("task.abandon", {"properties": {"task": _TASK}})
def abandon(session, task="", client="cli", task_id=""):
    """Abandon the task: its changes are thrown away (its design option is deleted)."""
    return session.tasks.abandon(task or task_id, client=client).to_dict()


@tool("task.status", {"properties": {"task": _TASK}})
def status(session, task="", client="cli", task_id=""):
    """Show the open task (or the named one) with what it changed so far, and every task of the project."""
    return session.tasks.status(task or task_id, client=client)


# ---------------------------------------------------------------- versions (D102)

def _versioned() -> None:
    if V._project is None:
        raise AgentError("not_versioned")


@tool("versions.log", {"properties": {"limit": {"type": "integer", "minimum": 1, "description": "Default 50."}}})
def log(session, limit=50):
    """List the saved versions of the current option, newest first: id, message, author, time, milestones."""
    return bridge(V.history, limit)


@tool("versions.diff", {"required": ["from"], "properties": {
    "from": {"type": "string", "description": "A version id, milestone or option name."},
    "to": {"type": "string", "description": "A version id, milestone, option name, or WORKING (default)."}}})
def diff(session, **kw):
    """Compare two versions: the elements added, modified and removed from one to the other (WORKING is the open
    model with its unsaved changes)."""
    _versioned()
    r = bridge(V.compare, kw["from"], kw.get("to") or "WORKING")
    r.pop("ok", None)
    return r


@tool("versions.options", {})
def options(session):
    """List the design options of the project and the current one."""
    return bridge(V.options)


@tool("versions.milestones", {})
def milestones(session):
    """List the milestones (named versions such as Concept or Schematic design)."""
    return bridge(V.milestones)


@tool("versions.element_history", {"required": ["element"], "properties": {
    "element": {"type": "string", "description": "GlobalId."}}})
def element_history(session, element):
    """List the saved versions that changed an element, newest first."""
    _versioned()
    r = bridge(V.element_history, element)
    r.pop("ok", None)
    return r


@tool("versions.export", {"required": ["out"], "properties": {
    "version": {"type": "string", "description": "A version id, milestone, option name, HEAD or WORKING."},
    "out": {"type": "string", "description": "Path of the IFC file to write."}}})
def export(session, out, version="HEAD"):
    """Write a version of the model as an IFC file (HEAD, the latest saved one, by default)."""
    if version == "WORKING":
        bridge(D.export_ifc, out)
    else:
        _versioned()
        try:
            model = V._model_at(version)
        except Exception as ex:  # noqa: BLE001  (an unknown revision)
            raise AgentError("not_found", hint=str(ex), what=version) from None
        try:
            model.write(out)
        except Exception as ex:  # noqa: BLE001  (an unwritable path)
            raise AgentError("bridge_error", hint=str(ex)) from None
    return {"path": out, "version": version}


# ---------------------------------------------------------------- selection and scripts

@tool("selection.get", {})
def selection_get(session):
    """Read the app's current selection. Needs the KimBim app to be running."""
    if session._selection_get is None:
        raise AgentError("needs_app")
    return {"elements": [{"guid": g, "label": session.label(g)} for g in session._selection_get()]}


@tool("selection.set", {"required": ["elements"], "properties": {
    "elements": {"type": "array", "items": {"type": "string"}, "description": "GlobalIds to select."}}})
def selection_set(session, elements):
    """Select elements in the app's window. Needs the KimBim app to be running."""
    if session._selection_set is None:
        raise AgentError("needs_app")
    session._selection_set(list(elements))
    return {"selected": len(elements)}


def _scripts_on(session, code):
    if not S.current().get("agent_scripts"):
        raise AgentError("scripts_off", hint="The architect turns scripts on in the project settings (agent_scripts).")


@tool("script.run", {"required": ["code"], "properties": {
    "code": {"type": "string", "description": "Python, as in the console: `ifc` is the model, `bridge` the KimBim "
                                              "commands, edit() groups edits."}}}, writes=True, check=_scripts_on)
def run(session, code):
    """Run a Python script in the project's console (the model is `ifc`, KimBim commands are in `bridge`). It is one
    undo step with the rest of the call; a script that raises is rolled back. Only when the architect allows
    scripts."""
    out = bridge(console.console_run, code, "[]")
    if out.get("error"):
        raise AgentError("bridge_error", hint=out.get("traceback") or "the script failed")
    return {"output": out.get("output", "")}
