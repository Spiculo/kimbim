# SPDX-License-Identifier: GPL-3.0-or-later
"""Three-way merge of canonical records (R4, docs/03-versioning.md#merge-combine-options).

Inputs are three record sets (key -> canonical JSON bytes, kimbim.records): the common base and the
two sides ("ours" = the option being combined into, "theirs" = the other option). The merge is pure
data comparison, so it is deterministic: the same three inputs give the same records and conflicts.

1. Per record: unchanged on one side -> the other side; the same change on both -> taken; added on
   both with different content -> conflict; deleted on one side and modified on the other -> conflict.
2. Inside a record changed on both sides, per attribute: different attributes combine; the same
   attribute changed to different values -> conflict. SET aggregates merge as sets (both sides adding
   walls to one level is not a conflict); property sets and quantity sets merge per property name.
   The placement is one value: both sides moving the same element is a conflict (deliberate, docs/03).
   Loose records (styles) merge their multiplicity.
3. Integrity, on the merged result: references to records that no longer exist and elements contained
   in two levels are semantic conflicts; IFC schema problems that neither side had are reported.

Conflicts carry base / ours / theirs values; nothing is resolved silently. A resolution maps a
conflict id to one of its options ("ours" / "theirs", or for integrity conflicts the ones listed).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .content import Contents
from .records import Schema, agg_info, canon

OURS, THEIRS = "ours", "theirs"
_PROPERTY_LISTS = {("IfcPropertySet", "HasProperties"), ("IfcElementQuantity", "Quantities")}


@dataclass
class Conflict:
    id: str
    kind: str  # both_added | delete_modify | class | attribute | property | loose | dangling | containment
    key: str  # the record
    ifc_type: str = ""
    name: str = ""
    attribute: str | None = None
    property: str | None = None
    base: object = None
    ours: object = None
    theirs: object = None
    options: list = field(default_factory=lambda: [OURS, THEIRS])
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MergeResult:
    records: dict  # merged records; unresolved conflicts keep "ours"
    conflicts: list  # every conflict found (resolved or not)
    unresolved: list  # ids of conflicts without a resolution
    warnings: list  # non-blocking (IFC validation messages new in the merge)
    stats: dict

    @property
    def clean(self) -> bool:
        return not self.unresolved


def _load(b):
    return None if b is None else json.loads(b)


def _entity(v):
    """The entity of a record value ({"t", "a"}), unwrapping loose records ({"e", "n"})."""
    return v["e"] if isinstance(v, dict) and "e" in v and "n" in v else v


def _describe(key, *values):
    for v in values:
        if v is None or key == "meta":
            continue
        e = _entity(v)
        return e.get("t", ""), str((e.get("a") or {}).get("Name") or "")
    return "", ""


class _Merger:
    def __init__(self, base, ours, theirs, resolutions):
        self.base, self.ours, self.theirs = base, ours, theirs
        self.res = resolutions or {}
        schema = "IFC4"
        for side in (ours, theirs, base):
            if "meta" in side:
                schema = json.loads(side["meta"]).get("schema", schema)
                break
        self.schema = Schema(schema)
        # Content digests per side (kimbim.content): a record or value only re-encoded (a value it shares
        # became a node) is unchanged, so it never conflicts with a real change on the other side.
        self.contents = {side: Contents(records.get, self.schema, owner_history=True)
                         for side, records in (("base", base), (OURS, ours), (THEIRS, theirs))}
        self.conflicts: list[Conflict] = []
        self.out: dict[str, bytes] = {}
        self._set_attrs: dict[str, set] = {}

    # ---------------------------------------------------------------- helpers
    def conflict(self, c: Conflict):
        self.conflicts.append(c)
        return self.res.get(c.id)

    def set_attributes(self, ifc_type: str) -> set:
        """Attribute names of an entity type that are SETs (order-free)."""
        if ifc_type not in self._set_attrs:
            names = set()
            try:
                for name, _i, t in self.schema.attrs(ifc_type):
                    if agg_info(t)[0] == "set":
                        names.add(name)
            except Exception:  # unknown type: treat every list as ordered
                pass
            self._set_attrs[ifc_type] = names
        return self._set_attrs[ifc_type]

    def same(self, key, x, y) -> bool:
        """Records with the same content on two sides."""
        return self.contents[x].record(key) == self.contents[y].record(key)

    def same_value(self, ifc_type, attr, x, vx, y, vy) -> bool:
        """An attribute with the same content on two sides."""
        t = self.attr_types(ifc_type).get(attr)
        return canon(self.contents[x].value(vx, t)) == canon(self.contents[y].value(vy, t))

    def attr_types(self, ifc_type: str) -> dict:
        return self.contents["base"]._attr_types(ifc_type)

    def node(self, side, ref):
        """The entity behind a node reference on a side (for property names), or the value itself."""
        if isinstance(ref, dict) and "@n" in ref:
            records = {OURS: self.ours, THEIRS: self.theirs, "base": self.base}[side]
            b = records.get("n/" + ref["@n"]) or self.base.get("n/" + ref["@n"])
            return _load(b) if b is not None else None
        return ref

    # ---------------------------------------------------------------- per record
    def run(self):
        keys = sorted(set(self.base) | set(self.ours) | set(self.theirs))
        for key in keys:
            b, o, t = self.base.get(key), self.ours.get(key), self.theirs.get(key)
            if o == t:
                merged = o
            elif o == b:
                merged = t
            elif t == b:
                merged = o
            elif self.same(key, "base", OURS):  # ours only re-encoded it
                merged = t
            elif self.same(key, "base", THEIRS) or self.same(key, OURS, THEIRS):
                merged = o
            else:
                merged = self.both_changed(key, b, o, t)
            if merged is not None:
                self.out[key] = merged
        return self.out

    def both_changed(self, key, b, o, t):
        vb, vo, vt = _load(b), _load(o), _load(t)
        ifc_type, name = _describe(key, vo, vt, vb)
        if b is None:
            pick = self.conflict(Conflict(f"{key}", "both_added", key, ifc_type, name, ours=vo, theirs=vt,
                                          message="added on both sides with different content"))
            return t if pick == THEIRS else o
        if o is None or t is None:
            pick = self.conflict(Conflict(f"{key}", "delete_modify", key, ifc_type, name, base=vb, ours=vo, theirs=vt,
                                          message="deleted on one side and modified on the other"))
            return t if pick == THEIRS else o
        if key.startswith("l/"):  # loose values: identical content, the count of copies merges
            n = vo["n"] + vt["n"] - vb["n"]
            if vo["e"] == vt["e"] == vb["e"]:
                return canon({"e": vb["e"], "n": n}) if n > 0 else None
            pick = self.conflict(Conflict(f"{key}", "loose", key, ifc_type, name, base=vb, ours=vo, theirs=vt))
            return t if pick == THEIRS else o
        if key == "meta" or "t" not in vo or "t" not in vt:
            pick = self.conflict(Conflict(f"{key}", "attribute", key, ifc_type, name, base=vb, ours=vo, theirs=vt))
            return t if pick == THEIRS else o
        if not (vo["t"] == vt["t"] == vb["t"]):
            pick = self.conflict(Conflict(f"{key}#class", "class", key, ifc_type, name, attribute="(class)",
                                          base=vb["t"], ours=vo["t"], theirs=vt["t"]))
            return t if pick == THEIRS else o
        if vo["t"] == "IfcOwnerHistory":  # edit bookkeeping updated in place (IFC2X3): the newer one
            def modified(v):
                value = v.get("a", {}).get("LastModifiedDate")
                return value if isinstance(value, (int, float)) else -1
            return t if modified(vt) > modified(vo) else o
        return canon(self.merge_entity(key, vb, vo, vt, name))

    # ---------------------------------------------------------------- per attribute
    def merge_entity(self, key, vb, vo, vt, name):
        ifc_type = vb["t"]
        ab, ao, at = vb.get("a", {}), vo.get("a", {}), vt.get("a", {})
        merged = {}
        sets = self.set_attributes(ifc_type)
        for attr in sorted(set(ab) | set(ao) | set(at)):
            b, o, t = ab.get(attr), ao.get(attr), at.get(attr)
            if o == t:
                value = o
            elif o == b:
                value = t
            elif t == b:
                value = o
            elif self.same_value(ifc_type, attr, "base", b, OURS, o):  # ours only re-encoded it
                value = t
            elif self.same_value(ifc_type, attr, "base", b, THEIRS, t) or self.same_value(ifc_type, attr, OURS, o, THEIRS, t):
                value = o
            elif attr == "OwnerHistory":  # edit bookkeeping (IFC2X3): this option's, never a question
                value = o
            elif (ifc_type, attr) in _PROPERTY_LISTS and all(isinstance(x, list) for x in (b, o, t)):
                value = self.merge_properties(key, ifc_type, name, attr, b, o, t)
            elif attr in sets and all(isinstance(x, list) for x in (b or [], o or [], t or [])):
                value = self.merge_set(ifc_type, attr, b or [], o or [], t or [])
            else:
                pick = self.conflict(Conflict(f"{key}#{attr}", "attribute", key, ifc_type, name, attribute=attr,
                                              base=b, ours=o, theirs=t))
                value = t if pick == THEIRS else o
            if value is not None:
                merged[attr] = value
        return {"a": merged, "t": ifc_type}

    def merge_set(self, ifc_type, attr, b, o, t):
        """base + what either side added - what either side removed (members compared by content, so a
        member only re-encoded on one side is neither removed nor added)."""
        el = agg_info(self.attr_types(ifc_type).get(attr))[1]

        def members(side, items):
            return {canon(self.contents[side].value(x, el)): x for x in items}

        cb, co, ct = members("base", b), members(OURS, o), members(THEIRS, t)
        keep = (set(cb) - (set(cb) - set(co)) - (set(cb) - set(ct))) | (set(co) - set(cb)) | (set(ct) - set(cb))
        chosen = {**cb, **co, **ct}
        return sorted({canon(chosen[k]): chosen[k] for k in keep}.values(), key=canon)

    def merge_properties(self, key, ifc_type, name, attr, b, o, t):
        """Property sets merge per property name (docs/03)."""
        def by_name(side, items):
            out = {}
            for item in items:
                e = self.node(side, item)
                prop = ((e or {}).get("a") or {}).get("Name") if isinstance(e, dict) else None
                out[prop if prop is not None else canon(item).decode()] = item
            return out

        nb, no, nt = by_name("base", b), by_name(OURS, o), by_name(THEIRS, t)
        result = []
        for prop in sorted(set(nb) | set(no) | set(nt)):
            pb, po, pt = nb.get(prop), no.get(prop), nt.get(prop)
            # Compare the property's content (a shared node edited in place keeps its reference).
            cb, co, ct = (canon(self.node(s, x)) if x is not None else None
                          for s, x in (("base", pb), (OURS, po), (THEIRS, pt)))
            if co == ct:
                value = po
            elif co == cb:
                value = pt
            elif ct == cb:
                value = po
            else:
                pick = self.conflict(Conflict(f"{key}#{attr}[{prop}]", "property", key, ifc_type, name, attribute=attr,
                                              property=prop, base=self.node("base", pb), ours=self.node(OURS, po),
                                              theirs=self.node(THEIRS, pt)))
                value = pt if pick == THEIRS else po
            if value is not None:
                result.append(value)
        sets = self.set_attributes(ifc_type)
        return sorted(result, key=canon) if attr in sets else result


# ---------------------------------------------------------------- integrity

def _references(value, out):
    if isinstance(value, dict):
        if "@o" in value:
            out.add("o/" + value["@o"])
        elif "@n" in value:
            out.add("n/" + value["@n"])
        elif "@a" in value:
            out.add("o/" + value["@a"].split("/", 1)[0])
        else:
            for v in value.values():
                _references(v, out)
    elif isinstance(value, list):
        for v in value:
            _references(v, out)
    return out


def _integrity(records, base, ours, theirs, resolutions, conflicts):
    """Dangling references and duplicate containment in the merged records; applies their resolutions
    (repeatedly: removing a record can leave others dangling). Returns the records."""
    records = dict(records)
    for _round in range(20):
        changed = False
        found = []
        # Shared values (n/) have no identity: whether a value is a node or inline depends on how many
        # referrers it has on each side, so a missing one is restored, never a conflict.
        missing_nodes = True
        while missing_nodes:
            missing_nodes = False
            for key in sorted(records):
                if key == "meta":
                    continue
                for target in _references(_load(records[key]), set()):
                    if target.startswith("n/") and target not in records:
                        source = ours.get(target) or theirs.get(target) or base.get(target)
                        if source is not None:
                            records[target] = source
                            missing_nodes = True
        missing_by_source = {}
        for key in sorted(records):
            if key == "meta":
                continue
            for target in sorted(_references(_load(records[key]), set())):
                if target not in records:
                    missing_by_source.setdefault(key, []).append(target)
        for key, targets in missing_by_source.items():
            v = _load(records[key])
            ifc_type, name = _describe(key, v)
            for target in targets:
                source = ours.get(target) or theirs.get(target) or base.get(target)
                cid = f"dangling:{key}->{target}"
                tt, tn = _describe(target, _load(source)) if source else ("", "")
                c = Conflict(cid, "dangling", key, ifc_type, name, attribute=target, options=["restore", "remove"],
                             message=f"{ifc_type} {name} refers to {tt} {tn} ({target}), which the other side deleted".strip(),
                             base=_load(base.get(target)), ours=_load(ours.get(target)), theirs=_load(theirs.get(target)))
                found.append(c)
                pick = resolutions.get(cid)
                if pick == "restore" and source is not None and target not in records:
                    records[target] = source
                    changed = True
                elif pick == "remove" and key in records:
                    del records[key]
                    changed = True
        # An element contained in two levels.
        holders = {}
        for key in sorted(records):
            if not key.startswith("o/"):
                continue
            v = _load(records[key])
            if v.get("t") != "IfcRelContainedInSpatialStructure":
                continue
            for member in v.get("a", {}).get("RelatedElements", []):
                if isinstance(member, dict) and "@o" in member:
                    holders.setdefault(member["@o"], []).append(key)
        for guid, rels in sorted(holders.items()):
            if len(rels) < 2:
                continue
            element = _load(records.get("o/" + guid))
            ifc_type, name = _describe("o/" + guid, element) if element else ("", "")
            cid = f"containment:{guid}"
            levels = []
            for rel in rels:
                structure = _load(records[rel])["a"].get("RelatingStructure", {}).get("@o", "")
                levels.append(_describe("o/" + structure, _load(records.get("o/" + structure)))[1] or structure)
            found.append(Conflict(cid, "containment", "o/" + guid, ifc_type, name, options=list(rels),
                                  message=f"contained in {len(rels)} levels: {', '.join(levels)}"))
            pick = resolutions.get(cid)
            if pick in rels:
                for rel in rels:
                    if rel == pick:
                        continue
                    v = _load(records[rel])
                    v["a"]["RelatedElements"] = [m for m in v["a"]["RelatedElements"] if m != {"@o": guid}]
                    records[rel] = canon(v)
                changed = True
        known = {c.id for c in conflicts}
        conflicts += [c for c in found if c.id not in known]
        if not changed:
            break
    return _collect_garbage(records)


def _collect_garbage(records):
    """Drop shared values (n/) nothing refers to any more."""
    while True:
        used = set()
        for key, b in records.items():
            if key != "meta":
                _references(_load(b), used)
        unused = [k for k in records if k.startswith("n/") and k not in used]
        if not unused:
            return records
        for k in unused:
            del records[k]


def merge_records(base: dict, ours: dict, theirs: dict, resolutions: dict | None = None,
                  validate: bool = False) -> MergeResult:
    """Merge three record sets. `resolutions`: {conflict id: option}. `validate`: also report IFC
    schema problems that the merged model has and neither side had (composes the models: slower)."""
    resolutions = resolutions or {}
    m = _Merger(base, ours, theirs, resolutions)
    records = m.run()
    records = _integrity(records, base, ours, theirs, resolutions, m.conflicts)
    unresolved = [c.id for c in m.conflicts if resolutions.get(c.id) not in c.options]
    warnings = _validation_warnings(records, ours, theirs) if validate and not unresolved else []
    stats = {"records": len(records), "conflicts": len(m.conflicts),
             "from_ours": sum(1 for k in records if records[k] == ours.get(k) and ours.get(k) != base.get(k)),
             "from_theirs": sum(1 for k in records if records[k] == theirs.get(k) and theirs.get(k) != base.get(k))}
    return MergeResult(records, m.conflicts, unresolved, warnings, stats)


def _validation_warnings(records, ours, theirs) -> list:
    import ifcopenshell.validate

    from .records import compose

    def messages(recs):
        try:
            f = compose(recs)
        except Exception as ex:  # noqa: BLE001 (any failure to compose is the message)
            return {f"cannot compose: {ex}"}
        log = ifcopenshell.validate.json_logger()
        ifcopenshell.validate.validate(f, log, express_rules=False)
        # STEP ids differ between composed models: compare the messages without them.
        return {re.sub(r"#\d+", "#", str(s.get("message", s))) for s in log.statements}

    merged = messages(records)
    return sorted(merged - messages(ours) - messages(theirs))
