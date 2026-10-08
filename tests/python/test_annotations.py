# SPDX-License-Identifier: GPL-3.0-or-later
"""Owner feedback, Slice 13: architects put labels, dimensions and marks on the plan."""
import json

import ifcopenshell.validate
import pytest

from kimcad import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


@pytest.fixture
def plan():
    assert call("new_project", "Notas")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    return {"l1": l1, "l2": l2}


def listed(storey):
    return {a["guid"]: a for a in call("annotations", storey)["annotations"]}


def test_text_dimension_and_mark_are_ifc_annotations_on_the_level(plan):
    t = call("add_annotation", plan["l1"], "text", json.dumps([[1, 2]]), "Living room")
    d = call("add_annotation", plan["l1"], "dimension", json.dumps([[0, 0], [4.5, 0], [0, -1]]), "")
    m = call("add_annotation", plan["l1"], "mark", json.dumps([[3, 3]]), "A")
    assert t["ok"] and d["ok"] and m["ok"], (t, d, m)
    shown = listed(plan["l1"])
    assert shown[t["guid"]] == {"guid": t["guid"], "kind": "text", "text": "Living room", "points": [[1.0, 2.0]], "size": 2.5, "pen": 23}
    assert shown[d["guid"]]["text"] == "4.50"  # dimensions measure themselves
    assert shown[d["guid"]]["points"] == [[0.0, 0.0], [4.5, 0.0], [0.0, -1.0]]
    assert shown[m["guid"]]["kind"] == "mark"
    assert listed(plan["l2"]) == {}
    for a in b._model.by_type("IfcAnnotation"):
        if a.ObjectType == "DRAWING":
            continue  # the new project's template elevations (D61)
        rep = a.Representation.Representations[0]
        assert rep.ContextOfItems.ContextType == "Plan" and rep.RepresentationIdentifier == "Annotation"
    meshed = b.mesh_elements(g(t["guid"]))
    assert meshed is None or len(meshed[1]) == 0  # nothing to mesh in 3D
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    assert logger.statements == []


def test_annotations_move_edit_delete_and_layer(plan):
    d = call("add_annotation", plan["l1"], "dimension", json.dumps([[0, 0], [3, 0], [0, -1]]), "")["guid"]
    t = call("add_annotation", plan["l1"], "text", json.dumps([[1, 1]]), "Hall")["guid"]
    assert call("move_elements", g(d, t), 2, 1, 0)["ok"]
    shown = listed(plan["l1"])
    assert shown[d]["points"][0] == [2.0, 1.0] and shown[d]["text"] == "3.00"
    assert call("set_annotation_text", t, "Entrance hall")["ok"]
    assert listed(plan["l1"])[t]["text"] == "Entrance hall"
    call("create_layer", "A-ANNO")
    assert call("assign_layer", g(t), "A-ANNO")["ok"]
    assert t in call("layer_members")["layers"]["A-ANNO"]
    assert call("delete_elements", g(t))["ok"]
    assert t not in listed(plan["l1"])
    call("undo")
    assert t in listed(plan["l1"])


def test_bad_annotations_are_refused(plan):
    assert not call("add_annotation", plan["l1"], "dimension", json.dumps([[0, 0], [0, 0], [0, 1]]), "")["ok"]
    assert not call("add_annotation", plan["l1"], "text", json.dumps([[0, 0]]), "  ")["ok"]
    assert not call("add_annotation", plan["l1"], "arrow", json.dumps([[0, 0]]), "x")["ok"]


# ---------------------------------------------------------------- Slice 15 (doc 13 open items)

def test_dimension_chain_measures_each_segment(plan):
    d = call("add_annotation", plan["l1"], "dimension", json.dumps([[0, 0], [4, 0], [7.5, 0], [0, -1]]), "")
    assert d["ok"], d
    shown = listed(plan["l1"])[d["guid"]]
    assert shown["text"] == "4.00 3.50" and len(shown["points"]) == 4
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    assert logger.statements == []


def test_leader_points_at_something_with_its_text(plan):
    r = call("add_annotation", plan["l1"], "leader", json.dumps([[1, 1], [2, 2], [3, 2]]), "Concrete")
    assert r["ok"], r
    shown = listed(plan["l1"])[r["guid"]]
    assert shown["kind"] == "leader" and shown["text"] == "Concrete" and len(shown["points"]) == 3
    assert not call("add_annotation", plan["l1"], "leader", json.dumps([[1, 1]]), "x")["ok"]  # needs a line


def test_text_size_is_in_paper_millimetres(plan):
    t = call("add_annotation", plan["l1"], "text", json.dumps([[1, 2]]), "Hall")["guid"]
    assert listed(plan["l1"])[t]["size"] == 2.5  # the default, as on a printed plan
    assert call("set_annotation_size", t, 5.0)["ok"]
    assert listed(plan["l1"])[t]["size"] == 5.0
    literal = next(i for i in b._model.by_guid(t).Representation.Representations[0].Items if i.is_a("IfcTextLiteralWithExtent"))
    assert abs(literal.Extent.SizeInY - 500.0) < 1e-6  # 5 mm at 1:100 = 0.5 m, in millimetres
    assert not call("set_annotation_size", t, 0)["ok"]


def _literals(guid):
    rep = b._model.by_guid(guid).Representation.Representations[0]
    return [i.Literal for i in rep.Items if i.is_a("IfcTextLiteral")]


def test_typed_dimension_text_with_spaces_is_kept_whole(plan):
    """Labels were split on whitespace (one word per segment): "2.50 m" printed as "2.50"."""
    from kimcad import drawgen

    one = call("add_annotation", plan["l1"], "dimension", json.dumps([[0, 0], [2.5, 0], [0, -1]]), "2.50 m")["guid"]
    assert _literals(one) == ["2.50 m"]
    chain = call("add_annotation", plan["l1"], "dimension", json.dumps([[0, 0], [4, 0], [7.5, 0], [0, -1]]),
                 "a eje A; 3,50")["guid"]
    assert _literals(chain) == ["a eje A", "3,50"]
    assert drawgen.segment_labels("4.00 3.50", 2) == ["4.00", "3.50"]  # measured chains, older files
    assert drawgen.segment_labels("ver nota; detalle 3", 1) == ["ver nota; detalle 3"]
    svg = "".join(drawgen.plan_annotations(b._model.by_guid(plan["l1"]), lambda x, y, z: (x * 10, y * 10)))
    assert ">2.50 m<" in svg and ">a eje A<" in svg


def test_annotations_take_the_current_pen_and_can_change_it(plan):
    """D73: new annotations take the current pen (the bottom bar's); a selected one can take another."""
    from kimcad import settings as s
    assert json.loads(s.set_project_settings(json.dumps({"current_pen": 26})))["ok"]
    guid = call("add_annotation", plan["l1"], "text", json.dumps([[1.0, 1.0]]), "Hello")["guid"]
    assert listed(plan["l1"])[guid]["pen"] == 26
    assert call("set_annotation_pen", guid, "5")["ok"]
    assert listed(plan["l1"])[guid]["pen"] == 5
    assert call("set_annotation_text", guid, "Bye")["ok"]  # other edits keep the pen
    assert listed(plan["l1"])[guid]["pen"] == 5
    assert not call("set_annotation_pen", guid, "300")["ok"]
    assert call("undo")["ok"] and listed(plan["l1"])[guid]["pen"] == 5 and listed(plan["l1"])[guid]["text"] == "Hello"
    s.load(None)
