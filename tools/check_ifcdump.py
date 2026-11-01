# SPDX-License-Identifier: GPL-3.0-or-later
"""Check the C++ IfcParse bridge against IfcOpenShell.

Stage 1 compared ids, types and attribute counts. Stage 2 compares schema attribute names, aggregate
kinds, parameter type trees and values. The bridge is the C++ side of route 1 (docs/19); matching it
now means the Rust decomposer can consume the same dump before it is written.
"""
from __future__ import annotations

import json
import math
import pathlib
import subprocess
import sys

import ifcopenshell
import ifcopenshell.ifcopenshell_wrapper as W

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
from kimbim import records  # noqa: E402

MODEL = ROOT / "build" / "house.ifc"
EXE = ROOT / "build" / "ifcdump" / ("ifcdump.exe" if sys.platform == "win32" else "ifcdump")

SIMPLE = {
    "binary": "BINARY",
    "boolean": "BOOLEAN",
    "integer": "INTEGER",
    "logical": "LOGICAL",
    "number": "NUMBER",
    "real": "REAL",
    "string": "STRING",
}


def normal(value):
    if isinstance(value, ifcopenshell.entity_instance):
        if value.id():
            return {"ref": value.id()}
        # A typed value (IfcLabel, IfcReal, ...): keep the type name in the canonical form.
        return {"@t": value.is_a(), "v": normal(value.wrappedValue)}
    if isinstance(value, (tuple, list)):
        return [normal(v) for v in value]
    return value


def type_tree(t):
    """Mirror of tools/ifcdump type_tree(): aggregate kinds and defined-type names."""
    if t is None:
        return "?"
    at = t.as_aggregation_type()
    if at is not None:
        kind = (at.type_of_aggregation_string() or "-").upper()
        return f"{kind}<{type_tree(at.type_of_element())}>"
    nt = t.as_named_type()
    if nt is not None:
        declaration = nt.declared_type()
        td = declaration.as_type_declaration()
        if td is not None:
            inner = td.declared_type()
            if inner is not None and inner.as_aggregation_type() is not None:
                return type_tree(inner)
        return declaration.name()
    st = t.as_simple_type()
    if st is not None:
        name = str(st.declared_type()).lower()
        for prefix in ("simple_type::", "simple_type."):
            name = name.replace(prefix, "")
        return SIMPLE.get(name, "?")
    return "?"


def same(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)
        except (TypeError, ValueError):
            return False
    return a == b


def main() -> int:
    if not MODEL.exists():
        raise SystemExit(f"{MODEL} is missing; run `pixi run house` first")
    if not EXE.exists():
        raise SystemExit(f"{EXE} is missing; run `pixi run ifcdump-build` first")
    result = subprocess.run([str(EXE), str(MODEL)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300)
    if result.returncode != 0:
        raise SystemExit(f"ifcdump failed ({result.returncode}): {result.stderr}")
    lines = result.stdout.splitlines()
    schema = lines[0].split("\t", 1)[1] if lines and lines[0].startswith("schema\t") else ""
    rows = {}
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) != 6:
            continue
        eid, type_name, attr, agg, tree, raw = parts
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        rows.setdefault(int(eid), {"type": type_name, "attrs": {}})["attrs"][attr] = (
            agg.upper(), tree, value)
    model = ifcopenshell.open(str(MODEL))
    entities = {e.id(): e for e in model}
    problems = []
    if schema != model.schema_identifier:
        problems.append(f"schema {schema!r} != {model.schema_identifier!r}")
    if len(rows) != len(entities):
        problems.append(f"{len(rows)} entities in the bridge, {len(entities)} in IfcOpenShell")
    for eid, e in entities.items():
        row = rows.get(eid)
        if row is None:
            problems.append(f"entity #{eid} missing from the bridge")
            continue
        if row["type"] != e.is_a():
            problems.append(f"#{eid} type {row['type']} != {e.is_a()}")
            continue
        declar = W.schema_by_name(model.schema_identifier).declaration_by_name(e.is_a()).as_entity()
        expected = [(a.name(), i, a.type_of_attribute()) for i, (a, der) in enumerate(zip(declar.all_attributes(), declar.derived())) if not der]
        if set(row["attrs"]) != {name for name, _, _ in expected}:
            problems.append(f"#{eid} attribute names differ: {sorted(row['attrs'])} vs {sorted(n for n, _, _ in expected)}")
            continue
        for name, i, param in expected:
            agg, tree, value = row["attrs"][name]
            want_agg = (records.agg_info(param)[0] or "-").upper()
            if agg != want_agg:
                problems.append(f"#{eid}.{name} aggregate {agg} != {want_agg}")
            want_tree = type_tree(param)
            if tree != want_tree:
                problems.append(f"#{eid}.{name} type tree {tree} != {want_tree}")
            if not same(normal(e[i]), value):
                problems.append(f"#{eid}.{name} {value!r} != {normal(e[i])!r}")
                if len(problems) > 30:
                    break
        if len(problems) > 30:
            break
    report = {"ok": not problems, "schema": schema, "entities": len(rows),
        "attributes": sum(len(r["attrs"]) for r in rows.values()), "problems": problems[:30]}
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
