# SPDX-License-Identifier: GPL-3.0-or-later
"""Library objects as data (D99, doc 16): the `.kimobj` format (`kimbim-object/1`), its parameters
and definitions. A definition is JSON the app reads; nothing in it runs. Geometry: objbuild.py."""
from __future__ import annotations

import functools
import json
import math
import pathlib
import re

import blake3

from . import objbuild
from .objbuild import ObjectError
from .objexpr import FormulaError, value_of

FORMAT = "kimbim-object/1"
KINDS = ("length", "angle", "count", "bool", "choice", "material")
CATEGORIES = ("furniture", "sanitary", "kitchen", "site", "office")
MAX_FILE_BYTES = 1_000_000
_FIELDS = {"format", "id", "name", "category", "ifc", "origin", "params", "materials", "parts", "components", "symbol"}
_PARAM_FIELDS = {"key", "kind", "label", "default", "min", "max", "options", "show_when", "group"}
_RESERVED = {"i", "n", "pi", "and", "or", "not", "true", "false", "if"}
_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_LIMITS = {"length": (0.01, 50.0), "angle": (-360.0, 360.0), "count": (1, 20)}
_TRUE = {"1", "true", "yes", "on", "sí", "si"}
_FALSE = {"0", "false", "no", "off", ""}


def canonical(data) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(text: str) -> str:
    return blake3.blake3(text.encode("utf-8")).hexdigest()[:32]


def _label(v, where: str) -> dict:
    if isinstance(v, str) and v.strip():
        return {"en": v, "es": v}
    if isinstance(v, dict) and isinstance(v.get("en"), str) and v["en"].strip():
        return {"en": v["en"], "es": str(v.get("es") or v["en"])}
    raise ObjectError(f"{where}: a label is text or {{\"en\": ..., \"es\": ...}}")


class ParamDef:
    def __init__(self, data: dict, where: str):
        if not isinstance(data, dict):
            raise ObjectError(f"{where}: a parameter is an object")
        key = data.get("key")
        if not isinstance(key, str) or not _KEY.match(key):
            raise ObjectError(f"{where}: key must be lower-case letters, digits and _")
        where = f"{where[:where.rfind('[')] if '[' in where else where}.{key}"
        if key in _RESERVED:
            raise ObjectError(f"{where}: {key!r} is reserved")
        unknown = set(data) - _PARAM_FIELDS
        if unknown:
            raise ObjectError(f"{where}: unknown field {sorted(unknown)[0]!r}")
        self.key, self.kind = key, data.get("kind")
        if self.kind not in KINDS:
            raise ObjectError(f"{where}: unknown kind {self.kind!r} (one of {', '.join(KINDS)})")
        self.label = _label(data.get("label", key), f"{where}.label")
        self.group, self.show_when = data.get("group"), data.get("show_when")
        lo, hi = _LIMITS.get(self.kind, (None, None))
        self.lo, self.hi = data.get("min", lo), data.get("max", hi)
        self.options = []
        if self.kind == "choice":
            for o in data.get("options") or ():
                if not isinstance(o, dict) or not isinstance(o.get("id"), str):
                    raise ObjectError(f"{where}.options: each option has an id and a label")
                self.options.append((o["id"], _label(o.get("label", o["id"]), f"{where}.options.{o['id']}")))
            if not self.options:
                raise ObjectError(f"{where}: a choice needs options")
        if "default" not in data:
            raise ObjectError(f"{where}: default is missing")
        self.default = data["default"]
        if self.kind == "choice" and self.default not in [i for i, _ in self.options]:
            raise ObjectError(f"{where}: default {self.default!r} is not one of the options")
        self.where = where

    def bounds(self, env, lenient: bool = False) -> tuple:
        """The limits; lenient: one that cannot evaluate yet (names a later parameter) is absent."""
        out = []
        for raw in (self.lo, self.hi):
            try:
                out.append(value_of(raw, env) if raw is not None else None)
            except FormulaError as ex:
                if not lenient:
                    raise ObjectError(f"{self.where}: {ex}") from None
                out.append(None)
        return tuple(out)

    def option_label(self, value_id: str, lang: str = "en") -> str:
        return next((label[lang] for i, label in self.options if i == value_id), str(value_id))

    def clean(self, value, env, lenient: bool = False):
        """The value as this kind (text from the UI too), clamped to the limits."""
        if self.kind == "material":
            return str(value).strip() or str(self.default)
        if self.kind == "choice":
            text = str(value).strip().lower()
            for i, label in self.options:
                if text in (i.lower(), label["en"].lower(), label["es"].lower()):
                    return i
            return self.default
        if self.kind == "bool":
            if isinstance(value, str):
                t = value.strip().lower()
                return True if t in _TRUE else False if t in _FALSE else bool(self.default)
            return bool(value)
        v = float(str(value).replace(",", ".")) if isinstance(value, str) else float(value)
        if not math.isfinite(v):
            raise ValueError("not a finite number")
        lo, hi = self.bounds(env, lenient)
        if self.kind == "count":
            v = int(round(v))
            lo = math.ceil(lo) if lo is not None else None
            hi = math.floor(hi) if hi is not None else None
        else:
            v = round(v, 4)
        if lo is not None:
            v = max(v, lo)
        if hi is not None:
            v = min(v, hi)
        return int(v) if self.kind == "count" else float(v)

    def text_of(self, value) -> str:
        """For type names: a count, choice, bool or material as written, a length in mm, an angle in °."""
        if self.kind == "length":
            return str(int(round(value * 1000)))
        if self.kind == "angle":
            return f"{value:g}°"
        if self.kind == "bool":
            return "yes" if value else "no"
        if self.kind == "choice":
            return self.option_label(value)
        return str(value)


def _params(raw, where) -> list:
    if not isinstance(raw, list):
        raise ObjectError(f"{where}: a list of parameters")
    out = [ParamDef(p, f"{where}[{k}]") for k, p in enumerate(raw)]
    seen = set()
    for p in out:
        if p.key in seen:
            raise ObjectError(f"{where}.{p.key}: the key is used twice")
        seen.add(p.key)
    return out


def _values(params, given) -> dict:
    """Two passes, both over cleaned values. Pass 1 in order: the given value, else the default (a formula
    over the values before it), cleaned; a limit that names a later parameter is skipped. Pass 2 cleans
    every value again with all of them known, so such limits apply. A given value that cannot be read
    falls back to the default."""
    given = given or {}
    done = {"pi": math.pi}

    def default_of(p):
        if isinstance(p.default, str) and p.kind not in ("choice", "material"):
            try:
                return value_of(p.default, done)
            except FormulaError as ex:
                raise ObjectError(f"{p.where}.default: {ex}") from None
        return p.default

    def clean(p, value, env, lenient):
        try:
            return p.clean(value, env, lenient)
        except (TypeError, ValueError, FormulaError):
            return p.clean(default_of(p), env, lenient)

    for p in params:
        done[p.key] = clean(p, given[p.key] if p.key in given else default_of(p), done, True)
    final = dict(done)
    for p in params:
        final[p.key] = clean(p, done[p.key], final, False)
    final.pop("pi")
    return final


class ComponentDef:
    """A part group inside an object file: an object without IFC class, origin or symbol."""

    def __init__(self, name: str, data: dict, where: str):
        if not isinstance(data, dict):
            raise ObjectError(f"{where}: a component is an object")
        unknown = set(data) - {"params", "parts"}
        if unknown:
            raise ObjectError(f"{where}: unknown field {sorted(unknown)[0]!r}")
        self.key, self.where = name, where
        self.params = _params(data.get("params", []), f"{where}.params")
        self.parts = data.get("parts", [])
        self.components = {}

    def values(self, given=None) -> dict:
        return _values(self.params, given)


class ObjectDef:
    def __init__(self, data: dict, source: str = "bundled", library: str = "", check: bool = True):
        if not isinstance(data, dict):
            raise ObjectError("an object file holds one JSON object")
        if data.get("format") != FORMAT:
            raise ObjectError(f"format: must be {FORMAT!r}")
        unknown = set(data) - _FIELDS
        if unknown:
            raise ObjectError(f"unknown field {sorted(unknown)[0]!r}")
        key = data.get("id")
        if not isinstance(key, str) or not _KEY.match(key):
            raise ObjectError("id: lower-case letters, digits and _")
        self.key, self.source, self.library = key, source, library
        self.ref = key if source == "bundled" else f"{source}:{key}"
        self.names = _label(data.get("name", key), "name")
        self.name = self.names["en"]
        self.category = data.get("category", "furniture")
        if self.category not in CATEGORIES:
            raise ObjectError(f"category: one of {', '.join(CATEGORIES)}")
        ifc = data.get("ifc") or {}
        if not isinstance(ifc, dict) or not all(isinstance(v, (list, tuple)) for v in ifc.values()):
            raise ObjectError("ifc: an object of schema -> [type class, predefined type, element type]")
        if "IFC4" not in ifc:
            raise ObjectError("ifc: an IFC4 entry [type class, predefined type, element type] is required")
        self.ifc = {k: tuple(v) for k, v in ifc.items()}
        try:
            self.origin = tuple(float(v) for v in data.get("origin", (0.0, 0.0)))
            if len(self.origin) != 2:
                raise ValueError
        except (TypeError, ValueError):
            raise ObjectError("origin: two numbers [x, y]") from None
        self.params = _params(data.get("params", []), "params")
        self.materials = {}
        for slot, m in (data.get("materials") or {}).items():
            if not _KEY.match(slot) or not isinstance(m, dict) or not m.get("default"):
                raise ObjectError(f"materials.{slot}: needs a label and a default building material")
            self.materials[slot] = (_label(m.get("label", "Material"), f"materials.{slot}.label"), m["default"])
            self.params.append(ParamDef({"key": f"mat_{slot}", "kind": "material", "label": m.get("label", "Material"),
                                         "default": m["default"]}, f"materials.{slot}"))
        labels = {}
        for p in self.params:  # Properties lists parameters by label: two must not share one
            if p.label["en"].lower() in labels:
                raise ObjectError(f"{p.where}: the label {p.label['en']!r} is used twice")
            labels[p.label["en"].lower()] = p.key
        self.parts = data.get("parts", [])
        if not isinstance(self.parts, list):
            raise ObjectError("parts: a list")
        self.components = {name: ComponentDef(name, c, f"components.{name}")
                           for name, c in (data.get("components") or {}).items()}
        self.symbol = data.get("symbol")
        self.text = canonical(data)
        self.hash = digest(self.text)
        self.data = data
        if check:
            objbuild.check(self)
            self.shape(self.values(), all_anchors=True)  # a definition must build at its defaults

    def param(self, key_or_label: str):
        k = (key_or_label or "").strip().lower()
        return next((p for p in self.params if p.key == k or p.label["en"].lower() == k
                     or p.label["es"].lower() == k), None)

    def values(self, given=None) -> dict:
        return _values(self.params, given)

    def visible(self, values: dict) -> list:
        out = []
        for p in self.params:
            try:
                shown = p.show_when is None or bool(value_of(p.show_when, {**values, "pi": math.pi}))
            except FormulaError:
                shown = True
            if shown:
                out.append(p.key)
        return out

    resolver = None  # `use` of other library objects: library.py sets it to library._resolve

    def shape(self, values: dict, all_anchors: bool = False):
        return objbuild.build(self, values, type(self).resolver, all_anchors=all_anchors)

    def material_of(self, values: dict, part: str) -> str | None:
        """The building material of one slot: its parameter, else the object's main one, else None."""
        if f"mat_{part}" in values:
            return values[f"mat_{part}"]
        if "mat_body" in values:
            return values["mat_body"]
        first = next(iter(self.materials), None)
        return values.get(f"mat_{first}") if first else None

    def type_name(self, values: dict) -> str:
        """`Chair 450x500x850 (Legs 3, Splay 8°)`: sizes, then every other value that is not its default.
        Material slots are left out (a type per material already differs by its Parameters)."""
        mm = lambda v: str(int(round(v * 1000)))  # noqa: E731
        name = f"{self.name} {'x'.join(mm(values[k]) for k in ('width', 'depth', 'height') if k in values)}".rstrip()
        defaults = self.values()
        extra = [f"{p.label['en']} {p.text_of(values[p.key])}" for p in self.params
                 if p.key not in ("width", "depth", "height") and not p.key.startswith("mat_")
                 and values[p.key] != defaults[p.key]]
        return name + (f" ({', '.join(extra)})" if extra else "")

    def ifc_for(self, schema: str):
        return self.ifc.get("IFC2X3" if schema == "IFC2X3" else "IFC4") or self.ifc["IFC4"]


def load(data: dict, source: str = "bundled", library: str = "", check: bool = True) -> ObjectDef:
    return ObjectDef(data, source, library, check)


def load_file(path: str, source: str, check: bool = True) -> ObjectDef:
    p = pathlib.Path(path)
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            raise ObjectError(f"file too large (at most {MAX_FILE_BYTES // 1000} kB)")
        data = json.loads(p.read_text(encoding="utf-8"))
        return ObjectDef(data, source, str(p), check)
    except (OSError, ValueError) as ex:
        raise ObjectError(f"{p.name}: {ex}") from None


@functools.lru_cache(maxsize=512)
def _from_text(text: str, source: str, library: str, ref: str) -> ObjectDef:
    d = ObjectDef(json.loads(text), source, library, check=False)
    if ref:
        d.ref = ref
    return d


def from_text(text: str, source: str, library: str = "", ref: str = "") -> ObjectDef:
    """A definition stored in a model (its type's Definition): parsed once per text and ref (two refs
    with the same text stay two definitions)."""
    return _from_text(text, source, library, ref)
