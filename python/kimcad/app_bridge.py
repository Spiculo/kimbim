# SPDX-License-Identifier: GPL-3.0-or-later
"""The desktop app's view of an open IFC model (docs/01: the model engine owns the working state).

The C++ app embeds Python and calls these functions. Protocol: plain strings and bytes only,
JSON for structured data, raw little-endian arrays for meshes. Functions never raise; errors are
returned as {"ok": false, "error": ...} or {"error": ...} so the GUI can show them.
"""
from __future__ import annotations

import json
import traceback

import ifcopenshell
import ifcopenshell.util.element

_model: ifcopenshell.file | None = None


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def open_model(path: str) -> str:
    global _model
    try:
        f = ifcopenshell.open(path)
    except Exception as e:  # unreadable or not IFC: report, keep the app usable
        return _dump({"ok": False, "error": f"{type(e).__name__}: {e}"})
    _model = f
    _reset_history(path)
    projects = f.by_type("IfcProject")
    return _dump({
        "ok": True,
        "schema": f.schema_identifier,
        "project": (projects[0].Name or "") if projects else "",
        "elements": len(f.by_type("IfcElement")),
    })


def _node(e) -> dict:
    children = []
    for rel in getattr(e, "IsDecomposedBy", None) or ():
        children.extend(rel.RelatedObjects)
    for rel in getattr(e, "ContainsElements", None) or ():
        children.extend(rel.RelatedElements)
    children.sort(key=lambda c: (c.is_a(), c.Name or "", c.GlobalId))
    return {"guid": e.GlobalId, "type": e.is_a(), "name": e.Name or "", "children": [_node(c) for c in children]}


def spatial_tree() -> str:
    if _model is None:
        return _dump({"error": "no model open"})
    projects = _model.by_type("IfcProject")
    if not projects:
        return _dump({"error": "the model has no IfcProject"})
    return _dump(_node(projects[0]))


def _scalar(v):
    if isinstance(v, ifcopenshell.entity_instance):
        return None if v.id() else v.wrappedValue  # entity references are not shown as attributes
    if isinstance(v, (tuple, list)):
        items = [_scalar(x) for x in v]
        return None if any(i is None for i in items) else items
    return v


def properties(guid: str) -> str:
    if _model is None:
        return _dump({"error": "no model open"})
    try:
        e = _model.by_guid(guid)
    except RuntimeError:
        return _dump({"error": f"unknown GlobalId {guid}"})
    try:
        attributes = {k: s for k, v in e.get_info(recursive=False).items() if k not in ("id", "type") and (s := _scalar(v)) is not None}
        psets = {
            name: {k: _scalar(v) if not isinstance(v, (str, int, float, bool)) else v for k, v in props.items() if k != "id"}
            for name, props in ifcopenshell.util.element.get_psets(e).items()
        }
        return _dump({"guid": guid, "type": e.is_a(), "name": e.Name or "", "attributes": attributes, "psets": psets})
    except Exception as ex:
        return _dump({"error": f"{type(ex).__name__}: {ex}", "trace": traceback.format_exc()[-400:]})


_iterator = None
_iterator_done = True
# Voids are subtracted from their hosts; spaces are room volumes that would hide walls and windows.
# Both stay in the tree and properties; spaces get a "show spaces" toggle later.
NOT_DISPLAYED = ["IfcOpeningElement", "IfcSpace"]


def start_meshing(threads: int = 0) -> str:
    """Start display tessellation: hybrid CGAL/OCCT kernel (D38), world coordinates."""
    global _iterator, _iterator_done
    import multiprocessing

    import ifcopenshell.geom

    _iterator, _iterator_done = None, True
    if _model is None:
        return _dump({"ok": False, "error": "no model open"})
    try:
        s = ifcopenshell.geom.settings()
        s.set("use-world-coords", True)
        n = int(threads) or multiprocessing.cpu_count()
        it = ifcopenshell.geom.iterator(s, _model, n, exclude=NOT_DISPLAYED, geometry_library="hybrid-cgal-simple-opencascade")
        if not it.initialize():
            return _dump({"ok": True, "total": 0})  # nothing to draw
    except Exception as e:
        return _dump({"ok": False, "error": f"{type(e).__name__}: {e}"})
    _iterator, _iterator_done = it, False
    return _dump({"ok": True, "total": len(_model.by_type("IfcProduct"))})


def next_mesh_chunk(max_elements: int = 1000):
    """Next batch of element meshes as (meta_json, verts f32 LE, tris u32 LE, chunk-local), or None when done."""
    global _iterator_done
    import numpy as np

    if _iterator is None or _iterator_done:
        return None
    guids, types, verts, tris, voff, toff = [], [], [], [], [0], [0]
    while len(guids) < int(max_elements):
        shape = _iterator.get()
        t = np.asarray(shape.geometry.faces, dtype=np.uint32)
        if len(t):
            v = np.asarray(shape.geometry.verts, dtype=np.float32)
            verts.append(v)
            tris.append(t + voff[-1])
            voff.append(voff[-1] + len(v) // 3)
            toff.append(toff[-1] + len(t) // 3)
            guids.append(shape.guid)
            types.append(shape.type)
        if not _iterator.next():
            _iterator_done = True
            break
    if not guids:
        return None
    meta = _dump({"guids": guids, "types": types, "voff": voff, "toff": toff})
    return meta, np.concatenate(verts).astype("<f4").tobytes(), np.concatenate(tris).astype("<u4").tobytes()


# ---------------------------------------------------------------- editing (M2, D49)
# Every user action is one ifcopenshell transaction (undo/redo for free). State ids mirror
# ifcopenshell's history stack so "unsaved changes" is exact, even after undoing past a save.
_path = ""
_base_id = 0      # state id with no transaction applied (changes if the history overflows)
_ids: list[int] = []      # one id per transaction in _model.history
_future_ids: list[int] = []  # one id per transaction in _model.future
_saved_id = 0
_next_id = 1


def _reset_history(path: str):
    global _path, _base_id, _ids, _future_ids, _saved_id, _next_id
    _path, _base_id, _ids, _future_ids, _saved_id, _next_id = path, 0, [], [], 0, 1


def _current_id() -> int:
    return _ids[-1] if _ids else _base_id


def _flags() -> dict:
    return {"can_undo": bool(_ids), "can_redo": bool(_future_ids)}


def state() -> str:
    return _dump({"dirty": _current_id() != _saved_id, "path": _path, **_flags()})


def _run(action) -> dict:
    """Run `action()` (which returns the number of changed elements) as one undoable transaction."""
    global _next_id, _base_id
    _model.begin_transaction()
    try:
        changed = action()
    finally:
        _model.end_transaction()
    _ids.append(_next_id)
    _next_id += 1
    _future_ids.clear()
    while len(_ids) > len(_model.history):  # ifcopenshell dropped its oldest transaction
        _base_id = _ids.pop(0)
    return {"ok": True, "changed": changed}


def _elements(guids_json: str) -> list:
    out = []
    for g in json.loads(guids_json):
        try:
            out.append(_model.by_guid(g))
        except RuntimeError:
            pass
    return out


def _schema():
    import ifcopenshell.ifcopenshell_wrapper as W

    return W.schema_by_name(_model.schema_identifier)


def _primitive(ifc_type: str) -> str | None:
    """Underlying EXPRESS simple type of a defined type: string, real, integer, boolean, logical, ..."""
    decl = _schema().declaration_by_name(ifc_type)
    while decl is not None:
        td = decl.as_type_declaration()
        if td is None:
            return None
        dt = td.declared_type()
        if dt.as_simple_type() is not None:
            return dt.as_simple_type().declared_type()
        nt = dt.as_named_type()
        decl = nt.declared_type() if nt is not None else None
    return None


_TRUE = {"true", "yes", "sí", "si", "1", "verdadero"}
_FALSE = {"false", "no", "0", "falso"}


def _convert(value, ifc_type: str):
    """Convert user input to the Python value of `ifc_type`; raises ValueError on invalid input."""
    prim = _primitive(ifc_type)
    bad = ValueError(f"{value!r} is not a valid {ifc_type}")
    if prim in ("real", "number"):
        if isinstance(value, bool):
            raise bad
        if isinstance(value, str):
            text = value.strip()
            if text.count(",") == 1 and "." not in text:
                text = text.replace(",", ".")  # Spanish decimal comma
            try:
                return float(text)
            except ValueError:
                raise bad from None
        return float(value)
    if prim == "integer":
        try:
            f = float(str(value).replace(",", "."))
        except ValueError:
            raise bad from None
        if isinstance(value, bool) or not f.is_integer():
            raise bad
        return int(f)
    if prim in ("boolean", "logical"):
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        if prim == "logical" and text == "unknown":
            return "UNKNOWN"
        raise bad
    return str(value)


def _infer_type(value) -> str:
    if isinstance(value, bool):
        return "IfcBoolean"
    if isinstance(value, int):
        return "IfcInteger"
    if isinstance(value, float):
        return "IfcReal"
    return "IfcLabel"


def _template_type(pset: str, prop: str) -> str | None:
    import ifcopenshell.util.pset

    template = ifcopenshell.util.pset.get_template(_template_schema()).get_by_name(pset)
    for p in getattr(template, "HasPropertyTemplates", None) or ():
        if p.Name == prop and getattr(p, "PrimaryMeasureType", None):
            return p.PrimaryMeasureType
    return None


def _template_schema() -> str:
    s = _model.schema_identifier
    return "IFC4X3" if s.startswith("IFC4X3") else ("IFC2X3" if s == "IFC2X3" else "IFC4")


def _own_pset(e, pset: str):
    """The element's own (occurrence) property set entity, or None. Type-level psets are not edited."""
    for rel in getattr(e, "IsDefinedBy", None) or ():
        if rel.is_a("IfcRelDefinesByProperties"):
            d = rel.RelatingPropertyDefinition
            if d.is_a("IfcPropertySet") and d.Name == pset:
                return d
    return None


def _own_property(e, pset: str, prop: str):
    ps = _own_pset(e, pset)
    for p in (ps.HasProperties if ps else ()):
        if p.Name == prop:
            return p
    return None


def set_property(guids_json: str, pset: str, prop: str, value_json: str) -> str:
    import ifcopenshell.api.pset

    if _model is None:
        return _dump({"ok": False, "error": "no model open"})
    try:
        elements = _elements(guids_json)
        value = json.loads(value_json)
        # Decide every element's IFC type and convert ALL values before touching the model,
        # so invalid input changes nothing (no partial edit, no undo step).
        fallback = _template_type(pset, prop) or _infer_type(value)
        plan = []
        for e in elements:
            existing = _own_property(e, pset, prop)
            ifc_type = existing.NominalValue.is_a() if existing is not None and existing.NominalValue else fallback
            plan.append((e, ifc_type, _convert(value, ifc_type)))
    except ValueError as ex:
        return _dump({"ok": False, "error": str(ex)})

    def action():
        for e, ifc_type, converted in plan:
            ps = _own_pset(e, pset) or ifcopenshell.api.pset.add_pset(_model, product=e, name=pset)
            ifcopenshell.api.pset.edit_pset(_model, pset=ps, properties={prop: _model.create_entity(ifc_type, converted)})
        return len(plan)

    try:
        return _dump(_run(action))
    except Exception as ex:
        return _dump({"ok": False, "error": f"{type(ex).__name__}: {ex}"})


def remove_property(guids_json: str, pset: str, prop: str) -> str:
    import ifcopenshell.api.pset

    if _model is None:
        return _dump({"ok": False, "error": "no model open"})
    targets = [e for e in _elements(guids_json) if _own_property(e, pset, prop) is not None]

    def action():
        for e in targets:
            ifcopenshell.api.pset.edit_pset(_model, pset=_own_pset(e, pset), properties={prop: None}, should_purge=True)
        return len(targets)

    return _dump(_run(action))


def set_name(guids_json: str, name: str) -> str:
    import ifcopenshell.api.attribute

    if _model is None:
        return _dump({"ok": False, "error": "no model open"})
    elements = _elements(guids_json)

    def action():
        for e in elements:
            ifcopenshell.api.attribute.edit_attributes(_model, product=e, attributes={"Name": name})
        return len(elements)

    return _dump(_run(action))


def undo() -> str:
    if _model is None or not _ids:
        return _dump({"ok": False, "error": "nothing to undo", **(_flags() if _model else {})})
    _model.undo()
    _future_ids.append(_ids.pop())
    return _dump({"ok": True, **_flags()})


def redo() -> str:
    if _model is None or not _future_ids:
        return _dump({"ok": False, "error": "nothing to redo", **(_flags() if _model else {})})
    _model.redo()
    _ids.append(_future_ids.pop())
    return _dump({"ok": True, **_flags()})


def save(path: str = "") -> str:
    global _saved_id, _path
    if _model is None:
        return _dump({"ok": False, "error": "no model open"})
    target = path or _path
    try:
        _model.write(target)
    except Exception as ex:
        return _dump({"ok": False, "error": f"{type(ex).__name__}: {ex}"})
    _saved_id, _path = _current_id(), target
    return _dump({"ok": True, "path": target})


def pset_templates(ifc_class: str) -> str:
    import ifcopenshell.util.pset

    if _model is None:
        return _dump({"names": []})
    names = ifcopenshell.util.pset.get_template(_template_schema()).get_applicable_names(ifc_class, pset_only=True)
    return _dump({"names": sorted(names)})


_MISSING = object()


def _element_values(e) -> dict:
    """{pset: {prop: (value, ifc_type, editable)}}: type-level values first, the element's own override them."""
    out: dict = {}
    import ifcopenshell.util.element

    definitions = []
    t = ifcopenshell.util.element.get_type(e)
    definitions += [(d, False) for d in (getattr(t, "HasPropertySets", None) or ())] if t is not None else []
    for rel in getattr(e, "IsDefinedBy", None) or ():
        if rel.is_a("IfcRelDefinesByProperties"):
            definitions.append((rel.RelatingPropertyDefinition, True))
    for d, own in definitions:
        props = out.setdefault(d.Name, {})
        if d.is_a("IfcPropertySet"):
            for p in d.HasProperties:
                if p.is_a("IfcPropertySingleValue"):
                    v = p.NominalValue
                    props[p.Name] = (v.wrappedValue if v is not None else None, v.is_a() if v is not None else None, True)
                else:
                    props[p.Name] = (p.is_a(), p.is_a(), False)  # lists/tables/enums: shown, not editable yet
        elif d.is_a("IfcElementQuantity"):
            for q in d.Quantities:
                value = next((x for k, x in q.get_info(recursive=False).items() if k.endswith("Value")), None)
                props[q.Name] = (value, q.is_a(), False)  # quantities are computed, not typed in
    return out


def properties_multi(guids_json: str) -> str:
    if _model is None:
        return _dump({"error": "no model open"})
    elements = _elements(guids_json)
    if not elements:
        return _dump({"error": "no known elements selected"})
    per = [_element_values(e) for e in elements]
    psets: dict = {}
    for pset in sorted({p for d in per for p in d}):
        props = {}
        for prop in sorted({k for d in per for k in d.get(pset, {})}):
            entries = [d.get(pset, {}).get(prop, _MISSING) for d in per]
            present = [x for x in entries if x is not _MISSING]
            values = [x[0] for x in present]
            varies = len(present) != len(entries) or any(v != values[0] for v in values)
            props[prop] = {
                "value": None if varies else values[0],
                "varies": varies,
                "ifc_type": next((x[1] for x in present if x[1]), None),
                "editable": all(x[2] for x in present),
            }
        psets[pset] = props
    names = [e.Name or "" for e in elements]
    same_name = all(n == names[0] for n in names)
    return _dump({
        "count": len(elements),
        "guids": [e.GlobalId for e in elements],
        "types": sorted({e.is_a() for e in elements}),
        "name": {"value": names[0] if same_name else None, "varies": not same_name},
        "psets": psets,
    })


def _write_test_model(path: str) -> str:
    """Write a small model (2 walls on one storey) for the app's C++ tests and self-test."""
    from .testing import build_model

    build_model(walls=2).write(path)
    return _dump({"ok": True, "path": path})
