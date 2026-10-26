# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent sessions open .kim, folders and IFC the way the app does (D102)."""
import json

import ifcopenshell
import pytest

from kimbim import app_bridge as B
from kimbim import documents as D
from kimbim import kimfile as K
from kimbim.agent.catalogue import AgentError
from kimbim.agent.session import Session


@pytest.fixture
def kim(model, tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    monkeypatch.setattr(K, "display_user", "")
    ifc = tmp_path / "src.ifc"
    model.write(str(ifc))
    path = tmp_path / "proj.kim"
    out = json.loads(D.import_ifc(str(ifc), str(path)))
    assert out["ok"]
    assert json.loads(B.open_model(out["path"]))["ok"]
    D.close_document()
    yield path
    D.close_document()


def _walls():
    return [w.GlobalId for w in B._model.by_type("IfcWall")]


def test_open_kim_and_save(kim):
    s = Session.open(str(kim))
    assert s.kind == "kim" and s.source == str(kim) and s.work and s.unit == "m"
    assert K.display_user == "KimBim agent"
    assert json.loads(B.set_name(json.dumps(_walls()[:1]), "Renamed"))["ok"]
    s.save()
    s.close()
    assert K.display_user == ""
    s = Session.open(str(kim))
    assert "Renamed" in [w.Name for w in B._model.by_type("IfcWall")]
    s.close()


def test_open_plain_ifc(model, tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    ifc = tmp_path / "plain.ifc"
    model.write(str(ifc))
    s = Session.open(str(ifc))
    assert s.kind == "ifc" and s.work == ""
    assert len(s.resolve(_walls())) == 2
    assert K.display_user == "KimBim agent"
    assert json.loads(B.set_name(json.dumps(_walls()[:1]), "Saved"))["ok"]
    s.save()
    s.close()
    assert K.display_user == ""
    assert "Saved" in [w.Name for w in ifcopenshell.open(str(ifc)).by_type("IfcWall")]


def test_open_folder(kim, tmp_path):
    s = Session.open(str(kim))
    folder = tmp_path / "folder"
    assert json.loads(D.save_as_folder(str(folder)))["ok"]
    s.close()
    s = Session.open(str(folder))
    assert s.kind == "folder" and s.work
    s.close()


def test_locked_kim(kim):
    holder = {"user": "Ana", "account": "other", "machine": "other-pc", "pid": 1, "since": "2026-01-01T00:00"}
    K.lock_path(kim).write_text(json.dumps(holder), encoding="utf-8")
    with pytest.raises(AgentError) as ex:
        Session.open(str(kim))
    assert ex.value.code == "project_locked"
    assert ex.value.extra["holder"]["user"] == "Ana"
    assert K.display_user == ""


def test_open_model_failure_cleans_up(kim, monkeypatch):
    monkeypatch.setattr(B, "open_model", lambda path: json.dumps({"ok": False, "error": "x"}))
    with pytest.raises(AgentError):
        Session.open(str(kim))
    assert not K.lock_path(kim).exists()
    assert K.display_user == ""
    assert D._pending is None


def test_resolve_unknown(kim):
    s = Session.open(str(kim))
    with pytest.raises(AgentError) as ex:
        s.resolve(["nope"])
    assert ex.value.code == "not_found"
    s.close()


def test_label(kim):
    s = Session.open(str(kim))
    assert s.label(_walls()[0]) == "Wall Wall 0, Level 1"
    s.close()
