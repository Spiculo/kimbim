# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the live-agent test on its own (it starts the kimbim CLI as a child process)."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME = "test_agent_live.exe" if os.name == "nt" else "test_agent_live"


def main() -> int:
    exe = ROOT / "build" / "app" / NAME
    if not exe.exists():
        raise SystemExit(f"{exe} is missing; run `pixi run app-build` first")
    env = os.environ.copy()
    env.setdefault("KIMBIM_PYTHON_PATH", str(ROOT / "python"))
    env["QT_QPA_PLATFORM"] = "offscreen"
    data = ROOT / "build" / "app" / "test-data-agent"
    data.mkdir(parents=True, exist_ok=True)
    env["KIMBIM_DATA_DIR"] = str(data)
    code = 1
    for attempt in (1, 2):
        code = subprocess.run([str(exe)], env=env).returncode
        if code == 0:
            return 0
        if attempt == 1:
            print(f"live-agent test failed (exit {code}); retrying once "
                  "(the child-process harness has shown a rare startup crash)", file=sys.stderr)
            time.sleep(1.0)
    return code


if __name__ == "__main__":
    sys.exit(main())
