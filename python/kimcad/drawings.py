# SPDX-License-Identifier: GPL-3.0-or-later
"""Sections and elevations in the app (Slice 14, D60/D61). Same protocol as app_bridge.

A drawing is model data (an IfcAnnotation DRAWING, see drawgen); its SVG is a cache keyed by the
model state, never model data. Generation runs in a child Python process from a snapshot of the
model, because IfcOpenShell's SVG serializer holds the GIL for seconds on real files (spike S6).
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import ifcopenshell.api.root
import ifcopenshell.util.element

from . import app_bridge as B
from . import authoring as A
from . import drawgen as G

SIDES = ("north", "south", "east", "west")
_CACHE_SIZE = 4  # model states remembered per drawing (undo/redo returns to cached ones)
_cache: dict[str, dict[tuple, str]] = {}


def _state_key() -> tuple:
    return id(B._model), B._current_id()


def _drawings():
    return [a for a in B._model.by_type("IfcAnnotation") if G.is_drawing(a) and G.settings_of(a) is not None]


def _drawing(guid: str):
    d = A._by_guid(guid) if B._model is not None else None
    return d if d is not None and G.is_drawing(d) and G.settings_of(d) is not None else None


def drawings() -> str:
    """[{guid, name, kind, depth (metres, null = infinite), auto, points, look, stale}]"""
    out = []
    if B._model is not None:
        key = _state_key()
        for d in _drawings():
            s = G.settings_of(d)
            out.append({"guid": d.GlobalId, "name": d.Name or "", "kind": s["kind"], "depth": s["depth"],
                        "auto": s["auto"], "points": s["points"], "look": s["look"],
                        "stale": not any(k[:2] == key for k in _cache.get(d.GlobalId, {}))})
        out.sort(key=lambda d: (d["kind"] != "elevation", d["name"]))
    return B._dump({"drawings": out})


def _new(name: str, s: dict):
    f = B._model
    drawing = ifcopenshell.api.root.create_entity(f, ifc_class="IfcAnnotation", name=name)
    drawing.ObjectType = "DRAWING"
    G.write_settings(f, drawing, s)
    G.place(f, drawing, s, G.model_bounds(f))
    return drawing


def create_template_elevations():
    """North, South, East and West elevations of a new project (D61, Archicad's default template).
    Called by new_project before its history starts, so they are part of the empty project."""
    bounds = G.model_bounds(B._model)
    for side in SIDES:
        points, look = G.auto_marker(side, bounds)
        _new(f"{side.capitalize()} Elevation",
             {"kind": "elevation", "points": points, "look": look, "depth": None, "auto": True, "side": side})


def create_elevations() -> str:
    """Add the North/South/East/West elevations a model is missing (an opened IFC has none), fitted
    to the model like a new project's template elevations. One undoable step."""
    if B._model is None:
        return A._fail("no model open")
    have = {G.settings_of(d).get("side") for d in _drawings()}
    missing = [side for side in SIDES if side not in have]

    def action():
        bounds = G.model_bounds(B._model)
        for side in missing:
            points, look = G.auto_marker(side, bounds)
            _new(f"{side.capitalize()} Elevation",
                 {"kind": "elevation", "points": points, "look": look, "depth": None, "auto": True, "side": side})
        return len(missing)

    if not missing:
        return B._dump({"ok": True, "created": 0})
    return B._dump({**B._run(action), "created": len(missing)})


def _next_name(prefix: str) -> str:
    taken = {d.Name for d in _drawings()}
    n = 1
    while f"{prefix} {n}" in taken:
        n += 1
    return f"{prefix} {n}"


def _create(kind, x1, y1, x2, y2, look_x, look_y, depth) -> str:
    if B._model is None:
        return A._fail("no model open")
    try:
        points = [[float(x1), float(y1)], [float(x2), float(y2)]]
        look = [float(look_x), float(look_y)]
        depth = float(depth)
    except (TypeError, ValueError) as ex:
        return A._fail(f"bad input: {ex}")
    if math.dist(*points) < 1e-6:
        return A._fail("draw the line with two different points")
    s = {"kind": kind, "points": points, "look": look, "depth": None if depth < 0 else depth, "auto": False}
    made = {}

    def action():
        drawing = _new(_next_name("Section" if kind == "section" else "Elevation"), s)
        made["guid"] = drawing.GlobalId
        return 1

    r = B._run(action)
    return B._dump({**r, "guid": made["guid"]})


def create_section(x1, y1, x2, y2, look_x, look_y, depth=-1.0) -> str:
    """A section along x1,y1-x2,y2 (world metres) looking towards the side of look_x,look_y (D61:
    Archicad's third click). depth < 0 = infinite (Archicad's default), 0 = the cut only."""
    return _create("section", x1, y1, x2, y2, look_x, look_y, depth)


def create_elevation(x1, y1, x2, y2, look_x, look_y, depth=-1.0) -> str:
    """An elevation marker placed by hand (same input as create_section)."""
    return _create("elevation", x1, y1, x2, y2, look_x, look_y, depth)


def _edit(guid: str, change) -> str:
    d = _drawing(guid)
    if d is None:
        return A._fail("not a drawing")

    def action():
        change(d)
        return 1

    return B._dump(B._run(action))


def set_drawing_depth(guid: str, depth) -> str:
    """Horizontal range: depth in metres, < 0 for infinite, 0 for the cut only."""
    try:
        depth = float(depth)
    except (TypeError, ValueError):
        return A._fail("bad depth")

    def change(d):
        s = G.settings_of(d)
        s["depth"] = None if depth < 0 else depth
        G.write_settings(B._model, d, s)
        G.place(B._model, d, s, G.model_bounds(B._model))

    return _edit(guid, change)


def rename_drawing(guid: str, name: str) -> str:
    name = (name or "").strip()
    if not name:
        return A._fail("type a name")

    def change(d):
        d.Name = name

    return _edit(guid, change)


def delete_drawing(guid: str) -> str:
    return _edit(guid, lambda d: ifcopenshell.api.root.remove_product(B._model, product=d))


def _python() -> str:
    """A Python interpreter for the child process. Inside the app, sys.executable is the app itself."""
    exe = Path(sys.executable or "")
    if exe.name.lower().startswith("python") and exe.exists():
        return str(exe)
    for candidate in (Path(sys.prefix) / "python.exe", Path(sys.prefix) / "bin" / "python3",
                      Path(sys.prefix) / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("no Python interpreter found for drawing generation")


def generate_drawing(guid: str, include_json: str = "") -> str:
    """{ok, svg, cached, timing}: the drawing's SVG for the current model state. include_json: the
    GlobalIds of the elements to draw (the visible ones, from the app); empty = all."""
    d = _drawing(guid)
    if d is None:
        return A._fail("not a drawing")
    key = (*_state_key(), include_json or "")  # the state and the elements given
    hit = _cache.get(guid, {}).get(key)
    if hit is not None:
        return B._dump({"ok": True, "svg": hit, "cached": True})
    try:
        with tempfile.TemporaryDirectory(prefix="kimcad-draw-") as tmp:
            snapshot = os.path.join(tmp, "model.ifc")
            B._model.write(snapshot)
            args = [_python(), G.__file__, snapshot, guid]
            if include_json:
                include = os.path.join(tmp, "include.json")
                Path(include).write_text(include_json, encoding="utf-8")
                args.append(include)
            done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result = json.loads(done.stdout) if done.stdout.strip() else \
            {"ok": False, "error": (done.stderr.strip().splitlines() or ["drawing generation failed"])[-1]}
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    if not result.get("ok"):
        return B._dump(result)
    entries = _cache.setdefault(guid, {})
    entries[key] = result["svg"]
    while len(entries) > _CACHE_SIZE:
        entries.pop(next(iter(entries)))
    return B._dump({"ok": True, "svg": result["svg"], "cached": False, "timing": result["timing"]})
