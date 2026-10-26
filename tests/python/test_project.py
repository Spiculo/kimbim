# SPDX-License-Identifier: GPL-3.0-or-later
import ifcopenshell
import ifcopenshell.api.pset
import pytest
from conftest import build_model

from kimbim.project import InvalidInput, NotAProject, NothingToCommit, NoVersions, Project, SchemaMismatch, TargetExists
from kimbim.records import body_text, decompose

AUTHOR = ("Test", "test@example.org")


def write(f, path):
    f.write(str(path))
    return path


@pytest.fixture
def project(tmp_path):
    return Project.init(tmp_path / "Proyecto ñ")


def test_first_commit_then_nothing_to_commit(project, tmp_path):
    src = write(build_model(), tmp_path / "a.ifc")
    cid, changes = project.commit(src, "first", author=AUTHOR, time=1790000000)
    assert len(cid) == 40 and changes.added and not changes.modified
    assert project.schema() == "IFC4"
    with pytest.raises(NothingToCommit):
        project.commit(src, "again", author=AUTHOR)
    assert len(project.log()) == 1


def test_property_edit_is_a_tiny_diff(project, tmp_path):
    f = build_model(walls=3)
    project.commit(write(f, tmp_path / "a.ifc"), "first", author=AUTHOR, time=1)
    pset = [p for p in f.by_type("IfcPropertySet") if p.Name == "Pset_WallCommon"][0]
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"FireRating": "EI60"})
    status = project.status(write(f, tmp_path / "b.ifc"))
    assert [c.ifc_type for c in status.modified] == ["IfcPropertySet"]
    assert not status.added and not status.removed
    project.commit(tmp_path / "b.ifc", "EI60", author=AUTHOR, time=2)
    d = project.diff()
    assert [(c.kind, c.ifc_type) for c in d.items] == [("modified", "IfcPropertySet")]


def test_export_reproduces_versions(project, tmp_path):
    f = build_model()
    project.commit(write(f, tmp_path / "a.ifc"), "first", author=AUTHOR, time=1)
    f.by_type("IfcWall")[0].Name = "Renamed"
    project.commit(write(f, tmp_path / "b.ifc"), "rename", author=AUTHOR, time=2)
    out1 = project.export(tmp_path / "v1.ifc", rev="HEAD~1")
    out2 = project.export(tmp_path / "v2.ifc")
    assert "Renamed" not in body_text(out1) and "Renamed" in body_text(out2)
    assert decompose(ifcopenshell.open(str(out2)))[0] == decompose(f)[0]
    with pytest.raises(TargetExists):
        project.export(out2)
    project.export(out2, overwrite=True)
    assert not project.status(out2)  # exported HEAD == HEAD


def test_schema_mismatch_refused(project, tmp_path):
    project.commit(write(build_model("IFC4"), tmp_path / "a.ifc"), "first", author=AUTHOR, time=1)
    with pytest.raises(SchemaMismatch, match="IFC4X3_ADD2"):
        project.commit(write(build_model("IFC4X3_ADD2"), tmp_path / "b.ifc"), "x", author=AUTHOR)
    assert len(project.log()) == 1


INVALID_IFC = """ISO-10303-21;
HEADER;FILE_DESCRIPTION((''),'2;1');FILE_NAME('','',(''),(''),'','','');FILE_SCHEMA(('IFC4'));ENDSEC;
DATA;
#1=IFCCARTESIANPOINTLIST3D(((0.,0.,0.),(1.,0.,0.),(0.,1.,0.)),$);
#2=IFCTRIANGULATEDFACESET(#1,$,.T.,((1,2,3)),((1,2,3)));
ENDSEC;
END-ISO-10303-21;
"""


def test_invalid_input_refused(project, tmp_path):
    bad = tmp_path / "bad.ifc"
    bad.write_text(INVALID_IFC)
    with pytest.raises(InvalidInput) as e:
        project.commit(bad, "bad", author=AUTHOR)
    assert e.value.messages
    assert project.log() == []


def test_empty_project_and_unknown_dir(project, tmp_path):
    assert project.log() == []
    with pytest.raises(NoVersions):
        project.diff()
    with pytest.raises(NoVersions):
        project.export(tmp_path / "x.ifc")
    with pytest.raises(NotAProject):
        Project.open(tmp_path / "nowhere")


def test_branches(project, tmp_path):
    f = build_model()
    project.commit(write(f, tmp_path / "a.ifc"), "base", author=AUTHOR, time=1)
    project.create_branch("option-b")
    project.switch("option-b")
    f.by_type("IfcWall")[0].Name = "B"
    project.commit(write(f, tmp_path / "b.ifc"), "b", author=AUTHOR, time=2)
    assert project.current_branch() == "option-b" and project.branches() == ["main", "option-b"]
    project.switch("main")
    assert len(project.log()) == 1


def test_malformed_globalids_are_reported_not_crashed(project, tmp_path):
    f = build_model()
    walls = f.by_type("IfcWall")
    walls[0].GlobalId = "bad/../id"
    walls[1].GlobalId = ""
    with pytest.raises(InvalidInput, match="GlobalId") as e:
        project.commit(write(f, tmp_path / "bad.ifc"), "x", author=AUTHOR)
    assert any("bad/../id" in m for m in e.value.messages)
    assert project.log() == []


def _shared_owner_history(f):
    """Like a Revit export: every rooted entity shares ONE IfcOwnerHistory."""
    shared = f.by_type("IfcOwnerHistory")[0]
    for r in f.by_type("IfcRoot"):
        r.OwnerHistory = shared
    for oh in f.by_type("IfcOwnerHistory"):
        if oh != shared:
            f.remove(oh)
    shared.LastModifyingUser = shared.LastModifyingApplication = None  # its user and application: inline
    return shared


def test_owner_history_is_bookkeeping_not_content(project, tmp_path):
    """Editing a wall gives it its own owner history (IFC2X3), which re-encodes the shared one and so
    every rooted record (the Clinic: 41,068 records); an in-place timestamp is no change of elements
    either. The edited wall is the one change reported."""
    from kimbim.testing import _reset_owner

    f = build_model(schema="IFC2X3", walls=3)
    _reset_owner()  # the IFC2X3 owner callbacks are global: don't leak them into later tests
    shared = _shared_owner_history(f)
    project.commit(write(f, tmp_path / "a.ifc"), "first", author=AUTHOR, time=1)
    walls = f.by_type("IfcWall")[:2]
    edited = f.createIfcOwnerHistory(shared.OwningUser, shared.OwningApplication, None, "MODIFIED",
                                     1790000000, shared.OwningUser, shared.OwningApplication, 0)
    for i, wall in enumerate(walls):
        wall.OwnerHistory = edited  # one edit, two walls
        wall.Name = f"Edited {i}"
    status = project.status(write(f, tmp_path / "b.ifc"))
    assert len([c for c in status.items if c.key.startswith("n/")]) >= 4  # the records changed: new ids
    expected = sorted(f"o/{w.GlobalId}" for w in walls)
    assert sorted(c.key for c in status.items if c.key.startswith("o/")) == expected
    project.commit(tmp_path / "b.ifc", "edit", author=AUTHOR, time=2)
    assert sorted(c.key for c in project.diff().items if c.key.startswith("o/")) == expected
    shared.LastModifiedDate = 1790000500  # edited in place: keeps its node id
    status = project.status(write(f, tmp_path / "c.ifc"))
    assert status and not [c for c in status.items if c.key.startswith("o/")]
