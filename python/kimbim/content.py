# SPDX-License-Identifier: GPL-3.0-or-later
"""What a record means, independent of how it is encoded (Task 11b).

kimbim.records stores a non-rooted value inline, anchored ({"@a"}) or as its own node ({"@n"})
depending on how many places refer to its content in the whole model. Editing one element can
therefore re-encode another one that did not change (a placement it shares becomes a node). Changes
are reported on content: a record's digest expands node and anchor references, so the same content
gives the same digest however it is stored, and a shared value edited in place changes every record
that uses it. The stored records are untouched (golden hashes pin them).

Two choices keep the digest about the model and not its bookkeeping:
- SET members are re-sorted by their digests (stored SETs are sorted by their encoded bytes, which
  re-encoding can reorder).
- OwnerHistory is left out: it is edit bookkeeping (merge treats it the same). A shared
  IfcOwnerHistory updated in place (an IFC2X3 timestamp) is not a change of every element, and one
  re-encoded because editing an element gave it a new owner history (IFC2X3, ifcopenshell.api)
  re-encodes every rooted record (seen on the Clinic: 41,068 records).
"""
from __future__ import annotations

import json
import re
from typing import Callable

from .records import Schema, agg_info, canon, h

# Byte patterns over records as records.canon writes them (sorted keys, no whitespace): a reference is
# exactly {"@n":"<id>"} or {"@a":"<GlobalId>/<Attr>"}; an inline entity starts {"a":.
_REF = re.compile(rb'(?<!"OwnerHistory":)\{"@([na])":"([^"]*)"\}')


def references(data: bytes) -> list[tuple[str, str]]:
    """The node ("n", id) and anchor ("a", "<GlobalId>/<Attr>") references in a record's bytes, but
    for its OwnerHistory (left out of content, see above)."""
    return [(k.decode(), v.decode()) for k, v in _REF.findall(data)]


def inline_owner_history(data: bytes) -> bool:
    """Whether a record holds its owner history inline (whose references are not content)."""
    return b'"OwnerHistory":{"a"' in data


def without_owner_history(v: dict) -> dict:
    """A decoded record without its OwnerHistory (for a quick equality test)."""
    if isinstance(v.get("a"), dict) and "OwnerHistory" in v["a"]:
        v = {**v, "a": {k: x for k, x in v["a"].items() if k != "OwnerHistory"}}
    return v


def ref_key(kind: str, ident: str) -> str:
    """The record that holds what a reference points at."""
    return f"n/{ident}" if kind == "n" else f"o/{ident.split('/', 1)[0]}"


class Contents:
    """Content digests of one record set (a version, or the working model), memoised.
    `get(key)` -> the record's canonical bytes, or None when the set has no such record.
    `owner_history`: keep OwnerHistory as stored (merge: a side's own history is a change it keeps)."""

    def __init__(self, get: Callable[[str], bytes | None], schema: Schema, owner_history: bool = False):
        self.get = get
        self.schema = schema
        self.owner_history = owner_history
        self._refs: dict[tuple[str, str], object] = {}
        self._types: dict[str, dict] = {}

    def record(self, key: str) -> str | None:
        """The digest of a record's content (None if absent)."""
        b = self.get(key)
        if b is None:
            return None
        v = json.loads(b)
        if key.startswith("l/"):
            return h(canon({"e": self.entity(v["e"]), "n": v["n"]}))
        if key == "meta" or "t" not in v:
            return h(b)
        return self.entity(v)["#"]

    def ref(self, kind: str, ident: str):
        """The expanded value a node or anchor reference stands for."""
        k = (kind, ident)
        if k not in self._refs:
            self._refs[k] = {"cycle": ident}  # never recurse forever through anchors (IFC values are acyclic)
            b = self.get(ref_key(kind, ident))
            if b is None:
                out = {"missing": ident}
            elif kind == "n":
                out = self.entity(json.loads(b))
            else:
                gid, attr = ident.split("/", 1)
                v = json.loads(b)
                out = self.value(v.get("a", {}).get(attr), self.attr_types(v["t"]).get(attr))
            self._refs[k] = out
        return self._refs[k]

    def entity(self, v) -> dict:
        types = self.attr_types(v["t"])
        a = {}
        for name, x in v.get("a", {}).items():
            if name != "OwnerHistory":
                a[name] = self.value(x, types.get(name))
            elif self.owner_history:
                a[name] = x
        return {"#": h(canon({"t": v["t"], "a": a}))}

    def value(self, v, t=None):
        if isinstance(v, dict):
            if "@n" in v:
                return self.ref("n", v["@n"])
            if "@a" in v:
                return self.ref("a", v["@a"])
            if "@o" in v:
                return v
            if "@t" in v:
                return {"@t": v["@t"], "v": self.value(v["v"], self._declared(v["@t"]))}
            if "t" in v:
                return self.entity(v)
            return v
        if isinstance(v, list):
            kind, el = agg_info(t) if t is not None else (None, None)
            items = [self.value(x, el) for x in v]
            if kind == "set":
                items.sort(key=canon)
            return items
        return v

    def attr_types(self, ifc_type: str) -> dict:
        """{attribute name: its schema type} of an entity type."""
        if ifc_type not in self._types:
            try:
                self._types[ifc_type] = {name: t for name, _i, t in self.schema.attrs(ifc_type)}
            except Exception:  # unknown type: every list keeps its order
                self._types[ifc_type] = {}
        return self._types[ifc_type]

    def _declared(self, type_name: str):
        try:
            d = self.schema.s.declaration_by_name(type_name).as_type_declaration()
            return d.declared_type() if d else None
        except Exception:
            return None


class Changed:
    """Which references stand for different content in two record sets (`a` before, `b` after),
    memoised. Records with identical bytes differ only through what they refer to, which is walked
    cheaply (no digests) where the bytes say enough."""

    def __init__(self, a: Contents, b: Contents):
        self.a, self.b = a, b
        self._memo: dict[tuple[str, str], bool] = {}

    def ref(self, kind: str, ident: str) -> bool:
        k = (kind, ident)
        if k not in self._memo:
            self._memo[k] = False  # never recurse forever through anchors (IFC values are acyclic)
            key = ref_key(kind, ident)
            da, db = self.a.get(key), self.b.get(key)
            if da is None or db is None:
                out = da is not db
            elif da == db and (kind == "n" or not references(da)):
                out = self.uses(da)  # same bytes: different exactly when a value it refers to is
            elif da == db and not self.uses(da):
                out = False  # an anchor in a record whose references are all unchanged
            else:
                out = self.a.ref(kind, ident) != self.b.ref(kind, ident)
            self._memo[k] = out
        return self._memo[k]

    def uses(self, data: bytes) -> bool:
        """Whether a value referred to from these bytes differs."""
        return any(self.ref(*r) for r in references(data))

    def record(self, key: str, data: bytes) -> bool:
        """Whether a record with the same bytes `data` in both sets has different content."""
        if not self.uses(data):
            return False
        return not inline_owner_history(data) or self.a.record(key) != self.b.record(key)


def schema_of(meta: bytes | None) -> Schema:
    return Schema(json.loads(meta)["schema"] if meta else "IFC4")
