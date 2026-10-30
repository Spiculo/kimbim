# SPDX-License-Identifier: GPL-3.0-or-later
"""An agent session (D102): one open project, opened the way the app opens it (lock, versioning, settings),
so the app and an agent never edit the same file at once. The lock shows as "KimBim agent"."""
from __future__ import annotations

import json
import pathlib

from .. import app_bridge as B
from .. import authoring as A
from .. import graphics as G
from .. import queries as Q
from .. import documents as D
from .. import kimfile as K
from .. import settings as S
from .. import versioning as V
from . import sessions as stored
from .catalogue import AgentError
from .tasks import Tasks


class Session:
    def __init__(self, kind: str, source: str, client: str = "cli"):
        self.kind = kind
        self.source = source
        self.client = client
        self.tasks = None  # the project's agent tasks (agent.tasks.Tasks), set by open()
        self.renderer = None  # the snapshot renderer (agent.render.Renderer), started by the first snapshot
        self._saved_user = ""
        self._closed = False
        self.live = False  # attached to the project the app already has open (D102 phase 2)
        self._selection_get = None  # live: () -> [GlobalId]; the app pushes its selection
        self._selection_set = None  # live: ([GlobalId]) -> None; the app selects them on its next poll
        self.store = None  # the stored-session Store (agent.sessions.Store), when this session is stored
        self.stored = None  # its StoredSession record (D111); None for an ad-hoc CLI/MCP session
        self.stored_id = ""

    @property
    def work(self) -> str:
        """The folder holding this session's working model: the worktree for a stored folder session."""
        return D._doc["work"]

    @property
    def project_path(self) -> str:
        """Where the project's task files live: the folder's own `.kimbim`, the .kim's unpacked copy, or the
        data folder for a plain IFC. A session's worktree does not hide the task from the app."""
        if self.kind == "folder":
            return self.source
        if self.kind == "kim":
            return D._doc.get("work") or self.source
        return self.source

    @property
    def unit(self) -> str:
        return S.current().get("length_unit", "m")

    @classmethod
    def attach(cls, source: str, kind: str, client: str = "assistant", session_id: str = "") -> "Session":
        """A session over the document the app already has open: no opening, locking or creating of tasks'
        storage. The app owns the document and the lock; it drives calls on its own thread."""
        session = cls(kind, source, client)
        session.tasks = Tasks(session)
        session.live = True
        if session_id:
            session.bind_stored(session_id)
        return session

    @classmethod
    def open(cls, path: str, client: str = "cli", session_id: str = "") -> "Session":
        if session_id:
            return cls.open_stored(session_id, client)
        p = pathlib.Path(path)
        if p.is_dir():
            kind = "folder"
        elif p.suffix.lower() == ".kim":
            kind = "kim"
        elif p.suffix.lower() == ".ifc":
            kind = "ifc"
        else:
            raise AgentError("bridge_error", hint=f"cannot open {path}")
        if kind != "ifc" and not p.exists():
            raise AgentError("not_found", what=str(p))
        session = cls(kind, str(p), client)
        session._saved_user = K.display_user
        K.display_user = "KimBim agent"
        try:
            session._open(p)
            session.tasks = Tasks(session)
        except BaseException:
            K.display_user = session._saved_user
            raise
        return session

    @classmethod
    def open_stored(cls, session_id: str, client: str = "cli") -> "Session":
        """Open a stored session (D111): a folder project gets its own worktree, so the app's working copy
        stays where it is; a `.kim`/IFC falls back to the existing open/lock path."""
        store = stored.Store()
        record = store.get(session_id)
        if record.status == "archived":
            raise AgentError("session_archived", session=session_id)
        p = pathlib.Path(record.project)
        kind = record.project_kind or stored.project_kind(str(p))
        if kind != "ifc" and not p.exists():
            raise AgentError("not_found", what=str(p))
        session = cls(kind, str(p), client)
        session.store, session.stored, session.stored_id = store, record, record.id
        session._saved_user = K.display_user
        K.display_user = "KimBim agent"
        try:
            worktree = store.ensure_worktree(record) if kind == "folder" else ""
            if worktree:
                # ensure_worktree already put the worktree on the session's branch
                out = json.loads(D.open_worktree(record.project, worktree))
            else:
                out = json.loads(D.open_kim(str(p)) if kind == "kim" else
                                 (D.open_folder(str(p)) if kind == "folder" else B.open_model(str(p))))
            if out.get("locked"):
                raise AgentError("project_locked", holder=out["locked"])
            if not out.get("ok"):
                raise AgentError("bridge_error", hint=str(out.get("error") or ""))
            if kind != "ifc":
                opened = json.loads(B.open_model(out["path"]))
                if not opened.get("ok"):
                    D.discard_pending()
                    raise AgentError("bridge_error", hint=str(opened.get("error") or ""))
            session.tasks = Tasks(session)
            session.record_opened()
        except BaseException:
            try:
                D.discard_pending()  # a failed open must not leave its worktree lock or pending note
            except Exception:  # noqa: BLE001
                pass
            K.display_user = session._saved_user
            raise
        return session

    def bind_stored(self, session_id: str) -> None:
        """Attach a stored record to a live session (the app already owns the document)."""
        try:
            self.store = stored.Store()
            self.stored = self.store.get(session_id)
            self.stored_id = self.stored.id
        except AgentError:
            self.store = self.stored = None
            self.stored_id = ""

    def record_opened(self) -> None:
        if self.store is None or self.stored is None:
            return
        try:
            state = json.loads(V.project_state())
            fields = {"status": "open"}
            worktree = self.work if self.kind == "folder" and self.work != self.source else ""
            if worktree:
                fields["worktree"] = worktree
            if state.get("versioned"):
                if not self.stored.base_option:
                    fields["base_option"] = state.get("option", "")
                if not self.stored.base_version:
                    fields["base_version"] = state.get("head") or ""
            self.store.update(self.stored_id, **fields)
            self.stored = self.store.get(self.stored_id)
        except (AgentError, OSError):
            pass

    def sync_worktree(self) -> None:
        """Bring a session worktree's working model to its branch's latest version (D111). The architect may
        have saved a version since the worktree was made; a task must branch from what is there now."""
        if not (self.store and self.stored and self.kind == "folder" and self.work != self.source):
            return
        try:
            head = json.loads(V.project_state()).get("head") or ""
            state = json.loads((pathlib.Path(self.work) / ".kimbim" / "working.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if head and state.get("head") != head and not V._unversioned():
            V.discard_changes()  # exports the branch's latest version into the worktree and opens it

    def branch_hint(self) -> str:
        """The session's branch, when it has one: `Tasks` reuses it instead of naming a new option."""
        return self.stored.branch if self.stored is not None else ""

    def bind_task(self, task) -> None:
        if self.store is None or self.stored is None:
            return
        stored.bind_task(self.stored_id, task.id, branch=task.option or self.stored.branch,
                         base_option=task.base_option, base_version=task.base_version)
        self.stored = self.store.get(self.stored_id)

    def task_status(self, task, status: str) -> None:
        """A task changed state. A shared `.kim` worker restores its unbound session after each request, so the
        task remembers its session id; the store is opened again here."""
        session_id = self.stored_id or getattr(task, "session", "")
        if not session_id:
            return
        store = self.store or stored.Store()
        stored.finish_task(session_id, task.id, status, branch=task.option)
        if self.stored is not None:  # a shared worker stays unbound between requests
            try:
                self.stored = store.get(session_id)
            except AgentError:
                pass

    def _open(self, p: pathlib.Path) -> None:
        if self.kind == "ifc":
            out = json.loads(B.open_model(str(p)))
        else:
            out = json.loads(D.open_kim(str(p)) if self.kind == "kim" else D.open_folder(str(p)))
            if out.get("locked"):
                raise AgentError("project_locked", holder=out["locked"])
            if out.get("ok"):
                out = json.loads(B.open_model(out["path"]))
                if not out.get("ok"):
                    D.discard_pending()
        if not out.get("ok"):
            raise AgentError("bridge_error", hint=str(out.get("error") or ""))

    def save(self) -> None:
        if self.kind == "ifc":
            out = json.loads(B.save())
        else:
            out = json.loads(D.save_document())
        if not out.get("ok"):
            raise AgentError("bridge_error", hint=str(out.get("error") or ""))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.renderer is not None:
                self.renderer.close()  # the windowless helper goes with the session
            if not self.live:  # the app owns its open document: closing the session must not close it
                D.close_document()
        finally:
            if not self.live:
                K.display_user = self._saved_user

    def resolve(self, selector) -> list[str]:
        """GlobalIds for a selector: a GlobalId list, "selection" (needs the app) or a find object. Raises
        not_found for an unknown GlobalId or level and no_match when nothing matches."""
        if selector == "selection":
            if self._selection_get is None:
                raise AgentError("needs_app")
            guids = list(self._selection_get())
            if not guids:
                raise AgentError("no_match")
            return guids
        if isinstance(selector, (list, tuple)):
            for g in selector:
                try:
                    B._model.by_guid(g)
                except RuntimeError:
                    raise AgentError("not_found", what=g) from None
            if not selector:
                raise AgentError("no_match")
            return list(selector)
        if not isinstance(selector, dict):
            raise AgentError("bad_input", hint="unsupported selector")
        shortcuts = []
        if selector.get("kind") is not None:
            kind = str(selector["kind"]).strip().lower()
            kind = kind if kind in G.KINDS else kind + "s"
            if kind not in G.KINDS:
                raise AgentError("bad_input", hint=f"unknown kind {selector['kind']}")
            shortcuts.append({"field": "kind", "op": "equals", "value": kind})
        if selector.get("level") is not None:
            want = str(selector["level"])
            hit = next((s for s in json.loads(A.storeys())["storeys"]
                        if s["guid"] == want or s["name"].strip().lower() == want.strip().lower()), None)
            if hit is None:
                raise AgentError("not_found", what=want)
            shortcuts.append({"field": "level", "op": "equals", "value": hit["guid"]})
        for key in ("ifc_class", "name", "type", "layer", "status"):
            if selector.get(key) is not None:
                shortcuts.append({"field": key, "op": "equals", "value": selector[key]})
        where = list(selector.get("where") or ())
        match = selector.get("match", "all")
        if match == "any" and shortcuts:
            raise AgentError("bad_input", hint="match any can't mix with the shortcut fields; put them in where")
        out = json.loads(Q.find_elements(json.dumps({"rows": shortcuts + where, "match": match})))
        if not out.get("ok"):
            raise AgentError("bad_input", hint=str(out.get("error") or ""))
        if not out["guids"]:
            raise AgentError("no_match")
        return out["guids"]

    def label(self, guid: str) -> str:
        e = B._model.by_guid(guid)
        text = f"{e.is_a()[3:]} {e.Name or ''}".strip()
        storey = None
        for rel in getattr(e, "ContainedInStructure", None) or ():
            storey = rel.RelatingStructure
        return f"{text}, {storey.Name}" if storey is not None and storey.Name else text
