# SPDX-License-Identifier: GPL-3.0-or-later
"""The people commands of the `kimbim` CLI (project init, versions save|status|show|tag|branch|merge, script run).
The generated tool commands are in test_agent_cli.py."""
import json

from conftest import build_model

from kimbim.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_full_cli_flow(tmp_path, capsys):
    proj = tmp_path / "Mi Proyecto ñ"
    f = build_model()
    a = tmp_path / "a.ifc"
    f.write(str(a))
    assert run(capsys, "project", "init", str(proj))[0] == 0
    code, out, _ = run(capsys, "--project", str(proj), "versions", "save", str(a), "-m", "first")
    assert code == 0 and "added" in out
    code, out, err = run(capsys, "--project", str(proj), "versions", "save", str(a), "-m", "again")
    assert code == 1 and "nothing to commit" in err
    f.by_type("IfcWall")[0].Name = "Renamed"
    b = tmp_path / "b.ifc"
    f.write(str(b))
    code, out, _ = run(capsys, "--project", str(proj), "versions", "status", str(b))
    assert code == 0 and "IfcWall" in out and "Renamed" in out
    run(capsys, "--project", str(proj), "versions", "save", str(b), "-m", "rename")
    code, out, _ = run(capsys, "--project", str(proj), "--no-worker", "versions", "log")
    assert code == 0 and out.index("rename") < out.index("first")
    code, env, _ = run(capsys, "--project", str(proj), "--no-worker", "versions", "diff", "--from", "HEAD~1", "--json")
    assert code == 0 and json.loads(env)["ok"]
    assert run(capsys, "--project", str(proj), "versions", "branch", "option-b")[0] == 0
    code, out, _ = run(capsys, "--project", str(proj), "versions", "branch")
    assert "* main" in out and "option-b" in out


def test_save_the_working_model_without_a_file(tmp_path, capsys, monkeypatch):
    from kimbim import app_bridge as B
    from kimbim import documents as D
    from kimbim import kimfile as K
    from kimbim.agent.session import Session

    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    monkeypatch.setattr(K, "display_user", "")
    proj = tmp_path / "p"
    a = tmp_path / "a.ifc"
    f = build_model()
    f.write(str(a))
    run(capsys, "project", "init", str(proj))
    base = ["--project", str(proj)]
    run(capsys, *base, "versions", "save", str(a), "-m", "first")
    s = Session.open(str(proj))
    B.set_name(json.dumps([f.by_type("IfcWall")[0].GlobalId]), "Edited")
    s.save()
    s.close()
    code, out, err = run(capsys, *base, "versions", "save", "-m", "from the working model")
    assert code == 0, err
    code, out, _ = run(capsys, *base, "--no-worker", "versions", "log")
    assert code == 0 and "from the working model" in out and "first" in out


def test_empty_project_messages(tmp_path, capsys):
    proj = tmp_path / "p"
    run(capsys, "project", "init", str(proj))
    code, _, err = run(capsys, "--project", str(proj), "versions", "show", "o/XYZ")
    assert code == 1 and "Traceback" not in err


def test_unicode_names_survive_real_pipes(tmp_path):
    # Windows pipes default to the legacy code page; names in any script must still print.
    import os
    import pathlib
    import subprocess
    import sys

    f = build_model()
    f.by_type("IfcWall")[0].Name = "墙 ✓ Muro"
    a = tmp_path / "a.ifc"
    f.write(str(a))
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parents[2] / "python")
    proj = tmp_path / "p"
    cmd = [sys.executable, "-m", "kimbim", "--project", str(proj)]
    subprocess.run(cmd + ["project", "init"], env=env, check=True, capture_output=True)
    out = subprocess.run(cmd + ["versions", "status", str(a)], env=env, capture_output=True)
    assert out.returncode == 0, out.stderr.decode(errors="replace")
    assert "墙 ✓ Muro" in out.stdout.decode("utf-8")


def test_not_a_project(tmp_path, capsys):
    code, _, err = run(capsys, "--project", str(tmp_path), "versions", "show", "o/x")
    assert code == 1 and "not a KimBim project" in err


def test_engine_errors_are_messages_not_tracebacks(tmp_path, capsys, monkeypatch):
    proj = tmp_path / "p"
    a = tmp_path / "a.ifc"
    build_model().write(str(a))
    run(capsys, "project", "init", str(proj))
    monkeypatch.setenv("KIMBIM_AUTHOR_NAME", "Evil <x>")
    code, _, err = run(capsys, "--project", str(proj), "versions", "save", str(a), "-m", "x")
    assert code == 1 and "invalid author" in err and "Traceback" not in err


def test_tags_and_history(tmp_path, capsys):
    proj = tmp_path / "p"
    f = build_model()
    wall = f.by_type("IfcWall")[0]
    a = tmp_path / "a.ifc"
    f.write(str(a))
    run(capsys, "project", "init", str(proj))
    base = ["--project", str(proj)]
    run(capsys, *base, "versions", "save", str(a), "-m", "first")
    assert run(capsys, *base, "versions", "tag", "Concept", "-m", "for the client")[0] == 0
    wall.Name = "Renamed"
    f.write(str(a))
    run(capsys, *base, "versions", "save", str(a), "-m", "rename")
    code, out, _ = run(capsys, *base, "versions", "tag")
    assert code == 0 and "Concept" in out and "for the client" in out
    code, out, _ = run(capsys, *base, "--no-worker", "versions", "element-history", "--element", wall.GlobalId, "--json")
    assert code == 0 and json.loads(out)["ok"]
    assert run(capsys, *base, "versions", "tag", "--delete", "Concept")[0] == 0
    code, out, _ = run(capsys, *base, "versions", "tag")
    assert "Concept" not in out


def test_script_run_edits_a_model_in_place(tmp_path, capsys):
    import ifcopenshell

    model = build_model(walls=2)
    ifc = tmp_path / "house.ifc"
    model.write(str(ifc))
    script = tmp_path / "rename.py"
    script.write_text(
        "for w in ifc.by_type('IfcWall'):\n    w.Name = 'From script'\nprint('renamed', len(ifc.by_type('IfcWall')))\n",
        encoding="utf-8")
    code, out, err = run(capsys, "script", "run", str(script), str(ifc))
    assert code == 0, err
    assert "renamed 2" in out
    result = ifcopenshell.open(str(ifc))
    assert {w.Name for w in result.by_type("IfcWall")} == {"From script"}


def test_script_run_error_reports_and_leaves_the_model(tmp_path, capsys):
    import ifcopenshell

    model = build_model(walls=1)
    ifc = tmp_path / "house.ifc"
    model.write(str(ifc))
    script = tmp_path / "boom.py"
    script.write_text("ifc.by_type('IfcWall')[0].Name = 'half'\nraise ValueError('nope')\n", encoding="utf-8")
    code, out, err = run(capsys, "script", "run", str(script), str(ifc))
    assert code == 1 and "ValueError" in err
    result = ifcopenshell.open(str(ifc))
    assert {w.Name for w in result.by_type("IfcWall")} != {"half"}  # the failed run rolled back
