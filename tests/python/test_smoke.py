# SPDX-License-Identifier: GPL-3.0-or-later
import ifcopenshell


def test_ifcopenshell_is_conda_forge_0_9():
    assert ifcopenshell.version.startswith("0.9.0")


def test_package_version():
    import kimcad

    assert kimcad.__version__ == "0.1.0"
