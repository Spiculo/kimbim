# SPDX-License-Identifier: GPL-3.0-or-later
"""D102 phase 3: API keys in the OS credential store and the Assistant's provider loop."""
import json
import os
import uuid

import pytest

from kimbim.agent import assistant, credentials


@pytest.mark.skipif(os.name != "nt", reason="the credential store test is for Windows")
def test_credentials_round_trip():
    provider = "kimbim-test-" + uuid.uuid4().hex
    try:
        credentials.clear_key(provider)
        assert not credentials.has_key(provider)
        credentials.set_key(provider, "sk-test-123")
        assert credentials.get_key(provider) == "sk-test-123"
        assert credentials.has_key(provider)
        credentials.clear_key(provider)
        assert not credentials.has_key(provider)
    finally:
        credentials.clear_key(provider)


@pytest.fixture(autouse=True)
def _fresh_turn():
    assistant._end_turn()
    yield
    assistant._end_turn()


def _fake_live(monkeypatch, result=None):
    monkeypatch.setattr(assistant.live, "_host", object())
    monkeypatch.setattr(assistant, "get_key", lambda provider: "sk-test")
    calls = []

    def run_tool(name, args, client="assistant"):
        calls.append((name, args))
        return result or {"ok": True, "result": {"elements": 8}, "changes": {"counts": {"modified": 8}}}

    monkeypatch.setattr(assistant.live, "call_tool_sync", run_tool)
    return calls


def test_openai_tool_loop(monkeypatch):
    calls = _fake_live(monkeypatch)
    replies = [
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [{"id": "c1", "type": "function", "function": {
                                      "name": "elements_find", "arguments": "{\"elements\":{\"kind\":\"wall\"}}"}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "Found the walls."}}]},
    ]
    monkeypatch.setattr(assistant, "_http", lambda *a, **k: replies.pop(0))
    out = json.loads(assistant.chat('[{"role":"user","content":"find walls"}]',
                                    '{"provider":"openai","model":"m","base_url":"https://example.test/v1"}'))
    assert out["ok"], out
    assert out["result"]["text"] == "Found the walls."
    assert out["result"]["tool_calls"][0]["name"] == "elements_find"
    assert calls == [("elements.find", {"elements": {"kind": "wall"}})]


def test_anthropic_tool_loop(monkeypatch):
    calls = _fake_live(monkeypatch)
    replies = [
        {"content": [{"type": "text", "text": "Let me check."},
                     {"type": "tool_use", "id": "t1", "name": "project_info", "input": {}}]},
        {"content": [{"type": "text", "text": "The project has 8 walls."}]},
    ]
    monkeypatch.setattr(assistant, "_http", lambda *a, **k: replies.pop(0))
    out = json.loads(assistant.chat('[{"role":"user","content":"how many walls?"}]',
                                    '{"provider":"anthropic","model":"claude"}'))
    assert out["ok"], out
    assert out["result"]["text"] == "The project has 8 walls."
    assert calls == [("project.info", {})]


def test_the_tool_loop_has_no_step_cap(monkeypatch):
    calls = _fake_live(monkeypatch)
    replies = []
    for i in range(12):
        replies.append({"choices": [{"message": {"role": "assistant", "content": "",
                                                 "tool_calls": [{"id": f"c{i}", "type": "function", "function": {
                                                     "name": "elements_find",
                                                     "arguments": json.dumps({"elements": {"kind": "wall"},
                                                                              "limit": i + 1})}}]}}]})
    replies.append({"choices": [{"message": {"role": "assistant", "content": "All done."}}]})
    monkeypatch.setattr(assistant, "_http", lambda *a, **k: replies.pop(0))
    out = json.loads(assistant.chat('[{"role":"user","content":"keep going"}]',
                                    '{"provider":"openai","model":"m"}'))
    assert out["ok"], out
    assert out["result"]["text"] == "All done."
    assert len(calls) == 12
    assert len(out["result"]["tool_calls"]) == 12


def test_a_repeated_call_stops_instead_of_looping(monkeypatch):
    calls = _fake_live(monkeypatch)
    reply = {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c", "type": "function", "function": {
            "name": "elements_find", "arguments": "{\"elements\": {\"kind\": \"wall\"}}"}}]}}]}
    monkeypatch.setattr(assistant, "_http", lambda *a, **k: reply)
    out = json.loads(assistant.chat('[{"role":"user","content":"loop"}]', '{"provider":"openai","model":"m"}'))
    assert out["ok"], out
    assert out["result"]["stopped"] == "stalled"
    assert len(calls) == assistant.STALL_ROUNDS
    entries = json.loads(assistant.progress())["result"]["entries"]
    assert any(entry["kind"] == "status" for entry in entries)


def test_progress_shows_the_model_text_and_each_call(monkeypatch):
    _fake_live(monkeypatch)
    replies = [
        {"content": [{"type": "text", "text": "I will look at the model."},
                     {"type": "tool_use", "id": "t1", "name": "project_info", "input": {}}]},
        {"content": [{"type": "text", "text": "There are eight walls."}]},
    ]
    monkeypatch.setattr(assistant, "_http", lambda *a, **k: replies.pop(0))
    turn = json.loads(assistant.begin())["result"]["turn"]
    out = json.loads(assistant.chat('[{"role":"user","content":"how many walls?"}]',
                                    '{"provider":"anthropic","model":"claude"}'))
    assert out["ok"], out
    result = json.loads(assistant.progress(str(turn), "0"))["result"]
    assert result["done"] is True
    assert [entry["kind"] for entry in result["entries"]] == ["message", "tool"]
    assert result["entries"][0]["text"] == "I will look at the model."
    assert result["entries"][1]["summary"].startswith("project_info")
    # A poll for an older turn does not show another turn's steps.
    assert json.loads(assistant.progress(str(turn - 1), "0"))["result"]["entries"] == []


def test_progress_carries_a_snapshot_path(monkeypatch):
    _fake_live(monkeypatch, {"ok": True, "result": {"path": "C:/tmp/shot.png"}})
    replies = [
        {"content": [{"type": "tool_use", "id": "t1", "name": "snapshot_take", "input": {}}]},
        {"content": [{"type": "text", "text": "A picture."}]},
    ]
    monkeypatch.setattr(assistant, "_http", lambda *a, **k: replies.pop(0))
    turn = json.loads(assistant.begin())["result"]["turn"]
    out = json.loads(assistant.chat('[{"role":"user","content":"show me"}]',
                                    '{"provider":"anthropic","model":"claude"}'))
    assert out["ok"], out
    entries = json.loads(assistant.progress(str(turn), "0"))["result"]["entries"]
    tool = next(entry for entry in entries if entry["kind"] == "tool")
    assert tool["snapshot"] == "C:/tmp/shot.png"


def test_project_context_reports_what_changed_since_the_last_turn(monkeypatch):
    counts = {"windows": 12}

    def read_tool(name, args, client="assistant"):
        if name == "project.info":
            return {"ok": True, "result": {"counts": dict(counts), "option": "main", "versioned": True,
                                            "unsaved": True, "levels": [{"name": "Level 1"}]}}
        if name == "versions.log":
            return {"ok": True, "result": {"versions": [{"id": "abcdef123456", "short": "abcdef12",
                                                          "message": "Start"}]}}
        return {"ok": True, "result": {}}

    monkeypatch.setattr(assistant.live, "call_tool_sync", read_tool)
    assistant._last_state.clear()
    config = {"project_context": True, "session": "test-session"}
    first = "\n".join(assistant._project_context(config))
    assert "windows 12" in first and "recent versions" in first
    assistant._remember_state(config)
    counts["windows"] = 15
    second = "\n".join(assistant._project_context(config))
    assert "windows 12 -> 15" in second
    assert "Since your previous answer" in second


def test_assistant_without_a_key(monkeypatch):
    _fake_live(monkeypatch)
    monkeypatch.setattr(assistant, "get_key", lambda provider: "")
    out = json.loads(assistant.chat('[{"role":"user","content":"hi"}]', '{"provider":"anthropic"}'))
    assert not out["ok"] and out["error"]["code"] == "no_key"

@pytest.mark.parametrize("base,want", [
    ("https://api.openai.com/v1", "https://api.openai.com/v1/chat/completions"),
    ("https://api.openai.com/v1/chat/completions", "https://api.openai.com/v1/chat/completions"),
    ("https://api.deepseek.com", "https://api.deepseek.com/v1/chat/completions"),
    ("https://openrouter.ai/api/v1/", "https://openrouter.ai/api/v1/chat/completions"),
])
def test_openai_endpoint_is_not_duplicated(monkeypatch, base, want):
    _fake_live(monkeypatch)
    seen = []
    monkeypatch.setattr(assistant, "_http", lambda url, headers, body: (
        seen.append(url), {"choices": [{"message": {"role": "assistant", "content": "ok"}}]})[1])
    out = json.loads(assistant.chat('[{"role":"user","content":"hi"}]',
                                    json.dumps({"provider": "openai", "model": "m", "base_url": base})))
    assert out["ok"], out
    assert seen == [want]


@pytest.mark.parametrize("base,want", [
    ("https://api.anthropic.com", "https://api.anthropic.com/v1/messages"),
    ("https://api.anthropic.com/v1", "https://api.anthropic.com/v1/messages"),
    ("https://api.anthropic.com/v1/messages", "https://api.anthropic.com/v1/messages"),
])
def test_anthropic_endpoint_is_not_duplicated(monkeypatch, base, want):
    _fake_live(monkeypatch)
    seen = []
    monkeypatch.setattr(assistant, "_http", lambda url, headers, body: (
        seen.append(url), {"content": [{"type": "text", "text": "ok"}]})[1])
    out = json.loads(assistant.chat('[{"role":"user","content":"hi"}]',
                                    json.dumps({"provider": "anthropic", "model": "m", "base_url": base})))
    assert out["ok"], out
    assert seen == [want]

@pytest.mark.parametrize("base,want", [
    ("https://provider.example/v1/chat/completions?api-version=2024-10-21",
     "https://provider.example/v1/chat/completions?api-version=2024-10-21"),
    ("https://provider.example/v1/?api-version=2024-10-21",
     "https://provider.example/v1/chat/completions?api-version=2024-10-21"),
])
def test_openai_endpoint_keeps_a_query(monkeypatch, base, want):
    _fake_live(monkeypatch)
    seen = []
    monkeypatch.setattr(assistant, "_http", lambda url, headers, body: (
        seen.append(url), {"choices": [{"message": {"role": "assistant", "content": "ok"}}]})[1])
    out = json.loads(assistant.chat('[{"role":"user","content":"hi"}]',
                                    json.dumps({"provider": "openai", "model": "m", "base_url": base})))
    assert out["ok"], out
    assert seen == [want]

def test_openai_falls_back_to_responses_for_reasoning_models(monkeypatch):
    calls = _fake_live(monkeypatch)
    urls = []

    def http(url, headers, body):
        urls.append(url)
        if "/chat/completions" in url:
            raise assistant.AssistantError(
                "provider_error", "Function tools with reasoning_effort are not supported; use /v1/responses")
        if len(urls) == 2:
            return {"output": [{"type": "function_call", "call_id": "c1", "name": "project_info", "arguments": "{}"}]}
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "done"}]}]}

    monkeypatch.setattr(assistant, "_http", http)
    out = json.loads(assistant.chat('[{"role":"user","content":"hi"}]',
                                    json.dumps({"provider": "openai", "model": "gpt-6-luna",
                                                "base_url": "https://provider.example/v1/chat/completions?api-version=1"})))
    assert out["ok"], out
    assert out["result"]["text"] == "done"
    assert urls[0] == "https://provider.example/v1/chat/completions?api-version=1"
    assert urls[1] == "https://provider.example/v1/responses?api-version=1"
    assert calls == [("project.info", {})]
