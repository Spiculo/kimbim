"""Independent semantic comparison of two IFC files (does not use records.py's ownership logic).

Every rooted entity is expanded fully (non-rooted references expanded recursively, rooted
references replaced by GlobalId, SETs order-independent, step ids ignored). Loose non-rooted
entities (no referrers, e.g. IfcStyledItem) are compared as a multiset.
"""
from collections import Counter

import blake3
import ifcopenshell

from records import Schema, agg_info, norm_float


def _schema(f):
    return Schema(f.schema_identifier if f.schema_identifier == "IFC4X3_ADD2" else f.schema)


def deep(f):
    S = _schema(f)
    memo = {}

    def dv(v, t):
        if v is None:
            return "$"
        if isinstance(v, ifcopenshell.entity_instance):
            if v.id() == 0:
                decl = S.s.declaration_by_name(v.is_a()).as_type_declaration()
                return f"T({v.is_a()},{dv(v.wrappedValue, decl.declared_type() if decl else None)})"
            if v.is_a("IfcRoot"):
                return f"R({v.GlobalId})"
            return ent(v)
        if isinstance(v, (tuple, list)):
            kind, el = agg_info(t) if t is not None else (None, None)
            items = [dv(x, el) for x in v]
            if kind == "set":
                items.sort()
            return "[" + ",".join(items) + "]"
        if isinstance(v, bool):
            return "B" + str(v)
        if isinstance(v, float):
            return "F" + repr(norm_float(v))
        if isinstance(v, int):
            return "I" + str(v)
        return "S" + repr(v)

    def body(e):
        return e.is_a() + "(" + ",".join(dv(e[i], t) for _, i, t in S.attrs(e.is_a())) + ")"

    def ent(e):
        k = e.id()
        if k not in memo:
            memo[k] = "E:" + blake3.blake3(body(e).encode()).hexdigest()[:24]
        return memo[k]

    roots = Counter()
    for r in f.by_type("IfcRoot"):
        roots[(r.GlobalId, blake3.blake3(body(r).encode()).hexdigest()[:24])] += 1
    loose = Counter()
    for e in f:
        if not e.is_a("IfcRoot") and f.get_total_inverses(e) == 0:
            loose[ent(e)] += 1
    return roots, loose


def compare(a, b):
    ra, la = deep(a)
    rb, lb = deep(b)
    problems = []
    if ra != rb:
        only_a = ra - rb
        only_b = rb - ra
        problems.append(f"rooted entities differ: {sum(only_a.values())} only in A, {sum(only_b.values())} only in B; e.g. {list(only_a)[:3]}")
    if la != lb:
        problems.append(f"loose entities differ: {sum((la - lb).values())} only in A, {sum((lb - la).values())} only in B")
    return problems
