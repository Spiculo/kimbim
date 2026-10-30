# SPDX-License-Identifier: GPL-3.0-or-later
"""Live agent sessions (D102 phase 2): the app hosts the project, the CLI finds it through the same discovery
file as an offline worker, and calls run on the app's thread with undo steps and selection."""
import json
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import documents as D
from kimbim.agent import client

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402


@pytest.fixture(scope="module")
def house_kim(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("house")
    saved = D._data_dir
    D._data_dir = folder / "data"
    try:
        ifc = folder / "house.ifc"
        make_house.build(str(ifc))
        kim = folder / "house.kim"
        assert json.loads(D.import_ifc(str(ifc), str(kim)))["ok"]
        D.close_document()
    finally:
        D._data_dir = saved
    return kim


@pytest.fixture
def app_house(house_kim, tmp_path, monkeypatch):
    """A .kim opened the way the app opens it: the document is attached, the lock is held by this process."""
    data = tmp_path / "data"
    monkeypatch.setenv("KIMBIM_DATA_DIR", str(data))
    monkeypatch.setattr(D, "_data_dir", None)
    kim = tmp_path / "house.kim"
    shutil.copyfile(house_kim, kim)
    opened = json.loads(D.open_kim(str(kim)))
    assert opened["ok"], opened
    assert json.loads(B.open_model(opened["path"]))["ok"]
    started = json.loads(B.agent_live_start())
    assert started["ok"], started
    yield kim
    B.agent_live_stop()
    D.close_document()


def call_live(kim: Path, tool: str, args: dict, client_id: str = "live-test", task: str = "") -> dict:
    """A CLI/MCP call while the app drains its request queue on this (the test's) thread."""
    out: dict = {}

    def request():
        out["envelope"] = client.request(str(kim), tool, args, client=client_id, task=task)

    thread = threading.Thread(target=request, daemon=True)
    thread.start()
    ui = {}
    end = time.monotonic() + 30
    while thread.is_alive() and time.monotonic() < end:
        pending = json.loads(B.agent_live_pending()).get("request")
        if pending is None:
            time.sleep(0.01)
            continue
        ran = json.loads(B.agent_live_run(pending["id"]))
        if ran.get("busy"):
            time.sleep(0.01)
            continue
        ui = ran.get("ui") or {}
    thread.join(5)
    assert not thread.is_alive(), f"{tool} did not finish"
    return {"envelope": out.get("envelope", {}), "ui": ui}


def test_live_project_info_and_selection(app_house):
    info = call_live(app_house, "project.info", {})["envelope"]
    assert info["ok"] and info["result"]["mode"] == "live"
    walls = call_live(app_house, "elements.find", {"elements": {"kind": "wall"}})["envelope"]
    assert walls["ok"] and walls["result"]["items"]
    guid = walls["result"]["items"][0]["guid"]
    B.agent_live_set_selection(json.dumps([guid]))
    got = call_live(app_house, "selection.get", {})["envelope"]
    assert got["ok"] and got["result"]["elements"][0]["guid"] == guid
    chosen = call_live(app_house, "selection.set", {"elements": [guid]})
    assert chosen["envelope"]["ok"] and chosen["ui"]["select"] == [guid]


def test_live_task_and_proposal_accept(app_house):
    started = call_live(app_house, "task.start", {"title": "Rename walls"})
    assert started["envelope"]["ok"], started
    task = started["envelope"]["result"]["id"]
    renamed = call_live(app_house, "elements.rename", {"elements": {"kind": "wall"}, "name": "Agent wall"}, task=task)
    assert renamed["envelope"]["ok"] and renamed["ui"].get("edited"), renamed
    finished = call_live(app_house, "task.finish", {"summary": "renamed"}, task=task)
    assert finished["envelope"]["ok"], finished
    listed = json.loads(B.agent_proposals())["proposals"]
    assert [p["id"] for p in listed] == [task]
    accepted = json.loads(B.agent_accept(task))
    assert accepted["ok"], accepted
    assert json.loads(B.agent_proposals())["proposals"] == []
    assert {w.Name for w in B._model.by_type("IfcWall")} == {"Agent wall"}  # combined into the base option


def test_ready_proposals_are_listed_when_the_live_host_is_off(app_house):
    """The proposal bar reads the task files of the open project, so a failed/read-only live host does not
    hide a proposal waiting for review."""
    started = call_live(app_house, "task.start", {"title": "Offline proposal"})
    task = started["envelope"]["result"]["id"]
    call_live(app_house, "elements.rename", {"elements": {"kind": "wall"}, "name": "Offline wall"}, task=task)
    call_live(app_house, "task.finish", {"summary": "offline"}, task=task)
    B.agent_live_stop()
    listed = json.loads(B.agent_proposals())["proposals"]
    assert [p["id"] for p in listed] == [task]


def test_live_task_and_proposal_reject(app_house):
    started = call_live(app_house, "task.start", {"title": "Reject me"})
    task = started["envelope"]["result"]["id"]
    call_live(app_house, "elements.rename", {"elements": {"kind": "wall"}, "name": "Never"}, task=task)
    call_live(app_house, "task.finish", {"summary": "no"}, task=task)
    rejected = json.loads(B.agent_reject(task))
    assert rejected["ok"], rejected
    assert json.loads(B.agent_proposals())["proposals"] == []
    assert all(w.Name != "Never" for w in B._model.by_type("IfcWall"))
