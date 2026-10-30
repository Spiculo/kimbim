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
# Both stay in the tree and properties; spaces get a "show spaces" toggle later. Annotations are 2D
# (drawn by the plan overlay) or drawing cameras, whose box would hide the model (D60).
NOT_DISPLAYED = ["IfcOpeningElement", "IfcSpace", "IfcAnnotation"]


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


def _collect_meshes(it, max_elements=None):
    """Element meshes from a geometry iterator as (meta_json, verts f32 LE, tris u32 LE, face colours
    u16 LE), chunk-local, or None without any. Stops after `max_elements` (returns done=True at the end).
    D96: each triangle has a palette index (`meta.palette`: [r, g, b, transparency] rows); 0xFFFF is
    no surface (the app's class colour)."""
    import numpy as np

    from . import materials

    from . import settings

    palette = materials.Palette()
    slice_layers = bool(settings.current().get("layers_in_3d", True))
    guids, types, verts, tris, colours, voff, toff = [], [], [], [], [], [0], [0]
    done = False
    while max_elements is None or len(guids) < int(max_elements):
        shape = it.get()
        t = np.asarray(shape.geometry.faces, dtype=np.uint32)
        if len(t):
            v = np.asarray(shape.geometry.verts, dtype=np.float32)
            try:
                element = _model.by_id(shape.id)
                sliced = materials.layered_mesh(element, v, t, palette) if slice_layers else None  # D96
                if sliced is not None:
                    v, t, c = sliced
                else:
                    c = materials.face_colours(element, shape.geometry, v, t, palette)
            except Exception:  # a colour problem must never stop the model from showing
                c = np.full(len(t) // 3, materials.NO_COLOUR, dtype=np.uint32)
            verts.append(v)
            tris.append(t + voff[-1])
            colours.append(c)
            voff.append(voff[-1] + len(v) // 3)
            toff.append(toff[-1] + len(t) // 3)
            guids.append(shape.guid)
            types.append(shape.type)
        if not it.next():
            done = True
            break
    if not guids:
        return None, done
    meta = _dump({"guids": guids, "types": types, "voff": voff, "toff": toff, "palette": palette.rows})
    return (meta, np.concatenate(verts).astype("<f4").tobytes(), np.concatenate(tris).astype("<u4").tobytes(),
            np.concatenate(colours).astype("<u2").tobytes()), done


def next_mesh_chunk(max_elements: int = 1000):
    """Next batch of element meshes (see _collect_meshes), or None when done."""
    global _iterator_done

    if _iterator is None or _iterator_done:
        return None
    parts, done = _collect_meshes(_iterator, max_elements)
    if done:
        _iterator_done = True
    return parts


def _mesh_settings():
    import ifcopenshell.geom

    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    return s


def mesh_elements(guids_json: str):
    """Meshes of specific elements (after an edit), in the next_mesh_chunk format, or None."""
    import ifcopenshell.geom

    if _model is None:
        return None
    elements = [e for e in _elements(guids_json) if e.is_a() not in NOT_DISPLAYED and getattr(e, "Representation", None)]
    if not elements:
        return None
    it = ifcopenshell.geom.iterator(_mesh_settings(), _model, 1, include=elements,
                                    geometry_library="hybrid-cgal-simple-opencascade")
    if not it.initialize():
        return None
    return _collect_meshes(it)[0]


# ---------------------------------------------------------------- editing (M2, D49)
# Every user action is one ifcopenshell transaction (undo/redo for free). State ids mirror
# ifcopenshell's history stack so "unsaved changes" is exact, even after undoing past a save.
_path = ""
_base_id = 0      # state id with no transaction applied (changes if the history overflows)
_ids: list[int] = []      # one id per transaction in _model.history
_future_ids: list[int] = []  # one id per transaction in _model.future
_saved_id = 0
_next_id = 1
# Geometry touched by each transaction (guids whose shape changed or that were added/removed),
# parallel to _ids/_future_ids, so undo/redo can tell the 3D view what to re-mesh (Slice 4).
_deltas: list[list[str]] = []
_future_deltas: list[list[str]] = []
# Drawing revision, parallel to _ids/_future_ids: it only advances for transactions that can change
# what a drawing shows. Sheet-placement edits (moving a view, legend or symbol on a sheet, D72/D74)
# touch an IfcDocumentReference and leave the drawings untouched, so they keep the revision and the
# generated drawing cache stays valid (moving a drawing on a sheet must not regenerate it).
_base_drawing_id = 0
_drawing_ids: list[int] = []
_future_drawing_ids: list[int] = []
# Settings snapshot of each step that changed them (D92: underlay edits are undoable), parallel to
# _ids/_future_ids; None for a step that left the settings alone.
_settings_before: list = []
_future_settings_before: list = []
_pending_settings = None  # set by _run_settings: the settings state before its transaction


# Set when a failed edit could not be rolled back: the model may be half-changed, so edits and
# undo stop until the file is reopened (saving a copy still works).
_inconsistent = False
INCONSISTENT = ("The edit failed and could not be undone, so the model may be inconsistent. "
                "Save a copy if you need it, then reopen the file.")


def _reset_history(path: str):
    global _path, _base_id, _ids, _future_ids, _saved_id, _next_id, _deltas, _future_deltas, _inconsistent
    global _base_drawing_id, _drawing_ids, _future_drawing_ids, _settings_before, _future_settings_before
    _path, _base_id, _ids, _future_ids, _saved_id, _next_id = path, 0, [], [], 0, 1
    _deltas, _future_deltas = [], []
    _base_drawing_id, _drawing_ids, _future_drawing_ids = 0, [], []
    _settings_before, _future_settings_before = [], []
    _inconsistent = False
    from . import versioning  # a different model leaves versioned mode (not the project's own working copy)

    versioning.forget(path)
    from . import layers

    layers.forget()
    from . import documents, settings

    kept = settings.current()
    settings.load(None)
    if documents.on_model_opened(path) == "working copy":
        # the document's own working copy reopened (an option switch, discard, combine): its settings
        # are the ones the switch put in place, not the defaults
        settings.load(kept)
    from . import drawings  # the cached drawing snapshots belong to the old model

    drawings.forget_snapshots()


def _geometry_now(guids) -> dict:
    """Split touched guids into those that exist now (re-mesh) and those that don't (remove)."""
    changed, removed = [], []
    for g in dict.fromkeys(guids):
        try:
            _model.by_guid(g)
            changed.append(g)
        except RuntimeError:
            removed.append(g)
    return {"changed": changed, "removed": removed}


def _current_id() -> int:
    return _ids[-1] if _ids else _base_id


def _drawing_rev() -> int:
    """Model state as drawings see it: unchanged by sheet-placement edits (see _drawing_ids)."""
    return _drawing_ids[-1] if _drawing_ids else _base_drawing_id


def _flags() -> dict:
    return {"can_undo": bool(_ids), "can_redo": bool(_future_ids)}


def _dirty() -> bool:
    """Unsaved work: model edits since the last save, or changed project settings."""
    from . import settings

    return _current_id() != _saved_id or settings.is_dirty()


def state() -> str:
    return _dump({"dirty": _dirty(), "path": _path, "inconsistent": _inconsistent, **_flags()})


# Called inside every edit's transaction with (geometry_changed, geometry_removed) GlobalIds; returns
# more changed GlobalIds. Modules register follow-ups that must be part of the same undo step.
AFTER_ACTION: list = []
# An open console edit() block (D82): (geometry_changed, geometry_removed) collected from the commands run
# inside it, which then join its undo step instead of making their own.
_step: tuple[list, list] | None = None


def _run(action, affects_drawings: bool = True) -> dict:
    """Run `action()` as one undoable transaction. It returns the number of changed elements, or
    (count, geometry_changed_guids, geometry_removed_guids) when it touched shapes.
    `affects_drawings=False` for edits that only move things on a sheet: the generated drawing cache
    stays valid (moving a placed view must not regenerate its drawing)."""
    if _step is not None:  # inside the console's edit() block: join its undo step
        changed = action()
        count, geo_changed, geo_removed = changed if isinstance(changed, tuple) else (changed, [], [])
        _step[0].extend(geo_changed)
        _step[1].extend(geo_removed)
        geometry = {"changed": list(dict.fromkeys(geo_changed)), "removed": list(dict.fromkeys(geo_removed))}
        return {"ok": True, "changed": count, "geometry": geometry}
    _begin()
    try:
        changed = action()
        count, geo_changed, geo_removed = changed if isinstance(changed, tuple) else (changed, [], [])
        changed = _follow_ups(count, geo_changed, geo_removed)
    except BaseException as failure:
        _abort(failure)
        raise
    return _commit(*changed, affects_drawings=affects_drawings)


def _run_settings(action, affects_drawings: bool = False) -> dict:
    """Run `action()` as one undoable transaction whose settings change is undone with it (D92: underlay
    edits). `action()` returns the usual count (or tuple); the settings it changes are snapshotted."""
    global _pending_settings
    from . import settings

    _pending_settings = settings.current()
    try:
        return _run(action, affects_drawings=affects_drawings)
    finally:
        _pending_settings = None


def _begin() -> None:
    """Open the transaction of one undo step (`_run`, and the console's `edit()`)."""
    if _inconsistent:
        raise RuntimeError(INCONSISTENT)
    _model.begin_transaction()


def _follow_ups(count, geo_changed, geo_removed) -> tuple:
    # Follow-ups inside the same undo step (e.g. rooms re-fitted to walls that moved, Slice 18).
    for hook in AFTER_ACTION:
        geo_changed = list(geo_changed) + list(hook(list(geo_changed), list(geo_removed)) or ())
    return (count, geo_changed, geo_removed)


def _end_step_without_change() -> None:
    """Close a step whose transaction changed nothing and drop it from the history, so a run that made no
    change leaves no empty undo step (D92)."""
    _model.end_transaction()
    _model.undo()
    _model.future.pop()


def _abort(failure: BaseException) -> None:
    """Roll back a half-applied step so the model and the history stay as they were. The caller re-raises."""
    global _base_id, _base_drawing_id, _inconsistent, _pending_settings
    if _pending_settings is not None:  # D92: a settings change rolled back with its step
        from . import settings

        settings.restore(_pending_settings)
        _pending_settings = None
    _model.end_transaction()
    try:
        _model.undo()
        _model.future.pop()
    except Exception:
        # ifcopenshell could not undo the partial transaction: say so, never carry on silently.
        _inconsistent = True
        _ids.clear()
        _future_ids.clear()
        _deltas.clear()
        _future_deltas.clear()
        _drawing_ids.clear()
        _future_drawing_ids.clear()
        _settings_before.clear()
        _future_settings_before.clear()
        _model.history.clear()
        _model.future.clear()
        _base_id = -1  # differs from any saved state: the model counts as changed
        _base_drawing_id = -1
        raise RuntimeError(INCONSISTENT) from failure


def _commit(count, geo_changed, geo_removed, affects_drawings: bool = True) -> dict:
    """Close the step's transaction and record it in the undo history."""
    global _next_id, _base_id, _base_drawing_id, _pending_settings
    _model.end_transaction()
    _ids.append(_next_id)
    _deltas.append(list(dict.fromkeys([*geo_changed, *geo_removed])))
    _drawing_ids.append(_drawing_rev() + (1 if affects_drawings else 0))
    _settings_before.append(_pending_settings)  # D92: a settings change undone with its step
    _pending_settings = None
    _next_id += 1
    _future_ids.clear()
    _future_deltas.clear()
    _future_drawing_ids.clear()
    _future_settings_before.clear()
    while len(_ids) > len(_model.history):  # ifcopenshell dropped its oldest transaction
        _base_id = _ids.pop(0)
        _deltas.pop(0)
        _base_drawing_id = _drawing_ids.pop(0)
        _settings_before.pop(0)
    geometry = {"changed": list(dict.fromkeys(geo_changed)), "removed": list(dict.fromkeys(geo_removed))}
    return {"ok": True, "changed": count, "geometry": geometry}


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


def _pset_users(pset) -> list:
    """The objects a property set is attached to. The inverse is DefinesOccurrence in IFC4 and
    PropertyDefinitionOf in IFC2X3 (imported Revit files)."""
    rels = pset.DefinesOccurrence if hasattr(pset, "DefinesOccurrence") else getattr(pset, "PropertyDefinitionOf", ())
    return [o for rel in rels or () for o in rel.RelatedObjects]


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


def _type_of(e):
    import ifcopenshell.util.element

    return ifcopenshell.util.element.get_type(e)


def _type_pset(t, pset: str):
    """The type object's own property set entity with this name, or None."""
    for d in getattr(t, "HasPropertySets", None) or ():
        if d.is_a("IfcPropertySet") and d.Name == pset:
            return d
    return None


def _type_property(t, pset: str, prop: str):
    ps = _type_pset(t, pset) if t is not None else None
    for p in (ps.HasProperties if ps else ()):
        if p.Name == prop:
            return p
    return None


def _value_type(p, fallback: str) -> str:
    return p.NominalValue.is_a() if p is not None and getattr(p, "NominalValue", None) else fallback


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


def _selected_types(elements) -> tuple[list, int]:
    """Distinct types of the elements (first-seen order) and how many elements have no type."""
    types, untyped = [], 0
    for e in elements:
        t = _type_of(e)
        if t is None:
            untyped += 1
        elif t not in types:
            types.append(t)
    return types, untyped


def _type_usage(types, pset: str, prop: str) -> dict:
    import ifcopenshell.util.element

    out, elements = [], 0
    for t in types:
        occurrences = ifcopenshell.util.element.get_types(t)
        out.append({"guid": t.GlobalId, "name": t.Name or t.is_a(), "count": len(occurrences)})
        # An element's own value overrides the type's, so overridden elements will not change.
        elements += sum(1 for o in occurrences if _own_property(o, pset, prop) is None)
    return {"types": out, "elements": elements}


def type_usage(guids_json: str, pset: str, prop: str) -> str:
    """Which types a type edit of pset/prop would change, and how many elements would show it."""
    if _model is None:
        return _dump({"error": "no model open"})
    types, untyped = _selected_types(_elements(guids_json))
    return _dump({**_type_usage(types, pset, prop), "untyped": untyped})


def set_type_property(guids_json: str, pset: str, prop: str, value_json: str) -> str:
    """Set pset/prop on the TYPES of the selected elements (every element of those types inherits it)."""
    import ifcopenshell.api.pset

    if _model is None:
        return _dump({"ok": False, "error": "no model open"})
    types, _ = _selected_types(_elements(guids_json))
    if not types:
        return _dump({"ok": False, "error": "the selected elements have no type"})
    try:
        value = json.loads(value_json)
        fallback = _template_type(pset, prop) or _infer_type(value)
        plan = []
        for t in types:
            ifc_type = _value_type(_type_property(t, pset, prop), fallback)
            plan.append((t, ifc_type, _convert(value, ifc_type)))
    except ValueError as ex:
        return _dump({"ok": False, "error": str(ex)})
    usage = _type_usage(types, pset, prop)

    def action():
        for t, ifc_type, converted in plan:
            ps = _type_pset(t, pset) or ifcopenshell.api.pset.add_pset(_model, product=t, name=pset)
            ifcopenshell.api.pset.edit_pset(_model, pset=ps, properties={prop: _model.create_entity(ifc_type, converted)})
        return len(plan)

    try:
        r = _run(action)
    except Exception as ex:
        return _dump({"ok": False, "error": f"{type(ex).__name__}: {ex}"})
    return _dump({**r, "types": len(plan), "elements": usage["elements"]})


def reset_to_type(guids_json: str, pset: str, prop: str) -> str:
    """Remove the elements' own value where their type defines pset/prop, so the type value shows again."""
    import ifcopenshell.api.pset

    if _model is None:
        return _dump({"ok": False, "error": "no model open"})
    targets = [
        e for e in _elements(guids_json)
        if _own_property(e, pset, prop) is not None and _type_property(_type_of(e), pset, prop) is not None
    ]

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
    from . import settings

    before = _settings_before[-1]
    after = settings.current() if before is not None else None  # D92: for redo
    _model.undo()
    _future_ids.append(_ids.pop())
    _future_deltas.append(_deltas.pop())
    _future_drawing_ids.append(_drawing_ids.pop())
    _future_settings_before.append(after)
    _settings_before.pop()
    if before is not None:
        settings.restore(before)
    return _dump({"ok": True, **_flags(), "geometry": _geometry_now(_future_deltas[-1])})


def redo() -> str:
    if _model is None or not _future_ids:
        return _dump({"ok": False, "error": "nothing to redo", **(_flags() if _model else {})})
    from . import settings

    after = _future_settings_before[-1]
    before = settings.current() if after is not None else None
    _model.redo()
    _ids.append(_future_ids.pop())
    _deltas.append(_future_deltas.pop())
    _drawing_ids.append(_future_drawing_ids.pop())
    _settings_before.append(before)
    _future_settings_before.pop()
    if after is not None:
        settings.restore(after)
    return _dump({"ok": True, **_flags(), "geometry": _geometry_now(_deltas[-1])})


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
SUMMARY_PARAMETERS = 6  # D100: the Parameters summary shows the first few; Edit... has them all


def _element_values(e) -> dict:
    """{pset: {prop: (value, ifc_type, editable, source, type_value)}}: type-level values first, the
    element's own override them. source: "type", "element" or "override" (own value over a type value)."""
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

        def put(name, value, ifc_type, editable):
            if not own:
                props[name] = (value, ifc_type, editable, "type", value)
            elif name in props and props[name][3] == "type":
                props[name] = (value, ifc_type, editable, "override", props[name][0])
            else:
                props[name] = (value, ifc_type, editable, "element", None)

        if d.is_a("IfcPropertySet"):
            for p in d.HasProperties:
                if p.is_a("IfcPropertySingleValue"):
                    v = p.NominalValue
                    put(p.Name, v.wrappedValue if v is not None else None, v.is_a() if v is not None else None, True)
                else:
                    put(p.Name, p.is_a(), p.is_a(), False)  # lists/tables/enums: shown, not editable yet
        elif d.is_a("IfcElementQuantity"):
            for q in d.Quantities:
                value = next((x for k, x in q.get_info(recursive=False).items() if k.endswith("Value")), None)
                put(q.Name, value, q.is_a(), False)  # quantities are computed, not typed in
    return out


def _shared_type_value(present: list, total: int):
    """The type-level value when every selected element inherits the same one, else None."""
    values = [x[4] for x in present]
    if len(present) != total or any(x[3] == "element" for x in present) or any(v != values[0] for v in values):
        return None
    return values[0]


def properties_multi(guids_json: str) -> str:
    if _model is None:
        return _dump({"error": "no model open"})
    from . import stairs

    elements = stairs.drop_parts(_elements(guids_json))  # D88: a stair stands for its flights and landings
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
                "source": present[0][3] if all(x[3] == present[0][3] for x in present) else "mixed",
                "type_value": _shared_type_value(present, len(entries)),
            }
        psets[pset] = props
    # Dimensions (owner feedback): live from the model, editable through set_dimension.
    from . import authoring

    per_dims = [{name: (value, editable) for name, value, editable in authoring.element_dimensions(e)} for e in elements]
    dim_names = [name for name, _, _ in authoring.element_dimensions(elements[0])]
    for d in per_dims[1:]:
        dim_names += [k for k in d if k not in dim_names]
    if dim_names:
        group = {}
        for name in dim_names:
            present = [d[name] for d in per_dims if name in d]
            values = [round(v, 6) for v, _ in present]
            varies = len(present) != len(per_dims) or any(v != values[0] for v in values)
            group[name] = {"value": None if varies else values[0], "varies": varies, "ifc_type": "IfcLengthMeasure",
                           "editable": all(ed for _, ed in present), "source": "dimension", "type_value": None}
        psets = {authoring.DIMENSIONS: group, **psets}
    # D86/D100: a library object's parameters: a read-only summary (its type, then the first visible
    # parameters); Edit... opens the Object settings dialog, for a selection of one type.
    from . import library

    per_params = library.parameters_of(elements)
    object_settings = None
    if all(p is not None for p in per_params):
        import ifcopenshell.util.element

        types = [ifcopenshell.util.element.get_type(e) for e in elements]
        one_type = all(t == types[0] for t in types)
        object_settings = {"enabled": one_type}
        ifc_types = {"length": "IfcLengthMeasure", "angle": "IfcPlaneAngleMeasure", "count": "IfcInteger",
                     "bool": "IfcBoolean", "choice": "IfcLabel", "material": "IfcLabel"}
        group = {"Type": {"value": (types[0].Name or "") if one_type else None, "varies": not one_type,
                          "ifc_type": "IfcLabel", "editable": False, "source": "parameter", "type_value": None}}
        for row in per_params[0][:SUMMARY_PARAMETERS]:  # D99: the visible parameters of the first, by label
            label = row["label"]
            present = [next((r["value"] for r in rows if r["label"] == label), _MISSING) for rows in per_params]
            varies = any(v is _MISSING or v != present[0] for v in present)
            row_name, n = label, 2
            while row_name in group:  # a parameter labelled "Type" (or twice the same label): its own row
                row_name, n = f"{label} ({n})", n + 1
            group[row_name] = {"value": None if varies else present[0], "varies": varies,
                            "ifc_type": ifc_types[row["kind"]], "editable": False, "source": "parameter",
                            "type_value": None}
        psets = {**{k: v for k, v in psets.items() if k == authoring.DIMENSIONS}, library.PARAMETERS: group,
                 **{k: v for k, v in psets.items() if k != authoring.DIMENSIONS}}
    outdated = len(library._outdated(elements))  # D99: objects whose library definition changed
    from . import renovation

    statuses = [renovation.status_of(e) for e in elements if not e.is_a("IfcAnnotation")]
    status = {"value": statuses[0] if statuses and len(set(statuses)) == 1 else None, "varies": len(set(statuses)) > 1}
    names = [e.Name or "" for e in elements]
    same_name = all(n == names[0] for n in names)
    # Sections and elevations: a small, friendly group for their path and cut plane. The raw
    # KIMBIM_Drawing properties stay too (they are IFC data), but these edit through the drawing's
    # own operations, so the placement and the generated drawing follow.
    settings = []
    if elements and all(e.is_a("IfcAnnotation") and e.ObjectType == "DRAWING" for e in elements):
        from . import drawgen as _drawgen

        settings = [_drawgen.settings_of(e) for e in elements]
    if settings and all(s is not None and s.get("kind") != "plan" for s in settings):
        def shared(get, ifc_type, editable=True, source="drawing"):
            values = [get(s) for s in settings]
            varies = any(v != values[0] for v in values)
            return {"value": None if varies else values[0], "varies": varies, "ifc_type": ifc_type,
                    "editable": editable, "source": source, "type_value": None}

        def shape_of(s):
            if any(abs(b) > 1e-9 for b in s.get("bulges") or []):
                return "Curved"
            return "Bent" if len(s.get("points") or []) > 2 else "Straight"

        section = {
            "Tilt (°)": shared(lambda s: round(float(s.get("tilt", 0.0)), 6), "IfcPlaneAngleMeasure"),
            "Base (m)": shared(lambda s: round(float(s.get("base", 0.0)), 6), "IfcLengthMeasure"),
            "Depth (m)": shared(lambda s: -1.0 if s.get("depth") is None else float(s["depth"]),
                                "IfcLengthMeasure"),
            "Vertices": shared(lambda s: len(s.get("points") or []), "IfcInteger", editable=False),
            "Shape": shared(shape_of, "IfcLabel", editable=False),
        }
        psets = {"Section": section, **psets}
        raw = psets.get("KIMBIM_Drawing")
        if raw:  # the friendly group above stands for these
            for key in ("Path", "Bulges", "Tilt", "Base", "Depth"):
                raw.pop(key, None)
    payload = {
        "count": len(elements),
        "guids": [e.GlobalId for e in elements],
        "types": sorted({e.is_a() for e in elements}),
        "name": {"value": names[0] if same_name else None, "varies": not same_name},
        "status": status,
        "material": _materials.merged(elements),  # D96: the Material row (None: not shown)
        "classifications": _classifications.summary_for(elements),
        "psets": _with_settings(psets, elements),
    }
    if outdated:
        payload["library_update"] = outdated
    if object_settings is not None:
        payload["object_settings"] = object_settings
    return _dump(payload)


def _with_settings(psets: dict, elements) -> dict:
    """D97: the Geometry and Surfaces groups go after Dimensions (and an object's Parameters)."""
    from . import authoring, library

    first = {k: v for k, v in psets.items() if k in (authoring.DIMENSIONS, library.PARAMETERS)}
    return {**first, **_configure.groups(elements), **{k: v for k, v in psets.items() if k not in first}}


def _write_occlusion_model(path: str) -> str:
    """A 4 m wall in front of a 1 m wall that it hides completely in the default view (Slice 4b
    visible-only box selection self-test). Leaves no model open."""
    global _model
    from . import authoring

    authoring.new_project("Occlusion")
    level = json.loads(authoring.storeys())["storeys"][0]["guid"]
    wall_type = json.loads(authoring.wall_types())["types"][0]["guid"]
    authoring.create_wall(level, wall_type, -4, 0, 8, 0, 4.0)
    authoring.create_wall(level, wall_type, 1, 2, 2, 2, 1.0)
    _model.write(path)
    _model = None
    _reset_history("")
    return _dump({"ok": True, "path": path})


def _write_unmarked_model(path: str) -> str:
    """Two walls with no renovation status, as a survey from another tool (D74 self-test). Leaves no
    model open."""
    import ifcopenshell.api.root

    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="Survey")
    for _ in range(2):
        ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall")
    f.write(path)
    return _dump({"ok": True, "path": path})


def count_entities(ifc_class: str) -> str:
    """Number of entities of a class (self-test reports)."""
    return _dump({"count": len(_model.by_type(ifc_class)) if _model is not None else 0})


def _write_test_model(path: str) -> str:
    """Write a small model (2 walls of type "Basic Wall 200" on one storey) for the app's C++ tests and self-test."""
    from .testing import build_model

    import ifcopenshell.api.pset
    import ifcopenshell.api.root
    import ifcopenshell.api.type

    f = build_model(walls=2)
    wall_type = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWallType", name="Basic Wall 200")
    ps = ifcopenshell.api.pset.add_pset(f, product=wall_type, name="Pset_WallCommon")
    u = f.createIfcThermalTransmittanceMeasure(0.35)
    ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"ThermalTransmittance": u})
    ifcopenshell.api.type.assign_type(f, related_objects=f.by_type("IfcWall"), relating_type=wall_type)
    f.write(path)
    return _dump({"ok": True, "path": path})


# The app calls this module, so the feature modules' bridge functions are re-exported here. Those
# modules import this one (their `B`), so the names resolve lazily (PEP 562 module __getattr__):
# importing any kimbim module first never meets a half-initialized one. The modules are still
# imported eagerly, so their AFTER_ACTION hooks register as before.
from . import authoring as _authoring  # noqa: E402
from . import versioning as _versioning  # noqa: E402
from . import layers as _layers  # noqa: E402
from . import annotations as _annotations  # noqa: E402
from . import drawings as _drawings  # noqa: E402
from . import sheets as _sheets  # noqa: E402
from . import editing as _editing  # noqa: E402
from . import modify as _modify  # noqa: E402
from . import rooms as _rooms  # noqa: E402
from . import roofs as _roofs  # noqa: E402
from . import settings as _settings  # noqa: E402
from . import queries as _queries  # noqa: E402
from . import levels as _levels  # noqa: E402
from . import checks as _checks  # noqa: E402
from . import renovation as _renovation  # noqa: E402
from . import graphics as _graphics  # noqa: E402
from . import schedules as _schedules  # noqa: E402
from . import documents as _documents  # noqa: E402
from . import console as _console  # noqa: E402
from . import library as _library  # noqa: E402
from . import objversions as _objversions  # noqa: E402
from . import objedit as _objedit  # noqa: E402
from . import drafting as _drafting  # noqa: E402
from . import underlays as _underlays  # noqa: E402
from . import symbols as _symbols  # noqa: E402
from . import tags as _tags  # noqa: E402
from . import stairs as _stairs  # noqa: E402
from . import showon as _showon  # noqa: E402
from . import materials as _materials  # noqa: E402
from . import configure as _configure  # noqa: E402
from . import curved_walls as _curved_walls  # noqa: E402
from . import sun as _sun  # noqa: E402
from . import worksheets as _worksheets  # noqa: E402
from . import classifications as _classifications  # noqa: E402
from . import typemanager as _typemanager  # noqa: E402
_EXPORTS = {
    "authoring": (
        "add_grid_axis",
        "add_grid_system",
        "add_slab_opening",
        "add_storey",
        "beam_types",
        "column_types",
        "copy_to_storey",
        "create_model",
        "explode_instance",
        "instance_members",
        "model_elements",
        "models",
        "place_model",
        "update_model_instances",
        "create_beam",
        "create_column",
        "create_curtain_wall",
        "curtain_wall_info",
        "add_slab_edge",
        "set_slab_slope",
        "slab_slope",
        "create_slab",
        "create_wall",
        "delete_elements",
        "edit_opening",
        "insert_opening",
        "move_elements",
        "new_project",
        "opening_types",
        "rotate_elements",
        "set_wall_axis",
        "set_dimension",
        "set_wall_height",
        "slide_openings",
        "slab_outline_from_walls",
        "slab_types",
        "snap_data",
        "storeys",
        "wall_types",
    ),
    "versioning": (
        "before_after",
        "combine_options",
        "combine_preview",
        "compare",
        "diff_details",
        "create_milestone",
        "create_option",
        "delete_milestone",
        "delete_option",
        "discard_changes",
        "element_history",
        "milestones",
        "enable_versioning",
        "history",
        "open_project",
        "options",
        "project_state",
        "save_version",
        "switch_option",
        "version_changes",
        "version_checks",
        "remotes",
        "add_remote",
        "remove_remote",
        "push",
        "pull",
    ),
    "layers": (
        "assign_layer",
        "create_layer",
        "delete_layer",
        "delete_view",
        "layer_members",
        "layers",
        "rename_layer",
        "save_view",
        "set_active_layer",
        "views",
    ),
    "annotations": (
        "add_annotation",
        "auto_dimension",
        "annotations",
        "set_annotation_pen",
        "set_annotation_size",
        "set_annotation_text",
    ),
    "drawings": (
        "create_drawings",
        "create_elevation",
        "create_elevations",
        "create_plan",
        "create_section",
        "delete_drawing",
        "drawings",
        "drawing_bounds",
        "generate_drawing",
        "generate_plan_drawing",
        "generate_view_drawing",
        "rename_drawing",
        "set_drawing_depth",
        "set_drawing_hlr",
        "set_drawing_timeout",
        "set_view_depth",
    ),
    "sheets": (
        "add_sheet",
        "delete_sheet",
        "edit_sheet",
        "export_sheet_svg",
        "move_placed",
        "place_drawing",
        "project_info",
        "remove_placed",
        "set_placed_scale",
        "set_project_info",
        "set_sheet_purpose",
        "sheet_svg",
        "sheets",
        "update_placed",
        "update_sheet",
        "place_legend",
        "move_legend",
        "remove_legend",
        "move_title_block",
        "set_title_block",
        "place_sheet_image",
        "place_sheet_symbol",
        "move_sheet_symbol",
        "set_sheet_symbol",
        "remove_sheet_symbol",
    ),
    "editing": (
        "array_elements",
        "copy_elements",
        "duplicate_elements",
        "fillet_corners",
        "mirror_elements",
        "resize_elements",
        "offset_elements",
        "set_slab_outline",
        "slab_outline",
        "slab_outlines",
    ),
    "modify": (
        "join_elements",
        "modify_targets",
        "split_element",
        "trim_corner",
        "trim_extend",
        "unjoin_elements",
    ),
    "rooms": (
        "create_room",
        "edit_room",
        "export_room_schedule",
        "room_schedule",
        "rooms",
    ),
    "roofs": (
        "attach_walls_to_roof",
        "create_roof",
        "detach_walls_from_roof",
        "roof_info",
    ),
    "settings": (
        "load_settings_file",
        "project_settings",
        "set_project_settings",
    ),
    "queries": (
        "find_elements",
        "query_choices",
        "selection_set_members",
        "similar_elements",
    ),
    "levels": (
        "delete_storey",
        "edit_storeys",
        "insert_storey",
        "levels_table",
        "rename_storey",
        "set_storey_elevation",
        "set_storey_shown",
    ),
    "showon": (
        "set_element_view_depth",
        "set_show_on",
        "visible_on",
    ),
    "checks": (
        "_write_sample_house",
        "cancel_checks",
        "export_ids_report",
        "read_ids_file",
        "run_check",
    ),
    "renovation": (
        "mark_unmarked",
        "set_status",
        "set_status_for_new",
        "unmarked",
    ),
    "graphics": (
        "graphics_state",
        "graphics_tables",
        "set_current_pen",
        "set_graphics",
        "set_purpose",
    ),
    "schedules": (
        "delete_schedule_scheme",
        "export_schedule",
        "save_schedule_scheme",
        "schedule",
        "schedule_classes",
        "schedule_fields",
        "schedule_schemes",
        "set_schedule_value",
    ),
    "documents": (
        "clear_recovery",
        "close_document",
        "discard_recovery",
        "document_state",
        "export_ifc",
        "import_ifc",
        "kim_beside",
        "new_from_template",
        "open_folder",
        "open_kim",
        "recover",
        "recoveries",
        "save_as_folder",
        "save_as_ifc",
        "save_as_kim",
        "save_document",
        "save_template",
        "set_app_paths",
        "set_author",
        "templates",
        "write_recovery",
    ),
    "drafting": (
        "add_drafting",
        "fill_at",
        "fill_from_shape",
        "fill_patterns",
        "set_annotation_points",
        "set_drafting_style",
    ),
    "symbols": (
        "add_symbol",
        "get_true_north",
        "set_true_north",
    ),
    "tags": (
        "add_tag",
        "delete_tag_style",
        "save_tag_style",
        "set_tag",
        "tag_all",
        "tag_styles",
        "tag_target",
    ),
    "console": (
        "console_help",
        "console_run",
        "console_run_file",
        "console_stop",
    ),
    "stairs": (
        "add_stair_railings",
        "assembly_members",
        "create_railing",
        "create_ramp",
        "create_stair",
        "set_stair_params",
        "stair_at",
        "stair_info",
        "stair_preview",
        "stair_symbols",
    ),
    "underlays": (
        "add_underlay",
        "place_figure",
        "remove_underlay",
        "set_underlay",
        "trace_lines",
        "underlay_lines",
        "underlay_probe",
        "underlay_raster",
        "underlays",
    ),
    "classifications": (
        "add_reference",
        "assign_classification",
        "create_system",
        "of_element",
        "remove_reference",
        "systems",
        "unassign_classification",
    ),
    "typemanager": (
        "assign_type",
        "create_type",
        "edit_type",
        "list_types",
        "type_details",
        "type_of",
        "update_type_all",
    ),
    "worksheets": (
        "create_worksheet",
        "delete_worksheet",
        "rename_worksheet",
        "worksheets",
    ),
    "curved_walls": ("create_curved_wall",),
    "sun": ("sun_state",),
    "configure": (
        "flip_walls",
        "inject",
        "pick_up",
        "save_wall_profile",
        "set_junctions",
        "set_element_setting",
        "wall_options",
    ),
    "materials": (
        "add_standard_materials",
        "apply_materials",
        "assign_material",
        "element_material",
        "materials_state",
        "place_picture_3d",
        "purge_materials",
    ),
    "library": (
        "library_objects",
        "library_updates",
        "object_form",
        "object_preview",
        "object_preview_error",
        "object_symbol",
        "place_object",
        "set_library_paths",
        "set_object_parameter",
        "set_plan_display",
        "update_from_library",
    ),
    "objedit": (
        "check_draft",
        "draft_form",
        "draft_preview",
        "draft_preview_error",
        "draft_symbol",
        "object_draft",
        "object_part_template",
        "object_symbol_template",
        "save_draft",
    ),
    "objversions": (
        "apply_object_settings",
        "assign_version",
        "delete_version",
        "move_version_to_library",
        "object_settings_of",
        "object_versions",
        "rename_version",
        "save_object_version",
        "set_last_used",
    ),
}
# D102 phase 2: the live session and the review bar (named apart from the catalogue's bare verbs).
def agent_live_start() -> str:
    from .agent import live; return live.start()


def agent_live_stop() -> str:
    from .agent import live; return live.stop()


def agent_live_status() -> str:
    from .agent import live; return live.status()


def agent_live_pending() -> str:
    from .agent import live; return live.pending()


def agent_live_run(request_id: str = "") -> str:
    from .agent import live; return live.run(request_id)


def agent_live_set_selection(guids_json: str = "[]") -> str:
    from .agent import live; return live.set_selection(guids_json)


def agent_proposals() -> str:
    from .agent import live; return live.proposals()


def agent_proposal(task_id: str) -> str:
    from .agent import live; return live.proposal(task_id)


def agent_accept(task_id: str, resolutions_json: str = "{}") -> str:
    from .agent import live; return live.accept(task_id, resolutions_json)


def agent_reject(task_id: str) -> str:
    from .agent import live; return live.reject(task_id)


def assistant_chat(messages_json: str, config_json: str) -> str:
    from .agent import assistant

    return assistant.chat(messages_json, config_json)


def assistant_begin() -> str:
    from .agent import assistant

    return assistant.begin()


def assistant_progress(turn: str = "0", since: str = "0") -> str:
    from .agent import assistant

    return assistant.progress(int(turn or 0), int(since or 0))


def assistant_set_key(provider: str, key: str) -> str:
    from .agent import assistant

    return assistant.set_key(provider, key)


def assistant_clear_key(provider: str) -> str:
    from .agent import assistant

    return assistant.clear_key(provider)


def assistant_key_set(provider: str) -> str:
    from .agent import assistant

    return assistant.key_set(provider)


def agent_connect_info(client: str, project: str = "") -> str:
    """The configuration or command for `kimbim setup <client> --print` (Help › Connect an AI agent)."""
    from .agent import clients

    try:
        text, _ = clients.setup(client, project or None, True)
    except (clients.SetupError, OSError) as ex:
        return _dump({"ok": False, "error": str(ex)})
    return _dump({"ok": True, "text": text})


_EXPORTED = {name: module for module, names in _EXPORTS.items() for name in names}
del annotations  # `from __future__ import annotations` bound it; the bridge function resolves lazily


def __getattr__(name: str):
    module = _EXPORTED.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(globals()["_" + module], name)
    globals()[name] = value  # later lookups skip this function
    return value


def __dir__():
    return sorted({*globals(), *_EXPORTED})


# DXF export (D83): ezdxf takes most of a second to import, so kimbim.dxf loads on the first export.
def dxf_targets() -> str:
    from . import dxf

    return dxf.dxf_targets()


def export_drawing_dxf(guid: str, path: str, options_json: str = "") -> str:
    from . import dxf

    return dxf.export_drawing_dxf(guid, path, options_json)


def export_sheet_dxf(number: str, path: str, options_json: str = "") -> str:
    from . import dxf

    return dxf.export_sheet_dxf(number, path, options_json)


def export_dxf(items_json: str, folder: str, options_json: str = "") -> str:
    from . import dxf

    return dxf.export_dxf(items_json, folder, options_json)


def export_drawing_dwg(guid: str, path: str, options_json: str = "") -> str:
    from . import dxf

    return dxf.export_drawing_dwg(guid, path, options_json)


def export_sheet_dwg(number: str, path: str, options_json: str = "") -> str:
    from . import dxf

    return dxf.export_sheet_dwg(number, path, options_json)


def export_dwg(items_json: str, folder: str, options_json: str = "") -> str:
    from . import dxf

    return dxf.export_dwg(items_json, folder, options_json)


def dwg_available() -> str:
    from . import dwg

    return _dump({"ok": True, "available": dwg.available(), "to_dxf": dwg.to_dxf_tool() or "",
                  "from_dxf": dwg.from_dxf_tool() or "", "error": "" if dwg.available() else dwg.error()})
