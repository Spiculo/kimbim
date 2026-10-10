# SPDX-License-Identifier: GPL-3.0-or-later
"""The object library (doc 14 §8, D86): furniture, sanitary, kitchen and site objects generated in
code, as Archicad's GDL library objects are: each object has parameters (width, depth, height and a
few of its own), a 3D body made of extrusions and a 2D plan symbol.

Objects become IFC types (IfcFurnitureType, IfcSanitaryTerminalType, IfcElectricApplianceType,
IfcGeographicElementType, IfcBuildingElementProxyType; IFC2X3 equivalents), one type per object and
parameter set (D50's type/occurrence pattern), so repeated placements share their geometry through
mapped items and schedules count them by type. The type carries two representation maps: Body
(Model/Body/MODEL_VIEW, swept solids) and the plan symbol (Plan/Annotation/PLAN_VIEW, an
IfcGeometricCurveSet), and the KIMCAD_LibraryObject property set (Object, Parameters as JSON in
metres, Library).

Object coordinates (metres): x along the width, y along the depth, z up from the level; the front
is the side at y = 0 (Archicad's convention), the origin its left front corner.

The office library (a folder set in the preferences) adds objects: Python files that call
`define(...)` like the bundled ones below, and IFC files whose types (with their representation
maps) are copied into the model when placed.

This module's object definitions are pure; the bridge functions import app_bridge when called.
"""
from __future__ import annotations

import json
import math
import os
import pathlib

PSET = "KIMCAD_LibraryObject"
CATEGORIES = (("furniture", "Furniture"), ("sanitary", "Sanitary"), ("kitchen", "Kitchen"),
              ("site", "People, trees and cars"), ("office", "Office library"))
CIRCLE_POINTS = 16  # ellipses and arcs in plan symbols and prism outlines


# ---------------------------------------------------------------- definitions

class Param:
    """A parameter: `kind` is "length" (metres) or "count" (a whole number)."""

    def __init__(self, key, label, default, kind="length", lo=None, hi=None):
        self.key, self.label, self.default, self.kind = key, label, default, kind
        self.lo = lo if lo is not None else (0.01 if kind == "length" else 1)
        self.hi = hi if hi is not None else (50.0 if kind == "length" else 20)

    def clean(self, value):
        v = float(value)
        if self.kind == "count":
            v = int(round(v))
        else:
            v = round(v, 4)
        return min(max(v, self.lo), self.hi)

    def listing(self) -> dict:
        return {"key": self.key, "label": self.label, "value": self.default, "kind": self.kind,
                "min": self.lo, "max": self.hi}


class Shape:
    """What a build function makes: solids (3D) and curves (the plan symbol), in object metres."""

    def __init__(self):
        self.solids, self.curves = [], []

    # 3D
    def box(self, x, y, z, dx, dy, dz):
        if dx > 1e-6 and dy > 1e-6 and dz > 1e-6:
            self.solids.append(("box", x, y, z, dx, dy, dz))

    def prism(self, points, z, dz):
        """A polygon (x, y) extruded up from z."""
        if dz > 1e-6 and len(points) >= 3:
            self.solids.append(("prism", [tuple(p) for p in points], z, dz))

    def cylinder(self, cx, cy, z, r, dz):
        if r > 1e-6 and dz > 1e-6:
            self.solids.append(("cylinder", cx, cy, z, r, dz))

    def side_prism(self, points, x, dx):
        """A polygon in the (y, z) plane extruded along x from x."""
        if dx > 1e-6 and len(points) >= 3:
            self.solids.append(("side", [tuple(p) for p in points], x, dx))

    def side_cylinder(self, cy, cz, x, r, dx):
        """A cylinder along x (wheels)."""
        if r > 1e-6 and dx > 1e-6:
            self.solids.append(("side_cylinder", cy, cz, x, r, dx))

    # plan symbol
    def line(self, *points, closed=False):
        pts = [tuple(p) for p in points]
        if closed:
            pts.append(pts[0])
        self.curves.append(("poly", pts))

    def rect(self, x, y, dx, dy):
        self.line((x, y), (x + dx, y), (x + dx, y + dy), (x, y + dy), closed=True)

    def circle(self, cx, cy, r):
        self.curves.append(("circle", cx, cy, r))

    def ellipse(self, cx, cy, rx, ry, a0=0.0, a1=2 * math.pi):
        closed = abs(a1 - a0 - 2 * math.pi) < 1e-9
        n = CIRCLE_POINTS if closed else max(4, int(CIRCLE_POINTS * abs(a1 - a0) / (2 * math.pi)) + 1)
        pts = ellipse_points(cx, cy, rx, ry, a0, a1, n, closed)
        self.line(*pts, closed=closed)


def ellipse_points(cx, cy, rx, ry, a0=0.0, a1=2 * math.pi, n=CIRCLE_POINTS, closed=True):
    count = n if closed else n
    step = (a1 - a0) / (n if closed else n - 1)
    return [(cx + rx * math.cos(a0 + i * step), cy + ry * math.sin(a0 + i * step)) for i in range(count)]


def rounded_rect(x, y, dx, dy, r, n=4):
    """A rectangle with rounded corners as a polygon (r clipped to fit)."""
    r = max(0.0, min(r, dx / 2 - 1e-4, dy / 2 - 1e-4))
    if r <= 1e-4:
        return [(x, y), (x + dx, y), (x + dx, y + dy), (x, y + dy)]
    pts = []
    for cx, cy, start in ((x + dx - r, y + r, -90), (x + dx - r, y + dy - r, 0), (x + r, y + dy - r, 90), (x + r, y + r, 180)):
        for i in range(n + 1):
            a = math.radians(start + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


class Obj:
    """A library object: `ifc` maps a schema family ("IFC4", "IFC2X3") to (type class, predefined
    type or None, element type text or None)."""

    def __init__(self, key, name, category, ifc, params, build, library="bundled"):
        self.key, self.name, self.category, self.ifc = key, name, category, ifc
        self.params, self.build, self.library = params, build, library

    def param(self, key_or_label: str):
        k = (key_or_label or "").strip().lower()
        return next((p for p in self.params if p.key == k or p.label.lower() == k), None)

    def values(self, given=None) -> dict:
        """All parameter values, defaults filled in and clamped."""
        given = given or {}
        out = {}
        for p in self.params:
            v = given.get(p.key, p.default)
            try:
                out[p.key] = p.clean(v)
            except (TypeError, ValueError):
                out[p.key] = p.clean(p.default)
        return out

    def shape(self, values) -> Shape:
        s = Shape()
        self.build(s, dict(values))
        return s

    def type_name(self, values) -> str:
        mm = lambda v: str(int(round(v * 1000)))  # noqa: E731
        name = f"{self.name} {'x'.join(mm(values[k]) for k in ('width', 'depth', 'height') if k in values)}"
        extra = [f"{p.label} {values[p.key] if p.kind == 'count' else mm(values[p.key])}"
                 for p in self.params if p.key not in ("width", "depth", "height") and values[p.key] != p.clean(p.default)]
        return name + (f" ({', '.join(extra)})" if extra else "")

    def ifc_for(self, schema: str):
        return self.ifc.get("IFC2X3" if schema == "IFC2X3" else "IFC4") or self.ifc["IFC4"]


OBJECTS: dict = {}


def define(key, name, category, ifc, params, build, library="bundled"):
    """Add an object to the library (the office library's Python files call this too)."""
    if isinstance(ifc, (tuple, list)):
        ifc = {"IFC4": tuple(ifc)}
    OBJECTS[key] = Obj(key, name, category, dict(ifc), list(params), build, library)
    return OBJECTS[key]


W = lambda d=1.0: Param("width", "Width", d)  # noqa: E731
D = lambda d=1.0: Param("depth", "Depth", d)  # noqa: E731
H = lambda d=1.0: Param("height", "Height", d)  # noqa: E731
FURNITURE = lambda pre, element=None: {  # noqa: E731
    "IFC4": ("IfcFurnitureType", pre, element),
    "IFC2X3": ("IfcFurnitureType", None, element or pre.title())}
SANITARY = lambda pre: {"IFC4": ("IfcSanitaryTerminalType", pre, None)}  # noqa: E731
APPLIANCE = lambda pre: {"IFC4": ("IfcElectricApplianceType", pre, None)}  # noqa: E731
PROXY = lambda element: {"IFC4": ("IfcBuildingElementProxyType", "USERDEFINED", element),  # noqa: E731
                         "IFC2X3": ("IfcBuildingElementProxyType", "USERDEFINED", element)}


# ---------------------------------------------------------------- furniture

def _legs(s, w, d, h, leg, inset=0.03):
    for x in (inset, w - inset - leg):
        for y in (inset, d - inset - leg):
            s.box(x, y, 0, leg, leg, h)


def _table(s, p):
    w, d, h, top = p["width"], p["depth"], p["height"], 0.04
    _legs(s, w, d, h - top, 0.06)
    s.box(0, 0, h - top, w, d, top)
    s.rect(0, 0, w, d)


def _chair(s, p):
    w, d, h, seat = p["width"], p["depth"], p["height"], p["seat"]
    _legs(s, w, d, seat - 0.04, 0.04, 0.0)
    s.box(0, 0, seat - 0.04, w, d, 0.04)
    s.box(0, d - 0.04, seat, w, 0.04, max(h - seat, 0.01))
    s.rect(0, 0, w, d)
    s.line((0, d - 0.04), (w, d - 0.04))


def _sofa(s, p):
    w, d, h, n = p["width"], p["depth"], p["height"], p["seats"]
    arm, back, seat = 0.15, 0.2, 0.42
    s.box(0, 0, 0, arm, d, h * 0.75)
    s.box(w - arm, 0, 0, arm, d, h * 0.75)
    s.box(arm, d - back, 0, w - 2 * arm, back, h)
    s.box(arm, 0, 0, w - 2 * arm, d - back, seat)
    s.rect(0, 0, w, d)
    s.line((arm, 0), (arm, d))
    s.line((w - arm, 0), (w - arm, d))
    s.line((arm, d - back), (w - arm, d - back))
    for i in range(1, n):
        x = arm + (w - 2 * arm) * i / n
        s.line((x, 0.05), (x, d - back))


def _bed(pillows):
    def build(s, p):
        w, d, h = p["width"], p["depth"], p["height"]
        head = 0.05
        s.box(0, 0, 0.1, w, d - head, h - 0.1)
        for x in (0.02, w - 0.07):
            for y in (0.02, d - head - 0.07):
                s.box(x, y, 0, 0.05, 0.05, 0.1)
        s.box(0, d - head, 0, w, head, h + 0.4)
        s.rect(0, 0, w, d)
        s.line((0, d - head), (w, d - head))
        pw = (w - 0.1 * (pillows + 1)) / pillows
        for i in range(pillows):
            x = 0.1 + i * (pw + 0.1)
            s.line(*rounded_rect(x, d - head - 0.45, pw, 0.35, 0.06, 2), closed=True)
        fold = d * 0.62
        s.line((0, fold), (w, fold))  # the turned-down sheet
        s.line((0, fold), (w * 0.25, fold - 0.18), (w, fold - 0.18))
    return build


def _wardrobe(s, p):
    w, d, h, doors = p["width"], p["depth"], p["height"], p["doors"]
    s.box(0, 0, 0, w, d, h)
    s.rect(0, 0, w, d)
    s.line((0, 0.02), (w, 0.02))
    s.line((0.03, d / 2), (w - 0.03, d / 2))  # hanging rail
    for i in range(1, int(w / 0.15)):
        x = i * 0.15
        s.line((x - 0.04, d / 2 - 0.2), (x + 0.04, d / 2 + 0.2))  # hangers
    for i in range(1, doors):
        s.line((w * i / doors, 0), (w * i / doors, 0.02))


def _desk(s, p):
    w, d, h, top, side = p["width"], p["depth"], p["height"], 0.03, 0.025
    s.box(0, 0.05, 0, side, d - 0.05, h - top)
    s.box(w - side, 0.05, 0, side, d - 0.05, h - top)
    s.box(side, d - 0.03, 0.3, w - 2 * side, 0.02, h - top - 0.3)
    s.box(0, 0, h - top, w, d, top)
    s.rect(0, 0, w, d)


def _shelf(s, p):
    w, d, h, n, t = p["width"], p["depth"], p["height"], p["shelves"], 0.02
    s.box(0, 0, 0, t, d, h)
    s.box(w - t, 0, 0, t, d, h)
    s.box(t, d - 0.01, 0, w - 2 * t, 0.01, h)
    for i in range(n):
        z = 0.05 + (h - 0.05 - t) * i / max(n - 1, 1)
        s.box(t, 0, z, w - 2 * t, d - 0.01, t)
    s.rect(0, 0, w, d)
    s.line((0, 0), (w, d))


define("table", "Table", "furniture", FURNITURE("TABLE"), [W(1.6), D(0.9), H(0.75)], _table)
define("chair", "Chair", "furniture", FURNITURE("CHAIR"),
       [W(0.45), D(0.5), H(0.85), Param("seat", "Seat height", 0.45)], _chair)
define("sofa", "Sofa", "furniture", FURNITURE("SOFA"),
       [W(2.0), D(0.9), H(0.8), Param("seats", "Seats", 3, "count", 1, 6)], _sofa)
define("bed_single", "Single bed", "furniture", FURNITURE("BED"), [W(0.9), D(2.0), H(0.5)], _bed(1))
define("bed_double", "Double bed", "furniture", FURNITURE("BED"), [W(1.6), D(2.0), H(0.5)], _bed(2))
define("wardrobe", "Wardrobe", "furniture", FURNITURE("USERDEFINED", "WARDROBE"),
       [W(1.2), D(0.6), H(2.2), Param("doors", "Doors", 2, "count", 1, 8)], _wardrobe)
define("desk", "Desk", "furniture", FURNITURE("DESK"), [W(1.4), D(0.7), H(0.75)], _desk)
define("shelf", "Shelf", "furniture", FURNITURE("SHELF"),
       [W(0.9), D(0.35), H(2.0), Param("shelves", "Shelves", 5, "count", 2, 12)], _shelf)


# ---------------------------------------------------------------- sanitary

def _wc(s, p):
    w, d, h = p["width"], p["depth"], p["height"]
    tank = min(0.18, d * 0.3)
    s.box(0, d - tank, 0, w, tank, h + 0.4)
    bowl = ellipse_points(w / 2, (d - tank) / 2 + 0.02, w / 2, (d - tank) / 2 + 0.02, n=12)
    s.prism(bowl, 0, h)
    s.rect(0, d - tank, w, tank)
    s.ellipse(w / 2, (d - tank) / 2 + 0.02, w / 2, (d - tank) / 2 + 0.02)
    s.ellipse(w / 2, (d - tank) / 2 + 0.04, w / 2 - 0.06, (d - tank) / 2 - 0.06)


def _washbasin(s, p):
    w, d, h = p["width"], p["depth"], p["height"]
    outline = rounded_rect(0, 0, w, d, min(w, d) * 0.3)
    s.prism(outline, h - 0.18, 0.18)
    s.box(w / 2 - 0.09, d - 0.2, 0, 0.18, 0.18, h - 0.18)  # pedestal
    s.line(*outline, closed=True)
    s.ellipse(w / 2, d * 0.45, w / 2 - 0.07, d * 0.45 - 0.05)
    s.circle(w / 2, d - 0.06, 0.02)


def _bathtub(s, p):
    w, d, h, t = p["width"], p["depth"], p["height"], 0.06
    s.box(0, 0, 0, w, d, 0.06)
    s.box(0, 0, 0.06, w, t, h - 0.06)
    s.box(0, d - t, 0.06, w, t, h - 0.06)
    s.box(0, t, 0.06, t, d - 2 * t, h - 0.06)
    s.box(w - t, t, 0.06, t, d - 2 * t, h - 0.06)
    s.rect(0, 0, w, d)
    s.line(*rounded_rect(t, t, w - 2 * t, d - 2 * t, (d - 2 * t) * 0.45), closed=True)
    s.circle(w - 0.2, d / 2, 0.03)


def _shower(s, p):
    w, d, h = p["width"], p["depth"], p["height"]
    s.box(0, 0, 0, w, d, h)
    s.rect(0, 0, w, d)
    s.line((0, 0), (w, d))
    s.line((w, 0), (0, d))
    s.circle(w / 2, d / 2, 0.04)


def _bidet(s, p):
    w, d, h = p["width"], p["depth"], p["height"]
    s.box(0, d - 0.08, 0, w, 0.08, h)
    s.prism(ellipse_points(w / 2, (d - 0.08) / 2 + 0.02, w / 2, (d - 0.08) / 2 + 0.02, n=12), 0, h)
    s.rect(0, d - 0.08, w, 0.08)
    s.ellipse(w / 2, (d - 0.08) / 2 + 0.02, w / 2, (d - 0.08) / 2 + 0.02)
    s.ellipse(w / 2, (d - 0.08) / 2 + 0.03, w / 2 - 0.06, (d - 0.08) / 2 - 0.06)
    s.circle(w / 2, d - 0.12, 0.015)


define("wc", "WC", "sanitary", SANITARY("TOILETPAN"), [W(0.38), D(0.7), H(0.4)], _wc)
define("washbasin", "Washbasin", "sanitary", SANITARY("WASHHANDBASIN"), [W(0.6), D(0.45), H(0.85)], _washbasin)
define("bathtub", "Bathtub", "sanitary", SANITARY("BATH"), [W(1.7), D(0.75), H(0.55)], _bathtub)
define("shower_tray", "Shower tray", "sanitary", SANITARY("SHOWER"), [W(0.9), D(0.9), H(0.05)], _shower)
define("bidet", "Bidet", "sanitary", SANITARY("BIDET"), [W(0.38), D(0.55), H(0.4)], _bidet)


# ---------------------------------------------------------------- kitchen

def _cabinets(s, w, d, h, units, counter=0.04, plinth=0.1):
    s.box(0, 0.05, 0, w, d - 0.05, plinth)
    s.box(0, 0.02, plinth, w, d - 0.02, h - counter - plinth)
    s.box(0, 0, h - counter, w, d, counter)
    s.rect(0, 0, w, d)
    for i in range(1, units):
        x = w * i / units
        s.line((x, 0), (x, 0.08))  # the doors' joints along the front


def _base_cabinets(s, p):
    _cabinets(s, p["width"], p["depth"], p["height"], p["units"])


def _wall_cabinets(s, p):
    w, d, h, z, units = p["width"], p["depth"], p["height"], p["elevation"], p["units"]
    s.box(0, 0, z, w, d, h)
    s.rect(0, 0, w, d)
    s.line((0, 0), (w, d))  # above the plan cut: crossed, as drawn by hand
    s.line((w, 0), (0, d))
    for i in range(1, units):
        s.line((w * i / units, 0), (w * i / units, d))


def _sink_unit(s, p):
    w, d, h, bowls = p["width"], p["depth"], p["height"], p["bowls"]
    _cabinets(s, w, d, h, max(1, round(w / 0.6)))
    bw = min(0.4, (w * 0.6 - 0.05 * (bowls + 1)) / bowls)
    for i in range(bowls):
        x = 0.08 + i * (bw + 0.05)
        s.line(*rounded_rect(x, 0.1, bw, d - 0.2, 0.05, 2), closed=True)
        s.circle(x + bw / 2, d / 2, 0.025)
    drainer = 0.08 + bowls * (bw + 0.05) + 0.03
    for k in range(4):  # the drainer's grooves
        y = 0.15 + (d - 0.3) * k / 3
        s.line((drainer, y), (w - 0.08, y))
    s.circle(0.08 + bowls * (bw + 0.05) / 2, d - 0.06, 0.02)


def _fridge(s, p):
    w, d, h = p["width"], p["depth"], p["height"]
    s.box(0, 0.04, 0, w, d - 0.04, h)
    s.box(0, 0, 0.05, w, 0.04, h - 0.05)
    s.rect(0, 0, w, d)
    s.line((0, 0.04), (w, 0.04))
    s.line((0, 0.04), (w, d))


def _cooker(s, p):
    w, d, h, burners = p["width"], p["depth"], p["height"], p["burners"]
    s.box(0, 0.02, 0, w, d - 0.02, h - 0.01)
    s.box(0.03, 0.05, h - 0.01, w - 0.06, d - 0.1, 0.01)
    s.rect(0, 0, w, d)
    s.rect(0.03, 0.05, w - 0.06, d - 0.1)
    cols = 1 if burners == 1 else 2
    rows = max(1, math.ceil(burners / cols))
    r = min((w - 0.12) / (2 * cols), (d - 0.16) / (2 * rows)) * 0.75
    k = 0
    for row in range(rows):
        for col in range(cols):
            if k < burners:
                s.circle(0.06 + (w - 0.12) * (col + 0.5) / cols, 0.08 + (d - 0.16) * (row + 0.5) / rows, r)
                k += 1


KITCHEN_FURNITURE = FURNITURE("USERDEFINED", "KITCHENCABINET")
define("base_cabinets", "Base cabinets", "kitchen", KITCHEN_FURNITURE,
       [W(2.4), D(0.6), H(0.9), Param("units", "Units", 4, "count", 1, 12)], _base_cabinets)
define("wall_cabinets", "Wall cabinets", "kitchen", KITCHEN_FURNITURE,
       [W(1.2), D(0.35), H(0.7), Param("elevation", "Elevation", 1.45, "length", 0.0, 3.0),
        Param("units", "Units", 2, "count", 1, 12)], _wall_cabinets)
define("sink_unit", "Sink unit", "kitchen", SANITARY("SINK"),
       [W(1.2), D(0.6), H(0.9), Param("bowls", "Bowls", 1, "count", 1, 2)], _sink_unit)
define("fridge", "Fridge", "kitchen", APPLIANCE("FRIDGE_FREEZER"), [W(0.6), D(0.65), H(1.85)], _fridge)
define("cooker", "Cooktop and oven", "kitchen", APPLIANCE("ELECTRICCOOKER"),
       [W(0.6), D(0.6), H(0.9), Param("burners", "Burners", 4, "count", 1, 6)], _cooker)


# ---------------------------------------------------------------- people, trees and cars

def _person(s, p):
    w, d, h = p["width"], p["depth"], p["height"]
    leg = h * 0.47
    s.box(w * 0.2, d * 0.25, 0, w * 0.25, d * 0.5, leg)
    s.box(w * 0.55, d * 0.25, 0, w * 0.25, d * 0.5, leg)
    s.prism(ellipse_points(w / 2, d / 2, w / 2, d / 2, n=8), leg, h * 0.36)
    s.cylinder(w / 2, d / 2, leg + h * 0.38, h * 0.065, h * 0.15)
    s.ellipse(w / 2, d / 2, w / 2, d / 2)
    s.circle(w / 2, d / 2, h * 0.065)


def _tree(s, p):
    crown, h, trunk = p["width"], p["height"], p["trunk"]
    c = crown / 2
    s.cylinder(c, c, 0, trunk / 2, h * 0.45)
    for i, (z, r) in enumerate(((0.3, 0.8), (0.5, 1.0), (0.7, 0.75), (0.85, 0.4))):
        s.prism(ellipse_points(c, c, c * r, c * r, n=10), h * z, h * (0.2 if i < 3 else 0.15))
    s.circle(c, c, c)
    s.circle(c, c, trunk / 2)
    for k in range(8):  # the classic star of branches
        a = 2 * math.pi * k / 8
        s.line((c + trunk / 2 * math.cos(a), c + trunk / 2 * math.sin(a)), (c + c * 0.7 * math.cos(a), c + c * 0.7 * math.sin(a)))


def _car(s, p):
    w, d, h = p["width"], p["depth"], p["height"]  # the car is `depth` long, front at y = 0
    wheel = 0.32
    for y in (d * 0.18, d * 0.78):
        for x in (0.05, w - 0.25):
            s.side_cylinder(y, wheel, x, wheel, 0.2)
    s.box(0, 0, 0.25, w, d, max(h * 0.55 - 0.25, 0.1))
    cabin = [(d * 0.3, h * 0.55), (d * 0.85, h * 0.55), (d * 0.75, h), (d * 0.42, h)]
    s.side_prism(cabin, 0.1, w - 0.2)
    s.line(*rounded_rect(0, 0, w, d, 0.3, 3), closed=True)
    s.line((0.1, d * 0.3), (w - 0.1, d * 0.3))  # windscreen
    s.line((0.1, d * 0.42), (w - 0.1, d * 0.42))
    s.line((0.1, d * 0.75), (w - 0.1, d * 0.75))  # rear window
    s.line((0.1, d * 0.85), (w - 0.1, d * 0.85))


define("person", "Person", "site", PROXY("PERSON"), [W(0.5), D(0.3), H(1.75)], _person)
define("tree", "Tree", "site",
       {"IFC4": ("IfcGeographicElementType", "USERDEFINED", "TREE"),
        "IFC2X3": ("IfcBuildingElementProxyType", "USERDEFINED", "TREE")},
       [Param("width", "Crown diameter", 4.0), H(6.0), Param("trunk", "Trunk diameter", 0.3)], _tree)
define("car", "Car", "site", PROXY("CAR"), [W(1.8), D(4.5), H(1.5)], _car)


def footprint(obj: Obj, values: dict) -> tuple[float, float]:
    """Width and depth (metres) of an object's plan box."""
    w = values.get("width", 1.0)
    return w, values.get("depth", w)


# ---------------------------------------------------------------- office library

_office: dict = {}  # key -> Obj or IFC type entry {"path", "guid", "name", "ifc_class"}
_office_paths = {"folder": "", "files": []}
_office_errors: list = []
_ifc_cache: dict = {}  # path -> (mtime, ifcopenshell.file)


def _open_library_ifc(path: str):
    import ifcopenshell

    mtime = os.path.getmtime(path)
    cached = _ifc_cache.get(path)
    if cached is None or cached[0] != mtime:
        cached = (mtime, ifcopenshell.open(path))
        _ifc_cache[path] = cached
    return cached[1]


def _load_ifc_types(path: str, category: str):
    f = _open_library_ifc(path)
    for t in f.by_type("IfcTypeProduct"):
        if t.is_a("IfcDoorType") or t.is_a("IfcWindowType") or not getattr(t, "RepresentationMaps", None):
            continue  # doors and windows go in walls; types without a shape place nothing
        key = f"ifc:{path}::{t.GlobalId}"
        _office[key] = {"path": path, "guid": t.GlobalId, "name": t.Name or t.is_a(), "ifc_class": t.is_a(),
                        "category": category}


def load_office(folder: str = "", files=()) -> None:
    """(Re)load the office library: *.py files that call define(), and *.ifc files' types."""
    _office.clear()
    _office_errors.clear()
    _office_paths["folder"], _office_paths["files"] = folder or "", list(files or ())
    paths = []
    if folder and os.path.isdir(folder):
        paths += sorted(str(p) for p in pathlib.Path(folder).iterdir() if p.suffix.lower() in (".py", ".ifc"))
    paths += [p for p in files or () if p not in paths]
    for path in paths:
        try:
            if path.lower().endswith(".py"):
                before = set(OBJECTS)
                namespace = {"define": define, "Param": Param, "W": W, "D": D, "H": H, "FURNITURE": FURNITURE,
                             "SANITARY": SANITARY, "APPLIANCE": APPLIANCE, "PROXY": PROXY, "math": math,
                             "rounded_rect": rounded_rect, "ellipse_points": ellipse_points, "__file__": path}
                code = pathlib.Path(path).read_text(encoding="utf-8")
                exec(compile(code, path, "exec"), namespace)  # the office's own object scripts (like GDL)
                for key in set(OBJECTS) - before:
                    OBJECTS[key].category, OBJECTS[key].library = "office", path
                    _office[key] = OBJECTS.pop(key)
            elif os.path.isfile(path):
                _load_ifc_types(path, "office")
        except Exception as ex:  # a broken file must not break the library
            _office_errors.append({"file": path, "error": f"{type(ex).__name__}: {ex}"})


def get(key: str):
    """The object definition (Obj) or an office IFC type entry (dict), or None."""
    return OBJECTS.get(key) or _office.get(key)


# ---------------------------------------------------------------- listing (the Library panel)

def _symbol(shape: Shape) -> list:
    """The plan symbol as polylines (object metres), circles tessellated."""
    out = []
    for c in shape.curves:
        if c[0] == "poly":
            out.append([[round(x, 4), round(y, 4)] for x, y in c[1]])
        else:
            _, cx, cy, r = c
            pts = ellipse_points(cx, cy, r, r, n=24)
            out.append([[round(x, 4), round(y, 4)] for x, y in pts + pts[:1]])
    return out


def _listing(obj: Obj) -> dict:
    values = obj.values()
    w, d = footprint(obj, values)
    return {"id": obj.key, "name": obj.name, "category": obj.category, "ifc_class": obj.ifc["IFC4"][0],
            "params": [p.listing() for p in obj.params], "symbol": _symbol(obj.shape(values)),
            "width": w, "depth": d, "height": values.get("height", 1.0), "library": obj.library}


def library_objects() -> str:
    from . import app_bridge as B

    objects = [_listing(o) for o in OBJECTS.values()]
    for key, entry in _office.items():
        if isinstance(entry, Obj):
            item = _listing(entry)
            item["id"] = key
        else:
            item = {"id": key, "name": entry["name"], "category": entry["category"], "ifc_class": entry["ifc_class"],
                    "params": [], "symbol": [], "width": 1.0, "depth": 1.0, "height": 1.0, "library": entry["path"]}
        objects.append(item)
    return B._dump({"categories": [{"id": k, "name": n} for k, n in CATEGORIES], "objects": objects,
                    "office": dict(_office_paths), "errors": list(_office_errors)})


def object_symbol(key: str, params_json: str = "") -> str:
    """The plan symbol and plan box of an object with these parameters (the panel's thumbnail)."""
    from . import app_bridge as B

    obj = get(key)
    if not isinstance(obj, Obj):
        return B._dump({"symbol": [], "width": 1.0, "depth": 1.0})
    try:
        given = json.loads(params_json) if params_json else {}
    except ValueError:
        given = {}
    values = obj.values(given)
    w, d = footprint(obj, values)
    return B._dump({"symbol": _symbol(obj.shape(values)), "width": w, "depth": d, "params": values})


def set_library_paths(data: str) -> str:
    """The office library: {"folder": path, "files": [IFC or .py files]} (from the preferences)."""
    from . import app_bridge as B

    try:
        d = json.loads(data or "{}")
    except ValueError as ex:
        return B._dump({"ok": False, "error": str(ex)})
    load_office(d.get("folder", ""), d.get("files", []))
    return B._dump({"ok": True, "objects": len(_office), "errors": list(_office_errors)})


# ---------------------------------------------------------------- IFC (needs a model)

def _schema_family(f) -> str:
    return "IFC2X3" if f.schema == "IFC2X3" else "IFC4"


class _Writer:
    """Writes a Shape as IFC items in the model's length unit."""

    def __init__(self, f, unit_scale):
        self.f, self.k = f, 1.0 / unit_scale
        self.z = f.createIfcDirection((0.0, 0.0, 1.0))
        self.x = f.createIfcDirection((1.0, 0.0, 0.0))
        self.y = f.createIfcDirection((0.0, 1.0, 0.0))

    def p2(self, x, y):
        return self.f.createIfcCartesianPoint((float(x) * self.k, float(y) * self.k))

    def p3(self, x, y, z):
        return self.f.createIfcCartesianPoint((float(x) * self.k, float(y) * self.k, float(z) * self.k))

    def a2(self, x=0.0, y=0.0):
        return self.f.createIfcAxis2Placement2D(self.p2(x, y), None)

    def polyline2(self, pts):
        return self.f.createIfcPolyline([self.p2(x, y) for x, y in pts])

    def extrude(self, profile, position, depth):
        return self.f.createIfcExtrudedAreaSolid(profile, position, self.z, float(depth) * self.k)

    def solid(self, s):
        f, kind = self.f, s[0]
        if kind == "box":
            _, x, y, z, dx, dy, dz = s
            profile = f.createIfcRectangleProfileDef("AREA", None, self.a2(x + dx / 2, y + dy / 2), dx * self.k, dy * self.k)
            return self.extrude(profile, f.createIfcAxis2Placement3D(self.p3(0, 0, z), None, None), dz)
        if kind == "cylinder":
            _, cx, cy, z, r, dz = s
            profile = f.createIfcCircleProfileDef("AREA", None, self.a2(cx, cy), r * self.k)
            return self.extrude(profile, f.createIfcAxis2Placement3D(self.p3(0, 0, z), None, None), dz)
        if kind == "prism":
            _, pts, z, dz = s
            profile = f.createIfcArbitraryClosedProfileDef("AREA", None, self.polyline2(list(pts) + [pts[0]]))
            return self.extrude(profile, f.createIfcAxis2Placement3D(self.p3(0, 0, z), None, None), dz)
        # profiles in the (y, z) plane extruded along x: local X = world Y, local Z = world X
        position = f.createIfcAxis2Placement3D(self.p3(s[-2] if kind == "side" else s[3], 0, 0), self.x, self.y)
        if kind == "side":
            _, pts, x, dx = s
            profile = f.createIfcArbitraryClosedProfileDef("AREA", None, self.polyline2(list(pts) + [pts[0]]))
            return self.extrude(profile, position, dx)
        _, cy, cz, x, r, dx = s  # side_cylinder
        profile = f.createIfcCircleProfileDef("AREA", None, self.a2(cy, cz), r * self.k)
        return self.extrude(profile, position, dx)

    def curve(self, c):
        if c[0] == "poly":
            return self.polyline2(c[1])
        _, cx, cy, r = c
        return self.f.createIfcCircle(self.a2(cx, cy), r * self.k)


def _contexts():
    from . import annotations, authoring

    return authoring._body_context(), annotations._context()


def _representations(obj: Obj, values: dict):
    """(body, plan) IfcShapeRepresentations for the object with these values."""
    import ifcopenshell.util.unit

    from . import app_bridge as B

    f = B._model
    shape = obj.shape(values)
    writer = _Writer(f, ifcopenshell.util.unit.calculate_unit_scale(f))
    body_context, plan_context = _contexts()
    body = f.createIfcShapeRepresentation(body_context, "Body", "SweptSolid", [writer.solid(s) for s in shape.solids])
    plan = None
    if shape.curves:
        curve_set = f.createIfcGeometricCurveSet([writer.curve(c) for c in shape.curves])
        plan = f.createIfcShapeRepresentation(plan_context, "Annotation", "Annotation2D", [curve_set])
    return body, plan


def _params_of_type(t) -> tuple[str, dict] | None:
    """(object key, parameter values) of a library type, or None."""
    import ifcopenshell.util.element

    data = ifcopenshell.util.element.get_pset(t, PSET) if t is not None else None
    if not data or not data.get("Object"):
        return None
    try:
        values = json.loads(data.get("Parameters") or "{}")
    except ValueError:
        values = {}
    return data["Object"], values


def _library_types(f):
    out = []
    for t in f.by_type("IfcTypeProduct"):
        if any(getattr(ps, "Name", None) == PSET for ps in (getattr(t, "HasPropertySets", None) or ())):
            out.append(t)
    return out


def _find_type(f, key: str, values: dict):
    for t in _library_types(f):
        info = _params_of_type(t)
        if info is not None and info[0] == key and info[1] == values:
            return t
    return None


def _set_predefined(t, predefined, element):
    if predefined and hasattr(t, "PredefinedType"):
        t.PredefinedType = predefined
    if element and (predefined in (None, "USERDEFINED") or not hasattr(t, "PredefinedType")):
        t.ElementType = element
    if hasattr(t, "AssemblyPlace") and t.AssemblyPlace is None:
        t.AssemblyPlace = "NOTDEFINED"


def _write_pset(t, key, values, library):
    import ifcopenshell.api.pset

    from . import app_bridge as B

    f = B._model
    ps = next((p for p in (t.HasPropertySets or ()) if p.Name == PSET), None) or \
        ifcopenshell.api.pset.add_pset(f, product=t, name=PSET)
    ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={
        "Object": key, "Parameters": json.dumps(values, sort_keys=True), "Library": library})


def _make_type(obj: Obj, values: dict):
    import ifcopenshell.api.geometry
    import ifcopenshell.api.root

    from . import app_bridge as B

    f = B._model
    type_class, predefined, element = obj.ifc_for(f.schema)
    t = ifcopenshell.api.root.create_entity(f, ifc_class=type_class, name=obj.type_name(values))
    _set_predefined(t, predefined, element)
    body, plan = _representations(obj, values)
    ifcopenshell.api.geometry.assign_representation(f, product=t, representation=body)
    if plan is not None:
        ifcopenshell.api.geometry.assign_representation(f, product=t, representation=plan)
    _write_pset(t, obj.key, values, obj.library)
    return t


def _type_for(obj: Obj, values: dict):
    from . import app_bridge as B

    return _find_type(B._model, obj.key, values) or _make_type(obj, values)


def _ifc_type(entry: dict):
    """The office IFC type copied into the model (once: placing it again reuses it)."""
    import ifcopenshell.api.project

    from . import app_bridge as B

    f = B._model
    try:
        return f.by_guid(entry["guid"])
    except RuntimeError:
        pass
    library = _open_library_ifc(entry["path"])
    t = ifcopenshell.api.project.append_asset(f, library=library, element=library.by_guid(entry["guid"]))
    _write_pset(t, f"ifc:{entry['guid']}", {}, entry["path"])
    return t


def _remove_type_if_unused(t) -> None:
    """A library type nothing uses any more goes, with its geometry (keeps files small)."""
    import ifcopenshell.api.root
    import ifcopenshell.util.element

    from . import app_bridge as B

    if t is None or not t.id() or ifcopenshell.util.element.get_types(t):
        return
    if _params_of_type(t) is None or str(_params_of_type(t)[0]).startswith("ifc:"):
        return  # only types the library generated
    ifcopenshell.api.root.remove_product(B._model, product=t)


def _occurrence_class(type_class: str, schema: str) -> str:
    import ifcopenshell.util.type

    names = ifcopenshell.util.type.get_applicable_entities(type_class, schema=schema)
    decl = __import__("ifcopenshell").schema_by_name(schema)
    for name in names:
        try:
            if not decl.declaration_by_name(name).is_abstract():
                return name
        except RuntimeError:
            continue
    return "IfcBuildingElementProxy"


def _scale() -> float:
    import ifcopenshell.util.unit

    from . import app_bridge as B

    return ifcopenshell.util.unit.calculate_unit_scale(B._model)


def place_object(storey_guid: str, key: str, params_json: str, x, y, angle=0.0) -> str:
    """Place a library object on a level: its origin (left front corner) at (x, y) metres, turned
    `angle` radians. The type with these parameters is reused, or made. One undo step."""
    import ifcopenshell.api.geometry
    import ifcopenshell.api.root
    import ifcopenshell.api.spatial
    import ifcopenshell.api.type
    import numpy as np

    from . import app_bridge as B
    from . import authoring as A
    from . import layers, renovation

    if B._model is None:
        return A._fail("no model open")
    storey = A._by_guid(storey_guid)
    if storey is None or not storey.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    obj = get(key)
    if obj is None:
        return A._fail(f"no library object {key}")
    try:
        given = json.loads(params_json) if params_json else {}
        x, y, angle = float(x), float(y), float(angle or 0.0)
    except (TypeError, ValueError) as ex:
        return A._fail(str(ex))
    values = obj.values(given) if isinstance(obj, Obj) else {}
    made = {}

    def action():
        f = B._model
        t = _type_for(obj, values) if isinstance(obj, Obj) else _ifc_type(obj)
        element = ifcopenshell.api.root.create_entity(f, ifc_class=_occurrence_class(t.is_a(), f.schema),
                                                      name=obj.name if isinstance(obj, Obj) else (t.Name or ""))
        ifcopenshell.api.type.assign_type(f, related_objects=[element], relating_type=t)
        c, s = math.cos(angle), math.sin(angle)
        matrix = np.array([[c, -s, 0, x], [s, c, 0, y], [0, 0, 1, A._elevation(storey)], [0, 0, 0, 1]], dtype=float)
        ifcopenshell.api.geometry.edit_object_placement(f, product=element, matrix=matrix, is_si=True)
        ifcopenshell.api.spatial.assign_container(f, products=[element], relating_structure=storey)
        layers.assign_active(element)
        renovation.stamp_new(element)
        made["element"], made["type"] = element, t
        return 1, [element.GlobalId], []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "guid": made["element"].GlobalId, "type": made["type"].GlobalId})


def _object_of(e):
    """(Obj, values, type) of a placed library object, or None."""
    import ifcopenshell.util.element

    t = ifcopenshell.util.element.get_type(e)
    info = _params_of_type(t)
    if info is None or info[0] not in OBJECTS and info[0] not in _office:
        return None
    obj = get(info[0])
    if not isinstance(obj, Obj):
        return None
    return obj, obj.values(info[1]), t


def parameters_of(elements) -> list:
    """The Properties panel's Parameters group: [(label, value, kind)] per element (lists)."""
    out = []
    for e in elements:
        found = _object_of(e)
        if found is None:
            out.append(None)
            continue
        obj, values, _ = found
        out.append([(p.label, values[p.key], p.kind) for p in obj.params])
    return out


def is_object(e) -> bool:
    return _object_of(e) is not None


def _regenerate_type(t, obj: Obj, values: dict) -> None:
    """New geometry for a type in place: every placement of it follows (mapped items)."""
    import ifcopenshell.util.element

    from . import app_bridge as B

    f = B._model
    body, plan = _representations(obj, values)
    for rep_map in t.RepresentationMaps or ():
        old = rep_map.MappedRepresentation
        new = body if old.RepresentationIdentifier == "Body" else plan
        if new is None:
            continue
        old_items = list(old.Items)
        old.Items = new.Items
        old.RepresentationType = new.RepresentationType
        f.remove(new)
        for item in old_items:
            ifcopenshell.util.element.remove_deep2(f, item)
    for unused in (body, plan):
        if unused is not None and unused.id() and not unused.OfProductRepresentation and not unused.RepresentationMap:
            try:
                f.remove(unused)
            except RuntimeError:
                pass
    t.Name = obj.type_name(values)
    _write_pset(t, obj.key, values, obj.library)


def set_object_parameter(guids_json: str, name: str, value) -> str:
    """Change a parameter of the selected library objects. If they are every placement of their
    type, the type changes in place (keeping its GlobalId); otherwise only the selected ones move to
    the type with the new value (found or made) and the others keep theirs. One undo step."""
    import ifcopenshell.api.type
    import ifcopenshell.util.element

    from . import app_bridge as B
    from . import authoring as A

    if B._model is None:
        return A._fail("no model open")
    groups: dict = {}
    for e in B._elements(guids_json):
        found = _object_of(e)
        if found is None:
            continue
        obj, values, t = found
        p = obj.param(name)
        if p is None:
            continue
        try:
            v = float(str(value).strip().replace(",", "."))
        except ValueError:
            return A._fail(f"not a number: {value}")
        if p.kind == "length" and v <= 0:
            return A._fail(f"{p.label} must be more than 0")
        new_values = dict(values)
        new_values[p.key] = p.clean(v)
        groups.setdefault(t.id(), (t, obj, new_values, []))[3].append(e)
    if not groups:
        return A._fail(f"no selected object has a parameter {name}")

    def action():
        f = B._model
        changed = []
        for t, obj, new_values, elements in groups.values():
            everyone = set(ifcopenshell.util.element.get_types(t))
            if everyone <= set(elements) and _find_type(f, obj.key, new_values) is None:
                _regenerate_type(t, obj, new_values)
                changed += [o.GlobalId for o in everyone]
            else:
                target = _type_for(obj, new_values)
                ifcopenshell.api.type.assign_type(f, related_objects=elements, relating_type=target)
                _remove_type_if_unused(t)
                changed += [e.GlobalId for e in elements]
        return len(changed), changed, []

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump(r)
