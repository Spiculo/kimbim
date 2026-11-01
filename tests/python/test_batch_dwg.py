# SPDX-License-Identifier: GPL-3.0-or-later
"""Batch DWG publishing: sheets are written as DXF, then converted through LibreDWG."""
import json
import sys
from pathlib import Path

import pytest

from kimbim import app_bridge, dwg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import make_house  # noqa: E402

pytestmark = pytest.mark.skipif(not dwg.available(), reason="no DWG converter (pixi install -e dwg)")


def test_sheets_export_to_dwg_in_a_batch(tmp_path):
    ifc = tmp_path / "house.ifc"
    make_house.build(str(ifc))
    assert json.loads(app_bridge.open_model(str(ifc)))["ok"]
    added = json.loads(app_bridge.add_sheet("A3", "Details"))
    assert added["ok"], added
    numbers = ["A01", added["number"]]

    folder = tmp_path / "dwg"
    result = json.loads(app_bridge.export_dwg(json.dumps([{"sheet": n} for n in numbers]), str(folder)))
    assert result["ok"], result
    files = sorted(folder.glob("*.dwg"))
    assert len(files) == 2
    for path in files:
        data = path.read_bytes()
        assert len(data) > 100 and data[:2] == b"AC"  # a DWG header, not an empty DXF copy
