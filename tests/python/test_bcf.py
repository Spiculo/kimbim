# SPDX-License-Identifier: GPL-3.0-or-later
"""BCF 2.1 issue management (doc 14 §17): settings storage, viewpoints, comments, export and import.

Every export is opened with bcf-client (LGPL, pixi.toml), so the file is checked by an independent
BCF implementation, not only by our own reader.
"""
import json
import zipfile

import pytest
from conftest import build_model
from kimbim import app_bridge as B
from kimbim import bcf as BCF
from kimbim import settings

bcf_client = pytest.importorskip("bcf.bcfxml")


def _json(fn, *args):
    out = fn(*args)
    assert isinstance(out, str), f"{fn.__name__} returned {type(out).__name__}, not a JSON string"
    return json.loads(out)


@pytest.fixture(autouse=True)
def _clean_settings():
    settings.load({})
    yield
    settings.load({})
    B._model = None


@pytest.fixture
def app(tmp_path):
    f = build_model(walls=2)
    p = tmp_path / "model.ifc"
    f.write(str(p))
    assert json.loads(B.open_model(str(p)))["ok"]
    return f, p


def _issue(title, **fields):
    return _json(BCF.create_issue, json.dumps({"title": title, **fields}))["issue"]


def _export(tmp_path, name="issues.bcfzip"):
    path = tmp_path / name
    out = _json(BCF.export_bcf, str(path))
    assert out["ok"], out
    return path, out


def test_export_is_a_bcf_that_bcf_client_reads(app, tmp_path):
    f, _p = app
    walls = f.by_type("IfcWall")
    viewpoint = {
        "camera": {"type": "perspective", "eye": [10.0, -5.0, 2.0], "target": [0.0, 0.0, 1.0],
                   "up": [0.0, 0.0, 1.0], "fov": 60.0, "scale": 1.0},
        "components": [walls[0].GlobalId],
        "clipping": [{"point": [0.0, 0.0, 1.5], "normal": [0.0, 0.0, -1.0]}],
    }
    first = _issue("Wall clash", description="The wall hits the beam", type="Clash", status="Open",
                   priority="High", assigned_to="Ana", viewpoint=viewpoint)
    second = _issue("Missing door", type="Issue", status="In Progress",
                    viewpoint={"components": [walls[1].GlobalId]})
    commented = _json(BCF.add_comment, first["id"], "Move the wall", "Ana")
    assert commented["ok"] and commented["issue"]["comments"][0]["text"] == "Move the wall"

    path, out = _export(tmp_path)
    assert out["topics"] == 2 and out["path"] == str(path)

    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
    assert {"bcf.version", "project.bcfp"} <= names
    for issue in (first, second):
        assert f"{issue['id']}/markup.bcf" in names
        assert f"{issue['id']}/viewpoint.bcfv" in names

    doc = bcf_client.load(path)
    try:
        assert doc.version.version_id == "2.1"
        assert doc.project.project_id
        assert set(doc.topics) == {first["id"], second["id"]}
        topic = doc.topics[first["id"]]
        assert topic.topic.title == "Wall clash"
        assert topic.topic.description == "The wall hits the beam"
        assert topic.topic.topic_status == "Open"
        assert topic.topic.topic_type == "Clash"
        assert topic.topic.priority == "High"
        assert topic.topic.assigned_to == "Ana"
        assert [c.comment for c in topic.comments] == ["Move the wall"]
        assert [c.author for c in topic.comments] == ["Ana"]
        info = topic.viewpoints["viewpoint.bcfv"].visualization_info
        assert info.perspective_camera.camera_view_point.x == pytest.approx(10.0)
        assert info.perspective_camera.camera_view_point.y == pytest.approx(-5.0)
        assert [c.ifc_guid for c in info.components.selection.component] == [walls[0].GlobalId]
        assert info.clipping_planes.clipping_plane[0].location.z == pytest.approx(1.5)
        other = doc.topics[second["id"]]
        assert other.topic.title == "Missing door"
        assert other.topic.topic_status == "In Progress"
        assert [c.ifc_guid for c in other.viewpoints["viewpoint.bcfv"]
                .visualization_info.components.selection.component] == [walls[1].GlobalId]
    finally:
        doc.close()


def test_import_merges_by_topic_guid_and_maps_components(app, tmp_path):
    f, p = app
    walls = f.by_type("IfcWall")
    first = _issue("Clash", status="Open", viewpoint={"components": [walls[0].GlobalId]})
    second = _issue("Missing door", status="Closed", viewpoint={"components": [walls[1].GlobalId]})
    assert _json(BCF.add_comment, first["id"], "Please fix", "Ana")["ok"]
    path, _out = _export(tmp_path)

    # a fresh open model and no issues: import brings both back, with their ids and components
    settings.load({})
    assert json.loads(B.open_model(str(p)))["ok"]
    assert _json(BCF.list_issues)["issues"] == []
    imported = _json(BCF.import_bcf, str(path))
    assert imported["ok"], imported
    assert (imported["added"], imported["updated"]) == (2, 0)
    assert (imported["components"], imported["unknown_components"]) == (2, 0)

    issues = {i["title"]: i for i in _json(BCF.list_issues)["issues"]}
    assert set(issues) == {"Clash", "Missing door"}
    assert issues["Clash"]["id"] == first["id"]
    assert issues["Clash"]["status"] == "Open"
    assert issues["Clash"]["viewpoint"]["components"] == [walls[0].GlobalId]
    assert [c["text"] for c in issues["Clash"]["comments"]] == ["Please fix"]
    assert issues["Missing door"]["id"] == second["id"]
    assert issues["Missing door"]["status"] == "Closed"
    assert issues["Missing door"]["viewpoint"]["components"] == [walls[1].GlobalId]

    # importing the same file again updates the two topics, it does not duplicate them
    again = _json(BCF.import_bcf, str(path))
    assert (again["added"], again["updated"]) == (0, 2)
    issues = _json(BCF.list_issues)["issues"]
    assert len(issues) == 2
    assert [c["text"] for c in next(i for i in issues if i["title"] == "Clash")["comments"]] == ["Please fix"]


def test_import_restores_the_camera_and_ignores_unknown_components(app, tmp_path):
    f, _p = app
    wall = f.by_type("IfcWall")[0]
    _issue("View", viewpoint={
        "camera": {"type": "orthogonal", "eye": [3.0, 4.0, 5.0], "target": [3.0, 4.0, 0.0],
                   "up": [0.0, 0.0, 1.0], "fov": 45.0, "scale": 2.5},
        "components": [wall.GlobalId, "0000000000000000000000"],
        "clipping": [{"point": [1.0, 2.0, 3.0], "normal": [0.0, 0.0, 1.0]}],
    })
    path, _out = _export(tmp_path)
    settings.load({})
    imported = _json(BCF.import_bcf, str(path))
    assert imported["ok"] and imported["components"] == 1 and imported["unknown_components"] == 1

    issue = _json(BCF.list_issues)["issues"][0]
    assert issue["viewpoint"]["components"] == [wall.GlobalId]
    camera = issue["viewpoint"]["camera"]
    assert camera["type"] == "orthogonal"
    assert camera["eye"] == pytest.approx([3.0, 4.0, 5.0])
    assert camera["target"][:2] == pytest.approx([3.0, 4.0])
    assert camera["up"] == pytest.approx([0.0, 0.0, 1.0])
    assert camera["scale"] == pytest.approx(2.5)
    assert issue["viewpoint"]["clipping"][0]["point"] == pytest.approx([1.0, 2.0, 3.0])


def test_update_comment_and_delete(app):
    created = _issue("First")
    assert created["status"] == "Open" and created["id"]
    updated = _json(BCF.update_issue, created["id"],
                    json.dumps({"title": "Second", "status": "Resolved", "priority": "Low"}))
    assert updated["ok"], updated
    assert updated["issue"]["title"] == "Second"
    assert updated["issue"]["status"] == "Resolved"
    assert updated["issue"]["priority"] == "Low"
    assert updated["issue"]["modified"] >= created["modified"]

    commented = _json(BCF.add_comment, created["id"], "Done", "Ana")
    assert commented["ok"]
    assert commented["issue"]["comments"] == [
        {"author": "Ana", "date": commented["issue"]["comments"][0]["date"], "text": "Done"}]

    assert _json(BCF.delete_issue, created["id"])["ok"]
    assert _json(BCF.list_issues)["issues"] == []
    assert _json(BCF.delete_issue, created["id"])["ok"] is False
    assert _json(BCF.update_issue, "nope", "{}")["ok"] is False
    assert _json(BCF.add_comment, "nope", "text")["ok"] is False


def test_bad_input_is_reported_not_raised(app, tmp_path):
    assert _json(BCF.create_issue, "not json")["ok"] is False
    assert _json(BCF.create_issue, json.dumps({"description": "no title"}))["ok"] is False
    assert _json(BCF.create_issue, json.dumps({"title": "x", "status": "Unknown"}))["ok"] is False
    assert _json(BCF.update_issue, "nope", "not json")["ok"] is False

    assert _json(BCF.import_bcf, str(tmp_path / "missing.bcfzip"))["ok"] is False
    bad = tmp_path / "bad.bcfzip"
    bad.write_text("not a zip", encoding="utf-8")
    assert _json(BCF.import_bcf, str(bad))["ok"] is False
    empty = tmp_path / "empty.bcfzip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("hello.txt", "hi")
    assert _json(BCF.import_bcf, str(empty))["ok"] is False
    assert _json(BCF.export_bcf, str(tmp_path))["ok"] is False

def test_issue_viewpoint_is_available_for_show_viewpoint(app):
    f, _p = app
    wall = f.by_type("IfcWall")[0].GlobalId
    issue = _issue("Show me", viewpoint={
        "camera": {"type": "orthogonal", "eye": [3.0, 4.0, 5.0], "target": [0.0, 0.0, 0.0],
                   "up": [0.0, 1.0, 0.0], "fov": 60.0, "scale": 2.0},
        "components": [wall]})
    out = _json(BCF.issue_viewpoint, issue["id"])
    assert out["ok"] and out["camera"]["type"] == "orthogonal"
    assert out["camera"]["eye"] == [3.0, 4.0, 5.0]
    assert out["components"] == [wall]
    assert _json(BCF.issue_viewpoint, "missing")["ok"] is False
