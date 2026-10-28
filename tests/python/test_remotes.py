# SPDX-License-Identifier: GPL-3.0-or-later
"""Push and pull to a Git remote (thin wrappers over git; the storage is already Git)."""
import pathlib
import subprocess

import pytest

from kimbim.project import KimbimError, Project
from kimbim.testing import build_model


def make_project(tmp_path, name="project"):
    model = build_model(walls=2)
    first = tmp_path / f"{name}.ifc"
    model.write(str(first))
    project = Project.init(tmp_path / name)
    project.commit(first, "Initial import")
    return project, model, first


def bare_remote(tmp_path):
    path = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(path)], check=True, capture_output=True)
    return path


def test_push_and_pull_fast_forward(tmp_path):
    project, model, first = make_project(tmp_path)
    remote = bare_remote(tmp_path)
    project.add_remote("origin", str(remote))
    assert project.remotes() == [{"name": "origin", "url": str(remote)}]

    pushed = project.push()
    assert pushed["branch"] == "main" and pushed["remote"] == "origin"
    head = project.head_commit()
    assert subprocess.run(["git", f"--git-dir={remote}", "rev-parse", "main"], check=True,
                          capture_output=True, text=True).stdout.strip() == head

    model.by_type("IfcWall")[0].Name = "Second"
    second = tmp_path / "second.ifc"
    model.write(str(second))
    project.commit(second, "Second version")
    project.push()

    # A fresh project pulls the branch: the first pull creates it, the second is up to date.
    clone = Project.init(tmp_path / "clone")
    clone.add_remote("origin", str(remote))
    out = clone.pull()
    assert out["status"] == "fast_forward" and out["head"] == project.head_commit()
    assert clone.head_commit() == project.head_commit()
    assert clone.diff("HEAD~1", "HEAD").modified

    model.by_type("IfcWall")[1].Name = "Third"
    third = tmp_path / "third.ifc"
    model.write(str(third))
    project.commit(third, "Third version")
    project.push()
    assert clone.pull()["head"] == project.head_commit()

    with pytest.raises(KimbimError):
        project.pull("nope")


def test_diverged_branches_are_refused(tmp_path):
    project, model, first = make_project(tmp_path)
    remote = bare_remote(tmp_path)
    project.add_remote("origin", str(remote))
    project.push()

    clone = Project.init(tmp_path / "clone")
    clone.add_remote("origin", str(remote))
    clone.pull()
    # Both sides make a different version.
    model.by_type("IfcWall")[0].Name = "From source"
    changed = tmp_path / "source.ifc"
    model.write(str(changed))
    project.commit(changed, "Source change")
    project.push()

    other = Project.init(tmp_path / "other")
    other.add_remote("origin", str(remote))
    other.pull()
    other_model = Project.open(tmp_path / "other").export(tmp_path / "other-base.ifc")
    import ifcopenshell
    f = ifcopenshell.open(str(other_model))
    f.by_type("IfcWall")[0].Name = "From other"
    changed = tmp_path / "other.ifc"
    f.write(str(changed))
    other.commit(changed, "Other change")
    with pytest.raises(KimbimError, match="diverged"):
        other.pull()


def test_remote_management(tmp_path):
    project, _, _ = make_project(tmp_path)
    assert project.remotes() == []
    project.add_remote("origin", "https://example.invalid/repo.git")
    assert [r["name"] for r in project.remotes()] == ["origin"]
    project.remove_remote("origin")
    assert project.remotes() == []
    with pytest.raises(KimbimError):
        project.add_remote("", "x")
