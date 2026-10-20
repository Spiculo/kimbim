# SPDX-License-Identifier: GPL-3.0-or-later
from conftest import build_model

from kimbim.layout import blob_oid, key_to_path
from kimbim.nodeids import decompose_against_head
from kimbim.records import decompose


def as_head(records):
    by_oid = {blob_oid(v): v for v in records.values()}
    entries = {key_to_path(k): blob_oid(v) for k, v in records.items()}
    return entries, lambda oids: [by_oid[o] for o in oids]


def changed(a, b):
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def test_unchanged_model_reuses_every_id():
    f = build_model()
    base, _ = decompose(f)
    entries, read = as_head(base)
    again, _ = decompose_against_head(f, entries, read)
    assert again == base


def test_edited_shared_node_keeps_its_id():
    f = build_model(walls=3)
    base, _ = decompose(f)
    entries, read = as_head(base)
    ctx = [c for c in f.by_type("IfcGeometricRepresentationContext") if not c.is_a("IfcGeometricRepresentationSubContext")][0]
    ctx.Precision = 0.0001  # shared node referenced by every representation
    new, _ = decompose_against_head(f, entries, read)
    diff = changed(base, new)
    assert len(diff) == 1 and diff[0].startswith("n/")


def test_owner_history_timestamp_changes_one_record():
    # Spike S3: with content-hash ids this rewrote every rooted record (3,897 of 9,996 on Duplex).
    # Like a Revit export: every rooted entity shares ONE IfcOwnerHistory.
    f = build_model(schema="IFC2X3", walls=3)
    shared = f.by_type("IfcOwnerHistory")[0]
    for r in f.by_type("IfcRoot"):
        r.OwnerHistory = shared
    for oh in f.by_type("IfcOwnerHistory"):
        if oh != shared:
            f.remove(oh)
    base, _ = decompose(f)
    entries, read = as_head(base)
    shared.LastModifiedDate = 1790000000
    shared.ChangeAction = "MODIFIED"
    new, _ = decompose_against_head(f, entries, read)
    diff = changed(base, new)
    assert len(diff) == 1 and diff[0].startswith("n/")


def test_renaming_a_wall_changes_only_that_wall():
    f = build_model(walls=2)
    base, _ = decompose(f)
    entries, read = as_head(base)
    f.by_type("IfcWall")[0].Name = "Renamed"
    new, _ = decompose_against_head(f, entries, read)
    assert changed(base, new) == [f"o/{f.by_type('IfcWall')[0].GlobalId}"]
