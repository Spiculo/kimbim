# SPDX-License-Identifier: GPL-3.0-or-later
import json

from conftest import build_model

from kimcad.cli import main


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
    cmd = [sys.executable, "-m", "kimcad", "-C", str(proj)]
    subprocess.run([sys.executable, "-m", "kimcad", "init", str(proj)], env=env, check=True, capture_output=True)
    out = subprocess.run(cmd + ["status", str(a)], env=env, capture_output=True)
    assert out.returncode == 0, out.stderr.decode(errors="replace")
    assert "墙 ✓ Muro" in out.stdout.decode("utf-8")


def test_not_a_project(tmp_path, capsys):
    code, _, err = run(capsys, "-C", str(tmp_path), "log")
    assert code == 1 and "not a KIMCAD project" in err
