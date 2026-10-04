# SPDX-License-Identifier: GPL-3.0-or-later
"""Spike S2 (viewer half), step 2: OCCT AIS viewer performance on per-element meshes.

Displays meshes from prepare_meshes.py in OCCT's interactive viewer (AIS/V3d, OpenGL) inside a
Qt window, then measures load time, orbit frame time, pick (hover) latency and memory.

Layouts:
  per-element : one AIS_Shape (mesh-only face) per IFC element -> simplest selection model
  batched     : elements merged into batches of N -> far fewer interactive objects

Usage: python view_bench.py <meshes.npz> <per-element|batched> [limit] [batch=1000] [window|offscreen]

window    : on-screen Qt window; frames are capped by vsync (what a user sees, max ~60 fps)
offscreen : FBO rendering with a full pixel read-back per frame, so GPU work is complete and
            vsync does not apply (an upper bound on the true frame cost)
Writes a JSON line with the results to stdout.
"""
import json
import os
import math
import random
import sys
import time

import numpy as np
import psutil
from OCC.Core.AIS import AIS_Shape, AIS_Shaded
from OCC.Core.BRep import BRep_Builder
from OCC.Core.gp import gp_Pnt
from OCC.Core.Poly import Poly_Triangle, Poly_Triangulation
from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCC.Core.TopoDS import TopoDS_Face
from OCC.Core.Graphic3d import Graphic3d_TOSM_FRAGMENT
from OCC.Display.OCCViewer import Viewer3d
from OCC.Display.SimpleGui import init_display

FRAMES = 120
PICKS = 100


def make_face(v: np.ndarray, t: np.ndarray) -> TopoDS_Face:
    tri = Poly_Triangulation(len(v), len(t), False)
    for i, (x, y, z) in enumerate(v.tolist(), 1):
        tri.SetNode(i, gp_Pnt(x, y, z))
    for j, (a, b, c) in enumerate(t.tolist(), 1):
        tri.SetTriangle(j, Poly_Triangle(a + 1, b + 1, c + 1))
    face = TopoDS_Face()
    BRep_Builder().MakeFace(face, tri)
    return face


def groups(d, layout, limit, batch):
    n = min(limit, len(d["voff"]) - 1)
    size = 1 if layout == "per-element" else batch
    for start in range(0, n, size):
        end = min(n, start + size)
        v0, v1 = d["voff"][start], d["voff"][end]
        t0, t1 = d["toff"][start], d["toff"][end]
        v = d["verts"][v0:v1]
        t = d["tris"][t0:t1].copy()
        # re-base element-local indices to the batch: each element's indices start at its own vertex offset
        for k in range(start, end):
            a, b = d["toff"][k] - t0, d["toff"][k + 1] - t0
            t[a:b] += d["voff"][k] - v0
        yield v, t, end - start


def main():
    path, layout = sys.argv[1], sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9
    batch = int(sys.argv[4]) if len(sys.argv) > 4 else 1000
    mode = sys.argv[5] if len(sys.argv) > 5 else "window"
    d = dict(np.load(path))
    proc = psutil.Process()
    rss0 = proc.memory_info().rss

    w, h = 1280, 800
    if mode == "offscreen":
        display = Viewer3d()
        display.InitOffscreen(w, h)
        display.Viewer.SetDefaultLights()
        display.Viewer.SetLightOn()
        display.View.SetShadingModel(Graphic3d_TOSM_FRAGMENT)
    else:
        display, _, _, _ = init_display("pyside6", size=(w, h), display_triedron=False)
    ctx, view = display.Context, display.View
    res = {"file": path, "layout": layout, "mode": mode}

    def frame():
        view.Redraw()
        if mode == "offscreen":
            pass  # Redraw waits for the buffer swap (vsync is on in pythonocc), so the GPU work is complete

    t = time.perf_counter()
    objects = elements = triangles = 0
    color = Quantity_Color(0.75, 0.72, 0.68, Quantity_TOC_RGB)
    for v, tr, k in groups(d, layout, limit, batch):
        ais = AIS_Shape(make_face(v, tr))
        ais.SetColor(color)
        ctx.Display(ais, AIS_Shaded, 0, False)
        objects += 1
        elements += k
        triangles += len(tr)
    res["build_and_display_s"] = round(time.perf_counter() - t, 2)
    res.update(objects=objects, elements=elements, triangles=triangles)

    t = time.perf_counter()
    display.FitAll()
    view.Redraw()
    res["first_frame_s"] = round(time.perf_counter() - t, 2)
    res["rss_mb"] = round((proc.memory_info().rss - rss0) / 1e6)

    # Orbit: move the eye around the model and redraw synchronously.
    cam = view.Camera()
    center, eye = cam.Center(), cam.Eye()
    dx, dy, dz = eye.X() - center.X(), eye.Y() - center.Y(), eye.Z() - center.Z()
    r = math.hypot(dx, dy)
    a0 = math.atan2(dy, dx)
    times = []
    for i in range(FRAMES):
        a = a0 + 2 * math.pi * i / FRAMES
        cam.SetEye(gp_Pnt(center.X() + r * math.cos(a), center.Y() + r * math.sin(a), center.Z() + dz))
        f0 = time.perf_counter()
        frame()
        times.append(time.perf_counter() - f0)
    times.sort()
    res["frame_ms_median"] = round(1000 * times[len(times) // 2], 1)
    res["frame_ms_p95"] = round(1000 * times[int(len(times) * 0.95)], 1)
    res["fps_median"] = round(1 / times[len(times) // 2], 1)

    # Pick: detection under random pixels (what hovering does), without redrawing, so this is the
    # selection cost alone; the highlight redraw costs about one frame on top.
    random.seed(1)
    picks, hits = [], 0
    for _ in range(PICKS):
        x, y = random.randint(0, w - 1), random.randint(0, h - 1)
        p0 = time.perf_counter()
        ctx.MoveTo(x, y, view, False)
        picks.append(time.perf_counter() - p0)
        hits += ctx.HasDetected()
    picks.sort()
    res["pick_ms_median"] = round(1000 * picks[len(picks) // 2], 1)
    res["pick_ms_p95"] = round(1000 * picks[int(len(picks) * 0.95)], 1)
    res["pick_hits"] = hits
    res["rss_after_mb"] = round((proc.memory_info().rss - rss0) / 1e6)
    print(json.dumps(res), flush=True)
    os._exit(0)  # skip Qt teardown; results are printed


if __name__ == "__main__":
    main()
