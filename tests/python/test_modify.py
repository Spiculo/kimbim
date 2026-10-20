# SPDX-License-Identifier: GPL-3.0-or-later
"""D80: split, trim / extend, corner, join (merge) and unjoin for walls and beams (doc 14 §4)."""
import json

import ifcopenshell.util.element
import ifcopenshell.validate
import pytest

from kimbim import app_bridge as b
from kimbim import authoring, layers, renovation


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


def axis(guid):
    return [[round(float(c), 6) for c in p] for p in authoring._axis_world(b._model.by_guid(guid))]


def valid():
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    return logger.statements


def joins(guid):
    w = b._model.by_guid(guid)
    out = {}
    for rel in authoring._path_joins(w):
        mine = rel.RelatingConnectionType if rel.RelatingElement == w else rel.RelatedConnectionType
        other = rel.RelatedElement if rel.RelatingElement == w else rel.RelatingElement
        out[other.GlobalId] = mine
    return out


def host(door):
    return authoring._opening_info(b._model.by_guid(door))[1].GlobalId


@pytest.fixture
def model():
    """A 10 m wall along x with a door at 2 m and a window at 8 m, a wall joined at each end (L), on
    layer A-WALL, existing."""
    assert call("new_project", "Modify")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    ext = next(t for t in call("wall_types")["types"] if t["name"] == "Exterior 300")["guid"]
    call("create_layer", "A-WALL")
    call("set_active_layer", "A-WALL")
    w = call("create_wall", l1, ext, 0, 0, 10, 0, 3.0, "", "")["guid"]
    left = call("create_wall", l1, ext, 0, 0, 0, 5, 3.0, w, "")["guid"]
    right = call("create_wall", l1, ext, 10, 0, 10, 5, 3.0, w, "")["guid"]
    door = next(t for t in call("opening_types", "door")["types"])
    window = next(t for t in call("opening_types", "window")["types"])
    d = call("insert_opening", "door", w, door["guid"], 2.0, door["width"], door["height"], door["sill"])["guid"]
    win = call("insert_opening", "window", w, window["guid"], 8.0, window["width"], window["height"], window["sill"])["guid"]
    assert call("set_status", g(w), "existing")["ok"]
    return {"l1": l1, "type": ext, "w": w, "left": left, "right": right, "door": d, "window": win}


def test_split_a_wall_keeps_its_doors_joins_and_properties(model):
    r = call("split_element", model["w"], 5.0, 0.1, "1")
    assert r["ok"], r
    piece = r["piece"]
    assert axis(model["w"]) == [[0, 0], [5, 0]]
    assert axis(piece) == [[5, 0], [10, 0]]
    assert host(model["door"]) == model["w"] and host(model["window"]) == piece
    assert abs(authoring._opening_info(b._model.by_guid(model["window"]))[2] - 3.0) < 1e-6  # 8 m from 0 = 3 m from 5
    assert joins(model["w"]) == {model["left"]: "ATSTART", piece: "ATEND"}
    assert joins(piece) == {model["right"]: "ATEND", model["w"]: "ATSTART"}
    p = b._model.by_guid(piece)
    assert ifcopenshell.util.element.get_type(p).GlobalId == model["type"]
    assert layers.element_layer(p).Name == "A-WALL"
    assert renovation.status_of(p) == renovation.status_of(b._model.by_guid(model["w"])) == "existing"
    assert piece in r["geometry"]["changed"] and model["window"] in r["geometry"]["changed"]
    assert valid() == []
    assert call("undo")["ok"]
    assert axis(model["w"]) == [[0, 0], [10, 0]] and host(model["window"]) == model["w"]


def test_split_through_a_door_is_refused_and_ctrl_leaves_the_pieces_apart(model):
    r = call("split_element", model["w"], 2.1, 0, "1")
    assert not r["ok"] and "inside" in r["error"]
    r = call("split_element", model["w"], 5.0, 0, "0")
    assert r["ok"]
    assert model["w"] not in joins(r["piece"])


def test_split_a_beam(model):
    beam_type = call("beam_types")["types"][0]["guid"]
    beam = call("create_beam", model["l1"], beam_type, 0, 3, 6, 3, 3.0)["guid"]
    r = call("split_element", beam, 2.0, 3.0, "1")
    assert r["ok"], r
    from kimbim import modify
    a = modify._beam_axis(b._model.by_guid(beam))
    c = modify._beam_axis(b._model.by_guid(r["piece"]))
    z = round(a[0][2], 6)  # the extrusion axis (mid-depth, below the top at 3 m)
    assert [round(v, 6) for v in a[1]] == [2.0, 3.0, z]
    assert [round(v, 6) for v in c[0]] == [2.0, 3.0, z] and [round(v, 6) for v in c[1]] == [6.0, 3.0, z]
    assert valid() == []


def test_trim_and_extend_to_a_wall(model):
    # A free wall crossing the 10 m wall: trimmed to it, keeping the clicked (north) side, joined in a T.
    cross = call("create_wall", model["l1"], model["type"], 5, -2, 5, 4, 3.0, "", "")["guid"]
    r = call("trim_extend", cross, 5, 3, model["w"], 0, 0, 0, 0, "1")
    assert r["ok"], r
    assert axis(cross) == [[5, 0], [5, 4]]
    assert joins(cross) == {model["w"]: "ATSTART"} and joins(model["w"])[cross] == "ATPATH"
    # A short wall that stops before the right wall is extended to it.
    short = call("create_wall", model["l1"], model["type"], 6, 3, 8, 3, 3.0, "", "")["guid"]
    r = call("trim_extend", short, 7, 3, model["right"], 0, 0, 0, 0, "1")
    assert r["ok"], r
    assert axis(short) == [[6, 3], [10, 3]]
    assert joins(short) == {model["right"]: "ATEND"}
    assert valid() == []
    # To a line (a grid line), without joining.
    r = call("trim_extend", short, 9, 3, "", 7, -5, 7, 5, "1")
    assert r["ok"] and axis(short) == [[7, 3], [10, 3]]
    assert joins(short) == {model["right"]: "ATEND"}


def test_trimming_off_a_door_is_refused(model):
    r = call("trim_extend", model["w"], 9, 0, "", 4, -5, 4, 5, "1")  # keep the east side: the door at 2 m would go
    assert not r["ok"] and "cut off" in r["error"]


def test_trimming_off_a_door_can_delete_it(model):
    # D92: the option deletes the door the trim would leave outside the wall.
    r = call("trim_extend", model["w"], 9, 0, "", 4, -5, 4, 5, "1", "delete")
    assert r["ok"], r
    assert model["door"] in r["geometry"]["removed"]
    with pytest.raises(RuntimeError):
        b._model.by_guid(model["door"])
    assert axis(model["w"]) == [[4, 0], [10, 0]]


def test_trimming_off_a_door_can_keep_it(model):
    # D92: the option keeps the door where it is and trims the wall anyway.
    r = call("trim_extend", model["w"], 9, 0, "", 4, -5, 4, 5, "1", "keep")
    assert r["ok"], r
    assert axis(model["w"]) == [[4, 0], [10, 0]]
    assert host(model["door"]) == model["w"]


def test_corner_meets_two_walls_in_an_l(model):
    a = call("create_wall", model["l1"], model["type"], 20, 0, 24, 0, 3.0, "", "")["guid"]
    c = call("create_wall", model["l1"], model["type"], 26, 1, 26, 6, 3.0, "", "")["guid"]
    r = call("trim_corner", a, 21, 0, c, 26, 5, "1")
    assert r["ok"], r
    assert axis(a) == [[20, 0], [26, 0]] and axis(c) == [[26, 0], [26, 6]]
    assert joins(a) == {c: "ATEND"} and joins(c) == {a: "ATSTART"}
    assert valid() == []
    assert call("undo")["ok"] and axis(a) == [[20, 0], [24, 0]]


def test_merge_collinear_walls_and_join_walls_that_meet(model):
    r = call("split_element", model["w"], 5.0, 0, "1")
    piece = r["piece"]
    walls = len(b._model.by_type("IfcWall"))
    r = call("join_elements", model["w"], piece)
    assert r["ok"] and r["merged"], r
    assert len(b._model.by_type("IfcWall")) == walls - 1 and piece in r["geometry"]["removed"]
    assert axis(model["w"]) == [[0, 0], [10, 0]]
    assert host(model["window"]) == model["w"]
    assert joins(model["w"]) == {model["left"]: "ATSTART", model["right"]: "ATEND"}
    assert valid() == []
    # Two walls that touch get an L join; unjoin breaks it.
    free = call("create_wall", model["l1"], model["type"], 0, 5, 4, 5, 3.0, "", "")["guid"]
    r = call("join_elements", free, model["left"])
    assert r["ok"] and not r["merged"], r
    assert joins(free) == {model["left"]: "ATSTART"} and joins(model["left"])[free] == "ATEND"
    assert not call("join_elements", free, model["left"])["ok"]  # already joined
    r = call("unjoin_elements", g(free, model["left"]))
    assert r["ok"] and model["left"] not in joins(free)
    assert model["w"] in joins(model["left"])  # other joins stay
    assert not call("unjoin_elements", g(free, model["left"]))["ok"]
    assert valid() == []


def test_merge_refuses_different_types(model):
    other = next(t for t in call("wall_types")["types"] if t["name"] != "Exterior 300")["guid"]
    a = call("create_wall", model["l1"], other, 10, -3, 14, -3, 3.0, "", "")["guid"]
    c = call("create_wall", model["l1"], model["type"], 14, -3, 18, -3, 3.0, "", "")["guid"]
    r = call("join_elements", a, c)
    assert not r["ok"] and "type" in r["error"]


def test_merge_keeps_the_first_properties_or_refuses_when_they_differ(model):
    """D92: Merge keeps the first wall's properties (default); with "refuse" it stops if they differ."""
    a = call("create_wall", model["l1"], model["type"], 20, 0, 24, 0, 3.0, "", "")["guid"]
    c = call("create_wall", model["l1"], model["type"], 24, 0, 28, 0, 3.0, "", "")["guid"]
    assert call("set_name", g(c), "Fire wall")["ok"]
    before = b._model.by_guid(a).Name
    r = call("join_elements", a, c, "refuse")
    assert not r["ok"] and "properties" in r["error"], r
    r = call("join_elements", a, c)  # default: keeps the first's properties
    assert r["ok"] and r["merged"], r
    assert b._model.by_guid(a).Name == before
    assert valid() == []


def test_modify_targets_lists_beams(model):
    beam_type = call("beam_types")["types"][0]["guid"]
    beam = call("create_beam", model["l1"], beam_type, 0, 3, 6, 3, 3.0)["guid"]
    beams = call("modify_targets", model["l1"])["beams"]
    assert [x["guid"] for x in beams] == [beam] and beams[0]["x2"] == 6.0


def test_split_moves_a_t_join_to_the_piece_it_meets(model):
    t = call("create_wall", model["l1"], model["type"], 7, 0, 7, 4, 3.0, model["w"], "")["guid"]
    assert joins(model["w"])[t] == "ATPATH"
    r = call("split_element", model["w"], 5.0, 0, "1")
    assert r["ok"], r
    assert t in joins(r["piece"]) and t not in joins(model["w"])
    assert valid() == []


def test_an_imported_wall_gets_kimbim_shape_when_split(model):
    """A wall whose body sits on the plain Model context (as Revit exports it) is rebuilt from its axis,
    layers and height, then split (D80)."""
    import ifcopenshell.util.representation as R
    wall = b._model.by_guid(model["left"])
    body = R.get_representation(wall, "Model", "Body", "MODEL_VIEW")
    body.ContextOfItems = R.get_context(b._model, "Model")
    assert R.get_representation(wall, "Model", "Body", "MODEL_VIEW") is None
    r = call("split_element", model["left"], 0, 2.0, "1")
    assert r["ok"], r
    for guid in (model["left"], r["piece"]):
        e = b._model.by_guid(guid)
        assert R.get_representation(e, "Model", "Body", "MODEL_VIEW") is not None
        assert len([x for x in e.Representation.Representations if x.RepresentationIdentifier == "Body"]) == 1
        assert abs(authoring._wall_height(e) - 3.0) < 1e-6
    assert axis(r["piece"]) == [[0, 2], [0, 5]]
    assert valid() == []


def test_imported_wall_keeps_its_shape_and_is_cut(model):
    """D92: with imported_walls "keep", a split keeps the imported body and cuts it in place."""
    import ifcopenshell.geom
    import ifcopenshell.util.representation as R
    wall = b._model.by_guid(model["left"])
    R.get_representation(wall, "Model", "Body", "MODEL_VIEW").ContextOfItems = R.get_context(b._model, "Model")
    assert call("set_project_settings", json.dumps({"imported_walls": "keep"}))["ok"]
    r = call("split_element", model["left"], 0, 2.0, "1")
    assert r["ok"], r
    for guid in (model["left"], r["piece"]):
        e = b._model.by_guid(guid)
        assert R.get_representation(e, "Model", "Body", "MODEL_VIEW") is None  # still the imported body
    assert axis(model["left"]) == [[0, 0], [0, 2]]
    assert axis(r["piece"]) == [[0, 2], [0, 5]]
    # the bodies were cut: each piece's mesh spans its own half of the 5 m wall
    settings_obj = ifcopenshell.geom.settings()
    settings_obj.set("use-world-coords", True)
    spans = []
    for guid in (model["left"], r["piece"]):
        verts = b._model.by_guid(guid)
        shape = ifcopenshell.geom.create_shape(settings_obj, verts)
        import numpy as np
        pts = np.asarray(shape.geometry.verts).reshape(-1, 3)
        spans.append((round(float(pts[:, 1].min()), 3), round(float(pts[:, 1].max()), 3)))
    assert spans[0][1] == pytest.approx(2.0, abs=1e-3) and spans[1][0] == pytest.approx(2.0, abs=1e-3)
    assert spans[1][1] > spans[0][0]  # the second piece is the far half
    assert valid() == []
