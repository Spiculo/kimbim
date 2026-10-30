# SPDX-License-Identifier: GPL-3.0-or-later
"""Model tools: a unit drawn once in a model container and placed on many levels (D58). Editing the
model refreshes every placement automatically; these tools let an agent create, place and inspect it."""
from __future__ import annotations

from ... import authoring as A
from ..catalogue import AgentError, bridge, tool
from .common import level_guid, point

_MODEL = {"type": "string", "description": "Model name or GlobalId (models.list lists them)."}
_LEVEL = {"type": "string", "description": "Building level name or GlobalId."}
_POINT = {"type": "array", "items": {"type": ["number", "string"]},
          "description": "[x, y] in project units or strings with units."}


def _model_guid(ref) -> str:
    want = str(ref).strip().lower()
    for model in bridge(A.models)["models"]:
        if model["guid"] == ref or model["name"].strip().lower() == want:
            return model["guid"]
    raise AgentError("not_found", what=ref)


@tool("models.list", {})
def list_models(session):
    """List the project's models (units drawn once and placed on levels) with their GlobalId, name,
    elevation and how many places use them."""
    return bridge(A.models)


@tool("models.create", {"required": ["name"], "properties": {
    "name": {"type": "string", "description": "The model's name, e.g. \"Apartment A\"."}}}, writes=True)
def create(session, name):
    """Create an empty model container below the building; draw the unit in it, then place it on levels."""
    return bridge(A.create_model, name)


@tool("models.place", {"required": ["model", "level", "at"], "properties": {
    "model": _MODEL, "level": _LEVEL, "at": _POINT,
    "angle": {"type": "number", "description": "Rotation in radians (default 0)."}}}, writes=True)
def place(session, model, level, at, angle=0.0):
    """Place a model on a building level as one linked instance (a copy of its elements that follows
    later edits to the model)."""
    try:
        angle = float(angle or 0.0)
    except (TypeError, ValueError):
        raise AgentError("bad_input", hint="angle must be a number in radians") from None
    x, y = point(session, at)
    return bridge(A.place_model, _model_guid(model), level_guid(level), x, y, angle)


@tool("models.update", {"required": ["model"], "properties": {"model": _MODEL}}, writes=True)
def update(session, model):
    """Apply the model's current content to every place it is used; edits already do this automatically,
    so this is for a project loaded with stale instances."""
    return bridge(A.update_model_instances, _model_guid(model))


@tool("models.explode", {"required": ["instance"], "properties": {
    "instance": {"type": "string", "description": "The instance id models.place or models.list printed."}}},
    writes=True)
def explode(session, instance):
    """Unlink an instance: its elements become ordinary elements that no longer follow the model."""
    return bridge(A.explode_instance, instance)
