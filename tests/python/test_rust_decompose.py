# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 3 of the Rust decomposer (docs/19): the dump-driven decomposer must produce the exact
record dict and state hash of ``records.decompose`` before ``Project._decompose_file`` switches.

The tests skip when the C++ bridge has not been built; the dedicated ``ifcdump-check`` CI job always
builds it.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import ifcopenshell
import ifcopenshell.api.pset
import pytest
from conftest import build_model

from kimbim import records
from kimbim.layout import blob_oid, key_to_path
from kimbim.nodeids import decompose_against_head, decompose_dump_against_head

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXE = ROOT / "build" / "ifcdump" / ("ifcdump.exe" if sys.platform == "win32" else "ifcdump")


def dump_of(path):
    if not EXE.exists():
        pytest.skip(f"{EXE} is missing; run `pixi run ifcdump-build` first")
    result = subprocess.run(
        [str(EXE), str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def as_head(recs):
    by_oid = {blob_oid(v): v for v in recs.values()}
    entries = {key_to_path(k): blob_oid(v) for k, v in recs.items()}
    return entries, lambda oids: [by_oid[o] for o in oids]


def check_model(model, tmp_path, name="model.ifc"):
    path = tmp_path / name
    model.write(str(path))
    dump = dump_of(path)
    python_records, _ = records.decompose(ifcopenshell.open(str(path)))
    rust_records = records.decompose_dump(dump)
    assert rust_records == python_records
    assert records.state_hash(rust_records) == records.state_hash(python_records)
    return rust_records, dump


def test_rust_decomposer_matches_records(tmp_path):
    check_model(build_model(walls=3), tmp_path)


def test_rust_decomposer_keeps_typed_values(tmp_path):
    model = build_model(walls=2)
    wall = model.by_type("IfcWall")[0]
    pset = ifcopenshell.api.pset.add_pset(model, product=wall, name="KIMBIM_Test")
    ifcopenshell.api.pset.edit_pset(
        model,
        pset=pset,
        properties={"I": model.createIfcInteger(1), "R": model.createIfcReal(1.0), "L": model.createIfcLabel("x")},
    )
    check_model(model, tmp_path, "typed.ifc")


def test_rust_decomposer_keeps_duplicate_globalids_and_loose_records(tmp_path):
    model = build_model(walls=2)
    wall = model.by_type("IfcWall")[0]
    model.createIfcWall(wall.GlobalId, None, "Dup")
    for _ in range(2):
        model.createIfcCartesianPoint((9.0, 9.0, 9.0))
    recs, _ = check_model(model, tmp_path, "dups.ifc")
    assert f"o/{wall.GlobalId}" in recs and f"o/{wall.GlobalId}~1" in recs
    assert any(k.startswith("l/") for k in recs)


def test_rust_decomposer_reuses_stable_node_ids(tmp_path):
    model = build_model(walls=3)
    path = tmp_path / "stable.ifc"
    model.write(str(path))
    dump = dump_of(path)
    base, _ = records.decompose(ifcopenshell.open(str(path)))
    entries, read = as_head(base)

    # Unchanged model: every node id survives.
    rust_again, _ = decompose_dump_against_head(dump, entries, read)
    assert rust_again == base

    # One edited shared context: the Rust loop must force the old id exactly like the Python one.
    context = [
        c
        for c in model.by_type("IfcGeometricRepresentationContext")
        if not c.is_a("IfcGeometricRepresentationSubContext")
    ][0]
    context.Precision = 0.0001
    model.write(str(path))
    dump = dump_of(path)
    python_new, _ = decompose_against_head(model, entries, read)
    rust_new, _ = decompose_dump_against_head(dump, entries, read)
    assert rust_new == python_new
    changed = sorted(k for k in set(base) | set(rust_new) if base.get(k) != rust_new.get(k))
    assert len(changed) == 1 and changed[0].startswith("n/")
