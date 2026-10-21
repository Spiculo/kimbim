# SPDX-License-Identifier: GPL-3.0-or-later
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
    assert run(capsys, "init", str(proj))[0] == 0
    code, out, _ = run(capsys, "-C", str(proj), "commit", str(a), "-m", "first")
    assert code == 0 and "added" in out
    code, out, err = run(capsys, "-C", str(proj), "commit", str(a), "-m", "again")
    assert code == 1 and "nothing to commit" in err
    f.by_type("IfcWall")[0].Name = "Renamed"
    b = tmp_path / "b.ifc"
    f.write(str(b))
    code, out, _ = run(capsys, "-C", str(proj), "status", str(b))
    assert code == 0 and "IfcWall" in out and "Renamed" in out
    run(capsys, "-C", str(proj), "commit", str(b), "-m", "rename")
    code, out, _ = run(capsys, "-C", str(proj), "log")
    assert code == 0 and out.index("rename") < out.index("first")
    code, out, _ = run(capsys, "-C", str(proj), "diff", "--json")
    assert json.loads(out)["modified"][0]["ifc_type"] == "IfcWall"
    out_ifc = tmp_path / "out.ifc"
    assert run(capsys, "-C", str(proj), "export", str(out_ifc), "--rev", "HEAD~1")[0] == 0
    code, _, err = run(capsys, "-C", str(proj), "export", str(out_ifc))
    assert code == 1 and "--force" in err
    assert run(capsys, "-C", str(proj), "export", str(out_ifc), "--force")[0] == 0
    assert run(capsys, "-C", str(proj), "branch", "option-b")[0] == 0
    code, out, _ = run(capsys, "-C", str(proj), "branch")
    assert "* main" in out and "option-b" in out


def test_empty_project_messages(tmp_path, capsys):
    proj = tmp_path / "p"
    run(capsys, "init", str(proj))
    code, out, _ = run(capsys, "-C", str(proj), "log")
    assert code == 0 and "no versions" in out
    for argv in (["diff"], ["export", str(tmp_path / "x.ifc")]):
        code, _, err = run(capsys, "-C", str(proj), *argv)
        assert code == 1 and "no versions" in err and "Traceback" not in err


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
    cmd = [sys.executable, "-m", "kimbim", "-C", str(proj)]
    subprocess.run([sys.executable, "-m", "kimbim", "init", str(proj)], env=env, check=True, capture_output=True)
    out = subprocess.run(cmd + ["status", str(a)], env=env, capture_output=True)
    assert out.returncode == 0, out.stderr.decode(errors="replace")
    assert "墙 ✓ Muro" in out.stdout.decode("utf-8")


def test_not_a_project(tmp_path, capsys):
    code, _, err = run(capsys, "-C", str(tmp_path), "log")
    assert code == 1 and "not a KimBim project" in err


def test_engine_errors_are_messages_not_tracebacks(tmp_path, capsys, monkeypatch):
    proj = tmp_path / "p"
    a = tmp_path / "a.ifc"
    build_model().write(str(a))
    run(capsys, "init", str(proj))
    monkeypatch.setenv("KIMBIM_AUTHOR_NAME", "Evil <x>")
    code, _, err = run(capsys, "-C", str(proj), "commit", str(a), "-m", "x")
    assert code == 1 and "invalid author" in err and "Traceback" not in err


def test_tags_and_blame(tmp_path, capsys):
    proj = tmp_path / "p"
    f = build_model()
    wall = f.by_type("IfcWall")[0]
    a = tmp_path / "a.ifc"
    f.write(str(a))
    run(capsys, "init", str(proj))
    run(capsys, "-C", str(proj), "commit", str(a), "-m", "first")
    assert run(capsys, "-C", str(proj), "tag", "Concept", "-m", "for the client")[0] == 0
    wall.Name = "Renamed"
    f.write(str(a))
    run(capsys, "-C", str(proj), "commit", str(a), "-m", "rename")
    code, out, _ = run(capsys, "-C", str(proj), "tag")
    assert code == 0 and "Concept" in out and "for the client" in out
    code, out, _ = run(capsys, "-C", str(proj), "diff", "Concept", "HEAD")
    assert code == 0 and "1 modified" in out
    code, out, _ = run(capsys, "-C", str(proj), "blame", wall.GlobalId)
    assert code == 0 and out.index("rename") < out.index("first") and "~ modified" in out and "+ added" in out
    assert run(capsys, "-C", str(proj), "tag", "--delete", "Concept")[0] == 0
    code, out, _ = run(capsys, "-C", str(proj), "tag")
    assert "Concept" not in out


def test_run_script_edits_a_model_in_place(tmp_path, capsys):
    import ifcopenshell

    model = build_model(walls=2)
    ifc = tmp_path / "house.ifc"
    model.write(str(ifc))
    script = tmp_path / "rename.py"
    script.write_text(
        "for w in ifc.by_type('IfcWall'):\n    w.Name = 'From script'\nprint('renamed', len(ifc.by_type('IfcWall')))\n",
        encoding="utf-8")
    code, out, err = run(capsys, "run", str(script), str(ifc))
    assert code == 0, err
    assert "renamed 2" in out
    result = ifcopenshell.open(str(ifc))
    assert {w.Name for w in result.by_type("IfcWall")} == {"From script"}


def test_run_script_error_reports_and_leaves_the_model(tmp_path, capsys):
    import ifcopenshell

    model = build_model(walls=1)
    ifc = tmp_path / "house.ifc"
    model.write(str(ifc))
    script = tmp_path / "boom.py"
    script.write_text("ifc.by_type('IfcWall')[0].Name = 'half'\nraise ValueError('nope')\n", encoding="utf-8")
    code, out, err = run(capsys, "run", str(script), str(ifc))
    assert code == 1 and "ValueError" in err
    result = ifcopenshell.open(str(ifc))
    assert {w.Name for w in result.by_type("IfcWall")} != {"half"}  # the failed run rolled back
