# SPDX-License-Identifier: GPL-3.0-or-later
"""The headless agent worker (D102, spec §4.2): `kimbim serve PROJECT` opens the project (taking its lock as
"KimBim agent") and keeps it open between CLI/MCP commands, so a big model is opened once, not per command.

It listens on a local pipe (named pipe on Windows, Unix socket elsewhere) with a random authkey and announces
itself in a discovery file, `<data dir>/agent/sessions/<path hash>.json`, that only this user can read. One
request at a time: `{"tool", "args", "client", "task"}` -> the tool's envelope (catalogue.call_tool), plus
`_ping` and `_shutdown`. After `idle` seconds without a request (KIMBIM_AGENT_IDLE, default 600) it parks an open
task, saves, releases the lock and exits. A worker that can't open the project writes `{"error": envelope}` to
the discovery path, for the client that started it, and exits.

All model work stays on the main thread (the bridge is not thread-safe); the idle watchdog thread only wakes
the listener up by connecting to it.
"""
from __future__ import annotations

import argparse
import json
import os
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
FAMILY = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
_IDLE = "_idle"  # the watchdog's wake-up request (not a tool)


def _log(message: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} [{os.getpid()}] {message}", file=sys.stderr, flush=True)


def idle_seconds() -> float:
    try:
        return float(os.environ.get("KIMBIM_AGENT_IDLE", "") or IDLE_DEFAULT)
    except ValueError:
        return IDLE_DEFAULT


def discovery_path(project) -> Path:
    return D.data_dir() / "agent" / "sessions" / f"{K.path_hash(project)}.json"


def read_discovery(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_discovery(path: Path, data: dict) -> None:
    """Atomically, readable only by this user (the authkey is in it)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _remove_discovery(path: Path) -> None:
    """Only our own file: a newer worker's stays."""
    data = read_discovery(path)
    if data is not None and data.get("pid") == os.getpid():
        path.unlink(missing_ok=True)


def _address(project) -> str:
    name = f"kimbim-{K.path_hash(project)}-{os.getpid()}"
    if FAMILY == "AF_PIPE":
        return rf"\\.\pipe\{name}"
    return str(Path(tempfile.gettempdir()) / f"{name}.sock")  # short: AF_UNIX paths are limited to ~100 bytes


class _Watchdog(threading.Thread):
    """Wakes the main loop's accept() once `idle` seconds pass without a request."""

    def __init__(self, address: str, authkey: bytes, idle: float):
        super().__init__(daemon=True)
        self.address, self.authkey, self.idle = address, authkey, idle
        self.last = time.monotonic()
        self.busy = False
        self.poked = False
        self.stopped = threading.Event()

    def touch(self) -> None:
        self.last = time.monotonic()
        self.poked = False

    def idle_now(self) -> bool:
        return not self.busy and time.monotonic() - self.last >= self.idle

    def run(self) -> None:
        tick = max(0.05, min(1.0, self.idle / 4))
        while not self.stopped.wait(tick):
            if self.poked or not self.idle_now():
                continue
            self.poked = True
            try:
                conn = Client(self.address, family=FAMILY, authkey=self.authkey)
                conn.send({"tool": _IDLE})
                conn.close()
            except (OSError, EOFError, AuthenticationError):
                self.poked = False


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
        return {"ok": True, "result": {"pid": os.getpid(), "project": session.source}}
    return call_tool(session, str(name or ""), request.get("args") or {}, client=str(request.get("client") or "cli"),
                     task_id=str(request.get("task") or ""))


def serve(project: str, idle: float) -> int:
    """Open `project` and serve requests until idle for `idle` seconds or told to shut down."""
    from .session import Session

    project = os.path.abspath(project)
    found = discovery_path(project)
    other = read_discovery(found)
    if other and other.get("address") and other.get("pid") != os.getpid() and K.pid_alive(int(other.get("pid", 0))):
        _log(f"a worker for {project} is already running (pid {other['pid']})")
        return 0
    _log(f"opening {project}")
    try:
        session = Session.open(project, "cli")
    except AgentError as ex:
        _log(f"cannot open {project}: {ex.code} {ex}")
        _write_discovery(found, {"error": ex.envelope(), "pid": os.getpid(), "project": project})
        return 1
    except Exception as ex:  # noqa: BLE001
        _log(f"cannot open {project}: {ex}")
        _write_discovery(found, {"error": AgentError("bridge_error", hint=str(ex)).envelope(), "pid": os.getpid(),
                                 "project": project})
        return 1
    try:
        session.tasks.resume("")  # a parked task's option is current again (call_tool's resume is then a no-op)
    except Exception as ex:  # noqa: BLE001  (the next command reports it)
        _log(f"unpark: {ex}")
    authkey = os.urandom(32)
    address = _address(project)
    try:
        listener = Listener(address, family=FAMILY, authkey=authkey)
    except OSError as ex:
        _log(f"cannot listen on {address}: {ex}")
        _stop(session)
        _write_discovery(found, {"error": AgentError("worker_failed", hint=str(ex)).envelope(), "pid": os.getpid(),
                                 "project": project})
        return 1
    _write_discovery(found, {"address": address, "authkey": authkey.hex(), "pid": os.getpid(), "project": project,
                             "kind": "worker", "started": datetime.now().isoformat(timespec="seconds")})
    _log(f"serving {project} on {address} (idle exit after {idle:g} s)")
    watchdog = _Watchdog(address, authkey, idle)
    watchdog.start()
    stopped = False
    try:
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
                    request = conn.recv()
                except (OSError, EOFError):
                    continue
                if isinstance(request, dict) and request.get("tool") == _IDLE:
                    if watchdog.idle_now():
                        _log("idle: exiting")
                        break
                    watchdog.poked = False
                    continue
                watchdog.busy = True
                try:
                    if isinstance(request, dict) and request.get("tool") == "_shutdown":
                        _log("shutdown requested")
                        problems = _stop(session)
                        stopped = True
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
    finally:
        watchdog.stopped.set()
        listener.close()  # new clients fail to connect and wait for this process to end
        if not stopped:
            _stop(session)
        _remove_discovery(found)
        _log("stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kimbim serve", description="Keep a project open for agent commands.")
    parser.add_argument("project")
    parser.add_argument("--idle", type=float, default=None, help="seconds without a request before exiting")
    args = parser.parse_args(argv)
    return serve(args.project, idle_seconds() if args.idle is None else args.idle)
