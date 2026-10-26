# SPDX-License-Identifier: GPL-3.0-or-later
"""`python -m kimbim`: the command line (agent/cli.py)."""
import os
import sys
from pathlib import Path


def _env_path() -> None:
    """An AI client starts `<env python> -m kimbim mcp` without activating its conda/pixi environment, so the
    env's DLL and program folders (Library/bin: OCCT's and numpy's DLLs, git) are not on PATH and the import
    crashes. Put them first, as activation would (D102). Nothing changes in an activated or plain environment."""
    prefix = Path(sys.prefix)
    if not (prefix / "conda-meta").is_dir():
        return
    if sys.platform == "win32":
        lib = prefix / "Library"
        dirs = [prefix, lib / "mingw-w64" / "bin", lib / "usr" / "bin", lib / "bin", prefix / "Scripts", prefix / "bin"]
    else:
        dirs = [prefix / "bin"]
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    have = {os.path.normcase(os.path.normpath(p)) for p in parts}
    missing = [str(d) for d in dirs if d.is_dir() and os.path.normcase(os.path.normpath(str(d))) not in have]
    if missing:
        os.environ["PATH"] = os.pathsep.join(missing + parts)


_env_path()

from .cli import main  # noqa: E402  (after the PATH fix: importing it loads the native libraries)

sys.exit(main())
