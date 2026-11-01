# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the portable KimBim desktop package (the installer-free distribution).

It packs the app's conda environment with conda-pack, trims build-only files, unpacks it under
dist/KimBim/runtime (conda-unpack rewrites every prefix), and adds the app binary, the Python
sources, the bundled library and a launcher that carries the environment with it.

Run it through `pixi run -e pack package` (or `pixi run -e pack package -- --zip`). The result
starts on a machine with no pixi, no conda and no KimBim checkout: see tools/check_package.py.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PACKAGE = DIST / "KimBim"
WORK = ROOT / "build" / "package"

# Build-only material. The app needs the Python runtime, Qt, OCCT, MKL, git (versioning) and the
# Python packages; it does not need compilers, the Rust toolchain, headers, import libraries, CMake,
# test tools, docs or pip entry points.
EXCLUDES = [
    "*.pdb",
    "*.pyc",
    "__pycache__/*",
    "Library/lib/rustlib/*",
    "Library/include/*",
    "include/*",
    "Library/lib/*.lib",
    "node_modules/*",
    "node.exe",
    "npm*",
    "npx*",
    "Library/bin/rustc*",
    "Library/bin/cargo*",
    "Library/bin/clippy*",
    "Library/bin/rustdoc*",
    "Library/bin/clang*",
    "Library/bin/llvm*",
    "Library/bin/lld*",
    "Library/bin/cmake*",
    "Library/bin/ninja*",
    "Library/bin/maturin*",
    "Library/bin/ccmake*",
    "Library/bin/cpack*",
    "Library/bin/ctest*",
    "Library/share/doc/*",
    "Library/share/man/*",
    "Scripts/*",
]


def app_version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def app_binary() -> pathlib.Path:
    name = "kimbim-app.exe" if os.name == "nt" else "kimbim-app"
    path = ROOT / "build" / "app" / name
    if not path.exists():
        raise SystemExit(f"{path} is missing; run `pixi run app-build` first")
    return path


def pack_runtime(prefix: pathlib.Path, tar_path: pathlib.Path, force: bool) -> None:
    try:
        import conda_pack
    except ImportError:
        raise SystemExit("conda-pack is missing; run this through `pixi run -e pack package`") from None
    if tar_path.exists() and not force:
        print(f"reusing {tar_path}")
        return
    WORK.mkdir(parents=True, exist_ok=True)
    tar_path.unlink(missing_ok=True)
    print(f"packing {prefix} (this takes several minutes)...")
    conda_pack.pack(
        prefix=str(prefix),
        output=str(tar_path),
        format="tar.gz",
        force=True,
        compress_level=4,
        n_threads=max(1, (os.cpu_count() or 2)),
        filters=[("exclude", pattern) for pattern in EXCLUDES],
    )


def unpack_runtime(tar_path: pathlib.Path, runtime: pathlib.Path) -> None:
    runtime.mkdir(parents=True, exist_ok=True)
    print(f"unpacking {tar_path.name}...")
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(runtime, filter="data")
    unpack = runtime / ("Scripts/conda-unpack.exe" if os.name == "nt" else "bin/conda-unpack")
    if not unpack.exists():
        raise SystemExit(f"{unpack} is missing from the packed environment")
    print("rewriting prefixes with conda-unpack...")
    subprocess.run([str(unpack)], cwd=runtime, check=True)


def copy_tree(src: pathlib.Path, dst: pathlib.Path) -> None:
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pdb"),
        dirs_exist_ok=True,
    )


def remove_tree(path: pathlib.Path) -> None:
    """Delete a folder even when conda-pack left read-only files (and OneDrive holds one briefly)."""
    def retry(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    if path.exists():
        shutil.rmtree(path, onexc=retry)


def write_launchers(package: pathlib.Path) -> None:
    if os.name == "nt":
        (package / "KimBim.cmd").write_text(
            "@echo off\r\n"
            "rem SPDX-License-Identifier: GPL-3.0-or-later\r\n"
            "rem Portable KimBim launcher: the runtime and the Python sources travel with this folder.\r\n"
            "setlocal\r\n"
            'set "KIMBIM_HOME=%~dp0"\r\n'
            'set "CONDA_PREFIX=%KIMBIM_HOME%runtime"\r\n'
            'set "KIMBIM_PYTHON_PATH=%KIMBIM_HOME%python"\r\n'
            'set "PATH=%CONDA_PREFIX%;%CONDA_PREFIX%\\Library\\bin;%CONDA_PREFIX%\\Scripts;%PATH%"\r\n'
            '"%~dp0kimbim-app.exe" %*\r\n',
            encoding="utf-8",
            newline="",
        )
        (package / "kimbim-cli.cmd").write_text(
            "@echo off\r\n"
            "rem SPDX-License-Identifier: GPL-3.0-or-later\r\n"
            "setlocal\r\n"
            'set "KIMBIM_HOME=%~dp0"\r\n'
            'set "CONDA_PREFIX=%KIMBIM_HOME%runtime"\r\n'
            'set "KIMBIM_PYTHON_PATH=%KIMBIM_HOME%python"\r\n'
            'set "PYTHONPATH=%KIMBIM_HOME%python"\r\n'
            'set "PATH=%CONDA_PREFIX%;%CONDA_PREFIX%\\Library\\bin;%CONDA_PREFIX%\\Scripts;%PATH%"\r\n'
            '"%CONDA_PREFIX%\\python.exe" -m kimbim %*\r\n',
            encoding="utf-8",
            newline="",
        )
    else:
        launcher = package / "KimBim.sh"
        launcher.write_text(
            "#!/bin/sh\n"
            "# SPDX-License-Identifier: GPL-3.0-or-later\n"
            "# Portable KimBim launcher: the runtime and the Python sources travel with this folder.\n"
            'here=$(cd "$(dirname "$0")" && pwd)\n'
            'export CONDA_PREFIX="$here/runtime"\n'
            'export KIMBIM_PYTHON_PATH="$here/python"\n'
            'export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$LD_LIBRARY_PATH"\n'
            'exec "$here/kimbim-app" "$@"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        cli = package / "kimbim-cli.sh"
        cli.write_text(
            "#!/bin/sh\n"
            "# SPDX-License-Identifier: GPL-3.0-or-later\n"
            'here=$(cd "$(dirname "$0")" && pwd)\n'
            'export CONDA_PREFIX="$here/runtime"\n'
            'export KIMBIM_PYTHON_PATH="$here/python"\n'
            'export PYTHONPATH="$here/python"\n'
            'export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$LD_LIBRARY_PATH"\n'
            'exec "$CONDA_PREFIX/bin/python" -m kimbim "$@"\n',
            encoding="utf-8",
        )
        cli.chmod(0o755)


def write_readme(package: pathlib.Path) -> None:
    version = app_version()
    windows = os.name == "nt"
    if windows:
        start = "Double-click **KimBim.cmd** (or run it from a terminal)."
        platform_name = "Windows 10/11 x64"
        fallback = "set `QT_OPENGL=software` before launching (the bundled `opengl32sw.dll` is used)"
        cli = "`kimbim-cli.cmd`"
    else:
        start = "Run **./KimBim.sh** from a terminal."
        platform_name = f"Linux {platform.machine()}"
        fallback = "set `QT_OPENGL=software` before launching"
        cli = "`kimbim-cli.sh`"
    text = f"""# KimBim {version} — portable build ({platform_name})

{start}

Everything KimBim needs is in this folder. Move the whole folder anywhere you like; keep
`runtime/` and `python/` next to `kimbim-app` — the launcher finds them relative to itself.

- `samples/house.ifc` — the two-storey sample used by the tests.
- {cli} — the command-line and agent tools (`help` lists them).
- No installer, no administrator rights and no network connection are required.
- The 3D view needs OpenGL 3.3 or newer. If the driver cannot provide it, {fallback}.
- DWG import/export needs a separate LibreDWG install (the `dwg` pixi environment in a source
  checkout); this portable build does not bundle it. DXF works out of the box.
- Preferences are stored in the user profile; projects are saved where you choose.
- KimBim is GPL-3.0-or-later. The third-party components are listed in `THIRD_PARTY.md`.

This build is not code-signed, so Windows SmartScreen (or your desktop's security policy) may warn
the first time. An installer and signing are future work.
"""
    (package / "README-PORTABLE.md").write_text(text, encoding="utf-8")
    (package / "START-HERE.txt").write_text(
        f"KimBim {version}\n\n{start}\nSee README-PORTABLE.md for details.\n", encoding="utf-8"
    )


def package_size(path: pathlib.Path) -> float:
    total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return round(total / (1024 * 1024), 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=pathlib.Path, help="the environment to pack (default: .pixi/envs/default)")
    parser.add_argument("--out", type=pathlib.Path, default=PACKAGE, help="the package folder")
    parser.add_argument("--force", action="store_true", help="pack again instead of reusing the tar")
    parser.add_argument("--zip", action="store_true", help="also write a .zip next to the folder")
    parser.add_argument("--keep-runtime", action="store_true", help="keep an existing runtime folder")
    args = parser.parse_args()

    default_prefix = ROOT / ".pixi" / "envs" / "default"
    prefix = args.prefix or (default_prefix if default_prefix.exists() else pathlib.Path(os.environ.get("CONDA_PREFIX", "")))
    if not (prefix / "conda-meta").exists():
        raise SystemExit(f"{prefix} is not a conda environment; pass --prefix")

    package = args.out.resolve()
    if package.exists() and not args.keep_runtime:
        print(f"clearing {package}...")
        remove_tree(package)
    package.mkdir(parents=True, exist_ok=True)

    tar_path = WORK / "kimbim-env.tar.gz"
    started = time.time()
    pack_runtime(prefix, tar_path, args.force)
    unpack_runtime(tar_path, package / "runtime")

    print("adding the app, the Python sources and the samples...")
    shutil.copy2(app_binary(), package / app_binary().name)
    # The Rust decomposer's C++ bridge. Without it, kimbim falls back to the Python decomposer;
    # shipping it keeps cold decomposition fast in the portable build.
    bridge = ROOT / "build" / "ifcdump" / ("ifcdump.exe" if os.name == "nt" else "ifcdump")
    if bridge.exists():
        (package / "ifcdump").mkdir(exist_ok=True)
        shutil.copy2(bridge, package / "ifcdump" / bridge.name)
    else:
        print(f"warning: {bridge} is missing; the portable build will decompose in Python "
              "(run `pixi run ifcdump-build` before packaging)")
    copy_tree(ROOT / "python" / "kimbim", package / "python" / "kimbim")
    samples = package / "samples"
    samples.mkdir(exist_ok=True)
    house = ROOT / "build" / "house.ifc"
    if house.exists():
        shutil.copy2(house, samples / "house.ifc")
    for name in ("LICENSE", "THIRD_PARTY.md", "README.md"):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, package / name)
    write_launchers(package)
    write_readme(package)

    zip_path = None
    if args.zip:
        print("writing the zip (several minutes)...")
        base = DIST / f"KimBim-{app_version()}-{platform.system().lower()}-{platform.machine().lower()}"
        zip_path = pathlib.Path(shutil.make_archive(str(base), "zip", root_dir=DIST, base_dir="KimBim"))

    size = package_size(package)
    result = {
        "ok": True,
        "folder": str(package),
        "zip": str(zip_path) if zip_path else None,
        "size_mb": size,
        "seconds": round(time.time() - started, 1),
    }
    import json

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
