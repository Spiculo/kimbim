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
    ("(1 + 2", r"expected '\)'"),
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


def test_function_overflow_is_a_formula_error():
    with pytest.raises(FormulaError, match="too large"):
        ev("floor(1e308 * 10)")
    with pytest.raises(FormulaError, match="too large"):
        ev("round(1e308 * 10)")


def test_deep_parse_is_a_formula_error(monkeypatch):
    import inspect
    import sys

    monkeypatch.setattr(sys, "getrecursionlimit", sys.getrecursionlimit)
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(len(inspect.stack(0)) + 60)
    try:
        with pytest.raises(FormulaError, match="nested"):
            compile_formula("not " * 120 + "1")
    finally:
        sys.setrecursionlimit(old)
