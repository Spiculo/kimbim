# SPDX-License-Identifier: GPL-3.0-or-later
"""The client side of the agent worker (D102, spec §4.2): find the project's worker through its discovery file,
or start one (`python -m kimbim serve PROJECT`, detached, logging to `<data dir>/agent/logs/<path hash>.log`),
and send it one request. Every outcome is an envelope; nothing raises."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client
from pathlib import Path

from .. import documents as D
from .. import kimfile as K
from .catalogue import AgentError
from .worker import FAMILY, discovery_path, read_discovery

START_WAIT = 60.0  # seconds to wait for a new worker's discovery file
EXIT_WAIT = 30.0  # seconds to wait for a worker that is shutting down
AGENT_USER = "KimBim agent"

spawned: list[int] = []  # pids of the workers this process started (tests kill them in teardown)
_procs: list[subprocess.Popen] = []  # kept so a running worker's Popen isn't collected (ResourceWarning)


def _wait(cond, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def _live(project: str) -> dict | None:
    """The project's running worker, from its discovery file. A file left by a dead worker, or an error left
    for another client, is removed."""
    path = discovery_path(project)
    data = read_discovery(path)
    if data is None:
        return None
    pid = int(data.get("pid", 0) or 0)
    if data.get("address") and data.get("authkey") and K.pid_alive(pid):
        return data
    if "error" in data or not K.pid_alive(pid):
        path.unlink(missing_ok=True)
    return None


def _log_path(project: str) -> Path:
    return D.data_dir() / "agent" / "logs" / f"{K.path_hash(project)}.log"


def _env() -> dict:
    """The worker imports this same kimbim package (a dev checkout isn't installed: add python/ to the path)."""
    env = dict(os.environ)
    root = str(Path(__file__).resolve().parents[2])
    parts = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    if root not in parts:
        env["PYTHONPATH"] = os.pathsep.join([root, *parts])
    return env


def _spawn(project: str) -> subprocess.Popen:
    log = _log_path(project)
    log.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    with open(log, "ab") as out:
        proc = subprocess.Popen([sys.executable, "-m", "kimbim", "serve", project], stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT, close_fds=True, env=_env(), **kwargs)
    _procs[:] = [p for p in _procs if p.poll() is None]
    _procs.append(proc)
    spawned.append(proc.pid)
    return proc


def _start(project: str) -> dict:
    """Start a worker and wait for its discovery file: the worker's entry, or {"error": envelope}."""
    proc = _spawn(project)
    path = discovery_path(project)
    locked = None
    end = time.monotonic() + START_WAIT
    while time.monotonic() < end:
        data = read_discovery(path)
        if data is not None:
            pid = int(data.get("pid", 0) or 0)
            if data.get("address") and K.pid_alive(pid):
                return data  # ours, or another client's worker that won the race
            if "error" in data and pid == proc.pid:
                path.unlink(missing_ok=True)
                error = data["error"]
                holder = ((error.get("error") or {}).get("details") or {}).get("holder") or {}
                if holder.get("user") == AGENT_USER and K.pid_alive(int(holder.get("pid", 0) or 0)):
                    locked = error  # another client's worker holds it: wait for its discovery file
                    continue
                return {"error": error}
        if locked is None and proc.poll() is not None and read_discovery(path) is None:
            hint = f"the worker exited with code {proc.returncode}; see {_log_path(project)}"
            return {"error": AgentError("worker_failed", hint=hint).envelope()}
        time.sleep(0.05)
    if locked is not None:
        return {"error": locked}
    return {"error": AgentError("worker_failed", hint=f"no answer in {START_WAIT:g} s; see {_log_path(project)}")
            .envelope()}


def request(project: str, tool: str, args: dict | None = None, *, client: str = "cli", task: str = "",
            start: bool = True, timeout: float = 120) -> dict:
    """Run `tool` with `args` in the project's worker (started if needed and `start`) and return the envelope."""
    project = os.path.abspath(str(project))
    message = {"tool": tool, "args": args or {}, "client": client, "task": task}
    problem = ""
    for _attempt in range(3):
        info = _live(project)
        if info is None:
            if not start:
                return AgentError("no_session").envelope()
            info = _start(project)
            if "error" in info:
                return info["error"]
        try:
            conn = Client(info["address"], family=FAMILY, authkey=bytes.fromhex(info["authkey"]))
        except (OSError, EOFError, AuthenticationError, ValueError) as ex:
            # the worker is exiting (idle or shut down): nothing ran, so wait for it to end and try again
            problem = str(ex)
            _wait(lambda: not K.pid_alive(int(info.get("pid", 0) or 0)), EXIT_WAIT)
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
