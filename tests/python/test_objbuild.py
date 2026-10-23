# SPDX-License-Identifier: GPL-3.0-or-later
"""D99 geometry: shapes, frames, anchors and patterns, repeats, when, use/with, axes, symbol and
auto outline, limits."""
import math
import re

import numpy as np
import pytest

from kimbim import objects
from kimbim.objbuild import MAX_SOLIDS, ObjectError, build


def obj(parts, params=None, symbol=None, components=None, **extra):
    data = {"format": "kimbim-object/1", "id": "t", "name": "T", "category": "furniture",
            "ifc": {"IFC4": ["IfcFurnitureType", "CHAIR", None]},
            "params": params or [{"key": "width", "kind": "length", "label": "Width", "default": 1.0},
                                 {"key": "depth", "kind": "length", "label": "Depth", "default": 0.5}],
            "parts": parts, **extra}
    if symbol is not None:
        data["symbol"] = symbol
    if components is not None:
        data["components"] = components
    return objects.load(data)


def shape(d, **given):
    return d.shape(d.values(given))


def origin(s):
    return np.array(s["matrix"])[:3, 3]


def test_box_and_metrics():
    s = shape(obj([{"id": "b", "box": {"dx": "width", "dy": "depth", "dz": 0.1}}]))
    m = s.metrics()
    assert m["bbox"] == pytest.approx([0, 0, 0, 1, 0.5, 0.1])
    assert m["volume"] == pytest.approx(0.05)


@pytest.mark.parametrize("part, volume", [
    ({"cylinder": {"r": 0.1, "h": 1}}, math.pi * 0.01),
    ({"cone": {"r1": 0.1, "r2": 0.05, "h": 1}}, math.pi * (0.01 + 0.005 + 0.0025) / 3),
    ({"prism": {"points": [[0, 0], [1, 0], [0, 1]], "h": 2}}, 1.0),
    ({"revolve": {"profile": [[0, 0], [0.1, 0], [0.1, 1], [0, 1]]}}, math.pi * 0.01),
    ({"sweep": {"r": 0.01, "path": [[0, 0, 0], [1, 0, 0], [1, 1, 0]]}}, math.pi * 0.0001 * 2),
    ({"sweep": {"profile": [[-0.05, -0.05], [0.05, -0.05], [0.05, 0.05], [-0.05, 0.05]], "path": [[0, 0, 0], [0, 0, 2]]}}, 0.02),
    ({"box": {"dx": 1, "dy": 1, "dz": 3, "taper": 0.5}}, 3 * (1 + 0.25 + 0.5) / 3),
])
def test_every_shape_has_a_volume(part, volume):
    s = shape(obj([{"id": "p", **part}]))
    assert len(s.solids) == 1
    assert s.metrics()["volume"] == pytest.approx(volume, rel=1e-6)


def test_point_generators():
    s = shape(obj([{"id": "p", "prism": {"points": [{"ellipse": [0.5, 0.5, 0.5, 0.25], "n": 12}], "h": 1}}]))
    assert len(s.solids[0]["points"]) == 12
    s = shape(obj([{"id": "p", "prism": {"points": [{"rounded_rect": [0, 0, 1, 1, 0.2], "n": 4}], "h": 1}}]))
    assert len(s.solids[0]["points"]) == 20
    s = shape(obj([{"id": "p", "prism": {"points": [{"rounded_rect": [0, 0, 1, 1, 0.2], "n": 1}], "h": 1}}]))
    assert len(s.solids[0]["points"]) == 8
    with pytest.raises(ObjectError, match="n between 3"):
        shape(obj([{"id": "p", "prism": {"points": [{"ellipse": [0.5, 0.5, 0.5, 0.25], "n": 2}], "h": 1}}]))


def test_thin_shapes_are_skipped():
    assert shape(obj([{"id": "b", "box": {"dx": 1, "dy": 0, "dz": 1}}])).solids == []


def test_repeat_with_index_and_when():
    d = obj([{"id": "leg", "repeat": {"count": 4}, "when": "width > 0.5",
              "box": {"x": "if(i < 2, 0, width - 0.1)", "y": "if(i % 2 == 0, 0, depth - 0.1)", "dx": 0.1, "dy": 0.1, "dz": 1}}])
    s = shape(d)
    assert sorted(tuple(np.round([x["x"], x["y"]], 3)) for x in s.solids) == [(0, 0), (0, 0.4), (0.9, 0), (0.9, 0.4)]
    assert shape(d, width=0.4).solids == []


def test_repeat_step_and_turn():
    s = shape(obj([{"id": "slat", "repeat": {"count": 3, "step": [0.2, 0, 0]}, "box": {"dx": 0.1, "dy": 0.1, "dz": 0.1}}]))
    assert [origin(x)[0] for x in s.solids] == pytest.approx([0, 0.2, 0.4])
    s = shape(obj([{"id": "arm", "repeat": {"count": 4, "turn": 90}, "box": {"x": 1, "dx": 0.1, "dy": 0.1, "dz": 0.1}}]))
    pts = [np.array(x["matrix"]) @ [1, 0, 0, 1] for x in s.solids]
    assert [tuple(np.round(p[:2], 6)) for p in pts] == [(1, 0), (0, 1), (-1, 0), (0, -1)]


SEAT = {"id": "seat", "box": {"z": 0.41, "dx": "width", "dy": "depth", "dz": 0.04},
        "anchors": {"corners": {"pattern": "rect_corners", "inset": 0.02, "z": 0.41, "dir": "down"},
                    "ring": {"pattern": "circle", "cx": "width / 2", "cy": "depth / 2", "r": 0.2, "z": 0.41, "dir": "down"},
                    "back_edge": {"x": "width / 2", "y": "depth - 0.02", "z": 0.45}}}


def test_built_in_and_single_anchors_attach_and_feed_formulas():
    s = shape(obj([SEAT,
                   {"id": "back", "attach": "seat.anchors.back_edge", "box": {"x": -0.1, "dx": 0.2, "dy": 0.02, "dz": 0.4}},
                   {"id": "lamp", "attach": "seat.top", "box": {"dx": 0.01, "dy": 0.01, "dz": "seat.back_edge.z"}}]))
    back, lamp = s.solids[1], s.solids[2]
    assert origin(back) == pytest.approx([0.5, 0.48, 0.45])
    assert origin(lamp) == pytest.approx([0.5, 0.25, 0.45])
    assert lamp["dz"] == pytest.approx(0.45)


def test_rect_corners_pattern_ignores_count_and_points_down():
    s = shape(obj([SEAT, {"id": "leg", "repeat": {"on": "seat.anchors.corners", "count": 3},
                          "box": {"x": -0.02, "y": -0.02, "dx": 0.04, "dy": 0.04, "dz": 0.41}}]))
    legs = s.solids[1:]
    assert len(legs) == 4
    assert sorted(tuple(np.round(origin(x)[:2], 3)) for x in legs) == [(0.02, 0.02), (0.02, 0.48), (0.98, 0.02), (0.98, 0.48)]
    assert s.metrics()["bbox"][2] == pytest.approx(0)  # legs reach the floor (dir down)


def test_circle_pattern_with_count_and_template():
    d = obj([SEAT, {"id": "leg", "repeat": {"on": "seat.anchors.{layout}", "count": "legs"},
                    "cylinder": {"r": 0.02, "h": 0.41}}],
            params=[{"key": "width", "kind": "length", "label": "W", "default": 1.0},
                    {"key": "depth", "kind": "length", "label": "D", "default": 0.5},
                    {"key": "legs", "kind": "count", "label": "L", "default": 3, "max": 8},
                    {"key": "layout", "kind": "choice", "label": "Layout", "default": "ring",
                     "options": [{"id": "ring", "label": "Ring"}, {"id": "corners", "label": "Corners"}]}])
    assert len(shape(d).solids) == 1 + 3
    assert len(shape(d, legs=5).solids) == 1 + 5
    assert len(shape(d, layout="corners").solids) == 1 + 4
    ring = [origin(x) for x in shape(d).solids[1:]]
    assert all(math.dist(p[:2], (0.5, 0.25)) == pytest.approx(0.2) for p in ring)


def test_away_from_centre_tilts_far_ends_outward():
    d = obj([SEAT, {"id": "leg", "repeat": {"on": "seat.anchors.ring", "count": 3},
                    "rotate": {"axis": "away_from_centre", "angle": 10}, "cylinder": {"r": 0.02, "h": 0.41}}])
    for s in shape(d).solids[1:]:
        m = np.array(s["matrix"])
        top, foot = m @ [0, 0, 0, 1], m @ [0, 0, 0.41, 1]
        centre = np.array([0.5, 0.25])
        assert np.linalg.norm(foot[:2] - centre) > np.linalg.norm(top[:2] - centre)  # the foot splays out
        assert foot[2] < top[2]
    one = obj([SEAT, {"id": "leg", "repeat": {"on": "seat.anchors.ring", "count": 1},
                      "rotate": {"axis": "away_from_centre", "angle": 10}, "cylinder": {"r": 0.02, "h": 0.41}}])
    m = np.array(shape(one).solids[1]["matrix"])
    assert m[:3, 2] == pytest.approx([0, 0, -1])  # a single copy stays upright


def test_axes_for_upright_profiles():
    s = shape(obj([{"id": "wheel", "axes": ["y", "z", "x"], "cylinder": {"cx": 2, "cy": 0.3, "z": 0.1, "r": 0.3, "h": 0.2}}]))
    assert s.metrics()["bbox"] == pytest.approx([0.1, 1.7, 0, 0.3, 2.3, 0.6], abs=1e-6)


def test_use_components_with_values_and_material_override():
    comps = {"leg_round": {"params": [{"key": "size", "kind": "length", "label": "Size", "default": 0.04},
                                      {"key": "h", "kind": "length", "label": "H", "default": 0.4}],
                           "parts": [{"id": "post", "cylinder": {"r": "size / 2", "h": "h"}}]}}
    d = obj([{"id": "leg", "material": "frame", "use": "leg_{style}", "with": {"h": "width / 2"}}],
            params=[{"key": "width", "kind": "length", "label": "W", "default": 1.0},
                    {"key": "style", "kind": "choice", "label": "S", "default": "round",
                     "options": [{"id": "round", "label": "Round"}]}],
            components=comps)
    (s,) = shape(d).solids
    assert s["h"] == pytest.approx(0.5) and s["r"] == pytest.approx(0.02) and s["part"] == "frame"


def test_use_another_library_object():
    other = objects.load({"format": "kimbim-object/1", "id": "knob", "name": "Knob", "category": "furniture",
                          "ifc": {"IFC4": ["IfcFurnitureType", "USERDEFINED", "KNOB"]},
                          "params": [{"key": "r", "kind": "length", "label": "R", "default": 0.02}],
                          "parts": [{"id": "k", "cylinder": {"r": "r", "h": 0.02}}]})
    d = objects.load({"format": "kimbim-object/1", "id": "t", "name": "T", "category": "furniture",
                      "ifc": {"IFC4": ["IfcFurnitureType", "CHAIR", None]},
                      "parts": [{"id": "k", "use": "knob", "with": {"r": 0.05}}]}, check=False)
    (s,) = build(d, d.values(), resolve=lambda ref: other if ref == "knob" else None).solids
    assert s["r"] == pytest.approx(0.05)


def test_use_cycle_is_an_error():
    with pytest.raises(ObjectError, match="cycle"):
        obj([{"id": "a", "use": "x"}], components={"x": {"parts": [{"id": "b", "use": "y"}]},
                                                     "y": {"parts": [{"id": "c", "use": "x"}]}})


def test_repeat_over_the_limit_fails_before_looping():
    import time
    start = time.perf_counter()
    with pytest.raises(ObjectError, match="limit"):
        obj([{"id": "b", "repeat": {"count": 1e9}, "box": {"dx": 1, "dy": 1, "dz": 1}}])
    with pytest.raises(ObjectError, match="limit"):
        obj([{"id": "b", "repeat": {"count": MAX_SOLIDS // 2 + 1},
              "use": "two"}], components={"two": {"parts": [{"id": "x", "repeat": {"count": 2}, "box": {"dx": 1, "dy": 1, "dz": 1}}]}})
    assert time.perf_counter() - start < 10  # the limit error is the test; the bound only catches hangs


BIG = [{"ellipse": [0, 0, 1, 1], "n": 250}] * 8  # 2,000 points, the most one shape takes


def test_symbol_repeat_of_many_points_over_the_limit_fails():
    import time
    start = time.perf_counter()
    with pytest.raises(ObjectError, match="limit"):
        obj([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}}], symbol=[{"polygon": {"points": BIG}, "repeat": {"count": 200}}])
    with pytest.raises(ObjectError, match="limit"):  # every symbol copy counts as work too
        obj([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}}],
            symbol=[{"rect": {"x": 0, "y": 0, "dx": 1, "dy": 1}, "repeat": {"count": 5000}}] * 5)
    assert time.perf_counter() - start < 10  # the limit error is the test; the bound only catches hangs


def test_many_large_prisms_over_the_point_limit_fail():
    import time
    start = time.perf_counter()
    with pytest.raises(ObjectError, match="limit"):
        obj([{"id": f"p{k}", "prism": {"points": BIG, "h": 1}} for k in range(200)])
    with pytest.raises(ObjectError, match="limit"):
        obj([{"id": "p", "repeat": {"count": 200}, "prism": {"points": BIG, "h": 1}}])
    assert time.perf_counter() - start < 10  # the limit error is the test; the bound only catches hangs


BOX = {"dx": 1, "dy": 1, "dz": 1}


@pytest.mark.parametrize("parts, message", [
    ([{"id": "a", "box": {**BOX, "dx": "'1e400'"}}], "parts.a.box.dx: a number, not '1e400'"),
    ([{"id": "a", "box": {**BOX, "dy": "'nan'"}}], "parts.a.box.dy: a number, not 'nan'"),
    ([{"id": "a", "box": {**BOX, "dz": float("inf")}}], "parts.a.box.dz: inf is not a finite number"),
    ([{"id": "a", "box": {**BOX, "dx": "1e300 * 1e300"}}], "parts.a.box.dx: number too large"),
    ([{"id": "a", "box": BOX, "at": ["'nan'", 0, 0]}], "parts.a.at: a number"),
    ([{"id": "a", "box": BOX, "repeat": {"count": "'1e400'"}}], "parts.a.repeat.count: a number"),
    ([{"id": "a", "box": BOX, "repeat": {"count": float("nan")}}], "parts.a.repeat.count: nan is not a finite number"),
    ([{"id": "a", "box": BOX, "rotate": {"angle": float("inf")}}], "parts.a.rotate.angle: inf"),
    ([{"id": "a", "prism": {"points": [[0, 0], [1, 0], ["'inf'", 1]], "h": 1}}], "parts.a.prism.points: a number"),
    ([{"id": "a", "box": BOX, "anchors": {"p": {"x": 0, "dir": [0, 0, 0]}}},
      {"id": "b", "attach": "a.p", "box": BOX}], "parts.a.anchors.p.dir: a direction of zero length"),
    ([{"id": "a", "box": BOX, "anchors": {"p": {"pattern": "line", "from": [0, 0, 0], "to": [1, 0, 0], "dir": [0, 0, 0]}}},
      {"id": "b", "repeat": {"on": "a.p", "count": 2}, "box": BOX}], "parts.a.anchors.p: dir: a direction of zero length"),
    ([{"id": "s", "sweep": {"profile": [[0, 0], [0.1, 0], [0.1, 0.1]], "path": [[0, 0, 0], [0, 0, 0], [0, 0, 1]]}}],
     "parts.s.sweep.path: points 0 and 1 are in the same place"),
])
def test_non_finite_and_degenerate_geometry_fails_at_load_naming_the_field(parts, message):
    with pytest.raises(ObjectError, match=re.escape(message)):
        obj(parts)


def test_non_finite_symbol_values_name_the_field():
    with pytest.raises(ObjectError, match=r"symbol\[0\]\.rect\.dx: a number"):
        obj([{"id": "b", "box": BOX}], symbol=[{"rect": {"x": 0, "y": 0, "dx": "'inf'", "dy": 1}}])


def test_a_build_never_returns_non_finite_numbers():
    d = obj([{"id": "a", "box": BOX}])
    s = d.shape(d.values())
    s.solids[0]["matrix"][0][3] = float("nan")
    from kimbim.objbuild import _check_finite
    with pytest.raises(ObjectError, match=re.escape("solid 1 (box): a value that is not a finite number")):
        _check_finite(s)


@pytest.mark.parametrize("part, message", [
    ({"id": "a", "use": 5}, "parts.a.use: a name"),
    ({"id": "a", "box": BOX, "rotate": 5}, "parts.a.rotate: an object"),
    ({"id": "a", "box": BOX, "anchors": [{"x": 0}]}, "parts.a.anchors: an object of named anchors"),
    ({"id": "a", "box": BOX, "anchors": {"p": 5}}, "parts.a.anchors.p: an object"),
    ({"id": "a", "box": BOX, "repeat": {}}, "parts.a.repeat: count or on is missing"),
    ({"id": "a", "box": BOX, "repeat": 3}, "parts.a.repeat: an object"),
    ({"id": "a", "box": BOX, "at": 1}, "parts.a.at: a list of numbers"),
])
def test_wrong_json_types_name_the_field(part, message):
    with pytest.raises(ObjectError, match=message):
        obj([part])
    with pytest.raises(ObjectError, match=r"symbol\[0\]\.repeat: an object with a count"):
        obj([{"id": "b", "box": BOX}], symbol=[{"rect": {"x": 0, "y": 0, "dx": 1, "dy": 1}, "repeat": {}}])


@pytest.mark.parametrize("parts, message", [
    ([{"id": "b", "box": {"dx": 1, "dy": 1}}], "parts.b.box: dz is missing"),
    ([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1, "colour": 2}}], "parts.b.box: unknown field 'colour'"),
    ([{"id": "b", "box": {"dx": "wdth", "dy": 1, "dz": 1}}], "parts.b.box.dx: unknown name 'wdth'"),
    ([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}, "cylinder": {"r": 1, "h": 1}}], "parts.b: one shape"),
    ([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}}, {"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}}], "twice"),
    ([{"id": "b", "attach": "nothing.top", "box": {"dx": 1, "dy": 1, "dz": 1}}], "unknown part 'nothing'"),
    ([{"id": "b", "use": "ghost"}], "unknown component or object 'ghost'"),
    ([{"id": "b", "axes": ["x", "x", "z"], "box": {"dx": 1, "dy": 1, "dz": 1}}], "axes"),
    ([{"id": "b", "axes": ["y", "x", "z"], "box": {"dx": 1, "dy": 1, "dz": 1}}], "right-handed"),
    ([{"id": "Baño", "box": {"dx": 1, "dy": 1, "dz": 1}}], "must be lower-case"),
    ([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}, "anchors": {"e": {"x": "zz"}}}], "parts.b.anchors.e: unknown name 'zz'"),
    ([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}, "anchors": {"g": {"pattern": "grid", "nx": -1, "ny": 2, "dx": 1, "dy": 1}}}],
     "parts.b.anchors.g: nx and ny must be positive"),
])
def test_part_errors_name_the_field(parts, message):
    with pytest.raises(ObjectError, match=message):
        obj(parts)


def test_explicit_symbol_with_repeat():
    d = obj([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}}],
            symbol=[{"rect": {"x": 0, "y": 0, "dx": "width", "dy": "depth"}},
                    {"circle": {"cx": 0.5, "cy": 0.25, "r": 0.1}},
                    {"repeat": {"count": 3}, "line": {"points": [["0.1 + i * 0.2", 0], ["0.1 + i * 0.2", 0.1]]}},
                    {"when": "width > 5", "line": {"points": [[0, 0], [1, 1]]}},
                    {"ellipse": {"cx": 0.5, "cy": 0.25, "rx": 0.2, "ry": 0.1}}])
    curves = shape(d).curves
    assert [c[0] for c in curves] == ["poly", "circle", "poly", "poly", "poly", "poly"]
    assert curves[0][1] == [(0, 0), (1, 0), (1, 0.5), (0, 0.5), (0, 0)]
    assert len(curves[-1][1]) == 17  # 16 points, closed


def test_auto_outline_is_the_union_seen_from_above():
    d = obj([{"id": "a", "box": {"dx": 1, "dy": 1, "dz": 1}}, {"id": "b", "box": {"x": 0.5, "dx": 1, "dy": 1, "dz": 0.5}}])
    curves = shape(d).curves
    assert len(curves) == 1
    xs = [p[0] for p in curves[0][1]]
    assert min(xs) == pytest.approx(0) and max(xs) == pytest.approx(1.5)


def test_origin_shifts_solids_and_curves():
    d = obj([{"id": "a", "box": {"dx": 1, "dy": 1, "dz": 1}}], origin=[0.5, 0.5],
            symbol=[{"rect": {"x": 0, "y": 0, "dx": 1, "dy": 1}}])
    s = shape(d)
    assert s.metrics()["bbox"][:2] == pytest.approx([-0.5, -0.5])
    assert s.curves[0][1][0] == pytest.approx((-0.5, -0.5))


def test_anchor_selection_is_sound():
    # templated references, anchors with no reference, and symbol references all resolve
    parts = [{"id": "front", "box": {"dx": 1, "dy": 1, "dz": 1}}, {"id": "back_", "box": {"y": 2, "dx": 1, "dy": 1, "dz": 1}},
             {"id": "knob", "attach": "{which}.top", "box": {"dx": 0.1, "dy": 0.1, "dz": 0.1}}]
    d = obj(parts, params=[{"key": "which", "kind": "choice", "label": "W", "default": "front",
                            "options": [{"id": "front", "label": "F"}, {"id": "back_", "label": "B"}]}])
    assert origin(shape(d, which="back_").solids[2])[1] == pytest.approx(2.5)
    d = obj([SEAT], symbol=[{"line": {"points": [[0, 0], [0, "seat.back_edge.y"]]}}])
    assert shape(d).curves[0][1][1] == (0, pytest.approx(0.48))


def test_work_budget_counts_thin_and_anchor_only_parts():
    import time
    start = time.perf_counter()
    thin = {"id": "o", "repeat": {"count": 300}, "use": "row"}
    with pytest.raises(ObjectError, match="limit"):
        obj([thin], components={"row": {"parts": [{"id": "t", "repeat": {"count": 300}, "box": {"dx": 1, "dy": 0, "dz": 1}}]}})
    nest = {"id": "o", "repeat": {"count": 30}, "use": "a"}
    comps = {"a": {"parts": [{"id": "x", "repeat": {"count": 30}, "use": "b"}]},
             "b": {"parts": [{"id": "y", "repeat": {"count": 30}, "anchors": {"p": {"x": 0}}}]}}
    with pytest.raises(ObjectError, match="limit"):
        obj([nest], components=comps)
    assert time.perf_counter() - start < 10  # the limit error is the test; the bound only catches hangs


def test_arc_symbol():
    d = obj([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}}], symbol=[{"arc": {"cx": 0, "cy": 0, "r": 1, "a0": 0, "a1": 90}}])
    pts = shape(d).curves[0][1]
    assert pts[0] == pytest.approx((1, 0)) and pts[-1] == pytest.approx((0, 1), abs=1e-9)


def test_symbol_item_must_be_an_object():
    with pytest.raises(ObjectError, match=r"symbol\[0\]: an object"):
        obj([{"id": "b", "box": {"dx": 1, "dy": 1, "dz": 1}}], symbol=[5])
