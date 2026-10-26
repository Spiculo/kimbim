# SPDX-License-Identifier: GPL-3.0-or-later
"""`kimbim setup claude-desktop|claude-code|opencode` (D102, spec §7): the client's MCP configuration is merged into
its existing file, never replacing it. Every config location points into tmp_path (no real client config is touched)."""
import json
import sys
from pathlib import Path

import pytest

from kimbim.agent import clients
from kimbim.cli import main

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """APPDATA, the home folder and XDG_CONFIG_HOME all inside tmp_path."""
    h = tmp_path / "home"
    (h / "AppData").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(h / "AppData"))
    monkeypatch.setenv("USERPROFILE", str(h))
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(h / ".config"))
    monkeypatch.chdir(tmp_path)
    return h


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    kim = folder / "house.kim"
    kim.write_bytes(b"")
    return kim


def _command_ok(command: list[str], kim: Path | None):
    assert command[0] == sys.executable and Path(command[0]).is_absolute()
    assert command[1:4] == ["-m", "kimbim", "mcp"]
    if kim is not None:
        assert command[4:] == ["--project", str(kim.resolve())]


def _env_ok(env: dict):
    # a development checkout isn't installed: the package's folder goes on PYTHONPATH
    assert str(ROOT / "python") in env.get("PYTHONPATH", "").split(";" if sys.platform == "win32" else ":")


def test_paths_stay_in_tmp(home, project):
    assert clients.config_path("claude-desktop", None).is_relative_to(home)
    assert clients.config_path("claude-code", project) == project.parent / ".mcp.json"
    assert clients.config_path("opencode", project) == project.parent / "opencode.json"
    assert clients.config_path("opencode", None).is_relative_to(home)


def test_setup_merges_existing_claude_desktop(home, project, capsys):
    path = clients.config_path("claude-desktop", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    other = {"command": "npx", "args": ["other-server"]}
    path.write_text(json.dumps({"mcpServers": {"other": other}, "globalShortcut": "Ctrl+Space"}), encoding="utf-8")
    assert main(["setup", "claude-desktop", "--project", str(project)]) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"] == other
    assert data["globalShortcut"] == "Ctrl+Space"
    entry = data["mcpServers"]["kimbim"]
    _command_ok([entry["command"], *entry["args"]], project)
    _env_ok(entry["env"])
    assert str(path) in capsys.readouterr().out
    # a second run updates its own entry and keeps the rest
    assert main(["setup", "claude-desktop"]) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["mcpServers"]) == {"other", "kimbim"}
    _command_ok([data["mcpServers"]["kimbim"]["command"], *data["mcpServers"]["kimbim"]["args"]], None)
    assert data["mcpServers"]["kimbim"]["args"] == ["-m", "kimbim", "mcp"]


def test_setup_creates_claude_desktop(home):
    assert main(["setup", "claude-desktop"]) == 0
    data = json.loads(clients.config_path("claude-desktop", None).read_text(encoding="utf-8"))
    assert list(data["mcpServers"]) == ["kimbim"]


def test_setup_merges_existing_claude_code(home, project):
    path = project.parent / ".mcp.json"
    other = {"type": "stdio", "command": "uvx", "args": ["x"]}
    path.write_text(json.dumps({"mcpServers": {"other": other}}), encoding="utf-8")
    assert main(["setup", "claude-code", "--project", str(project)]) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"] == other
    entry = data["mcpServers"]["kimbim"]
    assert entry["type"] == "stdio"
    _command_ok([entry["command"], *entry["args"]], project)
    _env_ok(entry["env"])


def test_setup_claude_code_print(home, project, capsys):
    assert main(["setup", "claude-code", "--project", str(project), "--print"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("claude mcp add")
    assert " kimbim " in out and "-m kimbim mcp --project" in out and "PYTHONPATH=" in out
    assert not (project.parent / ".mcp.json").exists()  # --print writes nothing


def test_setup_merges_existing_opencode(home, project):
    path = project.parent / "opencode.json"
    path.write_text(json.dumps({"$schema": "https://opencode.ai/config.json", "model": "x/y",
                                "mcp": {"other": {"type": "remote", "url": "https://example.test/mcp"}}}),
                    encoding="utf-8")
    agents = project.parent / "AGENTS.md"
    agents.write_text("# My project\n\nKeep this.\n", encoding="utf-8")
    assert main(["setup", "opencode", "--project", str(project)]) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "x/y" and data["mcp"]["other"]["url"] == "https://example.test/mcp"
    entry = data["mcp"]["kimbim"]
    assert entry["type"] == "local" and entry["enabled"] is True
    _command_ok(entry["command"], project)
    _env_ok(entry["environment"])
    text = agents.read_text(encoding="utf-8")
    assert text.startswith("# My project\n\nKeep this.\n")
    assert "kimbim" in text and text.count(clients.AGENTS_START) == 1
    # idempotent: a second run replaces its own section
    assert main(["setup", "opencode", "--project", str(project)]) == 0
    assert agents.read_text(encoding="utf-8") == text


def test_setup_opencode_global_writes_no_agents_md(home, tmp_path):
    assert main(["setup", "opencode"]) == 0
    path = clients.config_path("opencode", None)
    assert json.loads(path.read_text(encoding="utf-8"))["mcp"]["kimbim"]["type"] == "local"
    assert not (tmp_path / "AGENTS.md").exists()


def test_setup_print_writes_nothing(home, project, capsys):
    assert main(["setup", "claude-desktop", "--print"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert "kimbim" in printed["mcpServers"]
    assert not clients.config_path("claude-desktop", None).exists()
    assert main(["setup", "opencode", "--project", str(project), "--print"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["mcp"]["kimbim"]["type"] == "local"
    assert not (project.parent / "opencode.json").exists() and not (project.parent / "AGENTS.md").exists()


def test_setup_refuses_a_broken_file(home, project, capsys):
    path = project.parent / ".mcp.json"
    path.write_text("{ not json", encoding="utf-8")
    assert main(["setup", "claude-code", "--project", str(project)]) == 1
    assert path.read_text(encoding="utf-8") == "{ not json"  # left as it was
    assert "kimbim: error" in capsys.readouterr().err
