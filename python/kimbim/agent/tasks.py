# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent tasks (D102, spec §4.3): how an agent's changes become reviewable.

Option mode (default): the agent's edits go into a design option `agent/<slug>` made from the architect's
latest version (unsaved work is first saved as "Before agent: <title>"); `finish` saves a version on it, by
"<client> (agent)", and goes back to the base option, ready for the architect to review, combine or reject.
Direct mode: the edits are saved in place on `finish`, with a way back (a version first, or for a plain IFC
the recovery copy and `<stem>.before-agent.ifc`).

Project setting `agent_changes`: option, direct, or agent_decides (the task's mode, default option). Task
state is a JSON file per task in `<work>/.kimbim/agent/tasks/` (it travels in the .kim), or for a plain IFC in
`<data dir>/agent/tasks/<path hash>/`, so it survives the worker's exit.

Phase 1 narrowing: one open task per project (`task_busy` on a second start); state stays per client.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import shutil
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .. import app_bridge as B
from .. import documents as D
from .. import kimfile as K
from .. import settings as S
from .. import versioning as V
from . import messages
from .catalogue import AgentError, bridge
from .steps import Changes

ACTIVE = ("open", "parked")
AGENT_EMAIL = "agent@kimbim.local"


@dataclass
class Task:
    id: str
    title: str
    mode: str  # "option" | "direct"
    client: str
    status: str = "open"  # "open" | "parked" | "ready" | "abandoned"
    base_option: str = ""
    base_version: str = ""
    option: str = ""
    created: str = ""
    summary: str = ""
    changes: dict = field(default_factory=dict)  # accumulated: {"added", "modified", "removed", "labels"}

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d.pop("changes")
        return d


def slug(title: str) -> str:
    """ASCII, lowercase, words joined by "-", at most 40 characters ("Ampliar ventanas ñ" -> ampliar-ventanas-n)."""
    text = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:40].rstrip("-") or "task"


def _author(client: str) -> str:
    return json.dumps({"name": f"{client} (agent)", "email": AGENT_EMAIL})


def _option() -> str:
    return json.loads(V.project_state()).get("option", "")


class Tasks:
    """The tasks of a session's project, read from and written to disk on every change."""

    def __init__(self, session):
        self.session = session
        self._current = ""  # the task the write being run belongs to (for_write -> record)
        self._start_steps: dict[str, int] = {}  # direct tasks started in this process: the undo id at start

    # ------------------------------------------------------------ storage

    def _dir(self) -> pathlib.Path:
        if self.session.kind == "ifc":
            return D.data_dir() / "agent" / "tasks" / K.path_hash(self.session.source)
        return pathlib.Path(self.session.work) / ".kimbim" / "agent" / "tasks"

    def _write(self, task: Task) -> None:
        folder = self._dir()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{task.id}.json").write_text(json.dumps(dataclasses.asdict(task), indent=1, ensure_ascii=False),
                                               encoding="utf-8")

    def all(self) -> list[Task]:
        out = []
        folder = self._dir()
        for p in sorted(folder.glob("*.json")) if folder.is_dir() else ():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                out.append(Task(**{f.name: data[f.name] for f in dataclasses.fields(Task) if f.name in data}))
            except (OSError, ValueError, TypeError, KeyError):
                continue  # a damaged task file is skipped, not fatal
        return sorted(out, key=lambda t: (t.created, t.id))

    def get(self, task_id: str) -> Task:
        hit = next((t for t in self.all() if t.id == task_id), None)
        if hit is None:
            raise AgentError("unknown_task", task=task_id)
        return hit

    # ------------------------------------------------------------ which task

    def open_task(self, client: str, task_id: str = "") -> Task | None:
        """`task_id` -> that task; else the client's open task; else the only open task on the project;
        several -> ambiguous_task. Parked tasks count as open."""
        if task_id:
            t = self.get(task_id)
            if t.status not in ACTIVE:
                raise AgentError("no_task", task=task_id)
            return t
        active = [t for t in self.all() if t.status in ACTIVE]
        mine = [t for t in active if t.client == client]
        for group in (mine, active):
            if len(group) == 1:
                return group[0]
            if len(group) > 1:
                raise AgentError("ambiguous_task", tasks=[t.id for t in group])
        return None

    def mode_for(self, mode: str = "") -> str:
        setting = S.current().get("agent_changes", "option")
        if setting == "direct":
            return "direct"
        if setting == "agent_decides":
            return mode or "option"
        return "option"

    # ------------------------------------------------------------ helpers

    def _no_step(self) -> None:
        if B._step is not None:  # a console run or edit() block is open: switching options would break it
            raise AgentError("bad_input", hint=messages.text("hint_open_step"))

    def _save_version(self, message: str, client: str = "") -> str:
        """A version of the unversioned work (none needed: ""). `client`: made by that agent, else the user."""
        if not V._unversioned():
            return ""
        out = json.loads(V.save_version(message, _author(client) if client else ""))
        if not out.get("ok"):
            if V._unversioned():
                raise AgentError("bridge_error", hint=str(out.get("error") or ""))
            return ""  # nothing changed after all (edits undone)
        return out["id"]

    def _free_option(self, base: str) -> str:
        taken = set(json.loads(V.options())["options"])
        name, n = f"agent/{base}", 2
        while name in taken:
            name, n = f"agent/{base}-{n}", n + 1
        return name

    def _enter(self, task: Task) -> None:
        """Make `task` the open one: an option task works on its option (unparking it)."""
        if task.mode == "option" and _option() != task.option:
            bridge(V.switch_option, task.option)
        if task.status != "open":
            task.status = "open"
            self._write(task)
        self._current = task.id

    def _save_document(self) -> None:
        bridge(D.save_document)

    def changes(self, task: Task) -> dict:
        c = task.changes or {}
        acc = Changes(list(c.get("added", [])), list(c.get("modified", [])), list(c.get("removed", [])),
                      dict(c.get("labels", {})))
        return acc.to_dict(getattr(self.session, "label", None))

    # ------------------------------------------------------------ lifecycle

    def start(self, title: str, mode: str = "", client: str = "") -> Task:
        self._no_step()
        client = client or getattr(self.session, "client", "cli")
        title = " ".join((title or "").split())
        if not title:
            raise AgentError("bad_input", hint=messages.text("hint_required", field="title"))
        busy = next((t for t in self.all() if t.status in ACTIVE), None)
        if busy is not None:  # phase 1: one open task per project
            raise AgentError("task_busy", task=busy.id, title=busy.title)
        task = Task(uuid.uuid4().hex[:8], title, self.mode_for(mode), client,
                    created=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        if task.mode == "option":
            if V._project is None:
                raise AgentError("not_versioned", hint=messages.text("hint_not_versioned"))
            self._save_version(f"Before agent: {title}")  # the architect's work, so the architect's version
        if V._project is not None:
            state = json.loads(V.project_state())
            task.base_option, task.base_version = state["option"], state["head"] or ""
        if task.mode == "option":
            task.option = self._free_option(slug(title))
            self._write(task)  # before the option: creating it packs the .kim, task file included
            try:
                bridge(V.create_option, task.option)
            except AgentError:
                (self._dir() / f"{task.id}.json").unlink(missing_ok=True)
                raise
        else:
            self._write(task)
            self._start_steps[task.id] = B._current_id()
        self._current = task.id
        return task

    def for_write(self, client: str, task_id: str = "", title: str = "") -> Task:
        """The task a write tool's call belongs to: the open one (unparked), or a new implicit one titled
        `title`, so nothing bypasses review."""
        task = self.open_task(client, task_id)
        if task is None:
            return self.start(title or "agent edit", client=client)
        self._enter(task)
        return task

    def record(self, changes: Changes) -> None:
        """Add one write call's changes to the task it ran in (catalogue.call_tool)."""
        if not changes or not self._current:
            return
        try:
            task = self.get(self._current)
        except AgentError:
            return
        c = task.changes or {}
        added, modified, removed = list(c.get("added", [])), list(c.get("modified", [])), list(c.get("removed", []))
        labels = dict(c.get("labels", {}))
        for g in changes.added:
            if g in removed:  # put back: it was there before the task
                removed.remove(g)
                modified.append(g)
            elif g not in added:
                added.append(g)
        for g in changes.modified:
            if g not in added and g not in modified:
                modified.append(g)
        for g in changes.removed:
            if g in added:  # made and deleted within the task: no change
                added.remove(g)
            else:
                if g in modified:
                    modified.remove(g)
                if g not in removed:
                    removed.append(g)
        labels.update(changes.fallback)
        keep = set(added) | set(modified) | set(removed)
        task.changes = {"added": added, "modified": modified, "removed": removed,
                        "labels": {g: v for g, v in labels.items() if g in keep}}
        self._write(task)

    def finish(self, task_id: str, summary: str = "", client: str = "") -> dict:
        self._no_step()
        task = self.open_task(client, task_id)
        if task is None:
            raise AgentError("no_task")
        summary = (summary or "").strip()
        version = ""
        if task.mode == "option":
            self._enter(task)
            version = self._save_version(f"{task.title}\n\n{summary}" if summary else task.title, task.client)
            bridge(V.switch_option, task.base_option)
        elif V._project is not None:
            version = self._save_version(f"{task.title} (agent)", task.client)
        elif self.session.kind == "ifc":
            bridge(D.write_recovery)
            source = pathlib.Path(self.session.source)
            if source.exists():
                shutil.copyfile(source, source.with_name(source.stem + ".before-agent.ifc"))
        task.status, task.summary = "ready", summary
        self._write(task)  # before saving: a .kim packs it
        self._save_document()
        self._current = ""
        self._start_steps.pop(task.id, None)
        return {"task": task.to_dict(), "changes": self.changes(task), "version": version}

    def abandon(self, task_id: str = "", client: str = "") -> Task:
        self._no_step()
        task = self.open_task(client, task_id)
        if task is None:
            raise AgentError("no_task")
        if task.mode == "option":
            if _option() == task.option:
                bridge(V.discard_changes)
                bridge(V.switch_option, task.base_option)
            task.status = "abandoned"
            self._write(task)
            bridge(V.delete_option, task.option)  # packs the .kim, task file included
        else:
            start = self._start_steps.pop(task.id, None)
            if start is not None and (start == B._base_id or start in B._ids):
                while B._current_id() != start and B._ids:  # undo the task's steps
                    B.undo()
            task.status = "abandoned"
            self._write(task)
            D.history_changed()
        self._current = ""
        return task

    def park(self) -> None:
        """The worker exits with a task open: keep its work as a version on its option and go back to the base
        (a direct task keeps its unsaved work in the recovery copy)."""
        for task in self.all():
            if task.status != "open":
                continue
            if task.mode == "option":
                if _option() == task.option:
                    self._save_version(f"Work in progress: {task.title}", task.client)
                    bridge(V.switch_option, task.base_option)
                task.status = "parked"
                self._write(task)
                self._save_document()
            else:
                bridge(D.write_recovery)
                task.status = "parked"
                self._write(task)
        self._current = ""

    def unpark(self, task_id: str = "", client: str = "") -> Task | None:
        """The next command after a park: back on the task's option."""
        task = self.open_task(client or getattr(self.session, "client", "cli"), task_id)
        if task is not None:
            self._enter(task)
        return task

    def status(self, task_id: str = "", client: str = "") -> dict:
        task = self.get(task_id) if task_id else self.open_task(client)
        return {"task": task.to_dict() if task else None, "changes": self.changes(task) if task else None,
                "tasks": [t.to_dict() for t in self.all()]}
