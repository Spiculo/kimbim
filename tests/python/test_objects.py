# SPDX-License-Identifier: GPL-3.0-or-later
"""D99 format: loading, validation messages, parameters (kinds, limits as formulas, show_when), clean."""
import json

import pytest

from kimbim import objects
from kimbim.objects import ObjectError


def minimal(**over):
    data = {
        "format": "kimbim-object/1", "id": "stool", "name": {"en": "Stool", "es": "Taburete"},
        "category": "furniture", "ifc": {"IFC4": ["IfcFurnitureType", "CHAIR", None]},
        "params": [
            {"key": "width", "kind": "length", "label": "Width", "default": 0.4},
            {"key": "height", "kind": "length", "label": {"en": "Height", "es": "Altura"}, "default": 0.6,
             "max": "width * 3"},
            {"key": "legs", "kind": "count", "label": "Legs", "default": 3, "min": 1, "max": 8},
            {"key": "layout", "kind": "choice", "label": "Layout", "default": "circle",
             "options": [{"id": "circle", "label": {"en": "On a circle", "es": "En círculo"}},
                         {"id": "corners", "label": "At the corners"}]},
            {"key": "radius", "kind": "length", "label": "Radius", "default": 0.15, "show_when": "layout == 'circle'"},
            {"key": "arms", "kind": "bool", "label": "Arms", "default": False},
            {"key": "splay", "kind": "angle", "label": "Splay", "default": 0, "min": 0, "max": 20},
        ],
        "materials": {"frame": {"label": "Frame material", "default": "Steel"}},
        "parts": [{"id": "seat", "box": {"dx": "width", "dy": "width", "dz": 0.04, "z": "height - 0.04"}}],
    }
    data.update(over)
    return data


def test_loads_and_fills_defaults():
    d = objects.load(minimal())
    assert d.key == d.ref == "stool" and d.name == "Stool" and d.names["es"] == "Taburete"
    assert d.ifc["IFC4"] == ("IfcFurnitureType", "CHAIR", None)
    v = d.values()
    assert v == {"width": 0.4, "height": 0.6, "legs": 3, "layout": "circle", "radius": 0.15, "arms": False,
                 "splay": 0.0, "mat_frame": "Steel"}
    assert d.param("Legs").key == "legs" and d.param("mat_frame").kind == "material"


def test_office_and_project_refs():
    assert objects.load(minimal(), source="office").ref == "office:stool"


def test_limits_are_formulas_and_values_clamp():
    d = objects.load(minimal())
    assert d.values({"height": 5})["height"] == pytest.approx(1.2)  # max = width * 3
    assert d.values({"legs": 99})["legs"] == 8
    assert d.values({"legs": 2.6})["legs"] == 3
    assert d.values({"splay": -5})["splay"] == 0


def test_clean_choice_and_bool_from_text():
    d = objects.load(minimal())
    assert d.values({"layout": "At the corners"})["layout"] == "corners"
    assert d.values({"layout": "en círculo"})["layout"] == "circle"
    assert d.values({"layout": "nonsense"})["layout"] == "circle"  # unknown: the default
    for text, want in (("true", True), ("false", False), ("1", True), ("0", False), (True, True), ("sí", True)):
        assert d.values({"arms": text})["arms"] is want


def test_show_when():
    d = objects.load(minimal())
    assert "radius" in d.visible(d.values())
    assert "radius" not in d.visible(d.values({"layout": "corners"}))


def test_type_name():
    d = objects.load(minimal())
    assert d.type_name(d.values()) == "Stool 400x600"
    assert d.type_name(d.values({"legs": 4, "splay": 8, "arms": True})) == "Stool 400x600 (Legs 4, Arms yes, Splay 8°)"


def test_canonical_and_digest_are_stable():
    a = objects.canonical(minimal())
    b = objects.canonical(json.loads(json.dumps(minimal(), indent=3)))
    assert a == b and objects.digest(a) == objects.digest(b) and len(objects.digest(a)) == 32
    assert objects.load(minimal()).hash == objects.digest(a)


@pytest.mark.parametrize("change, message", [
    ({"format": "kimbim-object/0"}, "format"),
    ({"id": "Bad Id"}, "id"),
    ({"category": "spaceship"}, "category"),
    ({"ifc": {"IFC2X3": ["IfcFurnitureType", None, "Chair"]}}, "IFC4"),
    ({"colour": "red"}, "unknown field 'colour'"),
    ({"params": [{"key": "w", "kind": "size", "label": "W", "default": 1}]}, "params.w: unknown kind"),
    ({"params": [{"key": "i", "kind": "count", "label": "I", "default": 1}]}, "reserved"),
    ({"params": [{"key": "a", "kind": "count", "label": "A", "default": 1},
                 {"key": "a", "kind": "count", "label": "B", "default": 1}]}, "twice"),
    ({"params": [{"key": "c", "kind": "choice", "label": "C", "default": "x", "options": [{"id": "y", "label": "Y"}]}]},
     "params.c: default"),
    ({"params": [{"key": "a", "kind": "count", "label": "Legs", "default": 1},
                 {"key": "b", "kind": "count", "label": "legs", "default": 1}]}, "label 'legs' is used twice"),
])
def test_validation_names_the_field(change, message):
    with pytest.raises(ObjectError, match=message):
        objects.load(minimal(**change))


def test_load_file_limits_size(tmp_path):
    p = tmp_path / "big.kimobj"
    p.write_text(" " * (objects.MAX_FILE_BYTES + 1), encoding="utf-8")
    with pytest.raises(ObjectError, match="too large"):
        objects.load_file(str(p), "office")
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ObjectError, match="big.kimobj"):
        objects.load_file(str(p), "office")


def test_from_text_is_cached():
    text = objects.canonical(minimal())
    assert objects.from_text(text, "project") is objects.from_text(text, "project")


def derived(**over):
    d = minimal()
    d["parts"] = [{"id": "b", "box": {"dx": "base", "dy": "base", "dz": "tall"}}]
    d.pop("symbol", None)
    d["params"] = [
        {"key": "base", "kind": "length", "label": "Base", "default": 0.4},
        {"key": "w2", "kind": "length", "label": "Double", "default": "base * 2", "max": 100},
        {"key": "wide", "kind": "length", "label": "Wide", "default": 0.3, "max": "tall * 3"},
        {"key": "tall", "kind": "length", "label": "Tall", "default": 0.5},
    ]
    d.update(over)
    return objects.load(d)


def test_formula_default_from_text_value():
    assert derived().values({"base": "0,5"})["w2"] == pytest.approx(1.0)


def test_formula_default_with_junk_value_uses_default():
    v = derived().values({"base": "abc"})
    assert v["base"] == 0.4 and v["w2"] == pytest.approx(0.8)


def test_clamped_value_propagates():
    v = derived().values({"base": 99})
    assert v["base"] == 50 and v["w2"] == 100


def test_forward_limit_with_text_input():
    d = derived()
    assert d.values({"tall": "0,9", "wide": 5})["wide"] == pytest.approx(2.7)


def test_malformed_ifc_and_origin():
    with pytest.raises(ObjectError, match="ifc"):
        objects.load(minimal(ifc="IFC4"))
    with pytest.raises(ObjectError, match="ifc"):
        objects.load(minimal(ifc={"IFC4": "chair"}))
    with pytest.raises(ObjectError, match="origin"):
        objects.load(minimal(origin="here"))
