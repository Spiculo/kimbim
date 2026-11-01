# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent array, offset, fillet, resize and slab-outline tools on the sample house, in direct tasks (D102)."""
import json
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import authoring as A
from kimbim import documents as D
from kimbim import editing as E
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


def wall(s, start, end):
    r = run(s, "create.wall", level="Level 1", start=start, end=end, join=False)
    assert r["ok"], r
    return r["result"]["guids"][0]


def slab(s, points):
    r = run(s, "create.slab", level="Level 1", points=points)
    assert r["ok"], r
    return r["result"]["guids"][0]


def axis(guid):
    return [[round(float(c), 6) for c in p] for p in A._axis_world(B._model.by_guid(guid))]


def outline(guid):
    return [[round(float(c), 6) for c in p] for p in E._slab_outline_world(B._model.by_guid(guid))]


def column(s, at):
    r = run(s, "create.column", level="Level 1", at=at, height=3)
    assert r["ok"], r
    return r["result"]["guids"][0]


def world(guid):
    return tuple(round(float(c), 6) for c in A._world(B._model.by_guid(guid))[:2])


def test_array_linear_rectangular_and_polar(s):
    w = wall(s, [30, 30], [34, 30])
    r = run(s, "elements.array", elements=[w], kind="linear", dx=5, dy=0, count=2)
    assert r["ok"], r
    assert r["result"]["count"] == 2
    assert {tuple(map(tuple, axis(g))) for g in r["result"]["copies"]} == {((35, 30), (39, 30)),
                                                                         ((40, 30), (44, 30))}

    col = column(s, [60, 30])
    r = run(s, "elements.array", elements=[col], kind="rectangular", dx=3, dy=4, nx=2, ny=2)
    assert r["ok"], r
    assert r["result"]["count"] == 3
    assert {world(g) for g in r["result"]["copies"]} == {(63, 30), (60, 34), (63, 34)}

    col = column(s, [80, 30])
    r = run(s, "elements.array", elements=[col], kind="polar", center=[70, 30], angle="90deg", count=3)
    assert r["ok"], r
    assert r["result"]["count"] == 3
    assert {world(g) for g in r["result"]["copies"]} == {(70, 40), (60, 30), (70, 20)}


def test_offset_copies_a_wall_and_grows_a_slab(s):
    w = wall(s, [30, 50], [34, 50])
    r = run(s, "elements.offset", elements=[w], distance=2)
    assert r["ok"], r
    assert r["result"]["count"] == 1
    copy = r["result"]["copies"][0]
    assert axis(w) == [[30, 50], [34, 50]]
    assert axis(copy) == [[30, 52], [34, 52]]

    sl = slab(s, [[60, 50], [64, 50], [64, 54], [60, 54]])
    before = outline(sl)
    r = run(s, "elements.offset", elements=[sl], distance=1)
    assert r["ok"], r
    after = outline(sl)
    assert after != before
    xs, ys = [p[0] for p in after], [p[1] for p in after]
    assert min(xs) == pytest.approx(59) and max(xs) == pytest.approx(65)
    assert min(ys) == pytest.approx(49) and max(ys) == pytest.approx(55)


def test_fillet_and_set_slab_outline(s):
    sl = slab(s, [[70, 50], [74, 50], [74, 54], [70, 54]])
    r = run(s, "elements.fillet", elements=[sl], size=1, mode="chamfer")
    assert r["ok"], r
    assert len(outline(sl)) == 8
    got = run(s, "elements.get_slab_outline", element=sl)
    assert got["ok"] and len(got["result"]["points"]) == 8

    r = run(s, "elements.set_slab_outline", element=sl, points=[[80, 50], [84, 50], [84, 54]])
    assert r["ok"], r
    pts = outline(sl)
    assert len(pts) == 3
    assert sorted(p[0] for p in pts) == [80, 84, 84]


def test_resize_about_a_point_and_the_default_middle(s):
    w = wall(s, [30, 70], [34, 70])
    r = run(s, "elements.resize", elements=[w], factor=2, center=[30, 70])
    assert r["ok"], r
    assert axis(w) == [[30, 70], [38, 70]]

    w = wall(s, [30, 80], [34, 80])
    r = run(s, "elements.resize", elements=[w], factor=0.5)
    assert r["ok"], r
    assert axis(w) == [[31, 80], [33, 80]]


def test_stretch_moves_a_wall_end_and_drops_its_join(s):
    w = wall(s, [30, 100], [34, 100])
    r = run(s, "elements.stretch", element=w, end="end", to=[40, 100])
    assert r["ok"], r
    assert axis(w) == [[30, 100], [40, 100]]
    r = run(s, "elements.stretch", element=w, end="start", to=[25, 100])
    assert r["ok"], r
    assert axis(w) == [[25, 100], [40, 100]]

    a = run(s, "create.wall", level="Level 1", start=[30, 110], end=[34, 110])["result"]["guids"][0]
    run(s, "create.wall", level="Level 1", start=[34, 110], end=[34, 114])
    assert len(A._path_joins(B._model.by_guid(a))) == 1
    r = run(s, "elements.stretch", element=a, end="end", to=[40, 110])
    assert r["ok"], r
    assert not A._path_joins(B._model.by_guid(a))


def test_editing_tool_validation(s):
    w = wall(s, [30, 90], [34, 90])
    assert run(s, "elements.array", elements=[w], kind="polar", count=2)["error"]["code"] == "bad_input"
    assert run(s, "elements.array", elements=[w], kind="spiral")["error"]["code"] == "bad_input"
    assert run(s, "elements.offset", elements=[w], distance=0)["error"]["code"] == "bridge_error"
    assert run(s, "elements.resize", elements=[w], factor=1)["error"]["code"] == "bad_input"
    assert run(s, "elements.set_slab_outline", element=w, points=[[0, 0], [1, 0]])["error"]["code"] == "bad_input"
    assert run(s, "elements.stretch", element=w, end="middle", to=[40, 90])["error"]["code"] == "bad_input"
    assert run(s, "elements.stretch", element=w, end="end", to=[30, 90])["error"]["code"] == "bridge_error"
