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
            storey = G._storey(d, s) if s["kind"] == "plan" else None
            if s["kind"] == "plan" and storey is None:
                continue  # its level was deleted
            out.append({"guid": d.GlobalId, "name": d.Name or "", "kind": s["kind"], "depth": s["depth"],
                        "auto": s["auto"], "points": s["points"], "look": s["look"],
                        **({"storey": s["storey"], "elevation": round(G.storey_elevation(storey), 6)} if storey else {}),
                        "stale": not any(k[:2] == key for k in _cache.get(d.GlobalId, {}))})
        # Archicad's Project Map order: floor plans (by story height), sections, elevations.
        order = {"plan": 0, "section": 1, "elevation": 2}
        out.sort(key=lambda d: (order[d["kind"]], d.get("elevation", 0.0), d["name"]))
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


def plan_name(storey) -> str:
    return f"{storey.Name or 'Level'} Floor Plan"


def create_plan(storey_guid: str, undoable: bool = True) -> str:
    """The floor plan of a story (Archicad: every story has one), cut 1.10 m above it."""
    storey = A._by_guid(storey_guid) if B._model is not None else None
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    made = {}

    def action():
        made["guid"] = _new(plan_name(storey), {"kind": "plan", "points": [], "look": [], "depth": None,
                                                "auto": True, "side": "", "storey": storey.GlobalId,
                                                "cut": G.PLAN_CUT}).GlobalId
        return 1

    if not undoable:  # part of another action (a new level, a new project)
        action()
        return B._dump({"ok": True, "guid": made["guid"]})
    return B._dump({**B._run(action), "guid": made["guid"]})


def _plans_by_storey() -> dict:
    out = {}
    for d in _drawings():
        s = G.settings_of(d)
        if s["kind"] == "plan":
            out[s["storey"]] = d
    return out


def create_drawings() -> str:
    """Add what a model is missing (an opened IFC has no drawings): a floor plan for every story and
    the North/South/East/West elevations, fitted to the model. One undoable step."""
    if B._model is None:
        return A._fail("no model open")
    have_plans = _plans_by_storey()
    stories = [st for st in B._model.by_type("IfcBuildingStorey")
               if st.GlobalId not in have_plans and not A._is_model(st)]
    have = {G.settings_of(d).get("side") for d in _drawings()}
    missing = [side for side in SIDES if side not in have]

    def action():
        bounds = G.model_bounds(B._model)
        for st in stories:
            create_plan(st.GlobalId, undoable=False)
        for side in missing:
            points, look = G.auto_marker(side, bounds)
            _new(f"{side.capitalize()} Elevation",
                 {"kind": "elevation", "points": points, "look": look, "depth": None, "auto": True, "side": side})
        return len(stories) + len(missing)

    if not stories and not missing:
        return B._dump({"ok": True, "created": 0})
    return B._dump({**B._run(action), "created": len(stories) + len(missing)})


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


def _without_hidden(include_json: str, hidden) -> str:
    """The include list minus the elements the purpose hides (D73): they are left out of the hidden-line
    pass, so they don't hide what is behind them."""
    if not hidden:
        return include_json
    gone = set(hidden)
    wanted = json.loads(include_json) if include_json else [p.GlobalId for p in G.drawn_products(B._model)]
    return json.dumps(sorted(g for g in wanted if g not in gone))


def raw_drawing(guid: str, include_json: str = "", hidden=()) -> dict:
    """{ok, svg (unstyled), cached, timing}: the drawing's geometry for the current model state, cached.
    include_json: the GlobalIds of the elements to draw (the visible ones, from the app); empty = all.
    hidden: GlobalIds the purpose hides."""
    d = _drawing(guid)
    if d is None:
        return {"ok": False, "error": "not a drawing"}
    include_json = _without_hidden(include_json, hidden)
    key = (*_state_key(), include_json or "")  # the state and the elements given
    hit = _cache.get(guid, {}).get(key)
    if hit is not None:
        return {"ok": True, "svg": _drafted(hit, d), "cached": True}
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
        result = json.loads(done.stdout) if done.stdout.strip() else             {"ok": False, "error": (done.stderr.strip().splitlines() or ["drawing generation failed"])[-1]}
    except Exception as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
    if not result.get("ok"):
        return result
    entries = _cache.setdefault(guid, {})
    entries[key] = result["svg"]
    while len(entries) > _CACHE_SIZE:
        entries.pop(next(iter(entries)))
    return {"ok": True, "svg": _drafted(result["svg"], d), "cached": False, "timing": result["timing"]}


def _drafted(svg: str, drawing) -> str:
    """D84: plans get their level's lines, arcs and fills here, not in the drawing process: the
    fill patterns and line types are project settings, so they are drawn as they are now. D87: and
    their tags, room stamps and symbols (tag styles are settings too); sections their levels."""
    from . import drafting, tags

    return tags.add_to_drawing(drafting.add_to_drawing(svg, drawing), drawing)  # D87: tags, symbols, stamps


def generate_drawing(guid: str, include_json: str = "") -> str:
    """{ok, svg, cached, timing}: the drawing's SVG for the current model state, styled by the current
    purpose (D73: pens, line types, overrides; hidden elements left out)."""
    from . import graphics

    resolved = graphics.resolve()
    r = raw_drawing(guid, include_json, resolved["hidden"])
    if r.get("ok"):
        r["svg"] = graphics.style_svg(r["svg"], resolved, 1.0)
    return B._dump(r)
