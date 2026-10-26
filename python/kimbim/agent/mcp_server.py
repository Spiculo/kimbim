# SPDX-License-Identifier: GPL-3.0-or-later
"""`kimbim mcp [--project P]` (D102, spec §7): the agent tool catalogue as an MCP server over stdio, with the official
Python SDK's low-level `Server`.

One MCP tool per catalogue tool, named `group_verb`; its input schema is the tool's parameters plus `project`
(required when the server was started without `--project`). A call goes to the project's background worker through
`client.request`, as the client `mcp-<clientInfo.name>`, and its JSON envelope comes back as one text block
(`isError` when `ok` is false). `snapshot_take` adds the picture as an image block. The server remembers the task
it started on each project and passes it on later calls, until it is finished or abandoned. The project summary
(`project.info`) is also the resource `kimbim://project/info`."""
from __future__ import annotations

import base64
import copy
import json
import os
import threading

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import MCPError

from . import client as _client
from . import messages
from .catalogue import TOOLS, AgentError

NAME = "kimbim"
RESOURCE = "kimbim://project/info"
_PROJECT = {"type": "string", "description": "The KimBim project: a folder, .kim or .ifc path."}
_STALE = ("no_task", "unknown_task")  # the task we remembered is gone (finished or abandoned in the app)

INSTRUCTIONS = """\
KimBim is a BIM app. These tools read and change a KimBim project: an IFC model with saved versions.
Start with project_info (also the resource kimbim://project/info): levels, units, settings, the open task.
Tasks and review:
- Call task_start with a short title before changing anything. Your changes go in a design option
  (agent/<title>) that the architect reviews in KimBim; a change made without a task starts one.
- When you are done, call task_finish with a summary of what you changed and why. task_abandon discards it.
- Never accept your own option: combining, accepting or rejecting it is the architect's decision.
- Every write tool takes dry_run: true to see what would change without changing anything.
Selecting elements: `elements` is a list of GlobalIds, "selection" (the app's selection) or a find object
  such as {"kind": "window", "level": "Level 1"}. Try elements_find first to see what matches.
Units: lengths are numbers in the project's unit or text with a unit ("50cm", "1.2 m", "500 mm"); angles
  "90deg"; relative changes "+50cm" or "-10%".
Take a snapshot to check your work: snapshot_take returns a picture; changes: "task" colours what your task
  changed.
Every result is a JSON envelope: {"ok": true, "result": ...} or {"ok": false, "error": {"code", "message",
  "hint"}}. Read the hint, fix the call and try again.
"""


def mcp_name(tool: str) -> str:
    """`elements.set_dimensions` -> `elements_set_dimensions`."""
    return tool.replace(".", "_")


def input_schema(name: str, project_fixed: bool) -> dict:
    """The tool's parameters (with `dry_run` on write tools) plus `project`."""
    schema = copy.deepcopy(TOOLS[name].params)
    schema["properties"] = {**schema.get("properties", {}), "project": _PROJECT}
    if not project_fixed:
        schema["required"] = [*schema.get("required", ()), "project"]
    return schema


def _text(envelope: dict) -> types.TextContent:
    return types.TextContent(text=json.dumps(envelope, ensure_ascii=False, default=str))


class KimbimMcp:
    """What the server does, apart from the MCP plumbing: tool list, calls and the remembered tasks.
    `request` is `client.request` (a stand-in in tests)."""

    def __init__(self, project: str | None = None, request=None):
        self.project = os.path.abspath(project) if project else None
        self.request = request or _client.request
        self.names = {mcp_name(n): n for n in TOOLS if not n.startswith("_")}
        self.tasks: dict[tuple[str, str], str] = {}  # (client, project) -> the task this server started
        self.lock = threading.Lock()

    def tools(self) -> list[types.Tool]:
        return [types.Tool(name=m, description=TOOLS[n].description,
                           input_schema=input_schema(n, self.project is not None))
                for m, n in self.names.items()]

    def envelope(self, client: str, tool: str, arguments: dict | None) -> dict:
        """Run catalogue tool `tool` in the project's worker; the envelope. Never raises."""
        args = dict(arguments or {})
        project = args.pop("project", None) or self.project
        if not project:
            return AgentError("bad_input", hint=messages.text("hint_required", field="project")).envelope()
        project = str(project)
        key = (client, os.path.abspath(project))
        with self.lock:
            task = self.tasks.get(key, "")
        envelope = self.request(project, tool, args, client=client, task=task)
        code = (envelope.get("error") or {}).get("code") if not envelope.get("ok") else None
        if task and code in _STALE:
            with self.lock:
                if self.tasks.get(key) == task:
                    del self.tasks[key]
            if not tool.startswith("task."):  # nothing ran: once more in whatever task is open now
                envelope = self.request(project, tool, args, client=client, task="")
        if envelope.get("ok"):
            with self.lock:
                if tool == "task.start":
                    self.tasks[key] = str((envelope.get("result") or {}).get("id") or "")
                elif tool in ("task.finish", "task.abandon"):
                    done = args.get("task") or task
                    if done and self.tasks.get(key) == done:
                        del self.tasks[key]
        return envelope

    def call(self, client: str, name: str, arguments: dict | None) -> types.CallToolResult:
        tool = self.names.get(name)
        if tool is None:
            envelope = AgentError("unknown_tool", tool=name).envelope()
        else:
            try:
                envelope = self.envelope(client, tool, arguments)
            except Exception as ex:  # noqa: BLE001  (an agent sees an error, the server carries on)
                envelope = AgentError("worker_failed", hint=str(ex)).envelope()
        content: list = []
        path = str((envelope.get("result") or {}).get("path") or "") if envelope.get("ok") and tool == "snapshot.take" \
            else ""
        if path.lower().endswith(".png"):
            try:
                with open(path, "rb") as f:
                    content.append(types.ImageContent(data=base64.b64encode(f.read()).decode("ascii"),
                                                      mime_type="image/png"))
            except OSError:
                pass  # the text block still says where it should be
        content.append(_text(envelope))
        return types.CallToolResult(content=content, is_error=not envelope.get("ok"))


def client_id(ctx) -> str:
    """`mcp-<clientInfo.name>` (the name the client gave when it connected), else `mcp`."""
    params = getattr(ctx.session, "client_params", None)
    name = (params.client_info.name if params is not None and params.client_info else "").strip()
    return f"mcp-{name}" if name else "mcp"


def build_server(project: str | None = None, request=None) -> Server:
    """The MCP server for `project` (None: every call names its project)."""
    from .. import agent  # noqa: F401  (importing the package fills the catalogue)

    core = KimbimMcp(project, request)

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=core.tools())

    async def call_tool(ctx, params):
        who = client_id(ctx)
        return await anyio.to_thread.run_sync(core.call, who, params.name, params.arguments)

    async def list_resources(ctx, params):
        resources = [types.Resource(name="project_info", uri=RESOURCE, mime_type="application/json",
                                    description="The project: levels, units, settings and the open task.")]
        return types.ListResourcesResult(resources=resources if core.project else [])

    async def read_resource(ctx, params):
        if str(params.uri) != RESOURCE:
            raise MCPError(types.INVALID_PARAMS, f"unknown resource {params.uri}")
        if not core.project:
            raise MCPError(types.INVALID_PARAMS, "the server has no project (start it with --project)")
        who = client_id(ctx)
        envelope = await anyio.to_thread.run_sync(core.envelope, who, "project.info", {})
        body = envelope["result"] if envelope.get("ok") else envelope
        return types.ReadResourceResult(contents=[types.TextResourceContents(
            uri=RESOURCE, mime_type="application/json", text=json.dumps(body, ensure_ascii=False, default=str))])

    server = Server(NAME, version=_version(), instructions=INSTRUCTIONS, on_list_tools=list_tools,
                    on_call_tool=call_tool, on_list_resources=list_resources, on_read_resource=read_resource)
    server.core = core
    return server


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("kimbim")
    except Exception:  # noqa: BLE001  (a development checkout isn't installed)
        return "dev"


def serve(project: str | None = None) -> int:
    """`kimbim mcp`: serve over stdin/stdout until the client closes them."""
    from mcp.server.stdio import stdio_server

    server = build_server(project)

    async def run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)
    return 0
