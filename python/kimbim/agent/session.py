# SPDX-License-Identifier: GPL-3.0-or-later
"""An agent session (D102): one open project, opened the way the app opens it (lock, versioning, settings),
so the app and an agent never edit the same file at once. The lock shows as "KimBim agent"."""
from __future__ import annotations

import json
import pathlib

from .. import app_bridge as B
from .. import authoring as A
from .. import graphics as G
from .. import queries as Q
from .. import documents as D
from .. import kimfile as K
from .. import settings as S
from .catalogue import AgentError
from .tasks import Tasks


class Session:
    def __init__(self, kind: str, source: str, client: str = "cli"):
        self.kind = kind
        self.source = source
        self.client = client
        self.tasks = None  # the project's agent tasks (agent.tasks.Tasks), set by open()
        self.renderer = None  # the snapshot renderer (agent.render.Renderer), started by the first snapshot
        self._saved_user = ""
        self._closed = False
        self.live = False  # attached to the project the app already has open (D102 phase 2)
        self._selection_get = None  # live: () -> [GlobalId]; the app pushes its selection
        self._selection_set = None  # live: ([GlobalId]) -> None; the app selects them on its next poll

    @property
    def work(self) -> str:
        return D._doc["work"]

    @property
    def unit(self) -> str:
        return S.current().get("length_unit", "m")

    @classmethod
    def attach(cls, source: str, kind: str, client: str = "assistant") -> "Session":
        """A session over the document the app already has open: no opening, locking or creating of tasks'
        storage. The app owns the document and the lock; it drives calls on its own thread."""
        session = cls(kind, source, client)
        session.tasks = Tasks(session)
        session.live = True
        return session

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
            session.tasks = Tasks(session)
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
            if self.renderer is not None:
                self.renderer.close()  # the windowless helper goes with the session
            if not self.live:  # the app owns its open document: closing the session must not close it
                D.close_document()
        finally:
            if not self.live:
                K.display_user = self._saved_user

    def resolve(self, selector) -> list[str]:
        """GlobalIds for a selector: a GlobalId list, "selection" (needs the app) or a find object. Raises
        not_found for an unknown GlobalId or level and no_match when nothing matches."""
        if selector == "selection":
            if self._selection_get is None:
                raise AgentError("needs_app")
            guids = list(self._selection_get())
            if not guids:
                raise AgentError("no_match")
            return guids
        if isinstance(selector, (list, tuple)):
            for g in selector:
                try:
                    B._model.by_guid(g)
                except RuntimeError:
                    raise AgentError("not_found", what=g) from None
            if not selector:
                raise AgentError("no_match")
            return list(selector)
        if not isinstance(selector, dict):
            raise AgentError("bad_input", hint="unsupported selector")
        shortcuts = []
        if selector.get("kind") is not None:
            kind = str(selector["kind"]).strip().lower()
            kind = kind if kind in G.KINDS else kind + "s"
            if kind not in G.KINDS:
                raise AgentError("bad_input", hint=f"unknown kind {selector['kind']}")
            shortcuts.append({"field": "kind", "op": "equals", "value": kind})
        if selector.get("level") is not None:
            want = str(selector["level"])
            hit = next((s for s in json.loads(A.storeys())["storeys"]
                        if s["guid"] == want or s["name"].strip().lower() == want.strip().lower()), None)
            if hit is None:
                raise AgentError("not_found", what=want)
            shortcuts.append({"field": "level", "op": "equals", "value": hit["guid"]})
        for key in ("ifc_class", "name", "type", "layer", "status"):
            if selector.get(key) is not None:
                shortcuts.append({"field": key, "op": "equals", "value": selector[key]})
        where = list(selector.get("where") or ())
        match = selector.get("match", "all")
        if match == "any" and shortcuts:
            raise AgentError("bad_input", hint="match any can't mix with the shortcut fields; put them in where")
        out = json.loads(Q.find_elements(json.dumps({"rows": shortcuts + where, "match": match})))
        if not out.get("ok"):
            raise AgentError("bad_input", hint=str(out.get("error") or ""))
        if not out["guids"]:
            raise AgentError("no_match")
        return out["guids"]

    def label(self, guid: str) -> str:
        e = B._model.by_guid(guid)
        text = f"{e.is_a()[3:]} {e.Name or ''}".strip()
        storey = None
        for rel in getattr(e, "ContainedInStructure", None) or ():
            storey = rel.RelatingStructure
        return f"{text}, {storey.Name}" if storey is not None and storey.Name else text
