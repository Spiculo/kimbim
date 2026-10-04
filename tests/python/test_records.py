# SPDX-License-Identifier: GPL-3.0-or-later
import json

import ifcopenshell
import ifcopenshell.api.pset
from conftest import build_model
from semantic import compare

from kimcad.records import FORMAT, body_text, compose, decompose


def roundtrip(f, tmp_path, name="b.ifc"):
    r1, _ = decompose(f)
    b = compose(r1)
    pb = tmp_path / name
    b.write(str(pb))
    b2 = ifcopenshell.open(str(pb))
    r2, _ = decompose(b2)
    return r1, r2, b2, pb


def test_fixed_point_and_lossless(model, tmp_path):
    r1, r2, b2, _ = roundtrip(model, tmp_path)
    assert r1 == r2
    assert compare(model, b2) == []
    assert json.loads(r1["meta"]) == {"k": FORMAT, "schema": "IFC4"}


def test_export_is_deterministic(model, tmp_path):
    r1, _ = decompose(model)
    compose(r1).write(str(tmp_path / "x.ifc"))
    compose(r1).write(str(tmp_path / "y.ifc"))
    assert body_text(tmp_path / "x.ifc") == body_text(tmp_path / "y.ifc")


def test_storey_placement_is_anchored_not_copied(model):
    recs, _ = decompose(model)
    walls = [json.loads(v) for k, v in recs.items() if k.startswith("o/") and json.loads(v)["t"] == "IfcWall"]
    rel_to = walls[0]["a"]["ObjectPlacement"]["a"]["PlacementRelTo"]
    assert "@a" in rel_to and rel_to["@a"].endswith("/ObjectPlacement")


def test_loose_duplicates_keep_multiplicity(model, tmp_path):
    for _ in range(2):
        model.createIfcCartesianPoint((9.0, 9.0, 9.0))
    recs, _ = decompose(model)
    loose = [json.loads(v) for k, v in recs.items() if k.startswith("l/") and json.loads(v)["e"]["t"] == "IfcCartesianPoint"]
    assert [x["n"] for x in loose] == [2]
    _, _, b2, _ = roundtrip(model, tmp_path)
    assert len([p for p in b2.by_type("IfcCartesianPoint") if b2.get_total_inverses(p) == 0]) == 2


def test_strings_are_not_normalized(model, tmp_path):
    decomposed = "Ñandú"  # 'Ñandú' with a combining tilde (NFD) for the Ñ
    model.by_type("IfcWall")[0].Name = decomposed
    _, _, b2, _ = roundtrip(model, tmp_path)
    assert decomposed in [w.Name for w in b2.by_type("IfcWall")]


def test_integer_and_real_stay_distinct(model, tmp_path):
    w = model.by_type("IfcWall")[0]
    pset = ifcopenshell.api.pset.add_pset(model, product=w, name="KIMCAD_Test")
    ifcopenshell.api.pset.edit_pset(
        model, pset=pset, properties={"I": model.createIfcInteger(1), "R": model.createIfcReal(1.0)}
    )
    _, _, b2, _ = roundtrip(model, tmp_path)
    vals = {p.Name: p.NominalValue for p in b2.by_type("IfcPropertySingleValue") if p.Name in ("I", "R")}
    assert vals["I"].is_a() == "IfcInteger" and vals["R"].is_a() == "IfcReal"


def test_duplicate_globalids_get_ordinals(model, tmp_path):
    w = model.by_type("IfcWall")[0]
    model.createIfcWall(w.GlobalId, None, "Dup")
    recs, d = decompose(model)
    assert f"o/{w.GlobalId}" in recs and f"o/{w.GlobalId}~1" in recs
    assert any("duplicate GlobalId" in i for i in d.issues)
    r1, r2, _, _ = roundtrip(model, tmp_path)
    assert r1 == r2


def test_ifc2x3_and_ifc4x3_models_roundtrip(tmp_path):
    for schema in ("IFC2X3", "IFC4X3_ADD2"):
        f = build_model(schema=schema, walls=1)
        r1, r2, b2, _ = roundtrip(f, tmp_path, name=f"{schema}.ifc")
        assert r1 == r2 and compare(f, b2) == []
