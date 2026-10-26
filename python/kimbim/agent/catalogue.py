# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent tool catalogue (D102): tools register with @tool, `call_tool` validates the input, runs a write
tool as one undo step (or a dry run) inside the task gate, and wraps everything in the JSON envelope

    {"ok": true, "result": ..., "changes"?: {..., "dry_run"?: true}, "warnings"?: [...]}
    {"ok": false, "error": {"code", "message", "hint"?, "details"?}}

`changes` comes with every write tool (`dry_run: true` in it when the call was rolled back). A tool returns
its result, or `ToolResult(result, warnings=[...])` to add warnings (in the envelope only when there are any).
Write tools are refused while another undo step is open (a console run or edit() block).

The CLI and the MCP server both call `call_tool`; tools never re-implement modelling, they call the bridge
through `bridge(fn, *args)`.
"""
from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Callable

from . import messages, steps
from .. import app_bridge as B


class AgentError(Exception):
    """A tool error with a stable English `code`; the message comes from `messages.text(code, **extra)`."""

    def __init__(self, code: str, hint: str = "", **extra):
        self.code = code
        self.hint = hint
        self.extra = extra
        super().__init__(messages.text(code, **extra))

    def envelope(self) -> dict:
        error = {"code": self.code, "message": str(self)}
        if self.hint:
            error["hint"] = self.hint
        if self.extra:
            error["details"] = self.extra
        return {"ok": False, "error": error}


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    writes: bool
    fn: Callable
    needs_task: bool | None = None

    def __post_init__(self):
        if self.needs_task is None:
            self.needs_task = self.writes


TOOLS: dict[str, Tool] = {}


@dataclass
class ToolResult:
    """What a tool returns when it has warnings for the agent (EN/ES text, e.g. from `messages.text`)."""
    result: object = None
    warnings: list[str] = field(default_factory=list)


def _unwrap(out) -> tuple:
    return (out.result, list(out.warnings)) if isinstance(out, ToolResult) else (out, [])


_DRY_RUN = {"type": "boolean", "description": "Report what would change, then roll it back."}


def tool(name: str, params: dict, writes: bool = False, needs_task: bool | None = None):
    """Register `fn(session, **args)` as tool `name`. Its docstring is the description agents read, so it is
    required. Write tools get a `dry_run` parameter. Unknown arguments are refused unless `params` says
    otherwise (`additionalProperties`)."""
    def register(fn):
        description = inspect.cleandoc(fn.__doc__ or "")
        if not re.search(r"\w.*[.!?](\s|$)", description):
            raise ValueError(f"tool {name}: the docstring must be at least one sentence")
        if name in TOOLS:
            raise ValueError(f"tool {name} is already registered")
        schema = {"type": "object", **params}
        schema["properties"] = dict(schema.get("properties") or {})
        schema.setdefault("additionalProperties", False)
        if writes:
            schema["properties"]["dry_run"] = _DRY_RUN
        t = Tool(name, description, schema, writes, fn, needs_task)
        TOOLS[name] = t
        return t
    return register


# ---------------------------------------------------------------- validation (a small JSON Schema subset)

_TYPE_NAMES = {"object": "an object", "string": "a string", "number": "a number", "integer": "an integer",
               "boolean": "true or false", "array": "a list", "null": "null"}


def _is_type(value, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "array":
        return isinstance(value, list)
    if t == "null":
        return value is None
    if isinstance(value, bool):
        return False
    if t == "number":
        return isinstance(value, (int, float))
    if t == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    return False


def _bad(code: str, **fmt):
    return AgentError("bad_input", hint=messages.text(code, **fmt))


def validate(schema: dict, value, path: str = "input") -> None:
    """Check `value` against `schema`: type (one or a list), required, properties, additionalProperties,
    enum, items and oneOf. Raises AgentError("bad_input") with a hint naming the field."""
    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            try:
                validate(option, value, path)
                matches += 1
            except AgentError:
                pass
        if matches != 1:
            raise _bad("hint_form", field=path)
    types = schema.get("type")
    if types is not None:
        types = [types] if isinstance(types, str) else list(types)
        if not any(_is_type(value, t) for t in types):
            raise _bad("hint_type", field=path, type=" / ".join(_TYPE_NAMES.get(t, t) for t in types))
    if "enum" in schema and value not in schema["enum"]:
        raise _bad("hint_enum", field=path, values=", ".join(json.dumps(v, ensure_ascii=False)
                                                             for v in schema["enum"]))
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for key in schema.get("required") or ():
            if key not in value:
                raise _bad("hint_required", field=key if path == "input" else f"{path}.{key}")
        for key, v in value.items():
            where = key if path == "input" else f"{path}.{key}"
            if key in props:
                validate(props[key], v, where)
            elif schema.get("additionalProperties") is False:
                raise _bad("hint_unknown_field", field=where)
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, v in enumerate(value):
            validate(schema["items"], v, f"{path}[{i}]")


# ---------------------------------------------------------------- calling

def bridge(fn, *args) -> dict:
    """Call a bridge function (or its name in app_bridge) and parse its JSON. A result with `ok: false` (or an
    `error` and no `ok`) raises AgentError("bridge_error") with the bridge's error as the hint."""
    if isinstance(fn, str):
        fn = getattr(B, fn)
    out = fn(*args)
    result = json.loads(out) if isinstance(out, (str, bytes)) else out
    if isinstance(result, dict) and (result.get("ok") is False or ("ok" not in result and result.get("error"))):
        raise AgentError("bridge_error", hint=str(result.get("error") or ""))
    return result


def _title(name: str, args: dict) -> str:
    """An implicit task's title: the tool's name and the first words of what it acts on."""
    words: list[str] = []

    def walk(v):
        if len(words) >= 6:
            return
        if isinstance(v, str):
            words.extend(v.split()[: 6 - len(words)])
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(args.get("elements", args))
    return " ".join([name, *words])[:80]


def _ok(result, changes, warnings) -> dict:
    envelope = {"ok": True, "result": result}
    if changes is not None:
        envelope["changes"] = changes
    if warnings:
        envelope["warnings"] = warnings
    return envelope


def call_tool(session, name: str, args: dict, *, client: str = "cli", task_id: str = "") -> dict:
    """Run tool `name` with `args` and return its envelope. Never raises."""
    try:
        t = TOOLS.get(name)
        if t is None:
            raise AgentError("unknown_tool", tool=name)
        args = {} if args is None else args
        validate(t.params, args)  # refuses a non-object too
        args = dict(args)
        dry_run = bool(args.pop("dry_run", False)) if t.writes else False
        if not t.writes:
            result, warnings = _unwrap(t.fn(session, **args))
            return _ok(result, None, warnings)
        if B._step is not None:  # inside a console run or edit() block: refused before any task starts
            raise AgentError("bad_input", hint=messages.text("hint_open_step"))
        if t.needs_task and not dry_run:  # a dry run changes nothing, so it starts no task
            session.tasks.for_write(client, task_id, title=_title(name, args))
        with steps.step(dry_run) as changes:
            result, warnings = _unwrap(t.fn(session, **args))
        summary = changes.to_dict(getattr(session, "label", None))
        if dry_run:
            summary["dry_run"] = True
        return _ok(result, summary, warnings)
    except AgentError as ex:
        return ex.envelope()
    except Exception as ex:  # noqa: BLE001  (an agent sees an error, the process carries on)
        return AgentError("bridge_error", hint=str(ex)).envelope()
