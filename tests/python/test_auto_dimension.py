# SPDX-License-Identifier: GPL-3.0-or-later
"""D98: Archicad's Automatic Dimensioning of walls and their openings."""
import json

import pytest

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def project():
    assert call("new_project", "Dims")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    types = {t["name"]: t["guid"] for t in call("wall_types")["types"]}
    return {"level": level, **types}


def test_automatic_wall_dimensions(project):
    """D98: Archicad's Automatic Dimensioning: the wall's ends and its doors' edges, outside its face."""
    t = project["Exterior 300"]
    w = call("create_wall", project["level"], t, 0, 0, 6, 0, 3.0, "", "", "Outside face")["guid"]
    door = call("opening_types", "door")["types"][0]
    assert call("insert_opening", "door", w, door["guid"], 2.0, 1.0, door["height"], door["sill"])["ok"]
    r = call("auto_dimension", json.dumps([w]), 0.8)
    assert r["ok"] and len(r["guids"]) == 1, r
    dim = next(a for a in call("annotations", project["level"])["annotations"] if a["guid"] == r["guids"][0])
    assert dim["kind"] == "dimension"
    xs = [round(p[0], 6) for p in dim["points"][:-1]]
    assert xs == [0.0, 1.5, 2.5, 6.0]
    assert {round(p[1], 6) for p in dim["points"][:-1]} == {0.0}  # on the outside face (the drawn line)
    assert dim["points"][-1][1] == pytest.approx(-0.8)  # outside it, away from the body (y 0 to 0.3)
    assert dim["text"].split() == ["1.50", "1.00", "3.50"]
    assert not call("auto_dimension", json.dumps([]), 0.8)["ok"]
