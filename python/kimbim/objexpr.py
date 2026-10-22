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
        except OverflowError:
            raise FormulaError("number too large", pos) from None
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
        try:
            parser = _Parser(text)
            tree = parser.parse()
        except RecursionError:
            raise FormulaError("formula nested too deeply") from None
        self.text, self.tree, self.names = text, tree, frozenset(parser.names)

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
