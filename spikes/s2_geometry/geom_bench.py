"""Spike S2 (geometry half): tessellation throughput of the IfcOpenShell geometry iterator.

Rendering performance (OCCT AIS viewer) needs the M0 Qt app; this measures the CPU side that
feeds it: time to triangulate every element, triangle counts, and peak memory.

Usage:
  python geom_bench.py synth 100000      # generate a synthetic model with N walls (10% with openings)
  python geom_bench.py <file.ifc> [...]  # benchmark files
"""
import multiprocessing
import os
import pathlib
import sys
import time

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import ifcopenshell.geom
import psutil

HERE = pathlib.Path(__file__).parent


def synth(n: int) -> pathlib.Path:
    """N walls on a grid, 10% with a window opening (boolean subtraction)."""
    out = HERE / "out" / f"synth-{n}.ifc"
    out.parent.mkdir(exist_ok=True)
    if out.exists():
        return out
    f = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="Synthetic")
    ifcopenshell.api.unit.assign_unit(f)
    model = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model)
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite")
    building = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding")
    storey = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(f, products=[storey], relating_object=building)
    side = int(n ** 0.5) + 1
    walls = []
    t = time.perf_counter()
    for i in range(n):
        w = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name=f"W{i}")
        rep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=4.0, height=3.0, thickness=0.2)
        ifcopenshell.api.geometry.assign_representation(f, product=w, representation=rep)
        x, y = (i % side) * 5.0, (i // side) * 1.0
        m = [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, 0], [0, 0, 0, 1]]
        ifcopenshell.api.geometry.edit_object_placement(f, product=w, matrix=m, is_si=True)
        walls.append(w)
        if i % 10 == 0:
            o = ifcopenshell.api.root.create_entity(f, ifc_class="IfcOpeningElement")
            orep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=1.0, height=1.2, thickness=0.4)
            ifcopenshell.api.geometry.assign_representation(f, product=o, representation=orep)
            mo = [[1, 0, 0, x + 1.5], [0, 1, 0, y - 0.1], [0, 0, 1, 0.9], [0, 0, 0, 1]]
            ifcopenshell.api.geometry.edit_object_placement(f, product=o, matrix=mo, is_si=True)
            ifcopenshell.api.feature.add_feature(f, feature=o, element=w)
        if (i + 1) % 10000 == 0:
            print(f"  generated {i + 1} walls ({time.perf_counter() - t:.0f}s)", flush=True)
    ifcopenshell.api.spatial.assign_container(f, products=walls, relating_structure=storey)
    f.write(str(out))
    return out


def bench(path: pathlib.Path):
    proc = psutil.Process()
    t0 = time.perf_counter()
    f = ifcopenshell.open(str(path))
    t1 = time.perf_counter()
    rss_open = proc.memory_info().rss
    settings = ifcopenshell.geom.settings()
    threads = multiprocessing.cpu_count()
    kernel = os.environ.get("KIMBIM_KERNEL", "hybrid-cgal-simple-opencascade")
    it = ifcopenshell.geom.iterator(settings, f, threads, geometry_library=kernel)
    elements = tris = 0
    peak = rss_open
    t2 = time.perf_counter()
    if it.initialize():
        while True:
            shape = it.get()
            elements += 1
            tris += len(shape.geometry.faces) // 3
            if elements % 2000 == 0:
                peak = max(peak, proc.memory_info().rss)
            if not it.next():
                break
    t3 = time.perf_counter()
    peak = max(peak, proc.memory_info().rss)
    print(
        f"{path.name}: {len(f.by_type('IfcProduct'))} products, {elements} tessellated, {tris:,} triangles | "
        f"open {t1 - t0:.1f}s, tessellate {t3 - t2:.1f}s on {threads} threads, {kernel} "
        f"({elements / max(t3 - t2, 1e-9):,.0f} elem/s) | RSS after open {rss_open / 1e6:.0f} MB, peak {peak / 1e6:.0f} MB",
        flush=True,
    )


if __name__ == "__main__":
    if sys.argv[1] == "synth":
        p = synth(int(sys.argv[2]))
        bench(p)
    else:
        for a in sys.argv[1:]:
            bench(pathlib.Path(a))
