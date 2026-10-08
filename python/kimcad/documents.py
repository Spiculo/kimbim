# SPDX-License-Identifier: GPL-3.0-or-later
"""The open document (step 2, D72): a .kim, a project folder, a template being edited, or a plain IFC.

A .kim is unpacked to a working folder (<data>/open/<hash>/) while it is open; Ctrl+S writes the
model and settings there and packs it back. A project folder is used in place. Opening prepares the
working copy and leaves a "pending" note; the app's loader then opens it (B.open_model), and
on_model_opened() attaches the history, the settings and the document state.

Same protocol as app_bridge (strings in, JSON out, never raise).
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import uuid

from . import app_bridge as B
from . import kimfile as K
from . import project as P
from . import settings as S
from . import versioning as V
from .project import KimcadError, NotAProject, Project

_data_dir: pathlib.Path | None = None
_pending: dict | None = None


def _plain(path: str = "") -> dict:
    # rid: names an untitled document's recovery copy (two untitled models never share one)
    return {"mode": "plain", "source": path, "work": "", "lock": "", "read_only": False, "template": "",
            "rid": uuid.uuid4().hex}


_doc: dict = _plain()


def _fail(message: str, **extra) -> str:
    return B._dump({"ok": False, "error": message, **extra})


def data_dir() -> pathlib.Path:
    if _data_dir is not None:
        return _data_dir
    if os.environ.get("KIMCAD_DATA_DIR"):
        return pathlib.Path(os.environ["KIMCAD_DATA_DIR"])
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return pathlib.Path(os.environ["LOCALAPPDATA"]) / "KIMCAD"
    return pathlib.Path.home() / ".local" / "share" / "KIMCAD"


def _same(a, b) -> bool:
    return bool(a) and bool(b) and os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def _skip(_dir, names):
    return [n for n in names if n in ("lock", "cache", "index.db", "recovery")]


def _read(path: pathlib.Path):
    try:
        return path.read_bytes()
    except OSError:
        return None


def _locked(name: str, holder: dict) -> str:
    return _fail(f"{holder.get('user', '?')} has {name} open on {holder.get('machine', '?')} "
                 f"since {holder.get('since', '?')}", locked=holder)


# ---------------------------------------------------------------- state

def set_app_paths(data: str) -> str:
    global _data_dir
    _data_dir = pathlib.Path(data) if data else None
    return B._dump({"ok": True, "data": str(data_dir())})


def set_author(name: str, email: str) -> str:
    P._AUTHOR = (name.strip(), (email or "").strip() or "user@localhost") if (name or "").strip() else None
    K.display_user = (name or "").strip()
    return B._dump({"ok": True})


def state_fields() -> dict:
    d = _doc
    untitled = d["mode"] == "plain" and not B._path
    source = d["source"] or ("" if untitled else B._path)
    return {"mode": d["mode"], "path": source, "name": pathlib.Path(source).name if source else "",
            "read_only": d["read_only"], "untitled": untitled, "template": d["template"], "kept": S.kept}


def document_state() -> str:
    return B._dump({"ok": True, **state_fields()})


def on_model_opened(path: str) -> None:
    """Called by app_bridge whenever a model is opened or created (after versioning.forget)."""
    global _pending, _doc
    if _pending is not None and _same(path, _pending["path"]):
        p, _pending = _pending, None
        _doc = p["doc"]
        V._project = p["project"]
        S.load(p["settings"], dirty=p.get("dirty", False))
        S.kept = _doc["mode"] != "plain"
        if p["project"] is not None:
            V.mark_versioned(unversioned=p["unversioned"])
        if p.get("untitled"):
            B._path = ""
        elif p.get("source_path"):
            B._path = p["source_path"]
        if p.get("dirty"):
            B._saved_id = -1
        return
    if _doc["work"] and _same(path, pathlib.Path(_doc["work"]) / ".kimcad" / "working.ifc"):
        return  # the document's own working copy reopened (an option switch, discard, combine)
    _close()
    _doc = _plain(path)
    S.kept = False


def _close() -> None:
    """Leave the document: its lock and working folder go. Its recovery copy stays (only a save or an
    explicit close_document, after the user saved or discarded, clears it)."""
    d = _doc
    if d["lock"]:
        K.release(d["lock"])
    if d["mode"] in ("kim", "template") and d["work"]:
        K.remove_tree(d["work"])


def _recovery_key() -> str:
    return _doc["source"] or B._path or _doc.get("rid", "")


def close_document() -> str:
    global _doc
    _clear_recovery(_recovery_key())
    _close()
    _doc = _plain()
    V._project = None
    S.kept = False
    return B._dump({"ok": True})


# ---------------------------------------------------------------- opening

def _prepare(project_dir: pathlib.Path, files_dir: pathlib.Path, doc: dict, attach: bool) -> pathlib.Path:
    """Make files_dir/.kimcad/working.ifc the document's current work and leave the pending note."""
    global _pending
    project = Project.open(project_dir) if (project_dir / ".git" / "HEAD").is_file() else None
    head = project.repo.head() if project else None
    try:
        state = json.loads(_read(project_dir / ".kimcad" / "working.json") or b"{}")
    except ValueError:
        state = {}
    src = project_dir / ".kimcad" / "working.ifc"
    working = files_dir / ".kimcad" / "working.ifc"
    working.parent.mkdir(parents=True, exist_ok=True)
    if head and not (src.exists() and state.get("head") == head):
        project.export(working, overwrite=True, one_owner=True)
        settings, unversioned = S.from_bytes(project.settings_at("HEAD")), False
    else:
        if not src.exists():
            raise KimcadError("the file has no model in it")
        if not _same(src, working):
            shutil.copyfile(src, working)
        settings = S.from_bytes(_read(project_dir / ".kimcad" / "settings.json"))
        unversioned = bool(state.get("unversioned")) and head is not None
    _pending = {"path": str(working), "doc": doc, "project": project if attach else None,
                "settings": settings, "unversioned": unversioned}
    return working


def open_kim(path: str, read_only: str = "") -> str:
    kim = pathlib.Path(path)
    try:
        manifest = K.read_manifest(kim)
    except K.KimError as ex:
        return _fail(str(ex))
    ro = bool(read_only)
    lock = K.lock_path(kim)
    if not ro and (holder := K.acquire(lock)) is not None:
        return _locked(kim.name, holder)
    work = data_dir() / "open" / (K.path_hash(kim) + (f"-ro-{os.getpid()}" if ro else ""))
    mode = "template" if manifest.get("kind") == "template" else "kim"
    doc = {"mode": mode, "source": str(kim), "work": str(work), "lock": "" if ro else str(lock),
           "read_only": ro, "template": ""}
    try:
        K.unpack(kim, work)
        working = _prepare(work, work, doc, attach=not ro and mode == "kim")
    except (K.KimError, KimcadError, OSError) as ex:
        if not ro:
            K.release(lock)
        K.remove_tree(work)
        return _fail(str(ex))
    return B._dump({"ok": True, "path": str(working), "read_only": ro, "kind": manifest.get("kind", "project")})


def open_folder(folder: str, read_only: str = "") -> str:
    path = pathlib.Path(folder)
    try:
        project = Project.open(path)
    except (NotAProject, KimcadError) as ex:
        return _fail(f"not a KIMCAD project: {ex}")
    if project.repo.head() is None:
        return _fail("the project has no versions yet")
    ro = bool(read_only)
    lock = path / ".kimcad" / "lock"
    if not ro and (holder := K.acquire(lock)) is not None:
        return _locked(path.name, holder)
    files = data_dir() / "open" / f"{K.path_hash(path)}-ro-{os.getpid()}" if ro else path
    doc = {"mode": "folder", "source": str(path), "work": "" if ro else str(path), "lock": "" if ro else str(lock),
           "read_only": ro, "template": ""}
    try:
        working = _prepare(path, files, doc, attach=not ro)
    except (KimcadError, OSError) as ex:
        if not ro:
            K.release(lock)
        return _fail(str(ex))
    return B._dump({"ok": True, "path": str(working), "read_only": ro})


def kim_beside(ifc_path: str) -> str:
    ifc = pathlib.Path(ifc_path)
    kim = ifc.with_suffix(".kim")
    free, n = kim, 2
    while free.exists():
        free = ifc.with_name(f"{ifc.stem} ({n}).kim")
        n += 1
    return B._dump({"kim": str(kim), "exists": kim.exists(), "free": str(free)})


def import_ifc(ifc_path: str, kim_path: str) -> str:
    """A new .kim beside an IFC: its first version is the IFC as it is. The IFC is never modified."""
    global _pending
    ifc, kim = pathlib.Path(ifc_path), pathlib.Path(kim_path)
    if kim.exists():
        return _fail(f"{kim.name} already exists")
    lock = K.lock_path(kim)
    if (holder := K.acquire(lock)) is not None:
        return _locked(kim.name, holder)
    work = data_dir() / "open" / K.path_hash(kim)
    defaults = S.from_bytes(None)
    try:
        K.remove_tree(work)
        (work / ".kimcad").mkdir(parents=True)
        working = work / ".kimcad" / "working.ifc"
        shutil.copyfile(ifc, working)
        project = Project.init(work)
        project.commit(working, f"Imported from {ifc.name}", settings=S.to_bytes(defaults))
        (work / ".kimcad" / "settings.json").write_bytes(S.to_bytes(defaults))
        (work / ".kimcad" / "working.json").write_text(
            json.dumps({"head": project.repo.head(), "option": project.current_branch(), "unversioned": False}))
        K.pack(work, kim)
    except (KimcadError, K.KimError, OSError) as ex:
        K.release(lock)
        K.remove_tree(work)
        return _fail(str(ex))
    doc = {"mode": "kim", "source": str(kim), "work": str(work), "lock": str(lock), "read_only": False, "template": ""}
    _pending = {"path": str(working), "doc": doc, "project": project, "settings": defaults, "unversioned": False}
    return B._dump({"ok": True, "path": str(working), "kim": str(kim)})


# ---------------------------------------------------------------- saving

def _write_files(work: pathlib.Path) -> None:
    """The model, the settings and where they stand against the history, into a project folder."""
    (work / ".kimcad").mkdir(parents=True, exist_ok=True)
    B._model.write(str(work / ".kimcad" / "working.ifc"))
    (work / ".kimcad" / "settings.json").write_bytes(S.to_bytes())
    project = V._project
    (work / ".kimcad" / "working.json").write_text(json.dumps({
        "head": project.repo.head() if project else None,
        "option": project.current_branch() if project else "",
        "unversioned": V._unversioned()}))


def _saved() -> None:
    B._saved_id = B._current_id()
    S.mark_saved()
    _clear_recovery(_recovery_key())


def save_document() -> str:
    if B._model is None:
        return _fail("no model open")
    d = _doc
    if d["read_only"]:
        return _fail("this file is open read-only; use Save As to keep your changes")
    if d["mode"] == "plain":
        if not B._path:
            return _fail("untitled: choose where to save it")
        r = json.loads(B.save(""))
        if r.get("ok"):
            _clear_recovery(_recovery_key())
        return B._dump(r)
    work = pathlib.Path(d["work"])
    try:
        _write_files(work)
        if d["mode"] in ("kim", "template"):
            K.pack(work, d["source"], "template" if d["mode"] == "template" else "project")
    except (K.KimError, OSError) as ex:
        return _fail(str(ex))
    _saved()
    return B._dump({"ok": True, "path": d["source"]})


def _first_message(message: str) -> str:
    if message:
        return message
    return f"Created from {_doc['template']}" if _doc["template"] else "First version"


def _make_history(work: pathlib.Path, message: str) -> None:
    """A history for a model that has none (plain, untitled, a template): one first version."""
    working = work / ".kimcad" / "working.ifc"
    (work / ".kimcad").mkdir(parents=True, exist_ok=True)
    B._model.write(str(working))
    project = Project.init(work)
    project.commit(working, _first_message(message), settings=S.to_bytes())
    V._project = project
    V.mark_versioned()


def _switch_to(doc: dict, work: pathlib.Path) -> None:
    global _doc
    old = _doc
    if old["lock"] and old["lock"] != doc["lock"]:
        K.release(old["lock"])
    if old["mode"] in ("kim", "template") and old["work"] and not _same(old["work"], work):
        K.remove_tree(old["work"])
    _doc = doc
    V._project = Project.open(work) if (work / ".git" / "HEAD").is_file() else None
    B._path = str(work / ".kimcad" / "working.ifc")
    S.kept = True


def save_as_kim(path: str, message: str = "") -> str:
    if B._model is None:
        return _fail("no model open")
    kim = pathlib.Path(path)
    if _doc["mode"] == "kim" and _same(kim, _doc["source"]) and not _doc["read_only"]:
        return save_document()
    lock = K.lock_path(kim)
    if (holder := K.acquire(lock)) is not None:
        return _locked(kim.name, holder)
    work = data_dir() / "open" / K.path_hash(kim)
    try:
        K.remove_tree(work)
        if _doc["work"] and not _doc["read_only"] and _doc["mode"] != "plain":
            shutil.copytree(_doc["work"], work, ignore=_skip)
        else:
            work.mkdir(parents=True)
        if not (work / ".git" / "HEAD").is_file():
            _make_history(work, message)
        unversioned = V._unversioned()
        _switch_to({"mode": "kim", "source": str(kim), "work": str(work), "lock": str(lock), "read_only": False,
                    "template": ""}, work)
        if unversioned:
            V.mark_versioned(unversioned=True)
        _write_files(work)
        K.pack(work, kim)
    except (KimcadError, K.KimError, OSError) as ex:
        K.release(lock)
        return _fail(str(ex))
    _saved()
    return B._dump({"ok": True, "path": str(kim)})


def save_as_folder(folder: str, message: str = "") -> str:
    if B._model is None:
        return _fail("no model open")
    path = pathlib.Path(folder)
    if path.exists() and any(path.iterdir()):
        return _fail("choose an empty or new folder for the project")
    lock = path / ".kimcad" / "lock"
    try:
        if _doc["work"] and not _doc["read_only"] and _doc["mode"] != "plain":
            shutil.copytree(_doc["work"], path, ignore=_skip, dirs_exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
        if not (path / ".git" / "HEAD").is_file():
            _make_history(path, message)
        unversioned = V._unversioned()
        K.acquire(lock)
        _switch_to({"mode": "folder", "source": str(path), "work": str(path), "lock": str(lock), "read_only": False,
                    "template": ""}, path)
        if unversioned:
            V.mark_versioned(unversioned=True)
        _write_files(path)
    except (KimcadError, OSError) as ex:
        return _fail(str(ex))
    _saved()
    return B._dump({"ok": True, "path": str(path)})


def export_ifc(path: str) -> str:
    if B._model is None:
        return _fail("no model open")
    try:
        B._model.write(path)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({"ok": True, "path": path})


def _clear_recovery(key: str) -> None:  # Task 6 replaces this stub
    pass
