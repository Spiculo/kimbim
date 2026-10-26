# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent worker (D102, spec §4.2): a background `kimbim serve` keeps the project open between commands; the
client finds it through a discovery file or starts it. These tests start real processes and kill every one of
them in teardown."""
import json
import os
import shutil
import signal
import sys
import time
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import documents as D
from kimbim import kimfile as K
from kimbim import versioning as V
from kimbim.agent import client
from kimbim.agent.session import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402


def _wait(cond, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


def _kill(pid):
    if K.pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)  # TerminateProcess on Windows
        except OSError:
            pass
        _wait(lambda: not K.pid_alive(pid), 10)


@pytest.fixture(scope="module")
def house_kim(tmp_path_factory) -> Path:
    """The sample house as a .kim, built once (each test works on a copy)."""
    folder = tmp_path_factory.mktemp("house")
    saved = D._data_dir
    D._data_dir = folder / "data"
    try:
        ifc = folder / "house.ifc"
        make_house.build(str(ifc))
        kim = folder / "house.kim"
        out = json.loads(D.import_ifc(str(ifc), str(kim)))
        assert out["ok"], out
        assert json.loads(B.open_model(out["path"]))["ok"]
        D.close_document()
    finally:
        D._data_dir = saved
    return kim


@pytest.fixture
def house(house_kim, tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("KIMBIM_DATA_DIR", str(data))
    monkeypatch.setenv("KIMBIM_AGENT_IDLE", "3")
    monkeypatch.setattr(D, "_data_dir", None)
    monkeypatch.setattr(K, "display_user", "")
    monkeypatch.setattr(client, "spawned", [])
    kim = tmp_path / "house.kim"
    shutil.copyfile(house_kim, kim)
    yield kim
    pids = list(client.spawned)
    sessions = data / "agent" / "sessions"
    for p in sessions.glob("*.json") if sessions.is_dir() else ():
        try:
            pids.append(int(json.loads(p.read_text(encoding="utf-8")).get("pid", 0)))
        except (OSError, ValueError):
            pass
    for pid in pids:
        _kill(pid)


def _discovery(kim) -> Path:
    return D.data_dir() / "agent" / "sessions" / f"{K.path_hash(kim)}.json"


def test_request_starts_worker(house):
    first = client.request(str(house), "_ping", {})
    assert first["ok"], first
    pid = first["result"]["pid"]
    assert pid != os.getpid() and K.pid_alive(pid)
    info = client.request(str(house), "project.info", {})
    assert info["ok"], info
    assert info["result"]["counts"]["walls"] == 8
    again = client.request(str(house), "_ping", {})
    assert again["result"]["pid"] == pid
    assert len(client.spawned) == 1
    found = json.loads(_discovery(house).read_text(encoding="utf-8"))
    assert found["pid"] == pid and found["kind"] == "worker" and found["project"] == str(house)
    lock = json.loads(K.lock_path(house).read_text(encoding="utf-8"))
    assert lock["user"] == "KimBim agent" and lock["pid"] == pid
    bye = client.request(str(house), "_shutdown", {})
    assert bye["ok"], bye
    assert _wait(lambda: not K.pid_alive(pid))
    assert not _discovery(house).exists() and not K.lock_path(house).exists()


def test_request_without_worker_and_no_start(house):
    out = client.request(str(house), "_ping", {}, start=False)
    assert out["ok"] is False and out["error"]["code"] == "no_session"
    assert client.spawned == []


def test_idle_exit_releases_lock(house):
    pid = client.request(str(house), "_ping", {})["result"]["pid"]
    assert K.lock_path(house).exists()
    assert _wait(lambda: not K.pid_alive(pid), 30)
    assert not K.lock_path(house).exists()
    assert not _discovery(house).exists()


def test_killed_worker_restarts_and_unparks(house):
    started = client.request(str(house), "task.start", {"title": "Rename walls"}, client="test")
    assert started["ok"], started
    task = started["result"]
    assert task["option"] == "agent/rename-walls"
    wrote = client.request(str(house), "elements.rename", {"elements": {"kind": "wall"}, "name": "X"}, client="test")
    assert wrote["ok"], wrote
    pid = client.request(str(house), "_ping", {})["result"]["pid"]
    _kill(pid)
    assert not K.pid_alive(pid)
    assert _discovery(house).exists()  # stale: the client removes it and starts another worker
    status = client.request(str(house), "task.status", {}, client="test")
    assert status["ok"], status
    assert status["result"]["task"]["id"] == task["id"] and status["result"]["task"]["status"] == "open"
    info = client.request(str(house), "project.info", {}, client="test")
    assert info["result"]["option"] == task["option"]
    new_pid = client.request(str(house), "_ping", {})["result"]["pid"]
    assert new_pid != pid
    again = client.request(str(house), "elements.rename", {"elements": {"kind": "wall"}, "name": "Y"}, client="test")
    assert again["ok"], again
    bye = client.request(str(house), "_shutdown", {})
    assert bye["ok"], bye
    assert _wait(lambda: not K.pid_alive(new_pid))
    # the shutdown parked the task: a version on its option, the project back on the base, main untouched
    s = Session.open(str(house))
    try:
        assert json.loads(V.project_state())["option"] == task["base_option"]
        assert all(w.Name not in ("X", "Y") for w in B._model.by_type("IfcWall"))
        assert s.tasks.get(task["id"]).status == "parked"
        assert json.loads(V.switch_option(task["option"]))["ok"]
        assert {w.Name for w in B._model.by_type("IfcWall")} == {"Y"}
    finally:
        s.close()


def test_locked_project(house):
    K.lock_path(house).write_text(json.dumps({"user": "Ana", "account": "ana", "machine": "elsewhere", "pid": 4242,
                                              "since": "2026-10-26T09:00"}), encoding="utf-8")
    out = client.request(str(house), "_ping", {})
    assert out["ok"] is False and out["error"]["code"] == "project_locked", out
    assert out["error"]["details"]["holder"]["user"] == "Ana"
    assert len(client.spawned) == 1
    assert _wait(lambda: not K.pid_alive(client.spawned[0]), 10)
    assert not _discovery(house).exists()


def test_wrong_authkey_rejected(house):
    pid = client.request(str(house), "_ping", {})["result"]["pid"]
    found = json.loads(_discovery(house).read_text(encoding="utf-8"))
    assert len(bytes.fromhex(found["authkey"])) == 32
    with pytest.raises(AuthenticationError):
        Client(found["address"], authkey=b"not the key")
    again = client.request(str(house), "_ping", {})
    assert again["ok"] and again["result"]["pid"] == pid
