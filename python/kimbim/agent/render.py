# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent worker's renderer (D102, spec §6): `kimbim-app --snapshot-server`, the app's own MainWindow and OCCT
renderer with no window, driven over JSON lines (app/src/SnapshotServer.h). One per worker, started on the first
snapshot and kept for the next ones; it loads a copy of the model (data_dir()/agent/render/<hash>.ifc, plus the
project settings) only when the model or its settings changed since the last load. The helper never gets the
project's own file: it opens what it is given as the app does and closes it on EOF.

Any helper failure is `render_failed`; the helper's (English) message and its log go in the error's details."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import queue
import shutil
import subprocess
import sys
import threading

from .. import app_bridge as B
from .. import documents as D
from .. import kimfile as K
from .. import settings as S
from .. import underlays
from . import messages
from .catalogue import AgentError

# The app's Compare colours (app/src/HistoryPanel.h: addedColor, modifiedColor; MainWindow::compareWith).
# Removed elements aren't in the model, so they have no colour (a count only).
ADDED = "#3caf5a"
MODIFIED = "#eb9628"

LOAD_TIMEOUT = 20 * 60  # seconds: a large model opens in minutes (the helper's own limit is the same)
RENDER_TIMEOUT = 5 * 60


def app_binary() -> pathlib.Path | None:
    """The app binary: KIMBIM_APP, else next to the Python package (build/app/kimbim-app[.exe] in development)."""
    env = os.environ.get("KIMBIM_APP")
    if env:
        return pathlib.Path(env) if pathlib.Path(env).is_file() else None
    package = pathlib.Path(__file__).resolve().parents[1]  # .../kimbim
    folders = [package.parents[1] / "build" / "app", package.parent, package.parents[1]]
    names = ("kimbim-app.exe", "kimbim-app") if sys.platform == "win32" else ("kimbim-app",)
    return next((f / n for f in folders for n in names if (f / n).is_file()), None)


def _no_app() -> AgentError:
    return AgentError("render_failed", hint=messages.text("hint_no_app"))


class Renderer:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue | None = None
        self._log = None
        self._loaded = None  # (model id, undo id, settings digest) of the last load
        self.loads = 0  # loads sent to the helper (tests)

    # ------------------------------------------------------------ the helper process

    @staticmethod
    def folder() -> pathlib.Path:
        path = D.data_dir() / "agent" / "render"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def data(cls) -> pathlib.Path:
        """The helper's KIMBIM_DATA_DIR."""
        path = cls.folder() / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _stage_files(cls, settings: dict) -> None:
        """The underlay, texture and sheet-picture files the settings name (by content hash), copied to the
        helper's per-computer store, where it looks for them: it opens a plain IFC copy, so the project's
        working folder isn't its own. Missing files are skipped (the app would lack them too)."""
        store = cls.data() / "underlays"
        for name in underlays.referenced(settings):
            target = store / name
            if target.is_file():
                continue  # named by content: an existing copy is the same file
            source = underlays.file_path(name)
            if source is None:
                continue
            store.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(source, target)
            except OSError:
                continue

    @property
    def log_path(self) -> pathlib.Path:
        return self.folder() / "helper.log"

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start(self) -> None:
        app = app_binary()
        if app is None:
            raise _no_app()
        env = dict(os.environ)
        env.pop("QT_QPA_PLATFORM", None)  # the helper needs a real platform plugin; it shows no window anyway
        env.setdefault("KIMBIM_PYTHON_PATH", str(pathlib.Path(__file__).resolve().parents[2]))  # this code
        # Its own data folder: whatever opening a model writes (recovery copies, open/tmp folders, caches)
        # stays out of the user's, and the files the settings use are staged there (_stage_files).
        env["KIMBIM_DATA_DIR"] = str(self.data())
        self._log = open(self.log_path, "ab")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self._proc = subprocess.Popen([str(app), "--snapshot-server"], stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=self._log, env=env, creationflags=flags)
        except OSError as ex:
            self._log.close()
            self._log = None
            raise self._failed(str(ex)) from None
        lines: queue.Queue = queue.Queue()

        def read(stdout=self._proc.stdout):
            for line in stdout:
                lines.put(line)
            lines.put(None)  # EOF: the helper exited

        threading.Thread(target=read, daemon=True, name="kimbim-render-reader").start()
        self._lines = lines
        self._loaded = None

    def _failed(self, error: str, code: str = "") -> AgentError:
        log = str(self.log_path)
        extra = {"helper_code": code} if code else {}
        return AgentError("render_failed", hint=messages.text("hint_render", error=error, log=log),
                          error=error, log=log, **extra)

    def _request(self, req: dict, timeout: float) -> dict:
        if not self.running:
            self.close()
            self._start()
        try:
            self._proc.stdin.write((json.dumps(req) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
            line = self._lines.get(timeout=timeout)
        except (OSError, ValueError) as ex:
            self.close()
            raise self._failed(str(ex)) from None
        except queue.Empty:
            self.close()
            raise self._failed(f"no reply in {timeout:.0f} s") from None
        if line is None:
            code = self._proc.wait()
            self.close()
            raise self._failed(f"the renderer exited (code {code})")
        try:
            reply = json.loads(line)
        except ValueError:
            raise self._failed(f"not JSON: {line[:200]!r}") from None
        if not reply.get("ok"):
            e = reply.get("error") or {}
            raise self._failed(str(e.get("message") or e.get("code") or "?"), str(e.get("code") or ""))
        return reply

    def close(self) -> None:
        """End the helper: EOF on its input (it closes its document and exits), killed if it doesn't."""
        proc, self._proc = self._proc, None
        self._loaded = None
        if proc is not None:
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if self._log is not None:
            self._log.close()
            self._log = None

    # ------------------------------------------------------------ requests

    def _ensure_loaded(self, session) -> None:
        settings = S.to_bytes()
        key = (id(B._model), B._current_id(), hashlib.sha256(settings).hexdigest())
        if self.running and self._loaded == key:
            return
        folder = self.folder()
        stem = K.path_hash(session.source)
        model, settings_path = folder / f"{stem}.ifc", folder / f"{stem}.settings.json"
        try:
            B._model.write(str(model))
            settings_path.write_bytes(settings)
        except (OSError, RuntimeError) as ex:
            raise self._failed(str(ex)) from None
        self._stage_files(S.current())
        self._loaded = None
        self._request({"op": "load", "model": str(model), "settings": str(settings_path)}, LOAD_TIMEOUT)
        self.loads += 1
        self._loaded = key

    def render3d(self, session, **req) -> dict:
        """A 3D picture of the session's model; `req` as the helper's render3d (out, size, camera...)."""
        if app_binary() is None:
            raise _no_app()
        self._ensure_loaded(session)
        return self._request({"op": "render3d", **req}, RENDER_TIMEOUT)

    def svg2png(self, svg: str, out: str, size) -> dict:
        if app_binary() is None:
            raise _no_app()
        return self._request({"op": "svg2png", "svg": svg, "out": out, "size": size}, RENDER_TIMEOUT)
