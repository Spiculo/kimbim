# SPDX-License-Identifier: GPL-3.0-or-later
"""Stairs, ramps and railings (D88), after Archicad's Stair and Railing tools (Revit where Archicad has none).

A stair is an `IfcStair` aggregating its parts: one `IfcStairFlight` per flight and an `IfcSlab`
(LANDING) per landing, placed relative to the stair, so moving the stair moves them. Its shape comes
from a few parameters kept in `KIMBIM_Stair` (shape, turn, width, height, target riser, tread,
landing depth, the walking line for a stair by sketch): editing one rebuilds the parts (the stair keeps
its GlobalId, parts are reused in order). Risers come from the height and the target riser (Archicad:
the riser count is computed, the riser height follows); building-code checks (riser, tread,
2 risers + tread) are warnings, with limits in the project settings (`stair_rules`).

Shapes: straight; L (a quarter landing, turning left or right); U (a half landing, the second flight
coming back beside the first); by sketch (a walking line clicked as a polyline: one flight per segment,
a landing at each corner, the risers shared out by length). Ramps (`IfcRamp` with `IfcRampFlight` and
landings) are straight or L, from a slope in percent (warning above the rules' maximum, 1:12).

Railings are `IfcRailing` elements with posts, a top rail and balusters (boxes: 12 triangles each).
A railing on a stair or ramp side names it in `KIMBIM_Railing.Host`: it is rebuilt whenever the stair
changes (an AFTER_ACTION hook, same undo step), so it follows. A railing by path keeps its own points.

Where a stair arrives under a floor slab, the slab gets an opening of the stair's outline (D53's slab
openings), kept up to date by the same hook and deleted with the stair.

The plan symbol (walking line with its arrow, the break line at the plan cut, the part above it dashed,
UP/DN) is drawn from `Plan`, a compact list of the stair's lines with their heights kept in the pset,
by drawgen (drawings) and stair_symbols (plan views). Same protocol as app_bridge.
"""
from __future__ import annotations

import json
import math

import ifcopenshell.api.aggregate
import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import ifcopenshell.util.unit
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import drawgen
from . import layers
from . import renovation

STAIR_PSET = "KIMBIM_Stair"
RAMP_PSET = "KIMBIM_Ramp"
RAILING_PSET = "KIMBIM_Railing"
STAIR_SHAPES = ("straight", "L", "U", "sketch")
RAMP_SHAPES = ("straight", "L")
STAIR_TYPES = {"straight": "STRAIGHT_RUN_STAIR", "L": "QUARTER_TURN_STAIR", "U": "HALF_TURN_STAIR", "sketch": "USERDEFINED"}
RAMP_TYPES = {"straight": "STRAIGHT_RUN_RAMP", "L": "QUARTER_TURN_RAMP"}

DEFAULTS = {"width": 1.0, "riser": 0.175, "tread": 0.28, "landing": 0.0, "turn": "left", "slope": 8.0}
THICKNESS = 0.2       # metres: the flights' waist and the landings' thickness
U_GAP = 0.1           # metres between the two flights of a U stair (the well)
HEADROOM = 2.0        # metres: the clearance under the floor above that keeps a headroom-only opening
RAMP_THICKNESS = 0.15  # metres
# Building-code checks (warnings): a project setting, these are the defaults (Blondel's 2R+G 600-650 mm).
RULES = {"max_riser": 0.18, "min_tread": 0.25, "step_min": 0.60, "step_max": 0.65, "max_ramp_slope": 8.33}

# Railings (metres)
RAILING_HEIGHT = {"stair": 0.9, "path": 1.1}
RAIL = 0.05           # top rail section
POST = 0.05           # post section
BALUSTER = 0.02       # baluster section
POST_SPACING = 1.2    # at most this far apart
BALUSTER_SPACING = 0.12
INSET = 0.05          # railing axis inside the stair edge


# ---------------------------------------------------------------- maths (pure)

def riser_count(height: float, target: float) -> int:
    """Risers for a level-to-level height at a target riser height (rounded up, at least 2)."""
    if height <= 0 or target <= 0:
        raise ValueError("the height and the riser must be more than 0")
    return max(2, math.ceil(height / target - 1e-9))


def default_tread(riser: float, mode: str = "fixed", fixed: float = DEFAULTS["tread"]) -> float:
    """A new stair's tread (D92): fixed (the default) or from 2 risers + tread = 625 mm (Blondel)."""
    if mode != "blondel":
        return fixed
    return max(RULES["min_tread"], round(0.625 - 2 * riser, 4))


def rules() -> dict:
    """The project's building-code limits (settings `stair_rules`), defaults filled in."""
    from . import settings

    own = settings.current().get("stair_rules") or {}
    return {**RULES, **{k: float(v) for k, v in own.items() if k in RULES}}


def validate_rules(value) -> str | None:
    """None if `value` is a valid `stair_rules` setting (limits in metres, the ramp slope in %)."""
    if not isinstance(value, dict):
        return "stair_rules must be a table"
    for k, v in value.items():
        if k not in RULES:
            return f"unknown stair rule {k}"
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 < v <= (100 if k == "max_ramp_slope" else 2):
            return f"stair rule {k} must be a number above 0"
    merged = {**RULES, **value}
    if merged["step_min"] > merged["step_max"]:
        return "the step range's minimum is above its maximum"
    return None


def stair_warnings(riser: float, tread: float, limits: dict | None = None) -> list[str]:
    """Building-code warnings for a riser and tread (metres): maximum riser, minimum tread and
    2 risers + tread within the step range."""
    r = {**RULES, **(limits or {})}
    out = []
    if riser > r["max_riser"] + 1e-9:
        out.append(f"riser {riser * 1000:.0f} mm is over the {r['max_riser'] * 1000:.0f} mm maximum")
    if tread < r["min_tread"] - 1e-9:
        out.append(f"tread {tread * 1000:.0f} mm is under the {r['min_tread'] * 1000:.0f} mm minimum")
    step = 2 * riser + tread
    if not r["step_min"] - 1e-9 <= step <= r["step_max"] + 1e-9:
        out.append(f"2 risers + tread = {step * 1000:.0f} mm, outside {r['step_min'] * 1000:.0f}-{r['step_max'] * 1000:.0f} mm")
    return out


def ramp_warnings(slope_percent: float, limits: dict | None = None) -> list[str]:
    r = {**RULES, **(limits or {})}
    if slope_percent > r["max_ramp_slope"] + 1e-9:
        return [f"slope {slope_percent:.1f}% (1:{100 / slope_percent:.1f}) is steeper than "
                f"{r['max_ramp_slope']:.2f}% (1:{100 / r['max_ramp_slope']:.0f})"]
    return []


def _unit(v):
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise ValueError("two walking line points are the same")
    return v / n


def _left(d):
    return np.array([-d[1], d[0]])


def _flight(start, d, length, z0, z1, risers=0, riser=0.0, tread=0.0):
    return {"start": np.asarray(start, dtype=float), "dir": _unit(d), "length": float(length), "z0": float(z0),
            "z1": float(z1), "risers": int(risers), "riser": float(riser), "tread": float(tread)}


def _rect(a, d, length, width):
    """The rectangle of a strip of `width` centred on the line from `a` along `d` for `length`."""
    n = _left(d) * width / 2
    b = a + d * length
    return [a - n, b - n, b + n, a + n]


def _split(total: int, weights: list[float], minimum: int) -> list[int]:
    """`total` shared out by weight (largest remainder), each at least `minimum`."""
    k = len(weights)
    if total < minimum * k:
        raise ValueError("too few risers for that many flights")
    spare = total - minimum * k
    w = sum(weights) or 1.0
    raw = [spare * x / w for x in weights]
    out = [int(math.floor(x)) for x in raw]
    for i in sorted(range(k), key=lambda i: raw[i] - out[i], reverse=True)[: spare - sum(out)]:
        out[i] += 1
    return [o + minimum for o in out]


def stair_layout(shape: str, height: float, width: float, riser: float, tread: float, landing: float = 0.0,
                 turn: str = "left", points=None, split: int | None = None, well: float | None = None) -> dict:
    """Flights and landings of a stair in its own frame (metres): the walking line starts at (0, 0) at
    the base, the first flight climbs along +X. Flights: start (walking line, first riser), dir, length,
    risers, tread, z0 (its base), z1/z0 walking heights at its ends; landings: polygon, z (top)."""
    if shape not in STAIR_SHAPES:
        raise ValueError(f"unknown stair shape {shape}")
    if width <= 0 or tread <= 0:
        raise ValueError("the stair needs a width and a tread")
    n = riser_count(height, riser)
    r = height / n
    side = 1.0 if turn != "right" else -1.0
    ld = landing if landing > 0 else width
    flights, landings, walk = [], [], []
    x = np.array([1.0, 0.0])

    def add_flight(start, d, k, z0, g):
        length = (k - 1) * g
        f = _flight(start, d, length, z0, z0 + k * r, k, r, g)
        f["walk0"] = z0 + r
        flights.append(f)
        return f

    if shape == "straight":
        add_flight((0.0, 0.0), x, n, 0.0, tread)
    elif shape in ("L", "U"):
        if n < 4:
            raise ValueError("an L or U stair needs at least 4 risers")
        n1 = math.ceil(n / 2)
        if split is not None:  # D92: an editable split of the risers between the flights
            n1 = int(split)
            if not 2 <= n1 <= n - 2:
                raise ValueError("the flight split leaves fewer than 2 risers in a flight")
        f1 = add_flight((0.0, 0.0), x, n1, 0.0, tread)
        l1 = f1["length"]
        zl = n1 * r
        if shape == "L":
            cx = l1 + ld - width / 2
            poly = [(l1, -side * width / 2), (l1 + ld, -side * width / 2), (l1 + ld, side * width / 2), (l1, side * width / 2)]
            landings.append({"polygon": [np.array(p) for p in poly], "z": zl,
                             "walk": [np.array([cx, 0.0])]})
            add_flight((cx, side * width / 2), (0.0, side), n - n1, zl, tread)
        else:
            gap = U_GAP if well is None else float(well)  # D92: an editable well width
            if gap < 0:
                raise ValueError("the well width can't be negative")
            y2 = side * (width + gap)
            outer = -side * width / 2
            far = side * (width * 1.5 + gap)
            poly = [(l1, outer), (l1 + ld, outer), (l1 + ld, far), (l1, far)]
            landings.append({"polygon": [np.array(p) for p in poly], "z": zl,
                             "walk": [np.array([l1 + ld / 2, 0.0]), np.array([l1 + ld / 2, y2])]})
            add_flight((l1, y2), (-1.0, 0.0), n - n1, zl, tread)
    else:  # by sketch: one flight per segment of the walking line, a landing at each corner
        pts = [np.array([float(p[0]), float(p[1])]) for p in (points or [])]
        pts = [p for i, p in enumerate(pts) if i == 0 or np.linalg.norm(p - pts[i - 1]) > 1e-6]
        if len(pts) < 2:
            raise ValueError("the walking line needs at least two points")
        dirs = [_unit(pts[i + 1] - pts[i]) for i in range(len(pts) - 1)]
        for a, b in zip(dirs, dirs[1:]):
            if float(np.dot(a, b)) < -0.5:
                raise ValueError("the walking line turns back too sharply (use the U shape)")
        k = len(dirs)
        usable = []
        for i in range(k):
            seg = float(np.linalg.norm(pts[i + 1] - pts[i]))
            u = seg - (width / 2 if i > 0 else 0.0) - (width / 2 if i < k - 1 else 0.0)
            if u <= 1e-6:
                raise ValueError("a walking line segment is too short for the stair's width")
            usable.append(u)
        counts = _split(n, usable, 2)
        z = 0.0
        for i in range(k):
            start = pts[i] + (dirs[i] * width / 2 if i > 0 else 0.0)
            g = usable[i] / (counts[i] - 1)
            f = add_flight(start, dirs[i], counts[i], z, g)
            z = f["z1"]
            if i < k - 1:
                landings.append({"polygon": _corner_landing(pts[i + 1], dirs[i], dirs[i + 1], width), "z": z,
                                 "walk": [pts[i + 1]]})
    # The walking line: each flight from its first riser to its top, through the landings.
    for i, f in enumerate(flights):
        walk.append((*f["start"], f["walk0"]))
        walk.append((*(f["start"] + f["dir"] * f["length"]), f["z1"]))
        if i < len(landings):
            walk += [(*p, landings[i]["z"]) for p in landings[i]["walk"]]
    treads = [f["tread"] for f in flights]
    return {"risers": n, "riser": r, "tread": min(treads), "flights": flights, "landings": landings,
            "walk": [tuple(float(v) for v in p) for p in walk], "width": width, "height": height}


def _corner_landing(corner, d1, d2, width):
    """A landing at a walking line corner: the end of the flight coming in, the start of the one going
    out, and the corner where their outer sides meet."""
    h = width / 2
    n1, n2 = _left(d1), _left(d2)
    end_edge = [corner - d1 * h - n1 * h, corner - d1 * h + n1 * h]
    start_edge = [corner + d2 * h - n2 * h, corner + d2 * h + n2 * h]
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < 1e-9:  # straight on: a flat stretch of the walking line
        return _rect(corner - d1 * h, d1, width, width)
    outer = -1.0 if cross > 0 else 1.0  # turning left, the outer side is the right
    p = _line_cross(corner + n1 * h * outer, d1, corner + n2 * h * outer, d2)
    poly = end_edge + [p] + start_edge if outer < 0 else end_edge + start_edge + [p]
    return _hull(poly)


def _line_cross(p, d, q, e):
    """Where the lines p + t d and q + s e meet (None when parallel)."""
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-12:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return p + d * t


def _hull(points):
    pts = sorted({(round(float(p[0]), 9), round(float(p[1]), 9)) for p in points})
    if len(pts) <= 2:
        return [np.array(p) for p in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [np.array(p) for p in lower[:-1] + upper[:-1]]


def ramp_layout(shape: str, height: float, width: float, slope: float, landing: float = 0.0, turn: str = "left") -> dict:
    """Flights and landings of a ramp in its own frame (metres), from the rise and the slope (%)."""
    if shape not in RAMP_SHAPES:
        raise ValueError(f"unknown ramp shape {shape}")
    if width <= 0 or height <= 0 or slope <= 0:
        raise ValueError("the ramp needs a width, a height and a slope")
    run = height / (slope / 100.0)
    side = 1.0 if turn != "right" else -1.0
    ld = landing if landing > 0 else width
    flights, landings = [], []
    if shape == "straight":
        flights.append(_flight((0.0, 0.0), (1.0, 0.0), run, 0.0, height))
    else:
        flights.append(_flight((0.0, 0.0), (1.0, 0.0), run / 2, 0.0, height / 2))
        cx = run / 2 + ld - width / 2
        poly = [(run / 2, -side * width / 2), (run / 2 + ld, -side * width / 2), (run / 2 + ld, side * width / 2),
                (run / 2, side * width / 2)]
        landings.append({"polygon": [np.array(p) for p in poly], "z": height / 2, "walk": [np.array([cx, 0.0])]})
        flights.append(_flight((cx, side * width / 2), (0.0, side), run / 2, height / 2, height))
    walk = []
    for i, f in enumerate(flights):
        f["walk0"] = f["z0"]
        walk.append((*f["start"], f["z0"]))
        walk.append((*(f["start"] + f["dir"] * f["length"]), f["z1"]))
        if i < len(landings):
            walk += [(*p, landings[i]["z"]) for p in landings[i]["walk"]]
    return {"run": run, "flights": flights, "landings": landings, "width": width, "height": height,
            "walk": [tuple(float(v) for v in p) for p in walk]}


def plan_lines(lay: dict, ramp: bool = False, arrow: str = "top", riser_numbers: bool = False) -> dict:
    """The plan symbol's data (stair frame, metres): the walking line with heights, and the stair's
    lines (risers, sides, landing edges) each with the height that decides whether it is above the plan
    cut. Kept in the pset for drawgen, which runs without this module."""
    w = lay["width"]
    lines = []

    def seg(a, b, z):
        lines.append([round(float(a[0]), 4), round(float(a[1]), 4), round(float(b[0]), 4), round(float(b[1]), 4),
                      round(float(z), 4)])

    for f in lay["flights"]:
        s, d = f["start"], f["dir"]
        n = _left(d) * w / 2
        if ramp:
            pieces = max(1, math.ceil(f["length"] / 0.5))
            for j in range(pieces):
                a, b = s + d * f["length"] * j / pieces, s + d * f["length"] * (j + 1) / pieces
                z = f["z0"] + (f["z1"] - f["z0"]) * (j + 1) / pieces
                seg(a - n, b - n, z)
                seg(a + n, b + n, z)
            seg(s - n, s + n, f["z0"])
            seg(s + d * f["length"] - n, s + d * f["length"] + n, f["z1"])
            continue
        k, g, r = f["risers"], f["tread"], f["riser"]
        for j in range(k):
            p = s + d * g * j
            seg(p - n, p + n, f["z0"] + (j + 1) * r)
            if j < k - 1:
                q = p + d * g
                seg(p - n, q - n, f["z0"] + (j + 1) * r)
                seg(p + n, q + n, f["z0"] + (j + 1) * r)
    for landing in lay["landings"]:
        poly = landing["polygon"]
        for i in range(len(poly)):
            seg(poly[i], poly[(i + 1) % len(poly)], landing["z"])
    risers = []  # D92: each riser's number, at its nosing, for the plan's riser numbers
    if not ramp:
        number = 0
        for f in lay["flights"]:
            d = f["dir"]
            for j in range(f["risers"]):
                number += 1
                p = f["start"] + d * f["tread"] * j
                risers.append([round(float(p[0]), 4), round(float(p[1]), 4), round(float(f["z0"] + (j + 1) * f["riser"]), 4),
                               number, round(float(d[0]), 4), round(float(d[1]), 4)])
    return {"w": w, "walk": [[round(v, 4) for v in p] for p in lay["walk"]], "lines": lines, "risers": risers,
            "arrow": arrow, "numbers": bool(riser_numbers), "ramp": ramp}


def side_paths(lay: dict, inset: float = INSET) -> dict:
    """The railing lines along a stair's or ramp's left and right sides (stair frame, metres, with the
    walking height under each point: the nosing line on flights, the top of landings)."""
    out = {}
    w = lay["width"]
    flights = lay["flights"]
    for name, sign in (("left", 1.0), ("right", -1.0)):
        o = sign * (w / 2 - inset)
        path = []
        for i, f in enumerate(flights):
            n = _left(f["dir"])
            a = f["start"] + n * o
            b = a + f["dir"] * f["length"]
            path.append((a, f["walk0"]))
            path.append((b, f["z1"]))
            if i + 1 < len(flights):
                g = flights[i + 1]
                m = _left(g["dir"])
                c = g["start"] + m * o
                zl = lay["landings"][i]["z"] if i < len(lay["landings"]) else f["z1"]
                p = _line_cross(b, f["dir"], c, g["dir"])
                if p is not None and np.linalg.norm(p - b) < 2 * w and np.dot(p - b, f["dir"]) > -1e-9:
                    path.append((p, zl))
                elif p is None and np.dot(n * o, g["start"] - f["start"]) <= 0:  # U, outer side: round the landing
                    poly = lay["landings"][i]["polygon"]
                    depth = max(float(np.dot(q - b, f["dir"])) for q in poly) - inset
                    p1 = b + f["dir"] * depth
                    p2 = c + g["dir"] * float(np.dot(p1 - c, g["dir"]))
                    path += [(p1, zl), (p2, zl)]
        clean = []
        for p, z in path:
            if not clean or np.linalg.norm(p - clean[-1][0]) > 1e-6 or abs(z - clean[-1][1]) > 1e-6:
                clean.append((p, z))
        out[name] = [[float(p[0]), float(p[1]), float(z)] for p, z in clean]
    return out


def railing_parts(path, height: float, post_spacing: float = POST_SPACING, baluster_spacing: float = BALUSTER_SPACING) -> dict:
    """Posts, rails and balusters of a railing along a 3D path (metres): posts at every corner and at
    most `post_spacing` apart, the top rail `height` above the path, balusters between."""
    pts = [np.array(p, dtype=float) for p in path]
    posts, rails, balusters = [], [], []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        run = float(np.linalg.norm(b[:2] - a[:2]))
        if run < 1e-6:
            continue
        rails.append((a + [0, 0, height], b + [0, 0, height]))
        k = max(1, math.ceil(run / post_spacing - 1e-9))
        for j in range(k + (1 if i == len(pts) - 2 else 0)):
            posts.append(a + (b - a) * j / k)
        m = int(run // baluster_spacing)
        for j in range(1, m):
            t = j / m
            if any(abs(t - q / k) * run < (POST + BALUSTER) for q in range(k + 1)):
                continue  # not on a post
            balusters.append(a + (b - a) * t)
    if len(pts) >= 2 and not posts:
        posts.append(pts[0])
    return {"posts": posts, "rails": rails, "balusters": balusters}


# ---------------------------------------------------------------- IFC helpers

def _s() -> float:
    return A._scale()


def _psets(e) -> dict:
    return ifcopenshell.util.element.get_psets(e)


def kind_of(e) -> str | None:
    """'stair', 'ramp' or 'railing' for KimBim's parametric elements, else None."""
    if e is None:
        return None
    if e.is_a("IfcStair") and ifcopenshell.util.element.get_pset(e, STAIR_PSET):
        return "stair"
    if e.is_a("IfcRamp") and ifcopenshell.util.element.get_pset(e, RAMP_PSET):
        return "ramp"
    if e.is_a("IfcRailing") and ifcopenshell.util.element.get_pset(e, RAILING_PSET):
        return "railing"
    return None


def parts(whole) -> list:
    return [o for rel in getattr(whole, "IsDecomposedBy", ()) or () for o in rel.RelatedObjects]


def whole_of(e):
    """The stair or ramp a flight or landing belongs to (None for anything else)."""
    w = ifcopenshell.util.element.get_aggregate(e) if e is not None else None
    return w if w is not None and (w.is_a("IfcStair") or w.is_a("IfcRamp")) else None


def drop_parts(elements: list) -> list:
    """Elements without the parts whose whole is among them (the whole stands for them)."""
    ids = {e.id() for e in elements}
    return [e for e in elements if (w := ifcopenshell.util.element.get_aggregate(e)) is None or w.id() not in ids]


def _set_attr(e, names, value):
    for name in names:
        if hasattr(e, name):
            try:
                setattr(e, name, value)
            except (TypeError, ValueError, RuntimeError):
                pass
            return


def _matrix(x, y, z, angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0, x], [s, c, 0, y], [0, 0, 1, z], [0, 0, 0, 1]], dtype=float)


def _world_si(e) -> np.ndarray:
    m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement).copy()
    m[:3, 3] *= _s()
    return m


def _profile_solid(f, pts_xz, width):
    """An extrusion of a side profile (x along, z up; metres) across `width`, centred on the X axis."""
    s = _s()
    curve = f.createIfcPolyline([f.createIfcCartesianPoint((px / s, pz / s)) for px, pz in pts_xz + [pts_xz[0]]])
    profile = f.createIfcArbitraryClosedProfileDef("AREA", None, curve)
    position = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, width / 2 / s, 0.0)),
                                           f.createIfcDirection((0.0, -1.0, 0.0)), f.createIfcDirection((1.0, 0.0, 0.0)))
    return f.createIfcExtrudedAreaSolid(profile, position, f.createIfcDirection((0.0, 0.0, 1.0)), width / s)


def _flight_profile(fl, ramp):
    """Side profile of a flight in its own frame (x along, z up from its base; metres)."""
    if ramp:
        h, length, t = fl["z1"] - fl["z0"], fl["length"], RAMP_THICKNESS
        if fl["z0"] > 1e-6:
            return [(0.0, 0.0), (length, h), (length, h - t), (0.0, -t)]
        if h > t:
            return [(0.0, 0.0), (length, h), (length, h - t), (length * t / h, 0.0)]
        return [(0.0, 0.0), (length, h), (length, 0.0)]
    k, g, r = fl["risers"], fl["tread"], fl["riser"]
    h, run = k * r, fl["length"]
    pts = [(0.0, 0.0)]
    for i in range(1, k):
        pts += [((i - 1) * g, i * r), (i * g, i * r)]
    pts += [(run, h), (run, max(h - THICKNESS, 0.0)), (min(g, run), 0.0)]
    return pts


def _body(f, items):
    return f.createIfcShapeRepresentation(A._body_context(), "Body", "SweptSolid", items)


def _landing_body(f, polygon):
    s = _s()
    pts = [tuple(float(v) for v in p) for p in polygon]
    curve = f.createIfcPolyline([f.createIfcCartesianPoint((x / s, y / s)) for x, y in pts + [pts[0]]])
    profile = f.createIfcArbitraryClosedProfileDef("AREA", None, curve)
    position = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, -THICKNESS / s)), None, None)
    return _body(f, [f.createIfcExtrudedAreaSolid(profile, position, f.createIfcDirection((0.0, 0.0, 1.0)), THICKNESS / s)])


def _layer_source(whole):
    for p in parts(whole):
        if layers.element_layer(p) is not None:
            return p
    return None


def _pset_edit(f, e, name, props):
    pset = ifcopenshell.util.element.get_pset(e, name)
    entity = f.by_id(pset["id"]) if pset else ifcopenshell.api.pset.add_pset(f, product=e, name=name)
    ifcopenshell.api.pset.edit_pset(f, pset=entity, properties=props)


def _text_props(f, props: dict) -> dict:
    """KimBim's own values: strings as IfcText (the walking line and plan data can pass 255 chars)."""
    return {k: (f.createIfcText(v) if isinstance(v, str) else v) for k, v in props.items()}


def _params(e) -> dict:
    kind = kind_of(e)
    data = ifcopenshell.util.element.get_pset(e, STAIR_PSET if kind == "stair" else RAMP_PSET) or {}
    return data


def _layout_of(e, data=None) -> dict:
    data = data or _params(e)
    if e.is_a("IfcRamp"):
        return ramp_layout(data.get("Shape") or "straight", float(data["Height"]), float(data["Width"]),
                           float(data["Slope"]), float(data.get("LandingDepth") or 0.0), data.get("Turn") or "left")
    points = json.loads(data.get("Points") or "[]")
    split = data.get("FlightSplit")
    return stair_layout(data.get("Shape") or "straight", float(data["Height"]), float(data["Width"]),
                        float(data["Riser"]), float(data["Tread"]), float(data.get("LandingDepth") or 0.0),
                        data.get("Turn") or "left", points,
                        int(split) if split not in (None, "", 0) else None,
                        data.get("WellWidth"))


def _build(whole, lay) -> list:
    """Inside an action: (re)make a stair's or ramp's flights and landings from its layout, reusing
    the parts it has (in order). Returns the GlobalIds of the parts made or changed."""
    f = B._model
    s = _s()
    ramp = whole.is_a("IfcRamp")
    flight_class = "IfcRampFlight" if ramp else "IfcStairFlight"
    old = parts(whole)
    old_flights = sorted([p for p in old if p.is_a(flight_class)], key=lambda p: p.Name or "")
    old_landings = sorted([p for p in old if p.is_a("IfcSlab")], key=lambda p: p.Name or "")
    source = _layer_source(whole)
    world = _world_si(whole)
    made, changed = [], []

    def place(part, local):
        ifcopenshell.api.geometry.edit_object_placement(f, product=part, matrix=world @ local, is_si=True)

    for i, fl in enumerate(lay["flights"]):
        if i < len(old_flights):
            part = old_flights[i]
        else:
            part = ifcopenshell.api.root.create_entity(f, ifc_class=flight_class, name=f"Flight {i + 1}")
            made.append(part)
        part.Name = f"Flight {i + 1}"
        rep = _body(f, [_profile_solid(f, _flight_profile(fl, ramp), lay["width"])])
        if i < len(old_flights):
            A._replace_body(part, rep)
        else:
            ifcopenshell.api.geometry.assign_representation(f, product=part, representation=rep)
            ifcopenshell.api.aggregate.assign_object(f, products=[part], relating_object=whole)
        d = fl["dir"]
        place(part, _matrix(fl["start"][0], fl["start"][1], fl["z0"], math.atan2(d[1], d[0])))
        if ramp:
            _set_attr(part, ("PredefinedType",), "STRAIGHT")
            angle = math.atan2(fl["z1"] - fl["z0"], fl["length"])
            _pset_edit(f, part, "Pset_RampFlightCommon", {"ClearWidth": lay["width"] / s, "Slope": _angle(angle)})
        else:
            _set_attr(part, ("NumberOfRisers", "NumberOfRiser"), fl["risers"])
            _set_attr(part, ("NumberOfTreads",), fl["risers"] - 1)
            _set_attr(part, ("RiserHeight",), fl["riser"] / s)
            _set_attr(part, ("TreadLength",), fl["tread"] / s)
            _set_attr(part, ("PredefinedType",), "STRAIGHT")
            _pset_edit(f, part, "Pset_StairFlightCommon", {
                "NumberOfRiser": fl["risers"], "NumberOfTreads": fl["risers"] - 1,
                "RiserHeight": fl["riser"] / s, "TreadLength": fl["tread"] / s, "WaistThickness": THICKNESS / s})
        changed.append(part)
    for i, landing in enumerate(lay["landings"]):
        if i < len(old_landings):
            part = old_landings[i]
            A._replace_body(part, _landing_body(f, landing["polygon"]))
        else:
            part = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlab", name=f"Landing {i + 1}",
                                                       predefined_type="LANDING")
            ifcopenshell.api.geometry.assign_representation(f, product=part, representation=_landing_body(f, landing["polygon"]))
            ifcopenshell.api.aggregate.assign_object(f, products=[part], relating_object=whole)
            made.append(part)
        part.Name = f"Landing {i + 1}"
        place(part, _matrix(0.0, 0.0, landing["z"], 0.0))
        changed.append(part)
    gone = old_flights[len(lay["flights"]):] + old_landings[len(lay["landings"]):]
    for part in gone:
        ifcopenshell.api.root.remove_product(f, product=part)
    for part in made:
        if source is not None:
            layers.copy_layer(source, part)
        else:
            layers.assign_active(part)
        renovation.copy_status(whole, part)
    return [p.GlobalId for p in changed]


def _angle(radians: float) -> float:
    """A plane angle in the project's unit (new projects: radians; many IFC2X3 files: degrees)."""
    unit = ifcopenshell.util.unit.get_project_unit(B._model, "PLANEANGLEUNIT")
    if unit is not None and unit.is_a("IfcConversionBasedUnit") and "DEGREE" in (unit.Name or "").upper():
        return math.degrees(radians)
    return radians


# ---------------------------------------------------------------- stairs and ramps

def _whole_params(e, lay) -> None:
    """Inside an action: the IFC common properties of a stair or ramp from its layout."""
    f = B._model
    s = _s()
    data = _params(e)
    if e.is_a("IfcRamp"):
        shape = data.get("Shape") or "straight"
        _set_attr(e, ("PredefinedType", "ShapeType"), RAMP_TYPES[shape])
        _pset_edit(f, e, "Pset_RampCommon", {"RequiredSlope": _angle(math.atan(float(data["Slope"]) / 100.0)),
                                              "HandicapAccessible": float(data["Slope"]) <= rules()["max_ramp_slope"] + 1e-9})
    else:
        shape = data.get("Shape") or "straight"
        _set_attr(e, ("PredefinedType", "ShapeType"), STAIR_TYPES[shape])
        e.ObjectType = "BY_SKETCH" if shape == "sketch" else None
        _pset_edit(f, e, "Pset_StairCommon", {
            "NumberOfRiser": lay["risers"], "NumberOfTreads": lay["risers"] - len(lay["flights"]),
            "RiserHeight": lay["riser"] / s, "TreadLength": lay["tread"] / s, "WaistThickness": THICKNESS / s})
    from . import settings

    prefs = settings.current()  # D92: the drawing settings are kept with each stair's plan data
    _pset_edit(f, e, STAIR_PSET if e.is_a("IfcStair") else RAMP_PSET,
               _text_props(f, {"Plan": json.dumps(plan_lines(lay, e.is_a("IfcRamp"), prefs.get("stair_arrow") or "top",
                                                             bool(prefs.get("stair_riser_numbers"))),
                               separators=(",", ":"))}))


def _make(kind: str, storey, x, y, angle, params: dict) -> dict:
    """Inside an action: a new stair or ramp. Returns {whole, layout}."""
    f = B._model
    lay = ramp_layout(params["Shape"], params["Height"], params["Width"], params["Slope"], params["LandingDepth"],
                      params["Turn"]) if kind == "ramp" else \
        stair_layout(params["Shape"], params["Height"], params["Width"], params["Riser"], params["Tread"],
                     params["LandingDepth"], params["Turn"], json.loads(params.get("Points") or "[]"),
                     params.get("FlightSplit") or None, params.get("WellWidth"))
    if kind == "ramp":
        whole = ifcopenshell.api.root.create_entity(f, ifc_class="IfcRamp", name="Ramp")
    else:
        whole = ifcopenshell.api.root.create_entity(f, ifc_class="IfcStair", name="Stair")
    ifcopenshell.api.geometry.edit_object_placement(f, product=whole, matrix=_matrix(x, y, A._elevation(storey), angle),
                                                    is_si=True)
    ifcopenshell.api.spatial.assign_container(f, products=[whole], relating_structure=storey)
    _pset_edit(f, whole, RAMP_PSET if kind == "ramp" else STAIR_PSET, _text_props(f, params))
    renovation.stamp_new(whole)
    _build(whole, lay)
    for p in parts(whole):
        layers.assign_active(p)
    _whole_params(whole, lay)
    return {"whole": whole, "layout": lay}


def _options(options_json: str) -> dict:
    try:
        o = json.loads(options_json) if options_json else {}
    except ValueError as ex:
        raise ValueError(f"bad options: {ex}") from ex
    if not isinstance(o, dict):
        raise ValueError("bad options")
    return o


def _number(o: dict, key: str, default: float) -> float:
    v = o.get(key, default)
    try:
        return float(default if v in (None, "") else v)
    except (TypeError, ValueError) as ex:
        raise ValueError(f"{key} must be a number") from ex


def create_stair(storey_guid: str, x, y, angle, width, height, options_json: str = "") -> str:
    """A stair from (x, y) climbing in direction `angle` (radians) up `height` metres (the level-to-level
    height), `width` wide. Options (JSON): shape (straight, L, U, sketch), turn (left, right), riser
    (target, metres), tread, landing (depth; 0 = the width), points (the walking line for a stair by
    sketch, world metres: then x, y and angle come from it), cut_slab (default true: an opening in the
    floor slab where the stair arrives). Reports the risers, the riser height and code warnings."""
    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    try:
        x, y, angle, width, height = float(x), float(y), float(angle), float(width), float(height)
        o = _options(options_json)
        shape = o.get("shape") or "straight"
        turn = "right" if o.get("turn") == "right" else "left"
        from . import settings

        st = settings.current()
        riser = _number(o, "riser", float(st.get("stair_riser", DEFAULTS["riser"])))
        mode = o.get("tread_mode") or st.get("stair_tread_mode") or "fixed"  # D92: fixed or from 2R+G
        if mode not in ("fixed", "blondel"):
            raise ValueError(f"unknown tread mode {mode}")
        tread = _number(o, "tread", default_tread(riser, mode, float(st.get("stair_tread", DEFAULTS["tread"]))))
        landing = _number(o, "landing", 0.0)
        split = int(o["split"]) if o.get("split") not in (None, "", 0) else None
        well = _number(o, "well", U_GAP) if o.get("well") not in (None, "") else None
        opening = o.get("opening") or "whole"
        if opening not in ("whole", "headroom"):
            raise ValueError(f"unknown opening {opening}")
        local = []
        if shape == "sketch":
            world = [(float(p[0]), float(p[1])) for p in o.get("points") or []]
            if len(world) < 2:
                raise ValueError("the walking line needs at least two points")
            x, y = world[0]
            angle = math.atan2(world[1][1] - y, world[1][0] - x)
            c, sn = math.cos(-angle), math.sin(-angle)
            local = [[round((px - x) * c - (py - y) * sn, 9), round((px - x) * sn + (py - y) * c, 9)] for px, py in world]
        if width <= 0 or height <= 0:
            raise ValueError("the stair needs a width and a height")
        lay = stair_layout(shape, height, width, riser, tread, landing, turn, local, split, well)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    params = {"Shape": shape, "Turn": turn, "Width": width, "Height": height, "Riser": riser, "Tread": tread,
              "TreadMode": mode, "LandingDepth": landing, "Points": json.dumps(local),
              "CutSlab": o.get("cut_slab", True) is not False, "Opening": opening}
    if split is not None:
        params["FlightSplit"] = split
    if well is not None:
        params["WellWidth"] = well
    made = {}

    def action():
        made.update(_make("stair", storey, x, y, angle, params))
        whole = made["whole"]
        return 1, [whole.GlobalId, *(p.GlobalId for p in parts(whole))], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["whole"].GlobalId, "risers": lay["risers"], "riser": round(lay["riser"], 6),
                    "tread": round(lay["tread"], 6), "run": round(lay["flights"][0]["length"], 6),
                    "flights": len(lay["flights"]), "landings": len(lay["landings"]),
                    "warnings": stair_warnings(lay["riser"], lay["tread"], rules())})


def create_ramp(storey_guid: str, x, y, angle, width, height, options_json: str = "") -> str:
    """A ramp from (x, y) going up in direction `angle` (radians), rising `height` metres at a slope
    (options: slope in percent, default 8), straight or L (shape, turn, landing)."""
    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    try:
        x, y, angle, width, height = float(x), float(y), float(angle), float(width), float(height)
        o = _options(options_json)
        shape = o.get("shape") or "straight"
        turn = "right" if o.get("turn") == "right" else "left"
        slope, landing = _number(o, "slope", DEFAULTS["slope"]), _number(o, "landing", 0.0)
        lay = ramp_layout(shape, height, width, slope, landing, turn)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    params = {"Shape": shape, "Turn": turn, "Width": width, "Height": height, "Slope": slope, "LandingDepth": landing}
    made = {}

    def action():
        made.update(_make("ramp", storey, x, y, angle, params))
        whole = made["whole"]
        return 1, [whole.GlobalId, *(p.GlobalId for p in parts(whole))], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["whole"].GlobalId, "run": round(lay["run"], 6), "flights": len(lay["flights"]),
                    "warnings": ramp_warnings(slope, rules())})


def stair_preview(kind: str, x, y, angle, width, height, options_json: str = "") -> str:
    """The outlines a stair or ramp would have (world metres), for the tool's preview: flights as
    [start, end, width] strips and landings as polygons; plus risers, riser and warnings."""
    try:
        x, y, angle, width, height = float(x), float(y), float(angle), float(width), float(height)
        o = _options(options_json)
        shape = o.get("shape") or "straight"
        turn = "right" if o.get("turn") == "right" else "left"
        if kind == "ramp":
            slope = _number(o, "slope", DEFAULTS["slope"])
            lay = ramp_layout(shape, height, width, slope, _number(o, "landing", 0.0), turn)
            info = {"run": round(lay["run"], 6), "warnings": ramp_warnings(slope, rules())}
        else:
            local = []
            if shape == "sketch":
                world = [(float(p[0]), float(p[1])) for p in o.get("points") or []]
                if len(world) < 2:
                    return B._dump({"ok": True, "flights": [], "landings": []})
                x, y = world[0]
                angle = math.atan2(world[1][1] - y, world[1][0] - x)
                c, sn = math.cos(-angle), math.sin(-angle)
                local = [[(px - x) * c - (py - y) * sn, (px - x) * sn + (py - y) * c] for px, py in world]
            lay = stair_layout(shape, height, width, _number(o, "riser", DEFAULTS["riser"]),
                               _number(o, "tread", DEFAULTS["tread"]), _number(o, "landing", 0.0), turn, local)
            info = {"risers": lay["risers"], "riser": round(lay["riser"], 6), "tread": round(lay["tread"], 6),
                    "warnings": stair_warnings(lay["riser"], lay["tread"], rules())}
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    m = _matrix(x, y, 0.0, angle)

    def w(p):
        q = m @ np.array([p[0], p[1], 0.0, 1.0])
        return [round(float(q[0]), 6), round(float(q[1]), 6)]

    flights = [{"a": w(f["start"]), "b": w(f["start"] + f["dir"] * f["length"]), "z0": round(f["z0"], 6),
                "z1": round(f["z1"], 6)} for f in lay["flights"]]
    landings = [{"points": [w(p) for p in landing["polygon"]], "z": round(landing["z"], 6)} for landing in lay["landings"]]
    return B._dump({"ok": True, "width": width, "flights": flights, "landings": landings, **info})


# ---------------------------------------------------------------- editing parameters

STAIR_DIMENSIONS = (("Width", "Width"), ("Tread", "Tread"), ("Riser (target)", "Riser"), ("Landing depth", "LandingDepth"),
                    ("Flight split", "FlightSplit"), ("Well width", "WellWidth"))
RAMP_DIMENSIONS = (("Width", "Width"), ("Height", "Height"), ("Slope %", "Slope"), ("Landing depth", "LandingDepth"))


def dimensions(e) -> list[tuple[str, float, bool]]:
    """The Properties panel's Dimensions of a stair, ramp or railing (editable: they rebuild it)."""
    kind = kind_of(e)
    if kind == "railing":
        return [("Height", float(ifcopenshell.util.element.get_pset(e, RAILING_PSET).get("Height") or 0.0), True)]
    if kind is None:
        return []
    data = _params(e)
    out = [(label, float(data.get(key) or 0.0), True) for label, key in (RAMP_DIMENSIONS if kind == "ramp" else STAIR_DIMENSIONS)
           if key not in ("FlightSplit", "WellWidth")]
    if kind == "stair":
        out.insert(1, ("Height", float(data.get("Height") or 0.0), True))
        if data.get("Shape") in ("L", "U"):  # D92: the risers shared between the flights, editable
            fl = _layout_of(e)["flights"]
            out.append(("Flight split", float(fl[0]["risers"] if fl else 0), True))
        if data.get("Shape") == "U":  # D92: the well between the two flights
            out.append(("Well width", float(data.get("WellWidth") or U_GAP), True))
    return out


def set_dimension(elements, name: str, value: float):
    """Plan an edit of a stair/ramp/railing dimension: (count, action) or an error string."""
    plan = []
    for e in elements:
        kind = kind_of(e)
        if kind is None:
            continue
        if kind == "railing":
            if name == "Height":
                plan.append((e, RAILING_PSET, "Height"))
            continue
        table = dict(RAMP_DIMENSIONS if kind == "ramp" else STAIR_DIMENSIONS + (("Height", "Height"),))
        if name not in table:
            continue
        key = table[name]
        if key == "LandingDepth" and value < 0:
            return "the landing depth can't be negative"
        if key == "FlightSplit":
            value = float(int(round(value)))
            if value < 2:
                return "the flight split needs at least 2 risers in each flight"
        if key == "WellWidth" and value < 0:
            return "the well width can't be negative"
        data = {**_params(e), key: value}
        try:
            _layout_of(e, data)
        except (TypeError, ValueError) as ex:
            return str(ex)
        plan.append((e, RAMP_PSET if kind == "ramp" else STAIR_PSET, key))
    if not plan:
        return None

    def apply():
        changed = []
        for e, pset, key in plan:
            props = {key: value}
            if key == "Riser" and _params(e).get("TreadMode") == "blondel":
                props["Tread"] = default_tread(value, "blondel")  # D92: the tread follows the riser
            _pset_edit(B._model, e, pset, props)
            changed += rebuild(e)
        return changed

    return len(plan), apply


def set_stair_params(guid: str, params_json: str) -> str:
    """Change a stair's or ramp's parameters (JSON: Shape, Turn, Width, Height, Riser, Tread,
    LandingDepth, Slope) and rebuild it."""
    e = A._by_guid(guid) if B._model is not None else None
    kind = kind_of(e)
    if kind not in ("stair", "ramp"):
        return A._fail("not a KimBim stair or ramp")
    try:
        new = json.loads(params_json)
        allowed = ("Shape", "Turn", "Width", "Height", "Slope", "LandingDepth") if kind == "ramp" else \
            ("Shape", "Turn", "Width", "Height", "Riser", "Tread", "TreadMode", "LandingDepth", "FlightSplit",
             "WellWidth", "Opening")
        new = {k: (v if k in ("Shape", "Turn", "TreadMode", "Opening") else
                   int(v) if k == "FlightSplit" else float(v))
               for k, v in new.items() if k in allowed}
        if new.get("Opening") not in (None, "whole", "headroom"):
            return A._fail(f"unknown opening {new['Opening']}")
        if new.get("TreadMode") not in (None, "fixed", "blondel"):
            return A._fail(f"unknown tread mode {new['TreadMode']}")
        if new.get("TreadMode", _params(e).get("TreadMode") or "fixed") == "blondel" and "Tread" not in new:
            new["Tread"] = default_tread(float(new.get("Riser", _params(e)["Riser"])), "blondel")
        data = {**_params(e), **new}
        lay = _layout_of(e, data)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))

    def action():
        _pset_edit(B._model, e, RAMP_PSET if kind == "ramp" else STAIR_PSET, new)
        return 1, rebuild(e), []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    warnings = ramp_warnings(float(data["Slope"]), rules()) if kind == "ramp" else stair_warnings(lay["riser"], lay["tread"], rules())
    return B._dump({**r, "warnings": warnings})


def rebuild(e) -> list:
    """Inside an action: rebuild a stair or ramp from its parameters (and what follows it). Returns
    the GlobalIds whose shapes changed."""
    kind = kind_of(e)
    if kind not in ("stair", "ramp"):
        return [e.GlobalId] if kind == "railing" and _rebuild_railing(e) else []
    lay = _layout_of(e)
    changed = _build(e, lay)
    _whole_params(e, lay)
    return [e.GlobalId, *changed, *_follow_whole(e)]


def stair_info(guid: str) -> str:
    """A stair's or ramp's parameters, risers and warnings (for the app's status line)."""
    e = A._by_guid(guid) if B._model is not None else None
    kind = kind_of(e)
    if kind not in ("stair", "ramp"):
        return A._fail("not a KimBim stair or ramp")
    data = {k: v for k, v in _params(e).items() if k not in ("id", "Plan")}
    lay = _layout_of(e)
    out = {"ok": True, "kind": kind, "params": data, "flights": len(lay["flights"]), "landings": len(lay["landings"])}
    if kind == "stair":
        out.update(risers=lay["risers"], riser=round(lay["riser"], 6), tread=round(lay["tread"], 6),
                   warnings=stair_warnings(lay["riser"], lay["tread"], rules()))
    else:
        out.update(run=round(lay["run"], 6), warnings=ramp_warnings(float(data["Slope"]), rules()))
    return B._dump(out)


# ---------------------------------------------------------------- railings

def _railing_body(f, path, height):
    s = _s()
    items = []
    bits = railing_parts(path, height)
    centre = f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0)), None)  # required in IFC2X3
    post = f.createIfcRectangleProfileDef("AREA", None, centre, POST / s, POST / s)
    baluster = f.createIfcRectangleProfileDef("AREA", None, centre, BALUSTER / s, BALUSTER / s)
    rail = f.createIfcRectangleProfileDef("AREA", None, centre, RAIL / s, RAIL / s)
    up = f.createIfcDirection((0.0, 0.0, 1.0))

    def vertical(profile, p, length):
        position = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint(tuple(float(v) / s for v in p)), None, None)
        return f.createIfcExtrudedAreaSolid(profile, position, up, length / s)

    for p in bits["posts"]:
        items.append(vertical(post, p, height))
    for p in bits["balusters"]:
        items.append(vertical(baluster, p, height - RAIL))
    for a, b in bits["rails"]:
        d = b - a
        length = float(np.linalg.norm(d))
        axis = d / length
        ref = np.cross([0.0, 0.0, 1.0], axis)
        ref = ref / np.linalg.norm(ref) if np.linalg.norm(ref) > 1e-9 else np.array([1.0, 0.0, 0.0])
        position = f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint(tuple(float(v) / s for v in (a - [0, 0, RAIL / 2]))),
            f.createIfcDirection(tuple(float(v) for v in axis)), f.createIfcDirection(tuple(float(v) for v in ref)))
        items.append(f.createIfcExtrudedAreaSolid(rail, position, up, length / s))
    return _body(f, items), bits


def _host_path(host, side):
    lay = _layout_of(host)
    return side_paths(lay)[side]


def _rebuild_railing(railing) -> bool:
    """Inside an action: rebuild a railing from its pset (on its host's side when it has one).
    False when its host is gone (the railing keeps its last shape)."""
    f = B._model
    data = ifcopenshell.util.element.get_pset(railing, RAILING_PSET) or {}
    height = float(data.get("Height") or RAILING_HEIGHT["path"])
    host = A._by_guid(data.get("Host") or "")
    if data.get("Host"):
        if host is None or kind_of(host) not in ("stair", "ramp"):
            return False
        path = _host_path(host, data.get("Side") or "left")
        ifcopenshell.api.geometry.edit_object_placement(f, product=railing, matrix=_world_si(host), is_si=True)
        _pset_edit(f, railing, RAILING_PSET, _text_props(f, {"Path": json.dumps([[round(v, 6) for v in p] for p in path])}))
    else:
        path = json.loads(data.get("Path") or "[]")
    rep, bits = _railing_body(f, path, height)
    A._replace_body(railing, rep)
    _pset_edit(f, railing, "Pset_RailingCommon", {"Height": height / _s()})
    _pset_edit(f, railing, RAILING_PSET, {"Posts": len(bits["posts"])})
    return True


def _new_railing(storey, matrix_si, props) -> object:
    f = B._model
    railing = ifcopenshell.api.root.create_entity(f, ifc_class="IfcRailing", name="Railing")
    _set_attr(railing, ("PredefinedType",), "BALUSTRADE")
    ifcopenshell.api.geometry.edit_object_placement(f, product=railing, matrix=matrix_si, is_si=True)
    ifcopenshell.api.spatial.assign_container(f, products=[railing], relating_structure=storey)
    _pset_edit(f, railing, RAILING_PSET, _text_props(f, props))
    rep, _ = _railing_body(f, json.loads(props.get("Path") or "[]") or [[0, 0, 0], [1, 0, 0]], props["Height"])
    ifcopenshell.api.geometry.assign_representation(f, product=railing, representation=rep)
    _rebuild_railing(railing)
    layers.assign_active(railing)
    renovation.stamp_new(railing)
    return railing


def railings_of(host) -> list:
    """The railings that follow this stair or ramp."""
    out = []
    for r in B._model.by_type("IfcRailing"):
        data = ifcopenshell.util.element.get_pset(r, RAILING_PSET)
        if data and data.get("Host") == host.GlobalId:
            out.append(r)
    return out


def add_stair_railings(guid: str, height="", sides: str = "both") -> str:
    """Railings on a stair's or ramp's sides (left, right or both), following it from now on.
    A side that already has one is left as it is. Height in metres (default 0.9)."""
    host = A._by_guid(guid) if B._model is not None else None
    if host is not None and whole_of(host) is not None:
        host = whole_of(host)
    if kind_of(host) not in ("stair", "ramp"):
        return A._fail("click a stair or ramp drawn with KimBim")
    try:
        height = float(height) if str(height).strip() else RAILING_HEIGHT["stair"]
    except ValueError:
        return A._fail(f"not a number: {height}")
    if not 0.3 <= height <= 3.0:
        return A._fail("the railing height must be between 0.3 and 3 m")
    storey = ifcopenshell.util.element.get_container(host)
    have = {(ifcopenshell.util.element.get_pset(r, RAILING_PSET) or {}).get("Side") for r in railings_of(host)}
    wanted = [s for s in (("left", "right") if sides == "both" else (sides,)) if s in ("left", "right") and s not in have]
    if not wanted:
        return A._fail("that stair already has its railings")
    made = []

    def action():
        for side in wanted:
            made.append(_new_railing(storey, _world_si(host), {"Host": host.GlobalId, "Side": side, "Height": height,
                                                               "Path": "[]"}))
        return len(made), [r.GlobalId for r in made], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    posts = [int(ifcopenshell.util.element.get_pset(m, RAILING_PSET).get("Posts") or 0) for m in made]
    return B._dump({**r, "guids": [m.GlobalId for m in made], "posts": posts})


def create_railing(storey_guid: str, points_json: str, height="") -> str:
    """A railing along a path clicked on a level (world metres), `height` high (default 1.1 m)."""
    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    try:
        pts = [(float(p[0]), float(p[1])) for p in json.loads(points_json)]
        height = float(height) if str(height).strip() else RAILING_HEIGHT["path"]
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    pts = [p for i, p in enumerate(pts) if i == 0 or math.dist(p, pts[i - 1]) > 1e-6]
    if len(pts) < 2:
        return A._fail("the railing needs at least two points")
    if not 0.3 <= height <= 3.0:
        return A._fail("the railing height must be between 0.3 and 3 m")
    x0, y0 = pts[0]
    local = [[round(x - x0, 6), round(y - y0, 6), 0.0] for x, y in pts]
    made = {}

    def action():
        made["r"] = _new_railing(storey, _matrix(x0, y0, A._elevation(storey), 0.0),
                                 {"Host": "", "Side": "", "Height": height, "Path": json.dumps(local)})
        return 1, [made["r"].GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    posts = int(ifcopenshell.util.element.get_pset(made["r"], RAILING_PSET).get("Posts") or 0)
    return B._dump({**r, "guid": made["r"].GlobalId, "posts": posts})


def stair_at(storey_guid: str, x, y) -> str:
    """The KimBim stair or ramp on a level whose outline holds the point (world metres), if any."""
    storey = A._by_guid(storey_guid) if B._model is not None else None
    if storey is None:
        return B._dump({"guid": ""})
    p = (float(x), float(y))
    for rel in getattr(storey, "ContainsElements", ()) or ():
        for e in rel.RelatedElements:
            if kind_of(e) in ("stair", "ramp"):
                for poly in _footprint(e):
                    if _inside(p, poly):
                        return B._dump({"guid": e.GlobalId})
    return B._dump({"guid": ""})


def _inside(p, poly) -> bool:
    x, y = p
    inside = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _footprint(e) -> list:
    """A stair's or ramp's flights and landings as plan polygons (world metres)."""
    lay = _layout_of(e)
    m = _world_si(e)

    def w(p):
        q = m @ np.array([p[0], p[1], 0.0, 1.0])
        return (float(q[0]), float(q[1]))

    out = [[w(p) for p in _rect(fl["start"], fl["dir"], fl["length"], lay["width"])] for fl in lay["flights"]]
    out += [[w(p) for p in landing["polygon"]] for landing in lay["landings"]]
    return out


# ---------------------------------------------------------------- the floor above: an opening

def _headroom_footprint(e) -> list:
    """The part of the stair that leaves too little headroom under the floor above (D92): only that
    part of the footprint is cut, so the slab stays over the lower steps."""
    lay = _layout_of(e)
    m = _world_si(e)
    top = float(_params(e).get("Height") or 0.0)
    limit = top - HEADROOM

    def w(p):
        q = m @ np.array([p[0], p[1], 0.0, 1.0])
        return (float(q[0]), float(q[1]))

    out = []
    for fl in lay["flights"]:
        z0, z1 = fl["z0"], fl["z1"]
        if z1 <= limit + 1e-9:
            continue  # the whole flight has headroom: the slab stays over it
        t = 0.0 if z0 >= limit else (limit - z0) / (z1 - z0)
        start = fl["start"] + fl["dir"] * fl["length"] * t
        out.append([w(p) for p in _rect(start, fl["dir"], fl["length"] * (1 - t), lay["width"])])
    for landing in lay["landings"]:
        if landing["z"] > limit + 1e-9:
            out.append([w(p) for p in landing["polygon"]])
    return out


def _outline(polys):
    """One outline around the stair's pieces (the U stair's well closed), or the pieces when shapely
    is missing."""
    try:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
    except ImportError:
        return polys
    shape = unary_union([Polygon(p).buffer(0) for p in polys if len(p) >= 3])
    shape = shape.buffer(U_GAP / 2 + 0.01, join_style=2).buffer(-(U_GAP / 2 + 0.01), join_style=2)
    geoms = getattr(shape, "geoms", [shape])
    return [list(g.exterior.coords)[:-1] for g in geoms if not g.is_empty]


def _slabs_above(e):
    """Floor slabs on the level where the stair or ramp arrives (top within 5 cm of its top)."""
    storey = ifcopenshell.util.element.get_container(e)
    if storey is None:
        return []
    top = A._elevation(storey) + float(_params(e).get("Height") or 0.0)
    out = []
    for s in B._model.by_type("IfcBuildingStorey"):
        if abs(A._elevation(s) - top) > 0.05:
            continue
        for rel in getattr(s, "ContainsElements", ()) or ():
            out += [x for x in rel.RelatedElements if x.is_a("IfcSlab") and getattr(x, "PredefinedType", None) != "LANDING"]
    return out


def _sync_opening(e) -> list:
    """Inside an action: the openings a stair cuts in the floor above, made again when the stair's
    outline changed. Returns the slabs whose shapes changed."""
    from . import editing

    f = B._model
    data = _params(e)
    if e.is_a("IfcRamp") or data.get("CutSlab") is False:
        wanted, slabs = [], []
    else:
        outline = _outline(_headroom_footprint(e) if data.get("Opening") == "headroom" else _footprint(e))
        slabs = []
        try:
            from shapely.geometry import Polygon
        except ImportError:
            Polygon = None
        for slab in _slabs_above(e):
            shape = editing._slab_outline_world(slab)
            if len(shape) < 3:
                continue
            if Polygon is not None and not any(Polygon(shape).buffer(0).intersects(Polygon(o).buffer(0)) for o in outline):
                continue
            slabs.append(slab)
        wanted = [[[round(x, 4), round(y, 4)] for x, y in o] for o in outline] if slabs else []
    key = json.dumps({"slabs": [s.GlobalId for s in slabs], "outline": wanted})
    if key == (data.get("OpeningKey") or json.dumps({"slabs": [], "outline": []})):
        return []
    changed = set()
    for g in json.loads(data.get("Openings") or "[]"):
        opening = A._by_guid(g)
        if opening is not None:
            changed.update(v.RelatingBuildingElement.GlobalId for v in getattr(opening, "VoidsElements", ()) or ())
            ifcopenshell.api.root.remove_product(f, product=opening)
    made = []
    for slab in slabs:
        for poly in wanted:
            made.append(A._cut_slab(slab, [tuple(p) for p in poly], "Stair opening").GlobalId)
        changed.add(slab.GlobalId)
    _pset_edit(f, e, STAIR_PSET, _text_props(f, {"Openings": json.dumps(made), "OpeningKey": key}))
    return sorted(changed)


def _follow_whole(e) -> list:
    """Inside an action: what follows a stair or ramp (its railings, the opening above)."""
    out = []
    for r in railings_of(e):
        if _rebuild_railing(r):
            out.append(r.GlobalId)
    out += _sync_opening(e)
    return out


def _follow(changed, removed) -> list:
    """AFTER_ACTION: a stair or ramp that moved, turned or changed takes its parts, railings and
    floor opening along (same undo step)."""
    if B._model is None or not changed:
        return []
    wholes = {}
    for g in changed:
        e = A._by_guid(g)
        if e is None:
            continue
        w = e if e.is_a("IfcStair") or e.is_a("IfcRamp") else whole_of(e) if (e.is_a("IfcStairFlight") or e.is_a("IfcRampFlight") or e.is_a("IfcSlab")) else None
        if w is not None and kind_of(w) is not None:
            wholes[w.id()] = w
    out = []
    for w in wholes.values():
        out += [p.GlobalId for p in parts(w)]
        out += _follow_whole(w)
    return out


B.AFTER_ACTION.append(_follow)


# ---------------------------------------------------------------- deleting, copying, mirroring

def cascade(elements: list) -> tuple[list, list]:
    """For a delete: add the parts and railings of the stairs and ramps being deleted; returns
    (openings to remove, slabs to re-mesh)."""
    openings, slabs = [], []
    for e in list(elements):
        if kind_of(e) not in ("stair", "ramp"):
            continue
        for p in parts(e) + railings_of(e):
            if p not in elements:
                elements.append(p)
        for g in json.loads(_params(e).get("Openings") or "[]"):
            opening = A._by_guid(g)
            if opening is not None:
                openings.append(opening)
                slabs += [v.RelatingBuildingElement for v in getattr(opening, "VoidsElements", ()) or ()]
    return openings, slabs


def after_copy(pairs) -> None:
    """Inside an action, after copying: copied stairs and ramps get their own parts (and no openings
    yet); copied railings follow the copy of their stair, or keep their shape as a path railing."""
    f = B._model
    copies = {src.GlobalId: c for src, c in pairs}
    for src, c in pairs:
        kind = kind_of(c)
        if kind in ("stair", "ramp"):
            for p in parts(c):
                ifcopenshell.api.root.remove_product(f, product=p)
            if kind == "stair":
                _pset_edit(f, c, STAIR_PSET, _text_props(f, {"Openings": "[]", "OpeningKey": ""}))
            lay = _layout_of(c)
            _build(c, lay)
            for p in parts(src)[:1]:
                for q in parts(c):
                    layers.copy_layer(p, q)
            if kind == "stair":
                _sync_opening(c)
    for src, c in pairs:
        if kind_of(c) == "railing":
            data = ifcopenshell.util.element.get_pset(c, RAILING_PSET) or {}
            host = copies.get(data.get("Host") or "")
            if host is not None:
                _pset_edit(f, c, RAILING_PSET, {"Host": host.GlobalId})
            elif data.get("Host"):
                _pset_edit(f, c, RAILING_PSET, {"Host": "", "Side": ""})  # copied alone: a path railing now
            _rebuild_railing(c)


def mirror(e, point, direction) -> bool:
    """Inside an action: mirror a stair, ramp or railing in place: its placement reflected, an L/U turn
    the other way, a sketch's walking line and a path railing's points reflected; rebuilt."""
    from . import editing

    kind = kind_of(e)
    if kind is None:
        return False
    editing._mirror_placement(e, point, direction)
    f = B._model
    if kind in ("stair", "ramp"):
        data = _params(e)
        pset = RAMP_PSET if kind == "ramp" else STAIR_PSET
        props = {"Turn": "right" if (data.get("Turn") or "left") == "left" else "left"}
        if data.get("Points"):
            props["Points"] = json.dumps([[p[0], -p[1]] for p in json.loads(data["Points"])])
        _pset_edit(f, e, pset, _text_props(f, props))
        rebuild(e)
    else:
        data = ifcopenshell.util.element.get_pset(e, RAILING_PSET) or {}
        if not data.get("Host"):
            path = [[p[0], -p[1], p[2]] for p in json.loads(data.get("Path") or "[]")]
            _pset_edit(f, e, RAILING_PSET, _text_props(f, {"Path": json.dumps(path)}))
        _rebuild_railing(e)
    return True


# ---------------------------------------------------------------- plan symbols and selection

def refresh_plan_settings() -> None:
    """Update every stair's stored plan data after the stair drawing settings change (no undo step:
    the settings change itself already marks the project)."""
    if B._model is None:
        return
    from . import settings

    prefs = settings.current()
    for e in B._model.by_type("IfcStair"):
        if kind_of(e) != "stair":
            continue
        try:
            lay = _layout_of(e)
            plan = plan_lines(lay, False, prefs.get("stair_arrow") or "top", bool(prefs.get("stair_riser_numbers")))
        except (TypeError, ValueError):
            continue
        _pset_edit(B._model, e, STAIR_PSET, _text_props(B._model, {"Plan": json.dumps(plan, separators=(",", ":"))}))


def stair_symbols(storey_guid: str, cut="") -> str:
    """The plan symbols of the stairs and ramps on a level (world metres), for plan views: solid and
    dashed polylines and labels, with the cut height above the level (default: the project's)."""
    storey = A._by_guid(storey_guid) if B._model is not None else None
    out = []
    if storey is None:
        return B._dump({"symbols": out})
    try:
        from . import settings

        cut = float(cut) if str(cut).strip() else float(settings.current().get("plan_cut_height") or drawgen.PLAN_CUT)
    except ValueError:
        cut = drawgen.PLAN_CUT
    s = _s()
    for rel in getattr(storey, "ContainsElements", ()) or ():
        for e in rel.RelatedElements:
            kind = kind_of(e)
            if kind not in ("stair", "ramp"):
                continue
            data = _params(e)
            try:
                plan = json.loads(data.get("Plan") or "{}")
            except ValueError:
                continue
            if not plan:
                continue
            m = ifcopenshell.util.placement.get_local_placement(e.ObjectPlacement)
            base = float(m[2][3]) * s - A._elevation(storey)
            solid, dashed, labels = drawgen.stair_symbol(plan, cut - base, False,
                                                         plan.get("arrow") or "top", bool(plan.get("numbers")))

            def w(p):
                q = m @ np.array([p[0] / s, p[1] / s, 0.0, 1.0])
                return [round(float(q[0] * s), 5), round(float(q[1] * s), 5)]

            out.append({"guid": e.GlobalId, "kind": kind, "solid": [[w(p) for p in line] for line in solid],
                        "dashed": [[w(p) for p in line] for line in dashed],
                        "labels": [{"at": w((x, y)), "text": t} for x, y, t, _ in labels]})
    return B._dump({"symbols": out})


def assembly_members() -> str:
    """Stairs and ramps with their parts (flights, landings): a click on a part selects the whole."""
    out = {}
    if B._model is not None:
        for cls in ("IfcStair", "IfcRamp"):
            for w in B._model.by_type(cls):
                ps = parts(w)
                if ps:
                    out[w.GlobalId] = {"type": w.is_a(), "parts": [p.GlobalId for p in ps]}
    return B._dump({"assemblies": out})
