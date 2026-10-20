# SPDX-License-Identifier: GPL-3.0-or-later
"""Associative tags and labels (doc 14 §13, D87; Archicad's Label tool with autotext, its door and
window markers and zone stamps). Same protocol as app_bridge.

A tag is an IfcAnnotation TAG on its element's level (drawn by kimbim.symbols) assigned to the element
with an IfcRelAssignsToProduct (IFC's way to say what an annotation annotates; the element's GlobalId
is also kept in the tag's property set, so a copied tag finds it). Its text comes from a **template**
such as "{Mark}" or "{Type}\\n{Width}×{Height}": each {field} is one of D77's schedule fields (Name,
Mark, Type, Level, a quantity such as Area or Width, or Pset.Property); "{Mark|Name}" takes the first
that has a value. A line whose fields are all empty is left out.

Tags **follow their element**: after every edit (an AFTER_ACTION hook, inside the same undo step) each
tag's text is resolved again and, when its element's anchor moved and the tag itself did not, the
tag moves with it; the IFC representation is rewritten only when something changed. A tag whose
element is gone is deleted with it (Archicad deletes associative labels with their element).

Tag **styles** are the `tag_styles` project settings table (D73's way: versioned, merged; the
built-ins unless the project changes them): name, the IFC classes they tag, template, shape (none,
circle, box, hexagon), text size (mm on paper), leader, and where the tag goes from the element's
anchor ([along, across] metres in the element's frame, across measured from its face). The **room
stamp** style is also the text of every room's own stamp (rooms keep their stamp, as Archicad's zones).
"""
from __future__ import annotations

import json
import math
import re
import sys
import traceback

import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import ifcopenshell.util.unit
import numpy as np

from . import app_bridge as B
from . import symbols as S

KEY = "tag_styles"
BUILTIN = {
    "door": {"name": "Door marker", "classes": ["IfcDoor"], "template": "{Mark}\n{Width}×{Height}", "shape": "none",
             "size": 2.0, "leader": False, "offset": [0.0, -0.5]},
    "window": {"name": "Window marker", "classes": ["IfcWindow"], "template": "{Mark}\n{Width}×{Height}",
               "shape": "none", "size": 2.0, "leader": False, "offset": [0.0, -0.5]},
    "wall": {"name": "Wall tag", "classes": ["IfcWall"], "template": "{Type}", "shape": "box", "size": 2.0,
             "leader": False, "offset": [0.0, 0.4]},
    "room": {"name": "Room stamp", "classes": ["IfcSpace"], "template": "{LongName}\n{Name}\n{Area}", "shape": "none",
             "size": 2.5, "leader": False, "offset": [0.0, 0.0]},
    "mark": {"name": "Mark", "classes": [], "template": "{Mark}", "shape": "hexagon", "size": 2.5, "leader": True,
             "offset": [0.6, 0.6]},
    "label": {"name": "Label", "classes": [], "template": "{Name}", "shape": "none", "size": 2.5, "leader": True,
              "offset": [0.8, 0.8]},
}
AUTO_STYLES = ("door", "window", "wall")  # what Tag all places (rooms have their stamps)
# Template words -> schedule fields (D77); matched without case, spaces or underscores.
_ATTRIBUTES = {"name": "Name", "mark": "Tag", "tag": "Tag", "number": "Name", "longname": "LongName",
               "description": "Description", "objecttype": "ObjectType", "predefinedtype": "PredefinedType",
               "globalid": "GlobalId"}
_INFO = {"class": "class", "type": "type", "level": "level"}
_TOKEN = re.compile(r"\{([^{}]+)\}")


# ---------------------------------------------------------------- styles

def _stored(settings: dict | None = None) -> dict:
    from . import settings as St

    table = (settings if settings is not None else St.current()).get(KEY) or {}
    return table if isinstance(table, dict) else {}


def styles(settings: dict | None = None) -> dict:
    """The built-in styles (or the project's edited copies), then the project's own."""
    out = {k: dict(v) for k, v in BUILTIN.items()}
    for sid, st in _stored(settings).items():
        out[sid] = {**BUILTIN.get(sid, BUILTIN["label"]), **st}
    return out


def style_error(st) -> str | None:
    if not isinstance(st, dict):
        return "a tag style must be an object"
    if not str(st.get("name") or "").strip():
        return "a tag style needs a name"
    if not isinstance(st.get("template", ""), str):
        return "the template must be text"
    if st.get("shape", "none") not in S.SHAPES:
        return f"unknown tag shape {st.get('shape')}"
    classes = st.get("classes", [])
    if not isinstance(classes, list) or not all(isinstance(c, str) for c in classes):
        return "classes must be a list of IFC class names"
    size = st.get("size", 2.5)
    if not isinstance(size, (int, float)) or isinstance(size, bool) or not 0.5 <= size <= 50:
        return "the text size must be between 0.5 and 50 mm"
    off = st.get("offset", [0, 0])
    if not (isinstance(off, list) and len(off) == 2 and all(isinstance(v, (int, float)) for v in off)):
        return "the offset must be [along, across] in metres"
    return None


def table_error(table) -> str | None:
    """None, or what is wrong with the `tag_styles` settings table."""
    if not isinstance(table, dict):
        return "tag styles must be an object of styles by id"
    for sid, st in table.items():
        if (err := style_error({**BUILTIN.get(sid, {}), **st} if isinstance(st, dict) else st)) is not None:
            return f"tag style {sid}: {err}"
    return None


def style_for(e, settings: dict | None = None) -> str:
    """The first style (built-ins first) whose classes the element is one of; else the plain label."""
    for sid, st in styles(settings).items():
        if any(e.is_a(c) for c in st.get("classes") or ()):
            return sid
    return "label"


def effective(extra: dict, settings: dict | None = None) -> dict:
    """A tag's values with its template and shape filled in from its style when it has none of its own."""
    st = styles(settings).get(extra.get("Style") or "label") or BUILTIN["label"]
    return {**extra, "Template": extra.get("Template") or st.get("template", "{Name}"),
            "Shape": extra.get("Shape") or st.get("shape", "none")}


# ---------------------------------------------------------------- text

def _field(word: str):
    """The schedule field a template word names, or None."""
    from . import schedules

    word = word.strip()
    if "." in word:
        pset, _, prop = word.partition(".")
        return {"source": "property", "pset": pset.strip(), "name": prop.strip()}
    key = re.sub(r"[\s_]", "", word.lower())
    if key in _ATTRIBUTES:
        return {"source": "attribute", "name": _ATTRIBUTES[key]}
    if key in _INFO:
        return {"source": "info", "name": _INFO[key]}
    for q in schedules.QUANTITIES:
        if q.replace("_", "") == key:
            return {"source": "quantity", "name": q}
    return None


def template_fields(template: str) -> list:
    out = []
    for token in _TOKEN.findall(template or ""):
        for word in token.split("|"):
            f = _field(word)
            if f is not None and f not in out:
                out.append(f)
    return out


def format_value(field: dict, v) -> str:
    from . import schedules
    from .settings import format_length

    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if field["source"] == "quantity":
        kind = schedules.QUANTITIES[field["name"]][0]
        if kind == "length":
            return format_length(float(v), unit=False)
        if kind == "area":
            return f"{float(v):.2f} m²"
        if kind == "volume":
            return f"{float(v):.2f} m³"
        return str(int(v))
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def render(template: str, values: dict) -> str:
    """The template's text: `values` maps schedules.field_key(field) to a value."""
    from . import schedules

    lines = []
    for line in (template or "").replace("\\n", "\n").split("\n"):
        had = bool(_TOKEN.search(line))
        filled = [False]

        def sub(m):
            for word in m.group(1).split("|"):
                f = _field(word)
                text = format_value(f, values.get(schedules.field_key(f))) if f is not None else ""
                if text:
                    filled[0] = True
                    return text
            return ""

        out = _TOKEN.sub(sub, line)
        if had and not filled[0]:
            continue  # all its fields are empty: the line goes
        lines.append(out)
    return "\n".join(lines).strip("\n") or "?"


def texts(pairs) -> dict:
    """{element GlobalId: text} for (element, template) pairs, one schedule pass (D77)."""
    from . import schedules

    fields = []
    for _e, template in pairs:
        for f in template_fields(template):
            if f not in fields:
                fields.append(f)
    elements = list({e.id(): e for e, _t in pairs}.values())
    values = {}
    if fields and elements:
        for rec in schedules.collect_elements(elements, fields):
            values[rec["guid"]] = rec["values"]
    return {e.GlobalId + "|" + t: render(t, values.get(e.GlobalId, {})) for e, t in pairs}


def text_of(e, template: str) -> str:
    return texts([(e, template)])[e.GlobalId + "|" + template]


def stamp_text(space, settings: dict | None = None) -> str:
    """A room's stamp: the room stamp style's template (name, number and area by default)."""
    return text_of(space, styles(settings)["room"].get("template") or BUILTIN["room"]["template"])


# ---------------------------------------------------------------- where an element is

def _unit2(v):
    n = math.hypot(float(v[0]), float(v[1]))
    return (float(v[0]) / n, float(v[1]) / n) if n > 1e-12 else (1.0, 0.0)


def _thickness(e) -> float:
    """Metres: a wall's layer set, or a door/window's host wall."""
    from . import drawgen as G

    if e.is_a("IfcDoor") or e.is_a("IfcWindow"):
        return G._wall_thickness(e)
    unit = ifcopenshell.util.unit.calculate_unit_scale(e.file)
    usage = ifcopenshell.util.element.get_material(e)
    layers = getattr(getattr(usage, "ForLayerSet", None), "MaterialLayers", None) or getattr(usage, "MaterialLayers", None) or ()
    return sum(float(layer.LayerThickness or 0.0) for layer in layers) * unit


def frame(e):
    """(anchor, along, across, half thickness): where a tag of `e` hangs from (world metres, plan), the
    element's direction and its normal, and how far its face is from the anchor."""
    from . import authoring as A

    s = A._scale()
    if e.is_a("IfcSpace"):
        from . import rooms

        pts = rooms._outline(e)
        if pts:
            p = rooms._stamp_point(e, pts)
            return (float(p[0]), float(p[1])), (1.0, 0.0), (0.0, 1.0), 0.0
    if e.ObjectPlacement is None:
        return None
    m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
    o = m[:3, 3] * s
    x, y = _unit2(m[:2, 0]), _unit2(m[:2, 1])
    if e.is_a("IfcDoor") or e.is_a("IfcWindow"):
        width = float(getattr(e, "OverallWidth", None) or 0.0) * s
        t = _thickness(e)
        return (o[0] + x[0] * width / 2 + y[0] * t / 2, o[1] + x[1] * width / 2 + y[1] * t / 2), x, y, t / 2
    axis = ifcopenshell.util.representation.get_representation(e, "Plan", "Axis", "GRAPH_VIEW") or \
        ifcopenshell.util.representation.get_representation(e, "Model", "Axis")
    item = next((i for i in (axis.Items if axis else ()) if i.is_a("IfcPolyline") or i.is_a("IfcIndexedPolyCurve")), None)
    if item is not None:
        local = [p.Coordinates[:2] for p in item.Points] if item.is_a("IfcPolyline") else [p[:2] for p in item.Points.CoordList]
        world = [(m @ np.array([px, py, 0.0, 1.0]))[:2] * s for px, py in local]
        if len(world) >= 2:
            a, b = world[0], world[-1]
            d = _unit2(b - a)
            return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), d, (-d[1], d[0]), _thickness(e) / 2
    return (o[0], o[1]), x, y, 0.0


def default_position(e, st: dict):
    """Where a new tag of style `st` goes: the style's offset from the element's anchor."""
    fr = frame(e)
    if fr is None:
        return None, None
    anchor, along, across, half = fr
    a, c = (float(v) for v in st.get("offset", [0.0, 0.0]))
    c = c + math.copysign(half, c) if c else 0.0
    return (anchor[0] + along[0] * a + across[0] * c, anchor[1] + along[1] * a + across[1] * c), anchor


# ---------------------------------------------------------------- the model

def _is_tag(a) -> bool:
    return a.is_a("IfcAnnotation") and a.ObjectType == "TAG"


def all_tags(f=None) -> list:
    f = f or B._model
    return [a for a in f.by_type("IfcAnnotation") if a.ObjectType == "TAG"]


def element_of(tag):
    """The element a tag annotates: its IfcRelAssignsToProduct, else the GlobalId in its property set."""
    for rel in getattr(tag, "HasAssignments", None) or ():
        if rel.is_a("IfcRelAssignsToProduct") and rel.RelatingProduct is not None:
            return rel.RelatingProduct
    guid = (ifcopenshell.util.element.get_pset(tag, "KIMBIM_Annotation") or {}).get("Element")
    if guid:
        try:
            return tag.file.by_guid(guid)
        except RuntimeError:
            return None
    return None


def tagged_elements(f=None) -> set:
    return {e.GlobalId for t in all_tags(f) if (e := element_of(t)) is not None}


def _assign(tag, e):
    """Inside an action: tag -> element (IfcRelAssignsToProduct), unless it is already."""
    for rel in list(getattr(tag, "HasAssignments", None) or ()):
        if rel.is_a("IfcRelAssignsToProduct"):
            if rel.RelatingProduct == e:
                return
            others = [o for o in rel.RelatedObjects if o != tag]  # it annotated something else before
            if others:
                rel.RelatedObjects = others
            else:
                B._model.remove(rel)
    rel = ifcopenshell.api.root.create_entity(B._model, ifc_class="IfcRelAssignsToProduct")
    rel.RelatedObjects = [tag]
    rel.RelatingProduct = e


def _jpoint(p) -> str:
    return json.dumps([round(float(p[0]), 6), round(float(p[1]), 6)])


def _read_point(v):
    try:
        p = json.loads(v) if v else None
        return (float(p[0]), float(p[1])) if p else None
    except (TypeError, ValueError, IndexError):
        return None


def _write(tag, e, at, anchor, text, extra=None):
    """Inside an action: the tag at `at` (its text), hanging from `anchor` (world metres)."""
    from . import annotations as N

    N._place_at(tag, at)
    N._set(tag, "tag", text, [(0.0, 0.0), (anchor[0] - at[0], anchor[1] - at[1])],
           extra={**(extra or {}), "Element": e.GlobalId, "Anchor": _jpoint(anchor), "At": _jpoint(at)})
    tag.Name = text.replace("\n", " ")[:60]
    _assign(tag, e)


def _create(e, st_id: str, st: dict, at, anchor, text, template="", shape="", leader=None, pen=None):
    """Inside an action: a new tag of `e` on its level."""
    from . import annotations as N
    from . import authoring as A
    from . import layers
    from . import schedules
    from . import settings as St

    f = B._model
    storey = schedules._level(e)
    tag = ifcopenshell.api.root.create_entity(f, ifc_class="IfcAnnotation", name=text.replace("\n", " ")[:60])
    tag.ObjectType = "TAG"
    ifcopenshell.api.spatial.assign_container(f, products=[tag], relating_structure=storey)
    matrix = np.eye(4)
    matrix[0][3], matrix[1][3], matrix[2][3] = at[0], at[1], A._elevation(storey)
    ifcopenshell.api.geometry.edit_object_placement(f, product=tag, matrix=matrix, is_si=True)
    N._set(tag, "tag", text, [(0.0, 0.0), (anchor[0] - at[0], anchor[1] - at[1])], size=float(st.get("size", 2.5)),
           pen=pen if pen is not None else St.current().get("current_pen"),
           extra={"Style": st_id, "Template": template or "", "Shape": shape or "",
                  "Leader": bool(st.get("leader")) if leader is None else bool(leader),
                  "Element": e.GlobalId, "Anchor": _jpoint(anchor), "At": _jpoint(at)})
    layers.assign_active(tag)
    _assign(tag, e)
    return tag


def _options(options_json):
    try:
        o = json.loads(options_json) if options_json else {}
    except ValueError:
        return None
    return o if isinstance(o, dict) else None


def add_tag(element_guid: str, options_json: str = "") -> str:
    """Tag an element. options: {style (id; default: the element's kind's), template and shape (the
    style's when empty), leader (the style's when absent), at: [x, y] where the text goes (world metres;
    default: the style's offset), pen}. One undo step; returns the tag's GlobalId."""
    from . import authoring as A
    from . import schedules

    if B._model is None:
        return A._fail("no model open")
    e = A._by_guid(element_guid)
    if e is None or not e.is_a("IfcProduct") or e.is_a("IfcAnnotation") or schedules._level(e) is None:
        return A._fail("pick an element on a level")
    o = _options(options_json)
    if o is None:
        return A._fail("bad options")
    table = styles()
    sid = o.get("style") or style_for(e)
    if sid not in table:
        return A._fail(f"no tag style {sid}")
    st = table[sid]
    shape = o.get("shape") or ""
    if shape and shape not in S.SHAPES:
        return A._fail(f"unknown tag shape {shape}")
    at, anchor = default_position(e, st)
    if anchor is None:
        return A._fail("the element has no position")
    if o.get("at") is not None:
        try:
            at = (float(o["at"][0]), float(o["at"][1]))
        except (TypeError, ValueError, IndexError):
            return A._fail("bad position")
    template = str(o.get("template") or "")
    text = text_of(e, template or st.get("template", "{Name}"))
    made = {}

    def action():
        made["guid"] = _create(e, sid, st, at, anchor, text, template, shape, o.get("leader"),
                               o.get("pen") if isinstance(o.get("pen"), int) else None).GlobalId
        return 1, [made["guid"]], []

    r = B._run(action)
    return B._dump({**r, "guid": made["guid"]})


def tag_all(storey_guid: str, guids_json: str = "", style: str = "", categories: str = "") -> str:
    """Tag every untagged element on a level (Archicad: Label all; Revit: Tag all not tagged) with its
    kind's style: doors, windows and walls (rooms have their stamps), or the elements of one `style`.
    `guids_json`: only these elements (the ones the view shows). `categories` (D92): a comma-separated
    list of tag-style ids to tag (Tag all asks which categories). One undo step."""
    from . import authoring as A
    from . import schedules

    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    table = styles()
    if style and style not in table:
        return A._fail(f"no tag style {style}")
    try:
        only = set(json.loads(guids_json)) if guids_json else None
    except ValueError as ex:
        return A._fail(f"bad input: {ex}")
    done = tagged_elements()
    if style:
        wanted = [style]
    elif categories:
        wanted = [c for c in (c.strip() for c in categories.split(",")) if c in table]
        if not wanted:
            return A._fail("choose at least one category")
    else:
        wanted = list(AUTO_STYLES)
    todo = []
    for sid in wanted:
        classes = table[sid].get("classes") or []
        for cls in classes:
            try:
                found = B._model.by_type(cls)
            except RuntimeError:
                continue
            for e in found:
                if e.GlobalId in done or (only is not None and e.GlobalId not in only) or e.is_a("IfcTypeObject"):
                    continue
                if schedules._level(e) != storey or (not style and style_for(e) != sid):
                    continue
                done.add(e.GlobalId)
                todo.append((e, sid))
    if not todo:
        return B._dump({"ok": True, "changed": 0, "tagged": 0, "guids": []})
    text = texts([(e, table[sid].get("template", "{Name}")) for e, sid in todo])
    made = []

    def action():
        for e, sid in todo:
            st = table[sid]
            at, anchor = default_position(e, st)
            if anchor is None:
                continue
            made.append(_create(e, sid, st, at, anchor, text[e.GlobalId + "|" + st.get("template", "{Name}")]).GlobalId)
        return len(made), list(made), []

    r = B._run(action)
    return B._dump({**r, "tagged": len(made), "guids": made})


def set_tag(guid: str, options_json: str) -> str:
    """Change a tag: {style, template, shape, leader}; empty template/shape: the style's."""
    from . import annotations as N
    from . import authoring as A

    tag = A._by_guid(guid) if B._model is not None else None
    if tag is None or not _is_tag(tag):
        return A._fail("not a tag")
    o = _options(options_json)
    if o is None:
        return A._fail("bad options")
    if "style" in o and o["style"] not in styles():
        return A._fail(f"no tag style {o['style']}")
    if o.get("shape") and o["shape"] not in S.SHAPES:
        return A._fail(f"unknown tag shape {o['shape']}")
    extra = {k: v for k, v in (("Style", o.get("style")), ("Template", o.get("template")), ("Shape", o.get("shape")),
                               ("Leader", o.get("leader"))) if k.lower() in o}
    extra = {k: (bool(v) if k == "Leader" else (v or "")) for k, v in extra.items()}
    e = element_of(tag)
    if e is None:
        return A._fail("the tag's element is gone")

    def action():
        data = N._read(tag)
        N._set(tag, "tag", data[1], data[2], extra=extra)
        _sync_one(tag, force=True)
        return 1, [tag.GlobalId], []

    return B._dump(B._run(action))


def tag_styles() -> str:
    return B._dump({"ok": True, "styles": styles(), "builtin": list(BUILTIN), "shapes": list(S.SHAPES)})


def save_tag_style(style_json: str) -> str:
    """Store a tag style in the project settings ({id?, name, classes, template, shape, size, leader,
    offset}); the tags of that style update (one undo step)."""
    from . import settings as St

    try:
        st = json.loads(style_json)
    except ValueError as ex:
        return B._dump({"ok": False, "error": f"bad input: {ex}"})
    if not isinstance(st, dict):
        return B._dump({"ok": False, "error": "bad input: expected an object"})
    sid = st.get("id") or re.sub(r"[^a-z0-9]+", "-", str(st.get("name", "")).lower()).strip("-") or "style"
    body = {k: v for k, v in st.items() if k in ("name", "classes", "template", "shape", "size", "leader", "offset")}
    if (err := style_error({**BUILTIN.get(sid, {}), **body})) is not None:
        return B._dump({"ok": False, "error": err})
    r = json.loads(St.set_project_settings(json.dumps({KEY: {**_stored(), sid: body}})))
    if not r.get("ok"):
        return B._dump(r)
    return B._dump({**r, "id": sid, "updated": refresh_tags()})


def delete_tag_style(sid: str) -> str:
    """A custom style goes (its tags take their kind's style); a built-in one goes back to its default."""
    from . import settings as St

    stored = _stored()
    if sid not in stored:
        return B._dump({"ok": False, "error": f"no stored tag style {sid}"})
    rest = {k: v for k, v in stored.items() if k != sid}
    r = json.loads(St.set_project_settings(json.dumps({KEY: rest})))
    return B._dump({**r, "updated": refresh_tags()}) if r.get("ok") else B._dump(r)


def refresh_tags() -> int:
    """Bring every tag up to date now (after its style changed): one undo step if any changed."""
    if B._model is None or not all_tags():
        return 0
    changed = []

    def action():
        changed.extend(_sync(force_all=True))
        return len(changed), list(changed), []

    B._run(action)
    return len(changed)


def tag_target(storey_guid: str, x, y, tolerance=0.2) -> str:
    """The element a click at x, y (world metres) tags: a door or window, then a wall, column or other
    element, then the room around it. {ok, guid, class, style} or ok false."""
    from . import authoring as A
    from . import rooms

    storey = A._by_guid(storey_guid) if B._model is not None else None
    if storey is None:
        return A._fail("unknown level")
    try:
        p, tol = (float(x), float(y)), float(tolerance)
    except (TypeError, ValueError):
        return A._fail("bad point")
    contained = [e for rel in getattr(storey, "ContainsElements", None) or () for e in rel.RelatedElements]
    best, best_d = None, math.inf
    for rank, classes in enumerate((("IfcDoor", "IfcWindow"), ("IfcWall", "IfcColumn", "IfcBeam", "IfcStair",
                                                                "IfcFurnishingElement", "IfcBuildingElementProxy"))):
        for e in contained:
            if not any(e.is_a(c) for c in classes):
                continue
            fr = frame(e)
            if fr is None:
                continue
            anchor, along, across, half = fr
            dx, dy = p[0] - anchor[0], p[1] - anchor[1]
            u, v = dx * along[0] + dy * along[1], dx * across[0] + dy * across[1]
            if e.is_a("IfcDoor") or e.is_a("IfcWindow"):
                reach = float(getattr(e, "OverallWidth", None) or 0.0) * A._scale() / 2
                hit = abs(u) <= reach + tol and abs(v) <= half + tol
            elif e.is_a("IfcWall"):
                length = _wall_length(e)
                hit = abs(u) <= length / 2 + tol and abs(v) <= half + tol
            else:
                hit = math.hypot(dx, dy) <= 0.5 + tol
            d = math.hypot(dx, dy)
            if hit and d < best_d:
                best, best_d = e, d
        if best is not None:
            break
    if best is None:
        for space in rooms._rooms(storey):
            pts = rooms._outline(space)
            if pts and rooms._inside(p, pts):
                best = space
                break
    if best is None:
        return A._fail("nothing to tag there")
    return B._dump({"ok": True, "guid": best.GlobalId, "class": best.is_a(), "style": style_for(best)})


def _wall_length(e) -> float:
    fr = frame(e)
    axis = ifcopenshell.util.representation.get_representation(e, "Plan", "Axis", "GRAPH_VIEW") or \
        ifcopenshell.util.representation.get_representation(e, "Model", "Axis")
    item = next((i for i in (axis.Items if axis else ()) if i.is_a("IfcPolyline")), None)
    if item is None or fr is None:
        return 1.0
    from . import authoring as A

    pts = [p.Coordinates[:2] for p in item.Points]
    return math.dist(pts[0], pts[-1]) * A._scale()


# ---------------------------------------------------------------- following the element

def _sync_one(tag, force=False, text=None):
    """Inside an action: bring one tag up to date; True if it changed (or was deleted)."""
    from . import annotations as N

    e = element_of(tag)
    if e is None:
        from . import settings as S

        if S.current().get("orphan_tags", "delete") == "keep":  # D92: keep it, showing "?"
            data = N._read(tag)
            if data is not None and data[1] != "?":
                N._set(tag, data[0], "?", [tuple(p) for p in data[2]], extra={**N.extra_of(tag), "Element": ""})
                tag.Name = "?"
                return True
            return False
        ifcopenshell.api.root.remove_product(B._model, product=tag)
        return True
    data = N._read(tag)
    if data is None:
        return False
    extra = N.extra_of(tag)
    fr = frame(e)
    if fr is None:
        return False
    anchor = fr[0]
    at = tuple(N.world_points(tag)[0])
    old_anchor, old_at = _read_point(extra.get("Anchor")), _read_point(extra.get("At"))
    if old_at is not None and old_anchor is not None and math.dist(at, old_at) < 1e-6 \
            and math.dist(anchor, old_anchor) > 1e-6:
        at = (at[0] + anchor[0] - old_anchor[0], at[1] + anchor[1] - old_anchor[1])  # the element moved: follow
    if text is None:
        text = text_of(e, effective(extra)["Template"])
    stale = (force or text != data[1] or old_at is None or old_anchor is None or math.dist(at, old_at) > 1e-6
             or math.dist(anchor, old_anchor) > 1e-6 or extra.get("Element") != e.GlobalId
             or not any(r.is_a("IfcRelAssignsToProduct") for r in getattr(tag, "HasAssignments", None) or ()))
    if stale:
        _write(tag, e, at, anchor, text)
    return stale


def _sync(force_all=False) -> list:
    """Inside an action: every tag up to date, and levels and spot elevations that measure themselves;
    returns the GlobalIds that changed."""
    from . import annotations as N

    f = B._model
    changed = []
    tags = all_tags(f)
    if tags:
        live = [(t, element_of(t)) for t in tags]
        pairs = [(e, effective(N.extra_of(t))["Template"]) for t, e in live if e is not None]
        resolved = texts(pairs) if pairs else {}
        for t, e in live:
            guid = t.GlobalId
            text = resolved.get(e.GlobalId + "|" + effective(N.extra_of(t))["Template"]) if e is not None else None
            if _sync_one(t, force=force_all, text=text):
                changed.append(guid)
    for a in f.by_type("IfcAnnotation"):
        if a.ObjectType not in ("LEVEL", "SPOT"):
            continue
        data = N._read(a)
        if data is None or not N.extra_of(a).get("Auto"):
            continue
        storey = ifcopenshell.util.element.get_container(a)
        if storey is None:
            continue
        text = S.elevation_text(S.elevation_at(storey, N.world_points(a)[0]))
        if text != data[1]:
            N._set(a, data[0], text, data[2])
            a.Name = text[:60]
            changed.append(a.GlobalId)
    return changed


def _after(geo_changed, geo_removed):
    """AFTER_ACTION: tags follow their elements and show their values as they are now."""
    if B._model is None:
        return []
    try:
        return _sync()
    except Exception:  # never lose the user's edit to a tag: report it on the console
        traceback.print_exc(file=sys.stderr)
        return []


B.AFTER_ACTION.append(_after)


# ---------------------------------------------------------------- drawings

def room_stamp_parts(storey, to_paper) -> list:
    """Each room's stamp on a plan drawing (paper mm): the room stamp style's lines at its stamp point."""
    from . import drawgen as G
    from . import rooms

    st = styles()["room"]
    size = float(st.get("size", 2.5))
    z = G.storey_elevation(storey)
    spaces = [(sp, rooms._outline(sp)) for sp in rooms._rooms(storey)]
    spaces = [(sp, pts) for sp, pts in spaces if pts]
    resolved = texts([(sp, st.get("template", "")) for sp, _ in spaces])
    out = []
    for sp, pts in spaces:
        p = rooms._stamp_point(sp, pts)
        lines = resolved[sp.GlobalId + "|" + st.get("template", "")].split("\n")
        x, y = to_paper(p[0], p[1], z)
        step = 1.6 * size
        for i, line in enumerate(lines):
            first = i == 0 and len(lines) > 1
            out.append(G._text(x, y + (i - (len(lines) - 1) / 2) * step, line, size * (1.2 if first else 1.0),
                               baseline="central"))
    return out


def add_to_drawing(svg: str, drawing, settings: dict | None = None) -> str:
    """D87: a plan drawing gets its level's room stamps, tags, north arrows, scale bars, clouds and
    dimensions; sections and elevations their levels. Drawn on every request (styles and templates are
    settings, so never stale), styled by graphics.style_svg."""
    from . import drawgen as G

    s = G.settings_of(drawing)
    to_paper = G.paper_mapping(svg)
    if s is None or to_paper is None:
        return svg
    parts = []
    if s.get("kind") == "plan":
        storey = G._storey(drawing, s)
        if storey is None:
            return svg
        stamps = room_stamp_parts(storey, to_paper)
        if stamps:
            parts += ['<g data-kind="room">', *stamps, "</g>"]
        parts += S.drawing_parts(storey, to_paper, G.SCALE / 1000.0, settings)
    else:
        levels = S.level_markers(drawing.file, drawing, s, svg, to_paper)
        if levels:
            parts += ['<g data-kind="marker">', *levels, "</g>"]
    if not parts:
        return svg
    group = ('<g class="kimbim-marks" fill="none" stroke="#000000" stroke-width="0.18" font-family="sans-serif">\n'
             + "\n".join(parts) + "\n</g>\n")
    group = group.replace("<text ", '<text fill="#000000" stroke="none" ')
    return G.crop(svg.replace("</svg>", group + "</svg>", 1))
