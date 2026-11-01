# SPDX-License-Identifier: GPL-3.0-or-later
"""The working-decomposition cache: a second status/commit of the same IFC does not decompose again,
a changed file does, and a corrupt cache falls back to a real decomposition."""
import pathlib

import ifcopenshell

import kimbim.project as project
from kimbim.project import Project
from kimbim.testing import build_model


def _write(path, walls=2):
    build_model(walls=walls).write(str(path))
    return path


def test_second_status_uses_the_cache(tmp_path, monkeypatch):
    ifc = _write(tmp_path / "model.ifc")
    p = Project.init(tmp_path / "project")
    calls = []

    original = project.decompose_against_head
    original_dump = project.decompose_dump_against_head

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    def counted_dump(*args, **kwargs):
        calls.append(1)
        return original_dump(*args, **kwargs)

    monkeypatch.setattr(project, "decompose_against_head", counted)
    monkeypatch.setattr(project, "decompose_dump_against_head", counted_dump)

    first = p.status(ifc)
    assert calls == [1]
    cache = list((p.work / ".kimbim" / "cache" / "decompose").glob("*.json"))
    assert len(cache) == 1
    second = p.status(ifc)
    assert calls == [1], "the second status used the on-disk decomposition"
    assert [(c.kind, c.key) for c in second.items] == [(c.kind, c.key) for c in first.items]


def test_a_changed_file_is_decomposed_again(tmp_path, monkeypatch):
    ifc = _write(tmp_path / "model.ifc")
    p = Project.init(tmp_path / "project")
    calls = []
    original = project.decompose_against_head
    original_dump = project.decompose_dump_against_head

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    def counted_dump(*args, **kwargs):
        calls.append(1)
        return original_dump(*args, **kwargs)

    monkeypatch.setattr(project, "decompose_against_head", counted)
    monkeypatch.setattr(project, "decompose_dump_against_head", counted_dump)
    p.status(ifc)
    assert len(calls) == 1
    _write(ifc, walls=3)
    p.status(ifc)
    assert len(calls) == 2, "a different file must not reuse the old records"


def test_a_corrupt_cache_falls_back(tmp_path):
    ifc = _write(tmp_path / "model.ifc")
    p = Project.init(tmp_path / "project")
    p.status(ifc)
    cache = next((p.work / ".kimbim" / "cache" / "decompose").glob("*.json"))
    cache.write_text("{not json", encoding="utf-8")
    # No monkeypatch: the fallback has to run the real decomposer and still return a status.
    assert p.status(ifc) is not None
    assert cache.read_text(encoding="utf-8").startswith("{")
    assert ifcopenshell.open(str(ifc)).by_type("IfcWall")
