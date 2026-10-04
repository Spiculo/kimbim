# SPDX-License-Identifier: GPL-3.0-or-later
"""Guards for the pixi/conda-forge environment (docs/11 spike S2, D43)."""
import pathlib
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DLL search order issue")
def test_no_mesa_opengl_in_environment():
    # The conda-forge "all" build of OCCT pulls VTK -> viskores -> Mesa, whose opengl32.dll is loaded
    # before the GPU driver, forcing software rendering for the whole app. OCCT must be the novtk build.
    bin_dir = pathlib.Path(sys.prefix) / "Library" / "bin"
    offenders = [p.name for p in bin_dir.glob("*") if p.name.lower() in ("opengl32.dll", "libgallium_wgl.dll")]
    assert offenders == [], f"Mesa software OpenGL in the environment: {offenders} (pin occt build novtk*)"
