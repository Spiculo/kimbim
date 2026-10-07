# SPDX-License-Identifier: GPL-3.0-or-later
"""M4 exit test: the sample house's sheet A01 (ground floor plan, a section, the south elevation, a title
block) exported to PDF by the app, without a window, and checked.

Checks: one page of A3 landscape (420 x 297 mm), vector drawing operators in the page content, fonts
embedded for the text; and in the sheet's SVG (same composition), the three drawings by name, the
title block's project, client, sheet number and scale.

Usage: python tools/check_m4.py build/house.ifc [OUT_DIR]   (prints JSON; exit 1 on failure)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A3 = (420.0, 297.0)


def app() -> Path:
    for name in ("kimcad-app.exe", "kimcad-app"):
        for base in (ROOT / "build" / "app" / "app", ROOT / "build" / "app"):
            if (base / name).exists():
                return base / name
    raise SystemExit("kimcad-app not built (pixi run app-build)")


def export(ifc: Path, out: Path) -> dict:
    env = {**os.environ, "KIMCAD_PYTHON_PATH": str(ROOT / "python")}
    if sys.platform == "win32":
        # Qt's offscreen platform on Windows sees no system fonts, so the PDF's text came out as outlines
        # (no fonts embedded). The native platform needs no visible window for an export.
        env.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    else:
        env["QT_QPA_PLATFORM"] = "offscreen"
    done = subprocess.run([str(app()), "--export-sheet", "A01", str(ifc), str(out)], capture_output=True,
                          text=True, env=env, timeout=600)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("{")), "")
    result = json.loads(line) if line else {"ok": False, "error": done.stderr[-2000:]}
    result["exit_code"] = done.returncode
    return result


def check_pdf(path: Path) -> dict:
    data = path.read_bytes()
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    box = re.search(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", data)
    size = (round((float(box.group(3)) - float(box.group(1))) * 25.4 / 72, 1),
            round((float(box.group(4)) - float(box.group(2))) * 25.4 / 72, 1)) if box else (0, 0)
    operators = 0
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = m.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        operators += len(re.findall(rb"(?<![A-Za-z])[lmc](?![A-Za-z])", raw))
    fonts = len(re.findall(rb"/Type\s*/Font\b", data))
    return {"pdf": data[:5] == b"%PDF-", "pages": pages, "size_mm": size, "path_operators": operators,
            "fonts": fonts, "bytes": len(data)}


def main(argv) -> int:
    ifc = Path(argv[1]).resolve()
    out_dir = Path(argv[2]) if len(argv) > 2 else ifc.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf, svg = out_dir / "house-A01.pdf", out_dir / "house-A01.svg"
    report = {"export_pdf": export(ifc, pdf), "export_svg": export(ifc, svg)}
    problems = [f"export {k}: {v.get('error')}" for k, v in report.items() if not v.get("ok")]
    if pdf.exists():
        report["pdf"] = check_pdf(pdf)
        p = report["pdf"]
        if not p["pdf"] or p["pages"] != 1:
            problems.append(f"expected a one-page PDF, got {p['pages']} page(s)")
        if abs(p["size_mm"][0] - A3[0]) > 2 or abs(p["size_mm"][1] - A3[1]) > 2:
            problems.append(f"expected A3 landscape, got {p['size_mm']} mm")
        if p["path_operators"] < 200:
            problems.append(f"too little vector content ({p['path_operators']} path operators)")
        if p["fonts"] < 1:
            problems.append("no fonts: the text is missing")
    if svg.exists():
        text = svg.read_text(encoding="utf-8")
        wanted = ["Level 1 Floor Plan", "Section 1", "South Elevation", "KIMCAD two-storey house",
                  "Client: KIMCAD test client", "A01", "1:100"]
        report["svg_texts"] = {w: f">{w}<" in text for w in wanted}
        problems += [f"the sheet lacks '{w}'" for w, ok in report["svg_texts"].items() if not ok]
        if text.count('class="kimcad-view"') != 3:
            problems.append("the sheet should hold 3 drawings")
    report["ok"] = not problems
    report["problems"] = problems
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
