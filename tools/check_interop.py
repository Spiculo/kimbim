# SPDX-License-Identifier: GPL-3.0-or-later
"""M3 exit check: is an exported IFC file valid, and does another engine open it?

1. IfcOpenShell's validator: IFC4 schema (types, cardinalities, inverses) and the EXPRESS
   WHERE rules and functions.
2. web-ifc (the That Open / IFC.js engine, independent of IfcOpenShell) opens the file and must
   produce geometry for every building element (tools/interop/webifc_check.mjs).

Usage: python tools/check_interop.py FILE.ifc   (exit code 0 = both pass; prints a JSON report)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.validate

HERE = Path(__file__).resolve().parent


def validate(path: str) -> dict:
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(ifcopenshell.open(path), logger, express_rules=True)
    issues = [{"level": s.get("level"), "message": str(s.get("message", ""))[:300]} for s in logger.statements]
    errors = [i for i in issues if str(i["level"]).lower() in ("error", "critical")]
    return {"ok": not errors, "issues": len(issues), "errors": errors[:20]}


def webifc(path: str) -> dict:
    node = shutil.which("node")
    if node is None:
        return {"ok": False, "error": "node not found (run through pixi: pixi run interop)"}
    if not (HERE / "interop" / "node_modules" / "web-ifc").exists():
        return {"ok": False, "error": "web-ifc not installed (pixi run interop installs it)"}
    run = subprocess.run([node, str(HERE / "interop" / "webifc_check.mjs"), str(Path(path).resolve())],
                         capture_output=True, text=True, cwd=HERE / "interop")
    lines = [line for line in run.stdout.splitlines() if line.startswith("{")]
    report = json.loads(lines[-1]) if lines else {"ok": False}
    report["warnings"] = [line for line in run.stderr.splitlines() if line.strip()][:20]
    report["ok"] = bool(report.get("ok")) and run.returncode == 0
    return report


def main(path: str) -> int:
    result = {"file": path, "validation": validate(path), "web_ifc": webifc(path)}
    result["ok"] = result["validation"]["ok"] and result["web_ifc"]["ok"]
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tools/check_interop.py FILE.ifc")
    sys.exit(main(sys.argv[1]))
