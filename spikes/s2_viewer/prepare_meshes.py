# SPDX-License-Identifier: GPL-3.0-or-later
"""Spike S2 (viewer half), step 1: tessellate an IFC model into per-element meshes (.npz).

Uses the hybrid CGAL/OCCT kernel (D38) in world coordinates, so the viewer needs no transforms.
Usage: python prepare_meshes.py <model.ifc> <out.npz>
"""
import multiprocessing
import sys
import time

import ifcopenshell
import ifcopenshell.geom
import numpy as np


def main(src, dst):
    t0 = time.perf_counter()
    f = ifcopenshell.open(src)
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    it = ifcopenshell.geom.iterator(s, f, multiprocessing.cpu_count(), geometry_library="hybrid-cgal-simple-opencascade")
    verts, tris, voff, toff, guids, types = [], [], [0], [0], [], []
    if it.initialize():
        while True:
            sh = it.get()
            v = np.asarray(sh.geometry.verts, dtype=np.float32).reshape(-1, 3)
            t = np.asarray(sh.geometry.faces, dtype=np.int32).reshape(-1, 3)
            if len(t):
                verts.append(v)
                tris.append(t)
                voff.append(voff[-1] + len(v))
                toff.append(toff[-1] + len(t))
                guids.append(sh.guid)
                types.append(sh.type)
            if not it.next():
                break
    np.savez(
        dst,
        verts=np.concatenate(verts),
        tris=np.concatenate(tris),
        voff=np.asarray(voff, dtype=np.int64),
        toff=np.asarray(toff, dtype=np.int64),
        guids=np.asarray(guids),
        types=np.asarray(types),
    )
    print(f"{len(guids)} elements, {toff[-1]:,} triangles, {voff[-1]:,} vertices in {time.perf_counter() - t0:.1f}s -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
