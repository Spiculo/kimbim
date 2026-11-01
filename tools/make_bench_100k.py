# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the 100k-object model used by the release benchmark (tools/bench_100k.py).

It reuses the S2 spike's generator (100k walls on a grid, 10% with openings) without psutil.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPIKE = ROOT / "spikes" / "s2_geometry" / "geom_bench.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("kimbim_geom_bench", SPIKE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = module.synth(100_000)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
