# SPDX-License-Identifier: GPL-3.0-or-later
"""Spike S6: IfcOpenShell's SVG serializer on KimBim files — quality and speed (Slice 14 risk check).

For an IFC file it adds drawing definitions the way Bonsai does (an IfcAnnotation with ObjectType
DRAWING: placement = camera, Body = IfcBlock giving width x height x depth, EPset_Drawing.Scale),
then generates each drawing with `elevation-ref-guid` and times the stages:

  - plan of the storey holding the most elements (cut 1.2 m above it, 1.5 m deep, only its elements)
  - a section through the middle of the building, looking north
  - the south elevation

Usage: python drawing_bench.py FILE.ifc OUTDIR [--slow-hlr] [--all-elements]
FILE may be a bare file name; it is then looked up under tests/corpus/files (pixi run fetch-corpus).
Writes OUTDIR/<name>.svg and prints one line per drawing (also as JSON at the end).
--slow-hlr: OpenCASCADE's exact HLR instead of the polygon HLR (svg-poly).
--all-elements: give the serializer every element instead of pre-filtering plans by storey.
"""
from __future__ import annotations

import json
import multiprocessing
import sys
import time
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.representation
import ifcopenshell.util.unit
import numpy as np

W = ifcopenshell.ifcopenshell_wrapper
SKIP = ("IfcOpeningElement", "IfcSpace", "IfcAnnotation", "IfcGrid", "IfcVirtualElement")


def products(f):
    return [p for p in f.by_type("IfcProduct") if p.Representation and not any(p.is_a(c) for c in SKIP)]


def bounds(f, prods):
    """World bounding box of the products' placements (metres), padded. Cheap; good enough here."""
    unit = ifcopenshell.util.unit.calculate_unit_scale(f)
    pts = np.array([ifcopenshell.util.placement.get_local_placement(p.ObjectPlacement)[:3, 3] * unit
                    for p in prods if p.ObjectPlacement])
    return pts.min(axis=0) - 3.0, pts.max(axis=0) + 3.0


def add_drawing(f, name, origin, z, x, size, target_view):
    """Camera at origin (metres), looking along -z, x to the right; size = (w, h, depth) in metres."""
    unit = ifcopenshell.util.unit.calculate_unit_scale(f)
    model = ifcopenshell.util.representation.get_context(f, "Model")
    body = ifcopenshell.util.representation.get_context(f, "Model", "Body", "MODEL_VIEW") or \
        ifcopenshell.api.run("context.add_context", f, context_type="Model", context_identifier="Body",
                             target_view="MODEL_VIEW", parent=model)
    cam = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcAnnotation", name=name)
    cam.ObjectType = "DRAWING"
    z, x = np.array(z, float), np.array(x, float)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, np.cross(z, x), z, np.array(origin) / unit
    ifcopenshell.api.run("geometry.edit_object_placement", f, product=cam, matrix=m, is_si=False)
    w, h, d = (v / unit for v in size)
    block = f.createIfcBlock(f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((-w / 2, -h / 2, -d))), w, h, d)
    rep = f.createIfcShapeRepresentation(body, "Body", "CSG", [f.createIfcCsgSolid(block)])
    ifcopenshell.api.run("geometry.assign_representation", f, product=cam, representation=rep)
    pset = ifcopenshell.api.run("pset.add_pset", f, product=cam, name="EPset_Drawing")
    ifcopenshell.api.run("pset.edit_pset", f, pset=pset, properties={"TargetView": target_view, "Scale": "1/100"})
    return cam


def generate(f, cam, prods, slow_hlr):
    s = ifcopenshell.geom.settings(ELEMENT_HIERARCHY=True)
    for k, v in (("dimensionality", W.CURVES_SURFACES_AND_SOLIDS), ("iterator-output", W.NATIVE),
                 ("apply-default-materials", True), ("elevation-ref-guid", cam.GlobalId),
                 ("svg-without-storeys", True), ("svg-write-poly", True), ("svg-xmlns", True),
                 ("svg-project", True), ("bounds", "1189x841"), ("scale", "0.01"), ("door-arcs", True),
                 ("svg-poly", not slow_hlr), ("svg-prefilter", True), ("svg-unify-inputs", slow_hlr)):
        s.set(k, v)
    buf = W.buffer()
    ser = ifcopenshell.geom.serializers.svg(buf, s)
    ser.setFile(f)
    t0 = time.perf_counter()
    elements = list(ifcopenshell.geom.iterator(s, f, multiprocessing.cpu_count(), include=prods + [cam]))
    t1 = time.perf_counter()
    for e in elements:
        ser.write(e)
    t2 = time.perf_counter()
    ser.finalize()
    t3 = time.perf_counter()
    return buf.get_value(), {"elements": len(elements), "geometry_s": round(t1 - t0, 2),
                             "write_s": round(t2 - t1, 2), "hlr_s": round(t3 - t2, 2), "total_s": round(t3 - t0, 2)}


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    if not src.exists():
        corpus = Path(__file__).resolve().parents[2] / "tests" / "corpus" / "files"
        src = next(corpus.rglob(src.name), src)
    slow_hlr, all_elements = "--slow-hlr" in sys.argv, "--all-elements" in sys.argv
    out.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    f = ifcopenshell.open(str(src))
    prods = products(f)
    lo, hi = bounds(f, prods)
    mid, size = (lo + hi) / 2, hi - lo
    by_storey = {}
    for p in prods:
        container = ifcopenshell.util.element.get_container(p)
        if container is not None and container.is_a("IfcBuildingStorey"):
            by_storey.setdefault(container, []).append(p)
    storey = max(by_storey, key=lambda s: len(by_storey[s]), default=None)
    unit = ifcopenshell.util.unit.calculate_unit_scale(f)
    z0 = (storey.Elevation or 0.0) * unit if storey else lo[2]
    results = {"file": src.name, "products": len(prods), "open_s": round(time.perf_counter() - t, 2),
               "plan_storey": storey.Name if storey else None}
    plan_prods = prods if all_elements or storey is None else by_storey[storey]
    jobs = [
        ("plan", (mid[0], mid[1], z0 + 1.2), (0, 0, 1), (1, 0, 0), (size[0], size[1], 1.5), "PLAN_VIEW", plan_prods),
        ("section", (mid[0], mid[1], mid[2]), (0, -1, 0), (1, 0, 0), (size[0], size[2], size[1] / 2 + 3), "SECTION_VIEW", prods),
        ("elevation", (mid[0], lo[1], mid[2]), (0, -1, 0), (1, 0, 0), (size[0], size[2], size[1] + 3), "ELEVATION_VIEW", prods),
    ]
    for name, origin, z, x, sz, view, these in jobs:
        cam = add_drawing(f, f"S6 {name}", origin, z, x, sz, view)
        svg, timing = generate(f, cam, these, slow_hlr)
        (out / f"{name}.svg").write_text(svg)
        results[name] = timing
        print(name, timing, flush=True)
    print(json.dumps(results))


if __name__ == "__main__":
    main()
