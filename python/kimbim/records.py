# SPDX-License-Identifier: GPL-3.0-or-later
"""Canonical records: decompose an IFC model into KimBim records and compose it back.

Specification: docs/02-data-model-and-format.md (validated by spike S3, docs/11). Record kinds:

  o/<GlobalId>   rooted entity (IfcRoot). Owns its non-rooted subgraph inline.
  n/<id>         shared non-rooted entity with a STABLE id: the content hash at first import,
                 kept across versions (see kimbim.nodeids) when edited in place.
  l/<blake3>     loose non-rooted value (no referrers, e.g. IfcStyledItem), with multiplicity.

Non-rooted entities are classified as
  Classification is by CONTENT CLASS (identical non-rooted entities are hash-consed first),
  counting distinct (parent class, attribute, index) reference edges:
  INLINE    exactly one edge -> nested inside the referrer
  ANCHORED  several references, but exactly one comes from a rooted entity's
            single-valued attribute -> stored inline in that rooted record,
            others refer to it by owner path {"@a": "<GlobalId>/<Attr>"}
  NODE      anything else (shared without a single rooted owner, or loose with
            no referrer, e.g. IfcStyledItem) -> own record n/<id> (or l/<hash> if loose)

Value encoding (canonical JSON, sorted keys, no whitespace):
  entity (inline)   {"t": "IfcX", "a": {"Attr": value, ...}}   unset attrs omitted
  rooted reference  {"@o": "<GlobalId>"}
  node reference    {"@n": "<id>"}
  anchor reference  {"@a": "<GlobalId>/<Attr>"}
  typed value       {"@t": "IfcLabel", "v": value}
  SET aggregates    sorted by canonical bytes of members; LIST/ARRAY/BAG keep order
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
from typing import Callable

import blake3
import ifcopenshell
import ifcopenshell.ifcopenshell_wrapper as W

FORMAT = "kimbim/1"
INLINE, ANCHORED, NODE = "inline", "anchored", "node"


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def h(b: bytes) -> str:
    return blake3.blake3(b).hexdigest()[:32]


def norm_float(x: float) -> float:
    if math.isnan(x) or math.isinf(x):
        raise ValueError("NaN/Inf not allowed in IFC")
    return 0.0 if x == 0.0 else x  # -0.0 -> 0.0


class Schema:
    def __init__(self, name: str):
        self.s = W.schema_by_name(name)
        self._attrs = {}

    def attrs(self, type_name: str):
        """[(name, index, param_type)] of explicit (non-derived) attributes."""
        r = self._attrs.get(type_name)
        if r is None:
            d = self.s.declaration_by_name(type_name).as_entity()
            r = [(a.name(), i, a.type_of_attribute()) for i, (a, der) in enumerate(zip(d.all_attributes(), d.derived())) if not der]
            self._attrs[type_name] = r
        return r


def agg_info(t):
    """Return (kind, element_type) if param type t is an aggregate (resolving defined types), else (None, None)."""
    while t is not None:
        at = t.as_aggregation_type()
        if at is not None:
            return at.type_of_aggregation_string(), at.type_of_element()
        nt = t.as_named_type()
        if nt is None:
            return None, None
        td = nt.declared_type().as_type_declaration()
        if td is None:
            return None, None
        t = td.declared_type()
    return None, None


class Decomposer:
    def __init__(self, f: ifcopenshell.file, format_tag: str = FORMAT, resolve_node_id: Callable[[str, bytes], str | None] | None = None):
        # resolve_node_id(ifc_type, canonical_bytes) -> existing node id, or None for the content hash
        self.format_tag = format_tag
        self.resolve_node_id = resolve_node_id
        self.f = f
        self.schema = Schema(f.schema_identifier if f.schema_identifier in ("IFC4X3_ADD2",) else f.schema)
        self.records: dict[str, bytes] = {}
        self.kind: dict[int, str] = {}
        self.anchor_of: dict[int, str] = {}
        self.node_key: dict[str, str] = {}  # content class -> node id
        self.inst_node_key: dict[int, str] = {}  # instance id -> node id
        self.fresh_ids: dict[str, str] = {}  # node id -> content hash, for nodes that got a new id
        self.gid: dict[int, str] = {}
        self.issues: list[str] = []
        self._visiting: set[int] = set()

    # ---------- classification ----------
    def classify(self):
        # Duplicate GlobalIds: the first occurrence (file order) keeps the GlobalId, later ones
        # get "<GlobalId>~1", "~2"... Exports write records in key order, so "<g>" comes before
        # "<g>~1" and the ordinals survive export -> re-import (fixed point).
        count: dict[str, int] = {}
        for r in sorted(self.f.by_type("IfcRoot"), key=lambda x: x.id()):
            g = r.GlobalId
            n = count.get(g, 0)
            count[g] = n + 1
            if n:
                self.issues.append(f"duplicate GlobalId {g} (occurrence {n + 1}, #{r.id()})")
                g = f"{g}~{n}"
            self.gid[r.id()] = g
        # Classification must depend on CONTENT only, never on how many duplicate instances
        # the source file happened to contain (otherwise export -> re-import changes records).
        # 1. Hash-cons: identical non-rooted entities (same type, same attribute values,
        #    same referenced content) form one content class.
        self.ckey: dict[int, str] = {}
        sys.setrecursionlimit(max(10000, sys.getrecursionlimit()))
        for e in self.f:
            if e.id() not in self.gid:
                self._key(e)
        # 2. Reference edges between classes: (parent class, attribute, index path).
        #    Duplicate parents collapse into the same edge.
        edges: dict[str, set] = {}
        for e in self.f:
            eid = e.id()
            if eid in self.gid:
                continue
            c = self.ckey[eid]
            s = edges.setdefault(c, set())
            for p in self.f.get_inverse(e):
                pc = "R" + self.gid[p.id()] if p.id() in self.gid else self.ckey[p.id()]
                for name, i, t in self.schema.attrs(p.is_a()):
                    for pos in _positions(p[i], eid, ()):
                        s.add((pc, name, pos))
        # 3. Kind per class.
        ckind: dict[str, tuple] = {}
        for c, s in edges.items():
            if len(s) <= 1:
                ckind[c] = (INLINE, None)  # 0 edges = only loose instances (handled in run)
                continue
            root_edges = [x for x in s if x[0].startswith("R")]
            if len(root_edges) == 1 and root_edges[0][2] == ():
                ckind[c] = (ANCHORED, f"{root_edges[0][0][1:]}/{root_edges[0][1]}")
            else:
                ckind[c] = (NODE, None)
        for eid, c in self.ckey.items():
            k, path = ckind[c]
            self.kind[eid] = k
            if path:
                self.anchor_of[eid] = path

    def _key(self, e) -> str:
        eid = e.id()
        k = self.ckey.get(eid)
        if k is not None:
            return k
        parts = [e.is_a()]
        for _, i, t in self.schema.attrs(e.is_a()):
            parts.append(self._kv(e[i], t))
        k = h("(".join(parts).encode("utf-8"))
        self.ckey[eid] = k
        return k

    def _kv(self, v, t) -> str:
        if v is None:
            return "$"
        if isinstance(v, ifcopenshell.entity_instance):
            if v.id() == 0:
                return f"T{v.is_a()}:{self._kv(v.wrappedValue, None)}"
            if v.id() in self.gid:
                return "R" + self.gid[v.id()]
            return "E" + self._key(v)
        if isinstance(v, (tuple, list)):
            kind, el = agg_info(t) if t is not None else (None, None)
            items = [self._kv(x, el) for x in v]
            if kind == "set":
                items.sort()
            return "[" + ",".join(items) + "]"
        if isinstance(v, float):
            return "F" + repr(norm_float(v))
        return type(v).__name__[0] + repr(v)

    # ---------- encoding ----------
    def ref(self, e, owner_id: int | None, attr: str | None):
        """Encode a reference to entity e appearing in attribute `attr` of entity `owner_id`."""
        eid = e.id()
        if eid in self.gid:
            return {"@o": self.gid[eid]}
        k = self.kind[eid]
        if k == INLINE:
            return self.entity_value(e)
        if k == ANCHORED:
            path = self.anchor_of[eid]
            if owner_id is not None and owner_id in self.gid and f"{self.gid[owner_id]}/{attr}" == path:
                return self.entity_value(e)  # this is the owner location: embed
            return {"@a": path}
        return {"@n": self.node(e)}

    def value(self, v, t, owner_id, attr):
        if v is None:
            return None
        if isinstance(v, ifcopenshell.entity_instance):
            if v.id() == 0:  # typed value, e.g. IfcLabel('x')
                decl = self.schema.s.declaration_by_name(v.is_a())
                inner_t = decl.as_type_declaration().declared_type() if decl.as_type_declaration() else None
                return {"@t": v.is_a(), "v": self.value(v.wrappedValue, inner_t, owner_id, attr)}
            return self.ref(v, owner_id, attr)
        if isinstance(v, (tuple, list)):
            kind, el_t = agg_info(t) if t is not None else (None, None)
            items = [self.value(x, el_t, owner_id, attr) for x in v]
            if kind == "set":
                items.sort(key=canon)
            return items
        if isinstance(v, bool):
            return v
        if isinstance(v, float):
            return norm_float(v)
        if isinstance(v, (int, str)):
            return v
        raise TypeError(f"unsupported value {type(v)} {v!r}")

    def entity_value(self, e):
        eid = e.id()
        if eid in self._visiting:
            raise ValueError(f"cycle through #{eid}")
        self._visiting.add(eid)
        a = {}
        for name, i, t in self.schema.attrs(e.is_a()):
            v = self.value(e[i], t, eid, name)
            if v is not None:
                a[name] = v
        self._visiting.discard(eid)
        return {"t": e.is_a(), "a": a}

    def node(self, e) -> str:
        eid = e.id()
        c = self.ckey[eid]  # memo per content class: duplicates encode once
        key = self.node_key.get(c)
        if key is None:
            b = canon(self.entity_value(e))
            fresh = h(b)
            key = (self.resolve_node_id(e.is_a(), b) if self.resolve_node_id else None) or fresh
            if key == fresh:
                self.fresh_ids[key] = fresh
            self.node_key[c] = key
            self.records[f"n/{key}"] = b
        self.inst_node_key[eid] = key
        return key

    def run(self) -> dict[str, bytes]:
        self.classify()
        for r in self.f.by_type("IfcRoot"):
            self.records[f"o/{self.gid[r.id()]}"] = canon(self.entity_value(r))
        loose: dict[str, list] = {}
        for e in self.f:  # loose entities, and shared nodes not reached from any root
            if e.id() in self.gid:
                continue
            if self.f.get_total_inverses(e) == 0:
                # Loose (unreferenced) entity, e.g. IfcStyledItem: keyed by content, with
                # multiplicity so identical duplicates are preserved (lossless).
                v = self.entity_value(e)
                hx = h(canon(v))
                loose.setdefault(hx, [v, 0])[1] += 1
            elif self.kind[e.id()] == NODE:
                self.node(e)
        for hx, (v, n) in loose.items():
            self.records[f"l/{hx}"] = canon({"e": v, "n": n})
        self.records["meta"] = canon({"k": self.format_tag, "schema": self.f.schema_identifier})
        return self.records


def _positions(v, eid, path):
    """Yield index paths where entity `eid` occurs in attribute value v (() = the value itself)."""
    if isinstance(v, ifcopenshell.entity_instance):
        if v.id() == eid:
            yield path
    elif isinstance(v, tuple):
        for i, x in enumerate(v):
            yield from _positions(x, eid, path + (i,))


def decompose(f: ifcopenshell.file, *, format_tag: str = FORMAT, resolve_node_id: Callable[[str, bytes], str | None] | None = None):
    d = Decomposer(f, format_tag, resolve_node_id)
    recs = d.run()
    return recs, d


class Composer:
    """records -> ifcopenshell.file, with deterministic step ids."""

    def __init__(self, records: dict[str, bytes]):
        self.r = {k: json.loads(v) for k, v in records.items()}
        meta = self.r.pop("meta")
        self.f = ifcopenshell.file(schema=meta["schema"])
        self.schema = Schema(meta["schema"])
        self.roots: dict[str, ifcopenshell.entity_instance] = {}
        self.nodes: dict[str, ifcopenshell.entity_instance] = {}
        self.anchors: dict[str, ifcopenshell.entity_instance] = {}
        self.filled: set[str] = set()

    def build(self):
        keys = sorted(self.r)
        for k in keys:  # phase 1: shells for roots, in sorted order
            if k.startswith("o/"):
                self.roots[k[2:]] = self.f.create_entity(self.r[k]["t"])
        for k in keys:  # phase 2: fill
            if k.startswith("o/"):
                self.fill_root(k[2:])
            elif k.startswith("n/"):
                self.get_node(k[2:])
            elif k.startswith("l/"):
                for _ in range(self.r[k]["n"]):
                    self.make_entity(self.r[k]["e"])
        return self.f

    def fill_root(self, gid, only_attr=None):
        rec = self.r[f"o/{gid}"]
        inst = self.roots[gid]
        for name, i, t in self.schema.attrs(rec["t"]):
            key = f"{gid}/{name}"
            if key in self.filled or name not in rec["a"]:
                continue
            if only_attr is not None and name != only_attr:
                continue
            self.filled.add(key)
            val = self.decode(rec["a"][name], t, anchor_path=key)
            setattr(inst, name, val)

    def get_node(self, hx):
        n = self.nodes.get(hx)
        if n is None:
            n = self.make_entity(self.r[f"n/{hx}"])
            self.nodes[hx] = n
        return n

    def get_anchor(self, path):
        if path not in self.anchors:
            gid, attr = path.split("/", 1)
            self.fill_root(gid, only_attr=attr)
        return self.anchors[path]

    def make_entity(self, ev, anchor_path=None):
        args = {}
        for name, i, t in self.schema.attrs(ev["t"]):
            if name in ev["a"]:
                args[name] = self.decode(ev["a"][name], t)
        inst = self.f.create_entity(ev["t"], **args)
        if anchor_path is not None:
            self.anchors[anchor_path] = inst
        return inst

    def decode(self, v, t, anchor_path=None):
        if isinstance(v, dict):
            if "@o" in v:
                return self.roots[v["@o"]]
            if "@n" in v:
                return self.get_node(v["@n"])
            if "@a" in v:
                return self.get_anchor(v["@a"])
            if "@t" in v:
                decl = self.schema.s.declaration_by_name(v["@t"]).as_type_declaration()
                inner = self.decode(v["v"], decl.declared_type() if decl else None)
                return self.f.create_entity(v["@t"], inner)
            return self.make_entity(v, anchor_path=anchor_path)
        if isinstance(v, list):
            kind, el_t = agg_info(t) if t is not None else (None, None)
            return [self.decode(x, el_t) for x in v]
        return v


def compose(records: dict[str, bytes]) -> ifcopenshell.file:
    return Composer(records).build()


# Inverses that IFC's WHERE rules limit to one owner although the schema declares a set
# (IfcShapeModel.WR11: a shape representation belongs to one product shape, map or aspect).
_ONE_OWNER = {"OfProductRepresentation"}


def unshare(f: ifcopenshell.file) -> int:
    """Give each owner its own copy of entities IFC allows only one owner for (a material layer in
    one layer set, a shape representation in one product shape...). Records hash-cons identical
    values, so composing can share them; decomposing the copies hash-conses them again, so records
    (and every stored hash) are unchanged. Deterministic (entity id order). Returns the copies made."""
    schema = W.schema_by_name(f.schema)
    exclusive: dict[str, list] = {}

    def single_owner(type_name):
        if type_name not in exclusive:
            d = schema.declaration_by_name(type_name).as_entity()
            exclusive[type_name] = [
                (inv.name(), inv.attribute_reference().name()) for inv in d.all_inverse_attributes()
                if inv.type_of_aggregation_string() == "" or inv.bound2() == 1 or inv.name() in _ONE_OWNER]
        return exclusive[type_name]

    copies = 0
    for e in sorted(f, key=lambda x: x.id()):
        for inverse, forward in single_owner(e.is_a()):
            owners = getattr(e, inverse, None)
            if owners is None:
                continue
            owners = sorted(owners if isinstance(owners, (list, tuple)) else [owners], key=lambda x: x.id())
            for owner in owners[1:]:
                copy = f.create_entity(e.is_a(), *list(e))
                value = getattr(owner, forward)
                if isinstance(value, (list, tuple)):
                    setattr(owner, forward, [copy if v == e else v for v in value])
                elif value == e:
                    setattr(owner, forward, copy)
                copies += 1
    return copies


def state_hash(records: dict[str, bytes]) -> str:
    """Hash of the whole state: sorted (key, record-hash) pairs. Stand-in for a Git root tree hash."""
    hh = blake3.blake3()
    for k in sorted(records):
        hh.update(k.encode() + b"\0" + h(records[k]).encode() + b"\n")
    return hh.hexdigest()[:32]


def body_text(path) -> str:
    """IFC text from the DATA section on (the HEADER holds timestamps)."""
    t = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    return t[t.index("DATA;"):]
