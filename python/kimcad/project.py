# SPDX-License-Identifier: GPL-3.0-or-later
"""A KIMCAD project: IFC versions stored as canonical records in Git (docs/03-versioning.md)."""
from __future__ import annotations

import json
import os
import re
import pathlib
import subprocess
import time as _time
from dataclasses import dataclass, field

import ifcopenshell
import ifcopenshell.validate

from . import _core
from .layout import META_PATH, SETTINGS_PATH, blob_oid, key_to_path, path_to_key
from .nodeids import decompose_against_head
from .records import compose, unshare

REPACK_THRESHOLD = 10_000  # changed records; D39
GLOBALID = re.compile(r"[0-9A-Za-z_$]{22}")  # IFC GlobalId: 22 chars of the IFC base-64 alphabet


class KimcadError(Exception):
    pass


class NotAProject(KimcadError):
    pass


class NothingToCommit(KimcadError):
    pass


class SchemaMismatch(KimcadError):
    pass


class NoVersions(KimcadError):
    pass


class UnknownRevision(KimcadError):
    pass


class TargetExists(KimcadError):
    pass


class MergeConflicts(KimcadError):
    def __init__(self, result):
        super().__init__(f"{len(result.unresolved)} conflict(s) to resolve before combining")
        self.result = result


class InvalidInput(KimcadError):
    def __init__(self, message: str, messages: list[str]):
        super().__init__(message)
        self.messages = messages


@dataclass
class MergePreview:
    status: str  # "up_to_date" | "fast_forward" | "merge"
    base: str | None
    ours: str
    theirs: str
    result: object = None  # kimcad.merge.MergeResult for "merge"
    settings: bytes | None = None  # the merged project settings ("merge"; None when no side has any)
    settings_conflicts: list = field(default_factory=list)  # keys changed differently on both sides


@dataclass
class Change:
    kind: str  # "added" | "modified" | "removed"
    key: str
    ifc_type: str
    name: str | None


@dataclass
class Changes:
    items: list[Change] = field(default_factory=list)

    def of(self, kind: str) -> list[Change]:
        return [c for c in self.items if c.kind == kind]

    @property
    def added(self) -> list[Change]:
        return self.of("added")

    @property
    def modified(self) -> list[Change]:
        return self.of("modified")

    @property
    def removed(self) -> list[Change]:
        return self.of("removed")

    def __bool__(self) -> bool:
        return bool(self.items)


def _describe(key: str, blob: bytes) -> tuple[str, str | None]:
    if key == "settings":
        return "(project settings)", None
    if key == "meta":
        return "(project metadata)", None
    v = json.loads(blob)
    if key.startswith("l/"):
        v = v["e"]
    return v["t"], v.get("a", {}).get("Name")


def _git_config(key: str) -> str | None:
    try:
        out = subprocess.run(["git", "config", "--get", key], capture_output=True, text=True)
    except OSError:
        return None
    return out.stdout.strip() or None


_AUTHOR: tuple[str, str] | None = None  # set by the app from its preferences (documents.set_author)


def _author() -> tuple[str, str]:
    if _AUTHOR is not None:
        return _AUTHOR
    name = os.environ.get("KIMCAD_AUTHOR_NAME") or _git_config("user.name") or "KIMCAD User"
    email = os.environ.get("KIMCAD_AUTHOR_EMAIL") or _git_config("user.email") or "user@localhost"
    return name, email


class Project:
    def __init__(self, path: pathlib.Path, repo):
        self.path = path
        self.repo = repo

    @classmethod
    def init(cls, path) -> Project:
        path = pathlib.Path(path)
        path.mkdir(parents=True, exist_ok=True)
        try:
            return cls(path, _core.Repo.init(str(path)))
        except _core.RepoError as e:
            raise KimcadError(str(e)) from None

    @classmethod
    def open(cls, path) -> Project:
        path = pathlib.Path(path)
        try:
            return cls(path, _core.Repo.open(str(path)))
        except _core.RepoError as e:
            raise NotAProject(str(e)) from None

    # ---- helpers ----
    def _rev(self, rev: str) -> str:
        if self.repo.head() is None:
            raise NoVersions("this project has no versions yet (use `kimcad commit <file.ifc>`)")
        try:
            return self.repo.resolve(rev)
        except _core.RepoError:
            raise UnknownRevision(f"unknown version: {rev}") from None

    def _entries(self, rev: str) -> dict[str, str]:
        return self.repo.tree_entries(self._rev(rev))

    def _records(self, rev: str) -> dict[str, bytes]:
        entries = {p: o for p, o in self._entries(rev).items() if p != SETTINGS_PATH}
        paths = sorted(entries)
        blobs = self.repo.read_blobs([entries[p] for p in paths])
        return {path_to_key(p): b for p, b in zip(paths, blobs)}

    def settings_at(self, rev: str = "HEAD") -> bytes | None:
        """The project settings stored with a version (None for versions made before step 2)."""
        if self.repo.head() is None:
            return None
        oid = self._entries(rev).get(SETTINGS_PATH)
        return self.repo.read_blobs([oid])[0] if oid else None

    def _head_entries(self) -> dict[str, str]:
        head = self.repo.head()
        return self.repo.tree_entries(head) if head else {}

    def schema(self) -> str | None:
        entries = self._head_entries()
        if META_PATH not in entries:
            return None
        return json.loads(self.repo.read_blobs([entries[META_PATH]])[0])["schema"]

    def _changes(self, old_entries: dict[str, str], new: dict[str, bytes],
                 settings: bytes | None = None) -> tuple[Changes, dict[str, bytes | None]]:
        old_settings = old_entries.get(SETTINGS_PATH)
        old_entries = {p: o for p, o in old_entries.items() if p != SETTINGS_PATH}
        new_paths = {key_to_path(k): v for k, v in new.items()}
        writes: dict[str, bytes | None] = {}
        added, modified, removed = [], [], []
        for p, data in new_paths.items():
            old = old_entries.get(p)
            if old is None:
                added.append(p)
                writes[p] = data
            elif old != blob_oid(data):
                modified.append(p)
                writes[p] = data
        for p in old_entries:
            if p not in new_paths:
                removed.append(p)
                writes[p] = None
        old_blobs = dict(zip(removed, self.repo.read_blobs([old_entries[p] for p in removed]))) if removed else {}
        items = []
        for kind, paths in (("added", added), ("modified", modified), ("removed", removed)):
            for p in sorted(paths):
                key = path_to_key(p)
                ifc_type, name = _describe(key, old_blobs[p] if kind == "removed" else new_paths[p])
                items.append(Change(kind, key, ifc_type, name))
        if settings is not None and old_settings != blob_oid(settings):
            writes[SETTINGS_PATH] = settings
            items.append(Change("added" if old_settings is None else "modified", "settings", "(project settings)", None))
        return Changes(items), writes

    def _decompose_file(self, ifc_path) -> dict[str, bytes]:
        f = ifcopenshell.open(str(ifc_path))
        current = self.schema()
        if current and f.schema_identifier != current:
            raise SchemaMismatch(
                f"{ifc_path} is {f.schema_identifier} but this project is {current}; "
                "KIMCAD never converts schemas silently (docs/02, D30)"
            )
        bad = [r for r in f.by_type("IfcRoot") if not GLOBALID.fullmatch(r.GlobalId or "")]
        if bad:
            raise InvalidInput(
                f"{ifc_path} has {len(bad)} malformed GlobalId(s); KIMCAD needs valid IFC GlobalIds to track objects",
                [f"#{r.id()} {r.is_a()}: GlobalId {r.GlobalId!r}" for r in bad[:50]],
            )
        records, _ = decompose_against_head(f, self._head_entries(), self.repo.read_blobs)
        try:
            compose(records)  # records must be writable back to IFC (lossless guarantee, D36)
        except RuntimeError as e:
            log = ifcopenshell.validate.json_logger()
            ifcopenshell.validate.validate(f, log)
            messages = [str(s.get("message", s)) for s in log.statements] or [str(e)]
            raise InvalidInput(
                f"{ifc_path} is not valid {f.schema_identifier} and cannot be stored losslessly", messages
            ) from None
        return records

    # ---- commands ----
    def status(self, ifc_path, settings: bytes | None = None) -> Changes:
        changes, _ = self._changes(self._head_entries(), self._decompose_file(ifc_path), settings)
        return changes

    def commit(self, ifc_path, message: str, *, author: tuple[str, str] | None = None, time: int | None = None,
               merged: list[str] | None = None, settings: bytes | None = None):
        """A new version from an IFC file; `merged`: other versions it combines (a merge commit, which
        is recorded even when the result equals the current version)."""
        records = self._decompose_file(ifc_path)
        changes, writes = self._changes(self._head_entries(), records, settings)
        if not changes and not merged:
            raise NothingToCommit("nothing to commit: the file matches the current version")
        name, email = author or _author()
        when = int(time if time is not None else _time.time())
        if merged:
            try:
                cid = self.repo.commit_merge(writes, message, name, email, when, list(merged))
            except _core.RepoError as e:
                raise KimcadError(str(e)) from None
        else:
            cid = self.repo.commit(writes, message, name, email, when)
        if len(writes) > REPACK_THRESHOLD:
            self.repo.repack_no_delta()
        return cid, changes

    def log(self, rev: str = "HEAD", limit: int = 50):
        if self.repo.head() is None:
            return []
        return self.repo.log(self._rev(rev), limit)

    def diff(self, rev_a: str | None = None, rev_b: str = "HEAD") -> Changes:
        b = self._rev(rev_b)
        if rev_a is None:
            parents = self.repo.log(b, 1)[0].parents
            old = self.repo.tree_entries(parents[0]) if parents else {}
        else:
            old = self._entries(rev_a)
        changes, _ = self._changes(old, self._records(b), self.settings_at(b))
        return changes

    def export(self, out_path, rev: str = "HEAD", overwrite: bool = False, one_owner: bool = False) -> pathlib.Path:
        """Write a version as IFC. `one_owner`: give each owner its own copy of values IFC wants owned
        once (D70; the app and the CLI use it). Off by default: the bytes are then exactly compose()'s,
        which the golden reference hashes pin."""
        out = pathlib.Path(out_path)
        records = self._records(rev)
        if out.exists() and not overwrite:
            raise TargetExists(f"{out} already exists (use --force to overwrite)")
        f = compose(records)
        if one_owner:
            unshare(f)  # one owner where IFC requires it (records hash-cons identical values)
        f.write(str(out))
        return out

    def show(self, key: str, rev: str = "HEAD") -> dict:
        entries = self._entries(rev)
        p = key_to_path(key)
        if p not in entries:
            raise KimcadError(f"no record {key} in {rev}")
        return json.loads(self.repo.read_blobs([entries[p]])[0])

    def branches(self) -> list[str]:
        return self.repo.branches()

    def current_branch(self) -> str:
        return self.repo.current_branch()

    def create_branch(self, name: str, rev: str = "HEAD"):
        target = self._rev(rev)
        try:
            self.repo.create_branch(name, target)
        except _core.RepoError as e:
            raise KimcadError(str(e)) from None

    def switch(self, name: str):
        try:
            self.repo.switch(name)
        except _core.RepoError as e:
            raise KimcadError(str(e)) from None

    def delete_branch(self, name: str):
        try:
            self.repo.delete_branch(name)
        except _core.RepoError as e:
            raise KimcadError(str(e)) from None

    # ---- milestones (annotated tags) ----
    def tag(self, name: str, message: str, rev: str = "HEAD", *, author: tuple[str, str] | None = None,
            time: int | None = None):
        target = self._rev(rev)
        tagger, email = author or _author()
        try:
            self.repo.create_tag(name, target, message or name, tagger, email, int(time if time is not None else _time.time()))
        except _core.RepoError as e:
            raise KimcadError(str(e)) from None

    def tags(self):
        return self.repo.tags()

    def delete_tag(self, name: str):
        try:
            self.repo.delete_tag(name)
        except _core.RepoError as e:
            raise KimcadError(str(e)) from None

    # ---- object history ("blame", docs/03) ----
    def history_of(self, main: str, related: set[str] = frozenset(), rev: str = "HEAD", limit: int = 100):
        """[(commit, "added" | "modified" | "removed")] for the commits (first-parent chain, newest
        first) that changed the record at path `main` or any `related` one (e.g. its property sets);
        added/removed refer to `main`."""
        paths = {main, *related}
        if self.repo.head() is None:
            return []
        commits = self.repo.log(self._rev(rev), limit)
        out = []
        cache: dict[str, dict[str, str]] = {}

        def entries(cid):
            if cid not in cache:
                cache[cid] = {p: o for p, o in self.repo.tree_entries(cid).items() if p in paths}
            return cache[cid]

        for c in commits:
            now = entries(c.id)
            before = entries(c.parents[0]) if c.parents else {}
            if now == before:
                continue
            if main in now and main not in before:
                kind = "added"
            elif main in before and main not in now:
                kind = "removed"
            else:
                kind = "modified"
            out.append((c, kind))
        return out

    # ---- combining options (R4 merge) ----
    def merge_preview(self, other: str, resolutions: dict | None = None) -> MergePreview:
        """What combining `other` into the current option would do; for a real merge, the merged records
        and the conflicts (with `resolutions` applied)."""
        from .merge import merge_records

        ours, theirs = self._rev("HEAD"), self._rev(other)
        base = self.repo.merge_base(ours, theirs)
        if base == theirs:
            return MergePreview("up_to_date", base, ours, theirs)
        if base == ours:
            return MergePreview("fast_forward", base, ours, theirs)
        base_records = self._records(base) if base else {}
        result = merge_records(base_records, self._records(ours), self._records(theirs), resolutions)
        from . import settings as S

        sides = [self.settings_at(r) if r else None for r in (base, ours, theirs)]
        merged_settings, conflicts = None, []
        if any(s is not None for s in sides):
            merged, conflicts = S.merge(*[S.from_bytes(s) for s in sides])
            merged_settings = S.to_bytes(merged)
        return MergePreview("merge", base, ours, theirs, result, merged_settings, conflicts)

    def merge(self, other: str, message: str, resolutions: dict | None = None, *,
              author: tuple[str, str] | None = None, time: int | None = None) -> str:
        """Combine `other` into the current option: fast-forward, or a merge commit with two parents.
        Raises MergeConflicts while conflicts remain unresolved."""
        preview = self.merge_preview(other, resolutions)
        if preview.status == "up_to_date":
            return preview.ours
        if preview.status == "fast_forward":
            try:
                return self.repo.fast_forward(preview.theirs)
            except _core.RepoError as e:
                raise KimcadError(str(e)) from None
        if not preview.result.clean:
            raise MergeConflicts(preview.result)
        compose(preview.result.records)  # the result must be writable as IFC (lossless guarantee)
        _changes, writes = self._changes(self._head_entries(), preview.result.records, preview.settings)
        name, email = author or _author()
        try:
            return self.repo.commit_merge(writes, message, name, email,
                                          int(time if time is not None else _time.time()), [preview.theirs])
        except _core.RepoError as e:
            raise KimcadError(str(e)) from None

