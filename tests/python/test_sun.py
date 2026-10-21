# SPDX-License-Identifier: GPL-3.0-or-later
"""D96: the sun for the 3D views (Archicad's Sun settings)."""
import datetime as dt
import json
import math

import pytest

from kimbim import app_bridge as b
from kimbim import sun as SUN


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def test_solar_position_matches_known_values():
    # Montevideo, 21 December 2026 at 13:00 local (UTC-3): the sun is high, to the north (southern summer)
    az, alt = SUN.position(-34.9, -56.2, dt.datetime(2026, 12, 21, 13, 0), -3.0)
    assert alt == pytest.approx(78, abs=2)
    # London at noon on the June solstice (UTC+1): high in the south
    az, alt = SUN.position(51.5, -0.13, dt.datetime(2026, 6, 21, 13, 0), 1.0)
    assert az == pytest.approx(180, abs=5) and alt == pytest.approx(62, abs=1.5)
    # the equator at an equinox's sunrise: due east, at the horizon
    az, alt = SUN.position(0.0, 0.0, dt.datetime(2026, 3, 20, 6, 7), 0.0)
    assert az == pytest.approx(90, abs=2) and alt == pytest.approx(0, abs=1.5)


def test_the_sun_setting_turns_with_true_north():
    assert call("new_project", "Sun")["ok"]
    assert call("set_project_settings", json.dumps({"sun": {"mode": "custom", "azimuth": 90, "altitude": 30}}))["ok"]
    s = call("sun_state")
    assert s["direction"] == pytest.approx([math.cos(math.radians(30)), 0.0, 0.5], abs=1e-9)  # due east
    assert call("set_project_settings", json.dumps({"sun": {"mode": "time", "latitude": 51.5, "longitude": -0.13,
                                                           "date": "2026-06-21", "time": "13:00", "utc_offset": 1}}))["ok"]
    s = call("sun_state")
    assert s["up"] and s["azimuth"] == pytest.approx(180, abs=5)
    assert not call("set_project_settings", json.dumps({"sun": {"altitude": 120}}))["ok"]
    assert not call("set_project_settings", json.dumps({"sun": {"mode": "time", "date": "21/06/2026"}}))["ok"]
