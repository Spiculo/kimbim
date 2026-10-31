# SPDX-License-Identifier: GPL-3.0-or-later
"""The attribute manager: an office's standards carried between projects as one JSON file.

Archicad calls these the project's attributes: the pen sets, line types, fill patterns, element
styles, visibility and graphic-override sets, layer combinations, purposes and renovation styles
(the project settings tables, D73) plus the IFC layers and the building materials, surfaces and
composites (D96). The file is self-contained (``kimbim-attributes/1``): the settings dictionary
holds only the tables the source project customised (an empty table means the built-ins), and the
``layers`` / ``materials`` / ``surfaces`` / ``composites`` lists hold what IFC stores.

Importing merges by name: a table or entity the target already has is kept unless ``replace`` is
set. The settings changes go through the settings step like every other settings dialog; the IFC
entities are created or updated in one undo step. Layers are created by name; the colour and weight
a file stores are kept for reference but not applied, because KimBim assigns shape representations
to a layer and a styled layer (IfcPresentationLayerWithStyle) may not hold them. Same protocol as
app_bridge (strings in, JSON out, never raise).
"""
from __future__ import annotations

import copy
import datetime
import json
import pathlib

from . import app_bridge as B

FORMAT = "kimbim-attributes/1"

# The settings groups the file carries: the name the options and the catalogue use -> the settings key.
SETTINGS_GROUPS = {
    "pens": "pen_sets",
    "line_types": "line_types",
    "fill_patterns": "fill_patterns",
    "element_styles": "element_styles",
    "visibility_sets": "visibility_sets",
    "graphic_overrides": "override_sets",
    "layer_combinations": "layer_combinations",
    "purposes": "purposes",
    "renovation_filters": "renovation_filters",
    "renovation_styles": "renovation_styles",
}
IFC_GROUPS = ("layers", "materials", "surfaces", "composites")
GROUPS = tuple(SETTINGS_GROUPS) + IFC_GROUPS

_SURFACE_FIELDS = ("colour", "transparency", "shine", "reflectance", "texture", "texture_size")
_MATERIAL_FIELDS = ("category", "description", "surface", "pen", "bg", "pattern", "priority", "identifier",
                    "manufacturer", "density", "conductivity", "heat")


def _fail(message: str) -> str:
    return B._dump({"ok": False, "error": message})


def _text(value) -> str:
    return str(value or "").strip()


# ---------------------------------------------------------------- the open project

def _layer_looks(f) -> dict:
    """{layer name: {colour, weight}} of the layers that carry styles (an IfcPresentationLayerWithStyle)."""
    from . import materials as M

    out = {}
    for layer in f.by_type("IfcPresentationLayerWithStyle"):
        entry = {}
        for style in layer.LayerStyles or ():
            if style.is_a("IfcSurfaceStyle"):
                look = M.surface_look(style)
                if look and look.get("colour"):
                    entry["colour"] = look["colour"]
            elif style.is_a("IfcCurveStyle"):
                width = getattr(style, "CurveWidth", None)
                width = getattr(width, "wrappedValue", width)
                if isinstance(width, (int, float)) and not isinstance(width, bool):
                    entry["weight"] = float(width)
        if entry:
            out[layer.Name or ""] = entry
    return out


def _layers(f) -> list:
    """Every layer of the project by name (the underlay-only ones included, as the layer list shows them)."""
    from . import layers as L

    looks = _layer_looks(f)
    try:
        listing = json.loads(L.layers()).get("layers") or []
    except Exception:  # no model or an odd file: the IFC assignments are enough
        listing = [{"name": layer.Name or "", "count": 0} for layer in f.by_type("IfcPresentationLayerAssignment")]
    return [{"name": item["name"], "count": item.get("count", 0), **looks.get(item["name"], {})} for item in listing]


def _materials(f) -> list:
    from . import materials as M

    state = M.state(f)
    surfaces = {s["name"]: s for s in state["surfaces"]}
    out = []
    for item in state["materials"]:
        surface = item.get("surface") or ""
        look = surfaces.get(surface, {})
        entry = {key: item.get(key) for key in _MATERIAL_FIELDS if key in item and key != "surface"}
        entry.update({"name": item["name"], "surface": surface})
        for key in ("texture", "texture_size"):
            if look.get(key):
                entry[key] = look[key]
        out.append(entry)
    return out


def _surfaces(f) -> list:
    from . import materials as M

    out = []
    for item in M.state(f)["surfaces"]:
        entry = {"name": item["name"]}
        for key in _SURFACE_FIELDS:
            if item.get(key) is not None:
                entry[key] = item[key]
        out.append(entry)
    return out


def _composites(f) -> list:
    from . import materials as M

    return [{"name": item["name"], "type": item.get("type") or "", "layers": copy.deepcopy(item.get("layers") or [])}
            for item in M.state(f)["composites"]]


def _counts(settings: dict, layers: list, materials: list, surfaces: list, composites: list) -> dict:
    counts = {group: len(settings.get(key) or {}) for group, key in SETTINGS_GROUPS.items()}
    counts.update({"layers": len(layers), "materials": len(materials), "surfaces": len(surfaces),
                   "composites": len(composites)})
    return counts


# ---------------------------------------------------------------- catalogue

def attribute_catalogue() -> str:
    """The open project's attribute groups and what each holds: pens, line types, ... and the IFC
    layers, materials, surfaces and composites, for the attribute manager's checklist."""
    if B._model is None:
        return _fail("no model open")
    from . import graphics, settings as S

    st = S.current()
    groups = {group: len(graphics.effective(key, st)) for group, key in SETTINGS_GROUPS.items()}
    try:
        layers, materials = _layers(B._model), _materials(B._model)
        surfaces, composites = _surfaces(B._model), _composites(B._model)
    except Exception as ex:  # an odd model must not stop the dialog
        return _fail(f"{type(ex).__name__}: {ex}")
    groups.update({"layers": len(layers), "materials": len(materials), "surfaces": len(surfaces),
                   "composites": len(composites)})
    return B._dump({
        "ok": True, "format": FORMAT, "groups": groups, "order": list(GROUPS),
        "layers": layers,
        "materials": [{"name": m["name"], "category": m.get("category") or "", "surface": m.get("surface") or ""}
                      for m in materials],
        "surfaces": [{"name": s["name"], "colour": s.get("colour") or ""} for s in surfaces],
        "composites": [{"name": c["name"], "type": c["type"], "layers": len(c["layers"])} for c in composites],
    })


# ---------------------------------------------------------------- export

def export_attributes(path: str) -> str:
    """Write the project's standards (settings tables, layers, materials, surfaces, composites) as one
    self-contained ``kimbim-attributes/1`` JSON file, ready to import into another project."""
    if B._model is None:
        return _fail("no model open")
    target = _text(path)
    if not target:
        return _fail("a file path is needed")
    from . import settings as S

    try:
        st = S.current()
        layers, materials = _layers(B._model), _materials(B._model)
        surfaces, composites = _surfaces(B._model), _composites(B._model)
    except Exception as ex:
        return _fail(f"{type(ex).__name__}: {ex}")
    settings = {}
    for key in SETTINGS_GROUPS.values():
        table = st.get(key)
        settings[key] = copy.deepcopy(table) if isinstance(table, dict) else {}
    data = {"format": FORMAT, "saved": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "settings": settings, "layers": layers, "materials": materials, "surfaces": surfaces,
            "composites": composites}
    try:
        out = pathlib.Path(target)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as ex:
        return _fail(f"cannot write {target}: {ex}")
    counts = _counts(settings, layers, materials, surfaces, composites)
    return B._dump({"ok": True, "path": str(out), "format": FORMAT, "saved": data["saved"], "counts": counts})


# ---------------------------------------------------------------- import: settings

def _purpose_problem(purpose: dict, st: dict) -> str | None:
    """What a purpose refers to that the settings don't have (graphics' own reference check, for one)."""
    from . import graphics

    tables = {"pen_set": ("pen_sets", "pen set"), "visibility": ("visibility_sets", "visibility set"),
              "overrides": ("override_sets", "override set"), "layers": ("layer_combinations", "layer combination"),
              "renovation": ("renovation_filters", "renovation filter")}
    for field, (key, label) in tables.items():
        name = purpose.get(field)
        if name is None:
            continue
        if name not in graphics.effective(key, st):
            return f"uses a {label} that doesn't exist: {name}"
    return None


def _merge_settings(data: dict, groups: list, replace: bool, skipped: list) -> tuple[dict, dict]:
    """(the settings changes, per-group counts) from the file's tables, merged over the project's own
    (effective: a table the project never customised starts from the built-ins, so importing one pen
    set keeps the others)."""
    from . import graphics, settings as S

    st = S.current()
    changes, imported = {}, {group: 0 for group in groups}
    settings_data = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    for group in groups:
        key = SETTINGS_GROUPS.get(group)
        if key is None:
            continue
        table = settings_data.get(key)
        if not isinstance(table, dict) or not table:
            continue
        current = graphics.effective(key, st)
        merged = copy.deepcopy(current)
        for name, value in table.items():
            if not isinstance(name, str) or not name.strip():
                skipped.append(f"{group}: an entry without a name")
                continue
            if name in current and not replace:
                skipped.append(f"{group}: {name} already exists")
                continue
            merged[name] = copy.deepcopy(value)
            imported[group] += 1
        if merged == current:
            continue
        changes[key] = merged
    # D84's purposes must point at sets that exist; a purpose whose set was not imported is left out.
    if "purposes" in changes:
        purposes = changes["purposes"]
        prospective = {**st, **changes}
        for name in list(purposes):
            if not isinstance(purposes[name], dict):
                continue  # validate() reports it
            problem = _purpose_problem(purposes[name], prospective)
            if problem is not None:
                del purposes[name]
                imported["purposes"] = max(0, imported["purposes"] - 1)
                skipped.append(f"purposes: {name} {problem}")
        if not purposes:
            del changes["purposes"]
    for key, merged in changes.items():
        if (err := graphics.validate(key, merged)) is not None:
            raise ValueError(f"{_label(key)}: {err}")
    return changes, imported


def _label(key: str) -> str:
    return next((group for group, value in SETTINGS_GROUPS.items() if value == key), key)


# ---------------------------------------------------------------- import: IFC

def _plan(data: dict, groups: list, replace: bool, skipped: list) -> dict:
    """Which IFC entities are new and which are updates, decided before the transaction starts (nothing
    changes between the plan and the step)."""
    from . import materials as M

    f = B._model
    plan = {"surfaces": [], "materials": [], "composites": [], "layers": []}

    def entries(key: str) -> list:
        value = data.get(key)
        return value if isinstance(value, list) else []

    surface_names = {s.Name for s in f.by_type("IfcSurfaceStyle") if s.Name}
    for entry in entries("surfaces") if "surfaces" in groups else []:
        if not isinstance(entry, dict):
            skipped.append("surfaces: an entry that is not an object")
            continue
        name = _text(entry.get("name"))
        if not name:
            skipped.append("surfaces: an entry without a name")
            continue
        existing = M._surface_by_name(f, name)
        if existing is not None and not replace:
            skipped.append(f"surfaces: {name} already exists")
            continue
        plan["surfaces"].append((entry, existing))
        surface_names.add(name)
    material_names = {m.Name for m in f.by_type("IfcMaterial") if m.Name}
    for entry in entries("materials") if "materials" in groups else []:
        if not isinstance(entry, dict):
            skipped.append("materials: an entry that is not an object")
            continue
        name = _text(entry.get("name"))
        if not name:
            skipped.append("materials: an entry without a name")
            continue
        existing = M._material_by_name(f, name)
        if existing is not None and not replace:
            skipped.append(f"materials: {name} already exists")
            continue
        item = {key: copy.deepcopy(entry[key]) for key in _MATERIAL_FIELDS if key in entry}
        item["name"] = name
        wanted = _text(item.get("surface"))
        if wanted and wanted not in surface_names:
            item.pop("surface", None)
            skipped.append(f"materials: {name} has no surface {wanted} (created without it)")
        plan["materials"].append((item, existing))
        material_names.add(name)
    for entry in entries("composites") if "composites" in groups else []:
        if not isinstance(entry, dict):
            skipped.append("composites: an entry that is not an object")
            continue
        name = _text(entry.get("name"))
        if not name:
            skipped.append("composites: an entry without a name")
            continue
        layers = entry.get("layers") or []
        if not isinstance(layers, list) or not layers:
            skipped.append(f"composites: {name} has no layers")
            continue
        if not all(isinstance(layer, dict) for layer in layers):
            skipped.append(f"composites: {name} has a layer that is not an object")
            continue
        missing = [_text(layer.get("material")) for layer in layers
                   if _text(layer.get("material")) not in material_names]
        if missing:
            skipped.append(f"composites: {name} needs the building materials {', '.join(missing)}")
            continue
        existing = next((ls for ls in f.by_type("IfcMaterialLayerSet") if ls.LayerSetName == name), None)
        if existing is not None and not replace:
            skipped.append(f"composites: {name} already exists")
            continue
        item = {"name": name, "type": entry.get("type") or "IfcWallType", "layers": copy.deepcopy(layers)}
        plan["composites"].append((item, existing))
    layer_names = {layer.Name for layer in f.by_type("IfcPresentationLayerAssignment") if layer.Name}
    for entry in entries("layers") if "layers" in groups else []:
        if not isinstance(entry, dict):
            skipped.append("layers: an entry that is not an object")
            continue
        name = _text(entry.get("name"))
        if not name:
            skipped.append("layers: an entry without a name")
            continue
        if name in layer_names:
            skipped.append(f"layers: {name} already exists")
            continue
        if entry.get("colour") or entry.get("weight") is not None:
            skipped.append(f"layers: {name} is imported without its colour and weight")
        plan["layers"].append(entry)
        layer_names.add(name)
    return plan


def _new_layer(f, name: str):
    """A layer (IfcPresentationLayerAssignment). KimBim assigns shape representations to layers, which an
    IfcPresentationLayerWithStyle may not hold (its ApplicableOnlyToItems rule), so a layer's colour and
    weight travel in the file for reference but are not applied here."""
    import ifcopenshell.api.layer

    return ifcopenshell.api.layer.add_layer(f, name=name)


def _apply_plan(plan: dict) -> tuple[int, list]:
    """Create and update the planned entities inside the caller's transaction: (count, touched guids)."""
    from . import materials as M

    f = B._model
    touched: set = set()
    count = 0
    for entry, existing in plan["surfaces"]:
        item = {"name": _text(entry.get("name"))}
        for key in _SURFACE_FIELDS:
            if key in entry:
                item[key] = copy.deepcopy(entry[key])
        if existing is not None:
            item["key"] = existing.id()
        M._apply_surface(f, item, touched)
        count += 1
    for item, existing in plan["materials"]:
        if existing is not None:
            item["key"] = existing.id()
        M._apply_material(f, item, touched)
        count += 1
    for item, existing in plan["composites"]:
        if existing is not None:
            item["key"] = existing.id()
        M._apply_composite(f, item, touched)
        count += 1
    for entry in plan["layers"]:
        _new_layer(f, _text(entry.get("name")))
        count += 1
    guids = [e.GlobalId for e in touched if getattr(e, "GlobalId", None)]
    return count, guids


# ---------------------------------------------------------------- import

def import_attributes(path: str, options_json: str = "") -> str:
    """Merge an attribute file into the open project. Options: ``groups`` (any of the catalogue's group
    names; default all) and ``replace`` (false: a name the project already has is kept). Settings
    tables merge by name and apply as one settings step; the IFC entities are one undo step."""
    if B._model is None:
        return _fail("no model open")
    try:
        options = json.loads(options_json) if (options_json or "").strip() else {}
    except ValueError as ex:
        return _fail(f"bad options: {ex}")
    if not isinstance(options, dict):
        return _fail("bad options: expected an object")
    groups = options.get("groups")
    if groups is None:
        groups = list(GROUPS)
    if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
        return _fail("bad options: groups is a list of group names")
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        return _fail(f"unknown attribute group {unknown[0]}")
    replace = bool(options.get("replace", False))
    target = _text(path)
    if not target:
        return _fail("a file path is needed")
    try:
        data = json.loads(pathlib.Path(target).read_text(encoding="utf-8"))
    except OSError as ex:
        return _fail(f"cannot read {target}: {ex}")
    except ValueError as ex:
        return _fail(f"{target} is not an attribute file: {ex}")
    if not isinstance(data, dict):
        return _fail(f"{target} is not an attribute file: expected an object")
    if data.get("format") != FORMAT:
        return _fail(f"{target} is not an attribute file: unknown format {data.get('format')!r}")

    from . import settings as S

    skipped: list = []
    try:
        changes, imported = _merge_settings(data, groups, replace, skipped)
    except ValueError as ex:
        return _fail(str(ex))
    except Exception as ex:  # a corrupt table must not take the app down
        return _fail(f"{type(ex).__name__}: {ex}")
    before = S.current()
    settings_step = bool(changes)
    if settings_step:
        r = json.loads(S.set_project_settings(json.dumps(changes)))
        if not r.get("ok"):
            return _fail(r.get("error") or "the settings could not be imported")
    for group in IFC_GROUPS:
        imported.setdefault(group, 0)
    if any(group in groups for group in IFC_GROUPS):
        try:
            plan = _plan(data, groups, replace, skipped)
        except Exception as ex:
            if settings_step:
                S.restore(before)
            return _fail(f"{type(ex).__name__}: {ex}")
        for group in IFC_GROUPS:
            imported[group] = len(plan[group])
        if any(plan[group] for group in IFC_GROUPS):
            try:
                r = B._run(lambda: (*_apply_plan(plan), []))
            except Exception as ex:
                if settings_step:
                    S.restore(before)
                message = str(ex) if isinstance(ex, ValueError) else f"{type(ex).__name__}: {ex}"
                return _fail(message)
            imported["changed"] = r.get("changed", 0)
    return B._dump({"ok": True, "path": str(pathlib.Path(target)), "format": FORMAT, "imported": imported,
                    "skipped": skipped, "settings": settings_step,
                    "dirty": B._dirty()})
