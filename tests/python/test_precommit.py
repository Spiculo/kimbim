# SPDX-License-Identifier: GPL-3.0-or-later
"""M6: pre-commit checks run on Save version; a blocking check stops it and a warning check's result
is recorded with the version (checks.json in its tree)."""
import json

import pytest

from kimbim import app_bridge as b


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def g(*guids):
    return json.dumps(list(guids))


def precommit(*entries):
    return call("set_project_settings", json.dumps({"precommit_checks": list(entries)}))


@pytest.fixture
def versioned(tmp_path):
    """A versioned project with two identical walls (the model check finds a duplicate)."""
    assert call("new_project", "Pre-commit")["ok"]
    level = call("storeys")["storeys"][0]["guid"]
    wall_type = call("wall_types")["types"][0]["guid"]
    first = call("create_wall", level, wall_type, 0, 0, 5, 0, 3.0, "", "")["guid"]
    second = call("create_wall", level, wall_type, 0, 0, 5, 0, 3.0, "", "")["guid"]
    folder = tmp_path / "project"
    assert call("enable_versioning", str(folder), "Initial import")["ok"]
    return {"level": level, "type": wall_type, "walls": [first, second]}


def test_a_blocking_check_stops_the_save(versioned):
    assert precommit({"check": "model", "mode": "block", "options": {"model_checks": ["duplicates"]}})["ok"]
    call("set_name", g(versioned["walls"][0]), "Muro sur")
    r = call("save_version", "Rename the south wall")
    assert not r["ok"] and r["blocked"]
    assert "model checks" in r["error"].lower()
    checks = r["checks"]
    assert len(checks) == 1 and checks[0]["check"] == "model" and checks[0]["mode"] == "block"
    assert checks[0]["failed"] and checks[0]["total"] >= 1
    assert checks[0]["issues"][0]["guids"]
    # Nothing was committed.
    assert [v["message"] for v in call("history", 10)["versions"]] == ["Initial import"]


def test_a_warning_check_saves_and_records_its_result(versioned):
    assert precommit({"check": "model", "mode": "warn", "options": {"model_checks": ["duplicates"]}})["ok"]
    call("set_name", g(versioned["walls"][0]), "Muro sur")
    r = call("save_version", "Duplicates left for later")
    assert r["ok"], r
    assert r["checks"][0]["failed"] is True

    recorded = call("version_checks")
    assert recorded["ok"] and recorded["time"]
    found = recorded["checks"][0]
    assert found["check"] == "model" and found["mode"] == "warn" and found["failed"]
    assert found["total"] >= 1 and found["issues"][0]["guids"]

    # The record travels with the version, not with the working model.
    first = call("history", 10)["versions"][-1]["id"]
    assert call("version_checks", first)["checks"] == []


def test_a_passing_blocking_check_lets_the_save_through(versioned):
    call("delete_elements", g(versioned["walls"][1]))
    assert precommit({"check": "model", "mode": "block", "options": {"model_checks": ["duplicates"]}})["ok"]
    call("set_name", g(versioned["walls"][0]), "Muro sur")
    r = call("save_version", "One wall fewer")
    assert r["ok"], r
    assert r["checks"][0]["failed"] is False
    assert call("version_checks")["checks"][0]["total"] == 0


def test_precommit_entries_are_validated(versioned):
    assert not precommit({"check": "nope", "mode": "warn"})["ok"]
    assert not precommit({"check": "model", "mode": "sometimes"})["ok"]
    assert not precommit({"check": "model", "mode": "warn"}, {"check": "model", "mode": "block"})["ok"]
    assert not call("set_project_settings", json.dumps({"precommit_checks": {"check": "model"}}))["ok"]
