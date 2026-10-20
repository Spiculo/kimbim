# SPDX-License-Identifier: GPL-3.0-or-later
"""`kimbim` command line (docs/03-versioning.md#cli)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

from . import _core
from .layout import key_to_path
from .project import Changes, KimbimError, MergeConflicts, Project

SYMBOL = {"added": "+", "modified": "~", "removed": "-"}
MAX_LINES = 200


def _print_changes(changes: Changes, as_json: bool = False):
    if as_json:
        data = {k: [vars(c) for c in changes.of(k)] for k in ("added", "modified", "removed")}
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return
    print(f"{len(changes.added)} added, {len(changes.modified)} modified, {len(changes.removed)} removed")
    for c in changes.items[:MAX_LINES]:
        name = f" {c.name!r}" if c.name else ""
        print(f"  {SYMBOL[c.kind]} {c.ifc_type}{name}  [{c.key}]")
    if len(changes.items) > MAX_LINES:
        print(f"  ... {len(changes.items) - MAX_LINES} more (use --json for all)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kimbim", description="Versioned IFC projects.")
    p.add_argument("-C", dest="project", default=".", help="project directory (default: current)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="create a project")
    s.add_argument("dir", nargs="?")
    s = sub.add_parser("commit", help="save an IFC file as a new version")
    s.add_argument("file")
    s.add_argument("-m", "--message", required=True)
    s = sub.add_parser("status", help="show what committing an IFC file would change")
    s.add_argument("file")
    s = sub.add_parser("log", help="list versions")
    s.add_argument("rev", nargs="?", default="HEAD")
    s.add_argument("-n", type=int, default=50)
    s = sub.add_parser("diff", help="compare versions (default: last version vs its parent)")
    s.add_argument("rev_a", nargs="?")
    s.add_argument("rev_b", nargs="?", default="HEAD")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("export", help="write a version as IFC, or its drawings and sheets as DXF")
    s.add_argument("out", help="IFC file; with --format dxf a folder (or a .dxf file for one drawing or sheet)")
    s.add_argument("--rev", default="HEAD")
    s.add_argument("--force", action="store_true")
    s.add_argument("--format", choices=("ifc", "dxf"), default=None,
                   help="default: dxf when OUT ends in .dxf, else ifc")
    s.add_argument("--drawing", action="append", default=[], metavar="NAME",
                   help="DXF: a drawing to export, by name (repeatable; default every drawing and sheet)")
    s.add_argument("--sheet", action="append", default=[], metavar="NUMBER",
                   help="DXF: a sheet to export, by number (repeatable)")
    s.add_argument("--layers", choices=("layer", "kind"), default="layer",
                   help="DXF layers by KimBim layer (default) or by element kind")
    s.add_argument("--purpose", default="", help="DXF: the purpose (pens, visibility) to draw with")
    s = sub.add_parser("show", help="print one canonical record")
    s.add_argument("key")
    s.add_argument("--rev", default="HEAD")
    s = sub.add_parser("branch", help="list or create design options (branches)")
    s.add_argument("name", nargs="?")
    s.add_argument("--rev", default="HEAD")
    s = sub.add_parser("switch", help="switch to a design option (branch)")
    s.add_argument("name")
    s = sub.add_parser("tag", help="list, set or delete milestones (annotated tags)")
    s.add_argument("name", nargs="?")
    s.add_argument("-m", "--message", default="")
    s.add_argument("--rev", default="HEAD")
    s.add_argument("--delete", action="store_true")
    s = sub.add_parser("merge", help="combine another design option into the current one")
    s.add_argument("option")
    s.add_argument("-m", "--message", default="")
    s.add_argument("--resolve", action="append", default=[], metavar="CONFLICT=CHOICE",
                   help="a conflict's choice (ours, theirs, or one of its options); repeatable")
    s.add_argument("--json", action="store_true", help="print the conflicts as JSON")
    s = sub.add_parser("blame", help="object history: the versions that changed an object (by GlobalId)")
    s.add_argument("guid")
    s.add_argument("--rev", default="HEAD")
    s.add_argument("-n", type=int, default=100)
    return p


def run(args) -> int:
    if args.cmd == "init":
        target = pathlib.Path(args.dir or args.project)
        Project.init(target)
        print(f"Initialized KimBim project in {target.resolve()}")
        return 0
    proj = Project.open(args.project)
    if args.cmd == "commit":
        cid, changes = proj.commit(args.file, args.message)
        print(f"[{proj.current_branch()} {cid[:10]}] {args.message}")
        _print_changes(changes)
    elif args.cmd == "status":
        changes = proj.status(args.file)
        if changes:
            _print_changes(changes)
        else:
            print("no changes")
    elif args.cmd == "log":
        commits = proj.log(args.rev, args.n)
        if not commits:
            print("no versions yet")
        for c in commits:
            when = dt.datetime.fromtimestamp(c.time, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            first_line = (c.message.strip().splitlines() or [""])[0]
            print(f"{c.id[:10]}  {when}  {c.author_name}  {first_line}")
    elif args.cmd == "diff":
        _print_changes(proj.diff(args.rev_a, args.rev_b), as_json=args.json)
    elif args.cmd == "export":
        if (args.format or ("dxf" if args.out.lower().endswith(".dxf") else "ifc")) == "dxf":
            return _export_dxf(proj, args)
        out = proj.export(args.out, args.rev, overwrite=args.force, one_owner=True)
        print(f"wrote {out}")
    elif args.cmd == "show":
        print(json.dumps(proj.show(args.key, args.rev), ensure_ascii=False, indent=1, sort_keys=True))
    elif args.cmd == "branch":
        if args.name:
            proj.create_branch(args.name, args.rev)
            print(f"created design option {args.name}")
        else:
            current = proj.current_branch()
            for b in proj.branches():
                print(f"{'*' if b == current else ' '} {b}")
    elif args.cmd == "switch":
        proj.switch(args.name)
        print(f"switched to {args.name}")
    elif args.cmd == "tag":
        if args.name and args.delete:
            proj.delete_tag(args.name)
            print(f"deleted milestone {args.name}")
        elif args.name:
            proj.tag(args.name, args.message, args.rev)
            print(f"milestone {args.name} on {proj.repo.resolve(args.rev)[:10]}")
        else:
            for t in proj.tags():
                first_line = (t.message.strip().splitlines() or [""])[0]
                print(f"{t.name}  {t.target[:10]}  {first_line}")
    elif args.cmd == "merge":
        resolutions = dict(r.rsplit("=", 1) for r in args.resolve if "=" in r)
        message = args.message or f"Combine {args.option} into {proj.current_branch()}"
        try:
            cid = proj.merge(args.option, message, resolutions)
        except MergeConflicts as e:
            conflicts = [c.to_dict() for c in e.result.conflicts if c.id in e.result.unresolved]
            if args.json:
                print(json.dumps(conflicts, ensure_ascii=False, indent=1, default=str))
            else:
                print(f"{len(conflicts)} conflict(s); choose with --resolve ID=CHOICE:")
                for c in conflicts:
                    what = c["attribute"] or ""
                    if c["property"]:
                        what += f"[{c['property']}]"
                    print(f"  {c['id']}  {c['kind']}  {c['ifc_type']} {c['name']!r} {what}  options: {', '.join(c['options'])}")
                    if c["kind"] in ("attribute", "property", "class"):
                        print(f"      base {json.dumps(c['base'], default=str)[:80]}  ours {json.dumps(c['ours'], default=str)[:80]}"
                              f"  theirs {json.dumps(c['theirs'], default=str)[:80]}")
            return 1
        print(f"[{proj.current_branch()} {cid[:10]}] {message}")
    elif args.cmd == "blame":
        steps = proj.history_of(key_to_path("o/" + args.guid), rev=args.rev, limit=args.n)
        if not steps:
            print(f"no version changed {args.guid}")
        for c, kind in steps:
            when = dt.datetime.fromtimestamp(c.time, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            first_line = (c.message.strip().splitlines() or [""])[0]
            print(f"{SYMBOL[kind]} {kind:<8}  {c.id[:10]}  {when}  {c.author_name}  {first_line}")
    return 0


def _export_dxf(proj: Project, args) -> int:
    """Drawings and sheets of a version as DXF files (D83): the version is written to a temporary IFC,
    opened the way the app opens it, and exported with the built-in graphics (or --purpose)."""
    import tempfile

    from . import app_bridge, dxf

    with tempfile.TemporaryDirectory(prefix="kimbim-dxf-") as tmp:
        ifc = proj.export(pathlib.Path(tmp) / "version.ifc", args.rev, overwrite=True, one_owner=True)
        opened = json.loads(app_bridge.open_model(str(ifc)))
    if not opened.get("ok"):
        raise KimbimError(opened.get("error", "could not open the version"))
    targets = json.loads(dxf.dxf_targets())
    by_name = {d["name"]: d["guid"] for d in targets["drawings"]}
    numbers = {s["number"] for s in targets["sheets"]}
    missing = [n for n in args.drawing if n not in by_name] + [n for n in args.sheet if n not in numbers]
    if missing:
        raise KimbimError(f"no drawing or sheet called {', '.join(missing)} in {args.rev}")
    items = [{"drawing": by_name[n]} for n in args.drawing] + [{"sheet": n} for n in args.sheet]
    if not items:
        items = [{"drawing": d["guid"]} for d in targets["drawings"]] + [{"sheet": s["number"]} for s in targets["sheets"]]
    if not items:
        raise KimbimError(f"{args.rev} has no drawings or sheets")
    options = json.dumps({"layers": args.layers, "purpose": args.purpose or None})
    out = pathlib.Path(args.out)
    if out.suffix.lower() == ".dxf":
        if len(items) != 1:
            raise KimbimError("a .dxf file holds one drawing or sheet; give a folder for more")
        if out.exists() and not args.force:
            raise KimbimError(f"{out} already exists (use --force to overwrite)")
        item = items[0]
        r = json.loads(dxf.export_drawing_dxf(item["drawing"], str(out), options) if "drawing" in item
                       else dxf.export_sheet_dxf(item["sheet"], str(out), options))
        files, errors = ([r["path"]], []) if r.get("ok") else ([], [{"item": str(out), "error": r.get("error")}])
    else:
        r = json.loads(dxf.export_dxf(json.dumps(items), str(out), options))
        if "files" not in r:
            raise KimbimError(r.get("error", "export failed"))
        files, errors = r["files"], r["errors"]
    for f in files:
        print(f"wrote {f}")
    for e in errors:
        print(f"kimbim: error: {e['item']}: {e['error']}", file=sys.stderr)
    return 1 if errors else 0


def _utf8_streams():
    """Names can be in any script; Windows pipes default to the legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KimbimError as e:
        print(f"kimbim: error: {e}", file=sys.stderr)
        for m in getattr(e, "messages", [])[:20]:
            print(f"  {m}", file=sys.stderr)
        return 1
    except (OSError, _core.RepoError) as e:
        print(f"kimbim: error: {e}", file=sys.stderr)
        return 1
