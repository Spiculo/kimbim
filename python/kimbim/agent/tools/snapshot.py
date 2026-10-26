# SPDX-License-Identifier: GPL-3.0-or-later
"""snapshot.take (D102, spec §6): a picture of the model, a plan, a drawing or a sheet, so an agent can see its
work. 3D comes from the app's own renderer with no window (agent.render); plans, sections, elevations and sheets
are the drawing generator's SVG (the code path drawings.export / sheets.export use), turned into a PNG by the same
helper unless `format: "svg"`. A read tool: the model is only written out as a copy for the renderer."""
from __future__ import annotations

import pathlib
from datetime import datetime

from ... import app_bridge as B
from ... import authoring as A
from ... import documents as D
from ... import drawings as DR
from ... import graphics as G
from ... import settings as S
from ... import sheets as SH
from ... import versioning as V
from .. import messages
from ..catalogue import SELECTOR, AgentError, ToolResult, bridge, tool
from ..render import ADDED, MODIFIED, Renderer
from .common import lengths, level_guid
from .outputs import _drawing_guid, _sheet_number

PRESETS = ["top", "bottom", "front", "back", "left", "right", "iso-se", "iso-sw", "iso-ne", "iso-nw"]
_POINT = {"type": "array", "items": {"type": ["number", "string"]}}
_3D_ONLY = ("elements", "isolate", "highlight", "changes", "camera", "style", "cut")
_HIDDEN = ("IfcOpeningElement", "IfcVirtualElement")  # in a compare, never drawn: nothing to frame on


def _out_path(out: str, ext: str) -> str:
    if out:
        return out
    folder = D.data_dir() / "agent" / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.{ext}")


def _renderer(session) -> Renderer:
    if getattr(session, "renderer", None) is None:
        session.renderer = Renderer()
    return session.renderer


def _check_purpose(purpose: str) -> None:
    if purpose and purpose not in G.effective("purposes", S.current()):
        raise AgentError("not_found", what=purpose)


def _changes(session, changes, client, task_id) -> dict:
    """The compare of the snapshot's `changes`: {added, modified, removed} lists as versioning.compare gives."""
    if changes == "task":
        task = session.tasks.open_task(client, task_id)
        if task is None:
            raise AgentError("no_task")
        if V._project is None or not task.base_version:
            raise AgentError("not_versioned")
        rev_a, rev_b = task.base_version, "WORKING"
    else:
        rev_a, rev_b = changes.get("rev_a"), changes.get("rev_b") or "WORKING"
        if not rev_a:
            raise AgentError("bad_input", hint=messages.text("hint_required", field="changes.rev_a"))
        if V._project is None:
            raise AgentError("not_versioned")
    r = bridge(V.compare, rev_a, rev_b)
    return {k: r.get(k) or [] for k in ("added", "modified", "removed")}


def _camera(session, camera):
    if camera is None or isinstance(camera, str):
        return camera
    eye, target = (lengths(session, *camera.get(k) or ()) for k in ("eye", "target"))
    if len(eye) != 3 or len(target) != 3:
        raise AgentError("bad_input", hint="camera eye and target must be [x, y, z]")
    out = {"eye": eye, "target": target}
    if camera.get("up") is not None:
        out["up"] = [float(v) for v in camera["up"]]
    if camera.get("fov") is not None:
        out["fov"] = float(camera["fov"])
    return out


def _take_3d(session, args, client, task_id) -> dict:
    req = {"out": _out_path(args["out"], "png"), "size": args["size"]}
    frame = session.resolve(args["elements"]) if args["elements"] is not None else []
    legend, counts = [], None
    if args["changes"] not in (None, "none"):
        diff = _changes(session, args["changes"], client, task_id)
        colours = {}
        for kind, colour in (("added", ADDED), ("modified", MODIFIED)):
            for e in diff[kind]:
                colours[e["guid"]] = colour
            legend.append({"colour": colour, "meaning": kind, "count": len(diff[kind])})
        counts = {k: len(v) for k, v in diff.items()}
        req["colours"] = colours
        if not frame:  # the camera frames what changed (the whole model when nothing did)
            frame = [e["guid"] for e in diff["added"] + diff["modified"] if e["type"] not in _HIDDEN]
    if frame:
        req["frame"] = frame
        req["isolate"] = bool(args["isolate"])
    if args["highlight"] is not None:
        req["highlight"] = session.resolve(args["highlight"])
    if args["camera"] is not None:
        req["camera"] = _camera(session, args["camera"])
    for key in ("style", "purpose"):
        if args[key]:
            req[key] = args[key]
    if args["cut"] is not None:
        base = 0.0
        if args["level"]:
            guid = level_guid(args["level"])
            base = next(st["elevation"] for st in bridge(A.storeys)["storeys"] if st["guid"] == guid)
        req["cut"] = base + lengths(session, args["cut"])[0]
    reply = _renderer(session).render3d(session, **req)
    if req.get("highlight"):
        legend.append({"colour": reply.get("highlight_colour"), "meaning": "highlight",
                       "count": len(req["highlight"])})
    result = {"path": reply["out"], "format": "png", "size": reply["size"], "camera": {**reply["camera"], "unit": "m"},
              "framed": reply["framed"], "legend": legend, "view": "3d"}
    if counts is not None:
        result["changes"] = counts
    return result


def _drawing_for(view, args) -> str:
    """The GlobalId of the drawing a 2D view shows."""
    if args["drawing"]:
        guid = _drawing_guid(args["drawing"])
        kind = next((d["kind"] for d in bridge(DR.drawings)["drawings"] if d["guid"] == guid), None)
        if kind is None:
            raise AgentError("not_found", what=args["drawing"])
        if view != "drawing" and kind != view:
            raise AgentError("bad_input", hint=f"{args['drawing']} is a {kind}, not a {view}")
        return guid
    if view == "drawing":
        raise AgentError("bad_input", hint=messages.text("hint_required", field="drawing"))
    drawings = [d for d in bridge(DR.drawings)["drawings"] if d["kind"] == view]
    if view == "plan":  # the level's plan; the lowest level's by default (drawings lists them by height)
        if args["level"]:
            level = level_guid(args["level"])
            drawings = [d for d in drawings if d.get("storey") == level]
            if not drawings:
                raise AgentError("not_found", what=f"{args['level']} floor plan",
                                 hint="create it with drawings.create kind=plan")
    if not drawings:
        raise AgentError("not_found", what=view)
    return drawings[0]["guid"]


def _take_2d(session, view, args) -> dict:
    if view == "sheet":
        sheets = bridge(SH.sheets)["sheets"]
        if not args["sheet"] and not sheets:
            raise AgentError("not_found", what="sheet")
        number = _sheet_number(args["sheet"]) if args["sheet"] else sheets[0]["number"]
        svg = bridge(SH.sheet_svg, number)["svg"]  # styled by the sheet's own purpose
    else:
        svg = bridge(DR.generate_drawing, _drawing_for(view, args), "", args["purpose"] or "")["svg"]
    if args["format"] == "svg":
        out = _out_path(args["out"], "svg")
        try:
            pathlib.Path(out).write_text(svg, encoding="utf-8")
        except OSError as ex:
            raise AgentError("bridge_error", hint=str(ex)) from None
        return {"path": out, "format": "svg", "size": None, "camera": None, "framed": None, "legend": [],
                "view": view}
    renderer = _renderer(session)
    source = renderer.folder() / f"view-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.svg"
    try:
        source.write_text(svg, encoding="utf-8")
    except OSError as ex:
        raise AgentError("bridge_error", hint=str(ex)) from None
    try:
        reply = renderer.svg2png(str(source), _out_path(args["out"], "png"), args["size"])
    finally:
        source.unlink(missing_ok=True)
    return {"path": reply["out"], "format": "png", "size": reply["size"], "camera": None, "framed": None,
            "legend": [], "view": view}


@tool("snapshot.take", {"properties": {
    "view": {"type": "string", "enum": ["3d", "plan", "section", "elevation", "drawing", "sheet"],
             "description": "Default 3d."},
    "level": {"type": "string", "description": "plan: the level (name or GlobalId; default the lowest). 3d: the "
                                               "level `cut` is measured from."},
    "drawing": {"type": "string", "description": "drawing (or plan/section/elevation): its name or GlobalId; "
                                                 "default the first of the view's kind."},
    "sheet": {"type": "string", "description": "sheet: its number or title; default the first sheet."},
    "elements": {**SELECTOR, "description": "3d: the elements to frame on (default the whole model, or what "
                                            "changed with `changes`)."},
    "isolate": {"type": "boolean", "description": "3d: show only the framed elements (default false)."},
    "highlight": {**SELECTOR, "description": "3d: elements drawn in the highlight colour."},
    "changes": {"oneOf": [{"type": "string", "enum": ["none", "task"]},
                          {"type": "object", "required": ["rev_a"], "properties": {
                              "rev_a": {"type": "string"}, "rev_b": {"type": "string"}},
                           "additionalProperties": False}],
                "description": "3d: colour the changes as the app's Compare does: \"task\" (your open task against "
                               "its base version) or {rev_a, rev_b} (rev_b default WORKING). Default none."},
    "camera": {"oneOf": [{"type": "string", "enum": PRESETS},
                         {"type": "object", "required": ["eye", "target"], "properties": {
                             "eye": _POINT, "target": _POINT, "up": {"type": "array", "items": {"type": "number"}},
                             "fov": {"type": "number", "minimum": 0, "maximum": 179}},
                          "additionalProperties": False}],
               "description": "3d: a view-cube preset (default iso-se, framed on the target) or {eye, target "
                              "(project units), up, fov (degrees; 0 or none: orthographic)}."},
    "style": {"type": "string", "enum": ["shaded", "white", "lines", "textured"], "description": "3d; default "
                                                                                                  "shaded."},
    "purpose": {"type": "string", "description": "The purpose (pen set, visibility); default the project's."},
    "cut": {"type": ["number", "string"], "description": "3d: a horizontal cut at this height (project units or "
                                                         "\"1.1m\"), above `level` when given."},
    "size": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 8192},
             "description": "[w, h] in pixels; default [1024, 768]."},
    "format": {"type": "string", "enum": ["png", "svg"], "description": "png, or svg for 2D views (default png)."},
    "out": {"type": "string", "description": "The file to write; default a new file in the KimBim data folder."}}})
def take(session, view="3d", level="", drawing="", sheet="", elements=None, isolate=False, highlight=None,
         changes=None, camera=None, style="", purpose="", cut=None, size=None, format="png", out="",
         client="cli", task_id=""):
    """Take a picture of the model to check your work: a 3D view (optionally framed on elements, with what your
    task changed coloured as the app's Compare shows it), a floor plan, a section or elevation, any drawing, or a
    sheet. Returns the image file's path, the camera used, how many elements are in the picture and the colour
    legend. It changes nothing in the model."""
    if B._model is None:
        raise AgentError("no_model")
    size = [1024, 768] if size is None else size
    if len(size) != 2:
        raise AgentError("bad_input", hint="size must be [w, h]")
    _check_purpose(purpose)
    args = dict(level=level, drawing=drawing, sheet=sheet, elements=elements, isolate=isolate,
                highlight=highlight, changes=changes, camera=camera, style=style, purpose=purpose, cut=cut,
                size=size, format=format, out=out)
    if view == "3d":
        if format == "svg":
            raise AgentError("bad_input", hint="svg is for 2D views (plan, section, elevation, drawing, sheet)")
        return _take_3d(session, args, client, task_id)
    ignored = [k for k in _3D_ONLY if args[k] not in (None, False, "", "none")]
    if view == "sheet" and purpose:
        ignored.append("purpose")  # a sheet is drawn with its own purpose
    result = _take_2d(session, view, args)
    if ignored:
        return ToolResult(result, [messages.text("warn_snapshot_ignored", fields=", ".join(ignored))])
    return result
