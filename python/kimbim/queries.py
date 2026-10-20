# SPDX-License-Identifier: GPL-3.0-or-later
"""Selection tools (D78): select similar, Find & Select queries and selection sets.

A query is a list of criteria rows ({"field", "op", "value"[, "property"]}) joined by AND ("all") or OR
("any"), run over a scope (the whole model, one level or the current selection). The row matching
reuses D73's override-rule conditions (graphics.matches and its per-name property index), so a query
and an override rule read an element the same way. Saved criteria sets and selection sets live in the
project settings (D72: versioned, merged, carried by templates).

Same protocol as app_bridge for the bridge functions (strings in, JSON out, never raise).
"""
from __future__ import annotations

import json
import time

import ifcopenshell.util.element

from . import app_bridge as B
from . import graphics as G

FIELDS = ("kind", "ifc_class", "type", "name", "property", "layer", "level", "status", "material")
OPS = ("equals", "not_equals", "contains", "less", "more", "exists", "missing", "true", "false")
# Which operators each field takes (the panel offers these).
FIELD_OPS = {
    "kind": ("equals", "not_equals"),
    "ifc_class": ("equals", "not_equals"),
    "type": ("equals", "not_equals", "contains", "exists", "missing"),
    "name": ("equals", "not_equals", "contains"),
    "property": OPS,
    "layer": ("equals", "not_equals", "contains", "exists", "missing"),
    "level": ("equals", "not_equals"),
    "status": ("equals", "not_equals"),
    "material": ("equals", "not_equals", "contains", "exists", "missing"),
}
MATCH = ("all", "any")
SCOPES = ("model", "level", "selection")
SIMILAR = ("type", "class", "class_predefined")


# ---------------------------------------------------------------- validation (project settings)

def _criteria_error(c) -> str | None:
    if not isinstance(c, dict) or not isinstance(c.get("rows", []), list):
        return "criteria need a list of rows"
    if c.get("match", "all") not in MATCH:
        return f"unknown match {c.get('match')} (all or any)"
    for row in c.get("rows", []):
        if not isinstance(row, dict):
            return "a criteria row must be an object"
        field, op = row.get("field"), row.get("op", "equals")
        if field not in FIELDS:
            return f"unknown criteria field {field}"
        if op not in FIELD_OPS[field]:
            return f"{field}: unknown operator {op}"
        if field == "property" and not (isinstance(row.get("property"), str) and row["property"].strip()):
            return "a property row needs a property name (Name or Pset.Name)"
        if field == "kind" and row.get("value") not in G.KINDS:
            return f"unknown element kind {row.get('value')}"
        if field == "status" and row.get("value") not in G.STATUS_KEYS:
            return f"unknown renovation status {row.get('value')}"
        if "value" in row and (not isinstance(row["value"], (str, int, float)) or isinstance(row["value"], bool)):
            return f"{field}: the value must be text or a number"
    return None


def validate(key: str, value) -> str | None:
    if not isinstance(value, dict) or any(not isinstance(k, str) or not k.strip() for k in value):
        return f"{key} must map names to entries"
    if key == "selection_criteria":
        for name, c in value.items():
            if (err := _criteria_error(c)) is not None:
                return f"criteria {name}: {err}"
    elif key == "selection_sets":
        for name, guids in value.items():
            if not (isinstance(guids, list) and all(isinstance(g, str) for g in guids)):
                return f"selection set {name} must be a list of GlobalIds"
    return None


# ---------------------------------------------------------------- matching

class _Context:
    """File-wide facts a query needs, built once per query and only when a row asks: element -> type,
    element -> level (storey). One pass over the relationships, never a pass per element."""

    def __init__(self, model):
        self.model = model
        self._types = None
        self._storeys = None

    def type_of(self, e):
        if self._types is None:
            self._types = {}
            for rel in self.model.by_type("IfcRelDefinesByType"):
                for o in rel.RelatedObjects or ():
                    self._types[o.id()] = rel.RelatingType
        return self._types.get(e.id())

    def storey_of(self, e):
        if self._storeys is None:
            self._storeys = {}
            for rel in self.model.by_type("IfcRelContainedInSpatialStructure"):
                s = _storey_above(rel.RelatingStructure)
                if s is not None:
                    for o in rel.RelatedElements or ():
                        self._storeys[o.id()] = s
        s = self._storeys.get(e.id())
        if s is None:  # a part (stair flight, curtain wall panel) or a filling: its whole's level
            parent = ifcopenshell.util.element.get_aggregate(e) or _filled_host(e)
            if parent is not None and parent.is_a("IfcElement"):
                s = self._storeys.get(parent.id())
            if s is None and parent is None:
                s = _storey_above(ifcopenshell.util.element.get_container(e))
            self._storeys[e.id()] = s
        return s


def _storey_above(structure):
    while structure is not None and not structure.is_a("IfcBuildingStorey"):
        if structure.is_a("IfcBuilding") or structure.is_a("IfcSite") or structure.is_a("IfcProject"):
            return None
        structure = ifcopenshell.util.element.get_aggregate(structure)
    return structure


def _filled_host(e):
    for rel in getattr(e, "FillsVoids", None) or ():
        voids = rel.RelatingOpeningElement.VoidsElements
        if voids:
            return voids[0].RelatingBuildingElement
    return None


def _norm(v) -> str:
    return str(v).strip().lower()


def _compare(values: list, op: str, want) -> bool:
    """`values`: the element's texts for the field (several for materials); empty: it has none."""
    values = [v for v in values if v not in (None, "")]
    if op == "missing":
        return not values
    if op == "exists":
        return bool(values)
    w = _norm(want if want is not None else "")
    if op == "equals":
        return any(_norm(v) == w for v in values)
    if op == "not_equals":
        return not any(_norm(v) == w for v in values)
    if op == "contains":
        return any(w in _norm(v) for v in values)
    if op in ("less", "more"):
        b = G._float(want)
        return b is not None and any((a := G._float(v)) is not None and (a < b if op == "less" else a > b) for v in values)
    return False


def _row_matches(row: dict, e, facts, ctx: _Context) -> bool:
    field, op, want = row.get("field"), row.get("op", "equals"), row.get("value")
    if field in ("kind", "ifc_class"):  # D73's conditions, negated for "not equals"
        hit = G.matches({field: want}, e, facts)
        return hit if op == "equals" else not hit
    if field == "property":
        return G.matches({"property": row["property"].strip(), "op": op, "value": want}, e, facts)
    if field == "type":
        t = ctx.type_of(e)
        return _compare([t.Name] if t is not None else [], op, want)
    if field == "name":
        return _compare([getattr(e, "Name", None)], op, want)
    if field == "layer":
        return _compare([facts.layer], op, want)
    if field == "material":
        return _compare(facts.materials, op, want)
    if field == "level":
        s = ctx.storey_of(e)
        hit = s is not None and (s.GlobalId == want or _norm(s.Name or "") == _norm(want or ""))
        return hit if op == "equals" else not hit
    if field == "status":
        from . import renovation

        hit = renovation.status_of(e, facts) == want
        return hit if op == "equals" else not hit
    return False


def matches(criteria: dict, e, facts, ctx: _Context) -> bool:
    rows = criteria.get("rows", [])
    if not rows:
        return True
    hits = (_row_matches(r, e, facts, ctx) for r in rows)
    return all(hits) if criteria.get("match", "all") == "all" else any(hits)


def find(model, criteria: dict, scope: str = "model", level: str | None = None, selection=None,
         skip_layers=()) -> list[str]:
    """GlobalIds of the products in scope that meet the criteria, in file order. Elements on
    `skip_layers` (hidden or locked layers) are left out: they can't be selected."""
    ctx = _Context(model)
    if scope == "selection":
        candidates = []
        for g in selection or ():
            try:
                candidates.append(model.by_guid(g))
            except RuntimeError:
                pass
        candidates = [e for e in candidates if e.is_a("IfcProduct")]
    else:
        candidates = G._products(model)
    skip = {_norm(n) for n in skip_layers or ()}
    shared: dict = {}
    out = []
    for e in candidates:
        facts = G._Facts(e, shared)
        if skip and _norm(facts.layer or "") in skip and facts.layer is not None:
            continue
        if scope == "level":
            s = ctx.storey_of(e)
            if s is None or s.GlobalId != level:
                continue
        if matches(criteria, e, facts, ctx):
            out.append(e.GlobalId)
    return out


def _class_key(e) -> str:
    """IFC2X3's StandardCase/ElementedCase subclasses count as their base class."""
    cls = e.is_a()
    for suffix in ("StandardCase", "ElementedCase"):
        if cls.endswith(suffix) and cls != "Ifc" + suffix:
            return cls[: -len(suffix)]
    return cls


def similar(model, guids, mode: str = "type", skip_layers=()) -> list[str]:
    """Select similar (D78). "type": every element of the selected elements' IFC types; an untyped one
    brings the other untyped elements of its class and predefined type (annotations: and kind).
    "class": every element of the selected elements' classes. "class_predefined" (D92): every element of
    the same IFC class and predefined type."""
    ctx = _Context(model)
    picked = []
    for g in guids:
        try:
            picked.append(model.by_guid(g))
        except RuntimeError:
            pass
    types, keys, classes = set(), set(), set()
    for e in picked:
        t = ctx.type_of(e)
        if mode == "type" and t is not None:
            types.add(t.id())
        elif mode in ("type", "class_predefined"):
            keys.add(_untyped_key(e))
        classes.add(_class_key(e))
    skip = {_norm(n) for n in skip_layers or ()}
    shared: dict = {}
    out = []
    for cls in sorted(classes | {k[0] for k in keys}):
        for e in model.by_type(cls):  # subclasses too (IfcWallStandardCase); filtered by key below
            if _class_key(e) not in classes:
                continue
            if mode == "type":
                t = ctx.type_of(e)
                if not (t.id() in types if t is not None else _untyped_key(e) in keys):
                    continue
            elif mode == "class_predefined":
                if _untyped_key(e) not in keys:
                    continue
            if e.is_a("IfcAnnotation") and getattr(e, "ObjectType", None) == "DRAWING":
                continue
            if skip:
                layer = G._Facts(e, shared).layer
                if layer is not None and _norm(layer) in skip:
                    continue
            out.append(e.GlobalId)
    return list(dict.fromkeys(out))


def _untyped_key(e) -> tuple:
    predefined = ifcopenshell.util.element.get_predefined_type(e)
    kind = getattr(e, "ObjectType", None) if e.is_a("IfcAnnotation") else None
    return (_class_key(e), predefined, kind)


def choices(model, limit: int = 2000) -> dict:
    """What the Find & Select rows offer: the model's classes, type names, layers, levels, materials
    and property names (from the property sets in the file, one pass)."""
    if model is None:
        return {"kinds": list(G.KINDS), "classes": [], "types": [], "layers": [], "levels": [],
                "materials": [], "properties": [], "statuses": list(G.STATUS_KEYS)}
    classes = sorted({_class_key(e) for e in G._products(model)})
    types = sorted({t.Name for t in model.by_type("IfcTypeObject") if t.Name}, key=str.lower)
    layers = sorted({l.Name for l in model.by_type("IfcPresentationLayerAssignment") if l.Name}, key=str.lower)
    storeys = sorted(model.by_type("IfcBuildingStorey"),
                     key=lambda s: (getattr(s, "Elevation", None) or 0.0, s.Name or ""))
    materials = sorted({m.Name for m in model.by_type("IfcMaterial") if m.Name}, key=str.lower)
    props = set()
    for pset in model.by_type("IfcPropertySet"):
        for p in pset.HasProperties or ():
            props.add(f"{pset.Name}.{p.Name}")
            if len(props) >= limit:
                break
        if len(props) >= limit:
            break
    return {"kinds": list(G.KINDS), "classes": classes, "types": types[:limit], "layers": layers,
            "levels": [{"guid": s.GlobalId, "name": s.Name or ""} for s in storeys],
            "materials": materials[:limit], "properties": sorted(props, key=str.lower),
            "statuses": list(G.STATUS_KEYS)}


# ---------------------------------------------------------------- bridge

def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def find_elements(query_json: str) -> str:
    """query: {"match", "rows", "scope", "level", "selection", "skip_layers"} -> {"ok", "guids", "ms"}."""
    try:
        q = json.loads(query_json)
    except ValueError as ex:
        return _fail(f"bad input: {ex}")
    if B._model is None:
        return _fail("no model open")
    if not isinstance(q, dict) or (err := _criteria_error(q)) is not None:
        return _fail(err or "bad input: expected an object")
    scope = q.get("scope", "model")
    if scope not in SCOPES:
        return _fail(f"unknown scope {scope}")
    if scope == "level" and not q.get("level"):
        return _fail("no active level")
    t0 = time.perf_counter()
    try:
        guids = find(B._model, q, scope, q.get("level"), q.get("selection"), q.get("skip_layers", ()))
    except Exception as ex:  # an IFC this reader doesn't follow: report, keep the app usable
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "guids": guids, "ms": round((time.perf_counter() - t0) * 1000, 1)})


def similar_elements(guids_json: str, mode: str = "type", skip_layers_json: str = "[]") -> str:
    try:
        guids, skip = json.loads(guids_json), json.loads(skip_layers_json or "[]")
    except ValueError as ex:
        return _fail(f"bad input: {ex}")
    if B._model is None:
        return _fail("no model open")
    if mode not in SIMILAR:
        return _fail(f"unknown mode {mode} (type, class or class_predefined)")
    t0 = time.perf_counter()
    try:
        out = similar(B._model, guids, mode, skip)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "guids": out, "ms": round((time.perf_counter() - t0) * 1000, 1)})


def query_choices() -> str:
    try:
        return B._dump({"ok": True, **choices(B._model)})
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


def selection_set_members(name: str) -> str:
    """The saved set's GlobalIds still in the model (deleted elements drop out silently)."""
    from . import settings

    guids = settings.current().get("selection_sets", {}).get(name)
    if guids is None:
        return _fail(f"no selection set called {name}")
    if B._model is None:
        return _fail("no model open")
    found = []
    for g in guids:
        try:
            B._model.by_guid(g)
            found.append(g)
        except RuntimeError:
            pass
    return B._dump({"ok": True, "guids": found, "missing": len(guids) - len(found)})
