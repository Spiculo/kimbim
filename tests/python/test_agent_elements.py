# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent element write tools on the sample house, in direct tasks (D102)."""
import json
import math
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import authoring as A
from kimbim import documents as D
from kimbim import kimfile as K
from kimbim import settings as S
from kimbim.agent.catalogue import call_tool
from kimbim.agent.session import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    monkeypatch.setattr(K, "display_user", "")
    ifc = tmp_path / "house.ifc"
    make_house.build(str(ifc))
    out = json.loads(D.import_ifc(str(ifc), str(tmp_path / "house.kim")))
    assert out["ok"]
    D.close_document()
    session = Session.open(str(tmp_path / "house.kim"))
    assert json.loads(S.set_project_settings(json.dumps({"agent_changes": "direct"})))["ok"]
    yield session
    session.close()


def run(s, tool_name, **args):
    return call_tool(s, tool_name, args, client="test")


L1_WINDOWS = {"kind": "window", "level": "Level 1"}


def width(g):
    return dict((n, v) for n, v, _ in A.element_dimensions(B._model.by_guid(g)))["Width"]


def widths(guids):
    return [round(width(g), 6) for g in guids]


def window_guids():
    return sorted(w.GlobalId for w in B._model.by_type("IfcWindow"))


def test_widen_windows_relative(s):
    r = run(s, "elements.set_dimensions", elements=L1_WINDOWS, width="+50cm")
    assert r["ok"], r
    guids = [i["guid"] for i in run(s, "elements.find", elements=L1_WINDOWS)["result"]["items"]]
    assert len(guids) == 4 and widths(guids) == [1.7] * 4
    assert {m["guid"] for m in r["changes"]["modified"]} >= set(guids)


def test_mixed_widths_grouped(s):
    guids = [i["guid"] for i in run(s, "elements.find", elements=L1_WINDOWS)["result"]["items"]]
    assert run(s, "elements.set_dimensions", elements=[guids[0]], width=1.0)["ok"]
    r = run(s, "elements.set_dimensions", elements=guids, width="+50cm")
    assert r["ok"], r
    assert widths(guids) == [1.5, 1.7, 1.7, 1.7]


def test_negative_result_rolls_back(s):
    before = widths(window_guids())
    r = run(s, "elements.set_dimensions", elements={"kind": "window"}, width="-2m")
    assert not r["ok"] and r["error"]["code"] == "bad_length"
    assert widths(window_guids()) == before


def test_lacking_dimension_warns(s):
    walls = [w.GlobalId for w in B._model.by_type("IfcWall")][:1]
    win = window_guids()[:1]
    r = run(s, "elements.set_dimensions", elements=walls + win, width="1m")
    assert r["ok"] and r["warnings"] and widths(win) == [1.0]
    r = run(s, "elements.set_dimensions", elements=walls, width="1m")
    assert not r["ok"] and r["error"]["code"] == "no_match"


def test_move_and_rotate(s):
    win = window_guids()[:1]
    before = A._world(B._model.by_guid(win[0]))
    assert run(s, "elements.move", elements=win, dx=1, dy=0.5)["ok"]
    after = A._world(B._model.by_guid(win[0]))
    assert after[0] == pytest.approx(before[0] + 1) and after[1] == pytest.approx(before[1] + 0.5)
    r = run(s, "elements.rotate", elements=win, angle="90deg", center=[after[0] - 1, after[1]])
    assert r["ok"], r
    rot = A._world(B._model.by_guid(win[0]))
    assert rot[0] == pytest.approx(after[0] - 1, abs=1e-6) and rot[1] == pytest.approx(after[1] + 1, abs=1e-6)
    assert run(s, "elements.rotate", elements=win, angle="abc")["error"]["code"] == "bad_input"
    assert run(s, "elements.rotate", elements=win, angle=90)["ok"]  # default centre


def test_set_properties_typed(s):
    win = window_guids()[:2]
    r = run(s, "elements.set_properties", elements=win,
            properties={"Pset_Custom.Flag": True, "Pset_Custom.Score": 3.5})
    assert r["ok"], r
    props = run(s, "elements.get", elements=win[:1])["result"]["items"][0]["properties"]["Pset_Custom"]
    assert props["Flag"] is True and props["Score"] == 3.5
    assert run(s, "elements.set_properties", elements=win, properties={"NoDot": 1})["error"]["code"] == "bad_input"
    assert run(s, "elements.remove_properties", elements=win, properties=["Pset_Custom.Flag"])["ok"]
    props = run(s, "elements.get", elements=win[:1])["result"]["items"][0]["properties"]["Pset_Custom"]
    assert "Flag" not in props and "Score" in props


def test_rename_status_layer(s):
    win = window_guids()[:1]
    assert run(s, "elements.rename", elements=win, name="W-test")["ok"]
    assert B._model.by_guid(win[0]).Name == "W-test"
    assert run(s, "elements.set_status", elements=win, status="demolish")["ok"]
    assert run(s, "elements.find", elements={"status": "demolish"})["result"]["total"] == 1
    assert run(s, "elements.set_layer", elements=win, layer="nope")["error"]["code"] == "bridge_error"


def test_copy_mirror_copy_to_level(s):
    n = len(B._model.by_type("IfcWall"))
    walls = [w.GlobalId for w in B._model.by_type("IfcWall")][:1]
    r = run(s, "elements.copy", elements=walls, dx=0, dy=10)
    assert r["ok"] and len(B._model.by_type("IfcWall")) == n + 1 and r["changes"]["counts"]["added"] >= 1
    r = run(s, "elements.mirror", elements=walls, line=[[0, 0], [0, 1]], copy=True)
    assert r["ok"] and len(B._model.by_type("IfcWall")) == n + 2
    r = run(s, "elements.copy_to_level", elements=walls, level="Level 2")
    assert r["ok"], r
    assert run(s, "elements.copy_to_level", elements=walls, level="Nope")["error"]["code"] == "not_found"


def test_delete_reports_removed(s):
    win = window_guids()[:1]
    r = run(s, "elements.delete", elements=win)
    assert r["ok"], r
    assert win[0] in [m["guid"] for m in r["changes"]["removed"]]
    assert len(B._model.by_type("IfcWindow")) == 7


def test_dry_run_widen(s):
    before = widths(window_guids())
    r = run(s, "elements.set_dimensions", elements=L1_WINDOWS, width="+50cm", dry_run=True)
    assert r["ok"] and r["changes"]["dry_run"]
    modified = {m["guid"] for m in r["changes"]["modified"]}
    assert len(modified & set(window_guids())) == 4
    assert widths(window_guids()) == before


def test_set_status_unknown(s):
    r = run(s, "elements.set_status", elements=window_guids()[:1], status="bogus")
    assert not r["ok"] and r["error"]["code"] == "bad_input"
