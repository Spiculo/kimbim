# SPDX-License-Identifier: GPL-3.0-or-later
"""Element tools: find, get and the edit tools (D102). Elements are chosen with the shared SELECTOR."""
from __future__ import annotations

import json
import math

import ifcopenshell.util.element

from ... import app_bridge as B
from ... import authoring as A
from ... import editing as E
from ... import graphics as G
from ... import layers as Ly
from ... import modify as M
from ... import renovation as R
from .. import messages, units
from ..catalogue import SELECTOR, AgentError, ToolResult, bridge, tool
from .common import lengths, level_guid, point


def _offset(cursor: str) -> int:
    try:
        n = int(cursor or 0)
    except ValueError:
        n = -1
    if n < 0:
        raise AgentError("bad_input", hint="cursor must come from a previous next_cursor")
    return n


def _level_name(e) -> str:
    for rel in getattr(e, "ContainedInStructure", None) or ():
        return rel.RelatingStructure.Name or ""
    return ""


@tool("elements.find", {"required": ["elements"], "properties": {
    "elements": SELECTOR,
    "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Page size (default 200)."},
    "cursor": {"type": "string", "description": "next_cursor from the previous page."}}})
def find(session, elements, limit=200, cursor=""):
    """Find elements and list them: GlobalId, label, kind and level, a page at a time."""
    guids = session.resolve(elements)
    start, limit = _offset(cursor), int(limit)
    items = []
    for g in guids[start:start + limit]:
        e = B._model.by_guid(g)
        items.append({"guid": g, "label": session.label(g), "kind": G.kind_of(e), "level": _level_name(e)})
    end = start + limit
    return {"items": items, "total": len(guids), "next_cursor": str(end) if end < len(guids) else ""}


def _related(e) -> dict:
    """The wall a door/window sits in (host), or what fills a wall's openings (openings), as GlobalIds."""
    out: dict = {}
    for fill in getattr(e, "FillsVoids", None) or ():
        for void in getattr(fill.RelatingOpeningElement, "VoidsElements", None) or ():
            out["host"] = void.RelatingBuildingElement.GlobalId
    fillers = [f.RelatedBuildingElement.GlobalId for v in getattr(e, "HasOpenings", None) or ()
               for f in getattr(v.RelatedOpeningElement, "HasFillings", None) or ()]
    if fillers:
        out["openings"] = fillers
    return out


@tool("elements.get", {"required": ["elements"], "properties": {
    "elements": SELECTOR, "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Most elements to describe (default 50)."}}})
def get(session, elements, limit=50):
    """Describe elements in full: class, type, level, dimensions (metres), property sets, host and openings."""
    guids = session.resolve(elements)
    limit = int(limit)
    out = []
    for g in guids[:limit]:
        e = B._model.by_guid(g)
        t = ifcopenshell.util.element.get_type(e)
        props = bridge("properties_multi", json.dumps([g]))
        psets = {name: {k: v["value"] for k, v in group.items()}
                 for name, group in (props.get("psets") or {}).items() if name != A.DIMENSIONS}
        row = {"guid": g, "label": session.label(g), "class": e.is_a(), "type": (t.Name or "") if t else "",
               "level": _level_name(e),
               "dimensions": {"unit": "m", "values": {n: round(v, 6) for n, v, _ in A.element_dimensions(e)}},
               "properties": psets}
        row.update(_related(e))
        out.append(row)
    return {"items": out, "total": len(guids), "truncated": len(guids) > limit}


# ---------------------------------------------------------------- write tools (D102)

_DIMENSIONS = (("width", "Width"), ("height", "Height"), ("sill", "Sill height"), ("length", "Length"))
_LENGTH = {"type": ["number", "string"], "description": "Project units, \"50cm\", or relative \"+50cm\" / \"-10%\"."}
_NUMBER = {"type": ["number", "string"], "description": "Project units or a string with units (\"50cm\")."}


def _guids(guids) -> str:
    return json.dumps(list(guids))


@tool("elements.set_dimensions", {"required": ["elements"], "properties": {
    "elements": SELECTOR, "width": _LENGTH, "height": _LENGTH, "sill": _LENGTH, "length": _LENGTH}}, writes=True)
def set_dimensions(session, elements, **values):
    """Change dimensions of elements: width, height and sill of doors/windows, height or length of walls, columns
    and beams. Values are absolute or relative to each element's own size ("+50cm", "-10%"). Elements without
    the dimension are skipped with a warning; a result of 0 or less refuses the whole call."""
    guids = session.resolve(elements)
    plan: dict[tuple[str, float], list[str]] = {}
    warnings: list[str] = []
    for guid in guids:
        current = {n: v for n, v, _ in A.element_dimensions(B._model.by_guid(guid))}
        for key, name in _DIMENSIONS:
            if key not in values:
                continue
            if name not in current:
                warnings.append(messages.text("warn_no_dimension", label=session.label(guid), name=name))
                continue
            try:
                target = units.apply_change(current[name], values[key], session.unit)
            except ValueError:
                raise AgentError("bad_length", value=values[key]) from None
            if target < -1e-9 if name == "Sill height" else target <= 1e-9:
                raise AgentError("bad_length", value=values[key])
            plan.setdefault((name, round(target, 6)), []).append(guid)
    if not plan:
        raise AgentError("no_match", hint="; ".join(warnings))
    for (name, target), group in plan.items():
        bridge(A.set_dimension, _guids(group), name, target)
    return ToolResult({"changed": len({g for group in plan.values() for g in group})}, warnings)


def _check_keys(keys) -> None:
    for key in keys:
        if "." not in key.strip(".") or key.startswith("."):
            raise AgentError("bad_input", hint=messages.text("hint_bad_property", key=key))


@tool("elements.set_properties", {"required": ["elements", "properties"], "properties": {
    "elements": SELECTOR, "properties": {
        "type": "object", "description": "{\"Pset.Name\": value}; booleans, numbers and text keep their type.",
        "additionalProperties": {"type": ["string", "number", "boolean"]}}}}, writes=True)
def set_properties(session, elements, properties):
    """Set property values on elements, creating the property set when needed."""
    guids = session.resolve(elements)
    _check_keys(properties)
    for key, value in properties.items():
        pset, prop = key.split(".", 1)
        bridge(B.set_property, _guids(guids), pset, prop, json.dumps(value))
    return {"elements": len(guids), "properties": list(properties)}


@tool("elements.remove_properties", {"required": ["elements", "properties"], "properties": {
    "elements": SELECTOR, "properties": {"type": "array", "items": {"type": "string"},
                                         "description": "[\"Pset.Name\", ...]"}}}, writes=True)
def remove_properties(session, elements, properties):
    """Remove properties from elements."""
    guids = session.resolve(elements)
    _check_keys(properties)
    for key in properties:
        pset, prop = key.split(".", 1)
        bridge(B.remove_property, _guids(guids), pset, prop)
    return {"elements": len(guids), "properties": list(properties)}


@tool("elements.rename", {"required": ["elements", "name"], "properties": {
    "elements": SELECTOR, "name": {"type": "string"}}}, writes=True)
def rename(session, elements, name):
    """Give elements a name."""
    guids = session.resolve(elements)
    bridge(B.set_name, _guids(guids), name)
    return {"elements": len(guids)}


@tool("elements.move", {"required": ["elements"], "properties": {
    "elements": SELECTOR, "dx": _NUMBER, "dy": _NUMBER, "dz": _NUMBER}}, writes=True)
def move(session, elements, dx=0, dy=0, dz=0):
    """Move elements by dx, dy, dz. Joined walls follow and hosted doors/windows move with their wall."""
    guids = session.resolve(elements)
    x, y, z = lengths(session, dx, dy, dz)
    bridge(A.move_elements, _guids(guids), x, y, z)
    return {"elements": len(guids)}


def _centre(guids) -> tuple[float, float]:
    """The middle of the selection's footprint: wall axes and element origins (metres)."""
    points = []
    for g in guids:
        e = B._model.by_guid(g)
        axis = A._axis_world(e) if e.is_a("IfcWall") else None
        points.extend(axis if axis else [A._world(e)[:2]])
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


@tool("elements.rotate", {"required": ["elements", "angle"], "properties": {
    "elements": SELECTOR,
    "angle": {"type": ["number", "string"], "description": "Degrees (90, \"90deg\") or \"1.57rad\"; counter-clockwise."},
    "center": {"type": "array", "items": {"type": "number"}, "description":
               "[x, y] to turn around (project units); default the middle of the selection."}}}, writes=True)
def rotate(session, elements, angle, center=None):
    """Rotate elements around a point on the plan; joined walls follow."""
    guids = session.resolve(elements)
    try:
        degrees = units.parse_angle(angle)
    except ValueError:
        raise AgentError("bad_input", hint=messages.text("hint_bad_angle", value=angle)) from None
    if center is not None and len(center) != 2:
        raise AgentError("bad_input", hint="center must be [x, y]")
    cx, cy = lengths(session, *center) if center is not None else _centre(guids)
    bridge(A.rotate_elements, _guids(guids), cx, cy, math.radians(degrees))
    return {"elements": len(guids), "center_m": [round(cx, 6), round(cy, 6)]}


@tool("elements.copy", {"required": ["elements"], "properties": {
    "elements": SELECTOR, "dx": _NUMBER, "dy": _NUMBER, "dz": _NUMBER,
    "level": {"type": "string", "description": "Level name or GlobalId to copy onto (same plan position)."}}},
    writes=True)
def copy(session, elements, dx=0, dy=0, dz=0, level=""):
    """Copy elements, shifted by dx, dy, dz, optionally onto another level."""
    guids = session.resolve(elements)
    x, y, z = lengths(session, dx, dy, dz)
    storey = level_guid(level) if level else ""
    bridge(E.copy_elements, _guids(guids), x, y, z, storey)
    return {"elements": len(guids)}


@tool("elements.mirror", {"required": ["elements", "line"], "properties": {
    "elements": SELECTOR,
    "line": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
             "description": "[[x1, y1], [x2, y2]]: the mirror line (project units)."},
    "copy": {"type": "boolean", "description": "Mirror a copy and keep the originals (default false)."}}},
    writes=True)
def mirror(session, elements, line, copy=False):
    """Mirror elements across a line on the plan."""
    guids = session.resolve(elements)
    if len(line) != 2 or any(len(p) != 2 for p in line):
        raise AgentError("bad_input", hint="line must be [[x1, y1], [x2, y2]]")
    x1, y1, x2, y2 = lengths(session, line[0][0], line[0][1], line[1][0], line[1][1])
    bridge(E.mirror_elements, _guids(guids), x1, y1, x2, y2, bool(copy))
    return {"elements": len(guids)}


@tool("elements.copy_to_level", {"required": ["elements", "level"], "properties": {
    "elements": SELECTOR, "level": {"type": "string", "description": "Level name or GlobalId."}}}, writes=True)
def copy_to_level(session, elements, level):
    """Copy elements to another level at the same plan position (walls bring their doors and windows)."""
    guids = session.resolve(elements)
    bridge(A.copy_to_storey, _guids(guids), level_guid(level))
    return {"elements": len(guids)}


@tool("elements.delete", {"required": ["elements"], "properties": {"elements": SELECTOR}}, writes=True)
def delete(session, elements):
    """Delete elements (and the doors/windows they host)."""
    guids = session.resolve(elements)
    bridge(A.delete_elements, _guids(guids))
    return {"requested": len(guids)}


# ---------------------------------------------------------------- split / trim / join (D80)

_ELEMENT = {"type": "string", "description": "GlobalId of a wall or beam."}
_SPOT = {"type": "array", "items": _NUMBER, "description": "[x, y] in project units or strings with units."}
_OPENINGS = {"type": "string", "enum": ["refuse", "delete", "keep"],
             "description": "What to do with a door, window or opening the trim would leave outside the wall: "
                            "refuse (default), delete it, or keep it."}


@tool("elements.split", {"required": ["element", "at"], "properties": {
    "element": _ELEMENT, "at": _SPOT,
    "join": {"type": "boolean", "description": "Join the two pieces (default true)."}}}, writes=True)
def split(session, element, at, join=True):
    """Split a wall or beam at a point on its axis; doors and windows stay with the piece they are in."""
    x, y = point(session, at, "at")
    r = bridge(M.split_element, element, x, y, join)
    return {"element": element, "piece": r.get("piece", "")}


@tool("elements.trim", {"required": ["element", "at"], "properties": {
    "element": _ELEMENT, "at": _SPOT,
    "boundary": {"type": "string", "description": "GlobalId of the wall or beam to trim to."},
    "line": {"type": "array", "items": {"type": "array", "items": _NUMBER},
             "description": "[[x1, y1], [x2, y2]]: a boundary line (for example a grid line) instead of a boundary element."},
    "join": {"type": "boolean", "description": "Join the element to a boundary wall (default true)."},
    "openings": _OPENINGS}}, writes=True)
def trim(session, element, at, boundary="", line=None, join=True, openings="refuse"):
    """Trim or extend a wall or beam to a boundary wall/beam or line, keeping the side the point is on."""
    if bool(boundary) == (line is not None):
        raise AgentError("bad_input", hint="give boundary or line, not both")
    x, y = point(session, at, "at")
    bx1 = by1 = bx2 = by2 = 0.0
    if line is not None:
        if len(line) != 2 or any(len(p) != 2 for p in line):
            raise AgentError("bad_input", hint="line must be [[x1, y1], [x2, y2]]")
        bx1, by1, bx2, by2 = lengths(session, line[0][0], line[0][1], line[1][0], line[1][1])
    bridge(M.trim_extend, element, x, y, boundary or "", bx1, by1, bx2, by2, join, openings)
    return {"element": element}


@tool("elements.trim_corner", {"required": ["first", "first_at", "second", "second_at"], "properties": {
    "first": _ELEMENT, "first_at": _SPOT, "second": _ELEMENT, "second_at": _SPOT,
    "join": {"type": "boolean", "description": "Join the two walls in an L at the corner (default true)."},
    "openings": _OPENINGS}}, writes=True)
def trim_corner(session, first, first_at, second, second_at, join=True, openings="refuse"):
    """Trim or extend two walls or beams to their corner, keeping the side each point is on."""
    x1, y1 = point(session, first_at, "first_at")
    x2, y2 = point(session, second_at, "second_at")
    bridge(M.trim_corner, first, x1, y1, second, x2, y2, join, openings)
    return {"elements": [first, second]}


@tool("elements.join", {"required": ["first", "second"], "properties": {
    "first": {**_ELEMENT, "description": "GlobalId of the first wall or beam; a merge keeps its GlobalId."},
    "second": {**_ELEMENT, "description": "GlobalId of the second wall or beam."},
    "props": {"type": "string", "enum": ["keep", "refuse"],
              "description": "Merging collinear walls whose properties differ: keep the first's (default) or refuse."}}},
    writes=True)
def join(session, first, second, props="keep"):
    """Join two walls (L or T) or merge two collinear walls or beams into the first."""
    r = bridge(M.join_elements, first, second, props)
    return {"merged": bool(r.get("merged")), "first": first, "second": second}


@tool("elements.unjoin", {"required": ["elements"], "properties": {"elements": SELECTOR}}, writes=True)
def unjoin(session, elements):
    """Break the joins between walls or beams (one element: all its joins), giving them plain ends."""
    guids = session.resolve(elements)
    bridge(M.unjoin_elements, _guids(guids))
    return {"elements": len(guids)}


@tool("elements.stretch", {"required": ["element", "end", "to"], "properties": {
    "element": _ELEMENT,
    "end": {"type": "string", "enum": ["start", "end"], "description": "The wall end to move."},
    "to": _SPOT}}, writes=True)
def stretch(session, element, end, to):
    """Move one end of a wall to a point, stretching or shortening it; joins at that end are dropped."""
    from ... import curved_walls

    x, y = point(session, to, "to")
    try:
        e = B._model.by_guid(element) if B._model is not None else None
    except RuntimeError:
        e = None
    if e is None:
        raise AgentError("not_found", what=element)
    if not e.is_a("IfcWall"):
        raise AgentError("bad_input", hint="element must be a wall")
    axis = A._axis_world(e)
    if axis is None and curved_walls.is_curved(e):
        axis = tuple(tuple(float(c) for c in p) for p in curved_walls.ends_world(e))
    if axis is None:
        raise AgentError("bad_input", hint="not a wall with an axis")
    (x1, y1), (x2, y2) = axis
    if end == "start":
        x1, y1 = x, y
    else:
        x2, y2 = x, y
    bridge(A.set_wall_axis, element, x1, y1, x2, y2)
    return {"element": element}


# ---------------------------------------------------------------- array / offset / fillet / resize

@tool("elements.array", {"required": ["elements", "kind"], "properties": {
    "elements": SELECTOR,
    "kind": {"type": "string", "enum": ["linear", "polar", "rectangular"]},
    "dx": _NUMBER, "dy": _NUMBER,
    "count": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "Number of copies (linear, polar)."},
    "center": {"type": "array", "items": _NUMBER, "description": "Polar: [x, y] to turn around."},
    "angle": {"type": ["number", "string"], "description": "Polar: degrees (90, \"90deg\") or \"1.57rad\"."},
    "nx": {"type": "integer", "minimum": 1, "description": "Rectangular: columns."},
    "ny": {"type": "integer", "minimum": 1, "description": "Rectangular: rows."}}}, writes=True)
def array(session, elements, kind, dx=0, dy=0, count=1, center=None, angle=None, nx=1, ny=1):
    """Multiply elements: a linear row, a polar turn, or a rectangular grid of copies."""
    guids = session.resolve(elements)
    if kind == "linear":
        params = {"dx": lengths(session, dx)[0], "dy": lengths(session, dy)[0], "count": int(count)}
    elif kind == "polar":
        if center is None or angle is None:
            raise AgentError("bad_input", hint="polar needs center [x, y] and angle")
        cx, cy = point(session, center, "center")
        try:
            radians = math.radians(units.parse_angle(angle))
        except ValueError:
            raise AgentError("bad_input", hint=messages.text("hint_bad_angle", value=angle)) from None
        params = {"cx": cx, "cy": cy, "angle": radians, "count": int(count)}
    else:
        params = {"dx": lengths(session, dx)[0], "dy": lengths(session, dy)[0], "nx": int(nx), "ny": int(ny)}
    r = bridge(E.array_elements, _guids(guids), kind, json.dumps(params))
    return {"copies": r.get("guids", []), "count": len(r.get("guids", []))}


@tool("elements.offset", {"required": ["elements", "distance"], "properties": {
    "elements": SELECTOR,
    "distance": {**_NUMBER, "description": "Perpendicular distance in project units; negative offsets the other way."}}},
    writes=True)
def offset(session, elements, distance):
    """Offset walls as a parallel copy and grow or shrink slabs in place (negative shrinks)."""
    guids = session.resolve(elements)
    r = bridge(E.offset_elements, _guids(guids), lengths(session, distance)[0])
    return {"copies": r.get("guids", []), "count": len(r.get("guids", []))}


@tool("elements.fillet", {"required": ["elements", "size"], "properties": {
    "elements": SELECTOR,
    "size": {**_NUMBER, "description": "Radius (fillet) or setback distance (chamfer) in project units."},
    "mode": {"type": "string", "enum": ["fillet", "chamfer"], "description": "Default fillet."}}}, writes=True)
def fillet(session, elements, size, mode="fillet"):
    """Round (fillet) or cut (chamfer) the corners of slabs, 2D polylines/fills, or two meeting walls."""
    guids = session.resolve(elements)
    bridge(E.fillet_corners, _guids(guids), lengths(session, size)[0], mode)
    return {"elements": len(guids), "mode": mode}


@tool("elements.resize", {"required": ["elements", "factor"], "properties": {
    "elements": SELECTOR,
    "factor": {"type": "number", "description": "Scale factor, more than 0 and not 1."},
    "center": {"type": "array", "items": _NUMBER,
               "description": "[x, y] to scale about (project units); default the selection's middle."}}}, writes=True)
def resize(session, elements, factor, center=None):
    """Scale elements about a point on the plan; thicknesses and heights stay."""
    guids = session.resolve(elements)
    try:
        k = float(factor)
    except (TypeError, ValueError):
        raise AgentError("bad_input", hint="factor must be a number") from None
    if k <= 0 or abs(k - 1.0) < 1e-12:
        raise AgentError("bad_input", hint="factor must be more than 0 and not 1")
    cx = cy = ""
    if center is not None:
        cx, cy = point(session, center, "center")
    bridge(E.resize_elements, _guids(guids), cx, cy, k)
    return {"elements": len(guids), "factor": k}


@tool("elements.get_slab_outline", {"required": ["element"], "properties": {
    "element": {"type": "string", "description": "GlobalId of a slab."}}})
def get_slab_outline(session, element):
    """A slab's outline points in world metres, for moving, adding or deleting corners."""
    return bridge(E.slab_outline, element)


@tool("elements.set_slab_outline", {"required": ["element", "points"], "properties": {
    "element": {"type": "string", "description": "GlobalId of a slab."},
    "points": {"type": "array", "items": {"type": "array", "items": _NUMBER},
               "description": "The new outline [x, y] points (at least 3, not crossing itself)."}}}, writes=True)
def set_slab_outline(session, element, points):
    """Give a slab a new outline (moving, adding or deleting corners); its thickness and level stay."""
    if not isinstance(points, (list, tuple)) or len(points) < 3:
        raise AgentError("bad_input", hint="points must be at least three [x, y] pairs")
    pts = [list(point(session, p, "points")) for p in points]
    bridge(E.set_slab_outline, element, json.dumps(pts))
    return {"element": element, "points": pts}


@tool("elements.set_slab_slope", {"required": ["elements"], "properties": {
    "elements": SELECTOR,
    "slope_x": {"type": "number", "description": "Rise over run along the slab's local +X (0 = flat)."},
    "slope_y": {"type": "number", "description": "Rise over run along the slab's local +Y."}}}, writes=True)
def set_slab_slope(session, elements, slope_x=0, slope_y=0):
    """Tilt slabs: 0, 0 returns them to horizontal."""
    guids = session.resolve(elements)
    r = bridge(A.set_slab_slope, _guids(guids), slope_x, slope_y)
    return {"elements": len(r.get("slabs", [])), "slope_x": slope_x, "slope_y": slope_y}


@tool("elements.get_slab_slope", {"required": ["element"], "properties": {
    "element": {"type": "string", "description": "GlobalId of a slab."}}})
def get_slab_slope(session, element):
    """A slab's slope (rise over run)."""
    return bridge(A.slab_slope, element)


@tool("elements.set_layer", {"required": ["elements", "layer"], "properties": {
    "elements": SELECTOR, "layer": {"type": "string", "description": "An existing layer's name."}}}, writes=True)
def set_layer(session, elements, layer):
    """Move elements to a layer."""
    guids = session.resolve(elements)
    bridge(Ly.assign_layer, _guids(guids), layer)
    return {"elements": len(guids)}


@tool("elements.set_status", {"required": ["elements", "status"], "properties": {
    "elements": SELECTOR, "status": {"type": "string", "enum": list(G.STATUS_KEYS)}}}, writes=True)
def set_status(session, elements, status):
    """Set the renovation status of elements: existing, demolish, new, temporary or auxiliary."""
    guids = session.resolve(elements)
    bridge(R.set_status, _guids(guids), status)
    return {"elements": len(guids)}
