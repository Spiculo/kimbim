# SPDX-License-Identifier: GPL-3.0-or-later
"""Where records live inside a KimBim Git tree (docs/03-versioning.md).

One shard level for now; adaptive sharding (D39) waits until models above ~64k records need it.
This module is the only place that knows the layout.
"""
import hashlib
import json
import re

import blake3

META_PATH = "kimbim.json"
SETTINGS_PATH = "settings.json"  # project settings (step 2, D72); not a record, never composed into IFC
# Files kept with a version (D85: underlays), named by their blob id "<sha1>.<ext>", so a file is
# stored once however many versions use it. Not records, never composed into IFC. In the working folder
# they live in WORK_FILES_DIR.
FILES_DIR = "files"
WORK_FILES_DIR = ".kimbim/underlays"
_FILE_NAME = re.compile(r"[0-9a-f]{40}\.[a-z]{3,4}")
_DIRS = {"objects": "o", "nodes": "n", "loose": "l"}
_KINDS = {v: k for k, v in _DIRS.items()}


def key_to_path(key: str) -> str:
    if key == "meta":
        return META_PATH
    kind, _, ident = key.partition("/")
    if kind not in _KINDS or not ident:
        raise ValueError(f"unknown record key {key!r}")
    # Rooted ids are GlobalIds (not uniformly distributed), so shard them by hash.
    shard = blake3.blake3(ident.encode("utf-8")).hexdigest()[:2] if kind == "o" else ident[:2]
    return f"{_KINDS[kind]}/{shard}/{ident}.json"


def path_to_key(path: str) -> str:
    if path == META_PATH:
        return "meta"
    parts = path.split("/")
    if len(parts) != 3 or parts[0] not in _DIRS or not parts[2].endswith(".json"):
        raise ValueError(f"not a record path: {path!r}")
    return f"{_DIRS[parts[0]]}/{parts[2][:-5]}"


def blob_oid(data: bytes) -> str:
    """Git blob id (SHA-1), so unchanged records are detected without reading the repository."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def is_file_path(path: str) -> bool:
    return path.startswith(FILES_DIR + "/")


def is_record_path(path: str) -> bool:
    return path != SETTINGS_PATH and not is_file_path(path)


def referenced_files(settings: bytes | None) -> set[str]:
    """Tree paths of the files a version's settings use (its underlays, D85)."""
    try:
        data = json.loads(settings) if settings else {}
    except ValueError:
        return set()
    names = set()
    for u in (data.get("underlays") or ()) if isinstance(data, dict) else ():
        name = u.get("file", "") if isinstance(u, dict) else ""
        if isinstance(name, str) and _FILE_NAME.fullmatch(name):
            names.add(f"{FILES_DIR}/{name}")
    for name in [*(data.get("sheet_files") or ()), *(data.get("texture_files") or ())] if isinstance(data, dict) else ():
        # D98 pictures on sheets, D96 surface textures
        if isinstance(name, str) and _FILE_NAME.fullmatch(name):
            names.add(f"{FILES_DIR}/{name}")
    return names
