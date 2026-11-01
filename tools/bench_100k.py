# SPDX-License-Identifier: GPL-3.0-or-later
"""Release gate for large models: 100k objects, first frame, full load and the decomposition cache.

Run it through `pixi run bench-100k` after generating the synthetic model:
    pixi run bench-model
    pixi run bench-100k

The first frame (the first mesh batch on screen) must stay under 15 s, the target in docs/09.
The full load and the cold decomposition are reported; the warm decomposition comes from the
project's on-disk cache and must also stay under 15 s.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

FIRST_FRAME_LIMIT = 15.0
WARM_DECOMPOSE_LIMIT = 15.0
FULL_LOAD_LIMIT = 240.0  # catches a regression, not the target


def app_binary() -> pathlib.Path:
    name = "kimbim-app.exe" if os.name == "nt" else "kimbim-app"
    return ROOT / "build" / "app" / name


def run_app(ifc: pathlib.Path) -> dict:
    app = app_binary()
    if not app.exists():
        raise SystemExit(f"{app} is missing; run `pixi run app-build` first")
    env = os.environ.copy()
    env["KIMBIM_PYTHON_PATH"] = str(ROOT / "python")
    env.setdefault("QT_OPENGL", "software")  # a real window, no GPU requirement
    started = time.perf_counter()
    result = subprocess.run(
        [str(app), "--self-test", str(ifc), "--frames", "1", "--chunk", "500", "--bench-snap", "--plan-view"],
        capture_output=True, text=True, env=env, timeout=900,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip().startswith("{")]
    if result.returncode != 0 or not lines:
        raise SystemExit(f"app self-test failed ({result.returncode}): {result.stdout}{result.stderr}")
    report = json.loads(lines[-1])
    if not report.get("ok"):
        raise SystemExit(f"app self-test reported a failure: {report}")
    report["wall_s"] = round(time.perf_counter() - started, 2)
    return report


def run_decomposition(ifc: pathlib.Path) -> tuple[float, float]:
    """Cold and warm `Project.status` on the same file (the warm run uses the cache)."""
    from kimbim.project import Project

    with tempfile.TemporaryDirectory(prefix="kimbim-bench-") as tmp:
        project = Project.init(pathlib.Path(tmp) / "p")
        started = time.perf_counter()
        project.status(ifc)
        cold = time.perf_counter() - started
        started = time.perf_counter()
        project.status(ifc)
        warm = time.perf_counter() - started
    return round(cold, 2), round(warm, 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ifc", type=pathlib.Path,
        default=ROOT / "spikes" / "s2_geometry" / "out" / "synth-100000.ifc")
    parser.add_argument("--skip-decompose", action="store_true", help="only measure the viewer")
    parser.add_argument("--first-frame-limit", type=float, default=FIRST_FRAME_LIMIT)
    parser.add_argument("--full-load-limit", type=float, default=FULL_LOAD_LIMIT)
    parser.add_argument("--warm-decompose-limit", type=float, default=WARM_DECOMPOSE_LIMIT)
    parser.add_argument("--cold-decompose-limit", type=float, default=150.0,
        help="cold Project.status with the Rust decomposer (bridge) and the Python fallback bound")
    parser.add_argument("--set-tool-limit", type=float, default=2.0, help="seconds to select the Wall tool")
    parser.add_argument("--plan-paint-limit", type=float, default=180.0, help="seconds for the plan cut/poché paint")
    parser.add_argument("--snap-limit", type=float, default=1.0, help="seconds to dispatch snap-data loading")
    args = parser.parse_args()

    ifc = args.ifc.resolve()
    if not ifc.exists():
        raise SystemExit(f"{ifc} is missing; run `pixi run bench-model` first")

    report = run_app(ifc)
    problems = []
    if report.get("elements", 0) < 100_000:
        problems.append(f"the model has {report.get('elements')} elements, expected 100000")
    first = float(report.get("first_frame_s", -1))
    if first < 0 or first > args.first_frame_limit:
        problems.append(f"first frame {first:.2f}s exceeds {args.first_frame_limit:.1f}s")
    full = float(report.get("load_s", -1))
    if full < 0 or full > args.full_load_limit:
        problems.append(f"full load {full:.2f}s exceeds {args.full_load_limit:.1f}s")
    set_tool = float(report.get("set_tool_ms", -1)) / 1000.0
    plan_view = float(report.get("plan_view_ms", -1)) / 1000.0
    plan_paint = float(report.get("plan_paint_ms", -1)) / 1000.0
    steps = report.get("load_steps_ms") or {}
    snap = float(steps.get("tool:snap", -1)) / 1000.0
    if set_tool < 0 or set_tool > args.set_tool_limit:
        problems.append(f"selecting the Wall tool took {set_tool:.2f}s (limit {args.set_tool_limit:.1f}s)")
    if plan_paint < 0 or plan_paint > args.plan_paint_limit:
        problems.append(f"plan cut/poché paint took {plan_paint:.2f}s (limit {args.plan_paint_limit:.1f}s)")
    if snap < 0 or snap > args.snap_limit:
        problems.append(f"dispatching snap-data loading took {snap:.2f}s (limit {args.snap_limit:.1f}s)")

    cold = warm = None
    if not args.skip_decompose:
        cold, warm = run_decomposition(ifc)
        if cold > args.cold_decompose_limit:
            problems.append(f"cold decomposition {cold:.2f}s exceeds {args.cold_decompose_limit:.1f}s")
        if warm > args.warm_decompose_limit:
            problems.append(f"warm decomposition {warm:.2f}s exceeds {args.warm_decompose_limit:.1f}s")

    result = {
        "ok": not problems,
        "ifc": str(ifc),
        "elements": report.get("elements"),
        "first_frame_s": first,
        "load_s": full,
        "set_tool_s": set_tool,
        "plan_view_s": plan_view,
        "plan_paint_s": plan_paint,
        "snap_dispatch_s": snap,
        "cold_decompose_s": cold,
        "warm_decompose_s": warm,
        "limits": {"first_frame_s": args.first_frame_limit, "full_load_s": args.full_load_limit,
                   "set_tool_s": args.set_tool_limit, "plan_paint_s": args.plan_paint_limit,
                   "snap_dispatch_s": args.snap_limit, "cold_decompose_s": args.cold_decompose_limit,
                   "warm_decompose_s": args.warm_decompose_limit},
        "load_steps_ms": report.get("load_steps_ms"),
        "problems": problems,
    }
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
