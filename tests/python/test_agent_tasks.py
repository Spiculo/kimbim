# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent tasks (D102): option mode puts an agent's edits in a design option agent/<slug>, direct mode saves them
with a way back; task state is stored with the project."""
import json
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import documents as D
from kimbim import kimfile as K
from kimbim import settings as S
from kimbim import versioning as V
from kimbim.agent import catalogue, tasks
from kimbim.agent.catalogue import bridge, call_tool, tool
from kimbim.agent.session import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402


@pytest.fixture(autouse=True)
def rename_tool():
    """A throwaway write tool (elements.rename arrives with Task 6)."""
    import kimbim.agent.tools  # noqa: F401  (registers task.*, project.*)

    @tool("test.rename", {"required": ["guids", "name"], "properties": {
        "guids": {"type": "array", "items": {"type": "string"}}, "name": {"type": "string"}}}, writes=True)
    def rename(session, guids, name):
        """Rename elements."""
        bridge(B.set_name, json.dumps(guids), name)
        return {"renamed": len(guids)}

    yield
    catalogue.TOOLS.pop("test.rename", None)


def _house_kim(tmp_path) -> Path:
    ifc = tmp_path / "house.ifc"
    make_house.build(str(ifc))
    kim = tmp_path / "house.kim"
    out = json.loads(D.import_ifc(str(ifc), str(kim)))
    assert out["ok"], out
    assert json.loads(B.open_model(out["path"]))["ok"]
    D.close_document()
    return kim


@pytest.fixture
def house(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    monkeypatch.setattr(K, "display_user", "")
    kim = _house_kim(tmp_path)
    opened = []

    def open_(path=kim):
        s = Session.open(str(path))
        opened.append(s)
        return s

    yield open_
    for s in opened:
        s.close()


def run(s, tool_name, **args):
    return call_tool(s, tool_name, args, client="test")


def walls():
    return sorted(B._model.by_type("IfcWall"), key=lambda w: w.GlobalId)


def names():
    return {w.GlobalId: w.Name for w in walls()}


def option():
    return json.loads(V.project_state())["option"]


def test_slug():
    assert tasks.slug("Ampliar ventanas ñ") == "ampliar-ventanas-n"
    assert tasks.slug("  Widen   first-floor WINDOWS!! ") == "widen-first-floor-windows"
    assert len(tasks.slug("x" * 100)) == 40
    assert tasks.slug("¿¿??") == "task"


def test_option_task_round_trip(house):
    s = house()
    before = names()
    r = run(s, "task.start", title="Widen windows")
    assert r["ok"], r
    task = r["result"]
    assert task["mode"] == "option" and task["option"] == "agent/widen-windows" and task["status"] == "open"
    assert len(task["id"]) == 8 and task["base_option"] == "main" and task["client"] == "test"
    assert option() == "agent/widen-windows"
    two = [w.GlobalId for w in walls()[:2]]
    assert run(s, "test.rename", guids=[two[0]], name="Agent A")["ok"]
    assert run(s, "test.rename", guids=[two[1]], name="Agent B")["ok"]
    st = run(s, "task.status")["result"]
    assert st["task"]["id"] == task["id"]
    assert set(two) <= {m["guid"] for m in st["changes"]["modified"]}
    r = run(s, "task.finish", summary="Renamed two walls")
    assert r["ok"], r
    assert r["result"]["task"]["status"] == "ready"
    assert option() == "main"
    assert names() == before  # main's model unchanged
    assert "agent/widen-windows" in json.loads(V.options())["options"]
    log = V._project.log(V._encode("agent/widen-windows"), 10)
    assert log[0].author_name == "test (agent)"
    assert log[0].message.startswith("Widen windows") and "Renamed two walls" in log[0].message
    assert log[1].id == task["base_version"]  # one new version on the option
    assert run(s, "task.status")["result"]["task"] is None  # nothing open now


def test_before_agent_version(house):
    s = house()
    g = walls()[0].GlobalId
    assert json.loads(B.set_name(json.dumps([g]), "Architect"))["ok"]  # unsaved work on main
    task = run(s, "task.start", title="Tidy")["result"]
    head = V._project.log(V._encode("main"), 1)[0]
    assert head.message == "Before agent: Tidy"
    assert task["base_version"] == head.id
    assert run(s, "test.rename", guids=[g], name="Agent")["ok"]
    assert run(s, "task.finish", summary="done")["ok"]
    log = V._project.log(V._encode("agent/tidy"), 10)
    assert log[1].id == head.id
    assert names()[g] == "Architect"


def test_implicit_task(house):
    s = house()
    g = [w.GlobalId for w in walls()[:2]]
    r = run(s, "test.rename", guids=[g[0]], name="One")
    assert r["ok"], r
    open_ = [t for t in s.tasks.all() if t.status == "open"]
    assert len(open_) == 1 and open_[0].title.startswith("test.rename")
    assert option() == open_[0].option and open_[0].option.startswith("agent/test-rename")
    assert run(s, "test.rename", guids=[g[1]], name="Two")["ok"]
    assert len(s.tasks.all()) == 1
    st = run(s, "task.status")["result"]
    assert set(g) <= {m["guid"] for m in st["changes"]["modified"]}  # (a wall's windows may be reported too)
    assert not st["changes"]["added"] and not st["changes"]["removed"]


def test_task_busy(house):
    s = house()
    first = run(s, "task.start", title="First")["result"]
    r = run(s, "task.start", title="Second")
    assert r["error"]["code"] == "task_busy"
    assert r["error"]["details"]["task"] == first["id"]
    assert len(s.tasks.all()) == 1


def test_two_clients_can_have_tasks(house):
    """D102 phase 2: one task per client, several clients at once, each on its own option from the same base."""
    s = house()
    a = call_tool(s, "task.start", {"title": "A"}, client="a")["result"]
    b = call_tool(s, "task.start", {"title": "B"}, client="b")
    assert b["ok"], b
    b = b["result"]
    assert a["option"] != b["option"] and a["base_option"] == b["base_option"] == "main"
    again = call_tool(s, "task.start", {"title": "A2"}, client="a")
    assert again["error"]["code"] == "task_busy" and again["error"]["details"]["task"] == a["id"]
    assert {t.id for t in s.tasks.all() if t.status in tasks.ACTIVE} == {a["id"], b["id"]}
    # each client's next write goes to its own option
    ga = walls()[0].GlobalId
    gb = walls()[1].GlobalId
    assert call_tool(s, "test.rename", {"guids": [ga], "name": "A wall"}, client="a")["ok"]
    rb = call_tool(s, "test.rename", {"guids": [gb], "name": "B wall"}, client="b")
    assert rb["ok"], rb
    assert call_tool(s, "task.finish", {"summary": "A"}, client="a")["ok"]
    assert call_tool(s, "task.finish", {"summary": "B"}, client="b")["ok"]
    assert {t.status for t in s.tasks.all()} == {"ready"}


def test_abandon_deletes_option(house):
    s = house()
    before = names()
    task = run(s, "task.start", title="Nope")["result"]
    assert run(s, "test.rename", guids=[walls()[0].GlobalId], name="Gone")["ok"]
    r = run(s, "task.abandon")
    assert r["ok"], r
    assert r["result"]["status"] == "abandoned"
    assert option() == "main" and names() == before
    assert task["option"] not in json.loads(V.options())["options"]
    assert run(s, "task.status")["result"]["task"] is None


def test_direct_plain_ifc_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    ifc = tmp_path / "plain.ifc"
    make_house.build(str(ifc))
    original = ifc.read_bytes()
    s = Session.open(str(ifc))
    try:
        assert json.loads(S.set_project_settings(json.dumps({"agent_changes": "direct"})))["ok"]  # the architect
        task = run(s, "task.start", title="Direct")["result"]
        assert task["mode"] == "direct" and task["option"] == ""
        assert (tmp_path / "plain.before-agent.ifc").read_bytes() == original  # the way back, made at start
        g = walls()[0].GlobalId
        assert run(s, "test.rename", guids=[g], name="Direct edit")["ok"]
        r = run(s, "task.finish", summary="one wall")
        assert r["ok"], r
        assert (tmp_path / "plain.before-agent.ifc").read_bytes() == original
        import ifcopenshell
        assert ifcopenshell.open(str(ifc)).by_guid(g).Name == "Direct edit"
        files = list((tmp_path / "data" / "agent" / "tasks" / K.path_hash(str(ifc))).glob("*.json"))
        assert len(files) == 1 and json.loads(files[0].read_text(encoding="utf-8"))["status"] == "ready"
    finally:
        s.close()


def test_not_versioned(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    ifc = tmp_path / "plain.ifc"
    make_house.build(str(ifc))
    s = Session.open(str(ifc))
    try:
        r = run(s, "task.start", title="Option")
        assert r["error"]["code"] == "not_versioned" and "direct" in r["error"]["hint"]
        assert run(s, "task.start", title="Option", mode="option")["error"]["code"] == "not_versioned"
        # a write outside a task can't start one either: nothing bypasses review
        assert run(s, "test.rename", guids=[walls()[0].GlobalId], name="X")["error"]["code"] == "not_versioned"
        assert s.tasks.all() == []
    finally:
        s.close()


def test_agent_decides(house):
    s = house()
    assert json.loads(S.set_project_settings(json.dumps({"agent_changes": "agent_decides"})))["ok"]
    assert run(s, "task.start", title="Small", mode="direct")["result"]["mode"] == "direct"
    assert run(s, "task.abandon")["ok"]
    assert run(s, "task.start", title="Big")["result"]["mode"] == "option"


def test_slug_unicode(house):
    s = house()
    assert run(s, "task.start", title="Ampliar ventanas ñ")["result"]["option"] == "agent/ampliar-ventanas-n"
    assert run(s, "test.rename", guids=[walls()[0].GlobalId], name="A")["ok"]
    assert run(s, "task.finish", summary="first")["ok"]
    assert run(s, "task.start", title="Ampliar ventanas ñ")["result"]["option"] == "agent/ampliar-ventanas-n-2"


def test_reserved_settings(house):
    s = house()
    for key, value in (("agent_changes", "direct"), ("agent_scripts", True)):
        r = run(s, "project.set_settings", changes={key: value})
        assert r["error"]["code"] == "setting_reserved", r
    assert s.tasks.all() == [] and option() == "main"  # refused before any task started
    assert run(s, "project.set_settings", changes={"length_decimals": 9})["error"]["code"] == "bad_input"
    assert s.tasks.all() == []
    assert S.current()["agent_changes"] == "option" and S.current()["agent_scripts"] is False
    r = run(s, "project.set_settings", changes={"length_decimals": 3})
    assert r["ok"], r
    assert S.current()["length_decimals"] == 3
    assert not json.loads(S.set_project_settings(json.dumps({"agent_changes": "sometimes"})))["ok"]
    assert not json.loads(S.set_project_settings(json.dumps({"agent_scripts": "yes"})))["ok"]


def test_task_file_in_kim(house, tmp_path, monkeypatch):
    s = house()
    task = run(s, "task.start", title="Travel")["result"]
    assert run(s, "test.rename", guids=[walls()[0].GlobalId], name="T")["ok"]
    assert run(s, "task.finish", summary="ok")["ok"]
    s.close()
    kim = tmp_path / "house.kim"
    import zipfile
    assert f".kimbim/agent/tasks/{task['id']}.json" in zipfile.ZipFile(kim).namelist()
    monkeypatch.setattr(D, "_data_dir", tmp_path / "fresh")
    s2 = house(kim)
    listed = run(s2, "task.status")["result"]["tasks"]
    assert [(t["id"], t["status"]) for t in listed] == [(task["id"], "ready")]


def test_entries_pack_task_files(tmp_path):
    (tmp_path / ".kimbim" / "agent" / "tasks").mkdir(parents=True)
    (tmp_path / ".kimbim" / "agent" / "tasks" / "abcd1234.json").write_text("{}")
    assert ".kimbim/agent/tasks/abcd1234.json" in [name for _, name in K._entries(tmp_path)]


def test_park_unpark(house):
    s = house()
    task = run(s, "task.start", title="Long job")["result"]
    g = walls()[0].GlobalId
    assert run(s, "test.rename", guids=[g], name="Before park")["ok"]
    s.tasks.park()
    assert option() == "main" and names()[g] != "Before park"
    assert s.tasks.get(task["id"]).status == "parked"
    wip = V._project.log(V._encode(task["option"]), 1)[0]
    assert wip.message == "Work in progress: Long job" and wip.author_name == "test (agent)"
    # the next write unparks it: back on the option with the work in progress
    assert run(s, "test.rename", guids=[walls()[1].GlobalId], name="After park")["ok"]
    assert option() == task["option"] and s.tasks.get(task["id"]).status == "open"
    assert names()[g] == "Before park"
    s.tasks.park()
    s.tasks.unpark()
    assert option() == task["option"] and names()[g] == "Before park"
    assert run(s, "test.rename", guids=[walls()[2].GlobalId], name="Last")["ok"]
    assert run(s, "task.finish", summary="done")["ok"]
    assert option() == "main"
    log = V._project.log(V._encode(task["option"]), 5)
    assert log[0].message.startswith("Long job") and log[1].message == "Work in progress: Long job"


def test_direct_versioned(house):
    s = house()
    assert json.loads(S.set_project_settings(json.dumps({"agent_changes": "direct"})))["ok"]
    g = walls()[0].GlobalId
    task = run(s, "task.start", title="Quick fix")["result"]
    assert task["mode"] == "direct" and option() == "main"
    assert run(s, "test.rename", guids=[g], name="Fixed")["ok"]
    assert run(s, "task.finish", summary="x")["ok"]
    head = V._project.log(V._encode("main"), 2)
    assert head[0].message == "Quick fix (agent)" and head[0].author_name == "test (agent)"
    assert not B._dirty() and names()[g] == "Fixed"


def test_direct_abandon_undoes(house):
    s = house()
    assert json.loads(S.set_project_settings(json.dumps({"agent_changes": "direct"})))["ok"]
    g = walls()[0].GlobalId
    before = names()[g]
    run(s, "task.start", title="Oops")
    assert run(s, "test.rename", guids=[g], name="Oops")["ok"]
    assert run(s, "task.abandon")["result"]["status"] == "abandoned"
    assert names()[g] == before


def test_record_merges(house):
    s = house()
    from kimbim.agent.steps import Changes
    s.tasks.start("Merge", client="test")
    s.tasks.record(Changes(added=["a"], modified=["m"], fallback={"a": "Wall A", "m": "Wall M"}))
    s.tasks.record(Changes(modified=["a", "m"], removed=["r"], fallback={"r": "Wall R"}))
    s.tasks.record(Changes(removed=["a"]))
    c = s.tasks.status()["changes"]
    assert [x["guid"] for x in c["added"]] == [] and [x["guid"] for x in c["modified"]] == ["m"]
    assert c["removed"] == [{"guid": "r", "label": "Wall R"}]


def test_direct_explicit_on_plain_ifc(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    ifc = tmp_path / "plain.ifc"
    make_house.build(str(ifc))
    original = ifc.read_bytes()
    s = Session.open(str(ifc))
    try:
        assert S.current()["agent_changes"] == "option"  # the default: an explicit direct is still honoured
        task = run(s, "task.start", title="Plain", mode="direct")["result"]
        assert task["mode"] == "direct"
        g = walls()[0].GlobalId
        assert run(s, "test.rename", guids=[g], name="Plain edit")["ok"]
        assert run(s, "task.finish", summary="done")["ok"]
        assert (tmp_path / "plain.before-agent.ifc").read_bytes() == original
        import ifcopenshell
        assert ifcopenshell.open(str(ifc)).by_guid(g).Name == "Plain edit"
    finally:
        s.close()


def test_failed_implicit_write_rolls_back(house):
    s = house()

    @tool("test.fail", {"required": ["guids"], "properties": {"guids": {"type": "array", "items": {"type": "string"}}}},
          writes=True)
    def fail(session, guids):
        """Rename, then fail."""
        bridge(B.set_name, json.dumps(guids), "Half")
        raise catalogue.AgentError("no_match")

    try:
        before = names()
        r = run(s, "test.fail", guids=[walls()[0].GlobalId])
        assert r["error"]["code"] == "no_match"
        assert s.tasks.all() == [] and option() == "main" and names() == before
        assert not [o for o in json.loads(V.options())["options"] if o.startswith("agent/")]
        assert run(s, "test.rename", guids=[walls()[0].GlobalId], name="Fine")["ok"]  # a later write still works
        assert len(s.tasks.all()) == 1
    finally:
        catalogue.TOOLS.pop("test.fail", None)


def test_read_after_restart_resumes(house, tmp_path):
    s = house()
    task = run(s, "task.start", title="Overnight")["result"]
    assert run(s, "test.rename", guids=[walls()[0].GlobalId], name="Night")["ok"]
    s.tasks.park()
    s.close()
    s2 = house(tmp_path / "house.kim")
    assert option() == "main"
    info = run(s2, "project.info")["result"]  # any command unparks, a read too
    assert info["option"] == task["option"]
    assert s2.tasks.get(task["id"]).status == "open"
    assert "Night" in names().values()


def test_direct_versioned_keeps_architect_work(house):
    s = house()
    assert json.loads(S.set_project_settings(json.dumps({"agent_changes": "direct"})))["ok"]
    g, h = walls()[0].GlobalId, walls()[1].GlobalId
    assert json.loads(B.set_name(json.dumps([g]), "Architect"))["ok"]
    run(s, "task.start", title="Agent fix")
    assert run(s, "test.rename", guids=[h], name="Agent")["ok"]
    assert run(s, "task.finish", summary="x")["ok"]
    log = V._project.log(V._encode("main"), 3)
    assert log[0].message == "Agent fix (agent)" and log[0].author_name == "test (agent)"
    assert log[1].message == "Before agent: Agent fix" and log[1].author_name != "test (agent)"


def test_finish_without_edits(house):
    s = house()
    task = run(s, "task.start", title="Idle")["result"]
    r = run(s, "task.finish", summary="nothing to do")["result"]
    assert r["no_changes"] is True and r["version"] == "" and r["task"]["status"] == "abandoned"
    assert option() == "main" and task["option"] not in json.loads(V.options())["options"]


def test_abandon_parked_with_wip(house):
    s = house()
    task = run(s, "task.start", title="Parked")["result"]
    before = names()
    assert run(s, "test.rename", guids=[walls()[0].GlobalId], name="WIP")["ok"]
    s.tasks.park()
    assert s.tasks.abandon(task["id"]).status == "abandoned"  # straight away, no write in between
    assert option() == "main" and names() == before
    assert task["option"] not in json.loads(V.options())["options"]


def test_park_reports_failures(house, monkeypatch):
    s = house()
    task = run(s, "task.start", title="Stuck")["result"]
    assert run(s, "test.rename", guids=[walls()[0].GlobalId], name="S")["ok"]
    monkeypatch.setattr(V, "switch_option", lambda name: json.dumps({"ok": False, "error": "disk full"}))
    with pytest.raises(catalogue.AgentError) as ex:
        s.tasks.park()
    assert ex.value.extra["tasks"] == [task["id"]] and "disk full" in ex.value.hint
    assert s.tasks.get(task["id"]).status == "open"


def test_failed_rollback_keeps_task(house, monkeypatch):
    s = house()

    @tool("test.fail2", {"required": ["guids"], "properties": {"guids": {"type": "array", "items": {"type": "string"}}}},
          writes=True)
    def fail(session, guids):
        """Fail."""
        raise catalogue.AgentError("no_match")

    try:
        monkeypatch.setattr(V, "switch_option", lambda name: json.dumps({"ok": False, "error": "disk full"}))
        assert run(s, "test.fail2", guids=[walls()[0].GlobalId])["error"]["code"] == "no_match"
        left = s.tasks.all()
        assert len(left) == 1 and left[0].status == "open" and left[0].option.startswith("agent/test-fail2")
        assert (s.tasks._dir() / f"{left[0].id}.json").exists()
        assert option() == left[0].option  # still on it, and still tracked
    finally:
        catalogue.TOOLS.pop("test.fail2", None)
