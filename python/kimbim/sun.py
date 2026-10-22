# SPDX-License-Identifier: GPL-3.0-or-later
"""The sun (D96, Archicad's Sun settings): where it is for the 3D views' light and shadows.

Either given as an azimuth (degrees clockwise from true north) and an altitude (degrees above the
horizon), or worked out for a place, date and time (NOAA's solar position equations, good to well
under a degree). The model's true north turns it into plan directions.
"""
from __future__ import annotations

import datetime as dt
import json
import math

DEFAULT = {"mode": "custom", "azimuth": 135.0, "altitude": 40.0, "latitude": -34.9, "longitude": -56.2,
           "date": "2026-12-21", "time": "15:00", "utc_offset": -3.0}


def error(value) -> str | None:
    """Why a `sun` setting is not valid, or None."""
    if not isinstance(value, dict):
        return "the sun is a table: mode, azimuth, altitude or latitude, longitude, date, time, utc_offset"
    if value.get("mode", "custom") not in ("custom", "time"):
        return "the sun's mode is custom or time"
    for k, lo, hi in (("azimuth", -360, 360), ("altitude", 0, 90), ("latitude", -90, 90),
                      ("longitude", -180, 180), ("utc_offset", -14, 14)):
        if k in value and not (isinstance(value[k], (int, float)) and lo <= value[k] <= hi):
            return f"the sun's {k} must be a number from {lo} to {hi}"
    try:
        dt.date.fromisoformat(str(value.get("date", DEFAULT["date"])))
        dt.time.fromisoformat(str(value.get("time", DEFAULT["time"])))
    except ValueError:
        return "the sun's date is YYYY-MM-DD and its time HH:MM"
    return None


def position(latitude: float, longitude: float, when: dt.datetime, utc_offset: float) -> tuple[float, float]:
    """(azimuth clockwise from north, altitude) in degrees of the sun at a place and local time."""
    utc = when - dt.timedelta(hours=utc_offset)
    day = utc.timetuple().tm_yday
    hour = utc.hour + utc.minute / 60 + utc.second / 3600
    g = 2 * math.pi / 365 * (day - 1 + (hour - 12) / 24)  # the fractional year
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    solar_minutes = hour * 60 + eqtime + 4 * longitude
    ha = math.radians(solar_minutes / 4 - 180)
    lat = math.radians(latitude)
    cos_zenith = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(ha)
    zenith = math.acos(max(-1.0, min(1.0, cos_zenith)))
    altitude = 90 - math.degrees(zenith)
    azimuth = math.degrees(math.atan2(math.sin(ha), math.cos(ha) * math.sin(lat) - math.tan(decl) * math.cos(lat))) + 180
    return azimuth % 360, altitude


def sun(settings: dict | None = None) -> dict:
    """{azimuth, altitude, direction [x, y, z] (plan, towards the sun), up (above the horizon)} for
    the project's sun setting."""
    from . import settings as S
    from . import symbols

    st = {**DEFAULT, **((settings or S.current()).get("sun") or {})}
    if st["mode"] == "time":
        when = dt.datetime.combine(dt.date.fromisoformat(st["date"]), dt.time.fromisoformat(st["time"]))
        azimuth, altitude = position(float(st["latitude"]), float(st["longitude"]), when, float(st["utc_offset"]))
    else:
        azimuth, altitude = float(st["azimuth"]), float(st["altitude"])
    north = math.radians(symbols.true_north_angle())  # true north turned counter-clockwise from +Y
    bearing = math.radians(azimuth) - north  # clockwise from the plan's +Y
    alt = math.radians(max(altitude, 0.0))
    direction = [math.sin(bearing) * math.cos(alt), math.cos(bearing) * math.cos(alt), math.sin(alt)]
    return {"azimuth": round(azimuth, 3), "altitude": round(altitude, 3),
            "direction": [round(v, 9) for v in direction], "up": altitude > 0}


def sun_state() -> str:
    from . import app_bridge as B

    return B._dump({"ok": True, **sun()})
