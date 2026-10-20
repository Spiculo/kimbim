# SPDX-License-Identifier: GPL-3.0-or-later
"""Model checking (D81, doc 14 §19): schema validation, IDS, clash detection and model checks.

Every check returns issues of one shape, {"severity", "message", "guids", "labels", "group"}, so the
Checks panel lists them the same way: by check, then by group (a validation rule, an IDS
specification, a clash set, a model check), then the issue; clicking one selects its elements.

- **Schema**: `ifcopenshell.validate` with the EXPRESS WHERE rules, the same call CI makes
  (tools/check_interop.py). A problem in a geometry or property entity is reported on the element
  that uses it.
- **IDS**: IfcTester (LGPL-3.0). The IDS files are stored *in* the project settings (`ids_files`:
  {name: XML}), so they are versioned, merged and travel with the .kim like the other tables (D72).
  The last run's results export to IfcTester's HTML or JSON report.
- **Clash**: IfcOpenShell's geometry tree (`ifcopenshell.geom.tree`, the same calls ifcclash makes:
  hard clashes = `clash_intersection_many` with a tolerance, clearance = `clash_clearance_many`)
  between two sets picked by IFC class, by a saved Find & Select criteria set (D78) or a selection
  set. Clash sets are the `clash_sets` project settings table.
- **Model** (Archicad/Solibri-lite): duplicate elements, rooms without a number or name, walls of
  zero length, elements not on a level, doors and windows without an opening in a host.

Same protocol as app_bridge for the bridge functions (strings in, JSON out, never raise). The app
runs `run_check` on a worker thread; `cancel_checks` (from the GUI thread) stops it.
"""
from __future__ import annotations

import ctypes
import json
import math
import threading
import time

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import ifcopenshell.util.unit

from . import app_bridge as B

CHECKS = ("schema", "ids", "clash", "model")
MODEL_CHECKS = ("duplicates", "rooms", "zero_walls", "not_on_level", "no_host")
CLASH_MODES = ("hard", "clearance")
MAX_ISSUES = 5000  # per check: beyond this the list says it was cut
# Never clash or count as elements: voids, virtual elements, rooms (they are volumes, not things)
NOT_PHYSICAL = ("IfcFeatureElement", "IfcVirtualElement", "IfcSpatialElement", "IfcSpatialStructureElement")


class Cancelled(Exception):
    pass


_cancel = False
_running: int | None = None  # the thread running a check
_last_ids: dict = {}  # name -> validated ifctester Ids, for the report


def _poll():
    if _cancel:
        raise Cancelled()


# ---------------------------------------------------------------- settings tables

def validate(key: str, value) -> str | None:
    if not isinstance(value, dict) or any(not isinstance(k, str) or not k.strip() for k in value):
        return f"{key} must map names to entries"
    if key == "ids_files":
        for name, xml in value.items():
            if not isinstance(xml, str) or "<" not in xml:
                return f"IDS {name} must be the XML text of the .ids file"
    elif key == "clash_sets":
        for name, c in value.items():
            if (err := _clash_set_error(c)) is not None:
                return f"clash set {name}: {err}"
    return None


def _side_error(side) -> str | None:
    if not isinstance(side, dict):
        return "a side must be an object"
    if "classes" in side:
        if not (isinstance(side["classes"], list) and side["classes"] and all(isinstance(c, str) and c.startswith("Ifc") for c in side["classes"])):
            return "classes must be a list of IFC class names"
    elif not any(isinstance(side.get(k), str) and side[k] for k in ("criteria", "selection_set")):
        return "a side needs classes, a criteria set or a selection set"
    return None


def _clash_set_error(c) -> str | None:
    if not isinstance(c, dict):
        return "must be an object"
    if (err := _side_error(c.get("a"))) is not None:
        return f"set A: {err}"
    if c.get("b") is not None and (err := _side_error(c["b"])) is not None:
        return f"set B: {err}"
    if c.get("mode", "hard") not in CLASH_MODES:
        return f"unknown mode {c.get('mode')} (hard or clearance)"
    for k in ("tolerance", "clearance"):
        v = c.get(k, 0.0)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 10:
            return f"{k} must be a distance in metres between 0 and 10"
    return None


# ---------------------------------------------------------------- shared helpers

def _label(e) -> str:
    if e is None:
        return ""
    name = getattr(e, "Name", None) if e.is_a("IfcRoot") else None
    if e.is_a("IfcSpace") and getattr(e, "LongName", None):
        name = f"{name or ''} {e.LongName}".strip()
    return f"{e.is_a()} {name}".strip() if name else f"{e.is_a()} #{e.id()}"


def _issue(severity, message, elements=(), group="") -> dict:
    elements = [e for e in elements if e is not None and hasattr(e, "GlobalId")]
    return {"severity": severity, "message": message, "guids": [e.GlobalId for e in elements],
            "labels": [_label(e) for e in elements[:5]], "group": group}


def _physical(e) -> bool:
    return e.is_a("IfcElement") and not any(e.is_a(c) for c in NOT_PHYSICAL)


def _owner(model, inst, budget: int = 400):
    """The product (or other rooted object) a problem entity belongs to: itself, or the nearest one
    that references it (a point -> its polyline -> ... -> the wall's shape -> the wall)."""
    if inst is None:
        return None
    if inst.is_a("IfcProduct"):
        return inst
    seen, queue = {inst.id()}, [inst]
    fallback = inst if inst.is_a("IfcRoot") else None
    while queue and budget > 0:
        nxt = []
        for x in queue:
            ups = list(model.get_inverse(x)) if x.id() else []
            if x.is_a("IfcRelationship"):  # a property set's relation: its objects
                for v in x:
                    ups.extend(v if isinstance(v, tuple) else [v])
            for u in ups:
                if not isinstance(u, ifcopenshell.entity_instance) or not u.id() or u.id() in seen:
                    continue
                if u.is_a("IfcProduct"):
                    return u
                if fallback is None and u.is_a("IfcRoot") and not u.is_a("IfcRelationship"):
                    fallback = u
                seen.add(u.id())
                nxt.append(u)
                budget -= 1
        queue = nxt
    return fallback


def _class_key(e) -> str:
    from .queries import _class_key as k

    return k(e)


# ---------------------------------------------------------------- schema validation

_rules_code: dict = {}


def _reuse_compiled_rules():
    """IfcOpenShell's rule executor parses, rewrites (pytest's assertion rewriter) and compiles the
    schema's rule module on every run: about 5 s, more than the rules take on a house. Keep the
    compiled module: its `ast.parse` and `compile` (module globals) are given a cache. If the
    executor changes shape, nothing is patched and it simply runs as before."""
    import ast

    try:
        from ifcopenshell.express import rule_executor as R
    except ImportError:
        return
    if getattr(R, "_kimbim_cache", False) or getattr(R, "ast", None) is not ast:
        return
    seen_sources: set = set()

    class _Ast:
        def __getattr__(self, name):
            return getattr(ast, name)

        @staticmethod
        def parse(source, *args, **kwargs):
            if isinstance(source, str) and hash(source) in seen_sources:
                return ast.Module(body=[], type_ignores=[])  # compiled already: nothing to rewrite
            seen_sources.add(hash(source)) if isinstance(source, str) else None
            return ast.parse(source, *args, **kwargs)

    def _compile(tree, filename, mode, *args, **kwargs):
        if isinstance(tree, ast.Module) and not tree.body and filename in _rules_code:
            return _rules_code[filename]
        code = compile(tree, filename, mode, *args, **kwargs)
        _rules_code[filename] = code
        return code

    R.ast, R.compile, R._kimbim_cache = _Ast(), _compile, True


def check_schema(model, options: dict) -> dict:
    import ifcopenshell.validate

    logger = ifcopenshell.validate.json_logger()
    express = bool(options.get("express_rules", True))
    _reuse_compiled_rules()
    # The validator and the rule executor switch global IfcOpenShell settings for the run; a cancel
    # (an exception in the middle) must not leave them switched.
    saved = (ifcopenshell.settings.unpack_non_aggregate_inverses, ifcopenshell.settings.compare_instances_by_value,
             ifcopenshell.ifcopenshell_wrapper.get_feature("use_attribute_value_derived"))
    try:
        ifcopenshell.validate.validate(model, logger, express_rules=express)
    finally:
        ifcopenshell.settings.unpack_non_aggregate_inverses, ifcopenshell.settings.compare_instances_by_value = saved[:2]
        ifcopenshell.ifcopenshell_wrapper.set_feature("use_attribute_value_derived", saved[2])
    _poll()
    issues, owners = [], {}
    for s in logger.statements:
        inst = s.get("instance")
        if not isinstance(inst, ifcopenshell.entity_instance):
            inst = None
        if inst is not None and inst.id() not in owners:
            owners[inst.id()] = _owner(model, inst)
        owner = owners.get(inst.id()) if inst is not None else None
        level = str(s.get("level", "error")).lower()
        message = " ".join(str(s.get("message", "")).split())
        if inst is not None:
            message = f"#{inst.id()}={inst.is_a()}: {message}"
        group =s.get("attribute") or _rule_name(str(s.get("message", ""))) or (s.get("type") or "") or "Schema"
        issues.append(_issue("warning" if level == "warning" else "error", message[:400],
                             [owner] if owner is not None else [], group))
    return {"issues": issues, "detail": "EXPRESS rules included" if express else "attributes and inverses only"}


def _rule_name(message: str) -> str:
    """The rule a rule-executor message is about ("Rule IfcWall.CorrectTypeAssigned violated ..")."""
    for word in message.replace("\n", " ").split():
        w = word.strip(".,:;'\"()")
        if w.startswith("Ifc") and "." in w:
            return w
    return ""


# ---------------------------------------------------------------- IDS (IfcTester)

def _ifctester():
    try:
        import ifctester.ids  # noqa: F401
        import ifctester.reporter  # noqa: F401
    except ImportError as ex:  # pragma: no cover - the env has it (pixi.toml)
        raise RuntimeError(f"IfcTester is not installed: {ex}") from ex
    return ifctester


def parse_ids(xml: str):
    t = _ifctester()
    return t.ids.from_string(xml)


def check_ids(model, options: dict) -> dict:
    from . import settings

    files = options.get("ids") if isinstance(options.get("ids"), dict) else settings.current().get("ids_files", {})
    _last_ids.clear()
    issues, groups = [], []
    if not files:
        return {"issues": [], "groups": [], "detail": "no IDS files: add one in the Checks panel", "empty": "no_ids"}
    for name, xml in files.items():
        _poll()
        try:
            ids = parse_ids(xml)
        except Exception as ex:
            issues.append(_issue("error", f"{name}: the IDS could not be read: {type(ex).__name__}: {str(ex)[:200]}", group=name))
            continue
        ids.validate(model, should_filter_version=True)
        _last_ids[name] = ids
        for spec in ids.specifications:
            _poll()
            group = f"{name} · {spec.name}"
            applicable, failed = len(spec.applicable_entities), len(spec.failed_entities)
            if spec.status is None:
                groups.append({"name": group, "status": "skip", "detail": f"not {model.schema}"})
                continue
            usage = spec.get_usage()
            if spec.status:
                groups.append({"name": group, "status": "pass", "detail": f"{applicable}/{applicable}"})
                continue
            groups.append({"name": group, "status": "fail",
                           "detail": f"{applicable - failed}/{applicable}"})
            if usage == "required" and not applicable:
                issues.append(_issue("error", "Required, but no element is applicable: "
                                     + "; ".join(a.to_string("applicability") for a in spec.applicability), group=group))
            elif usage == "prohibited" and applicable:
                for e in spec.applicable_entities:
                    issues.append(_issue("error", f"Prohibited: {_label(e)}", [_owner(model, e)], group))
            for facet in spec.requirements:
                try:
                    what = facet.to_string("requirement", spec, facet)
                except Exception:
                    what = type(facet).__name__
                for failure in facet.failures:
                    e = failure["element"]
                    issues.append(_issue("error", f"{_label(e)}: {failure['reason']} (requirement: {what})",
                                         [_owner(model, e)], group))
    return {"issues": issues, "groups": groups}


def ids_summary(xml: str) -> dict:
    ids = parse_ids(xml)
    return {"title": ids.info.get("title", ""), "specifications": len(ids.specifications)}


def write_ids_report(path: str) -> str:
    """The last IDS run as IfcTester's report: .json is its JSON reporter, anything else HTML."""
    t = _ifctester()
    if not _last_ids:
        raise RuntimeError("run the IDS check first")
    if len(_last_ids) == 1:
        ids = next(iter(_last_ids.values()))
    else:  # one report: the specifications of every file
        ids = t.ids.Ids(title=" + ".join(i.info.get("title") or n for n, i in _last_ids.items()))
        for i in _last_ids.values():
            ids.specifications.extend(i.specifications)
    ids.filepath = ids.filename = getattr(B, "_path", None) or None
    if path.lower().endswith(".json"):
        r = t.reporter.Json(ids)
    else:
        r = t.reporter.Html(ids)
    r.report()
    r.to_file(path)
    return path


# ---------------------------------------------------------------- clash detection

def _side_elements(model, side: dict) -> list:
    from . import queries, settings

    if "classes" in side:
        out = []
        for c in side["classes"]:
            try:
                out.extend(model.by_type(c))
            except RuntimeError:  # not a class of this schema
                pass
    elif side.get("criteria"):
        criteria = settings.current().get("selection_criteria", {}).get(side["criteria"])
        if criteria is None:
            raise RuntimeError(f"no criteria set called {side['criteria']}")
        out = [model.by_guid(g) for g in queries.find(model, criteria)]
    else:
        guids = settings.current().get("selection_sets", {}).get(side["selection_set"])
        if guids is None:
            raise RuntimeError(f"no selection set called {side['selection_set']}")
        out = []
        for g in guids:
            try:
                out.append(model.by_guid(g))
            except RuntimeError:
                pass
    return [e for e in dict.fromkeys(out) if _physical(e) and e.Representation is not None]


def _related_pairs(model) -> set:
    """Pairs that touch by design: a door or window and the wall it fills, a whole and its parts."""
    pairs = set()
    for rel in model.by_type("IfcRelFillsElement"):
        filling = rel.RelatedBuildingElement
        for v in rel.RelatingOpeningElement.VoidsElements or ():
            pairs.add(frozenset((filling.id(), v.RelatingBuildingElement.id())))
    for rel in model.by_type("IfcRelAggregates"):
        whole = rel.RelatingObject
        parts = list(rel.RelatedObjects or ())
        for p in parts:
            pairs.add(frozenset((whole.id(), p.id())))
    return pairs


_RAY = None


def _inside(points, tris) -> "np.ndarray":
    """Which points are inside a closed triangle mesh (tris: n x 3 x 3): ray casting, odd crossings.
    The ray is skewed so it does not run along the faces and edges of axis-aligned shapes."""
    import numpy as np

    global _RAY
    if _RAY is None:
        _RAY = np.array([0.5773, 0.5712, 0.5834]) / np.linalg.norm([0.5773, 0.5712, 0.5834])
    v0, e1, e2 = tris[:, 0], tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    h = np.cross(_RAY, e2)
    det = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(det) > 1e-12
    v0, e1, e2, h, det = v0[ok], e1[ok], e2[ok], h[ok], det[ok]
    inv = 1.0 / det
    out = np.zeros(len(points), dtype=bool)
    for k, p in enumerate(points):
        s = p - v0
        u = np.einsum("ij,ij->i", s, h) * inv
        q = np.cross(s, e1)
        v = (q @ _RAY) * inv
        t = np.einsum("ij,ij->i", e2, q) * inv
        out[k] = int(np.count_nonzero((u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9))) % 2 == 1
    return out


def _overlapping(meshes: dict, a, b, tolerance: float, known: set) -> list:
    """Hard clashes the tree's triangle test misses: shapes whose faces lie in the same planes (two
    walls of the same height overlapping along their length have coplanar tops and bottoms, so no
    triangle crosses another). Pairs whose boxes overlap by more than the tolerance in every
    direction are probed at points inside that overlap: one inside both shapes is a clash. Returns
    (a, b, depth) with depth the overlap's smallest extent."""
    import numpy as np

    ia = [e for e in a if e.id() in meshes]
    ib = [e for e in b if e.id() in meshes]
    if not ia or not ib:
        return []
    boxes_b = np.array([meshes[e.id()][1] for e in ib])  # n x 2 x 3
    grid = np.array([(x, y, z) for x in (0.23, 0.5, 0.77) for y in (0.19, 0.53, 0.81) for z in (0.27, 0.49, 0.73)])
    out = []
    for ea in ia:
        _poll()
        box_a = meshes[ea.id()][1]
        lo = np.maximum(box_a[0], boxes_b[:, 0]) + tolerance
        hi = np.minimum(box_a[1], boxes_b[:, 1]) - tolerance
        for j in np.nonzero(np.all(hi > lo, axis=1))[0]:
            eb = ib[int(j)]
            key = frozenset((ea.id(), eb.id()))
            if ea.id() == eb.id() or key in known:
                continue
            known.add(key)
            points = lo[j] + grid * (hi[j] - lo[j])
            both = _inside(points, meshes[ea.id()][0]) & _inside(points, meshes[eb.id()][0])
            if both.any():
                out.append((ea, eb, float(np.min(hi[j] - lo[j]) + 2 * tolerance)))
    return out


def clash(model, clash_set: dict, name: str = "") -> list[dict]:
    import multiprocessing

    import ifcopenshell.geom
    import numpy as np

    a = _side_elements(model, clash_set["a"])
    b = _side_elements(model, clash_set["b"]) if clash_set.get("b") else a
    if not a or not b:
        return []
    everything = list(dict.fromkeys(a + b))
    tree = ifcopenshell.geom.tree(backend="opencascade.trianglebvh")  # as ifcclash 0.9
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)  # metres, world: the probes below use the same triangles
    mode = clash_set.get("mode", "hard")
    meshes = {}
    it = ifcopenshell.geom.iterator(s, model, multiprocessing.cpu_count(), include=everything)
    if it.initialize():
        while True:
            shape = it.get()
            tree.add_element(shape)
            if mode == "hard":
                v = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
                f = np.asarray(shape.geometry.faces, dtype=np.int64).reshape(-1, 3)
                if len(f):
                    meshes[shape.id] = (v[f], np.array([v.min(axis=0), v.max(axis=0)]))
            if not it.next():
                break
            _poll()
    _poll()
    tolerance = float(clash_set.get("tolerance", 0.002))
    if mode == "clearance":
        results = tree.clash_clearance_many(a, b, clearance=float(clash_set.get("clearance", 0.05)), check_all=False)
    else:
        results = tree.clash_intersection_many(a, b, tolerance=tolerance, check_all=False)
    skip = _related_pairs(model)
    found = [(r.a, r.b, float(r.distance)) for r in results]
    if mode == "hard":
        known = set(skip) | {frozenset((x.id(), y.id())) for x, y, _d in found}
        found += _overlapping(meshes, a, b, tolerance, known)
    issues, seen = [], set()
    for ea, eb, distance in found:
        key = frozenset((ea.id(), eb.id()))
        if ea.id() == eb.id() or key in seen or key in skip:
            continue
        seen.add(key)
        d = abs(distance) * 1000.0
        if mode == "clearance":
            text = f"{_label(ea)} and {_label(eb)} are {d:.0f} mm apart (clearance {float(clash_set.get('clearance', 0.05)) * 1000:.0f} mm)"
        else:
            text = f"{_label(ea)} and {_label(eb)} intersect ({d:.0f} mm)"
        issues.append(_issue("warning" if mode == "clearance" else "error", text, [ea, eb], name))
    return issues


def check_clash(model, options: dict) -> dict:
    from . import settings

    sets = options.get("clash_sets") if isinstance(options.get("clash_sets"), dict) else settings.current().get("clash_sets", {})
    if not sets:
        return {"issues": [], "groups": [], "detail": "no clash sets: add one in the Checks panel", "empty": "no_clash_sets"}
    issues, groups = [], []
    for name, c in sets.items():
        _poll()
        if (err := _clash_set_error(c)) is not None:
            issues.append(_issue("error", f"{name}: {err}", group=name))
            continue
        found = clash(model, c, name)
        groups.append({"name": name, "status": "fail" if found else "pass", "detail": str(len(found))})
        issues.extend(found)
    return {"issues": issues, "groups": groups}


# ---------------------------------------------------------------- model checks

def _fingerprint(x, memo: dict, budget: list):
    """A comparable value for a representation: entities by class and attributes (numbers rounded),
    shared entities by identity. Big shapes (over the budget) only compare equal when identical."""
    if isinstance(x, ifcopenshell.entity_instance):
        if not x.id():
            return (x.is_a(), _fingerprint(x.wrappedValue, memo, budget))
        if x.id() in memo:
            return memo[x.id()]
        budget[0] -= 1
        if budget[0] < 0:
            return ("#", x.id())
        memo[x.id()] = ("#", x.id())  # cycles
        fp = (x.is_a(),) + tuple(_fingerprint(v, memo, budget) for v in x)
        memo[x.id()] = fp
        return fp
    if isinstance(x, tuple):
        return tuple(_fingerprint(v, memo, budget) for v in x)
    if isinstance(x, float):
        return round(x, 6)
    return x


def _duplicates(model, elements, unit: float) -> list[dict]:
    from .queries import _Context

    ctx = _Context(model)
    buckets: dict = {}
    for e in elements:
        _poll()
        if e.ObjectPlacement is None or e.Representation is None:
            continue
        m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
        place = tuple(round(float(v) * (unit if i % 4 == 3 and i < 12 else 1.0), 3) for i, v in enumerate(m.flatten()))
        t = ctx.type_of(e)
        buckets.setdefault((_class_key(e), t.id() if t is not None else None, place), []).append(e)
    issues = []
    for (cls, _t, _p), group in buckets.items():
        if len(group) < 2:
            continue
        by_shape: dict = {}
        for e in group:
            memo, budget = {}, [20000]
            by_shape.setdefault(_fingerprint(e.Representation, memo, budget), []).append(e)
        for same in by_shape.values():
            if len(same) > 1:
                names = ", ".join(_label(e) for e in same[:4])
                issues.append(_issue("warning", f"{len(same)} {cls} elements in the same place with the same shape: {names}",
                                     same, "Duplicate elements"))
    return issues


def _rooms(model) -> list[dict]:
    issues = []
    for s in model.by_type("IfcSpace"):
        missing = [w for w, v in (("number", s.Name), ("name", getattr(s, "LongName", None))) if not (v or "").strip()]
        if missing:
            issues.append(_issue("warning", f"{_label(s)} has no {' and no '.join(missing)}", [s], "Rooms without a number or name"))
    return issues


def _curve_length(c, unit: float) -> float | None:
    if c.is_a("IfcPolyline"):
        pts = [p.Coordinates for p in c.Points]
    elif c.is_a("IfcIndexedPolyCurve"):
        pts = list(c.Points.CoordList)
    elif c.is_a("IfcTrimmedCurve") and c.BasisCurve.is_a("IfcLine"):
        t = [x for x in c.Trim1 if isinstance(x, ifcopenshell.entity_instance)], [x for x in c.Trim2 if isinstance(x, ifcopenshell.entity_instance)]
        if t[0] and t[1]:
            pts = [t[0][0].Coordinates, t[1][0].Coordinates]
        else:
            p1 = [x.wrappedValue if isinstance(x, ifcopenshell.entity_instance) else x for x in c.Trim1]
            p2 = [x.wrappedValue if isinstance(x, ifcopenshell.entity_instance) else x for x in c.Trim2]
            try:
                mag = c.BasisCurve.Dir.Magnitude
                return abs(float(p2[0]) - float(p1[0])) * mag * unit
            except (IndexError, TypeError, ValueError):
                return None
    else:
        return None
    return sum(math.dist(pts[i][:2], pts[i + 1][:2]) for i in range(len(pts) - 1)) * unit


def _wall_length(w, unit: float) -> float | None:
    axis = ifcopenshell.util.representation.get_representation(w, "Model", "Axis")
    if axis is not None:
        for item in axis.Items:
            length = _curve_length(item, unit)
            if length is not None:
                return length
    q = ifcopenshell.util.element.get_psets(w, qtos_only=True)
    for name in ("Qto_WallBaseQuantities", "BaseQuantities"):
        if (v := q.get(name, {}).get("Length")) is not None:
            return float(v) * unit
    body = ifcopenshell.util.representation.get_representation(w, "Model", "Body")
    for item in getattr(body, "Items", None) or ():
        if item.is_a("IfcExtrudedAreaSolid") and item.SweptArea.is_a("IfcRectangleProfileDef"):
            return float(item.SweptArea.XDim) * unit
    return None


def _zero_walls(model, unit: float) -> list[dict]:
    issues = []
    for w in model.by_type("IfcWall"):
        _poll()
        length = _wall_length(w, unit)
        if length is not None and length < 0.001:
            issues.append(_issue("error", f"{_label(w)} has zero length", [w], "Walls with zero length"))
    return issues


def _not_on_level(model, elements) -> list[dict]:
    from .queries import _Context

    ctx = _Context(model)
    out = []
    for e in elements:
        _poll()
        if ctx.storey_of(e) is None:
            container = ifcopenshell.util.element.get_container(e)
            where = f"it is in {_label(container)}" if container is not None else "it is in no spatial structure"
            out.append(_issue("warning", f"{_label(e)} is not on a level ({where})", [e], "Elements not on a level"))
    return out


def _no_host(model) -> list[dict]:
    out = []
    for cls in ("IfcDoor", "IfcWindow"):
        for e in model.by_type(cls):
            if getattr(e, "FillsVoids", None):
                continue
            if ifcopenshell.util.element.get_aggregate(e) is not None:  # a curtain wall's door or window
                continue
            out.append(_issue("warning", f"{_label(e)} is not in an opening of a wall or slab", [e], "Doors and windows without a host"))
    return out


def check_model(model, options: dict) -> dict:
    which = options.get("model_checks") or MODEL_CHECKS
    unit = ifcopenshell.util.unit.calculate_unit_scale(model)
    elements = [e for e in model.by_type("IfcElement") if _physical(e)]
    issues, groups = [], []
    timings = {}
    for name, title, run in (
        ("duplicates", "Duplicate elements", lambda: _duplicates(model, elements, unit)),
        ("rooms", "Rooms without a number or name", lambda: _rooms(model)),
        ("zero_walls", "Walls with zero length", lambda: _zero_walls(model, unit)),
        ("not_on_level", "Elements not on a level", lambda: _not_on_level(model, elements)),
        ("no_host", "Doors and windows without a host", lambda: _no_host(model)),
    ):
        if name not in which:
            continue
        _poll()
        t0 = time.perf_counter()
        found = run()
        timings[name] = round(time.perf_counter() - t0, 3)
        groups.append({"name": title, "status": "fail" if found else "pass", "detail": str(len(found))})
        issues.extend(found)
    return {"issues": issues, "groups": groups, "timings": timings}


RUNNERS = {"schema": check_schema, "ids": check_ids, "clash": check_clash, "model": check_model}
TITLES = {"schema": "Schema validation", "ids": "IDS", "clash": "Clash detection", "model": "Model checks"}


def run(model, name: str, options: dict | None = None) -> dict:
    t0 = time.perf_counter()
    out = RUNNERS[name](model, options or {})
    issues = out["issues"]
    counts = {k: sum(1 for i in issues if i["severity"] == k) for k in ("error", "warning", "info")}
    cut = len(issues) > MAX_ISSUES
    return {"ok": True, "check": name, "title": TITLES[name], "issues": issues[:MAX_ISSUES], "truncated": cut,
            "total": len(issues), "groups": out.get("groups", []), "counts": counts, "detail": out.get("detail", ""),
            "timings": out.get("timings", {}), "empty": out.get("empty", ""), "seconds": round(time.perf_counter() - t0, 3)}


# ---------------------------------------------------------------- bridge

def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def run_check(name: str, options_json: str = "{}") -> str:
    """One check on the open model -> {"ok", "check", "title", "issues", "groups", "counts", "seconds"}."""
    global _cancel, _running
    try:
        options = json.loads(options_json or "{}")
    except ValueError as ex:
        return _fail(f"bad input: {ex}")
    if name not in RUNNERS:
        return _fail(f"unknown check {name} ({', '.join(CHECKS)})")
    if B._model is None:
        return _fail("no model open")
    try:
        _cancel = False
        _running = threading.get_ident()
        try:
            return B._dump(run(B._model, name, options if isinstance(options, dict) else {}))
        except Cancelled:
            raise
        except Exception as ex:  # an IFC this checker doesn't follow: report, keep the app usable
            return _fail(f"{type(ex).__name__}: {ex}")
        finally:
            _running = None
    except Cancelled:
        _running = None
        return B._dump({"ok": False, "cancelled": True, "error": "cancelled"})


def cancel_checks() -> str:
    """Stop the running check: a flag the loops read, and an exception raised in the running thread so
    long pure-Python passes (schema validation) stop too."""
    global _cancel
    _cancel = True
    tid = _running
    if tid is not None:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), ctypes.py_object(Cancelled))
    return B._dump({"ok": True, "running": tid is not None})


def read_ids_file(path: str) -> str:
    """An .ids file's XML and summary, for adding it to the project settings (`ids_files`)."""
    import pathlib

    p = pathlib.Path(path)
    try:
        xml = p.read_text(encoding="utf-8-sig")
    except OSError as ex:
        return _fail(f"could not read {path}: {ex}")
    try:
        summary = ids_summary(xml)
    except Exception as ex:
        return _fail(f"{p.name} is not a valid IDS file: {type(ex).__name__}: {str(ex)[:300]}")
    return B._dump({"ok": True, "name": p.name, "xml": xml, **summary})


def export_ids_report(path: str) -> str:
    try:
        return B._dump({"ok": True, "path": write_ids_report(path)})
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


def _write_sample_house(path: str) -> str:
    """The M3 sample house (tools/make_house.py) saved to `path`, for the app's Qt tests (dev tree only)."""
    import pathlib
    import sys

    tools = pathlib.Path(__file__).resolve().parents[2] / "tools"
    if not (tools / "make_house.py").exists():
        return _fail("tools/make_house.py is not here (not a source tree)")
    try:
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        import make_house

        return B._dump({"ok": True, **make_house.build(path)})
    except BaseException as ex:  # make_house exits on failure
        return _fail(f"{type(ex).__name__}: {ex}")
