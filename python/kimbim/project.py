# SPDX-License-Identifier: GPL-3.0-or-later
"""A KimBim project: IFC versions stored as canonical records in Git (docs/03-versioning.md)."""
from __future__ import annotations

import json
import os
import re
import pathlib
import subprocess
import tempfile
import time as _time
from dataclasses import dataclass, field

import ifcopenshell
import ifcopenshell.validate

from . import _core
from .content import Changed, Contents, references, schema_of, without_owner_history
from .layout import (CHECKS_PATH, META_PATH, SETTINGS_PATH, WORK_FILES_DIR, blob_oid, is_file_path, is_record_path,
                     key_to_path, path_to_key, referenced_files)
from .nodeids import decompose_against_head
from .records import compose, unshare

REPACK_THRESHOLD = 10_000  # changed records; D39
GLOBALID = re.compile(r"[0-9A-Za-z_$]{22}")  # IFC GlobalId: 22 chars of the IFC base-64 alphabet


class KimbimError(Exception):
    pass


class NotAProject(KimbimError):
    pass


class NothingToCommit(KimbimError):
    pass


class SchemaMismatch(KimbimError):
    pass


class NoVersions(KimbimError):
    pass


class UnknownRevision(KimbimError):
    pass


class TargetExists(KimbimError):
    pass


class MergeConflicts(KimbimError):
    def __init__(self, result):
        super().__init__(f"{len(result.unresolved)} conflict(s) to resolve before combining")
        self.result = result


class InvalidInput(KimbimError):
    def __init__(self, message: str, messages: list[str]):
        super().__init__(message)
        self.messages = messages


@dataclass
class MergePreview:
    status: str  # "up_to_date" | "fast_forward" | "merge"
    base: str | None
    ours: str
    theirs: str
    result: object = None  # kimbim.merge.MergeResult for "merge"
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


def _by_content(old_entries: dict[str, str], old_blobs: dict[str, bytes], read_blobs, new_paths: dict[str, bytes],
                new_oids: dict[str, str], added: list[str], modified: list[str], removed: list[str]):
    """The record changes by content (kimbim.content, Task 11b): a record only re-encoded (a value it
    shares became a node, so its reference changed) is not modified; an element or loose value whose
    shared value was edited in place (same bytes, same node id) is. Loose values re-keyed by a
    re-encoding cancel out. Owner histories are bookkeeping, not content. Shared values (n/) keep their
    own entries when their bytes change: they are storage, reported as such. Returns (added, modified,
    removed) paths."""
    def old_get(key):
        p = key_to_path(key)
        oid = old_entries.get(p)
        if oid is None:
            return None
        if new_oids.get(p) == oid:
            return new_paths[p]
        if p not in old_blobs:
            old_blobs[p] = read_blobs([oid])[0]
        return old_blobs[p]

    def new_get(key):
        return new_paths.get(key_to_path(key))

    schema = schema_of(new_get("meta") or old_get("meta"))
    old_c, new_c = Contents(old_get, schema), Contents(new_get, schema)
    changed = Changed(old_c, new_c)

    def content(p: str) -> bool:
        return p.startswith(("objects/", "nodes/", "loose/"))

    def same(p: str) -> bool:
        key = path_to_key(p)
        if without_owner_history(json.loads(old_get(key))) == without_owner_history(json.loads(new_paths[p])):
            return not changed.record(key, new_paths[p])  # a common case: only its owner history re-encoded
        return old_c.record(key) == new_c.record(key)

    # Fast path (R3): when the change touches only object records and none of them carries an anchor
    # value another record can refer to, no unchanged record can have changed through it. Property and
    # name edits take this path, so their diff does not walk the whole model.
    if not any(p.startswith(("nodes/", "loose/")) for p in added + modified + removed) and \
            not any(p.startswith("objects/") and (b'"@a"' in old_blobs.get(p, b"") or b'"@a"' in new_paths[p])
                    for p in modified):
        kept = [p for p in modified if not content(p) or not same(p)]
        return added, kept, removed

    kept = [p for p in modified if not content(p) or not same(p)]
    touched = set(modified)
    for p in new_paths:  # same bytes, but a shared value it uses changed
        if p.startswith(("objects/", "loose/")) and p not in touched and p in old_entries and \
                changed.record(path_to_key(p), new_paths[p]):
            kept.append(p)
    gone: dict[str, list[str]] = {}
    for p in removed:
        if p.startswith("loose/"):
            gone.setdefault(old_c.record(path_to_key(p)), []).append(p)
    still_added, rekeyed = [], set()
    for p in added:
        if p.startswith("loose/") and gone.get(d := new_c.record(path_to_key(p))):
            rekeyed.add(gone[d].pop())
        else:
            still_added.append(p)
    return still_added, kept, [p for p in removed if p not in rekeyed]


_AUTHOR: tuple[str, str] | None = None  # set by the app from its preferences (documents.set_author)


def _author() -> tuple[str, str]:
    if _AUTHOR is not None:
        return _AUTHOR
    name = os.environ.get("KIMBIM_AUTHOR_NAME") or _git_config("user.name") or "KimBim User"
    email = os.environ.get("KIMBIM_AUTHOR_EMAIL") or _git_config("user.email") or "user@localhost"
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
            raise KimbimError(str(e)) from None

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
            raise NoVersions("this project has no versions yet (use `kimbim versions save FILE.ifc -m MESSAGE`)")
        try:
            return self.repo.resolve(rev)
        except _core.RepoError:
            raise UnknownRevision(f"unknown version: {rev}") from None

    def _entries(self, rev: str) -> dict[str, str]:
        return self.repo.tree_entries(self._rev(rev))

    def _records(self, rev: str) -> dict[str, bytes]:
        entries = {p: o for p, o in self._entries(rev).items() if is_record_path(p)}
        paths = sorted(entries)
        blobs = self.repo.read_blobs([entries[p] for p in paths])
        return {path_to_key(p): b for p, b in zip(paths, blobs)}

    def settings_at(self, rev: str = "HEAD") -> bytes | None:
        """The project settings stored with a version (None for versions made before step 2)."""
        if self.repo.head() is None:
            return None
        oid = self._entries(rev).get(SETTINGS_PATH)
        return self.repo.read_blobs([oid])[0] if oid else None

    def checks_at(self, rev: str = "HEAD") -> bytes | None:
        """The pre-commit check results stored with a version (None when no check ran)."""
        if self.repo.head() is None:
            return None
        oid = self._entries(rev).get(CHECKS_PATH)
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
        old_files = {p: o for p, o in old_entries.items() if is_file_path(p)}
        old_entries = {p: o for p, o in old_entries.items() if is_record_path(p)}
        new_paths = {key_to_path(k): v for k, v in new.items()}
        new_oids = {p: blob_oid(data) for p, data in new_paths.items()}
        writes: dict[str, bytes | None] = {}
        added, modified, removed = [], [], []
        for p, data in new_paths.items():
            old = old_entries.get(p)
            if old is None:
                added.append(p)
                writes[p] = data
            elif old != new_oids[p]:
                modified.append(p)
                writes[p] = data
        for p in old_entries:
            if p not in new_paths:
                removed.append(p)
                writes[p] = None
        read = removed + modified
        old_blobs = dict(zip(read, self.repo.read_blobs([old_entries[p] for p in read]))) if read else {}
        added, modified, removed = _by_content(old_entries, old_blobs, self.repo.read_blobs, new_paths, new_oids,
                                               added, modified, removed)
        items = []
        for kind, paths in (("added", added), ("modified", modified), ("removed", removed)):
            for p in sorted(paths):
                key = path_to_key(p)
                ifc_type, name = _describe(key, old_blobs[p] if kind == "removed" else new_paths[p])
                items.append(Change(kind, key, ifc_type, name))
        if settings is not None and old_settings != blob_oid(settings):
            writes[SETTINGS_PATH] = settings
            items.append(Change("added" if old_settings is None else "modified", "settings", "(project settings)", None))
        if settings is not None:
            writes.update(self._file_writes(old_files, referenced_files(settings)))
        return Changes(items), writes

    def _file_writes(self, old_files: dict[str, str], wanted: set[str]) -> dict[str, bytes | None]:
        """The files (D85: underlays) a version's settings use: new ones from the working folder (or, made
        in another option, from the repository by their blob id, which is their name); unused ones go. A
        file found nowhere is left out (the settings still name it; the app reports it missing)."""
        writes: dict[str, bytes | None] = {p: None for p in old_files if p not in wanted}
        for p in sorted(wanted - set(old_files)):
            name = p.split("/", 1)[1]
            local = self.path / WORK_FILES_DIR / name
            data = None
            if local.is_file():
                data = local.read_bytes()
            else:
                try:
                    data = self.repo.read_blobs([name.split(".")[0]])[0]
                except _core.RepoError:
                    data = None
            if data is not None and blob_oid(data) == name.split(".")[0]:
                writes[p] = data
        return writes

    def _decompose_file(self, ifc_path) -> dict[str, bytes]:
        f = ifcopenshell.open(str(ifc_path))
        current = self.schema()
        if current and f.schema_identifier != current:
            raise SchemaMismatch(
                f"{ifc_path} is {f.schema_identifier} but this project is {current}; "
                "KimBim never converts schemas silently (docs/02, D30)"
            )
        bad = [r for r in f.by_type("IfcRoot") if not GLOBALID.fullmatch(r.GlobalId or "")]
        if bad:
            raise InvalidInput(
                f"{ifc_path} has {len(bad)} malformed GlobalId(s); KimBim needs valid IFC GlobalIds to track objects",
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
               merged: list[str] | None = None, settings: bytes | None = None, checks: bytes | None = None,
               records: dict[str, bytes] | None = None):
        """A new version from an IFC file; `merged`: other versions it combines (a merge commit, which
        is recorded even when the result equals the current version). `checks`: the pre-commit check
        results to record with the version (M6); None leaves no checks.json in the tree. `records`: an
        already decomposed working model (the app caches it between Compare and Save version)."""
        head = self._head_entries()
        if records is None:
            records = self._decompose_file(ifc_path)
        changes, writes = self._changes(head, records, settings)
        if not changes and not merged and not any(is_record_path(p) for p in writes):
            raise NothingToCommit("nothing to commit: the file matches the current version")
        if checks is not None:
            writes[CHECKS_PATH] = checks
        elif CHECKS_PATH in head:
            writes[CHECKS_PATH] = None
        name, email = author or _author()
        when = int(time if time is not None else _time.time())
        if merged:
            try:
                cid = self.repo.commit_merge(writes, message, name, email, when, list(merged))
            except _core.RepoError as e:
                raise KimbimError(str(e)) from None
        else:
            cid = self.repo.commit(writes, message, name, email, when)
        if len(writes) > REPACK_THRESHOLD:
            self.repo.repack_no_delta()
        return cid, changes

    def import_ifc(self, ifc_path, message: str, *, accept_heuristic: bool = False, dry_run: bool = False,
                   author: tuple[str, str] | None = None) -> dict:
        """Re-import an IFC, reconciling its products with the current version's before committing.

        `dry_run` returns the report without writing anything. Otherwise matched imported objects take
        the existing GlobalIds (Tag and, if accepted, heuristic matches) and the result is one ordinary
        commit, so their history and Compare keep working.
        """
        from .reconcile import reconcile

        if self.repo.head() is None:
            raise NoVersions("this project has no versions yet")
        new = ifcopenshell.open(str(ifc_path))
        current = self.schema()
        if current and new.schema_identifier != current:
            raise SchemaMismatch(
                f"{ifc_path} is {new.schema_identifier} but this project is {current}; "
                "KimBim never converts schemas silently (docs/02, D30)"
            )
        old = compose(self._records("HEAD"))
        report = reconcile(old, new, accept_heuristic)
        applied = report.pop("applied", {})
        if dry_run:
            return report
        entities = {guid: new.by_guid(guid) for guid in applied}
        for guid, entity in entities.items():
            entity.GlobalId = applied[guid]
        fd, path = tempfile.mkstemp(suffix=".ifc", prefix="kimbim-import-")
        os.close(fd)
        try:
            new.write(path)
            cid, changes = self.commit(path, message, author=author)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        report.update({"id": cid, "added": len(changes.added), "modified": len(changes.modified),
                       "removed": len(changes.removed)})
        return report

    def log(self, rev: str = "HEAD", limit: int = 50):
        if self.repo.head() is None:
            return []
        return self.repo.log(self._rev(rev), limit)

    def diff(self, rev_a: str | None = None, rev_b: str = "HEAD") -> Changes:
        b = self._rev(rev_b)
        if rev_a is None:
            parents = self.repo.log(b, 1)[0].parents
            a = parents[0] if parents else b
        else:
            a = self._rev(rev_a)
        return self._diff_entries(a, b)

    def _diff_entries(self, rev_a: str, rev_b: str) -> Changes:
        """A diff that reads only the changed records when nothing shared could have changed (R3).

        The tree diff skips identical subtrees. A property or name edit touches object records only,
        and those records carry no anchor value another record can refer to, so no unchanged record
        can differ. Node/loose changes or anchors fall back to the full content pass in `_changes`.
        """
        rows = [r for r in self.repo.diff_entries(rev_a, rev_b) if is_record_path(r[0])]
        added = [p for p, old, _new in rows if old is None]
        removed = [p for p, _old, new in rows if new is None]
        modified = [(p, old, new) for p, old, new in rows if old is not None and new is not None]
        changed = added + [p for p, _, _ in modified] + removed
        if not changed:
            settings = self.repo.read_blob_at(rev_b, SETTINGS_PATH)
            old_settings = self.repo.read_blob_at(rev_a, SETTINGS_PATH)
            items = []
            if settings is not None and settings != old_settings:
                items.append(Change("added" if old_settings is None else "modified", "settings",
                                    "(project settings)", None))
            return Changes(items)
        if any(p.startswith(("nodes/", "loose/")) for p in changed):
            return self._changes(self._entries(rev_a), self._records(rev_b), self.settings_at(rev_b))[0]

        old_paths = [p for p, old, _new in rows if old]
        new_paths = [p for p, _old, new in rows if new]
        old_data = dict(zip(old_paths, self.repo.read_blobs([old for _p, old, _n in rows if old]))) if old_paths else {}
        new_data = dict(zip(new_paths, self.repo.read_blobs([new for _p, _o, new in rows if new]))) if new_paths else {}
        if any(references(old_data[p]) != references(new_data[p]) for p, _, _ in modified):
            return self._changes(self._entries(rev_a), self._records(rev_b), self.settings_at(rev_b))[0]

        # Content digests only for the modified records; nodes they reference are read on demand.
        meta = self.repo.read_blob_at(rev_b, META_PATH) or self.repo.read_blob_at(rev_a, META_PATH)
        schema = schema_of(meta)

        def getter(rev, cache):
            def get(key):
                path = key_to_path(key)
                if path in cache:
                    return cache[path]
                data = self.repo.read_blob_at(rev, path)
                cache[path] = data
                return data
            return get

        old_c = Contents(getter(rev_a, {}), schema)
        new_c = Contents(getter(rev_b, {}), schema)
        kept = []
        for p, _old, _new in modified:
            key = path_to_key(p)
            before, after = json.loads(old_data[p]), json.loads(new_data[p])
            if without_owner_history(before) == without_owner_history(after) and old_c.record(key) == new_c.record(key):
                continue
            kept.append(p)
        items = []
        for kind, paths in (("added", added), ("modified", kept), ("removed", removed)):
            for p in sorted(paths):
                key = path_to_key(p)
                ifc_type, name = _describe(key, old_data[p] if kind == "removed" else new_data[p])
                items.append(Change(kind, key, ifc_type, name))
        settings = self.repo.read_blob_at(rev_b, SETTINGS_PATH)
        old_settings = self.repo.read_blob_at(rev_a, SETTINGS_PATH)
        if settings is not None and settings != old_settings:
            items.append(Change("added" if old_settings is None else "modified", "settings",
                                "(project settings)", None))
        return Changes(items)

    def diff_details(self, rev_a: str | None = None, rev_b: str = "HEAD", *,
                     working_records: dict[str, bytes] | None = None) -> dict:
        """`diff()` plus the property-level explanation, categories and the level tree (R3)."""
        from .diff import changes_by_element

        if working_records is not None:
            a = self._rev(rev_a) if rev_a else self._rev("HEAD")
            b = "WORKING"
            changes, _ = self._changes(self._entries(a), working_records, None)
            out = changes_by_element(self, a, b, changes, new_records=working_records)
        else:
            changes = self.diff(rev_a, rev_b)
            b = self._rev(rev_b)
            if rev_a is None:
                parents = self.repo.log(b, 1)[0].parents
                a = parents[0] if parents else b
            else:
                a = self._rev(rev_a)
            out = changes_by_element(self, a, b, changes)

        products = out.pop("elements")
        detail_keys = {f"o/{item['guid']}" for kind in products for item in products[kind]}
        out.update({"from": a, "to": b, "changes": products,
                    "other": sum(1 for c in changes.items if c.key not in detail_keys and c.key != "settings"),
                    "settings": [c.key for c in changes.items if c.key == "settings"]})
        return out

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
            raise KimbimError(f"no record {key} in {rev}")
        return json.loads(self.repo.read_blobs([entries[p]])[0])

    # ---- remotes (R4 follow-up: push/pull over Git) ----
    def _git(self, *args: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        result = subprocess.run(["git", f"--git-dir={self.path / '.git'}", *args],
                                capture_output=True, text=True, env=env)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "git failed").strip().splitlines()[-1]
            raise KimbimError(f"git {args[0]}: {message}")
        return result

    def remotes(self) -> list[dict]:
        """Configured remotes: [{"name", "url"}]."""
        out = self._git("remote", "-v").stdout.splitlines()
        seen = {}
        for line in out:
            parts = line.split()
            if len(parts) >= 2 and parts[0] not in seen:
                seen[parts[0]] = parts[1]
        return [{"name": name, "url": url} for name, url in seen.items()]

    def add_remote(self, name: str, url: str) -> None:
        name, url = (name or "").strip(), (url or "").strip()
        if not name or not url or any(c in name for c in " ~^:?*[\\"):
            raise KimbimError("a remote needs a simple name and a URL")
        self._git("remote", "add", name, url)

    def remove_remote(self, name: str) -> None:
        self._git("remote", "remove", name)

    def push(self, remote: str = "origin", branch: str = "") -> dict:
        """Push a branch (the current option by default) to a remote."""
        branch = branch or self.current_branch()
        self._git("push", "--porcelain", remote, f"refs/heads/{branch}:refs/heads/{branch}")
        return {"remote": remote, "branch": branch, "url": next(
            (r["url"] for r in self.remotes() if r["name"] == remote), "")}

    def pull(self, remote: str = "origin", branch: str = "") -> dict:
        """Fetch a remote branch and fast-forward the current one (a diverged branch is refused)."""
        branch = branch or self.current_branch()
        ref = f"refs/remotes/{remote}/{branch}"
        self._git("fetch", "--prune", remote, f"+refs/heads/{branch}:{ref}")
        head = self.head_commit()
        if head is None:
            self._git("update-ref", f"refs/heads/{branch}", ref)
            result = "fast_forward"
        else:
            try:
                self._git("merge-base", "--is-ancestor", head, ref)
            except KimbimError:
                raise KimbimError(
                    f"{branch} has diverged from {remote}/{branch}; push your versions or combine them in an option"
                ) from None
            self._git("update-ref", f"refs/heads/{branch}", ref)
            result = "fast_forward"
        return {"remote": remote, "branch": branch, "status": result, "head": self.head_commit()}

    def head_commit(self) -> str | None:
        return self.repo.head()

    def branches(self) -> list[str]:
        return self.repo.branches()

    def current_branch(self) -> str:
        return self.repo.current_branch()

    def create_branch(self, name: str, rev: str = "HEAD"):
        target = self._rev(rev)
        try:
            self.repo.create_branch(name, target)
        except _core.RepoError as e:
            raise KimbimError(str(e)) from None

    def switch(self, name: str):
        try:
            self.repo.switch(name)
        except _core.RepoError as e:
            raise KimbimError(str(e)) from None

    def delete_branch(self, name: str):
        try:
            self.repo.delete_branch(name)
        except _core.RepoError as e:
            raise KimbimError(str(e)) from None

    # ---- milestones (annotated tags) ----
    def tag(self, name: str, message: str, rev: str = "HEAD", *, author: tuple[str, str] | None = None,
            time: int | None = None):
        target = self._rev(rev)
        tagger, email = author or _author()
        try:
            self.repo.create_tag(name, target, message or name, tagger, email, int(time if time is not None else _time.time()))
        except _core.RepoError as e:
            raise KimbimError(str(e)) from None

    def tags(self):
        return self.repo.tags()

    def delete_tag(self, name: str):
        try:
            self.repo.delete_tag(name)
        except _core.RepoError as e:
            raise KimbimError(str(e)) from None

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
                raise KimbimError(str(e)) from None
        if not preview.result.clean:
            raise MergeConflicts(preview.result)
        compose(preview.result.records)  # the result must be writable as IFC (lossless guarantee)
        _changes, writes = self._changes(self._head_entries(), preview.result.records, preview.settings)
        name, email = author or _author()
        try:
            return self.repo.commit_merge(writes, message, name, email,
                                          int(time if time is not None else _time.time()), [preview.theirs])
        except _core.RepoError as e:
            raise KimbimError(str(e)) from None

