# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared pytest fixtures. Model builders live in kimcad.testing (also used by the app self-test)."""
import pytest

from kimcad.testing import build_model  # noqa: F401  (re-exported for test modules)


@pytest.fixture
def model():
    return build_model()
