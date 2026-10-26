# SPDX-License-Identifier: GPL-3.0-or-later
"""Task tools (D102, spec §4.3): start, finish, abandon and status of the task an agent's changes go in."""
from __future__ import annotations

from ..catalogue import tool

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
