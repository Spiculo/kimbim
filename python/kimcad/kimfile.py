# SPDX-License-Identifier: GPL-3.0-or-later
"""The .kim file (step 2, D72): a zip of the project folder plus a small manifest.

Saving never touches the old file until the new one is complete: the zip is written beside the
target as <name>.kim.saving and swapped in with one os.replace (retried while OneDrive or an
antivirus holds the file for a moment). Unpacking refuses entries that would land outside the folder.
"""
from __future__ import annotations

import datetime
import getpass
import hashlib
import json
import os
import pathlib
import shutil
import socket
import stat
import time
import zipfile

MANIFEST = "kimcad-file.json"
VERSION = 1
REPLACE_TRIES = 5
REPLACE_WAIT = 0.2  # seconds between tries
SKIP = (".kimcad/cache/", ".kimcad/index.db", ".kimcad/lock", ".kimcad/recovery/")


class KimError(Exception):
    pass


def remove_tree(path) -> None:
    """Delete a folder, including the read-only files Git writes (pack files, on Windows)."""
    def retry(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    if os.path.exists(path):
        shutil.rmtree(path, onexc=retry)


def path_hash(path) -> str:
    full = os.path.normcase(os.path.abspath(str(path)))
    return hashlib.sha256(full.encode("utf-8")).hexdigest()[:16]


def _app_version() -> str:
    try:
        from importlib.metadata import version

        return version("kimcad")
    except Exception:  # noqa: BLE001 (not installed as a package: a dev checkout)
        return "dev"


def _entries(folder: pathlib.Path):
    for p in sorted(folder.rglob("*")):
        if not p.is_file():
            continue
        name = p.relative_to(folder).as_posix()
        if name == MANIFEST or any(name == s or name.startswith(s) for s in SKIP):
            continue
        yield p, name


def _write_entries(z: zipfile.ZipFile, folder: pathlib.Path, kind: str) -> None:
    z.writestr(MANIFEST, json.dumps({"format": "kim", "version": VERSION, "kind": kind, "app": _app_version()}, indent=1))
    for p, name in _entries(folder):
        stored = name.startswith(".git/objects/pack/")  # already compressed
        z.write(p, name, compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)


def pack(folder, kim, kind: str = "project") -> None:
    folder, kim = pathlib.Path(folder), pathlib.Path(kim)
    tmp = kim.with_name(kim.name + ".saving")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            _write_entries(z, folder, kind)
        with open(tmp, "rb+") as f:
            os.fsync(f.fileno())
    except OSError as ex:
        tmp.unlink(missing_ok=True)
        raise KimError(f"could not write {kim.name}: {ex.strerror or ex}") from None
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, kim)
            return
        except PermissionError as ex:
            error = ex
            time.sleep(REPLACE_WAIT)
    raise KimError(f"could not replace {kim.name}: {error.strerror or error} (the new version is in {tmp.name})")


def read_manifest(kim) -> dict:
    kim = pathlib.Path(kim)
    try:
        with zipfile.ZipFile(kim) as z:
            manifest = json.loads(z.read(MANIFEST))
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        raise KimError(f"{kim.name} is not a KIMCAD file, or it is damaged") from None
    if not isinstance(manifest, dict) or manifest.get("format") != "kim":
        raise KimError(f"{kim.name} is not a KIMCAD file, or it is damaged")
    if int(manifest.get("version", 0)) > VERSION:
        raise KimError(f"{kim.name} was made by a newer KIMCAD; update KIMCAD to open it")
    return manifest


def _safe(name: str) -> bool:
    if not name or name.startswith(("/", "\\")):
        return False
    parts = pathlib.PurePosixPath(name).parts
    return ":" not in parts[0] and ".." not in parts


def unpack(kim, folder) -> dict:
    kim, folder = pathlib.Path(kim), pathlib.Path(folder)
    manifest = read_manifest(kim)
    with zipfile.ZipFile(kim) as z:
        names = [n for n in z.namelist() if n != MANIFEST]
        bad = [n for n in names if not _safe(n.replace("\\", "/"))]
        if bad:
            raise KimError(f"{kim.name} has unsafe entries ({bad[0]}); it was not opened")
        if folder.exists():
            remove_tree(folder)
            if folder.exists():
                raise KimError(f"could not clear {folder}: a file in it is in use")
        folder.mkdir(parents=True)
        for n in names:
            if n.endswith("/"):
                continue
            target = folder / n
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return manifest


# ---------------------------------------------------------------- locks

display_user = ""  # the name others see in the lock (the author name from preferences)


def lock_path(kim) -> pathlib.Path:
    kim = pathlib.Path(kim)
    return kim.with_name(kim.name + ".lock")


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def me() -> dict:
    try:
        account = getpass.getuser()
    except Exception:  # noqa: BLE001
        account = "?"
    return {"user": display_user or account, "account": account, "machine": socket.gethostname(),
            "pid": os.getpid(), "since": datetime.datetime.now().isoformat(timespec="minutes")}


def _read_lock(lock: pathlib.Path) -> dict | None:
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _ours(held: dict) -> bool:
    mine = me()
    return held.get("account") == mine["account"] and held.get("machine") == mine["machine"]


def acquire(lock) -> dict | None:
    """Lock the file for this process. Returns None when it is ours now, else who holds it. A lock left
    by this user on this machine by a process that is gone (a crash) is taken over."""
    lock = pathlib.Path(lock)
    held = _read_lock(lock) if lock.exists() else None
    if held and held.get("pid") != os.getpid():
        if not (_ours(held) and not pid_alive(int(held.get("pid", 0)))):
            return held
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps(me()), encoding="utf-8")
    return None


def release(lock) -> None:
    lock = pathlib.Path(lock)
    held = _read_lock(lock) if lock.exists() else None
    if held is not None and held.get("pid") == os.getpid() and _ours(held):
        lock.unlink(missing_ok=True)
