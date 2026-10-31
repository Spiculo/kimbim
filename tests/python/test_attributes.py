# SPDX-License-Identifier: GPL-3.0-or-later
"""The attribute manager: an office's standards (settings tables, layers, materials, surfaces and
composites) exported to one file and merged into another project."""
import json

import ifcopenshell
import ifcopenshell.validate
import pytest

from kimbim import app_bridge as b
from kimbim import attributes as A
from kimbim import materials as M
from kimbim import settings as s


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def attr(fn, *args):
    return json.loads(getattr(A, fn)(*args))


def new_project(name="Standards"):
    r = call("new_project", name)
    assert r["ok"], r


def add_office_standards():
    """A source office: its own pen set, line type, fill, sets and purposes, plus its IFC material,
    surface, composite and layer."""
    r = json.loads(s.set_project_settings(json.dumps({
        "pen_sets": {"Office": {"pens": {
            "10": {"color": "#112233", "weight": 0.35, "name": "Office walls"},
            "23": {"color": "#000000", "weight": 0.18, "name": "Office annotations"}}}},
        "line_types": {"Solid": [], "Office axis": [6.0, 1.5]},
        "fill_patterns": {"Office hatch": {"lines": [{"angle": 30, "spacing": 1.5}]}},
        "visibility_sets": {"Office": {"hidden_kinds": ["furniture"], "rules": []}},
        "override_sets": {"Office": {"rules": []}},
        "layer_combinations": {"Office": {"hidden": ["A-GRID"], "locked": []}},
        "purposes": {"Office": {"pen_set": "Office", "visibility": "Office", "overrides": "Office",
                                "layers": "Office", "renovation": "Everything"}},
        "renovation_styles": {"Office": {"new": {"pen": 38, "line": "Solid", "fill": 39}}},
    })))
    assert r["ok"], r
    r = call("apply_materials", json.dumps({
        "surfaces": [{"name": "Office lime", "colour": "#e8e0c8", "transparency": 0.0, "shine": 0.2,
                      "reflectance": "MATT"}],
        "materials": [{"name": "Office lime plaster", "category": "Finish", "surface": "Office lime",
                       "pen": 12, "pattern": "Office hatch", "priority": 350, "density": 1500}],
        "composites": [{"name": "Office wall 250", "type": "IfcWallType",
                        "layers": [{"material": "Office lime plaster", "thickness": 0.25, "core": True}]}],
    }))
    assert r["ok"], r
    assert call("create_layer", "A-OFFICE")["ok"]


def layer_names():
    return {layer.Name for layer in b._model.by_type("IfcPresentationLayerAssignment")}


def material(name):
    return next((m for m in b._model.by_type("IfcMaterial") if m.Name == name), None)


@pytest.fixture
def office(tmp_path):
    new_project("Source")
    add_office_standards()
    path = tmp_path / "office-standards.json"
    r = attr("export_attributes", str(path))
    assert r["ok"], r
    return path, r


# ---------------------------------------------------------------- catalogue and export

def test_catalogue_lists_the_projects_attributes(tmp_path):
    new_project("Source")
    add_office_standards()
    r = attr("attribute_catalogue")
    assert r["ok"], r
    groups = r["groups"]
    assert groups["pens"] == 1 and groups["line_types"] == 2 and groups["fill_patterns"] == 1
    assert groups["purposes"] == 1 and groups["layer_combinations"] == 1
    assert groups["layers"] == len(r["layers"]) >= 1
    assert "A-OFFICE" in [layer["name"] for layer in r["layers"]]
    assert "Office lime plaster" in [m["name"] for m in r["materials"]]
    assert "Office lime" in [surface["name"] for surface in r["surfaces"]]
    assert "Office wall 250" in [composite["name"] for composite in r["composites"]]
    assert r["order"] == list(A.GROUPS)


def test_export_writes_a_self_contained_file(office):
    path, r = office
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == "kimbim-attributes/1"
    assert data["saved"]
    assert data["settings"]["line_types"]["Office axis"] == [6.0, 1.5]
    assert data["settings"]["pen_sets"]["Office"]["pens"]["10"]["color"] == "#112233"
    assert data["settings"]["purposes"]["Office"]["pen_set"] == "Office"
    assert "A-OFFICE" in [layer["name"] for layer in data["layers"]]
    lime = next(m for m in data["materials"] if m["name"] == "Office lime plaster")
    assert lime["surface"] == "Office lime" and lime["pen"] == 12
    assert [layer["material"] for layer in data["composites"][0]["layers"]] == ["Office lime plaster"]
    assert r["counts"]["materials"] == len(data["materials"])
    assert r["counts"]["line_types"] == len(data["settings"]["line_types"])
    assert path.name in r["path"]


# ---------------------------------------------------------------- import

def test_import_merges_settings_and_creates_ifc_attributes(office):
    path, _r = office
    new_project("Target")
    assert "Office" not in s.current()["pen_sets"]
    r = attr("import_attributes", str(path))
    assert r["ok"], r
    st = s.current()
    assert st["pen_sets"]["Office"]["pens"]["10"]["color"] == "#112233"
    assert "Working" in st["pen_sets"]  # merged over the built-ins, not replacing them
    assert st["line_types"]["Office axis"] == [6.0, 1.5] and "Solid" in st["line_types"]
    assert st["visibility_sets"]["Office"]["hidden_kinds"] == ["furniture"]
    assert st["purposes"]["Office"]["pen_set"] == "Office"
    assert st["layer_combinations"]["Office"]["hidden"] == ["A-GRID"]
    assert st["renovation_styles"]["Office"]["new"]["pen"] == 38
    lime = material("Office lime plaster")
    assert lime is not None and lime.Category == "Finish"
    assert M.surface_look(M.surface_of(lime))["colour"] == "#e8e0c8"
    assert M.properties(lime)["pen"] == 12 and M.properties(lime)["pattern"] == "Office hatch"
    assert any(style.Name == "Office lime" for style in b._model.by_type("IfcSurfaceStyle"))
    assert "A-OFFICE" in layer_names()
    composite = next(c for c in call("materials_state")["composites"] if c["name"] == "Office wall 250")
    assert [layer["material"] for layer in composite["layers"]] == ["Office lime plaster"]
    assert composite["layers"][0]["thickness"] == pytest.approx(0.25)
    assert r["imported"]["line_types"] >= 1 and r["imported"]["materials"] == 1
    assert r["settings"] is True


def test_import_keeps_existing_names_unless_replace(office):
    path, _r = office
    new_project("Target")
    assert attr("import_attributes", str(path))["ok"]
    # the target changes its own line type and material afterwards
    changed = json.loads(s.set_project_settings(
        json.dumps({"line_types": {"Solid": [], "Office axis": [2.0, 2.0]}})))
    assert changed["ok"]
    current = next(m for m in call("materials_state")["materials"] if m["name"] == "Office lime plaster")
    assert call("apply_materials", json.dumps({"materials": [{**current, "pen": 99}]}))["ok"]
    # without replace, the project keeps its own versions
    r = attr("import_attributes", str(path))
    assert r["ok"], r
    assert s.current()["line_types"]["Office axis"] == [2.0, 2.0]
    assert M.properties(material("Office lime plaster"))["pen"] == 99
    assert any("Office axis" in message for message in r["skipped"])
    assert any("Office lime plaster" in message for message in r["skipped"])
    # with replace, the file's versions win
    r = attr("import_attributes", str(path), json.dumps({"replace": True}))
    assert r["ok"], r
    assert s.current()["line_types"]["Office axis"] == [6.0, 1.5]
    assert M.properties(material("Office lime plaster"))["pen"] == 12


def test_import_can_select_groups(office):
    path, _r = office
    new_project("Target")
    r = attr("import_attributes", str(path), json.dumps({"groups": ["line_types", "surfaces", "materials"]}))
    assert r["ok"], r
    assert s.current()["line_types"]["Office axis"] == [6.0, 1.5]
    assert "Office" not in s.current()["pen_sets"]
    assert material("Office lime plaster") is not None
    assert any(style.Name == "Office lime" for style in b._model.by_type("IfcSurfaceStyle"))
    assert "A-OFFICE" not in layer_names()
    assert not any(ls.LayerSetName == "Office wall 250" for ls in b._model.by_type("IfcMaterialLayerSet"))


def test_import_without_the_surfaces_group_creates_the_material_without_one(office):
    path, _r = office
    new_project("Target")
    r = attr("import_attributes", str(path), json.dumps({"groups": ["materials"]}))
    assert r["ok"], r
    lime = material("Office lime plaster")
    assert lime is not None and M.surface_of(lime) is None
    assert any("Office lime" in message for message in r["skipped"])


def test_import_brings_a_layer_and_reports_a_lost_colour(tmp_path):
    new_project("Target")
    path = tmp_path / "layers.json"
    path.write_text(json.dumps({
        "format": "kimbim-attributes/1", "saved": "", "settings": {},
        "layers": [{"name": "A-COLOUR", "colour": "#ff0000", "weight": 0.25}],
        "materials": [], "surfaces": [], "composites": [],
    }), encoding="utf-8")
    r = attr("import_attributes", str(path))
    assert r["ok"], r
    assert any("A-COLOUR" in message and "colour" in message for message in r["skipped"])
    assert "A-COLOUR" in layer_names()
    level = call("storeys")["storeys"][0]["guid"]
    wall = call("create_wall", level, call("wall_types")["types"][0]["guid"], 0, 0, 4, 0, 3.0)["guid"]
    assert call("assign_layer", json.dumps([wall]), "A-COLOUR")["ok"]
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    assert [s for s in logger.statements if s.get("level") == "error"] == []


def test_import_refuses_bad_files_and_options(tmp_path):
    new_project("Target")
    r = attr("import_attributes", str(tmp_path / "missing.json"))
    assert not r["ok"] and "cannot read" in r["error"]
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    r = attr("import_attributes", str(broken))
    assert not r["ok"] and "not an attribute file" in r["error"]
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"format": "some-other-format/2"}), encoding="utf-8")
    r = attr("import_attributes", str(wrong))
    assert not r["ok"] and "unknown format" in r["error"]
    r = attr("import_attributes", str(wrong), json.dumps({"groups": ["towers"]}))
    assert not r["ok"] and "towers" in r["error"]
    r = attr("import_attributes", str(wrong), "not json")
    assert not r["ok"] and "bad options" in r["error"]
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps({
        "format": "kimbim-attributes/1", "settings": ["not a table"], "layers": "not a list",
        "materials": [1], "composites": [{"name": "Broken", "layers": ["not an object"]}],
    }), encoding="utf-8")
    r = attr("import_attributes", str(odd))  # malformed sections are skipped, never raised
    assert r["ok"] and r["skipped"]


def test_settings_only_import_is_a_settings_step(office):
    path, _r = office
    new_project("Target")
    assert not call("state")["can_undo"]
    r = attr("import_attributes", str(path), json.dumps({"groups": ["pens", "line_types"]}))
    assert r["ok"], r
    assert s.current()["pen_sets"]["Office"]["pens"]["10"]["color"] == "#112233"
    assert not call("state")["can_undo"]  # settings apply as a settings step, not an empty undo step
    assert s.is_dirty()


def test_the_ifc_part_of_an_import_is_one_undo_step(office):
    path, _r = office
    new_project("Target")
    assert attr("import_attributes", str(path))["ok"]
    assert material("Office lime plaster") is not None and "A-OFFICE" in layer_names()
    assert call("undo")["ok"]
    assert material("Office lime plaster") is None and "A-OFFICE" not in layer_names()
    assert not any(ls.LayerSetName == "Office wall 250" for ls in b._model.by_type("IfcMaterialLayerSet"))
    assert s.current()["line_types"]["Office axis"] == [6.0, 1.5]  # the settings step is not undone


def test_agent_tools_are_registered():
    import kimbim.agent.tools.attributes  # noqa: F401
    from kimbim.agent import catalogue

    for name in ("attributes.catalogue", "attributes.export", "attributes.import"):
        assert name in catalogue.TOOLS


def test_agent_tools_export_and_dry_run_import(office, tmp_path):
    import types

    from kimbim.agent.catalogue import call_tool

    class Tasks:
        def for_write(self, client, task_id, title):
            return None

        def record(self, changes):
            pass

        def resume(self, client, task_id):
            pass

        def write_failed(self):
            pass

    session = types.SimpleNamespace(tasks=Tasks(), label=lambda guid: guid)
    path, _r = office
    out = tmp_path / "agent-standards.json"
    r = call_tool(session, "attributes.catalogue", {})
    assert r["ok"] and r["result"]["groups"]["line_types"] == 2
    r = call_tool(session, "attributes.export", {"path": str(out)})
    assert r["ok"] and out.is_file()
    new_project("Target")
    r = call_tool(session, "attributes.import", {"path": str(out), "dry_run": True})
    assert r["ok"], r
    assert "Office" not in s.current()["pen_sets"]  # the dry run left no trace
    assert material("Office lime plaster") is None
    r = call_tool(session, "attributes.import", {"path": str(out)})
    assert r["ok"], r
    assert s.current()["line_types"]["Office axis"] == [6.0, 1.5]
    assert material("Office lime plaster") is not None


def test_imported_model_is_valid_ifc(office):
    path, _r = office
    new_project("Target")
    assert attr("import_attributes", str(path))["ok"]
    # a layer holds items: put a wall on the imported layer before validating the express rules
    level = call("storeys")["storeys"][0]["guid"]
    wall = call("create_wall", level, call("wall_types")["types"][0]["guid"], 0, 0, 4, 0, 3.0)["guid"]
    assert call("assign_layer", json.dumps([wall]), "A-OFFICE")["ok"]
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    assert [s for s in logger.statements if s.get("level") == "error"] == []
