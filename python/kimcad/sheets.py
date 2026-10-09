# SPDX-License-Identifier: GPL-3.0-or-later
"""Sheets and project info (Slice 16, M4 exit). Same protocol as app_bridge.

A sheet (Archicad: a layout) is an IfcDocumentInformation with Purpose "SHEET" (Bonsai stores sheets
the same way): Identification = sheet number, Name = title, Scope = paper size. Each drawing placed on it
is an IfcDocumentReference to that sheet: Identification = the drawing's GlobalId (its name is read
from the drawing; IFC allows a Name or a referenced document, not both), Description = where it sits ({"x", "y"} top-left in sheet millimetres, "scale" as 1:n). IFC2X3 names these DocumentId and
ItemReference; its references have no Description (and a Name is not allowed beside the document), so
there the position follows the marker in Location: "kimcad:drawing#{...}". Sheets are model
data (versioned, undoable); their SVG is composed on demand from the drawings' cached SVG.

Project info goes where IFC keeps it (and where Archicad's IFC export puts it): project number in
IfcProject.Name, project name in IfcProject.LongName, the site address in IfcBuilding.BuildingAddress,
and the client as an IfcActor assigned to the project with the CLIENT role.
"""
from __future__ import annotations

import datetime
import json
import re

import ifcopenshell.api.document
import ifcopenshell.guid

from . import app_bridge as B
from . import authoring as A
from . import drawings as D

PURPOSE = "SHEET"
PAPERS = {"A1": (841, 594), "A3": (420, 297)}  # landscape, millimetres
MARGIN = 10.0
TITLE_W, TITLE_H = 180.0, 50.0


def _x3() -> bool:
    return B._model.schema == "IFC2X3"


def _number_attr() -> str:  # a sheet's number
    return "DocumentId" if _x3() else "Identification"


def _link_attr() -> str:  # the GlobalId of the drawing a placed view shows
    return "ItemReference" if _x3() else "Identification"


MARKER = "kimcad:drawing"


def _data(ref) -> str:  # where a placed view sits, as JSON
    if _x3():
        return (ref.Location or "").partition("#")[2]
    return ref.Description or ""


def _data_fields(data: str, marker: str = MARKER) -> dict:
    return {"Location": f"{marker}#{data}"} if _x3() else {"Location": marker, "Description": data}


def _number(sheet) -> str:
    return getattr(sheet, _number_attr())


def _link(ref) -> str:
    return getattr(ref, _link_attr())
GAP = 15.0  # between placed drawings
TITLE_BAND = 12.0  # the drawing title under each drawing


# ---------------------------------------------------------------- project info

def _project():
    return B._model.by_type("IfcProject")[0]


def _client_actor():
    for rel in B._model.by_type("IfcRelAssignsToActor"):
        role = rel.ActingRole
        if role is not None and role.Role == "CLIENT":
            return rel
    return None


def project_info() -> str:
    if B._model is None:
        return A._fail("no model open")
    project = _project()
    building = next(iter(B._model.by_type("IfcBuilding")), None)
    address = getattr(building, "BuildingAddress", None) if building else None
    rel = _client_actor()
    client = rel.RelatingActor.TheActor if rel else None
    return B._dump({"ok": True, "number": project.Name or "", "name": project.LongName or "",
                    "client": (getattr(client, "Name", None) or getattr(client, "FamilyName", None) or "") if client else "",
                    "address": ", ".join(address.AddressLines or ()) if address is not None and address.AddressLines else ""})


def _remove_if_unused(f, entity):
    """Remove a replaced organization, role or address once nothing refers to it (no loose records)."""
    if entity is not None and f.get_total_inverses(entity) == 0:
        f.remove(entity)


def set_project_info(info_json: str) -> str:
    """{number, name, client, address}: any of them; empty strings clear."""
    if B._model is None:
        return A._fail("no model open")
    try:
        info = json.loads(info_json)
    except ValueError as ex:
        return A._fail(f"bad input: {ex}")

    def action():
        f = B._model
        project = _project()
        if "number" in info:
            project.Name = info["number"] or None
        if "name" in info:
            project.LongName = info["name"] or None
        if "address" in info:
            building = next(iter(f.by_type("IfcBuilding")), None)
            if building is not None:
                if info["address"]:
                    if building.BuildingAddress is None:
                        building.BuildingAddress = f.createIfcPostalAddress(Purpose="SITE")
                    building.BuildingAddress.AddressLines = [info["address"]]
                else:
                    old, building.BuildingAddress = building.BuildingAddress, None
                    _remove_if_unused(f, old)
        if "client" in info:
            rel = _client_actor()
            if rel is not None:
                actor, role = rel.RelatingActor, rel.ActingRole
                f.remove(rel)
                org = actor.TheActor
                f.remove(actor)
                _remove_if_unused(f, role)
                _remove_if_unused(f, org)  # imported files can share it (e.g. with owner history)
            if info["client"]:
                org = f.createIfcOrganization(Name=info["client"])
                actor = f.createIfcActor(GlobalId=ifcopenshell.guid.new(), Name=info["client"], TheActor=org)
                role = f.createIfcActorRole(Role="CLIENT")
                f.createIfcRelAssignsToActor(GlobalId=ifcopenshell.guid.new(), RelatedObjects=[project],
                                             RelatingActor=actor, ActingRole=role)
        return 1

    return B._dump(B._run(action))


# ---------------------------------------------------------------- sheets

def _sheets():
    out = [d for d in B._model.by_type("IfcDocumentInformation") if d.Purpose == PURPOSE]
    return sorted(out, key=lambda d: _number(d) or "")


def _sheet(number: str):
    return next((d for d in _sheets() if _number(d) == number), None)


def _views(sheet):
    refs = sheet.DocumentReferences if _x3() else getattr(sheet, "HasDocumentReferences", ())
    return [r for r in refs or () if (r.Location or "").partition("#")[0] == MARKER]


def _name(ref) -> str:
    d = D._drawing(_link(ref))
    return (d.Name or "") if d is not None else ""


def _placement(ref) -> dict:
    try:
        data = json.loads(_data(ref) or "{}")
    except ValueError:
        data = {}
    return {"x": float(data.get("x", MARGIN)), "y": float(data.get("y", MARGIN)), "scale": int(data.get("scale", 100))}


def _drawing_size(guid: str, hidden=()):
    """The drawing's size on paper at 1:100 (mm) and its unstyled SVG (generated if needed); `hidden`:
    the elements the sheet's purpose leaves out (D73)."""
    r = D.raw_drawing(guid, "", hidden)
    if not r.get("ok"):
        return None, r.get("error", "could not generate the drawing")
    return _svg_size(r["svg"]), r["svg"]


def sheets() -> str:
    """[{number, title, paper, width, height, views: [{drawing, name, x, y, w, h, scale}]}] (mm)."""
    if B._model is None:
        return B._dump({"sheets": []})
    out = []
    for sheet in _sheets():
        w, h = PAPERS.get(sheet.Scope or "A1", PAPERS["A1"])
        views = []
        for ref in _views(sheet):
            p = _placement(ref)
            size = _cached_size(_link(ref))
            k = 100.0 / p["scale"]
            views.append({"drawing": _link(ref), "name": _name(ref), "x": p["x"], "y": p["y"],
                          "w": round(size[0] * k, 3), "h": round(size[1] * k, 3), "scale": p["scale"]})
        legends = []
        refs = _legends(sheet)
        if refs:
            lw, lh = _legend_size(sheet)
            for ref in refs:
                p = _placement(ref)
                legends.append({"id": _link(ref), "x": p["x"], "y": p["y"], "w": round(lw, 3), "h": round(lh, 3)})
        out.append({"number": _number(sheet), "title": sheet.Name or "", "paper": sheet.Scope or "A1",
                    "width": w, "height": h, "views": views, "legends": legends})
    return B._dump({"sheets": out})


_sizes: dict[str, tuple] = {}  # drawing GlobalId -> (model state, size): the last size measured


def _svg_size(svg: str):
    m = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', svg)
    return (float(m.group(3)), float(m.group(4))) if m else (0.0, 0.0)


def _cached_size(guid: str):
    """The drawing's size on paper. sheets() runs on the GUI thread after every edit, so a drawing is
    generated here only when it was never measured; otherwise its last size is kept until a generation
    at the current state (the sheet's, in the background) is in the drawing cache."""
    state = D._state_key()
    known = _sizes.get(guid)
    if known is not None and known[0] == state:
        return known[1]
    svg = next((s for k, s in D._cache.get(guid, {}).items() if k[:2] == state), None)
    if svg is not None:
        size = _svg_size(svg)
    elif known is not None:
        return known[1]
    else:
        size = _drawing_size(guid)[0] or (0.0, 0.0)
    _sizes[guid] = (state, size)
    return size


def _next_number() -> str:
    taken = {_number(d) for d in _sheets()}
    n = 1
    while f"A{n:02d}" in taken:
        n += 1
    return f"A{n:02d}"


def add_sheet(paper: str, title: str) -> str:
    """A new sheet (A1 or A3, landscape), numbered automatically A01, A02..."""
    if B._model is None:
        return A._fail("no model open")
    if paper not in PAPERS:
        return A._fail(f"unknown paper size {paper}")
    number = _next_number()

    def action():
        f = B._model
        info = ifcopenshell.api.document.add_information(f)
        ifcopenshell.api.document.edit_information(f, information=info, attributes={
            _number_attr(): number, "Name": (title or "").strip() or f"Sheet {number}",
            "Purpose": PURPOSE, "Scope": paper})
        return 1

    return B._dump({**B._run(action), "number": number})


def edit_sheet(number: str, changes_json: str) -> str:
    """{title, number, paper}; a new number must be free."""
    sheet = _sheet(number) if B._model is not None else None
    if sheet is None:
        return A._fail("unknown sheet")
    try:
        changes = json.loads(changes_json)
    except ValueError as ex:
        return A._fail(f"bad input: {ex}")
    if "paper" in changes and changes["paper"] not in PAPERS:
        return A._fail("unknown paper size")
    if changes.get("number") and changes["number"] != number and _sheet(changes["number"]) is not None:
        return A._fail("that sheet number is taken")

    def action():
        attributes = {}
        if changes.get("title"):
            attributes["Name"] = changes["title"]
        if changes.get("number"):
            attributes[_number_attr()] = changes["number"]
        if changes.get("paper"):
            attributes["Scope"] = changes["paper"]
        ifcopenshell.api.document.edit_information(B._model, information=sheet, attributes=attributes)
        return 1

    return B._dump(B._run(action))


def delete_sheet(number: str) -> str:
    sheet = _sheet(number) if B._model is not None else None
    if sheet is None:
        return A._fail("unknown sheet")

    def action():
        for ref in _views(sheet):
            ifcopenshell.api.document.remove_reference(B._model, reference=ref)
        ifcopenshell.api.document.remove_information(B._model, information=sheet)
        return 1

    return B._dump(B._run(action))


def _free_spot(sheet, w, h):
    """Where a w x h drawing fits: left to right, top to bottom, clear of the others and the title block."""
    width, height = PAPERS.get(sheet.Scope or "A1", PAPERS["A1"])
    taken = []
    for ref in _views(sheet):
        p = _placement(ref)
        sw, sh = _cached_size(_link(ref))
        k = 100.0 / p["scale"]
        taken.append((p["x"], p["y"], sw * k, sh * k + TITLE_BAND))
    for ref in _legends(sheet):
        p = _placement(ref)
        lw, lh = _legend_size(sheet)
        taken.append((p["x"], p["y"], lw, lh))
    taken.append((width - MARGIN - TITLE_W, height - MARGIN - TITLE_H, TITLE_W, TITLE_H))
    y = MARGIN + 5
    while y + h <= height - MARGIN:
        x = MARGIN + 5
        while x + w <= width - MARGIN:
            box = (x, y, w, h + TITLE_BAND)
            clash = next((t for t in taken if box[0] < t[0] + t[2] + GAP and t[0] < box[0] + box[2] + GAP
                          and box[1] < t[1] + t[3] + GAP and t[1] < box[1] + box[3] + GAP), None)
            if clash is None:
                return x, y
            x = clash[0] + clash[2] + GAP
        y += 10
    # No free room: the spot overlapping the others least (the user moves it), not on top of another drawing.
    def overlap(x, y):
        return sum(max(0.0, min(x + w, t[0] + t[2]) - max(x, t[0])) * max(0.0, min(y + h + TITLE_BAND, t[1] + t[3]) - max(y, t[1]))
                   for t in taken)

    candidates = [(MARGIN + 5 + i * 5.0, MARGIN + 5 + j * 5.0)
                  for j in range(int(max(0.0, height - 2 * MARGIN - 5 - h) // 5) + 1)
                  for i in range(int(max(0.0, width - 2 * MARGIN - 5 - w) // 5) + 1)]
    return min(candidates, key=lambda c: (round(overlap(*c), 3), c[1], c[0]))


def place_drawing(number: str, drawing_guid: str, x=-1, y=-1, scale=100) -> str:
    """Put a drawing on a sheet at scale 1:scale; x, y < 0 finds a free spot (top-left, mm)."""
    sheet = _sheet(number) if B._model is not None else None
    if sheet is None:
        return A._fail("unknown sheet")
    d = D._drawing(drawing_guid)
    if d is None:
        return A._fail("not a drawing")
    try:
        x, y, scale = float(x), float(y), int(scale)
    except (TypeError, ValueError):
        return A._fail("bad position or scale")
    if scale <= 0:
        return A._fail("bad scale")
    if any(_link(r) == drawing_guid for r in _views(sheet)):
        return A._fail("the drawing is already on this sheet")
    size, _ = _drawing_size(drawing_guid)
    if size is None:
        return A._fail("could not generate the drawing")
    k = 100.0 / scale
    if x < 0 or y < 0:
        x, y = _free_spot(sheet, size[0] * k, size[1] * k)

    def action():
        f = B._model
        ref = ifcopenshell.api.document.add_reference(f, information=sheet)
        ifcopenshell.api.document.edit_reference(f, reference=ref, attributes={
            _link_attr(): drawing_guid,
            **_data_fields(json.dumps({"x": round(x, 3), "y": round(y, 3), "scale": scale}))})
        return 1

    return B._dump(B._run(action))


def _edit_placed(number, drawing_guid, change):
    sheet = _sheet(number) if B._model is not None else None
    ref = next((r for r in _views(sheet) if _link(r) == drawing_guid), None) if sheet else None
    if ref is None:
        return A._fail("the drawing is not on that sheet")

    def action():
        p = _placement(ref)
        change(p)
        data = json.dumps({"x": round(p["x"], 3), "y": round(p["y"], 3), "scale": p["scale"]})
        for name, value in _data_fields(data).items():
            setattr(ref, name, value)
        return 1

    return B._dump(B._run(action))


def move_placed(number: str, drawing_guid: str, x, y) -> str:
    try:
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        return A._fail("bad position")
    return _edit_placed(number, drawing_guid, lambda p: p.update(x=x, y=y))


def set_placed_scale(number: str, drawing_guid: str, scale) -> str:
    try:
        scale = int(scale)
    except (TypeError, ValueError):
        return A._fail("bad scale")
    if scale <= 0:
        return A._fail("bad scale")
    return _edit_placed(number, drawing_guid, lambda p: p.update(scale=scale))


def remove_placed(number: str, drawing_guid: str) -> str:
    sheet = _sheet(number) if B._model is not None else None
    ref = next((r for r in _views(sheet) if _link(r) == drawing_guid), None) if sheet else None
    if ref is None:
        return A._fail("the drawing is not on that sheet")

    def action():
        ifcopenshell.api.document.remove_reference(B._model, reference=ref)
        return 1

    return B._dump(B._run(action))


# ---------------------------------------------------------------- legends (D74)
# A legend is a reference on the sheet like a placed drawing, with its own marker: an id (in the drawing
# link's attribute) and {"x", "y"} (mm). It is drawn from the sheet's purpose.

LEGEND = "kimcad:legend"


def _legends(sheet):
    refs = sheet.DocumentReferences if _x3() else getattr(sheet, "HasDocumentReferences", ())
    return [r for r in refs or () if (r.Location or "").partition("#")[0] == LEGEND]


def _sheet_resolved(number: str):
    from . import graphics, settings as S

    return graphics.resolve(S.current().get("sheet_purposes", {}).get(number) or None)


def _legend_size(sheet):
    """The legend's size for listing and placing: from the whole model, so listing sheets never
    generates drawings (the composed legend, limited to the sheet's drawings, may have fewer rows)."""
    from . import graphics

    _, w, h = graphics.legend_svg(_sheet_resolved(_number(sheet)))
    return w, h


def _legend_content(sheet, resolved):
    """(body, w, h): the sheet purpose's legend, limited to the elements its drawings show."""
    from . import graphics

    views = _views(sheet)
    guids = set()
    for ref in views:
        size, svg = _drawing_size(_link(ref), resolved["hidden"])
        if size is not None:
            guids.update(re.findall(r'ifc:guid="([^"]+)"', svg))
    return graphics.legend_svg(resolved, guids if views else None)


def place_legend(number: str) -> str:
    """A legend of the sheet's purpose, at a free spot."""
    sheet = _sheet(number) if B._model is not None else None
    if sheet is None:
        return A._fail("unknown sheet")
    x, y = _free_spot(sheet, *_legend_size(sheet))
    legend_id = ifcopenshell.guid.new()[:8]

    def action():
        f = B._model
        ref = ifcopenshell.api.document.add_reference(f, information=sheet)
        ifcopenshell.api.document.edit_reference(f, reference=ref, attributes={
            _link_attr(): legend_id, **_data_fields(json.dumps({"x": round(x, 3), "y": round(y, 3)}), LEGEND)})
        return 1

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "id": legend_id})


def _legend_ref(number, legend_id):
    sheet = _sheet(number) if B._model is not None else None
    return next((r for r in _legends(sheet) if _link(r) == legend_id), None) if sheet else None


def move_legend(number: str, legend_id: str, x, y) -> str:
    try:
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        return A._fail("bad position")
    ref = _legend_ref(number, legend_id)
    if ref is None:
        return A._fail("the legend is not on that sheet")

    def action():
        for name, value in _data_fields(json.dumps({"x": round(x, 3), "y": round(y, 3)}), LEGEND).items():
            setattr(ref, name, value)
        return 1

    return B._dump(B._run(action))


def remove_legend(number: str, legend_id: str) -> str:
    ref = _legend_ref(number, legend_id)
    if ref is None:
        return A._fail("the legend is not on that sheet")

    def action():
        ifcopenshell.api.document.remove_reference(B._model, reference=ref)
        return 1

    return B._dump(B._run(action))


# ---------------------------------------------------------------- composing the sheet

def _esc(value: str) -> str:
    return (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inner(svg: str):
    """A drawing SVG's styles, its <defs> (markers its style points at with url(#...)) and its content
    without the outer <svg> element."""
    styles = re.findall(r"<style[^>]*>.*?</style>", svg, re.S)
    defs = re.findall(r"<defs>.*?</defs>", svg, re.S)
    body = re.sub(r"^.*?<svg[^>]*>", "", svg, count=1, flags=re.S)
    body = body.rsplit("</svg>", 1)[0]
    body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.S)
    body = re.sub(r"<defs>.*?</defs>", "", body, flags=re.S)
    return styles, defs, body


def _title_block(sheet, width, height, info) -> list:
    """Archicad-like title block, bottom right: project, client, address, sheet title and number,
    scale, date, issued with KIMCAD."""
    x0, y0 = width - MARGIN - TITLE_W, height - MARGIN - TITLE_H
    scales = sorted({_placement(r)["scale"] for r in _views(sheet)})
    scale = f"1:{scales[0]}" if len(scales) == 1 else "As indicated" if scales else ""
    rows = [
        (x0 + 3, y0 + 8, 5.0, info.get("name") or info.get("number") or B._model.by_type("IfcProject")[0].Name or ""),
        (x0 + 3, y0 + 14, 3.0, f"Project no. {info.get('number', '')}" if info.get("number") else ""),
        (x0 + 3, y0 + 19, 3.0, f"Client: {info.get('client')}" if info.get("client") else ""),
        (x0 + 3, y0 + 24, 3.0, info.get("address", "")),
        (x0 + 3, y0 + 36, 4.5, sheet.Name or ""),
        (x0 + 3, y0 + 45, 2.5, datetime.date.today().isoformat()),
        (x0 + 60, y0 + 45, 2.5, "KIMCAD"),
    ]
    out = [f'<rect x="{x0}" y="{y0}" width="{TITLE_W}" height="{TITLE_H}" fill="none" stroke="#000" stroke-width="0.5"/>',
           f'<path d="M{x0},{y0 + 28} L{x0 + TITLE_W},{y0 + 28}" stroke="#000" stroke-width="0.25"/>',
           f'<path d="M{x0 + 130},{y0 + 28} L{x0 + 130},{y0 + TITLE_H}" stroke="#000" stroke-width="0.25"/>',
           f'<text x="{x0 + 133}" y="{y0 + 34}" font-size="2.5">Sheet</text>',
           f'<text x="{x0 + 133}" y="{y0 + 44}" font-size="7">{_esc(_number(sheet))}</text>',
           f'<text x="{x0 + 100}" y="{y0 + 45}" font-size="3">{_esc(scale)}</text>']
    for x, y, size, value in rows:
        if value:
            out.append(f'<text x="{x}" y="{y}" font-size="{size}">{_esc(value)}</text>')
    return out


def sheet_svg(number: str) -> str:
    """The sheet as one SVG in millimetres: border, title block, each drawing at its scale with its title."""
    sheet = _sheet(number) if B._model is not None else None
    if sheet is None:
        return A._fail("unknown sheet")
    from . import graphics, settings as S

    width, height = PAPERS.get(sheet.Scope or "A1", PAPERS["A1"])
    info = json.loads(project_info())
    resolved = graphics.resolve(S.current().get("sheet_purposes", {}).get(number) or None)
    styles, parts = [], []
    for ref in _views(sheet):
        size, svg = _drawing_size(_link(ref), resolved["hidden"])
        if size is None:
            return A._fail(f"could not generate {_name(ref)}: {svg}")
        p = _placement(ref)
        k = 100.0 / p["scale"]
        svg = graphics.style_svg(svg, resolved, k)  # a pen prints at its weight at any scale
        m = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', svg)
        vx, vy = (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)
        own_styles, own_defs, body = _inner(svg)
        for block in own_styles + own_defs:  # the drawings share them: each distinct one once
            if block not in styles:
                styles.append(block)
        parts.append(f'<g class="kimcad-view" transform="translate({p["x"]:.3f} {p["y"]:.3f}) scale({k:g}) '
                     f'translate({-vx:.3f} {-vy:.3f})">\n{body}\n</g>')
        tx, ty = p["x"], p["y"] + size[1] * k + 6
        parts.append(f'<g class="kimcad-view-title"><path d="M{tx:.3f},{ty + 1.5:.3f} L{tx + size[0] * k:.3f},{ty + 1.5:.3f}" '
                     f'stroke="#000" stroke-width="0.35"/><text x="{tx:.3f}" y="{ty:.3f}" font-size="4">{_esc(_name(ref))}</text>'
                     f'<text x="{tx:.3f}" y="{ty + 6:.3f}" font-size="3">1:{p["scale"]}</text></g>')
    legend_refs = _legends(sheet)
    if legend_refs:
        body, _, _ = _legend_content(sheet, resolved)
        for ref in legend_refs:
            p = _placement(ref)
            parts.append(f'<g class="kimcad-legend" transform="translate({p["x"]:.3f} {p["y"]:.3f})">\n{body}\n</g>')
    frame = [f'<rect x="{MARGIN}" y="{MARGIN}" width="{width - 2 * MARGIN}" height="{height - 2 * MARGIN}" '
             f'fill="none" stroke="#000" stroke-width="0.7"/>']
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}">\n'
           + "\n".join(styles) + '\n<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>\n'
           + "\n".join(frame + parts) + '\n<g class="kimcad-title-block" font-family="sans-serif" fill="#000">\n'
           + "\n".join(_title_block(sheet, width, height, info)) + "\n</g>\n</svg>\n")
    return B._dump({"ok": True, "svg": svg, "width": width, "height": height})


def export_sheet_svg(number: str, path: str) -> str:
    r = json.loads(sheet_svg(number))
    if not r.get("ok"):
        return B._dump(r)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(r["svg"])
    except OSError as ex:
        return A._fail(str(ex))
    return B._dump({"ok": True, "path": path})


def set_sheet_purpose(number: str, purpose: str) -> str:
    from . import graphics, settings as S

    if _sheet(number) is None:
        return A._fail("unknown sheet")
    current = dict(S.current().get("sheet_purposes", {}))
    if purpose:
        if purpose not in graphics.effective("purposes"):
            return A._fail(f"no purpose called {purpose}")
        current[number] = purpose
    else:
        current.pop(number, None)
    r = json.loads(S.set_project_settings(json.dumps({"sheet_purposes": current})))
    return B._dump({"ok": r["ok"], "dirty": r.get("dirty", False)})
