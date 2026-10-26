# SPDX-License-Identifier: GPL-3.0-or-later
"""`kimbim setup claude-desktop|claude-code|opencode [--project P] [--print]` (D102, spec §7): the AI client's
configuration for `kimbim mcp`, merged into its existing file (other servers and settings are kept; a file that
isn't valid JSON is left alone and reported).

The command is the running interpreter, by absolute path, with `-m kimbim mcp [--project P]`. A development
checkout isn't installed, so its `python` folder goes in the server's environment as PYTHONPATH (the pixi env's own
folders are put on PATH by `kimbim/__main__.py`, so the env's python runs without activation).

- Claude Desktop: `claude_desktop_config.json` in `%APPDATA%/Claude` (Windows), `~/Library/Application
  Support/Claude` (macOS) or `$XDG_CONFIG_HOME/Claude` (`~/.config/Claude`), key `mcpServers.kimbim`.
- Claude Code: `.mcp.json` in the project's folder (the current folder without --project), `mcpServers.kimbim`;
  `--print` prints the `claude mcp add` line instead. With --project, the same marked section as opencode's goes
  in the folder's CLAUDE.md.
- opencode: `opencode.json` in the project's folder (`$XDG_CONFIG_HOME/opencode/opencode.json` without --project),
  `mcp.kimbim` = `{"type": "local", "command": [...]}`; with --project, a marked section in the folder's AGENTS.md
  tells the agent the `kimbim` command line exists (replaced, not repeated, on the next run)."""
from __future__ import annotations

import json
import os
import pathlib
import shlex
import site
import subprocess
import sys

CLIENTS = ("claude-desktop", "claude-code", "opencode")
SERVER = "kimbim"
AGENTS_START = "<!-- kimbim:start -->"
AGENTS_END = "<!-- kimbim:end -->"
INSTRUCTIONS = {"opencode": "AGENTS.md", "claude-code": "CLAUDE.md"}  # the file each client reads its instructions from


class SetupError(Exception):
    pass


# ---------------------------------------------------------------- the server command

def package_root() -> pathlib.Path:
    """The folder that holds the `kimbim` package (python/ in a development checkout)."""
    return pathlib.Path(__file__).resolve().parents[2]


def _same(a: pathlib.Path, b: str) -> bool:
    try:
        return a == pathlib.Path(b).resolve()
    except OSError:
        return False


def installed() -> bool:
    """True when the package is importable without help (in site-packages)."""
    folders = list(site.getsitepackages()) + [site.getusersitepackages()]
    return any(_same(package_root(), f) for f in folders)


def server_command(project: str | None) -> tuple[list[str], dict]:
    """The command line that starts `kimbim mcp` and the environment it needs."""
    command = [str(pathlib.Path(sys.executable).resolve()), "-m", "kimbim", "mcp"]
    if project:
        command += ["--project", str(pathlib.Path(project).resolve())]
    env = {} if installed() else {"PYTHONPATH": str(package_root())}
    return command, env


def project_folder(project: str | None) -> pathlib.Path:
    if not project:
        return pathlib.Path.cwd()
    p = pathlib.Path(project).resolve()
    return p if p.is_dir() else p.parent


# ---------------------------------------------------------------- where each client keeps its configuration

def _config_home() -> pathlib.Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return pathlib.Path(xdg) if xdg else pathlib.Path.home() / ".config"


def config_path(client: str, project: str | None) -> pathlib.Path:
    if client == "claude-desktop":
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            base = pathlib.Path(appdata) if appdata else pathlib.Path.home() / "AppData" / "Roaming"
        elif sys.platform == "darwin":
            base = pathlib.Path.home() / "Library" / "Application Support"
        else:
            base = _config_home()
        return base / "Claude" / "claude_desktop_config.json"
    if client == "claude-code":
        return project_folder(project) / ".mcp.json"
    if client == "opencode":
        return project_folder(project) / "opencode.json" if project else _config_home() / "opencode" / "opencode.json"
    raise SetupError(f"unknown client {client}")


def snippet(client: str, project: str | None) -> dict:
    """The client's configuration for the kimbim server, under its top-level key."""
    command, env = server_command(project)
    if client == "opencode":
        entry = {"type": "local", "command": command, "enabled": True}
        if env:
            entry["environment"] = env
        return {"mcp": {SERVER: entry}}
    entry = {"command": command[0], "args": command[1:]}
    if client == "claude-code":
        entry = {"type": "stdio", **entry}
    if env:
        entry["env"] = env
    return {"mcpServers": {SERVER: entry}}


def merged(path: pathlib.Path, part: dict) -> dict:
    """The file at `path` with `part`'s server entries put in (other keys and servers kept)."""
    data: dict = {}
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8-sig")
            data = json.loads(text) if text.strip() else {}
        except (OSError, ValueError) as ex:
            raise SetupError(f"{path} is not valid JSON ({ex}); fix or move it, then run setup again") from None
        if not isinstance(data, dict):
            raise SetupError(f"{path} does not hold a JSON object; fix or move it, then run setup again")
    elif "mcp" in part:
        data["$schema"] = "https://opencode.ai/config.json"
    for key, servers in part.items():
        current = data.get(key)
        if current is None:
            current = data[key] = {}
        if not isinstance(current, dict):
            raise SetupError(f"{path}: \"{key}\" is not a JSON object; fix it, then run setup again")
        current.update(servers)
    return data


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".kimbim-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- Claude Code's command, the instructions section

def _join(args: list[str]) -> str:
    return subprocess.list2cmdline(args) if sys.platform == "win32" else shlex.join(args)


def claude_add_line(project: str | None) -> str:
    command, env = server_command(project)
    options = [a for k, v in env.items() for a in ("--env", f"{k}={v}")]
    return _join(["claude", "mcp", "add", *options, SERVER, "--", *command])


def agents_section() -> str:
    command, env = server_command(None)
    cli = _join(command[:3])
    how = f"`{cli}`" + (f" with the environment variable `PYTHONPATH={env['PYTHONPATH']}`" if env else "")
    return "\n".join([
        AGENTS_START,
        "## KimBim",
        "",
        "This folder holds a KimBim project (a BIM model with saved versions). The `kimbim` MCP server gives you its",
        "tools. The same tools are a command line, `kimbim`: run it as " + how + ";",
        "`--help`, `<group> --help` and `<group> <verb> --help` describe the commands, and `--json` prints the result",
        "envelope. Make changes inside a task (`task start`, then `task finish` with a summary) so the architect can",
        "review them; never accept your own option. Take a snapshot (`snapshot take`) to check your work.",
        AGENTS_END,
    ]) + "\n"


def merge_agents(text: str, section: str) -> str:
    """`text` with the kimbim section replaced, or appended when it has none."""
    start, end = text.find(AGENTS_START), text.find(AGENTS_END)
    if start >= 0 and end > start:
        tail = text[end + len(AGENTS_END):]
        return text[:start] + section + tail.lstrip("\r\n")
    if text and not text.endswith("\n"):
        text += "\n"
    return text + ("\n" if text else "") + section


# ---------------------------------------------------------------- setup

def setup(client: str, project: str | None, print_only: bool = False) -> tuple[str, list[pathlib.Path]]:
    """Write the client's configuration (and, with a project, the instructions section in opencode's AGENTS.md or
    Claude Code's CLAUDE.md). Returns the text to print (with --print, the configuration; nothing is written) and
    the files written."""
    if client not in CLIENTS:
        raise SetupError(f"unknown client {client}")
    part = snippet(client, project)
    if print_only:
        if client == "claude-code":
            return claude_add_line(project), []
        return json.dumps(part, indent=2, ensure_ascii=False), []
    path = config_path(client, project)
    data = merged(path, part)
    written = [path]
    agents = None
    if project and client in INSTRUCTIONS:
        agents = project_folder(project) / INSTRUCTIONS[client]
        try:
            old = agents.read_text(encoding="utf-8") if agents.exists() else ""
        except (OSError, ValueError) as ex:
            raise SetupError(f"{agents}: {ex}") from None
    _write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    if agents is not None:
        new = merge_agents(old, agents_section())
        if new != old:
            _write(agents, new)
        written.append(agents)
    return "", written
