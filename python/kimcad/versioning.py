# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned projects in the desktop app (M5, docs/03-versioning.md): save versions, history,
compare and design options, on top of kimcad.project (the Slice 1 engine).

Same protocol as app_bridge (strings in, JSON out, never raise). The open model is the working
state; "Save version" writes it to <project>/.kimcad/working.ifc (local only, never committed) and
commits it. Opening a project or switching option exports that version to the same file and opens
it. Design options are Git branches; their names are shown as typed (spaces etc. are encoded in the
branch name).
"""
from __future__ import annotations

import json
import pathlib
import urllib.parse

from . import app_bridge as B
from .layout import blob_oid, key_to_path
from .project import KimcadError, NothingToCommit, NotAProject, Project
from .records import compose

_project: Project | None = None

MAIN = "main"


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def _working(project: Project | None = None) -> pathlib.Path:
    return (project or _project).path / ".kimcad" / "working.ifc"


def forget(path: str = "") -> None:
    """Called when a model is opened or created: leave versioned mode unless it's our working copy."""
    global _project
    if _project is not None and path and pathlib.Path(path).resolve() == _working().resolve():
        return
    _project = None


def _encode(option: str) -> str:
    return option if option == MAIN else urllib.parse.quote(option, safe="")


def _decode(branch: str) -> str:
    return urllib.parse.unquote(branch)


def _dirty() -> bool:
    return B._current_id() != B._saved_id


def project_state() -> str:
    if _project is None:
        return B._dump({"versioned": False, "dirty": _dirty() if B._model is not None else False})
    head = _project.repo.head()
    return B._dump({"versioned": True, "folder": str(_project.path), "option": _decode(_project.current_branch()),
                    "options": sorted(_decode(b) for b in _project.branches()), "head": head, "dirty": _dirty()})


def _write_working() -> pathlib.Path:
    working = _working()
    working.parent.mkdir(parents=True, exist_ok=True)
    B._model.write(str(working))
    return working


def _mark_saved(working: pathlib.Path) -> None:
    B._saved_id, B._path = B._current_id(), str(working)


def _open_head(project: Project) -> str:
    """Export the current option's latest version to the working copy and open it."""
    global _project
    working = _working(project)
    working.parent.mkdir(parents=True, exist_ok=True)
    project.export(working, overwrite=True)
    _project = project
    info = json.loads(B.open_model(str(working)))  # keeps _project: it's our working copy
    _project = project
    return B._dump({**info, "path": str(working)})


def enable_versioning(folder: str, message: str = "Initial import") -> str:
    """Turn the open model into a versioned project in an empty (or new) folder; first version."""
    global _project
    if B._model is None:
        return _fail("no model open")
    path = pathlib.Path(folder)
    if path.exists() and any(path.iterdir()):
        return _fail("choose an empty or new folder for the project")
    try:
        project = Project.init(path)
        _project = project
        working = _write_working()
        project.commit(working, message or "Initial import")
    except KimcadError as ex:
        _project = None
        return _fail(str(ex))
    _mark_saved(working)
    return B._dump({"ok": True, **json.loads(project_state())})


def open_project(folder: str) -> str:
    try:
        project = Project.open(folder)
    except (NotAProject, KimcadError) as ex:
        return _fail(f"not a KIMCAD project: {ex}")
    if project.repo.head() is None:
        return _fail("the project has no versions yet")
    try:
        return _open_head(project)
    except KimcadError as ex:
        return _fail(str(ex))


def _ancestors(ifc_type: str) -> set[str]:
    import ifcopenshell.ifcopenshell_wrapper as W

    try:
        d = W.schema_by_name(B._model.schema if B._model is not None else "IFC4").declaration_by_name(ifc_type)
    except Exception:
        return set()
    out = set()
    while d is not None:
        out.add(d.name())
        d = d.supertype()
    return out


def _summary(changes) -> dict:
    """Element-level changes: products (walls, doors...) as they are; property sets attributed to the
    elements using them (when they exist in the open model); relationships and other records counted
    in "other" (they change whenever elements are added, moved between levels, retyped...)."""
    out = {"added": [], "modified": [], "removed": [], "other": 0}
    seen = set()

    def add(kind, guid, ifc_type, name):
        if guid in seen:
            return
        seen.add(guid)
        out[kind].append({"guid": guid, "type": ifc_type, "name": name or "", "kind": kind})

    deferred = []
    for c in changes.items:
        if not c.key.startswith("o/"):
            out["other"] += 1
            continue
        guid = c.key[2:].split("~", 1)[0]
        kinds = _ancestors(c.ifc_type)
        if "IfcProduct" in kinds or "IfcTypeObject" in kinds:
            add(c.kind, guid, c.ifc_type, c.name)
        elif "IfcPropertySetDefinition" in kinds:
            deferred.append((c, guid))
        else:
            out["other"] += 1
    for c, guid in deferred:  # a changed property set modifies the elements that use it
        users = []
        if B._model is not None:
            try:
                pset = B._model.by_guid(guid)
                for rel in getattr(pset, "DefinesOccurrence", ()) or ():
                    users += list(rel.RelatedObjects)
            except RuntimeError:
                pass
        if not users:
            out["other"] += 1
        for u in users:
            if u.GlobalId not in seen:
                add("modified", u.GlobalId, u.is_a(), getattr(u, "Name", None))
    return out


def version_changes() -> str:
    """What "Save version" would record: the working model against the latest version."""
    if _project is None:
        return _fail("this model isn't versioned")
    try:
        s = _summary(_project.status(_write_working()))
    except KimcadError as ex:
        return _fail(str(ex))
    items = (s["added"] + s["modified"] + s["removed"])[:500]
    return B._dump({"ok": True, "added": len(s["added"]), "modified": len(s["modified"]),
                    "removed": len(s["removed"]), "other": s["other"], "items": items})


def save_version(message: str) -> str:
    if _project is None:
        return _fail("this model isn't versioned: enable versioning first")
    if not (message or "").strip():
        return _fail("a version needs a message")
    working = _write_working()
    try:
        cid, changes = _project.commit(working, message.strip())
    except NothingToCommit:
        _mark_saved(working)
        return _fail("nothing changed since the last version")
    except KimcadError as ex:
        return _fail(str(ex))
    _mark_saved(working)
    s = _summary(changes)
    return B._dump({"ok": True, "id": cid, "added": len(s["added"]), "modified": len(s["modified"]),
                    "removed": len(s["removed"]), "other": s["other"]})


def history(limit=100) -> str:
    if _project is None:
        return B._dump({"versions": []})
    marks = {}
    for t in _project.tags():
        marks.setdefault(t.target, []).append(_decode(t.name))
    return B._dump({"versions": [{"id": c.id, "short": c.id[:8], "message": c.message, "author": c.author_name,
                                  "time": c.time, "parents": list(c.parents), "milestones": sorted(marks.get(c.id, []))}
                                 for c in _project.log("HEAD", int(limit))]})


def compare(rev_a: str, rev_b: str = "WORKING") -> str:
    """Elements added/modified/removed from version `rev_a` to `rev_b` ("WORKING" = the open model)."""
    if _project is None:
        return _fail("this model isn't versioned")
    try:
        rev_a = _revision(rev_a)
        if rev_b == "WORKING":
            changes, _ = _project._changes(_project._entries(rev_a), _project._decompose_file(_write_working()))
        else:
            changes = _project.diff(rev_a, _revision(rev_b))
    except KimcadError as ex:
        return _fail(str(ex))
    return B._dump({"ok": True, **_summary(changes)})


def options() -> str:
    if _project is None:
        return B._dump({"options": [], "current": ""})
    return B._dump({"options": sorted(_decode(b) for b in _project.branches()), "current": _decode(_project.current_branch())})


def create_option(name: str) -> str:
    """A new design option from the latest version of the current one; it becomes current (the
    open model, including unsaved edits, carries over)."""
    if _project is None:
        return _fail("this model isn't versioned")
    name = (name or "").strip()
    if not name:
        return _fail("an option needs a name")
    if name in json.loads(options())["options"]:
        return _fail(f"there is already an option called {name}")
    try:
        _project.create_branch(_encode(name))
        _project.switch(_encode(name))
    except KimcadError as ex:
        return _fail(str(ex))
    return B._dump({"ok": True, **json.loads(project_state())})


def switch_option(name: str) -> str:
    if _project is None:
        return _fail("this model isn't versioned")
    if _dirty():
        return _fail("there are unsaved changes: save a version or discard them before switching options")
    try:
        _project.switch(_encode(name))
        return _open_head(_project)
    except KimcadError as ex:
        return _fail(str(ex))


def discard_changes() -> str:
    """Throw away unsaved changes: reopen the current option's latest version."""
    if _project is None:
        return _fail("this model isn't versioned")
    try:
        return _open_head(_project)
    except KimcadError as ex:
        return _fail(str(ex))


def delete_option(name: str) -> str:
    """Delete a design option (Git branch); not the current one, never main."""
    if _project is None:
        return _fail("this model isn't versioned")
    if name == MAIN:
        return _fail("the main option can't be deleted")
    if name not in json.loads(options())["options"]:
        return _fail(f"there is no option called {name}")
    if _encode(name) == _project.current_branch():
        return _fail("switch to another option before deleting this one")
    try:
        _project.delete_branch(_encode(name))
    except KimcadError as ex:
        return _fail(str(ex))
    return B._dump({"ok": True, **json.loads(project_state())})


# ---------------------------------------------------------------- milestones (Slice 20)

def _revision(rev: str) -> str:
    """A version id, a milestone name (as shown) or anything Git resolves."""
    if _project is not None and rev and rev != "WORKING":
        for t in _project.tags():
            if _decode(t.name) == rev:
                return t.target
    return rev


def milestones() -> str:
    """[{name, id, short, message, author, time}] sorted by the time they were set."""
    if _project is None:
        return B._dump({"milestones": []})
    out = [{"name": _decode(t.name), "id": t.target, "short": t.target[:8], "message": t.message.strip(),
            "author": t.tagger_name, "time": t.time} for t in _project.tags()]
    out.sort(key=lambda m: (m["time"], m["name"]))
    return B._dump({"milestones": out})


def create_milestone(name: str, message: str = "") -> str:
    """Mark the latest saved version of the current option as a milestone (Concept, Schematic design...)."""
    if _project is None:
        return _fail("this model isn't versioned")
    name = (name or "").strip()
    if not name:
        return _fail("a milestone needs a name")
    if _dirty():
        return _fail("there are unsaved changes: save a version first, then mark it as a milestone")
    if any(m["name"] == name for m in json.loads(milestones())["milestones"]):
        return _fail(f"there is already a milestone called {name}")
    try:
        _project.tag(_encode(name), message or name)
    except KimcadError as ex:
        return _fail(str(ex))
    return B._dump({"ok": True, "milestones": json.loads(milestones())["milestones"]})


def delete_milestone(name: str) -> str:
    if _project is None:
        return _fail("this model isn't versioned")
    try:
        _project.delete_tag(_encode(name))
    except KimcadError as ex:
        return _fail(f"no milestone called {name}" if "unknown" in str(ex) else str(ex))
    return B._dump({"ok": True, "milestones": json.loads(milestones())["milestones"]})


# ---------------------------------------------------------------- object history and before/after

def _related_paths(guid: str) -> set[str]:
    """Record paths whose changes count as changes to the element: its property sets."""
    out = set()
    if B._model is not None:
        try:
            e = B._model.by_guid(guid)
        except RuntimeError:
            return out
        for rel in getattr(e, "IsDefinedBy", ()) or ():
            if rel.is_a("IfcRelDefinesByProperties"):
                definition = rel.RelatingPropertyDefinition
                if getattr(definition, "GlobalId", None):
                    out.add(key_to_path("o/" + definition.GlobalId))
    return out


def element_history(guid: str, limit=100) -> str:
    """The saved versions that changed an element (or its properties), newest first; unsaved changes
    to it come first as "unsaved"."""
    if _project is None:
        return _fail("this model isn't versioned")
    main = key_to_path("o/" + guid)
    related = _related_paths(guid)
    try:
        steps = _project.history_of(main, related, "HEAD", int(limit))
    except KimcadError as ex:
        return _fail(str(ex))
    marks = {}
    for t in _project.tags():
        marks.setdefault(t.target, []).append(_decode(t.name))
    out = [{"id": c.id, "short": c.id[:8], "message": c.message.strip(), "author": c.author_name, "time": c.time,
            "change": kind, "milestones": sorted(marks.get(c.id, []))} for c, kind in steps]
    if _dirty():
        try:
            records = _project._decompose_file(_write_working())
            head = _project._head_entries()
            paths = {main, *related}
            now = {key_to_path(k): blob_oid(v) for k, v in records.items() if key_to_path(k) in paths}
            if now != {p: o for p, o in head.items() if p in paths}:
                out.insert(0, {"id": "WORKING", "short": "", "message": "", "author": "", "time": 0,
                               "change": "unsaved", "milestones": []})
        except KimcadError:
            pass
    return B._dump({"ok": True, "guid": guid, "versions": out})


_models: dict[str, object] = {}


def _model_at(rev: str):
    """The model at a version (ifcopenshell file), or the open one for "WORKING"; the last few cached."""
    if rev == "WORKING":
        return B._model
    cid = _project._rev(_revision(rev))
    if cid not in _models:
        if len(_models) >= 3:
            _models.pop(next(iter(_models)))
        _models[cid] = compose(_project._records(cid))
    return _models[cid]


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _element_rows(f, guid: str) -> dict | None:
    """What a person compares: identity, level, type, position and every property, as text."""
    import ifcopenshell.util.element
    import ifcopenshell.util.placement
    import ifcopenshell.util.unit

    try:
        e = f.by_guid(guid)
    except RuntimeError:
        return None
    rows = {"Class": e.is_a(), "Name": _fmt(getattr(e, "Name", None)),
            "Description": _fmt(getattr(e, "Description", None)), "Tag": _fmt(getattr(e, "Tag", None)),
            "Predefined type": _fmt(getattr(e, "PredefinedType", None))}
    container = ifcopenshell.util.element.get_container(e)
    rows["Level"] = _fmt(container.Name if container is not None else "")
    t = ifcopenshell.util.element.get_type(e)
    rows["Type"] = _fmt(t.Name if t is not None else "")
    if getattr(e, "ObjectPlacement", None) is not None:
        s = ifcopenshell.util.unit.calculate_unit_scale(f)
        m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
        import math

        angle = math.degrees(math.atan2(m[1][0], m[0][0]))
        rows["Position"] = ", ".join(f"{m[i][3] * s:.3f}" for i in range(3)) + f" ({angle:.1f}°)"
    for pset, props in sorted(ifcopenshell.util.element.get_psets(e, psets_only=False).items()):
        for k, v in sorted(props.items()):
            if k != "id":
                rows[f"{pset}.{k}"] = _fmt(v)
    return rows


def before_after(guid: str, rev_a: str, rev_b: str = "WORKING") -> str:
    """One element at two versions, field by field: [{field, before, after, changed}]."""
    if _project is None:
        return _fail("this model isn't versioned")
    try:
        before = _element_rows(_model_at(rev_a), guid)
        after = _element_rows(_model_at(rev_b), guid)
    except (KimcadError, RuntimeError) as ex:
        return _fail(str(ex))
    if before is None and after is None:
        return _fail("the element is in neither version")
    fields = list((after or {}).keys()) + [k for k in (before or {}) if k not in (after or {})]
    rows = [{"field": k, "before": (before or {}).get(k, ""), "after": (after or {}).get(k, ""),
             "changed": (before or {}).get(k) != (after or {}).get(k)} for k in fields]
    return B._dump({"ok": True, "guid": guid, "before_exists": before is not None, "after_exists": after is not None,
                    "rows": rows})

