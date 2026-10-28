# SPDX-License-Identifier: GPL-3.0-or-later
"""R4 reconciliation: re-import an IFC whose GlobalIds changed and keep the objects' identities."""
import pathlib
import uuid

import ifcopenshell
import ifcopenshell.guid
import pytest

from kimbim.project import Project
from kimbim.testing import build_model

ROOT = pathlib.Path(__file__).resolve().parents[2]
DUPLEX = (ROOT / "tests" / "corpus" / "files" / "community" / "IFC 2.3.0.1 (IFC 2x3)" /
          "Duplex Apartment" / "Duplex_A_20110907.ifc")


def regenerate_global_ids(model):
    """Every rooted object gets a fresh GlobalId, as another tool's re-export may do."""
    seen = set()
    for entity in model.by_type("IfcRoot"):
        guid = ifcopenshell.guid.compress(uuid.uuid4().hex)
        while guid in seen:
            guid = ifcopenshell.guid.compress(uuid.uuid4().hex)
        seen.add(guid)
        entity.GlobalId = guid


def walls(model):
    return [e for e in model.by_type("IfcProduct") if e.is_a("IfcWall")]


def test_tag_matches_keep_elements_and_their_history(tmp_path):
    model = build_model(walls=4)
    for i, wall in enumerate(walls(model)):
        wall.Tag = f"W{i}"
    first = tmp_path / "first.ifc"
    model.write(str(first))
    project = Project.init(tmp_path / "project")
    project.commit(first, "Initial import")

    again = ifcopenshell.open(str(first))
    regenerate_global_ids(again)
    changed = tmp_path / "changed.ifc"
    again.write(str(changed))

    report = project.import_ifc(changed, "Re-import", accept_heuristic=True)
    assert report["counts"]["globalid"] == 0
    assert report["counts"]["tag"] == 4
    assert report["counts"]["changed"] >= 4
    assert report["counts"]["new"] == 0 and report["counts"]["deleted"] == 0
    assert report["identity_rate"] == 1.0

    # The walls kept their record keys, so Compare sees no wall added or removed.
    changes = project.diff("HEAD^", "HEAD")
    assert not [c for c in changes.added if c.ifc_type == "IfcWall"]
    assert not [c for c in changes.removed if c.ifc_type == "IfcWall"]


def test_heuristic_matches_need_acceptance(tmp_path):
    model = build_model(walls=3)
    first = tmp_path / "first.ifc"
    model.write(str(first))
    project = Project.init(tmp_path / "project")
    project.commit(first, "Initial import")
    head = project.repo.head()

    again = ifcopenshell.open(str(first))
    regenerate_global_ids(again)
    changed = tmp_path / "changed.ifc"
    again.write(str(changed))

    review = project.import_ifc(changed, "Review", accept_heuristic=False, dry_run=True)
    assert project.repo.head() == head  # a dry run writes nothing
    assert review["counts"]["heuristic_review"] >= 3
    assert review["counts"]["new"] >= 4 and review["counts"]["deleted"] >= 4

    applied = project.import_ifc(changed, "Re-import", accept_heuristic=True)
    assert applied["counts"]["heuristic"] >= 3
    assert applied["counts"]["new"] == 0 and applied["counts"]["deleted"] == 0
    assert applied["identity_rate"] == 1.0


@pytest.mark.slow
def test_the_duplex_reimport_keeps_most_identities(tmp_path):
    """The R4 exit on a real Revit export: regenerate every GlobalId and re-import it."""
    if not DUPLEX.exists():
        pytest.skip("corpus not downloaded (pixi run fetch-corpus)")
    project = Project.init(tmp_path / "duplex")
    project.commit(DUPLEX, "Initial import")
    again = ifcopenshell.open(str(DUPLEX))
    regenerate_global_ids(again)
    changed = tmp_path / "duplex-reidentified.ifc"
    again.write(str(changed))

    report = project.import_ifc(changed, "Re-import the revised model", accept_heuristic=True)
    assert report["identity_rate"] > 0.95, report["counts"]
    assert report["counts"]["tag"] > 0
    assert report["counts"]["heuristic"] > 0
