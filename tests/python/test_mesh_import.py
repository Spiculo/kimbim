# SPDX-License-Identifier: GPL-3.0-or-later
"""Generic mesh import: OBJ, ASCII/binary STL and ASCII PLY, scale/rotation/translation, the proxy and
its KIMBIM_MeshImport property set, IFC2X3 fallback, error reports and a saved-model validation."""
import json
import struct

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.representation
import ifcopenshell.validate
import numpy as np
import pytest

from kimbim import app_bridge as B
from kimbim import meshimport as M
from kimbim.testing import _reset_owner, build_model

CUBE_VERTICES = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
                 (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (0.0, 1.0, 1.0)]
CUBE_QUADS = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 4, 7, 3),
              (1, 5, 4, 0), (2, 6, 5, 1), (3, 7, 6, 2)]


def call(fn, *args):
    return json.loads(fn(*args))


def open_model(schema="IFC4"):
    f = build_model(schema=schema, walls=0)
    B._model = f
    B._reset_history("")
    return f, f.by_type("IfcBuildingStorey")[0].GlobalId


def issues(model=None):
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model or B._model, logger, express_rules=True)
    return logger.statements


def mesh(guid):
    import ifcopenshell.geom

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    shape = ifcopenshell.geom.create_shape(settings, B._model.by_guid(guid))
    return np.array(shape.geometry.verts).reshape(-1, 3), np.array(shape.geometry.faces).reshape(-1, 3)


def obj_cube() -> str:
    lines = ["# unit cube", "o cube"]
    lines += ["v " + " ".join(f"{c:g}" for c in p) for p in CUBE_VERTICES]
    lines += ["f " + " ".join(str(i + 1) for i in quad) for quad in CUBE_QUADS]
    return "\n".join(lines) + "\n"


def stl_triangles():
    out = []
    for quad in CUBE_QUADS:
        out.append((CUBE_VERTICES[quad[0]], CUBE_VERTICES[quad[1]], CUBE_VERTICES[quad[2]]))
        out.append((CUBE_VERTICES[quad[0]], CUBE_VERTICES[quad[2]], CUBE_VERTICES[quad[3]]))
    return out


def stl_binary() -> bytes:
    triangles = stl_triangles()
    data = bytearray(b"binary STL cube".ljust(80, b" "))
    data += struct.pack("<I", len(triangles))
    for corners in triangles:
        data += struct.pack("<3f", 0.0, 0.0, 0.0)
        for x, y, z in corners:
            data += struct.pack("<3f", x, y, z)
        data += struct.pack("<H", 0)
    return bytes(data)


def stl_ascii() -> str:
    lines = ["solid cube"]
    for corners in stl_triangles():
        lines.append("  facet normal 0 0 0")
        lines.append("    outer loop")
        lines += [f"      vertex {x:g} {y:g} {z:g}" for x, y, z in corners]
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid cube")
    return "\n".join(lines) + "\n"


PLY_SQUARE = """ply
format ascii 1.0
comment a unit square
element vertex 4
property float x
property float y
property float z
element face 1
property list uchar int vertex_indices
end_header
0 0 0
1 0 0
1 1 0
0 1 0
4 0 1 2 3
"""

PLY_TRIANGLE = """ply
format ascii 1.0
element vertex 3
property float x
property float y
property float z
element face 1
property list uchar int vertex_indices
end_header
0 0 0
2 0 0
0 2 0
3 0 1 2
"""


def write(tmp_path, name, content):
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return str(path)


def test_mesh_formats():
    r = call(M.mesh_formats)
    assert r == {"ok": True, "formats": ["obj", "stl", "ply"]}


def test_obj_cube_scaled_rotated_and_contained(tmp_path):
    f, level = open_model()
    path = write(tmp_path, "cube.obj", obj_cube())
    r = call(M.import_mesh, path, level, json.dumps({"name": "SketchUp cube", "scale": 2, "rotation": 90}))
    assert r["ok"], r
    assert r["name"] == "SketchUp cube" and r["format"] == "obj"
    assert r["triangles"] == 12  # six quads, fanned
    assert r["bounds"] == {"min": [-2.0, 0.0, 0.0], "max": [0.0, 2.0, 2.0]}

    element = f.by_guid(r["guid"])
    assert element.is_a("IfcBuildingElementProxy")
    assert element.ObjectType == "Imported mesh" and element.Name == "SketchUp cube"
    assert ifcopenshell.util.element.get_container(element).GlobalId == level
    data = ifcopenshell.util.element.get_pset(element, M.PSET)
    assert data["Source"] == str(tmp_path.joinpath("cube.obj").resolve())
    assert data["Format"] == "obj"
    assert data["Triangles"] == 12
    assert data["Scale"] == pytest.approx(2.0)
    assert data["Rotation"] == pytest.approx(90.0)
    assert json.loads(data["Bounds"]) == r["bounds"]
    verts, faces = mesh(r["guid"])
    assert len(faces) == 12
    assert verts[:, 0].min() == pytest.approx(-2.0) and verts[:, 0].max() == pytest.approx(0.0)
    assert verts[:, 2].max() == pytest.approx(2.0)
    assert issues() == []


@pytest.mark.parametrize("kind", ["ascii", "binary"])
def test_stl_cube(tmp_path, kind):
    f, level = open_model()
    path = write(tmp_path, f"cube-{kind}.stl", stl_ascii() if kind == "ascii" else stl_binary())
    r = call(M.import_mesh, path, level)
    assert r["ok"], r
    assert r["format"] == "stl" and r["triangles"] == 12
    assert r["name"] == f"cube-{kind}"
    assert r["bounds"] == {"min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]}
    assert ifcopenshell.util.element.get_pset(f.by_guid(r["guid"]), M.PSET)["Format"] == "stl"
    assert issues() == []


def test_ascii_ply_square_is_fanned(tmp_path):
    f, level = open_model()
    path = write(tmp_path, "square.ply", PLY_SQUARE)
    r = call(M.import_mesh, path, level, json.dumps({"x": 1, "y": 2, "z": 3, "scale": 0.5}))
    assert r["ok"], r
    assert r["format"] == "ply" and r["triangles"] == 2
    assert r["bounds"] == {"min": [1.0, 2.0, 3.0], "max": [1.5, 2.5, 3.0]}
    element = f.by_guid(r["guid"])
    assert element.ObjectType == "Imported mesh"
    data = ifcopenshell.util.element.get_pset(element, M.PSET)
    assert data["Format"] == "ply" and data["Triangles"] == 2
    assert data["Scale"] == pytest.approx(0.5)
    assert issues() == []


def test_ascii_ply_triangle(tmp_path):
    _f, level = open_model()
    r = call(M.import_mesh, write(tmp_path, "triangle.ply", PLY_TRIANGLE), level)
    assert r["ok"], r
    assert r["triangles"] == 1
    assert r["bounds"] == {"min": [0.0, 0.0, 0.0], "max": [2.0, 2.0, 0.0]}
    assert issues() == []


def test_unknown_level_and_default_level(tmp_path):
    f, level = open_model()
    path = write(tmp_path, "triangle.ply", PLY_TRIANGLE)
    assert call(M.import_mesh, path, "no-such-level")["ok"] is False
    assert not f.by_type("IfcBuildingElementProxy")
    r = call(M.import_mesh, path)  # no level: the first storey
    assert r["ok"], r
    assert ifcopenshell.util.element.get_container(f.by_guid(r["guid"])).GlobalId == level


@pytest.mark.parametrize("name,content", [
    ("empty.obj", ""),
    ("empty.stl", ""),
    ("no-triangles.obj", "v 0 0 0\nv 1 0 0\nv 0 1 0\n"),
    ("bad-index.obj", "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 9\n"),
    ("bad-face.ply", PLY_SQUARE.replace("4 0 1 2 3", "2 0 1")),
    ("binary.ply", PLY_SQUARE.replace("format ascii 1.0", "format binary_little_endian 1.0")),
    ("broken.stl", "solid x\n  facet normal 0 0 0\n    outer loop\n      vertex 0 0 0\n"),
    ("notes.txt", "not a mesh"),
    ("mesh.fbx", "not supported"),
])
def test_bad_files_are_reported_not_raised(tmp_path, name, content):
    f, level = open_model()
    r = call(M.import_mesh, write(tmp_path, name, content), level)
    assert r["ok"] is False and r["error"]
    assert not f.by_type("IfcBuildingElementProxy")


def test_missing_file_and_bad_options(tmp_path):
    f, level = open_model()
    path = write(tmp_path, "triangle.ply", PLY_TRIANGLE)
    assert call(M.import_mesh, str(tmp_path / "absent.obj"), level)["ok"] is False
    assert call(M.import_mesh, "", level)["ok"] is False
    for options in ("not json", json.dumps({"scale": 0}), json.dumps({"scale": "big"}),
                    json.dumps({"rotation": "x"}), json.dumps({"x": "left"}), json.dumps([1, 2])):
        r = call(M.import_mesh, path, level, options)
        assert r["ok"] is False and r["error"], options
    assert not f.by_type("IfcBuildingElementProxy")


def test_saved_model_validates(tmp_path):
    f, level = open_model()
    assert call(M.import_mesh, write(tmp_path, "cube.obj", obj_cube()), level, json.dumps({"scale": 2}))["ok"]
    assert call(M.import_mesh, write(tmp_path, "cube.stl", stl_binary()), level)["ok"]
    assert call(M.import_mesh, write(tmp_path, "square.ply", PLY_SQUARE), level)["ok"]
    path = tmp_path / "meshes.ifc"
    f.write(str(path))
    written = ifcopenshell.open(str(path))
    assert written.schema_identifier == "IFC4"
    assert len(written.by_type("IfcBuildingElementProxy")) == 3
    assert issues(written) == []


def test_ifc2x3_uses_a_surface_model(tmp_path):
    try:
        f, level = open_model("IFC2X3")
        r = call(M.import_mesh, write(tmp_path, "cube.obj", obj_cube()), level)
        assert r["ok"], r
        element = f.by_guid(r["guid"])
        assert element.is_a("IfcBuildingElementProxy") and element.ObjectType == "Imported mesh"
        representation = ifcopenshell.util.representation.get_representation(
            element, "Model", "Body", "MODEL_VIEW")
        assert representation is not None
        assert representation.RepresentationType == "SurfaceModel"
        assert any(item.is_a("IfcShellBasedSurfaceModel") for item in representation.Items)
        assert ifcopenshell.util.element.get_pset(element, M.PSET)["Triangles"] == 12
        assert issues() == []
    finally:
        _reset_owner()  # the IFC2X3 owner callbacks are global


def test_agent_tools_are_registered():
    from kimbim.agent import catalogue
    from kimbim.agent.tools import imports  # noqa: F401  (registers import.mesh and import.formats)

    assert "import.mesh" in catalogue.TOOLS and catalogue.TOOLS["import.mesh"].writes
    assert "import.formats" in catalogue.TOOLS and not catalogue.TOOLS["import.formats"].writes
