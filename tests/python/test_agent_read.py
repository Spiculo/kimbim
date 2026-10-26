# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent read tools on the sample house: project, levels, find, get (D102)."""
import json
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import documents as D
from kimbim import kimfile as K
from kimbim.agent import catalogue
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
    yield session
    session.close()


def run(s, name, **args):
    return call_tool(s, name, args)


def test_tools_registered():
    import kimbim.agent  # noqa: F401
    for name in ("project.info", "project.settings", "levels.list", "elements.find", "elements.get"):
        assert name in catalogue.TOOLS


def test_info_counts(s):
    r = run(s, "project.info")
    assert r["ok"], r
    info = r["result"]
    walls = len(B._model.by_type("IfcWall"))
    assert info["counts"]["walls"] == walls == 8
    assert len(info["levels"]) >= 2 and {"Level 1", "Level 2"} <= {l["name"] for l in info["levels"]}
    assert info["kind"] == "kim" and info["unit"] == "m" and info["mode"] == "offline"
    assert info["versioned"] in (True, False) and "unsaved" in info and "options" in info


def test_settings_and_levels(s):
    r = run(s, "project.settings", keys=["length_unit"])
    assert r["result"] == {"length_unit": "m"}
    assert "length_unit" in run(s, "project.settings")["result"]
    levels = run(s, "levels.list")["result"]
    assert levels["unit"] == "m"
    rows = levels["levels"]
    assert [x["name"] for x in rows][:2] == ["Level 1", "Level 2"]


def test_find_windows_level(s):
    r = run(s, "elements.find", elements={"kind": "window", "level": "Level 1"})
    assert r["ok"], r
    assert r["result"]["total"] == 4
    assert all(i["kind"] == "windows" and i["level"] == "Level 1" for i in r["result"]["items"])
    assert run(s, "elements.find", elements={"kind": "windows"})["result"]["total"] == 8


def test_find_no_match(s):
    assert run(s, "elements.find", elements={"kind": "window", "level": "Level 9"})["error"]["code"] == "not_found"
    # the house has no HVAC
    assert run(s, "elements.find", elements={"kind": "hvac"})["error"]["code"] == "no_match"
    assert run(s, "elements.find", elements=[])["error"]["code"] == "no_match"
    assert run(s, "elements.find", elements="selection")["error"]["code"] == "needs_app"
    assert run(s, "elements.find", elements=["nope"])["error"]["code"] == "not_found"


def test_find_where_and_guids(s):
    r = run(s, "elements.find", elements={"where": [{"field": "kind", "op": "equals", "value": "doors"}]})
    assert r["result"]["total"] == 2
    g = r["result"]["items"][0]["guid"]
    assert run(s, "elements.find", elements=[g])["result"]["total"] == 1


def test_get_dimensions(s):
    g = run(s, "elements.find", elements={"kind": "window"})["result"]["items"][0]["guid"]
    r = run(s, "elements.get", elements=[g])
    assert r["ok"], r
    item = r["result"]["items"][0]
    assert item["dimensions"]["values"]["Width"] == pytest.approx(1.2)
    assert item["dimensions"]["unit"] == "m" and item["class"] == "IfcWindow"
    assert item["host"] and item["level"] == "Level 1"
    wall = run(s, "elements.get", elements=[item["host"]])["result"]["items"][0]
    assert g in wall["openings"]


def test_paging(s):
    seen, cursor = [], ""
    while True:
        r = run(s, "elements.find", elements={"kind": "wall"}, limit=3, cursor=cursor)["result"]
        assert r["total"] == 8 and len(r["items"]) <= 3
        seen += [i["guid"] for i in r["items"]]
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 8 and len(set(seen)) == 8
    assert run(s, "elements.find", elements={"kind": "wall"}, cursor="x")["error"]["code"] == "bad_input"


def test_limit_bounds(s):
    for bad in (0, 1001, -5):
        assert run(s, "elements.find", elements={"kind": "wall"}, limit=bad)["error"]["code"] == "bad_input"
    assert run(s, "elements.get", elements={"kind": "wall"}, limit=0)["error"]["code"] == "bad_input"
