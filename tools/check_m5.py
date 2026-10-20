# SPDX-License-Identifier: GPL-3.0-or-later
"""M5 exit test (Slice 22): two design options of the sample house are created, edited separately,
compared and combined with one conflict resolved. The app's UI path is tested in test_main_window
(m5ExitCombineOptions); this runs the same bridge calls on the full house, without a window.

Scheme B renames the south wall, moves the column and renames the upper room; main renames the same
wall differently (the conflict), adds a window and renames the living room. Combining keeps B's wall
name; the result must hold every other edit from both options, be a version with two parents, and
pass IFC4 schema + EXPRESS-rule validation.

Usage: python tools/check_m5.py OUT_DIR   (prints JSON; exit 1 on failure)
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "tools"))
import ifcopenshell.util.element  # noqa: E402
import ifcopenshell.util.placement  # noqa: E402
import ifcopenshell.validate  # noqa: E402

import make_house  # noqa: E402
from kimbim import app_bridge as b  # noqa: E402
from kimbim import authoring  # noqa: E402


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def main(argv) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path(tempfile.mkdtemp())
    out.mkdir(parents=True, exist_ok=True)
    problems, report = [], {}
    house = out / "house-m5.ifc"
    make_house.build(str(house))
    project = out / "project"
    if project.exists():
        shutil.rmtree(project)
    m = b._model  # the house just built
    l1 = call("storeys")["storeys"][0]["guid"]
    south = next(w for w in m.by_type("IfcWall")  # Level 1, along y = 0
                 if ifcopenshell.util.element.get_container(w).GlobalId == l1
                 and all(abs(p[1]) < 1e-6 for p in authoring._axis_world(w)))
    column = m.by_type("IfcColumn")[0].GlobalId
    rooms = {s.LongName: s.GlobalId for s in m.by_type("IfcSpace")}
    report["enable"] = call("enable_versioning", str(project), "The sample house")["ok"]

    # Scheme B
    report["create_option"] = call("create_option", "Scheme B")["ok"]
    call("set_name", json.dumps([south.GlobalId]), "South wall (glazed)")
    call("move_elements", json.dumps([column]), 1.0, 0.0, 0.0)
    call("edit_room", rooms["Bedroom"], json.dumps({"name": "Main bedroom"}))
    report["save_b"] = call("save_version", "Scheme B: glazed south wall, column moved")["ok"]

    # main
    report["switch_main"] = call("switch_option", "main")["ok"]
    call("set_name", json.dumps([south.GlobalId]), "South wall (brick)")
    window = next(t for t in call("opening_types", "window")["types"])
    added = call("insert_opening", "window", south.GlobalId, window["guid"], 2.0, window["width"], window["height"], window["sill"])
    rooms_now = {s.LongName: s.GlobalId for s in b._model.by_type("IfcSpace")}
    call("edit_room", rooms_now["Living room"], json.dumps({"name": "Living and dining"}))
    report["save_main"] = call("save_version", "main: brick south wall, a window")["ok"]

    # Compared
    cmp = call("compare", "Scheme B", "main")
    report["compare"] = {k: len(cmp.get(k, [])) for k in ("added", "modified", "removed")}
    if not cmp.get("ok") or not cmp.get("modified"):
        problems.append(f"compare failed: {cmp}")

    # Combined, one conflict resolved
    preview = call("combine_preview", "Scheme B", "{}")
    conflicts = preview.get("conflicts", [])
    report["conflicts"] = [{"id": c["id"], "kind": c["kind"], "ours": c["ours_text"], "theirs": c["theirs_text"]} for c in conflicts]
    if len(conflicts) != 1 or conflicts[0]["attribute"] != "Name" or conflicts[0]["guid"] != south.GlobalId:
        problems.append(f"expected one conflict on the south wall's name, got {report['conflicts']}")
    choices = {c["id"]: "theirs" for c in conflicts}
    combined = call("combine_options", "Scheme B", json.dumps(choices))
    report["combine"] = {k: combined.get(k) for k in ("ok", "status", "error")}
    saved = call("save_version", "Combine Scheme B into main")
    report["save_combined"] = saved.get("ok")
    top = call("history", 1)["versions"][0]
    report["parents"] = len(top["parents"])
    if top["parents"] and len(top["parents"]) != 2:
        problems.append("the combined version should have two parents")

    # What the combined model holds
    m = b._model
    names = {s.LongName for s in m.by_type("IfcSpace")}
    col = m.by_guid(column)
    x = ifcopenshell.util.placement.get_local_placement(col.ObjectPlacement)[0][3] * authoring._scale()
    checks = {
        "wall name from Scheme B": m.by_guid(south.GlobalId).Name == "South wall (glazed)",
        "column moved in Scheme B": abs(x - 6.0) < 1e-6,
        "room renamed in Scheme B": "Main bedroom" in names,
        "room renamed in main": "Living and dining" in names,
        "window added in main": added.get("ok") and bool(m.by_guid(added["guid"])),
    }
    report["checks"] = checks
    problems += [f"combined model: {k} is missing" for k, ok in checks.items() if not ok]
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(m, log, express_rules=True)
    report["validation_errors"] = len(log.statements)
    if log.statements:
        problems.append(f"{len(log.statements)} IFC validation error(s): {log.statements[:2]}")
    report["ok"] = not problems
    report["problems"] = problems
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
