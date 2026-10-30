# SPDX-License-Identifier: GPL-3.0-or-later
"""Stored agent sessions (D111, docs/18 §4): metadata, transcript, lifecycle, worktrees and the CLI."""
import json
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import documents as D
from kimbim import versioning as V
from kimbim.agent import sessions
from kimbim.agent.catalogue import call_tool
from kimbim.agent.session import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    monkeypatch.setenv("KIMBIM_DATA_DIR", str(tmp_path / "data"))
    yield tmp_path / "data"


@pytest.fixture
def folder(tmp_path):
    """A versioned folder project (a worktree needs a repository outside a .kim archive)."""
    folder = tmp_path / "house"
    folder.mkdir()
    ifc = tmp_path / "house.ifc"
    make_house.build(str(ifc))
    from kimbim.project import Project

    project = Project.init(folder)
    project.commit(ifc, "Initial")
    return folder


@pytest.fixture
def opened():
    live = []
    yield live
    for s in live:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass


def test_store_lifecycle(data_dir, folder):
    store = sessions.Store(user="ana")
    one = store.create(str(folder), "Widen windows", provider="anthropic", model="claude")
    assert store.get(one.id).title == "Widen windows"
    assert [s.id for s in store.all(str(folder))] == [one.id]
    assert store.all(str(folder / "other")) == []

    store.append(one.id, {"role": "user", "text": "hello"})
    store.append(one.id, {"role": "assistant", "text": "hi"})
    assert [m["content"] for m in store.messages(one.id)] == ["hello", "hi"]

    two = store.fork(one.id)
    assert two.id != one.id and "copy" in two.title
    assert store.messages(two.id) == store.messages(one.id)
    assert store.get(one.id).branch == ""  # a fork starts on the base, not on the old branch

    assert store.rename(one.id, "Wider windows").title == "Wider windows"
    assert store.archive(one.id).status == "archived"
    assert [s for s in store.all(str(folder)) if s.id == one.id][0].status == "archived"
    assert store.restore(one.id).status == "open"
    assert store.delete(two.id)["transcript"] is True
    assert store.all(str(folder))[0].id == one.id


def test_sessions_are_per_user(data_dir, folder):
    ana = sessions.Store(user="ana")
    record = ana.create(str(folder), "Ana's session")
    assert [s.id for s in ana.all(str(folder))] == [record.id]
    assert sessions.Store(user="bob").all(str(folder)) == []


def test_review_session_is_not_deleted_silently(data_dir, folder):
    store = sessions.Store()
    record = store.create(str(folder), "Proposal")
    store.update(record.id, status="ready")
    with pytest.raises(sessions.AgentError) as ex:
        store.delete(record.id)
    assert ex.value.code == "session_review"
    assert store.get(record.id).status == "ready"
    store.delete(record.id, confirm=True)
    with pytest.raises(sessions.AgentError):
        store.get(record.id)


def test_transcript_keeps_tool_lines_and_attachments(data_dir, folder, tmp_path):
    store = sessions.Store()
    record = store.create(str(folder), "Look")
    store.append(record.id, {"role": "user", "text": "how many windows?"})
    store.record_tool(record.id, "elements.find", "elements.find: 12 item(s)", ok=True,
                      snapshot=str(tmp_path / "shot.png"), result={"guids": ["a"]})
    store.append(record.id, {"role": "assistant", "text": "Twelve."})
    assert [m["role"] for m in store.messages(record.id)] == ["user", "assistant"]
    assert [e["role"] for e in store.transcript(record.id)] == ["status", "user", "tool", "tool_result", "assistant"]

    shot = tmp_path / "shot.png"
    shot.write_bytes(b"png")
    first = store.attachment(record.id, str(shot))
    again = store.attachment(record.id, str(shot))
    assert first == again and Path(first).read_bytes() == b"png"


def test_worktree_sessions_do_not_share_a_working_tree(folder, opened):
    store = sessions.Store()
    a = store.create(str(folder), "Session A")
    b = store.create(str(folder), "Session B")
    assert a.worktree == "" and b.worktree == ""

    sa = Session.open(str(folder), "test", a.id)
    opened.append(sa)
    a_work = sa.work
    assert a_work != str(folder) and Path(a_work).is_dir()
    assert store.get(a.id).worktree == a_work
    started = call_tool(sa, "task.start", {"title": "A"}, client="test")
    assert started["ok"], started
    branch = started["result"]["option"]
    assert branch.startswith("agent/")
    wall = B._model.by_type("IfcWall")[0]
    assert json.loads(B.set_name(json.dumps([wall.GlobalId]), "A wall"))["ok"]
    assert call_tool(sa, "task.finish", {"summary": "renamed"}, client="test")["ok"]
    assert store.get(a.id).status == "ready" and store.get(a.id).branch == branch
    assert store.for_task(started["result"]["id"], str(folder)).id == a.id

    # B opens its own worktree on the base; the owner's repository is still on main at the first version
    sb = Session.open(str(folder), "test", b.id)
    opened.append(sb)
    assert sb.work != a_work and Path(a_work).is_dir()
    assert json.loads(V.project_state())["option"] == "main"
    assert all(w.Name != "A wall" for w in B._model.by_type("IfcWall"))
    from kimbim.project import Project

    owner = Project.open(folder)
    assert owner.repo.current_branch() == "main"
    assert V._encode(branch) in owner.repo.branches()


def test_opening_a_session_restores_its_branch(folder, opened):
    store = sessions.Store()
    record = store.create(str(folder), "Resume me")
    first = Session.open(str(folder), "test", record.id)
    opened.append(first)
    call_tool(first, "task.start", {"title": "Resume me"}, client="test")
    branch = json.loads(V.project_state())["option"]
    assert branch.startswith("agent/")
    first.close()
    opened.remove(first)

    again = Session.open(str(folder), "test", record.id)
    opened.append(again)
    assert json.loads(V.project_state())["option"] == branch
    assert again.stored.branch == branch


def test_archived_session_refuses_to_open(data_dir, folder):
    store = sessions.Store()
    record = store.create(str(folder), "Old")
    store.archive(record.id)
    with pytest.raises(sessions.AgentError) as ex:
        Session.open(str(folder), "test", record.id)
    assert ex.value.code == "session_archived"


def test_the_assistant_records_its_turn_once(folder):
    from kimbim.agent import assistant

    store = sessions.Store()
    record = store.create(str(folder), "Ask")
    config = {"session": record.id, "provider": "openai", "model": "gpt"}
    messages = [{"role": "user", "content": "How many windows?"}]
    assistant._open_transcript(config, messages)
    assistant._open_transcript(config, messages)  # a retry of the same turn does not duplicate the question
    assert [e["role"] for e in store.transcript(record.id)] == ["status", "user"]
    assert store.get(record.id).provider == "openai" and store.get(record.id).model == "gpt"
    assert assistant._session_worker(record.id) == str(folder)
    assistant._tx.store = assistant._tx.id = None


def test_the_assistant_works_in_the_session_worktree(folder, monkeypatch):
    from kimbim.agent import assistant

    store = sessions.Store()
    record = store.create(str(folder), "Ask")
    calls, owner = [], []
    monkeypatch.setattr(assistant.client, "request",
                        lambda project, tool, args, **kw: calls.append((project, tool, kw))
                        or {"ok": True, "result": {}})
    monkeypatch.setattr(assistant.live, "call_tool_sync",
                        lambda tool, args, **kw: owner.append((tool, args)))
    back = {"project_info": "project.info", "task_start": "task.start"}
    assert assistant._tool("project_info", {}, back, record.id)["ok"]
    assert calls[-1][0] == str(folder) and calls[-1][2]["session"] == record.id
    assert assistant._tool("task_start", {"title": "Widen"}, back, record.id)["ok"]
    assert owner and owner[0][0] == "_owner_save" and "Before agent" in owner[0][1]["message"]
    assert calls[-1][1] == "task.start" and calls[-1][2]["session"] == record.id


def test_the_cli_lists_and_renames_sessions(folder, capsys):
    from kimbim.agent import cli

    assert cli.main(["--project", str(folder), "sessions", "new", "CLI session"]) == 0
    session_id = capsys.readouterr().out.strip()
    assert sessions.Store().get(session_id).title == "CLI session"

    assert cli.main(["--project", str(folder), "sessions", "list"]) == 0
    assert session_id in capsys.readouterr().out

    assert cli.main(["--project", str(folder), "sessions", "rename", session_id, "Renamed"]) == 0
    assert sessions.Store().get(session_id).title == "Renamed"
    assert cli.main(["--project", str(folder), "sessions", "archive", session_id]) == 0
    assert sessions.Store().get(session_id).status == "archived"


def test_a_kim_session_uses_the_shared_worker(tmp_path):
    from kimbim import kimfile as K
    from kimbim.agent import client, worker

    ifc = tmp_path / "house.ifc"
    make_house.build(str(ifc))
    kim = tmp_path / "house.kim"
    out = json.loads(D.import_ifc(str(ifc), str(kim)))
    assert out["ok"], out
    json.loads(B.open_model(out["path"]))
    D.close_document()

    store = sessions.Store()
    record = store.create(str(kim), "Kim session")
    started = client.request(str(kim), "task.start", {"title": "Kim"}, client="test", session=record.id)
    assert started["ok"], started
    assert started["result"]["option"].startswith("agent/")
    assert store.get(record.id).tasks == [started["result"]["id"]]
    assert store.get(record.id).branch == started["result"]["option"]
    pid = client.request(str(kim), "_ping", {}, session=record.id)["result"]["pid"]
    assert worker.discovery_path(str(kim), record.id).exists() is False  # no separate worker for a .kim
    assert worker.discovery_path(str(kim)).is_file()
    assert client.request(str(kim), "_shutdown", {}, session=record.id)["ok"]
    import time

    end = time.monotonic() + 20
    while K.pid_alive(pid) and time.monotonic() < end:
        time.sleep(0.1)
    assert not K.pid_alive(pid)
    assert store.get(record.id).status == "parked"


def test_the_session_worker_keeps_its_own_worktree(folder):
    import time

    from kimbim import kimfile as K
    from kimbim.agent import client, worker

    store = sessions.Store()
    record = store.create(str(folder), "Worker session")
    first = client.request(str(folder), "_ping", {}, session=record.id)
    assert first["ok"], first
    pid = first["result"]["pid"]
    assert pid != __import__("os").getpid()
    assert first["result"]["session"] == record.id
    assert worker.discovery_path(str(folder), record.id).is_file()
    assert not worker.discovery_path(str(folder)).exists()  # not the project's shared worker
    assert not K.lock_path(folder).exists()  # the app's working copy is not locked
    info = client.request(str(folder), "project.info", {}, session=record.id)
    assert info["ok"], info
    assert "worktrees" in info["result"]["worktree"]
    started = client.request(str(folder), "task.start", {"title": "Worker"}, client="test", session=record.id)
    assert started["ok"], started
    assert started["result"]["option"].startswith("agent/")
    bye = client.request(str(folder), "_shutdown", {}, session=record.id)
    assert bye["ok"], bye
    end = time.monotonic() + 20
    while K.pid_alive(pid) and time.monotonic() < end:
        time.sleep(0.1)
    assert not K.pid_alive(pid)
    assert not worker.discovery_path(str(folder), record.id).exists()
    assert store.get(record.id).status == "parked"
