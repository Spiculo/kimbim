"""Spike S3 runner: round-trip every corpus file through canonical records.

For each file A:
  1. records R1 = decompose(A)
  2. B = compose(R1), written to disk and re-read
  3. R2 = decompose(B)                      -> fixed point: R1 == R2
  4. C = compose(R2)                        -> export determinism: text(B) == text(C)
  5. semantic compare A vs B (independent)  -> lossless
Also writes manifest-<platform>.json with per-file state hashes for spike S4.

Usage: python run.py [substring-filter]
"""
import json
import os
import pathlib
import platform
import sys
import time
import traceback

import blake3
import ifcopenshell
import ifcopenshell.validate

from records import compose, decompose, state_hash
from semantic import compare

HERE = pathlib.Path(__file__).parent
CORPUS = HERE.parent / "corpus" / "files"
OUT = pathlib.Path(os.environ.get("KIMBIM_SPIKE_OUT", HERE / "out"))


def body_text(path):
    """IFC text without the HEADER section (it holds timestamps)."""
    t = path.read_text(encoding="utf-8", errors="replace")
    return t[t.index("DATA;"):]


def run_one(path: pathlib.Path):
    res = {"file": str(path.relative_to(CORPUS)).replace("\\", "/")}
    t0 = time.perf_counter()
    a = ifcopenshell.open(str(path))
    res["schema"] = a.schema_identifier
    res["entities"] = len(list(a))
    res["roots"] = len(a.by_type("IfcRoot"))
    t1 = time.perf_counter()
    r1, d = decompose(a)
    t2 = time.perf_counter()
    res["issues"] = d.issues
    kinds = list(d.kind.values())
    res["inline"] = kinds.count("inline")
    res["anchored"] = kinds.count("anchored")
    res["node_records"] = sum(1 for k in r1 if k.startswith("n/"))
    res["records"] = len(r1)
    res["record_bytes"] = sum(len(v) for v in r1.values())
    res["ifc_bytes"] = path.stat().st_size

    res["loose_records"] = sum(1 for k in r1 if k.startswith("l/"))
    try:
        b = compose(r1)
    except RuntimeError as e:
        # Distinguish KimBim bugs from schema-invalid input: validate the original file.
        log = ifcopenshell.validate.json_logger()
        ifcopenshell.validate.validate(a, log)
        if log.statements:
            res["invalid_input"] = [str(s.get("message", s))[:200] for s in log.statements[:3]]
            res["invalid_count"] = len(log.statements)
            return res
        raise
    t3 = time.perf_counter()
    OUT.mkdir(exist_ok=True)
    pb = OUT / (path.stem + ".B.ifc")
    b.write(str(pb))
    b2 = ifcopenshell.open(str(pb))
    r2, _ = decompose(b2)
    res["fixed_point"] = r1 == r2
    if not res["fixed_point"]:
        diff = sorted(set(r1.items()) ^ set(r2.items()))
        res["fixed_point_diff"] = [k for k, _ in diff[:5]]
    c = compose(r2)
    pc = OUT / (path.stem + ".C.ifc")
    c.write(str(pc))
    res["export_deterministic"] = body_text(pb) == body_text(pc)

    problems = compare(a, b2)
    res["lossless"] = not problems
    res["problems"] = problems
    res["state_hash"] = state_hash(r1)
    res["export_hash"] = blake3.blake3(body_text(pb).encode()).hexdigest()[:32]
    res["t_open"] = round(t1 - t0, 3)
    res["t_decompose"] = round(t2 - t1, 3)
    res["t_compose"] = round(t3 - t2, 3)
    return res


def status(r):
    if "error" in r:
        return "ERROR"
    if "invalid_input" in r:
        return "INVALID"
    return "OK" if r["fixed_point"] and r["lossless"] and r["export_deterministic"] else "FAIL"


def save(results):
    OUT.mkdir(exist_ok=True)
    tag = platform.system().lower()
    (OUT / f"results-{tag}.json").write_text(json.dumps(results, indent=1))
    manifest = {r["file"]: [r.get("state_hash"), r.get("export_hash")] for r in results}
    (OUT / f"manifest-{tag}.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))


def main():
    flt = sys.argv[1] if len(sys.argv) > 1 else ""
    files = sorted(p for p in CORPUS.rglob("*") if p.suffix.lower() == ".ifc" and flt in str(p))
    results = []
    for p in files:
        try:
            r = run_one(p)
        except Exception as e:  # record failures, keep going
            r = {"file": str(p.relative_to(CORPUS)).replace("\\", "/"), "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-800:]}
        ok = status(r)
        print(f"{ok:5} {r['file']}" + (f"  {r.get('error', '')}" if ok == "ERROR" else ""), flush=True)
        results.append(r)
        save(results)  # after every file, so an interrupted run still leaves usable data
    n = len(results)
    counts = {}
    for r in results:
        counts[status(r)] = counts.get(status(r), 0) + 1
    print(f"\n{n} files on {platform.system()} (ifcopenshell {ifcopenshell.version}): {counts}")


if __name__ == "__main__":
    main()
