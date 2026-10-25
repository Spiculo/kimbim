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
import functools
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


def _template_names(defn, name: str):
    """The names a templated `use` gives when every {name} in it is a choice parameter (of the object
    or one of its components; a key in several takes all their options): one per combination of the
    options; else None."""
    choices = {}
    for p in [*defn.params, *(p for c in defn.components.values() for p in c.params)]:
        if p.kind == "choice":
            choices.setdefault(p.key, {}).update(dict.fromkeys(i for i, _ in p.options))
    keys = objbuild._TEMPLATE.findall(name)
    if not keys or any(k not in choices for k in keys):
        return None
    out = [name]
    for k in dict.fromkeys(keys):
        out = [n.replace("{" + k + "}", option) for n in out for option in choices[k]]
    return out


def _uses_of(obj) -> dict:
    """{ref: definition text} of every library object `obj` may `use`, transitively (D99): a project keeps
    them on the type, so it builds without the library and a changed library does not change it. A
    templated `use` ("leg_{foot}") takes the names its choice parameters' options give, or, when a name in
    it is not a choice, every library object its name can match; names of the file's components are its
    own parts, never library objects."""
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
                expanded = _template_names(d, name)
                if expanded is None:
                    names = names if names is not None else _library_refs()
                    texts = objbuild._TEMPLATE.split(name)[::2]  # the text between the {names}
                    pattern = re.compile("^" + ".+".join(re.escape(t) for t in texts) + "$")
                    expanded = [n for n in names if pattern.match(n)]
                found = [_resolve(n) for n in expanded if n not in d.components]
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
# D100: saved versions shared through the office library (types of its IFC files with a VersionId), by id:
# {"id", "name", "object", "values", "hash", "path", "guid"}
_office_versions: dict = {}
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
    """An office IFC file's types: fixed `ifc:` entries, or office versions (D100) when they carry a
    VersionId (kimbim-versions.ifc, written by objversions.move_version_to_library)."""
    import ifcopenshell.util.element

    from . import objversions

    f = _open_library_ifc(path)
    for t in f.by_type("IfcTypeProduct"):
        data = ifcopenshell.util.element.get_pset(t, PSET) or {}
        if data.get(objversions.VERSION_ID):
            try:
                values = json.loads(data.get("Parameters") or "{}")
            except ValueError:
                values = {}
            vid = data[objversions.VERSION_ID]
            _office_versions[vid] = {"id": vid, "name": data.get(objversions.VERSION_NAME) or t.Name or "",
                                     "object": data.get("Object") or "",
                                     "values": values if isinstance(values, dict) else {},
                                     "hash": data.get("DefinitionHash") or "", "path": path, "guid": t.GlobalId}
            continue
        if t.is_a("IfcDoorType") or t.is_a("IfcWindowType") or not getattr(t, "RepresentationMaps", None):
            continue  # doors and windows go in walls; types without a shape place nothing
        key = f"ifc:{path}::{t.GlobalId}"
        _office[key] = {"path": path, "guid": t.GlobalId, "name": t.Name or t.is_a(), "ifc_class": t.is_a(),
                        "category": category}


def load_office(folder: str = "", files=()) -> None:
    """(Re)load the office library: *.kimobj definitions (D99) and *.ifc files' types. A file that does
    not load or build is listed in the errors and left out; the rest load."""
    _office.clear()
    _office_versions.clear()
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


def office_definition(entry: dict):
    """The definition an office version (D100) was made from: the text stored on its type, or None."""
    try:
        return definition_of_type(_open_library_ifc(entry["path"]).by_guid(entry["guid"]))
    except Exception:  # the file went or changed since it loaded
        return None


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
                "kind": p.kind, "min": lo, "max": hi, "group": p.group, "group_es": p.group_es,
                "visible": p.key in visible}
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


def _definition_for(key: str, version: str = ""):
    """(definition, the version's values) the dialog works on (D100): saved or office version `version`'s
    own stored definition, or a placed type's ("type:<GlobalId>", objversions.object_settings_of), else
    the object's (also one gone from the library, stored on a type). The definition is None for an office
    IFC type or an unknown key, version or type."""
    from . import objversions

    if version.startswith(objversions.TYPE_SOURCE):
        t = objversions.type_of_source(version)
        info = _params_of_type(t) if t is not None else None
        return (definition_of_type(t), info[1]) if info is not None else (None, {})
    if version:
        saved = objversions.find_version(version)
        if saved is not None:
            info = _params_of_type(saved)
            return definition_of_type(saved), (info[1] if info is not None else {})
        if version in _office_versions:
            entry = _office_versions[version]
            return office_definition(entry), dict(entry["values"])
        return None, {}
    return objversions._definition(key), {}


def object_symbol(key: str, params_json: str = "", version: str = "") -> str:
    """The plan symbol and plan box of an object with these parameters (the panel's thumbnail; with
    `version`, from that saved version's own definition, D100)."""
    from . import app_bridge as B

    obj, base = _definition_for(key, version)
    if not isinstance(obj, objects.ObjectDef):
        return B._dump({"symbol": [], "width": 1.0, "depth": 1.0})
    values = obj.values({**base, **_given(params_json)})
    w, d = footprint(obj, values)
    try:
        symbol = obj.shape(values).polylines()
    except ObjectError:  # values the definition cannot build: no thumbnail rather than an error
        symbol = []
    return B._dump({"symbol": symbol, "width": w, "depth": d, "params": values})


def object_form(key: str, params_json: str = "", version: str = "") -> str:
    """The parameter form for these values (D99): kinds, limits, which are shown, and the object's name.
    With `version` (D100), from that saved or office version's own stored definition, over its values."""
    from . import app_bridge as B

    obj, base = _definition_for(key, version)
    if not isinstance(obj, objects.ObjectDef):
        entry = get(key)  # an office IFC type (fixed geometry): only its name
        name = entry["name"] if isinstance(entry, dict) else key
        return B._dump({"params": [], "visible": [], "name": name, "name_es": name})
    values = obj.values({**base, **_given(params_json)})
    return B._dump({"params": _param_listing(obj, values), "visible": obj.visible(values), "values": values,
                    "name": obj.name, "name_es": obj.names["es"]})


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
    """The unnamed library type made from this definition (its DefinitionHash) with these values, or None.
    Saved versions (D100) are never found by their values: they are chosen by their id."""
    import ifcopenshell.util.element

    from . import objversions

    for t in _library_types(f):
        info = _params_of_type(t)
        if info is not None and info[0] == ref and info[1] == values and \
                ifcopenshell.util.element.get_pset(t, PSET, "DefinitionHash") == digest and not objversions.is_saved(t):
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
    """The type's KIMBIM_LibraryObject: its object, values, library and its definition (D99). Only these
    fields are written: a saved version's VersionId and VersionName (D100) stay."""
    import ifcopenshell.api.pset

    from . import app_bridge as B

    f, uses = B._model, _uses_of(obj)
    # the long texts are IfcText (doc 16 §4): an IfcLabel holds at most 255 characters
    ifcopenshell.api.pset.edit_pset(f, pset=_pset_of(t), properties={
        "Object": obj.ref, "Parameters": f.createIfcText(json.dumps(values, sort_keys=True)),
        "Library": _library_of(obj), "DefinitionHash": _hash_of(obj), "Definition": f.createIfcText(obj.text),
        "Uses": f.createIfcText(objects.canonical(uses))})


@functools.lru_cache(maxsize=512)
def _checked(text) -> bool:
    """Whether a definition text stored in a project parses and passes objbuild.check (once per text)."""
    try:
        objbuild.check(objects.from_text(text, "project"))
        return True
    except Exception:
        return False


def definition_of_type(t):
    """The definition a library type was made from (D99): the text stored on it, so a project opens and
    edits without the library that made it."""
    import ifcopenshell.util.element

    data = ifcopenshell.util.element.get_pset(t, PSET) if t is not None else None
    if not data or not data.get("Definition"):
        return None
    try:
        uses = json.loads(data.get("Uses") or "{}")
        if not all(_checked(text) for text in [data["Definition"], *uses.values()]):
            return None  # a stored text that is not a definition (edited by hand): not an object
        stored = {ref: objects.from_text(text, "project", "", ref) for ref, text in uses.items()}
        # a copy: the parsed definition is shared by every type with this text, the Uses are this type's
        d = copy.copy(objects.from_text(data["Definition"], "project", data.get("Library") or "", data.get("Object") or ""))
    except Exception:  # whatever a tampered pset holds, the element is just not an editable object
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
        "Object": f"ifc:{entry['guid']}", "Parameters": f.createIfcText("{}"), "Library": entry["path"]})
    return t


def _remove_type_if_unused(t) -> None:
    """A library type nothing uses any more goes, with its geometry (keeps files small). Saved versions
    (D100) stay: the project library keeps them until they are deleted."""
    import ifcopenshell.api.root
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import objversions

    if t is None or not t.id() or ifcopenshell.util.element.get_types(t) or objversions.is_saved(t):
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


def place_object(storey_guid: str, key: str, params_json: str, x, y, angle=0.0, gravity="", version="") -> str:
    """Place a library object on a level: its origin (left front corner) at (x, y) metres, turned
    `angle` radians. The type with these parameters is reused, or made. One undo step. `gravity`
    (D97, Archicad's Gravity): "1" puts it on the top of the slab under (x, y), if any. `version` (D100):
    a saved version's id; it places that version's type and `params_json` is ignored (it works without
    the object in the library: the type has everything). An office version's id the project has no copy
    of copies it in first, in the same undo step (objversions.copy_office_version); later placements
    reuse the copy."""
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
    saved = office = None
    if version:
        from . import objversions

        saved = objversions.find_version(version)
        office = _office_versions.get(version) if saved is None else None
        if saved is None and office is None:
            return A._fail("unknown version")
        if saved is not None:
            info = _params_of_type(saved)
            if info is None or (key and info[0] != key):
                return A._fail(f"that version is not one of {key}")
            obj = definition_of_type(saved)
            name = obj.name if obj is not None else (saved.Name or "")
        else:
            if key and office["object"] != key:
                return A._fail(f"that version is not one of {key}")
            obj = office_definition(office)
            if obj is None:
                return A._fail(f"the office version {office['name']} has no definition")
            name = obj.name
        params_json = ""
    else:
        obj = get(key)
        if obj is None:
            return A._fail(f"no library object {key}")
    try:
        given = json.loads(params_json) if params_json else {}
        x, y, angle = float(x), float(y), float(angle or 0.0)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    fresh = saved is None and isinstance(obj, objects.ObjectDef)  # values to build: given, or an office version's
    values = obj.values(office["values"] if office is not None else given) if fresh else {}
    if fresh:
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
        if saved is not None:
            t, element_name = saved, name
        elif office is not None:
            t, element_name = objversions.copy_office_version(office, obj, values), name
        elif isinstance(obj, objects.ObjectDef):
            t, element_name = _type_for(obj, values), obj.name
        else:
            t = _ifc_type(obj)
            element_name = t.Name or ""
        element = ifcopenshell.api.root.create_entity(f, ifc_class=_occurrence_class(t.is_a(), f.schema),
                                                      name=element_name)
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


# ---------------------------------------------------------------- the settings dialog's preview (D100)

PREVIEW_GUID = "0KimBimPreviewObject00"  # the preview's one element: each update replaces the last


def _preview_definition(key: str, params_json: str, version: str = ""):
    """(definition, values) the Object settings dialog previews: `version`'s (a saved or office version's
    id) or the object's, with the dialog's values checked and applied like an edit (doc 16 §7). An office
    IFC type gives (its entry, {}). ObjectError with the reason when the values don't build."""
    if version:
        from . import objversions

        if objversions.find_version(version) is None and version not in _office_versions \
                and objversions.type_of_source(version) is None:
            raise ObjectError("unknown version")
        obj, base = _definition_for(key, version)
        if obj is None:
            raise ObjectError("that version has no definition")
    else:
        entry = get(key)
        if entry is not None and not isinstance(entry, objects.ObjectDef):
            return entry, {}  # fixed geometry, no parameters
        obj, base = _definition_for(key)
        if obj is None:
            raise ObjectError(f"no library object {key}")
    try:
        given = json.loads(params_json) if params_json else {}
    except ValueError as ex:
        raise ObjectError(f"bad input: {ex}") from None
    if not isinstance(given, dict):
        raise ObjectError("the values are an object {parameter: value}")
    return obj, _edited_values(obj, obj.values(base), given)


def _copy_materials(model, f, obj, values: dict) -> None:
    """The project's own building materials into the scratch model, so the preview shows their surfaces
    as the project has them (edited or not in the catalogue); materials.ensure makes the rest."""
    import ifcopenshell.api.project

    from . import materials

    if model is None:
        return
    names = {obj.material_of(values, part) for part in obj.materials} | {v for k, v in values.items() if k.startswith("mat_")}
    for name in sorted(n for n in names if n):
        m = materials._material_by_name(model, name)
        if m is not None and materials._material_by_name(f, name) is None:
            ifcopenshell.api.project.append_asset(f, library=model, element=m)


def _preview_meshes(obj, values: dict):
    """One placement of the object at the origin, built in a scratch in-memory model with the code real
    types use (_make_type: the same representations and part styles), meshed in the mesh_elements format.
    B._model is swapped in only while building and always restored: the project and its undo history are
    never touched."""
    import ifcopenshell.api.geometry
    import ifcopenshell.api.owner.settings
    import ifcopenshell.api.project
    import ifcopenshell.api.root
    import ifcopenshell.api.type
    import ifcopenshell.api.unit
    import ifcopenshell.geom

    from . import app_bridge as B

    model = B._model
    schema = model.schema if model is not None else "IFC4"
    f = ifcopenshell.api.project.create_file(version=schema)
    owner = ifcopenshell.api.owner.settings
    get_user, get_application = owner.get_user, owner.get_application
    if schema == "IFC2X3":  # every root entity needs an owner history: the scratch model's own user
        organization = f.createIfcOrganization(None, "KimBim")
        user = f.createIfcPersonAndOrganization(f.createIfcPerson(None, None, "KimBim"), organization)
        application = f.createIfcApplication(organization, "0", "KimBim", "KimBim")
        owner.get_user = lambda ifc: user if ifc is f else get_user(ifc)
        owner.get_application = lambda ifc: application if ifc is f else get_application(ifc)
    B._model = f
    try:
        ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="Preview")
        ifcopenshell.api.unit.assign_unit(f)
        if isinstance(obj, objects.ObjectDef):
            _copy_materials(model, f, obj, values)
            t = _make_type(obj, values)
        else:
            t = _ifc_type(obj)  # copied from its IFC library file into the scratch model
        element = ifcopenshell.api.root.create_entity(f, ifc_class=_occurrence_class(t.is_a(), schema))
        element.GlobalId = PREVIEW_GUID
        ifcopenshell.api.type.assign_type(f, related_objects=[element], relating_type=t)
        ifcopenshell.api.geometry.edit_object_placement(f, product=element)
        it = ifcopenshell.geom.iterator(B._mesh_settings(), f, 1, include=[element],
                                        geometry_library="hybrid-cgal-simple-opencascade")
        if not it.initialize():
            return None
        return B._collect_meshes(it)[0]
    finally:
        B._model = model
        owner.get_user, owner.get_application = get_user, get_application


def object_preview(key: str, params_json: str = "", version: str = ""):
    """The Object settings dialog's 3D preview (D100): mesh parts in the mesh_elements format for one
    placement of the object (or saved version `version`) with these values at the origin, or None when
    the values don't build (object_preview_error says why)."""
    try:
        obj, values = _preview_definition(key, params_json, version)
    except (ObjectError, ValueError):
        return None
    try:
        return _preview_meshes(obj, values)
    except Exception:  # whatever goes wrong, the dialog keeps its last preview
        return None


def object_preview_error(key: str, params_json: str = "", version: str = "") -> str:
    """{"ok": true} when these values of an object (or of saved version `version`) build, else
    {"ok": false, "error": the reason}."""
    from . import app_bridge as B
    from . import authoring as A

    try:
        obj, values = _preview_definition(key, params_json, version)
        if isinstance(obj, objects.ObjectDef):
            obj.shape(values)
    except (ObjectError, ValueError) as ex:
        return A._fail(str(ex))
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True})


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
    """The Properties panel's Parameters summary per element: the visible parameters as
    {"label", "value", "kind"} (a choice shows its option's label), or None."""
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
            rows.append(row)
        out.append(rows)
    return out


def is_object(e) -> bool:
    return _object_of(e) is not None


def _regenerate_type(t, obj, values: dict) -> None:
    """New geometry for a type in place: every placement of it follows (mapped items). A saved version
    (D100) keeps its name."""
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import objversions

    f = B._model
    body, plan = _representations(obj, values)
    leftover = [r for r in (body, plan) if r is not None]
    for rep_map in t.RepresentationMaps or ():
        old = rep_map.MappedRepresentation
        new = body if old.RepresentationIdentifier == "Body" else plan
        if new is None or not any(new is r for r in leftover):
            continue
        old_items = list(old.Items)
        old.Items = new.Items
        old.RepresentationType = new.RepresentationType
        leftover = [r for r in leftover if r is not new]
        f.remove(new)
        for item in old_items:
            ifcopenshell.util.element.remove_deep2(f, item)
    # Removed once each: removing an entity twice logs it twice in the undo transaction, and undo then
    # fails re-creating it (D100 review focus 1).
    for unused in leftover:
        f.remove(unused)
    if not objversions.is_saved(t):
        t.Name = obj.type_name(values)
    _write_pset(t, obj, values)


def _checked_value(p, value):
    """A value for parameter `p` as the UI gives it (text, or JSON from the dialog), checked: ObjectError
    with the reason when it is not one (values() would quietly fall back to the default, or clamp a length
    to its limit)."""
    from . import app_bridge as B

    if p.kind == "material":  # D97: a building material for one part
        from . import materials

        v = str(value).strip()
        if not v or (materials._material_by_name(B._model, v) is None and v not in materials.CATALOGUE):
            raise ObjectError(f"unknown building material {value}")
        return v
    if p.kind == "choice":  # an option's id or label (either language)
        v = str(value).strip().lower()
        if not any(v in (i.lower(), label["en"].lower(), label["es"].lower()) for i, label in p.options):
            raise ObjectError(f"unknown option {value} for {p.label['en']}")
        return value
    if p.kind == "bool":
        if not isinstance(value, bool) and str(value).strip().lower() not in objects._TRUE | objects._FALSE:
            raise ObjectError(f"{p.label['en']}: not on or off")
        return value
    try:
        v = float(str(value).strip().replace(",", "."))
    except ValueError:
        raise ObjectError(f"not a number: {value}") from None
    if not math.isfinite(v):
        raise ObjectError(f"not a number: {value}")
    if p.kind == "length" and v <= 0:
        raise ObjectError(f"{p.label['en']} must be more than 0")
    return v


def _edited_values(obj, values: dict, edits: dict) -> dict:
    """`values` with `edits` ({parameter key or label: value}) checked and applied, every value re-cleaned
    (limits that are formulas follow) and built: ObjectError (a ValueError) when a value is not one or the
    definition cannot build them (doc 16 §7)."""
    new_values = dict(values)
    for name, value in edits.items():
        p = obj.param(name)
        if p is None:
            raise ObjectError(f"{obj.name} has no parameter {name}")
        new_values[p.key] = _checked_value(p, value)
    new_values = obj.values(new_values)
    obj.shape(new_values)
    return new_values


def _retype_whole(t, obj, values: dict) -> None:
    """Every placement of type `t` takes these values (D100 *modify all*). The type regenerates in place,
    keeping its GlobalId, unless it is unnamed and an unnamed type with these values exists: everyone moves
    there and `t` goes. A saved version never merges, into any type."""
    import ifcopenshell.api.type
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import objversions

    target = None if objversions.is_saved(t) else _find_type(B._model, obj.ref, values, _hash_of(obj))
    if target is None or target == t:
        _regenerate_type(t, obj, values)
        return
    ifcopenshell.api.type.assign_type(B._model, related_objects=list(ifcopenshell.util.element.get_types(t)),
                                      relating_type=target)
    _remove_type_if_unused(t)


def set_object_parameter(guids_json: str, name: str, value, scope: str = "") -> str:
    """Change a parameter of the selected library objects. If they are every placement of their
    type, the type changes (_retype_whole: in place, keeping its GlobalId, or joining an identical unnamed
    type); otherwise only the selected ones move to the type with the new value (found or made) and the
    others keep theirs. `scope` (D92): "selection" (the default behaviour) or "type" (every placement of
    their types changes). One undo step."""
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
        try:
            new_values = _edited_values(obj, values, {p.key: value})
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
            if scope == "type" or (scope != "selection" and everyone <= set(elements)):
                _retype_whole(t, obj, new_values)
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


def _kept_values(obj, values: dict, current) -> dict:
    """`values` (of definition `obj`) for definition `current`: every value whose key and kind still exist
    is kept, the rest take `current`'s defaults. Not built: the caller checks they build."""
    kinds = {p.key: p.kind for p in current.params}
    kept = {k: v for k, v in values.items() if k in kinds and obj.param(k) is not None and kinds[k] == obj.param(k).kind}
    return current.values(kept)


def _outdated(elements) -> list:
    """[(element, project definition, values, type, library definition)] whose library has another version
    (its text or the text of an object it uses differs: the DefinitionHash). A placement of a saved version
    (D100) is outdated when its type is (objversions.outdated_versions)."""
    from . import objversions

    out, saved = [], {}
    for e in elements:
        found = _object_of(e)
        if found is None:
            continue
        obj, values, t = found
        if objversions.is_saved(t):
            if t.id() not in saved:
                saved[t.id()] = objversions._outdated_version(t)
            if saved[t.id()] is not None:
                out.append((e, obj, values, t, saved[t.id()][3]))
            continue
        current = get(obj.ref)
        if isinstance(current, objects.ObjectDef) and _hash_of(current) != _hash_of(obj):
            out.append((e, obj, values, t, current))
    return out


def _targets(guids_json: str):
    from . import app_bridge as B

    if guids_json in ("", "[]"):
        return [e for e in B._model.by_type("IfcElement") if _object_of(e) is not None]
    return B._elements(guids_json)


def _outdated_versions_of(guids_json: str) -> list:
    """objversions.outdated_versions of every saved version (given "", used or not), or of the types of
    these elements."""
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import objversions

    if guids_json in ("", "[]"):
        return objversions.outdated_versions()
    types = {t.id(): t for e in B._elements(guids_json) if (t := ifcopenshell.util.element.get_type(e)) is not None}
    return objversions.outdated_versions(list(types.values()))


def library_updates(guids_json: str = "") -> str:
    """How many of these placed objects (all, given "") have a newer definition in the library (D99), and
    how many saved versions (D100: every one, used or not, given ""; else the selection's) are outdated."""
    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    return B._dump({"ok": True, "outdated": len(_outdated(_targets(guids_json))),
                    "versions": len(_outdated_versions_of(guids_json))})


def update_from_library(guids_json: str = "") -> str:
    """Regenerate these placed objects (all, given "") from the library's definition, keeping every
    parameter value whose key and kind still exist. Outdated saved versions (D100: every one given "", else
    the selection's) regenerate in place, keeping their GlobalId, name and VersionId; every placement
    follows. One undo step."""
    import ifcopenshell.api.type
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import authoring as A
    from . import objversions

    if B._model is None:
        return A._fail("no model open")
    versions = _outdated_versions_of(guids_json)
    todo = [x for x in _outdated(_targets(guids_json)) if not objversions.is_saved(x[3])]
    if not todo and not versions:
        return A._fail("these objects already match the library")
    for t, _, _, current, new_values in versions:
        try:
            current.shape(new_values)
        except (ObjectError, ValueError) as ex:
            return A._fail(f"{t.Name}: {ex}")
    groups: dict = {}
    for e, obj, values, t, current in todo:
        try:
            new_values = _kept_values(obj, values, current)
            current.shape(new_values)
        except (ObjectError, ValueError) as ex:
            return A._fail(f"{current.name}: {ex}")
        key = (t.id(), json.dumps(new_values, sort_keys=True))
        groups.setdefault(key, (t, current, new_values, []))[3].append(e)

    def action():
        changed = []
        for t, _, _, current, new_values in versions:
            _regenerate_type(t, current, new_values)  # keeps the name and the version fields
            objversions.refresh_office_state(t)  # an office copy: the office state it now follows
            changed += [e.GlobalId for e in ifcopenshell.util.element.get_types(t)]
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
