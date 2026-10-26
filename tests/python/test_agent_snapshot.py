# SPDX-License-Identifier: GPL-3.0-or-later
"""snapshot.take on the sample house (D102, spec §6): 3D pictures from the app's windowless renderer, plans,
drawings and sheets from the drawing generator. Tests marked `app` need the built app binary
(build/app/kimbim-app, or KIMBIM_APP) and are skipped without it."""
import json
import re
import struct
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import documents as D
from kimbim import kimfile as K
from kimbim import versioning as V
from kimbim.agent import render
from kimbim.agent.catalogue import call_tool
from kimbim.agent.session import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402

app = pytest.mark.app
needs_app = pytest.mark.skipif(render.app_binary() is None, reason="the KimBim app binary isn't built")


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_data_dir", tmp_path / "data")
    monkeypatch.setattr(K, "display_user", "")
    ifc = tmp_path / "house.ifc"
    make_house.build(str(ifc))
    out = json.loads(D.import_ifc(str(ifc), str(tmp_path / "house.kim")))
    assert out["ok"]
    D.close_document()
    session = Session.open(str(tmp_path / "house.kim"))
    yield session
    session.close()
    assert session.renderer is None or not session.renderer.running  # the helper went with the session


def run(s, tool_name, **args):
    return call_tool(s, tool_name, args, client="test")


def png_size(path) -> tuple[int, int]:
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", data[16:24])


def _digest(tmp_path, name):
    path = tmp_path / name
    assert json.loads(D.export_ifc(str(path)))["ok"]
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.startswith("FILE_NAME"))


def test_compare_colours_match_the_app():
    """The legend's colours are the app's Compare colours (HistoryPanel::addedColor / modifiedColor)."""
    header = (ROOT / "app" / "src" / "HistoryPanel.h").read_text(encoding="utf-8")

    def colour(name):
        m = re.search(rf"{name}\(\)\s*\{{\s*return QColor\((\d+),\s*(\d+),\s*(\d+)\)", header)
        assert m, name
        return "#%02x%02x%02x" % tuple(int(v) for v in m.groups())

    assert render.ADDED == colour("addedColor")
    assert render.MODIFIED == colour("modifiedColor")


@app
@needs_app
def test_snapshot_3d_default(s, tmp_path):
    before, current = _digest(tmp_path, "before.ifc"), B._current_id()
    r = run(s, "snapshot.take")
    assert r["ok"], r
    res = r["result"]
    assert res["format"] == "png" and res["size"] == [1024, 768]
    assert png_size(res["path"]) == (1024, 768)
    assert Path(res["path"]).parent == D.data_dir() / "agent" / "snapshots"
    assert res["framed"] > 10 and res["legend"] == []
    assert set(res["camera"]) >= {"eye", "target", "up", "fov"}
    out = tmp_path / "top.png"
    r = run(s, "snapshot.take", camera="top", style="lines", size=[400, 300], out=str(out),
            elements={"kind": "column"}, highlight={"kind": "column"})
    assert r["ok"], r
    assert r["result"]["path"] == str(out) and png_size(out) == (400, 300)
    assert r["result"]["framed"] == 1
    assert [e["meaning"] for e in r["result"]["legend"]] == ["highlight"]
    assert B._current_id() == current and _digest(tmp_path, "after.ifc") == before  # a read tool


@app
@needs_app
def test_snapshot_plan_level1(s, tmp_path):
    r = run(s, "snapshot.take", view="plan", level="Level 1", size=[800, 600])
    assert r["ok"], r
    assert r["result"]["format"] == "png" and png_size(r["result"]["path"]) == (800, 600)
    assert r["result"]["camera"] is None
    svg = tmp_path / "plan.svg"
    r = run(s, "snapshot.take", view="plan", level="Level 1", format="svg", out=str(svg))
    assert r["ok"], r
    assert r["result"]["format"] == "svg" and "<svg" in svg.read_text(encoding="utf-8")
    sec = run(s, "snapshot.take", view="section", size=[300, 200])
    assert sec["ok"] and png_size(sec["result"]["path"]) == (300, 200), sec
    elev = run(s, "snapshot.take", view="drawing", drawing="South Elevation", format="svg")
    assert elev["ok"] and elev["result"]["path"].endswith(".svg"), elev


def test_snapshot_plan_unknown_level(s):
    r = run(s, "snapshot.take", view="plan", level="Level 9", format="svg")
    assert not r["ok"] and r["error"]["code"] == "not_found"


@app
@needs_app
def test_snapshot_changes_task(s):
    assert run(s, "task.start", title="Widen windows")["ok"]
    windows = s.resolve({"kind": "window", "level": "Level 1"})
    assert len(windows) == 4
    assert run(s, "elements.set_dimensions", elements=windows, width="+50cm")["ok"]
    task = s.tasks.open_task("test")
    diff = json.loads(V.compare(task.base_version, "WORKING"))
    shown = {e["guid"] for e in diff["added"] + diff["modified"] if e["type"] != "IfcOpeningElement"}
    assert set(windows) <= shown
    r = run(s, "snapshot.take", changes="task")
    assert r["ok"], r
    res = r["result"]
    assert {"colour": render.MODIFIED, "meaning": "modified", "count": len(diff["modified"])} in res["legend"]
    assert res["changes"] == {"added": len(diff["added"]), "modified": len(diff["modified"]),
                              "removed": len(diff["removed"])}
    assert res["framed"] == len(shown)  # framed on the coloured elements
    revs = run(s, "snapshot.take", changes={"rev_a": task.base_version}, elements=windows, size=[200, 150])
    assert revs["ok"] and revs["result"]["changes"] == res["changes"] and revs["result"]["framed"] == 4, revs
    assert run(s, "task.status")["result"]["task"]["status"] == "open"


def test_compare_reports_only_the_widened_windows(s):
    """What a changes snapshot colours is versioning.compare's list: it should be the 4 Level 1 windows."""
    assert run(s, "task.start", title="Widen windows")["ok"]
    windows = s.resolve({"kind": "window", "level": "Level 1"})
    assert run(s, "elements.set_dimensions", elements=windows, width="+50cm")["ok"]
    diff = json.loads(V.compare(s.tasks.open_task("test").base_version, "WORKING"))
    assert sorted(e["guid"] for e in diff["modified"] if e["type"] == "IfcWindow") == sorted(windows)


def test_renderer_stages_the_files_settings_use(s, tmp_path):
    """Textures and underlays named in the settings are copied where the helper (a plain IFC copy, its own
    data folder) looks for them."""
    from kimbim import underlays

    name = "ab" * 20 + ".png"
    store = underlays.store_dir()
    store.mkdir(parents=True, exist_ok=True)
    (store / name).write_bytes(b"picture")
    render.Renderer._stage_files({"texture_files": [name, "cd" * 20 + ".png"]})  # the second is missing
    staged = render.Renderer.data() / "underlays"
    assert (staged / name).read_bytes() == b"picture"
    assert not (staged / ("cd" * 20 + ".png")).exists()
    assert render.Renderer.data() != D.data_dir()


@app
@needs_app
def test_helper_keeps_out_of_the_data_folder(s):
    before = {p.name for p in D.data_dir().iterdir()}
    assert run(s, "snapshot.take", size=[200, 150])["ok"]
    assert {p.name for p in D.data_dir().iterdir()} - before <= {"agent"}
    assert not (D.data_dir() / "recovery").exists()
    assert (D.data_dir() / "agent" / "render" / "data").is_dir()


def test_snapshot_changes_without_task(s):
    r = run(s, "snapshot.take", changes="task")
    assert not r["ok"] and r["error"]["code"] == "no_task"


def test_snapshot_svg_sheet(s, tmp_path):
    before, current = _digest(tmp_path, "before.ifc"), B._current_id()
    out = tmp_path / "a01.svg"
    r = run(s, "snapshot.take", view="sheet", sheet="A01", format="svg", out=str(out))
    assert r["ok"], r
    assert r["result"] == {"path": str(out), "format": "svg", "size": None, "camera": None, "framed": None,
                           "legend": [], "view": "sheet"}
    assert "<svg" in out.read_text(encoding="utf-8")
    default = run(s, "snapshot.take", view="sheet", format="svg")  # the first sheet, a default path
    assert default["ok"] and Path(default["result"]["path"]).read_text(encoding="utf-8").lstrip().startswith("<")
    assert run(s, "snapshot.take", format="svg")["error"]["code"] == "bad_input"  # 3D has no SVG
    assert B._current_id() == current and _digest(tmp_path, "after.ifc") == before


def test_snapshot_without_the_binary_is_render_failed(s, tmp_path, monkeypatch):
    monkeypatch.setenv("KIMBIM_APP", str(tmp_path / "missing.exe"))
    r = run(s, "snapshot.take")
    assert not r["ok"] and r["error"]["code"] == "render_failed"
    assert "KIMBIM_APP" in r["error"]["hint"]


@app
@needs_app
def test_renderer_reuses_load(s):
    assert run(s, "snapshot.take", size=[200, 150])["ok"]
    assert run(s, "snapshot.take", size=[200, 150], camera="front")["ok"]
    assert s.renderer.loads == 1
    walls = s.resolve({"kind": "wall", "level": "Level 1"})
    assert call_tool(s, "elements.rename", {"elements": walls[:1], "name": "Renamed"}, client="test")["ok"]
    assert run(s, "snapshot.take", size=[200, 150])["ok"]
    assert s.renderer.loads == 2  # the model changed: loaded again
