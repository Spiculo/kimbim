# SPDX-License-Identifier: GPL-3.0-or-later
"""Stable ids for shared nodes across versions (docs/02 rule 5, spike S3).

A shared node keeps its id when its content is unchanged (same Git blob) or when it is the only
changed node of its IFC type (e.g. IfcOwnerHistory after a timestamp update). New nodes get their
content hash, re-hashed deterministically if that collides with an existing id.
"""
import json
from typing import Callable

from .layout import blob_oid, path_to_key
from .records import FORMAT, decompose, h


def decompose_against_head(
    f,
    head_entries: dict[str, str],
    read_blobs: Callable[[list[str]], list[bytes]],
    *,
    format_tag: str = FORMAT,
    max_rounds: int = 5,
):
    head_nodes = {path_to_key(p)[2:]: oid for p, oid in head_entries.items() if p.startswith("nodes/")}
    id_by_oid = {oid: nid for nid, oid in head_nodes.items()}
    taken = set(head_nodes)
    forced: dict[str, str] = {}  # content hash of a changed node -> its old id

    def resolver(ifc_type: str, b: bytes):
        nid = id_by_oid.get(blob_oid(b))
        if nid:
            return nid
        fresh = h(b)
        if fresh in forced:
            return forced[fresh]
        while fresh in taken:  # never collide with an existing node id
            fresh = h((fresh + "~").encode())
        return fresh

    head_types: dict[str, str] = {}
    recs, d = decompose(f, format_tag=format_tag, resolve_node_id=resolver)
    for _ in range(max_rounds):
        new_ids = {k[2:] for k in recs if k.startswith("n/")}
        unmatched_old = sorted(taken - new_ids)
        unmatched_new = sorted(i for i in new_ids if i not in taken)
        if not unmatched_old or not unmatched_new:
            break
        need = [i for i in unmatched_old if i not in head_types]
        for nid, blob in zip(need, read_blobs([head_nodes[i] for i in need]) if need else []):
            head_types[nid] = json.loads(blob)["t"]
        old_by_type: dict[str, list[str]] = {}
        for i in unmatched_old:
            old_by_type.setdefault(head_types[i], []).append(i)
        new_by_type: dict[str, list[str]] = {}
        for i in unmatched_new:
            new_by_type.setdefault(json.loads(recs[f"n/{i}"])["t"], []).append(i)
        added = 0
        for t, olds in old_by_type.items():
            news = new_by_type.get(t, [])
            if len(olds) == 1 and len(news) == 1:
                content_hash = h(recs[f"n/{news[0]}"])
                if forced.get(content_hash) != olds[0]:
                    forced[content_hash] = olds[0]
                    added += 1
        if not added:
            break
        recs, d = decompose(f, format_tag=format_tag, resolve_node_id=resolver)
    return recs, d
