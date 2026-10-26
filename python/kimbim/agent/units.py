# SPDX-License-Identifier: GPL-3.0-or-later
"""Length and angle parsing for agent tools (D102). The bridge works in metres and degrees."""
import math
import re

_TO_M = {"m": 1.0, "cm": 0.01, "mm": 0.001}
_NUM = r"[-+]?(?:\d+[.,]?\d*|[.,]\d+)"
_LEN = re.compile(rf"^\s*({_NUM})\s*(mm|cm|m)?\s*$", re.I)
_ANG = re.compile(rf"^\s*({_NUM})\s*(deg|°|rad)?\s*$", re.I)


def _num(s):
    return float(s.replace(",", "."))


def parse_length(v, unit="m"):
    """Metres from a number (in the project `unit`) or a string like "50cm", "500 mm", "1,2m"."""
    if isinstance(v, bool):
        raise ValueError(str(v))
    if isinstance(v, (int, float)):
        return float(v) * _TO_M[unit]
    m = _LEN.match(str(v))
    if not m:
        raise ValueError(str(v))
    return _num(m.group(1)) * _TO_M[(m.group(2) or unit).lower()]


def parse_angle(v):
    """Degrees from a number (degrees) or a string like "90deg" / "3.14rad"."""
    if isinstance(v, bool):
        raise ValueError(str(v))
    if isinstance(v, (int, float)):
        return float(v)
    m = _ANG.match(str(v))
    if not m:
        raise ValueError(str(v))
    n = _num(m.group(1))
    return math.degrees(n) if (m.group(2) or "").lower() == "rad" else n


def apply_change(current, v, unit="m"):
    """New metres from `current` and an absolute ("0.9"), relative ("+50cm", "-1") or percent ("-10%") value."""
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("%"):
            try:
                return current * (1 + _num(s[:-1]) / 100.0)
            except ValueError:
                raise ValueError(v) from None
        if s[:1] in "+-" and len(s) > 1:
            return current + parse_length(s, unit)
    return parse_length(v, unit)
