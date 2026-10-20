# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 2: the .kim container (a zip of the project folder)."""
import json
import os
import zipfile

import pytest

from kimbim import kimfile as K


def project_folder(root):
    (root / ".git" / "objects" / "pack").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (root / ".git" / "objects" / "pack" / "pack-1.pack").write_bytes(b"PACK" + bytes(100))
    (root / ".kimbim" / "cache").mkdir(parents=True)
    (root / ".kimbim" / "cache" / "big.bin").write_bytes(bytes(1000))
    (root / ".kimbim" / "working.ifc").write_text("ISO-10303-21;\n")
    (root / ".kimbim" / "settings.json").write_text("{}\n")
    (root / ".kimbim" / "lock").write_text("{}")
    return root


def test_pack_and_unpack_round_trip(tmp_path):
    src = project_folder(tmp_path / "src")
    kim = tmp_path / "Casa ñ.kim"
    K.pack(src, kim)
    with zipfile.ZipFile(kim) as z:
        names = set(z.namelist())
        assert z.getinfo(".git/objects/pack/pack-1.pack").compress_type == zipfile.ZIP_STORED
        assert z.getinfo(".kimbim/working.ifc").compress_type == zipfile.ZIP_DEFLATED
    assert ".kimbim/cache/big.bin" not in names and ".kimbim/lock" not in names
    manifest = K.unpack(kim, tmp_path / "out")
    assert manifest["format"] == "kim" and manifest["version"] == 1 and manifest["kind"] == "project"
    assert (tmp_path / "out" / ".kimbim" / "working.ifc").read_text() == "ISO-10303-21;\n"
    assert (tmp_path / "out" / ".git" / "HEAD").exists()
    assert not (tmp_path / "out" / K.MANIFEST).exists()  # the manifest describes the file, not the folder


def test_a_failed_save_leaves_the_old_file(tmp_path, monkeypatch):
    src = project_folder(tmp_path / "src")
    kim = tmp_path / "a.kim"
    K.pack(src, kim)
    before = kim.read_bytes()
    (src / ".kimbim" / "working.ifc").write_text("changed")
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


@pytest.mark.parametrize("name", ["../evil.txt", "/abs.txt", "C:/x.txt", ".kimbim/../../evil.txt"])
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
    with pytest.raises(K.KimError, match="not a KimBim file"):
        K.read_manifest(junk)
    nomani = tmp_path / "nomani.kim"
    with zipfile.ZipFile(nomani, "w") as z:
        z.writestr("x", "y")
    with pytest.raises(K.KimError, match="not a KimBim file"):
        K.read_manifest(nomani)
    newer = tmp_path / "newer.kim"
    with zipfile.ZipFile(newer, "w") as z:
        z.writestr(K.MANIFEST, json.dumps({"format": "kim", "version": 99, "kind": "project"}))
    with pytest.raises(K.KimError, match="newer KimBim"):
        K.unpack(newer, tmp_path / "o")
    assert junk.read_bytes() == b"not a zip"


def test_path_hash_is_stable_and_case_insensitive_on_windows(tmp_path):
    a = K.path_hash(tmp_path / "A.kim")
    assert len(a) == 16 and a == K.path_hash(str(tmp_path / "A.kim"))
    if os.name == "nt":
        assert a == K.path_hash(str(tmp_path / "a.KIM"))


def test_a_free_file_is_locked_and_released(tmp_path):
    lock = K.lock_path(tmp_path / "a.kim")
    assert lock.name == "a.kim.lock"
    assert K.acquire(lock) is None
    held = json.loads(lock.read_text())
    assert held["pid"] == os.getpid() and held["machine"] and held["user"]
    K.release(lock)
    assert not lock.exists()


def test_someone_elses_lock_is_reported(tmp_path):
    lock = tmp_path / "a.kim.lock"
    lock.write_text(json.dumps({"user": "Ana", "machine": "OTHER-PC", "pid": 1, "since": "2026-10-08T10:42"}))
    holder = K.acquire(lock)
    assert holder["user"] == "Ana" and holder["machine"] == "OTHER-PC"
    K.release(lock)  # not ours: left alone
    assert lock.exists()


def test_our_own_lock_from_a_crash_is_taken_over(tmp_path):
    lock = tmp_path / "a.kim.lock"
    dead = 999_999_999
    assert not K.pid_alive(dead)
    lock.write_text(json.dumps({**K.me(), "pid": dead}))
    assert K.acquire(lock) is None
    assert json.loads(lock.read_text())["pid"] == os.getpid()


def test_a_second_window_of_ours_does_not_take_the_lock(tmp_path):
    import subprocess
    import sys

    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        lock = tmp_path / "a.kim.lock"
        lock.write_text(json.dumps({**K.me(), "pid": other.pid}))
        holder = K.acquire(lock)
        assert holder is not None and holder["pid"] == other.pid
    finally:
        other.kill()


def test_a_garbled_lock_counts_as_free(tmp_path):
    lock = tmp_path / "a.kim.lock"
    lock.write_text("{{{")
    assert K.acquire(lock) is None
