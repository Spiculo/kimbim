# SPDX-License-Identifier: GPL-3.0-or-later
"""One undo step per agent tool call, with a summary of what changed, and the dry run that rolls it back (D102).

Built on the console's step machinery (D82/D92): bridge calls made while `B._step` is set join the open step,
`console._finish_step` closes it (or drops it when nothing changed), `console.touched` says what it touched.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from .. import app_bridge as B
from .. import console


@dataclass
class Changes:
    """GlobalIds a step added, modified and removed, with a fallback label for each taken while it existed."""
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    fallback: dict[str, str] = field(default_factory=dict)

    def to_dict(self, labels=None) -> dict:
        """{"added": [{"guid","label"}], "modified": [...], "removed": [...], "counts": {...}}; `labels(guid)`
        names an element (the session's label), else the label taken during the step."""
        def item(g):
            label = ""
            if labels is not None:
                try:
                    label = labels(g) or ""
                except Exception:  # noqa: BLE001  (gone after the step: use the one taken during it)
                    label = ""
            return {"guid": g, "label": label or self.fallback.get(g, g)}

        out = {k: [item(g) for g in getattr(self, k)] for k in ("added", "modified", "removed")}
        out["counts"] = {k: len(out[k]) for k in ("added", "modified", "removed")}
        return out

    def __bool__(self) -> bool:
        return bool(self.added or self.modified or self.removed)


def _short(ifc_class: str) -> str:
    return ifc_class[3:] if ifc_class.startswith("Ifc") else ifc_class


def _label(ifc_class: str, name) -> str:
    return f"{_short(ifc_class)} {name}" if name else _short(ifc_class)


def _is_product(ifc_class: str) -> bool:
    try:
        decl = B._schema().declaration_by_name(ifc_class)
    except Exception:  # noqa: BLE001
        return False
    while decl is not None:
        if decl.name() == "IfcProduct":
            return True
        decl = decl.supertype()
    return False


def _summarise(f, operations, step_changed, step_removed) -> Changes:
    """Changes from the step's transaction operations plus the geometry its bridge calls reported."""
    created, deleted = [], {}
    for op in operations or ():
        value = op.get("value") or {}
        if op.get("action") == "create" and isinstance(value.get("id"), int):
            created.append(value["id"])
        elif op.get("action") == "delete" and value.get("GlobalId"):
            deleted[value["GlobalId"]] = value
    found = console.touched(f, operations) if operations is not None else None
    changed, removed = found if found is not None else ([], [])
    changes = Changes()
    for i in created:
        try:
            e = f.by_id(i)
        except RuntimeError:
            continue  # created and deleted again in the same step
        if e.is_a("IfcProduct"):
            changes.added.append(e.GlobalId)
    added = set(changes.added)
    created_guids = {(op.get("value") or {}).get("GlobalId") for op in operations or ()
                     if op.get("action") == "create"}
    for g in dict.fromkeys([*removed, *step_removed]):
        if g in created_guids:
            continue
        value = deleted.get(g)
        if value is not None and not _is_product(value.get("type", "")):
            continue  # a property set, relationship, ... has a GlobalId too
        try:
            f.by_guid(g)
            continue  # still there
        except RuntimeError:
            pass
        changes.removed.append(g)
        if value is not None:
            changes.fallback[g] = _label(value.get("type", ""), value.get("Name"))
    gone = set(changes.removed)
    for g in dict.fromkeys([*changed, *step_changed]):
        if g in added or g in gone:
            continue
        try:
            f.by_guid(g)
        except RuntimeError:
            continue
        changes.modified.append(g)
    for g in [*changes.added, *changes.modified]:
        e = f.by_guid(g)
        changes.fallback[g] = _label(e.is_a(), getattr(e, "Name", None))
    return changes


def _drop_last_undo(saved_future) -> None:
    """Undo the step just committed and forget it, putting back the redo stack it cleared."""
    B.undo()
    B._model.future.pop()
    for stack in (B._future_ids, B._future_deltas, B._future_drawing_ids, B._future_settings_before):
        stack.pop()
    model_future, ids, deltas, drawing_ids, settings_before = saved_future
    B._model.future = model_future
    B._future_ids[:] = ids
    B._future_deltas[:] = deltas
    B._future_drawing_ids[:] = drawing_ids
    B._future_settings_before[:] = settings_before


@contextlib.contextmanager
def step(dry_run: bool = False):
    """`with step(dry_run) as changes:` the block's edits are one undo step; on exit `changes` says what was
    added, modified and removed. A dry run then undoes the step and leaves no trace in the history. On an
    exception the step is rolled back and the exception re-raised, so a failing call leaves nothing."""
    from .catalogue import AgentError

    if B._model is None:
        raise AgentError("no_model")
    changes = Changes()
    if B._step is not None:  # already inside an open step (a console run): join it
        if dry_run:
            from . import messages

            raise AgentError("bad_input", hint=messages.text("hint_nested_dry_run"))
        tx = B._model.transaction
        start = len(tx.operations) if tx else 0
        marks = (len(B._step[0]), len(B._step[1]))
        yield changes
        found = _summarise(B._model, tx.operations[start:] if tx else None,
                           B._step[0][marks[0]:], B._step[1][marks[1]:])
        changes.__dict__.update(found.__dict__)
        return
    saved_future = (list(B._model.future), list(B._future_ids), list(B._future_deltas),
                    list(B._future_drawing_ids), list(B._future_settings_before))
    B._begin()
    B._step = ([], [])
    try:
        yield changes
        reported = B._step
        kept = console._finish_step()  # runs the follow-ups (rooms re-fitted, ...) inside the step
    except BaseException as failure:
        B._step = None
        B._abort(failure)
        raise
    if kept:
        operations = B._model.history[-1].operations if B._model.history else None
        found = _summarise(B._model, operations, reported[0], reported[1])
        changes.__dict__.update(found.__dict__)
        if dry_run:
            _drop_last_undo(saved_future)
