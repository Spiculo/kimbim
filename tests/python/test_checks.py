# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks (D81, doc 14 §19): schema validation, IDS, clash detection and model checks, each on a small
model with planted problems; the sample house is clean; timings on the Clinic (slow)."""
import json
import sys
import time
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.util.element
import numpy as np
import pytest

from kimbim import app_bridge as b
from kimbim import checks
from kimbim import settings
from kimbim.testing import build_model

ROOT = Path(__file__).resolve().parents[2]
CLINIC = ROOT / "tests" / "corpus" / "files" / "community" / "IFC 2.3.0.1 (IFC 2x3)" / "Medical-Dental Clinic" / "Clinic_Architectural.ifc"
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def run(name, options=None):
    r = call("run_check", name, json.dumps(options or {}))
    assert r["ok"], r
    return r


def by_group(result, group):
    return [i for i in result["issues"] if i["group"] == group]


def _body(f):
    return next(c for c in f.by_type("IfcGeometricRepresentationSubContext") if c.ContextIdentifier == "Body")


def _wall(f, name, x=0.0, y=0.0, length=4.0, contained=True):
    w = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name=name)
    rep = ifcopenshell.api.geometry.add_wall_representation(f, context=_body(f), length=length, height=3.0, thickness=0.2)
    ifcopenshell.api.geometry.assign_representation(f, product=w, representation=rep)
    m = np.eye(4)
    m[0][3], m[1][3] = x, y
    ifcopenshell.api.geometry.edit_object_placement(f, product=w, matrix=m, is_si=True)
    if contained:
        ifcopenshell.api.spatial.assign_container(f, products=[w], relating_structure=f.by_type("IfcBuildingStorey")[0])
    return w


@pytest.fixture
def opened():
    """Open an in-memory model in the bridge (the checks read B._model and the project settings)."""
    def _open(f):
        b._model = f
        settings.load(None)
        return f
    yield _open
    b._model = None
    settings.load(None)


@pytest.fixture(scope="module")
def house_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("house") / "house.ifc"
    make_house.build(str(path))
    return str(path)


# ---------------------------------------------------------------- the house is clean

def test_the_house_has_no_schema_or_model_issues(house_file):
    assert call("open_model", house_file)["ok"]
    for name in ("schema", "model"):
        r = run(name)
        assert r["issues"] == [], (name, r["issues"][:5])
    model = run("model")
    assert [g["status"] for g in model["groups"]] == ["pass"] * 5
    # Walls never clash with walls they are joined to; doors never with their walls.
    r = run("clash", {"clash_sets": {"walls": {"a": {"classes": ["IfcWall"]}},
                                     "doors": {"a": {"classes": ["IfcDoor", "IfcWindow"]}, "b": {"classes": ["IfcWall"]}}}})
    assert r["issues"] == [] and [g["status"] for g in r["groups"]] == ["pass", "pass"]


# ---------------------------------------------------------------- schema validation

def test_schema_validation_reports_attribute_and_where_rule_errors_on_their_element(opened):
    f = opened(build_model())
    wall = f.by_type("IfcWall")[0]
    wall.PredefinedType = "USERDEFINED"  # IfcWall.CorrectPredefinedType: needs an ObjectType
    owner = f.by_type("IfcWall")[1]
    solid = owner.Representation.Representations[0].Items[0]
    assert solid.is_a("IfcExtrudedAreaSolid")
    solid.Depth = -1.0  # IfcPositiveLengthMeasure's WHERE rule (> 0)
    r = run("schema")
    assert r["counts"]["error"] >= 2
    rule = [i for i in r["issues"] if "CorrectPredefinedType" in i["group"]]
    assert rule and rule[0]["guids"] == [wall.GlobalId]
    positive = [i for i in r["issues"] if "IfcExtrudedAreaSolid" in i["message"]]
    assert positive and positive[0]["guids"] == [owner.GlobalId]  # the profile's wall, to select
    quick = run("schema", {"express_rules": False})  # attributes and inverses only: no WHERE rules
    assert not [i for i in quick["issues"] if "CorrectPredefinedType" in i["group"]]


def test_schema_validation_runs_fast_the_second_time(opened):
    opened(build_model())
    run("schema")
    t0 = time.perf_counter()
    run("schema")
    assert time.perf_counter() - t0 < 2.5  # the rule module is compiled once per session


# ---------------------------------------------------------------- IDS

IDS = """<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS" xmlns:xs="http://www.w3.org/2001/XMLSchema"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:schemaLocation="http://standards.buildingsmart.org/IDS http://standards.buildingsmart.org/IDS/1.0/ids.xsd">
  <info><title>Office rules</title></info>
  <specifications>
    <specification name="Walls have a fire rating" ifcVersion="IFC2X3 IFC4">
      <applicability minOccurs="0" maxOccurs="unbounded"><entity><name><simpleValue>IFCWALL</simpleValue></name></entity></applicability>
      <requirements>
        <property dataType="IFCLABEL"><propertySet><simpleValue>Pset_WallCommon</simpleValue></propertySet>
          <baseName><simpleValue>FireRating</simpleValue></baseName></property>
      </requirements>
    </specification>
    <specification name="Walls have a name" ifcVersion="IFC2X3 IFC4">
      <applicability minOccurs="0" maxOccurs="unbounded"><entity><name><simpleValue>IFCWALL</simpleValue></name></entity></applicability>
      <requirements><attribute><name><simpleValue>Name</simpleValue></name></attribute></requirements>
    </specification>
    <specification name="There are doors" ifcVersion="IFC2X3 IFC4">
      <applicability minOccurs="1" maxOccurs="unbounded"><entity><name><simpleValue>IFCDOOR</simpleValue></name></entity></applicability>
    </specification>
  </specifications>
</ids>
"""


def test_ids_files_are_read_stored_in_the_settings_and_run(opened, tmp_path):
    f = opened(build_model(walls=3))
    bare = _wall(f, "No rating", x=20.0)
    path = tmp_path / "office.ids"
    path.write_text(IDS, encoding="utf-8")
    read = call("read_ids_file", str(path))
    assert read["ok"] and read["name"] == "office.ids" and read["specifications"] == 3 and read["title"] == "Office rules"
    # Stored in the project settings (versioned with the project, D81), not as a path.
    assert call("set_project_settings", json.dumps({"ids_files": {read["name"]: read["xml"]}}))["ok"]
    assert call("set_project_settings", json.dumps({"ids_files": {"x.ids": 3}}))["ok"] is False
    r = run("ids")
    status = {g["name"]: g["status"] for g in r["groups"]}
    assert status == {"office.ids · Walls have a fire rating": "fail", "office.ids · Walls have a name": "pass",
                      "office.ids · There are doors": "fail"}
    fire = by_group(r, "office.ids · Walls have a fire rating")
    assert [i["guids"] for i in fire] == [[bare.GlobalId]] and "No rating" in fire[0]["message"]
    doors = by_group(r, "office.ids · There are doors")
    assert len(doors) == 1 and doors[0]["guids"] == [] and "Required" in doors[0]["message"]
    # IfcTester's reports of the last run.
    html, js = tmp_path / "report.html", tmp_path / "report.json"
    assert call("export_ids_report", str(html))["ok"] and "Walls have a fire rating" in html.read_text(encoding="utf-8")
    assert call("export_ids_report", str(js))["ok"]
    report = json.loads(js.read_text(encoding="utf-8"))
    assert report["total_specifications"] == 3 and report["total_specifications_fail"] == 2


def test_a_broken_ids_file_is_refused(tmp_path):
    path = tmp_path / "bad.ids"
    path.write_text("<ids><nope/></ids>", encoding="utf-8")
    r = call("read_ids_file", str(path))
    assert r["ok"] is False and "bad.ids" in r["error"]


# ---------------------------------------------------------------- clash detection

def test_hard_clashes_and_clearance_between_two_sets(opened):
    f = opened(build_model())  # walls at x 0..4 and 5..9, 200 mm thick
    over = _wall(f, "Overlapping", x=2.0)  # crosses both
    near = _wall(f, "Near", x=0.0, y=0.35)  # 150 mm from wall 0
    w0, w1 = f.by_type("IfcWall")[:2]
    hard = run("clash", {"clash_sets": {"walls": {"a": {"classes": ["IfcWall"]}, "mode": "hard", "tolerance": 0.002}}})
    pairs = {frozenset(i["guids"]) for i in hard["issues"]}
    assert pairs == {frozenset((over.GlobalId, w0.GlobalId)), frozenset((over.GlobalId, w1.GlobalId))}
    assert all(i["severity"] == "error" and i["group"] == "walls" for i in hard["issues"])
    gap = run("clash", {"clash_sets": {"gap": {"a": {"classes": ["IfcWall"]}, "mode": "clearance", "clearance": 0.2}}})
    near_pairs = {frozenset(i["guids"]) for i in gap["issues"]}
    assert frozenset((near.GlobalId, w0.GlobalId)) in near_pairs
    tight = run("clash", {"clash_sets": {"gap": {"a": {"classes": ["IfcWall"]}, "mode": "clearance", "clearance": 0.1}}})
    assert frozenset((near.GlobalId, w0.GlobalId)) not in {frozenset(i["guids"]) for i in tight["issues"]}


def test_clash_sets_from_saved_find_and_select_criteria(opened):
    f = opened(build_model())
    over = _wall(f, "Overlapping", x=2.0)
    w0 = f.by_type("IfcWall")[0]
    criteria = {"overlap": {"match": "all", "rows": [{"field": "name", "op": "equals", "value": "Overlapping"}]},
                "first": {"match": "all", "rows": [{"field": "name", "op": "equals", "value": "Wall 0"}]}}
    sets = {"D78": {"a": {"criteria": "overlap"}, "b": {"criteria": "first"}, "mode": "hard"}}
    assert call("set_project_settings", json.dumps({"selection_criteria": criteria, "clash_sets": sets}))["ok"]
    r = run("clash")  # the project's clash sets
    assert [set(i["guids"]) for i in r["issues"]] == [{over.GlobalId, w0.GlobalId}]
    bad = call("set_project_settings", json.dumps({"clash_sets": {"x": {"a": {}, "mode": "hard"}}}))
    assert bad["ok"] is False and "set A" in bad["error"]


# ---------------------------------------------------------------- model checks

def test_model_checks_find_each_planted_problem(opened):
    f = opened(build_model())
    w0 = f.by_type("IfcWall")[0]
    twin = ifcopenshell.api.root.copy_class(f, product=w0)  # same class and place
    twin.Representation = ifcopenshell.util.element.copy_deep(f, w0.Representation)  # and the same shape
    stray = _wall(f, "Not on a level", x=30.0, contained=False)
    axis_ctx = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Axis",
                                                    target_view="GRAPH_VIEW", parent=f.by_type("IfcGeometricRepresentationContext")[0])
    zero = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name="Zero")
    rep = ifcopenshell.api.geometry.add_axis_representation(f, context=axis_ctx, axis=[(1.0, 1.0), (1.0, 1.0)])
    ifcopenshell.api.geometry.assign_representation(f, product=zero, representation=rep)
    ifcopenshell.api.spatial.assign_container(f, products=[zero], relating_structure=f.by_type("IfcBuildingStorey")[0])
    door = ifcopenshell.api.root.create_entity(f, ifc_class="IfcDoor", name="Loose door")
    ifcopenshell.api.spatial.assign_container(f, products=[door], relating_structure=f.by_type("IfcBuildingStorey")[0])
    storey = f.by_type("IfcBuildingStorey")[0]
    room = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSpace", name="101")
    nameless = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSpace")
    ifcopenshell.api.aggregate.assign_object(f, products=[room, nameless], relating_object=storey)
    room.LongName = ""  # a number, no name
    r = run("model")
    dup = by_group(r, "Duplicate elements")
    assert len(dup) == 1 and set(dup[0]["guids"]) == {w0.GlobalId, twin.GlobalId}
    rooms = by_group(r, "Rooms without a number or name")
    assert {i["guids"][0]: i["message"] for i in rooms} == {
        room.GlobalId: "IfcSpace 101 has no name", nameless.GlobalId: f"IfcSpace #{nameless.id()} has no number and no name"}
    assert [i["guids"] for i in by_group(r, "Walls with zero length")] == [[zero.GlobalId]]
    assert [i["guids"] for i in by_group(r, "Elements not on a level")] == [[stray.GlobalId]]
    assert [i["guids"] for i in by_group(r, "Doors and windows without a host")] == [[door.GlobalId]]
    only = run("model", {"model_checks": ["rooms"]})
    assert [g["name"] for g in only["groups"]] == ["Rooms without a number or name"]


def test_bad_input_and_no_model(opened):
    assert call("run_check", "nope", "{}")["ok"] is False
    b._model = None
    assert "no model" in call("run_check", "model", "{}")["error"]


def test_cancel_stops_a_running_check(opened):
    import threading

    opened(build_model(walls=40))
    out = {}
    checks._cancel = False

    def slow(model, options):  # a check that polls, like the real loops
        for _ in range(10_000):
            time.sleep(0.001)
            checks._poll()
        return {"issues": []}

    checks.RUNNERS["slow"], checks.TITLES["slow"] = slow, "Slow"
    try:
        t = threading.Thread(target=lambda: out.update(json.loads(checks.run_check("slow", "{}"))))
        t.start()
        time.sleep(0.2)
        assert call("cancel_checks")["running"] is True
        t.join(5)
        assert not t.is_alive() and out.get("cancelled") is True
    finally:
        del checks.RUNNERS["slow"], checks.TITLES["slow"]
    assert run("model")["ok"]  # the next run is not cancelled


# ---------------------------------------------------------------- the Clinic (timings)

@pytest.mark.slow
@pytest.mark.golden
def test_checks_on_the_clinic_timed(opened, capsys):
    if not CLINIC.exists():
        pytest.skip("corpus not fetched (pixi run fetch-corpus)")
    opened(ifcopenshell.open(str(CLINIC)))
    times = {}
    for name, options in (("model", {}), ("clash", {"clash_sets": {"walls": {"a": {"classes": ["IfcWall"]}}}}),
                          ("ids", {"ids": {"office.ids": IDS}}), ("schema", {"express_rules": False}), ("schema", {})):
        t0 = time.perf_counter()
        r = run(name, options)
        key = name + ("" if options.get("express_rules", True) else " (no rules)")
        times[key] = (round(time.perf_counter() - t0, 1), r["total"])
    with capsys.disabled():
        print("\nClinic checks (seconds, issues):", times)
    assert times["model"][0] < 15 and times["clash"][0] < 30
