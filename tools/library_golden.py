# SPDX-License-Identifier: GPL-3.0-or-later
"""One-off for D99 (doc 16 §8): measure today's Python-built library objects so the .kimobj port can be
checked against them. Run before library.py changes:

    pixi run python tools/library_golden.py tests/golden/library_objects.json
"""
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
from kimbim import library as L  # noqa: E402

SAMPLES = 64


def value_sets(obj):
    large, small = {}, {}
    for p in obj.params:
        if p.kind == "length":
            large[p.key], small[p.key] = p.default * 1.25, p.default * 0.8
        elif p.kind == "count":
            large[p.key], small[p.key] = p.default + 1, p.lo
    return {"default": {}, "large": large, "small": small}


def circle(cx, cy, r):
    return [(cx + r * math.cos(2 * math.pi * k / SAMPLES), cy + r * math.sin(2 * math.pi * k / SAMPLES))
            for k in range(SAMPLES)]


def area(pts):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2


def solid_points_and_volume(s):
    kind = s[0]
    if kind == "box":
        _, x, y, z, dx, dy, dz = s
        pts = [(x + a * dx, y + b * dy, z + c * dz) for a in (0, 1) for b in (0, 1) for c in (0, 1)]
        return pts, dx * dy * dz
    if kind == "cylinder":
        _, cx, cy, z, r, dz = s
        return [(px, py, pz) for px, py in circle(cx, cy, r) for pz in (z, z + dz)], math.pi * r * r * dz
    if kind == "prism":
        _, pts2, z, dz = s
        return [(px, py, pz) for px, py in pts2 for pz in (z, z + dz)], area(list(pts2)) * dz
    if kind == "side":  # polygon in (y, z) extruded along x
        _, pts2, x, dx = s
        return [(px, py, pz) for py, pz in pts2 for px in (x, x + dx)], area(list(pts2)) * dx
    if kind == "side_cylinder":
        _, cy, cz, x, r, dx = s
        return [(px, py, pz) for py, pz in circle(cy, cz, r) for px in (x, x + dx)], math.pi * r * r * dx
    raise ValueError(kind)


def metrics(shape):
    pts, volume = [], 0.0
    for s in shape.solids:
        p, v = solid_points_and_volume(s)
        pts += p
        volume += v
    lines = L._symbol(shape)
    flat = [pt for line in lines for pt in line]
    length = sum(math.dist(a, b) for line in lines for a, b in zip(line, line[1:]))
    return {
        "bbox": [round(min(p[i] for p in pts), 6) for i in range(3)] + [round(max(p[i] for p in pts), 6) for i in range(3)],
        "volume": round(volume, 9),
        "symbol_bbox": [round(min(p[0] for p in flat), 6), round(min(p[1] for p in flat), 6),
                        round(max(p[0] for p in flat), 6), round(max(p[1] for p in flat), 6)],
        "symbol_length": round(length, 6),
    }


def main(out):
    result = {}
    for key, obj in sorted(L.OBJECTS.items()):
        result[key] = {}
        for name, given in value_sets(obj).items():
            values = obj.values(given)
            result[key][name] = {"values": {k: v for k, v in values.items() if not k.startswith("mat_")},
                                 **metrics(obj.shape(values))}
    pathlib.Path(out).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(result)} objects -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
