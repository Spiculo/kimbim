# SPDX-License-Identifier: GPL-3.0-or-later
"""D99 port (doc 16 §8): every bundled .kimobj builds the same geometry and plan symbol as the
Python object it replaces, at its defaults and at two other value sets (tests/golden/library_objects.json)."""
import json
import pathlib

import pytest

from kimbim import objects

ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT / "tests/golden/library_objects.json").read_text(encoding="utf-8"))
BUNDLED = ROOT / "python/kimbim/bundled_objects"


def cases():
    return [(key, name) for key in sorted(GOLDEN) for name in sorted(GOLDEN[key])]


@pytest.mark.parametrize("key, name", cases())
def test_port_matches_the_python_object(key, name):
    want = GOLDEN[key][name]
    d = objects.load_file(str(BUNDLED / f"{key}.kimobj"), "bundled")
    assert d.key == key
    values = d.values(want["values"])
    for k, v in want["values"].items():
        assert values[k] == pytest.approx(v), k
    got = d.shape(values).metrics()
    assert got["bbox"] == pytest.approx(want["bbox"], abs=1e-3)
    assert got["volume"] == pytest.approx(want["volume"], rel=5e-3)
    assert got["symbol_bbox"] == pytest.approx(want["symbol_bbox"], abs=1e-3)
    assert got["symbol_length"] == pytest.approx(want["symbol_length"], rel=5e-3)


def test_every_bundled_file_is_a_golden_object():
    assert sorted(p.stem for p in BUNDLED.glob("*.kimobj")) == sorted(GOLDEN)
