<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Parametric Objects, Part A: the Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Library objects become `.kimobj` data files (parameters, formulas, parts, anchors, repeats, variants) built by KimBim's own evaluator; the 21 bundled objects are ported and proven identical; Python object definitions are removed; the chair becomes the customisable showcase.

**Architecture:** Three new pure-Python modules — `objexpr.py` (formulas), `objects.py` (the file format, parameters, definitions), `objbuild.py` (geometry: frames, shapes, anchors, repeats, `use`, plan symbol, metrics) — feed the existing `library.py`, which keeps the IFC side (types, placement, parameter edits) and now writes each type's definition into the model. Nothing in an object file can execute.

**Tech Stack:** Python 3.12, ifcopenshell 0.8/0.9 (IFC4, IFC2X3), numpy, shapely (plan outlines), blake3; C++17/Qt 6 for the Library panel and Properties; pytest; Qt Test via ctest.

**Spec:** [docs/16-parametric-objects.md](../../16-parametric-objects.md) (D99). Read it first; this plan argues from it.

## Global Constraints

- Format id `kimbim-object/1`, extension `.kimobj`, JSON; bundled files in `python/kimbim/bundled_objects/`.
- Lengths in metres, angles in degrees, everywhere in object files.
- Formulas: never Python `eval`/`exec`; max 500 characters, nesting depth 32.
- Limits: 5,000 solids per object after repeats; `use` nested at most 50 deep; 2,000 points per shape; generators `n` ≤ 256; files ≤ 1 MB.
- Parameter kinds exactly: `length`, `angle`, `count`, `bool`, `choice`, `material`. Defaults when not given: length 0.01–50, angle −360–360, count 1–20.
- Object origin: left front corner, front at y = 0 (Archicad); D92 `origin` shifts it.
- No backward compatibility: `define()`, `Param`, `Obj`, the build functions and `.py` office files are deleted, not shimmed.
- Every new or changed source file starts with `# SPDX-License-Identifier: GPL-3.0-or-later` (or `//` in C++); `pixi run check-spdx` must pass.
- UI strings in English and Spanish (`tr()` + `app/translations/kimbim_es.ts`; object files carry `es` labels).
- One user action = one undo step (`B._run(action)`).
- Run Python with the pixi env: `pixi run pytest ...` (or `.pixi/envs/default/python.exe -m pytest ...`). Rebuild the Rust module only if Rust changes (it doesn't here).

## Review Focus

1. **A formula breaks at some values but not the defaults** (`sqrt(width - 1)` with width 0.5 typed in Properties): the edit fails with a message naming the field, and the placed object keeps its old type and geometry. Test in Task 6 (`test_bad_value_keeps_the_old_type`).
2. **A hostile or broken office file** (`count: 1e9`, `2^2^2^2^2^2^2^2^2^2`, a `use` cycle, 5 MB of JSON): it is listed in the Library panel's errors and the rest of the library loads, fast. Tests in Task 2 (`test_hostile_formulas_fail_fast`), Task 4 (`test_repeat_over_the_limit_fails_before_looping`, `test_use_cycle_is_an_error`) and Task 6 (`test_broken_office_files_are_listed_not_loaded`).
3. **A project opened on a machine without the office library** (the consultant's case): its objects still show, and editing a parameter regenerates from the definition stored on the type. Test in Task 6 (`test_project_objects_edit_without_the_library`).
4. **Choice and bool values coming from the UI as text** (`"On a circle"`, `"true"`, `"false"`, Spanish labels): they map to the option id / boolean, never to the default silently. Tests in Task 3 (`test_clean_choice_and_bool_from_text`) and Task 8 (C++ bool edit).
5. **A splayed leg tilts the wrong way** (into the seat instead of out) or a single leg tilts: the far end moves away from the copies' centroid; one copy stays upright. Test in Task 4 (`test_away_from_centre_tilts_far_ends_outward`).

---

## File structure

| File | Responsibility |
|------|----------------|
| `python/kimbim/objexpr.py` (new) | Tokenise, parse and evaluate formulas; `FormulaError` |
| `python/kimbim/objbuild.py` (new) | `ObjectError`, `Shape` (solids as dicts with a 4×4 matrix, curves, polylines, metrics), `check()` (structure), `build()` (frames, anchors, patterns, repeats, `use`, symbol, auto outline) |
| `python/kimbim/objects.py` (new) | Format loading and validation, `ParamDef`, `ComponentDef`, `ObjectDef`, `canonical()`, `digest()`, `load()`, `load_file()`, `from_text()` |
| `python/kimbim/bundled_objects/*.kimobj` (new) | The 21 bundled objects, then the showcase chair |
| `python/kimbim/library.py` (modify) | Loads bundled/office `.kimobj`; IFC writer for the new solids; definitions on types; Properties/Library glue; Update from library |
| `python/kimbim/app_bridge.py` (modify) | Parameters group per kind; `library_update` flag; export new bridge functions |
| `app/src/LibraryPanel.cpp/.h`, `PropertiesPanel.cpp/.h`, `MainWindow.cpp/.h`, `Translations.cpp/.h` (modify) | New kinds in the panel form, visibility, Update button, bool edits, Spanish labels from files |
| `tools/library_golden.py` (new, deleted in Task 6) | One-off: measure today's Python objects |
| `tests/golden/library_objects.json` (new) | Their measurements |
| `tests/python/test_objexpr.py`, `test_objects.py`, `test_objbuild.py`, `test_object_port.py` (new); `test_library.py` (modify) | Tests |
| `app/tests/test_library.cpp`, `test_properties_panel.cpp` (modify) | C++ tests |

---

### Task 1: Measure today's 21 objects (the port's oracle)

**Files:**
- Create: `tools/library_golden.py`
- Create: `tests/golden/library_objects.json` (generated)

**Interfaces:**
- Produces: `tests/golden/library_objects.json` = `{object_key: {set_name: {"values": {...}, "bbox": [x0,y0,z0,x1,y1,z1], "volume": float, "symbol_bbox": [x0,y0,x1,y1], "symbol_length": float}}}` with set names `default`, `large`, `small`. Task 5 compares against it; Task 4's `Shape.metrics()` must compute the same quantities the same way (cylinders sampled with 64 points, circles in symbols tessellated with 24).

This must run **before** any change to `library.py`.

- [ ] **Step 1: Write the tool**

```python
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
```

- [ ] **Step 2: Run it**

Run: `pixi run python tools/library_golden.py tests/golden/library_objects.json`
Expected: `21 objects -> tests/golden/library_objects.json`; the file has 21 keys × 3 sets, every `volume` > 0.

- [ ] **Step 3: Commit**

```bash
git add tools/library_golden.py tests/golden/library_objects.json
git commit -m "test(library): measure today's 21 objects as the .kimobj port's oracle (D99)"
```

---

### Task 2: The formula evaluator (`objexpr.py`)

**Files:**
- Create: `python/kimbim/objexpr.py`
- Test: `tests/python/test_objexpr.py`

**Interfaces:**
- Produces:
  - `class FormulaError(ValueError)` (attribute `pos: int | None`)
  - `compile_formula(text: str) -> Formula` (cached); `Formula.eval(env: Mapping[str, object]) -> float | bool | str`; `Formula.names: frozenset[str]`
  - `value_of(v, env) -> float | bool | str`: numbers and bools pass through, strings are compiled and evaluated, anything else raises `FormulaError`.
  - `MAX_LENGTH = 500`, `MAX_DEPTH = 32`

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""D99 formulas: arithmetic, logic, functions in degrees, errors with positions, and hostile input."""
import math
import time

import pytest

from kimbim.objexpr import MAX_LENGTH, FormulaError, compile_formula, value_of


def ev(text, **env):
    return compile_formula(text).eval(env)


def test_arithmetic_and_precedence():
    assert ev("1 + 2 * 3") == 7
    assert ev("(1 + 2) * 3") == 9
    assert ev("2 ^ 3 ^ 2") == 512  # right associative
    assert ev("-2 ^ 2") == -4
    assert ev("7 % 3") == 1
    assert ev("seat_h - 0.04", seat_h=0.45) == pytest.approx(0.41)


def test_logic_comparisons_and_strings():
    assert ev("layout == 'circle'", layout="circle") is True
    assert ev("back != 'none' and arms", back="slats", arms=True) is True
    assert ev("not arms or legs > 3", arms=True, legs=4) is True
    assert ev("true") is True and ev("false") is False


def test_functions_use_degrees():
    assert ev("sin(90)") == pytest.approx(1)
    assert ev("cos(60)") == pytest.approx(0.5)
    assert ev("atan2(1, 1)") == pytest.approx(45)
    assert ev("asin(1)") == pytest.approx(90)
    assert ev("clamp(5, 0, 2)") == 2
    assert ev("min(3, 1, 2)") == 1 and ev("max(3, 1, 2)") == 3
    assert ev("floor(2.7) + ceil(2.1) + round(2.5) + abs(-1) + sqrt(9)") == 2 + 3 + 2 + 1 + 3
    assert ev("pi", pi=math.pi) == pytest.approx(math.pi)


def test_if_is_lazy():
    assert ev("if(x > 0, 1 / x, 0)", x=0) == 0


def test_dotted_names():
    assert ev("seat.top.z + 1", **{"seat.top.z": 0.45}) == pytest.approx(1.45)
    assert compile_formula("a + seat.back.y").names == frozenset({"a", "seat.back.y"})


@pytest.mark.parametrize("text, message", [
    ("1 +", "expected a value"),
    ("foo(1)", "unknown function"),
    ("x + 1", "unknown name"),
    ("1 / 0", "division by zero"),
    ("sqrt(-1)", "math domain"),
    ("'a' + 1", "not a number"),
    ("1 $ 2", "unexpected"),
    ("(1 + 2", "expected ')'"),
    ("min()", "needs"),
])
def test_errors_name_the_problem(text, message):
    with pytest.raises(FormulaError, match=message):
        ev(text)


def test_error_positions():
    with pytest.raises(FormulaError) as e:
        ev("1 + $")
    assert e.value.pos == 4


def test_hostile_formulas_fail_fast():
    start = time.perf_counter()
    with pytest.raises(FormulaError, match="too long"):
        compile_formula("1+" * MAX_LENGTH + "1")
    with pytest.raises(FormulaError, match="nested"):
        compile_formula("(" * 40 + "1" + ")" * 40)
    with pytest.raises(FormulaError, match="too large"):
        ev("10 ^ 10 ^ 10 ^ 10")
    with pytest.raises(FormulaError):
        ev("__import__('os')")
    with pytest.raises(FormulaError):
        ev("x.__class__", x=1)
    assert time.perf_counter() - start < 0.5


def test_value_of():
    assert value_of(0.5, {}) == 0.5
    assert value_of(True, {}) is True
    assert value_of("w / 2", {"w": 1.0}) == 0.5
    with pytest.raises(FormulaError):
        value_of([1, 2], {})
```

- [ ] **Step 2: Run to verify they fail**

Run: `pixi run pytest tests/python/test_objexpr.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'kimbim.objexpr'`

- [ ] **Step 3: Implement**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Formulas in object definitions (D99, doc 16 §1): numbers, parameter names, + - * / ^ %, comparisons,
and/or/not, if(), a few functions (trig in degrees). A recursive-descent parser written for KimBim:
nothing here calls Python's eval, and nothing a formula says can reach Python objects."""
from __future__ import annotations

import functools
import math
import re
from collections.abc import Mapping

MAX_LENGTH = 500
MAX_DEPTH = 32
_KEYWORDS = {"and", "or", "not", "true", "false", "if"}
_TOKEN = re.compile(
    r"\s*(?:(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
    r"|(?P<str>'[^']*')"
    r"|(?P<name>[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*)"
    r"|(?P<op>==|!=|<=|>=|[-+*/^%(),<>]))")


class FormulaError(ValueError):
    def __init__(self, message: str, pos: int | None = None):
        super().__init__(message if pos is None else f"{message} (at character {pos + 1})")
        self.pos = pos


def _deg(f):
    return lambda x: f(math.radians(x))


def _inv(f):
    return lambda x: math.degrees(f(x))


_FUNCTIONS = {
    "min": (1, None, min), "max": (1, None, max), "abs": (1, 1, abs), "sqrt": (1, 1, math.sqrt),
    "round": (1, 1, lambda x: float(round(x))), "floor": (1, 1, lambda x: float(math.floor(x))),
    "ceil": (1, 1, lambda x: float(math.ceil(x))), "clamp": (3, 3, lambda x, lo, hi: min(max(x, lo), hi)),
    "sin": (1, 1, _deg(math.sin)), "cos": (1, 1, _deg(math.cos)), "tan": (1, 1, _deg(math.tan)),
    "asin": (1, 1, _inv(math.asin)), "acos": (1, 1, _inv(math.acos)), "atan": (1, 1, _inv(math.atan)),
    "atan2": (2, 2, lambda y, x: math.degrees(math.atan2(y, x))),
}


def _tokens(text: str) -> list:
    out, pos = [], 0
    while pos < len(text):
        if not text[pos:].strip():
            break
        m = _TOKEN.match(text, pos)
        if m is None:
            at = pos + len(text[pos:]) - len(text[pos:].lstrip())
            raise FormulaError(f"unexpected {text[at]!r}", at)
        kind = m.lastgroup
        out.append((kind, m.group(kind), m.start(kind)))
        pos = m.end()
    out.append(("end", "", len(text)))
    return out


class _Parser:
    def __init__(self, text):
        self.toks, self.i, self.depth, self.names = _tokens(text), 0, 0, set()

    def peek(self):
        return self.toks[self.i]

    def take(self):
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def is_op(self, *ops):
        kind, value, _ = self.peek()
        return (kind == "op" and value in ops) or (kind == "name" and value in ops)

    def expect(self, op):
        kind, value, pos = self.take()
        if value != op:
            raise FormulaError(f"expected {op!r}", pos)

    def parse(self):
        node = self.expr()
        kind, value, pos = self.peek()
        if kind != "end":
            raise FormulaError(f"unexpected {value!r}", pos)
        return node

    def expr(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaError("formula nested too deeply", self.peek()[2])
        node = self.or_()
        self.depth -= 1
        return node

    def or_(self):
        node = self.and_()
        while self.is_op("or"):
            self.take()
            node = ("or", node, self.and_())
        return node

    def and_(self):
        node = self.not_()
        while self.is_op("and"):
            self.take()
            node = ("and", node, self.not_())
        return node

    def not_(self):
        if self.is_op("not"):
            self.take()
            return ("not", self.not_())
        return self.cmp()

    def cmp(self):
        node = self.add()
        if self.is_op("==", "!=", "<", "<=", ">", ">="):
            op = self.take()[1]
            node = (op, node, self.add())
        return node

    def add(self):
        node = self.mul()
        while self.is_op("+", "-"):
            op = self.take()[1]
            node = (op, node, self.mul())
        return node

    def mul(self):
        node = self.unary()
        while self.is_op("*", "/", "%"):
            op = self.take()[1]
            node = (op, node, self.unary())
        return node

    def unary(self):
        if self.is_op("-", "+"):
            op = self.take()[1]
            self.depth += 1
            if self.depth > MAX_DEPTH:
                raise FormulaError("formula nested too deeply", self.peek()[2])
            node = self.unary()
            self.depth -= 1
            return ("neg", node) if op == "-" else node
        return self.power()

    def power(self):
        node = self.atom()
        if self.is_op("^"):
            self.take()
            node = ("^", node, self.unary())
        return node

    def atom(self):
        kind, value, pos = self.take()
        if kind == "num":
            return ("lit", float(value))
        if kind == "str":
            return ("lit", value[1:-1])
        if kind == "name" and value == "true":
            return ("lit", True)
        if kind == "name" and value == "false":
            return ("lit", False)
        if kind == "name" and self.peek()[1] == "(" and value not in _KEYWORDS - {"if"}:
            self.take()
            args = []
            if self.peek()[1] != ")":
                args.append(self.expr())
                while self.peek()[1] == ",":
                    self.take()
                    args.append(self.expr())
            self.expect(")")
            if value == "if":
                if len(args) != 3:
                    raise FormulaError("if needs 3 values", pos)
                return ("if", *args)
            if value not in _FUNCTIONS:
                raise FormulaError(f"unknown function {value!r}", pos)
            lo, hi, _ = _FUNCTIONS[value]
            if len(args) < lo or (hi is not None and len(args) > hi):
                raise FormulaError(f"{value} needs {lo if hi == lo else f'{lo} or more'} values", pos)
            return ("call", value, args, pos)
        if kind == "name" and value not in _KEYWORDS:
            self.names.add(value)
            return ("name", value, pos)
        if kind == "op" and value == "(":
            node = self.expr()
            self.expect(")")
            return node
        raise FormulaError("expected a value", pos)


def _num(v):
    if isinstance(v, str):
        raise FormulaError(f"not a number: {v!r}")
    return v


def _eval(node, env):
    op = node[0]
    if op == "lit":
        return node[1]
    if op == "name":
        if node[1] not in env:
            raise FormulaError(f"unknown name {node[1]!r}", node[2])
        return env[node[1]]
    if op == "if":
        return _eval(node[2] if _eval(node[1], env) else node[3], env)
    if op == "not":
        return not _eval(node[1], env)
    if op == "and":
        return bool(_eval(node[1], env)) and bool(_eval(node[2], env))
    if op == "or":
        return bool(_eval(node[1], env)) or bool(_eval(node[2], env))
    if op == "neg":
        return -_num(_eval(node[1], env))
    if op == "call":
        _, name, args, pos = node
        values = [_num(_eval(a, env)) for a in args]
        try:
            return _FUNCTIONS[name][2](*values)
        except ValueError:
            raise FormulaError(f"math domain error in {name}", pos) from None
    a, b = _eval(node[1], env), _eval(node[2], env)
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    a, b = _num(a), _num(b)
    try:
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return a / b
        if op == "%":
            return math.fmod(a, b) if b else a / b
        if op == "^":
            return math.pow(a, b)
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    except ZeroDivisionError:
        raise FormulaError("division by zero") from None
    except OverflowError:
        raise FormulaError("number too large") from None
    except ValueError:
        raise FormulaError("math domain error") from None


class Formula:
    def __init__(self, text: str):
        if len(text) > MAX_LENGTH:
            raise FormulaError(f"formula too long ({len(text)} characters, at most {MAX_LENGTH})")
        parser = _Parser(text)
        self.text, self.tree, self.names = text, parser.parse(), frozenset(parser.names)

    def eval(self, env: Mapping[str, object]):
        try:
            v = _eval(self.tree, env)
        except RecursionError:
            raise FormulaError("formula nested too deeply") from None
        if isinstance(v, float) and not math.isfinite(v):
            raise FormulaError("number too large")
        return v


@functools.lru_cache(maxsize=4096)
def compile_formula(text: str) -> Formula:
    return Formula(text)


def value_of(v, env: Mapping[str, object]):
    """A field's value: a number or bool as it is, a string evaluated as a formula."""
    if isinstance(v, bool | int | float):
        return v
    if isinstance(v, str):
        return compile_formula(v).eval(env)
    raise FormulaError(f"not a number or formula: {v!r}")
```

Note: `7 % 3` must equal 1 — `math.fmod(7, 3)` is `1.0`, fine; `x % 0` falls into `a / b` and raises division by zero.

- [ ] **Step 4: Run to verify they pass**

Run: `pixi run pytest tests/python/test_objexpr.py -q`
Expected: all PASS. If `"x.__class__"` passes the tokenizer as the dotted name `x.__class__`: it can't — names after a dot must start with a letter, so `_` is unexpected (`FormulaError`).

- [ ] **Step 5: Commit**

```bash
git add python/kimbim/objexpr.py tests/python/test_objexpr.py
git commit -m "feat(objects): formula evaluator for object definitions, no eval (D99)"
```

---

### Task 3: The format and parameters (`objects.py`)

**Files:**
- Create: `python/kimbim/objects.py`
- Create: `python/kimbim/objbuild.py` (only `ObjectError` and stubs `check`/`build` in this task; Task 4 fills them)
- Test: `tests/python/test_objects.py`

**Interfaces:**
- Consumes: `objexpr.value_of`, `FormulaError`.
- Produces (objects.py):
  - `FORMAT = "kimbim-object/1"`, `KINDS`, `MAX_FILE_BYTES = 1_000_000`
  - `ObjectError` (re-exported from objbuild)
  - `ParamDef(data: dict, where: str)` with `key, kind, label: dict[str,str]` (`en`, `es`), `default, lo, hi` (raw: number or formula), `options: list[tuple[str, dict]]` (id, label), `show_when: str | None`, `group: str | None`; `bounds(env) -> (lo, hi)`; `clean(value, env)`; `option_label(value_id, lang="en")`
  - `ComponentDef(name, data, where)` with `params: list[ParamDef]`, `parts: list[dict]`, `values(given=None) -> dict`
  - `ObjectDef(data, source="bundled", library="", check=True)` with `key, ref, name, names, category, ifc: dict[str, tuple], origin, params, materials: dict[slot, (label_dict, default)], parts, components: dict[str, ComponentDef], symbol: list | None, source, library, text, hash`; methods `param(key_or_label)`, `values(given=None) -> dict`, `visible(values) -> list[str]`, `material_of(values, part)`, `type_name(values) -> str`, `ifc_for(schema)`, `shape(values)` (Task 4)
  - `canonical(data) -> str`, `digest(text) -> str` (32 hex), `load(data, source="bundled", library="", check=True)`, `load_file(path, source, check=True)`, `from_text(text, source, library="")` (cached by digest)

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""D99 format: loading, validation messages, parameters (kinds, limits as formulas, show_when), clean."""
import json

import pytest

from kimbim import objects
from kimbim.objects import ObjectError


def minimal(**over):
    data = {
        "format": "kimbim-object/1", "id": "stool", "name": {"en": "Stool", "es": "Taburete"},
        "category": "furniture", "ifc": {"IFC4": ["IfcFurnitureType", "CHAIR", None]},
        "params": [
            {"key": "width", "kind": "length", "label": "Width", "default": 0.4},
            {"key": "height", "kind": "length", "label": {"en": "Height", "es": "Altura"}, "default": 0.6,
             "max": "width * 3"},
            {"key": "legs", "kind": "count", "label": "Legs", "default": 3, "min": 1, "max": 8},
            {"key": "layout", "kind": "choice", "label": "Layout", "default": "circle",
             "options": [{"id": "circle", "label": {"en": "On a circle", "es": "En círculo"}},
                         {"id": "corners", "label": "At the corners"}]},
            {"key": "radius", "kind": "length", "label": "Radius", "default": 0.15, "show_when": "layout == 'circle'"},
            {"key": "arms", "kind": "bool", "label": "Arms", "default": False},
            {"key": "splay", "kind": "angle", "label": "Splay", "default": 0, "min": 0, "max": 20},
        ],
        "materials": {"frame": {"label": "Frame material", "default": "Steel"}},
        "parts": [{"id": "seat", "box": {"dx": "width", "dy": "width", "dz": 0.04, "z": "height - 0.04"}}],
    }
    data.update(over)
    return data


def test_loads_and_fills_defaults():
    d = objects.load(minimal())
    assert d.key == d.ref == "stool" and d.name == "Stool" and d.names["es"] == "Taburete"
    assert d.ifc["IFC4"] == ("IfcFurnitureType", "CHAIR", None)
    v = d.values()
    assert v == {"width": 0.4, "height": 0.6, "legs": 3, "layout": "circle", "radius": 0.15, "arms": False,
                 "splay": 0.0, "mat_frame": "Steel"}
    assert d.param("Legs").key == "legs" and d.param("mat_frame").kind == "material"


def test_office_and_project_refs():
    assert objects.load(minimal(), source="office").ref == "office:stool"


def test_limits_are_formulas_and_values_clamp():
    d = objects.load(minimal())
    assert d.values({"height": 5})["height"] == pytest.approx(1.2)  # max = width * 3
    assert d.values({"legs": 99})["legs"] == 8
    assert d.values({"legs": 2.6})["legs"] == 3
    assert d.values({"splay": -5})["splay"] == 0


def test_clean_choice_and_bool_from_text():
    d = objects.load(minimal())
    assert d.values({"layout": "At the corners"})["layout"] == "corners"
    assert d.values({"layout": "en círculo"})["layout"] == "circle"
    assert d.values({"layout": "nonsense"})["layout"] == "circle"  # unknown: the default
    for text, want in (("true", True), ("false", False), ("1", True), ("0", False), (True, True), ("sí", True)):
        assert d.values({"arms": text})["arms"] is want


def test_show_when():
    d = objects.load(minimal())
    assert "radius" in d.visible(d.values())
    assert "radius" not in d.visible(d.values({"layout": "corners"}))


def test_type_name():
    d = objects.load(minimal())
    assert d.type_name(d.values()) == "Stool 400x600"
    assert d.type_name(d.values({"legs": 4, "splay": 8, "arms": True})) == "Stool 400x600 (Legs 4, Arms yes, Splay 8°)"


def test_canonical_and_digest_are_stable():
    a = objects.canonical(minimal())
    b = objects.canonical(json.loads(json.dumps(minimal(), indent=3)))
    assert a == b and objects.digest(a) == objects.digest(b) and len(objects.digest(a)) == 32
    assert objects.load(minimal()).hash == objects.digest(a)


@pytest.mark.parametrize("change, message", [
    ({"format": "kimbim-object/0"}, "format"),
    ({"id": "Bad Id"}, "id"),
    ({"category": "spaceship"}, "category"),
    ({"ifc": {"IFC2X3": ["IfcFurnitureType", None, "Chair"]}}, "IFC4"),
    ({"colour": "red"}, "unknown field 'colour'"),
    ({"params": [{"key": "w", "kind": "size", "label": "W", "default": 1}]}, "params.w: unknown kind"),
    ({"params": [{"key": "i", "kind": "count", "label": "I", "default": 1}]}, "reserved"),
    ({"params": [{"key": "a", "kind": "count", "label": "A", "default": 1},
                 {"key": "a", "kind": "count", "label": "B", "default": 1}]}, "twice"),
    ({"params": [{"key": "c", "kind": "choice", "label": "C", "default": "x", "options": [{"id": "y", "label": "Y"}]}]},
     "params.c: default"),
    ({"params": [{"key": "a", "kind": "count", "label": "Legs", "default": 1},
                 {"key": "b", "kind": "count", "label": "legs", "default": 1}]}, "label 'legs' is used twice"),
])
def test_validation_names_the_field(change, message):
    with pytest.raises(ObjectError, match=message):
        objects.load(minimal(**change))


def test_load_file_limits_size(tmp_path):
    p = tmp_path / "big.kimobj"
    p.write_text(" " * (objects.MAX_FILE_BYTES + 1), encoding="utf-8")
    with pytest.raises(ObjectError, match="too large"):
        objects.load_file(str(p), "office")
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ObjectError, match="big.kimobj"):
        objects.load_file(str(p), "office")


def test_from_text_is_cached():
    text = objects.canonical(minimal())
    assert objects.from_text(text, "project") is objects.from_text(text, "project")
```

- [ ] **Step 2: Run to verify they fail**

Run: `pixi run pytest tests/python/test_objects.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'kimbim.objects'`

- [ ] **Step 3: Create `objbuild.py` with the error class and stubs**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Building an object's geometry from its definition (D99, doc 16 §2–3)."""
from __future__ import annotations


class ObjectError(ValueError):
    """A definition that cannot load or build; the message starts with the field's path."""


def check(defn) -> None:
    """Structural validation of the parts (Task 4)."""


def build(defn, values, resolve=None):
    return None  # Task 4
```

- [ ] **Step 4: Implement `objects.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Library objects as data (D99, doc 16): the `.kimobj` format (`kimbim-object/1`), its parameters
and definitions. A definition is JSON the app reads; nothing in it runs. Geometry: objbuild.py."""
from __future__ import annotations

import functools
import json
import math
import pathlib
import re

import blake3

from . import objbuild
from .objbuild import ObjectError
from .objexpr import FormulaError, value_of

FORMAT = "kimbim-object/1"
KINDS = ("length", "angle", "count", "bool", "choice", "material")
CATEGORIES = ("furniture", "sanitary", "kitchen", "site", "office")
MAX_FILE_BYTES = 1_000_000
_FIELDS = {"format", "id", "name", "category", "ifc", "origin", "params", "materials", "parts", "components", "symbol"}
_PARAM_FIELDS = {"key", "kind", "label", "default", "min", "max", "options", "show_when", "group"}
_RESERVED = {"i", "n", "pi", "and", "or", "not", "true", "false", "if"}
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_LIMITS = {"length": (0.01, 50.0), "angle": (-360.0, 360.0), "count": (1, 20)}
_TRUE = {"1", "true", "yes", "on", "sí", "si"}
_FALSE = {"0", "false", "no", "off", ""}


def canonical(data) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(text: str) -> str:
    return blake3.blake3(text.encode("utf-8")).hexdigest()[:32]


def _label(v, where: str) -> dict:
    if isinstance(v, str) and v.strip():
        return {"en": v, "es": v}
    if isinstance(v, dict) and isinstance(v.get("en"), str) and v["en"].strip():
        return {"en": v["en"], "es": str(v.get("es") or v["en"])}
    raise ObjectError(f"{where}: a label is text or {{\"en\": ..., \"es\": ...}}")


class ParamDef:
    def __init__(self, data: dict, where: str):
        if not isinstance(data, dict):
            raise ObjectError(f"{where}: a parameter is an object")
        key = data.get("key")
        if not isinstance(key, str) or not _KEY.match(key):
            raise ObjectError(f"{where}: key must be lower-case letters, digits and _")
        where = f"{where[:where.rfind('[')] if '[' in where else where}.{key}"
        if key in _RESERVED:
            raise ObjectError(f"{where}: {key!r} is reserved")
        unknown = set(data) - _PARAM_FIELDS
        if unknown:
            raise ObjectError(f"{where}: unknown field {sorted(unknown)[0]!r}")
        self.key, self.kind = key, data.get("kind")
        if self.kind not in KINDS:
            raise ObjectError(f"{where}: unknown kind {self.kind!r} (one of {', '.join(KINDS)})")
        self.label = _label(data.get("label", key), f"{where}.label")
        self.group, self.show_when = data.get("group"), data.get("show_when")
        lo, hi = _LIMITS.get(self.kind, (None, None))
        self.lo, self.hi = data.get("min", lo), data.get("max", hi)
        self.options = []
        if self.kind == "choice":
            for o in data.get("options") or ():
                if not isinstance(o, dict) or not isinstance(o.get("id"), str):
                    raise ObjectError(f"{where}.options: each option has an id and a label")
                self.options.append((o["id"], _label(o.get("label", o["id"]), f"{where}.options.{o['id']}")))
            if not self.options:
                raise ObjectError(f"{where}: a choice needs options")
        if "default" not in data:
            raise ObjectError(f"{where}: default is missing")
        self.default = data["default"]
        if self.kind == "choice" and self.default not in [i for i, _ in self.options]:
            raise ObjectError(f"{where}: default {self.default!r} is not one of the options")
        self.where = where

    def bounds(self, env) -> tuple:
        try:
            lo = value_of(self.lo, env) if self.lo is not None else None
            hi = value_of(self.hi, env) if self.hi is not None else None
        except FormulaError as ex:
            raise ObjectError(f"{self.where}: {ex}") from None
        return lo, hi

    def option_label(self, value_id: str, lang: str = "en") -> str:
        return next((label[lang] for i, label in self.options if i == value_id), str(value_id))

    def clean(self, value, env):
        """The value as this kind (text from the UI too), clamped to the limits."""
        if self.kind == "material":
            return str(value).strip() or str(self.default)
        if self.kind == "choice":
            text = str(value).strip().lower()
            for i, label in self.options:
                if text in (i.lower(), label["en"].lower(), label["es"].lower()):
                    return i
            return self.default
        if self.kind == "bool":
            if isinstance(value, str):
                t = value.strip().lower()
                return True if t in _TRUE else False if t in _FALSE else bool(self.default)
            return bool(value)
        v = float(str(value).replace(",", ".")) if isinstance(value, str) else float(value)
        if not math.isfinite(v):
            raise ValueError("not a finite number")
        lo, hi = self.bounds(env)
        if self.kind == "count":
            v = int(round(v))
            lo = math.ceil(lo) if lo is not None else None
            hi = math.floor(hi) if hi is not None else None
        else:
            v = round(v, 4)
        if lo is not None:
            v = max(v, lo)
        if hi is not None:
            v = min(v, hi)
        return int(v) if self.kind == "count" else float(v)

    def text_of(self, value) -> str:
        """For type names: a count, choice, bool or material as written, a length in mm, an angle in °."""
        if self.kind == "length":
            return str(int(round(value * 1000)))
        if self.kind == "angle":
            return f"{value:g}°"
        if self.kind == "bool":
            return "yes" if value else "no"
        if self.kind == "choice":
            return self.option_label(value)
        return str(value)


def _params(raw, where) -> list:
    if not isinstance(raw, list):
        raise ObjectError(f"{where}: a list of parameters")
    out = [ParamDef(p, f"{where}[{k}]") for k, p in enumerate(raw)]
    seen = set()
    for p in out:
        if p.key in seen:
            raise ObjectError(f"{where}.{p.key}: the key is used twice")
        seen.add(p.key)
    return out


def _values(params, given) -> dict:
    """Defaults (formulas over earlier values) or the given values, then each cleaned."""
    given = given or {}
    raw = {"pi": math.pi}
    for p in params:
        if p.key in given:
            raw[p.key] = given[p.key]
        elif isinstance(p.default, str) and p.kind not in ("choice", "material"):
            try:
                raw[p.key] = value_of(p.default, raw)
            except FormulaError as ex:
                raise ObjectError(f"{p.where}.default: {ex}") from None
        else:
            raw[p.key] = p.default
    out = {}
    for p in params:
        env = {**raw, **out}
        try:
            out[p.key] = p.clean(raw[p.key], env)
        except ObjectError:
            raise
        except (TypeError, ValueError):  # a given value that cannot be read: the default
            default = (value_of(p.default, raw) if isinstance(p.default, str) and p.kind not in ("choice", "material")
                       else p.default)
            out[p.key] = p.clean(default, env)
    return out


class ComponentDef:
    """A part group inside an object file: an object without IFC class, origin or symbol."""

    def __init__(self, name: str, data: dict, where: str):
        if not isinstance(data, dict):
            raise ObjectError(f"{where}: a component is an object")
        unknown = set(data) - {"params", "parts"}
        if unknown:
            raise ObjectError(f"{where}: unknown field {sorted(unknown)[0]!r}")
        self.key, self.where = name, where
        self.params = _params(data.get("params", []), f"{where}.params")
        self.parts = data.get("parts", [])
        self.components = {}

    def values(self, given=None) -> dict:
        return _values(self.params, given)


class ObjectDef:
    def __init__(self, data: dict, source: str = "bundled", library: str = "", check: bool = True):
        if not isinstance(data, dict):
            raise ObjectError("an object file holds one JSON object")
        if data.get("format") != FORMAT:
            raise ObjectError(f"format: must be {FORMAT!r}")
        unknown = set(data) - _FIELDS
        if unknown:
            raise ObjectError(f"unknown field {sorted(unknown)[0]!r}")
        key = data.get("id")
        if not isinstance(key, str) or not _KEY.match(key):
            raise ObjectError("id: lower-case letters, digits and _")
        self.key, self.source, self.library = key, source, library
        self.ref = key if source == "bundled" else f"{source}:{key}"
        self.names = _label(data.get("name", key), "name")
        self.name = self.names["en"]
        self.category = data.get("category", "furniture")
        if self.category not in CATEGORIES:
            raise ObjectError(f"category: one of {', '.join(CATEGORIES)}")
        ifc = data.get("ifc") or {}
        if "IFC4" not in ifc:
            raise ObjectError("ifc: an IFC4 entry [type class, predefined type, element type] is required")
        self.ifc = {k: tuple(v) for k, v in ifc.items()}
        self.origin = tuple(float(v) for v in data.get("origin", (0.0, 0.0)))
        self.params = _params(data.get("params", []), "params")
        self.materials = {}
        for slot, m in (data.get("materials") or {}).items():
            if not _KEY.match(slot) or not isinstance(m, dict) or not m.get("default"):
                raise ObjectError(f"materials.{slot}: needs a label and a default building material")
            self.materials[slot] = (_label(m.get("label", "Material"), f"materials.{slot}.label"), m["default"])
            self.params.append(ParamDef({"key": f"mat_{slot}", "kind": "material", "label": m.get("label", "Material"),
                                         "default": m["default"]}, f"materials.{slot}"))
        labels = {}
        for p in self.params:  # Properties lists parameters by label: two must not share one
            if p.label["en"].lower() in labels:
                raise ObjectError(f"{p.where}: the label {p.label['en']!r} is used twice")
            labels[p.label["en"].lower()] = p.key
        self.parts = data.get("parts", [])
        if not isinstance(self.parts, list):
            raise ObjectError("parts: a list")
        self.components = {name: ComponentDef(name, c, f"components.{name}")
                           for name, c in (data.get("components") or {}).items()}
        self.symbol = data.get("symbol")
        self.text = canonical(data)
        self.hash = digest(self.text)
        self.data = data
        if check:
            objbuild.check(self)
            self.shape(self.values())  # a definition must build at its defaults

    def param(self, key_or_label: str):
        k = (key_or_label or "").strip().lower()
        return next((p for p in self.params if p.key == k or p.label["en"].lower() == k
                     or p.label["es"].lower() == k), None)

    def values(self, given=None) -> dict:
        return _values(self.params, given)

    def visible(self, values: dict) -> list:
        out = []
        for p in self.params:
            try:
                shown = p.show_when is None or bool(value_of(p.show_when, {**values, "pi": math.pi}))
            except FormulaError:
                shown = True
            if shown:
                out.append(p.key)
        return out

    def shape(self, values: dict):
        return objbuild.build(self, values)

    def material_of(self, values: dict, part: str) -> str | None:
        """The building material of one slot: its parameter, else the object's main one, else None."""
        if f"mat_{part}" in values:
            return values[f"mat_{part}"]
        if "mat_body" in values:
            return values["mat_body"]
        first = next(iter(self.materials), None)
        return values.get(f"mat_{first}") if first else None

    def type_name(self, values: dict) -> str:
        """`Chair 450x500x850 (Legs 3, Splay 8°)`: sizes, then every other value that is not its default.
        Material slots are left out (a type per material already differs by its Parameters)."""
        mm = lambda v: str(int(round(v * 1000)))  # noqa: E731
        name = f"{self.name} {'x'.join(mm(values[k]) for k in ('width', 'depth', 'height') if k in values)}".rstrip()
        defaults = self.values()
        extra = [f"{p.label['en']} {p.text_of(values[p.key])}" for p in self.params
                 if p.key not in ("width", "depth", "height") and not p.key.startswith("mat_")
                 and values[p.key] != defaults[p.key]]
        return name + (f" ({', '.join(extra)})" if extra else "")

    def ifc_for(self, schema: str):
        return self.ifc.get("IFC2X3" if schema == "IFC2X3" else "IFC4") or self.ifc["IFC4"]


def load(data: dict, source: str = "bundled", library: str = "", check: bool = True) -> ObjectDef:
    return ObjectDef(data, source, library, check)


def load_file(path: str, source: str, check: bool = True) -> ObjectDef:
    p = pathlib.Path(path)
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            raise ObjectError(f"file too large (at most {MAX_FILE_BYTES // 1000} kB)")
        data = json.loads(p.read_text(encoding="utf-8"))
        return ObjectDef(data, source, str(p), check)
    except (OSError, ValueError) as ex:
        raise ObjectError(f"{p.name}: {ex}") from None


@functools.lru_cache(maxsize=512)
def _from_text(text: str, source: str, library: str) -> ObjectDef:
    return ObjectDef(json.loads(text), source, library, check=False)


def from_text(text: str, source: str, library: str = "") -> ObjectDef:
    """A definition stored in a model (its type's Definition): parsed once per text."""
    return _from_text(text, source, library)
```

`ParamDef.__init__` turns `where="params[0]"` and key `w` into `params.w`, which is what the validation messages start with.

- [ ] **Step 5: Run to verify they pass**

Run: `pixi run pytest tests/python/test_objects.py -q`
Expected: all PASS (the stub `build` returns None, so the load-time dry build does nothing yet).

- [ ] **Step 6: Commit**

```bash
git add python/kimbim/objects.py python/kimbim/objbuild.py tests/python/test_objects.py
git commit -m "feat(objects): the kimobj format, parameter kinds and definitions (D99)"
```

---

### Task 4: Building geometry (`objbuild.py`)

**Files:**
- Modify: `python/kimbim/objbuild.py` (replace the stubs)
- Modify: `pixi.toml` (`shapely = "*"` under `[dependencies]`, beside `numpy`) — it is already installed transitively; make it explicit
- Test: `tests/python/test_objbuild.py`

**Interfaces:**
- Consumes: `objexpr.value_of`, `FormulaError`; a definition with `key, parts, components, symbol, origin, values()` (duck-typed: `ObjectDef`, `ComponentDef`).
- Produces:
  - `MAX_SOLIDS = 5000`, `MAX_USE_DEPTH = 50`, `MAX_POINTS = 2000`, `SHAPES`
  - `class Shape`: `solids: list[dict]` — each `{"kind": "box"|"cylinder"|"cone"|"prism"|"revolve"|"sweep", "matrix": 4×4 nested list (object metres; local→object), "part": slot, ...fields}`; fields after evaluation: box `x y z dx dy dz taper`; cylinder `cx cy z r h`; cone `cx cy z r1 r2 h`; prism `points z h`; revolve `profile angle`; sweep `path` and `r` or `profile`. `curves: list` of `("poly", [(x, y), ...])` or `("circle", cx, cy, r)`. Methods `polylines() -> list[list[[x, y]]]` (circles as 24 points + closing point, rounded 4 decimals), `metrics() -> dict` (same keys as Task 1's golden).
  - `solid_points(s) -> list[(x, y, z)]` (object coordinates; 64 samples per circle), `solid_volume(s) -> float`
  - `ellipse_points(cx, cy, rx, ry, a0=0, a1=2π, n=16, closed=True)`, `rounded_rect(x, y, dx, dy, r, n=4)` (moved from library.py, identical maths)
  - `check(defn)`, `build(defn, values, resolve=None) -> Shape`; `resolve(ref) -> ObjectDef | None` for `use` of another library object.

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""D99 geometry: shapes, frames, anchors and patterns, repeats, when, use/with, axes, symbol and
auto outline, limits."""
import math

import numpy as np
import pytest

from kimbim import objects
from kimbim.objbuild import MAX_SOLIDS, ObjectError


def obj(parts, params=None, symbol=None, components=None, **extra):
    data = {"format": "kimbim-object/1", "id": "t", "name": "T", "category": "furniture",
            "ifc": {"IFC4": ["IfcFurnitureType", "CHAIR", None]},
            "params": params or [{"key": "width", "kind": "length", "label": "Width", "default": 1.0},
                                 {"key": "depth", "kind": "length", "label": "Depth", "default": 0.5}],
            "parts": parts, **extra}
    if symbol is not None:
        data["symbol"] = symbol
    if components is not None:
        data["components"] = components
    return objects.load(data)


def shape(d, **given):
    return d.shape(d.values(given))


def origin(s):
    return np.array(s["matrix"])[:3, 3]


def test_box_and_metrics():
    s = shape(obj([{"id": "b", "box": {"dx": "width", "dy": "depth", "dz": 0.1}}]))
    m = s.metrics()
    assert m["bbox"] == pytest.approx([0, 0, 0, 1, 0.5, 0.1])
    assert m["volume"] == pytest.approx(0.05)


@pytest.mark.parametrize("part, volume", [
    ({"cylinder": {"r": 0.1, "h": 1}}, math.pi * 0.01),
    ({"cone": {"r1": 0.1, "r2": 0.05, "h": 1}}, math.pi * (0.01 + 0.005 + 0.0025) / 3),
    ({"prism": {"points": [[0, 0], [1, 0], [0, 1]], "h": 2}}, 1.0),
    ({"revolve": {"profile": [[0, 0], [0.1, 0], [0.1, 1], [0, 1]]}}, math.pi * 0.01),
    ({"sweep": {"r": 0.01, "path": [[0, 0, 0], [1, 0, 0], [1, 1, 0]]}}, math.pi * 0.0001 * 2),
    ({"sweep": {"profile": [[-0.05, -0.05], [0.05, -0.05], [0.05, 0.05], [-0.05, 0.05]], "path": [[0, 0, 0], [0, 0, 2]]}}, 0.02),
    ({"box": {"dx": 1, "dy": 1, "dz": 3, "taper": 0.5}}, 3 * (1 + 0.25 + 0.5) / 3),
])
def test_every_shape_has_a_volume(part, volume):
    s = shape(obj([{"id": "p", **part}]))
    assert len(s.solids) == 1
    assert s.metrics()["volume"] == pytest.approx(volume, rel=1e-6)


def test_point_generators():
    s = shape(obj([{"id": "p", "prism": {"points": [{"ellipse": [0.5, 0.5, 0.5, 0.25], "n": 12}], "h": 1}}]))
    assert len(s.solids[0]["points"]) == 12
    s = shape(obj([{"id": "p", "prism": {"points": [{"rounded_rect": [0, 0, 1, 1, 0.2], "n": 4}], "h": 1}}]))
    assert len(s.solids[0]["points"]) == 20


def test_thin_shapes_are_skipped():
    assert shape(obj([{"id": "b", "box": {"dx": 1, "dy": 0, "dz": 1}}])).solids == []


def test_repeat_with_index_and_when():
    d = obj([{"id": "leg", "repeat": {"count": 4}, "when": "width > 0.5",
              "box": {"x": "if(i < 2, 0, width - 0.1)", "y": "if(i % 2 == 0, 0, depth - 0.1)", "dx": 0.1, "dy": 0.1, "dz": 1}}])
    s = shape(d)
    assert sorted(tuple(np.round([x["x"], x["y"]], 3)) for x in s.solids) == [(0, 0), (0, 0.4), (0.9, 0), (0.9, 0.4)]
    assert shape(d, width=0.4).solids == []


def test_repeat_step_and_turn():
    s = shape(obj([{"id": "slat", "repeat": {"count": 3, "step": [0.2, 0, 0]}, "box": {"dx": 0.1, "dy": 0.1, "dz": 0.1}}]))
    assert [origin(x)[0] for x in s.solids] == pytest.approx([0, 0.2, 0.4])
    s = shape(obj([{"id": "arm", "repeat": {"count": 4, "turn": 90}, "box": {"x": 1, "dx": 0.1, "dy": 0.1, "dz": 0.1}}]))
    pts = [np.array(x["matrix"]) @ [1, 0, 0, 1] for x in s.solids]
    assert [tuple(np.round(p[:2], 6)) for p in pts] == [(1, 0), (0, 1), (-1, 0), (0, -1)]


SEAT = {"id": "seat", "box": {"z": 0.41, "dx": "width", "dy": "depth", "dz": 0.04},
        "anchors": {"corners": {"pattern": "rect_corners", "inset": 0.02, "z": 0.41, "dir": "down"},
                    "ring": {"pattern": "circle", "cx": "width / 2", "cy": "depth / 2", "r": 0.2, "z": 0.41, "dir": "down"},
                    "back_edge": {"x": "width / 2", "y": "depth - 0.02", "z": 0.45}}}


def test_built_in_and_single_anchors_attach_and_feed_formulas():
    s = shape(obj([SEAT,
                   {"id": "back", "attach": "seat.anchors.back_edge", "box": {"x": -0.1, "dx": 0.2, "dy": 0.02, "dz": 0.4}},
                   {"id": "lamp", "attach": "seat.top", "box": {"dx": 0.01, "dy": 0.01, "dz": "seat.back_edge.z"}}]))
    back, lamp = s.solids[1], s.solids[2]
    assert origin(back) == pytest.approx([0.5, 0.48, 0.45])
    assert origin(lamp) == pytest.approx([0.5, 0.25, 0.45])
    assert lamp["dz"] == pytest.approx(0.45)


def test_rect_corners_pattern_ignores_count_and_points_down():
    s = shape(obj([SEAT, {"id": "leg", "repeat": {"on": "seat.anchors.corners", "count": 3},
                          "box": {"x": -0.02, "y": -0.02, "dx": 0.04, "dy": 0.04, "dz": 0.41}}]))
    legs = s.solids[1:]
    assert len(legs) == 4
    assert sorted(tuple(np.round(origin(x)[:2], 3)) for x in legs) == [(0.02, 0.02), (0.02, 0.48), (0.98, 0.02), (0.98, 0.48)]
    assert s.metrics()["bbox"][2] == pytest.approx(0)  # legs reach the floor (dir down)


def test_circle_pattern_with_count_and_template():
    d = obj([SEAT, {"id": "leg", "repeat": {"on": "seat.anchors.{layout}", "count": "legs"},
                    "cylinder": {"r": 0.02, "h": 0.41}}],
            params=[{"key": "width", "kind": "length", "label": "W", "default": 1.0},
                    {"key": "depth", "kind": "length", "label": "D", "default": 0.5},
                    {"key": "legs", "kind": "count", "label": "L", "default": 3, "max": 8},
                    {"key": "layout", "kind": "choice", "label": "Layout", "default": "ring",
                     "options": [{"id": "ring", "label": "Ring"}, {"id": "corners", "label": "Corners"}]}])
    assert len(shape(d).solids) == 1 + 3
    assert len(shape(d, legs=5).solids) == 1 + 5
    assert len(shape(d, layout="corners").solids) == 1 + 4
    ring = [origin(x) for x in shape(d).solids[1:]]
    assert all(math.dist(p[:2], (0.5, 0.25)) == pytest.approx(0.2) for p in ring)


def test_away_from_centre_tilts_far_ends_outward():
    d = obj([SEAT, {"id": "leg", "repeat": {"on": "seat.anchors.ring", "count": 3},
                    "rotate": {"axis": "away_from_centre", "angle": 10}, "cylinder": {"r": 0.02, "h": 0.41}}])
    for s in shape(d).solids[1:]:
        m = np.array(s["matrix"])
        top, foot = m @ [0, 0, 0, 1], m @ [0, 0, 0.41, 1]
        centre = np.array([0.5, 0.25])
        assert np.linalg.norm(foot[:2] - centre) > np.linalg.norm(top[:2] - centre)  # the foot splays out
        assert foot[2] < top[2]
    one = obj([SEAT, {"id": "leg", "repeat": {"on": "seat.anchors.ring", "count": 1},
                      "rotate": {"axis": "away_from_centre", "angle": 10}, "cylinder": {"r": 0.02, "h": 0.41}}])
    m = np.array(shape(one).solids[1]["matrix"])
    assert m[:3, 2] == pytest.approx([0, 0, -1])  # a single copy stays upright


def test_axes_for_upright_profiles():
    s = shape(obj([{"id": "wheel", "axes": ["y", "z", "x"], "cylinder": {"cx": 2, "cy": 0.3, "z": 0.1, "r": 0.3, "h": 0.2}}]))
    assert s.metrics()["bbox"] == pytest.approx([0.1, 1.7, 0, 0.3, 2.3, 0.6], abs=1e-6)


def test_use_components_with_values_and_material_override():
    comps = {"leg_round": {"params": [{"key": "size", "kind": "length", "label": "Size", "default": 0.04},
                                      {"key": "h", "kind": "length", "label": "H", "default": 0.4}],
                           "parts": [{"id": "post", "cylinder": {"r": "size / 2", "h": "h"}}]}}
    d = obj([{"id": "leg", "material": "frame", "use": "leg_{style}", "with": {"h": "width / 2"}}],
            params=[{"key": "width", "kind": "length", "label": "W", "default": 1.0},
                    {"key": "style", "kind": "choice", "label": "S", "default": "round",
                     "options": [{"id": "round", "label": "Round"}]}],
            components=comps)
    (s,) = shape(d).solids
    assert s["h"] == pytest.approx(0.5) and s["r"] == pytest.approx(0.02) and s["part"] == "frame"


def test_use_another_library_object():
    other = objects.load({"format": "kimbim-object/1", "id": "knob", "name": "Knob", "category": "furniture",
                          "ifc": {"IFC4": ["IfcFurnitureType", "USERDEFINED", "KNOB"]},
                          "params": [{"key": "r", "kind": "length", "label": "R", "default": 0.02}],
                          "parts": [{"id": "k", "cylinder": {"r": "r", "h": 0.02}}]})
    d = objects.load({"format": "kimbim-object/1", "id": "t", "name": "T", "category": "furniture",
                      "ifc": {"IFC4": ["IfcFurnitureType", "CHAIR", None]},
                      "parts": [{"id": "k", "use": "knob", "with": {"r": 0.05}}]}, check=False)
    (s,) = build(d, d.values(), resolve=lambda ref: other if ref == "knob" else None).solids
    assert s["r"] == pytest.approx(0.05)


def test_use_cycle_is_an_error():
    with pytest.raises(ObjectError, match="cycle"):
        obj([{"id": "a", "use": "x"}], components={"x": {"parts": [{"id": "b", "use": "y"}]},
                                                     "y": {"parts": [{"id": "c", "use": "x"}]}})


def test_repeat_over_the_limit_fails_before_looping():
    import time
    start = time.perf_counter()
    with pytest.raises(ObjectError, match="limit"):
        obj([{"id": "b", "repeat": {"count": 1e9}, "box": {"dx": 1, "dy": 1, "dz": 1}}])
    with pytest.raises(ObjectError, match="limit"):
        obj([{"id": "b", "repeat": {"count": MAX_SOLIDS // 2 + 1},
              "use": "two"}], components={"two": {"parts": [{"id": "x", "repeat": {"count": 2}, "box": {"dx": 1, "dy": 1, "dz": 1}}]}})
    assert time.perf_counter() - start < 2


@pytest.mark.parametrize("parts, message", [
    ([{"id": "b", "box": {"dx": 1, "dy": 1}}], "parts.b.box: dz is missing"),
    ([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1, "colour": 2}}], "parts.b.box: unknown field 'colour'"),
    ([{"id": "b", "box": {"dx": "wdth", "dy": 1, "dz": 1}}], "parts.b: unknown name 'wdth'"),
    ([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}, "cylinder": {"r": 1, "h": 1}}], "parts.b: one shape"),
    ([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}}, {"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}}], "twice"),
    ([{"id": "b", "attach": "nothing.top", "box": {"dx": 1, "dy": 1, "dz": 1}}], "unknown part 'nothing'"),
    ([{"id": "b", "use": "ghost"}], "unknown component or object 'ghost'"),
    ([{"id": "b", "axes": ["x", "x", "z"], "box": {"dx": 1, "dy": 1, "dz": 1}}], "axes"),
])
def test_part_errors_name_the_field(parts, message):
    with pytest.raises(ObjectError, match=message):
        obj(parts)


def test_explicit_symbol_with_repeat():
    d = obj([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}}],
            symbol=[{"rect": {"x": 0, "y": 0, "dx": "width", "dy": "depth"}},
                    {"circle": {"cx": 0.5, "cy": 0.25, "r": 0.1}},
                    {"repeat": {"count": 3}, "line": {"points": [["0.1 + i * 0.2", 0], ["0.1 + i * 0.2", 0.1]]}},
                    {"when": "width > 5", "line": {"points": [[0, 0], [1, 1]]}},
                    {"ellipse": {"cx": 0.5, "cy": 0.25, "rx": 0.2, "ry": 0.1}}])
    curves = shape(d).curves
    assert [c[0] for c in curves] == ["poly", "circle", "poly", "poly", "poly", "poly"]
    assert curves[0][1] == [(0, 0), (1, 0), (1, 0.5), (0, 0.5), (0, 0)]
    assert len(curves[-1][1]) == 17  # 16 points, closed


def test_auto_outline_is_the_union_seen_from_above():
    d = obj([{"id": "a", "box": {"dx": 1, "dy": 1, "dz": 1}}, {"id": "b", "box": {"x": 0.5, "dx": 1, "dy": 1, "dz": 0.5}}])
    curves = shape(d).curves
    assert len(curves) == 1
    xs = [p[0] for p in curves[0][1]]
    assert min(xs) == pytest.approx(0) and max(xs) == pytest.approx(1.5)


def test_origin_shifts_solids_and_curves():
    d = obj([{"id": "a", "box": {"dx": 1, "dy": 1, "dz": 1}}], origin=[0.5, 0.5],
            symbol=[{"rect": {"x": 0, "y": 0, "dx": 1, "dy": 1}}])
    s = shape(d)
    assert s.metrics()["bbox"][:2] == pytest.approx([-0.5, -0.5])
    assert s.curves[0][1][0] == pytest.approx((-0.5, -0.5))
```

(`check=False` because the load-time dry build has no resolver; add `from kimbim.objbuild import build` to the imports.)

- [ ] **Step 2: Run to verify they fail**

Run: `pixi run pytest tests/python/test_objbuild.py -q`
Expected: FAIL (the stub `build` returns None: `AttributeError: 'NoneType' object has no attribute ...`).

- [ ] **Step 3: Implement `objbuild.py`**

```python
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
                 "ellipse": (("cx", "cy", "rx", "ry"), {"a0": 0, "a1": 360})}
_DIRS = {"up": (0, 0, 1), "down": (0, 0, -1), "front": (0, -1, 0), "back": (0, 1, 0),
         "left": (-1, 0, 0), "right": (1, 0, 0)}
_AXES = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1), "-x": (-1, 0, 0), "-y": (0, -1, 0), "-z": (0, 0, -1)}
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
    z = z / np.linalg.norm(z)
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


def _points(spec, env, dims, where):
    if not isinstance(spec, list):
        raise ObjectError(f"{where}: a list of points")
    out = []
    for item in spec:
        if isinstance(item, dict):
            n = int(value_of(item.get("n", CIRCLE_POINTS), env))
            if not 3 <= n <= MAX_GENERATOR_POINTS:
                raise ObjectError(f"{where}: n between 3 and {MAX_GENERATOR_POINTS}")
            if "ellipse" in item:
                cx, cy, rx, ry = (float(value_of(v, env)) for v in item["ellipse"])
                a0, a1 = (math.radians(float(value_of(item.get(k, d), env))) for k, d in (("a0", 0), ("a1", 360)))
                full = abs(a1 - a0 - 2 * math.pi) < 1e-9
                out += ellipse_points(cx, cy, rx, ry, a0, a1, n, closed=full)
            elif "rounded_rect" in item:
                x, y, dx, dy, r = (float(value_of(v, env)) for v in item["rounded_rect"])
                out += rounded_rect(x, y, dx, dy, r, n)
            else:
                raise ObjectError(f"{where}: a point generator is ellipse or rounded_rect")
        elif isinstance(item, list | tuple) and len(item) == dims:
            out.append(tuple(float(value_of(v, env)) for v in item))
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
    for p, q in zip(path, path[1:]):
        f, length = _segment_frame(p, q)
        for u, v in s["profile"]:
            for w in (0.0, length):
                out.append(tuple((f @ [u, v, w, 1])[:3]))
    return out


def solid_points(s) -> list:
    m = np.asarray(s["matrix"])
    return [tuple((m @ [x, y, z, 1])[:3]) for x, y, z in _local_points(s)]


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
        if "axes" in part:
            axes = part["axes"]
            if (not isinstance(axes, list) or len(axes) != 3 or any(a not in _AXES for a in axes)
                    or abs(np.linalg.det(np.array([_AXES[a] for a in axes], dtype=float))) < 0.5):
                raise ObjectError(f"{w}.axes: three different axes among x, y, z, -x, -y, -z")
        if "use" in part and "{" not in part["use"] and part["use"] in components:
            name = part["use"]
            if name in seen_components:
                raise ObjectError(f"{w}: use cycle {' > '.join([*seen_components, name])}")
            _check_parts(components[name].parts, f"components.{name}.parts", components, [*seen_components, name])


def check(defn) -> None:
    _check_parts(defn.parts, "parts", defn.components, [])
    for name, comp in defn.components.items():
        _check_parts(comp.parts, f"components.{name}.parts", defn.components, [name])
    if defn.symbol is not None and not isinstance(defn.symbol, list):
        raise ObjectError("symbol: a list of 2D items")


# ---------------------------------------------------------------- build

class _Ctx:
    def __init__(self, resolve):
        self.shape, self.resolve, self.material = Shape(), resolve, None

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
        elif f in _POINT_FIELDS:
            out[f] = _points(v, env, 3 if f == "path" else 2, f"{where}.{f}")
        else:
            out[f] = float(value_of(v, env))
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


def _dir_frame(spec, env, origin):
    d = spec.get("dir", "up")
    zdir = _DIRS.get(d) if isinstance(d, str) else tuple(float(value_of(v, env)) for v in d)
    if zdir is None:
        raise ObjectError(f"unknown direction {d!r} (up, down, front, back, left, right or a vector)")
    return _frame(origin, zdir)


def _pattern(spec, env, count, bbox):
    kind = spec["pattern"]
    ev = lambda k, d=None: float(value_of(spec.get(k, d), env))  # noqa: E731
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
        a = [float(value_of(v, env)) for v in spec["from"]]
        b = [float(value_of(v, env)) for v in spec["to"]]
        ts = [0.5] if count == 1 else [k / (count - 1) for k in range(count)]
        return [_dir_frame(spec, env, [a[j] + (b[j] - a[j]) * t for j in range(3)]) for t in ts]
    elif kind == "grid":
        nx, ny = int(ev("nx")), int(ev("ny"))
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
        n = float(value_of(v, env))
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
    step = [float(value_of(v, env)) for v in r.get("step", (0, 0, 0))]
    turn = float(value_of(r.get("turn", 0), env))
    return [frame @ _translate(*(k * s for s in step)) @ _rotation((0, 0, 1), k * turn) for k in range(count)]


class _Pattern:
    """A pattern anchor: frames made when a repeat asks, with its count."""

    def __init__(self, spec, env, bbox, base):
        self.spec, self.env, self.bbox, self.base = spec, env, bbox, base
        self.counted = spec["pattern"] in ("circle", "line")

    def frames(self, count):
        return [self.base @ f for f in _pattern(self.spec, self.env, count or 0, self.bbox)]


def _local(part, env, frame, centroid, where):
    m = np.eye(4)
    if "at" in part:
        m = m @ _translate(*(float(value_of(v, env)) for v in part["at"]))
    rot = part.get("rotate")
    if rot:
        angle = float(value_of(rot.get("angle", 0), env))
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
            vec = [float(value_of(v, env)) for v in axis]
        if vec is not None:
            m = m @ _rotation(vec, angle)
    if "axes" in part:
        a = np.eye(4)
        for j, name in enumerate(part["axes"]):
            a[:3, j] = _AXES[name]
        m = m @ a
    return m


def _anchors(part, env, m, solid_fields, kind, base_inv):
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
        if "pattern" in spec:
            out[name] = _Pattern(spec, env, bbox, m)
        else:
            origin = [float(value_of(spec.get(k, 0), env)) for k in ("x", "y", "z")]
            out[name] = m @ _dir_frame(spec, env, origin)
    coords = {}
    for name, f in out.items():
        if not isinstance(f, _Pattern):
            local = base_inv @ f
            coords.update({f"{part['id']}.{name}.{axis}": float(local[j, 3]) for j, axis in enumerate("xyz")})
    return out, coords


def _parts(ctx, defn, components, env, base, stack, where):
    """Build `defn.parts` in the frame `base`; `components` are the object file's components (a
    component may use its siblings)."""
    anchors = {}
    env = dict(env)
    base_inv = np.linalg.inv(base)
    for part in defn.parts:
        w = f"{where}.{part['id']}"
        try:
            if "when" in part and not value_of(part["when"], env):
                continue
            frames = _copies(part, env, anchors, base, w)
            n = len(frames)
            centroid = np.mean([f[:3, 3] for f in frames], axis=0) if frames else np.zeros(3)
            kind = next((k for k in SHAPES if k in part), None)
            first = None
            for i, frame in enumerate(frames):
                e = {**env, "i": i, "n": n}
                m = frame @ _local(part, e, frame, centroid, w)
                if "use" in part:
                    _use(ctx, components, part, e, m, stack, w)
                elif kind is not None:
                    fields = _fields(kind, part[kind], e, f"{w}.{kind}")
                    if _solid_ok(kind, fields):
                        ctx.add({"kind": kind, **fields, "matrix": m.tolist(),
                                 "part": ctx.material or part.get("material", "body")})
                if first is None:
                    first = (m, e, _fields(kind, part[kind], e, f"{w}.{kind}") if kind else None)
            if first is None:  # no copies: anchors still exist, at the base, for later parts
                e = {**env, "i": 0, "n": 0}
                first = (base @ _local(part, e, base, np.zeros(3), w), e,
                         _fields(kind, part[kind], e, f"{w}.{kind}") if kind else None)
            found, coords = _anchors(part, first[1], first[0], first[2], kind, base_inv)
            anchors[part["id"]] = found
            env.update(coords)
        except FormulaError as ex:
            raise ObjectError(f"{w}: {ex}") from None


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


def _symbol(defn, env):
    curves = []
    for k, item in enumerate(defn.symbol):
        where = f"symbol[{k}]"
        kinds = [s for s in _SYMBOL_KINDS if s in item]
        if len(kinds) != 1:
            raise ObjectError(f"{where}: one of {', '.join(_SYMBOL_KINDS)}")
        kind = kinds[0]
        try:
            if "when" in item and not value_of(item["when"], env):
                continue
            count = _count(item["repeat"]["count"], env, f"{where}.repeat.count") if "repeat" in item else 1
            for i in range(count):
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
                    x, y, dx, dy = (float(value_of(raw[f], e)) for f in ("x", "y", "dx", "dy"))
                    curves.append(("poly", [(x, y), (x + dx, y), (x + dx, y + dy), (x, y + dy), (x, y)]))
                elif kind == "circle":
                    curves.append(("circle", *(float(value_of(raw[f], e)) for f in ("cx", "cy", "r"))))
                else:
                    cx, cy, rx, ry = (float(value_of(raw[f], e)) for f in ("cx", "cy", "rx", "ry"))
                    a0, a1 = (math.radians(float(value_of(raw.get(f, d), e))) for f, d in (("a0", 0), ("a1", 360)))
                    closed = abs(a1 - a0 - 2 * math.pi) < 1e-9
                    n = CIRCLE_POINTS if closed else max(4, int(CIRCLE_POINTS * abs(a1 - a0) / (2 * math.pi)) + 1)
                    pts = ellipse_points(cx, cy, rx, ry, a0, a1, n, closed)
                    curves.append(("poly", pts + pts[:1] if closed else pts))
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


def build(defn, values, resolve=None) -> Shape:
    ctx = _Ctx(resolve)
    env = {**values, "pi": math.pi}
    _parts(ctx, defn, defn.components, env, np.eye(4), [], "parts")
    shape = ctx.shape
    shape.curves = _symbol(defn, env) if defn.symbol is not None else _outline(shape)
    ox, oy = getattr(defn, "origin", (0.0, 0.0))
    if abs(ox) > 1e-12 or abs(oy) > 1e-12:  # D92: the object's own origin goes to (0, 0)
        shift = _translate(-ox, -oy, 0)
        for s in shape.solids:
            s["matrix"] = (shift @ np.asarray(s["matrix"])).tolist()
        shape.curves = [("poly", [(x - ox, y - oy) for x, y in c[1]]) if c[0] == "poly" else (c[0], c[1] - ox, c[2] - oy, c[3])
                        for c in shape.curves]
    return shape
```

Implementation notes:
- `repeat.count` above `MAX_SOLIDS` fails in `_count` before any loop; the second limit test (2,501 × 2 solids) fails in `_Ctx.add` once the 5,001st solid is added.
- The structural `check()` catches the cycle without values; `_use` also catches it at build time (for template names like `"x_{style}"`).

- [ ] **Step 4: Add shapely to `pixi.toml`**

Add `shapely = "*"` next to `numpy = "*"` in `[dependencies]`, then `pixi install`.

- [ ] **Step 5: Run to verify they pass**

Run: `pixi run pytest tests/python/test_objbuild.py tests/python/test_objects.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add python/kimbim/objbuild.py tests/python/test_objbuild.py pixi.toml pixi.lock
git commit -m "feat(objects): build geometry from definitions: shapes, anchors, repeats, use, symbols (D99)"
```

---

### Task 5: Port the 21 bundled objects and prove them identical

**Files:**
- Create: `python/kimbim/bundled_objects/{table,chair,sofa,bed_single,bed_double,wardrobe,desk,shelf,wc,washbasin,bathtub,shower_tray,bidet,base_cabinets,wall_cabinets,sink_unit,fridge,cooker,person,tree,car}.kimobj`
- Test: `tests/python/test_object_port.py`

**Interfaces:**
- Consumes: `objects.load_file(path, "bundled")`, `ObjectDef.values`, `Shape.metrics()`; `tests/golden/library_objects.json` (Task 1).
- Produces: 21 files whose `id` equals today's key, with today's parameter keys, labels, defaults, limits and material slots.

`library.py` is unchanged in this task: the Python objects keep working while the files are proven.

- [ ] **Step 1: Write the failing test**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""D99 port (doc 16 §8): every bundled .kimobj builds the same geometry and plan symbol as the
Python object it replaces, at its defaults and at two other value sets (tests/golden/library_objects.json)."""
import json
import pathlib

import pytest

from kimbim import objects

ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT / "tests/golden/library_objects.json").read_text(encoding="utf-8"))
BUNDLED = ROOT / "python/kimbim/bundled_objects"


def cases():
    return [(key, name) for key in sorted(GOLDEN) for name in sorted(GOLDEN[key])]


@pytest.mark.parametrize("key, name", cases())
def test_port_matches_the_python_object(key, name):
    want = GOLDEN[key][name]
    d = objects.load_file(str(BUNDLED / f"{key}.kimobj"), "bundled")
    assert d.key == key
    values = d.values(want["values"])
    for k, v in want["values"].items():
        assert values[k] == pytest.approx(v), k
    got = d.shape(values).metrics()
    assert got["bbox"] == pytest.approx(want["bbox"], abs=1e-3)
    assert got["volume"] == pytest.approx(want["volume"], rel=5e-3)
    assert got["symbol_bbox"] == pytest.approx(want["symbol_bbox"], abs=1e-3)
    assert got["symbol_length"] == pytest.approx(want["symbol_length"], rel=5e-3)


def test_every_bundled_file_is_a_golden_object():
    assert sorted(p.stem for p in BUNDLED.glob("*.kimobj")) == sorted(GOLDEN)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pixi run pytest tests/python/test_object_port.py -q`
Expected: FAIL (`FileNotFoundError`/`ObjectError` for each missing file).

- [ ] **Step 3: Write the files**

Port each builder in `python/kimbim/library.py` (lines 271–576 today) statement by statement with this mapping. Keep each object's `define(...)` arguments: id, English name, category, IFC tuple (expand `FURNITURE(pre, element)` to `{"IFC4": ["IfcFurnitureType", pre, element], "IFC2X3": ["IfcFurnitureType", null, element or pre.title()]}`, `SANITARY(pre)` to `{"IFC4": ["IfcSanitaryTerminalType", pre, null]}`, `APPLIANCE(pre)` to `{"IFC4": ["IfcElectricApplianceType", pre, null]}`, `PROXY(e)` to `{"IFC4": ["IfcBuildingElementProxyType", "USERDEFINED", e], "IFC2X3": [same]}`), parameters (`W(d)` = `{"key": "width", "kind": "length", "label": "Width", "default": d}`, likewise `D`/`H`; `Param(key, label, default, kind, lo, hi)` with `min`/`max` only when given), and materials (`materials={part: (label, default)}`; objects in furniture, sanitary and kitchen **without** `materials` get `{"body": {"label": "Material", "default": DEFAULT_MATERIALS[category]}}`: `Timber - finish` for furniture and kitchen, `Porcelain` for sanitary). Spanish names and labels: copy them from `app/translations/kimbim_es.ts` (context `LibraryPanel`; e.g. `Chair` → `Silla`) into `{"en": ..., "es": ...}`.

| Python | `.kimobj` |
|--------|-----------|
| `s.part = "frame"` before solids | `"material": "frame"` on those parts |
| `s.box(x, y, z, dx, dy, dz)` | `{"id": ..., "box": {"x": x, "y": y, "z": z, "dx": dx, "dy": dy, "dz": dz}}` |
| `s.cylinder(cx, cy, z, r, dz)` | `{"cylinder": {"cx": cx, "cy": cy, "z": z, "r": r, "h": dz}}` |
| `s.prism(points, z, dz)` | `{"prism": {"points": points, "z": z, "h": dz}}` |
| `s.side_prism(pts_yz, x, dx)` | `{"axes": ["y", "z", "x"], "prism": {"points": pts_yz, "z": x, "h": dx}}` |
| `s.side_cylinder(cy, cz, x, r, dx)` | `{"axes": ["y", "z", "x"], "cylinder": {"cx": cy, "cy": cz, "z": x, "r": r, "h": dx}}` |
| `ellipse_points(cx, cy, rx, ry, n=k)` in a prism | `{"ellipse": [cx, cy, rx, ry], "n": k}` |
| `rounded_rect(x, y, dx, dy, r, n)` | `{"rounded_rect": [x, y, dx, dy, r], "n": n}` |
| `s.rect(x, y, dx, dy)` | `{"rect": {"x": x, "y": y, "dx": dx, "dy": dy}}` in `symbol` |
| `s.line(a, b, ...)` / `closed=True` | `{"line": {"points": [a, b, ...], "closed": true}}` |
| `s.circle(cx, cy, r)` | `{"circle": {"cx": cx, "cy": cy, "r": r}}` |
| `s.ellipse(cx, cy, rx, ry)` | `{"ellipse": {"cx": cx, "cy": cy, "rx": rx, "ry": ry}}` |
| `for` loops | `"repeat": {"count": ...}` with `i`; nested loops become one repeat with `i % k` and `floor(i / k)` |
| local variables (`arm = 0.15`) | inline the expression in each formula |
| `p["seat"]` | the parameter name `seat` |
| `int(x)` of a positive value | `floor(x)` |

Every object must have an explicit `symbol` (they all draw one today), so the auto outline is never used by bundled objects.

Six complete examples — write these exactly, and the other fifteen the same way:

`table.kimobj`
```json
{
 "format": "kimbim-object/1", "id": "table", "name": {"en": "Table", "es": "Mesa"}, "category": "furniture",
 "ifc": {"IFC4": ["IfcFurnitureType", "TABLE", null], "IFC2X3": ["IfcFurnitureType", null, "Table"]},
 "params": [
  {"key": "width", "kind": "length", "label": {"en": "Width", "es": "Ancho"}, "default": 1.6},
  {"key": "depth", "kind": "length", "label": {"en": "Depth", "es": "Fondo"}, "default": 0.9},
  {"key": "height", "kind": "length", "label": {"en": "Height", "es": "Altura"}, "default": 0.75}
 ],
 "materials": {"top": {"label": "Top material", "default": "Timber - finish"},
               "legs": {"label": "Legs material", "default": "Steel"}},
 "parts": [
  {"id": "leg", "material": "legs", "repeat": {"count": 4},
   "box": {"x": "if(i < 2, 0.03, width - 0.09)", "y": "if(i % 2 == 0, 0.03, depth - 0.09)",
           "dx": 0.06, "dy": 0.06, "dz": "height - 0.04"}},
  {"id": "top", "material": "top", "box": {"z": "height - 0.04", "dx": "width", "dy": "depth", "dz": 0.04}}
 ],
 "symbol": [{"rect": {"x": 0, "y": 0, "dx": "width", "dy": "depth"}}]
}
```

`chair.kimobj` (the plain port; Task 9 extends it)
```json
{
 "format": "kimbim-object/1", "id": "chair", "name": {"en": "Chair", "es": "Silla"}, "category": "furniture",
 "ifc": {"IFC4": ["IfcFurnitureType", "CHAIR", null], "IFC2X3": ["IfcFurnitureType", null, "Chair"]},
 "params": [
  {"key": "width", "kind": "length", "label": {"en": "Width", "es": "Ancho"}, "default": 0.45},
  {"key": "depth", "kind": "length", "label": {"en": "Depth", "es": "Fondo"}, "default": 0.5},
  {"key": "height", "kind": "length", "label": {"en": "Height", "es": "Altura"}, "default": 0.85},
  {"key": "seat", "kind": "length", "label": {"en": "Seat height", "es": "Altura del asiento"}, "default": 0.45}
 ],
 "materials": {"frame": {"label": "Frame material", "default": "Steel"},
               "seat": {"label": "Seat material", "default": "Timber - finish"}},
 "parts": [
  {"id": "leg", "material": "frame", "repeat": {"count": 4},
   "box": {"x": "if(i < 2, 0, width - 0.04)", "y": "if(i % 2 == 0, 0, depth - 0.04)",
           "dx": 0.04, "dy": 0.04, "dz": "seat - 0.04"}},
  {"id": "seat_board", "material": "seat", "box": {"z": "seat - 0.04", "dx": "width", "dy": "depth", "dz": 0.04}},
  {"id": "back", "material": "seat",
   "box": {"y": "depth - 0.04", "z": "seat", "dx": "width", "dy": 0.04, "dz": "max(height - seat, 0.01)"}}
 ],
 "symbol": [{"rect": {"x": 0, "y": 0, "dx": "width", "dy": "depth"}},
            {"line": {"points": [[0, "depth - 0.04"], ["width", "depth - 0.04"]]}}]
}
```

`sofa.kimobj`
```json
{
 "format": "kimbim-object/1", "id": "sofa", "name": {"en": "Sofa", "es": "Sofá"}, "category": "furniture",
 "ifc": {"IFC4": ["IfcFurnitureType", "SOFA", null], "IFC2X3": ["IfcFurnitureType", null, "Sofa"]},
 "params": [
  {"key": "width", "kind": "length", "label": {"en": "Width", "es": "Ancho"}, "default": 2.0},
  {"key": "depth", "kind": "length", "label": {"en": "Depth", "es": "Fondo"}, "default": 0.9},
  {"key": "height", "kind": "length", "label": {"en": "Height", "es": "Altura"}, "default": 0.8},
  {"key": "seats", "kind": "count", "label": {"en": "Seats", "es": "Plazas"}, "default": 3, "min": 1, "max": 6}
 ],
 "materials": {"body": {"label": "Material", "default": "Fabric"}},
 "parts": [
  {"id": "arm_left", "box": {"dx": 0.15, "dy": "depth", "dz": "height * 0.75"}},
  {"id": "arm_right", "box": {"x": "width - 0.15", "dx": 0.15, "dy": "depth", "dz": "height * 0.75"}},
  {"id": "back", "box": {"x": 0.15, "y": "depth - 0.2", "dx": "width - 0.3", "dy": 0.2, "dz": "height"}},
  {"id": "seat", "box": {"x": 0.15, "dx": "width - 0.3", "dy": "depth - 0.2", "dz": 0.42}}
 ],
 "symbol": [
  {"rect": {"x": 0, "y": 0, "dx": "width", "dy": "depth"}},
  {"line": {"points": [[0.15, 0], [0.15, "depth"]]}},
  {"line": {"points": [["width - 0.15", 0], ["width - 0.15", "depth"]]}},
  {"line": {"points": [[0.15, "depth - 0.2"], ["width - 0.15", "depth - 0.2"]]}},
  {"repeat": {"count": "seats - 1"},
   "line": {"points": [["0.15 + (width - 0.3) * (i + 1) / seats", 0.05], ["0.15 + (width - 0.3) * (i + 1) / seats", "depth - 0.2"]]}}
 ]
}
```

`cooker.kimobj` (nested loops → one repeat; local variables inlined)
```json
{
 "format": "kimbim-object/1", "id": "cooker", "name": {"en": "Cooktop and oven", "es": "Cocina y horno"}, "category": "kitchen",
 "ifc": {"IFC4": ["IfcElectricApplianceType", "ELECTRICCOOKER", null]},
 "params": [
  {"key": "width", "kind": "length", "label": {"en": "Width", "es": "Ancho"}, "default": 0.6},
  {"key": "depth", "kind": "length", "label": {"en": "Depth", "es": "Fondo"}, "default": 0.6},
  {"key": "height", "kind": "length", "label": {"en": "Height", "es": "Altura"}, "default": 0.9},
  {"key": "burners", "kind": "count", "label": {"en": "Burners", "es": "Fuegos"}, "default": 4, "min": 1, "max": 6}
 ],
 "materials": {"body": {"label": "Material", "default": "Timber - finish"}},
 "parts": [
  {"id": "body", "box": {"y": 0.02, "dx": "width", "dy": "depth - 0.02", "dz": "height - 0.01"}},
  {"id": "hob", "box": {"x": 0.03, "y": 0.05, "z": "height - 0.01", "dx": "width - 0.06", "dy": "depth - 0.1", "dz": 0.01}}
 ],
 "symbol": [
  {"rect": {"x": 0, "y": 0, "dx": "width", "dy": "depth"}},
  {"rect": {"x": 0.03, "y": 0.05, "dx": "width - 0.06", "dy": "depth - 0.1"}},
  {"repeat": {"count": "burners"},
   "circle": {"cx": "0.06 + (width - 0.12) * ((i % if(burners == 1, 1, 2)) + 0.5) / if(burners == 1, 1, 2)",
              "cy": "0.08 + (depth - 0.16) * (floor(i / if(burners == 1, 1, 2)) + 0.5) / max(1, ceil(burners / if(burners == 1, 1, 2)))",
              "r": "min((width - 0.12) / (2 * if(burners == 1, 1, 2)), (depth - 0.16) / (2 * max(1, ceil(burners / if(burners == 1, 1, 2))))) * 0.75"}}
 ]
}
```

`car.kimobj` (upright profiles with `axes`)
```json
{
 "format": "kimbim-object/1", "id": "car", "name": {"en": "Car", "es": "Coche"}, "category": "site",
 "ifc": {"IFC4": ["IfcBuildingElementProxyType", "USERDEFINED", "CAR"], "IFC2X3": ["IfcBuildingElementProxyType", "USERDEFINED", "CAR"]},
 "params": [
  {"key": "width", "kind": "length", "label": {"en": "Width", "es": "Ancho"}, "default": 1.8},
  {"key": "depth", "kind": "length", "label": {"en": "Depth", "es": "Fondo"}, "default": 4.5},
  {"key": "height", "kind": "length", "label": {"en": "Height", "es": "Altura"}, "default": 1.5}
 ],
 "parts": [
  {"id": "wheel", "repeat": {"count": 4}, "axes": ["y", "z", "x"],
   "cylinder": {"cx": "if(i < 2, depth * 0.18, depth * 0.78)", "cy": 0.32, "z": "if(i % 2 == 0, 0.05, width - 0.25)", "r": 0.32, "h": 0.2}},
  {"id": "body", "box": {"z": 0.25, "dx": "width", "dy": "depth", "dz": "max(height * 0.55 - 0.25, 0.1)"}},
  {"id": "cabin", "axes": ["y", "z", "x"],
   "prism": {"points": [["depth * 0.3", "height * 0.55"], ["depth * 0.85", "height * 0.55"], ["depth * 0.75", "height"], ["depth * 0.42", "height"]],
             "z": 0.1, "h": "width - 0.2"}}
 ],
 "symbol": [
  {"line": {"points": [{"rounded_rect": [0, 0, "width", "depth", 0.3], "n": 3}], "closed": true}},
  {"line": {"points": [[0.1, "depth * 0.3"], ["width - 0.1", "depth * 0.3"]]}},
  {"line": {"points": [[0.1, "depth * 0.42"], ["width - 0.1", "depth * 0.42"]]}},
  {"line": {"points": [[0.1, "depth * 0.75"], ["width - 0.1", "depth * 0.75"]]}},
  {"line": {"points": [[0.1, "depth * 0.85"], ["width - 0.1", "depth * 0.85"]]}}
 ]
}
```

`tree.kimobj` (trig in degrees)
```json
{
 "format": "kimbim-object/1", "id": "tree", "name": {"en": "Tree", "es": "Árbol"}, "category": "site",
 "ifc": {"IFC4": ["IfcGeographicElementType", "USERDEFINED", "TREE"], "IFC2X3": ["IfcBuildingElementProxyType", "USERDEFINED", "TREE"]},
 "params": [
  {"key": "width", "kind": "length", "label": {"en": "Crown diameter", "es": "Diámetro de copa"}, "default": 4.0},
  {"key": "height", "kind": "length", "label": {"en": "Height", "es": "Altura"}, "default": 6.0},
  {"key": "trunk", "kind": "length", "label": {"en": "Trunk diameter", "es": "Diámetro del tronco"}, "default": 0.3}
 ],
 "parts": [
  {"id": "trunk_post", "cylinder": {"cx": "width / 2", "cy": "width / 2", "r": "trunk / 2", "h": "height * 0.45"}},
  {"id": "crown1", "prism": {"points": [{"ellipse": ["width / 2", "width / 2", "width / 2 * 0.8", "width / 2 * 0.8"], "n": 10}], "z": "height * 0.3", "h": "height * 0.2"}},
  {"id": "crown2", "prism": {"points": [{"ellipse": ["width / 2", "width / 2", "width / 2", "width / 2"], "n": 10}], "z": "height * 0.5", "h": "height * 0.2"}},
  {"id": "crown3", "prism": {"points": [{"ellipse": ["width / 2", "width / 2", "width / 2 * 0.75", "width / 2 * 0.75"], "n": 10}], "z": "height * 0.7", "h": "height * 0.2"}},
  {"id": "crown4", "prism": {"points": [{"ellipse": ["width / 2", "width / 2", "width / 2 * 0.4", "width / 2 * 0.4"], "n": 10}], "z": "height * 0.85", "h": "height * 0.15"}}
 ],
 "symbol": [
  {"circle": {"cx": "width / 2", "cy": "width / 2", "r": "width / 2"}},
  {"circle": {"cx": "width / 2", "cy": "width / 2", "r": "trunk / 2"}},
  {"repeat": {"count": 8},
   "line": {"points": [["width / 2 + trunk / 2 * cos(45 * i)", "width / 2 + trunk / 2 * sin(45 * i)"],
                       ["width / 2 + width / 2 * 0.7 * cos(45 * i)", "width / 2 + width / 2 * 0.7 * sin(45 * i)"]]}}
 ]
}
```

Watch for: the bed's `pillows` is fixed per object (`_bed(1)`, `_bed(2)`) — write the number into each file's formulas; the wardrobe's hangers are `"repeat": {"count": "floor(width / 0.15) - 1"}` at `x = (i + 1) * 0.15`; the sink unit's cabinet count `max(1, round(width / 0.6))`; `_cabinets`' door joints `count: "units - 1"` at `x = width * (i + 1) / units`.

- [ ] **Step 4: Run until every case passes**

Run: `pixi run pytest tests/python/test_object_port.py -q`
Expected: 63 + 1 PASS. A failure prints which metric differs for which object and value set; fix that file.

- [ ] **Step 5: Commit**

```bash
git add python/kimbim/bundled_objects tests/python/test_object_port.py
git commit -m "feat(library): the 21 bundled objects as .kimobj, proven against the Python ones (D99)"
```

---

### Task 6: Switch the library to definitions; remove the Python path

**Files:**
- Modify: `python/kimbim/library.py` (most of it)
- Modify: `python/kimbim/app_bridge.py:857-873` (Parameters group per kind), `:1296-1304` (exports)
- Modify: `python/kimbim/configure.py:822,881` (`obj.key` stays valid; no change needed unless tests show otherwise)
- Delete: `tools/library_golden.py`
- Test: `tests/python/test_library.py` (modify the office test, add new tests)

**Interfaces:**
- Consumes: `objects.ObjectDef`, `objects.load_file`, `objects.from_text`, `objbuild.ObjectError`, `Shape` solids/curves (Task 4).
- Produces:
  - `library.OBJECTS: dict[ref, ObjectDef]` (bundled, loaded from `bundled_objects/` at import); `library.get(ref)` → `ObjectDef` or an office IFC type entry dict, or None
  - `library.load_office(folder="", files=())` reads `.kimobj` and `.ifc`; errors in `_office_errors` as `{"file", "error"}`
  - `KIMBIM_LibraryObject` on each type: `Object` (ref), `Parameters` (JSON), `Library`, `DefinitionHash`, `Definition`
  - `library.definition_of_type(t) -> ObjectDef | None` (from the type's `Definition`, `source="project"`, `ref` from `Object`)
  - `library._object_of(e) -> (ObjectDef, values, type) | None` (from the type's own definition)
  - `library.parameters_of(elements) -> list[list[dict]] | None per element` — each dict `{"label", "value", "kind", "choices"?}` for **visible** parameters (choice values as their English label)
  - bridge `object_form(key, params_json) -> {"params": [listing...], "visible": [keys]}`
  - `listing` per parameter: `{"key", "label", "label_es", "value", "kind", "min", "max", "group", "options": [{"id", "label", "label_es"}]?, "choices"?}`; per object `name_es`

- [ ] **Step 1: Write the failing tests** (append to `tests/python/test_library.py`; replace `test_office_library_python_and_ifc_types`)

```python
STOOL = {
    "format": "kimbim-object/1", "id": "stool", "name": {"en": "Stool", "es": "Taburete"}, "category": "furniture",
    "ifc": {"IFC4": ["IfcFurnitureType", "CHAIR", None]},
    "params": [{"key": "width", "kind": "length", "label": "Width", "default": 0.35},
               {"key": "height", "kind": "length", "label": "Height", "default": 0.6},
               {"key": "legs", "kind": "count", "label": "Legs", "default": 3, "min": 3, "max": 6},
               {"key": "foot", "kind": "choice", "label": "Foot", "default": "round",
                "options": [{"id": "round", "label": "Round"}, {"id": "square", "label": "Square"}]},
               {"key": "ring", "kind": "bool", "label": "Foot ring", "default": False},
               {"key": "splay", "kind": "angle", "label": "Splay", "default": 0, "max": 15}],
    "parts": [
        {"id": "seat", "cylinder": {"cx": "width / 2", "cy": "width / 2", "z": "height - 0.03", "r": "width / 2", "h": 0.03},
         "anchors": {"ring": {"pattern": "circle", "cx": "width / 2", "cy": "width / 2", "r": "width / 2 - 0.04",
                              "z": "height - 0.03", "dir": "down"}}},
        {"id": "leg", "repeat": {"on": "seat.anchors.ring", "count": "legs"},
         "rotate": {"axis": "away_from_centre", "angle": "splay"}, "use": "leg_{foot}", "with": {"h": "height - 0.03"}},
        {"id": "hoop", "when": "ring", "sweep": {"r": 0.008, "path": [
            ["width / 2 + 0.12", "width / 2", 0.2], ["width / 2", "width / 2 + 0.12", 0.2], ["width / 2 - 0.12", "width / 2", 0.2],
            ["width / 2", "width / 2 - 0.12", 0.2], ["width / 2 + 0.12", "width / 2", 0.2]]}}],
    "components": {
        "leg_round": {"params": [{"key": "h", "kind": "length", "label": "H", "default": 0.5}],
                      "parts": [{"id": "p", "cone": {"r1": 0.015, "r2": 0.011, "h": "h"}}]},
        "leg_square": {"params": [{"key": "h", "kind": "length", "label": "H", "default": 0.5}],
                       "parts": [{"id": "p", "box": {"x": -0.015, "y": -0.015, "dx": 0.03, "dy": 0.03, "dz": "h", "taper": 0.7}}]}},
}


def write_office(folder, data=STOOL, name="stool.kimobj"):
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(json.dumps(data), encoding="utf-8")


def test_office_library_kimobj_and_ifc_types(project, tmp_path):
    folder = tmp_path / "office"
    write_office(folder)
    (folder / "old.py").write_text("raise SystemExit('must never run')\n", encoding="utf-8")
    r = call("set_library_paths", json.dumps({"folder": str(folder)}))
    assert r["ok"] and r["errors"] == []
    listed = {o["id"]: o for o in call("library_objects")["objects"]}
    assert "office:stool" in listed and listed["office:stool"]["category"] == "office"
    assert listed["office:stool"]["name_es"] == "Taburete"
    assert not any("old" in key for key in listed)  # .py files are not read
    assert call("place_object", project, "office:stool", "", 0, 0, 0)["ok"]


def test_types_carry_their_definition(project):
    r = call("place_object", project, "chair", "", 0, 0, 0)
    t = b._model.by_guid(r["type"])
    ps = ifcopenshell.util.element.get_pset(t, library.PSET)
    assert ps["Object"] == "chair" and ps["DefinitionHash"] == library.OBJECTS["chair"].hash
    assert json.loads(ps["Definition"])["id"] == "chair"


def test_project_objects_edit_without_the_library(project, tmp_path):
    folder = tmp_path / "office"
    write_office(folder)
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    guid = call("place_object", project, "office:stool", "", 0, 0, 0)["guid"]
    path = tmp_path / "with_stool.ifc"
    b.save(str(path))
    library.load_office()  # the consultant has no office library
    assert call("open_model", str(path))["ok"]
    r = call("set_object_parameter", json.dumps([guid]), "Legs", "5", "")
    assert r["ok"], r
    t = ifcopenshell.util.element.get_type(b._model.by_guid(guid))
    assert json.loads(ifcopenshell.util.element.get_pset(t, library.PSET)["Parameters"])["legs"] == 5
    assert "Legs 5" in t.Name


def test_new_kinds_in_properties(project, tmp_path):
    folder = tmp_path / "office"
    write_office(folder)
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    guid = call("place_object", project, "office:stool", "", 0, 0, 0)["guid"]
    group = call("properties_multi", json.dumps([guid]))["psets"]["Parameters"]
    assert group["Foot"]["choices"] == ["Round", "Square"] and group["Foot"]["value"] == "Round"
    assert group["Foot ring"]["ifc_type"] == "IfcBoolean" and group["Foot ring"]["value"] is False
    assert group["Splay"]["ifc_type"] == "IfcPlaneAngleMeasure"
    for name, value in (("Foot", "Square"), ("Foot ring", "true"), ("Splay", "8")):
        assert call("set_object_parameter", json.dumps([guid]), name, value, "")["ok"]
    t = ifcopenshell.util.element.get_type(b._model.by_guid(guid))
    values = json.loads(ifcopenshell.util.element.get_pset(t, library.PSET)["Parameters"])
    assert values["foot"] == "square" and values["ring"] is True and values["splay"] == 8


def test_bad_value_keeps_the_old_type(project, tmp_path):
    data = json.loads(json.dumps(STOOL))
    data["parts"][0]["cylinder"]["h"] = "sqrt(height - 0.5) * 0.1"  # breaks below 0.5 m
    folder = tmp_path / "office"
    write_office(folder, data)
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    r = call("place_object", project, "office:stool", "", 0, 0, 0)
    before = ifcopenshell.util.element.get_type(b._model.by_guid(r["guid"])).GlobalId
    bad = call("set_object_parameter", json.dumps([r["guid"]]), "Height", "0.3", "")
    assert not bad["ok"] and "parts.seat" in bad["error"]
    assert ifcopenshell.util.element.get_type(b._model.by_guid(r["guid"])).GlobalId == before


def test_broken_office_files_are_listed_not_loaded(tmp_path):
    folder = tmp_path / "office"
    write_office(folder)
    (folder / "big.kimobj").write_text(json.dumps({**STOOL, "id": "big", "parts": [
        {"id": "b", "repeat": {"count": 1e9}, "box": {"dx": 1, "dy": 1, "dz": 1}}]}), encoding="utf-8")
    (folder / "cycle.kimobj").write_text(json.dumps({**STOOL, "id": "cyc", "parts": [{"id": "a", "use": "x"}],
                                                     "components": {"x": {"parts": [{"id": "b", "use": "x"}]}}}), encoding="utf-8")
    (folder / "junk.kimobj").write_text("{", encoding="utf-8")
    r = call("set_library_paths", json.dumps({"folder": str(folder)}))
    assert sorted(pathlib.Path(e["file"]).name for e in r["errors"]) == ["big.kimobj", "cycle.kimobj", "junk.kimobj"]
    assert r["objects"] == 1
    library.load_office()


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_every_shape_kind_is_valid_ifc(tmp_path, schema):
    from kimbim import testing

    f = testing.build_model(schema, walls=1)
    storey = f.by_type("IfcBuildingStorey")[0].GlobalId
    model = tmp_path / f"base-{schema}.ifc"
    f.write(str(model))
    assert call("open_model", str(model))["ok"]
    folder = tmp_path / "office"
    write_office(folder)
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    for given in ({}, {"foot": "square", "ring": True, "splay": 10}):
        r = call("place_object", storey, "office:stool", json.dumps(given), 0, 0, 0)
        assert r["ok"], r
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        shape = ifcopenshell.geom.create_shape(settings, b._model.by_guid(r["guid"]))
        zs = shape.geometry.verts[2::3]
        assert len(shape.geometry.faces) > 0
        assert max(zs) - min(zs) == pytest.approx(0.6, abs=0.01)  # a cone on its side would not be 0.6 m tall
    path = tmp_path / f"shapes-{schema}.ifc"
    b.save(str(path))
    assert validate(ifcopenshell.open(str(path))) == []
    library.load_office()
```

Add `import pathlib` at the top of the file. `create_shape` returns vertices in metres (ifcopenshell converts from the file's unit by default).

- [ ] **Step 2: Run to verify they fail**

Run: `pixi run pytest tests/python/test_library.py -q`
Expected: the new tests FAIL (`office:stool` not listed, no `DefinitionHash`, ...); the old tests still pass.

- [ ] **Step 3: Rewrite `library.py`'s definition side**

Delete from `library.py`: `Param`, `_material_choices`'s import of `Param`-related code stays (keep `_material_choices`), `Shape`, `ellipse_points`, `rounded_rect`, `Obj`, `DEFAULT_MATERIALS`, `define`, `_shift_point`, `_shift_solid`, `_shift_curve`, `W`, `D`, `H`, `FURNITURE`, `SANITARY`, `APPLIANCE`, `PROXY`, `KITCHEN_FURNITURE`, every `_<object>` builder and every `define(...)` call, `CIRCLE_POINTS`. Update the module docstring: objects are `.kimobj` definitions (D99), the office library is a folder of `.kimobj` files and IFC files.

Add after the constants:

```python
from . import objects
from .objbuild import ObjectError

BUNDLED = pathlib.Path(__file__).with_name("bundled_objects")
OBJECTS: dict = {}  # ref -> objects.ObjectDef (bundled)


def _load_bundled() -> None:
    OBJECTS.clear()
    for path in sorted(BUNDLED.glob("*.kimobj")):
        d = objects.load_file(str(path), "bundled")
        OBJECTS[d.ref] = d


def _resolve(ref: str):
    """`use` of another library object: bundled ids, office refs, or office ids without the prefix."""
    found = OBJECTS.get(ref) or _office.get(ref) or _office.get(f"office:{ref}")
    return found if isinstance(found, objects.ObjectDef) else None
```

and at the end of the module, `_load_bundled()`.

Replace `load_office`:

```python
def load_office(folder: str = "", files=()) -> None:
    """(Re)load the office library: *.kimobj definitions (D99) and *.ifc files' types. A file that does
    not load or build is listed in the errors and left out; the rest load."""
    _office.clear()
    _office_errors.clear()
    _office_paths["folder"], _office_paths["files"] = folder or "", list(files or ())
    paths = []
    if folder and os.path.isdir(folder):
        paths += sorted(str(p) for p in pathlib.Path(folder).iterdir() if p.suffix.lower() in (".kimobj", ".ifc"))
    paths += [p for p in files or () if p not in paths]
    parsed = []
    for path in paths:
        try:
            if path.lower().endswith(".kimobj"):
                d = objects.load_file(path, "office", check=False)
                d.category = "office"
                _office[d.ref] = d
                parsed.append((path, d))
            elif os.path.isfile(path):
                _load_ifc_types(path, "office")
        except Exception as ex:  # a broken file must not break the library
            _office_errors.append({"file": path, "error": f"{type(ex).__name__}: {ex}"})
    for path, d in parsed:  # built once all are known, so office objects may use each other
        try:
            objbuild.check(d)
            objbuild.build(d, d.values(), _resolve)
        except (ObjectError, ValueError) as ex:
            _office.pop(d.ref, None)
            _office_errors.append({"file": path, "error": str(ex)})
```

(import `objbuild` alongside `objects`). Make `ObjectDef.shape` resolve too: change it in `objects.py` to

```python
    resolver = None  # library.py sets objects.ObjectDef.resolver = library._resolve

    def shape(self, values: dict):
        return objbuild.build(self, values, type(self).resolver)
```

and in `library.py` after `_resolve`: `objects.ObjectDef.resolver = staticmethod(_resolve)`.

Replace `_symbol(shape)` uses with `shape.polylines()`; delete `_symbol`. `_listing`:

```python
def _param_listing(obj, values) -> list:
    visible = set(obj.visible(values))
    env = {**values, "pi": math.pi}
    out = []
    for p in obj.params:
        lo, hi = p.bounds(env)
        item = {"key": p.key, "label": p.label["en"], "label_es": p.label["es"], "value": values[p.key],
                "kind": p.kind, "min": lo, "max": hi, "group": p.group, "visible": p.key in visible}
        if p.kind == "choice":
            item["options"] = [{"id": i, "label": label["en"], "label_es": label["es"]} for i, label in p.options]
        if p.kind == "material":
            item["choices"] = _material_choices(p.default)
        out.append(item)
    return out


def _listing(obj) -> dict:
    values = obj.values()
    w, d = footprint(obj, values)
    return {"id": obj.ref, "name": obj.name, "name_es": obj.names["es"], "category": obj.category,
            "ifc_class": obj.ifc["IFC4"][0], "params": _param_listing(obj, values),
            "symbol": obj.shape(values).polylines(), "width": w, "depth": d,
            "height": values.get("height", 1.0), "library": obj.library}
```

`library_objects()`: iterate `OBJECTS.values()` then `_office.items()`; an `ObjectDef` office entry is `_listing(entry)` (its `id` is already `office:<key>`); IFC entries unchanged. Replace `isinstance(x, Obj)` with `isinstance(x, objects.ObjectDef)` everywhere.

New bridge function (export it under `"library"` in `app_bridge._EXPORTS`, alphabetically):

```python
def object_form(key: str, params_json: str = "") -> str:
    """The Library panel's parameter form for these values (D99): kinds, limits, which are shown."""
    from . import app_bridge as B

    obj = get(key)
    if not isinstance(obj, objects.ObjectDef):
        return B._dump({"params": [], "visible": []})
    try:
        given = json.loads(params_json) if params_json else {}
    except ValueError:
        given = {}
    values = obj.values(given)
    return B._dump({"params": _param_listing(obj, values), "visible": obj.visible(values), "values": values})
```

`object_symbol` uses `obj.shape(values).polylines()`. `set_library_paths`' docstring: "IFC or .kimobj files".

- [ ] **Step 4: Rewrite the IFC writer for dict solids**

```python
class _Writer:
    """Writes a Shape as IFC items in the model's length unit (D99 solids: a kind, fields in the solid's
    own frame, and the frame as a 4×4 matrix in object metres)."""

    def __init__(self, f, unit_scale):
        import ifcopenshell.util.unit

        self.f, self.k = f, 1.0 / unit_scale
        self.ifc2x3 = f.schema == "IFC2X3"
        unit = ifcopenshell.util.unit.get_project_unit(f, "PLANEANGLEUNIT")
        self.degrees = unit is not None and unit.is_a("IfcConversionBasedUnit") and (unit.Name or "").upper() == "DEGREE"

    def angle(self, degrees):
        return float(degrees) if self.degrees else math.radians(degrees)

    def p2(self, x, y):
        return self.f.createIfcCartesianPoint((float(x) * self.k, float(y) * self.k))

    def p3(self, x, y, z):
        return self.f.createIfcCartesianPoint((float(x) * self.k, float(y) * self.k, float(z) * self.k))

    def d3(self, v):
        return self.f.createIfcDirection(tuple(float(c) for c in v))

    def a2(self, x=0.0, y=0.0):
        return self.f.createIfcAxis2Placement2D(self.p2(x, y), None)

    def placement(self, m):
        m = np.asarray(m)
        return self.f.createIfcAxis2Placement3D(self.p3(*m[:3, 3]), self.d3(m[:3, 2]), self.d3(m[:3, 0]))

    def polyline2(self, pts):
        return self.f.createIfcPolyline([self.p2(x, y) for x, y in pts])

    def closed(self, pts):
        return self.f.createIfcArbitraryClosedProfileDef("AREA", None, self.polyline2(list(pts) + [pts[0]]))

    def extrude(self, profile, m, depth):
        return self.f.createIfcExtrudedAreaSolid(profile, self.placement(m), self.d3((0, 0, 1)), float(depth) * self.k)

    def solids(self, s) -> list:
        f, kind, m = self.f, s["kind"], np.asarray(s["matrix"])
        up = lambda z: m @ _translate(0, 0, z)  # noqa: E731
        if kind == "box":
            t = s["taper"] if not self.ifc2x3 else 1.0
            scale = 1.0 if not self.ifc2x3 else (1 + s["taper"]) / 2  # IFC2X3: untapered at the mean size
            cx, cy = s["x"] + s["dx"] / 2, s["y"] + s["dy"] / 2
            profile = f.createIfcRectangleProfileDef("AREA", None, self.a2(cx, cy), s["dx"] * scale * self.k, s["dy"] * scale * self.k)
            if t < 1 - 1e-9:
                end = f.createIfcRectangleProfileDef("AREA", None, self.a2(cx, cy), s["dx"] * t * self.k, s["dy"] * t * self.k)
                return [f.createIfcExtrudedAreaSolidTapered(profile, self.placement(up(s["z"])), self.d3((0, 0, 1)),
                                                            s["dz"] * self.k, end)]
            return [self.extrude(profile, up(s["z"]), s["dz"])]
        if kind == "cylinder":
            profile = f.createIfcCircleProfileDef("AREA", None, self.a2(s["cx"], s["cy"]), s["r"] * self.k)
            return [self.extrude(profile, up(s["z"]), s["h"])]
        if kind == "prism":
            return [self.extrude(self.closed(s["points"]), up(s["z"]), s["h"])]
        if kind in ("cone", "revolve"):
            if kind == "cone":
                profile_pts = [(0, 0), (s["r1"], 0), (s["r2"], s["h"]), (0, s["h"])]
                base, angle = m @ _translate(s["cx"], s["cy"], s["z"]), 360.0
            else:
                profile_pts, base, angle = s["profile"], m, s["angle"]
            # The profile lies in the frame's x-z plane and turns about the frame's z axis: the placement's
            # x is the frame's x, its z is -y (so its y, z × x, is the frame's z), and the revolve axis is
            # the placement's y.
            plane = base.copy()
            plane[:3, 0], plane[:3, 1], plane[:3, 2] = base[:3, 0], base[:3, 2], -base[:3, 1]
            axis = f.createIfcAxis1Placement(self.p3(0, 0, 0), self.d3((0, 1, 0)))
            return [f.createIfcRevolvedAreaSolid(self.closed(profile_pts), self.placement(plane), axis, self.angle(angle))]
        # sweep
        path = [tuple((m @ [x, y, z, 1])[:3]) for x, y, z in s["path"]]
        if s.get("r") is not None:
            directrix = f.createIfcPolyline([self.p3(*p) for p in path])
            return [f.createIfcSweptDiskSolid(directrix, s["r"] * self.k, None, None, None)]
        out = []
        for p, q in zip(s["path"], s["path"][1:]):
            seg, length = objbuild._segment_frame(p, q)
            out.append(self.extrude(self.closed(s["profile"]), m @ seg, length))
        return out

    def curve(self, c):
        if c[0] == "poly":
            return self.polyline2(c[1])
        _, cx, cy, r = c
        return self.f.createIfcCircle(self.a2(cx, cy), r * self.k)
```

`test_every_shape_kind_is_valid_ifc` checks the stool's meshed height, which catches a revolve placed in the wrong plane (a cone lying on its side).

`_representations`:

```python
def _representations(obj, values: dict):
    """(body, plan) IfcShapeRepresentations for the object with these values."""
    import ifcopenshell.util.unit

    from . import app_bridge as B

    f = B._model
    shape = obj.shape(values)
    writer = _Writer(f, ifcopenshell.util.unit.calculate_unit_scale(f))
    body_context, plan_context = _contexts()
    items, parts = [], []
    for s in shape.solids:
        for item in writer.solids(s):
            items.append(item)
            parts.append(s["part"])
    advanced = any(i.is_a("IfcSweptDiskSolid") or i.is_a("IfcExtrudedAreaSolidTapered") for i in items)
    body = f.createIfcShapeRepresentation(body_context, "Body", "AdvancedSweptSolid" if advanced else "SweptSolid", items)
    _style_parts(f, obj, values, items, parts)
    plan = None
    if shape.curves:
        curve_set = f.createIfcGeometricCurveSet([writer.curve(c) for c in shape.curves])
        plan = f.createIfcShapeRepresentation(plan_context, "Annotation", "Annotation2D", [curve_set])
    return body, plan
```

Import `numpy as np` at module level is fine (numpy is a runtime dependency) and `from .objbuild import _translate`.

- [ ] **Step 5: Definitions on types, the project's definition first**

```python
def _write_pset(t, obj, values) -> None:
    import ifcopenshell.api.pset

    from . import app_bridge as B

    f = B._model
    ps = next((p for p in (t.HasPropertySets or ()) if p.Name == PSET), None) or \
        ifcopenshell.api.pset.add_pset(f, product=t, name=PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={
        "Object": obj.ref, "Parameters": json.dumps(values, sort_keys=True), "Library": obj.library or obj.source,
        "DefinitionHash": obj.hash, "Definition": obj.text})


def definition_of_type(t):
    """The definition a library type was made from (D99): the text stored on it, so a project opens and
    edits without the library that made it."""
    import ifcopenshell.util.element

    data = ifcopenshell.util.element.get_pset(t, PSET) if t is not None else None
    if not data or not data.get("Definition"):
        return None
    try:
        return objects.from_text(data["Definition"], "project", data.get("Library") or "", data.get("Object") or "")
    except (ObjectError, ValueError):
        return None
```

and in `objects.py` give `from_text` the ref, part of the cache key (two refs with the same text must stay two definitions):

```python
@functools.lru_cache(maxsize=512)
def _from_text(text: str, source: str, library: str, ref: str) -> ObjectDef:
    d = ObjectDef(json.loads(text), source, library, check=False)
    if ref:
        d.ref = ref
    return d


def from_text(text: str, source: str, library: str = "", ref: str = "") -> ObjectDef:
    """A definition stored in a model (its type's Definition): parsed once per text and ref."""
    return _from_text(text, source, library, ref)
```

`_params_of_type` keeps returning `(ref, values)`. `_find_type(f, ref, values, digest)` matches `info[0] == ref and info[1] == values` **and** the pset's `DefinitionHash == digest`. `_make_type(obj, values)` calls `_write_pset(t, obj, values)`. `_type_for(obj, values)` passes `obj.hash`. `_regenerate_type(t, obj, values)` calls `_write_pset(t, obj, values)`. `_remove_type_if_unused` unchanged. `_ifc_type(entry)` writes its pset directly (no definition): keep its existing `edit_pset` call inline instead of `_write_pset`.

```python
def _object_of(e):
    """(definition, values, type) of a placed library object, or None. The type's own definition (D99)."""
    import ifcopenshell.util.element

    t = ifcopenshell.util.element.get_type(e)
    obj = definition_of_type(t)
    info = _params_of_type(t)
    if obj is None or info is None:
        return None
    return obj, obj.values(info[1]), t
```

`place_object(storey, key, ...)`: `obj = get(key)`; `isinstance(obj, objects.ObjectDef)`; everything else unchanged.

`set_object_parameter`: per kind —

```python
        if p.kind == "material":
            ...  # unchanged (D97)
        elif p.kind in ("choice", "bool"):
            v = value
        else:
            try:
                v = float(str(value).strip().replace(",", "."))
            except ValueError:
                return A._fail(f"not a number: {value}")
            if p.kind == "length" and v <= 0:
                return A._fail(f"{p.label['en']} must be more than 0")
        new_values = dict(values)
        new_values[p.key] = v
        try:
            new_values = obj.values(new_values)
            obj.shape(new_values)  # a formula that breaks at these values fails the edit (Review Focus 1)
        except (ObjectError, ValueError) as ex:
            return A._fail(str(ex))
```

(`obj.values()` re-cleans every value, so limits that are formulas follow the new value.)

`parameters_of`:

```python
def parameters_of(elements) -> list:
    """The Properties panel's Parameters group per element: the visible parameters as
    {"label", "value", "kind", "choices"?} (a choice shows its option's label), or None."""
    out = []
    for e in elements:
        found = _object_of(e)
        if found is None:
            out.append(None)
            continue
        obj, values, _ = found
        visible = set(obj.visible(values))
        rows = []
        for p in obj.params:
            if p.key not in visible:
                continue
            row = {"label": p.label["en"], "value": values[p.key], "kind": p.kind}
            if p.kind == "choice":
                row["value"] = p.option_label(values[p.key])
                row["choices"] = [label["en"] for _, label in p.options]
            rows.append(row)
        out.append(rows)
    return out
```

- [ ] **Step 6: Parameters group in `app_bridge.properties_multi`** (`app_bridge.py:857-873`)

```python
    per_params = library.parameters_of(elements)
    if all(p is not None for p in per_params):
        group = {}
        ifc_types = {"length": "IfcLengthMeasure", "angle": "IfcPlaneAngleMeasure", "count": "IfcInteger",
                     "bool": "IfcBoolean", "choice": "IfcLabel", "material": "IfcLabel"}
        for row in per_params[0]:
            label = row["label"]
            present = [next((r["value"] for r in rows if r["label"] == label), _MISSING) for rows in per_params]
            varies = any(v is _MISSING or v != present[0] for v in present)
            group[label] = {"value": None if varies else present[0], "varies": varies,
                            "ifc_type": ifc_types[row["kind"]], "editable": True, "source": "dimension", "type_value": None}
            if row["kind"] == "material":  # D97: a part's building material, picked from a list
                group[label]["choices"] = library._material_choices(present[0] if isinstance(present[0], str) else "")
            elif row["kind"] == "choice":
                group[label]["choices"] = row["choices"]
        ...  # the rest unchanged
```

- [ ] **Step 7: Delete the one-off tool and run everything touched**

```bash
git rm tools/library_golden.py
```

Run: `pixi run pytest tests/python/test_library.py tests/python/test_object_port.py tests/python/test_objbuild.py tests/python/test_objects.py tests/python/test_configure.py tests/python/test_imports.py -q`
Expected: all PASS. Then `rg -n "define\(|\.build\b|Obj\b|Param\(" python/kimbim` — expected: no matches outside comments.

- [ ] **Step 8: Run the whole Python suite**

Run: `pixi run test-py`
Expected: all PASS (≈ 703 + new). Fix any caller of the deleted names (grep showed only `app_bridge.py` and `configure.py`).

- [ ] **Step 9: Commit**

```bash
git add -A python/kimbim tests/python tools
git commit -m "feat(library): objects from .kimobj definitions stored on their types; Python objects removed (D99)"
```

---

### Task 7: Update from library

**Files:**
- Modify: `python/kimbim/library.py` (two bridge functions), `python/kimbim/app_bridge.py` (`library_update` in `properties_multi`, exports)
- Modify: `app/src/PropertiesPanel.h/.cpp` (an Update row), `app/src/MainWindow.h/.cpp` (connect it; Model › Update library objects)
- Test: `tests/python/test_library.py`, `app/tests/test_properties_panel.cpp`

**Interfaces:**
- Consumes: `definition_of_type`, `_type_for`, `_remove_type_if_unused`, `get`.
- Produces:
  - bridge `library_updates(guids_json) -> {"ok", "outdated": int}` — `""` or `"[]"` means every library object in the model
  - bridge `update_from_library(guids_json) -> {"ok", "changed", "geometry": {...}}` — one undo step; parameter values whose key and kind still exist are kept
  - `properties_multi` payload key `"library_update": int` (outdated among the selection; absent when 0)
  - `PropertiesPanel::updateFromLibraryRequested()` signal; push button object name `libraryUpdate`
  - `QAction` object name `actionUpdateLibraryObjects` in the Model menu

- [ ] **Step 1: Write the failing Python test**

```python
def test_update_from_library_keeps_values_and_is_one_undo_step(project, tmp_path):
    folder = tmp_path / "office"
    write_office(folder)
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    guid = call("place_object", project, "office:stool", json.dumps({"legs": 5}), 0, 0, 0)["guid"]
    assert call("library_updates", json.dumps([guid]))["outdated"] == 0
    changed = json.loads(json.dumps(STOOL))
    changed["params"][1]["default"] = 0.75  # the office edits its stool
    changed["params"].append({"key": "glides", "kind": "bool", "label": "Glides", "default": True})
    write_office(folder, changed)
    call("set_library_paths", json.dumps({"folder": str(folder)}))
    assert call("library_updates", json.dumps([guid]))["outdated"] == 1
    assert call("properties_multi", json.dumps([guid]))["library_update"] == 1
    r = call("update_from_library", json.dumps([guid]))
    assert r["ok"], r
    t = ifcopenshell.util.element.get_type(b._model.by_guid(guid))
    ps = ifcopenshell.util.element.get_pset(t, library.PSET)
    values = json.loads(ps["Parameters"])
    assert values["legs"] == 5 and values["height"] == pytest.approx(0.6) and values["glides"] is True
    assert ps["DefinitionHash"] == library.get("office:stool").hash
    assert call("library_updates", "")["outdated"] == 0
    assert call("undo")["ok"]
    assert call("library_updates", "")["outdated"] == 1
    library.load_office()
```

(`height` keeps the placed value 0.6 — it was the default then and is a stored value now.) Check `call("undo")` against how other tests in this file undo (`test_one_placement_is_one_undo_step`) and use the same call.

- [ ] **Step 2: Run to verify it fails**

Run: `pixi run pytest tests/python/test_library.py -k update_from_library -q`
Expected: FAIL (`AttributeError: module 'kimbim.app_bridge' has no attribute 'library_updates'`).

- [ ] **Step 3: Implement**

```python
def _outdated(elements) -> list:
    """[(element, project definition, values, type, library definition)] whose library has another version."""
    out = []
    for e in elements:
        found = _object_of(e)
        if found is None:
            continue
        obj, values, t = found
        current = get(obj.ref)
        if isinstance(current, objects.ObjectDef) and current.hash != obj.hash:
            out.append((e, obj, values, t, current))
    return out


def _targets(guids_json: str):
    from . import app_bridge as B

    if guids_json in ("", "[]"):
        return [e for e in B._model.by_type("IfcElement") if _object_of(e) is not None]
    return B._elements(guids_json)


def library_updates(guids_json: str = "") -> str:
    """How many of these placed objects (all, given "") have a newer definition in the library (D99)."""
    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    return B._dump({"ok": True, "outdated": len(_outdated(_targets(guids_json)))})


def update_from_library(guids_json: str = "") -> str:
    """Regenerate these placed objects (all, given "") from the library's definition, keeping every
    parameter value whose key and kind still exist. One undo step."""
    import ifcopenshell.api.type

    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    todo = _outdated(_targets(guids_json))
    if not todo:
        return A._fail("these objects already match the library")
    groups: dict = {}
    for e, obj, values, t, current in todo:
        kinds = {p.key: p.kind for p in current.params}
        kept = {k: v for k, v in values.items() if kinds.get(k) == (obj.param(k).kind if obj.param(k) else None)}
        try:
            new_values = current.values(kept)
            current.shape(new_values)
        except (ObjectError, ValueError) as ex:
            return A._fail(f"{current.name}: {ex}")
        key = (t.id(), json.dumps(new_values, sort_keys=True))
        groups.setdefault(key, (t, current, new_values, []))[3].append(e)

    def action():
        changed = []
        for t, current, new_values, elements in groups.values():
            target = _type_for(current, new_values)
            ifcopenshell.api.type.assign_type(B._model, related_objects=elements, relating_type=target)
            _remove_type_if_unused(t)
            changed += [e.GlobalId for e in elements]
        return len(changed), changed, []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)
```

Export both under `"library"` in `app_bridge._EXPORTS`. In `properties_multi`, right after the Parameters group (before `from . import renovation`):

```python
    outdated = len(library._outdated(elements))  # D99: objects whose library definition changed
```

and turn the final `return _dump({...})` into:

```python
    payload = {
        "count": len(elements),
        "guids": [e.GlobalId for e in elements],
        "types": sorted({e.is_a() for e in elements}),
        "name": {"value": names[0] if same_name else None, "varies": not same_name},
        "status": status,
        "material": _materials.merged(elements),  # D96: the Material row (None: not shown)
        "psets": _with_settings(psets, elements),
    }
    if outdated:
        payload["library_update"] = outdated
    return _dump(payload)
```

- [ ] **Step 4: Run the Python test**

Run: `pixi run pytest tests/python/test_library.py -q`
Expected: all PASS.

- [ ] **Step 5: Write the failing C++ test** (in `app/tests/test_properties_panel.cpp`, a new slot)

```cpp
    void updateFromLibraryButton()
    {
        kimbim::PropertiesPanel panel;
        QSignalSpy spy(&panel, &kimbim::PropertiesPanel::updateFromLibraryRequested);
        QJsonObject merged{{"count", 1}, {"guids", QJsonArray{"g"}}, {"types", QJsonArray{"IfcFurniture"}},
                           {"name", QJsonObject{{"value", "Stool"}, {"varies", false}}},
                           {"psets", QJsonObject{}}, {"library_update", 1}};
        panel.showMulti(merged);
        auto* button = panel.findChild<QPushButton*>(QStringLiteral("libraryUpdate"));
        QVERIFY(button);
        button->click();
        QCOMPARE(spy.count(), 1);
        merged.remove("library_update");
        panel.showMulti(merged);
        QVERIFY(!panel.findChild<QPushButton*>(QStringLiteral("libraryUpdate")));
    }
```

Match the merged object's shape to what the existing slots in this file pass to `showMulti` (copy one and add `library_update`).

- [ ] **Step 6: Implement the row and the menu action**

`PropertiesPanel.h` signals: `void updateFromLibraryRequested(); // D99: the selection's objects have a newer library definition`.

`PropertiesPanel::showMulti`, right after the Name row is built:

```cpp
    // D99: placed objects whose library definition changed since they were placed.
    if (const int outdated = merged.value("library_update").toInt(); outdated > 0) {
        auto* row = new QTreeWidgetItem(element, {tr("Library"), QString()});
        row->setFlags(row->flags() & ~Qt::ItemIsEditable);
        auto* button = new QPushButton(tr("Update from library (%n)", nullptr, outdated), m_tree);
        button->setObjectName(QStringLiteral("libraryUpdate"));
        button->setToolTip(tr("The library has a newer version of this object; values that still exist are kept"));
        connect(button, &QPushButton::clicked, this, &PropertiesPanel::updateFromLibraryRequested);
        m_tree->setItemWidget(row, 1, button);
    }
```

`MainWindow`: connect `m_properties`' `updateFromLibraryRequested` to a new slot `updateFromLibrary(bool all = false)`:

```cpp
void MainWindow::updateFromLibrary(bool all)
{
    const QJsonObject r = bridge("update_from_library", {all ? QString() : jsonList(m_selection)});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not update from the library"), r.value("error").toString());
        return;
    }
    afterEdit(r);
}
```

In the Model menu (near `Flip walls`, `MainWindow.cpp:2235`):

```cpp
    QAction* updateObjects = model->addAction(tr("Update library objects"));
    updateObjects->setObjectName(QStringLiteral("actionUpdateLibraryObjects"));
    updateObjects->setToolTip(tr("Regenerate every placed object whose library definition changed"));
    connect(updateObjects, &QAction::triggered, this, [this] { updateFromLibrary(true); });
```

Add the Spanish strings to `app/translations/kimbim_es.ts` (contexts `PropertiesPanel`, `MainWindow`): "Library" → "Biblioteca", "Update from library (%n)" → "Actualizar desde la biblioteca (%n)", the tooltip → "La biblioteca tiene una versión más nueva de este objeto; se conservan los valores que siguen existiendo", "Could not update from the library" → "No se pudo actualizar desde la biblioteca", "Update library objects" → "Actualizar objetos de biblioteca", its tooltip → "Regenera cada objeto colocado cuya definición en la biblioteca cambió". Use the existing workflow for `.ts` entries (look at a recent commit that added strings, e.g. `git show 3fa19a7 -- app/translations` and follow it).

- [ ] **Step 7: Build and run the C++ tests**

Run: `pixi run app-build` then `ctest --test-dir build/app -R "test_properties_panel|test_library" --output-on-failure` (with `KIMBIM_PYTHON_PATH` set as in `pixi.toml`'s `app-test`; or `pixi run app-test-nogui`)
Expected: PASS. Then `pixi run check-translations`: PASS.

- [ ] **Step 8: Commit**

```bash
git add python/kimbim app/src app/tests app/translations tests/python
git commit -m "feat(library): update placed objects from a newer library definition (D99)"
```

---

### Task 8: The new kinds in the Library panel, bool edits, Spanish labels from files

**Files:**
- Modify: `app/src/LibraryPanel.cpp/.h` (`showParams`, `translated`), `app/src/MainWindow.cpp:1658-1663` (bool to text), `app/src/Translations.cpp/.h` (current language)
- Modify: `app/translations/kimbim_es.ts` (remove the object-name entries that move to the files)
- Test: `app/tests/test_library.cpp`

**Interfaces:**
- Consumes: `library_objects` listing (`name_es`, `label_es`, `options`, `visible`), bridge `object_form(key, params_json)` (Task 6).
- Produces: `QString kimbim::currentLanguage()` (`"en"` or `"es"`, set by `installTranslator`); `LibraryPanel::translated(const QString& english, const QString& spanish = {})`; panel form widgets named `param:<key>`.

- [ ] **Step 1: Write the failing C++ test** (new slot in `app/tests/test_library.cpp`)

```cpp
    void panelShowsNewKindsAndHidesByCondition()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        action(w, "actionObjectLibrary")->trigger();
        kimbim::LibraryPanel* panel = w.libraryPanel();
        QVERIFY(panel->selectObject(QStringLiteral("chair")));
        auto* layout = panel->findChild<QComboBox*>(QStringLiteral("param:layout"));
        QVERIFY(layout);
        QVERIFY(panel->findChild<QWidget*>(QStringLiteral("param:radius"))->isHidden());
        layout->setCurrentIndex(layout->findData(QStringLiteral("circle")));
        QCOMPARE(panel->currentParams().value("layout").toString(), QStringLiteral("circle"));
        QCoreApplication::processEvents(); // the form is rebuilt queued
        QVERIFY(!panel->findChild<QWidget*>(QStringLiteral("param:radius"))->isHidden());
        auto* arms = panel->findChild<QCheckBox*>(QStringLiteral("param:arms"));
        QVERIFY(arms);
        arms->setChecked(true);
        QCOMPARE(panel->currentParams().value("arms").toBool(), true);
        QCoreApplication::processEvents();
        auto* splay = panel->findChild<QDoubleSpinBox*>(QStringLiteral("param:splay"));
        QVERIFY(splay && splay->suffix() == QStringLiteral("°"));
    }

    void boolParameterEditsFromProperties()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.chooseObject(QStringLiteral("chair"), QJsonObject{}));
        const QStringList before = w.viewport()->guids();
        emit w.viewport()->workPointClicked(QPointF(1, 1), 0.01, Qt::NoModifier);
        const QStringList made = added(before, w.viewport()->guids());
        QCOMPARE(made.size(), 1);
        w.setTool(kimbim::MainWindow::Tool::None);
        w.setSelection(made);
        QVERIFY(w.applyPropertyEdit(QStringLiteral("Parameters"), QStringLiteral("Arms"), QJsonValue(true)));
        const QJsonObject props = kimbim::PythonEngine::instance()
            .callJson("properties_multi", {QStringLiteral("[\"%1\"]").arg(made[0])}).object();
        QCOMPARE(props.value("psets").toObject().value("Parameters").toObject().value("Arms").toObject().value("value").toBool(), true);
    }
```

Both slots need the showcase chair (Task 9): write them now, run them in Task 9's Step 4. Add `#include <QCheckBox>`, `#include <QComboBox>` and `#include <QDoubleSpinBox>` to the test file.

- [ ] **Step 2: Fix bool values going to the bridge as empty text** (`MainWindow.cpp:1658-1663`)

```cpp
    auto asText = [](const QJsonValue& v) {
        if (v.isBool())
            return v.toBool() ? QStringLiteral("true") : QStringLiteral("false");
        return v.isDouble() ? QString::number(v.toDouble(), 'g', 17) : v.toString();
    };
    const QJsonObject r = dimension || parameter
        ? bridge(parameter ? "set_object_parameter" : "set_dimension",
              parameter ? QStringList{jsonList(m_selection), prop, asText(value), scope}
                        : QStringList{jsonList(m_selection), prop, asText(value)})
        : bridge("set_property", {jsonList(m_selection), pset, prop, jsonValue(value)});
```

- [ ] **Step 3: The current language**

`Translations.h`: `QString currentLanguage(); // "en" or "es": what installTranslator installed`. `Translations.cpp`:

```cpp
namespace {
QString g_language = QStringLiteral("en");
}

bool installTranslator(QCoreApplication& app, const QString& lang)
{
    if (lang == QLatin1String("en")) {
        g_language = lang;
        return true;
    }
    auto* translator = new QTranslator(&app);
    if (!translator->load(QStringLiteral(":/i18n/kimbim_%1.qm").arg(lang))) {
        delete translator;
        return false;
    }
    app.installTranslator(translator);
    g_language = lang;
    return true;
}

QString currentLanguage() { return g_language; }
```

- [ ] **Step 4: Labels from the files**

`LibraryPanel::translated(english, spanish)`: if `kimbim::currentLanguage() == "es"` and `spanish` is not empty, return `spanish`; otherwise `QCoreApplication::translate("LibraryPanel", english)`. Every call site that shows an object name passes `o.value("name_es").toString()`; parameter labels pass `p.value("label_es")`; option labels `opt.value("label_es")`. Remove the `QT_TRANSLATE_NOOP("LibraryPanel", ...)` list of object names and parameter labels in `LibraryPanel.cpp` (lines ~30–55) — the files carry them now — and delete those entries from `kimbim_es.ts`; keep category names and other UI strings.

- [ ] **Step 5: The form** (`LibraryPanel::showParams`, `LibraryPanel.cpp:279-`)

Fetch the form from the bridge so limits that are formulas and `show_when` are right for the current values:

```cpp
void LibraryPanel::showParams()
{
    while (m_form->rowCount() > 0)
        m_form->removeRow(0);
    const QJsonObject o = m_objects.value(m_current);
    m_title->setText(o.isEmpty() ? QString() : translated(o.value("name").toString(), o.value("name_es").toString()));
    if (o.isEmpty())
        return;
    // D99: limits that are formulas and show_when depend on the current values, so Python makes the form.
    const QJsonObject form = PythonEngine::instance()
        .callJson("object_form", {m_current, QString::fromUtf8(QJsonDocument(m_params).toJson(QJsonDocument::Compact))})
        .object();
    for (const auto& v : form.value("params").toArray()) {
        const QJsonObject p = v.toObject();
        const QString key = p.value("key").toString(), kind = p.value("kind").toString();
        const QJsonValue value = m_params.contains(key) ? m_params.value(key) : p.value("value");
        QWidget* field = nullptr;
        if (kind == QLatin1String("material")) { // D97: a part's building material
            ...  // unchanged
        } else if (kind == QLatin1String("choice")) {
            auto* combo = new QComboBox(m_formHost);
            for (const auto& c : p.value("options").toArray()) {
                const QJsonObject opt = c.toObject();
                combo->addItem(translated(opt.value("label").toString(), opt.value("label_es").toString()), opt.value("id").toString());
            }
            combo->setCurrentIndex(std::max(0, combo->findData(value.toString())));
            connect(combo, &QComboBox::currentIndexChanged, this, [this, combo, key](int i) {
                m_params.insert(key, combo->itemData(i).toString());
                QMetaObject::invokeMethod(this, &LibraryPanel::showParams, Qt::QueuedConnection); // show_when may change
                emit currentChanged();
            });
            field = combo;
        } else if (kind == QLatin1String("bool")) {
            auto* check = new QCheckBox(m_formHost);
            check->setChecked(value.toBool());
            connect(check, &QCheckBox::toggled, this, [this, key](bool on) {
                m_params.insert(key, on);
                QMetaObject::invokeMethod(this, &LibraryPanel::showParams, Qt::QueuedConnection);
                emit currentChanged();
            });
            field = check;
        } else if (kind == QLatin1String("count")) {
            ...  // unchanged, range from p's min/max
        } else {
            auto* spin = new QDoubleSpinBox(m_formHost);
            if (kind == QLatin1String("angle")) {
                spin->setDecimals(1);
                spin->setSingleStep(1.0);
                spin->setSuffix(QStringLiteral("°"));
                spin->setRange(p.value("min").toDouble(-360), p.value("max").toDouble(360));
            } else {
                ...  // the existing length settings
            }
            spin->setValue(value.toDouble());
            ...  // existing valueChanged connection
            field = spin;
        }
        field->setObjectName(QStringLiteral("param:%1").arg(key));
        m_form->addRow(translated(p.value("label").toString(), p.value("label_es").toString()), field);
        m_form->setRowVisible(field, p.value("visible").toBool(true));
    }
}
```

Add `#include "PythonEngine.h"`, `<QCheckBox>` and `<QJsonDocument>` to `LibraryPanel.cpp`; `PythonEngine::instance().callJson(fn, args)` is what the app tests already use to reach the bridge.

- [ ] **Step 6: Build, run, check translations**

Run: `pixi run app-build`, `ctest --test-dir build/app -R test_library --output-on-failure` (after Task 9 for the two new slots), `pixi run check-translations`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/src app/tests app/translations
git commit -m "feat(library): choice, bool and angle parameters in the panel; labels from object files (D99)"
```

---

### Task 9: The showcase chair

**Files:**
- Modify: `python/kimbim/bundled_objects/chair.kimobj`
- Test: `tests/python/test_library.py` (new tests); the port test keeps passing (defaults unchanged)

**Interfaces:**
- Consumes: everything above.
- Produces: the chair's parameters `width, depth, height, seat, seat_shape (square|round), layout (corners|circle), legs (count 1–8, shown on a circle), radius (shown on a circle), leg_style (square|round|tapered|sled), leg_size, splay (angle 0–20, hidden for sled), back (panel|slats|upholstered|none), slats (count, shown for slats), arms (bool), arm_height (shown with arms)`, slots `frame`, `seat`.

At its defaults the chair is exactly today's chair (four square 40 mm legs at the corners, a panel back), so `test_object_port.py`'s three chair cases keep passing.

- [ ] **Step 1: Write the failing tests**

```python
def chair(**given):
    d = library.OBJECTS["chair"]
    return d, d.shape(d.values(given))


def test_chair_defaults_are_the_old_chair():
    d, s = chair()
    assert len(s.solids) == 6  # 4 legs, seat, back
    assert d.visible(d.values()) == [k for k in (p.key for p in d.params) if k not in ("legs", "radius", "slats", "arm_height")]


def test_chair_three_splayed_tapered_legs_on_a_circle():
    d, s = chair(layout="circle", legs=3, splay=8, leg_style="tapered", seat_shape="round")
    legs = [x for x in s.solids if x["part"] == "frame"]
    assert len(legs) == 3 and all(x["kind"] == "cone" for x in legs)
    assert s.metrics()["bbox"][2] == pytest.approx(0, abs=0.01)  # feet on the floor (within the splay's lift)
    feet = [np.array(x["matrix"]) @ [0, 0, x["h"], 1] for x in legs]
    assert all(math.dist(f[:2], (0.225, 0.25)) > 0.2 for f in feet)  # out past the 0.18 m leg circle


def test_chair_backs_and_arms():
    _, slats = chair(back="slats", slats=5)
    _, none = chair(back="none")
    _, arms = chair(arms=True)
    _, sled = chair(leg_style="sled")
    assert len(slats.solids) == 4 + 1 + 2 + 1 + 5  # legs, seat, two posts, top rail, slats
    assert len(none.solids) == 5
    assert len(arms.solids) == 6 + 4
    assert sum(1 for x in sled.solids if x["kind"] == "sweep") == 2


@pytest.mark.parametrize("given", [
    {"layout": "circle", "legs": 3, "splay": 8, "leg_style": "tapered", "seat_shape": "round", "back": "slats"},
    {"leg_style": "sled", "back": "upholstered", "arms": True},
    {"layout": "circle", "legs": 1, "radius": 0.05, "leg_style": "round", "back": "none"},
])
def test_chair_variants_are_valid_ifc(project, tmp_path, given):
    r = call("place_object", project, "chair", json.dumps(given), 0, 0, 0)
    assert r["ok"], r
    path = tmp_path / "chair.ifc"
    b.save(str(path))
    assert validate(ifcopenshell.open(str(path))) == []
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    shape = ifcopenshell.geom.create_shape(settings, b._model.by_guid(r["guid"]))
    zs = shape.geometry.verts[2::3]  # metres
    assert len(shape.geometry.faces) > 0
    top = 0.85 if given.get("back") != "none" else 0.45
    assert max(zs) - min(zs) == pytest.approx(top, rel=0.02)
```

(The level is at 0 in the `project` fixture, so the extent is the chair's height: 0.85 m with a back, the seat's 0.45 m without one.) Add `import math` and `import numpy as np` at the top.

- [ ] **Step 2: Run to verify they fail**

Run: `pixi run pytest tests/python/test_library.py -k chair -q`
Expected: FAIL (unknown parameters are ignored, so counts and kinds differ).

- [ ] **Step 3: Write the showcase chair**

```json
{
 "format": "kimbim-object/1", "id": "chair", "name": {"en": "Chair", "es": "Silla"}, "category": "furniture",
 "ifc": {"IFC4": ["IfcFurnitureType", "CHAIR", null], "IFC2X3": ["IfcFurnitureType", null, "Chair"]},
 "params": [
  {"key": "width", "kind": "length", "label": {"en": "Width", "es": "Ancho"}, "default": 0.45},
  {"key": "depth", "kind": "length", "label": {"en": "Depth", "es": "Fondo"}, "default": 0.5},
  {"key": "height", "kind": "length", "label": {"en": "Height", "es": "Altura"}, "default": 0.85},
  {"key": "seat", "kind": "length", "label": {"en": "Seat height", "es": "Altura del asiento"}, "default": 0.45, "min": 0.2, "max": "height"},
  {"key": "seat_shape", "kind": "choice", "label": {"en": "Seat", "es": "Asiento"}, "default": "square", "group": "Seat",
   "options": [{"id": "square", "label": {"en": "Square", "es": "Cuadrado"}}, {"id": "round", "label": {"en": "Round", "es": "Redondo"}}]},
  {"key": "layout", "kind": "choice", "label": {"en": "Leg layout", "es": "Disposición de las patas"}, "default": "corners", "group": "Legs",
   "options": [{"id": "corners", "label": {"en": "At the corners", "es": "En las esquinas"}},
               {"id": "circle", "label": {"en": "On a circle", "es": "En círculo"}}]},
  {"key": "legs", "kind": "count", "label": {"en": "Legs", "es": "Patas"}, "default": 4, "min": 1, "max": 8, "group": "Legs",
   "show_when": "layout == 'circle'"},
  {"key": "radius", "kind": "length", "label": {"en": "Leg circle radius", "es": "Radio del círculo de patas"}, "default": 0.18,
   "min": 0, "max": "min(width, depth) / 2", "group": "Legs", "show_when": "layout == 'circle'"},
  {"key": "leg_style", "kind": "choice", "label": {"en": "Leg style", "es": "Tipo de patas"}, "default": "square", "group": "Legs",
   "options": [{"id": "square", "label": {"en": "Square", "es": "Cuadradas"}}, {"id": "round", "label": {"en": "Round", "es": "Redondas"}},
               {"id": "tapered", "label": {"en": "Tapered", "es": "Cónicas"}}, {"id": "sled", "label": {"en": "Sled", "es": "Patín"}}]},
  {"key": "leg_size", "kind": "length", "label": {"en": "Leg size", "es": "Grosor de las patas"}, "default": 0.04, "min": 0.01, "max": 0.1, "group": "Legs"},
  {"key": "splay", "kind": "angle", "label": {"en": "Leg splay", "es": "Apertura de las patas"}, "default": 0, "min": 0, "max": 20,
   "group": "Legs", "show_when": "leg_style != 'sled'"},
  {"key": "back", "kind": "choice", "label": {"en": "Back", "es": "Respaldo"}, "default": "panel", "group": "Back",
   "options": [{"id": "panel", "label": {"en": "Panel", "es": "Panel"}}, {"id": "slats", "label": {"en": "Slats", "es": "Listones"}},
               {"id": "upholstered", "label": {"en": "Upholstered", "es": "Tapizado"}}, {"id": "none", "label": {"en": "None", "es": "Ninguno"}}]},
  {"key": "slats", "kind": "count", "label": {"en": "Slats", "es": "Listones"}, "default": 5, "min": 2, "max": 12, "group": "Back",
   "show_when": "back == 'slats'"},
  {"key": "arms", "kind": "bool", "label": {"en": "Arms", "es": "Brazos"}, "default": false, "group": "Arms"},
  {"key": "arm_height", "kind": "length", "label": {"en": "Arm height", "es": "Altura de los brazos"}, "default": 0.22, "min": 0.1, "max": 0.4,
   "group": "Arms", "show_when": "arms"}
 ],
 "materials": {"frame": {"label": {"en": "Frame material", "es": "Material de la estructura"}, "default": "Steel"},
               "seat": {"label": {"en": "Seat material", "es": "Material del asiento"}, "default": "Timber - finish"}},
 "parts": [
  {"id": "base",
   "anchors": {
    "corners": {"pattern": "rect_corners", "x": 0, "y": 0, "dx": "width", "dy": "depth", "inset": "leg_size / 2", "z": "seat - 0.04", "dir": "down"},
    "circle": {"pattern": "circle", "cx": "width / 2", "cy": "depth / 2", "r": "radius", "z": "seat - 0.04", "dir": "down"}}},
  {"id": "leg", "when": "leg_style != 'sled'", "material": "frame",
   "repeat": {"on": "base.anchors.{layout}", "count": "legs"},
   "rotate": {"axis": "away_from_centre", "angle": "splay"},
   "use": "leg_{leg_style}", "with": {"size": "leg_size", "h": "(seat - 0.04) / cos(splay)"}},
  {"id": "sled", "when": "leg_style == 'sled'", "material": "frame", "repeat": {"count": 2, "step": ["width - leg_size", 0, 0]},
   "sweep": {"r": "leg_size / 2", "path": [["leg_size / 2", "leg_size", "seat - 0.04"], ["leg_size / 2", "leg_size", "leg_size / 2"],
                                           ["leg_size / 2", "depth - leg_size", "leg_size / 2"], ["leg_size / 2", "depth - leg_size", "seat - 0.04"]]}},
  {"id": "seat_square", "when": "seat_shape == 'square'", "material": "seat",
   "box": {"z": "seat - 0.04", "dx": "width", "dy": "depth", "dz": 0.04}},
  {"id": "seat_round", "when": "seat_shape == 'round'", "material": "seat",
   "cylinder": {"cx": "width / 2", "cy": "depth / 2", "z": "seat - 0.04", "r": "min(width, depth) / 2", "h": 0.04}},
  {"id": "back_panel", "when": "back == 'panel'", "material": "seat",
   "box": {"y": "depth - 0.04", "z": "seat", "dx": "width", "dy": 0.04, "dz": "max(height - seat, 0.01)"}},
  {"id": "back_upholstered", "when": "back == 'upholstered'", "material": "seat",
   "box": {"y": "depth - 0.08", "z": "seat", "dx": "width", "dy": 0.08, "dz": "max(height - seat, 0.01)"}},
  {"id": "back_post", "when": "back == 'slats'", "material": "frame", "repeat": {"count": 2, "step": ["width - 0.04", 0, 0]},
   "box": {"y": "depth - 0.04", "z": "seat", "dx": 0.04, "dy": 0.04, "dz": "max(height - seat, 0.01)"}},
  {"id": "back_rail", "when": "back == 'slats'", "material": "frame",
   "box": {"x": 0.04, "y": "depth - 0.04", "z": "height - 0.06", "dx": "width - 0.08", "dy": 0.04, "dz": 0.06}},
  {"id": "back_slat", "when": "back == 'slats'", "material": "seat", "repeat": {"count": "slats"},
   "box": {"x": "0.04 + (i + 0.5) * (width - 0.08) / n - 0.015", "y": "depth - 0.035", "z": "seat", "dx": 0.03, "dy": 0.02,
           "dz": "max(height - seat - 0.06, 0.01)"}},
  {"id": "arm_post", "when": "arms", "material": "frame", "repeat": {"count": 2, "step": ["width - 0.04", 0, 0]},
   "box": {"y": 0.05, "z": "seat", "dx": 0.04, "dy": 0.04, "dz": "arm_height - 0.03"}},
  {"id": "arm_rest", "when": "arms", "material": "seat", "repeat": {"count": 2, "step": ["width - 0.05", 0, 0]},
   "box": {"y": 0.03, "z": "seat + arm_height - 0.03", "dx": 0.05, "dy": "depth - 0.07", "dz": 0.03}}
 ],
 "components": {
  "leg_square": {"params": [{"key": "size", "kind": "length", "label": "Size", "default": 0.04},
                            {"key": "h", "kind": "length", "label": "Length", "default": 0.41}],
                 "parts": [{"id": "post", "box": {"x": "-size / 2", "y": "-size / 2", "dx": "size", "dy": "size", "dz": "h"}}]},
  "leg_round": {"params": [{"key": "size", "kind": "length", "label": "Size", "default": 0.04},
                           {"key": "h", "kind": "length", "label": "Length", "default": 0.41}],
                "parts": [{"id": "post", "cylinder": {"r": "size / 2", "h": "h"}}]},
  "leg_tapered": {"params": [{"key": "size", "kind": "length", "label": "Size", "default": 0.04},
                             {"key": "h", "kind": "length", "label": "Length", "default": 0.41}],
                  "parts": [{"id": "post", "cone": {"r1": "size / 2", "r2": "size * 0.3", "h": "h"}}]}
 },
 "symbol": [
  {"when": "seat_shape == 'square'", "rect": {"x": 0, "y": 0, "dx": "width", "dy": "depth"}},
  {"when": "seat_shape == 'round'", "circle": {"cx": "width / 2", "cy": "depth / 2", "r": "min(width, depth) / 2"}},
  {"when": "back == 'panel' or back == 'slats'", "line": {"points": [[0, "depth - 0.04"], ["width", "depth - 0.04"]]}},
  {"when": "back == 'upholstered'", "line": {"points": [[0, "depth - 0.08"], ["width", "depth - 0.08"]]}},
  {"when": "arms", "repeat": {"count": 2},
   "line": {"points": [["i * (width - 0.05)", 0.03], ["i * (width - 0.05)", "depth - 0.04"]]}}
 ]
}
```

Notes:
- At the defaults, `rect_corners` with inset `leg_size / 2` puts each leg's centre 20 mm in from each edge and `leg_square` is a 40 mm post centred on it: exactly the old chair's legs (bbox and volume equal).
- `h = (seat - 0.04) / cos(splay)` keeps splayed feet on the floor; at 0° it is the old height.
- The `count` on the corners pattern is ignored (always four), so `legs` only matters on a circle, which is why it shows only then.
- Labels are unique (Task 3 enforces it: Properties lists parameters by label), so `legs` is "Legs" and `leg_style` is "Leg style". "Seat" the group heading and "Seat" the `seat_shape` label don't clash: groups are not parameters.

- [ ] **Step 4: Run the chair tests, the port test and the C++ library tests**

Run: `pixi run pytest tests/python/test_library.py tests/python/test_object_port.py tests/python/test_objects.py -q`, then `ctest --test-dir build/app -R test_library --output-on-failure`
Expected: all PASS (including Task 8's two C++ slots).

- [ ] **Step 5: Commit**

```bash
git add python/kimbim/bundled_objects/chair.kimobj python/kimbim/objects.py tests/python
git commit -m "feat(library): the customisable chair: legs, layout, splay, styles, backs, arms (D99)"
```

---

### Task 10: Documentation and full verification

**Files:**
- Modify: `docs/16-parametric-objects.md` (status; §5 Update locations), `docs/decisions.md` (D86 note, D99 status), `docs/14-tool-inventory.md` (§8 rows), `docs/15-scripting.md` (if it mentions `define()`), `docs/07-roadmap.md` (Next)

- [ ] **Step 1: Update the docs**

- doc 16: `**Status: Decided (D99, 2026-10-22); part A built.**`; in §5 replace "the Library panel and Properties show *Update from library*" with "Properties shows *Update from library* for the selection, and *Model › Update library objects* updates every placed object"; in "Not now" keep the Object Editor as part B; in §1 add after the `group` bullet: "(Part A stores and lists `group`; the panels show the headings with part B.)"
- decisions.md: D99 status `Decided (owner, 2026-10-22); part A built`; at the end of D86's text add "**Superseded in part by D99**: objects are `.kimobj` definitions; office Python files are no longer read".
- doc 14 §8: "Parametric object authoring" → 🟡 "D99: `.kimobj` definitions (parameters, formulas, parts, anchors, repeats, variants), stored on their types; Object Editor next"; "Bundled library" note → "D86/D99: 21 objects as `.kimobj`; the chair fully customisable".
- `rg -n "define\(" docs` and fix every mention that describes how to add an object (docs/15 especially) to point at doc 16.

- [ ] **Step 2: Full verification**

Run, and paste each result into the task report:

```bash
pixi run check-spdx
pixi run test            # rust + python
pixi run golden
pixi run app-test
pixi run check-translations
pixi run m4
pixi run drawings
```

Expected: every command passes. `golden` must be unchanged (library objects are not in the golden corpus; if a state hash moved, find out why before going on).

- [ ] **Step 3: Commit**

```bash
git add docs
git commit -m "docs: parametric objects part A is built (D99)"
```
