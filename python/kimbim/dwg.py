# SPDX-License-Identifier: GPL-3.0-or-later
"""DWG in and out (docs/14 §14/§18) through LibreDWG or the ODA File Converter.

DWG is a proprietary format; KimBim does not parse it itself. It calls a converter when one is
available: LibreDWG's `dwg2dxf` and `dxf2dwg` (GPL-3.0-or-later, the `dwg` pixi environment) or the
ODA File Converter. DWG underlays are converted to DXF and read by the existing DXF path; drawings
and sheets exported to DWG are first written as DXF, then converted.

Lookup order: `KIMBIM_DWG_BIN` (a folder), `KIMBIM_DWG2DXF` / `KIMBIM_DXF2DWG` (exact paths), PATH,
then the repository's `.pixi/envs/dwg` (a development tree). Without a converter the caller gets a
clear error instead of a silent failure.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import shutil
import subprocess
import tempfile

ENV_BIN = "KIMBIM_DWG_BIN"
ENV_TO_DXF = "KIMBIM_DWG2DXF"
ENV_FROM_DXF = "KIMBIM_DXF2DWG"
_TO_DXF = ("dwg2dxf", "dwg2dxf.exe", "ODAFileConverter")
_FROM_DXF = ("dxf2dwg", "dxf2dwg.exe", "dwgwrite", "dwgwrite.exe", "ODAFileConverter")


def _repo_bin() -> pathlib.Path | None:
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (parent / ".pixi" / "envs" / "dwg" / "Library" / "bin",
                          parent / ".pixi" / "envs" / "dwg" / "bin"):
            if candidate.is_dir():
                return candidate
    return None


def _find(names: tuple[str, ...], exact_env: str = "") -> str | None:
    exact = os.environ.get(exact_env, "")
    if exact and pathlib.Path(exact).is_file():
        return exact
    folder = os.environ.get(ENV_BIN, "")
    if folder:
        for name in names:
            candidate = pathlib.Path(folder) / name
            if candidate.is_file():
                return str(candidate)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    dev = _repo_bin()
    if dev is not None:
        for name in names:
            candidate = dev / name
            if candidate.is_file():
                return str(candidate)
    return None


def to_dxf_tool() -> str | None:
    return _find(_TO_DXF, ENV_TO_DXF)


def from_dxf_tool() -> str | None:
    return _find(_FROM_DXF, ENV_FROM_DXF)


def available() -> bool:
    return to_dxf_tool() is not None


def error() -> str:
    return ("DWG needs LibreDWG (dwg2dxf) or the ODA File Converter: install the `dwg` pixi "
            "environment (pixi install -e dwg) or set KIMBIM_DWG_BIN to its bin folder")


def _run(args: list[str], out: pathlib.Path) -> pathlib.Path:
    env = {**os.environ, "LC_ALL": "C"}
    result = subprocess.run(args, capture_output=True, text=True, env=env)
    if result.returncode != 0 or not out.is_file():
        message = (result.stderr or result.stdout or "the converter failed").strip().splitlines()
        raise RuntimeError(message[-1] if message else "the converter failed")
    return out


def dwg_to_dxf(path: str | pathlib.Path, out: str | pathlib.Path) -> pathlib.Path:
    """Convert a DWG to DXF (`-m`: entities only, which is all an underlay needs)."""
    tool = to_dxf_tool()
    if tool is None:
        raise RuntimeError(error())
    src, target = pathlib.Path(path), pathlib.Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    name = pathlib.Path(tool).name.lower()
    if name == "odafileconverter":
        raise RuntimeError("the ODA File Converter needs its folder interface; set KIMBIM_DWG2DXF "
                           "to a script that calls it")
    args = [tool, "-y", "--as", "r2000", "-o", str(target), str(src)]
    return _run(args, target)


def dxf_to_dwg(path: str | pathlib.Path, out: str | pathlib.Path) -> pathlib.Path:
    """Convert a DXF to DWG (LibreDWG `dxf2dwg`; experimental, as LibreDWG documents)."""
    tool = from_dxf_tool()
    if tool is None:
        raise RuntimeError(error())
    src, target = pathlib.Path(path), pathlib.Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    name = pathlib.Path(tool).name.lower()
    if name.startswith("dwgwrite"):
        args = [tool, "-y", "-o", str(target), str(src)]
    elif name == "odafileconverter":
        raise RuntimeError("the ODA File Converter needs its folder interface; set KIMBIM_DXF2DWG "
                           "to a script that calls it")
    else:
        args = [tool, "-y", "-o", str(target), str(src)]
    return _run(args, target)


def cached_dxf(dwg_path: str | pathlib.Path, cache_dir: str | pathlib.Path) -> pathlib.Path:
    """The converted DXF for a DWG, cached by the DWG's content (so a versioned underlay converts once)."""
    src, cache = pathlib.Path(dwg_path), pathlib.Path(cache_dir)
    key = hashlib.sha1(src.read_bytes()).hexdigest()
    target = cache / f"{key}.dxf"
    if target.is_file():
        return target
    return dwg_to_dxf(src, target)
