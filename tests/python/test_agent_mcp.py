# SPDX-License-Identifier: GPL-3.0-or-later
"""`kimbim mcp` (D102, spec §7): the catalogue as MCP tools, through the SDK's in-process client. The first tests
use a recording stand-in for `client.request`; the last ones run the real background worker on the sample house."""
import base64
import json
import os
import shutil
import signal
import struct
import sys
from pathlib import Path

import anyio
import mcp_types as types
import pytest
from mcp import Client

from kimbim import documents as D
from kimbim import kimfile as K
from kimbim.agent import client, mcp_server, render
from kimbim.agent.catalogue import TOOLS

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 1, 1) + b"\x08\x02\x00\x00\x00"


class Recorder:
    """Stands in for client.request: records each call and answers from `answers` (tool -> envelope)."""

    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def __call__(self, project, tool, args=None, *, client="cli", task="", start=True, timeout=120):
        self.calls.append({"project": project, "tool": tool, "args": args, "client": client, "task": task})
        answer = self.answers.get(tool, {"ok": True, "result": {}})
        return answer(len(self.calls)) if callable(answer) else answer


def session(server, fn, name="tester"):
    """Run `await fn(client)` against `server` with the in-process client."""
    async def go():
        async with Client(server, client_info=types.Implementation(name=name, version="1")) as c:
            return await fn(c)
    return anyio.run(go)


def envelope_of(result) -> dict:
    texts = [b for b in result.content if b.type == "text"]
    assert len(texts) == 1
    return json.loads(texts[0].text)


def test_tools_are_the_catalogue(tmp_path):
    server = mcp_server.build_server(None, request=Recorder())

    async def go(c):
        return (await c.list_tools()).tools, c.instructions

    tools, instructions = session(server, go)
    by_name = {t.name: t for t in tools}
    public = [n for n in TOOLS if not n.startswith("_")]
    assert set(by_name) == {n.replace(".", "_") for n in public}
    dims = by_name["elements_set_dimensions"]
    assert dims.description == TOOLS["elements.set_dimensions"].description
    assert "dry_run" in dims.input_schema["properties"]
    assert "project" in dims.input_schema["properties"]
    assert "project" in dims.input_schema["required"]  # no --project: every call names it
    assert "dry_run" not in by_name["project_info"].input_schema["properties"]  # a read tool
    lines = instructions.strip().splitlines()
    assert len(lines) <= 25
    assert "never accept your own option" in instructions.lower()
    assert "take a snapshot to check your work" in instructions.lower()


def test_project_optional_with_server_project(tmp_path):
    server = mcp_server.build_server(str(tmp_path / "house.kim"), request=Recorder())

    async def go(c):
        return (await c.list_tools()).tools

    dims = {t.name: t for t in session(server, go)}["elements_set_dimensions"]
    assert "project" in dims.input_schema["properties"]
    assert "project" not in dims.input_schema.get("required", [])
    assert "elements" in dims.input_schema["required"]  # the tool's own required parameters stay


def test_calls_go_to_the_worker_with_the_client_and_task(tmp_path):
    kim = str(tmp_path / "house.kim")
    rec = Recorder({"task.start": {"ok": True, "result": {"id": "t1", "title": "Widen"}},
                    "task.finish": {"ok": True, "result": {"task": {"id": "t1"}}}})
    server = mcp_server.build_server(kim, request=rec)

    async def go(c):
        await c.call_tool("project_info", {})
        await c.call_tool("task_start", {"title": "Widen"})
        r = await c.call_tool("elements_set_dimensions",
                              {"elements": {"kind": "window"}, "width": "+50cm", "dry_run": True})
        await c.call_tool("task_finish", {"summary": "done"})
        await c.call_tool("project_info", {"project": str(tmp_path / "other.kim")})
        return r

    r = session(server, go)
    assert not r.is_error
    assert [c["tool"] for c in rec.calls] == ["project.info", "task.start", "elements.set_dimensions",
                                              "task.finish", "project.info"]
    assert {c["client"] for c in rec.calls} == {"mcp-tester"}
    assert [c["task"] for c in rec.calls] == ["", "", "t1", "t1", ""]  # remembered after start, forgotten after finish
    assert rec.calls[2]["args"] == {"elements": {"kind": "window"}, "width": "+50cm", "dry_run": True}
    assert rec.calls[0]["project"] == kim
    assert rec.calls[4]["project"] == str(tmp_path / "other.kim")  # `project` overrides the server's, and is not passed on
    assert "project" not in rec.calls[4]["args"]


def test_stale_task_is_forgotten(tmp_path):
    def status(n):
        if n == 3:  # the architect finished the task meanwhile
            return {"ok": False, "error": {"code": "no_task", "message": "There is no open task."}}
        return {"ok": True, "result": {}}
    rec = Recorder({"task.start": {"ok": True, "result": {"id": "t1"}}, "elements.find": status})
    server = mcp_server.build_server(str(tmp_path / "p.kim"), request=rec)

    async def go(c):
        await c.call_tool("task_start", {"title": "x"})
        await c.call_tool("elements_find", {})
        return await c.call_tool("elements_find", {})

    r = session(server, go)
    assert not r.is_error
    assert [(c["tool"], c["task"]) for c in rec.calls] == [
        ("task.start", ""), ("elements.find", "t1"), ("elements.find", "t1"), ("elements.find", "")]


def test_error_envelope_is_an_error_result(tmp_path):
    bad = {"ok": False, "error": {"code": "bad_input", "message": "Invalid input."}}
    server = mcp_server.build_server(str(tmp_path / "p.kim"), request=Recorder({"elements.get": bad}))

    async def go(c):
        return await c.call_tool("elements_get", {"elements": ["x"]})

    r = session(server, go)
    assert r.is_error
    assert envelope_of(r) == bad


def test_missing_project_and_unknown_tool(tmp_path):
    rec = Recorder()
    server = mcp_server.build_server(None, request=rec)

    async def go(c):
        return await c.call_tool("project_info", {}), await c.call_tool("nope_nothing", {})

    missing, unknown = session(server, go)
    assert missing.is_error and envelope_of(missing)["error"]["code"] == "bad_input"
    assert unknown.is_error and envelope_of(unknown)["error"]["code"] == "unknown_tool"
    assert rec.calls == []


def test_snapshot_adds_the_image(tmp_path):
    png = tmp_path / "shot.png"
    png.write_bytes(PNG)
    rec = Recorder({"snapshot.take": {"ok": True, "result": {"path": str(png), "width": 1, "height": 1}}})
    server = mcp_server.build_server(str(tmp_path / "p.kim"), request=rec)

    async def go(c):
        return await c.call_tool("snapshot_take", {"view": "3d"})

    r = session(server, go)
    images = [b for b in r.content if b.type == "image"]
    assert len(images) == 1 and images[0].mime_type == "image/png"
    assert base64.b64decode(images[0].data) == PNG
    assert envelope_of(r)["result"]["path"] == str(png)


def test_project_info_resource(tmp_path):
    rec = Recorder({"project.info": {"ok": True, "result": {"name": "House", "levels": 2}}})
    server = mcp_server.build_server(str(tmp_path / "p.kim"), request=rec)

    async def go(c):
        listed = [str(r.uri) for r in (await c.list_resources()).resources]
        read = await c.read_resource("kimbim://project/info")
        return listed, read

    listed, read = session(server, go)
    assert listed == ["kimbim://project/info"]
    assert json.loads(read.contents[0].text) == {"name": "House", "levels": 2}
    assert rec.calls[0]["tool"] == "project.info" and rec.calls[0]["client"] == "mcp-tester"


# ---------------------------------------------------------------- the real worker on the sample house

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
        if K.pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


def test_worker_project_info_and_task(house):
    server = mcp_server.build_server(str(house))

    async def go(c):
        info = await c.call_tool("project_info", {})
        started = await c.call_tool("task_start", {"title": "Widen windows"})
        status = await c.call_tool("task_status", {})
        abandoned = await c.call_tool("task_abandon", {})
        return info, started, status, abandoned

    info, started, status, abandoned = session(server, go)
    assert not info.is_error, info.content
    assert envelope_of(info)["result"]
    assert not started.is_error, started.content
    task = envelope_of(started)["result"]
    assert task["client"] == "mcp-tester"
    assert not status.is_error and not abandoned.is_error


@pytest.mark.app
@pytest.mark.skipif(render.app_binary() is None, reason="the KimBim app binary isn't built")
def test_worker_snapshot_image(house):
    server = mcp_server.build_server(str(house))

    async def go(c):
        return await c.call_tool("snapshot_take", {"view": "3d", "size": [320, 240]})

    r = session(server, go)
    assert not r.is_error, r.content
    images = [b for b in r.content if b.type == "image"]
    assert len(images) == 1
    assert base64.b64decode(images[0].data)[:8] == b"\x89PNG\r\n\x1a\n"


def test_stdio_server_from_setup_command(house):
    """The command `kimbim setup` writes, started the way a client starts it: over stdio, with no activated
    environment on PATH (only the system's folders)."""
    from mcp import StdioServerParameters

    from kimbim.agent import clients

    command, env = clients.server_command(str(house))
    env = {**env, "KIMBIM_DATA_DIR": os.environ["KIMBIM_DATA_DIR"], "KIMBIM_AGENT_IDLE": "3"}
    if sys.platform == "win32":
        root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        env["PATH"] = os.pathsep.join([os.path.join(root, "System32"), root])
    else:
        env["PATH"] = "/usr/bin:/bin"
    params = StdioServerParameters(command=command[0], args=command[1:], env=env)

    async def go(c):
        names = [t.name for t in (await c.list_tools()).tools]
        return names, c.instructions, await c.call_tool("project_info", {})

    names, instructions, info = session(params, go, name="stdio-test")
    assert "elements_set_dimensions" in names and "snapshot_take" in names
    assert "Take a snapshot to check your work" in instructions
    assert not info.is_error, info.content
