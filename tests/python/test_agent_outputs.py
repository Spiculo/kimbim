# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent drawing, sheet, schedule, check, version, selection and script tools on the sample house (D102)."""
import json
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge as B
from kimbim import checks as C
from kimbim import documents as D
from kimbim import kimfile as K
from kimbim import settings as S
from kimbim.agent.catalogue import call_tool
from kimbim.agent.session import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_house  # noqa: E402


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
    assert json.loads(S.set_project_settings(json.dumps({"agent_changes": "direct"})))["ok"]
    yield session
    session.close()


def run(s, tool_name, **args):
    return call_tool(s, tool_name, args, client="test")


def test_plan_and_sheet_export_svg(s, tmp_path):
    plan = run(s, "drawings.create", kind="plan", level="Level 1")
    assert plan["ok"], plan
    guid = plan["result"]["guid"]
    assert any(d["guid"] == guid and d["kind"] == "plan" for d in run(s, "drawings.list")["result"]["drawings"])
    sheet = run(s, "sheets.create", title="Ground floor")
    assert sheet["ok"] and sheet["result"]["number"]
    number = sheet["result"]["number"]
    placed = run(s, "sheets.place_drawing", sheet=number, drawing=guid, scale=100)
    assert placed["ok"], placed
    assert run(s, "sheets.list")["result"]["sheets"][0]["views"]
    out = tmp_path / "sheet.svg"
    r = run(s, "sheets.export", sheet=number, format="svg", out=str(out))
    assert r["ok"], r
    assert "<svg" in out.read_text(encoding="utf-8")
    dxf = tmp_path / "plan.dxf"
    assert run(s, "drawings.export", drawing=guid, format="dxf", out=str(dxf))["ok"] and dxf.exists()
    svg = tmp_path / "plan.svg"
    assert run(s, "drawings.export", drawing=guid, format="svg", out=str(svg))["ok"]
    assert "<svg" in svg.read_text(encoding="utf-8")


def _digest(tmp_path, name):
    """The model as an IFC file's text, without the header (it carries a timestamp)."""
    path = tmp_path / name
    assert json.loads(D.export_ifc(str(path)))["ok"]
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.startswith("FILE_NAME"))


def test_section_and_exports_change_nothing(s, tmp_path):
    r = run(s, "drawings.create", kind="section", line=[[0, 2], [8, 2]])
    assert r["ok"] and r["result"]["guid"], r
    plan = run(s, "drawings.create", kind="plan", level="Level 1")["result"]["guid"]
    number = run(s, "sheets.create", title="S")["result"]["number"]
    assert run(s, "sheets.place_drawing", sheet=number, drawing=plan)["ok"]
    before, steps, current = _digest(tmp_path, "before.ifc"), len(B._ids), B._current_id()
    calls = [("drawings.export", dict(drawing=plan, format="svg", out=str(tmp_path / "d.svg"))),
             ("drawings.export", dict(drawing=plan, format="dxf", out=str(tmp_path / "d.dxf"))),
             ("sheets.export", dict(sheet=number, format="svg", out=str(tmp_path / "s.svg"))),
             ("sheets.export", dict(sheet=number, format="dxf", out=str(tmp_path / "s.dxf"))),
             ("schedules.export", dict(schedule="doors", out=str(tmp_path / "s.csv"))),
             ("checks.run", dict(checks=["model"])),
             ("versions.export", dict(out=str(tmp_path / "v.ifc"))),
             ("versions.diff", {"from": "HEAD", "to": "WORKING"})]
    for name, args in calls:
        assert run(s, name, **args)["ok"], name
    for f in ("d.svg", "d.dxf", "s.svg", "s.dxf", "s.csv", "v.ifc"):
        assert (tmp_path / f).stat().st_size > 0, f
    assert len(B._ids) == steps and B._current_id() == current
    assert _digest(tmp_path, "after.ifc") == before


def test_pdf_without_the_binary_is_render_failed(s, tmp_path, monkeypatch):
    monkeypatch.setenv("KIMBIM_APP", str(tmp_path / "nope.exe"))
    number = run(s, "sheets.create", title="A")["result"]["number"]
    r = run(s, "sheets.export", sheet=number, format="pdf", out=str(tmp_path / "a.pdf"))
    assert not r["ok"] and r["error"]["code"] == "render_failed" and r["error"]["hint"]


def test_schedule_get_doors(s):
    names = {x["id"] for x in run(s, "schedules.list")["result"]["schedules"]}
    assert "doors" in names
    r = run(s, "schedules.get", schedule="Doors", limit=1)
    assert r["ok"], r
    assert r["result"]["columns"] and r["result"]["count"] >= 1 and len(r["result"]["rows"]) <= 1
    assert run(s, "schedules.get", schedule="nope")["error"]["code"] == "not_found"


def test_checks_model(s):
    r = run(s, "checks.run", checks=["model"])
    assert r["ok"], r
    assert r["result"]["checks"][0]["check"] == "model" and "counts" in r["result"]["checks"][0]


IDS = """<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS" xmlns:xs="http://www.w3.org/2001/XMLSchema"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:schemaLocation="http://standards.buildingsmart.org/IDS http://standards.buildingsmart.org/IDS/1.0/ids.xsd">
  <info><title>Rules</title></info>
  <specifications>
    <specification name="Walls have a name" ifcVersion="IFC2X3 IFC4">
      <applicability minOccurs="0" maxOccurs="unbounded"><entity><name><simpleValue>IFCWALL</simpleValue></name></entity></applicability>
      <requirements><attribute><name><simpleValue>Name</simpleValue></name></attribute></requirements>
    </specification>
  </specifications>
</ids>
"""


def test_ids_report_before_any_run(s, tmp_path, monkeypatch):
    monkeypatch.setattr(C, "_last_ids", {})
    r = run(s, "checks.ids_report", out=str(tmp_path / "ids.html"))
    assert not r["ok"] and r["error"]["code"] == "bridge_error" and "run the IDS check first" in r["error"]["hint"]
    assert not (tmp_path / "ids.html").exists()


def test_ids_report_after_a_run(s, tmp_path):
    assert json.loads(S.set_project_settings(json.dumps({"ids_files": {"rules.ids": IDS}})))["ok"]
    assert run(s, "checks.run", checks=["ids"])["ok"]
    out = tmp_path / "ids.html"
    r = run(s, "checks.ids_report", out=str(out))
    assert r["ok"], r
    assert "<html" in out.read_text(encoding="utf-8").lower()


def test_elevations_and_hand_placed_elevation(s):
    r = run(s, "drawings.create", kind="elevation")
    assert r["ok"] and r["result"]["drawings"], r
    r = run(s, "drawings.create", kind="elevation", line=[[0, -1], [8, -1]], direction="right")
    assert r["ok"] and r["result"]["guid"], r
    assert r["result"]["guid"] in {d["guid"] for d in run(s, "drawings.list")["result"]["drawings"]
                                   if d["kind"] == "elevation"}


def test_versions_log_after_task(s):
    assert run(s, "task.start", title="Rename", mode="direct")["ok"]
    wall = B._model.by_type("IfcWall")[0].GlobalId
    assert run(s, "elements.rename", elements=[wall], name="W-X")["ok"]
    assert run(s, "task.finish", summary="done")["ok"]
    log = run(s, "versions.log", limit=10)
    assert log["ok"], log
    assert any("Before agent" in v["message"] for v in log["result"]["versions"])
    assert run(s, "versions.options")["ok"] and run(s, "versions.milestones")["ok"]
    head = log["result"]["versions"][0]["id"]
    older = log["result"]["versions"][-1]["id"]
    assert run(s, "versions.diff", **{"from": older, "to": head})["ok"]
    assert run(s, "versions.element_history", element=wall)["ok"]


def test_versions_export(s, tmp_path):
    out = tmp_path / "head.ifc"
    r = run(s, "versions.export", out=str(out))
    assert r["ok"], r
    assert out.stat().st_size > 0
    first = run(s, "versions.log")["result"]["versions"][-1]["id"]
    older = tmp_path / "older.ifc"
    assert run(s, "versions.export", version=first, out=str(older))["ok"] and older.stat().st_size > 0
    bad = run(s, "versions.export", version="no-such-version", out=str(tmp_path / "x.ifc"))
    assert bad["error"]["code"] == "not_found"
    blocked = run(s, "versions.export", out=str(tmp_path))  # a directory
    assert blocked["error"]["code"] == "bridge_error"


def test_selection_needs_app(s):
    assert run(s, "selection.get")["error"]["code"] == "needs_app"
    assert run(s, "selection.set", elements=[])["error"]["code"] == "needs_app"


def test_script_gate(s):
    wall = B._model.by_type("IfcWall")[0]
    code = f"ifc.by_guid('{wall.GlobalId}').Name = 'Scripted'"
    r = run(s, "script.run", code=code)
    assert not r["ok"] and r["error"]["code"] == "scripts_off"
    # the architect turns it on (not the tool: project.set_settings refuses the key)
    assert json.loads(S.set_project_settings(json.dumps({"agent_scripts": True})))["ok"]
    r = run(s, "script.run", code="print('hi')\nbridge.rename_element if False else None")
    assert r["ok"] and "hi" in r["result"]["output"], r
    r = run(s, "script.run", code=f"import ifcopenshell.api\nwith edit():\n    ifc.by_guid('{wall.GlobalId}').Name = 'Scripted'\n")
    assert r["ok"], r
    assert B._model.by_guid(wall.GlobalId).Name == "Scripted"
    assert [m["guid"] for m in r["changes"]["modified"]] == [wall.GlobalId]
    steps = len(B._ids)
    B.undo()
    assert B._model.by_guid(wall.GlobalId).Name != "Scripted" and len(B._ids) == steps - 1
    B.redo()
    # a failing script raises and rolls back
    r = run(s, "script.run", code=f"ifc.by_guid('{wall.GlobalId}').Name = 'Half'\nraise ValueError('boom')")
    assert not r["ok"] and "boom" in r["error"]["hint"]
    assert B._model.by_guid(wall.GlobalId).Name == "Scripted"


def test_script_dry_run_rolls_back(s):
    assert json.loads(S.set_project_settings(json.dumps({"agent_scripts": True})))["ok"]
    wall = B._model.by_type("IfcWall")[0]
    old = wall.Name
    r = run(s, "script.run", code=f"ifc.by_guid('{wall.GlobalId}').Name = 'Dry'", dry_run=True)
    assert r["ok"] and r["changes"]["dry_run"]
    assert B._model.by_guid(wall.GlobalId).Name == old
