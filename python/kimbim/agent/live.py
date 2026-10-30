# SPDX-License-Identifier: GPL-3.0-or-later
"""Live agent sessions (D102, phase 2): the app hosts the project, a local server and a discovery entry.

The server speaks the phase-1 worker protocol, so `kimbim` and `kimbim mcp` find it through the same
discovery file. Requests are queued and run on the app's thread (the app drains the queue with
`agent_live_pending` / `agent_live_run`), which keeps every model call serialised with the console and
lets the app apply the undo step's geometry and selection at once.

The app pushes its selection with `set_selection`; `selection.get` / `selection.set` and the `"selection"`
selector use it. Proposals (ready option tasks) are listed for the review bar and accepted or rejected here.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import uuid
from datetime import datetime, timezone

from .. import app_bridge as B
from .. import console
from .. import documents as D
from .. import versioning as V
from . import catalogue, worker
from .catalogue import AgentError
from .session import Session
from .tasks import _author

REQUEST_WAIT = 600.0  # seconds an agent waits for the app to run its request

_host: "LiveHost | None" = None
_lock = threading.Lock()


def _host_or_error() -> "LiveHost":
    if _host is None:
        raise AgentError("needs_app")
    return _host


class LiveHost:
    def __init__(self, source: str, project: str, kind: str):
        self.source = source
        self.project = os.path.abspath(project)
        self.session = Session.attach(source, kind, client="live")
        self.session._selection_get = lambda: list(self.selection)
        self.session._selection_set = self.select
        self.selection: list[str] = []
        self._wanted_selection: list[str] | None = None
        self._requests: queue.Queue = queue.Queue()
        self._current: tuple[str, dict] | None = None
        self._replies: dict[str, dict] = {}
        self._reply_lock = threading.Condition()
        self._closed = False
        self._listener = None
        self._thread = None
        self.authkey = os.urandom(32)
        self.address = worker._address(self.project)
        self.started = worker.process_started(os.getpid())
        self.since = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ------------------------------------------------------------ selection

    def select(self, guids: list[str]) -> None:
        self._wanted_selection = list(guids)

    def take_selection(self) -> list[str] | None:
        wanted, self._wanted_selection = self._wanted_selection, None
        return wanted

    # ------------------------------------------------------------ server

    def start(self) -> dict:
        worker.write_json(worker.live_discovery_path(self.project), self.entry())
        self._listener = worker.Listener(self.address, family=worker.FAMILY, authkey=self.authkey)
        self._thread = threading.Thread(target=self._serve, name="kimbim-live", daemon=True)
        self._thread.start()
        return {"ok": True, "project": self.project, "address": self.address, "kind": "live"}

    def entry(self) -> dict:
        return {"address": self.address, "authkey": self.authkey.hex(), "pid": os.getpid(),
                "started": self.started, "project": self.project, "kind": "live", "since": self.since}

    def _serve(self) -> None:
        while not self._closed:
            try:
                conn = self._listener.accept()
            except (OSError, EOFError):
                return
            try:
                if not conn.poll(30):
                    continue
                request = conn.recv()
                reply = self._receive(request)
                try:
                    conn.send(reply)
                except (OSError, EOFError):
                    pass
            except (OSError, EOFError):
                continue
            finally:
                conn.close()

    def _receive(self, request) -> dict:
        if not isinstance(request, dict):
            return AgentError("bad_input", hint="a request is an object").envelope()
        tool = str(request.get("tool") or "")
        if tool == "_ping":
            return {"ok": True, "result": {"pid": os.getpid(), "project": self.project, "live": True}}
        if tool == "_shutdown":  # the CLI's tests stop the host; the app owns the rest
            threading.Thread(target=self.stop, daemon=True).start()
            return {"ok": True, "result": {"stopped": True, "pid": os.getpid()}}
        rid = uuid.uuid4().hex
        with self._reply_lock:
            self._replies[rid] = None
        self._requests.put((rid, request))
        with self._reply_lock:
            self._reply_lock.wait_for(lambda: self._replies.get(rid) is not None, timeout=REQUEST_WAIT)
            reply = self._replies.pop(rid, None)
        return reply or AgentError("worker_failed", hint="the app did not answer").envelope()

    def stop(self) -> None:
        with _lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._listener.close()
            except (OSError, AttributeError):
                pass
            worker.unlink_if(worker.live_discovery_path(self.project), self.entry())
            with self._reply_lock:
                for rid, reply in list(self._replies.items()):
                    if reply is None:
                        self._replies[rid] = AgentError("worker_failed", hint="the app closed").envelope()
                self._reply_lock.notify_all()
            if self.session.renderer is not None:
                try:
                    self.session.renderer.close()
                except Exception:  # noqa: BLE001  (nothing useful to do while closing)
                    pass

    # ------------------------------------------------------------ requests run by the app

    def pending(self) -> dict | None:
        with _lock:
            if self._current is None:
                try:
                    self._current = self._requests.get_nowait()
                except queue.Empty:
                    return None
            rid, request = self._current
        tool = str(request.get("tool") or "")
        spec = catalogue.TOOLS.get(tool)
        return {"id": rid, "tool": tool, "writes": bool(spec is not None and spec.writes),
                "args": request.get("args") or {}, "client": str(request.get("client") or "live"),
                "task": str(request.get("task") or "")}

    def run(self, request_id: str = "") -> dict:
        """Run the pending request (on the app's thread). Returns the reply and what the app must apply."""
        with _lock:
            if self._current is None:
                return {"ok": False, "error": "no request"}
            rid, request = self._current
            if request_id and request_id != rid:
                return {"ok": False, "error": "stale request"}
        if not console._lock.acquire(blocking=False):
            return {"ok": False, "busy": True}  # a console run is open: try again on the next poll
        try:
            before_option = json.loads(V.project_state()).get("option", "")
            before_path = B._path
            before_id = B._current_id()
            sid = str(request.get("session") or "")
            rebound = bool(sid and self.session.stored_id != sid)
            before_stored = (self.session.store, self.session.stored, self.session.stored_id)
            if rebound:
                self.session.bind_stored(sid)
            try:
                envelope = catalogue.call_tool(
                    self.session, str(request.get("tool") or ""), request.get("args") or {},
                    client=str(request.get("client") or "live"), task_id=str(request.get("task") or ""))
            finally:
                if rebound:
                    self.session.store, self.session.stored, self.session.stored_id = before_stored
            ui: dict = {"state": json.loads(B.state())}
            if envelope.get("ok") and before_option != json.loads(V.project_state()).get("option", ""):
                ui["reload"] = B._path
            elif envelope.get("ok") and B._path != before_path:
                ui["reload"] = B._path
            if envelope.get("ok") and request.get("tool") not in ("selection.get", "selection.set"):
                changed = B._deltas[-1] if (B._ids and B._current_id() != before_id) else []
                if changed:
                    ui["geometry"] = B._geometry_now(changed)
                    ui["edited"] = True
                elif B._current_id() != before_id and not B._ids:
                    ui["refresh"] = True  # settings-only or no-shape step

            wanted = self.take_selection()
            if wanted is not None:
                ui["select"] = wanted
            if envelope.get("ok") and str(request.get("tool") or "").split(".")[0] in ("task", "versions"):
                ui["refresh"] = True
        finally:
            console._lock.release()
        with self._reply_lock:
            self._replies[rid] = envelope
            self._reply_lock.notify_all()
        with _lock:
            self._current = None
        return {"ok": True, "reply": envelope, "ui": ui}

    def call_tool_sync(self, tool: str, args: dict, client: str = "assistant", session: str = "") -> dict:
        """Run a tool through the app's queue (used by the Assistant's own thread): the app's poll runs it
        on its thread and applies the undo step, while this thread waits for the envelope."""
        if self._closed:
            return AgentError("worker_failed", hint="the app closed").envelope()
        rid = uuid.uuid4().hex
        with self._reply_lock:
            self._replies[rid] = None
        self._requests.put((rid, {"tool": tool, "args": args, "client": client, "task": "", "session": session}))
        with self._reply_lock:
            self._reply_lock.wait_for(lambda: self._replies.get(rid) is not None, timeout=REQUEST_WAIT)
            return self._replies.pop(rid, None) or AgentError("worker_failed", hint="the app did not answer").envelope()

    def status(self) -> dict:
        return {"ok": True, "active": not self._closed, "project": self.project, "address": self.address,
                "data": str(D.data_dir()), "entry": str(worker.live_discovery_path(self.project)),
                "pending": self._current is not None or not self._requests.empty(),
                "selection": list(self.selection)}


# ---------------------------------------------------------------- bridge functions (app -> Python)

def start() -> str:
    """Start the live host for the document the app has open. Called after the model is loaded."""
    global _host
    with _lock:
        if _host is not None:
            return B._dump({"ok": True, **_host.status()})
        fields = json.loads(D.document_state())
        if not fields.get("ok") or not fields.get("path") or fields.get("read_only"):
            return B._dump({"ok": False, "error": "the document has no path to serve"})
        kind = {"kim": "kim", "folder": "folder"}.get(fields.get("mode"), "ifc")
        _host = LiveHost(fields["path"], fields["path"], kind)
        try:
            out = _host.start()
        except Exception as ex:  # noqa: BLE001
            _host = None
            return B._dump({"ok": False, "error": str(ex)})
        return B._dump(out)


def stop() -> str:
    global _host
    with _lock:
        host, _host = _host, None
    if host is not None:
        host.stop()
    return B._dump({"ok": True})


def call_tool_sync(tool: str, args: dict, client: str = "assistant", session: str = "") -> dict:
    if _host is None:
        raise AgentError("needs_app")
    return _host.call_tool_sync(tool, args, client, session)


def status() -> str:
    return B._dump(_host.status() if _host is not None else {"ok": True, "active": False})


def pending() -> str:
    if _host is None:
        return B._dump({"ok": True, "request": None})
    req = _host.pending()
    return B._dump({"ok": True, "request": req})


def run(request_id: str = "") -> str:
    if _host is None:
        return B._dump({"ok": False, "error": "no live host"})
    return B._dump(_host.run(request_id))


def set_selection(guids_json: str = "[]") -> str:
    if _host is not None:
        try:
            guids = [g for g in json.loads(guids_json or "[]") if isinstance(g, str)]
        except ValueError:
            guids = []
        _host.selection = guids
    return B._dump({"ok": True})


# ---------------------------------------------------------------- proposals

def _counts(task) -> dict:
    c = task.changes or {}
    return {k: len(c.get(k) or ()) for k in ("added", "modified", "removed")}


def proposals() -> str:
    """Ready option tasks whose design option still exists: what the review bar lists. When the live host
    is not running (a read-only or failed session) the task files of the open project are read directly,
    so the bar still appears and says what is waiting for review."""
    out = []
    if _host is not None and V._project is not None:
        options = set(json.loads(V.options()).get("options", []))
        for task in _host.session.tasks.all():
            if task.status != "ready" or task.mode != "option" or not task.option or task.option not in options:
                continue
            out.append({"id": task.id, "title": task.title, "client": task.client, "summary": task.summary,
                        "option": task.option, "base_option": task.base_option, "base_version": task.base_version,
                        "created": task.created, "counts": _counts(task)})
    if not out:  # no live host, a read-only session, or a host that lost the task list: read the project files
        out = _offline_proposals()
    return B._dump({"ok": True, "proposals": out})


def _offline_proposals() -> list:
    """The open document's ready task files without a live host (the app's working folder has them)."""
    import pathlib

    work = (D._doc or {}).get("work") if hasattr(D, "_doc") else None
    if not work:
        return []
    folder = pathlib.Path(work) / ".kimbim" / "agent" / "tasks"
    if not folder.is_dir():
        return []
    try:
        options = set(json.loads(V.options()).get("options", [])) if V._project is not None else set()
    except Exception:  # noqa: BLE001  (a broken project state must not hide the bar)
        options = set()
    out = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("status") != "ready" or data.get("mode") != "option":
                continue
            option = str(data.get("option") or "")
            if option not in options:
                continue
            changes = data.get("changes") or {}
            out.append({"id": data.get("id", ""), "title": data.get("title", ""),
                        "client": data.get("client", ""), "summary": data.get("summary", ""),
                        "option": option, "base_option": data.get("base_option", ""),
                        "base_version": data.get("base_version", ""), "created": data.get("created", ""),
                        "counts": {k: len(changes.get(k) or ()) for k in ("added", "modified", "removed")}})
        except (OSError, ValueError, TypeError):
            continue  # a damaged task file is skipped, not fatal
    return out


def proposal(task_id: str) -> str:
    host = _host_or_error()
    task = host.session.tasks.get(task_id)
    return B._dump({"ok": True, "proposal": {
        "id": task.id, "title": task.title, "client": task.client, "summary": task.summary,
        "option": task.option, "base_option": task.base_option, "base_version": task.base_version,
        "status": task.status, "counts": _counts(task)}})


def _switch_to_base(task) -> None:
    if json.loads(V.project_state()).get("option", "") != task.base_option:
        bridge(V.switch_option, task.base_option)


def accept(task_id: str, resolutions_json: str = "{}") -> str:
    """Combine a ready proposal into its base option, save the result and delete the agent option."""
    host = _host_or_error()
    task = host.session.tasks.get(task_id)
    if task.status != "ready" or task.mode != "option" or not task.option:
        raise AgentError("bad_input", hint="that task is not a proposal")
    _switch_to_base(task)
    preview = json.loads(V.combine_preview(task.option, resolutions_json or "{}"))
    if not preview.get("ok"):
        raise AgentError("bridge_error", hint=str(preview.get("error") or ""))
    if preview.get("unresolved"):
        return B._dump({"ok": False, "error": "conflicts", "conflicts": preview.get("conflicts", []),
                        "unresolved": preview["unresolved"], "option": task.option})
    combined = json.loads(V.combine_options(task.option, resolutions_json or "{}"))
    if not combined.get("ok"):
        raise AgentError("bridge_error", hint=str(combined.get("error") or ""))
    if combined.get("status") == "merge":
        saved = json.loads(V.save_version(f"Accept agent: {task.title}", _author("architect")))
        if not saved.get("ok"):
            raise AgentError("bridge_error", hint=str(saved.get("error") or ""))
    if task.option in json.loads(V.options()).get("options", []):
        V.delete_option(task.option)
    task.status = "accepted"
    host.session.tasks._write(task)
    _end_session(task, host.project, "merged")
    D.save_document()
    return B._dump({"ok": True, "status": combined.get("status"), "path": combined.get("path", B._path),
                    "task": task.to_dict()})


def reject(task_id: str) -> str:
    """Delete a ready proposal's design option and mark the task rejected."""
    host = _host_or_error()
    task = host.session.tasks.get(task_id)
    if task.mode != "option" or not task.option:
        raise AgentError("bad_input", hint="that task has no design option")
    if json.loads(V.project_state()).get("option", "") == task.option:
        bridge(V.discard_changes)
        bridge(V.switch_option, task.base_option)
    if task.option in json.loads(V.options()).get("options", []):
        V.delete_option(task.option)
    task.status = "rejected"
    host.session.tasks._write(task)
    _end_session(task, host.project, "rejected")
    D.save_document()
    return B._dump({"ok": True, "path": B._path, "task": task.to_dict()})


def _end_session(task, project: str, status: str) -> None:
    """The architect accepted or rejected the task: its stored session ends with it (D111)."""
    try:
        from . import sessions

        record = sessions.Store().for_task(task.id, project)
        if record is not None:
            sessions.review(record.id, status)
    except Exception:  # noqa: BLE001  (the review itself must not fail because of the session bookkeeping)
        pass


# called from C++: keep the message text in the app's language
def _bridge(fn, *args):
    return json.loads(fn(*args))


bridge = _bridge
