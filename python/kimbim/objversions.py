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
import os
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
    vid = data[VERSION_ID]
    return {"id": vid, "name": data.get(VERSION_NAME) or t.Name or "", "object": data.get("Object") or "",
            "values": values if isinstance(values, dict) else {}, "type": t.GlobalId,
            "uses": len(ifcopenshell.util.element.get_types(t)), "source": "project",
            "office_id": vid if vid in library._office_versions else None}


def office_versions(ref: str) -> list[dict]:
    """The office library's saved versions of an object the project has no copy of (a project type with
    the same VersionId), by name. Listed like project versions, with no type and no uses."""
    mine = {_pset(t).get(VERSION_ID) for t in _saved_types(ref)}
    found = [{"id": e["id"], "name": e["name"], "object": e["object"], "values": e["values"], "type": None,
              "uses": 0, "source": "office", "office_id": e["id"]}
             for e in library._office_versions.values() if e["object"] == ref and e["id"] not in mine]
    return sorted(found, key=lambda v: (v["name"].casefold(), v["id"]))


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
    of that object (its object is gone from the library: the project still has it, D99), else an office
    version's."""
    obj = library.get(key)
    if isinstance(obj, objects.ObjectDef):
        return obj
    if obj is not None:
        return None  # an office IFC type: fixed geometry, no parameters to save
    from . import app_bridge as B

    if B._model is not None:
        for t in sorted(_saved_types(key), key=lambda t: t.id()) + library._library_types(B._model):
            info = library._params_of_type(t)
            if info is not None and info[0] == key and (d := library.definition_of_type(t)) is not None:
                return d
    for entry in library._office_versions.values():
        if entry["object"] == key and (d := library.office_definition(entry)) is not None:
            return d
    return None


def _outdated_version(t):
    """(type, definition, values, current definition, new values) when saved version `t` is outdated
    (D100), else None:
    - a copy of an office version (its VersionId is in the office library) follows that office version:
      outdated when the office version's values or definition (DefinitionHash) differ from the copy's; the
      new values are the office version's. Only the office version, never the live definition too: the two
      could disagree and the copy would never settle;
    - any other follows its object's live definition (bundled or office .kimobj): outdated when its
      DefinitionHash differs; values are kept as for unsaved placements (library._kept_values).
    The new values are not built: update_from_library checks they build."""
    data = _pset(t)
    obj = library.definition_of_type(t)
    info = library._params_of_type(t)
    if obj is None or info is None or not data.get(VERSION_ID):
        return None
    values = obj.values(info[1])
    entry = library._office_versions.get(data[VERSION_ID])
    if entry is not None and entry["object"] == info[0]:
        if entry["values"] == info[1] and entry["hash"] == (data.get("DefinitionHash") or ""):
            return None
        current = library.office_definition(entry)
        if current is None:
            return None  # the office file went or changed since it loaded: nothing to follow
        return t, obj, values, current, current.values(entry["values"])
    current = library.get(info[0])
    if not isinstance(current, objects.ObjectDef) or library._hash_of(current) == library._hash_of(obj):
        return None
    return t, obj, values, current, library._kept_values(obj, values, current)


def outdated_versions(types=None) -> list:
    """[(type, definition, values, current definition, new values)] of the project's outdated saved versions
    (_outdated_version), used or not; only those among `types` when given."""
    candidates = _saved_types() if types is None else [t for t in types if is_saved(t)]
    return [x for t in sorted(candidates, key=lambda t: t.id()) if (x := _outdated_version(t)) is not None]


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
    """The dialog's versions list for an object: its default values, the project's saved versions, then
    the office library's ("source": "office"; one the project has a copy of is listed once, as the
    project's, with its "office_id"), and the last one used (`object_last_used`)."""
    from . import app_bridge as B
    from . import authoring as A
    from . import settings

    obj = _definition(key)
    if obj is None:
        return A._fail(f"no library object {key}")
    last = settings.current().get("object_last_used", {}).get(key, {})
    if "version" in last and find_version(last["version"]) is None and last["version"] not in library._office_versions:
        last = {}  # a version no longer in the project or the office: a plain click places the Default
    return B._dump({"ok": True, "default": obj.values(), "versions": project_versions(key) + office_versions(key),
                    "last": last})


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


def _selection_type(guids_json: str):
    """(elements, definition, values, type) of a selection of placements of one library type, or an error
    text. The definition is the one stored on the type (D99)."""
    from . import app_bridge as B

    elements = B._elements(guids_json)
    if not elements:
        return "no library object selected"
    found = [library._object_of(e) for e in elements]
    if any(x is None for x in found):
        return "the selection holds elements that are not library objects"
    if len({x[2].id() for x in found}) > 1:
        return "the selection holds objects of more than one type"
    obj, values, t = found[0]
    return elements, obj, values, t


def object_settings_of(guids_json: str) -> str:
    """What the dialog edits for these placements (D100): their object, the values and version of their
    type, and whether the type is shared beyond the selection. Fails for no library object or more than one
    type."""
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    found = _selection_type(guids_json)
    if isinstance(found, str):
        return A._fail(found)
    elements, obj, values, t = found
    uses = len(ifcopenshell.util.element.get_types(t))
    return B._dump({"ok": True, "key": obj.ref, "values": values, "version": _pset(t).get(VERSION_ID) or None,
                    "name": t.Name or "", "selected": len(elements), "uses": uses, "shared": uses > len(elements)})


def apply_object_settings(guids_json: str, params_json: str, mode: str, name: str = "") -> str:
    """Apply the dialog's values to these placements of one type (D100). One undo step. `mode`:
    - "all": every placement of the type follows; the type regenerates in place, keeping its GlobalId, name
      and VersionId, and never merges into another type (an unnamed type moves everyone to an unnamed type
      with these values, if there is one: D99);
    - "new": a saved version called `name` (a name the object has fails with {"exists": id}); only the
      selection moves to it;
    - "auto": "all" when nothing outside the selection uses the type, else fails with {"shared": true} so
      the app asks."""
    import ifcopenshell.api.type
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    if mode not in ("all", "new", "auto"):
        return A._fail(f"unknown mode {mode}")
    found = _selection_type(guids_json)
    if isinstance(found, str):
        return A._fail(found)
    elements, obj, values, t = found
    try:
        given = json.loads(params_json) if params_json else {}
    except ValueError as ex:
        return A._fail(f"bad input: {ex}")
    if not isinstance(given, dict):
        return A._fail("the values are an object {parameter: value}")
    try:
        new_values = library._edited_values(obj, values, given)
    except (ObjectError, ValueError) as ex:
        return A._fail(str(ex))
    everyone = list(ifcopenshell.util.element.get_types(t))
    if mode == "auto":
        if len(everyone) > len(elements):
            return B._dump({"ok": False, "error": f"{len(everyone)} objects use this type", "shared": True,
                            "uses": len(everyone), "selected": len(elements)})
        mode = "all"
    if mode == "new":
        name, error = _clean_name(name)
        if error:
            return A._fail(error)
        existing = _clash(obj.ref, name)
        if existing is not None:
            return B._dump({"ok": False, "error": f"{obj.name} already has a version called {existing['name']}",
                            "exists": existing["id"]})
    made = {}

    def action():
        if mode == "all":
            library._retype_whole(t, obj, new_values)
            changed = everyone
        else:
            target = library._make_type(obj, new_values)
            made["id"] = uuid.uuid4().hex
            _write_version(target, made["id"], name)
            ifcopenshell.api.type.assign_type(B._model, related_objects=elements, relating_type=target)
            library._remove_type_if_unused(t)
            made["type"] = target.GlobalId
            changed = elements
        return len(changed), [e.GlobalId for e in changed], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, **made})


def assign_version(guids_json: str, version_id: str) -> str:
    """Move these placements to a saved version's type (D100). An office version the project has no copy
    of is copied in first (as placing it does). An unnamed type left unused goes. One undo step."""
    import ifcopenshell.api.type
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    target = find_version(version_id)
    office = library._office_versions.get(version_id) if target is None and version_id else None
    if target is None and office is None:
        return A._fail("unknown version")
    office_obj = library.office_definition(office) if office is not None else None
    if office is not None and office_obj is None:
        return A._fail(f"the office version {office['name']} has no definition")
    ref = office["object"] if office is not None else _pset(target).get("Object") or ""
    elements = B._elements(guids_json)
    if not elements:
        return A._fail("no library object selected")
    found = [library._object_of(e) for e in elements]
    if any(x is None or x[0].ref != ref for x in found):
        return A._fail(f"that version is not one of every selected object ({ref})")
    old = {x[2].id(): x[2] for x in found if x[2] != target}
    made = []

    def action():
        relating = target if office is None else copy_office_version(office, office_obj, dict(office["values"]))
        made.append(relating)
        ifcopenshell.api.type.assign_type(B._model, related_objects=elements, relating_type=relating)
        for t in old.values():
            library._remove_type_if_unused(t)
        return len(elements), [e.GlobalId for e in elements], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "type": made[0].GlobalId})


# ---------------------------------------------------------------- the office library

VERSIONS_FILE = "kimbim-versions.ifc"  # in the office folder: the versions every project sees


def _office_copy_name(ref: str, name: str) -> str:
    """`name`, or "<name> (office)" when another project version of `ref` has it (then "(office 2)", ...)."""
    candidate, n = name, 1
    while _clash(ref, candidate) is not None:
        suffix = " (office)" if n == 1 else f" (office {n})"
        candidate, n = name[:NAME_LIMIT - len(suffix)] + suffix, n + 1
    return candidate


def copy_office_version(entry: dict, obj, values: dict):
    """An office version copied into the project (library.place_object, inside its undo step): a project
    type built from the office type's stored definition and values, keeping the office VersionId, so later
    placements find and reuse it and the project never depends on the office library."""
    t = library._make_type(obj, values)
    _write_version(t, entry["id"], _office_copy_name(obj.ref, entry["name"]))
    return t


def _new_versions_file(model):
    """An empty office versions file in the project's schema, with its units. Its IfcProject is made
    directly: the api's owner history would point at the open model's person (IFC2X3 takes the copied
    type's, move_version_to_library)."""
    import ifcopenshell.api.project
    import ifcopenshell.guid

    f = ifcopenshell.api.project.create_file(version=model.schema)
    project = f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="KimBim versions")
    units = next(iter(model.by_type("IfcProject")), None)
    if units is not None and units.UnitsInContext is not None:
        project.UnitsInContext = f.add(units.UnitsInContext)
    return f


def move_version_to_library(version_id: str, replace: str = "") -> str:
    """Copy a project version into the office library's versions file (<office folder>/kimbim-versions.ifc,
    made in the project's schema if missing), keeping its VersionId. An office version with the same id,
    or the same object and name, fails with {"exists": id} unless `replace` ("1"), which replaces it. The
    office library reloads after. Not an undo step: the project does not change."""
    import ifcopenshell
    import ifcopenshell.api.project
    import ifcopenshell.api.root

    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    t = find_version(version_id)
    if t is None:
        return A._fail("unknown version")
    folder = library._office_paths["folder"]
    if not folder:
        return A._fail("no office library folder: set one in Preferences › Office library")
    if not os.path.isdir(folder):
        return A._fail(f"the office library folder {folder} is missing")
    if B._model.schema not in ("IFC4", "IFC2X3"):
        return A._fail("the office library shares versions of IFC4 and IFC2X3 projects")
    path = os.path.join(folder, VERSIONS_FILE)
    try:
        office = ifcopenshell.open(path) if os.path.isfile(path) else _new_versions_file(B._model)
    except Exception as ex:
        return A._fail(f"cannot read {path}: {type(ex).__name__}: {ex}")
    if office.schema != B._model.schema:
        return A._fail(f"the office versions file is {office.schema}, this project is {B._model.schema}")
    mine = version_of(t)
    same = [o for o in library._library_types(office) if (d := _pset(o)).get(VERSION_ID) and (
        d[VERSION_ID] == version_id or (d.get("Object") == mine["object"] and
                                        (d.get(VERSION_NAME) or o.Name or "").casefold() == mine["name"].casefold()))]
    if same and str(replace) not in ("1", "true", "True"):
        theirs = _pset(same[0])
        return B._dump({"ok": False, "error": "the office library already has a version called "
                        f"{theirs.get(VERSION_NAME) or same[0].Name}", "exists": theirs[VERSION_ID]})
    temp = path + ".tmp"
    try:
        for o in same:
            ifcopenshell.api.root.remove_product(office, product=o)
        copied = ifcopenshell.api.project.append_asset(office, library=B._model, element=t)  # the pset comes with it
        for p in office.by_type("IfcProject"):
            if p.OwnerHistory is None and office.schema == "IFC2X3":  # required in IFC2X3
                p.OwnerHistory = copied.OwnerHistory
        office.write(temp, format=".ifc")
        os.replace(temp, path)
    except Exception as ex:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass
        return A._fail(f"cannot write {path}: {type(ex).__name__}: {ex}")
    library._ifc_cache.pop(path, None)
    library.load_office(folder, library._office_paths["files"])
    return B._dump({"ok": True, "id": version_id, "path": path})


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
