# SPDX-License-Identifier: GPL-3.0-or-later
import subprocess

import pytest

from kimcad.layout import META_PATH, blob_oid, key_to_path, path_to_key


@pytest.mark.parametrize(
    "key", ["o/2O2Fr$t4X7Zf8NOew3FLOH", "o/2O2Fr$t4X7Zf8NOew3FLOH~1", "n/0123abcd", "l/ffee00", "meta"]
)
def test_key_path_roundtrip(key):
    p = key_to_path(key)
    assert path_to_key(p) == key
    assert not p.startswith("/") and ".." not in p


def test_meta_path():
    assert key_to_path("meta") == META_PATH == "kimcad.json"


def test_unknown_keys_and_paths_are_rejected():
    with pytest.raises(ValueError):
        key_to_path("x/abc")
    with pytest.raises(ValueError):
        path_to_key("other/ab/abc.json")


def test_blob_oid_matches_git():
    data = '{"t":"IfcWall","ñ":1}'.encode()
    out = subprocess.run(["git", "hash-object", "--stdin"], input=data, capture_output=True, check=True)
    assert blob_oid(data) == out.stdout.decode().strip()
