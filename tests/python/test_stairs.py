# SPDX-License-Identifier: GPL-3.0-or-later
"""Stairs with landings, railings and ramps (D88): riser maths and code warnings, L/U/sketch layouts,
the IFC they make (IFC4 and IFC2X3), the opening in the floor above, railings and editing."""
import json

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.shape
import ifcopenshell.validate
import numpy as np
import pytest

from kimcad import app_bridge as b
from kimcad import drawgen
from kimcad import stairs
from kimcad import testing


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


def bbox(guids):
    _, verts, _ = b.mesh_elements(json.dumps(list(guids)))
    v = np.frombuffer(verts, dtype="<f4").reshape(-1, 3)
    return v.min(axis=0), v.max(axis=0)


def volume(guid):
    s = ifcopenshell.geom.settings()
    return ifcopenshell.util.shape.get_volume(ifcopenshell.geom.create_shape(s, b._model.by_guid(guid)).geometry)


def parts(guid):
    return stairs.parts(b._model.by_guid(guid))


def errors():
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(b._model, logger, express_rules=True)
    return [s for s in logger.statements if s["level"] == "error"]


@pytest.fixture
def levels():
    assert call("new_project", "Escaleras")["ok"]
    l1 = call("storeys")["storeys"][0]["guid"]
    l2 = call("add_storey", "Level 2", 3.0)["guid"]
    slab_type = call("slab_types")["types"][0]["guid"]
    return {"l1": l1, "l2": l2, "slab_type": slab_type}


# ---------------------------------------------------------------- maths

def test_risers_come_from_the_height_and_the_target_riser():
    assert stairs.riser_count(3.0, 0.175) == 18  # 17.1 rounded up
    assert stairs.riser_count(2.8, 0.175) == 16  # exactly 16
    assert stairs.riser_count(0.1, 0.175) == 2  # at least two
    with pytest.raises(ValueError):
        stairs.riser_count(0.0, 0.175)
    lay = stairs.stair_layout("straight", 3.0, 1.0, 0.175, 0.28)
    assert lay["risers"] == 18 and lay["riser"] == pytest.approx(3.0 / 18)
    assert lay["flights"][0]["length"] == pytest.approx(17 * 0.28)


def test_code_warnings_riser_tread_and_two_risers_plus_tread():
    assert stairs.stair_warnings(3.0 / 18, 0.28) == []  # 613 mm
    w = stairs.stair_warnings(0.19, 0.24)
    assert len(w) == 2 and "190 mm" in w[0] and "240 mm" in w[1]  # 2R+G = 620 mm is fine
    assert stairs.stair_warnings(0.17, 0.34) == ["2 risers + tread = 680 mm, outside 600-650 mm"]
    assert stairs.ramp_warnings(8.0) == [] and "1:12" in stairs.ramp_warnings(10.0)[0]
    # The limits are a project setting.
    assert call("new_project", "Reglas")["ok"]
    assert stairs.rules()["max_riser"] == pytest.approx(0.18)
    assert call("set_project_settings", json.dumps({"stair_rules": {"max_riser": 0.2, "max_ramp_slope": 10}}))["ok"]
    assert stairs.stair_warnings(0.19, 0.25, stairs.rules()) == []
    assert stairs.ramp_warnings(10.0, stairs.rules()) == []
    assert not call("set_project_settings", json.dumps({"stair_rules": {"nonsense": 1}}))["ok"]
    assert not call("set_project_settings", json.dumps({"stair_rules": {"step_min": 0.7, "step_max": 0.6}}))["ok"]


def test_l_stair_has_two_flights_and_a_quarter_landing():
    lay = stairs.stair_layout("L", 3.0, 1.0, 0.175, 0.28)
    f1, f2 = lay["flights"]
    (landing,) = lay["landings"]
    assert (f1["risers"], f2["risers"]) == (9, 9)
    assert f1["length"] == pytest.approx(8 * 0.28)
    xs = sorted({round(float(p[0]), 6) for p in landing["polygon"]})
    ys = sorted({round(float(p[1]), 6) for p in landing["polygon"]})
    assert xs == pytest.approx([2.24, 3.24]) and ys == pytest.approx([-0.5, 0.5])
    assert landing["z"] == pytest.approx(1.5)
    assert f2["start"] == pytest.approx([2.74, 0.5]) and f2["dir"] == pytest.approx([0.0, 1.0])
    assert f2["z0"] == pytest.approx(1.5) and f2["z1"] == pytest.approx(3.0)
    right = stairs.stair_layout("L", 3.0, 1.0, 0.175, 0.28, turn="right")
    assert right["flights"][1]["dir"] == pytest.approx([0.0, -1.0])
    assert right["flights"][1]["start"] == pytest.approx([2.74, -0.5])


def test_u_stair_comes_back_beside_the_first_flight():
    lay = stairs.stair_layout("U", 3.0, 1.0, 0.175, 0.28, landing=1.2)
    f1, f2 = lay["flights"]
    (landing,) = lay["landings"]
    assert f2["dir"] == pytest.approx([-1.0, 0.0])
    assert f2["start"] == pytest.approx([2.24, 1.0 + stairs.U_GAP])
    xs = [float(p[0]) for p in landing["polygon"]]
    ys = [float(p[1]) for p in landing["polygon"]]
    assert (min(xs), max(xs)) == pytest.approx((2.24, 3.44))  # 1.2 m deep
    assert (min(ys), max(ys)) == pytest.approx((-0.5, 1.5 + stairs.U_GAP))  # both flights wide
    assert f2["start"][0] - f2["length"] == pytest.approx(0.0)  # it ends beside the start
    with pytest.raises(ValueError):
        stairs.stair_layout("U", 0.5, 1.0, 0.175, 0.28)  # 3 risers: too few for two flights


def test_stair_by_sketch_shares_the_risers_out_by_length():
    lay = stairs.stair_layout("sketch", 3.0, 1.0, 0.175, 0.28, points=[[0, 0], [3, 0], [3, 2.5]])
    f1, f2 = lay["flights"]
    assert f1["risers"] + f2["risers"] == 18
    assert f1["length"] == pytest.approx(2.5) and f2["length"] == pytest.approx(2.0)  # half a width off each corner
    assert f2["start"] == pytest.approx([3.0, 0.5])
    (landing,) = lay["landings"]
    xs = sorted({round(float(p[0]), 6) for p in landing["polygon"]})
    ys = sorted({round(float(p[1]), 6) for p in landing["polygon"]})
    assert xs == pytest.approx([2.5, 3.5]) and ys == pytest.approx([-0.5, 0.5])  # a square at the corner
    with pytest.raises(ValueError):
        stairs.stair_layout("sketch", 3.0, 1.0, 0.175, 0.28, points=[[0, 0], [3, 0], [0, 0.1]])  # turns back
    with pytest.raises(ValueError):
        stairs.stair_layout("sketch", 3.0, 1.0, 0.175, 0.28, points=[[0, 0], [0.4, 0], [0.4, 3]])  # too short


def test_railing_parts_posts_at_most_1_2_m_apart():
    bits = stairs.railing_parts([[0, 0, 0], [4, 0, 0], [4, 2, 0]], 1.1)
    assert len(bits["posts"]) == 4 + 3  # 4 m: 4 spans; 2 m: 2 spans and the end post
    assert len(bits["rails"]) == 2
    assert all(abs(p[2] - 0) < 1e-9 for p in bits["balusters"])
    assert 40 < len(bits["balusters"]) < 50


# ---------------------------------------------------------------- IFC

def test_l_stair_is_a_stair_with_flights_and_a_landing(levels):
    r = call("create_stair", levels["l1"], 1.0, 1.0, 0.0, 1.0, 3.0, json.dumps({"shape": "L"}))
    assert r["ok"], r
    assert (r["risers"], r["flights"], r["landings"], r["warnings"]) == (18, 2, 1, [])
    stair = b._model.by_guid(r["guid"])
    assert stair.PredefinedType == "QUARTER_TURN_STAIR"
    ps = parts(r["guid"])
    flights = [p for p in ps if p.is_a("IfcStairFlight")]
    landings = [p for p in ps if p.is_a("IfcSlab")]
    assert len(flights) == 2 and len(landings) == 1 and landings[0].PredefinedType == "LANDING"
    common = ifcopenshell.util.element.get_pset(stair, "Pset_StairCommon")
    assert common["NumberOfRiser"] == 18 and common["NumberOfTreads"] == 16
    assert common["RiserHeight"] == pytest.approx(3000 / 18) and common["TreadLength"] == pytest.approx(280)
    for f in flights:
        fc = ifcopenshell.util.element.get_pset(f, "Pset_StairFlightCommon")
        assert fc["NumberOfRiser"] == 9 and fc["NumberOfTreads"] == 8
        assert f.NumberOfRisers == 9 and f.RiserHeight == pytest.approx(3000 / 18)
    assert set(r["geometry"]["changed"]) >= {p.GlobalId for p in ps}
    lo, hi = bbox(p.GlobalId for p in ps)
    assert lo[2] == pytest.approx(-0.2, abs=2e-3) or lo[2] == pytest.approx(0.0, abs=2e-3)
    assert hi[2] == pytest.approx(3.0, abs=2e-3)
    assert lo[0] == pytest.approx(1.0, abs=2e-3) and hi[0] == pytest.approx(1.0 + 2.24 + 1.0, abs=2e-3)
    assert hi[1] == pytest.approx(1.0 + 0.5 + 8 * 0.28 + 0.0, abs=0.3)
    land_lo, land_hi = bbox([landings[0].GlobalId])
    assert land_hi[2] == pytest.approx(1.5, abs=2e-3) and land_lo[0] == pytest.approx(3.24, abs=2e-3)
    assert errors() == []


def test_every_shape_and_a_ramp_validate(levels):
    for shape, extra in (("straight", {}), ("U", {"turn": "right"}), ("sketch", {"points": [[0, 8], [3, 8], [3, 11]]})):
        assert call("create_stair", levels["l1"], 0, 0, 0, 1.0, 3.0, json.dumps({"shape": shape, **extra}))["ok"]
    assert call("create_ramp", levels["l1"], 10, 0, 0, 1.2, 0.5, json.dumps({"shape": "L"}))["ok"]
    sketch = [s for s in b._model.by_type("IfcStair") if s.PredefinedType == "USERDEFINED"]
    assert sketch and sketch[0].ObjectType == "BY_SKETCH"
    assert errors() == []


def test_the_floor_above_gets_an_opening_and_loses_it_with_the_stair(levels):
    upper = call("create_slab", levels["l2"], levels["slab_type"], json.dumps([[0, 0], [8, 0], [8, 6], [0, 6]]), 0.0)["guid"]
    before = volume(upper)
    r = call("create_stair", levels["l1"], 1.0, 1.0, 0.0, 1.0, 3.0)
    assert r["ok"]
    assert upper in r["geometry"]["changed"]
    openings = b._model.by_type("IfcOpeningElement")
    assert len(openings) == 1 and openings[0].VoidsElements[0].RelatingBuildingElement.GlobalId == upper
    assert volume(upper) == pytest.approx(before - 17 * 0.28 * 1.0 * 0.2, abs=2e-3)
    # Moving the stair moves the hole.
    assert call("move_elements", g(r["guid"]), 1.0, 0.0)["ok"]
    assert len(b._model.by_type("IfcOpeningElement")) == 1
    assert volume(upper) == pytest.approx(before - 17 * 0.28 * 0.2, abs=2e-3)
    d = call("delete_elements", g(r["guid"]))
    assert d["ok"] and upper in d["geometry"]["changed"]
    assert not b._model.by_type("IfcOpeningElement") and not b._model.by_type("IfcStairFlight")
    assert volume(upper) == pytest.approx(before, abs=1e-3)
    call("undo")
    assert len(b._model.by_type("IfcOpeningElement")) == 1 and len(b._model.by_type("IfcStairFlight")) == 1
    # Without cut_slab, no hole.
    call("undo")
    assert call("create_stair", levels["l1"], 1.0, 1.0, 0.0, 1.0, 3.0, json.dumps({"cut_slab": False}))["ok"]
    assert not b._model.by_type("IfcOpeningElement")


def test_u_stair_opening_is_one_outline_with_the_well_closed(levels):
    upper = call("create_slab", levels["l2"], levels["slab_type"], json.dumps([[0, 0], [8, 0], [8, 6], [0, 6]]), 0.0)["guid"]
    before = volume(upper)
    assert call("create_stair", levels["l1"], 1.0, 1.0, 0.0, 1.0, 3.0, json.dumps({"shape": "U"}))["ok"]
    assert len(b._model.by_type("IfcOpeningElement")) == 1
    width = 2 * 1.0 + stairs.U_GAP
    assert volume(upper) == pytest.approx(before - (8 * 0.28 + 1.0) * width * 0.2, abs=5e-3)


def test_railings_on_a_stair_follow_it(levels):
    r = call("create_stair", levels["l1"], 1.0, 1.0, 0.0, 1.0, 3.0)
    rl = call("add_stair_railings", r["guid"])
    assert rl["ok"], rl
    assert rl["posts"] == [5, 5]  # 4.76 m: four spans of at most 1.2 m
    railings = [b._model.by_guid(x) for x in rl["guids"]]
    assert all(x.is_a("IfcRailing") for x in railings)
    assert ifcopenshell.util.element.get_pset(railings[0], "Pset_RailingCommon")["Height"] == pytest.approx(900)
    lo, hi = bbox(rl["guids"][:1])
    assert hi[2] == pytest.approx(3.0 + 0.9, abs=0.02)  # its top 0.9 m above the top nosing
    assert lo[1] == pytest.approx(1.5 - stairs.INSET - stairs.POST / 2, abs=0.01)  # the left side
    assert not call("add_stair_railings", r["guid"])["ok"]  # it has them already
    # Moving the stair takes its railings along (same undo step).
    m = call("move_elements", g(r["guid"]), 2.0, 0.0)
    assert set(rl["guids"]) <= set(m["geometry"]["changed"])
    lo2, _ = bbox(rl["guids"][:1])
    assert lo2[0] == pytest.approx(lo[0] + 2.0, abs=1e-3)
    # A wider stair moves them out.
    assert call("set_dimension", g(r["guid"]), "Width", 1.4)["ok"]
    lo3, _ = bbox(rl["guids"][:1])
    assert lo3[1] == pytest.approx(lo[1] + 0.2, abs=0.01)
    # Their height is a dimension too.
    assert call("set_dimension", g(rl["guids"][0]), "Height", 1.1)["ok"]
    _, hi4 = bbox(rl["guids"][:1])
    assert hi4[2] == pytest.approx(3.0 + 1.1, abs=0.02)
    # Deleting the stair deletes its railings.
    assert call("delete_elements", g(r["guid"]))["ok"]
    assert not b._model.by_type("IfcRailing")
    assert errors() == []


def test_railing_by_path_and_on_an_l_stair(levels):
    r = call("create_railing", levels["l1"], json.dumps([[0, 0], [4, 0], [4, 2]]))
    assert r["ok"] and r["posts"] == 7
    lo, hi = bbox([r["guid"]])
    assert hi[2] == pytest.approx(1.1, abs=0.01)
    assert not call("create_railing", levels["l1"], json.dumps([[0, 0]]))["ok"]
    stair = call("create_stair", levels["l1"], 0, 3, 0, 1.0, 3.0, json.dumps({"shape": "L"}))["guid"]
    rl = call("add_stair_railings", stair, "1.0", "right")
    assert rl["ok"] and len(rl["guids"]) == 1
    path = json.loads(ifcopenshell.util.element.get_pset(b._model.by_guid(rl["guids"][0]), "KIMCAD_Railing")["Path"])
    assert len(path) == 5  # flight, round the outside of the landing (one corner), flight
    assert errors() == []


def test_ramps_straight_and_l_with_a_slope_warning(levels):
    r = call("create_ramp", levels["l1"], 0, 0, 0, 1.2, 0.5, json.dumps({"slope": 8}))
    assert r["ok"] and r["run"] == pytest.approx(6.25) and r["warnings"] == []
    ramp = b._model.by_guid(r["guid"])
    assert ramp.is_a("IfcRamp") and ramp.PredefinedType == "STRAIGHT_RUN_RAMP"
    (flight,) = parts(r["guid"])
    assert flight.is_a("IfcRampFlight")
    lo, hi = bbox([flight.GlobalId])
    assert hi[0] == pytest.approx(6.25, abs=2e-3) and hi[2] == pytest.approx(0.5, abs=2e-3) and lo[2] == pytest.approx(0, abs=2e-3)
    steep = call("create_ramp", levels["l1"], 0, 5, 0, 1.2, 0.5, json.dumps({"slope": 10, "shape": "L"}))
    assert steep["ok"] and len(steep["warnings"]) == 1
    ps = parts(steep["guid"])
    assert sorted(p.is_a() for p in ps) == ["IfcRampFlight", "IfcRampFlight", "IfcSlab"]
    assert b._model.by_guid(steep["guid"]).PredefinedType == "QUARTER_TURN_RAMP"
    assert call("add_stair_railings", steep["guid"], "", "left")["ok"]
    assert call("set_dimension", g(steep["guid"]), "Slope %", 6.0)["ok"]
    assert call("stair_info", steep["guid"])["warnings"] == []
    assert errors() == []


def test_copy_and_mirror_an_l_stair(levels):
    r = call("create_stair", levels["l1"], 1.0, 1.0, 0.0, 1.0, 3.0, json.dumps({"shape": "L"}))
    rails = call("add_stair_railings", r["guid"])["guids"]
    c = call("copy_elements", g(r["guid"], *(p.GlobalId for p in parts(r["guid"])), *rails), 10.0, 0.0)
    assert c["ok"] and len(c["guids"]) == 3  # the stair (its parts come with it) and its two railings
    copy = b._model.by_guid(c["guids"][0])
    assert len(stairs.parts(copy)) == 3
    assert {ifcopenshell.util.element.get_pset(b._model.by_guid(x), "KIMCAD_Railing")["Host"] for x in c["guids"][1:]} == {copy.GlobalId}
    lo, _ = bbox(p.GlobalId for p in stairs.parts(copy))
    assert lo[0] == pytest.approx(11.0, abs=2e-3)
    assert call("mirror_elements", g(r["guid"]), 0, 0, 1, 0)["ok"]
    assert call("stair_info", r["guid"])["params"]["Turn"] == "right"
    _, hi = bbox(p.GlobalId for p in parts(r["guid"]))
    assert hi[1] == pytest.approx(-0.5, abs=2e-3)  # it now climbs on the other side of the mirror line
    assert errors() == []


def test_properties_show_the_stair_for_its_parts(levels):
    r = call("create_stair", levels["l1"], 1.0, 1.0, 0.0, 1.0, 3.0, json.dumps({"shape": "U"}))
    everything = [r["guid"], *(p.GlobalId for p in parts(r["guid"]))]
    props = call("properties_multi", g(*everything))
    assert props["count"] == 1 and props["types"] == ["IfcStair"]
    dims = props["psets"]["Dimensions"]
    assert dims["Width"]["value"] == pytest.approx(1.0) and dims["Width"]["editable"]
    assert dims["Tread"]["value"] == pytest.approx(0.28)
    assert call("set_dimension", g(*everything), "Tread", 0.3)["ok"]
    assert call("stair_info", r["guid"])["tread"] == pytest.approx(0.3)
    assert not call("set_dimension", g(r["guid"]), "Width", -1)["ok"]
    members = call("assembly_members")["assemblies"]
    assert set(members[r["guid"]]["parts"]) == set(everything[1:])
    assert call("stair_at", levels["l1"], 2.0, 1.0)["guid"] == r["guid"]
    assert call("stair_at", levels["l1"], 20.0, 1.0)["guid"] == ""


# ---------------------------------------------------------------- plan symbol

def test_plan_symbol_breaks_at_the_cut_and_dashes_what_is_above():
    lay = stairs.stair_layout("straight", 3.0, 1.0, 0.175, 0.28)
    plan = stairs.plan_lines(lay)
    solid, dashed, labels = drawgen.stair_symbol(plan, 1.1)
    above = [x for x in plan["lines"] if x[4] > 1.1]
    walk_and_arrow = 2
    assert len(dashed) == len(above) + walk_and_arrow
    assert [t for *_, t, _ in labels] == ["UP"]
    zigzag = [line for line in solid if len(line) == 6]
    assert len(zigzag) == 1  # the break line
    bx = sum(p[0] for p in zigzag[0]) / 6
    assert bx == pytest.approx((1.1 - 3.0 / 18) / (3.0 / 18) * (17 * 0.28) / 17, abs=0.05)
    up_solid, up_dashed, up_labels = drawgen.stair_symbol(plan, 1.1, upper=True)
    assert up_dashed == [] and [t for *_, t, _ in up_labels] == ["DN"]
    # A stair wholly below the cut has no break line and no dashes.
    low = stairs.plan_lines(stairs.stair_layout("straight", 0.6, 1.0, 0.175, 0.28))
    s2, d2, _ = drawgen.stair_symbol(low, 1.1)
    assert d2 == [] and not [line for line in s2 if len(line) == 6]


def test_plan_view_symbols_and_the_floor_plan_drawing(levels):
    r = call("create_stair", levels["l1"], 1.0, 1.0, 0.0, 1.0, 3.0, json.dumps({"shape": "L"}))
    symbols = call("stair_symbols", levels["l1"], "1.2")["symbols"]
    assert len(symbols) == 1 and symbols[0]["guid"] == r["guid"] and symbols[0]["dashed"]
    assert symbols[0]["labels"][0]["text"] == "UP"
    assert symbols[0]["labels"][0]["at"][0] == pytest.approx(1.0 - 0.35, abs=1e-6)
    assert call("stair_symbols", levels["l2"])["symbols"] == []
    drawings = {d["name"]: d["guid"] for d in call("drawings")["drawings"]}
    plan = call("generate_drawing", drawings["Level 1 Floor Plan"], "")
    assert plan["ok"], plan
    assert f'data-guid="{r["guid"]}"' in plan["svg"] and ">UP<" in plan["svg"] and "stroke-dasharray" in plan["svg"]
    flight = parts(r["guid"])[0].GlobalId
    assert flight in plan["svg"]  # the flights are drawn on the stair's level
    call("create_plan", levels["l2"])
    drawings = {d["name"]: d["guid"] for d in call("drawings")["drawings"]}
    upper = call("generate_drawing", drawings["Level 2 Floor Plan"], "")["svg"]
    assert ">DN<" in upper


# ---------------------------------------------------------------- IFC2X3

def test_stairs_ramps_and_railings_in_an_ifc2x3_model():
    f = testing.build_model("IFC2X3", walls=0)
    try:
        storey = f.by_type("IfcBuildingStorey")[0]
        b._model = f
        b._reset_history("")
        r = call("create_stair", storey.GlobalId, 0, 0, 0, 1.0, 3.0, json.dumps({"shape": "L"}))
        assert r["ok"], r
        stair = f.by_guid(r["guid"])
        assert stair.ShapeType == "QUARTER_TURN_STAIR"
        flights = [p for p in parts(r["guid"]) if p.is_a("IfcStairFlight")]
        assert [x.NumberOfRiser for x in flights] == [9, 9]
        assert call("create_ramp", storey.GlobalId, 5, 0, 0, 1.2, 0.4, "")["ok"]
        assert f.by_type("IfcRamp")[0].ShapeType == "STRAIGHT_RUN_RAMP"
        assert call("add_stair_railings", r["guid"])["ok"]
        assert call("create_railing", storey.GlobalId, json.dumps([[0, -2], [3, -2]]), "")["ok"]
        assert f.schema == "IFC2X3" and len(f.by_type("IfcRailing")) == 3
        assert errors() == []
    finally:
        testing._reset_owner()
