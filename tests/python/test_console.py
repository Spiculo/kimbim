# SPDX-License-Identifier: GPL-3.0-or-later
"""The Python console (D82): namespace helpers, edit() as one undo step, select round trip, Stop."""
import json
import threading
import time

import pytest
from conftest import build_model

from kimbim import app_bridge, console


def call(fn, *args):
    return json.loads(getattr(app_bridge, fn)(*args))


def run(code, selection=()):
    return call("console_run", code, json.dumps(list(selection)))


@pytest.fixture
def opened(tmp_path):
    f = build_model(walls=3)
    path = tmp_path / "console.ifc"
    f.write(str(path))
    assert call("open_model", str(path))["ok"]
    console.reset()
    return [w.GlobalId for w in f.by_type("IfcWall")]


def test_expression_value_and_print_are_shown(opened):
    r = run('print("hello")\nlen(ifc.by_type("IfcWall"))')
    assert r["ok"] and not r["error"]
    assert r["output"] == "hello\n3\n"
    assert not r["edited"] and r["select"] is None


def test_namespace_persists_between_runs(opened):
    run("x = 41")
    assert run("x + 1")["output"] == "42\n"


def test_traceback_is_shown_and_the_app_survives(opened):
    r = run("def f():\n    return 1 / 0\nf()")
    assert r["ok"] and r["error"]
    assert "ZeroDivisionError" in r["traceback"] and "return 1 / 0" in r["traceback"]
    assert "console.py" not in r["traceback"]
    r = run("def broken(:")
    assert r["error"] and "SyntaxError" in r["traceback"]
    assert run("raise SystemExit(3)")["error"]


def test_every_run_is_one_undo_step_dropped_when_it_changed_nothing(opened):
    # D92: a console run is one undo step even without edit(), and no step is left when nothing changed.
    r = run("ifc.by_type('IfcWall')[0].Name = 'Scripted'")
    assert r["ok"] and not r["error"], r["traceback"]
    assert r["edited"]
    assert r["geometry"]["changed"] == [opened[0]]
    assert call("state")["can_undo"]
    assert call("undo")["ok"]
    assert not call("state")["can_undo"]
    assert run("1 + 1")["output"] == "2\n"
    assert not call("state")["can_undo"]


def test_edit_is_one_undo_step_and_redraws_what_changed(opened):
    code = (
        "import ifcopenshell.api.attribute\n"
        "with edit():\n"
        "    for w in ifc.by_type('IfcWall'):\n"
        "        ifcopenshell.api.attribute.edit_attributes(ifc, product=w, attributes={'Name': 'Scripted'})\n"
    )
    r = run(code)
    assert r["ok"] and not r["error"], r["traceback"]
    assert r["edited"]
    assert set(r["geometry"]["changed"]) == set(opened)
    assert call("state")["can_undo"]
    assert {w.Name for w in app_bridge._model.by_type("IfcWall")} == {"Scripted"}
    assert call("undo")["ok"]
    assert {w.Name for w in app_bridge._model.by_type("IfcWall")} != {"Scripted"}
    assert not call("state")["can_undo"]  # the three renames were one step


def test_bridge_commands_inside_edit_join_its_step(opened):
    code = (
        "with edit():\n"
        "    bridge.set_name(json.dumps([w.GlobalId for w in ifc.by_type('IfcWall')]), 'A')\n"
        "    bridge.delete_elements(json.dumps([ifc.by_type('IfcWall')[0].GlobalId]))\n"
    )
    r = run("import json\n" + code)
    assert not r["error"], r["traceback"]
    assert opened[0] in r["geometry"]["removed"]
    assert len(app_bridge._model.by_type("IfcWall")) == 2
    call("undo")
    assert len(app_bridge._model.by_type("IfcWall")) == 3
    assert not call("state")["can_undo"]


def test_failed_edit_rolls_back(opened):
    code = (
        "with edit():\n"
        "    ifc.by_type('IfcWall')[0].Name = 'half'\n"
        "    raise ValueError('nope')\n"
    )
    r = run(code)
    assert r["error"] and "ValueError" in r["traceback"]
    assert "half" not in {w.Name for w in app_bridge._model.by_type("IfcWall")}
    assert not call("state")["can_undo"] and not r["edited"]


def test_select_round_trip(opened):
    r = run("[e.GlobalId for e in selection()]", selection=opened[:2])
    assert r["output"].strip() == repr(opened[:2])
    r = run("select(ifc.by_type('IfcWall')[2])\n[e.GlobalId for e in selection()]", selection=opened[:2])
    assert r["select"] == [opened[2]]
    assert opened[2] in r["output"]
    assert run("select([])")["select"] == []


def test_refresh_redraws_everything(opened):
    r = run("refresh()")
    assert r["edited"] and set(opened) <= set(r["geometry"]["changed"])


def test_run_file_shares_the_namespace(opened, tmp_path):
    script = tmp_path / "count.py"
    script.write_text("walls = len(ifc.by_type('IfcWall'))\nprint(__file__.endswith('count.py'))\n", encoding="utf-8")
    r = call("console_run_file", str(script), "[]")
    assert r["output"] == "True\n"
    assert run("walls")["output"] == "3\n"


def test_help_lists_the_helpers(opened):
    out = run("help_kimbim()")["output"]
    for name in ("ifc", "selection()", "select(", "edit()", "refresh()"):
        assert name in out


def test_stop_interrupts_a_running_loop(opened):
    result = {}
    t = threading.Thread(target=lambda: result.update(run("n = 0\nwhile True:\n    n += 1\n")))
    t.start()
    for _ in range(100):
        if console._worker is not None:
            break
        time.sleep(0.02)
    time.sleep(0.1)
    assert json.loads(console.console_stop())["ok"]
    t.join(10)
    assert not t.is_alive()
    assert result["error"] and "KeyboardInterrupt" in result["traceback"]
    assert run("1 + 1")["output"] == "2\n"  # the console still works, with no tracing left
