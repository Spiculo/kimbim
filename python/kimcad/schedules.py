# SPDX-License-Identifier: GPL-3.0-or-later
"""Schedules and quantities (doc 14 §15, D77), after Archicad's Interactive Schedule: a scheme picks
IFC classes and fields (attributes, properties, quantities); the schedule lists one row per element,
or merges identical items (same values in the scheme's group fields) and sums their quantities.

Quantities are read from the element's Qto_ quantity set when it has one, else computed from its
parameters (wall axis, extrusion depth, layer thickness, opening sizes, profiles), and only as a last
resort from its tessellated shape (ifcopenshell.util.shape), batched in one geometry pass.

Schemes are a project settings table like D73's (`schedules` in settings.json: {id: scheme}), so they
are versioned and merged with the project. Built-in schemes need no entry; editing one stores a copy.

Same protocol as app_bridge (strings in, JSON out, never raise).
"""
from __future__ import annotations

import copy
import csv
import json
import math
import re
import time

import ifcopenshell
import ifcopenshell.api.attribute
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import ifcopenshell.util.unit

from . import app_bridge as B
from . import settings

KEY = "schedules"

# ---------------------------------------------------------------- fields

# Attributes a schedule can show; the editable ones are written back from the table.
ATTRIBUTES = ["Name", "Tag", "LongName", "Description", "ObjectType", "PredefinedType", "GlobalId"]
EDITABLE_ATTRIBUTES = {"Name", "Tag", "LongName", "Description", "ObjectType"}
INFO = ["class", "type", "level"]
# Quantity name -> (kind, summed when merging)
QUANTITIES = {
    "length": ("length", True), "height": ("length", False), "width": ("length", False),
    "thickness": ("length", False), "perimeter": ("length", True),
    "area": ("area", True), "gross_area": ("area", True),
    "gross_side_area": ("area", True), "net_side_area": ("area", True), "opening_area": ("area", True),
    "volume": ("volume", True), "gross_volume": ("volume", True), "count": ("count", True),
}
LABELS = {  # English labels; the app translates these (custom labels show as typed)
    "attribute:Name": "Name", "attribute:Tag": "Mark", "attribute:LongName": "Long name",
    "attribute:Description": "Description", "attribute:ObjectType": "Object type",
    "attribute:PredefinedType": "Predefined type", "attribute:GlobalId": "GlobalId",
    "info:class": "Class", "info:type": "Type", "info:level": "Level",
    "quantity:length": "Length", "quantity:height": "Height", "quantity:width": "Width",
    "quantity:thickness": "Thickness", "quantity:perimeter": "Perimeter", "quantity:area": "Area",
    "quantity:gross_area": "Gross area", "quantity:gross_side_area": "Gross side area",
    "quantity:net_side_area": "Net side area", "quantity:opening_area": "Opening area",
    "quantity:volume": "Volume", "quantity:gross_volume": "Gross volume", "quantity:count": "Count",
}


def _field(source: str, name: str, pset: str = "", label: str = "") -> dict:
    out = {"source": source, "name": name}
    if pset:
        out["pset"] = pset
    if label:
        out["label"] = label
    return out


def field_key(f: dict) -> str:
    if f.get("source") == "property":
        return f"property:{f.get('pset', '')}:{f.get('name', '')}"
    return f"{f.get('source', '')}:{f.get('name', '')}"


def _label(f: dict) -> str:
    return f.get("label") or LABELS.get(field_key(f)) or f.get("name", "")


A_, I_, Q_, P_ = (lambda n, **k: _field("attribute", n, **k)), (lambda n, **k: _field("info", n, **k)), \
    (lambda n, **k: _field("quantity", n, **k)), (lambda p, n, **k: _field("property", n, pset=p, **k))

BUILTIN = [
    {"id": "doors", "name": "Doors", "classes": ["IfcDoor"],
     "fields": [A_("Tag"), A_("Name"), I_("type"), I_("level"), Q_("width"), Q_("height"), Q_("area"),
                P_("Pset_DoorCommon", "FireRating"), P_("Pset_DoorCommon", "IsExternal")],
     "group_by": ["info:type", "quantity:width", "quantity:height"]},
    {"id": "windows", "name": "Windows", "classes": ["IfcWindow"],
     "fields": [A_("Tag"), A_("Name"), I_("type"), I_("level"), Q_("width"), Q_("height"), Q_("area"),
                P_("Pset_WindowCommon", "IsExternal")],
     "group_by": ["info:type", "quantity:width", "quantity:height"]},
    {"id": "walls", "name": "Walls", "classes": ["IfcWall"],
     "fields": [A_("Tag"), A_("Name"), I_("type"), I_("level"), Q_("length"), Q_("height"), Q_("thickness"),
                Q_("gross_side_area"), Q_("opening_area"), Q_("net_side_area"), Q_("volume"),
                P_("Pset_WallCommon", "IsExternal"), P_("Pset_WallCommon", "LoadBearing")],
     "group_by": ["info:type"]},
    {"id": "slabs", "name": "Slabs", "classes": ["IfcSlab"],
     "fields": [A_("Tag"), A_("Name"), I_("type"), I_("level"), Q_("thickness"), Q_("gross_area"),
                Q_("opening_area"), Q_("area", label="Net area"), Q_("perimeter"), Q_("volume")],
     "group_by": ["info:type"]},
    {"id": "columns", "name": "Columns", "classes": ["IfcColumn"],
     "fields": [A_("Tag"), A_("Name"), I_("type"), I_("level"), Q_("height"), Q_("area", label="Section area"),
                Q_("volume")],
     "group_by": ["info:type", "quantity:height"]},
    {"id": "beams", "name": "Beams", "classes": ["IfcBeam"],
     "fields": [A_("Tag"), A_("Name"), I_("type"), I_("level"), Q_("length"), Q_("area", label="Section area"),
                Q_("volume")],
     "group_by": ["info:type"]},
    {"id": "rooms", "name": "Rooms", "classes": ["IfcSpace"],
     "fields": [A_("Name", label="Number"), A_("LongName", label="Name"), I_("level"), Q_("area"),
                Q_("perimeter"), Q_("height"), Q_("volume")],
     "group_by": ["info:level"]},
]
_BUILTIN = {s["id"]: s for s in BUILTIN}


# ---------------------------------------------------------------- schemes in the project settings

def _stored() -> dict:
    table = settings.current().get(KEY)
    return {k: v for k, v in table.items() if isinstance(v, dict)} if isinstance(table, dict) else {}


def table_error(table) -> str | None:
    """None, or what is wrong with the `schedules` settings table."""
    if not isinstance(table, dict):
        return "schedules must map ids to schedule schemes"
    for sid, scheme in table.items():
        if not (isinstance(sid, str) and sid):
            return "a schedule needs an id"
        if (err := scheme_error(scheme)) is not None:
            return f"schedule {sid}: {err}"
    return None


def schemes() -> list[dict]:
    """Built-in schemes (or the project's edited copies), then the project's own, by name."""
    stored = _stored()
    out = []
    for s in BUILTIN:
        mine = stored.get(s["id"])
        out.append({**copy.deepcopy(mine or s), "id": s["id"], "builtin": True, "modified": mine is not None})
    custom = [{**copy.deepcopy(v), "id": k, "builtin": False, "modified": False} for k, v in stored.items() if k not in _BUILTIN]
    return out + sorted(custom, key=lambda s: (s.get("name") or "").lower())


def scheme_error(s) -> str | None:
    if not isinstance(s, dict):
        return "a schedule must be an object"
    if not isinstance(s.get("name"), str) or not s["name"].strip():
        return "a schedule needs a name"
    classes = s.get("classes")
    if not (isinstance(classes, list) and classes and all(isinstance(c, str) and c.startswith("Ifc") for c in classes)):
        return "a schedule needs at least one IFC class"
    fields = s.get("fields")
    if not (isinstance(fields, list) and fields):
        return "a schedule needs at least one field"
    for f in fields:
        if not isinstance(f, dict) or not isinstance(f.get("name"), str):
            return "bad field"
        src = f.get("source")
        if src == "attribute" and f["name"] not in ATTRIBUTES:
            return f"unknown attribute {f['name']}"
        if src == "info" and f["name"] not in INFO:
            return f"unknown field {f['name']}"
        if src == "quantity" and f["name"] not in QUANTITIES:
            return f"unknown quantity {f['name']}"
        if src == "property" and not (isinstance(f.get("pset"), str) and f["pset"] and f["name"]):
            return "a property field needs a property set and a name"
        if src not in ("attribute", "info", "quantity", "property"):
            return f"unknown field source {src}"
    group = s.get("group_by", [])
    if not (isinstance(group, list) and all(isinstance(g, str) for g in group)):
        return "group_by must be a list of field keys"
    return None


def _resolve(scheme) -> dict | None:
    """A scheme from its id (built-in or stored) or the scheme itself (a dict or JSON text)."""
    if isinstance(scheme, dict):
        return scheme
    text = str(scheme or "").strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except ValueError:
            return None
    return next((s for s in schemes() if s["id"] == text), None)


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "schedule"
    taken = {s["id"] for s in schemes()}
    out, n = base, 2
    while out in taken:
        out, n = f"{base}-{n}", n + 1
    return out


# ---------------------------------------------------------------- reading elements

class _Ctx:
    """Per-schedule caches: unit scale, storey elevations."""

    def __init__(self):
        unit = ifcopenshell.util.unit.calculate_unit_scale
        self.scale = unit(B._model)
        # Quantity sets are in the project's units, per kind (mm lengths often come with m² areas).
        self.kind_scale = {"length": self.scale, "area": unit(B._model, "AREAUNIT"),
                           "volume": unit(B._model, "VOLUMEUNIT")}
        self.elevations: dict = {}
        self._types: dict | None = None
        self._type_defs: dict = {}

    def type_of(self, e):
        """The element's type object, from one pass over the (few) type relations."""
        if self._types is None:
            self._types = {}
            for rel in B._model.by_type("IfcRelDefinesByType"):
                t = rel.RelatingType
                for o in rel.RelatedObjects:
                    self._types[o.id()] = t
        return self._types.get(e.id())

    def definitions(self, e) -> dict:
        """{name: [definitions]} for the element's property and quantity sets: its type's first, its own
        after (they override). Read from the element's relations (no file-wide index); the type's once."""
        t = self.type_of(e)
        out: dict = {}
        if t is not None:
            if t.id() not in self._type_defs:
                defs: dict = {}
                for d in getattr(t, "HasPropertySets", None) or ():
                    defs.setdefault(d.Name, []).append(d)
                self._type_defs[t.id()] = defs
            out = {k: list(v) for k, v in self._type_defs[t.id()].items()}
        for rel in getattr(e, "IsDefinedBy", None) or ():
            d = rel[5]  # RelatingPropertyDefinition (or RelatingType, for the type relation)
            for x in d if isinstance(d, tuple) else (d,):
                if x.is_a("IfcPropertySetDefinition"):
                    out.setdefault(x[2], []).append(x)
        return out

    def elevation(self, storey) -> float:
        if storey is None:
            return 0.0
        if storey.id() not in self.elevations:
            from . import authoring as A

            self.elevations[storey.id()] = A._elevation(storey)
        return self.elevations[storey.id()]


_values_cache: dict = {}


def _values(d) -> dict:
    """{name: value} of a property set (single values) or quantity set, read once per schedule."""
    got = _values_cache.get(d.id())
    if got is None:
        got = {}
        if d.is_a("IfcPropertySet"):
            for p in d.HasProperties:
                if p.is_a("IfcPropertySingleValue"):
                    got[p.Name] = p.NominalValue.wrappedValue if p.NominalValue is not None else None
        elif d.is_a("IfcElementQuantity"):
            for q in d.Quantities:
                got[q.Name] = q[3]  # LengthValue / AreaValue / VolumeValue / CountValue ...
        _values_cache[d.id()] = got
    return got


def _property(defs: dict, pset: str, name: str):
    """The value of pset.name (the element's own over its type's), or None."""
    value = None
    for d in defs.get(pset, ()):
        value = _values(d).get(name, value)
    return value


def _level(e):
    """The storey an element is on: its container (or its aggregate, for spaces), walking up."""
    node = ifcopenshell.util.element.get_container(e) or ifcopenshell.util.element.get_aggregate(e)
    for _ in range(8):
        if node is None or node.is_a("IfcBuildingStorey"):
            return node
        node = ifcopenshell.util.element.get_container(node) or ifcopenshell.util.element.get_aggregate(node)
    return None


# Qto names per class family: quantity -> [(quantity set, quantity name)]
_QTO = {
    "IfcWall": {"length": [("Qto_WallBaseQuantities", "Length")], "height": [("Qto_WallBaseQuantities", "Height")],
                "thickness": [("Qto_WallBaseQuantities", "Width")],
                "gross_side_area": [("Qto_WallBaseQuantities", "GrossSideArea")],
                "net_side_area": [("Qto_WallBaseQuantities", "NetSideArea")],
                "volume": [("Qto_WallBaseQuantities", "NetVolume")],
                "gross_volume": [("Qto_WallBaseQuantities", "GrossVolume")]},
    "IfcSlab": {"thickness": [("Qto_SlabBaseQuantities", "Depth"), ("Qto_SlabBaseQuantities", "Width")],
                "length": [("Qto_SlabBaseQuantities", "Length")], "perimeter": [("Qto_SlabBaseQuantities", "Perimeter")],
                "gross_area": [("Qto_SlabBaseQuantities", "GrossArea")], "area": [("Qto_SlabBaseQuantities", "NetArea")],
                "volume": [("Qto_SlabBaseQuantities", "NetVolume")],
                "gross_volume": [("Qto_SlabBaseQuantities", "GrossVolume")]},
    "IfcDoor": {"width": [("Qto_DoorBaseQuantities", "Width")], "height": [("Qto_DoorBaseQuantities", "Height")],
                "area": [("Qto_DoorBaseQuantities", "Area")], "perimeter": [("Qto_DoorBaseQuantities", "Perimeter")]},
    "IfcWindow": {"width": [("Qto_WindowBaseQuantities", "Width")], "height": [("Qto_WindowBaseQuantities", "Height")],
                  "area": [("Qto_WindowBaseQuantities", "Area")],
                  "perimeter": [("Qto_WindowBaseQuantities", "Perimeter")]},
    "IfcColumn": {"height": [("Qto_ColumnBaseQuantities", "Length")], "length": [("Qto_ColumnBaseQuantities", "Length")],
                  "area": [("Qto_ColumnBaseQuantities", "CrossSectionArea")],
                  "volume": [("Qto_ColumnBaseQuantities", "NetVolume")],
                  "gross_volume": [("Qto_ColumnBaseQuantities", "GrossVolume")]},
    "IfcBeam": {"length": [("Qto_BeamBaseQuantities", "Length")], "area": [("Qto_BeamBaseQuantities", "CrossSectionArea")],
                "volume": [("Qto_BeamBaseQuantities", "NetVolume")],
                "gross_volume": [("Qto_BeamBaseQuantities", "GrossVolume")]},
    "IfcSpace": {"area": [("Qto_SpaceBaseQuantities", "NetFloorArea")],
                 "gross_area": [("Qto_SpaceBaseQuantities", "GrossFloorArea")],
                 "perimeter": [("Qto_SpaceBaseQuantities", "NetPerimeter"), ("Qto_SpaceBaseQuantities", "GrossPerimeter")],
                 "height": [("Qto_SpaceBaseQuantities", "Height")],
                 "volume": [("Qto_SpaceBaseQuantities", "NetVolume")],
                 "gross_volume": [("Qto_SpaceBaseQuantities", "GrossVolume")]},
    "IfcCovering": {"area": [("Qto_CoveringBaseQuantities", "NetArea")],
                    "gross_area": [("Qto_CoveringBaseQuantities", "GrossArea")],
                    "thickness": [("Qto_CoveringBaseQuantities", "Width")]},
}


def _family(e) -> str:
    for c in _QTO:
        if e.is_a(c):
            return c
    return ""


def _rep(e, identifier: str):
    """The element's representation with this identifier (Body, Axis), in whatever context: imported
    files often lack KIMCAD's Model/Body/MODEL_VIEW context (e.g. Revit 2011 exports)."""
    shape = getattr(e, "Representation", None)
    for r in (shape.Representations if shape is not None else ()):
        if r.RepresentationIdentifier == identifier:
            return r
    return None


def _body_solids(e):
    """The extrusions the body is made of, or [] when it is anything else (a clipped wall, a brep, a
    mapped item): those are measured from their shape instead."""
    body = _rep(e, "Body")
    items = list(body.Items) if body is not None else []
    if not items or any(not i.is_a("IfcExtrudedAreaSolid") for i in items):
        return []
    return items


def _axis_length(e, s) -> float | None:
    """Length of the wall's axis (a polyline), in metres."""
    axis = _rep(e, "Axis")
    for item in (axis.Items if axis is not None else ()):
        if item.is_a("IfcPolyline") and len(item.Points) >= 2:
            pts = [p.Coordinates for p in item.Points]
            return sum(math.dist(a[:2], b[:2]) for a, b in zip(pts, pts[1:])) * s
        if item.is_a("IfcIndexedPolyCurve") and not item.Segments:
            pts = item.Points.CoordList
            return sum(math.dist(a[:2], b[:2]) for a, b in zip(pts, pts[1:])) * s
    return None


def _profile_area(profile, s) -> float | None:
    """Area of a profile in m², or None for kinds not handled here."""
    if profile.is_a("IfcRectangleProfileDef"):
        return float(profile.XDim) * float(profile.YDim) * s * s
    if profile.is_a("IfcCircleProfileDef"):
        return math.pi * (float(profile.Radius) * s) ** 2
    if profile.is_a("IfcArbitraryClosedProfileDef"):
        area = abs(_shoelace(_curve_points(profile.OuterCurve))) * s * s
        for inner in getattr(profile, "InnerCurves", None) or ():
            area -= abs(_shoelace(_curve_points(inner))) * s * s
        return area if area > 0 else None
    return None


def _curve_points(curve):
    if curve.is_a("IfcPolyline"):
        return [tuple(float(c) for c in p.Coordinates[:2]) for p in curve.Points]
    if curve.is_a("IfcIndexedPolyCurve") and not curve.Segments:
        return [tuple(float(c) for c in p[:2]) for p in curve.Points.CoordList]
    return []


def _shoelace(pts) -> float:
    n = len(pts)
    return sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) / 2 if n > 2 else 0.0


def _perimeter_of(profile, s) -> float | None:
    if profile.is_a("IfcRectangleProfileDef"):
        return 2 * (float(profile.XDim) + float(profile.YDim)) * s
    if profile.is_a("IfcCircleProfileDef"):
        return 2 * math.pi * float(profile.Radius) * s
    if profile.is_a("IfcArbitraryClosedProfileDef"):
        pts = _curve_points(profile.OuterCurve)
        if len(pts) > 2:
            return sum(math.dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))) * s
    return None


def _opening_area(opening, s) -> float:
    """The area an opening takes out of its host: its filling's size, else its body's two largest sizes."""
    for rel in getattr(opening, "HasFillings", None) or ():
        fill = rel.RelatedBuildingElement
        w, h = getattr(fill, "OverallWidth", None), getattr(fill, "OverallHeight", None)
        if w and h:
            return float(w) * float(h) * s * s
    for solid in _body_solids(opening):
        p = solid.SweptArea
        if p.is_a("IfcRectangleProfileDef"):
            dims = sorted([float(p.XDim), float(p.YDim), float(solid.Depth)])
            return dims[1] * dims[2] * s * s
        if p.is_a("IfcArbitraryClosedProfileDef"):
            return _profile_area(p, s) or 0.0
    return 0.0


def _layers_thickness(layer_set, s) -> float:
    return sum(float(layer.LayerThickness or 0.0) for layer in layer_set.MaterialLayers) * s


def _openings(e) -> list:
    return [rel.RelatedOpeningElement for rel in getattr(e, "HasOpenings", None) or ()]


def _parametric(e, family: str, ctx: _Ctx) -> dict:
    """Quantities from the element's parameters (no tessellation). Missing ones are left out."""
    from . import authoring as A

    s = ctx.scale
    q: dict = {}
    try:
        if family == "IfcWall":
            length = _axis_length(e, s)
            layer_set = A._layer_set(e)
            if length is not None:
                q["length"] = length
            if layer_set is not None:
                q["thickness"] = _layers_thickness(layer_set, s)
            q["opening_area"] = sum(_opening_area(o, s) for o in _openings(e))
            # A wall cut by a roof (or any clipping) is not a box: its height and areas come from its shape.
            solids = _body_solids(e)
            if solids:
                q["height"] = max(float(x.Depth) for x in solids) * s
            if "length" in q and "height" in q:
                gross = q["length"] * q["height"]
                openings = q["opening_area"]
                q.update(gross_side_area=gross, net_side_area=max(gross - openings, 0.0))
                if "thickness" in q:
                    q.update(gross_volume=gross * q["thickness"], volume=q["net_side_area"] * q["thickness"])
        elif family in ("IfcDoor", "IfcWindow"):
            w, h = getattr(e, "OverallWidth", None), getattr(e, "OverallHeight", None)
            if w and h:
                w, h = float(w) * s, float(h) * s
                q.update(width=w, height=h, area=w * h, perimeter=2 * (w + h))
        elif family in ("IfcSlab", "IfcSpace", "IfcCovering"):
            solids = _body_solids(e)
            if solids:
                solid = solids[0]
                depth = float(solid.Depth) * s
                gross = _profile_area(solid.SweptArea, s)
                t = ctx.type_of(e)
                layer_set = A._layer_set(e) or (A._layer_set(t) if t is not None else None)
                thickness = _layers_thickness(layer_set, s) if layer_set is not None else depth
                if family == "IfcSpace":
                    q["height"] = depth
                else:
                    q["thickness"] = thickness
                if gross is not None:
                    holes = sum(_opening_area(o, s) for o in _openings(e)) if family == "IfcSlab" else 0.0
                    net = max(gross - holes, 0.0)
                    q.update(gross_area=gross, area=net)
                    if family == "IfcSlab":
                        q["opening_area"] = holes
                    q.update(gross_volume=gross * (depth if family == "IfcSpace" else thickness),
                             volume=net * (depth if family == "IfcSpace" else thickness))
                perimeter = _perimeter_of(solid.SweptArea, s)
                if perimeter is not None:
                    q["perimeter"] = perimeter
        elif family in ("IfcColumn", "IfcBeam"):
            solids = _body_solids(e)
            if solids:
                depth = float(solids[0].Depth) * s
                q["height" if family == "IfcColumn" else "length"] = depth
                if family == "IfcColumn":
                    q["length"] = depth
                area = _profile_area(solids[0].SweptArea, s)
                if area is not None:
                    q.update(area=area, volume=area * depth, gross_volume=area * depth)
    except Exception:  # an odd representation: leave it to the geometry pass
        pass
    return q


# Geometry pass, cached per model state: {guid: {quantity: value}}
_geo_cache: dict = {"key": None, "values": {}}


def _geometry(elements) -> dict:
    """Quantities from tessellated shapes (ifcopenshell.util.shape), one iterator over the elements.
    The footprint (slow) only for floor-like elements."""
    import multiprocessing

    import ifcopenshell.geom
    import ifcopenshell.util.shape as S

    key = (B._model, B._current_id())  # holds the model: its id can't be reused by another
    if _geo_cache["key"] is None or _geo_cache["key"][0] is not key[0] or _geo_cache["key"][1] != key[1]:
        _geo_cache.update(key=key, values={})
    cache = _geo_cache["values"]
    todo = [e for e in elements if e.GlobalId not in cache and getattr(e, "Representation", None)]
    floors = {e.GlobalId for e in todo if _family(e) in ("IfcSlab", "IfcSpace", "IfcCovering")}
    if todo:
        st = ifcopenshell.geom.settings()
        it = ifcopenshell.geom.iterator(st, B._model, max(1, min(8, multiprocessing.cpu_count())), include=todo)
        if it.initialize():
            while True:
                shape = it.get()
                g = shape.geometry
                try:
                    v = {"volume": abs(float(S.get_volume(g))), "height": float(S.get_z(g))}
                    v["gross_volume"] = v["volume"]
                    if shape.guid in floors:
                        v["footprint"] = float(S.get_footprint_area(g))
                except Exception:
                    v = {}
                cache[shape.guid] = v
                if not it.next():
                    break
        for e in todo:
            cache.setdefault(e.GlobalId, {})
    return cache




def _collect(scheme, ctx: _Ctx) -> list[dict]:
    """One record per element: {guid, values: {field key: value}, sort: {...}}."""
    _values_cache.clear()  # entity ids are reused after edits
    seen, elements = set(), []
    for cls in scheme["classes"]:
        try:
            found = B._model.by_type(cls)
        except RuntimeError:  # a class this schema does not have
            continue
        for e in found:
            if e.id() not in seen and not e.is_a("IfcTypeObject"):
                seen.add(e.id())
                if e.is_a("IfcSlab") and _stair_part(e):
                    continue  # a stair's or ramp's landing is the stair's, not a floor slab (D88)
                elements.append(e)
    return collect_elements(elements, scheme["fields"], ctx)


def _stair_part(e) -> bool:
    whole = ifcopenshell.util.element.get_aggregate(e)
    return whole is not None and (whole.is_a("IfcStair") or whole.is_a("IfcRamp"))


def collect_elements(elements, fields, ctx: _Ctx | None = None) -> list[dict]:
    """The field values of these elements (D87's tags use it): one record per element, as _collect."""
    ctx = ctx or _Ctx()
    _values_cache.clear()
    wanted_q = {f["name"] for f in fields if f.get("source") == "quantity"} - {"count"}
    records, missing = [], []
    for e in elements:
        defs = ctx.definitions(e)
        family = _family(e)
        values, quantities = {}, None
        storey = None
        for f in fields:
            k, src, name = field_key(f), f.get("source"), f.get("name")
            if src == "attribute":
                v = getattr(e, name, None) if hasattr(e, name) else None
                values[k] = v if isinstance(v, (str, int, float, bool)) or v is None else str(v)
            elif src == "info":
                if name == "class":
                    values[k] = e.is_a()
                elif name == "type":
                    t = ctx.type_of(e)
                    # No type object: IFC's ObjectType names the type (how Revit 2011 exports walls).
                    values[k] = (t.Name or "") if t is not None else (getattr(e, "ObjectType", None) or "")
                else:
                    storey = storey or _level(e)
                    values[k] = (storey.Name or "") if storey is not None else ""
            elif src == "property":
                v = _property(defs, f.get("pset", ""), name)
                values[k] = v if isinstance(v, (str, int, float, bool)) or v is None else str(v)
            elif src == "quantity":
                if name == "count":
                    values[k] = 1
                    continue
                v = None
                for pset, prop in _QTO.get(family, {}).get(name, ()):
                    v = _property(defs, pset, prop)
                    if isinstance(v, (int, float)):
                        v = float(v) * _qto_scale(name, ctx)
                        break
                    v = None
                if v is None:
                    if quantities is None:
                        quantities = _parametric(e, family, ctx)
                    v = quantities.get(name)
                values[k] = v
        storey = storey or _level(e)
        rec = {"guid": e.GlobalId, "values": values, "elevation": ctx.elevation(storey)}
        records.append(rec)
        if any(values.get(f"quantity:{n}") is None for n in wanted_q & _geometric(family)):
            missing.append((e, rec, family, quantities or {}))
    if missing:  # the last resort: one geometry pass for every element still lacking a quantity
        geo = _geometry([m[0] for m in missing])
        for e, rec, family, q in missing:
            g = dict(geo.get(e.GlobalId, {}))
            if family == "IfcWall" and g.get("volume") and q.get("thickness") and q.get("length"):
                # A prism-like wall: net side area = net volume / thickness, the openings added back.
                net = g["volume"] / q["thickness"]
                gross = net + q.get("opening_area", 0.0)
                g.update(net_side_area=net, gross_side_area=gross, height=gross / q["length"],
                         gross_volume=gross * q["thickness"])
            elif family in ("IfcSlab", "IfcSpace", "IfcCovering") and g.get("footprint"):
                g.update(area=g["footprint"], gross_area=g["footprint"])
            for n in wanted_q & _geometric(family):
                k = f"quantity:{n}"
                if rec["values"].get(k) is None and g.get(n) is not None:
                    rec["values"][k] = g[n]
    return records


def _geometric(family: str) -> set:
    """Quantities the geometry pass can supply for this kind of element."""
    if family == "IfcWall":
        return {"volume", "gross_volume", "height", "gross_side_area", "net_side_area"}
    if family in ("IfcSlab", "IfcSpace", "IfcCovering"):
        return {"volume", "gross_volume", "height", "area", "gross_area"}
    return {"volume", "gross_volume", "height"}


def _qto_scale(name: str, ctx: _Ctx) -> float:
    """Quantities are in the project's units: metres per length / area / volume unit."""
    return ctx.kind_scale.get(QUANTITIES[name][0], 1.0)


# ---------------------------------------------------------------- the schedule

def _natural(v):
    if v is None:
        return (2, ())
    if isinstance(v, bool):
        return (0, (int(v),))
    if isinstance(v, (int, float)):
        return (0, (float(v),))
    parts = re.split(r"(\d+)", str(v).lower())
    return (1, tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts if p))


def _round(v):
    return round(v, 6) if isinstance(v, float) else v


def _columns(scheme) -> list[dict]:
    out = []
    for f in scheme["fields"]:
        k, src = field_key(f), f.get("source")
        if src == "quantity":
            kind, summed = QUANTITIES[f["name"]]
        else:
            kind, summed = "text", False
        editable = (src == "attribute" and f["name"] in EDITABLE_ATTRIBUTES) or src == "property"
        out.append({"key": k, "label": _label(f), "kind": kind, "sum": summed, "editable": editable, "field": f})
    return out


_records_cache: dict = {}


def compute(scheme, merge: bool = False) -> dict:
    """{columns, rows: [{guids, values, count}], totals, count, seconds}."""
    started = time.perf_counter()
    scheme = _resolve(scheme)
    if scheme is None:
        return {"ok": False, "error": "unknown schedule"}
    if (err := scheme_error(scheme)) is not None:
        return {"ok": False, "error": err}
    if B._model is None:
        return {"ok": True, "scheme": scheme, "columns": _columns(scheme), "rows": [], "totals": [], "count": 0, "seconds": 0.0}
    columns = _columns(scheme)
    keys = [c["key"] for c in columns]
    # The same schedule of the same model state (merging toggled, the window reopened, a row clicked)
    # reuses its records; any edit is a new state.
    cache_key = (id(B._model), B._current_id(), json.dumps([scheme["classes"], scheme["fields"]], sort_keys=True))
    for k in [k for k, v in _records_cache.items() if v[0] is not B._model]:
        del _records_cache[k]  # another model is open: let the old one go
    if _geo_cache["key"] is not None and _geo_cache["key"][0] is not B._model:
        _geo_cache.update(key=None, values={})
    entry = _records_cache.get(cache_key)
    records = entry[1] if entry is not None and entry[0] is B._model else None  # the entry holds its model: no id reuse
    if records is None:
        records = _collect(scheme, _Ctx())
        level_key = "info:level"

        def sort_key(rec):
            # Level (by elevation), then the first fields (Archicad sorts by the leading fields).
            return tuple([rec["elevation"]] if level_key in rec["values"] else []) + \
                tuple(_natural(rec["values"].get(k)) for k in keys[:4])

        records.sort(key=sort_key)
        if len(_records_cache) >= 8:
            _records_cache.pop(next(iter(_records_cache)))
        _records_cache[cache_key] = (B._model, records)
    if merge:
        group = [g for g in scheme.get("group_by", []) if g in keys] or [k for k, c in zip(keys, columns) if not c["sum"]]
        groups: dict = {}
        for rec in records:
            gk = tuple(json.dumps(_round(rec["values"].get(g)), default=str) for g in group)
            groups.setdefault(gk, []).append(rec)
        rows = []
        for members in groups.values():
            values = []
            for c in columns:
                vs = [m["values"].get(c["key"]) for m in members]
                if c["sum"]:
                    nums = [v for v in vs if isinstance(v, (int, float))]
                    values.append(_round(float(sum(nums))) if nums else None)
                else:
                    first = _round(vs[0])
                    values.append(first if all(_round(v) == first for v in vs) else None)
            rows.append({"guids": [m["guid"] for m in members], "values": values, "count": len(members),
                         "varies": [v is None and not c["sum"] and any(m["values"].get(c["key"]) is not None for m in members)
                                    for v, c in zip(values, columns)]})
    else:
        rows = [{"guids": [r["guid"]], "values": [_round(r["values"].get(k)) for k in keys], "count": 1,
                 "varies": [False] * len(keys)} for r in records]
    totals = []
    for i, c in enumerate(columns):
        nums = [r["values"][i] for r in rows if isinstance(r["values"][i], (int, float)) and not isinstance(r["values"][i], bool)]
        totals.append(_round(float(sum(nums))) if c["sum"] and nums else None)
    return {"ok": True, "scheme": {k: v for k, v in scheme.items()}, "columns": columns, "rows": rows,
            "totals": totals, "count": len(records), "merged": bool(merge),
            "seconds": round(time.perf_counter() - started, 4)}


def _cell_text(v, kind: str) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if kind == "count":
        return str(int(v))
    if isinstance(v, float):
        return f"{v:.3f}" if kind == "volume" else f"{v:.2f}"
    return str(v)


UNITS = {"length": " (m)", "area": " (m²)", "volume": " (m³)"}


def export(scheme, merge: bool, path: str) -> dict:
    """CSV (UTF-8, comma-separated) or XLSX (by the file's extension), with a header and a total row."""
    data = compute(scheme, merge)
    if not data.get("ok"):
        return data
    columns = data["columns"]
    header = [c["label"] + UNITS.get(c["kind"], "") for c in columns] + (["Count"] if merge else [])
    body = [r["values"] + ([r["count"]] if merge else []) for r in data["rows"]]
    totals = list(data["totals"]) + ([data["count"]] if merge else [])
    if totals and totals[0] is None:
        totals[0] = "Total"
    kinds = [c["kind"] for c in columns] + (["count"] if merge else [])
    try:
        if path.lower().endswith(".xlsx"):
            import openpyxl
            from openpyxl.styles import Font

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = (data["scheme"].get("name") or "Schedule")[:31]
            ws.append(header)
            for cell in ws[1]:
                cell.font = Font(bold=True)
            for row in body + [totals]:
                ws.append([v if isinstance(v, (int, float, str)) or v is None else str(v) for v in row])
            for col, kind in enumerate(kinds, start=1):
                fmt = {"length": "0.00", "area": "0.00", "volume": "0.000", "count": "0"}.get(kind)
                if fmt:
                    for r in range(2, len(body) + 3):
                        ws.cell(row=r, column=col).number_format = fmt
            for r in ws[len(body) + 2]:
                r.font = Font(bold=True)
            ws.freeze_panes = "A2"
            wb.save(path)
        else:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(header)
                for row in body + [totals]:
                    w.writerow([_cell_text(v, k) for v, k in zip(row, kinds)])
    except (OSError, ImportError) as ex:
        return {"ok": False, "error": str(ex)}
    return {"ok": True, "path": path, "rows": len(body)}


# ---------------------------------------------------------------- bridge

def _truthy(v) -> bool:
    return v is True or str(v).strip().lower() in ("1", "true", "yes")


def schedule_schemes() -> str:
    return B._dump({"ok": True, "schemes": schemes(), "quantities": list(QUANTITIES), "attributes": ATTRIBUTES,
                    "info": INFO, "labels": LABELS})


def schedule(scheme: str, merge="false") -> str:
    try:
        return B._dump(compute(scheme, _truthy(merge)))
    except Exception as ex:
        return B._dump({"ok": False, "error": f"{type(ex).__name__}: {ex}"})


def export_schedule(scheme: str, merge, path: str) -> str:
    try:
        return B._dump(export(scheme, _truthy(merge), path))
    except Exception as ex:
        return B._dump({"ok": False, "error": f"{type(ex).__name__}: {ex}"})


def save_schedule_scheme(scheme_json: str) -> str:
    """Store a scheme in the project settings (a new one gets an id from its name)."""
    try:
        s = json.loads(scheme_json)
    except ValueError as ex:
        return B._dump({"ok": False, "error": f"bad input: {ex}"})
    if (err := scheme_error(s)) is not None:
        return B._dump({"ok": False, "error": err})
    sid = s.get("id") or _slug(s["name"])
    body = {k: v for k, v in s.items() if k in ("name", "classes", "fields", "group_by")}
    r = json.loads(settings.set_project_settings(json.dumps({KEY: {**_stored(), sid: body}})))
    return B._dump({**r, "id": sid}) if r.get("ok") else B._dump(r)


def delete_schedule_scheme(sid: str) -> str:
    """A custom scheme goes; a built-in one goes back to its default."""
    stored = _stored()
    if sid not in stored:
        return B._dump({"ok": False, "error": "nothing to delete"})
    stored.pop(sid)
    return settings.set_project_settings(json.dumps({KEY: stored}))


def schedule_classes() -> str:
    """IFC classes in the model a schedule can list (elements and spaces), with counts."""
    counts: dict = {}
    if B._model is not None:
        for cls in ("IfcElement", "IfcSpatialElement" if B._model.schema != "IFC2X3" else "IfcSpatialStructureElement"):
            for e in B._model.by_type(cls):
                if not e.is_a("IfcOpeningElement") and not e.is_a("IfcVirtualElement"):
                    counts[e.is_a()] = counts.get(e.is_a(), 0) + 1
    return B._dump({"classes": [{"name": k, "count": v} for k, v in sorted(counts.items())]})


def schedule_fields(classes_json: str) -> str:
    """The fields available for these classes: attributes, info, quantities, and the properties found on
    (a sample of) their elements and types."""
    try:
        classes = json.loads(classes_json)
    except ValueError:
        classes = []
    props: dict = {}
    if B._model is not None:
        sample = []
        for cls in classes:
            try:
                sample += B._model.by_type(cls)[:300]
            except RuntimeError:
                pass
        ctx = _Ctx()
        for e in sample:
            for name, defs in ctx.definitions(e).items():
                for d in defs:
                    items = d.HasProperties if d.is_a("IfcPropertySet") else (d.Quantities if d.is_a("IfcElementQuantity") else ())
                    for p in items:
                        if not d.is_a("IfcPropertySet") or p.is_a("IfcPropertySingleValue"):
                            props.setdefault(name, set()).add(p.Name)
    fields = [_field("attribute", a) for a in ATTRIBUTES] + [_field("info", i) for i in INFO] + \
        [_field("quantity", q) for q in QUANTITIES]
    fields += [_field("property", p, pset=ps) for ps in sorted(props) for p in sorted(props[ps])]
    for f in fields:
        f["key"], f["label"] = field_key(f), _label(f)
    return B._dump({"fields": fields})


def set_schedule_value(guids_json: str, field_json: str, value_json: str) -> str:
    """Edit a cell: an attribute (Name, Tag, ...) or a property of every element in the row, one undo step.
    Properties go through app_bridge.set_property (the Properties panel's path)."""
    if B._model is None:
        return B._dump({"ok": False, "error": "no model open"})
    try:
        f = json.loads(field_json)
        value = json.loads(value_json)
    except ValueError as ex:
        return B._dump({"ok": False, "error": f"bad input: {ex}"})
    src, name = f.get("source"), f.get("name")
    if src == "property":
        return B.set_property(guids_json, f.get("pset", ""), name, json.dumps(value))
    if src != "attribute" or name not in EDITABLE_ATTRIBUTES:
        return B._dump({"ok": False, "error": f"{_label(f)} can't be edited here"})
    elements = [e for e in B._elements(guids_json) if hasattr(e, name)]
    if not elements:
        return B._dump({"ok": False, "error": f"these elements have no {name}"})
    text = None if value is None or str(value) == "" else str(value)

    def action():
        for e in elements:
            ifcopenshell.api.attribute.edit_attributes(B._model, product=e, attributes={name: text})
        return len(elements)

    try:
        return B._dump(B._run(action))
    except Exception as ex:
        return B._dump({"ok": False, "error": f"{type(ex).__name__}: {ex}"})
