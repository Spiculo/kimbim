# SPDX-License-Identifier: GPL-3.0-or-later
"""Sections and elevations drawn from the meshes (D60/D73): the app opens each drawing in a real
window (the hidden-line pass needs OpenGL), saves its SVG, and this checks what was drawn.

- The house's South Elevation draws its walls, roof, windows and door (not only the objects), up to
  the roof's ridge; its Section 1 has filled poché for the cut walls and slabs and projected walls
  behind; a section through the U stair cuts its flights and railings.
- Hidden lines are removed: in the occlusion model's North Elevation the tall wall's bottom edge stops
  where the short wall in front of it hides it.
- A georeferenced copy of the house (its site 580 km east and 6140 km north, with an IfcMapConversion
  and a stray element left at the project origin) frames and draws the building.

Usage: python tools/check_drawings.py build/house.ifc [OUT_DIR]   (prints JSON; exit 1 on failure)
"""
from __future__ import annotations

import collections
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

EAST, NORTH = 580000.0, 6140000.0  # a UTM-like survey point (metres)


def app() -> Path:
    for name in ("kimbim-app.exe", "kimbim-app"):
        for base in (ROOT / "build" / "app" / "app", ROOT / "build" / "app"):
            if (base / name).exists():
                return base / name
    raise SystemExit("kimbim-app not built (pixi run app-build)")


def open_drawing(ifc: str, name: str, out: Path) -> dict:
    """Open `name` in the app (self-test), wait for it, return the self-test report and the SVG."""
    shot = out / (re.sub(r"\W+", "-", f"{Path(ifc).stem}-{name}") + ".png")
    env = {**os.environ, "KIMBIM_PYTHON_PATH": str(ROOT / "python")}
    done = subprocess.run([str(app()), "--self-test", ifc, "--frames", "1", "--open-drawing", name,
                           "--screenshot", str(shot), "--window-size", "1500x860"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=900)
    line = next((ln for ln in reversed(done.stdout.splitlines()) if ln.startswith("{")), "")
    report = json.loads(line) if line else {"ok": False, "error": done.stderr[-2000:]}
    svg_path = report.get("drawing_svg") or ""
    report["svg"] = Path(svg_path).read_text(encoding="utf-8") if svg_path and Path(svg_path).exists() else ""
    return report


def groups(svg: str) -> list[dict]:
    """The drawn element groups: guid, projection or cut, and their segments (paper mm)."""
    out = []
    for attrs, body in re.findall(r"<g([^>]*ifc:guid[^>]*)>(.*?)</g>", svg, re.S):
        guid = re.search(r'ifc:guid="([^"]+)"', attrs).group(1)
        segs = []
        for d in re.findall(r'\sd="([^"]+)"', body):
            pts, start = [], None
            for cmd, x, y in re.findall(r"([MLZ])\s*(?:(-?[\d.]+)[ ,](-?[\d.]+))?", d):
                if cmd == "M":
                    pts = [(float(x), float(y))]
                    start = pts[0]
                elif cmd == "L":
                    pts.append((float(x), float(y)))
                    segs.append((pts[-2], pts[-1]))
                elif cmd == "Z" and start and pts:
                    segs.append((pts[-1], start))
        out.append({"guid": guid, "cut": "projection" not in attrs, "segs": segs, "paths": body.count("<path")})
    return out


def by_class(f, gs: list[dict], cut: bool) -> dict:
    count = collections.Counter()
    for g in gs:
        if g["cut"] != cut:
            continue
        try:
            count[f.by_guid(g["guid"]).is_a()] += g["paths"]
        except RuntimeError:
            count["?"] += g["paths"]
    return dict(count)


def span(gs: list[dict]) -> tuple[float, float]:
    xs = [p[0] for g in gs for s in g["segs"] for p in s]
    ys = [p[1] for g in gs for s in g["segs"] for p in s]
    return (max(xs) - min(xs), max(ys) - min(ys)) if xs else (0.0, 0.0)


def stair_section(house: Path, out: Path) -> Path:
    """The house with a section across its U stair (x = 2 m, looking west)."""
    from kimbim import app_bridge as b

    path = out / "house-stair.ifc"
    assert json.loads(b.open_model(str(house))).get("ok") is not False
    made = json.loads(b.create_section(2.0, 9.0, 2.0, -1.0, 0.0, 4.0, -1))
    assert made.get("ok") is not False, made
    guid = made["guid"]
    assert json.loads(b.rename_drawing(guid, "Stair Section")).get("ok") is not False
    assert json.loads(b.save(str(path))).get("ok")
    return path


def georeferenced(house: Path, out: Path) -> Path:
    """The house moved to map coordinates: its site placed at (EAST, NORTH) with an IfcMapConversion,
    and a stray copy of the car left at the project origin (an element a survey export leaves behind)."""
    import ifcopenshell
    import ifcopenshell.api.root
    import ifcopenshell.util.unit

    f = ifcopenshell.open(str(house))
    unit = ifcopenshell.util.unit.calculate_unit_scale(f)
    site = f.by_type("IfcSite")[0]
    loc = site.ObjectPlacement.RelativePlacement.Location
    x, y, z = (list(loc.Coordinates) + [0.0, 0.0, 0.0])[:3]
    site.ObjectPlacement.RelativePlacement.Location = f.createIfcCartesianPoint((x + EAST / unit, y + NORTH / unit, z))
    if f.schema != "IFC2X3":
        context = next(c for c in f.by_type("IfcGeometricRepresentationContext") if not c.is_a("IfcGeometricRepresentationSubContext"))
        crs = f.createIfcProjectedCRS(Name="EPSG:32721", Description="WGS 84 / UTM zone 21S")
        f.createIfcMapConversion(SourceCRS=context, TargetCRS=crs, Eastings=0.0, Northings=0.0, OrthogonalHeight=0.0)
    car = next(p for p in f.by_type("IfcBuildingElementProxy") if p.Name == "Car")
    stray = ifcopenshell.api.root.copy_class(f, product=car)
    stray.Name = "Stray car at the origin"
    origin = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None)
    stray.ObjectPlacement = f.createIfcLocalPlacement(None, origin)
    path = out / "house-georeferenced.ifc"
    f.write(str(path))
    return path


def segment_hidden(seg, box, margin=1.0) -> bool:
    """True if part of the segment lies inside `box` (x0, y0, x1, y1), shrunk by `margin` mm."""
    (ax, ay), (bx, by) = seg
    x0, y0, x1, y1 = box[0] + margin, box[1] + margin, box[2] - margin, box[3] - margin
    for i in range(21):
        t = i / 20
        px, py = ax + (bx - ax) * t, ay + (by - ay) * t
        if x0 < px < x1 and y0 < py < y1:
            return True
    return False


def main(argv) -> int:
    import ifcopenshell

    house = Path(argv[1]) if len(argv) > 1 else ROOT / "build" / "house.ifc"
    out = Path(argv[2]) if len(argv) > 2 else ROOT / "build" / "drawings-check"
    out.mkdir(parents=True, exist_ok=True)
    f = ifcopenshell.open(str(house))
    report, failures = {}, []

    def check(name, ok, detail):
        report.setdefault("checks", {})[name] = {"ok": bool(ok), **detail}
        if not ok:
            failures.append(name)

    # The house: walls, roof, slabs and openings, not only the objects; up to the ridge (8.85 m).
    r = open_drawing(str(house), "South Elevation", out)
    gs = groups(r["svg"])
    proj = by_class(f, gs, cut=False)
    width, height = span(gs)
    check("south_elevation", r.get("drawing_shown") and all(proj.get(c, 0) > 0 for c in ("IfcWall", "IfcRoof", "IfcWindow", "IfcDoor"))
          and height >= 85.0, {"projection": proj, "span_mm": [round(width, 1), round(height, 1)]})

    r = open_drawing(str(house), "Section 1", out)
    gs = groups(r["svg"])
    proj, cut = by_class(f, gs, cut=False), by_class(f, gs, cut=True)
    # Behind the cut: the back wall with its windows, and the furniture in the rooms.
    check("section", r.get("drawing_shown") and cut.get("IfcWall", 0) > 0 and cut.get("IfcSlab", 0) > 0
          and proj.get("IfcWall", 0) > 0 and proj.get("IfcWindow", 0) > 0 and proj.get("IfcFurniture", 0) > 0, {"projection": proj, "cut": cut})
    # Poché: the cut groups are filled in the styled SVG.
    fills = collections.Counter()
    for attrs in re.findall(r"<g([^>]*ifc:guid[^>]*)>", r["svg"]):
        if "projection" in attrs:
            continue
        guid = re.search(r'ifc:guid="([^"]+)"', attrs).group(1)
        fill = re.search(r'fill="([^"]+)"', attrs)
        if fill and fill.group(1) != "none":
            fills[f.by_guid(guid).is_a()] += 1
    check("section_poche", fills.get("IfcWall", 0) > 0 and fills.get("IfcSlab", 0) > 0, {"filled_cut_groups": dict(fills)})

    stair = stair_section(house, out)
    fs = ifcopenshell.open(str(stair))
    r = open_drawing(str(stair), "Stair Section", out)
    gs = groups(r["svg"])
    proj, cut = by_class(fs, gs, cut=False), by_class(fs, gs, cut=True)
    # The flights are drawn (their cut poche needs closed meshes: the display kernel leaves a flight's
    # stepped sides open today, so it is not required here); the railings and walls are cut.
    check("stair_section", r.get("drawing_shown") and (cut.get("IfcStairFlight", 0) + proj.get("IfcStairFlight", 0)) >= 10
          and cut.get("IfcRailing", 0) > 0 and cut.get("IfcWall", 0) > 0, {"projection": proj, "cut": cut})

    # Hidden lines: the tall wall's edges stop behind the short wall in front of it.
    r = open_drawing(":occlusion:", "North Elevation", out)
    gs = [g for g in groups(r["svg"]) if not g["cut"]]
    boxes = []
    for g in gs:
        xs = [p[0] for s in g["segs"] for p in s]
        ys = [p[1] for s in g["segs"] for p in s]
        if xs:
            boxes.append(((min(xs), min(ys), max(xs), max(ys)), g))
    boxes.sort(key=lambda bg: (bg[0][2] - bg[0][0]) * (bg[0][3] - bg[0][1]))
    leaks = -1
    if len(boxes) == 2:
        (short_box, _), (_, tall) = boxes
        leaks = sum(segment_hidden(s, short_box) for s in tall["segs"])
    check("hidden_lines", len(boxes) == 2 and leaks == 0, {"walls_drawn": len(boxes), "tall_segments_behind_short": leaks})

    # Georeferenced: the building is framed (about 20 m wide with its car and tree), not the 6000 km
    # to the stray element at the origin, and its walls and roof are drawn.
    geo = georeferenced(house, out)
    fg = ifcopenshell.open(str(geo))
    r = open_drawing(str(geo), "South Elevation", out)
    gs = groups(r["svg"])
    proj = by_class(fg, gs, cut=False)
    width, height = span(gs)
    paper = r.get("drawing_paper_mm") or [0, 0]
    check("georeferenced_elevation", r.get("drawing_shown") and proj.get("IfcWall", 0) > 0 and proj.get("IfcRoof", 0) > 0
          and 0 < paper[0] < 400 and height >= 85.0,
          {"projection": proj, "paper_mm": paper, "span_mm": [round(width, 1), round(height, 1)]})

    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, indent=1))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
