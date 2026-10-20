# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from kimbim import _core


def test_roundtrip_through_rust(tmp_path):
    repo = _core.Repo.init(str(tmp_path))
    assert repo.head() is None
    c1 = repo.commit({"objects/ab/W.json": b'{"a":1}', "kimbim.json": b"{}"}, "first", "T", "t@example.org", 1790000000)
    entries = repo.tree_entries("HEAD")
    assert sorted(entries) == ["kimbim.json", "objects/ab/W.json"]
    assert repo.read_blobs([entries["objects/ab/W.json"]]) == [b'{"a":1}']
    c2 = repo.commit({"kimbim.json": None}, "second", "T", "t@example.org", 1790000001)
    log = repo.log("HEAD", 10)
    assert [c.id for c in log] == [c2, c1]
    assert log[0].parents == [c1]
    assert log[1].message.strip() == "first"


def test_errors_are_repo_errors(tmp_path):
    with pytest.raises(_core.RepoError, match="not a KimBim project"):
        _core.Repo.open(str(tmp_path))
    repo = _core.Repo.init(str(tmp_path))
    with pytest.raises(_core.RepoError, match="unknown revision"):
        repo.resolve("nope")
