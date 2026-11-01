# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent split, trim/corner, join and unjoin tools on the sample house, in direct tasks (D80, D102)."""
import json
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import authoring as A
from kimbim import documents as D
from kimbim import kimfile as K
from kimbim import settings as S
from kimbim.agent import assistant
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


def test_the_internal_assistant_sees_the_new_tools():
    schemas, back = assistant._tool_names()
    names = {schema["name"] for schema in schemas}
    assert {"elements_split", "elements_trim", "elements_trim_corner", "elements_join",
            "elements_unjoin", "elements_array", "elements_offset", "elements_fillet", "elements_resize",
            "elements_stretch", "elements_get_slab_outline", "elements_set_slab_outline"} <= names
    assert back["elements_split"] == "elements.split"


def wall(s, start, end):
    r = run(s, "create.wall", level="Level 1", start=start, end=end, join=False)
    assert r["ok"], r
    return r["result"]["guids"][0]


def axis(guid):
    return [[round(float(c), 6) for c in p] for p in A._axis_world(B._model.by_guid(guid))]


def host(fill):
    return fill.FillsVoids[0].RelatingOpeningElement.VoidsElements[0].RelatingBuildingElement.GlobalId


def test_split_keeps_openings_and_returns_the_piece(s):
    w = wall(s, [30, 30], [40, 30])
    door = run(s, "create.opening", kind="door", wall=w, along=2)["result"]["guids"][0]
    window = run(s, "create.opening", kind="window", wall=w, along=8)["result"]["guids"][0]
    r = run(s, "elements.split", element=w, at=[35, 30.2])
    assert r["ok"], r
    piece = r["result"]["piece"]
    assert piece and piece != w
    assert axis(w) == [[30, 30], [35, 30]]
    assert axis(piece) == [[35, 30], [40, 30]]
    assert host(B._model.by_guid(door)) == w
    assert host(B._model.by_guid(window)) == piece
    assert {m["guid"] for m in r["changes"]["added"]} == {piece}
    assert w in {m["guid"] for m in r["changes"]["modified"]}


def test_split_beside_an_opening_and_at_the_end_are_refused(s):
    w = wall(s, [30, 40], [40, 40])
    run(s, "create.opening", kind="door", wall=w, along=2)
    r = run(s, "elements.split", element=w, at=[32, 40])
    assert not r["ok"] and r["error"]["code"] == "bridge_error" and "inside" in r["error"]["hint"]
    r = run(s, "elements.split", element=w, at=[50, 40])
    assert not r["ok"] and "end" in r["error"]["hint"]


def test_trim_to_a_boundary_wall_and_to_a_line(s):
    boundary = wall(s, [50, 50], [60, 50])
    cross = wall(s, [55, 45], [55, 55])
    r = run(s, "elements.trim", element=cross, at=[55, 54], boundary=boundary)
    assert r["ok"], r
    assert axis(cross) == [[55, 50], [55, 55]]
    assert len(A._path_joins(B._model.by_guid(cross))) == 1  # joined to the boundary

    short = wall(s, [60, 55], [62, 55])
    r = run(s, "elements.trim", element=short, at=[61, 55], line=[[66, 50], [66, 60]])
    assert r["ok"], r
    assert axis(short) == [[60, 55], [66, 55]]


def test_trim_corner_extends_both_to_their_intersection(s):
    a = wall(s, [70, 70], [74, 70])
    b = wall(s, [76, 72], [76, 77])
    r = run(s, "elements.trim_corner", first=a, first_at=[74, 70], second=b, second_at=[76, 72])
    assert r["ok"], r
    assert axis(a) == [[70, 70], [76, 70]]
    assert axis(b) == [[76, 70], [76, 77]]
    assert len(A._path_joins(B._model.by_guid(a))) == 1


def test_join_merges_collinear_walls_l_joins_others_and_unjoin_breaks_it(s):
    a = wall(s, [80, 80], [84, 80])
    b = wall(s, [84, 80], [88, 80])
    r = run(s, "elements.join", first=a, second=b)
    assert r["ok"] and r["result"]["merged"] is True
    assert axis(a) == [[80, 80], [88, 80]]
    assert not any(e.GlobalId == b for e in B._model.by_type("IfcWall"))

    c = wall(s, [90, 90], [94, 90])
    d = wall(s, [94, 90], [94, 94])
    r = run(s, "elements.join", first=c, second=d)
    assert r["ok"] and r["result"]["merged"] is False
    assert len(A._path_joins(B._model.by_guid(c))) == 1
    r = run(s, "elements.unjoin", elements=[c, d])
    assert r["ok"], r
    assert not A._path_joins(B._model.by_guid(c))


def test_join_refuses_property_differences_when_asked(s):
    a = wall(s, [100, 100], [104, 100])
    b = wall(s, [104, 100], [108, 100])
    assert run(s, "elements.set_properties", elements=[b], properties={"Pset_Custom.X": 1})["ok"]
    r = run(s, "elements.join", first=a, second=b, props="refuse")
    assert not r["ok"] and "properties differ" in r["error"]["hint"]


def test_trim_requires_exactly_one_boundary(s):
    w = wall(s, [110, 110], [114, 110])
    r = run(s, "elements.trim", element=w, at=[111, 110])
    assert not r["ok"] and r["error"]["code"] == "bad_input"
    r = run(s, "elements.trim", element=w, at=[111, 110], boundary=w, line=[[0, 0], [1, 1]])
    assert not r["ok"] and r["error"]["code"] == "bad_input"
