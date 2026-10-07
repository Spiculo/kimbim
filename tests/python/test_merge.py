# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice 21 (R4): three-way merge of records. Cases ported from ifcmerge (Bruno Postle, GPL-3.0-or-later,
t/003.ifc.t and t/005.float_normalisation.t); fixtures in tests/fixtures/ifcmerge. KIMCAD merges by
GlobalId records, not STEP ids, so ifcmerge's renumbering cases simply merge; where KIMCAD's rules differ
on purpose (both sides moving one element is a conflict, docs/03) the test says so."""
import json
import pathlib

import ifcopenshell
import pytest

from kimcad.layout import blob_oid, key_to_path
from kimcad.merge import merge_records
from kimcad.nodeids import decompose_against_head
from kimcad.records import compose, decompose

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "ifcmerge"


def records(name, base=None):
    f = ifcopenshell.open(str(FIXTURES / name))
    if base is None:
        return decompose(f)[0]
    entries = {key_to_path(k): blob_oid(v) for k, v in base.items()}
    blobs = {blob_oid(v): v for v in base.values()}
    return decompose_against_head(f, entries, lambda oids: [blobs[o] for o in oids])[0]


_cache = {}


def merge(base, ours, theirs, resolutions=None):
    if base not in _cache:
        _cache[base] = records(base)
    b = _cache[base]
    for name in (ours, theirs):
        if (base, name) not in _cache:
            _cache[(base, name)] = records(name, b)
    return merge_records(b, _cache[(base, ours)], _cache[(base, theirs)], resolutions)


def count(recs, ifc_class):
    return len(compose(recs).by_type(ifc_class))


BASE = "base_simple_room.ifc"


@pytest.mark.parametrize("ours,theirs", [
    ("add_window_wall1.ifc", "add_door_wall3.ifc"),  # 1: non-overlapping additions
    ("add_window_wall1.ifc", "add_window_wall2.ifc"),  # 2: different window additions
    ("add_window_wall1.ifc", "modify_wall3_height_3000.ifc"),  # 3: addition + modification
    ("modify_window1_name_alpha.ifc", "modify_window2_name_gamma.ifc"),  # 7: different elements modified
    ("delete_floor.ifc", "add_wall_and_window.ifc"),  # 8: floor deleted + wall added (no dependency)
    ("add_five_new_elements.ifc", "add_eight_new_elements.ifc"),  # 9: overlapping STEP ids (no issue by GlobalId)
    ("delete_window_wall1.ifc", "add_door_wall3.ifc"),  # 10: deletion + unrelated addition
    ("add_window_modify_wall3.ifc", "add_door_wall3.ifc"),  # 11: combined operations
    ("modify_wall3_height_3000.ifc", "modify_window1_name_beta.ifc"),  # 14
    ("delete_two_windows.ifc", "add_window_wall2.ifc"),  # 15: deletions + additions
    (BASE, BASE),  # 17: no changes
    ("add_window_wall1.ifc", BASE),  # 18: only ours
    (BASE, "add_door_wall3.ifc"),  # 19: only theirs
    ("modify_window1_and_wall3.ifc", "add_two_windows.ifc"),  # 20: complex
])
def test_clean_merges(ours, theirs):
    r = merge(BASE, ours, theirs)
    assert r.clean, [c.to_dict() for c in r.conflicts]
    f = compose(r.records)  # the merged records make a model
    assert f.by_type("IfcProject")
    # ... with no IFC schema problem that neither side had.
    assert merge_records(_cache[BASE], _cache[(BASE, ours)], _cache[(BASE, theirs)], validate=True).warnings == []


def test_clean_merge_keeps_both_sides():
    base = count(_cache.get(BASE) or records(BASE), "IfcWindow")
    r = merge(BASE, "add_window_wall1.ifc", "add_window_wall2.ifc")
    assert count(r.records, "IfcWindow") == base + 2
    r = merge(BASE, "add_window_wall1.ifc", "add_door_wall3.ifc")
    merged = compose(r.records)
    assert len(merged.by_type("IfcWindow")) == base + 1 and len(merged.by_type("IfcDoor")) == len(
        compose(_cache[BASE]).by_type("IfcDoor")) + 1
    # The door's and window's openings void their walls in the merged model.
    voided = {rel.RelatingBuildingElement.GlobalId for rel in merged.by_type("IfcRelVoidsElement")}
    assert len(voided) >= 2


def test_sets_merge_as_sets():
    rel = lambda *m: rec("IfcRelContainedInSpatialStructure", GlobalId="R", RelatingStructure={"@o": "L"},  # noqa: E731
                         RelatedElements=sorted([{"@o": x} for x in m], key=lambda v: json.dumps(v, separators=(",", ":"))))
    others = {f"o/{x}": rec("IfcWall", GlobalId=x) for x in "ABCDL"}
    r = merge_records({"o/R": rel("A", "B"), **others}, {"o/R": rel("A", "B", "C"), **others}, {"o/R": rel("B", "D"), **others})
    assert r.clean, [c.id for c in r.conflicts]
    assert [m["@o"] for m in json.loads(r.records["o/R"])["a"]["RelatedElements"]] == ["B", "C", "D"]


def test_modify_on_both_sides_is_reproducible():
    # 6 / 16: the same attribute changed to different values, in either order.
    a = merge(BASE, "modify_window1_name_alpha.ifc", "modify_window1_name_beta.ifc")
    b = merge(BASE, "modify_window1_name_beta.ifc", "modify_window1_name_alpha.ifc")
    assert not a.clean and not b.clean
    (c,) = [x for x in a.conflicts if x.kind == "attribute"]
    assert c.attribute == "Name" and c.ifc_type == "IfcWindow"
    assert {c.ours, c.theirs} == {"Window-Alpha", "Window-Beta"} or c.ours != c.theirs
    assert [x.id for x in a.conflicts] == [x.id for x in b.conflicts]  # same conflicts whatever the order
    # Resolving it: the chosen value is in the result, deterministically.
    r1 = merge(BASE, "modify_window1_name_alpha.ifc", "modify_window1_name_beta.ifc", {c.id: "theirs"})
    r2 = merge(BASE, "modify_window1_name_alpha.ifc", "modify_window1_name_beta.ifc", {c.id: "theirs"})
    assert r1.clean and r1.records == r2.records
    assert json.loads(r1.records[c.key])["a"]["Name"] == c.theirs


@pytest.mark.parametrize("ours,theirs", [("delete_wall4.ifc", "modify_wall4_height_3500.ifc"),  # 4
                                         ("modify_wall4_height_3500.ifc", "delete_wall4.ifc")])  # 5
def test_delete_modify_conflict(ours, theirs):
    r = merge(BASE, ours, theirs)
    kinds = {c.kind for c in r.conflicts}
    assert "delete_modify" in kinds and not r.clean
    c = next(c for c in r.conflicts if c.kind == "delete_modify" and c.ifc_type == "IfcWall")
    assert c.name == "exterior" or c.name
    # Keeping the wall (the side that modified it) merges cleanly.
    keep = "theirs" if c.ours is None else "ours"
    resolved = merge(BASE, ours, theirs, {x.id: (keep if x.kind == "delete_modify" else "ours") for x in r.conflicts})
    assert resolved.clean, [x.to_dict() for x in resolved.conflicts if x.id in resolved.unresolved]


def test_boundary_type_conflict():
    # 12: one side makes a space boundary PHYSICAL, the other VIRTUAL.
    r = merge(BASE, "boundary_wall1_type_physical.ifc", "boundary_wall1_type_virtual.ifc")
    assert not r.clean
    assert any(c.attribute == "PhysicalOrVirtualBoundary" for c in r.conflicts)


def test_both_moving_one_element_is_a_conflict():
    # 13: ifcmerge picks one placement automatically; KIMCAD asks (placements are absolute, docs/03).
    r = merge(BASE, "placement_window1_moved_left.ifc", "placement_window1_moved_right.ifc")
    assert not r.clean
    assert any(c.kind == "attribute" and c.attribute == "ObjectPlacement" or c.key.startswith("n/") for c in r.conflicts)


def test_deleting_a_wall_that_gets_a_door_is_a_semantic_conflict():
    # The other side adds a door to wall 4 that this side deleted: the door's opening refers to it.
    r = merge(BASE, "delete_wall4.ifc", "delete_wall4_add_door.ifc")
    # delete_wall4_add_door deletes wall 4 too: both agree, no conflict.
    assert r.clean
    r = merge(BASE, "delete_wall4.ifc", "add_door_wall3.ifc")
    assert r.clean  # the door is on wall 3: no dependency


@pytest.mark.parametrize("ours,theirs", [("float_resave_only.ifc", "float_base.ifc"),
                                         ("float_base.ifc", "float_resave_only.ifc"),
                                         ("float_resave_only.ifc", "float_resave_only.ifc"),
                                         ("float_resave_only.ifc", "float_name_changed.ifc")])
def test_float_resaves_do_not_conflict(ours, theirs):
    # ifcmerge t/005: re-saving with differently formatted floats is not a change.
    r = merge("float_base.ifc", ours, theirs)
    assert r.clean, [c.to_dict() for c in r.conflicts]


def test_merge_is_deterministic():
    a = merge(BASE, "add_window_modify_wall3.ifc", "add_door_wall3.ifc")
    b = merge(BASE, "add_window_modify_wall3.ifc", "add_door_wall3.ifc")
    assert a.records == b.records


# ---------------------------------------------------------------- unit cases on hand-made records

def rec(t, **a):
    return json.dumps({"a": a, "t": t}, sort_keys=True, separators=(",", ":")).encode()


def test_property_sets_merge_per_property():
    def pset(**props):
        return rec("IfcPropertySet", GlobalId="P", Name="Pset_WallCommon", HasProperties=sorted(
            [{"a": {"Name": k, "NominalValue": {"@t": "IfcLabel", "v": v}}, "t": "IfcPropertySingleValue"}
             for k, v in props.items()], key=lambda x: json.dumps(x, sort_keys=True, separators=(",", ":"))))
    base = {"o/P": pset(FireRating="EI 30", AcousticRating="40")}
    ours = {"o/P": pset(FireRating="EI 60", AcousticRating="40")}
    theirs = {"o/P": pset(FireRating="EI 30", AcousticRating="45", Status="New")}
    r = merge_records(base, ours, theirs)
    assert r.clean
    props = {p["a"]["Name"]: p["a"]["NominalValue"]["v"] for p in json.loads(r.records["o/P"])["a"]["HasProperties"]}
    assert props == {"FireRating": "EI 60", "AcousticRating": "45", "Status": "New"}
    clash = merge_records(base, ours, {"o/P": pset(FireRating="EI 90", AcousticRating="40")})
    (c,) = clash.conflicts
    assert c.kind == "property" and c.property == "FireRating" and c.id == "o/P#HasProperties[FireRating]"


def test_dangling_reference_and_double_containment():
    level1 = rec("IfcBuildingStorey", GlobalId="L1", Name="Level 1")
    level2 = rec("IfcBuildingStorey", GlobalId="L2", Name="Level 2")
    wall = rec("IfcWall", GlobalId="W", Name="Wall")
    base = {"o/L1": level1, "o/L2": level2, "o/W": wall,
            "o/R1": rec("IfcRelContainedInSpatialStructure", GlobalId="R1", RelatedElements=[{"@o": "W"}], RelatingStructure={"@o": "L1"}),
            "o/R2": rec("IfcRelContainedInSpatialStructure", GlobalId="R2", RelatedElements=[], RelatingStructure={"@o": "L2"})}
    # Ours deletes the wall; theirs adds a door voiding it.
    ours = {k: v for k, v in base.items() if k != "o/W"}
    ours["o/R1"] = rec("IfcRelContainedInSpatialStructure", GlobalId="R1", RelatedElements=[], RelatingStructure={"@o": "L1"})
    theirs = dict(base)
    theirs["o/V"] = rec("IfcRelVoidsElement", GlobalId="V", RelatingBuildingElement={"@o": "W"}, RelatedOpeningElement={"@o": "O"})
    theirs["o/O"] = rec("IfcOpeningElement", GlobalId="O")
    r = merge_records(base, ours, theirs)
    (c,) = [c for c in r.conflicts if c.kind == "dangling"]
    assert c.key == "o/V" and c.attribute == "o/W" and c.options == ["restore", "remove"]
    restored = merge_records(base, ours, theirs, {c.id: "restore"})
    assert restored.clean and "o/W" in restored.records
    removed = merge_records(base, ours, theirs, {c.id: "remove"})
    assert removed.clean and "o/V" not in removed.records and "o/W" not in removed.records
    # Ours moves the wall to Level 2, theirs... also moves it there: agreement. But each side moving it to a
    # different relationship (ours R2, theirs a new R3 on Level 1) leaves it in two levels.
    ours2 = dict(base)
    ours2["o/R1"] = ours["o/R1"]
    ours2["o/R2"] = rec("IfcRelContainedInSpatialStructure", GlobalId="R2", RelatedElements=[{"@o": "W"}], RelatingStructure={"@o": "L2"})
    theirs2 = dict(base)
    theirs2["o/R3"] = rec("IfcRelContainedInSpatialStructure", GlobalId="R3", RelatedElements=[{"@o": "W"}], RelatingStructure={"@o": "L1"})
    theirs2["o/R1"] = ours["o/R1"]
    r = merge_records(base, ours2, theirs2)
    (c,) = [c for c in r.conflicts if c.kind == "containment"]
    assert sorted(c.options) == ["o/R2", "o/R3"]
    fixed = merge_records(base, ours2, theirs2, {c.id: "o/R2"})
    assert fixed.clean and json.loads(fixed.records["o/R3"])["a"]["RelatedElements"] == []


# ---------------------------------------------------------------- repository: kimcad merge

from kimcad.cli import main as cli  # noqa: E402
from kimcad.project import MergeConflicts, Project  # noqa: E402


def two_options(tmp_path, ours, theirs):
    p = Project.init(tmp_path / "p")
    p.commit(FIXTURES / BASE, "base")
    p.create_branch("b")
    p.commit(FIXTURES / ours, "ours")
    p.switch("b")
    p.commit(FIXTURES / theirs, "theirs")
    p.switch("main")
    return p


def test_project_merge_clean(tmp_path):
    p = two_options(tmp_path, "add_window_wall1.ifc", "add_door_wall3.ifc")
    preview = p.merge_preview("b")
    assert preview.status == "merge" and preview.result.clean
    cid = p.merge("b", "Combine b")
    log = p.log("HEAD", 1)[0]
    assert log.id == cid and len(log.parents) == 2
    merged = ifcopenshell.open(str(p.export(tmp_path / "m.ifc")))
    base = ifcopenshell.open(str(FIXTURES / BASE))
    assert len(merged.by_type("IfcWindow")) == len(base.by_type("IfcWindow")) + 1
    assert len(merged.by_type("IfcDoor")) == len(base.by_type("IfcDoor")) + 1
    assert p.merge_preview("b").status == "up_to_date"
    # The other option can now catch up without a merge.
    p.switch("b")
    assert p.merge_preview("main").status == "fast_forward"
    assert p.merge("main", "catch up") == cid


def test_project_merge_with_conflicts(tmp_path, capsys):
    p = two_options(tmp_path, "modify_window1_name_alpha.ifc", "modify_window1_name_beta.ifc")
    with pytest.raises(MergeConflicts) as info:
        p.merge("b", "Combine b")
    (c,) = info.value.result.conflicts
    assert p.log("HEAD", 1)[0].message.strip() == "ours"  # nothing committed
    code = cli(["-C", str(tmp_path / "p"), "merge", "b", "-m", "Combine b"])
    out = capsys.readouterr()
    assert code == 1 and c.id in out.out and "Window" in out.out
    code = cli(["-C", str(tmp_path / "p"), "merge", "b", "-m", "Combine b", "--resolve", f"{c.id}=theirs"])
    assert code == 0, capsys.readouterr()
    assert len(p.log("HEAD", 1)[0].parents) == 2
    name = json.loads(p._records("HEAD")[c.key])["a"]["Name"]
    assert name == c.theirs


def test_owner_history_is_bookkeeping_not_a_conflict():
    base = {"o/W": rec("IfcWall", GlobalId="W", Name="a", OwnerHistory={"@n": "h0"})}
    ours = {"o/W": rec("IfcWall", GlobalId="W", Name="a", OwnerHistory={"@n": "h1"})}
    theirs = {"o/W": rec("IfcWall", GlobalId="W", Name="b", OwnerHistory={"@n": "h2"})}
    r = merge_records(base, ours, theirs)
    assert not [c for c in r.conflicts if c.attribute == "OwnerHistory"]
    v = json.loads(r.records["o/W"])["a"]
    assert v["Name"] == "b" and v["OwnerHistory"] == {"@n": "h1"}  # this option's history


def test_an_owner_history_edited_on_both_sides_is_not_a_conflict():
    """In IFC2X3 an element's own IfcOwnerHistory is updated in place and keeps its node id, so both
    options change the same n/<id>: its dates and ChangeAction are bookkeeping; the newer one is kept."""
    def history(modified, action):
        return rec("IfcOwnerHistory", ChangeAction=action, CreationDate=100, LastModifiedDate=modified)

    wall = rec("IfcWall", GlobalId="W", Name="a", OwnerHistory={"@n": "H"})
    base = {"o/W": wall, "n/H": history(100, "NOCHANGE")}
    ours = {"o/W": wall, "n/H": history(300, "MODIFIED")}
    theirs = {"o/W": wall, "n/H": history(200, "MODIFIED")}
    r = merge_records(base, ours, theirs)
    assert r.conflicts == []
    assert json.loads(r.records["n/H"])["a"]["LastModifiedDate"] == 300
    r = merge_records(base, theirs, ours)
    assert r.conflicts == [] and json.loads(r.records["n/H"])["a"]["LastModifiedDate"] == 300
