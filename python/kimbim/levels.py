# SPDX-License-Identifier: GPL-3.0-or-later
"""The levels table (D79, Archicad's Story Settings): rename levels, change their elevations (their
elements move with them), insert and delete levels, and choose which ones the level list shows.

Same protocol as app_bridge (strings in, JSON out, never raise). The app's dialog sends the whole
table at once (`edit_storeys`): one undo step, however many levels changed.

A level is an IfcBuildingStorey: its elevation is its placement's height (what geometry uses) and
`Elevation` (kept equal). Elements on it are usually placed relative to it, so moving the storey's
placement moves them; elements placed otherwise (absolute, or relative to something else) are
moved explicitly, and anything that hangs off the storey's placement without being on the level is
moved back, so every element on the level, and only those, moves with it.
"""
from __future__ import annotations

import json
import math

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np

from . import app_bridge as B
from . import authoring as A
from . import drawgen as G

LEVEL_PSET = "KIMBIM_Level"  # ShowInLevelList (Archicad: "Show in Story List")
DEFAULT_HEIGHT = 3.0         # metres: a new level's height when nothing says otherwise
_EPS = 1e-9


def _levels() -> list:
    """The building's levels (models are not levels), lowest first."""
    from .worksheets import is_worksheet

    return sorted((s for s in B._model.by_type("IfcBuildingStorey") if not A._is_model(s) and not is_worksheet(s)),
                  key=A._elevation)


def _shown(storey) -> bool:
    return bool(ifcopenshell.util.element.get_psets(storey).get(LEVEL_PSET, {}).get("ShowInLevelList", True))


def _members(storey) -> list:
    """The level's products: contained elements, spaces and other parts aggregated under it, and
    what hangs off them (openings, doors and windows in them, parts of assemblies)."""
    out, seen = [], set()
    stack = list(A._contained(storey))
    stack += [o for rel in getattr(storey, "IsDecomposedBy", ()) or () for o in rel.RelatedObjects
              if not o.is_a("IfcBuildingStorey")]
    while stack:
        e = stack.pop()
        if e.id() in seen or not e.is_a("IfcProduct"):
            continue
        seen.add(e.id())
        out.append(e)
        for rel in getattr(e, "HasOpenings", ()) or ():
            stack.append(rel.RelatedOpeningElement)
            stack += [fill.RelatedBuildingElement for fill in getattr(rel.RelatedOpeningElement, "HasFillings", ()) or ()]
        for rel in getattr(e, "IsDecomposedBy", ()) or ():
            stack += list(rel.RelatedObjects)
        for rel in getattr(e, "ContainsElements", ()) or ():  # spaces can contain furniture
            stack += list(rel.RelatedElements)
    return out


def _element_count(storey) -> int:
    """Elements the user would lose with the level (openings come with their walls)."""
    return sum(1 for e in _members(storey) if not e.is_a("IfcOpeningElement") and not e.is_a("IfcAnnotation"))


def levels_table() -> str:
    """[{guid, name, elevation, height (to the next level, null for the top one), show, elements}]."""
    if B._model is None:
        return B._dump({"levels": []})
    levels = _levels()
    rows = []
    for i, s in enumerate(levels):
        elevation = A._elevation(s)
        above = A._elevation(levels[i + 1]) if i + 1 < len(levels) else None
        rows.append({"guid": s.GlobalId, "name": s.Name or "", "elevation": round(elevation, 6),
                     "height": None if above is None else round(above - elevation, 6),
                     "show": _shown(s), "elements": _element_count(s)})
    return B._dump({"levels": rows})


# ---------------------------------------------------------------- placements

def _depth(placement) -> int:
    n = 0
    while placement is not None:
        n += 1
        placement = getattr(placement, "PlacementRelTo", None)
    return n


def _world_z(product) -> float:
    return float(ifcopenshell.util.placement.get_local_placement(product.ObjectPlacement)[2][3])


def _lift(placement, dz_units: float):
    """Move a local placement up by dz (model units, world vertical), whatever its parent's tilt."""
    f = B._model
    parent = getattr(placement, "PlacementRelTo", None)
    up = np.array([0.0, 0.0, dz_units])
    if parent is not None:
        rotation = ifcopenshell.util.placement.get_local_placement(parent)[:3, :3]
        up = np.linalg.solve(rotation, up)
    relative = placement.RelativePlacement
    coords = list(relative.Location.Coordinates) + [0.0] * (3 - len(relative.Location.Coordinates))
    point = f.createIfcCartesianPoint([float(c) + float(d) for c, d in zip(coords, up)])
    # A new axis placement, never an edit: exporters share one (Revit: every placement uses #3).
    if relative.is_a("IfcAxis2Placement3D"):
        placement.RelativePlacement = f.createIfcAxis2Placement3D(point, relative.Axis, relative.RefDirection)
    else:  # 2D: the same turn about z
        ref = relative.RefDirection
        ref = f.createIfcDirection([*map(float, ref.DirectionRatios[:2]), 0.0]) if ref is not None else None
        placement.RelativePlacement = f.createIfcAxis2Placement3D(point, None, ref)
    if not f.get_inverse(relative):
        location = relative.Location
        f.remove(relative)
        if not f.get_inverse(location):
            f.remove(location)


def _own_placement(product):
    """The product's placement, copied first when other products share it (moving it would move them)."""
    placement = product.ObjectPlacement
    if sum(1 for x in B._model.get_inverse(placement) if x.is_a("IfcProduct")) > 1:
        product.ObjectPlacement = B._model.createIfcLocalPlacement(placement.PlacementRelTo, placement.RelativePlacement)
    return product.ObjectPlacement


def _shift(storey, dz: float) -> list:
    """Inside an action: raise a level by dz metres with everything on it. Returns the moved
    products that have a shape (to re-mesh).

    No placement maths for the usual case: which placements move follows from the placement
    tree (a member moves when the chain above it reaches a lifted placement), so only members
    placed some other way are lifted one by one (seconds saved on a 1500-element level)."""
    if abs(dz) < _EPS:
        return []
    units = dz / A._scale()
    members = [e for e in _members(storey) if getattr(e, "ObjectPlacement", None) is not None
               and e.ObjectPlacement.is_a("IfcLocalPlacement")]
    moved = {}  # placement id -> True (moves by dz) / False (stays)
    own = storey.ObjectPlacement
    if own is not None and own.is_a("IfcLocalPlacement"):
        placement = _own_placement(storey)
        if placement == own:
            # What hangs directly off the storey's placement without being on the level (other
            # storeys some exporters chain, elements of other levels) is put back where it was.
            ours = {e.ObjectPlacement.id() for e in members}
            for child in [x for x in B._model.get_inverse(own) if x.is_a("IfcLocalPlacement")
                          and x.PlacementRelTo == own and x.id() not in ours]:
                _lift(child, -units)
                moved[child.id()] = False
        _lift(placement, units)
        moved[placement.id()] = True
    if storey.Elevation is not None:  # kept in step with the placement (its own datum, whatever it is)
        storey.Elevation = float(storey.Elevation) + units

    def follows(placement) -> bool:
        p = getattr(placement, "PlacementRelTo", None)
        while p is not None:
            if p.id() in moved:
                return moved[p.id()]
            p = getattr(p, "PlacementRelTo", None)
        return False

    # Parents first, so a door placed relative to its lifted wall is seen to follow it.
    for e in sorted(members, key=lambda m: _depth(m.ObjectPlacement)):
        if e.ObjectPlacement.id() in moved and moved[e.ObjectPlacement.id()]:
            continue
        if not follows(e.ObjectPlacement):
            _lift(_own_placement(e), units)
        moved[e.ObjectPlacement.id()] = True
    _replace_plans(storey)
    return [e.GlobalId for e in members if getattr(e, "Representation", None) is not None]


def _plans(storey) -> list:
    from . import drawings

    return [d for d in drawings._drawings()
            if G.settings_of(d).get("kind") == "plan" and G.settings_of(d).get("storey") == storey.GlobalId]


def _replace_plans(storey):
    """The level's floor plans follow its new height (their camera sits above the level)."""
    plans = _plans(storey)
    if plans:
        bounds = G.model_bounds(B._model)
        for d in plans:
            G.place(B._model, d, G.settings_of(d), bounds)


# ---------------------------------------------------------------- the table

def _set_shown(storey, show: bool):
    if _shown(storey) == bool(show):
        return
    pset = ifcopenshell.util.element.get_pset(storey, LEVEL_PSET)
    pset = B._model.by_id(pset["id"]) if pset else ifcopenshell.api.pset.add_pset(B._model, product=storey, name=LEVEL_PSET)
    ifcopenshell.api.pset.edit_pset(B._model, pset=pset, properties={"ShowInLevelList": bool(show)})


def _rename(storey, name: str):
    from . import drawings

    if (storey.Name or "") == name:
        return
    old_plan = drawings.plan_name(storey)
    storey.Name = name
    for d in _plans(storey):  # its floor plan keeps the level's name unless the user renamed it
        if d.Name == old_plan:
            d.Name = drawings.plan_name(storey)


def _truthy(v) -> bool:
    return v is True or str(v).strip().lower() in ("1", "true", "yes")


def _number(value, what: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what}: not a number ({value})")
    if not math.isfinite(x) or abs(x) > 100000:
        raise ValueError(f"{what}: out of range ({value})")
    return x


def _check(changes: dict) -> tuple:
    """Validate a table edit before anything changes. Returns (rows, [(storey, mode, target)])."""
    levels = {s.GlobalId: s for s in _levels()}
    rows = []
    for row in changes.get("levels", []):
        guid = row.get("guid") or ""
        if guid and guid not in levels:
            raise ValueError(f"unknown level {guid}")
        name = str(row.get("name", "")).strip()
        if not name:
            raise ValueError("every level needs a name")
        rows.append({"guid": guid, "name": name, "elevation": _number(row.get("elevation"), name),
                     "show": bool(row.get("show", True))})
    deletions = []
    for d in changes.get("deleted", []):
        guid = d.get("guid") if isinstance(d, dict) else d
        if guid not in levels:
            raise ValueError(f"unknown level {guid}")
        mode = (d.get("elements") if isinstance(d, dict) else None) or "refuse"
        if mode not in ("refuse", "delete", "move"):
            raise ValueError(f"unknown choice for the level's elements: {mode}")
        if mode == "refuse" and _element_count(levels[guid]):
            raise ValueError(f"the level {levels[guid].Name or guid} has {_element_count(levels[guid])} elements: "
                             "delete them or move them to another level first")
        into = (d.get("move_to") if isinstance(d, dict) else None) or changes.get("move_to") or ""
        deletions.append((levels[guid], mode, into))
    gone = {s.GlobalId for s, _, _ in deletions}
    if gone and len(gone) >= len(levels) + sum(1 for r in rows if not r["guid"]):
        raise ValueError("a model needs at least one level")
    if any(r["guid"] in gone for r in rows):
        raise ValueError("a deleted level cannot be edited")
    out = []
    for storey, mode, into in deletions:
        target = levels.get(into) if mode == "move" else None
        if mode == "move" and (target is None or target.GlobalId in gone):
            raise ValueError("choose a level that stays to move the elements to")
        out.append((storey, mode, target))
    return rows, out


def _move_members(storey, target):
    """Put the level's elements on another level, where they are (world placement kept)."""
    f = B._model
    contained = [e for e in A._contained(storey) if e.is_a("IfcProduct")]
    if contained:
        ifcopenshell.api.spatial.assign_container(f, products=contained, relating_structure=target)

    for rel in list(getattr(storey, "IsDecomposedBy", ()) or ()):
        for part in [o for o in rel.RelatedObjects if not o.is_a("IfcBuildingStorey")]:
            world = ifcopenshell.util.placement.get_local_placement(part.ObjectPlacement) \
                if getattr(part, "ObjectPlacement", None) is not None else None
            ifcopenshell.api.aggregate.assign_object(f, products=[part], relating_object=target)
            if world is not None:
                part.ObjectPlacement.PlacementRelTo = target.ObjectPlacement
                ifcopenshell.api.geometry.edit_object_placement(f, product=part, matrix=world, is_si=False)


def _apply(rows, deletions, move_above: bool = False) -> tuple:
    """Inside an action: the whole table edit. Returns (count, geometry changed, removed, created)."""
    from . import drawings

    count, changed, removed, created = 0, [], [], []
    for row in rows:
        if row["guid"]:
            s = B._model.by_guid(row["guid"])
            if (s.Name or "") != row["name"]:
                _rename(s, row["name"])
                count += 1
            if _shown(s) != row["show"]:
                _set_shown(s, row["show"])
                count += 1
    # Elevations: every level moves by its own difference (placements are independent, and
    # anything chained to a moved level is put back by _shift). With `move_above` (D92), the levels
    # above a moved level go with it, as when one level's elevation is edited.
    for row in rows:
        if row["guid"]:
            s = B._model.by_guid(row["guid"])
            orig = A._elevation(s)
            dz = row["elevation"] - orig
            if abs(dz) > 1e-7:
                changed += _shift(s, dz)
                count += 1
                if move_above:
                    for above in B._model.by_type("IfcBuildingStorey"):
                        if above.id() != s.id() and A._elevation(above) > orig + 1e-7:
                            changed += _shift(above, dz)
                            count += 1
    for row in rows:
        if not row["guid"]:
            s = A._make_storey(row["name"], row["elevation"])
            drawings.create_plan(s.GlobalId, undoable=False)  # Archicad: every story has a floor plan
            if not row["show"]:
                _set_shown(s, False)
            created.append(s.GlobalId)
            count += 1
    for storey, mode, target in deletions:
        if mode == "refuse" and _element_count(storey):  # elements moved onto it by an earlier deletion
            raise ValueError(f"the level {storey.Name or storey.GlobalId} has elements: delete them or move them first")
        if mode == "move":
            _move_members(storey, target)
        elif mode == "delete":
            tops = [e for e in A._contained(storey) if e.is_a("IfcProduct")]
            tops += [o for rel in getattr(storey, "IsDecomposedBy", ()) or () for o in rel.RelatedObjects
                     if o.is_a("IfcProduct") and not o.is_a("IfcBuildingStorey")]
            if tops:
                _, again, gone = A._delete_cascade(tops)
                changed += again
                removed += gone
        for d in _plans(storey):
            ifcopenshell.api.root.remove_product(B._model, product=d)
        ifcopenshell.api.root.remove_product(B._model, product=storey)
        count += 1
    gone = set(removed)
    return count, [g for g in dict.fromkeys(changed) if g not in gone], removed, created


def edit_storeys(changes_json: str) -> str:
    """Apply the levels table in one undo step. `changes_json`: {"levels": [{guid ("" for a new
    level), name, elevation (m), show}], "deleted": [{guid, elements: "refuse" | "delete" | "move",
    move_to: guid}]} ("move_to" can also be given once for all). Levels left out of "levels" keep their values."""
    if B._model is None:
        return A._fail("no model open")
    try:
        changes = json.loads(changes_json) if isinstance(changes_json, str) else dict(changes_json)
        rows, deletions = _check(changes)
    except (ValueError, TypeError, AttributeError) as ex:
        return A._fail(str(ex))
    if any(not r["guid"] for r in rows) and not B._model.by_type("IfcBuilding"):
        return A._fail("the model has no building to add a level to")
    made = {}

    def action():
        count, changed, removed, made["created"] = _apply(rows, deletions, bool(changes.get("move_above")))
        return count, changed, removed

    try:
        r = B._run(action)
    except Exception as ex:
        return A._fail(f"{type(ex).__name__}: {ex}")
    return B._dump({**r, "created": made["created"]})


# ---------------------------------------------------------------- one change at a time

def _row(storey) -> dict:
    return {"guid": storey.GlobalId, "name": storey.Name or "", "elevation": A._elevation(storey), "show": _shown(storey)}


def _one(guid: str, _move_above: bool = False, **change) -> str:
    s = A._by_guid(guid) if B._model is not None else None
    if s is None or not s.is_a("IfcBuildingStorey"):
        return A._fail("unknown level")
    return edit_storeys(json.dumps({"levels": [{**_row(s), **change}], "move_above": _move_above}))


def rename_storey(guid: str, name: str) -> str:
    return _one(guid, name=name)


def set_storey_elevation(guid: str, elevation, move_above=False) -> str:
    """Move a level to a new elevation (metres); its elements move with it (Archicad). With
    `move_above` (D92) the levels above it move too."""
    return _one(guid, _move_above=_truthy(move_above), elevation=elevation)


def set_storey_shown(guid: str, show) -> str:
    return _one(guid, show=bool(show) and str(show).lower() not in ("0", "false"))


def insert_storey(name: str, elevation="", fit_between=False) -> str:
    """Add a level at `elevation`. With `fit_between` (D92, Revit) it goes in the middle of the gap it
    falls in and the levels around it stay; otherwise it is placed as given (Archicad's push above)."""
    if not _truthy(fit_between):
        return edit_storeys(json.dumps({"levels": [{"guid": "", "name": name, "elevation": elevation, "show": True}]}))
    try:
        z = _number(elevation, name)
    except ValueError as ex:
        return A._fail(str(ex))
    if B._model is None:
        return A._fail("no model open")
    others = sorted(A._elevation(s) for s in B._model.by_type("IfcBuildingStorey"))
    below = max((e for e in others if e <= z + 1e-7), default=None)
    above = min((e for e in others if e >= z - 1e-7), default=None)
    target = (below + above) / 2 if below is not None and above is not None and above - below > 1e-7 else z
    return edit_storeys(json.dumps({"levels": [{"guid": "", "name": name, "elevation": target, "show": True}]}))


def delete_storey(guid: str, elements: str = "refuse", move_to: str = "") -> str:
    """Delete a level. With elements on it: "refuse" (the default) fails, "delete" deletes them
    with the level (Archicad), "move" puts them on `move_to` where they are."""
    return edit_storeys(json.dumps({"deleted": [{"guid": guid, "elements": elements}], "move_to": move_to}))
