# SPDX-License-Identifier: GPL-3.0-or-later
"""Free work plane: a user height independent of the active level, kept in project settings."""
import json

from kimbim import app_bridge, settings


def test_work_plane_height_is_independent_and_persisted():
    settings.load(dict(settings.DEFAULTS))
    assert json.loads(app_bridge.work_plane()) == {"ok": True, "enabled": False, "z": 0.0, "angle": 0.0}

    enabled = json.loads(app_bridge.set_work_plane("2.75", "true", "0.5"))
    assert enabled["ok"] and enabled["z"] == 2.75 and enabled["angle"] == 0.5
    state = json.loads(app_bridge.work_plane())
    assert state["enabled"] and state["z"] == 2.75 and state["angle"] == 0.5

    # Disabling keeps the chosen height and rotation for the next use.
    assert json.loads(app_bridge.set_work_plane("2.75", "false", "0.5"))["ok"]
    off = json.loads(app_bridge.work_plane())
    assert not off["enabled"] and off["z"] == 2.75 and off["angle"] == 0.5

    assert json.loads(app_bridge.set_work_plane("not a number", "true"))["ok"] is False
