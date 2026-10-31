# SPDX-License-Identifier: GPL-3.0-or-later
"""Keynotes (doc 14 §13): a reusable keynote table in the project settings, and keynote annotations on
plans that show "[code] text" and follow the table when it changes."""
import json

import ifcopenshell.util.element
import ifcopenshell.validate
import pytest

from kimbim import app_bridge as b
from kimbim import keynotes
from kimbim import settings as s


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def j(fn, *args):
    return json.loads(fn(*args))


def g(*guids):
    return json.dumps(list(guids))


@pytest.fixture
def plan():
    """An empty project with one level; the keynote table empty."""
    s.load(None)
    assert call("new_project", "Keynotes")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    yield {"l1": l1}
    s.load(None)


def listed(storey):
    return {a["guid"]: a for a in call("annotations", storey)["annotations"]}


def valid():
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    return logger.statements


def literals(guid):
    rep = b._model.by_guid(guid).Representation.Representations[0]
    return [i.Literal for i in rep.Items if i.is_a("IfcTextLiteral")]


def pset(guid):
    return ifcopenshell.util.element.get_pset(b._model.by_guid(guid), "KIMBIM_Annotation")


# ---------------------------------------------------------------- the table

def test_the_table_is_a_project_setting_with_crud(plan):
    assert j(keynotes.keynote_table) == {"ok": True, "keynotes": []}
    r = j(keynotes.save_keynote, "A-2", "Gypsum board", "Finishes")
    assert r["ok"] and r["keynote"] == {"code": "A-2", "text": "Gypsum board", "category": "Finishes"}
    j(keynotes.save_keynote, "A-1", "Concrete slab", "Structure")
    assert [k["code"] for k in j(keynotes.keynote_table)["keynotes"]] == ["A-1", "A-2"]  # sorted
    assert s.current()["keynotes"]["A-1"] == {"code": "A-1", "text": "Concrete slab", "category": "Structure"}
    # Saving an existing code changes it; the table keeps one entry.
    j(keynotes.save_keynote, "A-1", "Concrete slab 200", "Structure")
    table = j(keynotes.keynote_table)["keynotes"]
    assert len(table) == 2 and table[0]["text"] == "Concrete slab 200"
    assert j(keynotes.delete_keynote, "A-2")["ok"]
    assert [k["code"] for k in j(keynotes.keynote_table)["keynotes"]] == ["A-1"]
    # A code is required, and so is a text.
    assert not j(keynotes.save_keynote, "", "No code")["ok"]
    assert not j(keynotes.save_keynote, "B-1", "   ")["ok"]
    assert not j(keynotes.delete_keynote, "A-2")["ok"]


# ---------------------------------------------------------------- placing

def test_place_read_update_delete_a_keynote(plan):
    j(keynotes.save_keynote, "A-1", "Concrete slab", "Structure")
    r = j(keynotes.place_keynote, plan["l1"], 1.0, 2.0, "A-1")
    assert r["ok"], r
    guid = r["guid"]
    assert guid in listed(plan["l1"])  # annotations() lists it like any plan annotation
    shown = listed(plan["l1"])[guid]
    assert shown["kind"] == "text" and shown["text"] == "[A-1] Concrete slab"
    assert shown["points"] == [[1.0, 2.0]]
    annotation = b._model.by_guid(guid)
    assert annotation.is_a("IfcAnnotation") and annotation.ObjectType == "TEXT"
    assert pset(guid)["Keynote"] == "A-1"  # the code is kept in the property set
    assert literals(guid) == ["[A-1] Concrete slab"]
    assert valid() == []
    # It moves and deletes like any annotation.
    assert call("move_elements", g(guid), 1, 0, 0)["ok"]
    assert listed(plan["l1"])[guid]["points"] == [[2.0, 2.0]]
    assert call("delete_elements", g(guid))["ok"]
    assert guid not in listed(plan["l1"])
    call("undo")
    assert guid in listed(plan["l1"])
    # Its own undo step: placing again and undoing leaves nothing.
    other = j(keynotes.place_keynote, plan["l1"], 4.0, 4.0, "A-1")["guid"]
    call("undo")
    assert other not in listed(plan["l1"])


def test_a_keynote_can_have_a_leader_and_a_size(plan):
    j(keynotes.save_keynote, "A-1", "Concrete slab")
    r = j(keynotes.place_keynote, plan["l1"], 5.0, 5.0, "A-1",
          json.dumps({"leader": [3.0, 4.0], "size": 3.5}))
    assert r["ok"], r
    guid = r["guid"]
    shown = listed(plan["l1"])[guid]
    assert shown["kind"] == "leader" and shown["size"] == 3.5
    # The arrow tip, then the text position (where the annotation is placed).
    assert shown["points"] == [[3.0, 4.0], [5.0, 5.0]]
    assert literals(guid) == ["[A-1] Concrete slab"]
    rep = b._model.by_guid(guid).Representation.Representations[0]
    assert any(i.is_a("IfcPolyline") for i in rep.Items)  # the leader line
    assert r["annotation"]["kind"] == "leader" and r["annotation"]["code"] == "A-1"
    assert pset(guid)["Keynote"] == "A-1"
    # Bad options are refused.
    assert not j(keynotes.place_keynote, plan["l1"], 5.0, 5.0, "A-1",
                 json.dumps({"leader": [5.0, 5.0]}))["ok"]  # no leader at all
    assert not j(keynotes.place_keynote, plan["l1"], 5.0, 5.0, "A-1", json.dumps({"size": 0}))["ok"]
    assert valid() == []


def test_unknown_codes_levels_and_options_are_refused(plan):
    j(keynotes.save_keynote, "A-1", "Concrete slab")
    assert not j(keynotes.place_keynote, plan["l1"], 0, 0, "Z-9")["ok"]  # not in the table
    assert not j(keynotes.place_keynote, plan["l1"], 0, 0, "")["ok"]
    assert not j(keynotes.place_keynote, "nope", 0, 0, "A-1")["ok"]
    assert not j(keynotes.place_keynote, plan["l1"], 0, 0, "A-1", "{not json")["ok"]
    assert not j(keynotes.place_keynote, plan["l1"], "x", 0, "A-1")["ok"]
    assert listed(plan["l1"]) == {}


# ---------------------------------------------------------------- following the table

def test_a_table_edit_rewrites_the_placed_keynotes(plan):
    j(keynotes.save_keynote, "A-1", "Concrete slab")
    j(keynotes.save_keynote, "A-2", "Gypsum board")
    one = j(keynotes.place_keynote, plan["l1"], 1.0, 1.0, "A-1")["guid"]
    two = j(keynotes.place_keynote, plan["l1"], 2.0, 1.0, "A-1")["guid"]
    other = j(keynotes.place_keynote, plan["l1"], 3.0, 1.0, "A-2")["guid"]
    quiet = j(keynotes.update_keynote_annotations)
    assert quiet["ok"] and quiet["updated"] == 0 and quiet["guids"] == []
    j(keynotes.save_keynote, "A-1", "Concrete slab, 200 mm")
    r = j(keynotes.update_keynote_annotations)
    assert r["ok"] and r["updated"] == 2 and set(r["guids"]) == {one, two}
    shown = listed(plan["l1"])
    assert shown[one]["text"] == shown[two]["text"] == "[A-1] Concrete slab, 200 mm"
    assert shown[other]["text"] == "[A-2] Gypsum board"  # another code does not change
    assert literals(one) == ["[A-1] Concrete slab, 200 mm"]
    assert b._model.by_guid(one).Name == "[A-1] Concrete slab, 200 mm"
    assert pset(one)["Keynote"] == "A-1"
    # One undo step; the table (project settings) is not part of it, so a refresh brings it back.
    call("undo")
    assert listed(plan["l1"])[one]["text"] == "[A-1] Concrete slab"
    assert j(keynotes.update_keynote_annotations)["updated"] == 2
    assert listed(plan["l1"])[one]["text"] == "[A-1] Concrete slab, 200 mm"
    # A code gone from the table keeps the text it shows.
    j(keynotes.delete_keynote, "A-2")
    assert j(keynotes.update_keynote_annotations)["updated"] == 0
    assert listed(plan["l1"])[other]["text"] == "[A-2] Gypsum board"
    assert valid() == []


# ---------------------------------------------------------------- the agent tools

def test_the_keynote_agent_tools_are_registered():
    from kimbim.agent import catalogue
    from kimbim.agent.tools import keynotes as tools  # noqa: F401

    names = {"keynotes.list", "keynotes.save", "keynotes.delete", "keynotes.place", "keynotes.refresh"}
    assert names <= set(catalogue.TOOLS)
    assert {n for n in names if catalogue.TOOLS[n].writes} == names - {"keynotes.list"}
