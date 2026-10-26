# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent tool catalogue (D102): envelope, input validation, one undo step per call, dry run, rollback."""
import json

import pytest

from kimbim import app_bridge as B
from kimbim.agent import catalogue
from kimbim.agent.catalogue import AgentError, ToolResult, bridge, call_tool, tool, validate


class _Tasks:
    def __init__(self):
        self.calls = []

    def for_write(self, client, task_id, title):
        self.calls.append((client, task_id, title))
        return None

    def record(self, changes):
        pass


class _Session:
    def __init__(self):
        self.tasks = _Tasks()

    def label(self, guid):
        e = B._model.by_guid(guid)
        return f"{e.is_a()[3:]} {e.Name}"


@pytest.fixture
def opened(model, tmp_path):
    path = tmp_path / "agent.ifc"
    model.write(str(path))
    assert json.loads(B.open_model(str(path)))["ok"]
    return [w.GlobalId for w in B._model.by_type("IfcWall")]


@pytest.fixture
def tools():
    names = []

    def register(*args, **kw):
        def wrap(fn):
            t = tool(*args, **kw)(fn)
            names.append(t.name)
            return t
        return wrap

    @register("test.count", {"type": "object", "properties": {"ifc_class": {"type": "string"}},
                             "required": ["ifc_class"]})
    def count(session, ifc_class):
        """Count the elements of a class."""
        return {"count": len(B._model.by_type(ifc_class))}

    @register("test.rename", {"type": "object", "properties": {
        "guids": {"type": "array", "items": {"type": "string"}},
        "name": {"type": "string"}, "fail": {"type": "boolean"}}, "required": ["guids", "name"]}, writes=True)
    def rename(session, guids, name, fail=False):
        """Rename elements, one guid per bridge call."""
        for g in guids:
            bridge(B.set_name, json.dumps([g]), name)
        if fail:
            raise AgentError("no_match")
        return {"renamed": len(guids)}

    yield
    for n in names:
        catalogue.TOOLS.pop(n, None)


def _names(guids):
    return [B._model.by_guid(g).Name for g in guids]


def test_envelope_ok(opened, tools):
    r = call_tool(_Session(), "test.count", {"ifc_class": "IfcWall"})
    assert r == {"ok": True, "result": {"count": len(opened)}}
    json.dumps(r)


def test_validation_error(opened, tools):
    r = call_tool(_Session(), "test.count", {})
    assert not r["ok"] and r["error"]["code"] == "bad_input" and "ifc_class" in r["error"]["hint"]
    r = call_tool(_Session(), "test.count", {"ifc_class": 3})
    assert r["error"]["code"] == "bad_input"
    r = call_tool(_Session(), "test.count", {"ifc_class": "IfcWall", "typo": 1})
    assert r["error"]["code"] == "bad_input" and "typo" in r["error"]["hint"]
    assert call_tool(_Session(), "test.count", ["IfcWall"])["error"]["code"] == "bad_input"
    assert call_tool(_Session(), "test.nope", {})["error"]["code"] == "unknown_tool"


def test_validator_types_enum_one_of():
    selector = {"oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string", "enum": ["selection"]},
                          {"type": "object", "properties": {"kind": {"type": "string"}}}]}
    for ok in (["a", "b"], "selection", {"kind": "window"}):
        validate(selector, ok)
    for bad in ("all", [1], 3, True):
        with pytest.raises(AgentError):
            validate(selector, bad)
    validate({"type": "integer"}, 3)
    validate({"type": "number"}, 2.5)
    validate({"type": ["number", "string"]}, "50cm")
    for schema, bad in (({"type": "integer"}, 2.5), ({"type": "number"}, True), ({"type": "boolean"}, 0),
                        ({"type": "string", "enum": ["a"]}, "b")):
        with pytest.raises(AgentError):
            validate(schema, bad)


def test_write_is_one_undo_step(opened, tools):
    session = _Session()
    before = _names(opened[:2])
    start = B._current_id()
    r = call_tool(session, "test.rename", {"guids": opened[:2], "name": "Agent"})
    assert r["ok"], r
    assert _names(opened[:2]) == ["Agent", "Agent"]
    assert sorted(g["guid"] for g in r["changes"]["modified"]) == sorted(opened[:2])
    assert r["changes"]["modified"][0]["label"] == "Wall Agent"
    assert r["changes"]["counts"] == {"added": 0, "modified": 2, "removed": 0}
    assert set(r) == {"ok", "result", "changes"} and "dry_run" not in r["changes"]
    assert session.tasks.calls and session.tasks.calls[0][0] == "cli"
    assert len(B._ids) == 1 and B._current_id() != start
    assert json.loads(B.undo())["ok"]
    assert _names(opened[:2]) == before and B._current_id() == start


def test_dry_run_rolls_back(opened, tools):
    session = _Session()
    before = _names(opened)
    start = B._current_id()
    r = call_tool(session, "test.rename", {"guids": opened[:2], "name": "Agent", "dry_run": True})
    assert r["ok"] and r["changes"]["dry_run"] is True and set(r) == {"ok", "result", "changes"}, r
    assert r["changes"]["counts"]["modified"] == 2
    assert _names(opened) == before
    assert B._current_id() == start and not B._ids and not B._future_ids and not B._model.future
    assert not json.loads(B.state())["can_redo"]
    assert session.tasks.calls == []  # a dry run starts no task


def test_dry_run_keeps_the_redo_stack(opened, tools):
    session = _Session()
    call_tool(session, "test.rename", {"guids": opened[:1], "name": "First"})
    assert json.loads(B.undo())["ok"]
    r = call_tool(session, "test.rename", {"guids": opened[:1], "name": "Probe", "dry_run": True})
    assert r["ok"]
    assert json.loads(B.redo())["ok"]
    assert _names(opened[:1]) == ["First"]


def test_failure_rolls_back(opened, tools):
    before = _names(opened)
    start = B._current_id()
    r = call_tool(_Session(), "test.rename", {"guids": opened[:2], "name": "Agent", "fail": True})
    assert r == {"ok": False, "error": {"code": "no_match", "message": r["error"]["message"]}}
    assert _names(opened) == before and B._current_id() == start and B._step is None


def test_other_exception_is_bridge_error(opened, tools):
    @tool("test.boom", {"type": "object"}, writes=True)
    def boom(session):
        """Rename then crash."""
        bridge(B.set_name, json.dumps(opened[:1]), "Boom")
        raise ValueError("kaput")

    try:
        before = _names(opened[:1])
        r = call_tool(_Session(), "test.boom", {})
        assert r["error"]["code"] == "bridge_error" and r["error"]["hint"] == "kaput"
        assert _names(opened[:1]) == before
    finally:
        catalogue.TOOLS.pop("test.boom")


def test_bridge_helper_raises_on_failure(opened):
    assert bridge(B.state)["path"]
    with pytest.raises(AgentError) as info:
        bridge(B.redo)  # nothing to redo: {"ok": false, "error": ...}
    assert info.value.code == "bridge_error" and info.value.hint == "nothing to redo"


def test_added_and_removed(opened, tools):
    @tool("test.add_remove", {"type": "object"}, writes=True)
    def add_remove(session):
        """Copy one wall and delete another."""
        from kimbim import authoring

        bridge(authoring.delete_elements, json.dumps([opened[0]]))
        import ifcopenshell.api.root

        w = ifcopenshell.api.root.create_entity(B._model, ifc_class="IfcWall", name="New")
        return {"guid": w.GlobalId}

    try:
        r = call_tool(_Session(), "test.add_remove", {"dry_run": True})
        assert r["ok"], r
        c = r["changes"]
        assert [a["guid"] for a in c["added"]] == [r["result"]["guid"]] and c["added"][0]["label"] == "Wall New"
        assert [x["guid"] for x in c["removed"]] == [opened[0]]
        assert c["removed"][0]["label"]  # still labelled: the dry run put it back
        assert all(m["guid"] not in (opened[0], r["result"]["guid"]) for m in c["modified"])
        assert len(B._model.by_type("IfcWall")) == len(opened)
    finally:
        catalogue.TOOLS.pop("test.add_remove")


def test_docstring_required():
    with pytest.raises(ValueError):
        @tool("test.undocumented", {"type": "object"})
        def undocumented(session):
            return 1
    assert "test.undocumented" not in catalogue.TOOLS
    with pytest.raises(ValueError):
        @tool("test.short", {"type": "object"})
        def short(session):
            """no sentence"""


def test_write_tool_schema_has_dry_run(tools):
    t = catalogue.TOOLS["test.rename"]
    assert t.writes and t.needs_task and t.params["properties"]["dry_run"]["type"] == "boolean"
    assert t.description == "Rename elements, one guid per bridge call."
    assert "dry_run" not in catalogue.TOOLS["test.count"].params["properties"]


def test_write_tool_refused_inside_an_open_step(opened, tools):
    from kimbim import console

    session = _Session()
    before = _names(opened)
    with console.edit():
        for args in ({"guids": opened[:1], "name": "Joined"}, {"guids": opened[:1], "name": "X", "dry_run": True}):
            r = call_tool(session, "test.rename", args)
            assert r["error"]["code"] == "bad_input" and r["error"]["hint"], r
        assert call_tool(session, "test.count", {"ifc_class": "IfcWall"})["ok"]  # reads still work
    assert _names(opened) == before and not B._ids and session.tasks.calls == []


def test_warnings_only_when_there_are_some(opened, tools):
    @tool("test.warn", {"type": "object", "properties": {"n": {"type": "integer"}}})
    def warn(session, n=0):
        """Return warnings."""
        return ToolResult({"n": n}, warnings=[f"w{i}" for i in range(n)])

    try:
        assert call_tool(_Session(), "test.warn", {"n": 2}) == {"ok": True, "result": {"n": 2},
                                                                "warnings": ["w0", "w1"]}
        assert call_tool(_Session(), "test.warn", {}) == {"ok": True, "result": {"n": 0}}
    finally:
        catalogue.TOOLS.pop("test.warn")


@pytest.fixture
def profile_tool(tmp_path):
    """A project with a closed polyline, and a write tool saving it as a wall profile: configure.save_wall_profile
    is a `_run_settings` bridge call that changes the project settings only."""
    from kimbim import configure

    assert json.loads(B.new_project("Settings"))["ok"]
    level = json.loads(B.storeys())["storeys"][0]["guid"]
    pts = [[0, 0], [0.3, 0], [0.3, 3], [0, 3]]
    d = json.loads(B.add_drafting(level, "polyline", json.dumps(pts), json.dumps({"closed": True})))
    assert d["ok"], d

    @tool("test.profile", {"type": "object", "properties": {"fail": {"type": "boolean"}}}, writes=True)
    def profile(session, fail=False):
        """Save the polyline as a wall profile."""
        bridge(configure.save_wall_profile, d["guid"], "Agent")
        if fail:
            raise AgentError("no_match")
        return {}

    yield configure.profiles
    catalogue.TOOLS.pop("test.profile")


def test_dry_run_restores_settings(profile_tool):
    start = B._current_id()
    r = call_tool(_Session(), "test.profile", {"dry_run": True})
    assert r["ok"] and r["changes"]["dry_run"], r
    assert "Agent" not in profile_tool() and B._current_id() == start and not B._future_ids


def test_undo_restores_settings(profile_tool):
    start = B._current_id()
    r = call_tool(_Session(), "test.profile", {})
    assert r["ok"], r
    assert "Agent" in profile_tool() and B._current_id() != start  # a settings-only change is a step
    assert json.loads(B.undo())["ok"]
    assert "Agent" not in profile_tool() and B._current_id() == start
    assert json.loads(B.redo())["ok"]
    assert "Agent" in profile_tool()


def test_failure_restores_settings(profile_tool):
    start = B._current_id()
    assert call_tool(_Session(), "test.profile", {"fail": True})["error"]["code"] == "no_match"
    assert "Agent" not in profile_tool() and B._current_id() == start
