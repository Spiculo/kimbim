# SPDX-License-Identifier: GPL-3.0-or-later
"""The in-app Assistant's model loop (D102 phase 3): the architect's own key, Anthropic or any
OpenAI-compatible endpoint, the same tool catalogue and the same live session as the CLI/MCP.

The panel passes the conversation and its provider settings; this module calls the provider, runs the
tools it asks for through the app's live queue (so every call is one of the app's undo steps), and returns
the final text, compact tool lines and snapshot paths."""
from __future__ import annotations

import inspect
import json
import pathlib
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from . import catalogue, client, live, sessions
from .credentials import KeyStoreError, get_key, has_key
from .messages import text as message_text

ANTHROPIC_DEFAULT = "https://api.anthropic.com"
OPENAI_DEFAULT = "https://api.openai.com/v1"
# The loop has no step cap: a legitimate task may need many calls. It stops only when the model repeats
# rounds that add no new call, so a stuck model cannot loop forever (the architect sees every step anyway).
STALL_ROUNDS = 3


# ---------------------------------------------------------------- progress of a turn
#
# The panel polls `progress` while `chat` runs on its own thread, so the architect sees what the model is
# doing as it happens: the text it writes before a tool call, each call's compact summary and snapshot.

_progress_lock = threading.Lock()
_progress_turn = 0
_progress_seq = 0
_progress_entries: list[dict] = []
_progress_done = True

# The stored session the running turn writes to (D111): its transcript gets every message and tool line.
_tx = threading.local()


def _record(entry: dict) -> None:
    store, session_id = getattr(_tx, "store", None), getattr(_tx, "id", "")
    if store is not None and session_id:
        try:
            store.append(session_id, entry)
        except OSError:
            pass  # a full disk must not stop the answer


def _start_turn() -> int:
    global _progress_turn, _progress_seq, _progress_done
    with _progress_lock:
        _progress_turn += 1
        _progress_seq = 0
        _progress_entries.clear()
        _progress_done = False
        return _progress_turn


def _ensure_turn() -> int:
    """The panel's turn when it called `begin`; a fresh one when chat is called on its own."""
    with _progress_lock:
        active = not _progress_done
    return _progress_turn if active else _start_turn()


def _emit(kind: str, **fields) -> None:
    global _progress_seq
    with _progress_lock:
        if _progress_done:
            return
        _progress_seq += 1
        _progress_entries.append({"seq": _progress_seq, "kind": kind, **fields})
    # D111: the transcript keeps what the architect saw, not only the model's messages
    text = str(fields.get("text") or "").strip()
    if kind == "message" and text:
        _record({"role": "assistant", "text": text})
    elif kind == "status" and text:
        _record({"role": "status", "text": text})


def _end_turn() -> None:
    global _progress_done
    with _progress_lock:
        _progress_done = True


def begin() -> str:
    """Start a turn's progress stream; the panel calls it before launching `chat` on its thread."""
    return _dump({"ok": True, "result": {"turn": _start_turn()}})


def progress(turn: int = 0, since: int = 0) -> str:
    """The entries a running (or just finished) turn added after `since`, and whether it is done."""
    turn, since = int(turn or 0), int(since or 0)
    with _progress_lock:
        if turn and turn != _progress_turn:
            return _dump({"ok": True, "result": {"turn": _progress_turn, "entries": [], "done": True}})
        entries = [dict(e) for e in _progress_entries if e["seq"] > since]
        return _dump({"ok": True, "result": {"turn": _progress_turn, "entries": entries,
                                              "done": _progress_done, "seq": _progress_seq}})


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
    if config.get("project_context"):
        lines.extend(_project_context(config))
    return "\n".join(lines)


def _session_worker(session: str) -> str:
    """The project whose session worker should run this conversation's tools (D111), or "".

    A versioned **folder** session has its own worktree: the app keeps the architect's working copy and the
    session writes through its worker, so the two never touch the same state. A `.kim`/IFC session has no
    second checkout and stays on the live host, as D102 phase 2 did."""
    if not session:
        return ""
    try:
        record = sessions.Store().get(session)
    except (catalogue.AgentError, OSError):
        return ""
    if record.status == "archived" or record.project_kind != "folder":
        return ""
    if not (pathlib.Path(record.project) / ".git" / "HEAD").is_file():
        return ""
    return record.project


def _live_call(name: str, args: dict, session: str = "") -> dict:
    """The live host call; `session` is only passed when the host takes it (test stand-ins may not)."""
    if session:
        try:
            accepts = "session" in inspect.signature(live.call_tool_sync).parameters
        except (TypeError, ValueError):
            accepts = True
        if accepts:
            return live.call_tool_sync(name, args, client="assistant", session=session)
    return live.call_tool_sync(name, args, client="assistant")


def _read_tool(name: str, args: dict, session: str = "") -> dict:
    """A read tool through the app's live queue (the model thread must not touch the model directly)."""
    project = _session_worker(session)
    try:
        if project:
            return client.request(project, name, args, client="assistant", session=session)
        return _live_call(name, args, session)
    except Exception:  # noqa: BLE001  (context is helpful, never fatal)
        return {}


def _save_owner(title: str) -> None:
    """The architect's unsaved work becomes a version before a session branches from it (spec §4.3). It
    runs on the live host, not in the session's worktree."""
    try:
        live.call_tool_sync("_owner_save", {"message": f"Before agent: {title}".strip()}, client="assistant")
    except Exception:  # noqa: BLE001  (a read-only window has no unsaved work to keep, and must not block)
        pass


_last_state: dict[str, dict] = {}


def _state_of(session: str) -> dict:
    info = _read_tool("project.info", {}, session)
    result = info.get("result") if info.get("ok") else None
    result = result if isinstance(result, dict) else {}
    versions = []
    if result.get("versioned"):
        log = _read_tool("versions.log", {"limit": 5}, session)
        versions = ((log.get("result") or {}) if log.get("ok") else {}).get("versions") or []
    return {"option": result.get("option", ""), "unsaved": bool(result.get("unsaved")),
            "counts": result.get("counts") or {}, "levels": len(result.get("levels") or []),
            "head": (versions[0].get("id", "") if versions else ""), "versions": versions}


def _project_context(config: dict) -> list[str]:
    """Current project state and what changed since the previous turn. The architect edits between
    messages; without this the model reads its earlier answer as a mistake instead of a changed model."""
    session = str(config.get("session") or "assistant")
    state = _state_of(session)
    previous = _last_state.get(session)
    lines = ["Current project state (the architect may change it between messages; these are the current values):"]
    lines.append(f"- option: {state['option'] or '(none)'}; unsaved changes: {'yes' if state['unsaved'] else 'no'}"
                 f"; levels: {state['levels']}")
    if state["versions"]:
        lines.append("- recent versions (newest first): " + "; ".join(
            f"{v.get('short') or str(v.get('id', ''))[:8]} {str(v.get('message', '')).split(chr(10))[0]}"
            for v in state["versions"][:5]))
    counts = {k: v for k, v in (state["counts"] or {}).items() if v}
    if counts:
        lines.append("- elements: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if previous is not None:
        changes = []
        if previous.get("option") != state["option"]:
            changes.append(f"option {previous.get('option') or '(none)'} -> {state['option'] or '(none)'}")
        if previous.get("head") != state["head"] and state["head"]:
            changes.append("a newer version is saved")
        if previous.get("unsaved") != state["unsaved"]:
            changes.append("unsaved changes " + ("started" if state["unsaved"] else "were saved or discarded"))
        old, new = previous.get("counts") or {}, state["counts"] or {}
        for kind in sorted(set(old) | set(new)):
            if old.get(kind, 0) != new.get(kind, 0):
                changes.append(f"{kind} {old.get(kind, 0)} -> {new.get(kind, 0)}")
        if changes:
            lines.append("Since your previous answer the project changed: " + "; ".join(changes) + ".")
            lines.append("Do not treat your earlier numbers as wrong: the model changed. Say what changed and "
                         "use the current values (re-read with a tool if you need the details).")
    lines.append("If a count differs from what you said before, check the current state with a tool before answering.")
    return lines


def _remember_state(config: dict) -> None:
    """Store the state at the end of the turn, so the next turn's delta is what changed between turns."""
    session = str(config.get("session") or "assistant")
    _last_state[session] = _state_of(session)


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


def _tool(public: str, args: dict, back: dict[str, str], session: str = "") -> dict:
    name = back.get(public)
    if name is None:
        return {"ok": False, "error": {"code": "unknown_tool", "message": f"unknown tool {public}"}}
    project = _session_worker(session)
    if project and name == "task.start":
        _save_owner(str((args or {}).get("title") or ""))
    try:
        if project:
            return client.request(project, name, args or {}, client="assistant", session=session)
        return _live_call(name, args or {}, session)
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


def _run_call(public: str, args: dict, back: dict[str, str], used: list[dict], session: str = "") -> dict:
    """Run one tool call and show it in the turn's progress stream (the panel renders it at once)."""
    envelope = _tool(public, args, back, session)
    result = envelope.get("result")
    entry = {"name": public, "summary": _summary(public, envelope), "ok": bool(envelope.get("ok")),
             "snapshot": str(result.get("path") or "") if public == "snapshot_take" and isinstance(result, dict)
             else ""}
    used.append(entry)
    _emit("tool", **entry)
    store, session_id = getattr(_tx, "store", None), getattr(_tx, "id", "")
    if store is not None and session_id:
        kept = entry["snapshot"]
        if kept:  # the snapshot's temp path may go: keep the bytes with the session (D111)
            try:
                kept = store.attachment(session_id, kept)
            except OSError:
                kept = entry["snapshot"]
        try:
            store.record_tool(session_id, public, entry["summary"], entry["ok"], kept, result)
        except OSError:
            pass
    return envelope


def _signature(public: str, args: dict) -> str:
    return public + "|" + json.dumps(args or {}, sort_keys=True, ensure_ascii=False, default=str)


def _stall_count(calls: list[tuple[str, dict]], seen: set[str], stalled: int) -> int:
    """Count consecutive rounds whose calls all appeared before: a model that repeats is stuck."""
    signatures = [_signature(name, args) for name, args in calls]
    stalled = stalled + 1 if signatures and all(s in seen for s in signatures) else 0
    seen.update(signatures)
    return stalled


def _endpoint(base: str, suffix: str, default: str) -> str:
    """The full endpoint for a configured URL: a host, a `/v1` root, or the endpoint itself (with an
    optional query such as Azure's `?api-version=`). Never appends the path twice."""
    parts = urlsplit((base or default).strip())
    path = parts.path.rstrip("/")
    if not path.endswith(suffix):
        path += suffix if path.endswith("/v1") else "/v1" + suffix
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _call_anthropic(config: dict, messages: list[dict], system: str, schemas: list[dict], back: dict) -> dict:
    key = _key("anthropic")
    url = _endpoint(config.get("base_url") or ANTHROPIC_DEFAULT, "/messages", ANTHROPIC_DEFAULT)
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    model = config.get("model") or "claude-sonnet-4-5"
    session = str(config.get("session") or "")
    used: list[dict] = []
    seen: set[str] = set()
    stalled = 0
    while True:
        data = _http(url, headers, {"model": model, "max_tokens": 4096, "system": system,
                                    "messages": messages, "tools": schemas})
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        calls = [b for b in blocks if b.get("type") == "tool_use"]
        if not calls:
            return {"text": text, "tool_calls": used}
        stalled = _stall_count([(c.get("name", ""), c.get("input") or {}) for c in calls], seen, stalled)
        if stalled >= STALL_ROUNDS:
            _emit("status", text=message_text("progress_stalled"))
            return {"text": "", "tool_calls": used, "stopped": "stalled"}
        if text:  # what the model says before a call: show it, don't fold it into the answer
            _emit("message", text=text)
        messages.append({"role": "assistant", "content": blocks})
        results = []
        for call in calls:
            envelope = _run_call(call.get("name", ""), call.get("input") or {}, back, used, session)
            results.append({"type": "tool_result", "tool_use_id": call.get("id", ""),
                            "content": json.dumps(envelope, ensure_ascii=False)})
        messages.append({"role": "user", "content": results})


def _responses_url(base: str) -> str:
    """The `/responses` sibling of the configured Chat Completions URL (keeping a query string)."""
    parts = urlsplit((base or OPENAI_DEFAULT).strip())
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    if not path.endswith("/v1"):
        path += "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path + "/responses", parts.query, parts.fragment))


def _openai_chat(key: str, config: dict, messages: list[dict], system: str, schemas: list[dict],
                 back: dict, used: list[dict]) -> dict:
    url = _endpoint(config.get("base_url") or OPENAI_DEFAULT, "/chat/completions", OPENAI_DEFAULT)
    headers = {"Authorization": f"Bearer {key}", "content-type": "application/json"}
    model = config.get("model") or "gpt-4o-mini"
    session = str(config.get("session") or "")
    tools = [{"type": "function", "function": {"name": s["name"], "description": s["description"],
                                                "parameters": s["input_schema"]}} for s in schemas]
    thread = [{"role": "system", "content": system}, *messages]
    seen: set[str] = set()
    stalled = 0
    while True:
        data = _http(url, headers, {"model": model, "messages": thread, "tools": tools})
        choices = data.get("choices") or []
        if not choices:
            raise AssistantError("provider_error", "the provider sent no answer")
        message = choices[0].get("message") or {}
        text = (message.get("content") or "").strip()
        calls = message.get("tool_calls") or []
        if not calls:
            return {"text": text, "tool_calls": used}
        parsed = []
        for call in calls:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            parsed.append((fn.get("name", ""), args))
        stalled = _stall_count(parsed, seen, stalled)
        if stalled >= STALL_ROUNDS:
            _emit("status", text=message_text("progress_stalled"))
            return {"text": "", "tool_calls": used, "stopped": "stalled"}
        if text:
            _emit("message", text=text)
        thread.append(message)
        for call, (name, args) in zip(calls, parsed):
            envelope = _run_call(name, args, back, used, session)
            thread.append({"role": "tool", "tool_call_id": call.get("id", ""),
                           "content": json.dumps(envelope, ensure_ascii=False)})


def _openai_responses(key: str, config: dict, messages: list[dict], system: str, schemas: list[dict],
                      back: dict, used: list[dict]) -> dict:
    """The OpenAI Responses API, whose tools work with reasoning models that reject Chat Completions tools."""
    url = _responses_url(config.get("base_url") or OPENAI_DEFAULT)
    headers = {"Authorization": f"Bearer {key}", "content-type": "application/json"}
    model = config.get("model") or "gpt-4o-mini"
    session = str(config.get("session") or "")
    tools = [{"type": "function", "name": s["name"], "description": s["description"],
              "parameters": s["input_schema"]} for s in schemas]
    items = [{"role": "system", "content": system}, *messages]
    seen: set[str] = set()
    stalled = 0
    while True:
        data = _http(url, headers, {"model": model, "input": items, "tools": tools})
        output = data.get("output") or []
        text = "".join(part.get("text", "") for item in output if item.get("type") == "message"
                       for part in (item.get("content") or []) if part.get("type") == "output_text").strip()
        calls = [item for item in output if item.get("type") == "function_call"]
        if not calls:
            return {"text": text, "tool_calls": used}
        parsed = []
        for call in calls:
            try:
                args = json.loads(call.get("arguments") or "{}")
            except ValueError:
                args = {}
            parsed.append((call.get("name", ""), args))
        stalled = _stall_count(parsed, seen, stalled)
        if stalled >= STALL_ROUNDS:
            _emit("status", text=message_text("progress_stalled"))
            return {"text": "", "tool_calls": used, "stopped": "stalled"}
        if text:
            _emit("message", text=text)
        items.extend(output)
        for call, (name, args) in zip(calls, parsed):
            envelope = _run_call(name, args, back, used, session)
            items.append({"type": "function_call_output", "call_id": call.get("call_id", ""),
                          "output": json.dumps(envelope, ensure_ascii=False)})


def _call_openai(config: dict, messages: list[dict], system: str, schemas: list[dict], back: dict) -> dict:
    key = _key(config.get("provider") or "openai")
    used: list[dict] = []
    try:
        return _openai_chat(key, config, messages, system, schemas, back, used)
    except AssistantError as ex:
        # Some reasoning models refuse tools on Chat Completions and name the Responses API in the error.
        # Only before any call has run: re-running a half-done conversation would repeat its changes.
        text = ex.message.lower()
        if ex.code == "provider_error" and not used and ("/v1/responses" in text or "reasoning_effort" in text):
            return _openai_responses(key, config, messages, system, schemas, back, used)
        raise


def _dump(data: dict) -> str:
    from .. import app_bridge as B
    return B._dump(data)


def _open_transcript(config: dict, messages: list[dict]) -> None:
    """D111: bind this turn to its stored session and record the architect's message once."""
    session_id = str(config.get("session") or "")
    if not session_id:
        return
    try:
        store = sessions.Store()
        record = store.get(session_id)
    except (catalogue.AgentError, OSError):
        return
    if record.status == "archived":
        return
    try:
        store.update(session_id, provider=str(config.get("provider") or record.provider),
                     model=str(config.get("model") or record.model))
    except OSError:
        pass
    _tx.store, _tx.id = store, session_id
    prompt = next((str(m.get("content") or "").strip() for m in reversed(messages)
                   if isinstance(m, dict) and m.get("role") == "user"), "")
    if prompt:
        history = store.transcript(session_id, limit=1)
        if not history or history[-1].get("role") != "user" or history[-1].get("text") != prompt:
            store.append(session_id, {"role": "user", "text": prompt})


def chat(messages_json: str, config_json: str) -> str:
    """Run one turn: `messages` is [{"role","content"}], `config` the provider, model and context."""
    _ensure_turn()
    config: dict = {}
    try:
        try:
            messages = json.loads(messages_json or "[]")
            config = json.loads(config_json or "{}")
            if not isinstance(messages, list) or not isinstance(config, dict):
                raise AssistantError("bad_input", "messages and config must be a list and an object")
        except ValueError as ex:
            return _dump({"ok": False, "error": {"code": "bad_input", "message": str(ex)}})
        if live._host is None:
            return _dump({"ok": False, "error": {"code": "needs_app", "message": "Open a project in KimBim first."}})
        session_id = str(config.get("session") or "")
        if session_id:
            try:
                if sessions.Store().get(session_id).status == "archived":
                    raise catalogue.AgentError("session_archived", session=session_id)
            except catalogue.AgentError as ex:
                return _dump(ex.envelope())
            except OSError:
                pass
        _open_transcript(config, messages)
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
            _record({"role": "status", "text": f"{ex.message} {ex.hint}".strip()})
            return _dump({"ok": False, "error": {"code": ex.code, "message": ex.message, "hint": ex.hint}})
        except Exception as ex:  # noqa: BLE001
            _record({"role": "status", "text": str(ex)})
            return _dump({"ok": False, "error": {"code": "bridge_error", "message": str(ex)}})
        text = str(answer.get("text") or "").strip()
        if text:
            _record({"role": "assistant", "text": text})
        elif answer.get("stopped"):
            _record({"role": "status", "text": message_text("progress_stalled")})
        return _dump({"ok": True, "result": answer})
    finally:
        if config.get("project_context") and live._host is not None:
            _remember_state(config)
        _tx.store, _tx.id = None, ""
        _end_turn()


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
