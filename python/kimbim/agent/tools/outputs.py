# SPDX-License-Identifier: GPL-3.0-or-later
"""Output tools: drawings, sheets, schedules, checks (D102). Creating a drawing or sheet and placing a drawing
are model changes (write tools); listing and exporting change nothing (exports only write the file asked for).
PDF has no Python renderer: it goes through the app binary's `--export-sheet NUMBER model.ifc out.pdf`."""
from __future__ import annotations

import json
import math
import os
import pathlib
import subprocess
import tempfile

from ... import app_bridge as B
from ... import checks as C
from ... import documents as D
from ... import drawings as DR
from ... import schedules as SC
from ... import sheets as SH
from ..catalogue import AgentError, bridge, tool
from .common import level_guid, point

_OUT = {"type": "string", "description": "Path of the file to write."}
_DRAWING = {"type": "string", "description": "Drawing name or GlobalId (drawings.list lists them)."}
_SHEET = {"type": "string", "description": "Sheet number (sheets.list lists them), e.g. \"A01\"."}


def _drawing_guid(ref) -> str:
    want = str(ref).strip().lower()
    for d in bridge(DR.drawings)["drawings"]:
        if d["guid"] == ref or d["name"].strip().lower() == want:
            return d["guid"]
    raise AgentError("not_found", what=ref)


def _sheet_number(ref) -> str:
    want = str(ref).strip().lower()
    for s in bridge(SH.sheets)["sheets"]:
        if s["number"].lower() == want or s["title"].strip().lower() == want:
            return s["number"]
    raise AgentError("not_found", what=ref)


def _write_text(path: str, text: str) -> None:
    try:
        pathlib.Path(path).write_text(text, encoding="utf-8")
    except OSError as ex:
        raise AgentError("bridge_error", hint=str(ex)) from None


# ---------------------------------------------------------------- drawings

@tool("drawings.list", {})
def drawings_list(session):
    """List the project's drawings: floor plans, sections and elevations with GlobalId, name, kind and level."""
    return {"drawings": bridge(DR.drawings)["drawings"]}


@tool("drawings.create", {"required": ["kind"], "properties": {
    "kind": {"type": "string", "enum": ["plan", "section", "elevation"]},
    "level": {"type": "string", "description": "Plan: the level (name or GlobalId)."},
    "line": {"type": "array", "items": {"type": "array"},
             "description": "Section/elevation: the marker line [[x, y], [x, y]] in project units."},
    "direction": {"type": ["string", "array"],
                  "description": "Section/elevation: which side of the line it looks at, \"left\" or \"right\" of "
                                 "start to end (default left), or a [x, y] point to look towards."}}}, writes=True)
def drawings_create(session, kind, level="", line=None, direction="left"):
    """Create a drawing. A plan needs a level. A section needs a line; an elevation takes a line too, or none to add
    the North/South/East/West elevations the model lacks."""
    if kind == "plan":
        if not level:
            raise AgentError("bad_input", hint="a plan needs a level")
        return {"guid": bridge(DR.create_plan, level_guid(level))["guid"]}
    if line is None:
        if kind == "section":
            raise AgentError("bad_input", hint="a section needs a line")
        r = bridge(DR.create_elevations)
        return {"created": r.get("created", 0), "drawings": [d["guid"] for d in bridge(DR.drawings)["drawings"]
                                                              if d["kind"] == "elevation"]}
    if not isinstance(line, list) or len(line) != 2:
        raise AgentError("bad_input", hint="line must be [[x, y], [x, y]]")
    (x1, y1), (x2, y2) = point(session, line[0], "line[0]"), point(session, line[1], "line[1]")
    if isinstance(direction, list):
        lx, ly = point(session, direction, "direction")
    else:
        if direction not in ("left", "right"):
            raise AgentError("bad_input", hint="direction must be \"left\", \"right\" or a [x, y] point")
        length = math.dist((x1, y1), (x2, y2)) or 1.0
        nx, ny = -(y2 - y1) / length, (x2 - x1) / length  # the left normal
        sign = 1 if direction == "left" else -1
        lx, ly = (x1 + x2) / 2 + sign * nx, (y1 + y2) / 2 + sign * ny
    make = DR.create_section if kind == "section" else DR.create_elevation
    return {"guid": bridge(make, x1, y1, x2, y2, lx, ly)["guid"]}


@tool("drawings.export", {"required": ["drawing", "format", "out"], "properties": {
    "drawing": _DRAWING, "format": {"type": "string", "enum": ["svg", "dxf", "pdf"]}, "out": _OUT}})
def drawings_export(session, drawing, format, out):
    """Export a drawing as SVG or DXF (pdf: put it on a sheet and use sheets.export)."""
    guid = _drawing_guid(drawing)
    if format == "svg":
        _write_text(out, bridge(DR.generate_drawing, guid)["svg"])
    elif format == "dxf":
        bridge(B.export_drawing_dxf, guid, out)
    else:
        raise AgentError("bad_input", hint="a drawing has no PDF of its own: place it on a sheet, then sheets.export")
    return {"path": out}


# ---------------------------------------------------------------- sheets

@tool("sheets.list", {})
def sheets_list(session):
    """List the sheets: number, title, paper size and the drawings placed on each."""
    return {"sheets": [{"number": s["number"], "title": s["title"], "paper": s["paper"],
                        "views": [{k: v[k] for k in ("drawing", "name", "x", "y", "scale")} for v in s["views"]]}
                       for s in bridge(SH.sheets)["sheets"]]}


@tool("sheets.create", {"required": ["title"], "properties": {
    "title": {"type": "string"}, "paper": {"type": "string", "enum": ["A1", "A3"], "description": "Default A1."}}},
    writes=True)
def sheets_create(session, title, paper="A1"):
    """Create an empty sheet; it gets the next number (A01, A02...)."""
    return {"number": bridge(SH.add_sheet, paper, title)["number"]}


@tool("sheets.place_drawing", {"required": ["sheet", "drawing"], "properties": {
    "sheet": _SHEET, "drawing": _DRAWING,
    "at": {"type": "array", "items": {"type": "number"}, "description": "[x, y] top-left on the sheet in mm; "
                                                                       "default: a free spot."},
    "scale": {"type": "integer", "minimum": 1, "description": "1:scale (default 100)."}}}, writes=True)
def sheets_place_drawing(session, sheet, drawing, at=None, scale=100):
    """Put a drawing on a sheet at a scale (1:100 by default)."""
    if at is not None and len(at) != 2:
        raise AgentError("bad_input", hint="at must be [x, y] in mm")
    x, y = at if at else (-1, -1)
    number = _sheet_number(sheet)
    bridge(SH.place_drawing, number, _drawing_guid(drawing), x, y, scale)
    return {"sheet": number}


def _app_binary() -> pathlib.Path | None:
    env = os.environ.get("KIMBIM_APP")
    candidates = [pathlib.Path(env)] if env else [
        pathlib.Path(__file__).resolve().parents[4] / "build" / "app" / name for name in ("kimbim-app.exe", "kimbim-app")]
    return next((c for c in candidates if c.is_file()), None)


def _pdf(number: str, out: str) -> None:
    app = _app_binary()
    if app is None:
        raise AgentError("render_failed", hint="The KimBim app binary was not found (build it with `pixi run "
                         "app-build`, or set KIMBIM_APP to its path). SVG and DXF need no binary.")
    with tempfile.TemporaryDirectory() as tmp:
        ifc = str(pathlib.Path(tmp) / "model.ifc")
        bridge(D.export_ifc, ifc)
        try:
            done = subprocess.run([str(app), "--export-sheet", number, ifc, out], capture_output=True, text=True,
                                  timeout=300)
        except (OSError, subprocess.SubprocessError) as ex:
            raise AgentError("render_failed", hint=str(ex)) from None
    if done.returncode != 0 or not pathlib.Path(out).exists():
        raise AgentError("render_failed", hint=(done.stderr or done.stdout or f"exit code {done.returncode}").strip())


@tool("sheets.export", {"required": ["sheet", "format", "out"], "properties": {
    "sheet": _SHEET, "format": {"type": "string", "enum": ["pdf", "svg", "dxf"]}, "out": _OUT}})
def sheets_export(session, sheet, format, out):
    """Export a sheet as PDF, SVG or DXF. PDF needs the KimBim app binary (render_failed when it is missing)."""
    number = _sheet_number(sheet)
    if format == "svg":
        bridge(SH.export_sheet_svg, number, out)
    elif format == "dxf":
        bridge(B.export_sheet_dxf, number, out)
    else:
        _pdf(number, out)
    return {"path": out}


# ---------------------------------------------------------------- schedules

def _scheme(ref) -> dict:
    want = str(ref).strip().lower()
    for s in SC.schemes():
        if s["id"].lower() == want or (s.get("name") or "").strip().lower() == want:
            return s
    raise AgentError("not_found", what=ref)


_SCHEDULE = {"type": "string", "description": "Schedule id or name (schedules.list lists them)."}


@tool("schedules.list", {})
def schedules_list(session):
    """List the schedules (door, window, wall... tables) with the classes and fields of each."""
    return {"schedules": [{"id": s["id"], "name": s.get("name", ""), "builtin": s["builtin"],
                           "classes": s.get("classes", []), "fields": s.get("fields", [])}
                          for s in SC.schemes()]}


@tool("schedules.get", {"required": ["schedule"], "properties": {
    "schedule": _SCHEDULE, "limit": {"type": "integer", "minimum": 1, "description": "Rows to return (default 500)."}}})
def schedules_get(session, schedule, limit=500):
    """Compute a schedule: its columns, rows (with the GlobalIds each row stands for), totals and count."""
    r = bridge(SC.schedule, _scheme(schedule)["id"])
    rows = r["rows"]
    return {"columns": r["columns"], "rows": rows[:limit], "totals": r["totals"], "count": r["count"],
            "truncated": len(rows) > limit}


@tool("schedules.export", {"required": ["schedule", "out"], "properties": {
    "schedule": _SCHEDULE, "out": {**_OUT, "description": "Path of the CSV file to write."}}})
def schedules_export(session, schedule, out):
    """Export a schedule as a CSV file."""
    bridge(SC.export_schedule, _scheme(schedule)["id"], False, out)
    return {"path": out}


# ---------------------------------------------------------------- checks

@tool("checks.run", {"required": ["checks"], "properties": {
    "checks": {"type": "array", "items": {"type": "string", "enum": list(C.CHECKS)}, "minItems": 1},
    "options": {"type": "object", "description": "Options per check, {check: {...}} (clash: mode, clearance...)."}}})
def checks_run(session, checks, options=None):
    """Run model checks: schema (IFC validation), ids (information requirements), clash (collisions) and model
    (duplicates, rooms, zero-length walls...). Returns the issues of each."""
    out = []
    for name in checks:
        r = bridge(C.run_check, name, json.dumps((options or {}).get(name) or {}))
        out.append({k: r[k] for k in ("check", "title", "counts", "issues", "groups", "seconds") if k in r})
    return {"checks": out}


@tool("checks.ids_report", {"required": ["out"], "properties": {"out": _OUT}})
def checks_ids_report(session, out):
    """Write the report of the last IDS check as a file."""
    bridge(C.export_ids_report, out)
    return {"path": out}
