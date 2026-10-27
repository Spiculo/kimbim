# SPDX-License-Identifier: GPL-3.0-or-later
"""The generated `kimbim` CLI (D102, spec §7) on the sample house: parameter parsing, exit codes, output."""
import json
import os
import shutil
import signal
import sys
from pathlib import Path

import pytest

from kimbim import documents as D
from kimbim import kimfile as K
from kimbim.agent import cli, client
from kimbim.agent.catalogue import TOOLS
from kimbim.cli import main

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402


@pytest.fixture(scope="module")
def house_kim(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("house")
    saved = D._data_dir
    D._data_dir = folder / "data"
    try:
        ifc = folder / "house.ifc"
        make_house.build(str(ifc))
        kim = folder / "house.kim"
        assert json.loads(D.import_ifc(str(ifc), str(kim)))["ok"]
        D.close_document()
    finally:
        D._data_dir = saved
    return kim


@pytest.fixture
def house(house_kim, tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("KIMBIM_DATA_DIR", str(data))
    monkeypatch.setenv("KIMBIM_AGENT_IDLE", "3")
    monkeypatch.delenv("KIMBIM_TASK", raising=False)
    monkeypatch.setattr(D, "_data_dir", None)
    monkeypatch.setattr(K, "display_user", "")
    monkeypatch.setattr(client, "spawned", [])
    kim = tmp_path / "house.kim"
    shutil.copyfile(house_kim, kim)
    yield kim
    pids = list(client.spawned)
    sessions = data / "agent" / "sessions"
    for p in sessions.glob("*.json") if sessions.is_dir() else ():
        try:
            pids.append(int(json.loads(p.read_text(encoding="utf-8")).get("pid", 0)))
        except (OSError, ValueError):
            pass
    for pid in pids:
        if K.pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


def run(capsys, kim, *argv):
    """Run in this process (`--no-worker`)."""
    code = main(["--project", str(kim), "--no-worker", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def envelope(capsys, kim, *argv):
    code, out, err = run(capsys, kim, *argv, "--json")
    return code, json.loads(out), err


def test_widen_windows_cli(house, capsys):
    code, env, err = envelope(capsys, house, "elements", "set-dimensions", "--elements",
                              '{"kind":"window","level":"Level 1"}', "--width", "+50cm")
    assert code == 0 and env["ok"], (env, err)
    windows = [m for m in env["changes"]["modified"] if m["label"].startswith("Window")]
    assert len(windows) == 4
    assert env["changes"]["task"]["status"] == "ready"  # the write's own task was finished: nothing is left open
    code, env, _ = envelope(capsys, house, "task", "status")
    assert code == 0 and env["result"]["task"] is None
    code, out, _ = run(capsys, house, "elements", "set-dimensions", "--elements", '{"kind":"door"}',
                       "--height", "+10cm", "--dry-run")
    assert code == 0 and out.startswith("Would change") and "dry run" in out


def test_help_lists_groups(capsys):
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    for group in ("elements", "create", "versions", "task", "project", "script", "serve", "mcp", "setup"):
        assert group in out
    assert main(["elements", "--help"]) == 0
    assert "set-dimensions" in capsys.readouterr().out
    assert main(["elements", "set-dimensions", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--width" in out and "--dry-run" in out and "Change dimensions" in out


def test_mcp_help_says_the_project_is_named_per_call(capsys):
    assert main(["mcp", "--help"]) == 0
    assert "every tool call names it" in capsys.readouterr().out


def test_help_markdown_is_the_tool_table(capsys):
    """`kimbim help --markdown` prints the table docs/17-agent-tools.md pastes: one row per public tool."""
    assert main(["help", "--markdown"]) == 0
    rows = capsys.readouterr().out.strip().splitlines()
    assert rows[0].startswith("| Tool (MCP) | Command line |") and rows[1].startswith("|---")
    public = [n for n in TOOLS if not n.startswith("_")]
    assert len(rows) == 2 + len(public)
    dims = next(r for r in rows if r.startswith("| `elements_set_dimensions` "))
    assert "`kimbim elements set-dimensions`" in dims and dims.endswith("| yes |")
    assert "wall... tables" in next(r for r in rows if r.startswith("| `schedules_list` "))  # "..." isn't a full stop
    doc = (ROOT / "docs" / "17-agent-tools.md").read_text(encoding="utf-8")
    assert "\n".join(rows) in doc  # the guide's table is the current catalogue's


def test_exit_codes(house, capsys):
    assert run(capsys, house, "elements", "find", "--bogus", "1")[0] == 2
    assert run(capsys, house, "elements", "find")[0] == 2  # --elements is required
    assert run(capsys, house, "elements", "find", "--elements", "{not json")[0] == 2
    code, env, _ = envelope(capsys, house, "elements", "find", "--elements", '{"kind":"window","name":"Nope"}')
    assert code == 1 and env["error"]["code"] == "no_match"
    code, _, err = run(capsys, house, "elements", "find", "--elements", '{"kind":"window","name":"Nope"}')
    assert code == 1 and err.startswith("kimbim: error:")


def test_no_project_is_a_usage_error(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["project", "info"]) == 2
    assert "--project" in capsys.readouterr().err


def test_project_discovery_from_the_current_folder(house, capsys, monkeypatch):
    monkeypatch.chdir(house.parent)
    code = main(["--no-worker", "project", "info", "--json"])
    assert code == 0 and json.loads(capsys.readouterr().out)["result"]["counts"]["walls"] == 8


def test_task_env(house, capsys, monkeypatch):
    code, env, err = envelope(capsys, house, "task", "start", "--title", "Rename walls", "--client", "t")
    assert code == 0, err
    task_id = env["result"]["id"]
    monkeypatch.setenv("KIMBIM_TASK", task_id)
    code, env, err = envelope(capsys, house, "elements", "rename", "--elements", '{"kind":"wall"}', "--name", "X",
                              "--client", "t")
    assert code == 0 and "task" not in env["changes"], (env, err)  # an explicit task is not finished by the write
    code, env, _ = envelope(capsys, house, "task", "status", "--client", "t")
    assert env["result"]["task"]["id"] == task_id and env["result"]["changes"]["modified"]
    monkeypatch.setenv("KIMBIM_TASK", "nope")
    code, env, _ = envelope(capsys, house, "elements", "rename", "--elements", '{"kind":"wall"}', "--name", "Y")
    assert code == 1 and env["error"]["code"] in ("unknown_task", "no_task")
    monkeypatch.delenv("KIMBIM_TASK")
    code, env, _ = envelope(capsys, house, "task", "finish", "--summary", "done", "--task", task_id, "--client", "t")
    assert code == 0 and env["result"]["task"]["status"] == "ready"


def test_versions_log(house, capsys):
    code, env, _ = envelope(capsys, house, "versions", "log")
    assert code == 0 and env["result"]["versions"]
    code, out, _ = run(capsys, house, "versions", "log", "--limit", "1")
    assert code == 0 and len(out.strip().splitlines()) == 1


def test_unicode_output(house, capsys):
    code, out, err = run(capsys, house, "task", "start", "--title", "Reforma de la cocina ñ", "--mode", "direct")
    assert code == 0, err
    assert "Reforma de la cocina ñ" in out


def test_parse_values():
    sel = TOOLS["elements.rename"].params["properties"]["elements"]
    assert cli.parse_value("selection", sel) == "selection"
    assert cli.parse_value("G1,G2 , G3", sel) == ["G1", "G2", "G3"]
    assert cli.parse_value('["G1","G2"]', sel) == ["G1", "G2"]
    assert cli.parse_value('{"kind":"window"}', sel) == {"kind": "window"}
    assert cli.parse_value("G1", sel) == ["G1"]
    length = TOOLS["elements.set_dimensions"].params["properties"]["width"]
    assert cli.parse_value("1.2", length) == 1.2 and cli.parse_value("2", length) == 2
    assert cli.parse_value("+50cm", length) == "+50cm" and cli.parse_value("-10%", length) == "-10%"
    text = TOOLS["elements.rename"].params["properties"]["name"]
    assert cli.parse_value("123", text) == "123" and cli.parse_value("[A]", text) == "[A]"
    flag = TOOLS["levels.edit"].params["properties"]["move_above"]
    assert cli.parse_value("true", flag) is True and cli.parse_value("false", flag) is False
    with pytest.raises(ValueError):
        cli.parse_value("{oops", sel)


def parsed(*argv):
    ns = cli.build_parser().parse_args(list(argv))
    return ns.tool, cli.tool_args(ns)


def test_generated_options():
    tool, args = parsed("levels", "edit", "--level", "Level 1", "--elevation", "3", "--move-above")
    assert tool == "levels.edit" and args == {"level": "Level 1", "elevation": 3, "move_above": True}
    assert parsed("levels", "edit", "--level", "L", "--move-above", "false")[1]["move_above"] is False
    _, args = parsed("elements", "remove-properties", "--elements", "selection",
                     "--properties", '["Pset_A.B","Pset_A.C"]')
    assert args == {"elements": "selection", "properties": ["Pset_A.B", "Pset_A.C"]}
    _, args = parsed("project", "set-settings", "--changes", '{"length_unit": "cm"}')
    assert args == {"changes": {"length_unit": "cm"}}
    _, args = parsed("elements", "rename", "--elements", "AAA,BBB", "--name", "N", "--dry-run")
    assert args == {"elements": ["AAA", "BBB"], "name": "N", "dry_run": True}
    _, args = parsed("versions", "diff", "--from", "HEAD~1")  # a parameter named like a keyword
    assert args == {"from": "HEAD~1"}


def test_every_tool_has_a_command():
    for name in TOOLS:
        if not name.startswith("_") and name != "script.run":
            group, verb = name.split(".", 1)
            with pytest.raises(SystemExit) as info:
                cli.build_parser().parse_args([group, verb.replace("_", "-"), "--help"])
            assert info.value.code == 0


def test_global_options_in_either_place():
    ns = cli.build_parser().parse_args(["--json", "task", "status", "--project", "P", "--client", "c"])
    assert ns.g_json and ns.g_project == "P" and ns.g_client == "c" and not ns.g_no_worker


def test_script_run_on_the_project(house, tmp_path, capsys):
    script = tmp_path / "s.py"
    script.write_text("print(len(ifc.by_type('IfcWall')))\n", encoding="utf-8")
    code, out, err = run(capsys, house, "script", "run", str(script))
    assert code == 1 and "script" in err.lower()  # agent_scripts is off: the architect turns it on


def test_setup_unknown_client_is_a_usage_error(capsys):
    assert main(["setup", "nope"]) == 2  # mcp and setup themselves: test_agent_mcp.py, test_agent_setup.py


def test_through_the_worker(house, capsys):
    code = main(["--project", str(house), "project", "info", "--json"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert json.loads(out)["result"]["counts"]["walls"] == 8
    assert len(client.spawned) == 1
    assert main(["--project", str(house), "elements", "find", "--elements", '{"kind":"door"}', "--json"]) == 0
    assert len(client.spawned) == 1  # the same worker
    capsys.readouterr()
    assert client.request(str(house), "_shutdown", {})["ok"]


# ---------------------------------------------------------------- fix round 1

@pytest.mark.parametrize("value", ["-10%", "-50cm"])
def test_negative_relative_values_are_values(value):
    argv = ["elements", "set-dimensions", "--elements", "selection", "--width", value]
    ns = cli.build_parser().parse_args(cli.fix_negative_values(argv, cli.build_parser()))
    assert cli.tool_args(ns) == {"elements": "selection", "width": value}


def test_negative_width_end_to_end(house, capsys):
    from kimbim import app_bridge as B
    from kimbim import authoring as A
    from kimbim.agent.session import Session

    from kimbim import settings as S

    s = Session.open(str(house))
    assert json.loads(S.set_project_settings(json.dumps({"agent_changes": "direct"})))["ok"]
    s.save()
    s.close()
    code, env, err = envelope(capsys, house, "elements", "set-dimensions", "--elements",
                              '{"kind":"window","level":"Level 1"}', "--width", "-10cm")
    assert code == 0 and env["ok"], (env, err)
    s = Session.open(str(house))
    try:
        widths = [round(dict((n, v) for n, v, _ in A.element_dimensions(w))["Width"], 6)
                  for w in B._model.by_type("IfcWindow")]
    finally:
        s.close()
    assert widths.count(1.1) == 4  # the four Level 1 windows were 1.2 m wide


def test_human_text_in_spanish(house, capsys, monkeypatch):
    monkeypatch.setenv("KIMBIM_LANG", "es")
    code, out, _ = run(capsys, house, "elements", "rename", "--elements", '{"kind":"door"}', "--name", "P",
                       "--dry-run")
    assert code == 0 and "Renombraría" in out
    code, _, err = run(capsys, house, "elements", "find", "--elements", '{"kind":"window","name":"Nope"}')
    assert code == 1 and err.startswith("kimbim: error: No hay coincidencias")
    monkeypatch.chdir(house.parent / "..")
    assert main(["project", "info"]) == 2
    assert "No hay ningún proyecto" in capsys.readouterr().err


def test_summaries_per_tool(house, capsys):
    code, out, err = run(capsys, house, "elements", "set-dimensions", "--elements",
                         '{"kind":"window","level":"Level 1"}', "--width", "+50cm")
    assert code == 0 and out.startswith("Changed 4 windows: width +50cm"), (out, err)
    code, out, _ = run(capsys, house, "elements", "rename", "--elements", '{"kind":"door"}', "--name", "P")
    assert code == 0 and out.startswith("Renamed ") and " to P" in out
    code, out, _ = run(capsys, house, "task", "start", "--title", "Mi tarea", "--mode", "direct")
    assert code == 0 and out.startswith("Task started") and "Mi tarea" in out
    code, out, _ = run(capsys, house, "elements", "rename", "--elements", '{"kind":"door"}', "--name", "P",
                       "--dry-run")
    assert out.startswith("Would rename")
    code, out, _ = run(capsys, house, "elements", "delete", "--elements", '{"kind":"door"}', "--dry-run")
    assert code == 0 and out.startswith("Would delete")


def test_no_changes_reads_naturally():
    assert cli.summarize("levels.add", {"ok": True, "result": {}, "changes": {}}, {}) == "No changes"


def _failing_finish(monkeypatch):
    from kimbim.agent import catalogue

    real = catalogue.call_tool

    def failing(session, name, args, **kw):
        if name == "task.finish":
            return catalogue.AgentError("bridge_error", hint="disk full").envelope()
        return real(session, name, args, **kw)

    monkeypatch.setattr(cli, "call_tool", failing)


ARGV = ["elements", "rename", "--elements", '{"kind":"door"}', "--name", "P"]


def test_finish_failure_is_reported_with_the_write(house, capsys, monkeypatch):
    _failing_finish(monkeypatch)
    code, out, err = run(capsys, house, *ARGV)
    assert code == 1 and "Renamed" in out and "disk full" in err


def test_finish_failure_json_is_an_error_envelope(house, capsys, monkeypatch):
    _failing_finish(monkeypatch)
    code, env, _ = envelope(capsys, house, *ARGV)
    assert code == 1 and env["ok"] is False and set(env) == {"ok", "error"}
    assert env["error"]["code"] == "bridge_error" and env["error"]["hint"] == "disk full"
    write = env["error"]["details"]["write"]
    assert write["result"]["elements"] == 2 and write["changes"]["modified"]


def test_json_envelope_keeps_its_shape(house, capsys):
    code, env, _ = envelope(capsys, house, "elements", "rename", "--elements", '{"kind":"door"}', "--name", "Q")
    assert code == 0 and set(env) <= {"ok", "result", "changes", "warnings"}
    assert env["changes"]["task"]["status"] == "ready"
    code, env, _ = envelope(capsys, house, "elements", "find", "--elements", '{"kind":"window","name":"Nope"}')
    assert code == 1 and set(env) == {"ok", "error"}
