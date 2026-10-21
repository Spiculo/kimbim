# SPDX-License-Identifier: GPL-3.0-or-later
"""Archicad's Grid System (D98): a rectangular set of grid axes in one undo step."""
import json

import pytest

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def level():
    assert call("new_project", "Casa")["ok"]
    return call("storeys")["storeys"][0]["guid"]


def lines(level):
    return {g["tag"]: g for g in call("snap_data", level)["grid"]}


def test_grid_system_makes_numbered_and_lettered_axes_in_one_step(level):
    r = call("add_grid_system", level, 0, 0, 0, json.dumps([5, 5]), json.dumps([4]), 1.0)
    assert r["ok"], r
    assert r["tags"] == ["1", "2", "3", "A", "B"]
    g = lines(level)
    assert (g["2"]["x1"], g["2"]["y1"], g["2"]["x2"], g["2"]["y2"]) == pytest.approx((5, -1, 5, 5))
    assert (g["B"]["x1"], g["B"]["y1"], g["B"]["x2"], g["B"]["y2"]) == pytest.approx((-1, 4, 11, 4))
    call("undo")
    assert lines(level) == {}


def test_grid_system_turns_and_continues_the_labels(level):
    assert call("add_grid_system", level, 0, 0, 0, json.dumps([3]), json.dumps([]), 1.0)["ok"]
    r = call("add_grid_system", level, 10, 0, 90, json.dumps([2]), json.dumps([]), 1.0)
    assert r["ok"], r
    assert r["tags"] == ["3", "4", "B"]  # labels go on from the first system (which took 1, 2 and A)
    g = lines(level)
    assert (g["4"]["x1"], g["4"]["y1"], g["4"]["x2"], g["4"]["y2"]) == pytest.approx((11, 2, 9, 2))  # turned 90 degrees


def test_grid_system_rejects_bad_input(level):
    assert not call("add_grid_system", level, 0, 0, 0, json.dumps([0]), json.dumps([]), 1.0)["ok"]
    assert not call("add_grid_system", "nope", 0, 0, 0, json.dumps([1]), "[]", 1.0)["ok"]
    assert not call("add_grid_system", level, 0, 0, 0, json.dumps([1]), "[]", 0.0)["ok"]  # zero-length lines
