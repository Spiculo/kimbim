# SPDX-License-Identifier: GPL-3.0-or-later
"""The Rust canonical encoder must produce byte-identical bytes to ``records.canon``.

This is stage 2 of the Rust decomposer (docs/19): before the decomposer writes records, its JSON
bytes have to match the Python reference exactly, including float repr, sorted keys, SET ordering
and string escaping.
"""
import json
import pathlib

import pytest

from kimbim import _core, records
from kimbim.testing import build_model


def _model(tmp_path):
    path = tmp_path / "model.ifc"
    build_model(walls=3).write(str(path))
    return path


def test_core_canon_matches_records_canon_on_values():
    values = [
        {"b": 1.0, "a": [1, 2.5, -0.0, 1e-05], "s": "hello\n\"x\"", "t": True, "n": None},
        {"z": {"y": [3, 4]}, "a": 0.1},
        [1, 2, 3.0, "x"],
        {"empty": {}, "list": []},
    ]
    for value in values:
        assert _core.canon(value) == records.canon(value)


def test_core_canon_matches_every_decomposed_record(tmp_path):
    import ifcopenshell

    model = ifcopenshell.open(str(_model(tmp_path)))
    records_map, _ = records.decompose(model)
    assert records_map
    for key, record in records_map.items():
        value = json.loads(record)
        assert _core.canon(value) == record, key
