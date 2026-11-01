# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent IFC interop check through xBIM (the .NET engine behind Xplorer).

It opens the model with a different parser from IfcOpenShell and counts the products, walls and
storeys. Run it after `pixi run house` / `pixi run interop`:
    pixi run interop-xbim
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODEL = ROOT / "build" / "house.ifc"
PROJECT = ROOT / "tools" / "interop-xbim"


def main() -> int:
    if not MODEL.exists():
        raise SystemExit(f"{MODEL} is missing; run `pixi run house` first")
    result = subprocess.run(
        ["dotnet", "run", "--project", str(PROJECT), "--", str(MODEL)],
        capture_output=True, text=True, timeout=300,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip().startswith("{")]
    report = json.loads(lines[-1]) if lines else {"ok": False, "error": result.stdout + result.stderr}
    problems = []
    if result.returncode != 0 or not report.get("ok"):
        problems.append(report.get("error", "xBIM could not open the model"))
    if report.get("storeys", 0) < 3:
        problems.append(f"xBIM sees {report.get('storeys')} storeys, expected 3")
    if report.get("walls", 0) < 8:
        problems.append(f"xBIM sees {report.get('walls')} walls, expected 8")
    report["problems"] = problems
    report["ok"] = not problems
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
