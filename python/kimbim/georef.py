# SPDX-License-Identifier: GPL-3.0-or-later
"""Georeferencing (doc 14 §1): the project's map conversion and true north.

IFC stores the survey point and the project's rotation on an ``IfcMapConversion`` whose
``TargetCRS`` is an ``IfcProjectedCRS``; true north is a direction on the geometric
representation context. Same protocol as app_bridge (strings in, JSON out, never raise).
"""
from __future__ import annotations

import json
import math

import ifcopenshell.api.georeference

from . import app_bridge as B


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def _conversion():
    return next(iter(B._model.by_type("IfcMapConversion")), None)


def _true_north_degrees() -> float | None:
    for ctx in B._model.by_type("IfcGeometricRepresentationContext"):
        direction = getattr(ctx, "TrueNorth", None)
        if direction is not None and direction.DirectionRatios:
            x, y = (list(direction.DirectionRatios) + [0.0, 0.0])[:2]
            # ifcopenshell stores true north as a direction rotated from +Y: 0 is up.
            angle = (math.degrees(math.atan2(y, x)) - 90.0 + 180.0) % 360.0 - 180.0
            return round(angle, 6)
    return None


def _state() -> dict:
    conversion = _conversion()
    crs = conversion.TargetCRS if conversion is not None else next(iter(B._model.by_type("IfcProjectedCRS")), None)
    return {
        "ok": True,
        "eastings": float(conversion.Eastings or 0.0) if conversion is not None else 0.0,
        "northings": float(conversion.Northings or 0.0) if conversion is not None else 0.0,
        "height": float(conversion.OrthogonalHeight or 0.0) if conversion is not None else 0.0,
        "rotation": round(math.degrees(math.atan2(float(conversion.XAxisOrdinate or 0.0),
                                                  float(conversion.XAxisAbscissa or 1.0))), 6)
        if conversion is not None else 0.0,
        "scale": float(conversion.Scale or 1.0) if conversion is not None else 1.0,
        "crs": {
            "name": (crs.Name or "") if crs is not None else "",
            "description": (crs.Description or "") if crs is not None else "",
            "geodetic_datum": (crs.GeodeticDatum or "") if crs is not None else "",
            "vertical_datum": (crs.VerticalDatum or "") if crs is not None else "",
            "map_projection": (crs.MapProjection or "") if crs is not None else "",
            "map_zone": (crs.MapZone or "") if crs is not None else "",
        },
        "true_north": _true_north_degrees(),
        "georeferenced": conversion is not None or crs is not None,
    }


def georef_state() -> str:
    """The project's map conversion (eastings, northings, height, rotation, scale), CRS and true north."""
    if B._model is None:
        return _fail("no model open")
    try:
        return B._dump(_state())
    except Exception as ex:  # noqa: BLE001  (never raise through the bridge)
        return _fail(f"{type(ex).__name__}: {ex}")


def set_georeferencing(values_json: str) -> str:
    """Set the map conversion, CRS and true north. Any key may be omitted; empty strings clear CRS text.

    Keys: eastings, northings, height, rotation (degrees clockwise from grid north), scale,
    true_north (degrees), crs_name, crs_description, geodetic_datum, vertical_datum,
    map_projection, map_zone.
    """
    if B._model is None:
        return _fail("no model open")
    try:
        values = json.loads(values_json or "{}")
        if not isinstance(values, dict):
            raise ValueError("expected an object")
        numbers = {}
        for key in ("eastings", "northings", "height", "rotation", "scale", "true_north"):
            if key in values and values[key] not in (None, ""):
                numbers[key] = float(values[key])
    except (TypeError, ValueError) as ex:
        return _fail(f"bad values: {ex}")

    def action():
        f = B._model
        if _conversion() is None:
            ifcopenshell.api.georeference.add_georeferencing(f, name=str(values.get("crs_name") or "EPSG:3857"))
        operation = {}
        for key, ifc_key in (("eastings", "Eastings"), ("northings", "Northings"),
                             ("height", "OrthogonalHeight"), ("scale", "Scale")):
            if key in numbers:
                operation[ifc_key] = numbers[key]
        if "rotation" in numbers:
            angle = math.radians(numbers["rotation"])
            operation["XAxisAbscissa"] = math.cos(angle)
            operation["XAxisOrdinate"] = math.sin(angle)
        crs = {}
        for key, ifc_key in (("crs_name", "Name"), ("crs_description", "Description"),
                             ("geodetic_datum", "GeodeticDatum"), ("vertical_datum", "VerticalDatum"),
                             ("map_projection", "MapProjection"), ("map_zone", "MapZone")):
            if key in values:
                crs[ifc_key] = str(values[key]) if values[key] not in (None, "") else None
        if operation or crs:
            ifcopenshell.api.georeference.edit_georeferencing(
                f, coordinate_operation=operation or None, projected_crs=crs or None)
        if "true_north" in numbers:
            ifcopenshell.api.georeference.edit_true_north(f, numbers["true_north"])
        return 1

    try:
        B._run(action)
        return B._dump(_state())
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")


def clear_georeferencing() -> str:
    """Remove the map conversion and projected CRS (true north stays)."""
    if B._model is None:
        return _fail("no model open")
    if _conversion() is None and not B._model.by_type("IfcProjectedCRS"):
        return B._dump({"ok": True, "removed": 0, "state": _state()})

    def action():
        ifcopenshell.api.georeference.remove_georeferencing(B._model)
        return 1

    try:
        B._run(action)
        return B._dump({"ok": True, "removed": 1, "state": _state()})
    except Exception as ex:  # noqa: BLE001
        return _fail(f"{type(ex).__name__}: {ex}")
