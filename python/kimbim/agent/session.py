# SPDX-License-Identifier: GPL-3.0-or-later
"""An agent session (D102): one open project, opened the way the app opens it (lock, versioning, settings),
so the app and an agent never edit the same file at once. The lock shows as "KimBim agent"."""
from __future__ import annotations

import json
import pathlib

from .. import app_bridge as B
from .. import documents as D
from .. import kimfile as K
from .. import settings as S
from .catalogue import AgentError


class Session:
    def __init__(self, kind: str, source: str, client: str = "cli"):
        self.kind = kind
        self.source = source
        self.client = client
        self.tasks = None  # filled by the task manager (Task 5)
        self._saved_user = ""
        self._closed = False

    @property
    def work(self) -> str:
        return D._doc["work"]

    @property
    def unit(self) -> str:
        return S.current().get("length_unit", "m")

    @classmethod
    def open(cls, path: str, client: str = "cli") -> "Session":
        p = pathlib.Path(path)
        if p.is_dir():
            kind = "folder"
        elif p.suffix.lower() == ".kim":
            kind = "kim"
        elif p.suffix.lower() == ".ifc":
            kind = "ifc"
        else:
            raise AgentError("bridge_error", hint=f"cannot open {path}")
        if kind != "ifc" and not p.exists():
            raise AgentError("not_found", what=str(p))
        session = cls(kind, str(p), client)
        session._saved_user = K.display_user
        K.display_user = "KimBim agent"
        try:
            session._open(p)
        except BaseException:
            K.display_user = session._saved_user
            raise
        return session

    def _open(self, p: pathlib.Path) -> None:
        if self.kind == "ifc":
            out = json.loads(B.open_model(str(p)))
        else:
            out = json.loads(D.open_kim(str(p)) if self.kind == "kim" else D.open_folder(str(p)))
            if out.get("locked"):
                raise AgentError("project_locked", holder=out["locked"])
            if out.get("ok"):
                out = json.loads(B.open_model(out["path"]))
                if not out.get("ok"):
                    D.discard_pending()
        if not out.get("ok"):
            raise AgentError("bridge_error", hint=str(out.get("error") or ""))

    def save(self) -> None:
        if self.kind == "ifc":
            out = json.loads(B.save())
        else:
            out = json.loads(D.save_document())
        if not out.get("ok"):
            raise AgentError("bridge_error", hint=str(out.get("error") or ""))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            D.close_document()
        finally:
            K.display_user = self._saved_user

    def resolve(self, selector) -> list[str]:
        """GlobalIds for a selector. Task 4 adds query selectors and "selection"."""
        if isinstance(selector, (list, tuple)) and all(isinstance(g, str) for g in selector):
            for g in selector:
                try:
                    B._model.by_guid(g)
                except RuntimeError:
                    raise AgentError("not_found", what=g) from None
            return list(selector)
        raise AgentError("bridge_error", hint="unsupported selector")

    def label(self, guid: str) -> str:
        e = B._model.by_guid(guid)
        text = f"{e.is_a()[3:]} {e.Name or ''}".strip()
        storey = None
        for rel in getattr(e, "ContainedInStructure", None) or ():
            storey = rel.RelatingStructure
        return f"{text}, {storey.Name}" if storey is not None and storey.Name else text
