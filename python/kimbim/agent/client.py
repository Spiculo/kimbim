# SPDX-License-Identifier: GPL-3.0-or-later
"""The client side of the agent worker (D102, spec §4.2): find the project's worker through its discovery file,
or start one (`python -m kimbim serve PROJECT`, detached, logging to `<data dir>/agent/logs/<path hash>.log`),
and send it one request. Every outcome is an envelope; nothing raises.

Starting is serialised per project by a `<hash>.starting` file made with O_EXCL, so concurrent clients (threads
or processes) start one worker and the others wait for its discovery entry."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client
from pathlib import Path


from .. import documents as D
from .. import kimfile as K
from .catalogue import AgentError
from .worker import (FAMILY, discovery_path, entry_alive, error_path, live_discovery_path, read_discovery,
                     same_entry, unlink_if)

START_WAIT_DEFAULT = 120.0  # seconds to wait for a new worker's entry (KIMBIM_AGENT_START_WAIT): big projects open slowly
ATTEMPTS = 4
GUARD_GRACE = 10.0  # seconds before an empty or half-written .starting file counts as stale

spawned: list[int] = []  # pids of the workers this process started (tests kill them in teardown)
_procs: list[subprocess.Popen] = []  # kept so a running worker's Popen isn't collected (ResourceWarning)


def start_wait() -> float:
    try:
        return float(os.environ.get("KIMBIM_AGENT_START_WAIT", "") or START_WAIT_DEFAULT)
    except ValueError:
        return START_WAIT_DEFAULT


def _wait(cond, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def _paths(project: str, session: str = "") -> tuple[Path, ...]:
    """A stored session's own worker (D111) has a worktree, so the live app's entry is not it. Without a
    session: the live app's entry (in the project) first, then an offline worker's (in the data folder)."""
    if session:
        return (discovery_path(project, session),)
    return live_discovery_path(project), discovery_path(project)


def _entry(project: str, session: str = "") -> dict | None:
    """The project's live or worker entry if its process is alive (it may be `stopping`); stale ones are removed."""
    for path in _paths(project, session):
        data = read_discovery(path)
        if data is None:
            continue
        if entry_alive(data):
            return data
        unlink_if(path, data)
    return None


def _path_for(project: str, info: dict, session: str = "") -> Path:
    """The discovery file that holds `info` (live first)."""
    for path in _paths(project, session):
        if same_entry(read_discovery(path), info):
            return path
    return discovery_path(project, session)


def _log_path(project: str, session: str = "") -> Path:
    name = f"session-{session}" if session else K.path_hash(project)
    return D.data_dir() / "agent" / "logs" / f"{name}.log"


def _env() -> dict:
    """The worker imports this same kimbim package (a dev checkout isn't installed: add python/ to the path)."""
    env = dict(os.environ)
    env["KIMBIM_DATA_DIR"] = str(D.data_dir())  # the worker must see the same sessions and worktrees
    root = str(Path(__file__).resolve().parents[2])
    parts = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    if root not in parts:
        env["PYTHONPATH"] = os.pathsep.join([root, *parts])
    return env


def _python_exe() -> str:
    """The Python to spawn a worker with. In the app, `sys.executable` may be kimbim-app.exe (an embedded
    interpreter), so prefer a real `python` when one is next to the runtime; KIMBIM_PYTHON_EXE overrides."""
    override = os.environ.get("KIMBIM_PYTHON_EXE", "")
    if override:
        return override
    exe = sys.executable or ""
    if Path(exe).name.lower().startswith("python"):
        return exe
    candidates = [Path(sys.prefix) / ("python.exe" if os.name == "nt" else "bin/python"),
                  Path(sys.base_prefix) / ("python.exe" if os.name == "nt" else "bin/python")]
    found = shutil.which("python")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return exe


def _spawn(project: str, session: str = "") -> subprocess.Popen:
    log = _log_path(project, session)
    log.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    cmd = [_python_exe(), "-m", "kimbim", "serve", project]
    if session:
        cmd += ["--session", session]
    with open(log, "ab") as out:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT, close_fds=True, env=_env(), **kwargs)
    _procs[:] = [p for p in _procs if p.poll() is None]
    _procs.append(proc)
    spawned.append(proc.pid)
    return proc


def _guard_stale(guard: Path) -> bool:
    try:
        age = time.time() - guard.stat().st_mtime
    except OSError:
        return False  # just removed: look again
    try:
        held = json.loads(guard.read_text(encoding="utf-8"))
        pid = int(held.get("pid", 0) or 0)
    except (OSError, ValueError):
        return age > GUARD_GRACE  # the writer died between O_EXCL and its write
    return not K.pid_alive(pid) or age > 2 * start_wait() + 10


def _unlink_guard(guard: Path, seen: os.stat_result) -> None:
    """Remove `guard` only if it is still the file we judged stale (another client may have taken it)."""
    try:
        now = guard.stat()
    except OSError:
        return
    if (now.st_mtime_ns, now.st_size, now.st_ino) == (seen.st_mtime_ns, seen.st_size, seen.st_ino):
        guard.unlink(missing_ok=True)


def _start(project: str, session: str = "") -> dict:
    """Start a worker (or wait for the one another client is starting): its entry, or {"error": envelope}."""
    path = discovery_path(project, session)
    guard = path.with_name(path.stem + ".starting")
    guard.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + start_wait()
    while True:
        live = _entry(project, session)
        if live is not None and not live.get("stopping"):
            return live
        try:
            fd = os.open(guard, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                seen = guard.stat()
            except OSError:
                seen = None
            if seen is not None and _guard_stale(guard):
                _unlink_guard(guard, seen)
            elif time.monotonic() > end:
                return {"error": AgentError("worker_failed", hint=f"no worker after {start_wait():g} s").envelope()}
            time.sleep(0.05)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid()}, f)
        break
    try:
        live = _entry(project, session)  # one may have started between our look and taking the guard
        if live is not None and not live.get("stopping"):
            return live
        if live is not None:  # the old worker is still saving: it holds the lock until it ends
            _wait(lambda: not entry_alive(read_discovery(path)), start_wait())
        return _spawn_and_wait(project, session)
    finally:
        guard.unlink(missing_ok=True)


def _spawn_and_wait(project: str, session: str = "") -> dict:
    proc = _spawn(project, session)
    failed = error_path(project, proc.pid, session)
    end = time.monotonic() + start_wait()
    while time.monotonic() < end:
        live = _entry(project, session)
        if live is not None and not live.get("stopping"):
            return live  # ours, or one that won a race we couldn't see
        error = read_discovery(failed)
        if error is not None and "error" in error:
            failed.unlink(missing_ok=True)
            return {"error": error["error"]}
        if proc.poll() is not None:  # gone without an entry or an error: one last look at both
            time.sleep(0.1)
            live = _entry(project, session)
            if live is not None and not live.get("stopping"):
                return live
            error = read_discovery(failed)
            failed.unlink(missing_ok=True)
            if error is not None and "error" in error:
                return {"error": error["error"]}
            hint = f"the worker exited with code {proc.returncode}; see {_log_path(project, session)}"
            return {"error": AgentError("worker_failed", hint=hint).envelope()}
        time.sleep(0.05)
    return {"error": AgentError("worker_failed",
                                hint=f"no answer in {start_wait():g} s; see {_log_path(project, session)}")
            .envelope()}


def request(project: str, tool: str, args: dict | None = None, *, client: str = "cli", task: str = "",
            start: bool = True, timeout: float = 120, session: str = "") -> dict:
    """Run `tool` with `args` in the project's worker (started if needed and `start`) and return the envelope.
    With `session`, a folder project's session worker and worktree are used (D111); a `.kim`/IFC session is
    sent to the project's live/worker session, which binds the stored record."""
    project = os.path.abspath(str(project))
    # Only a versioned folder has somewhere to check out a second working copy.
    route = session if Path(project).is_dir() and (Path(project) / ".git" / "HEAD").is_file() else ""
    message = {"tool": tool, "args": args or {}, "client": client, "task": task, "session": session}
    problem = ""
    for _attempt in range(ATTEMPTS):
        info = _entry(project, route)
        if info is not None and info.get("stopping"):  # shutting down: it holds the lock until it ends
            _wait(lambda: not same_entry(read_discovery(_path_for(project, info, route)), info) or not entry_alive(info),
                  start_wait())
            continue
        if info is None:
            if not start:
                return AgentError("no_session").envelope()
            info = _start(project, route)
            if "error" in info:
                return info["error"]
        path = _path_for(project, info, route)
        try:
            conn = Client(info["address"], family=FAMILY, authkey=bytes.fromhex(info["authkey"]))
        except (FileNotFoundError, ConnectionRefusedError) as ex:
            # nobody listens there. A stopping worker marks its entry first, so an unmarked entry is stale
            # (a dead worker's pid reused by another process): remove it, unless it changed meanwhile
            problem = str(ex)
            current = read_discovery(path)
            if same_entry(current, info) and not current.get("stopping"):
                unlink_if(path, info)
            continue
        except (OSError, EOFError, AuthenticationError, ValueError) as ex:
            # accepted and then dropped (the worker began to exit): nothing ran; once it is marked stopping
            # (or gone) the next attempt waits for it to end
            problem = str(ex)
            _wait(lambda: not same_entry(current := read_discovery(path), info) or current.get("stopping")
                  or not entry_alive(info), 5.0)
            continue
        try:
            conn.send(message)
            if not conn.poll(timeout):
                return AgentError("worker_failed", hint=f"no reply in {timeout:g} s").envelope()
            return conn.recv()
        except (OSError, EOFError) as ex:  # it may have run: don't send it again
            return AgentError("worker_failed", hint=f"{ex}; see {_log_path(project)}").envelope()
        finally:
            conn.close()
    return AgentError("worker_failed", hint=problem).envelope()
