# SPDX-License-Identifier: GPL-3.0-or-later
"""The in-app Assistant's model loop (D102 phase 3): the architect's own key, Anthropic or any
OpenAI-compatible endpoint, the same tool catalogue and the same live session as the CLI/MCP.

The panel passes the conversation and its provider settings; this module calls the provider, runs the
tools it asks for through the app's live queue (so every call is one of the app's undo steps), and returns
the final text, compact tool lines and snapshot paths."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import catalogue, live
from .credentials import KeyStoreError, get_key, has_key

ANTHROPIC_DEFAULT = "https://api.anthropic.com"
OPENAI_DEFAULT = "https://api.openai.com/v1"
MAX_STEPS = 8


def _tool_names() -> tuple[list[dict], dict[str, str]]:
    schemas, back = [], {}
    for name, tool in catalogue.TOOLS.items():
        if name.startswith("_"):
            continue
        public = name.replace(".", "_")
        back[public] = name
        schemas.append({"name": public, "description": tool.description, "input_schema": tool.params})
    return schemas, back


def _system(config: dict) -> str:
    selection = [g for g in (config.get("selection") or []) if isinstance(g, str)]
    lines = [
        "You are the assistant inside KimBim, a BIM application. You work on the project the architect has open.",
        "Use the tools to read, change and picture the model. Never claim a change you did not make.",
        "A write tool called without a task starts one; prefer task_start with a short title, then the changes, then",
        "task_finish with a summary. Changes go in a design option the architect reviews; never accept your own work.",
        "Take a snapshot (snapshot_take) when seeing the result helps. Lengths take units such as \"50cm\".",
        "Answer in the language the architect writes in. Be concise.",
    ]
    if selection:
        lines.append(f"The architect's current selection (GlobalIds): {', '.join(selection[:50])}.")
    if config.get("view"):
        lines.append(f"Current view: {config['view']}.")
    return "\n".join(lines)


def _http(url: str, headers: dict, body: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode("utf-8", "replace")[:1000]
        raise AssistantError("provider_error", f"the provider answered {ex.code}: {detail}") from None
    except (urllib.error.URLError, OSError) as ex:
        raise AssistantError("provider_error", f"cannot reach the provider: {ex}") from None
    except ValueError as ex:
        raise AssistantError("provider_error", f"the provider sent invalid JSON: {ex}") from None


class AssistantError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code, self.message, self.hint = code, message, hint


def _key(provider: str) -> str:
    try:
        key = get_key(provider)
    except KeyStoreError as ex:
        raise AssistantError("key_store", str(ex)) from None
    if not key:
        raise AssistantError("no_key", "No API key is set for this provider.",
                             "Set it in Preferences › Assistant.")
    return key


def _tool(public: str, args: dict, back: dict[str, str]) -> dict:
    name = back.get(public)
    if name is None:
        return {"ok": False, "error": {"code": "unknown_tool", "message": f"unknown tool {public}"}}
    try:
        return live.call_tool_sync(name, args or {}, client="assistant")
    except Exception as ex:  # noqa: BLE001  (the model gets an error, the panel keeps working)
        return {"ok": False, "error": {"code": "bridge_error", "message": str(ex)}}


def _summary(public: str, envelope: dict) -> str:
    if not envelope.get("ok"):
        err = envelope.get("error") or {}
        return f"{public}: {err.get('message') or err.get('code') or 'failed'}"
    changes = (envelope.get("changes") or {}).get("counts") or {}
    total = sum(int(changes.get(k, 0) or 0) for k in ("added", "modified", "removed"))
    if total:
        return f"{public}: {total} element(s) changed"
    result = envelope.get("result")
    if isinstance(result, dict):
        for key in ("elements", "items", "count", "message", "path"):
            if key in result and not isinstance(result[key], (dict, list)):
                return f"{public}: {result[key]}"
    return public


def _endpoint(base: str, suffix: str, default: str) -> str:
    """The full endpoint for a base URL that may be a host, a `/v1` root or the endpoint itself."""
    base = (base or default).rstrip("/")
    if base.endswith(suffix):
        return base
    return base + (suffix if base.endswith("/v1") else "/v1" + suffix)


def _call_anthropic(config: dict, messages: list[dict], system: str, schemas: list[dict], back: dict) -> dict:
    key = _key("anthropic")
    url = _endpoint(config.get("base_url") or ANTHROPIC_DEFAULT, "/messages", ANTHROPIC_DEFAULT)
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    model = config.get("model") or "claude-sonnet-4-5"
    used: list[dict] = []
    for _ in range(MAX_STEPS):
        data = _http(url, headers, {"model": model, "max_tokens": 4096, "system": system,
                                    "messages": messages, "tools": schemas})
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        calls = [b for b in blocks if b.get("type") == "tool_use"]
        if not calls:
            return {"text": text, "tool_calls": used}
        messages.append({"role": "assistant", "content": blocks})
        results = []
        for call in calls:
            envelope = _tool(call.get("name", ""), call.get("input") or {}, back)
            used.append({"name": call.get("name", ""), "summary": _summary(call.get("name", ""), envelope),
                         "snapshot": (envelope.get("result") or {}).get("path", "")
                         if call.get("name") == "snapshot_take" else ""})
            results.append({"type": "tool_result", "tool_use_id": call.get("id", ""),
                            "content": json.dumps(envelope, ensure_ascii=False)})
        messages.append({"role": "user", "content": results})
    raise AssistantError("too_many_steps", "The model kept calling tools; stop and ask again.")


def _call_openai(config: dict, messages: list[dict], system: str, schemas: list[dict], back: dict) -> dict:
    key = _key(config.get("provider") or "openai")
    url = _endpoint(config.get("base_url") or OPENAI_DEFAULT, "/chat/completions", OPENAI_DEFAULT)
    headers = {"Authorization": f"Bearer {key}", "content-type": "application/json"}
    model = config.get("model") or "gpt-4o-mini"
    tools = [{"type": "function", "function": {"name": s["name"], "description": s["description"],
                                                "parameters": s["input_schema"]}} for s in schemas]
    thread = [{"role": "system", "content": system}, *messages]
    used: list[dict] = []
    for _ in range(MAX_STEPS):
        data = _http(url, headers, {"model": model, "messages": thread, "tools": tools})
        choices = data.get("choices") or []
        if not choices:
            raise AssistantError("provider_error", "the provider sent no answer")
        message = choices[0].get("message") or {}
        text = (message.get("content") or "").strip()
        calls = message.get("tool_calls") or []
        if not calls:
            return {"text": text, "tool_calls": used}
        thread.append(message)
        for call in calls:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            envelope = _tool(fn.get("name", ""), args, back)
            used.append({"name": fn.get("name", ""), "summary": _summary(fn.get("name", ""), envelope),
                         "snapshot": (envelope.get("result") or {}).get("path", "")
                         if fn.get("name") == "snapshot_take" else ""})
            thread.append({"role": "tool", "tool_call_id": call.get("id", ""),
                           "content": json.dumps(envelope, ensure_ascii=False)})
    raise AssistantError("too_many_steps", "The model kept calling tools; stop and ask again.")


def _dump(data: dict) -> str:
    from .. import app_bridge as B
    return B._dump(data)


def chat(messages_json: str, config_json: str) -> str:
    """Run one turn: `messages` is [{"role","content"}], `config` the provider, model and context."""
    try:
        messages = json.loads(messages_json or "[]")
        config = json.loads(config_json or "{}")
        if not isinstance(messages, list) or not isinstance(config, dict):
            raise AssistantError("bad_input", "messages and config must be a list and an object")
    except ValueError as ex:
        return _dump({"ok": False, "error": {"code": "bad_input", "message": str(ex)}})
    if live._host is None:
        return _dump({"ok": False, "error": {"code": "needs_app", "message": "Open a project in KimBim first."}})
    try:
        schemas, back = _tool_names()
        system = _system(config)
        provider = config.get("provider") or "anthropic"
        if provider == "anthropic":
            answer = _call_anthropic(config, messages, system, schemas, back)
        elif provider == "openai":
            answer = _call_openai(config, messages, system, schemas, back)
        else:
            raise AssistantError("bad_input", f"unknown provider {provider}")
    except AssistantError as ex:
        return _dump({"ok": False, "error": {"code": ex.code, "message": ex.message, "hint": ex.hint}})
    except Exception as ex:  # noqa: BLE001
        return _dump({"ok": False, "error": {"code": "bridge_error", "message": str(ex)}})
    return _dump({"ok": True, "result": answer})


def set_key(provider: str, key: str) -> str:
    from .credentials import KeyStoreError, set_key as store
    try:
        store(provider, key)
    except KeyStoreError as ex:
        return _dump({"ok": False, "error": {"code": "key_store", "message": str(ex)}})
    return _dump({"ok": True})


def clear_key(provider: str) -> str:
    from .credentials import KeyStoreError, clear_key as clear
    try:
        clear(provider)
    except KeyStoreError as ex:
        return _dump({"ok": False, "error": {"code": "key_store", "message": str(ex)}})
    return _dump({"ok": True})


def key_set(provider: str) -> str:
    return _dump({"ok": True, "result": {"set": has_key(provider)}})
