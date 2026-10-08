# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 2: the .kim container (a zip of the project folder)."""
import json
import os
import zipfile

import pytest

from kimcad import kimfile as K


def project_folder(root):
    (root / ".git" / "objects" / "pack").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (root / ".git" / "objects" / "pack" / "pack-1.pack").write_bytes(b"PACK" + bytes(100))
    (root / ".kimcad" / "cache").mkdir(parents=True)
    (root / ".kimcad" / "cache" / "big.bin").write_bytes(bytes(1000))
    (root / ".kimcad" / "working.ifc").write_text("ISO-10303-21;\n")
    (root / ".kimcad" / "settings.json").write_text("{}\n")
    (root / ".kimcad" / "lock").write_text("{}")
    return root


def test_pack_and_unpack_round_trip(tmp_path):
    src = project_folder(tmp_path / "src")
    kim = tmp_path / "Casa ñ.kim"
    K.pack(src, kim)
    with zipfile.ZipFile(kim) as z:
        names = set(z.namelist())
        assert z.getinfo(".git/objects/pack/pack-1.pack").compress_type == zipfile.ZIP_STORED
        assert z.getinfo(".kimcad/working.ifc").compress_type == zipfile.ZIP_DEFLATED
    assert ".kimcad/cache/big.bin" not in names and ".kimcad/lock" not in names
    manifest = K.unpack(kim, tmp_path / "out")
    assert manifest["format"] == "kim" and manifest["version"] == 1 and manifest["kind"] == "project"
    assert (tmp_path / "out" / ".kimcad" / "working.ifc").read_text() == "ISO-10303-21;\n"
    assert (tmp_path / "out" / ".git" / "HEAD").exists()
    assert not (tmp_path / "out" / K.MANIFEST).exists()  # the manifest describes the file, not the folder


def test_a_failed_save_leaves_the_old_file(tmp_path, monkeypatch):
    src = project_folder(tmp_path / "src")
    kim = tmp_path / "a.kim"
    K.pack(src, kim)
    before = kim.read_bytes()
    (src / ".kimcad" / "working.ifc").write_text("changed")
    monkeypatch.setattr(K, "_write_entries", lambda *a, **k: (_ for _ in ()).throw(OSError(28, "No space left")))
    with pytest.raises(K.KimError, match="No space"):
        K.pack(src, kim)
    assert kim.read_bytes() == before


def test_a_busy_target_is_retried_then_reported(tmp_path, monkeypatch):
    src = project_folder(tmp_path / "src")
    kim = tmp_path / "a.kim"
    K.pack(src, kim)
    before = kim.read_bytes()
    calls = []

    def busy(a, b):
        calls.append(1)
        raise PermissionError(13, "in use by another program")

    monkeypatch.setattr(K.os, "replace", busy)
    monkeypatch.setattr(K, "REPLACE_WAIT", 0.0)
    with pytest.raises(K.KimError, match="in use"):
        K.pack(src, kim)
    assert len(calls) == K.REPLACE_TRIES and kim.read_bytes() == before


@pytest.mark.parametrize("name", ["../evil.txt", "/abs.txt", "C:/x.txt", ".kimcad/../../evil.txt"])
def test_entries_outside_the_folder_are_refused(tmp_path, name):
    kim = tmp_path / "bad.kim"
    with zipfile.ZipFile(kim, "w") as z:
        z.writestr(K.MANIFEST, json.dumps({"format": "kim", "version": 1, "kind": "project"}))
        z.writestr(name, "x")
    with pytest.raises(K.KimError, match="unsafe"):
        K.unpack(kim, tmp_path / "out" / "in")
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "out" / "evil.txt").exists()


def test_damaged_unknown_and_newer_files_are_refused_untouched(tmp_path):
    junk = tmp_path / "junk.kim"
    junk.write_bytes(b"not a zip")
    with pytest.raises(K.KimError, match="not a KIMCAD file"):
        K.read_manifest(junk)
    nomani = tmp_path / "nomani.kim"
    with zipfile.ZipFile(nomani, "w") as z:
        z.writestr("x", "y")
    with pytest.raises(K.KimError, match="not a KIMCAD file"):
        K.read_manifest(nomani)
    newer = tmp_path / "newer.kim"
    with zipfile.ZipFile(newer, "w") as z:
        z.writestr(K.MANIFEST, json.dumps({"format": "kim", "version": 99, "kind": "project"}))
    with pytest.raises(K.KimError, match="newer KIMCAD"):
        K.unpack(newer, tmp_path / "o")
    assert junk.read_bytes() == b"not a zip"


def test_path_hash_is_stable_and_case_insensitive_on_windows(tmp_path):
    a = K.path_hash(tmp_path / "A.kim")
    assert len(a) == 16 and a == K.path_hash(str(tmp_path / "A.kim"))
    if os.name == "nt":
        assert a == K.path_hash(str(tmp_path / "a.KIM"))
