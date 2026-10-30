# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent create, level and object tools on the sample house, in direct tasks (D102)."""
import json
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import authoring as A
from kimbim import documents as D
from kimbim import kimfile as K
from kimbim import library as Lib
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


def dims(guid):
    return {n: v for n, v, _ in A.element_dimensions(B._model.by_guid(guid))}


def param(guid, name):
    return Lib._object_of(B._model.by_guid(guid))[1][name]


def test_agent_model_tools_create_place_and_follow_edits(s):
    created = run(s, "models.create", name="Apartment")
    assert created["ok"], created
    model = created["result"]["guid"]
    level = next(s for s in json.loads(A.storeys())["storeys"] if not s.get("model"))["guid"]
    wall = run(s, "create.wall", level=model, start=[0, 0], end=[4, 0])
    assert wall["ok"], wall
    placed = run(s, "models.place", model=model, level=level, at=[1, 1])
    assert placed["ok"], placed
    assert run(s, "elements.rename", elements=[wall["result"]["guids"][0]], name="Unit wall")["ok"]
    instance = A._instances()[placed["result"]["instance"]]
    assert "Unit wall" in {e.Name for e in instance}
    listed = run(s, "models.list")
    assert listed["result"]["models"][0]["instances"] == 1


def test_create_wall_with_units(s):
    r = run(s, "create.wall", level="Level 2", start=[20, 20], end=["25m", "20"], height="280cm")
    assert r["ok"], r
    (guid,) = r["result"]["guids"]
    d = dims(guid)
    assert d["Length"] == pytest.approx(5) and d["Height"] == pytest.approx(2.8)
    assert [a["guid"] for a in r["changes"]["added"]] == [guid]


def test_wall_joins_a_wall_it_touches(s):
    first = run(s, "create.wall", level="Level 1", start=[30, 30], end=[34, 30])["result"]["guids"][0]
    second = run(s, "create.wall", level="Level 1", start=[34, 30], end=[34, 33])
    assert second["ok"] and first in {m["guid"] for m in second["changes"]["modified"]}


def test_slab_from_walls(s):
    for a, b in (([40, 40], [44, 40]), ([44, 40], [44, 44]), ([44, 44], [40, 44]), ([40, 44], [40, 40])):
        assert run(s, "create.wall", level="Level 1", start=a, end=b)["ok"]
    walls = [w.GlobalId for w in B._model.by_type("IfcWall") if A._axis_world(w)[0][0] >= 39.9]
    assert len(walls) == 4
    r = run(s, "create.slab", level="Level 1", from_walls=walls)
    assert r["ok"], r
    xs = [p[0] for p in r["result"]["points_m"]]
    assert min(xs) < 40 and max(xs) > 44  # outer faces
    assert B._model.by_guid(r["result"]["guids"][0]).is_a("IfcSlab")


def test_slab_from_points_and_conflicting_input(s):
    r = run(s, "create.slab", level="Level 1", points=[[50, 50], [54, 50], [54, 54]])
    assert r["ok"], r
    both = run(s, "create.slab", level="Level 1", points=[[0, 0], [1, 0], [1, 1]], from_walls=["x"])
    assert not both["ok"] and both["error"]["code"] == "bad_input"


def test_window_in_wall(s):
    wall = run(s, "create.wall", level="Level 1", start=[60, 60], end=[66, 60])["result"]["guids"][0]
    r = run(s, "create.opening", kind="window", wall=wall, along="3m", width="1.2m", sill="90cm")
    assert r["ok"], r
    (g,) = r["result"]["guids"]
    assert B._model.by_guid(g).is_a("IfcWindow")
    assert dims(g)["Width"] == pytest.approx(1.2) and dims(g)["Sill height"] == pytest.approx(0.9)
    assert wall in {m["guid"] for m in r["changes"]["modified"]}


def test_type_by_name(s):
    names = [t["name"] for t in run(s, "create.types", kind="wall")["result"]["types"]]
    assert names
    r = run(s, "create.wall", level="Level 1", start=[70, 70], end=[74, 70], type=names[-1].upper())
    assert r["ok"], r
    column = run(s, "create.column", level="Level 1", at=[80, 80], rotation="90deg")
    beam = run(s, "create.beam", level="Level 1", start=[80, 80], end=[84, 80])
    assert column["ok"] and beam["ok"], (column, beam)


def test_unknown_type(s):
    r = run(s, "create.wall", level="Level 1", start=[0, 0], end=[1, 0], type="No such wall")
    assert not r["ok"] and r["error"]["code"] == "not_found"
    r = run(s, "create.wall", level="Nowhere", start=[0, 0], end=[1, 0])
    assert not r["ok"] and r["error"]["code"] == "not_found"


def test_room(s):
    for a, b in (([90, 90], [94, 90]), ([94, 90], [94, 94]), ([94, 94], [90, 94]), ([90, 94], [90, 90])):
        assert run(s, "create.wall", level="Level 1", start=a, end=b)["ok"]
    r = run(s, "create.room", level="Level 1", at=[92, 92], name="Study")
    assert r["ok"], r
    assert B._model.by_guid(r["result"]["guids"][0]).is_a("IfcSpace")


def test_add_edit_delete_level(s):
    r = run(s, "levels.add", name="Terrace", elevation="9m")
    assert r["ok"], r
    levels = {l["name"]: l for l in run(s, "levels.list")["result"]["levels"]}
    assert levels["Terrace"]["elevation"] == pytest.approx(9)
    assert run(s, "levels.edit", level="Terrace", name="Attic", elevation="9.5m")["ok"]
    levels = {l["name"]: l for l in run(s, "levels.list")["result"]["levels"]}
    assert "Terrace" not in levels and levels["Attic"]["elevation"] == pytest.approx(9.5)
    assert not run(s, "levels.edit", level="Attic")["ok"]
    assert run(s, "levels.delete", level="Attic")["ok"]
    assert "Attic" not in {l["name"] for l in run(s, "levels.list")["result"]["levels"]}


def test_place_bundled_chair(s):
    lib = run(s, "objects.library")["result"]["objects"]
    chair = next(o for o in lib if o["id"] == "chair")
    assert any(p["key"] == "width" for p in chair["parameters"])
    r = run(s, "objects.place", object="chair", level="Level 1", at=["2m", "3m"], angle="90deg",
            parameters={"width": "50cm"})
    assert r["ok"], r
    (g,) = r["result"]["guids"]
    assert param(g, "width") == pytest.approx(0.5)
    r2 = run(s, "objects.set_parameters", elements=[g], parameters={"width": "60cm"})
    assert r2["ok"], r2
    assert param(g, "width") == pytest.approx(0.6)
    versions = run(s, "objects.versions", object="chair")
    assert versions["ok"] and "versions" in versions["result"]
    assert run(s, "objects.assign_version", elements=[g], version="#default")["ok"]
    current = run(s, "objects.update_from_library", elements=[g])
    assert current["ok"] and current["result"]["updated"] == 0
    assert not run(s, "objects.place", object="nope", level="Level 1", at=[0, 0])["ok"]


def entity_count():
    return sum(1 for _ in B._model)


def test_types_is_a_read_that_creates_nothing(s):
    # strip the sample house of its wall types; the other kinds are listed as they are
    walls = [w.GlobalId for w in B._model.by_type("IfcWall")]
    assert json.loads(A.delete_elements(json.dumps(walls)))["ok"]
    for t in list(B._model.by_type("IfcWallType")):
        B._model.remove(t)
    before = (B._current_id(), entity_count())
    r = run(s, "create.types", kind="wall")
    assert r["ok"] and r["result"]["types"] == [] and "hint" in r["result"], r
    for kind in ("slab", "column", "beam", "door", "window"):
        assert run(s, "create.types", kind=kind)["ok"], kind
    assert (B._current_id(), entity_count()) == before
    r = run(s, "create.wall", level="Level 1", start=[0, 0], end=[4, 0])
    assert r["ok"], r
    assert run(s, "create.types", kind="wall")["result"]["types"]


def test_wall_join_at(s):
    level = json.loads(A.storeys())["storeys"][0]["guid"]
    first = run(s, "create.wall", level="Level 1", start=[30, 30], end=[34, 30])["result"]["guids"][0]
    near = lambda x, y: json.loads(A.wall_join_at(level, x, y))  # noqa: E731
    assert near(34, 30)["guid"] == first and near(30.005, 30)["guid"] == first
    assert near(32, 30)["guid"] == first  # T join on the axis
    assert near(32, 31)["guid"] == "" and near(50, 50)["guid"] == ""
    assert not json.loads(A.wall_join_at("nope", 0, 0))["ok"]


def test_beam_top_is_above_the_level(s):
    r = run(s, "create.beam", level="Level 2", start=[80, 80], end=[84, 80], top="2.5m")
    assert r["ok"], r
    (g,) = r["result"]["guids"]
    assert r["result"]["top_m"] == pytest.approx(5.5)  # Level 2 is at 3 m
    assert A._world(B._model.by_guid(g))[2] == pytest.approx(5.5)


def test_delete_level_moving_its_elements(s):
    assert run(s, "levels.add", name="Annex", elevation="12m")["ok"]
    n = len([w for w in B._model.by_type("IfcWall")
             if w.ContainedInStructure[0].RelatingStructure.Name == "Level 2"])
    assert n
    assert not run(s, "levels.delete", level="Level 2")["ok"]  # refuse is the default
    assert not run(s, "levels.delete", level="Level 2", elements="move")["ok"]  # move needs move_to
    r = run(s, "levels.delete", level="Level 2", elements="move", move_to="Annex")
    assert r["ok"], r
    assert "Level 2" not in {l["name"] for l in run(s, "levels.list")["result"]["levels"]}
    annex = [w for w in B._model.by_type("IfcWall") if w.ContainedInStructure[0].RelatingStructure.Name == "Annex"]
    assert len(annex) == n
