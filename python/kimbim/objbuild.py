# SPDX-License-Identifier: GPL-3.0-or-later
"""Building an object's geometry from its definition (D99, doc 16 §2–3): parts with one shape each,
placed by formulas in frames (4×4 matrices, object metres), anchors and patterns other parts attach to,
repeats, `when`, `use` for components and other library objects, and the plan symbol (drawn, or the
outline of the parts seen from above). Pure: no IFC, no model."""
from __future__ import annotations

import math
import re

import numpy as np

from .objexpr import FormulaError, value_of

MAX_SOLIDS = 5000
MAX_USE_DEPTH = 50
MAX_POINTS = 2000
MAX_WORK = 4 * MAX_SOLIDS  # part copies evaluated, solid or not, nested included
MAX_BUILD_POINTS = 200_000  # points one build evaluates: solids' point lists, profiles and paths, and the symbol
MAX_GENERATOR_POINTS = 256
SAMPLES = 64  # circle samples for bounding boxes and outlines (Task 1's golden uses the same)
SYMBOL_CIRCLE_POINTS = 24
CIRCLE_POINTS = 16
SHAPES = ("box", "cylinder", "cone", "prism", "revolve", "sweep")
_PART_KEYS = {"id", "at", "rotate", "axes", "attach", "repeat", "when", "material", "anchors", "use", "with", *SHAPES}
_FIELDS = {  # kind: (required, optional with defaults)
    "box": (("dx", "dy", "dz"), {"x": 0, "y": 0, "z": 0, "taper": 1}),
    "cylinder": (("r", "h"), {"cx": 0, "cy": 0, "z": 0}),
    "cone": (("r1", "r2", "h"), {"cx": 0, "cy": 0, "z": 0}),
    "prism": (("points", "h"), {"z": 0}),
    "revolve": (("profile",), {"angle": 360}),
    "sweep": (("path",), {"r": None, "profile": None}),
}
_POINT_FIELDS = {"points", "profile", "path"}
_SYMBOL_KINDS = {"line": (("points",), {"closed": False}), "polygon": (("points",), {}),
                 "rect": (("x", "y", "dx", "dy"), {}), "circle": (("cx", "cy", "r"), {}),
                 "ellipse": (("cx", "cy", "rx", "ry"), {"a0": 0, "a1": 360}),
                 "arc": (("cx", "cy", "r", "a0", "a1"), {})}
_DIRS = {"up": (0, 0, 1), "down": (0, 0, -1), "front": (0, -1, 0), "back": (0, 1, 0),
         "left": (-1, 0, 0), "right": (1, 0, 0)}
_AXES = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1), "-x": (-1, 0, 0), "-y": (0, -1, 0), "-z": (0, 0, -1)}
_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_TEMPLATE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


class ObjectError(ValueError):
    """A definition that cannot load or build; the message starts with the field's path."""


# ---------------------------------------------------------------- frames

def _translate(x=0.0, y=0.0, z=0.0):
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def _rotation(axis, degrees):
    a = np.asarray(axis, dtype=float)
    n = np.linalg.norm(a)
    m = np.eye(4)
    if n < 1e-12 or abs(degrees) < 1e-12:
        return m
    x, y, z = a / n
    t = math.radians(degrees)
    c, s, k = math.cos(t), math.sin(t), 1 - math.cos(t)
    m[:3, :3] = [[c + x * x * k, x * y * k - z * s, x * z * k + y * s],
                 [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
                 [z * x * k - y * s, z * y * k + x * s, c + z * z * k]]
    return m


def _frame(origin, zdir, xdir=(1, 0, 0)):
    z = np.asarray(zdir, dtype=float)
    length = float(np.linalg.norm(z))
    if not math.isfinite(length) or length < 1e-12:
        raise ObjectError("a direction of zero length")
    z = z / length
    x = np.asarray(xdir, dtype=float)
    if abs(float(np.dot(x, z))) > 0.999:
        x = np.array([0.0, 1.0, 0.0])
    x = x - np.dot(x, z) * z
    x = x / np.linalg.norm(x)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, np.cross(z, x), z, origin
    return m


# ---------------------------------------------------------------- points

def ellipse_points(cx, cy, rx, ry, a0=0.0, a1=2 * math.pi, n=CIRCLE_POINTS, closed=True):
    step = (a1 - a0) / (n if closed else n - 1)
    return [(cx + rx * math.cos(a0 + i * step), cy + ry * math.sin(a0 + i * step)) for i in range(n)]


def rounded_rect(x, y, dx, dy, r, n=4):
    """A rectangle with rounded corners as a polygon (r clipped to fit)."""
    r = max(0.0, min(r, dx / 2 - 1e-4, dy / 2 - 1e-4))
    if r <= 1e-4:
        return [(x, y), (x + dx, y), (x + dx, y + dy), (x, y + dy)]
    pts = []
    for cx, cy, start in ((x + dx - r, y + r, -90), (x + dx - r, y + dy - r, 0), (x + r, y + dy - r, 90), (x + r, y + r, 180)):
        for i in range(n + 1):
            a = math.radians(start + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _num(v, env, where) -> float:
    """A numeric field's value (a number or a formula): a finite number, else an ObjectError naming the
    field. A formula error goes up as it is (the caller names the field)."""
    x = value_of(v, env)
    if not isinstance(x, bool | int | float):
        raise ObjectError(f"{where}: a number, not {x!r}")
    x = float(x)
    if not math.isfinite(x):
        raise ObjectError(f"{where}: {x} is not a finite number")
    return x


def _nums(spec, env, where, count=None) -> list:
    if not isinstance(spec, list | tuple) or (count is not None and len(spec) != count):
        raise ObjectError(f"{where}: a list of {count} numbers" if count else f"{where}: a list of numbers")
    return [_num(v, env, where) for v in spec]


def _points(spec, env, dims, where):
    if not isinstance(spec, list):
        raise ObjectError(f"{where}: a list of points")
    out = []
    for item in spec:
        if isinstance(item, dict):
            n = int(_num(item.get("n", CIRCLE_POINTS), env, f"{where}.n"))
            low = 1 if "rounded_rect" in item else 3
            if not low <= n <= MAX_GENERATOR_POINTS:
                raise ObjectError(f"{where}: n between {low} and {MAX_GENERATOR_POINTS}")
            if "ellipse" in item:
                cx, cy, rx, ry = _nums(item["ellipse"], env, f"{where}.ellipse", 4)
                a0, a1 = (math.radians(_num(item.get(k, d), env, f"{where}.{k}")) for k, d in (("a0", 0), ("a1", 360)))
                full = abs(a1 - a0 - 2 * math.pi) < 1e-9
                out += ellipse_points(cx, cy, rx, ry, a0, a1, n, closed=full)
            elif "rounded_rect" in item:
                x, y, dx, dy, r = _nums(item["rounded_rect"], env, f"{where}.rounded_rect", 5)
                out += rounded_rect(x, y, dx, dy, r, n)
            else:
                raise ObjectError(f"{where}: a point generator is ellipse or rounded_rect")
        elif isinstance(item, list | tuple) and len(item) == dims:
            out.append(tuple(_num(v, env, where) for v in item))
        else:
            raise ObjectError(f"{where}: each point has {dims} numbers")
        if len(out) > MAX_POINTS:
            raise ObjectError(f"{where}: more than {MAX_POINTS} points")
    return out


def _area(pts):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]))) / 2


def _centroid_x(pts):
    a = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2
    if abs(a) < 1e-15:
        return 0.0
    return sum((x0 + x1) * (x0 * y1 - x1 * y0) for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / (6 * a)


def _circle(cx, cy, r, n=SAMPLES):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def _segment_frame(p, q):
    d = np.asarray(q, dtype=float) - np.asarray(p, dtype=float)
    if not np.linalg.norm(d) > 1e-9:
        raise ObjectError("sweep: two path points in the same place")
    return _frame(p, d, (1, 0, 0) if abs(d[0]) < 0.9 * np.linalg.norm(d) else (0, 1, 0)), float(np.linalg.norm(d))


def _local_points(s):
    """A solid's points in its own frame (for bounding boxes, anchors and outlines)."""
    k = s["kind"]
    if k == "box":
        x, y, z, dx, dy, dz, t = (s[f] for f in ("x", "y", "z", "dx", "dy", "dz", "taper"))
        cx, cy = x + dx / 2, y + dy / 2
        out = []
        for zz, scale in ((z, 1.0), (z + dz, t)):
            out += [(cx + a * dx / 2 * scale, cy + b * dy / 2 * scale, zz) for a in (-1, 1) for b in (-1, 1)]
        return out
    if k == "cylinder":
        return [(x, y, zz) for x, y in _circle(s["cx"], s["cy"], s["r"]) for zz in (s["z"], s["z"] + s["h"])]
    if k == "cone":
        return ([(x, y, s["z"]) for x, y in _circle(s["cx"], s["cy"], s["r1"])]
                + [(x, y, s["z"] + s["h"]) for x, y in _circle(s["cx"], s["cy"], s["r2"])])
    if k == "prism":
        return [(x, y, zz) for x, y in s["points"] for zz in (s["z"], s["z"] + s["h"])]
    if k == "revolve":
        steps = max(2, int(SAMPLES * s["angle"] / 360))
        return [(r * math.cos(math.radians(s["angle"] * j / steps)), r * math.sin(math.radians(s["angle"] * j / steps)), z)
                for r, z in s["profile"] for j in range(steps + 1)]
    path = s["path"]
    if s.get("r") is not None:
        r = s["r"]
        return [(x + dx, y + dy, z + dz) for x, y, z in path
                for dx, dy, dz in ((r, 0, 0), (-r, 0, 0), (0, r, 0), (0, -r, 0), (0, 0, r), (0, 0, -r))]
    out = []
    profile = np.asarray(s["profile"], dtype=float).reshape(-1, 2)
    for p, q in zip(path, path[1:]):
        f, length = _segment_frame(p, q)
        for w in (0.0, length):
            local = np.column_stack([profile, np.full(len(profile), w)])
            out += [tuple(r) for r in _apply(f, local)]
    return out


def _apply(m, pts):
    """Points (an n×3 array) through a 4×4 matrix: one matrix product."""
    return np.asarray(pts, dtype=float).reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]


def solid_points(s) -> list:
    pts = _local_points(s)
    if not pts:
        return []
    return [tuple(r) for r in _apply(np.asarray(s["matrix"], dtype=float), pts).tolist()]


def solid_volume(s) -> float:
    k = s["kind"]
    if k == "box":
        t = s["taper"]
        return s["dx"] * s["dy"] * s["dz"] * (1 + t + t * t) / 3
    if k == "cylinder":
        return math.pi * s["r"] ** 2 * s["h"]
    if k == "cone":
        return math.pi * s["h"] * (s["r1"] ** 2 + s["r1"] * s["r2"] + s["r2"] ** 2) / 3
    if k == "prism":
        return _area(s["points"]) * s["h"]
    if k == "revolve":
        return _area(s["profile"]) * 2 * math.pi * abs(_centroid_x(s["profile"])) * s["angle"] / 360
    length = sum(math.dist(p, q) for p, q in zip(s["path"], s["path"][1:]))
    return (math.pi * s["r"] ** 2 if s.get("r") is not None else _area(s["profile"])) * length


# ---------------------------------------------------------------- Shape

class Shape:
    """What a definition builds: solids (3D) and curves (the plan symbol), in object metres."""

    def __init__(self):
        self.solids, self.curves = [], []

    def polylines(self) -> list:
        out = []
        for c in self.curves:
            if c[0] == "poly":
                out.append([[round(x, 4), round(y, 4)] for x, y in c[1]])
            else:
                _, cx, cy, r = c
                pts = ellipse_points(cx, cy, r, r, n=SYMBOL_CIRCLE_POINTS)
                out.append([[round(x, 4), round(y, 4)] for x, y in pts + pts[:1]])
        return out

    def metrics(self) -> dict:
        pts = [p for s in self.solids for p in solid_points(s)]
        lines = self.polylines()
        flat = [p for line in lines for p in line]
        out = {"volume": sum(solid_volume(s) for s in self.solids),
               "symbol_length": sum(math.dist(a, b) for line in lines for a, b in zip(line, line[1:]))}
        out["bbox"] = ([min(p[i] for p in pts) for i in range(3)] + [max(p[i] for p in pts) for i in range(3)]) if pts else []
        out["symbol_bbox"] = ([min(p[0] for p in flat), min(p[1] for p in flat), max(p[0] for p in flat),
                               max(p[1] for p in flat)] if flat else [])
        return out


# ---------------------------------------------------------------- check (structure, before any value)

def _check_parts(parts, where, components, seen_components):
    if not isinstance(parts, list):
        raise ObjectError(f"{where}: a list of parts")
    ids = set()
    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get("id"), str):
            raise ObjectError(f"{where}: every part has an id")
        if not _ID.match(part["id"]):
            raise ObjectError(f"{where}: id {part['id']!r} must be lower-case letters, digits and _")
        w = f"{where}.{part['id']}"
        if part["id"] in ids:
            raise ObjectError(f"{w}: the id is used twice")
        ids.add(part["id"])
        unknown = set(part) - _PART_KEYS
        if unknown:
            raise ObjectError(f"{w}: unknown field {sorted(unknown)[0]!r}")
        kinds = [k for k in SHAPES if k in part]
        if len(kinds) > 1 or (kinds and "use" in part):
            raise ObjectError(f"{w}: one shape or one use per part")
        if not kinds and "use" not in part and "anchors" not in part:
            raise ObjectError(f"{w}: a shape, a use or anchors")
        for k in kinds:
            fields = part[k]
            required, optional = _FIELDS[k]
            if not isinstance(fields, dict):
                raise ObjectError(f"{w}.{k}: an object of fields")
            extra = set(fields) - set(required) - set(optional)
            if extra:
                raise ObjectError(f"{w}.{k}: unknown field {sorted(extra)[0]!r}")
            for f in required:
                if f not in fields:
                    raise ObjectError(f"{w}.{k}: {f} is missing")
            if k == "sweep" and (fields.get("r") is None) == (fields.get("profile") is None):
                raise ObjectError(f"{w}.sweep: r (a tube) or profile, not both")
        for key, types, text in (("use", str, "a name"), ("attach", str, "an anchor name"),
                                 ("material", str, "a material slot"), ("rotate", dict, "an object {angle, axis}"),
                                 ("anchors", dict, "an object of named anchors"), ("with", dict, "an object of values"),
                                 ("repeat", dict, "an object {count, ...} or {on, ...}"), ("at", list, "a list of numbers")):
            if key in part and not isinstance(part[key], types):
                raise ObjectError(f"{w}.{key}: {text}")
        for name, spec in (part.get("anchors") or {}).items():
            if not isinstance(spec, dict):
                raise ObjectError(f"{w}.anchors.{name}: an object")
        if "repeat" in part and "count" not in part["repeat"] and "on" not in part["repeat"]:
            raise ObjectError(f"{w}.repeat: count or on is missing")
        if "repeat" in part and "on" in part["repeat"] and not isinstance(part["repeat"]["on"], str):
            raise ObjectError(f"{w}.repeat.on: an anchor name")
        if "axes" in part:
            axes = part["axes"]
            if (not isinstance(axes, list) or len(axes) != 3 or any(a not in _AXES for a in axes)
                    or np.linalg.det(np.array([_AXES[a] for a in axes], dtype=float)) < 0.5):
                raise ObjectError(f"{w}.axes: a right-handed set of three different axes among x, y, z, -x, -y, -z")
        if "use" in part and "{" not in part["use"] and part["use"] in components:
            name = part["use"]
            if name in seen_components:
                raise ObjectError(f"{w}: use cycle {' > '.join([*seen_components, name])}")
            _check_parts(components[name].parts, f"components.{name}.parts", components, [*seen_components, name])


def check(defn) -> None:
    _check_parts(defn.parts, "parts", defn.components, [])
    for name, comp in defn.components.items():
        _check_parts(comp.parts, f"components.{name}.parts", defn.components, [name])
    if defn.symbol is not None:
        if not isinstance(defn.symbol, list):
            raise ObjectError("symbol: a list of 2D items")
        for k, item in enumerate(defn.symbol):
            if not isinstance(item, dict):
                raise ObjectError(f"symbol[{k}]: an object")
            if "repeat" in item and (not isinstance(item["repeat"], dict) or "count" not in item["repeat"]):
                raise ObjectError(f"symbol[{k}].repeat: an object with a count")


# ---------------------------------------------------------------- build

class _Ctx:
    def __init__(self, resolve, all_anchors=False):
        self.shape, self.resolve, self.material = Shape(), resolve, None
        self.all_anchors, self.work, self.checked, self.points = all_anchors, 0, set(), 0

    def tick(self, where):
        self.work += 1
        if self.work > MAX_WORK:
            raise ObjectError(f"{where}: more than {MAX_WORK} part copies (over the limit)")

    def count_points(self, n, where):
        self.points += n
        if self.points > MAX_BUILD_POINTS:
            raise ObjectError(f"{where}: more than {MAX_BUILD_POINTS} points in the object (over the limit)")

    def count_fields(self, fields, where):
        self.count_points(sum(len(fields[f]) for f in _POINT_FIELDS if fields.get(f)), where)

    def add(self, solid):
        if len(self.shape.solids) >= MAX_SOLIDS:
            raise ObjectError(f"more than {MAX_SOLIDS} solids (the limit)")
        self.shape.solids.append(solid)


def _template(text, env, where):
    def sub(m):
        if m.group(1) not in env:
            raise ObjectError(f"{where}: unknown parameter {m.group(1)!r} in {text!r}")
        return str(env[m.group(1)])
    return _TEMPLATE.sub(sub, text)


def _fields(kind, raw, env, where):
    required, optional = _FIELDS[kind]
    out = {}
    for f in (*required, *optional):
        v = raw.get(f, optional.get(f))
        if v is None:
            out[f] = None
        else:
            try:
                if f in _POINT_FIELDS:
                    out[f] = _points(v, env, 3 if f == "path" else 2, f"{where}.{f}")
                else:
                    out[f] = _num(v, env, f"{where}.{f}")
            except FormulaError as ex:
                raise ObjectError(f"{where}.{f}: {ex}") from None
    return out


def _solid_ok(kind, s):
    if kind == "box":
        return min(s["dx"], s["dy"], s["dz"]) > 1e-6 and 0 <= s["taper"] <= 1
    if kind == "cylinder":
        return s["r"] > 1e-6 and s["h"] > 1e-6
    if kind == "cone":
        return max(s["r1"], s["r2"]) > 1e-6 and min(s["r1"], s["r2"]) >= 0 and s["h"] > 1e-6
    if kind == "prism":
        return s["h"] > 1e-6 and len(s["points"]) >= 3
    if kind == "revolve":
        return len(s["profile"]) >= 3 and s["angle"] > 1e-6
    return len(s["path"]) >= 2 and (s["r"] is None or s["r"] > 1e-6)


def _check_solid(kind, s, where):
    """A solid the IFC writer can take: a profile sweep's path has no two points in the same place."""
    if kind == "sweep" and s.get("profile") is not None:
        for k, (p, q) in enumerate(zip(s["path"], s["path"][1:])):
            if math.dist(p, q) <= 1e-9:
                raise ObjectError(f"{where}.path: points {k} and {k + 1} are in the same place")


def _dir_frame(spec, env, origin, where="dir"):
    d = spec.get("dir", "up")
    zdir = _DIRS.get(d) if isinstance(d, str) else _nums(d, env, where, 3)
    if zdir is None:
        raise ObjectError(f"unknown direction {d!r} (up, down, front, back, left, right or a vector)")
    try:
        return _frame(origin, zdir)
    except ObjectError as ex:
        raise ObjectError(f"{where}: {ex}") from None


def _pattern(spec, env, count, bbox):
    kind = spec["pattern"]
    ev = lambda k, d=None: _num(spec.get(k, d), env, k)  # noqa: E731
    z = ev("z", bbox[2] if bbox else 0)
    if kind == "rect_corners":
        x, y = ev("x", bbox[0] if bbox else 0), ev("y", bbox[1] if bbox else 0)
        dx, dy = ev("dx", (bbox[3] - bbox[0]) if bbox else 1), ev("dy", (bbox[4] - bbox[1]) if bbox else 1)
        i = ev("inset", 0)
        pts = [(x + i, y + i), (x + dx - i, y + i), (x + dx - i, y + dy - i), (x + i, y + dy - i)]
    elif kind == "circle":
        cx, cy, r, start = ev("cx"), ev("cy"), ev("r"), ev("start", -90)
        pts = [(cx + r * math.cos(math.radians(start + 360 * k / count)), cy + r * math.sin(math.radians(start + 360 * k / count)))
               for k in range(count)]
    elif kind == "line":
        a, b = _nums(spec["from"], env, "from", 3), _nums(spec["to"], env, "to", 3)
        ts = [0.5] if count == 1 else [k / (count - 1) for k in range(count)]
        return [_dir_frame(spec, env, [a[j] + (b[j] - a[j]) * t for j in range(3)]) for t in ts]
    elif kind == "grid":
        nx, ny = int(ev("nx")), int(ev("ny"))
        if nx < 1 or ny < 1:
            raise ObjectError("nx and ny must be positive")
        if nx * ny > MAX_SOLIDS:
            raise ObjectError(f"grid over the limit of {MAX_SOLIDS}")
        x, y, dx, dy = ev("x", 0), ev("y", 0), ev("dx"), ev("dy")
        pts = [(x + a * dx, y + b * dy) for b in range(ny) for a in range(nx)]
    else:
        raise ObjectError(f"unknown pattern {kind!r} (rect_corners, circle, line, grid)")
    return [_dir_frame(spec, env, (px, py, z)) for px, py in pts]


def _ref(text, anchors, where):
    bits = text.split(".")
    pid = bits[0]
    if pid not in anchors:
        raise ObjectError(f"{where}: unknown part {pid!r} (or it comes later)")
    name = bits[2] if len(bits) == 3 and bits[1] == "anchors" else bits[1] if len(bits) == 2 else None
    if name is None or name not in anchors[pid]:
        raise ObjectError(f"{where}: part {pid!r} has no anchor {text.split('.', 1)[1]!r}")
    return anchors[pid][name]


def _count(v, env, where):
    try:
        n = _num(v, env, where)
    except FormulaError as ex:
        raise ObjectError(f"{where}: {ex}") from None
    if n > MAX_SOLIDS:
        raise ObjectError(f"{where}: {int(n)} copies is over the limit of {MAX_SOLIDS}")
    return max(0, int(round(n)))


def _copies(part, env, anchors, base, where):
    frame = base
    if "attach" in part:
        f = _ref(_template(part["attach"], env, where), anchors, f"{where}.attach")
        if isinstance(f, list):
            raise ObjectError(f"{where}.attach: {part['attach']!r} is a pattern; use repeat.on")
        frame = f
    r = part.get("repeat")
    if r is None:
        return [frame]
    if "on" in r:
        on = _template(r["on"], env, where)
        target = _ref(on, anchors, f"{where}.repeat.on")
        if not isinstance(target, _Pattern):
            raise ObjectError(f"{where}.repeat.on: {on!r} is a single anchor; use attach")
        count = _count(r.get("count", 0), env, f"{where}.repeat.count") if target.counted else None
        return target.frames(count)
    count = _count(r["count"], env, f"{where}.repeat.count")
    step = _nums(r.get("step", (0, 0, 0)), env, f"{where}.repeat.step", 3)
    turn = _num(r.get("turn", 0), env, f"{where}.repeat.turn")
    return [frame @ _translate(*(k * s for s in step)) @ _rotation((0, 0, 1), k * turn) for k in range(count)]


class _Pattern:
    """A pattern anchor: frames made when a repeat asks, with its count."""

    def __init__(self, spec, env, bbox, base, where=""):
        self.spec, self.env, self.bbox, self.base, self.where = spec, env, bbox, base, where
        self.counted = spec["pattern"] in ("circle", "line")

    def frames(self, count):
        try:
            return [self.base @ f for f in _pattern(self.spec, self.env, count or 0, self.bbox)]
        except (FormulaError, ObjectError, KeyError) as ex:
            raise ObjectError(f"{self.where}: {ex}") from None


def _local(part, env, frame, centroid, where):
    m = np.eye(4)
    if "at" in part:
        m = m @ _translate(*_nums(part["at"], env, f"{where}.at"))
    rot = part.get("rotate")
    if rot:
        angle = _num(rot.get("angle", 0), env, f"{where}.rotate.angle")
        axis = rot.get("axis", "z")
        if axis == "away_from_centre":
            p = (frame @ m)[:3, 3]
            v = np.array([p[0] - centroid[0], p[1] - centroid[1], 0.0])
            if np.linalg.norm(v) < 1e-9:
                vec = None
            else:
                world = np.cross(v, (0, 0, 1))
                vec = np.linalg.inv((frame @ m)[:3, :3]) @ world
        elif isinstance(axis, str):
            vec = _AXES.get(axis)
            if vec is None:
                raise ObjectError(f"{where}.rotate: axis x, y, z, a vector or away_from_centre")
        else:
            vec = _nums(axis, env, f"{where}.rotate.axis", 3)
        if vec is not None:
            m = m @ _rotation(vec, angle)
    if "axes" in part:
        a = np.eye(4)
        for j, name in enumerate(part["axes"]):
            a[:3, j] = _AXES[name]
        m = m @ a
    return m


def _anchors(part, env, m, solid_fields, kind, base_inv, eager=False):
    out = {}
    bbox = None
    if kind is not None:
        pts = _local_points({"kind": kind, **solid_fields})
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        bbox = (*lo, *hi)
        c = [(lo[i] + hi[i]) / 2 for i in range(3)]
        for name, origin, d in (("centre", c, "up"), ("top", (c[0], c[1], hi[2]), "up"),
                                ("bottom", (c[0], c[1], lo[2]), "down"), ("front", (c[0], lo[1], c[2]), "front"),
                                ("back", (c[0], hi[1], c[2]), "back"), ("left", (lo[0], c[1], c[2]), "left"),
                                ("right", (hi[0], c[1], c[2]), "right")):
            out[name] = m @ _frame(origin, _DIRS[d])
    for name, spec in (part.get("anchors") or {}).items():
        where = f"parts.{part['id']}.anchors.{name}"
        try:
            if "pattern" in spec:
                out[name] = _Pattern(spec, env, bbox, m, where)
                if eager:
                    out[name].frames(1)
            else:
                origin = [_num(spec.get(k, 0), env, f"{where}.{k}") for k in ("x", "y", "z")]
                out[name] = m @ _dir_frame(spec, env, origin, f"{where}.dir")
        except (FormulaError, ObjectError) as ex:
            raise ObjectError(str(ex) if str(ex).startswith(where) else f"{where}: {ex}") from None
    coords = {}
    for name, f in out.items():
        if not isinstance(f, _Pattern):
            local = base_inv @ f
            coords.update({f"{part['id']}.{name}.{axis}": float(local[j, 3]) for j, axis in enumerate("xyz")})
    return out, coords


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(node, list | tuple):
        for v in node:
            yield from _strings(v)


def _needing_anchors(defn):
    """Ids of the parts whose anchors something refers to (None: all, a templated reference)."""
    for part in defn.parts:
        on = (part.get("repeat") or {}).get("on")
        for ref in (part.get("attach"), on):
            if isinstance(ref, str) and "{" in ref:
                return None
    text = list(_strings(defn.parts)) + list(_strings(getattr(defn, "symbol", None)))
    return {p["id"] for p in defn.parts if any(f"{p['id']}." in t for t in text)}


def _parts(ctx, defn, components, env, base, stack, where):
    """Build `defn.parts` in the frame `base`; `components` are the object file's components (a
    component may use its siblings)."""
    anchors = {}
    env = dict(env)
    base_inv = np.linalg.inv(base)
    full = ctx.all_anchors and id(defn) not in ctx.checked  # a component's anchors are checked once
    ctx.checked.add(id(defn))
    needed = None if full else _needing_anchors(defn)
    for part in defn.parts:
        w = f"{where}.{part['id']}"
        try:
            ctx.tick(w)
            if "when" in part and not value_of(part["when"], env):
                continue
            frames = _copies(part, env, anchors, base, w)
            n = len(frames)
            centroid = np.mean([f[:3, 3] for f in frames], axis=0) if frames else np.zeros(3)
            kind = next((k for k in SHAPES if k in part), None)
            first = None
            for i, frame in enumerate(frames):
                ctx.tick(w)
                e = {**env, "i": i, "n": n}
                m = frame @ _local(part, e, frame, centroid, w)
                fields = None
                if "use" in part:
                    _use(ctx, components, part, e, m, stack, w)
                elif kind is not None:
                    fields = _fields(kind, part[kind], e, f"{w}.{kind}")
                    ctx.count_fields(fields, f"{w}.{kind}")
                    if _solid_ok(kind, fields):
                        _check_solid(kind, fields, f"{w}.{kind}")
                        ctx.add({"kind": kind, **fields, "matrix": m.tolist(),
                                 "part": ctx.material or part.get("material", "body")})
                if first is None:
                    first = (m, e, fields)
            if first is None:  # no copies: anchors still exist, at the base, for later parts
                e = {**env, "i": 0, "n": 0}
                fields = _fields(kind, part[kind], e, f"{w}.{kind}") if kind else None
                if fields is not None:
                    ctx.count_fields(fields, f"{w}.{kind}")
                first = (base @ _local(part, e, base, np.zeros(3), w), e, fields)
            if needed is None or part["id"] in needed:  # anchors only for parts something refers to
                found, coords = _anchors(part, first[1], first[0], first[2], kind, base_inv, full)
                anchors[part["id"]] = found
                env.update(coords)
        except FormulaError as ex:
            raise ObjectError(f"{w}: {ex}") from None
    return env


def _use(ctx, components, part, env, m, stack, where):
    name = _template(part["use"], env, where)
    if name in stack:
        raise ObjectError(f"{where}: use cycle {' > '.join([*stack, name])}")
    if len(stack) >= MAX_USE_DEPTH:
        raise ObjectError(f"{where}: use nested more than {MAX_USE_DEPTH} deep")
    target, inner = components.get(name), components
    if target is None and ctx.resolve is not None:
        target = ctx.resolve(name)
        inner = target.components if target is not None else components  # another object: its own components
    if target is None:
        raise ObjectError(f"{where}: unknown component or object {name!r}")
    unknown = set(part.get("with", {})) - {p.key for p in target.params}
    if unknown:
        raise ObjectError(f"{where}.with: {name!r} has no parameter {sorted(unknown)[0]!r}")
    given = {k: value_of(v, env) for k, v in part.get("with", {}).items()}
    values = target.values(given)
    saved = ctx.material
    if "material" in part:
        ctx.material = part["material"]
    _parts(ctx, target, inner, {**values, "pi": math.pi}, m, [*stack, name], f"{where}>{name}")
    ctx.material = saved


def _symbol(ctx, defn, env):
    curves = []
    for k, item in enumerate(defn.symbol):
        where = f"symbol[{k}]"
        if not isinstance(item, dict):
            raise ObjectError(f"{where}: an object")
        kinds = [s for s in _SYMBOL_KINDS if s in item]
        if len(kinds) != 1:
            raise ObjectError(f"{where}: one of {', '.join(_SYMBOL_KINDS)}")
        kind = kinds[0]
        try:
            if "when" in item and not value_of(item["when"], env):
                continue
            count = _count(item["repeat"]["count"], env, f"{where}.repeat.count") if "repeat" in item else 1
            for i in range(count):
                ctx.tick(where)
                e = {**env, "i": i, "n": count}
                raw = item[kind]
                required, optional = _SYMBOL_KINDS[kind]
                for f in required:
                    if f not in raw:
                        raise ObjectError(f"{where}.{kind}: {f} is missing")
                if kind in ("line", "polygon"):
                    pts = _points(raw["points"], e, 2, f"{where}.{kind}.points")
                    closed = kind == "polygon" or bool(raw.get("closed", False))
                    curves.append(("poly", pts + pts[:1] if closed else pts))
                elif kind == "rect":
                    x, y, dx, dy = (_num(raw[f], e, f"{where}.{kind}.{f}") for f in ("x", "y", "dx", "dy"))
                    curves.append(("poly", [(x, y), (x + dx, y), (x + dx, y + dy), (x, y + dy), (x, y)]))
                elif kind == "circle":
                    curves.append(("circle", *(_num(raw[f], e, f"{where}.{kind}.{f}") for f in ("cx", "cy", "r"))))
                else:
                    if kind == "arc":
                        cx, cy, rx = (_num(raw[f], e, f"{where}.{kind}.{f}") for f in ("cx", "cy", "r"))
                        ry = rx
                    else:
                        cx, cy, rx, ry = (_num(raw[f], e, f"{where}.{kind}.{f}") for f in ("cx", "cy", "rx", "ry"))
                    a0, a1 = (math.radians(_num(raw.get(f, d), e, f"{where}.{kind}.{f}")) for f, d in (("a0", 0), ("a1", 360)))
                    closed = abs(a1 - a0 - 2 * math.pi) < 1e-9
                    n = CIRCLE_POINTS if closed else max(4, int(CIRCLE_POINTS * abs(a1 - a0) / (2 * math.pi)) + 1)
                    pts = ellipse_points(cx, cy, rx, ry, a0, a1, n, closed)
                    curves.append(("poly", pts + pts[:1] if closed else pts))
                last = curves[-1]
                ctx.count_points(len(last[1]) if last[0] == "poly" else SYMBOL_CIRCLE_POINTS, where)
        except FormulaError as ex:
            raise ObjectError(f"{where}: {ex}") from None
    return curves


def _outline(shape):
    """The parts seen from above: each solid's footprint (convex hull), unioned."""
    import shapely
    from shapely.ops import unary_union

    hulls = []
    for s in shape.solids:
        pts = [(x, y) for x, y, _ in solid_points(s)]
        hull = shapely.MultiPoint(pts).convex_hull
        if hull.area > 1e-10:
            hulls.append(hull)
    if not hulls:
        return []
    union = unary_union(hulls)
    polys = list(union.geoms) if hasattr(union, "geoms") else [union]
    curves = []
    for p in polys:
        for ring in (p.exterior, *p.interiors):
            curves.append(("poly", [(round(x, 6), round(y, 6)) for x, y in ring.coords]))
    return curves


def build(defn, values, resolve=None, all_anchors=False) -> Shape:
    ctx = _Ctx(resolve, all_anchors)
    env = {**values, "pi": math.pi}
    env = _parts(ctx, defn, defn.components, env, np.eye(4), [], "parts")
    shape = ctx.shape
    shape.curves = _symbol(ctx, defn, env) if defn.symbol is not None else _outline(shape)
    ox, oy = getattr(defn, "origin", (0.0, 0.0))
    if abs(ox) > 1e-12 or abs(oy) > 1e-12:  # D92: the object's own origin goes to (0, 0)
        shift = _translate(-ox, -oy, 0)
        for s in shape.solids:
            s["matrix"] = (shift @ np.asarray(s["matrix"])).tolist()
        shape.curves = [("poly", [(x - ox, y - oy) for x, y in c[1]]) if c[0] == "poly" else (c[0], c[1] - ox, c[2] - oy, c[3])
                        for c in shape.curves]
    _check_finite(shape)
    return shape


def _check_finite(shape):
    """Nothing that is not a finite number reaches the IFC writer (it would fail inside the model's
    transaction): every solid's matrix and numbers, and every curve."""
    for k, s in enumerate(shape.solids):
        numbers = [v for f, v in s.items() if f not in ("kind", "part", "matrix") and isinstance(v, int | float)]
        points = [c for f in _POINT_FIELDS if s.get(f) for p in s[f] for c in p]
        if not (np.isfinite(s["matrix"]).all() and np.isfinite(numbers).all() and np.isfinite(points).all()):
            raise ObjectError(f"solid {k + 1} ({s['kind']}): a value that is not a finite number")
    for k, c in enumerate(shape.curves):
        values = [v for p in c[1] for v in p] if c[0] == "poly" else list(c[1:])
        if not np.isfinite(values).all():
            raise ObjectError(f"symbol curve {k + 1}: a value that is not a finite number")
