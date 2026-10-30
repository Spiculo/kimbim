# SPDX-License-Identifier: GPL-3.0-or-later
"""Sections and elevations in the app (Slice 14, D60/D61). Same protocol as app_bridge.

A drawing is model data (an IfcAnnotation DRAWING, see drawgen); its SVG is a cache keyed by the
model state, never model data. Generation runs in a child Python process from a snapshot of the
model, because IfcOpenShell's SVG serializer holds the GIL for seconds on real files (spike S6).
"""
from __future__ import annotations

import atexit
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import ifcopenshell.api.root
import ifcopenshell.util.element
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import drawgen as G

SIDES = ("north", "south", "east", "west")
_CACHE_SIZE = 4  # model states remembered per drawing (undo/redo returns to cached ones)
_cache: dict[str, dict[tuple, str]] = {}
_worker = None  # (Popen, state) of the long-lived generator, or None
_bounds_cache: dict[tuple, list] = {}  # state -> model [lo, hi] in metres
_timeout = 0.0  # drawing generation timeout in seconds (0: no limit); set from the preferences
_hlr = "exact"  # hidden-line mode: "exact" (fast on BREP-heavy models) or "poly"


def set_drawing_timeout(seconds) -> str:
    """The drawing generation timeout (seconds; 0 = no limit). A slower drawing is abandoned."""
    global _timeout
    try:
        _timeout = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return A._fail("bad timeout")
    return B._dump({"ok": True, "timeout": _timeout})


def set_drawing_hlr(mode) -> str:
    """The hidden-line mode: "exact" or "poly". The generator child inherits it through the env."""
    global _hlr
    _hlr = "poly" if str(mode) == "poly" else "exact"
    os.environ["KIMBIM_SVG_OPTS"] = json.dumps({"svg-poly": _hlr == "poly"})
    return B._dump({"ok": True, "hlr": _hlr})


def _state_key() -> tuple:
    # The drawing revision ignores sheet-placement edits (D72/D74: moving a view, legend or symbol on
    # a sheet), so a move does not invalidate the generated drawing cache (see app_bridge._drawing_ids).
    return id(B._model), B._drawing_rev()


def _drawings():
    return [a for a in B._model.by_type("IfcAnnotation") if G.is_drawing(a) and G.settings_of(a) is not None]


def _drawing(guid: str):
    d = A._by_guid(guid) if B._model is not None else None
    return d if d is not None and G.is_drawing(d) and G.settings_of(d) is not None else None


def resolve_view_depth(storey_guid: str, s: dict) -> float:
    """D91: the view's own depth below, else its level's, else the project setting."""
    from . import settings as S

    if s.get("view_depth") is not None:
        return float(s["view_depth"])
    levels = S.current().get("view_depth_levels", {})
    if isinstance(levels, dict) and storey_guid in levels:
        return float(levels[storey_guid])
    return float(S.current().get("view_depth", G.PLAN_DEPTH))


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
                        "auto": s["auto"], "side": s.get("side") or "", "points": s["points"], "look": s["look"],
                        "bulges": s.get("bulges") or [], "tilt": float(s.get("tilt", 0.0)),
                        **({"storey": s["storey"], "elevation": round(G.storey_elevation(storey), 6),
                            "cut": float(s.get("cut", G.PLAN_CUT)),
                            "view_depth": resolve_view_depth(s["storey"], s)} if storey else {}),
                        "stale": not any(k[:2] == key for k in _cache.get(d.GlobalId, {}))})
        # Archicad's Project Map order: floor plans (by story height), sections, elevations.
        order = {"plan": 0, "section": 1, "elevation": 2}
        out.sort(key=lambda d: (order[d["kind"]], d.get("elevation", 0.0), d["name"]))
    return B._dump({"drawings": out})


_building_cache: dict[tuple, list] = {}  # state -> GlobalIds of the building's drawn products


def drawing_bounds() -> str:
    """The building's bounding box in metres ({lo, hi}, from placements) and its drawn products
    (`guids`): the app frames the drawings on those elements' meshes (exact, roofs included) and runs
    its visible-element pass there, not on the whole georeferenced site. Once per model state: the
    app asks for every drawing it generates, and walking a large model is seconds."""
    if B._model is None:
        return A._fail("no model open")
    lo, hi = _bounds_json()
    state = _state_key()
    guids = _building_cache.get(state)
    if guids is None:
        guids = [p.GlobalId for p in G.building_products(B._model)]
        _building_cache.clear()
        _building_cache[state] = guids
    return B._dump({"ok": True, "lo": lo, "hi": hi, "guids": guids})


def _new(name: str, s: dict, bounds=None):
    f = B._model
    drawing = ifcopenshell.api.root.create_entity(f, ifc_class="IfcAnnotation", name=name)
    drawing.ObjectType = "DRAWING"
    G.write_settings(f, drawing, s)
    # `bounds` is worked out once by the caller: model_bounds walks every product (the Centro Educativo
    # is 1.6 s), and creating a plan and four elevations would pay it once per drawing otherwise.
    G.place(f, drawing, s, G.model_bounds(f) if bounds is None else bounds)
    G.store_path(f, drawing, s)  # a bent or curved marker keeps its path in the drawing's own frame
    return drawing


def create_template_elevations():
    """North, South, East and West elevations of a new project (D61, Archicad's default template).
    Called by new_project before its history starts, so they are part of the empty project."""
    bounds = G.model_bounds(B._model)
    for side in SIDES:
        points, look = G.auto_marker(side, bounds)
        _new(f"{side.capitalize()} Elevation",
             {"kind": "elevation", "points": points, "look": look, "depth": None, "auto": True, "side": side}, bounds)


def plan_name(storey) -> str:
    return f"{storey.Name or 'Level'} Floor Plan"


def create_plan(storey_guid: str, undoable: bool = True, bounds=None) -> str:
    """The floor plan of a story (Archicad: every story has one), cut 1.10 m above it."""
    storey = A._by_guid(storey_guid) if B._model is not None else None
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    made = {}

    def action():
        made["guid"] = _new(plan_name(storey), {"kind": "plan", "points": [], "look": [], "depth": None,
                                                "auto": True, "side": "", "storey": storey.GlobalId,
                                                "cut": G.PLAN_CUT}, bounds).GlobalId
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
               if st.GlobalId not in have_plans and not A._is_model(st)]  # worksheets make their own
    have = {G.settings_of(d).get("side") for d in _drawings()}
    missing = [side for side in SIDES if side not in have]

    def action():
        bounds = G.model_bounds(B._model)  # once for every drawing this makes
        for st in stories:
            create_plan(st.GlobalId, undoable=False, bounds=bounds)
        for side in missing:
            points, look = G.auto_marker(side, bounds)
            _new(f"{side.capitalize()} Elevation",
                 {"kind": "elevation", "points": points, "look": look, "depth": None, "auto": True, "side": side}, bounds)
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
        bounds = G.model_bounds(B._model)  # once for every elevation this makes
        for side in missing:
            points, look = G.auto_marker(side, bounds)
            _new(f"{side.capitalize()} Elevation",
                 {"kind": "elevation", "points": points, "look": look, "depth": None, "auto": True, "side": side}, bounds)
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


def _create(kind, points, bulges, look_x, look_y, depth, tilt=0.0, base=0.0) -> str:
    if B._model is None:
        return A._fail("no model open")
    try:
        points = [[float(p[0]), float(p[1])] for p in points]
        bulges = [float(b) for b in bulges]
        look = [float(look_x), float(look_y)]
        depth = float(depth)
        tilt = float(tilt)
        base = float(base)
    except (TypeError, ValueError, IndexError) as ex:
        return A._fail(f"bad input: {ex}")
    if len(points) < 2 or any(math.dist(points[i], points[i + 1]) < 1e-6 for i in range(len(points) - 1)):
        return A._fail("draw the line with two different points")
    if abs(tilt) >= 89.0 or not math.isfinite(tilt):
        return A._fail("the tilt must be less than 89 degrees")
    bulges = (bulges + [0.0] * max(0, len(points) - 1))[: len(points) - 1]
    s = {"kind": kind, "points": points, "look": look, "depth": None if depth < 0 else depth, "auto": False,
         "bulges": bulges, "tilt": tilt, "base": base}
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
    return _create("section", [[x1, y1], [x2, y2]], [], look_x, look_y, depth)


def create_elevation(x1, y1, x2, y2, look_x, look_y, depth=-1.0) -> str:
    """An elevation marker placed by hand (same input as create_section)."""
    return _create("elevation", [[x1, y1], [x2, y2]], [], look_x, look_y, depth)


def create_drawing_path(kind, points_json, bulges_json, look_x, look_y, depth=-1.0, tilt=0.0, base=0.0) -> str:
    """A section or elevation along a path: `points_json` is [[x, y], ...] in world metres (a bend is
    several points; a curve is a segment with a non-zero bulge), `bulges_json` a bulge per segment
    (tan of a quarter of the sweep, 0 = straight), `tilt` the cut plane's angle about the line and
    `base` the height the line lies at (the tilt's pivot)."""
    try:
        import json as _json
        points = _json.loads(points_json) if isinstance(points_json, str) else points_json
        bulges = _json.loads(bulges_json) if isinstance(bulges_json, str) else bulges_json
    except ValueError as ex:
        return A._fail(f"bad input: {ex}")
    if not isinstance(points, list) or not isinstance(bulges, list):
        return A._fail("bad input: the path needs a list of points")
    return _create(kind, points, bulges, look_x, look_y, depth, tilt, base)


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


def set_drawing_path(guid: str, points_json: str, bulges_json: str = "[]", tilt=None, base=None) -> str:
    """Replace a section or elevation's marker path (world metres) and its bulges (one per segment).
    `tilt` and `base` keep their current values when omitted."""
    try:
        points = json.loads(points_json)
        bulges = json.loads(bulges_json) if bulges_json else []
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError("the path needs two points")
        points = [[float(p[0]), float(p[1])] for p in points]
        bulges = [float(b) for b in bulges]
    except (TypeError, ValueError, IndexError) as ex:
        return A._fail(f"bad path: {ex}")
    if any(math.dist(points[i], points[i + 1]) < 1e-6 for i in range(len(points) - 1)):
        return A._fail("two points of the path are the same")
    if tilt is not None and abs(float(tilt)) >= 89.0:
        return A._fail("the tilt must be less than 89 degrees")

    def change(d):
        s = G.settings_of(d)
        if s is None or s["kind"] == "plan":
            raise ValueError("not a section or elevation")
        s.update({"points": points, "auto": False,
                  "bulges": (bulges + [0.0] * max(0, len(points) - 1))[: len(points) - 1],
                  "tilt": float(s.get("tilt", 0.0)) if tilt is None else float(tilt),
                  "base": float(s.get("base", 0.0)) if base is None else float(base)})
        G.write_settings(B._model, d, s)
        G.place(B._model, d, s, G.model_bounds(B._model))
        G.store_path(B._model, d, s)

    try:
        return _edit(guid, change)
    except ValueError as ex:
        return A._fail(str(ex))


def set_drawing_tilt(guid: str, degrees) -> str:
    """The cut plane's angle about the marker line (0 = vertical section)."""
    try:
        tilt = float(degrees)
    except (TypeError, ValueError):
        return A._fail("bad angle")
    if not math.isfinite(tilt) or abs(tilt) >= 89.0:
        return A._fail("the tilt must be less than 89 degrees")

    def change(d):
        s = G.settings_of(d)
        if s is None or s["kind"] == "plan":
            raise ValueError("not a section or elevation")
        s["tilt"] = tilt
        G.write_settings(B._model, d, s)
        G.place(B._model, d, s, G.model_bounds(B._model))
        G.store_path(B._model, d, s)

    try:
        return _edit(guid, change)
    except ValueError as ex:
        return A._fail(str(ex))


def set_drawing_base(guid: str, metres) -> str:
    """The height the marker line lies at: the pivot of an oblique cut plane."""
    try:
        base = float(metres)
    except (TypeError, ValueError):
        return A._fail("bad height")
    if not math.isfinite(base):
        return A._fail("bad height")

    def change(d):
        s = G.settings_of(d)
        if s is None or s["kind"] == "plan":
            raise ValueError("not a section or elevation")
        s["base"] = base
        G.write_settings(B._model, d, s)
        G.place(B._model, d, s, G.model_bounds(B._model))
        G.store_path(B._model, d, s)

    try:
        return _edit(guid, change)
    except ValueError as ex:
        return A._fail(str(ex))


def set_view_depth(guid: str, depth) -> str:
    """D91: a plan's view depth below its level (metres); < 0 clears the view's own override."""
    try:
        depth = float(depth)
    except (TypeError, ValueError):
        return A._fail("bad depth")
    if depth > 20:
        return A._fail("bad depth")

    def change(d):
        s = G.settings_of(d)
        if s is None or s.get("kind") != "plan":
            raise ValueError("not a plan drawing")
        s["view_depth"] = None if depth < 0 else depth
        G.write_settings(B._model, d, s)
        G.place(B._model, d, s, G.model_bounds(B._model), resolve_view_depth(s["storey"], s))

    try:
        return _edit(guid, change)
    except ValueError as ex:
        return A._fail(str(ex))


def rename_drawing(guid: str, name: str) -> str:
    name = (name or "").strip()
    if not name:
        return A._fail("type a name")

    def change(d):
        d.Name = name

    return _edit(guid, change)


def delete_drawing(guid: str) -> str:
    def change(d):
        from . import sheets  # late: sheets imports this module

        sheets.remove_drawing_placements(guid)  # no broken views left on its sheets
        ifcopenshell.api.root.remove_product(B._model, product=d)

    return _edit(guid, change)


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


# The model snapshot handed to the child process (the serializer runs there, S6). Writing a large IFC
# is seconds of work (the Centro Educativo, 95 MB: ~20-30 s), so one snapshot per drawing state is kept
# and shared by every drawing generated at that state (creating plans and elevations makes one state).
# A long-lived worker (below) opens each snapshot once, so a second drawing at the same state is quick.
_SNAP_CACHE = 2
_snapshots: dict[tuple, tuple[str, str]] = {}  # state -> (snapshot path, its private temp folder)


def _stop_worker() -> None:
    global _worker
    if _worker is None:
        return
    proc = _worker[0]
    try:
        if proc.poll() is None:
            proc.stdin.write('{"op": "stop"}\n')
            proc.stdin.flush()
            proc.wait(timeout=3)
    except Exception:
        pass
    if proc.poll() is None:
        proc.kill()
    _worker = None


def forget_snapshots() -> None:
    """Drop the cached model snapshots and the generator (a different model was opened, or closing)."""
    _stop_worker()
    for _path_, folder in _snapshots.values():
        shutil.rmtree(folder, ignore_errors=True)
    _snapshots.clear()
    _bounds_cache.clear()
    _building_cache.clear()


def _snapshot() -> str:
    """Path of this model state's IFC snapshot, written once and reused while the state holds."""
    state = _state_key()
    cached = _snapshots.get(state)
    if cached is not None and os.path.exists(cached[0]):
        return cached[0]
    folder = tempfile.mkdtemp(prefix="kimbim-draw-")
    path = os.path.join(folder, "model.ifc")
    try:
        if B._current_id() == B._saved_id and B._path and os.path.exists(B._path):
            # A saved model is already on disk: copy its bytes (fast) instead of re-serializing it
            # (the snapshot is what the worker opens; the original stays free for the next save).
            shutil.copyfile(B._path, path)
        else:
            # to_string + one write is ~30 % faster than write() on a large model (the C++ serializer
            # is the same; write() pays per-entity Python/IO overhead).
            Path(path).write_text(B._model.to_string(), encoding="utf-8")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    _snapshots[state] = (path, folder)
    while len(_snapshots) > _SNAP_CACHE:  # the oldest state's snapshot leaves with its folder
        oldest = next(iter(_snapshots))
        folder_old = _snapshots.pop(oldest)[1]
        if folder_old:
            shutil.rmtree(folder_old, ignore_errors=True)
    return path


def _bounds_json() -> list:
    """The model's [lo, hi] in metres, once per state: the generator places the drawing without it."""
    state = _state_key()
    cached = _bounds_cache.get(state)
    if cached is not None:
        return cached
    lo, hi = G.model_bounds(B._model)
    out = [[float(v) for v in lo], [float(v) for v in hi]]
    _bounds_cache.clear()  # one state: the previous bounds are no longer needed
    _bounds_cache[state] = out
    return out


def _read_line(proc, timeout: float):
    """One line from the worker's stdout, or None if it takes longer than `timeout` seconds (0: wait)."""
    box: dict = {}

    def read():
        try:
            box["line"] = proc.stdout.readline()
        except (OSError, ValueError):
            box["line"] = ""

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    thread.join(None if timeout <= 0 else timeout)
    return box.get("line") if not thread.is_alive() else None


def _worker_generate(snapshot: str, state: tuple, job: dict) -> dict:
    """Generate through the long-lived worker, (re)starting it when the model state changed. The child
    opens the snapshot once, so opening a second drawing on the same state costs nothing. A generation
    that runs past the timeout is abandoned (the worker is killed) and reported as a timeout."""
    global _worker
    if _worker is None or _worker[1] != state:
        _stop_worker()
        proc = subprocess.Popen([_python(), G.__file__, "--worker", snapshot], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ready = _read_line(proc, _timeout or 60)
        ack = json.loads(ready) if ready and ready.strip() else {}
        if not ack.get("ready"):
            proc.kill()
            raise RuntimeError(ack.get("error") or "the drawing worker did not start")
        _worker = (proc, state)
    proc = _worker[0]
    proc.stdin.write(json.dumps(job) + "\n")
    proc.stdin.flush()
    line = _read_line(proc, _timeout)
    if line is None:  # the timeout (a setting): the hidden-line pass is too slow on this drawing
        _stop_worker()
        return {"ok": False, "error": f"the drawing timed out after {_timeout:.0f} s"}
    if not line.strip():
        _stop_worker()
        raise RuntimeError("the drawing worker stopped")
    return json.loads(line)


def _generate_once(snapshot: str, job: dict) -> dict:
    """One drawing in its own process (the fallback when the worker cannot be used)."""
    fd, path = tempfile.mkstemp(prefix="kimbim-job-", suffix=".json")
    os.close(fd)
    Path(path).write_text(json.dumps(job), encoding="utf-8")
    try:
        done = subprocess.run([_python(), G.__file__, snapshot, job["drawing"], path],
            capture_output=True, text=True, encoding="utf-8", timeout=(_timeout or None),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"the drawing timed out after {_timeout:.0f} s"}
    finally:
        os.remove(path)
    return json.loads(done.stdout) if done.stdout.strip() else \
        {"ok": False, "error": (done.stderr.strip().splitlines() or ["drawing generation failed"])[-1]}


atexit.register(forget_snapshots)


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
    mesh = _cache.get(guid, {}).get((*_state_key(), "mesh-drawing"))
    if mesh is not None:  # drawn from the meshes: reused here for sheets and size queries
        return {"ok": True, "svg": _drafted(mesh, d), "cached": True}
    include_json = _without_hidden(include_json, hidden)
    from . import settings as S
    plan_symbols = bool(S.current().get("plan_symbols", True))
    s = G.settings_of(d)
    view_depth = resolve_view_depth(s.get("storey", ""), s) if s and s.get("kind") == "plan" else G.PLAN_DEPTH
    key = (*_state_key(), include_json or "", plan_symbols, view_depth)  # state, elements, D91's choices
    hit = _cache.get(guid, {}).get(key)
    if hit is not None:
        return {"ok": True, "svg": _drafted(hit, d), "cached": True}
    try:
        state = _state_key()
        if _worker is not None and _worker[1] != state:  # free the old snapshot before it is replaced
            _stop_worker()
        snapshot = _snapshot()  # written once per state, shared by every drawing at that state
        job = {"drawing": guid, "include": json.loads(include_json) if include_json else None,
               "bounds": _bounds_json(), "plan_symbols": plan_symbols, "view_depth": view_depth}
        try:
            result = _worker_generate(snapshot, state, job)
        except Exception:  # the worker could not run: one process, one drawing
            result = _generate_once(snapshot, job)
    except Exception as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
    if not result.get("ok"):
        return result
    entries = _cache.setdefault(guid, {})
    entries[key] = result["svg"]
    while len(entries) > _CACHE_SIZE:
        entries.pop(next(iter(entries)))
    return {"ok": True, "svg": _drafted(result["svg"], d), "cached": False, "timing": result.get("timing")}


def _drafted(svg: str, drawing) -> str:
    """D84: plans get their level's lines, arcs and fills here, not in the drawing process: the
    fill patterns and line types are project settings, so they are drawn as they are now. D87: and
    their tags, room stamps and symbols (tag styles are settings too); sections their levels."""
    from . import drafting, tags

    return tags.add_to_drawing(drafting.add_to_drawing(svg, drawing), drawing)  # D87: tags, symbols, stamps


def generate_drawing(guid: str, include_json: str = "", purpose: str = "") -> str:
    """{ok, svg, cached, timing}: the drawing's SVG for the current model state, styled by the current
    purpose (D73: pens, line types, overrides; hidden elements left out), or by `purpose` (D102 snapshots)."""
    from . import graphics

    resolved = graphics.resolve(purpose or None)
    r = raw_drawing(guid, include_json, resolved["hidden"])
    if r.get("ok"):
        r["svg"] = graphics.style_svg(r["svg"], resolved, 1.0)
    return B._dump(r)


def _clip_half(poly, a, b, c):
    """The part of a 2D polygon where a*x + b*y + c >= 0 (Sutherland-Hodgman)."""
    out = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        dp, dq = a * p[0] + b * p[1] + c, a * q[0] + b * q[1] + c
        if dp >= 0:
            out.append(p)
        if (dp > 0 > dq) or (dp < 0 < dq):
            t = dp / (dp - dq)
            out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
    return out


def _layer_pieces(guid, loops, to_world):
    """D96: an element's cut loops split into its layers, [(layer index, polygon)], or None when it is
    not layered (or its layers do not cross this cut). `to_world(x, y)` -> world (x, y, z) in metres;
    loops are in the drawing's 2D coordinates."""
    from . import configure, materials

    try:
        if configure.profile_of(B._model.by_guid(guid)):  # D97: one fill for a complex profile
            return None
        bands = materials.layer_bands(B._model.by_guid(guid))
    except Exception:
        return None
    if bands is None:
        return None
    o, axis = np.asarray(bands["origin"]), np.asarray(bands["axis"])
    # the distance along the layer axis is linear in the drawing's x, y: a*x + b*y + c
    p0, px, py = (np.asarray(to_world(*xy)) for xy in ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)))
    c = float((p0 - o) @ axis)
    a, b = float((px - p0) @ axis), float((py - p0) @ axis)
    if math.hypot(a, b) < 0.5:  # the layers stack across the drawing's plane: one layer shows
        return None
    pieces = []
    for k in range(len(bands["bounds"]) - 1):
        lo, hi = sorted(bands["bounds"][k:k + 2])
        if hi - lo < 1e-6:
            continue
        for loop in loops:
            poly = _clip_half([tuple(map(float, pt)) for pt in loop], a, b, c - lo)
            poly = _clip_half(poly, -a, -b, hi - c) if len(poly) >= 3 else []
            if len(poly) >= 3:
                pieces.append((k, poly))
    return pieces


def _cut_group(guid, loops, to_paper, to_world, path) -> str:
    """A cut element's SVG group: one filled path per layer for a composite (D96), then its outline."""
    pieces = _layer_pieces(guid, loops, to_world)
    if not pieces:
        body = "".join(path(loop) for loop in loops)
        return f'<g ifc:guid="{guid}">{body}</g>' if body else ""
    layers = "".join(path(poly).replace("<path ", f'<path data-layer="{k}" ', 1) for k, poly in pieces)
    outline = "".join(path(loop).replace("<path ", '<path fill="none" ', 1) for loop in loops)
    return f'<g ifc:guid="{guid}">{layers}{outline}</g>'


def _plan_base_svg(g) -> str:
    """A plan drawing's base SVG from the app's meshes (no hidden-line pass). `g` is the geometry the
    viewport extracted: cut loops (poché) and projection loops, world x,y. Paper millimetres at the
    drawing scale, north up, with the plane/matrix3 the overlay and drafting expect."""
    scale = 1000.0 / G.SCALE  # paper millimetres per metre
    x0, y0, x1, y1 = (float(v) for v in g["bounds"])
    plane = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    m3 = [[scale, 0, -x0 * scale], [0, scale, y1 * scale], [0, 0, 1]]

    def to_paper(x, y):
        return scale * (x - x0), scale * (y1 - y)

    def paths(loops) -> str:
        out = []
        for loop in loops:
            pts = [to_paper(px, py) for px, py in loop]
            if len(pts) < 3:
                continue
            d = "M" + " L".join(f"{px:.3f},{py:.3f}" for px, py in pts) + " Z"
            out.append(f'<path d="{d}"/>')
        return "".join(out)

    def one(loop) -> str:
        pts = [to_paper(px, py) for px, py in loop]
        if len(pts) < 3:
            return ""
        return '<path d="M' + " L".join(f"{px:.3f},{py:.3f}" for px, py in pts) + ' Z"/>'

    parts = []
    for e in g["cut"]:  # walls and slabs cut by the plane: filled poché (by layer, D96)
        group = _cut_group(e["guid"], e["loops"], to_paper, lambda x, y: (x, y, 0.0), one)
        if group:
            parts.append(group)
    for e in g["proj"]:  # below the cut: their top outline, in projection
        body = paths(e["loops"])
        if body:
            parts.append(f'<g class="projection" ifc:guid="{e["guid"]}">{body}</g>')
    plane_json = json.dumps(plane, separators=(",", ":"))
    m3_json = json.dumps(m3, separators=(",", ":"))
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:ifc="http://www.ifcopenshell.org/ns" '
            'width="1mm" height="1mm" viewBox="0 0 1 1">\n'
            f'<g class="section" ifc:plane="{plane_json}" ifc:matrix3="{m3_json}">\n'
            + "\n".join(parts) + "\n</g>\n</svg>\n")


def generate_plan_drawing(guid: str, geometry_json: str) -> str:
    """{ok, svg, cached}: a plan drawing's SVG built from the meshes the app already has (the cut
    outlines and the projection), instead of IfcOpenShell's hidden-line pass, which is far too slow on
    a detailed storey. The overlay (doors, windows, rooms, annotations, markers), the drafting shapes,
    the tags and the purpose styling are the same as for any drawing."""
    from . import graphics

    d = _drawing(guid)
    if d is None:
        return A._fail("not a drawing")
    s = G.settings_of(d)
    if s is None or s.get("kind") != "plan":
        return A._fail("not a plan drawing")
    key = (*_state_key(), "plan", hash(geometry_json))
    hit = _cache.get(guid, {}).get(key)
    if hit is None:
        try:
            g = json.loads(geometry_json)
            svg = G.overlay(B._model, d, s, _plan_base_svg(g), None)
        except Exception as ex:
            return A._fail(f"{type(ex).__name__}: {ex}")
        entries = _cache.setdefault(guid, {})
        entries[key] = svg
        entries[(*_state_key(), "mesh-drawing")] = svg  # reused by raw_drawing for sheets and sizes
        while len(entries) > _CACHE_SIZE:
            entries.pop(next(iter(entries)))
        hit = svg
    svg = graphics.style_svg(G.crop(_drafted(hit, d)), graphics.resolve(), 1.0)
    return B._dump({"ok": True, "svg": svg, "cached": False})


def _view_base_svg(g) -> str:
    """A section/elevation's base SVG from the app's meshes (OCCT polygon hidden-line removal). `g` has
    the visible edges per element (`proj`, in the view plane) and, for a section, the cut loops
    (`cut`), plus the view->world matrix (`view`). Paper millimetres at the drawing scale."""
    scale = 1000.0 / G.SCALE
    flat = g["view"]  # view -> world, row-major (16 numbers)
    plane = [list(flat[i * 4:(i + 1) * 4]) for i in range(4)]
    xs, ys = [], []
    for e in g["proj"]:
        for x1, y1, x2, y2 in e["lines"]:
            xs += [x1, x2]
            ys += [y1, y2]
    for e in g["cut"]:
        for loop in e["loops"]:
            for x, y in loop:
                xs.append(x)
                ys.append(y)
    vx0 = min(xs) if xs else 0.0
    vy1 = max(ys) if ys else 0.0
    m3 = [[scale, 0, -scale * vx0], [0, scale, scale * vy1], [0, 0, 1]]

    def to_paper(x, y):  # view-up (larger y) goes up on the sheet (SVG y grows downward)
        return scale * (x - vx0), scale * (vy1 - y)

    def path(points, closed):
        pts = [to_paper(x, y) for x, y in points]
        if len(pts) < 2:
            return ""
        d = "M" + " L".join(f"{px:.3f},{py:.3f}" for px, py in pts) + (" Z" if closed else "")
        return f'<path d="{d}"/>'

    parts = []
    for e in g["proj"]:
        body = "".join(path([(x1, y1), (x2, y2)], False) for x1, y1, x2, y2 in e["lines"])
        if body:
            parts.append(f'<g class="projection" ifc:guid="{e["guid"]}">{body}</g>')
    plane = np.asarray(g["view"], dtype=float).reshape(4, 4)
    strips = g.get("strips") or [{"view": plane.reshape(-1).tolist(), "x": 0.0}]
    for e in g["cut"]:
        strip = strips[min(int(e.get("strip", 0)), len(strips) - 1)]
        view = np.asarray(strip["view"], dtype=float).reshape(4, 4)
        shift = float(strip.get("x", 0.0))
        group = _cut_group(e["guid"], e["loops"], to_paper,
                           lambda x, y, v=view, s=shift: tuple((v @ np.array([x - s, y, 0.0, 1.0]))[:3]),
                           lambda loop: path([(x, y) for x, y in loop], True))
        if group:
            parts.append(group)
    plane_json = json.dumps(plane.tolist(), separators=(",", ":"))
    m3_json = json.dumps(m3, separators=(",", ":"))
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:ifc="http://www.ifcopenshell.org/ns" '
            'width="1mm" height="1mm" viewBox="0 0 1 1">\n'
            f'<g class="section" ifc:plane="{plane_json}" ifc:matrix3="{m3_json}">\n'
            + "\n".join(parts) + "\n</g>\n</svg>\n")


def generate_view_drawing(guid: str, geometry_json: str) -> str:
    """{ok, svg, cached}: a section or elevation's SVG built from the app's meshes (OCCT polygon
    hidden-line removal), not IfcOpenShell's slow serializer. The tags (level markers) and the purpose
    styling are the same as for any drawing."""
    from . import graphics

    d = _drawing(guid)
    if d is None:
        return A._fail("not a drawing")
    s = G.settings_of(d)
    if s is None or s.get("kind") == "plan":
        return A._fail("not a section or elevation")
    key = (*_state_key(), "view", hash(geometry_json))
    hit = _cache.get(guid, {}).get(key)
    if hit is None:
        try:
            svg = _view_base_svg(json.loads(geometry_json))
        except Exception as ex:
            return A._fail(f"{type(ex).__name__}: {ex}")
        entries = _cache.setdefault(guid, {})
        entries[key] = svg
        entries[(*_state_key(), "mesh-drawing")] = svg  # reused by raw_drawing for sheets and sizes
        while len(entries) > _CACHE_SIZE:
            entries.pop(next(iter(entries)))
        hit = svg
    svg = graphics.style_svg(G.crop(_drafted(hit, d)), graphics.resolve(), 1.0)
    return B._dump({"ok": True, "svg": svg, "cached": False})
