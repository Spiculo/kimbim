# SPDX-License-Identifier: GPL-3.0-or-later
"""Keynotes (doc 14 §13): a reusable table of codes and texts, and keynote annotations on plans.

The table is the `keynotes` project setting, by code: {"A-1": {"code", "text", "category"}}. A keynote
annotation is an ordinary plan annotation (annotations, D59): an IfcAnnotation on a level with an
Annotation2D representation whose text is "[code] text"; the code is kept in its KIMBIM_Annotation
property set (`Keynote`), so a table edit can bring every placed keynote up to date
(`update_keynote_annotations`). A keynote with a leader is a leader annotation (arrow tip, then the
text position), so the same moving, editing, layers and undo apply. Same protocol as app_bridge.
"""
from __future__ import annotations

import json
import math

import ifcopenshell.api.pset
import ifcopenshell.util.element

from . import annotations as N
from . import app_bridge as B
from . import authoring as A
from . import settings

KEY = "keynotes"  # the project settings key: {code: {"code", "text", "category"}}
PSET = N.PSET
CODE_FIELD = "Keynote"
MAX_CODE = 40


# ---------------------------------------------------------------- the table

def _stored(table: dict | None = None) -> dict:
    """The project's keynote table, by code, with only the well-formed entries."""
    from . import settings as St

    data = (table if table is not None else St.current()).get(KEY) or {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        code = str(key or "").strip()
        text = str(entry.get("text") or "").strip()
        if not code or not text:
            continue
        out[code] = {"code": code, "text": text, "category": str(entry.get("category") or "").strip()}
    return out


def _label(entry: dict) -> str:
    """What a keynote annotation shows: its code in brackets, then the table's text."""
    return f"[{entry['code']}] {entry['text']}"


def _write(entries: dict) -> str:
    """Store the table (project settings); the response as the bridge returns it."""
    try:
        return settings.set_project_settings(json.dumps({KEY: entries}))
    except (TypeError, ValueError) as ex:  # the table is JSON: never leave it half-set
        return A._fail(f"bad keynote table: {ex}")


def keynote_table() -> str:
    """The project's keynotes: [{code, text, category}], sorted by code."""
    rows = sorted(_stored().values(), key=lambda e: e["code"].casefold())
    return B._dump({"ok": True, "keynotes": rows})


def save_keynote(code: str, text: str, category: str = "") -> str:
    """Add or change a keynote in the table (its code is required). Placed keynotes follow when
    `update_keynote_annotations` runs."""
    code = str(code or "").strip()
    if not code:
        return A._fail("type the keynote code")
    if len(code) > MAX_CODE:
        return A._fail(f"a keynote code is at most {MAX_CODE} characters")
    text = str(text or "").strip()
    if not text:
        return A._fail("type the keynote text")
    entry = {"code": code, "text": text, "category": str(category or "").strip()}
    r = json.loads(_write({**_stored(), code: entry}))
    if not r.get("ok"):
        return B._dump(r)
    return B._dump({"ok": True, "keynote": entry})


def delete_keynote(code: str) -> str:
    """Remove a keynote from the table. Keynotes already placed keep the text they show."""
    code = str(code or "").strip()
    stored = _stored()
    if code not in stored:
        return A._fail(f"no keynote {code}" if code else "type the keynote code")
    r = json.loads(_write({k: v for k, v in stored.items() if k != code}))
    if not r.get("ok"):
        return B._dump(r)
    return B._dump({"ok": True, "code": code})


# ---------------------------------------------------------------- the annotations

def _options(options_json: str):
    try:
        o = json.loads(options_json) if options_json else {}
    except ValueError:
        return None
    return o if isinstance(o, dict) else None


def _pair(v):
    try:
        return float(v[0]), float(v[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None


def _code_of(annotation) -> str:
    data = ifcopenshell.util.element.get_pset(annotation, PSET) or {}
    code = data.get(CODE_FIELD)
    return str(code).strip() if code else ""


def _mark(annotation, code: str) -> None:
    """Inside an action: keep the keynote's code in its property set (the representation is unchanged)."""
    f = B._model
    pset = ifcopenshell.util.element.get_pset(annotation, PSET)
    pset = f.by_id(pset["id"]) if pset else ifcopenshell.api.pset.add_pset(f, product=annotation, name=PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={CODE_FIELD: code})


def place_keynote(level_guid: str, x, y, code: str, options_json: str = "") -> str:
    """Place keynote `code` on a level with its text at (x, y), world metres. options: {leader: [x2, y2],
    size (mm on paper)}. With a leader the arrow tip goes at [x2, y2] and the text at (x, y). One undo
    step; returns the annotation's GlobalId."""
    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(level_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    code = str(code or "").strip()
    entry = _stored().get(code)
    if entry is None:
        return A._fail(f"no keynote {code}" if code else "choose a keynote")
    o = _options(options_json)
    if o is None:
        return A._fail("bad options")
    try:
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        return A._fail("bad point")
    size = o.get("size")
    if size is not None:
        try:
            size = float(size)
        except (TypeError, ValueError):
            return A._fail("bad text size")
        if not 0.5 <= size <= 50:
            return A._fail("the size must be between 0.5 and 50 mm")
    tip = None
    if o.get("leader") is not None:
        tip = _pair(o["leader"])
        if tip is None:
            return A._fail("the leader must be a point [x, y]")
        if math.dist(tip, (x, y)) < 1e-6:
            return A._fail("the leader needs a point away from the text")
    label = _label(entry)
    kind = "leader" if tip is not None else "text"
    local = [(tip[0] - x, tip[1] - y), (0.0, 0.0)] if tip is not None else [(0.0, 0.0)]
    made = {}

    def action():
        annotation = N._new(storey, kind, label, (x, y), local)
        if size is None:
            _mark(annotation, code)  # _new already wrote the label and the representation
        else:
            N._set(annotation, kind, label, local, size, extra={CODE_FIELD: code})
            annotation.Name = label[:60]
        made["guid"] = annotation.GlobalId
        return 1, [annotation.GlobalId], []

    r = B._run(action)
    return B._dump({**r, "guid": made["guid"], "annotation": {
        "guid": made["guid"], "kind": kind, "code": code, "text": label,
        "points": [[round(tip[0], 6), round(tip[1], 6)], [round(x, 6), round(y, 6)]] if tip is not None
        else [[round(x, 6), round(y, 6)]]}})


def update_keynote_annotations() -> str:
    """Rewrite every placed keynote's text from the current table (a code no longer in the table keeps
    its text). One undo step; returns the count and the GlobalIds that changed."""
    if B._model is None:
        return A._fail("no model open")
    stored = _stored()
    todo = []
    for annotation in B._model.by_type("IfcAnnotation"):
        code = _code_of(annotation)
        if not code or code not in stored:
            continue
        data = N._read(annotation)
        if data is None:
            continue
        label = _label(stored[code])
        if data[1] != label:
            todo.append((annotation, label, data[2], data[3], data[4]))
    changed = []

    def action():
        for annotation, label, local, size, pen in todo:
            N._set(annotation, N._read(annotation)[0], label, local, size, pen,
                   extra={CODE_FIELD: _code_of(annotation)})
            annotation.Name = label[:60]
            changed.append(annotation.GlobalId)
        return len(changed), list(changed), []

    r = B._run(action) if todo else {"ok": True, "changed": 0, "geometry": {"changed": [], "removed": []}}
    return B._dump({**r, "updated": len(changed), "guids": changed})
