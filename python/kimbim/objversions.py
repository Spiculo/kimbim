# SPDX-License-Identifier: GPL-3.0-or-later
"""Saved versions of library objects (D100): named value sets of an object ("Dining chair", "Bar stool")
kept in the project, the project library.

A saved version is a D99 library type with two more fields in its KIMBIM_LibraryObject pset: VersionId
(a stable id, kept when the version is renamed or edited) and VersionName; the type's Name is the
version's name too, so schedules count its placements together. Unlike the unnamed types D99 makes per
value set, a saved version has its own identity:
- it stays in the project when nothing uses it;
- unsaved values never resolve to it, even identical ones (library._find_type skips it);
- two versions may hold identical values and stay separate types.

Everything a version needs is on its type (the definition text, D99), so a version of an object gone
from the library still lists, places and saves.

The last version used per object is the project setting `object_last_used`: {object ref: {"version":
id}} or {object ref: {"values": {...}}} (unsaved values).

Same protocol as app_bridge for the bridge functions (strings in, JSON out, never raise).
"""
from __future__ import annotations

import json
import uuid

from . import library, objects
from .objbuild import ObjectError

VERSION_ID = "VersionId"
VERSION_NAME = "VersionName"
NAME_LIMIT = 255  # an IfcLabel


def _pset(t) -> dict:
    import ifcopenshell.util.element

    return (ifcopenshell.util.element.get_pset(t, library.PSET) or {}) if t is not None else {}


def is_saved(t) -> bool:
    """Whether a type is a saved version (it has a VersionId)."""
    return bool(_pset(t).get(VERSION_ID))


def version_of(t) -> dict | None:
    """A saved version's listing, or None for any other type."""
    import ifcopenshell.util.element

    data = _pset(t)
    if not data.get(VERSION_ID):
        return None
    try:
        values = json.loads(data.get("Parameters") or "{}")
    except ValueError:
        values = {}
    return {"id": data[VERSION_ID], "name": data.get(VERSION_NAME) or t.Name or "", "object": data.get("Object") or "",
            "values": values if isinstance(values, dict) else {}, "type": t.GlobalId,
            "uses": len(ifcopenshell.util.element.get_types(t)), "source": "project", "office_id": None}


def _saved_types(ref: str | None = None) -> list:
    from . import app_bridge as B

    if B._model is None:
        return []
    return [t for t in library._library_types(B._model)
            if (data := _pset(t)).get(VERSION_ID) and (ref is None or data.get("Object") == ref)]


def project_versions(ref: str) -> list[dict]:
    """The project's saved versions of an object, by name."""
    return sorted((version_of(t) for t in _saved_types(ref)), key=lambda v: (v["name"].casefold(), v["id"]))


def find_version(version_id: str):
    """The project type of a saved version, or None."""
    if not version_id:
        return None
    return next((t for t in _saved_types() if _pset(t).get(VERSION_ID) == version_id), None)


def _definition(key: str):
    """The definition to build versions of `key`: the library's, else the one stored on a project type
    of that object (its object is gone from the library: the project still has it, D99)."""
    obj = library.get(key)
    if isinstance(obj, objects.ObjectDef):
        return obj
    if obj is not None:
        return None  # an office IFC type: fixed geometry, no parameters to save
    from . import app_bridge as B

    if B._model is None:
        return None
    for t in sorted(_saved_types(key), key=lambda t: t.id()) + library._library_types(B._model):
        info = library._params_of_type(t)
        if info is not None and info[0] == key and (d := library.definition_of_type(t)) is not None:
            return d
    return None


def _clean_name(name) -> tuple[str, str | None]:
    """(stripped name, error or None)."""
    text = str(name or "").strip()
    if not text:
        return text, "a version needs a name"
    if len(text) > NAME_LIMIT:
        return text, f"a version name has at most {NAME_LIMIT} characters"
    return text, None


def _clash(ref: str, name: str, other_than: str = "") -> dict | None:
    """The version of `ref` called `name` (case-insensitive), other than `other_than`, or None."""
    return next((v for v in project_versions(ref) if v["name"].casefold() == name.casefold() and v["id"] != other_than), None)


def _write_version(t, version_id: str, name: str) -> None:
    import ifcopenshell.api.pset

    f = t.file
    ifcopenshell.api.pset.edit_pset(f, pset=library._pset_of(t), properties={
        VERSION_ID: f.createIfcIdentifier(version_id), VERSION_NAME: f.createIfcLabel(name)})
    t.Name = name


# ---------------------------------------------------------------- bridge

def object_versions(key: str) -> str:
    """The dialog's versions list for an object: its default values, the project's saved versions, and
    the last one used (`object_last_used`)."""
    from . import app_bridge as B
    from . import authoring as A
    from . import settings

    obj = _definition(key)
    if obj is None:
        return A._fail(f"no library object {key}")
    last = settings.current().get("object_last_used", {}).get(key, {})
    return B._dump({"ok": True, "default": obj.values(), "versions": project_versions(key), "last": last})


def save_object_version(key: str, name: str, params_json: str, replace: str = "") -> str:
    """Save these values of an object as a named version: a new project type. A name the object already
    has fails with {"exists": id} unless `replace` ("1"), which regenerates that version with these values
    (same id, type and name). One undo step."""
    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    obj = _definition(key)
    if obj is None:
        return A._fail(f"no library object {key} with parameters")
    name, error = _clean_name(name)
    if error:
        return A._fail(error)
    try:
        values = obj.values(library._given(params_json))
        obj.shape(values)  # values the definition cannot build save nothing
    except (ObjectError, ValueError) as ex:
        return A._fail(str(ex))
    existing = _clash(obj.ref, name)
    if existing is not None and str(replace) not in ("1", "true", "True"):
        return B._dump({"ok": False, "error": f"{obj.name} already has a version called {existing['name']}",
                        "exists": existing["id"]})
    made = {}

    def action():
        if existing is not None:
            t = find_version(existing["id"])
            library._regenerate_type(t, obj, values)  # keeps the name and the version fields
            made["id"] = existing["id"]
        else:
            t = library._make_type(obj, values)
            made["id"] = uuid.uuid4().hex
            _write_version(t, made["id"], name)
        made["type"] = t
        return 1

    try:
        B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "id": made["id"], "type": made["type"].GlobalId})


def rename_version(version_id: str, name: str) -> str:
    """Rename a saved version (its type's Name too). Names stay unique per object. One undo step."""
    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    t = find_version(version_id)
    if t is None:
        return A._fail("unknown version")
    name, error = _clean_name(name)
    if error:
        return A._fail(error)
    ref = _pset(t).get("Object") or ""
    other = _clash(ref, name, other_than=version_id)
    if other is not None:
        return B._dump({"ok": False, "error": f"there is already a version called {other['name']}", "exists": other["id"]})

    def action():
        _write_version(t, version_id, name)
        return 1

    try:
        B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "id": version_id, "type": t.GlobalId})


def delete_version(version_id: str) -> str:
    """Remove a saved version nothing uses (else {"used": n}). One undo step."""
    import ifcopenshell.api.root
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    t = find_version(version_id)
    if t is None:
        return A._fail("unknown version")
    used = len(ifcopenshell.util.element.get_types(t))
    if used:
        return B._dump({"ok": False, "error": f"{used} objects use this version", "used": used})

    def action():
        ifcopenshell.api.root.remove_product(B._model, product=t)
        return 1

    try:
        B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True})


def set_last_used(key: str, data_json: str) -> str:
    """Remember what a plain click places for this object: {"version": id} or {"values": {...}}. A
    project setting (`object_last_used`), not a model edit."""
    from . import app_bridge as B
    from . import settings

    try:
        data = json.loads(data_json or "{}")
    except ValueError as ex:
        return B._dump({"ok": False, "error": f"bad input: {ex}"})
    if not key or not (isinstance(data, dict) and len(data) == 1 and (
            isinstance(data.get("version"), str) or isinstance(data.get("values"), dict))):
        return B._dump({"ok": False, "error": 'the last used is {"version": id} or {"values": {...}}'})
    table = {**settings.current().get("object_last_used", {}), key: data}
    return settings.set_project_settings(json.dumps({"object_last_used": table}))
