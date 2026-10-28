# SPDX-License-Identifier: GPL-3.0-or-later
"""Property-level Compare (R3, docs/03-versioning.md#diff-compare).

`Project.diff` says which elements were added, modified or removed. This module explains a
modified element from the records themselves, without composing either version: the attributes that
changed (placement and geometry by name), the property sets' properties with their old and new
values, the IFC class and the level. It also groups the change by class and by level (the tree).

Everything is read lazily through the two versions' record trees, so the work follows the changed
elements and the records they use, not the size of the model.
"""
from __future__ import annotations

import json
from collections import defaultdict

from .layout import is_record_path, key_to_path

_MAX_VALUE = 300
_MAX_ITEMS = 5000
_GEOMETRY = {"ObjectPlacement": "Placement", "Representation": "Geometry"}
_SKIP = {"OwnerHistory", "GlobalId"}


def _text(value) -> str:
    if isinstance(value, dict):
        if "@t" in value:
            return _text(value.get("v"))
        if "@o" in value:
            return value["@o"]
        if "@n" in value:
            return value["@n"]
        if "@a" in value:
            return value["@a"]
        if "t" in value:
            return value["t"]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= _MAX_VALUE else text[:_MAX_VALUE] + "…"


def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True, separators=(",", ":"), ensure_ascii=False) == \
        json.dumps(b, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class _View:
    """One version's record tree: paths and blobs read on demand, plus the object records by type.

    With `records`, the set is already in memory (the working model): nothing is read from the repo.
    """

    def __init__(self, project, rev: str, records: dict[str, bytes] | None = None):
        self.project, self.rev = project, rev
        self._blobs: dict[str, bytes] = {}
        if records is not None:
            self.entries = {}
            for key, data in records.items():
                path = key_to_path(key)
                if is_record_path(path):
                    self.entries[path] = ""
                    self._blobs[path] = data
        else:
            self.entries = {p: o for p, o in project._entries(rev).items() if is_record_path(p)}
        self._objects: dict[str, bytes] | None = None
        self._psets: dict[str, dict] | None = None
        self._contained: dict[str, str] | None = None
        self._levels: dict[str, str] | None = None

    def blob(self, key: str) -> bytes | None:
        path = key_to_path(key)
        if path in self._blobs:
            return self._blobs[path]
        oid = self.entries.get(path)
        if oid is None:
            return None
        self._blobs[path] = self.project.repo.read_blobs([oid])[0]
        return self._blobs[path]

    def record(self, key: str) -> dict | None:
        data = self.blob(key)
        return json.loads(data) if data is not None else None

    def objects(self) -> dict[str, bytes]:
        """Every rooted object record's bytes, read once; the index passes never parse the rest."""
        if self._objects is None:
            paths = sorted(p for p in self.entries if p.startswith("objects/"))
            missing = [p for p in paths if p not in self._blobs]
            if missing:
                blobs = self.project.repo.read_blobs([self.entries[p] for p in missing])
                self._blobs.update(dict(zip(missing, blobs)))
            self._objects = {p: self._blobs[p] for p in paths}
        return self._objects

    def indexes(self):
        """(product -> [pset keys], pset key -> [product guids], product -> level name)."""
        if self._psets is not None:
            return self._psets, self._contained or {}, self._levels or {}
        products, by_pset, contained, levels = defaultdict(list), defaultdict(list), {}, {}
        for path, data in self.objects().items():
            if b'"t":"IfcRelDefinesByProperties"' in data:
                rel = json.loads(data)
                relating = (rel.get("a") or {}).get("RelatingPropertyDefinition")
                pset = relating.get("@o") if isinstance(relating, dict) else None
                if not pset:
                    continue
                pset = "o/" + pset
                for obj in (rel.get("a") or {}).get("RelatedObjects") or []:
                    guid = obj.get("@o") if isinstance(obj, dict) else None
                    if guid:
                        products[guid].append(pset)
                        by_pset[pset].append(guid)
            elif b'"t":"IfcRelContainedInSpatialStructure"' in data:
                rel = json.loads(data)
                storey = ((rel.get("a") or {}).get("RelatingStructure") or {}).get("@o")
                for obj in (rel.get("a") or {}).get("RelatedElements") or []:
                    guid = obj.get("@o") if isinstance(obj, dict) else None
                    if guid and storey:
                        contained[guid] = storey
        for storey in set(contained.values()):
            rec = self.record("o/" + storey)
            levels[storey] = ((rec or {}).get("a") or {}).get("Name") or storey
        self._psets, self._contained, self._levels = products, contained, levels
        return products, by_pset, levels

    def level_of(self, guid: str) -> str:
        _, _, levels = self.indexes()
        storey = (self._contained or {}).get(guid)
        return levels.get(storey, "") if storey else ""


def _properties(view: _View, pset_key: str) -> dict:
    rec = view.record(pset_key) or {}
    a = rec.get("a") or {}
    out = {}
    for item in a.get("HasProperties") or a.get("Quantities") or []:
        if not isinstance(item, dict):
            continue
        if "t" in item:
            prop = item.get("a") or {}
        elif "@n" in item:
            prop = (view.record("n/" + item["@n"]) or {}).get("a") or {}
        elif "@o" in item:
            prop = (view.record("o/" + item["@o"]) or {}).get("a") or {}
        else:
            continue
        name = prop.get("Name") or ""
        if name:
            out[name] = prop.get("NominalValue", prop.get("Value", prop))
    return out


def _pset_changes(old: _View, new: _View, guid: str) -> list[dict]:
    old_products, _, _ = old.indexes()
    new_products, _, _ = new.indexes()
    old_keys = old_products.get(guid, [])
    new_keys = new_products.get(guid, [])
    old_by_name = {}
    new_by_name = {}
    for key in old_keys:
        rec = old.record(key) or {}
        name = ((rec.get("a") or {}).get("Name") or key)
        old_by_name[name] = key
    for key in new_keys:
        rec = new.record(key) or {}
        name = ((rec.get("a") or {}).get("Name") or key)
        new_by_name[name] = key
    out = []
    for name in sorted(set(old_by_name) | set(new_by_name)):
        if name not in new_by_name:
            for prop, value in sorted(_properties(old, old_by_name[name]).items()):
                out.append({"pset": name, "property": prop, "kind": "removed", "old": _text(value), "new": None})
            continue
        if name not in old_by_name:
            for prop, value in sorted(_properties(new, new_by_name[name]).items()):
                out.append({"pset": name, "property": prop, "kind": "added", "old": None, "new": _text(value)})
            continue
        before, after = _properties(old, old_by_name[name]), _properties(new, new_by_name[name])
        for prop in sorted(set(before) | set(after)):
            if prop not in after:
                out.append({"pset": name, "property": prop, "kind": "removed", "old": _text(before[prop]), "new": None})
            elif prop not in before:
                out.append({"pset": name, "property": prop, "kind": "added", "old": None, "new": _text(after[prop])})
            elif not _same(before[prop], after[prop]):
                out.append({"pset": name, "property": prop, "kind": "modified",
                            "old": _text(before[prop]), "new": _text(after[prop])})
    return out


def _attributes(old: dict | None, new: dict | None) -> list[dict]:
    before = {k: v for k, v in ((old or {}).get("a") or {}).items() if k not in _SKIP}
    after = {k: v for k, v in ((new or {}).get("a") or {}).items() if k not in _SKIP}
    out = []
    for name in sorted(set(before) | set(after)):
        if name in before and name in after and _same(before[name], after[name]):
            continue
        label = _GEOMETRY.get(name, name)
        if name not in after:
            out.append({"name": label, "kind": "removed", "old": _text(before[name]), "new": None})
        elif name not in before:
            out.append({"name": label, "kind": "added", "old": None, "new": _text(after[name])})
        else:
            out.append({"name": label, "kind": "modified", "old": _text(before[name]),
                        "new": _text(after[name])})
    return out


def changes_by_element(project, rev_a: str, rev_b: str, changes, *, old_records=None, new_records=None) -> dict:
    """The element-level Changes plus the property-level detail, categories and tree (a dict)."""
    old, new = _View(project, rev_a, old_records), _View(project, rev_b, new_records)
    items = {"added": list(changes.added), "modified": list(changes.modified), "removed": list(changes.removed)}
    # A changed property set modifies the elements that use it (the same rule as versioning._summary).
    extra = set()
    for change in changes.items:
        if change.key.startswith("o/") and change.ifc_type in ("IfcPropertySet", "IfcElementQuantity"):
            guid = change.key[2:]
            for view in (old, new):
                _, by_pset, _ = view.indexes()
                extra.update(by_pset.get(guid, []))
    from .project import Change

    known = {c.key for c in items["modified"]} | {c.key for c in items["added"]} | {c.key for c in items["removed"]}
    for guid in sorted(extra):
        if "o/" + guid not in known:
            rec = new.record("o/" + guid) or old.record("o/" + guid) or {}
            if "t" in rec:
                items["modified"].append(Change("modified", "o/" + guid, rec["t"],
                                                (rec.get("a") or {}).get("Name")))

    def is_element(ifc_type: str) -> bool:
        return ifc_type.startswith("Ifc") and not ifc_type.startswith("IfcRel") and \
            ifc_type not in ("IfcPropertySet", "IfcElementQuantity")

    elements = {kind: [c for c in items[kind] if c.key.startswith("o/") and is_element(c.ifc_type)]
                for kind in ("added", "modified", "removed")}
    details = []
    for kind in ("added", "modified", "removed"):
        for change in elements[kind]:
            if not change.key.startswith("o/"):
                continue
            guid = change.key[2:].split("~", 1)[0]
            before, after = old.record(change.key), new.record(change.key)
            if kind == "modified" and before is not None and after is not None:
                if not (_attributes(before, after) or _pset_changes(old, new, guid)):
                    continue  # the element changed only through a relationship or encoding
            details.append({
                "guid": guid, "type": change.ifc_type, "name": change.name or "", "kind": kind,
                "level": (new.level_of(guid) if kind != "removed" else old.level_of(guid)),
                "attributes": _attributes(before, after) if kind == "modified" else [],
                "properties": _pset_changes(old, new, guid) if kind == "modified" else [],
            })

    categories, tree = defaultdict(lambda: {"added": 0, "modified": 0, "removed": 0}), defaultdict(
        lambda: defaultdict(lambda: {"added": 0, "modified": 0, "removed": 0}))
    for d in details:
        categories[d["type"]][d["kind"]] += 1
        tree[d["level"] or "(no level)"][d["type"]][d["kind"]] += 1
    listed = {kind: [{"guid": c.key[2:].split("~", 1)[0], "type": c.ifc_type, "name": c.name or "",
                      "kind": c.kind} for c in elements[kind]] for kind in elements}
    return {"details": details[:_MAX_ITEMS], "truncated": len(details) > _MAX_ITEMS,
            "elements": listed,
            "categories": {k: dict(v) for k, v in sorted(categories.items())},
            "tree": {level: {cls: dict(counts) for cls, counts in sorted(classes.items())}
                     for level, classes in sorted(tree.items())}}
