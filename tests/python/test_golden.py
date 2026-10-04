# SPDX-License-Identifier: GPL-3.0-or-later
"""Golden hashes from spikes S3/S4 (tests/golden). Needs `pixi run fetch-corpus`."""
import json
import pathlib

import blake3
import ifcopenshell
import pytest

from kimcad.records import body_text, compose, decompose, state_hash

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "corpus" / "files"
GOLDEN = json.loads((ROOT / "tests" / "golden" / "manifest-windows.json").read_text())
LARGE = 5_000_000  # bytes; larger files only run with -m "golden and slow"
def _case(rel):
    p = CORPUS / rel
    large = p.exists() and p.stat().st_size > LARGE
    return pytest.param(rel, marks=[pytest.mark.slow] if large else [], id=rel)


CASES = [_case(k) for k, v in sorted(GOLDEN.items()) if v[0]]


@pytest.mark.golden
@pytest.mark.parametrize("rel", CASES)
def test_matches_spike_golden_hashes(rel, tmp_path):
    path = CORPUS / rel
    if not path.exists():
        pytest.skip("corpus not downloaded (pixi run fetch-corpus)")
    want_state, want_export = GOLDEN[rel]
    recs, _ = decompose(ifcopenshell.open(str(path)), format_tag="kimcad-spike/1")
    assert state_hash(recs) == want_state
    out = tmp_path / "b.ifc"
    compose(recs).write(str(out))
    assert blake3.blake3(body_text(out).encode()).hexdigest()[:32] == want_export
