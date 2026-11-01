# SPDX-License-Identifier: GPL-3.0-or-later
"""Smoke-test the portable package on a clean environment.

Runs the packaged launcher with CONDA/PIXI/PYTHON variables removed and a minimal PATH, checks the
version, then exports the sample house's A01 sheet to PDF. That exercises the Qt runtime, the
embedded Python, IfcOpenShell, the sheet composer and the packaged Python sources without pixi.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_PACKAGE = ROOT / "dist" / "KimBim"


def clean_env() -> dict[str, str]:
    keep = {"SystemRoot", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME", "LANG", "LC_ALL", "NUMBER_OF_PROCESSORS"}
    env = {k: v for k, v in os.environ.items() if k in keep}
    env["PATH"] = r"C:\Windows\System32;C:\Windows" if os.name == "nt" else "/usr/bin:/bin"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_OPENGL"] = "software"
    return env


def run(command: list[str], env: dict[str, str], cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, env=env, cwd=cwd, timeout=600)


def launcher(package: pathlib.Path) -> list[str]:
    if os.name == "nt":
        return ["cmd", "/c", "call", str(package / "KimBim.cmd")]
    return [str(package / "KimBim.sh")]


def cli_launcher(package: pathlib.Path) -> list[str]:
    if os.name == "nt":
        return ["cmd", "/c", "call", str(package / "kimbim-cli.cmd")]
    return [str(package / "kimbim-cli.sh")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=pathlib.Path, default=DEFAULT_PACKAGE)
    args = parser.parse_args()
    package = args.package.resolve()
    launcher_command = launcher(package)
    env = clean_env()

    problems: list[str] = []
    version = run(launcher_command + ["--version"], env)
    if version.returncode != 0 or "KimBim" not in version.stdout:
        problems.append(f"version failed ({version.returncode}): {version.stdout}{version.stderr}")

    sample = package / "samples" / "house.ifc"
    pdf = pathlib.Path(tempfile.mkdtemp(prefix="kimbim-package-")) / "A01.pdf"
    exported = None
    if not sample.exists():
        problems.append(f"the sample is missing: {sample}")
    else:
        result = run(launcher_command + ["--export-sheet", "A01", str(sample), str(pdf)], env)
        lines = [line for line in result.stdout.splitlines() if line.strip().startswith("{")]
        if lines:
            try:
                exported = json.loads(lines[-1])
            except ValueError:
                exported = None
        if result.returncode != 0 or not exported or not exported.get("ok"):
            problems.append(f"sheet export failed ({result.returncode}): {result.stdout}{result.stderr}")
        elif not pdf.exists() or pdf.read_bytes()[:5] != b"%PDF-":
            problems.append(f"the exported file is not a PDF: {pdf}")

    # Versioning needs the git binary inside the runtime; keep that path covered so trimming the
    # package cannot silently break commits (the Library/bin git shim needs Library/ucrt64).
    versioning = None
    if sample.exists():
        project = pathlib.Path(tempfile.mkdtemp(prefix="kimbim-package-repo-"))
        init = run(cli_launcher(package) + ["project", "init", "p"], env, cwd=project)
        save = run(cli_launcher(package) + ["--project", "p", "versions", "save", str(sample), "-m", "package smoke"],
            env, cwd=project)
        versioning = {"init": init.returncode, "save": save.returncode,
            "git": (project / "p" / ".git").is_dir()}
        if init.returncode != 0 or save.returncode != 0 or not versioning["git"]:
            problems.append(f"versioning failed: init {init.returncode}, save {save.returncode}: "
                f"{init.stdout}{init.stderr}{save.stdout}{save.stderr}")

    report = {
        "ok": not problems,
        "package": str(package),
        "version": version.stdout.strip(),
        "sheet_export": exported,
        "versioning": versioning,
        "pdf": str(pdf) if pdf.exists() else None,
        "problems": problems,
    }
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
