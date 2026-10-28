# SPDX-License-Identifier: GPL-3.0-or-later
"""R3 property-level Compare: attributes, properties, categories, the level tree, CLI output and a
one-element diff whose cost does not follow the model size."""
import json
import pathlib
import time

import ifcopenshell.api.pset
import ifcopenshell.util.element

from kimbim.cli import main
from kimbim.project import Project
from kimbim.testing import build_model


def make_project(tmp_path, walls=3, name="project"):
    model = build_model(walls=walls)
    first = tmp_path / f"{name}-1.ifc"
    model.write(str(first))
    project = Project.init(tmp_path / name)
    project.commit(first, "Initial import")
    return project, model


def edit_wall(model, index=0, name="Renamed wall", fire="EI60"):
    wall = model.by_type("IfcWall")[index]
    wall.Name = name
    pset = ifcopenshell.util.element.get_pset(wall, "Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(model, pset=model.by_id(pset["id"]), properties={"FireRating": fire})
    return wall


def commit_edit(project, model, tmp_path, name="edit"):
    path = tmp_path / f"{name}.ifc"
    model.write(str(path))
    project.commit(path, name)
    return path


def test_property_level_detail(tmp_path):
    project, model = make_project(tmp_path, walls=2)
    wall = edit_wall(model)
    commit_edit(project, model, tmp_path)
    r = project.diff_details("HEAD^", "HEAD")

    assert len(r["changes"]["modified"]) == 1
    assert r["changes"]["modified"][0]["guid"] == wall.GlobalId
    detail = r["details"][0]
    assert detail["guid"] == wall.GlobalId and detail["type"] == "IfcWall"
    assert detail["level"] == "Level 1"
    assert detail["attributes"] == [{"name": "Name", "kind": "modified", "old": "Wall 0", "new": "Renamed wall"}]
    assert detail["properties"] == [{"pset": "Pset_WallCommon", "property": "FireRating",
                                     "kind": "modified", "old": "EI30", "new": "EI60"}]
    assert r["categories"] == {"IfcWall": {"added": 0, "modified": 1, "removed": 0}}
    assert r["tree"] == {"Level 1": {"IfcWall": {"added": 0, "modified": 1, "removed": 0}}}
    assert r["other"] >= 1  # the property set record itself


def test_added_and_removed_elements_are_listed(tmp_path):
    project, model = make_project(tmp_path, walls=2)
    walls = model.by_type("IfcWall")
    removed = walls[0].GlobalId
    model.remove(walls[0])
    # A new wall, placed by hand (no geometry needed for the report).
    import ifcopenshell.api.root
    import ifcopenshell.api.spatial
    new = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="New wall")
    ifcopenshell.api.spatial.assign_container(model, products=[new],
                                               relating_structure=model.by_type("IfcBuildingStorey")[0])
    commit_edit(project, model, tmp_path, "add-remove")
    r = project.diff_details("HEAD^", "HEAD")
    assert [e["guid"] for e in r["changes"]["added"]] == [new.GlobalId]
    assert [e["guid"] for e in r["changes"]["removed"]] == [removed]
    assert r["categories"]["IfcWall"] == {"added": 1, "modified": 0, "removed": 1}


def test_cli_diff_prints_human_and_json(tmp_path, capsys):
    project, model = make_project(tmp_path, walls=2)
    edit_wall(model)
    commit_edit(project, model, tmp_path)
    code = main(["--project", str(project.path), "--no-worker", "versions", "diff", "--from", "HEAD^",
                 "--to", "HEAD", "--detail"])
    out = capsys.readouterr().out
    assert code == 0
    assert "1 modified" in out and "Pset_WallCommon.FireRating" in out and "Renamed wall" in out

    code = main(["--project", str(project.path), "--no-worker", "versions", "diff", "--from", "HEAD^",
                 "--to", "HEAD", "--detail", "--json"])
    out = capsys.readouterr().out
    assert code == 0
    r = json.loads(out)["result"]
    assert r["details"][0]["properties"][0]["new"] == "EI60"


def test_a_one_element_diff_does_not_scale_with_the_model(tmp_path):
    def one_change(model, project, tag):
        wall = model.by_type("IfcWall")[0]
        wall.Name = f"Bench {tag}"
        path = tmp_path / f"{tag}.ifc"
        model.write(str(path))
        project.commit(path, tag)
        project.diff("HEAD^", "HEAD")  # warm the record cache
        start = time.perf_counter()
        project.diff_details("HEAD^", "HEAD")
        return time.perf_counter() - start

    small, small_model = make_project(tmp_path, walls=20, name="small")
    t_small = one_change(small_model, small, "small-change")
    large, large_model = make_project(tmp_path, walls=400, name="large")
    t_large = one_change(large_model, large, "large-change")
    # The 20x model must not make a one-name diff 20x slower (generous bound for CI noise).
    assert t_large < max(0.5, t_small * 5), (t_small, t_large)
