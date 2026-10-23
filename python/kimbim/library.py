# SPDX-License-Identifier: GPL-3.0-or-later
"""The object library (doc 14 §8, D86; doc 16, D99): furniture, sanitary, kitchen and site objects as
Archicad's GDL library objects are: each object has parameters (width, depth, height and a few of its
own), a 3D body made of swept solids and a 2D plan symbol.

Objects are `.kimobj` definitions (D99, objects.py and objbuild.py): JSON the app reads, nothing in it
runs. The bundled ones are in bundled_objects/; the office library (a folder set in the preferences)
adds `.kimobj` files and IFC files, whose types (with their representation maps) are copied into the
model when placed.

Objects become IFC types (IfcFurnitureType, IfcSanitaryTerminalType, IfcElectricApplianceType,
IfcGeographicElementType, IfcBuildingElementProxyType; IFC2X3 equivalents), one type per object and
parameter set (D50's type/occurrence pattern), so repeated placements share their geometry through
mapped items and schedules count them by type. The type carries two representation maps: Body
(Model/Body/MODEL_VIEW, swept solids) and the plan symbol (Plan/Annotation/PLAN_VIEW, an
IfcGeometricCurveSet), and the KIMBIM_LibraryObject property set (Object, Parameters as JSON in
metres, Library, DefinitionHash and Definition: the definition's text, so a project opens and edits
its objects without the library that made them).

Object coordinates (metres): x along the width, y along the depth, z up from the level; the front
is the side at y = 0 (Archicad's convention), the origin its left front corner.

The bridge functions import app_bridge when called.
"""
from __future__ import annotations

import copy
import json
import math
import os
import pathlib
import re

import numpy as np

from . import objbuild, objects
from .objbuild import ObjectError, _translate

PSET = "KIMBIM_LibraryObject"
PARAMETERS = "Parameters"  # the Properties panel group (its edits go to set_object_parameter)
CATEGORIES = (("furniture", "Furniture"), ("sanitary", "Sanitary"), ("kitchen", "Kitchen"),
              ("site", "People, trees and cars"), ("office", "Office library"))

BUNDLED = pathlib.Path(__file__).with_name("bundled_objects")
OBJECTS: dict = {}  # ref -> objects.ObjectDef (bundled)


def _load_bundled() -> None:
    OBJECTS.clear()
    for path in sorted(BUNDLED.glob("*.kimobj")):
        d = objects.load_file(str(path), "bundled")
        OBJECTS[d.ref] = d


def _resolve(ref: str):
    """`use` of another library object: bundled ids, office refs, or office ids without the prefix."""
    found = OBJECTS.get(ref) or _office.get(ref) or _office.get(f"office:{ref}")
    return found if isinstance(found, objects.ObjectDef) else None


objects.ObjectDef.resolver = staticmethod(_resolve)


def _library_of(obj) -> str:
    """The Library a type and the listing name: "bundled", else the definition's file (or the library
    a project's own definition came from)."""
    return "bundled" if obj.source == "bundled" else (obj.library or obj.source)


def _use_names(defn) -> list:
    """Every `use` text in a definition's parts and its components' parts."""
    out = []
    for parts in [defn.parts, *(c.parts for c in defn.components.values())]:
        for part in parts if isinstance(parts, list) else ():
            if isinstance(part, dict) and isinstance(part.get("use"), str):
                out.append(part["use"])
    return out


def _library_refs():
    """name -> definition for every name `_resolve` answers (bundled ids, office refs and ids)."""
    out = {}
    for ref, d in _office.items():
        if isinstance(d, objects.ObjectDef):
            out.setdefault(ref.split(":", 1)[1] if ref.startswith("office:") else ref, d)
            out[ref] = d
    out.update(OBJECTS)
    return out


def _uses_of(obj) -> dict:
    """{ref: definition text} of every library object `obj` may `use`, transitively (D99): a project keeps
    them on the type, so it builds without the library and a changed library does not change it. A
    templated `use` ("leg_{foot}") takes every library object its name can match."""
    stored = getattr(obj, "uses", None)
    if stored is not None:
        return dict(stored)
    names, out, todo, seen = None, {}, [obj], set()
    while todo:
        d = todo.pop()
        for name in _use_names(d):
            if "{" not in name:
                if name in d.components:
                    continue
                found = [_resolve(name)]
            else:
                names = names if names is not None else _library_refs()
                texts = objbuild._TEMPLATE.split(name)[::2]  # the text between the {names}
                pattern = re.compile("^" + ".+".join(re.escape(t) for t in texts) + "$")
                found = [names[n] for n in names if pattern.match(n)]
            for u in found:
                if u is not None and u.ref != obj.ref and u.ref not in seen:
                    seen.add(u.ref)
                    out[u.ref] = u.text
                    todo.append(u)
    return out


def _hash_of(obj) -> str:
    """The DefinitionHash: the definition's text and the texts of the objects it uses."""
    uses = _uses_of(obj)
    return obj.hash if not uses else objects.digest(obj.text + objects.canonical(uses))


def _material_choices(default: str) -> list:
    """The model's building materials (the catalogue without a model), the default first if missing."""
    from . import app_bridge as B
    from . import materials

    names = [m.Name for m in B._model.by_type("IfcMaterial") if m.Name] if B._model is not None else list(materials.CATALOGUE)
    return names if default in names else [default, *names]


def footprint(obj, values: dict) -> tuple[float, float]:
    """Width and depth (metres) of an object's plan box."""
    w = values.get("width", 1.0)
    return w, values.get("depth", w)


# ---------------------------------------------------------------- office library

_office: dict = {}  # ref -> objects.ObjectDef or IFC type entry {"path", "guid", "name", "ifc_class"}
_office_paths = {"folder": "", "files": []}
_office_errors: list = []
_ifc_cache: dict = {}  # path -> (mtime, ifcopenshell.file)


def _open_library_ifc(path: str):
    import ifcopenshell

    mtime = os.path.getmtime(path)
    cached = _ifc_cache.get(path)
    if cached is None or cached[0] != mtime:
        cached = (mtime, ifcopenshell.open(path))
        _ifc_cache[path] = cached
    return cached[1]


def _load_ifc_types(path: str, category: str):
    f = _open_library_ifc(path)
    for t in f.by_type("IfcTypeProduct"):
        if t.is_a("IfcDoorType") or t.is_a("IfcWindowType") or not getattr(t, "RepresentationMaps", None):
            continue  # doors and windows go in walls; types without a shape place nothing
        key = f"ifc:{path}::{t.GlobalId}"
        _office[key] = {"path": path, "guid": t.GlobalId, "name": t.Name or t.is_a(), "ifc_class": t.is_a(),
                        "category": category}


def load_office(folder: str = "", files=()) -> None:
    """(Re)load the office library: *.kimobj definitions (D99) and *.ifc files' types. A file that does
    not load or build is listed in the errors and left out; the rest load."""
    _office.clear()
    _office_errors.clear()
    _office_paths["folder"], _office_paths["files"] = folder or "", list(files or ())
    paths = []
    if folder and os.path.isdir(folder):
        paths += sorted(str(p) for p in pathlib.Path(folder).iterdir() if p.suffix.lower() in (".kimobj", ".ifc"))
    paths += [p for p in files or () if p not in paths]
    parsed = []
    for path in paths:
        try:
            if path.lower().endswith(".kimobj"):
                d = objects.load_file(path, "office", check=False)
                d.category = "office"
                _office[d.ref] = d
                parsed.append((path, d))
            elif os.path.isfile(path):
                _load_ifc_types(path, "office")
        except ObjectError as ex:
            _office_errors.append({"file": path, "error": str(ex)})
        except Exception as ex:  # a broken file must not break the library
            _office_errors.append({"file": path, "error": f"{type(ex).__name__}: {ex}"})
    # Built once all are known, so office objects may use each other; again while any goes, so an object
    # using one that failed later in the order goes too.
    removed = True
    while removed:
        removed = False
        for path, d in list(parsed):
            try:
                objbuild.check(d)
                objbuild.build(d, d.values(), _resolve, all_anchors=True)
                continue
            except ObjectError as ex:
                error = str(ex)
            except Exception as ex:  # e.g. a formula giving a non-number where a length goes
                error = f"{type(ex).__name__}: {ex}"
            _office.pop(d.ref, None)
            _office_errors.append({"file": path, "error": error})
            parsed.remove((path, d))
            removed = True


def get(key: str):
    """The object definition (objects.ObjectDef) or an office IFC type entry (dict), or None."""
    return OBJECTS.get(key) or _office.get(key)


# ---------------------------------------------------------------- listing (the Library panel)

def _param_listing(obj, values) -> list:
    visible = set(obj.visible(values))
    env = {**values, "pi": math.pi}
    out = []
    for p in obj.params:
        lo, hi = p.bounds(env)
        item = {"key": p.key, "label": p.label["en"], "label_es": p.label["es"], "value": values[p.key],
                "kind": p.kind, "min": lo, "max": hi, "group": p.group, "visible": p.key in visible}
        if p.kind == "choice":
            item["options"] = [{"id": i, "label": label["en"], "label_es": label["es"]} for i, label in p.options]
        if p.kind == "material":
            item["choices"] = _material_choices(p.default)
        out.append(item)
    return out


def _listing(obj) -> dict:
    values = obj.values()
    w, d = footprint(obj, values)
    return {"id": obj.ref, "name": obj.name, "name_es": obj.names["es"], "category": obj.category,
            "ifc_class": obj.ifc["IFC4"][0], "params": _param_listing(obj, values),
            "symbol": obj.shape(values).polylines(), "width": w, "depth": d,
            "height": values.get("height", 1.0), "library": _library_of(obj)}


def library_objects() -> str:
    from . import app_bridge as B

    listed = [_listing(o) for o in OBJECTS.values()]
    for key, entry in _office.items():
        if isinstance(entry, objects.ObjectDef):
            item = _listing(entry)
        else:
            item = {"id": key, "name": entry["name"], "name_es": entry["name"], "category": entry["category"],
                    "ifc_class": entry["ifc_class"], "params": [], "symbol": [], "width": 1.0, "depth": 1.0,
                    "height": 1.0, "library": entry["path"]}
        listed.append(item)
    return B._dump({"categories": [{"id": k, "name": n} for k, n in CATEGORIES], "objects": listed,
                    "office": dict(_office_paths), "errors": list(_office_errors)})


def _given(params_json: str) -> dict:
    try:
        given = json.loads(params_json) if params_json else {}
    except ValueError:
        return {}
    return given if isinstance(given, dict) else {}


def object_symbol(key: str, params_json: str = "") -> str:
    """The plan symbol and plan box of an object with these parameters (the panel's thumbnail)."""
    from . import app_bridge as B

    obj = get(key)
    if not isinstance(obj, objects.ObjectDef):
        return B._dump({"symbol": [], "width": 1.0, "depth": 1.0})
    values = obj.values(_given(params_json))
    w, d = footprint(obj, values)
    try:
        symbol = obj.shape(values).polylines()
    except ObjectError:  # values the definition cannot build: no thumbnail rather than an error
        symbol = []
    return B._dump({"symbol": symbol, "width": w, "depth": d, "params": values})


def object_form(key: str, params_json: str = "") -> str:
    """The Library panel's parameter form for these values (D99): kinds, limits, which are shown."""
    from . import app_bridge as B

    obj = get(key)
    if not isinstance(obj, objects.ObjectDef):
        return B._dump({"params": [], "visible": []})
    values = obj.values(_given(params_json))
    return B._dump({"params": _param_listing(obj, values), "visible": obj.visible(values), "values": values})


def set_library_paths(data: str) -> str:
    """The office library: {"folder": path, "files": [IFC or .kimobj files]} (from the preferences)."""
    from . import app_bridge as B

    try:
        d = json.loads(data or "{}")
    except ValueError as ex:
        return B._dump({"ok": False, "error": str(ex)})
    load_office(d.get("folder", ""), d.get("files", []))
    return B._dump({"ok": True, "objects": len(_office), "errors": list(_office_errors)})


# ---------------------------------------------------------------- IFC (needs a model)

def _schema_family(f) -> str:
    return "IFC2X3" if f.schema == "IFC2X3" else "IFC4"


class _Writer:
    """Writes a Shape as IFC items in the model's length unit (D99 solids: a kind, fields in the solid's
    own frame, and the frame as a 4×4 matrix in object metres)."""

    def __init__(self, f, unit_scale):
        import ifcopenshell.util.unit

        self.f, self.k = f, 1.0 / unit_scale
        self.ifc2x3 = f.schema == "IFC2X3"
        unit = ifcopenshell.util.unit.get_project_unit(f, "PLANEANGLEUNIT")
        self.degrees = unit is not None and unit.is_a("IfcConversionBasedUnit") and (unit.Name or "").upper() == "DEGREE"

    def angle(self, degrees):
        return float(degrees) if self.degrees else math.radians(degrees)

    def p2(self, x, y):
        return self.f.createIfcCartesianPoint((float(x) * self.k, float(y) * self.k))

    def p3(self, x, y, z):
        return self.f.createIfcCartesianPoint((float(x) * self.k, float(y) * self.k, float(z) * self.k))

    def d3(self, v):
        return self.f.createIfcDirection(tuple(float(c) for c in v))

    def a2(self, x=0.0, y=0.0):
        return self.f.createIfcAxis2Placement2D(self.p2(x, y), None)

    def placement(self, m):
        m = np.asarray(m)
        return self.f.createIfcAxis2Placement3D(self.p3(*m[:3, 3]), self.d3(m[:3, 2]), self.d3(m[:3, 0]))

    def polyline2(self, pts):
        return self.f.createIfcPolyline([self.p2(x, y) for x, y in pts])

    def closed(self, pts):
        pts = [tuple(p) for p in pts]
        return self.f.createIfcArbitraryClosedProfileDef("AREA", None, self.polyline2(pts + [pts[0]]))

    def extrude(self, profile, m, depth):
        return self.f.createIfcExtrudedAreaSolid(profile, self.placement(m), self.d3((0, 0, 1)), float(depth) * self.k)

    def solids(self, s) -> list:
        f, kind, m = self.f, s["kind"], np.asarray(s["matrix"])
        up = lambda z: m @ _translate(0, 0, z)  # noqa: E731
        if kind == "box":
            t = s["taper"] if not self.ifc2x3 else 1.0
            scale = 1.0 if not self.ifc2x3 else (1 + s["taper"]) / 2  # IFC2X3: untapered at the mean size
            cx, cy = s["x"] + s["dx"] / 2, s["y"] + s["dy"] / 2
            profile = f.createIfcRectangleProfileDef("AREA", None, self.a2(cx, cy), s["dx"] * scale * self.k, s["dy"] * scale * self.k)
            if t < 1 - 1e-9:
                end = f.createIfcRectangleProfileDef("AREA", None, self.a2(cx, cy), s["dx"] * t * self.k, s["dy"] * t * self.k)
                return [f.createIfcExtrudedAreaSolidTapered(profile, self.placement(up(s["z"])), self.d3((0, 0, 1)),
                                                            s["dz"] * self.k, end)]
            return [self.extrude(profile, up(s["z"]), s["dz"])]
        if kind == "cylinder":
            profile = f.createIfcCircleProfileDef("AREA", None, self.a2(s["cx"], s["cy"]), s["r"] * self.k)
            return [self.extrude(profile, up(s["z"]), s["h"])]
        if kind == "prism":
            return [self.extrude(self.closed(s["points"]), up(s["z"]), s["h"])]
        if kind in ("cone", "revolve"):
            if kind == "cone":
                profile_pts = [(0, 0), (s["r1"], 0), (s["r2"], s["h"]), (0, s["h"])]
                base, angle = m @ _translate(s["cx"], s["cy"], s["z"]), 360.0
            else:
                profile_pts, base, angle = s["profile"], m, s["angle"]
            # The profile lies in the frame's x-z plane and turns about the frame's z axis: the placement's
            # x is the frame's x, its z is -y (so its y, z × x, is the frame's z), and the revolve axis is
            # the placement's y.
            plane = base.copy()
            plane[:3, 0], plane[:3, 1], plane[:3, 2] = base[:3, 0], base[:3, 2], -base[:3, 1]
            axis = f.createIfcAxis1Placement(self.p3(0, 0, 0), self.d3((0, 1, 0)))
            return [f.createIfcRevolvedAreaSolid(self.closed(profile_pts), self.placement(plane), axis, self.angle(angle))]
        # sweep
        if s.get("r") is not None:
            path = [tuple((m @ [x, y, z, 1])[:3]) for x, y, z in s["path"]]
            directrix = f.createIfcPolyline([self.p3(*p) for p in path])
            # IFC2X3 requires the directrix's parameter range (a polyline's: 0 to its segment count)
            start, end = (0.0, float(len(path) - 1)) if self.ifc2x3 else (None, None)
            return [f.createIfcSweptDiskSolid(directrix, s["r"] * self.k, None, start, end)]
        out = []
        for p, q in zip(s["path"], s["path"][1:]):
            seg, length = objbuild._segment_frame(p, q)
            out.append(self.extrude(self.closed(s["profile"]), m @ seg, length))
        return out

    def curve(self, c):
        if c[0] == "poly":
            return self.polyline2(c[1])
        _, cx, cy, r = c
        return self.f.createIfcCircle(self.a2(cx, cy), r * self.k)


def _contexts():
    from . import annotations, authoring

    return authoring._body_context(), annotations._context()


def _representations(obj, values: dict):
    """(body, plan) IfcShapeRepresentations for the object with these values."""
    import ifcopenshell.util.unit

    from . import app_bridge as B

    f = B._model
    shape = obj.shape(values)
    writer = _Writer(f, ifcopenshell.util.unit.calculate_unit_scale(f))
    body_context, plan_context = _contexts()
    items, parts = [], []
    for s in shape.solids:
        for item in writer.solids(s):
            items.append(item)
            parts.append(s["part"])
    advanced = any(i.is_a("IfcSweptDiskSolid") or i.is_a("IfcExtrudedAreaSolidTapered") for i in items)
    # IFC2X3's AdvancedSweptSolid takes no area sweeps beside a disk sweep: SolidModel takes both
    kind = ("SolidModel" if writer.ifc2x3 else "AdvancedSweptSolid") if advanced else "SweptSolid"
    body = f.createIfcShapeRepresentation(body_context, "Body", kind, items)
    _style_parts(f, obj, values, items, parts)
    plan = None
    if shape.curves:
        curve_set = f.createIfcGeometricCurveSet([writer.curve(c) for c in shape.curves])
        plan = f.createIfcShapeRepresentation(plan_context, "Annotation", "Annotation2D", [curve_set])
    return body, plan


def _style_parts(f, obj, values: dict, items, parts):
    """D97: every solid shows its part's building material (its surface as the item's style), so the 3D
    view and other IFC viewers colour the parts."""
    import ifcopenshell.api.style

    from . import materials

    styles = {}
    for item, part in zip(items, parts):
        name = obj.material_of(values, part)
        if not name:
            continue
        if name not in styles:
            m = materials.ensure(name, f)
            styles[name] = materials.surface_of(m)
        if styles[name] is not None:
            ifcopenshell.api.style.assign_item_style(f, item=item, style=styles[name])


def _params_of_type(t) -> tuple[str, dict] | None:
    """(object key, parameter values) of a library type, or None."""
    import ifcopenshell.util.element

    data = ifcopenshell.util.element.get_pset(t, PSET) if t is not None else None
    if not data or not data.get("Object"):
        return None
    try:
        values = json.loads(data.get("Parameters") or "{}")
    except ValueError:
        values = {}
    return data["Object"], values


def _library_types(f):
    out = []
    for t in f.by_type("IfcTypeProduct"):
        if any(getattr(ps, "Name", None) == PSET for ps in (getattr(t, "HasPropertySets", None) or ())):
            out.append(t)
    return out


def _find_type(f, ref: str, values: dict, digest: str):
    """The library type made from this definition (its DefinitionHash) with these values, or None."""
    import ifcopenshell.util.element

    for t in _library_types(f):
        info = _params_of_type(t)
        if info is not None and info[0] == ref and info[1] == values and \
                ifcopenshell.util.element.get_pset(t, PSET, "DefinitionHash") == digest:
            return t
    return None


def _set_predefined(t, predefined, element):
    if predefined and hasattr(t, "PredefinedType"):
        t.PredefinedType = predefined
    if element and (predefined in (None, "USERDEFINED") or not hasattr(t, "PredefinedType")):
        t.ElementType = element
    if hasattr(t, "AssemblyPlace") and t.AssemblyPlace is None:
        t.AssemblyPlace = "NOTDEFINED"


def _pset_of(t):
    import ifcopenshell.api.pset

    from . import app_bridge as B

    return next((p for p in (t.HasPropertySets or ()) if p.Name == PSET), None) or \
        ifcopenshell.api.pset.add_pset(B._model, product=t, name=PSET)


def _write_pset(t, obj, values) -> None:
    """The type's KIMBIM_LibraryObject: its object, values, library and its definition (D99)."""
    import ifcopenshell.api.pset

    from . import app_bridge as B

    uses = _uses_of(obj)
    ifcopenshell.api.pset.edit_pset(B._model, pset=_pset_of(t), properties={
        "Object": obj.ref, "Parameters": json.dumps(values, sort_keys=True), "Library": _library_of(obj),
        "DefinitionHash": _hash_of(obj), "Definition": obj.text, "Uses": objects.canonical(uses)})


def definition_of_type(t):
    """The definition a library type was made from (D99): the text stored on it, so a project opens and
    edits without the library that made it."""
    import ifcopenshell.util.element

    data = ifcopenshell.util.element.get_pset(t, PSET) if t is not None else None
    if not data or not data.get("Definition"):
        return None
    try:
        uses = json.loads(data.get("Uses") or "{}")
        stored = {ref: objects.from_text(text, "project", "", ref) for ref, text in uses.items()}
        # a copy: the parsed definition is shared by every type with this text, the Uses are this type's
        d = copy.copy(objects.from_text(data["Definition"], "project", data.get("Library") or "", data.get("Object") or ""))
    except (ObjectError, ValueError, TypeError, AttributeError):
        return None
    d.uses = uses
    # `use` resolves only from the definitions stored with it, never the live library
    d.resolver = lambda name: stored.get(name) or stored.get(f"office:{name}")
    return d


def _make_type(obj, values: dict):
    import ifcopenshell.api.geometry
    import ifcopenshell.api.root

    from . import app_bridge as B

    f = B._model
    type_class, predefined, element = obj.ifc_for(f.schema)
    body, plan = _representations(obj, values)  # first: a definition that fails leaves no empty type
    t = ifcopenshell.api.root.create_entity(f, ifc_class=type_class, name=obj.type_name(values))
    _set_predefined(t, predefined, element)
    ifcopenshell.api.geometry.assign_representation(f, product=t, representation=body)
    if plan is not None:
        ifcopenshell.api.geometry.assign_representation(f, product=t, representation=plan)
    _write_pset(t, obj, values)
    return t


def _type_for(obj, values: dict):
    from . import app_bridge as B

    return _find_type(B._model, obj.ref, values, _hash_of(obj)) or _make_type(obj, values)


def _ifc_type(entry: dict):
    """The office IFC type copied into the model (once: placing it again reuses it)."""
    import ifcopenshell.api.project
    import ifcopenshell.api.pset

    from . import app_bridge as B

    f = B._model
    try:
        return f.by_guid(entry["guid"])
    except RuntimeError:
        pass
    library = _open_library_ifc(entry["path"])
    t = ifcopenshell.api.project.append_asset(f, library=library, element=library.by_guid(entry["guid"]))
    ifcopenshell.api.pset.edit_pset(f, pset=_pset_of(t), properties={
        "Object": f"ifc:{entry['guid']}", "Parameters": "{}", "Library": entry["path"]})
    return t


def _remove_type_if_unused(t) -> None:
    """A library type nothing uses any more goes, with its geometry (keeps files small)."""
    import ifcopenshell.api.root
    import ifcopenshell.util.element

    from . import app_bridge as B

    if t is None or not t.id() or ifcopenshell.util.element.get_types(t):
        return
    if _params_of_type(t) is None or str(_params_of_type(t)[0]).startswith("ifc:"):
        return  # only types the library generated
    ifcopenshell.api.root.remove_product(B._model, product=t)


def _occurrence_class(type_class: str, schema: str) -> str:
    import ifcopenshell.util.type

    names = ifcopenshell.util.type.get_applicable_entities(type_class, schema=schema)
    decl = __import__("ifcopenshell").schema_by_name(schema)
    for name in names:
        try:
            if not decl.declaration_by_name(name).is_abstract():
                return name
        except RuntimeError:
            continue
    return "IfcBuildingElementProxy"


def _scale() -> float:
    import ifcopenshell.util.unit

    from . import app_bridge as B

    return ifcopenshell.util.unit.calculate_unit_scale(B._model)


def place_object(storey_guid: str, key: str, params_json: str, x, y, angle=0.0, gravity="") -> str:
    """Place a library object on a level: its origin (left front corner) at (x, y) metres, turned
    `angle` radians. The type with these parameters is reused, or made. One undo step. `gravity`
    (D97, Archicad's Gravity): "1" puts it on the top of the slab under (x, y), if any."""
    import ifcopenshell.api.geometry
    import ifcopenshell.api.root
    import ifcopenshell.api.spatial
    import ifcopenshell.api.type
    import numpy as np

    from . import app_bridge as B
    from . import authoring as A
    from . import layers, renovation

    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    obj = get(key)
    if obj is None:
        return A._fail(f"no library object {key}")
    try:
        given = json.loads(params_json) if params_json else {}
        x, y, angle = float(x), float(y), float(angle or 0.0)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    values = obj.values(given) if isinstance(obj, objects.ObjectDef) else {}
    if isinstance(obj, objects.ObjectDef):
        try:
            obj.shape(values)  # a definition that does not build at these values places nothing
        except (ObjectError, ValueError) as ex:
            return A._fail(str(ex))
    z = A._elevation(storey)
    if str(gravity) in ("1", "true", "True"):
        from . import symbols

        top = symbols._slab_top(storey, (x, y))
        z = top if top is not None else z
    made = {}

    def action():
        f = B._model
        t = _type_for(obj, values) if isinstance(obj, objects.ObjectDef) else _ifc_type(obj)
        element = ifcopenshell.api.root.create_entity(f, ifc_class=_occurrence_class(t.is_a(), f.schema),
                                                      name=obj.name if isinstance(obj, objects.ObjectDef) else (t.Name or ""))
        ifcopenshell.api.type.assign_type(f, related_objects=[element], relating_type=t)
        c, s = math.cos(angle), math.sin(angle)
        matrix = np.array([[c, -s, 0, x], [s, c, 0, y], [0, 0, 1, z], [0, 0, 0, 1]], dtype=float)
        ifcopenshell.api.geometry.edit_object_placement(f, product=element, matrix=matrix, is_si=True)
        ifcopenshell.api.spatial.assign_container(f, products=[element], relating_structure=storey)
        layers.assign_active(element)
        renovation.stamp_new(element)
        made["element"], made["type"] = element, t
        return 1, [element.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["element"].GlobalId, "type": made["type"].GlobalId})


def set_plan_display(guids_json: str, value: str) -> str:
    """D91: per object, whether its plan shows the 2D plan symbol or the 3D body seen from above."""
    import ifcopenshell.api.pset
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import authoring as A

    if value not in ("symbol", "body"):
        return A._fail(f"unknown plan display {value}")
    if B._model is None:
        return A._fail("no model open")
    elements = B._elements(guids_json)
    if not elements:
        return A._fail("no elements selected")

    def action():
        for e in elements:
            data = ifcopenshell.util.element.get_pset(e, PSET, should_inherit=False)
            pset = e.file.by_id(data["id"]) if data else ifcopenshell.api.pset.add_pset(e.file, product=e, name=PSET)
            ifcopenshell.api.pset.edit_pset(e.file, pset=pset, properties={"PlanDisplay": value})
        return len(elements), [e.GlobalId for e in elements], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def _object_of(e):
    """(definition, values, type) of a placed library object, or None. The type's own definition (D99)."""
    import ifcopenshell.util.element

    t = ifcopenshell.util.element.get_type(e)
    obj = definition_of_type(t)
    info = _params_of_type(t)
    if obj is None or info is None:
        return None
    return obj, obj.values(info[1]), t


def parameters_of(elements) -> list:
    """The Properties panel's Parameters group per element: the visible parameters as
    {"label", "value", "kind", "choices"?} (a choice shows its option's label), or None."""
    out = []
    for e in elements:
        found = _object_of(e)
        if found is None:
            out.append(None)
            continue
        obj, values, _ = found
        visible = set(obj.visible(values))
        rows = []
        for p in obj.params:
            if p.key not in visible:
                continue
            row = {"label": p.label["en"], "value": values[p.key], "kind": p.kind}
            if p.kind == "choice":
                row["value"] = p.option_label(values[p.key])
                row["choices"] = [label["en"] for _, label in p.options]
            rows.append(row)
        out.append(rows)
    return out


def is_object(e) -> bool:
    return _object_of(e) is not None


def _regenerate_type(t, obj, values: dict) -> None:
    """New geometry for a type in place: every placement of it follows (mapped items)."""
    import ifcopenshell.util.element

    from . import app_bridge as B

    f = B._model
    body, plan = _representations(obj, values)
    for rep_map in t.RepresentationMaps or ():
        old = rep_map.MappedRepresentation
        new = body if old.RepresentationIdentifier == "Body" else plan
        if new is None:
            continue
        old_items = list(old.Items)
        old.Items = new.Items
        old.RepresentationType = new.RepresentationType
        f.remove(new)
        for item in old_items:
            ifcopenshell.util.element.remove_deep2(f, item)
    for unused in (body, plan):
        if unused is not None and unused.id() and not unused.OfProductRepresentation and not unused.RepresentationMap:
            try:
                f.remove(unused)
            except RuntimeError:
                pass
    t.Name = obj.type_name(values)
    _write_pset(t, obj, values)


def object_parameter_usage(guids_json: str, name: str) -> str:
    """Whether editing `name` on these objects would also touch other placements: {"elements": all
    placements of their types, "selected": those selected, "shared": any placement is not selected}."""
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    selected, everyone = 0, set()
    for e in B._elements(guids_json):
        found = _object_of(e)
        if found is None or found[0].param(name) is None:
            continue
        selected += 1
        everyone.update(ifcopenshell.util.element.get_types(found[2]))
    return B._dump({"ok": True, "elements": len(everyone), "selected": selected,
                    "shared": len(everyone) > selected})


def set_object_parameter(guids_json: str, name: str, value, scope: str = "") -> str:
    """Change a parameter of the selected library objects. If they are every placement of their
    type, the type changes in place (keeping its GlobalId); otherwise only the selected ones move to
    the type with the new value (found or made) and the others keep theirs. `scope` (D92): "selection"
    (the default behaviour) or "type" (every placement of their types changes). One undo step."""
    import ifcopenshell.api.type
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    groups: dict = {}
    for e in B._elements(guids_json):
        found = _object_of(e)
        if found is None:
            continue
        obj, values, t = found
        p = obj.param(name)
        if p is None:
            continue
        if p.kind == "material":  # D97: a building material for one part
            from . import materials

            v = str(value).strip()
            if not v or (materials._material_by_name(B._model, v) is None and v not in materials.CATALOGUE):
                return A._fail(f"unknown building material {value}")
        elif p.kind == "choice":  # an option's id or label (either language)
            v = str(value).strip().lower()
            if not any(v in (i.lower(), label["en"].lower(), label["es"].lower()) for i, label in p.options):
                return A._fail(f"unknown option {value} for {p.label['en']}")
            v = value
        elif p.kind == "bool":
            if not isinstance(value, bool) and str(value).strip().lower() not in objects._TRUE | objects._FALSE:
                return A._fail(f"{p.label['en']}: not on or off")
            v = value
        else:
            try:
                v = float(str(value).strip().replace(",", "."))
            except ValueError:
                return A._fail(f"not a number: {value}")
            if p.kind == "length" and v <= 0:
                return A._fail(f"{p.label['en']} must be more than 0")
        new_values = dict(values)
        new_values[p.key] = v
        try:
            new_values = obj.values(new_values)  # re-cleans every value: limits that are formulas follow
            obj.shape(new_values)  # a formula that breaks at these values fails the edit (doc 16 §7)
        except (ObjectError, ValueError) as ex:
            return A._fail(str(ex))
        groups.setdefault(t.id(), (t, obj, new_values, []))[3].append(e)
    if not groups:
        return A._fail(f"no selected object has a parameter {name}")

    def action():
        f = B._model
        changed = []
        for t, obj, new_values, elements in groups.values():
            everyone = set(ifcopenshell.util.element.get_types(t))
            whole_type = scope == "type" or (scope != "selection" and everyone <= set(elements))
            if whole_type and _find_type(f, obj.ref, new_values, _hash_of(obj)) is None:
                _regenerate_type(t, obj, new_values)
                changed += [o.GlobalId for o in everyone]
            elif whole_type:
                target = _type_for(obj, new_values)  # every placement moves to the existing type
                ifcopenshell.api.type.assign_type(f, related_objects=list(everyone), relating_type=target)
                _remove_type_if_unused(t)
                changed += [o.GlobalId for o in everyone]
            else:
                target = _type_for(obj, new_values)
                ifcopenshell.api.type.assign_type(f, related_objects=elements, relating_type=target)
                _remove_type_if_unused(t)
                changed += [e.GlobalId for e in elements]
        return len(changed), changed, []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


def _outdated(elements) -> list:
    """[(element, project definition, values, type, library definition)] whose library has another version
    (its text or the text of an object it uses differs: the DefinitionHash)."""
    out = []
    for e in elements:
        found = _object_of(e)
        if found is None:
            continue
        obj, values, t = found
        current = get(obj.ref)
        if isinstance(current, objects.ObjectDef) and _hash_of(current) != _hash_of(obj):
            out.append((e, obj, values, t, current))
    return out


def _targets(guids_json: str):
    from . import app_bridge as B

    if guids_json in ("", "[]"):
        return [e for e in B._model.by_type("IfcElement") if _object_of(e) is not None]
    return B._elements(guids_json)


def library_updates(guids_json: str = "") -> str:
    """How many of these placed objects (all, given "") have a newer definition in the library (D99)."""
    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    return B._dump({"ok": True, "outdated": len(_outdated(_targets(guids_json)))})


def update_from_library(guids_json: str = "") -> str:
    """Regenerate these placed objects (all, given "") from the library's definition, keeping every
    parameter value whose key and kind still exist. One undo step."""
    import ifcopenshell.api.type

    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    todo = _outdated(_targets(guids_json))
    if not todo:
        return A._fail("these objects already match the library")
    groups: dict = {}
    for e, obj, values, t, current in todo:
        kinds = {p.key: p.kind for p in current.params}
        kept = {k: v for k, v in values.items() if k in kinds and obj.param(k) is not None and kinds[k] == obj.param(k).kind}
        try:
            new_values = current.values(kept)
            current.shape(new_values)
        except (ObjectError, ValueError) as ex:
            return A._fail(f"{current.name}: {ex}")
        key = (t.id(), json.dumps(new_values, sort_keys=True))
        groups.setdefault(key, (t, current, new_values, []))[3].append(e)

    def action():
        changed = []
        for t, current, new_values, elements in groups.values():
            target = _type_for(current, new_values)
            ifcopenshell.api.type.assign_type(B._model, related_objects=elements, relating_type=target)
            _remove_type_if_unused(t)
            changed += [e.GlobalId for e in elements]
        return len(changed), changed, []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)


_load_bundled()
