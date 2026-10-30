# SPDX-License-Identifier: GPL-3.0-or-later
"""The headless agent worker (D102, spec §4.2): `kimbim serve PROJECT` opens the project (taking its lock as
"KimBim agent") and keeps it open between CLI/MCP commands, so a big model is opened once, not per command.

It listens on a local pipe (named pipe on Windows, Unix socket elsewhere) with a random authkey and announces
itself in a discovery file, `<data dir>/agent/sessions/<path hash>.json`, that only this user can read:
`{address, authkey, pid, started, project, kind, ...}`. `started` is the process's creation time, so a file left
behind by a dead worker whose pid was reused is still recognised as stale. One request at a time:
`{"tool", "args", "client", "task"}` -> the tool's envelope (catalogue.call_tool), plus `_ping` and `_shutdown`.
After `idle` seconds without a request (KIMBIM_AGENT_IDLE, default 600), on SIGTERM or on Ctrl+Break it marks
its entry `stopping`, parks an open task, saves, releases the lock and exits. A worker that can't open the
project writes `{"error": envelope}` to its own `<hash>.<pid>.error.json`, for the client that started it.

All model work stays on the main thread (the bridge is not thread-safe); the watchdog thread only wakes the
listener up by connecting to it (when idle, or when a signal arrives while accept() blocks).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import select
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
from pathlib import Path

from .. import documents as D
from .. import kimfile as K
from .catalogue import AgentError, call_tool

IDLE_DEFAULT = 600.0
RECV_WAIT = 30.0  # seconds a connected client gets to send its request
FAMILY = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
_WAKE = "_wake"  # the watchdog's wake-up request (not a tool)


def _log(message: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} [{os.getpid()}] {message}", file=sys.stderr, flush=True)


def idle_seconds() -> float:
    try:
        return float(os.environ.get("KIMBIM_AGENT_IDLE", "") or IDLE_DEFAULT)
    except ValueError:
        return IDLE_DEFAULT


# ---------------------------------------------------------------- discovery file

def _session_dir_name(session: str) -> str:
    """A session id is a hex name (D111); anything else must not become a path out of the data folder."""
    return session if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session or "") else "_invalid"


def discovery_path(project, session: str = "") -> Path:
    """A stored session's worker lives in the session's folder (D111), so two sessions on one project each
    have their own worker and worktree; without a session, the project's single worker is in the data folder."""
    if session:
        return D.data_dir() / "agent" / "sessions" / _session_dir_name(session) / "worker.json"
    return D.data_dir() / "agent" / "sessions" / f"{K.path_hash(project)}.json"


def live_discovery_path(project) -> Path:
    """The live app's entry, in the project itself (D102 phase 2), so the app and the CLI agree on it even when
    they use different data folders. Next to the lock: `<file>.kim.agent-live.json` or
    `<folder>/.kimbim/agent-live.json`."""
    p = Path(project)
    if p.is_dir():
        return p / ".kimbim" / "agent-live.json"
    return p.with_name(p.name + ".agent-live.json")


def error_path(project, pid: int, session: str = "") -> Path:
    """Where worker `pid` leaves its start error for the client that spawned it."""
    if session:
        return D.data_dir() / "agent" / "sessions" / _session_dir_name(session) / f"worker.{pid}.error.json"
    return D.data_dir() / "agent" / "sessions" / f"{K.path_hash(project)}.{pid}.error.json"


def process_started(pid: int) -> str:
    """The process's creation time as an opaque token ("" when unknown): a reused pid gives another token."""
    if pid <= 0:
        return ""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return ""
            try:
                times = [wintypes.FILETIME() for _ in range(4)]
                if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                    return ""
                return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
            finally:
                kernel32.CloseHandle(handle)
        if sys.platform == "darwin":  # macOS has no /proc; ps lstart is the same token for both calls
            out = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True, timeout=5)
            return out.stdout.strip() if out.returncode == 0 else ""
        stat = Path(f"/proc/{pid}/stat").read_text()
        return stat.rsplit(")", 1)[1].split()[19]  # field 22, starttime
    except (OSError, IndexError, ValueError, AttributeError, subprocess.SubprocessError):
        return ""


def read_discovery(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def entry_alive(data: dict | None) -> bool:
    """A worker entry whose process is still the one that wrote it (it may be `stopping`)."""
    if not data or not data.get("address") or not data.get("authkey"):
        return False
    pid = int(data.get("pid", 0) or 0)
    if not K.pid_alive(pid):
        return False
    then, now = str(data.get("started") or ""), process_started(pid)
    return not (then and now and then != now)


def same_entry(a: dict | None, b: dict | None) -> bool:
    return bool(a) and bool(b) and a.get("pid") == b.get("pid") and a.get("started") == b.get("started")


def unlink_if(path: Path, seen: dict) -> None:
    """Remove the file only if it still holds the entry `seen` (another worker may have replaced it)."""
    if same_entry(read_discovery(path), seen):
        path.unlink(missing_ok=True)


def write_json(path: Path, data: dict) -> None:
    """Atomically, readable only by this user (the authkey is in it)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _address(project) -> str:
    name = f"kimbim-{K.path_hash(project)}-{os.getpid()}"
    if FAMILY == "AF_PIPE":
        return rf"\\.\pipe\{name}"
    return str(Path(tempfile.gettempdir()) / f"{name}.sock")  # short: AF_UNIX paths are limited to ~100 bytes


# ---------------------------------------------------------------- signals and the watchdog

def _on_signal(signum, _frame):
    """SIGTERM / SIGBREAK: leave through serve()'s finally (park, save, release the lock)."""
    raise SystemExit(128 + int(signum))


_wakeup_pair: list[socket.socket] = []


def _install_signals() -> socket.socket | None:
    """Handlers that raise SystemExit, and a wakeup socket the watchdog watches: a signal arriving while the main
    thread blocks in accept() wakes it, so the handler runs."""
    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _on_signal)
    try:
        reader, writer = socket.socketpair()
        writer.setblocking(False)
        signal.set_wakeup_fd(writer.fileno(), warn_on_full_buffer=False)
        _wakeup_pair[:] = [reader, writer]  # the write end must stay open
        return reader
    except (OSError, ValueError):
        return None


class _Watchdog(threading.Thread):
    """Wakes the main loop's accept() once `idle` seconds pass without a request, or when a signal arrives."""

    def __init__(self, address: str, authkey: bytes, idle: float, wakeup: socket.socket | None):
        super().__init__(daemon=True)
        self.address, self.authkey, self.idle, self.wakeup = address, authkey, idle, wakeup
        self.last = time.monotonic()
        self.busy = False
        self.poked = False
        self.stopped = threading.Event()

    def touch(self) -> None:
        self.last = time.monotonic()
        self.poked = False

    def idle_now(self) -> bool:
        return not self.busy and time.monotonic() - self.last >= self.idle

    def _poke(self) -> None:
        try:
            conn = Client(self.address, family=FAMILY, authkey=self.authkey)
            conn.send({"tool": _WAKE})
            conn.close()
        except (OSError, EOFError, AuthenticationError):
            self.poked = False

    def run(self) -> None:
        tick = max(0.05, min(1.0, self.idle / 4))
        while not self.stopped.is_set():
            signalled = False
            if self.wakeup is not None:
                try:
                    signalled = bool(select.select([self.wakeup], [], [], tick)[0])
                    if signalled:
                        self.wakeup.recv(64)
                except OSError:
                    self.wakeup = None
            else:
                self.stopped.wait(tick)
            if self.stopped.is_set():
                return
            if signalled and not self.busy:
                self._poke()  # the handler runs (and raises) once accept() returns
            elif not self.poked and self.idle_now():
                self.poked = True
                self._poke()


# ---------------------------------------------------------------- serving

def _stop(session) -> list[str]:
    """Park an open task, save and close (releasing the lock). Returns the problems, which are logged."""
    problems = []
    try:
        session.tasks.park()
    except AgentError as ex:
        problems.append(f"park: {ex}: {ex.hint}")
    except Exception as ex:  # noqa: BLE001  (still save and release the lock)
        problems.append(f"park: {ex}")
    try:
        session.save()
    except AgentError as ex:
        problems.append(f"save: {ex}: {ex.hint}")
    except Exception as ex:  # noqa: BLE001
        problems.append(f"save: {ex}")
    try:
        session.close()
    except Exception as ex:  # noqa: BLE001
        problems.append(f"close: {ex}")
    for p in problems:
        _log(p)
    return problems


def _handle(session, request) -> dict:
    if not isinstance(request, dict):
        return AgentError("bad_input", hint="a request is an object").envelope()
    name = request.get("tool")
    if name == "_ping":
        return {"ok": True, "result": {"pid": os.getpid(), "project": session.source,
                                       "session": session.stored_id}}
    sid = str(request.get("session") or "")
    rebound = bool(sid and session.stored_id != sid)
    before = (session.store, session.stored, session.stored_id)
    if rebound:  # a .kim/IFC session: it shares this worker, but owns its task
        session.bind_stored(sid)
    try:
        return call_tool(session, str(name or ""), request.get("args") or {},
                         client=str(request.get("client") or "cli"), task_id=str(request.get("task") or ""))
    finally:
        if rebound:  # a session worker keeps its record: the task just updated it
            session.store, session.stored, session.stored_id = before


def _fail_start(project: str, envelope: dict, session: str = "") -> int:
    write_json(error_path(project, os.getpid(), session),
               {"error": envelope, "pid": os.getpid(), "project": project, "session": session})
    return 1


def serve(project: str, idle: float, session_id: str = "") -> int:
    """Open `project` (or a stored session's worktree, D111) and serve requests until idle for `idle` seconds,
    told to shut down or signalled."""
    from .session import Session

    project = os.path.abspath(project)
    found = discovery_path(project, session_id)
    other = read_discovery(found)
    # A session with a worktree does not conflict with the app's own working copy; one without a worktree
    # (.kim/IFC) does, so it must not start beside the live host.
    worktree = bool(session_id) and Path(project).is_dir()
    live = None if worktree else read_discovery(live_discovery_path(project))
    if (entry_alive(other) and not other.get("stopping")) or (entry_alive(live) and not live.get("stopping")):
        _log(f"a session for {project} is already running (pid {(other or live)['pid']})")
        return 0
    wakeup = _install_signals()
    _log(f"opening {project}" + (f" (session {session_id})" if session_id else ""))
    try:
        session = Session.open(project, "cli", session_id)
    except SystemExit as ex:  # a signal before there is a session: tell the client instead of vanishing
        _log(f"signal while opening {project}: {ex.code}")
        return _fail_start(project, AgentError("worker_failed", hint=f"signal {ex.code} while opening").envelope(),
                           session_id)
    except AgentError as ex:
        _log(f"cannot open {project}: {ex.code} {ex}")
        return _fail_start(project, ex.envelope(), session_id)
    except Exception as ex:  # noqa: BLE001
        _log(f"cannot open {project}: {ex}")
        return _fail_start(project, AgentError("bridge_error", hint=str(ex)).envelope(), session_id)
    authkey = os.urandom(32)
    address = _address(project)
    entry = {"address": address, "authkey": authkey.hex(), "pid": os.getpid(),
             "started": process_started(os.getpid()), "project": project, "kind": "worker",
             "session": session_id, "since": datetime.now().isoformat(timespec="seconds")}
    listener = None
    watchdog = None
    stopped = False
    try:
        try:
            session.tasks.resume("")  # a parked task's option is current again (call_tool's resume is then a no-op)
        except Exception as ex:  # noqa: BLE001  (the next command reports it)
            _log(f"unpark: {ex}")
        try:
            listener = Listener(address, family=FAMILY, authkey=authkey)
        except OSError as ex:
            _log(f"cannot listen on {address}: {ex}")
            _stop(session)
            stopped = True
            return _fail_start(project, AgentError("worker_failed", hint=str(ex)).envelope(), session_id)
        write_json(found, entry)  # we hold the project lock: no other live worker owns this entry
        _log(f"serving {project} on {address} (idle exit after {idle:g} s)")
        watchdog = _Watchdog(address, authkey, idle, wakeup)
        watchdog.start()
        while True:
            try:
                conn = listener.accept()
            except AuthenticationError:
                _log("refused a connection with a wrong authkey")
                continue
            except (OSError, EOFError) as ex:
                _log(f"accept: {ex}")
                continue
            try:
                try:
                    if not conn.poll(RECV_WAIT):
                        _log("a client connected but sent nothing")
                        continue
                    request = conn.recv()
                except (OSError, EOFError):
                    continue
                if isinstance(request, dict) and request.get("tool") == _WAKE:
                    if watchdog.idle_now():
                        _log("idle: exiting")
                        break
                    watchdog.poked = False
                    continue
                watchdog.busy = True
                try:
                    if isinstance(request, dict) and request.get("tool") == "_shutdown":
                        _log("shutdown requested")
                        write_json(found, {**entry, "stopping": True})
                        stopped = True  # set first: a signal during park/save must not run _stop twice
                        problems = _stop(session)
                        reply = {"ok": True, "result": {"stopped": True, "pid": os.getpid()}}
                        if problems:
                            reply["warnings"] = problems
                        try:
                            conn.send(reply)
                        except (OSError, EOFError):
                            pass
                        break
                    reply = _handle(session, request)
                    try:
                        conn.send(reply)
                    except (OSError, EOFError) as ex:
                        _log(f"reply lost: {ex}")
                finally:
                    watchdog.busy = False
                    watchdog.touch()
            finally:
                conn.close()
    except SystemExit as ex:
        _log(f"signal: exiting ({ex.code})")
    finally:
        for name in ("SIGTERM", "SIGBREAK"):  # a second signal must not cut the park and save short
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), signal.SIG_IGN)
        if watchdog is not None:
            watchdog.stopped.set()
        if listener is not None:
            if same_entry(read_discovery(found), entry):
                write_json(found, {**entry, "stopping": True})  # clients wait for this process to end
            listener.close()
        if not stopped:
            _stop(session)
        unlink_if(found, entry)
        _log("stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kimbim serve", description="Keep a project open for agent commands.")
    parser.add_argument("project")
    parser.add_argument("--session", default="", help="a stored session (agent/sessions): work in its worktree")
    parser.add_argument("--idle", type=float, default=None, help="seconds without a request before exiting")
    args = parser.parse_args(argv)
    return serve(args.project, idle_seconds() if args.idle is None else args.idle, args.session)
