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
    assert shown[t["guid"]] == {"guid": t["guid"], "kind": "text", "text": "Living room", "points": [[1.0, 2.0]]}
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
