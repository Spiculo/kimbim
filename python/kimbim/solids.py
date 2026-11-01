# SPDX-License-Identifier: GPL-3.0-or-later
"""Solid element operations (D-new): subtract one element's body from another.

The result is a standard IFC4 ``IfcBooleanResult`` in the target's Body representation, so it is
stored losslessly in the IFC and evaluated by every IFC engine (IfcOpenShell here, Bonsai, viewers).
The tool element keeps its own body; only the target changes. The bridge wraps the edit in one
undo step.
"""
from __future__ import annotations

from . import app_bridge as B


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def _body(element):
    """The element's Body shape representation and its single solid item, or None."""
    representation = getattr(element, "Representation", None)
    if representation is None:
        return None
    for shape in representation.Representations or ():
        if shape.RepresentationIdentifier == "Body":
            items = list(shape.Items or ())
            if len(items) == 1:
                return shape, items[0]
    return None


OPERATORS = ("DIFFERENCE", "INTERSECTION", "UNION")


def boolean_elements(target_guid: str, tool_guids_json: str, operator: str = "DIFFERENCE") -> str:
    """Combine ``target`` with one or more tools (IfcBooleanResult); one undo step.

    The operator is DIFFERENCE, INTERSECTION or UNION. Tools are folded left to right, so a
    multi-tool cut subtracts each tool and a union joins every selected element. The tools are not
    modified; each element needs a Body representation with exactly one solid item.
    """
    if B._model is None:
        return _fail("no model open")
    op = str(operator).strip().upper()
    if op not in OPERATORS:
        return _fail(f"unknown solid operation {operator!r}")
    try:
        import json

        tool_guids = json.loads(tool_guids_json) if isinstance(tool_guids_json, str) else list(tool_guids_json)
    except (TypeError, ValueError) as ex:
        return _fail(f"bad tool list: {ex}")
    if not isinstance(tool_guids, list) or not tool_guids:
        return _fail("choose at least one tool element")
    target = B._model.by_guid(target_guid)
    if target is None:
        return _fail("target not found")
    if target_guid in tool_guids:
        return _fail("target and tool are the same element")
    target_body = _body(target)
    if target_body is None:
        return _fail("the target needs a Body representation with exactly one item")
    shape, first = target_body
    if not first.is_a("IfcSolidModel"):
        return _fail("the target body item must be a solid model")
    tools = []
    for guid in tool_guids:
        tool = B._model.by_guid(str(guid))
        if tool is None:
            return _fail(f"tool {guid} not found")
        body = _body(tool)
        if body is None or not body[1].is_a("IfcSolidModel"):
            return _fail(f"tool {guid} needs a Body representation with exactly one solid item")
        tools.append(body[1])

    def action():
        result = first
        for operand in tools:
            result = B._model.createIfcBooleanResult(op, result, operand)
        shape.Items = (result,)
        return 1, [target.GlobalId], []

    try:
        outcome = B._run(action)
    except Exception as ex:  # noqa: BLE001  (the bridge reports the failure, never crashes the app)
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**outcome, "target": target.GlobalId, "tools": tool_guids, "operator": op})


def cut_elements(target_guid: str, tool_guid: str) -> str:
    """Cut ``target`` with ``tool`` (DIFFERENCE); kept for the older one-tool bridge callers."""
    import json

    return boolean_elements(target_guid, json.dumps([tool_guid]), "DIFFERENCE")


def boolean_batch(target_guids_json: str, tool_guids_json: str, operator: str = "DIFFERENCE") -> str:
    """Apply one solid operation to several targets with the same tools, in ONE undo step.

    Each target is combined with every tool (its tools are folded left to right). A target that is
    also listed as a tool is skipped for that target. Used by selection-set workflows; the Edit
    menu still applies a single target.
    """
    if B._model is None:
        return _fail("no model open")
    op = str(operator).strip().upper()
    if op not in OPERATORS:
        return _fail(f"unknown solid operation {operator!r}")
    try:
        import json

        targets = json.loads(target_guids_json) if isinstance(target_guids_json, str) else list(target_guids_json)
        tools = json.loads(tool_guids_json) if isinstance(tool_guids_json, str) else list(tool_guids_json)
    except (TypeError, ValueError) as ex:
        return _fail(f"bad element list: {ex}")
    if not isinstance(targets, list) or not targets:
        return _fail("choose at least one target element")
    if not isinstance(tools, list) or not tools:
        return _fail("choose at least one tool element")

    prepared = []
    for guid in tools:
        tool = B._model.by_guid(str(guid))
        body = _body(tool) if tool is not None else None
        if body is None or not body[1].is_a("IfcSolidModel"):
            return _fail(f"tool {guid} needs a Body representation with exactly one solid item")
        prepared.append((str(guid), body[1]))
    work = []
    for guid in targets:
        target = B._model.by_guid(str(guid))
        body = _body(target) if target is not None else None
        if body is None or not body[1].is_a("IfcSolidModel"):
            return _fail(f"target {guid} needs a Body representation with exactly one solid item")
        operands = [item for tool_guid, item in prepared if tool_guid != str(guid)]
        if not operands:
            return _fail(f"target {guid} has no other tool element")
        work.append((target, body[0], body[1], operands))

    def action():
        changed = []
        for target, shape, first, operands in work:
            result = first
            for operand in operands:
                result = B._model.createIfcBooleanResult(op, result, operand)
            shape.Items = (result,)
            changed.append(target.GlobalId)
        return len(changed), changed, []

    try:
        outcome = B._run(action)
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**outcome, "targets": list(targets), "tools": list(tools), "operator": op})
