# SPDX-License-Identifier: GPL-3.0-or-later
"""Every kimbim module imports on its own, in a fresh interpreter: no circular imports that only work
because another module happened to be imported first (the full suite hides those)."""
import pathlib
import subprocess
import sys

import pytest

import kimbim

PACKAGE = pathlib.Path(kimbim.__file__).parent
MODULES = sorted(p.stem for p in PACKAGE.glob("*.py") if p.stem not in ("__init__", "__main__"))


@pytest.mark.parametrize("name", MODULES)
def test_module_imports_alone(name):
    r = subprocess.run([sys.executable, "-c", f"import kimbim.{name}"], capture_output=True, text=True,
                       cwd=PACKAGE.parent, timeout=120)
    assert r.returncode == 0, r.stderr
