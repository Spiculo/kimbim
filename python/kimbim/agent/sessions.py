# SPDX-License-Identifier: GPL-3.0-or-later
"""Stored agent sessions (D111, docs/18 §4): a conversation that can be resumed after the app restarts,
bound to the project, its branch and its worktree.

A session is **not** an open project (`agent.session.Session` is that); it is the record of a conversation:
one `session.json` (id, project, title, provider/model, base option/version, status, branch, worktree, task
ids), one append-only `transcript.jsonl`, and content-addressed `attachments/`, all under
`<data dir>/agent/sessions/<session-id>/`. The model history is not in the project, so it is not versioned.

The branch is the session's design option (`agent/<slug>`); a session works in its own worktree of a
**folder** project (`<data dir>/agent/worktrees/<project hash>/<session id>/`), so two sessions and the
architect never write the same working folder. A `.kim` or a plain IFC is a single file with nowhere to
check out a second copy: those sessions record `worktree: ""` and use the existing open/lock/worker path
(the D102 fallback), so only one of them can be open at a time.
"""
from __future__ import annotations

import dataclasses
import getpass
import hashlib
import json
import os
import pathlib
import shutil
import uuid
from datetime import datetime, timezone

from .. import documents as D
from .. import kimfile as K
from .. import versioning as V
from ..project import NotAProject, Project
from .catalogue import AgentError

STATUSES = ("open", "parked", "ready", "merged", "rejected", "archived")
ACTIVE = ("open", "parked")
RESULT_LIMIT = 4000  # characters of a tool result kept in the transcript


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _user() -> str:
    try:
        return os.environ.get("USERNAME") or os.environ.get("USER") or getpass.getuser()
    except (OSError, KeyError):
        return ""


def project_kind(path: str) -> str:
    p = pathlib.Path(path)
    if p.is_dir():
        return "folder"
    if p.suffix.lower() == ".kim":
        return "kim"
    return "ifc"


def _read_json(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


@dataclasses.dataclass
class StoredSession:
    """One conversation: the `session.json` fields. Missing fields default, so an older file still opens."""
    id: str
    project: str = ""
    project_hash: str = ""
    project_kind: str = ""
    title: str = ""
    created: str = ""
    updated: str = ""
    user: str = ""
    provider: str = ""
    model: str = ""
    base_option: str = ""
    base_version: str = ""
    status: str = "open"
    branch: str = ""
    worktree: str = ""
    tasks: list = dataclasses.field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "StoredSession":
        known = {f.name for f in dataclasses.fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        if not isinstance(values.get("tasks"), list):
            values["tasks"] = []
        return cls(**values)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


class Store:
    """The sessions of one data folder (per project and per user, D111)."""

    def __init__(self, root: pathlib.Path | str | None = None, user: str = ""):
        self.root = pathlib.Path(root) if root is not None else D.data_dir() / "agent" / "sessions"
        self.user = user or _user()

    # ------------------------------------------------------------ files

    def dir(self, session_id: str) -> pathlib.Path:
        if not session_id or any(c in session_id for c in ("/", "\\", "..")):
            raise AgentError("unknown_session", session=session_id)
        return self.root / session_id

    def transcript_path(self, session_id: str) -> pathlib.Path:
        return self.dir(session_id) / "transcript.jsonl"

    def _path(self, session_id: str) -> pathlib.Path:
        return self.dir(session_id) / "session.json"

    def get(self, session_id: str) -> StoredSession:
        data = _read_json(self._path(session_id))
        if not data:
            raise AgentError("unknown_session", session=session_id)
        return StoredSession.from_dict(data)

    def save(self, record: StoredSession) -> StoredSession:
        record.updated = _now()
        _write_json(self._path(record.id), record.to_dict())
        return record

    # ------------------------------------------------------------ listing

    def all(self, project: str = "", include_archived: bool = True) -> list[StoredSession]:
        """Sessions newest first; `project` limits them to one path hash. A damaged file is skipped."""
        wanted = K.path_hash(project) if project else ""
        out = []
        if self.root.is_dir():
            for path in self.root.iterdir():
                if not path.is_dir():
                    continue
                data = _read_json(path / "session.json")
                if not data:
                    continue
                record = StoredSession.from_dict(data)
                if not record.id:
                    record.id = path.name
                if wanted and record.project_hash != wanted:
                    continue
                if not include_archived and record.status == "archived":
                    continue
                if self.user and record.user and record.user != self.user:
                    continue
                out.append(record)
        return sorted(out, key=lambda r: (r.updated, r.created, r.id), reverse=True)

    # ------------------------------------------------------------ lifecycle

    def create(self, project: str, title: str = "", kind: str = "", provider: str = "",
               model: str = "", base_option: str = "", base_version: str = "") -> StoredSession:
        project = os.path.abspath(str(project)) if project else ""
        title = " ".join((title or "").split()) or "New session"
        record = StoredSession(
            id=uuid.uuid4().hex[:12], project=project, project_hash=K.path_hash(project) if project else "",
            project_kind=kind or (project_kind(project) if project else ""), title=title,
            created=_now(), updated=_now(), user=self.user, provider=provider, model=model,
            base_option=base_option, base_version=base_version, status="open")
        self.dir(record.id).mkdir(parents=True, exist_ok=True)
        self.save(record)
        self.append(record.id, {"role": "status", "text": "Session created"})
        return record

    def update(self, session_id: str, **fields) -> StoredSession:
        record = self.get(session_id)
        for key, value in fields.items():
            if hasattr(record, key):
                setattr(record, key, value)
        return self.save(record)

    def rename(self, session_id: str, title: str) -> StoredSession:
        title = " ".join((title or "").split())
        if not title:
            raise AgentError("bad_input", hint="a session needs a title")
        return self.update(session_id, title=title)

    def archive(self, session_id: str) -> StoredSession:
        return self.update(session_id, status="archived")

    def restore(self, session_id: str) -> StoredSession:
        record = self.get(session_id)
        return self.update(session_id, status="open" if record.status == "archived" else record.status)

    def fork(self, session_id: str, title: str = "") -> StoredSession:
        """A new conversation with the same transcript and no branch: trying another answer starts clean."""
        old = self.get(session_id)
        new = self.create(old.project, title or f"{old.title} (copy)", kind=old.project_kind,
                          provider=old.provider, model=old.model, base_option=old.base_option,
                          base_version=old.base_version)
        src = self.transcript_path(old.id)
        if src.is_file():
            shutil.copyfile(src, self.transcript_path(new.id))
        old_attachments = self.dir(old.id) / "attachments"
        if old_attachments.is_dir():
            shutil.copytree(old_attachments, self.dir(new.id) / "attachments", dirs_exist_ok=True)
        return new

    def delete(self, session_id: str, confirm: bool = False, remove_branch: bool = False) -> dict:
        """Delete a session. A proposal waiting for review is never deleted silently: `confirm` is needed.
        The transcript always goes; the branch only with `remove_branch` and its worktree is removed."""
        record = self.get(session_id)
        if record.status == "ready" and not confirm:
            raise AgentError("session_review", session=session_id)
        removed = {"transcript": self.dir(session_id).exists(), "branch": False, "worktree": False}
        worktree = pathlib.Path(record.worktree) if record.worktree else None
        roots = (D.data_dir() / "agent" / "worktrees").resolve()
        if worktree is not None:
            try:
                inside = worktree.resolve().is_relative_to(roots)
            except OSError:
                inside = False
            if inside and worktree.is_dir():  # never follow a damaged session.json out of the data folder
                shutil.rmtree(worktree, ignore_errors=True)
                removed["worktree"] = True
        if remove_branch and record.branch and record.project_kind == "folder":
            try:
                project = Project.open(record.project)
                if record.branch in project.repo.branches() and project.repo.current_branch() != record.branch:
                    project.repo.delete_branch(record.branch)
                    removed["branch"] = True
            except (NotAProject, OSError):
                pass
        shutil.rmtree(self.dir(session_id), ignore_errors=True)
        return removed

    def for_task(self, task_id: str, project: str = "") -> StoredSession | None:
        """The session a task belongs to (the review bar ends a proposal in its session)."""
        for record in self.all(project):
            if task_id in (record.tasks or ()):
                return record
        return None

    # ------------------------------------------------------------ transcript

    def append(self, session_id: str, entry: dict) -> dict:
        entry = {"time": _now(), **entry}
        path = self.transcript_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def transcript(self, session_id: str, limit: int = 2000) -> list[dict]:
        path = self.transcript_path(session_id)
        if not path.is_file():
            return []
        out = []
        try:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue  # a half-written line at the end of a crash: skip it
                    if isinstance(entry, dict):
                        out.append(entry)
        except OSError:
            return []
        return out[-limit:] if limit else out

    def messages(self, session_id: str) -> list[dict]:
        """What the model needs on resume: the user and assistant text, in order (tool lines stay in the
        panel; the model can re-read the project with a tool when it needs detail)."""
        out = []
        for entry in self.transcript(session_id):
            role, text = entry.get("role"), str(entry.get("text") or "").strip()
            if role in ("user", "assistant") and text:
                if out and out[-1]["role"] == role:  # a turn split by a retry: keep one message each
                    out[-1]["content"] += "\n\n" + text
                else:
                    out.append({"role": role, "content": text})
        return out

    def record_tool(self, session_id: str, name: str, summary: str, ok: bool = True, snapshot: str = "",
                    result=None) -> None:
        self.append(session_id, {"role": "tool", "name": name, "summary": summary, "ok": bool(ok),
                                 "snapshot": snapshot})
        if result is not None:
            text = json.dumps(result, ensure_ascii=False, default=str)
            self.append(session_id, {"role": "tool_result", "name": name, "ok": bool(ok),
                                     "result": text[:RESULT_LIMIT]})

    def attachments_dir(self, session_id: str) -> pathlib.Path:
        path = self.dir(session_id) / "attachments"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def attachment(self, session_id: str, source: str) -> str:
        """Copy a snapshot or file into the session, named by its SHA-256 (the same bytes are stored once)."""
        src = pathlib.Path(source)
        data = src.read_bytes()
        digest = hashlib.sha256(data).hexdigest()[:32]
        target = self.attachments_dir(session_id) / (digest + (src.suffix.lower() or ".bin"))
        if not target.exists():
            target.write_bytes(data)
        return str(target)

    # ------------------------------------------------------------ worktree

    def worktree_dir(self, record: StoredSession) -> pathlib.Path:
        return D.data_dir() / "agent" / "worktrees" / (record.project_hash or "unknown") / record.id

    def ensure_worktree(self, record: StoredSession) -> str:
        """The session's own working folder (D111), or "" for a `.kim`/IFC (no second checkout is possible).
        The worktree starts on the session's branch, else the base option, else `main`."""
        if record.project_kind != "folder" or not record.project:
            return ""
        if not (pathlib.Path(record.project) / ".git" / "HEAD").is_file():
            return ""  # an unversioned folder: no second checkout, open it the old way
        work = self.worktree_dir(record)
        try:
            work.mkdir(parents=True, exist_ok=True)
            project = Project.open_worktree(record.project, work)
            branches = set(project.repo.branches())
            wanted = V._encode(record.branch or record.base_option) if (record.branch or record.base_option) else ""
            if wanted and wanted not in branches:  # the proposal was accepted/rejected: start from base
                wanted = V._encode(record.base_option) if record.base_option and \
                    V._encode(record.base_option) in branches else (V._encode("main") if "main" in branches else "")
                if record.branch:
                    record.branch = ""
                    self.save(record)
            if wanted and wanted in branches:
                project.switch(wanted)
            # The underlay files the worktree's settings name travel in the repository (D85): materialise
            # the branch's `files/` so a plan drawn from this checkout is not missing them.
            head = project.repo.head() or ""
            marker = work / ".kimbim" / "files-head"
            try:
                seen = marker.read_text(encoding="utf-8").strip()
            except OSError:
                seen = ""
            if head and seen != head:
                entries = {p: o for p, o in project.repo.tree_entries("HEAD").items() if p.startswith("files/")}
                data = project.repo.read_blobs(list(entries.values())) if entries else []
                keep = set()
                for path, blob in zip(entries, data):
                    target = work / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(blob)
                    keep.add(target.name)
                files = work / "files"
                if files.is_dir():
                    for old in files.iterdir():
                        if old.name not in keep:
                            old.unlink(missing_ok=True)
                marker.write_text(head, encoding="utf-8")
        except (NotAProject, OSError) as ex:
            raise AgentError("worktree_failed", hint=str(ex)) from None
        if record.worktree != str(work):
            record.worktree = str(work)
            self.save(record)
        return str(work)


# ---------------------------------------------------------------- convenience for app_bridge / assistant

def _store() -> Store:
    return Store()


def _project_of(session_id: str = "") -> str:
    if session_id:
        return _store().get(session_id).project
    return str((D._doc or {}).get("source") or "")


def ensure_for_project(title: str = "", project: str = "", provider: str = "", model: str = "") -> StoredSession:
    """The project's newest open session, or a new one. The Assistant calls this on its first turn."""
    store = _store()
    project = project or _project_of()
    if not project:
        raise AgentError("no_model")
    sessions = [s for s in store.all(project) if s.status in ACTIVE]
    if sessions:
        return sessions[0]
    kind = (D._doc or {}).get("mode", "") if not pathlib.Path(project).is_file() else ""
    return store.create(project, title or pathlib.Path(project).name, kind=kind, provider=provider, model=model)


def start(session_id: str) -> StoredSession:
    """Opening a session to work in: an archived one refuses; a parked one is open again."""
    store = _store()
    record = store.get(session_id)
    if record.status == "archived":
        raise AgentError("session_archived", session=session_id)
    return store.update(session_id, status="open")


def finish_task(session_id: str, task_id: str, status: str, branch: str = "") -> None:
    """A task changed state: keep the session's lifecycle and branch in step (best effort)."""
    try:
        store = _store()
        record = store.get(session_id)
        tasks = list(record.tasks or [])
        if task_id and task_id not in tasks:
            tasks.append(task_id)
        store.update(session_id, tasks=tasks, status=status,
                     branch=branch if branch is not None else record.branch)
    except (AgentError, OSError):
        pass


def bind_task(session_id: str, task_id: str, branch: str = "", base_option: str = "",
              base_version: str = "") -> None:
    try:
        store = _store()
        record = store.get(session_id)
        tasks = list(record.tasks or [])
        if task_id and task_id not in tasks:
            tasks.append(task_id)
        store.update(session_id, tasks=tasks, branch=branch or record.branch, status="open",
                     base_option=base_option or record.base_option,
                     base_version=base_version or record.base_version)
    except (AgentError, OSError):
        pass


def load(session_id: str) -> dict:
    """Metadata plus transcript and model messages for the panel (resume) and the CLI."""
    store = _store()
    record = store.get(session_id)
    return {"session": record.to_dict(), "transcript": store.transcript(session_id),
            "messages": store.messages(session_id)}


def list_sessions(project: str = "", include_archived: bool = True) -> dict:
    store = _store()
    project = project or _project_of()
    if not project:
        return {"sessions": [], "project": ""}  # no open document: no project to list
    return {"sessions": [s.to_dict() for s in store.all(project, include_archived)], "project": project}


def create(project: str = "", title: str = "", provider: str = "", model: str = "") -> dict:
    store = _store()
    project = project or _project_of()
    if not project:
        raise AgentError("no_model")
    return store.create(project, title, provider=provider, model=model).to_dict()


def rename(session_id: str, title: str) -> dict:
    return _store().rename(session_id, title).to_dict()


def archive(session_id: str) -> dict:
    return _store().archive(session_id).to_dict()


def restore(session_id: str) -> dict:
    return _store().restore(session_id).to_dict()


def delete(session_id: str, confirm: bool = False, branch: bool = False) -> dict:
    return _store().delete(session_id, confirm=confirm, remove_branch=branch)


def fork(session_id: str, title: str = "") -> dict:
    return _store().fork(session_id, title).to_dict()


def review(session_id: str, status: str) -> None:
    """The architect accepted or rejected the proposal: the session ends with it."""
    if status in ("merged", "rejected", "accepted"):
        try:
            _store().update(session_id, status="merged" if status != "rejected" else "rejected")
        except (AgentError, OSError):
            pass
