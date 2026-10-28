# SPDX-License-Identifier: GPL-3.0-or-later
"""Import reconciliation (R4, docs/03-versioning.md#import-reconciliation).

An IFC re-exported from another tool may keep its objects but hand them new GlobalIds, which would
otherwise look like deleting everything and adding it again. This module matches the imported
products to the objects already in the project, strongest first:

1. the same GlobalId;
2. the same IFC class and authoring-tool Tag (Revit's element id, for example);
3. a heuristic score from the class, Tag, name, type, storey and placement (nearby placement).

The matches are then applied by giving the imported objects the existing GlobalIds, so the ordinary
commit that follows is a small diff and the objects keep their history. Heuristic matches carry a
score and are only applied when the caller accepts them.
"""
from __future__ import annotations

import ifcopenshell.util.element
import ifcopenshell.util.placement

THRESHOLD = 0.7
MAX_REPORT = 5000
_WEIGHTS = {"class": 0.2, "tag": 0.5, "name": 0.25, "type": 0.15, "storey": 0.15, "place": 0.2}
_SPATIAL = ("IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcSpace", "IfcSpatialZone",
            "IfcExternalSpatialElement")


def _label(e) -> str:
    return f"{e.is_a()} {getattr(e, 'Name', None) or ''}".strip()


def _tag(e) -> str:
    value = getattr(e, "Tag", None)
    return value.strip() if isinstance(value, str) else ""


def _name(e) -> str:
    name = getattr(e, "Name", None) or ""
    return name.strip().lower()


def _type_name(e) -> str:
    try:
        t = ifcopenshell.util.element.get_type(e)
    except Exception:
        t = None
    return ((t.Name or "") if t is not None else "").strip().lower()


def _storey(e) -> str:
    try:
        c = ifcopenshell.util.element.get_container(e)
    except Exception:
        c = None
    while c is not None and not c.is_a("IfcBuildingStorey"):
        try:
            c = ifcopenshell.util.element.get_container(c)
        except Exception:
            c = None
    return ((c.Name or c.GlobalId) if c is not None else "").strip().lower()


def _place(e):
    placement = getattr(e, "ObjectPlacement", None)
    if placement is None:
        return None
    try:
        m = ifcopenshell.util.placement.get_local_placement(placement)
        return (round(float(m[0][3]), 2), round(float(m[1][3]), 2), round(float(m[2][3]), 2))
    except Exception:
        return None


def _features(e) -> dict:
    return {"class": e.is_a(), "tag": _tag(e), "name": _name(e), "type": _type_name(e),
            "storey": _storey(e), "place": _place(e)}


def _score(a: dict, b: dict) -> float:
    if a["class"] != b["class"]:
        return 0.0
    score = _WEIGHTS["class"]
    for key in ("tag", "name", "type", "storey"):
        if a[key] and a[key] == b[key]:
            score += _WEIGHTS[key]
    if a["place"] is not None and b["place"] is not None:
        if a["place"] == b["place"]:
            score += _WEIGHTS["place"]
        else:
            d = sum((x - y) ** 2 for x, y in zip(a["place"], b["place"])) ** 0.5
            if d <= 0.05:  # the same place after rounding, or a tiny re-export difference
                score += _WEIGHTS["place"] * 0.75
            elif d <= 0.5:
                score += _WEIGHTS["place"] * 0.5
    # A site, building or storey is identified by its class and name: it has no type or host.
    if a["class"] in _SPATIAL and a["name"]:
        score = max(score, 0.8)
    return round(score, 3)


def _entry(e, how: str, score: float = 0.0) -> dict:
    return {"new": e.GlobalId, "old": "", "how": how, "score": score, "label": _label(e)}


def reconcile(old_model, new_model, accept_heuristic: bool = False) -> dict:
    """Match the products of `new_model` to `old_model`.

    Returns the report and, in `applied`, the mapping (new GlobalId -> old GlobalId) to give the
    imported objects before committing. Heuristic matches are reported but are in `applied` only
    when `accept_heuristic` is true.
    """
    old = [e for e in old_model.by_type("IfcProduct") if getattr(e, "GlobalId", None)]
    new = [e for e in new_model.by_type("IfcProduct") if getattr(e, "GlobalId", None)]
    old_by_guid = {e.GlobalId: e for e in old}
    new_by_guid = {e.GlobalId: e for e in new}
    matched_old: set[str] = set()
    matches: dict[str, dict] = {}
    by_globalid, by_tag, heuristic = [], [], []

    for e in new:  # 1. the same GlobalId
        if e.GlobalId in old_by_guid:
            matches[e.GlobalId] = {"new": e.GlobalId, "old": e.GlobalId, "how": "globalid", "score": 1.0,
                                   "label": _label(e)}
            matched_old.add(e.GlobalId)
            by_globalid.append(matches[e.GlobalId])

    old_features = {e.GlobalId: _features(e) for e in old}
    remaining = [e for e in new if e.GlobalId not in matches]
    # 2. the same class and Tag. Tags are usually unique; if they are not, the best score wins.
    by_tag_old: dict[tuple[str, str], list] = {}
    for e in old:
        f = old_features[e.GlobalId]
        if f["tag"] and e.GlobalId not in matched_old:
            by_tag_old.setdefault((f["class"], f["tag"]), []).append(e)
    for e in sorted(remaining, key=lambda x: (x.is_a(), _tag(x), _name(x))):
        f = _features(e)
        if not f["tag"]:
            continue
        candidates = [c for c in by_tag_old.get((f["class"], f["tag"]), ()) if c.GlobalId not in matched_old]
        if not candidates:
            continue
        best = max(candidates, key=lambda c: _score(f, old_features[c.GlobalId]))
        matches[e.GlobalId] = {"new": e.GlobalId, "old": best.GlobalId, "how": "tag",
                               "score": _score(f, old_features[best.GlobalId]), "label": _label(e)}
        matched_old.add(best.GlobalId)
        by_tag.append(matches[e.GlobalId])

    remaining = [e for e in new if e.GlobalId not in matches]
    # 3. the heuristic. Candidate buckets keep this near-linear on large models.
    buckets: dict[tuple, list] = {}
    for e in old:
        if e.GlobalId in matched_old:
            continue
        f = old_features[e.GlobalId]
        for key in (("name", f["class"], f["type"], f["name"]) if f["name"] else None,
                    ("place", f["class"], f["storey"], f["place"]) if f["place"] else None):
            if key is not None:
                buckets.setdefault(key, []).append(e)
    pairs = []
    for e in remaining:
        f = _features(e)
        candidates = {}
        for key in (("name", f["class"], f["type"], f["name"]) if f["name"] else None,
                    ("place", f["class"], f["storey"], f["place"]) if f["place"] else None):
            for c in buckets.get(key, ()) if key is not None else ():
                candidates[c.GlobalId] = c
        for c in candidates.values():
            score = _score(f, old_features[c.GlobalId])
            if score >= THRESHOLD:
                pairs.append((score, e.GlobalId, c.GlobalId))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    for score, new_guid, old_guid in pairs:
        if new_guid in matches or old_guid in matched_old:
            continue
        e, c = new_by_guid[new_guid], old_by_guid[old_guid]
        matches[new_guid] = {"new": new_guid, "old": old_guid, "how": "heuristic", "score": score,
                             "label": _label(e)}
        matched_old.add(old_guid)
        heuristic.append(matches[new_guid])

    # Apply: the imported objects take the existing GlobalIds, unless that id still belongs to an
    # unmatched imported object (then the identity cannot be moved safely).
    applied, skipped = {}, []
    taken = set(new_by_guid)
    for new_guid, match in matches.items():
        old_guid = match["old"]
        if old_guid == new_guid:
            continue
        if match["how"] == "heuristic" and not accept_heuristic:
            continue
        if old_guid in taken and old_guid != new_guid:
            skipped.append({**match, "reason": "the GlobalId is still used by another imported object"})
            continue
        applied[new_guid] = old_guid
        taken.discard(new_guid)
        taken.add(old_guid)

    matched_old = {m["old"] for m in matches.values() if m["new"] in applied or m["old"] == m["new"]}
    matched_new = {m["new"] for m in matches.values() if m["new"] in applied or m["old"] == m["new"]}
    unmatched = [{"new": e.GlobalId, "label": _label(e)} for e in new if e.GlobalId not in matched_new]
    missing = [{"old": e.GlobalId, "label": _label(e)} for e in old if e.GlobalId not in matched_old]
    identity = len(matched_new) / len(new) if new else 1.0
    counts = {"globalid": len(by_globalid), "tag": len(by_tag),
              "heuristic": len(heuristic) if accept_heuristic else 0,
              "heuristic_review": 0 if accept_heuristic else len(heuristic),
              "new": len(unmatched), "deleted": len(missing),
              "changed": len(applied), "skipped": len(skipped)}
    report = {"ok": True, "counts": counts, "identity_rate": round(identity, 4),
              "accepted_heuristic": bool(accept_heuristic),
              "by_globalid": by_globalid[:MAX_REPORT], "by_tag": by_tag[:MAX_REPORT],
              "heuristic": heuristic[:MAX_REPORT], "unmatched": unmatched[:MAX_REPORT],
              "missing": missing[:MAX_REPORT], "skipped": skipped[:MAX_REPORT],
              "truncated": any(len(x) > MAX_REPORT for x in (by_globalid, by_tag, heuristic, unmatched, missing)),
              "applied": applied}
    return report
