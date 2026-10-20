# SPDX-License-Identifier: GPL-3.0-or-later
"""Slices 18-22 timed on Clinic (owner process rule): the after-edit hooks (rooms, roofs), versioning a
large model, object history, before/after, and combining two options.

Usage: python spikes/m5_bench/clinic_bench.py Clinic_Architectural.ifc WORK_DIR   (prints JSON)
"""
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
from kimbim import app_bridge as b  # noqa: E402


def call(fn, *args):
    r = json.loads(getattr(b, fn)(*args))
    if isinstance(r, dict) and r.get("ok") is False:
        raise SystemExit(f"{fn}: {r.get('error')}")
    return r


def timed(out, key, fn, *args):
    t = time.perf_counter()
    r = call(fn, *args)
    out[key] = round(time.perf_counter() - t, 3)
    return r


def main(argv):
    src, work = Path(argv[1]), Path(argv[2])
    if not src.exists():  # a bare name: look it up in the corpus (pixi run fetch-corpus)
        corpus = Path(__file__).resolve().parents[2] / "tests" / "corpus" / "files"
        src = next(corpus.rglob(src.name), src)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    t = {}
    timed(t, "open_model_s", "open_model", str(src))
    m = b._model
    walls = [w.GlobalId for w in m.by_type("IfcWall")]
    info = {"elements": len(m.by_type("IfcProduct")), "walls": len(walls), "spaces": len(m.by_type("IfcSpace")),
            "roofs": len(m.by_type("IfcRoof")), "property_sets": len(m.by_type("IfcPropertySet"))}
    # One edit with and without the after-action hooks (rooms re-fit, walls re-trimmed to roofs).
    hooks = list(b.AFTER_ACTION)
    timed(t, "rename_wall_with_hooks_s", "set_name", json.dumps(walls[:1]), "Bench 1")
    b.AFTER_ACTION[:] = []
    timed(t, "rename_wall_without_hooks_s", "set_name", json.dumps(walls[:1]), "Bench 2")
    b.AFTER_ACTION[:] = hooks
    timed(t, "move_wall_with_hooks_s", "move_elements", json.dumps(walls[1:2]), 0.1, 0.0, 0.0)
    # Versioning
    timed(t, "enable_versioning_s", "enable_versioning", str(work / "project"), "Clinic")
    timed(t, "create_option_s", "create_option", "Scheme B")
    call("set_name", json.dumps(walls[:5]), "Scheme B wall")
    call("move_elements", json.dumps(walls[10:12]), 0.0, 0.5, 0.0)
    timed(t, "save_version_b_s", "save_version", "B: five walls renamed, two moved")
    timed(t, "switch_option_s", "switch_option", "main")
    call("set_name", json.dumps(walls[:1]), "Main wall")  # conflicts with B
    call("set_name", json.dumps(walls[20:25]), "Main renamed")
    timed(t, "save_version_main_s", "save_version", "main: six walls renamed")
    timed(t, "milestone_s", "create_milestone", "Concept", "")
    timed(t, "element_history_s", "element_history", walls[0])
    timed(t, "before_after_first_s", "before_after", walls[0], "Concept", "Scheme B")
    timed(t, "before_after_cached_s", "before_after", walls[0], "Concept", "Scheme B")
    p = timed(t, "combine_preview_s", "combine_preview", "Scheme B", "{}")
    choices = {c["id"]: "theirs" for c in p["conflicts"]}
    info["conflicts"] = [c["id"] for c in p["conflicts"]]
    timed(t, "combine_options_s", "combine_options", "Scheme B", json.dumps(choices))
    timed(t, "save_combined_s", "save_version", "Combine Scheme B")
    info["parents"] = len(call("history", 1)["versions"][0]["parents"])
    print(json.dumps({"model": src.name, **info, "timings": t}, indent=2))


if __name__ == "__main__":
    main(sys.argv)
