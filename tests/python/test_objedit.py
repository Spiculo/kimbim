# SPDX-License-Identifier: GPL-3.0-or-later
"""The Object Editor (D101): objects made in the project, kept only on their types, are listed in the
Library and placed from the definition stored with them."""
import json

import ifcopenshell.util.element
import pytest

from kimbim import app_bridge as b
from kimbim import library, objects


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


@pytest.fixture
def project():
    assert call("new_project", "Editor")["ok"]
    yield call("storeys")["storeys"][0]["guid"]
    library.load_office()


BLOCK = {
    "format": "kimbim-object/1", "id": "block", "name": {"en": "Block", "es": "Bloque"}, "category": "furniture",
    "ifc": {"IFC4": ["IfcFurnitureType", "NOTDEFINED", None]},
    "params": [{"key": "width", "kind": "length", "label": "Width", "default": 0.4},
               {"key": "depth", "kind": "length", "label": "Depth", "default": 0.4},
               {"key": "height", "kind": "length", "label": "Height", "default": 0.45}],
    "parts": [{"id": "body", "box": {"dx": "width", "dy": "depth", "dz": "height"}}],
}


def test_a_project_object_lists_and_places(project):
    data = json.loads((library.BUNDLED / "table.kimobj").read_text(encoding="utf-8"))
    defn = objects.load({**data, "id": "stool"}, "project")
    assert defn.ref == "project:stool" and library.get("project:stool") is None
    b._run(lambda: (library._make_type(defn, defn.values()), 1)[1])
    listed = [o for o in call("library_objects")["objects"] if o["id"] == "project:stool"]
    assert len(listed) == 1 and listed[0]["category"] == "project" and listed[0]["library"] == "project"
    assert ("project", "Project") in [(c["id"], c["name"]) for c in call("library_objects")["categories"]]
    p = call("place_object", project, "project:stool", '{"width": 0.7}', 0, 0)
    assert p["ok"], p
    t = b._model.by_guid(p["type"])
    assert ifcopenshell.util.element.get_pset(t, library.PSET, "Object") == "project:stool"
    assert json.loads(ifcopenshell.util.element.get_pset(t, library.PSET, "Parameters"))["width"] == 0.7
    assert call("place_object", project, "project:nothing", "", 0, 0)["ok"] is False


def test_an_object_gone_from_the_library_still_places(project, tmp_path):
    (tmp_path / "block.kimobj").write_text(json.dumps(BLOCK), encoding="utf-8")
    library.load_office(str(tmp_path))
    assert call("place_object", project, "office:block", "", 0, 0)["ok"]
    library.load_office()
    p = call("place_object", project, "office:block", '{"height": 0.9}', 1, 0)
    assert p["ok"], p
    t = b._model.by_guid(p["type"])
    assert json.loads(ifcopenshell.util.element.get_pset(t, library.PSET, "Parameters"))["height"] == 0.9
