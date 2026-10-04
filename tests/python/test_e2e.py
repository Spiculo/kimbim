# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice 1 exit test on a real Revit export (needs the corpus: pixi run fetch-corpus)."""
import json
import pathlib

import blake3
import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.util.element
import pytest

from kimcad.project import Project
from kimcad.records import body_text

ROOT = pathlib.Path(__file__).resolve().parents[2]
REL = "community/IFC 2.3.0.1 (IFC 2x3)/Duplex Apartment/Duplex_A_20110907.ifc"
DUPLEX = ROOT / "tests" / "corpus" / "files" / REL
GOLDEN = json.loads((ROOT / "tests" / "golden" / "manifest-windows.json").read_text())


@pytest.mark.golden
def test_duplex_property_edit_roundtrip(tmp_path):
    if not DUPLEX.exists():
        pytest.skip("corpus not downloaded")
    proj = Project.init(tmp_path / "duplex")
    proj.commit(DUPLEX, "import Duplex", author=("T", "t@e.org"), time=1)
    v1 = proj.export(tmp_path / "v1.ifc")
    assert blake3.blake3(body_text(v1).encode()).hexdigest()[:32] == GOLDEN[REL][1]

    f = ifcopenshell.open(str(DUPLEX))
    walls = f.by_type("IfcWall")
    wall = walls[len(walls) // 2]
    pset = ifcopenshell.util.element.get_pset(wall, "Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=f.by_id(pset["id"]), properties={"FireRating": "EI60-KIMCAD"})
    edited = tmp_path / "edited.ifc"
    f.write(str(edited))
    _, changes = proj.commit(edited, "FireRating EI60", author=("T", "t@e.org"), time=2)
    assert 1 <= len(changes.items) <= 3, changes.items
    assert any(c.ifc_type == "IfcPropertySet" for c in changes.modified)
    assert not changes.removed

    v2 = proj.export(tmp_path / "v2.ifc")
    assert "EI60-KIMCAD" in body_text(v2)
    assert not proj.status(v2)
