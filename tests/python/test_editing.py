# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice 17: everyday editing (Archicad's Edit menu) — copy/paste, duplicate, mirror, multiply
(linear and polar arrays), offset. Copies get new GlobalIds and keep their layers and joins."""
import json
import math

import ifcopenshell.util.element
import ifcopenshell.util.representation
import ifcopenshell.validate
import pytest

from kimcad import app_bridge as b
from kimcad import authoring, layers


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


@pytest.fixture
def room():
    """Level 1 with an L of two joined walls (the first has a door) and a slab, all on layer A-WALL."""
    assert call("new_project", "Edit")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    ext = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")["guid"]
    call("create_layer", "A-WALL")
    call("set_active_layer", "A-WALL")
    w1 = call("create_wall", l1, ext, 0, 0, 6, 0, 3.0, "", "")["guid"]
    w2 = call("create_wall", l1, ext, 6, 0, 6, 4, 3.0, w1, "")["guid"]
    door = next(t for t in call("opening_types", "door")["types"])
    d = call("insert_opening", "door", w1, door["guid"], 1.5, door["width"], door["height"], door["sill"])["guid"]
    floor = call("slab_types")["types"][0]["guid"]
    slab = call("create_slab", l1, floor, json.dumps([[0, 0], [6, 0], [6, 4], [2, 4]]), 0.0)["guid"]
    return {"l1": l1, "w1": w1, "w2": w2, "door": d, "slab": slab}


def axis(guid):
    return [[round(float(c), 6) for c in p] for p in authoring._axis_world(b._model.by_guid(guid))]


def valid():
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    return logger.statements


def layer_of(guid):
    layer = layers.element_layer(b._model.by_guid(guid))
    return layer.Name if layer is not None else None


def test_copy_with_an_offset_keeps_layers_and_joins(room):
    before = len(b._model.by_type("IfcWall"))
    r = call("copy_elements", g(room["w1"], room["w2"]), 0, 10, 0, "")
    assert r["ok"], r
    copies = r["guids"]
    assert len(copies) == 2 and not set(copies) & {room["w1"], room["w2"]}
    assert len(b._model.by_type("IfcWall")) == before + 2
    assert axis(copies[0]) == [[x, y + 10] for x, y in axis(room["w1"])]
    assert len(b._model.by_type("IfcDoor")) == 2  # the door came with its wall
    new = [b._model.by_guid(c) for c in copies]
    joins = list(new[0].ConnectedTo or ()) + list(new[0].ConnectedFrom or ())
    assert any(rel.RelatedElement in new and rel.RelatingElement in new for rel in joins)  # the corner join was copied
    assert layer_of(copies[0]) == "A-WALL"
    assert valid() == []
    assert call("undo")["ok"] and len(b._model.by_type("IfcWall")) == before


def test_paste_onto_another_level_and_duplicate(room):
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    r = call("copy_elements", g(room["slab"]), 0, 0, 0, l2)
    assert r["ok"] and len(r["guids"]) == 1
    from ifcopenshell.util.element import get_container
    assert get_container(b._model.by_guid(r["guids"][0])).GlobalId == l2
    d = call("duplicate_elements", g(room["w2"]))
    # An offset copy; a lone copy of a joined wall keeps the length its body had (into the corner).
    assert d["ok"] and axis(d["guids"][0])[1] == [axis(room["w2"])[1][0] + 1, axis(room["w2"])[1][1] + 1]


def test_mirror_in_place_keeps_guids_and_flips_the_door(room):
    door = b._model.by_guid(room["door"])
    hand = door.OperationType or ifcopenshell.util.element.get_type(door).OperationType
    r = call("mirror_elements", g(room["w1"]), 0, 2, 10, 2, False)  # across y = 2
    assert r["ok"], r
    assert axis(room["w1"]) == [[6.0, 4.0], [0.0, 4.0]]  # reversed, so its layers mirror too
    info = authoring._opening_info(b._model.by_guid(room["door"]))
    assert abs(info[2] - (6.0 - 1.5)) < 1e-6  # 1.5 m from the start, now from the other end
    flipped = b._model.by_guid(room["door"]).OperationType
    assert flipped and flipped != hand and ("LEFT" in flipped) != ("LEFT" in (hand or "LEFT"))
    assert valid() == []


def test_mirror_a_copy_reflects_slab_outlines(room):
    r = call("mirror_elements", g(room["slab"]), 10, 0, 10, 1, True)  # across x = 10, as a copy
    assert r["ok"] and len(r["guids"]) == 1
    outline = sorted(tuple(round(c, 6) for c in p) for p in call("slab_outline", r["guids"][0])["points"])
    assert outline == sorted([(20.0, 0.0), (14.0, 0.0), (14.0, 4.0), (18.0, 4.0)])
    assert room["slab"] in [s.GlobalId for s in b._model.by_type("IfcSlab")]  # the original stays


def test_multiply_linear_and_polar(room):
    col = call("column_types")["types"][0]["guid"]
    c = call("create_column", room["l1"], col, 10, 0, 3.0, 0.0)["guid"]
    r = call("array_elements", g(c), "linear", json.dumps({"dx": 2, "dy": 0, "count": 3}))
    assert r["ok"] and len(r["guids"]) == 3
    xs = sorted(round(authoring._world(b._model.by_guid(x))[0], 6) for x in r["guids"])
    assert xs == [12.0, 14.0, 16.0]
    p = call("array_elements", g(c), "polar", json.dumps({"cx": 10, "cy": -5, "angle": math.pi / 2, "count": 3}))
    assert p["ok"] and len(p["guids"]) == 3
    pts = sorted((round(authoring._world(b._model.by_guid(x))[0], 6), round(authoring._world(b._model.by_guid(x))[1], 6))
                 for x in p["guids"])
    assert pts == sorted([(15.0, -5.0), (10.0, -10.0), (5.0, -5.0)])
    assert not call("array_elements", g(c), "linear", json.dumps({"dx": 1, "dy": 0, "count": 0}))["ok"]


def test_offset_copies_a_wall_parallel_and_grows_a_slab(room):
    r = call("offset_elements", g(room["w1"]), 1.0)
    assert r["ok"], r
    assert axis(r["guids"][0])[0] == [axis(room["w1"])[0][0], axis(room["w1"])[0][1] + 1]  # parallel, 1 m to the left
    s = call("offset_elements", g(room["slab"]), 0.5)
    assert s["ok"] and s["guids"] == []  # slabs grow in place (same GlobalId)
    outline = call("slab_outline", room["slab"])["points"]
    xs = [p[0] for p in outline]
    assert abs(max(xs) - 6.5) < 1e-6 and abs(min(p[1] for p in outline) + 0.5) < 1e-6
    assert valid() == []


def test_moving_walls_of_an_imported_model_keeps_their_geometry(room):
    """Revit's IFC2X3 exports put wall bodies on the Model context itself (no Body/MODEL_VIEW
    sub-context). Moving such walls moves them; their geometry is theirs, not rebuilt as KIMCAD walls."""
    f = b._model
    body = ifcopenshell.util.representation.get_context(f, "Model", "Body", "MODEL_VIEW")
    model = body.ParentContext
    for rep in f.by_type("IfcShapeRepresentation"):
        if rep.ContextOfItems == body:
            rep.ContextOfItems = model
    f.remove(body)
    w1 = b._model.by_guid(room["w1"])
    items = [r.Items for r in w1.Representation.Representations if r.RepresentationIdentifier == "Body"]
    r = call("move_elements", g(room["w1"]), 0, 1, 0)
    assert r["ok"], r
    assert axis(room["w1"])[0][1] == 1.0
    assert [r.Items for r in w1.Representation.Representations if r.RepresentationIdentifier == "Body"] == items
