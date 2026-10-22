# SPDX-License-Identifier: GPL-3.0-or-later
"""Building an object's geometry from its definition (D99, doc 16 §2–3)."""
from __future__ import annotations


class ObjectError(ValueError):
    """A definition that cannot load or build; the message starts with the field's path."""


def check(defn) -> None:
    """Structural validation of the parts (Task 4)."""


def build(defn, values, resolve=None):
    return None  # Task 4
