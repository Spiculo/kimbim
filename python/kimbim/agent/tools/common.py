# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers the tool modules share: levels by name, lengths with units, types by name (D102)."""
from __future__ import annotations

import json

from ... import authoring as A
from .. import units
from ..catalogue import AgentError


def level_guid(level: str) -> str:
    """A level's GlobalId from its name (any case) or GlobalId; not_found otherwise."""
    want = str(level).strip().lower()
    for s in json.loads(A.storeys())["storeys"]:
        if s["guid"] == level or s["name"].strip().lower() == want:
            return s["guid"]
    raise AgentError("not_found", what=level)


def lengths(session, *values) -> list[float]:
    """Metres from numbers (project units) or strings with units; bad_length for anything else."""
    out = []
    for v in values:
        try:
            out.append(units.parse_length(v, session.unit))
        except ValueError:
            raise AgentError("bad_length", value=v) from None
    return out


def point(session, p, name="point") -> tuple[float, float]:
    """(x, y) in metres from a [x, y] pair."""
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        raise AgentError("bad_input", hint=f"{name} must be [x, y]")
    x, y = lengths(session, *p)
    return x, y


def pick_type(types: list[dict], ref) -> str:
    """The GlobalId of the type named (any case) or identified by `ref`; the first listed when `ref` is empty."""
    if not types:
        raise AgentError("not_found", what=str(ref or "type"))
    if not ref:
        return types[0]["guid"]
    want = str(ref).strip().lower()
    for t in types:
        if t["guid"] == ref or t["name"].strip().lower() == want:
            return t["guid"]
    raise AgentError("not_found", what=ref)
