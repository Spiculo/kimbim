# SPDX-License-Identifier: GPL-3.0-or-later
"""Renovation exit check (D74): the sample house with an existing, a demolished and a new wall gives one
sheet per purpose (Existing, Demolition, New construction), each with a legend, each showing the right
walls. Usage: python tools/check_renovation.py build/house.ifc build/renovation"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
from kimbim import app_bridge as b  # noqa: E402
from kimbim import drawings as D  # noqa: E402


def call(fn, *args):
    r = json.loads(getattr(b, fn)(*args))
    if isinstance(r, dict) and r.get("ok") is False:
        raise SystemExit(f"{fn} failed: {r.get('error')}")
    return r


def main(house: str, out: str) -> int:
    outdir = pathlib.Path(out)
    outdir.mkdir(parents=True, exist_ok=True)
    call("open_model", house)
    plan = next(d["guid"] for d in call("drawings")["drawings"] if d["name"] == "Level 1 Floor Plan")
    drawn = D.raw_drawing(plan)["svg"]
    walls = [w.GlobalId for w in b._model.by_type("IfcWall") if w.GlobalId in drawn][:3]
    if len(walls) < 3:
        raise SystemExit("the plan shows fewer than three walls")
    for guid, status in zip(walls, ("existing", "demolish", "new")):
        call("set_status", json.dumps([guid]), status)
    expect = {"Existing": {walls[0], walls[1]}, "Demolition": {walls[0], walls[1]},
              "New construction": {walls[0], walls[2]}}
    failures = []
    for purpose, shown in expect.items():
        number = call("add_sheet", "A3", purpose)["number"]
        call("place_drawing", number, plan, 10, 10, 100)
        call("set_sheet_purpose", number, purpose)
        call("place_legend", number)
        svg = call("sheet_svg", number)["svg"]
        (outdir / f"{purpose}.svg").write_text(svg, encoding="utf-8")
        for guid in walls:
            if (guid in svg) != (guid in shown):
                failures.append(f"{purpose}: wall {guid} {'missing' if guid in shown else 'shown'}")
        if 'class="kimbim-legend"' not in svg:
            failures.append(f"{purpose}: no legend")
    if "To be demolished" not in (outdir / "Demolition.svg").read_text(encoding="utf-8"):
        failures.append("Demolition: the legend has no demolition row")
    if "Existing" not in (outdir / "New construction.svg").read_text(encoding="utf-8"):
        failures.append("New construction: the legend has no existing row")
    for f in failures:
        print("FAIL", f)
    print("renovation OK" if not failures else f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:3]))
