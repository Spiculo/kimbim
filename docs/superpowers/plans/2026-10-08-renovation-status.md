# Renovation Status, Filters and Legends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elements carry an Archicad-style renovation status (Existing / To be demolished / New) that purposes show, hide or restyle through renovation filters, with a legend on screen and on sheets.

**Architecture:** Status is IFC model data (`Pset_<Class>Common.Status` enumerated, or `KIMCAD_Renovation.Status`), read through the existing per-name property index. Renovation filters are a new D73-style settings table; `graphics.resolve` applies visibility → renovation filter → override rules and reports legend entries. Sheets get legend references beside placed drawings. The C++ app adds a Properties drop-down, a Model menu, a bottom-bar status for new elements, a filter editor and sheet legends.

**Tech Stack:** Python 3.12 + IfcOpenShell (python/kimcad), C++17/Qt 6 + OCCT app (app/src), pytest, Qt Test/ctest, pixi.

**Spec:** `docs/superpowers/specs/2026-10-08-renovation-status-design.md`

## Global Constraints

- Three statuses; internal keys `existing`, `demolish`, `new`; IFC values written `EXISTING`, `DEMOLISH`, `NEW`.
- No status, or any unknown value, means `new`.
- Read `Status` from any pset, or `Renovation Status`; own values win over type values.
- Write to `Pset_<Class>Common.Status` (an `IfcPropertyEnumeratedValue`) only when the schema's template has it (IFC4 yes; IFC2X3 Common psets don't), else `KIMCAD_Renovation.Status` (an `IfcLabel`).
- Empty `renovation_filters` means the built-ins; the first edit writes the whole table (D73 rule).
- Purposes without `renovation`, or naming a missing filter, mean `Everything`.
- Pens 31 (existing grey `#808080` 0.18), 32 (demolition `#c09000` 0.25), 33 (demolition fill `#f8e8a0`). In Permit: 31 `#808080`, 32 `#000000`, 33 `#ffffff`.
- Bridge functions follow the app_bridge protocol: strings in, JSON out, never raise.
- Every model edit is one undo step through `B._run`.
- Every new UI string gets Spanish (`app/translations/kimcad_es.ts`); `pixi run check-translations` passes.
- Python tests: `pixi run test-py` (or `pixi run pytest tests/python/<file> -q` after `pixi run build`). App: `pixi run app-test`.

## Review Focus

1. An imported IFC (Archicad/Revit export) with `Status` values in odd case or as `Renovation Status`, which should be read correctly and never crash. Task 1 tests it.
2. Undo after setting the status of several elements, which should restore every one in one step. Task 2 tests it.
3. Opening a survey IFC with no statuses, where the app should offer once to mark them Existing and apply the answer as one undo step. Task 7 tests it.
4. A purpose saved before this change (no `renovation` key) in a template or .kim, which should open and look the same. Task 3 tests it.
5. A project whose pen sets were already written before pens 31–33 existed, where the demolition style should fall back without errors. Task 4 tests it.
6. A sheet whose drawings contain no demolished elements under a Demolition purpose, where the legend should not list the demolition row. Task 6 tests it.

---

### Task 1: Status read and write (`renovation.py`)

**Files:**
- Create: `python/kimcad/renovation.py`
- Modify: `python/kimcad/graphics.py` (`_property_index`: enumerated values)
- Test: `tests/python/test_renovation.py`

**Interfaces:**
- Produces: `STATUSES = ("existing", "demolish", "new")`; `normalize(value) -> str`; `status_of(element, facts=None) -> str`; `write_status(element, status: str) -> None` (inside an action); `common_pset(element) -> str | None`.

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Renovation status (part B of BIM properties): read and write."""
import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.type
import ifcopenshell.util.element
import pytest

from kimcad import graphics as g
from kimcad import renovation as r
from kimcad.testing import _reset_owner, _set_owner


def _model(schema="IFC4"):
    f = ifcopenshell.file(schema=schema)
    if schema == "IFC2X3":
        _set_owner(f)
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    return f


def _el(f, cls, **psets):
    e = ifcopenshell.api.root.create_entity(f, ifc_class=cls)
    for pset_name, props in psets.items():
        p = ifcopenshell.api.pset.add_pset(f, product=e, name=pset_name)
        ifcopenshell.api.pset.edit_pset(f, pset=p, properties=props)
    return e


@pytest.mark.parametrize("value,expected", [
    ("EXISTING", "existing"), ("existing", "existing"), (["EXISTING"], "existing"),
    ("DEMOLISH", "demolish"), ("Demolished", "demolish"), ("To Be Demolished", "demolish"),
    ("NEW", "new"), ("TEMPORARY", "new"), ("OTHER", "new"), ("", "new"), (None, "new"), ("garbage", "new"),
])
def test_normalize(value, expected):
    assert r.normalize(value) == expected


def test_no_status_is_new():
    f = _model()
    assert r.status_of(_el(f, "IfcWall")) == "new"


def test_write_to_the_common_pset_as_enumerated_ifc4():
    f = _model()
    w = _el(f, "IfcWall")
    r.write_status(w, "demolish")
    prop = next(p for p in f.by_type("IfcPropertyEnumeratedValue") if p.Name == "Status")
    assert [v.wrappedValue for v in prop.EnumerationValues] == ["DEMOLISH"]
    assert r.status_of(w) == "demolish"
    r.write_status(w, "existing")  # rewrites, never duplicates
    assert r.status_of(w) == "existing"
    assert len([p for p in f.by_type("IfcPropertyEnumeratedValue") if p.Name == "Status"]) == 1


def test_classes_without_a_status_template_use_kimcad_renovation():
    f = _model()
    space = _el(f, "IfcSpace")
    r.write_status(space, "existing")
    assert ifcopenshell.util.element.get_pset(space, "KIMCAD_Renovation")["Status"] == "EXISTING"
    assert r.status_of(space) == "existing"


def test_ifc2x3_uses_kimcad_renovation():
    try:
        f = _model("IFC2X3")
        w = _el(f, "IfcWall")
        r.write_status(w, "demolish")
        assert ifcopenshell.util.element.get_pset(w, "KIMCAD_Renovation")["Status"] == "DEMOLISH"
        assert r.status_of(w) == "demolish"
    finally:
        _reset_owner()


def test_writing_clears_the_other_place():
    f = _model()
    w = _el(f, "IfcWall", KIMCAD_Renovation={"Status": "DEMOLISH"})
    r.write_status(w, "existing")  # goes to Pset_WallCommon; the KIMCAD one must not contradict it
    assert "Status" not in (ifcopenshell.util.element.get_pset(w, "KIMCAD_Renovation") or {})
    assert r.status_of(w) == "existing"


def test_read_from_archicad_name_and_from_the_type():
    f = _model()
    a = _el(f, "IfcWall", AC_Pset_RenovationAndPhasing={"Renovation Status": "To Be Demolished"})
    assert r.status_of(a) == "demolish"
    w = _el(f, "IfcFurniture")
    t = ifcopenshell.api.root.create_entity(f, ifc_class="IfcFurnitureType")
    p = ifcopenshell.api.pset.add_pset(f, product=t, name="Pset_FurnitureTypeCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=p, properties={"Status": ["EXISTING"]})
    ifcopenshell.api.type.assign_type(f, related_objects=[w], relating_type=t)
    assert r.status_of(w) == "existing"
    r.write_status(w, "demolish")  # the element's own value overrides the type's
    assert r.status_of(w) == "demolish"


def test_property_index_reads_enumerated_values():
    f = _model()
    w = _el(f, "IfcWall", Pset_WallCommon={"Status": ["NEW"]})
    assert g._property_index(f, "Status")[w.id()] == "NEW"
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `pixi run pytest tests/python/test_renovation.py -q`
Expected: FAIL, `ModuleNotFoundError: kimcad.renovation`

- [ ] **Step 3: Enumerated values in the property index**

In `graphics._property_index`, extend the candidate loop:

```python
    for cls, attr in (("IfcPropertySingleValue", "NominalValue"), ("IfcPropertyEnumeratedValue", "EnumerationValues"),
                      ("IfcPhysicalSimpleQuantity", None)):
        ...
            if attr == "EnumerationValues":
                values = getattr(p, attr) or ()
                value = _value(values[0]) if values else None
            else:
                value = (_value(getattr(p, attr)) if getattr(p, attr) is not None else None) if attr else _value(p[3])
```

- [ ] **Step 4: Write `renovation.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Renovation status (Archicad's model): Existing, To be demolished, New. Stored where IFC keeps it,
Pset_<Class>Common.Status (an enumerated value: EXISTING, DEMOLISH, NEW), or KIMCAD_Renovation.Status
where the schema's template for the class has no Status (IFC2X3, spaces, furniture occurrences). Read
from any pset's Status or Archicad's "Renovation Status"; no status, or an unknown one, is New.
Same protocol as app_bridge for the bridge functions (strings in, JSON out, never raise).
"""
from __future__ import annotations

import functools

import ifcopenshell.api.pset
import ifcopenshell.util.element
import ifcopenshell.util.pset

STATUSES = ("existing", "demolish", "new")
IFC_VALUE = {"existing": "EXISTING", "demolish": "DEMOLISH", "new": "NEW"}
PSET = "KIMCAD_Renovation"
NAMES = ("Status", "Renovation Status")


def normalize(value) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    text = str(value or "").strip().lower()
    if text == "existing":
        return "existing"
    if text in ("demolish", "demolished", "to be demolished"):
        return "demolish"
    return "new"


@functools.lru_cache(maxsize=None)
def _common_for(schema: str, ifc_class: str) -> str | None:
    template = ifcopenshell.util.pset.get_template(schema)
    for t in template.get_applicable(ifc_class, pset_only=True):
        if t.Name.endswith("Common") and not t.Name.endswith("TypeCommon") \
                and any(p.Name == "Status" for p in t.HasPropertyTemplates):
            return t.Name
    return None


def common_pset(element) -> str | None:
    """The standard pset whose Status this element's class can carry, if its schema has one."""
    return _common_for(element.file.schema, element.is_a())


def status_of(element, facts=None) -> str:
    from . import graphics

    facts = facts if facts is not None else graphics._Facts(element)
    for name in NAMES:
        v = facts.prop(name)
        if v is not None:
            return normalize(v)
    return "new"


def _own_pset(element, name):
    data = ifcopenshell.util.element.get_pset(element, name, should_inherit=False)
    return element.file.by_id(data["id"]) if data else None


def write_status(element, status: str) -> None:
    """Inside an action: the element's own status (one place; the other place's Status is removed)."""
    f = element.file
    target = common_pset(element)
    other = PSET if target else None
    if target:
        ps = _own_pset(element, target) or ifcopenshell.api.pset.add_pset(f, product=element, name=target)
        ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"Status": [IFC_VALUE[status]]})
    else:
        ps = _own_pset(element, PSET) or ifcopenshell.api.pset.add_pset(f, product=element, name=PSET)
        ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"Status": IFC_VALUE[status]})
    stale = _own_pset(element, other) if other else None
    if stale is not None and any(p.Name == "Status" for p in stale.HasProperties):
        ifcopenshell.api.pset.edit_pset(f, pset=stale, properties={"Status": None})
```

Note: `edit_pset(..., {"Status": None})` removes the property in IfcOpenShell (it purges `None` values). If the version in use keeps it, remove it by hand: find the `IfcProperty` named `Status` in `stale.HasProperties` and call `ifcopenshell.api.pset.remove_pset` when it was the only one, else `f.remove(prop)` after taking it out of `HasProperties`. The test `test_writing_clears_the_other_place` decides.

- [ ] **Step 5: Run the tests to make sure they pass**

Run: `pixi run pytest tests/python/test_renovation.py tests/python/test_graphics.py -q`
Expected: all pass. The graphics tests must keep passing after the index change.

- [ ] **Step 6: Commit**

```bash
git add python/kimcad/renovation.py python/kimcad/graphics.py tests/python/test_renovation.py
git commit -m "feat(renovation): status read and written where IFC keeps it (Common pset Status or KIMCAD_Renovation)"
```

---

### Task 2: Setting the status: bridge, stamping new elements, copies, Properties data

**Files:**
- Modify: `python/kimcad/renovation.py`, `python/kimcad/settings.py`, `python/kimcad/authoring.py` (each `layers.assign_active(...)` and `layers.copy_layer(...)` call), `python/kimcad/rooms.py:263`, `python/kimcad/roofs.py:287`, `python/kimcad/app_bridge.py` (`properties_multi`, the bridge imports)
- Test: `tests/python/test_renovation.py`

**Interfaces:**
- Consumes: Task 1's `write_status`, `status_of`, `STATUSES`.
- Produces: bridge `set_status(guids_json: str, status: str) -> str` (`{"ok", "changed", "geometry"}` or `{"ok": False, "error"}`); bridge `set_status_for_new(status: str) -> str` (`{"ok", "dirty"}`); `stamp_new(*elements)`; `copy_status(source, target)`; settings key `status_for_new` (default `"new"`); `properties_multi` returns `"status": {"value": str | None, "varies": bool}`; bridge `unmarked() -> {"ok", "count", "guids"}`; bridge `mark_unmarked(status) -> edit result` (one undo step; only `existing` or `demolish`).

- [ ] **Step 1: Write the failing tests** (append to `tests/python/test_renovation.py`)

```python
import json
import pathlib
import tempfile

from kimcad import app_bridge as b
from kimcad import authoring as A
from kimcad import settings as s


def call(fn, *args):
    return json.loads(getattr(b, fn)(*args))


def _house():
    s.load(None)
    assert call("new_project", "Reno")["ok"]
    level = json.loads(A.storeys())["storeys"][0]["guid"]
    wall_type = json.loads(A.wall_types())["types"][0]["guid"]
    w1 = json.loads(A.create_wall(level, wall_type, 0, 0, 5, 0, 3.0))["geometry"]["changed"][0]
    w2 = json.loads(A.create_wall(level, wall_type, 0, 3, 5, 3, 3.0))["geometry"]["changed"][0]
    return level, wall_type, w1, w2


def test_set_status_is_one_undo_step():
    _, _, w1, w2 = _house()
    assert call("set_status", json.dumps([w1, w2]), "demolish")["ok"]
    assert call("properties_multi", json.dumps([w1, w2]))["status"] == {"value": "demolish", "varies": False}
    assert call("undo")["ok"]
    assert call("properties_multi", json.dumps([w1, w2]))["status"] == {"value": "new", "varies": False}


def test_mixed_status_varies():
    _, _, w1, w2 = _house()
    call("set_status", json.dumps([w1]), "existing")
    assert call("properties_multi", json.dumps([w1, w2]))["status"] == {"value": None, "varies": True}


def test_set_status_refuses_unknown_status():
    _, _, w1, _ = _house()
    r = call("set_status", json.dumps([w1]), "ruined")
    assert not r["ok"] and "ruined" in r["error"]


def test_new_elements_get_the_status_for_new():
    level, wall_type, w1, _ = _house()
    assert r.status_of(b._model.by_guid(w1)) == "new"
    assert ifcopenshell.util.element.get_pset(b._model.by_guid(w1), "Pset_WallCommon")["Status"] == ["NEW"]
    assert call("set_status_for_new", "existing")["ok"]
    assert s.current()["status_for_new"] == "existing"
    w3 = json.loads(A.create_wall(level, wall_type, 0, 6, 5, 6, 3.0))["geometry"]["changed"][0]
    assert r.status_of(b._model.by_guid(w3)) == "existing"
    assert not call("set_status_for_new", "ruined")["ok"]


def test_doors_in_a_demolished_wall_take_the_status_for_new():
    _, _, w1, _ = _house()
    call("set_status", json.dumps([w1]), "demolish")
    door_type = json.loads(A.opening_types("door"))["types"][0]["guid"]
    door = json.loads(A.insert_opening("door", w1, door_type, 2.0, 0.9, 2.1, 0.0))["guid"]
    assert r.status_of(b._model.by_guid(door)) == "new"


def test_copies_keep_the_source_status():
    _, _, w1, _ = _house()
    call("set_status", json.dumps([w1]), "existing")
    call("set_status_for_new", "new")
    out = call("copy_elements", json.dumps([w1]), 0, 10, 0)
    copy = next(g for g in out["geometry"]["changed"] if g != w1)
    assert r.status_of(b._model.by_guid(copy)) == "existing"


def test_unmarked_and_mark_unmarked():
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="P")
    bare = [ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall") for _ in range(2)]
    explicit = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall")
    p = ifcopenshell.api.pset.add_pset(f, product=explicit, name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=p, properties={"Status": ["NEW"]})
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcAnnotation")  # never counted
    path = str(pathlib.Path(tempfile.mkdtemp()) / "survey.ifc")
    f.write(path)
    assert call("open_model", path)["ok"]
    u = call("unmarked")
    assert u["count"] == 2 and set(u["guids"]) == {w.GlobalId for w in bare}
    assert call("mark_unmarked", "existing")["ok"]
    assert call("unmarked")["count"] == 0
    assert r.status_of(b._model.by_guid(explicit.GlobalId)) == "new"  # explicit NEW left alone
    assert all(r.status_of(b._model.by_guid(w.GlobalId)) == "existing" for w in bare)
    assert call("undo")["ok"]  # one step
    assert call("unmarked")["count"] == 2
    assert not call("mark_unmarked", "new")["ok"]  # New is what unmarked already means


def test_annotations_are_not_stamped():
    _house()
    from kimcad import annotations

    level = json.loads(A.storeys())["storeys"][0]["guid"]
    out = json.loads(annotations.create_annotation(level, "text", json.dumps({"points": [[0, 0]], "text": "Hi"})))
    note = b._model.by_guid(out["guid"])
    assert ifcopenshell.util.element.get_pset(note, "KIMCAD_Renovation") is None
```

Before running, check these names in the code and adjust the test (not the code) to match:
- `A.opening_types(kind)`: grep `def .*types` in `authoring.py` for the door-type listing used by the app.
- The `insert_opening` result key.
- `annotations.create_annotation`'s signature.
- That the copy GUID appears in `copy_elements`' `geometry.changed`.

- [ ] **Step 2: Run them to make sure they fail**

Run: `pixi run pytest tests/python/test_renovation.py -q`
Expected: FAIL, `AttributeError: module 'kimcad.app_bridge' has no attribute 'set_status'`

- [ ] **Step 3: Settings key**

In `settings.py` `DEFAULTS` add `"status_for_new": "new",` after `"sheet_purposes": {},`. In `_error`, before the graphics delegation, add:

```python
    if key == "status_for_new" and value not in ("existing", "demolish", "new"):
        return f"unknown renovation status {value}"
```

- [ ] **Step 4: Bridge, stamping and copying in `renovation.py`**

```python
def _for_new() -> str:
    from . import settings as S

    value = S.current().get("status_for_new", "new")
    return value if value in STATUSES else "new"


def stamp_new(*elements) -> None:
    """New building elements get the status for new elements (annotations and drawings are not stamped)."""
    status = _for_new()
    for e in elements:
        if e is None or e.is_a("IfcAnnotation"):
            continue
        write_status(e, status)


def copy_status(source, target) -> None:
    """Copies keep their source's status (as they keep its layer)."""
    if not source.is_a("IfcAnnotation"):
        write_status(target, status_of(source))


def set_status(guids_json: str, status: str) -> str:
    from . import app_bridge as B

    if B._model is None:
        return B._dump({"ok": False, "error": "no model open"})
    if status not in STATUSES:
        return B._dump({"ok": False, "error": f"unknown renovation status {status}"})
    elements = [e for e in B._elements(guids_json) if not e.is_a("IfcAnnotation")]
    if not elements:
        return B._dump({"ok": False, "error": "no building elements selected"})

    def action():
        for e in elements:
            write_status(e, status)
        return len(elements), [e.GlobalId for e in elements], []  # restyled, not reshaped: the app restyles

    try:
        return B._dump(B._run(action))
    except Exception as ex:
        return B._dump({"ok": False, "error": f"{type(ex).__name__}: {ex}"})


def set_status_for_new(status: str) -> str:
    from . import app_bridge as B
    from . import settings as S

    if status not in STATUSES:
        return B._dump({"ok": False, "error": f"unknown renovation status {status}"})
    r = json.loads(S.set_project_settings(json.dumps({"status_for_new": status})))
    return B._dump({"ok": r["ok"], "dirty": r.get("dirty", False), **({"error": r["error"]} if not r["ok"] else {})})
```

Add `import json` at the top.

Also in `renovation.py`:

```python
def _unmarked_elements() -> list:
    from . import app_bridge as B
    from . import graphics

    shared: dict = {}
    out = []
    for e in graphics._products(B._model):
        if e.is_a("IfcAnnotation") or e.is_a("IfcGrid"):
            continue
        facts = graphics._Facts(e, shared)
        if all(facts.prop(n) is None for n in NAMES):
            out.append(e)
    return out


def unmarked() -> str:
    from . import app_bridge as B

    if B._model is None:
        return B._dump({"ok": False, "error": "no model open"})
    els = _unmarked_elements()
    return B._dump({"ok": True, "count": len(els), "guids": [e.GlobalId for e in els]})


def mark_unmarked(status: str) -> str:
    """Elements with no status at all (an imported survey) get this one, in one undo step."""
    from . import app_bridge as B

    if B._model is None:
        return B._dump({"ok": False, "error": "no model open"})
    if status not in ("existing", "demolish"):
        return B._dump({"ok": False, "error": "mark unmarked elements as existing or demolish"})
    els = _unmarked_elements()

    def action():
        for e in els:
            write_status(e, status)
        return len(els), [e.GlobalId for e in els], []

    try:
        return B._dump(B._run(action))
    except Exception as ex:
        return B._dump({"ok": False, "error": f"{type(ex).__name__}: {ex}"})
```

`_products` already skips the spatial structure, openings and drawings. Grids are excluded here too: they aren't building elements.

- [ ] **Step 5: Call sites**

Next to every `layers.assign_active(x)`, add `renovation.stamp_new(x)`:
- `authoring.py`: lines ~298 (wall), ~474 (slab), ~701 (door/window `element`; the opening itself is an `IfcOpeningElement`, so stamp only the filling), ~811 (column), ~850 (beam), ~1494 (stair);
- `rooms.py:263` (space) and `roofs.py:287` (roof).
- Not `annotations.py:190`.

Next to every `layers.copy_layer(src, dst)` (`authoring.py:1360` and `:1384`), add `renovation.copy_status(src, dst)`. Import with `from . import renovation` beside the existing `from . import layers`.

If a copy already carries the status (IfcOpenShell's `copy_class` copies psets), `copy_status` rewrites the same value, which is harmless. It keeps the rule explicit.

- [ ] **Step 6: `properties_multi` and the bridge list**

In `app_bridge.properties_multi`, before the final `_dump`:

```python
    from . import renovation

    statuses = [renovation.status_of(e) for e in elements if not e.is_a("IfcAnnotation")]
    status = {"value": statuses[0] if statuses and all(x == statuses[0] for x in statuses) else None,
              "varies": len(set(statuses)) > 1}
```

and add `"status": status,` to the dict. (Annotations only: `{"value": None, "varies": False}`.)

In the bridge import block (beside `from .settings import ...`), add:

```python
from .renovation import mark_unmarked, set_status, set_status_for_new, unmarked  # noqa: E402,F401
```

- [ ] **Step 7: Run the tests to make sure they pass**

Run: `pixi run pytest tests/python/test_renovation.py tests/python/test_authoring.py tests/python/test_editing.py tests/python/test_rooms.py tests/python/test_roofs.py tests/python/test_settings.py -q`
Expected: all pass.

Also run `pixi run golden`. New elements now carry a Status pset, which golden hashes of *imported* files don't touch. If a golden that builds elements changes, stop and report it; don't update the hashes.

- [ ] **Step 8: Commit**

```bash
git add -A python/kimcad tests/python/test_renovation.py
git commit -m "feat(renovation): set the status (one undo step), status for new elements, copies keep theirs, mark unmarked elements, Properties data"
```

---

### Task 3: Renovation filters table, pens 31–33, purposes

**Files:**
- Modify: `python/kimcad/graphics.py` (`TABLES`, `_BUILTINS`, `_ROLES`, `_pen_set`, `validate`, `_references_error`), `python/kimcad/settings.py` (`DEFAULTS`)
- Test: `tests/python/test_graphics.py`

**Interfaces:**
- Produces: `TABLES` gains `"renovation_filters"`; `builtin("renovation_filters")` has `Everything`, `Existing plan`, `Demolition plan`, `New plan`, `Planned`; purposes gain `renovation`; `FILTER_SHOW = ("as_is", "hide", "override")`; `FILTER_FIELDS = ("pen", "cut_pen", "projection_pen", "line", "fill", "surface", "transparency")`.

- [ ] **Step 1: Write the failing tests** (append to `tests/python/test_graphics.py`)

```python
def test_renovation_builtins():
    f = g.builtin("renovation_filters")
    assert list(f) == ["Everything", "Existing plan", "Demolition plan", "New plan", "Planned"]
    assert f["Demolition plan"]["new"] == {"show": "hide"}
    assert f["Demolition plan"]["demolish"]["show"] == "override"
    assert g.validate("renovation_filters", f) is None
    p = g.builtin("purposes")
    assert p["Demolition"]["renovation"] == "Demolition plan"
    assert p["Working"]["renovation"] == "Everything"
    assert {"Existing", "Demolition", "New construction"} <= set(p)
    pens = g.builtin("pen_sets")
    assert pens["Working"]["pens"]["32"] == {"color": "#c09000", "weight": 0.25, "name": "Demolition"}
    assert pens["Permit"]["pens"]["32"]["color"] == "#000000"


@pytest.mark.parametrize("value,message", [
    ({"A": {"ruined": {"show": "hide"}}}, "filter A: unknown status ruined"),
    ({"A": {"new": {"show": "blink"}}}, "filter A: show is as_is, hide or override"),
    ({"A": {"new": {"show": "override", "pen": 300}}}, "filter A: pens are 1-255"),
    ({"A": {"new": {"show": "override", "surface": "red"}}}, "filter A: colour must be #rrggbb"),
    ({"A": {"new": {"show": "override", "glow": 1}}}, "filter A: unknown field glow"),
])
def test_renovation_filter_validation(value, message):
    assert g.validate("renovation_filters", value) == message


def test_old_purposes_without_renovation_are_valid_and_mean_everything():
    old = {"Mine": {"pen_set": "Working", "visibility": "Everything", "overrides": "None", "layers": None}}
    assert g.validate("purposes", old) is None
    s.load({"purposes": old})
    assert g._references_error(s.current()) is None


def test_a_purpose_naming_a_missing_filter_is_refused_by_set_graphics():
    p = dict(g.builtin("purposes"))
    p["Working"] = {**p["Working"], "renovation": "Gone"}
    r = json.loads(g.set_graphics(json.dumps({"purposes": p})))
    assert not r["ok"] and "renovation filter" in r["error"]
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `pixi run pytest tests/python/test_graphics.py -q -k "renovation or old_purposes or missing_filter"`
Expected: FAIL (`KeyError: 'renovation_filters'`)

- [ ] **Step 3: Implement**

In `graphics.py`:

```python
TABLES = ("pen_sets", "line_types", "element_styles", "visibility_sets", "override_sets",
          "layer_combinations", "purposes", "renovation_filters")
FILTER_SHOW = ("as_is", "hide", "override")
FILTER_FIELDS = ("pen", "cut_pen", "projection_pen", "line", "fill", "surface", "transparency")
STATUS_KEYS = ("existing", "demolish", "new")
```

`_ROLES` gains `31: "Existing", 32: "Demolition", 33: "Demolition fill"`. Add:

```python
_RENOVATION_PENS = {"default": {31: ("#808080", .18), 32: ("#c09000", .25), 33: ("#f8e8a0", .18)},
                    "Permit": {31: ("#808080", .18), 32: ("#000000", .25), 33: ("#ffffff", .18)}}
```

and in `_BUILTINS["pen_sets"]` build with
`_pen_set({**roles, **_RENOVATION_PENS.get(name, _RENOVATION_PENS["default"])})`. In `_pen_set`, the `n in roles` branch is checked before the `n >= 30` ramp, so roles 31–33 win.

```python
_AS_IS = {"show": "as_is"}
_BUILTINS["renovation_filters"] = {
    "Everything": {"existing": _AS_IS, "demolish": _AS_IS, "new": _AS_IS},
    "Existing plan": {"existing": _AS_IS, "demolish": _AS_IS, "new": {"show": "hide"}},
    "Demolition plan": {"existing": _AS_IS,
                        "demolish": {"show": "override", "pen": 32, "line": "Dashed", "fill": 33, "surface": "#f0c020"},
                        "new": {"show": "hide"}},
    "New plan": {"existing": {"show": "override", "pen": 31, "fill": 31},
                 "demolish": {"show": "hide"}, "new": _AS_IS},
    "Planned": {"existing": _AS_IS, "demolish": {"show": "hide"}, "new": _AS_IS},
}
```

(Define it inside the `_BUILTINS` literal so ordering stays readable.) Each built-in purpose gets `"renovation": "Everything"`, and three purposes are added:

```python
        "Existing": {"pen_set": "Permit", "visibility": "Architectural", "overrides": "None", "layers": None,
                     "renovation": "Existing plan"},
        "Demolition": {"pen_set": "Permit", "visibility": "Architectural", "overrides": "None", "layers": None,
                       "renovation": "Demolition plan"},
        "New construction": {"pen_set": "Permit", "visibility": "Architectural", "overrides": "None", "layers": None,
                             "renovation": "New plan"},
```

In `validate`, add a branch:

```python
    elif key == "renovation_filters":
        for name, flt in value.items():
            if not isinstance(flt, dict):
                return f"filter {name}: expected an object"
            for status, t in flt.items():
                if status not in STATUS_KEYS:
                    return f"filter {name}: unknown status {status}"
                if not isinstance(t, dict) or t.get("show") not in FILTER_SHOW:
                    return f"filter {name}: show is as_is, hide or override"
                for k, v in t.items():
                    if k == "show":
                        continue
                    if k not in FILTER_FIELDS:
                        return f"filter {name}: unknown field {k}"
                    if k in ("pen", "cut_pen", "projection_pen", "fill") and not _pen_no(v):
                        return f"filter {name}: pens are 1-255"
                    if k == "surface" and not (isinstance(v, str) and _COLOR.match(v)):
                        return f"filter {name}: colour must be #rrggbb"
                    if k == "transparency" and not (_number(v) and 0 <= v <= 1):
                        return f"filter {name}: transparency must be 0-1"
                    if k == "line" and not isinstance(v, str):
                        return f"filter {name}: the line type is a name"
```

In the purposes branch, add:
`if "renovation" in v and not isinstance(v["renovation"], str): return f"purpose {name}: the renovation filter is a name"`.
In `_references_error`, add:

```python
    flts = effective("renovation_filters", st)
    ...
        if p.get("renovation") is not None and p["renovation"] not in flts:
            return f"purpose {name} uses a renovation filter that doesn't exist: {p['renovation']}"
```

`settings.DEFAULTS` gains `"renovation_filters": {},`. `settings._error` already delegates `graphics.TABLES`.

Update `test_builtins_are_complete_and_valid`, whose purposes set assertion now includes the three new purposes.

- [ ] **Step 4: Run all graphics and settings tests**

Run: `pixi run pytest tests/python/test_graphics.py tests/python/test_settings.py tests/python/test_settings_history.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add python/kimcad/graphics.py python/kimcad/settings.py tests/python/test_graphics.py
git commit -m "feat(graphics): renovation filters table, existing/demolition pens, Existing/Demolition/New construction purposes"
```

---

### Task 4: Resolution with the renovation filter, and legend entries

**Files:**
- Modify: `python/kimcad/graphics.py` (`resolve`, `graphics_state`, `GRAPHICS_KEYS`)
- Test: `tests/python/test_graphics.py`

**Interfaces:**
- Consumes: Task 1 `renovation.status_of(e, facts)`, Task 3 tables.
- Produces: `resolve()` output gains `"renovation": <filter name>`, `"legend": [{"label", "source", "key", "style"}]` and `"legend_members": [[guid, ...], ...]` (same order as `legend`; not sent by `graphics_state`). `key` is the status key or the rule name. Labels for statuses are English, `"Existing"`, `"To be demolished"`, `"New"`; the app translates them by `key`.

- [ ] **Step 1: Write the failing tests**

```python
def _reno_model():
    f = _model()
    from kimcad import renovation as r
    walls = {}
    for st in ("existing", "demolish", "new"):
        w = _el(f, "IfcWall", Pset_WallCommon={"FireRating": "60" if st == "demolish" else ""})
        r.write_status(w, st)
        walls[st] = w
    return f, walls


def test_demolition_purpose_hides_new_and_restyles_demolished():
    f, w = _reno_model()
    out = g.resolve("Demolition", model=f)
    assert w["new"].GlobalId in out["hidden"]
    demo = out["styles"][out["elements"][w["demolish"].GlobalId]]
    assert demo["cut"]["color"] == "#000000" and demo["cut"]["dash"] == [3.0, 1.5]  # Permit pen 32, Dashed
    assert demo["fill"] == "#ffffff"
    assert demo["surface"] == "#f0c020"
    assert out["renovation"] == "Demolition plan"


def test_override_rules_apply_on_top_of_the_renovation_filter():
    f, w = _reno_model()
    s.load({"purposes": {**g.builtin("purposes"),
                         "Mix": {"pen_set": "Working", "visibility": "Everything", "overrides": "Fire rating",
                                 "layers": None, "renovation": "Demolition plan"}}})
    out = g.resolve("Mix", model=f)
    demo = out["styles"][out["elements"][w["demolish"].GlobalId]]
    assert demo["cut"]["color"] == g.builtin("pen_sets")["Working"]["pens"]["27"]["color"]  # the 60 min rule's pen
    assert demo["cut"]["dash"] == [3.0, 1.5]  # the filter's line type stays


def test_legend_lists_only_applied_entries_in_order():
    f, w = _reno_model()
    out = g.resolve("Demolition", model=f)
    assert [(e["source"], e["key"]) for e in out["legend"]] == [("renovation", "existing"), ("renovation", "demolish")]
    assert out["legend"][1]["label"] == "To be demolished"
    assert out["legend_members"][1] == [w["demolish"].GlobalId]
    assert g.resolve("Working", model=f)["legend"] == []  # nothing changed: no legend


def test_legend_has_no_demolition_row_without_demolished_elements():
    f, w = _reno_model()
    from kimcad import renovation as r
    r.write_status(w["demolish"], "existing")
    out = g.resolve("Demolition", model=f)
    assert [e["key"] for e in out["legend"]] == []  # only as-is rows left: nothing to explain


def test_pen_sets_written_before_pens_31_33_fall_back():
    f, w = _reno_model()
    old = g.builtin("pen_sets")
    for p in old.values():
        for n in ("31", "32", "33"):
            p["pens"].pop(n)
    s.load({"pen_sets": old})
    out = g.resolve("Demolition", model=f)
    demo = out["styles"][out["elements"][w["demolish"].GlobalId]]
    assert demo["cut"]["color"] == g.FALLBACK_PEN["color"]


def test_graphics_state_leaves_out_the_members():
    s.load(None)
    state = json.loads(g.graphics_state())
    assert "legend" in state and "legend_members" not in state
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `pixi run pytest tests/python/test_graphics.py -q -k "demolition or renovation_filter or legend or 31_33"`
Expected: FAIL (`KeyError: 'renovation'` / assertion)

- [ ] **Step 3: Implement in `resolve`**

After `rules = ...`:

```python
    filters = effective("renovation_filters", st)
    flt_name = p.get("renovation") if p.get("renovation") in filters else ("Everything" if "Everything" in filters else None)
    flt = filters.get(flt_name) or {}
    flt_active = any(t.get("show") != "as_is" for t in flt.values())
    from . import renovation
    legend_hits: dict = {}  # (source, key) -> [first style dict, [guids]]
```

In the element loop, right after the visibility check:

```python
        status = renovation.status_of(e, facts) if flt_active else "new"
        treatment = flt.get(status, {"show": "as_is"}) if flt_active else {"show": "as_is"}
        if treatment.get("show") == "hide":
            hidden.append(e.GlobalId)
            continue
```

After `surface = transparency = None`, apply the treatment before the rule:

```python
        def apply(then):
            nonlocal cut_pen, proj_pen, cut_line, proj_line, fill_pen, surface, transparency
            cut_pen = then.get("cut_pen", then.get("pen", cut_pen))
            proj_pen = then.get("projection_pen", then.get("pen", proj_pen))
            if "line" in then:
                cut_line = proj_line = then["line"]
            fill_pen = then.get("fill", fill_pen)
            surface = then.get("surface", surface)
            transparency = then.get("transparency", transparency)

        if treatment.get("show") == "override":
            apply(treatment)
```

Replace the rule's field block with `apply(then)`. This keeps the rule's behaviour: before, it set `surface, transparency = then.get(...)`, so a rule without `surface` cleared it to None. Now an absent `surface` keeps the filter's value, which is the stacking the spec asks for. `apply` is a nested function, so `resolve` must not be a generator. It isn't, so `nonlocal` works.

After `elements[e.GlobalId] = index[k]`, record legend hits:

```python
        if flt_active:
            legend_hits.setdefault(("renovation", status), [style, []])[1].append(e.GlobalId)
        if rule is not None:
            legend_hits.setdefault(("override", rule.get("name", "")), [style, []])[1].append(e.GlobalId)
```

After the loop, build the legend:

```python
    labels = {"existing": "Existing", "demolish": "To be demolished", "new": "New"}
    legend, members = [], []
    reno = [(k, v) for k, v in legend_hits.items() if k[0] == "renovation"]
    reno.sort(key=lambda kv: STATUS_KEYS.index(kv[0][1]))
    if any(flt.get(k[1], {}).get("show") == "override" for k, _ in reno):
        for (src, key), (style, guids) in reno:
            legend.append({"label": labels[key], "source": src, "key": key, "style": index[json.dumps(style, sort_keys=True)]})
            members.append(guids)
    for (src, key), (style, guids) in legend_hits.items():
        if src == "override":
            legend.append({"label": key, "source": src, "key": key, "style": index[json.dumps(style, sort_keys=True)]})
            members.append(guids)
```

Add `"renovation": flt_name or "", "legend": legend, "legend_members": members` to `out`.

The cache key already includes every `TABLES` key through `GRAPHICS_KEYS = TABLES + (...)`, so `renovation_filters` is covered. Statuses are model data, covered by the model state.

In `graphics_state`, drop the members: build `res = resolve(settings=st)`, then `res = {k: v for k, v in res.items() if k != "legend_members"}`.

- [ ] **Step 4: Run all graphics tests**

Run: `pixi run pytest tests/python/test_graphics.py tests/python/test_drawings.py -q`
Expected: all pass.

- [ ] **Step 5: Time the Clinic**

Run (needs the corpus; skip with a note if missing):
`pixi run python -c "import time,json,kimcad.app_bridge as b,kimcad.graphics as g; b.open_model('tests/corpus/files/Clinic_Architectural.ifc'); t=time.time(); g.resolve('Demolition'); print(time.time()-t)"`
Expected: under 0.5 s. Record the number for doc 11 (Task 9).

- [ ] **Step 6: Commit**

```bash
git add python/kimcad/graphics.py tests/python/test_graphics.py
git commit -m "feat(graphics): the purpose's renovation filter hides or restyles by status, override rules on top; legend entries"
```

---

### Task 5: Legend SVG

**Files:**
- Modify: `python/kimcad/graphics.py` (new `legend_svg`)
- Test: `tests/python/test_graphics.py`

**Interfaces:**
- Consumes: Task 4 `resolve()["legend"]`, `["legend_members"]`, `["styles"]`.
- Produces: `legend_svg(resolved: dict, guids: set | None = None) -> tuple[str, float, float]`, which returns the SVG body (no outer `<svg>`) in mm with its top-left at 0,0, plus its width and height. `guids`: only entries with a member in this set (None = all). `LEGEND_EMPTY = "Everything is drawn with its element styles"`.

- [ ] **Step 1: Write the failing test**

```python
def test_legend_svg_rows_and_restriction():
    f, w = _reno_model()
    out = g.resolve("Demolition", model=f)
    body, width, height = g.legend_svg(out)
    assert body.count('class="kimcad-legend-row"') == 2
    assert "To be demolished" in body and 'stroke-dasharray="3 1.5"' in body
    assert width > 40 and height == pytest.approx(8 + 2 * 7)
    body, _, _ = g.legend_svg(out, guids={w["existing"].GlobalId})
    assert body.count('class="kimcad-legend-row"') == 1  # the demolished wall isn't in these drawings
    body, _, h = g.legend_svg(g.resolve("Working", model=f))
    assert g.LEGEND_EMPTY in body and h == pytest.approx(8 + 7)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `pixi run pytest tests/python/test_graphics.py -q -k legend_svg`
Expected: FAIL (`AttributeError: legend_svg`)

- [ ] **Step 3: Implement**

```python
LEGEND_EMPTY = "Everything is drawn with its element styles"
_ROW, _TITLE, _SWATCH_W, _SWATCH_H = 7.0, 8.0, 10.0, 5.0


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def legend_svg(resolved: dict, guids=None) -> tuple:
    """The legend as SVG in paper mm (top-left 0,0): a title, then a swatch and a label per entry.
    `guids`: only entries that apply to one of these elements (a sheet's drawings)."""
    styles = resolved.get("styles", [])
    rows = [e for e, members in zip(resolved.get("legend", []), resolved.get("legend_members", []))
            if guids is None or guids.intersection(members)]
    if all(e["source"] == "renovation" for e in rows) and len(rows) <= 1:
        rows = []  # one as-is row explains nothing
    parts = [f'<text x="0" y="5" font-size="4" font-family="sans-serif">Legend</text>']
    y = _TITLE
    if not rows:
        parts.append(f'<text x="0" y="{y + 4:g}" font-size="3" font-family="sans-serif">{_xml(LEGEND_EMPTY)}</text>')
        return "\n".join(parts), 4 + 1.8 * len(LEGEND_EMPTY), y + _ROW
    longest = 0
    for e in rows:
        st = styles[e["style"]]
        fill = st.get("fill") or st.get("surface") or "none"
        parts.append(f'<g class="kimcad-legend-row"><rect x="0" y="{y:g}" width="{_SWATCH_W:g}" height="{_SWATCH_H:g}" '
                     f'fill="{fill}"{_stroke(st["cut"], 1.0)}/>'
                     f'<text x="{_SWATCH_W + 3:g}" y="{y + 4:g}" font-size="3" font-family="sans-serif">{_xml(e["label"])}</text></g>')
        longest = max(longest, len(e["label"]))
        y += _ROW
    return "\n".join(parts), _SWATCH_W + 3 + 1.8 * longest, y
```

A single renovation row (an as-is one) explains nothing, so it's dropped. Text width is estimated at 1.8 mm per character for 3 mm sans text, which is enough for a free-spot search and drag bounds.

- [ ] **Step 4: Run it to make sure it passes**

Run: `pixi run pytest tests/python/test_graphics.py -q -k legend`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python/kimcad/graphics.py tests/python/test_graphics.py
git commit -m "feat(graphics): legend as SVG (swatch and label per entry, limited to given elements)"
```

---

### Task 6: Legends on sheets

**Files:**
- Modify: `python/kimcad/sheets.py`, `python/kimcad/app_bridge.py` (bridge imports)
- Test: `tests/python/test_sheets.py`

**Interfaces:**
- Consumes: Task 5 `graphics.legend_svg`.
- Produces: bridge `place_legend(number) -> {"ok", "id", ...edit}`, `move_legend(number, id, x, y)`, `remove_legend(number, id)`; `sheets()` per sheet gains `"legends": [{"id", "x", "y", "w", "h"}]`; `sheet_svg` draws them (`<g class="kimcad-legend">`). Legend refs: `IfcDocumentReference` with Location `kimcad:legend#{json}` (IFC2X3) or Location `kimcad:legend` + Description JSON (IFC4); id in `Identification` / `ItemReference`.

- [ ] **Step 1: Read the reference helpers.** Read `sheets.py:35-75` and `place_drawing` (`:334-366`) to reuse `_data`, `_link_attr`, `MARKER`, `_free_spot` and the IFC2X3 Location fallback.

- [ ] **Step 2: Write the failing tests** (append to `tests/python/test_sheets.py`)

```python
def _demolish_one_wall():
    from kimcad import renovation as r
    wall = b._model.by_type("IfcWall")[0]
    assert call("set_status", json.dumps([wall.GlobalId]), "demolish")["ok"]
    return wall


def test_a_legend_is_placed_moved_drawn_and_removed(house):
    _demolish_one_wall()
    number = call("add_sheet", "A3", "Demolition")["number"]
    assert call("place_drawing", number, drawing("Ground floor"), 10, 10, 100)["ok"]
    assert call("set_sheet_purpose", number, "Demolition")["ok"]
    r = call("place_legend", number)
    assert r["ok"]
    sheet = next(s_ for s_ in call("sheets")["sheets"] if s_["number"] == number)
    (leg,) = sheet["legends"]
    assert leg["id"] == r["id"] and leg["w"] > 0 and leg["h"] > 0
    assert call("move_legend", number, leg["id"], 300, 200)["ok"]
    svg = call("sheet_svg", number)["svg"]
    assert 'class="kimcad-legend"' in svg and "To be demolished" in svg and "translate(300" in svg
    assert call("undo")["ok"]  # the move is one step
    assert call("remove_legend", number, leg["id"])["ok"]
    sheet = next(s_ for s_ in call("sheets")["sheets"] if s_["number"] == number)
    assert sheet["legends"] == []


def test_the_legend_only_lists_what_the_sheet_shows(house):
    number = call("add_sheet", "A3", "Demolition")["number"]  # nothing demolished
    assert call("place_drawing", number, drawing("Ground floor"), 10, 10, 100)["ok"]
    assert call("set_sheet_purpose", number, "Demolition")["ok"]
    assert call("place_legend", number)["ok"]
    svg = call("sheet_svg", number)["svg"]
    assert "To be demolished" not in svg and "Everything is drawn with its element styles" in svg


def test_legends_are_not_drawings(house):
    number = call("add_sheet", "A3", "L")["number"]
    call("place_legend", number)
    sheet = next(s_ for s_ in call("sheets")["sheets"] if s_["number"] == number)
    assert sheet["views"] == []
```

Check the house's drawing names with `call("drawings")` and adjust `"Ground floor"` if the plan is named differently. Then add an IFC2X3 variant of the first test beside the existing IFC2X3 sheet test (`grep -n IFC2X3 tests/python/test_sheets.py`), following its owner-reset pattern.

- [ ] **Step 3: Run them to make sure they fail**

Run: `pixi run pytest tests/python/test_sheets.py -q -k legend`
Expected: FAIL (`AttributeError: place_legend`)

- [ ] **Step 4: Implement in `sheets.py`**

```python
LEGEND = "kimcad:legend"


def _legends(sheet):
    refs = sheet.DocumentReferences if _x3() else getattr(sheet, "HasDocumentReferences", ())
    return [r for r in refs or () if (r.Location or "").partition("#")[0] == LEGEND]


def _legend(sheet, legend_id: str):
    return next((r for r in _legends(sheet) if _link(r) == legend_id), None)


def _legend_content(sheet, number: str):
    """(body, w, h) of the sheet's legend: the sheet purpose, limited to its drawings' elements."""
    from . import graphics, settings as S

    resolved = graphics.resolve(S.current().get("sheet_purposes", {}).get(number) or None)
    guids = set()
    for ref in _views(sheet):
        size, svg = _drawing_size(_link(ref), resolved["hidden"])
        if size is not None:
            guids.update(re.findall(r'ifc:guid="([^"]+)"', svg))
    return graphics.legend_svg(resolved, guids if _views(sheet) else None)
```

`place_legend(number)`, `move_legend(number, id, x, y)` and `remove_legend(number, id)` mirror `place_drawing`, `move_placed` and `remove_placed`:
- the same `B._run` action;
- a new `IfcDocumentReference` created with `ifcopenshell.api.document.add_reference(f, information=sheet)`;
- id from `ifcopenshell.guid.new()[:8]`, set through `_link_attr()`;
- Location `LEGEND` and data `{"x", "y"}` through the same helper that `place_drawing` uses for a drawing's placement (it handles the IFC2X3 `Location` fallback);
- for the free spot, call `_free_spot(sheet, w, h)` with the size from `_legend_content`.

In `sheets()`, add `"legends": [{"id": _link(r), **{k: v for k, v in _placement(r).items() if k in ("x", "y")}, "w": w, "h": h}]`, with `w, h` from `_legend_content`. Compute it once per sheet, and only when the sheet has legends, so listing stays cheap.

The cost concern: `_legend_content` runs `_drawing_size`, which can generate. `sheets()` must not generate (see `test_listing_sheets_after_an_edit_never_generates_drawings`). So in `sheets()`, size legends from `graphics.legend_svg(resolved)` (the whole model, no generation). Only `sheet_svg` uses the drawings' elements. The size difference is a few rows and the drag box updates after the next compose. Note it in a comment.

In `sheet_svg`, after the views loop:

```python
    for ref in _legends(sheet):
        p = _placement(ref)
        body, _, _ = legend_body if legend_body is not None else (legend_body := _legend_content(sheet, number))
        parts.append(f'<g class="kimcad-legend" transform="translate({p["x"]:.3f} {p["y"]:.3f})">\n{body}\n</g>')
```

(Initialise `legend_body = None` before the loop.) `_views` filters on `MARKER`, so legends never appear as views.

Export `place_legend, move_legend, remove_legend` in the app_bridge `from .sheets import (...)` block.

- [ ] **Step 5: Run the sheet and drawing tests**

Run: `pixi run pytest tests/python/test_sheets.py tests/python/test_drawings.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add python/kimcad/sheets.py python/kimcad/app_bridge.py tests/python/test_sheets.py
git commit -m "feat(sheets): legends placed on sheets, drawn from the sheet purpose and its drawings' elements"
```

---

### Task 7: App: status in Properties, Model menu, status for new elements, status on import

**Files:**
- Modify: `app/src/PropertiesPanel.{h,cpp}`, `app/src/StatusStrip.{h,cpp}`, `app/src/MainWindow.{h,cpp}`, `app/src/Preferences.{h,cpp}` (`bool askImportStatus() const`, key `ask_import_status`, default true in `defaults()`; written with the existing `setValue`)
- Test: `app/tests/test_properties_panel.cpp`, `app/tests/test_main_window.cpp`

**Interfaces:**
- Consumes: bridge `set_status`, `set_status_for_new`, `unmarked`, `mark_unmarked`, `properties_multi.status`, settings `status_for_new`.
- Produces: `PropertiesPanel::statusCombo()`, signal `statusEdited(const QString& status)`; `StatusStrip::setStatusForNew(const QString&)`, signal `statusForNewRequested(const QString&)`, `statusForNewCombo()`; `MainWindow::setRenovationStatus(const QString& status) -> bool`, `MainWindow::setStatusForNew(const QString&) -> bool`; `MainWindow::markUnmarked(const QString& status) -> bool`; `MainWindow::askImportStatus()` (called at the end of `openIfc`'s two success paths); test hook `MainWindow::setImportStatusAnswer(const QString&)` (in quiet mode, the answer the question gets; empty = leave them).
- Status keys in C++ are the same strings: `existing`, `demolish`, `new`. Shared labels come from a small free function `QString renovationLabel(const QString& key)` in `PropertiesPanel.h` (`tr()` inside a `QCoreApplication::translate("Renovation", ...)` so both widgets share one context).

- [ ] **Step 1: Write the failing tests**

In `test_properties_panel.cpp`:

```cpp
    void statusShowsAndEmits()
    {
        PropertiesPanel p;
        QJsonObject m{{"count", 2}, {"types", QJsonArray{"IfcWall"}}, {"guids", QJsonArray{"a", "b"}},
            {"name", QJsonObject{{"value", "W"}, {"varies", false}}}, {"psets", QJsonObject{}},
            {"status", QJsonObject{{"value", QJsonValue()}, {"varies", true}}}};
        p.showMulti(m);
        QComboBox* c = p.statusCombo();
        QVERIFY(c);
        QCOMPARE(c->currentText(), p.variesText());
        QSignalSpy spy(&p, &PropertiesPanel::statusEdited);
        c->setCurrentIndex(c->findData(QStringLiteral("demolish")));
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.first().first().toString(), QStringLiteral("demolish"));
        m["status"] = QJsonObject{{"value", "existing"}, {"varies", false}};
        p.showMulti(m); // rebuilding doesn't emit
        QCOMPARE(spy.count(), 1);
        QCOMPARE(c = p.statusCombo(), c);
        QCOMPARE(p.statusCombo()->currentData().toString(), QStringLiteral("existing"));
    }
```

In `test_main_window.cpp`, follow the existing new-project + draw-walls helpers (grep `void .*wall` in that file for the helper that draws a wall and selects it):

```cpp
    void renovationStatusFromMenuAndForNewElements()
    {
        // new project, draw a wall, select it (existing helpers)
        ...
        QVERIFY(w.setRenovationStatus(QStringLiteral("demolish")));
        QCOMPARE(w.propertiesPanel()->statusCombo()->currentData().toString(), QStringLiteral("demolish"));
        QVERIFY(w.setPurpose(QStringLiteral("New construction")));
        QVERIFY(w.viewport()->hiddenByVisibility().contains(wallGuid)); // hidden, survives Show all
        QVERIFY(w.setStatusForNew(QStringLiteral("existing")));
        QCOMPARE(w.statusStrip()->statusForNewCombo()->currentData().toString(), QStringLiteral("existing"));
        // draw a second wall; its Properties status is "existing"
        ...
        auto* menu = w.findChild<QMenu*>(QStringLiteral("renovationMenu"));
        QVERIFY(menu && menu->actions().size() == 5); // 3 statuses, a separator, "Mark unmarked elements as"
    }

    void openingAnIfcOffersToMarkUnmarkedElements()
    {
        // a bare IFC with two walls: bridge "_write_occlusion_model" writes one (walls made by the
        // authoring commands are stamped NEW, so strip their Status psets first, or write the file
        // with ifcopenshell directly through a small bridge test helper)
        MainWindow w; // quiet, as the other tests
        w.setImportStatusAnswer(QStringLiteral("existing"));
        QVERIFY(w.openIfc(path));
        QCOMPARE(bridgeObject("unmarked").value("count").toInt(), 0);
        QVERIFY(bridgeObject("undo").value("ok").toBool()); // one step
        QCOMPARE(bridgeObject("unmarked").value("count").toInt(), 2);
        w.setImportStatusAnswer(QString()); // leave them
        QVERIFY(w.openIfc(path2));
        QCOMPARE(bridgeObject("unmarked").value("count").toInt(), 2);
    }
```

Fill the `...` from the existing helpers in this file. Use the accessor names the file already uses (`propertiesPanel()`, `viewport()`, `statusStrip()`); add accessors only if one is missing. `hiddenByVisibility()` is whatever the D73 test `hiddenByVisibilityIsNotSelectable` in `test_visibility.cpp` / `test_main_window.cpp` uses.

- [ ] **Step 2: Build and run to make sure they fail**

Run: `pixi run app-build` then `ctest --test-dir build/app -R "properties_panel|main_window" --output-on-failure`
Expected: compile errors (`statusCombo` not a member).

- [ ] **Step 3: PropertiesPanel**

In `showMulti`, after the Name item, if `merged.contains("status")` and the selection isn't annotations only (status `value` non-null or `varies`), add the row:

```cpp
    const QJsonObject status = merged.value("status").toObject();
    if (status.value("varies").toBool() || !status.value("value").isNull()) {
        auto* item = new QTreeWidgetItem(element, {tr("Renovation status"), QString()});
        if (!m_status) {
            m_status = new QComboBox; // reparented by setItemWidget; recreated after clear()
        }
        ...
    }
```

Simplest correct version: create a new `QComboBox` each time (`m_status = new QComboBox(m_tree)`). Fill it with `renovationLabel(k)` / data `k` for `existing`, `demolish`, `new`. When `varies`, insert a first item `variesText()` with empty data. Set the current index under a `QSignalBlocker`. Connect `currentIndexChanged` to emit `statusEdited(data)` when the data is non-empty and `!m_building`. Call `m_tree->setItemWidget(item, 1, m_status)`. `clear()` sets `m_status = nullptr` (the tree deletes item widgets). The test's `QCOMPARE(c = p.statusCombo(), c)` line only checks the getter works after a rebuild; replace it with `QVERIFY(p.statusCombo());` if it reads oddly.

- [ ] **Step 4: StatusStrip**

Add `m_statusForNew` (`QComboBox`, objectName `statusForNew`) before `m_purpose`, with the tooltip `tr("Renovation status for new elements")` and the three items. Its `activated(int)` emits `statusForNewRequested(data)`. `setStatusForNew(key)` selects under a `QSignalBlocker`.

- [ ] **Step 5: MainWindow**

- `connect(m_properties, &PropertiesPanel::statusEdited, this, &MainWindow::setRenovationStatus);`
- `setRenovationStatus(status)`: `afterEdit(bridge("set_status", {jsonList(m_selection), status}))`, then `refreshGraphics()` and return `ok`. Status edits restyle and maybe hide: `afterEdit` already calls `refreshLayers()`, which ends in `refreshGraphics()`. Check that, and don't call it twice.
- Model menu: after the existing Model menu items, add `QMenu* reno = model->addMenu(tr("Renovation status"))` with objectName `renovationMenu`. It has three actions (labels from `renovationLabel`) calling `setRenovationStatus(key)`, enabled only with a selection: update them where the other selection-dependent actions are enabled (grep `setEnabled(!m_selection.isEmpty())`).
- `connect(m_status, &StatusStrip::statusForNewRequested, this, &MainWindow::setStatusForNew)`. `setStatusForNew` calls `bridge("set_status_for_new", {key})`, refreshes `m_settings` and calls `setWindowModified(isDirty())`, as `setCurrentPen` does.
- In `refreshGraphics()`, add `m_status->setStatusForNew(m_settings.value("status_for_new").toString("new"))`.
- The renovation menu: after the three statuses, add a separator and a submenu `tr("Mark unmarked elements as")` with *Existing* / *To be demolished* calling `markUnmarked(key)`. These are enabled while a model is open. With nothing unmarked, show the message `tr("Every element already has a renovation status")`.
- `markUnmarked(status)`: `afterEdit(bridge("mark_unmarked", {status}))`; status message `tr("%n element(s) marked", nullptr, changed)`.
- `askImportStatus()`:
  - Return if `!m_prefs.askImportStatus()`.
  - Call `bridge("unmarked")` and return if the count is 0.
  - In quiet mode, use `m_importStatusAnswer` (return if empty).
  - Otherwise show a `QMessageBox` (question, title `tr("Renovation status")`, text `tr("%n element(s) have no renovation status. Mark them as:", nullptr, count)`). Buttons: `tr("Existing")`, `tr("To be demolished")` and `tr("Leave them (they count as New)")`, the last being the default and escape button. Add `QCheckBox(tr("Don't ask again"))` via `box.setCheckBox`; when checked, call `m_prefs.setValue("ask_import_status", false); m_prefs.save();`.
  - A status answer calls `markUnmarked(key)`.
  - Call `askImportStatus()` just before `return true` in both success paths of `openIfc` (the direct one after `openFile`, the `.kim` one after `rememberRecent`), not in `openKim`.

- [ ] **Step 6: Build and run the tests**

Run: `pixi run app-build` then `ctest --test-dir build/app -R "properties_panel|main_window" --output-on-failure`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/src app/tests
git commit -m "feat(app): renovation status in Properties and the Model menu; status for new elements; offer to mark unmarked elements when opening an IFC"
```

---

### Task 8: App: renovation filter editor, purpose drop-downs, on-screen legend

**Files:**
- Modify: `app/src/GraphicsDialogs.h`, `app/src/PurposeDialogs.cpp` (renovation drop-down), `app/src/RuleDialogs.cpp` or a new `app/src/RenovationDialogs.cpp` (the filter editor; add to `app/CMakeLists.txt` beside `PurposeDialogs.cpp`), `app/src/MainWindow.cpp` (`editPurposePieces`, `customizePurpose`, the Graphics menu), `app/src/Graphics.{h,cpp}` (parse `legend`)
- Test: `app/tests/test_graphics.cpp`

**Interfaces:**
- Consumes: `graphics_tables` (now with `renovation_filters`), `graphics_state.legend`.
- Produces: `class RenovationFiltersDialog : public NamedSetsDialog` with `setShow(const QString& status, const QString& show)`, `setOverridePen(status, int)`, `setOverrideFill(status, int)`, `setOverrideLine(status, QString)`, `setOverrideSurface(status, QColor)`; `PurposesDialog::setPieces(...)` gains a `renovation` argument; `Graphics::legend()` returns `QVector<LegendEntry>` (`QString label, source, key; int style`).

- [ ] **Step 1: Write the failing tests** (in `test_graphics.cpp`, following its existing dialog tests: grep `PurposesDialog` there for how `reply` is built from `graphics_tables`)

```cpp
    void renovationFilterEditorWritesValidTables()
    {
        const QJsonObject reply = bridgeObject("graphics_tables"); // the helper the file already uses
        RenovationFiltersDialog d(reply, nullptr);
        d.selectSet(QStringLiteral("Demolition plan"));
        d.setShow(QStringLiteral("new"), QStringLiteral("as_is"));
        d.setShow(QStringLiteral("existing"), QStringLiteral("override"));
        d.setOverridePen(QStringLiteral("existing"), 31);
        const QJsonObject flt = d.changes().value("renovation_filters").toObject().value("Demolition plan").toObject();
        QCOMPARE(flt.value("new").toObject().value("show").toString(), QStringLiteral("as_is"));
        QCOMPARE(flt.value("existing").toObject().value("pen").toInt(), 31);
        QVERIFY(bridgeObject("set_graphics", {QString::fromUtf8(QJsonDocument(d.changes()).toJson())}).value("ok").toBool());
    }

    void purposesDialogHasRenovation()
    {
        PurposesDialog d(bridgeObject("graphics_tables"), nullptr);
        d.selectSet(QStringLiteral("Working"));
        auto* c = d.findChild<QComboBox*>(QStringLiteral("renovationOf"));
        QVERIFY(c);
        c->setCurrentIndex(c->findData(QStringLiteral("New plan")));
        QCOMPARE(d.changes().value("purposes").toObject().value("Working").toObject().value("renovation").toString(),
            QStringLiteral("New plan"));
    }

    void legendParsed()
    {
        const Graphics g = Graphics::fromJson(QJsonObject{{"styles", QJsonArray{}}, {"legend", QJsonArray{
            QJsonObject{{"label", "To be demolished"}, {"source", "renovation"}, {"key", "demolish"}, {"style", 0}}}}});
        QCOMPARE(g.legend().size(), 1);
        QCOMPARE(g.legend().first().key, QStringLiteral("demolish"));
    }
```

- [ ] **Step 2: Build to make sure it fails**

Run: `pixi run app-build`
Expected: compile errors (`RenovationFiltersDialog` unknown).

- [ ] **Step 3: Implement**

- **`Graphics`**: `struct LegendEntry { QString label, source, key; int style = -1; };` plus the member and getter; parse in `fromJson`.
- **`RenovationFiltersDialog`** (`NamedSetsDialog(reply, "renovation_filters", "renovation", parent)`):
  - a `QTableWidget` with 3 rows (labels from `renovationLabel`) and columns *Show* (combo: Show as is / Hide / Override, data `as_is`/`hide`/`override`), *Line pen* (`QSpinBox` 1–255, or the PenGrid button that `ElementStylesDialog` uses: grep there and reuse it), *Line type* (combo of `table("line_types").keys()`), *Fill pen*, *3D colour* (a `QPushButton` opening `QColorDialog`, empty = none).
  - Override fields are enabled only when Show is Override.
  - Each setter writes `currentValue()[status]` and keeps only `show` plus the fields set (switching to as_is/hide drops the others), then `setCurrentValue` and `showSet`.
  - `showSet` fills the table under `m_loading`.
  - Add **Graphics › Renovation filters…** after Overrides in `MainWindow`'s Graphics menu, following how `OverridesDialog` is opened (`exec`, then `setGraphics(changes)`, then `refreshGraphics`/`regenerateOpenDrawings`).
- **PurposesDialog**: add the `m_renovation` combo (objectName `renovationOf`, items `table("renovation_filters").keys()`), the row *Renovation filter:*, and `setPieces(..., renovation)` writing `"renovation"`. In `showSet`, pick `p.value("renovation").toString("Everything")`.
- **`editPurposePieces`**: add the same combo (`tr("Renovation filter:")`). `customizePurpose` gains a `renovation` parameter and writes it.
  - Below the form, add the **Legend** section: a `QLabel(tr("Legend"))` then, per `m_viewport->graphics().legend()` entry, a row with a 30×14 swatch pixmap (fill rect + cut line in colour, `Qt::DashLine` when the style has a dash) and the label. Translate renovation keys with `renovationLabel(key)`; rule names stay as they are.
  - With no entries, show `tr("Everything is drawn with its element styles")`.
  - Swatch style data: `Graphics` already holds `styles` with colours and dashes. Reuse its `LineStyle`.

- [ ] **Step 4: Build and run**

Run: `pixi run app-build` then `ctest --test-dir build/app -R graphics --output-on-failure`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/src app/tests app/CMakeLists.txt
git commit -m "feat(app): renovation filters editor, renovation in purposes and the purpose popup, on-screen legend"
```

---

### Task 9: App: legends on sheet tabs; exit check; docs and Spanish

**Files:**
- Modify: `app/src/SheetsPanel.{h,cpp}` (Place legend), `app/src/DrawingView.{h,cpp}` (right-click *Remove from sheet* on a placed item), `app/src/MainWindow.cpp` (`refreshSheets`, `openSheet`)
- Create: `tools/check_renovation.py`; `pixi.toml` task `renovation`; `.github/workflows/*.yml` step beside `pixi run m4`
- Modify: `docs/decisions.md` (D74), `docs/14-tool-inventory.md` (Renovation status row ✅; Graphic overrides note), `docs/04-app-features.md` (renovation entry, as D73 did), `docs/11-spike-results.md` (Clinic timing from Task 4), `docs/07-roadmap.md` (if D73 is listed there), `app/translations/kimcad_es.ts` / `kimcad_en.ts`
- Test: `app/tests/test_main_window.cpp`

**Interfaces:**
- Consumes: Task 6 bridge `place_legend`, `move_legend`, `remove_legend`, `sheets().legends`.
- Produces: `SheetsPanel::legendRequested(number)`; `DrawingView::placedRemoveRequested(const QString& id)`; placed ids for legends are `"legend:" + id` inside `DrawingView::Placed.guid`.

- [ ] **Step 1: Write the failing app test**

```cpp
    void sheetLegendPlacedDraggedRemoved()
    {
        // open the sample house (the helper the M4 sheet test uses), add a sheet, place a plan
        ...
        QVERIFY(w.placeLegend(number));
        auto* view = w.drawingView(QStringLiteral("sheet:") + number); // existing accessor, or add one
        QVERIFY(std::any_of(view->placed().begin(), view->placed().end(),
            [](const DrawingView::Placed& p) { return p.guid.startsWith(QLatin1String("legend:")); }));
        const QString id = /* that placed item's guid */;
        emit view->placedMoved(id, QPointF(200, 150));
        QCOMPARE(bridgeSheet(number).value("legends").toArray().first().toObject().value("x").toDouble(), 200.0);
        emit view->placedRemoveRequested(id);
        QVERIFY(bridgeSheet(number).value("legends").toArray().isEmpty());
    }
```

Add `DrawingView::placed()` (a const getter for `m_placed`) and `MainWindow::placeLegend(number)` if they're missing.

- [ ] **Step 2: Implement**

- `SheetsPanel`: in its context menu (grep `placeRequested` for where *Place drawing* is), add `tr("Place legend")` emitting `legendRequested(number)`.
- `MainWindow::placeLegend(number)`: `afterEdit(bridge("place_legend", {number}))`, then `openSheet(number)`.
- `refreshSheets`: append legends to `placed` as `{QStringLiteral("legend:") + id, QRectF(x, y, w, h)}`.
- `openSheet`'s `placedMoved` handler: if `drawing.startsWith("legend:")`, call `move_legend` with `drawing.mid(7)`, else `move_placed` as now.
- `DrawingView`: on a right-press over a placed rect in sheet mode, show a `QMenu` with `tr("Remove from sheet")` emitting `placedRemoveRequested(guid)`. Right-drag elsewhere keeps panning: check `DrawingView::mousePressEvent`, which pans with the middle button, so the right button is free there.
- `MainWindow`: connect `placedRemoveRequested`, using `remove_legend` for `legend:` ids and `remove_placed` otherwise, then `afterEdit`.

- [ ] **Step 3: Exit check `tools/check_renovation.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Renovation exit check: the sample house with an existing, a demolished and a new wall gives one
sheet per purpose (Existing, Demolition, New construction), each with a legend, each showing the right
walls. Usage: python tools/check_renovation.py build/house.ifc build/renovation"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
from kimcad import app_bridge as b  # noqa: E402


def call(fn, *args):
    r = json.loads(getattr(b, fn)(*args))
    if isinstance(r, dict) and r.get("ok") is False:
        raise SystemExit(f"{fn} failed: {r.get('error')}")
    return r


def main(house: str, out: str) -> int:
    outdir = pathlib.Path(out)
    outdir.mkdir(parents=True, exist_ok=True)
    call("open_model", house)
    walls = [w.GlobalId for w in b._model.by_type("IfcWall")][:3]
    for guid, status in zip(walls, ("existing", "demolish", "new")):
        call("set_status", json.dumps([guid]), status)
    plan = next(d["guid"] for d in call("drawings")["drawings"] if d["kind"] == "plan")
    expect = {"Existing": {walls[0], walls[1]}, "Demolition": {walls[0], walls[1]}, "New construction": {walls[0], walls[2]}}
    failures = []
    for purpose, shown in expect.items():
        number = call("add_sheet", "A3", purpose)["number"]
        call("place_drawing", number, plan, 10, 10, 100)
        call("set_sheet_purpose", number, purpose)
        call("place_legend", number)
        svg = call("sheet_svg", number)["svg"]
        (outdir / f"{purpose}.svg").write_text(svg, encoding="utf-8")
        for guid in walls:
            if (guid in svg) != (guid in shown):
                failures.append(f"{purpose}: wall {guid} {'missing' if guid in shown else 'shown'}")
        if 'class="kimcad-legend"' not in svg:
            failures.append(f"{purpose}: no legend")
    if "To be demolished" not in (outdir / "Demolition.svg").read_text(encoding="utf-8"):
        failures.append("Demolition: the legend has no demolition row")
    for f in failures:
        print("FAIL", f)
    print("renovation OK" if not failures else f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:3]))
```

Check that the first three walls appear in the ground-floor plan (`d["kind"]` and the plan's level). If the house's first three `IfcWall`s aren't all on the plan's level, pick three walls whose GUIDs are in the plan's unstyled SVG instead. Add to `pixi.toml`:

```toml
renovation = { cmd = "python tools/check_renovation.py build/house.ifc build/renovation", depends-on = ["house", "build"] }
```

and a CI step `pixi run renovation` after `pixi run m4`.

- [ ] **Step 4: Translations**

Regenerate the `.ts` files the way the D73 commit did (`git show 91d6e41 --stat`; find `lupdate` under `.pixi/envs/default`, e.g. `pixi run lupdate app/src -ts app/translations/kimcad_en.ts app/translations/kimcad_es.ts`). Translate every new Spanish entry:

| English | Spanish |
|---|---|
| Existing | Existente |
| To be demolished | A demoler |
| New | Nuevo |
| Renovation status | Estado de renovación |
| Renovation status for new elements | Estado de renovación de elementos nuevos |
| Renovation filters... | Filtros de renovación... |
| Renovation filter: | Filtro de renovación: |
| Show as is | Mostrar tal cual |
| Hide | Ocultar |
| Override | Sustituir |
| Legend | Leyenda |
| Everything is drawn with its element styles | Todo se dibuja con los estilos de sus elementos |
| Place legend | Colocar leyenda |
| Remove from sheet | Quitar de la lámina |
| Mark unmarked elements as | Marcar elementos sin estado como |
| Every element already has a renovation status | Todos los elementos ya tienen un estado de renovación |
| %n element(s) marked | %n elemento(s) marcado(s) |
| %n element(s) have no renovation status. Mark them as: | %n elemento(s) no tienen estado de renovación. Marcarlos como: |
| Leave them (they count as New) | Dejarlos (cuentan como Nuevos) |
| Don't ask again | No volver a preguntar |

Run `pixi run check-translations` and `ctest --test-dir build/app -R translations`.

- [ ] **Step 5: Docs**

- D74 row in `docs/decisions.md`, in D73's style: what was decided (status in Pset Common Status / KIMCAD_Renovation, three statuses, no status = New, filters stack before override rules, legends on screen and on sheets from the sheet's drawings, Model menu not a context menu), "Decided (owner, 2026-10-08; architect check pending)", spec and plan links.
- Doc 14:
  - *Renovation status (existing / demolish / new) and filters* ✅ D74;
  - *Colour by property, class or type* note "D73 rules";
  - *Associative labels and tags* stays ⬜ (part A).
- Doc 11: the Clinic Demolition resolve time.
- Doc 04: a short renovation paragraph under the graphics entry D73 added.
- In `docs/open-questions.md`, the renovation questions stay.

- [ ] **Step 6: Full verification**

Run: `pixi run test`, `pixi run app-test`, `pixi run m4`, `pixi run renovation`, `pixi run check-translations`
Expected: all pass. If a known flaky test fails (e.g. `app_selftest_draw_walls`), rerun it once and report both runs.

- [ ] **Step 7: Commit**

```bash
git add -A app tools pixi.toml .github docs
git commit -m "feat(app)+docs: legends on sheet tabs, renovation exit check, D74, Spanish"
```
