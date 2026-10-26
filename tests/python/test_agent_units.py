# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent tools: unit parsing and EN/ES messages (D102)."""
import pytest

from kimbim.agent.messages import text
from kimbim.agent.units import apply_change, parse_angle, parse_length


def test_parse_length_units():
    assert parse_length("50cm") == pytest.approx(0.5)
    assert parse_length("500 mm") == pytest.approx(0.5)
    assert parse_length("1,2m") == pytest.approx(1.2)
    assert parse_length(2) == 2.0
    assert parse_length(2, "mm") == pytest.approx(0.002)


def test_apply_change():
    assert apply_change(1.2, "+50cm") == pytest.approx(1.7)
    assert apply_change(2.0, "-10%") == pytest.approx(1.8)
    assert apply_change(2.0, "0.9") == pytest.approx(0.9)


def test_bad_length_raises():
    with pytest.raises(ValueError, match="5 parsecs"):
        parse_length("5 parsecs")


def test_angle():
    assert parse_angle("90deg") == pytest.approx(90)
    assert parse_angle("3.14159rad") == pytest.approx(180, abs=0.01)
    assert parse_angle(45) == 45.0
    with pytest.raises(ValueError, match="abc"):
        parse_angle("abc")


def test_language_env(monkeypatch):
    monkeypatch.setenv("KIMBIM_LANG", "es")
    from kimbim.agent.messages import MESSAGES
    assert text("no_match") == MESSAGES["no_match"]["es"]
    monkeypatch.setenv("KIMBIM_LANG", "en")
    assert text("no_match") == MESSAGES["no_match"]["en"]
    assert text("nope_code") == "nope_code"
