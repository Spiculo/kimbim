# SPDX-License-Identifier: GPL-3.0-or-later
"""The Object Editor's drafts (D101, doc 16 §6): the Python side of the dialog that makes library objects.

The draft protocol. A draft is the object's `.kimobj` JSON as text, held by the dialog; every function
here takes it as a string and answers JSON (the bridge protocol: strings in, JSON out, never raising,
failures as {"ok": false, "error": ...}). A draft is never registered: nothing here touches
library.OBJECTS, library._office or the open model (the preview builds in a scratch model).
- `object_draft(source)`: the draft to start from, "new", a library id, "office:<id>", "project:<id>" or
  "type:<GlobalId>" (Customise a copy).
- `check_draft(draft)`: every problem with its field path: formula syntax everywhere first, then what the
  real loader says (structure, names, limits, a build at the defaults).
- `draft_form`, `draft_symbol`, `draft_preview`, `draft_preview_error`: the Library's object_form,
  object_symbol, object_preview and object_preview_error for the draft, at the dialog's trial values.
- `object_part_template(shape)`: a part to add that builds as it is.
- `save_draft(draft, target, replace)`: the draft kept in the office library (a `.kimobj` file; with the
  count and GUIDs of this object's placements it left outdated) or in the project (its types, one undo step)."""
from __future__ import annotations

import copy
import json
import os
import uuid

from . import library, objbuild, objects
from .objbuild import ObjectError
from .objexpr import FormulaError, compile_formula

_NEW = {
    "format": objects.FORMAT, "id": "new_object", "name": {"en": "New object", "es": "Objeto nuevo"},
    "category": "furniture",
    "ifc": {"IFC4": ["IfcFurnitureType", "NOTDEFINED", None], "IFC2X3": ["IfcFurnitureType", None, None]},
    "params": [
        {"key": "width", "kind": "length", "label": {"en": "Width", "es": "Ancho"}, "default": 0.6},
        {"key": "depth", "kind": "length", "label": {"en": "Depth", "es": "Fondo"}, "default": 0.6},
        {"key": "height", "kind": "length", "label": {"en": "Height", "es": "Altura"}, "default": 0.75},
    ],
    "materials": {"body": {"label": {"en": "Material", "es": "Material"}, "default": "Timber - finish"}},
    "parts": [{"id": "body", "material": "body",
               "box": {"x": 0, "y": 0, "z": 0, "dx": "width", "dy": "depth", "dz": "height"}}],
}
_TEMPLATE_POINTS = {  # the point lists of the shapes that need them, as small valid solids
    "prism": [[0, 0], [0.1, 0], [0.1, 0.1]],
    "revolve": [[0.05, 0], [0.1, 0], [0.1, 0.1]],
    "sweep": [[0, 0, 0], [0, 0, 0.1]],
}


def _fail(message: str) -> str:
    from . import authoring

    return authoring._fail(message)


def _dump(data) -> str:
    from . import app_bridge as B

    return B._dump(data)


# ---------------------------------------------------------------- check: formula syntax

class _Syntax:
    """Walks a draft and compiles the strings the loader would evaluate as formulas (objbuild._num and
    _points, objects.ParamDef: min, max, show_when, a number-like default); the rest (ids, labels, slot
    names, `use`, `attach`, `on`, a choice default) is text and is left to the real load."""

    def __init__(self):
        self.errors: list = []
        self.names: set = set()  # what a formula in the scope being walked may name: its parameters, i, n, pi
        self.part_ids: set = set()  # parts of the scope: `seat.top.z` names an anchor of part `seat`

    def formula(self, v, path):
        if isinstance(v, str):
            try:
                f = compile_formula(v)
            except FormulaError as ex:
                self.errors.append({"path": path, "message": str(ex)})
                return
            for name in sorted(f.names):  # the loader's message for a name the scope does not have
                if name not in self.names and not ("." in name and name.split(".")[0] in self.part_ids):
                    self.errors.append({"path": path, "message": f"unknown name {name!r}"})
        elif isinstance(v, list | tuple):  # a list of numbers (at, step, a vector)
            for k, item in enumerate(v):
                self.formula(item, f"{path}[{k}]")

    def points(self, spec, path):
        if not isinstance(spec, list):
            return
        for k, item in enumerate(spec):
            if isinstance(item, dict):
                for key, v in item.items():  # n, a0, a1, ellipse, rounded_rect: all numbers
                    self.formula(v, f"{path}[{k}].{key}")
            else:
                self.formula(item, f"{path}[{k}]")

    def params(self, params, path):
        if not isinstance(params, list):
            return
        for k, p in enumerate(params):
            if not isinstance(p, dict):
                continue
            for f in ("min", "max", "show_when"):
                self.formula(p.get(f), f"{path}[{k}].{f}")
            if p.get("kind") not in ("choice", "material"):
                self.formula(p.get("default"), f"{path}[{k}].default")

    def parts(self, parts, path):
        if not isinstance(parts, list):
            return
        for k, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            w = f"{path}.{part['id']}" if isinstance(part.get("id"), str) else f"{path}[{k}]"
            self.formula(part.get("when"), f"{w}.when")
            self.formula(part.get("at"), f"{w}.at")
            rot = part.get("rotate")
            if isinstance(rot, dict):
                self.formula(rot.get("angle"), f"{w}.rotate.angle")
                if not isinstance(rot.get("axis"), str):
                    self.formula(rot.get("axis"), f"{w}.rotate.axis")
            rep = part.get("repeat")
            if isinstance(rep, dict):
                self.formula(rep.get("count"), f"{w}.repeat.count")
                if "on" not in rep:  # a repeat on a pattern takes its frames from the pattern
                    self.formula(rep.get("step"), f"{w}.repeat.step")
                    self.formula(rep.get("turn"), f"{w}.repeat.turn")
            if isinstance(part.get("with"), dict):
                for key, v in part["with"].items():
                    self.formula(v, f"{w}.with.{key}")
            for kind in objbuild.SHAPES:
                fields = part.get(kind)
                if isinstance(fields, dict):
                    for f, v in fields.items():
                        (self.points if f in objbuild._POINT_FIELDS else self.formula)(v, f"{w}.{kind}.{f}")
            if isinstance(part.get("anchors"), dict):
                for name, spec in part["anchors"].items():
                    if isinstance(spec, dict):
                        for f, v in spec.items():
                            if f != "pattern" and not (f == "dir" and isinstance(v, str)):
                                self.formula(v, f"{w}.anchors.{name}.{f}")

    def symbol(self, items, path="symbol"):
        if not isinstance(items, list):
            return
        for k, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            w = f"{path}[{k}]"
            self.formula(item.get("when"), f"{w}.when")
            if isinstance(item.get("repeat"), dict):
                self.formula(item["repeat"].get("count"), f"{w}.repeat.count")
            for kind in objbuild._SYMBOL_KINDS:
                fields = item.get(kind)
                if isinstance(fields, dict):
                    for f, v in fields.items():
                        (self.points if f == "points" else self.formula)(v, f"{w}.{kind}.{f}")

    def scope(self, params, parts, slots=()):
        self.names = {"i", "n", "pi", *(f"mat_{k}" for k in slots)}
        self.names |= {p["key"] for p in params or () if isinstance(p, dict) and isinstance(p.get("key"), str)}             if isinstance(params, list) else set()
        self.part_ids = {p["id"] for p in parts or () if isinstance(p, dict) and isinstance(p.get("id"), str)}             if isinstance(parts, list) else set()

    def draft(self, data):
        mats = data.get("materials")
        self.scope(data.get("params"), data.get("parts"), mats if isinstance(mats, dict) else ())
        self.params(data.get("params"), "params")
        self.parts(data.get("parts"), "parts")
        self.symbol(data.get("symbol"))
        if isinstance(data.get("components"), dict):
            for name, comp in data["components"].items():
                if isinstance(comp, dict):
                    self.scope(comp.get("params"), comp.get("parts"))  # a component sees its own parameters only
                    self.params(comp.get("params"), f"components.{name}.params")
                    self.parts(comp.get("parts"), f"components.{name}.parts")


def _split(text: str) -> tuple[str, str]:
    """An ObjectError's field path (the text before the first ': ', else none) and the rest."""
    path, sep, rest = text.partition(": ")
    return (path, rest) if sep else ("", text)


def _load(draft_json: str):
    """(definition, errors): the draft loaded with the library's own checks as a project object, or None
    and every problem found (syntax first, then the loader's)."""
    syntax = _Syntax()
    try:
        data = json.loads(draft_json)
        if isinstance(data, dict):
            syntax.draft(data)
    except ValueError as ex:
        return None, [{"path": "", "message": f"not JSON: {ex}"}]
    except Exception as ex:  # a hostile draft (nested past Python's recursion limit, say)
        return None, [{"path": "", "message": f"cannot read the draft: {type(ex).__name__}"}]
    errors = syntax.errors
    try:
        return objects.load(data, "project", check=True), errors
    except Exception as ex:  # an ObjectError, or whatever a hand-made draft's odd shapes raise
        path, message = _split(str(ex) if isinstance(ex, ObjectError | ValueError) else f"{type(ex).__name__}: {ex}")
        if not any(message.startswith(e["message"]) for e in errors):  # a formula error found above is not said twice
            errors.append({"path": path, "message": message})
        return None, errors


def check_draft(draft_json: str) -> str:
    _, errors = _load(draft_json)
    return _dump({"ok": not errors, "errors": errors})


# ---------------------------------------------------------------- the draft's views

def _draft_values(draft_json: str, values_json: str):
    """(definition, cleaned trial values) or ObjectError with the first problem."""
    obj, errors = _load(draft_json)
    if obj is None or errors:
        e = errors[0]
        raise ObjectError(f"{e['path']}: {e['message']}" if e["path"] else e["message"])
    return obj, obj.values(library._given(values_json))


def draft_form(draft_json: str, values_json: str = "") -> str:
    try:
        obj, values = _draft_values(draft_json, values_json)
        return _dump(library.form_json(obj, values))
    except ObjectError as ex:
        return _fail(str(ex))


def draft_symbol(draft_json: str, values_json: str = "") -> str:
    try:
        obj, values = _draft_values(draft_json, values_json)
        return _dump(library.symbol_json(obj, values))
    except ObjectError as ex:
        return _fail(str(ex))


def _preview_values(draft_json: str, values_json: str):
    """(definition, values) the preview builds: the trial values checked and applied like an edit."""
    obj, _ = _draft_values(draft_json, "")
    try:
        given = json.loads(values_json) if values_json else {}
    except ValueError as ex:
        raise ObjectError(f"bad input: {ex}") from None
    if not isinstance(given, dict):
        raise ObjectError("the values are an object {parameter: value}")
    return obj, library._edited_values(obj, obj.values(), given)


def draft_preview(draft_json: str, values_json: str = ""):
    """Mesh parts like library.object_preview, or None when the draft or values don't build."""
    try:
        obj, values = _preview_values(draft_json, values_json)
        return library._preview_meshes(obj, values)
    except Exception:  # whatever goes wrong, the dialog keeps its last preview
        return None


def draft_preview_error(draft_json: str, values_json: str = "") -> str:
    try:
        obj, values = _preview_values(draft_json, values_json)
        obj.shape(values)
    except (ObjectError, ValueError) as ex:
        return _fail(str(ex))
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return _dump({"ok": True})


# ---------------------------------------------------------------- opening a draft

def _taken_ids() -> set:
    """Object ids in use: bundled, office and project refs (the ids without their `office:` / `project:`)."""
    from . import app_bridge as B

    taken = {k.partition(":")[2] if ":" in k else k for k in (*library.OBJECTS, *library._office)}
    if B._model is not None:
        for t in library._library_types(B._model):
            info = library._params_of_type(t)
            if info is not None and info[0].startswith("project:"):
                taken.add(info[0].partition(":")[2])
    return taken


def _copy_of(data: dict, base_id: str) -> dict:
    """A copy to edit: a free id `<id>_copy`, `<id>_copy2`, ..., and the name marked as a copy."""
    taken, k = _taken_ids(), 1
    new_id = f"{base_id}_copy"
    while new_id in taken:
        k += 1
        new_id = f"{base_id}_copy{k}"
    name = data.get("name", base_id)
    en = name if isinstance(name, str) else name.get("en", base_id)
    es = name if isinstance(name, str) else name.get("es") or en
    return {**data, "id": new_id, "name": {"en": f"{en} (copy)", "es": f"{es} (copia)"}}


def _with_type_values(data: dict, values: dict) -> None:
    """Each parameter's default becomes the type's value (a choice only when it is one of the options)."""
    for p in data.get("params") or ():
        if p.get("key") in values:
            v = values[p["key"]]
            if p.get("kind") != "choice" or v in [o.get("id") for o in p.get("options") or ()]:
                p["default"] = v
    for slot, m in (data.get("materials") or {}).items():
        if values.get(f"mat_{slot}"):
            m["default"] = values[f"mat_{slot}"]


def object_draft(source: str) -> str:
    from . import objversions

    try:
        if source == "new":
            return _dump({"ok": True, "draft": copy.deepcopy(_NEW), "target": "", "copy": False})
        if source.startswith(objversions.TYPE_SOURCE):
            t = objversions.type_of_source(source)
            obj = library.definition_of_type(t) if t is not None else None
            if obj is None:
                return _fail(f"no placed object {source}")
            data = copy.deepcopy(obj.data)
            _with_type_values(data, library._params_of_type(t)[1])
            return _dump({"ok": True, "draft": _copy_of(data, obj.key), "target": "", "copy": True})
        if source.startswith(("office:", "project:")):
            obj = objversions._definition(source)
            if not isinstance(obj, objects.ObjectDef):
                return _fail(f"no editable library object {source}")
            return _dump({"ok": True, "draft": copy.deepcopy(obj.data), "copy": False,
                          "target": source.partition(":")[0]})
        obj = library.OBJECTS.get(source)
        if obj is None:
            return _fail(f"no library object {source}")
        return _dump({"ok": True, "draft": _copy_of(copy.deepcopy(obj.data), obj.key), "target": "", "copy": True})
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")


def object_part_template(shape: str) -> str:
    if shape == "use":
        return _dump({"ok": True, "part": {"id": "part", "use": ""}})
    if shape == "anchors":
        return _dump({"ok": True, "part": {"id": "part", "anchors": {}}})
    if shape not in objbuild.SHAPES:
        return _fail(f"unknown shape {shape!r}")
    required, _ = objbuild._FIELDS[shape]
    fields = {f: _TEMPLATE_POINTS.get(shape, 0.1) if f in objbuild._POINT_FIELDS else 0.1 for f in required}
    if shape == "sweep":
        fields["r"] = 0.05  # a sweep is a tube (r) or a profile
    return _dump({"ok": True, "part": {"id": "part", shape: fields}})


# ---------------------------------------------------------------- saving a draft

def _save_office(obj, draft_json: str, replace: str) -> str:
    folder = library._office_paths["folder"]
    if not folder:
        return _fail("no office library folder (Preferences › Office library)")
    ref = f"office:{obj.key}"
    path = os.path.join(folder, f"{obj.key}.kimobj")
    known = library._office.get(ref)  # an object loaded from a file with another name is replaced in place
    if isinstance(known, objects.ObjectDef) and known.library:
        path = known.library
    if (os.path.exists(path) or known is not None) and replace != obj.key:
        return _dump({"ok": False, "exists": obj.key})
    text = json.dumps(json.loads(draft_json), indent=2, ensure_ascii=False) + "\n"
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except OSError as ex:
        return _fail(f"cannot write {path}: {ex}")
    library.load_office(folder, library._office_paths["files"])
    from . import app_bridge as B

    placed = [e for e in B._model.by_type("IfcElement")
              if (found := library._object_of(e)) is not None and found[0].ref == ref] if B._model is not None else []
    outdated = library._outdated(placed)  # this object's placements only: the app offers to update them
    return _dump({"ok": True, "ref": ref, "path": path, "outdated": len(outdated),
                  "guids": [e.GlobalId for e, *_ in outdated]})


def _save_project(obj) -> str:
    from . import app_bridge as B
    from . import objversions

    if B._model is None:
        return _fail("no model open")
    types = [t for t in library._library_types(B._model)
             if (info := library._params_of_type(t)) is not None and info[0] == obj.ref]
    plans = []
    for t in types:  # every type must build before any changes
        old = library.definition_of_type(t) or obj
        values = library._kept_values(old, library._params_of_type(t)[1], obj)
        try:
            obj.shape(values)
        except (ObjectError, ValueError) as ex:
            return _fail(f"{t.Name}: {ex}")
        plans.append((t, values))

    def action():
        if not plans:  # kept in the project by a saved version named after the object
            objversions._write_version(library._make_type(obj, obj.values()), uuid.uuid4().hex, obj.name)
        for t, values in plans:
            library._regenerate_type(t, obj, values)
        return max(len(plans), 1), [], []

    try:
        B._run(action)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    return _dump({"ok": True, "ref": obj.ref, "types": max(len(plans), 1)})


def save_draft(draft_json: str, target: str, replace: str = "") -> str:
    try:
        obj, errors = _load(draft_json)
        if obj is None or errors:
            return _dump({"ok": False, "error": "the object has errors", "errors": errors})
        if target not in ("office", "project"):
            return _fail(f"unknown target {target!r}")
        if obj.key in library.OBJECTS:
            return _fail(f"{obj.key} is a bundled object: give the copy another id")
        return _save_office(obj, draft_json, replace) if target == "office" else _save_project(obj)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
