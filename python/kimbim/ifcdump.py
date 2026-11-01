# SPDX-License-Identifier: GPL-3.0-or-later
"""Locate and run the C++ IfcParse bridge that feeds the Rust decomposer (docs/19).

The bridge is optional: when it is not installed, `kimbim.records.decompose` remains the reference
implementation. The dump is a one-shot subprocess because IfcOpenShell's C++ destructor crashes
after value access on Windows.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

EXE_NAME = "ifcdump.exe" if sys.platform == "win32" else "ifcdump"


def executable() -> pathlib.Path | None:
    candidates: list[pathlib.Path] = []
    if value := os.environ.get("KIMBIM_IFCDUMP"):
        candidates.append(pathlib.Path(value))
    here = pathlib.Path(__file__).resolve()
    # Checkout: python/kimbim/ifcdump.py -> <repo>/build/ifcdump/ifcdump(.exe)
    candidates.append(here.parents[2] / "build" / "ifcdump" / EXE_NAME)
    if home := os.environ.get("KIMBIM_HOME"):
        candidates.append(pathlib.Path(home) / "ifcdump" / EXE_NAME)
    candidates.append(here.parent / EXE_NAME)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def dump(ifc_path, timeout: float = 900) -> str | None:
    """The bridge dump for `ifc_path`, or None when the bridge is unavailable or failed."""
    exe = executable()
    if exe is None:
        return None
    try:
        result = subprocess.run(
            [str(exe), str(ifc_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout
