# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent tools exit test (D102 phase 1, spec §11): an AI agent widens the sample house's first-floor windows
through MCP only, and the architect's model is untouched until they accept.

The house is imported into a versioned .kim; an in-process MCP client (the SDK's, as an AI client would connect)
finds the windows on Level 1, starts the task "Widen first-floor windows", makes them 50 cm wider, takes a
snapshot coloured by the task's changes and finishes the task. The worker is then shut down (it saves the .kim)
and the history is read with `Project`: the option agent/widen-first-floor-windows holds one new version whose
difference from main is exactly those 4 windows at 1.7 m wide (only their openings and host walls may also
appear), main's head has not moved, and the snapshot is a real picture (a PNG with at least 100 colours).

Timing run on a big model (the numbers go in docs/17-agent-tools.md): `--project P.kim` works on that .kim (made
from IFC on the first run, then reused) and `--windows N` widens any N windows instead of Level 1's. When fewer
than N fit their wall 50 cm wider (none of the Clinic's Revit windows do: their openings aren't where KimBim's own
are), the write is timed as renaming N windows and the JSON line says so (`"write": "rename"`). On the Clinic the
run stops at the `changes: "task"` snapshot: its compare takes minutes, longer than the client's 120 s wait.

Usage: python tools/check_agent.py IFC OUT_DIR [--project P.kim] [--windows N]   (one JSON line; exit 1 on failure)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

TITLE = "Widen first-floor windows"
OPTION = "agent/widen-first-floor-windows"
WIDER = 0.5  # metres: "+50cm"
HOUSE_WIDTH = 1.7  # the house's 1.2 m windows, widened
MAY_ALSO_CHANGE = {"IfcOpeningElement", "IfcWall", "IfcWallStandardCase"}  # a wider window's opening and host


# ---------------------------------------------------------------- the snapshot's colours (no imaging library)

def png_colours(path: Path, limit: int = 100_000) -> int:
    """The number of distinct colours in an 8-bit, non-interlaced RGB or RGBA PNG (counting stops at `limit`)."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, header = 8, [], None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        pos += 12 + length
    width, height, depth, colour_type, _, _, interlace = header
    if depth != 8 or colour_type not in (2, 6) or interlace:
        raise ValueError(f"unsupported PNG (depth {depth}, colour type {colour_type}, interlace {interlace})")
    bpp = 3 if colour_type == 2 else 4
    raw = zlib.decompress(b"".join(idat))
    stride = width * bpp
    prev = bytearray(stride)
    colours: set[bytes] = set()
    for y in range(height):
        start = y * (stride + 1)
        f, row = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        if f == 1:
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif f == 2:
            row = bytearray((a + b) & 0xFF for a, b in zip(row, prev))
        elif f == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b, c = prev[i], prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        if len(colours) < limit:
            colours.update(bytes(row[i:i + 3]) for i in range(0, stride, bpp))
        prev = row
    return len(colours)


# ---------------------------------------------------------------- the agent's side: MCP only

def agent_flow(kim: Path, windows: int | None, out: dict) -> None:
    """What an AI client does, through the SDK's in-process MCP client. Fills `out` with what it got and the
    timings as it goes (so a failure still reports how far it came)."""
    import anyio
    import mcp_types as types
    from mcp import Client

    from kimbim.agent import mcp_server

    server = mcp_server.build_server(str(kim))

    async def call(c, tool: str, args: dict, timed: str = "", fail: bool = True) -> dict:
        t0 = time.perf_counter()
        r = await c.call_tool(tool, args)
        if timed:
            out["ms"][timed] = round((time.perf_counter() - t0) * 1000)
            print(f"{tool}: {out['ms'][timed]} ms", file=sys.stderr)
        text = next(b.text for b in r.content if b.type == "text")
        envelope = json.loads(text)
        if fail and (r.is_error or not envelope.get("ok")):
            raise RuntimeError(f"{tool} failed: {text}")
        if tool == "snapshot_take":
            out["images"] = sum(1 for b in r.content if b.type == "image")
        return envelope

    async def widenable(c, guids: list[str], n: int) -> list[str]:
        """The first n windows that still fit their wall 50 cm wider (a dry run each, inside the task)."""
        fit = []
        for g in guids:
            dry = await call(c, "elements_set_dimensions", {"elements": [g], "width": "+50cm", "dry_run": True},
                             fail=False)
            if dry.get("ok"):
                fit.append(g)
                if len(fit) == n:
                    break
        return fit

    async def go():
        async with Client(server, client_info=types.Implementation(name="check", version="1")) as c:
            await call(c, "project_info", {}, "open")  # starts the worker: the project is opened once
            where = {"kind": "window"} if windows else {"kind": "window", "level": "Level 1"}
            found = await call(c, "elements_find", {"elements": where, "limit": 1000}, "find")
            guids = [e["guid"] for e in found["result"]["items"]]
            started = await call(c, "task_start", {"title": TITLE}, fail=False)
            left = (started.get("error") or {}).get("details") or {}
            if not started["ok"] and started["error"]["code"] == "task_busy" and left.get("title") == TITLE:
                await call(c, "task_abandon", {"task": left["task"]})  # a reused .kim: an earlier run's, cut short
                started = await call(c, "task_start", {"title": TITLE})
            if not started["ok"]:
                raise RuntimeError(f"task_start failed: {json.dumps(started)}")
            out["task"] = started["result"]
            try:
                out["write"] = "set_dimensions"
                if windows:  # any N windows: some of a real model's have no room to grow in their wall
                    fit = await widenable(c, guids, windows)
                    if len(fit) < windows:  # too few to time the write on: rename N windows instead
                        out["write"], out["widenable"] = "rename", len(fit)
                    guids = fit if len(fit) == windows else guids[:windows]
                if out["write"] == "set_dimensions":
                    got = await call(c, "elements_get", {"elements": guids, "limit": len(guids)})
                    out["before_m"] = {e["guid"]: e["dimensions"]["values"].get("Width")
                                       for e in got["result"]["items"]}
                    await call(c, "elements_set_dimensions", {"elements": guids, "width": "+50cm"}, "set_dimensions")
                    summary = f"{len(guids)} windows 50 cm wider."
                else:
                    await call(c, "elements_rename", {"elements": guids, "name": "Window (agent check)"}, "rename")
                    summary = f"{len(guids)} windows renamed."
                out["snapshot"] = (await call(c, "snapshot_take", {"changes": "task"}, "snapshot"))["result"]
                out["finish"] = (await call(c, "task_finish", {"summary": summary}, "finish"))["result"]
            except BaseException:
                await call(c, "task_abandon", {}, fail=False)  # leave no open task behind
                raise
            out["guids"] = guids

    anyio.run(go)


def _first_error(ex: BaseException) -> BaseException:
    """The error inside the MCP client's task groups."""
    while isinstance(ex, BaseExceptionGroup) and ex.exceptions:
        ex = ex.exceptions[0]
    return ex


def shut_down(kim: Path) -> None:
    """Stop the project's worker (it parks, saves the .kim and releases the lock) and wait for it to go."""
    from kimbim import kimfile as K
    from kimbim.agent import client

    bye = client.request(str(kim), "_shutdown", {}, start=False)
    pid = (bye.get("result") or {}).get("pid", 0)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline and (K.lock_path(kim).exists() or (pid and K.pid_alive(pid))):
        time.sleep(0.1)


# ---------------------------------------------------------------- the architect's side: the history

def history(kim: Path, folder: Path):
    from kimbim import kimfile as K
    from kimbim.project import Project

    K.remove_tree(folder)
    K.unpack(kim, folder)
    return Project.open(folder)


def width_of(project, key: str, rev: str):
    record = project.show(key, rev)
    attrs = record.get("a", {})  # the IFC attributes of a canonical record
    return attrs.get("OverallWidth")


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ifc")
    ap.add_argument("out")
    ap.add_argument("--project", default="", help="work on this .kim (made from IFC if missing, else reused)")
    ap.add_argument("--windows", type=int, default=0, help="widen any N windows (default: Level 1's)")
    a = ap.parse_args(argv[1:])
    out = Path(a.out).resolve()
    house = not a.project
    if house:
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    # The worker and the renderer keep out of the user's data. For the house, a temporary folder, as a user's data
    # folder is (in LOCALAPPDATA): a synced folder (this checkout is in OneDrive) can briefly hold a file the worker
    # is replacing. A reused project keeps its data (its model cache) in OUT_DIR.
    data = Path(tempfile.mkdtemp(prefix="kimbim-agent-check-")) if house else out / "data"
    os.environ["KIMBIM_DATA_DIR"] = str(data)

    from kimbim import app_bridge as B
    from kimbim import documents as D
    from kimbim import versioning as V

    report: dict = {"model": Path(a.ifc).name}
    problems: list[str] = []
    kim = Path(a.project).resolve() if a.project else out / (Path(a.ifc).stem + ".kim")
    if not kim.exists():
        t0 = time.perf_counter()
        made = json.loads(D.import_ifc(str(Path(a.ifc).resolve()), str(kim)))
        if made.get("ok"):  # opened and closed the way the app does: the .kim's lock is released
            made = json.loads(B.open_model(made["path"]))
        D.close_document()
        report["import_ms"] = round((time.perf_counter() - t0) * 1000)
        if not made.get("ok"):
            print(json.dumps({**report, "ok": False, "problems": [f"import failed: {made}"]}))
            return 1

    before = history(kim, out / "before")
    main_head = before.repo.resolve("main")
    options_before = set(before.branches())

    flow: dict = {"ms": {}}
    report["ms"] = flow["ms"]
    try:
        agent_flow(kim, a.windows or None, flow)
    except Exception as ex:  # noqa: BLE001  (one JSON line, also on failure)
        report.update(ok=False, problems=[f"{type(_first_error(ex)).__name__}: {_first_error(ex)}"])
        print(json.dumps(report, default=str))
        return 1
    finally:
        shut_down(kim)
    guids = flow["guids"]
    report["windows"] = len(guids)
    report["write"] = flow["write"]
    if "widenable" in flow:  # recorded, not a failure of this check: the write was timed as a rename
        report["widenable"] = flow["widenable"]
    option = flow["finish"]["task"].get("option", "")
    report["option"] = option
    report["task"] = flow["finish"]["task"].get("status")

    after = history(kim, out / "after")
    branch = V._encode(option)
    if house and (len(guids) != 4 or option != OPTION):
        problems.append(f"expected 4 Level 1 windows in {OPTION}, got {len(guids)} in {option!r}")
    if branch not in set(after.branches()) - options_before:
        problems.append(f"no new option {option!r} (options: {after.branches()})")
    else:
        log = after.log(branch, 3)
        if len(log) < 2 or log[1].id != main_head:
            problems.append(f"{option} should hold one version on top of main's head")
        if after.repo.resolve("main") != main_head:
            problems.append("main's head moved")
        # Element by element, as the app's Compare (versioning.compare) reports it: geometry, placements and
        # relationships are the elements' records, counted in "other".
        diff = V._summary(after.diff("main", branch))
        elements = [e for k in ("added", "modified", "removed") for e in diff[k]]
        windows = {e["guid"] for e in elements if e["type"] == "IfcWindow" and e["kind"] == "modified"}
        extra = [e for e in elements if e["guid"] not in windows]
        report["diff"] = {"windows": len(windows), "extra": [f"{e['kind']} {e['type']} {e['name']}".strip()
                                                             for e in extra], "other_records": diff["other"]}
        if windows != set(guids):
            problems.append(f"the diff's windows are not the {len(guids)} widened ones: {sorted(windows)}")
        bad_extra = [e for e in extra if e["type"] not in MAY_ALSO_CHANGE or e["kind"] != "modified"]
        if bad_extra:
            problems.append(f"the diff holds more than the windows, their openings and walls: {bad_extra[:10]}")
        widths = {}
        for g in guids if flow["write"] == "set_dimensions" else ():
            old, new = width_of(after, "o/" + g, "main"), width_of(after, "o/" + g, branch)
            metres = flow["before_m"].get(g)
            scale = metres / old if metres and old else 1.0  # model units to metres
            widths[g] = round(new * scale, 4) if new is not None else None
            want = HOUSE_WIDTH if house else round(metres + WIDER, 4) if metres else None
            if widths[g] is None or want is None or abs(widths[g] - want) > 1e-6:
                problems.append(f"window {g}: width {widths[g]} m, expected {want}")
        report["widths_m"] = sorted(set(widths.values()), key=str)

    shot = Path(flow["snapshot"]["path"])
    try:
        report["snapshot_colours"] = png_colours(shot)
    except (OSError, ValueError, TypeError) as ex:
        report["snapshot_colours"] = 0
        problems.append(f"snapshot {shot}: {ex}")
    if report["snapshot_colours"] < 100:
        problems.append(f"the snapshot has {report['snapshot_colours']} colours (want at least 100)")
    if flow.get("images") != 1:
        problems.append("the snapshot's MCP result does not carry the picture")

    report["ok"] = not problems
    report["problems"] = problems
    print(json.dumps(report, default=str))
    if house and report["ok"]:
        shutil.rmtree(data, ignore_errors=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
