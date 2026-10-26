# SPDX-License-Identifier: GPL-3.0-or-later
"""EN/ES message text for agent tool errors and CLI output (D102). Codes and JSON keys stay English."""
import json
import locale
import os
import sys
from pathlib import Path

MESSAGES = {
    "no_model": {"en": "No project is open.", "es": "No hay ningún proyecto abierto."},
    "no_match": {"en": "Nothing matches.", "es": "No hay coincidencias."},
    "bad_input": {"en": "Invalid input.", "es": "Entrada no válida."},
    "bad_length": {"en": "Not a length: {value}", "es": "No es una longitud: {value}"},
    "bridge_error": {"en": "The command failed.", "es": "El comando falló."},
    "not_versioned": {"en": "The project has no version history.", "es": "El proyecto no tiene historial de versiones."},
    "task_busy": {"en": "A task is already open; finish or cancel it first.",
                  "es": "Ya hay una tarea abierta; termínala o cancélala primero."},
    "no_task": {"en": "There is no open task.", "es": "No hay ninguna tarea abierta."},
    "ambiguous_task": {"en": "More than one task is open; say which one.",
                       "es": "Hay más de una tarea abierta; indica cuál."},
    "unknown_task": {"en": "Unknown task: {task}", "es": "Tarea desconocida: {task}"},
    "project_locked": {"en": "The project is open in another process.",
                       "es": "El proyecto está abierto en otro proceso."},
    "setting_reserved": {"en": "That setting can only be changed by the user.",
                         "es": "Esa configuración solo la puede cambiar el usuario."},
    "scripts_off": {"en": "Scripts are turned off for this project.",
                    "es": "Los scripts están desactivados en este proyecto."},
    "needs_app": {"en": "This needs the KimBim app to be running.",
                  "es": "Esto requiere que la aplicación KimBim esté en ejecución."},
    "render_failed": {"en": "The view could not be rendered.", "es": "No se pudo generar la vista."},
    "unknown_tool": {"en": "Unknown tool: {tool}", "es": "Herramienta desconocida: {tool}"},
    "not_found": {"en": "Not found: {what}", "es": "No se encontró: {what}"},
    # hints for bad_input (catalogue.validate)
    "hint_required": {"en": "Missing {field}.", "es": "Falta {field}."},
    "hint_unknown_field": {"en": "Unknown field {field}.", "es": "Campo desconocido {field}."},
    "hint_type": {"en": "{field} must be {type}.", "es": "{field} debe ser {type}."},
    "hint_enum": {"en": "{field} must be one of: {values}.", "es": "{field} debe ser uno de: {values}."},
    "hint_range": {"en": "{field} must be between {minimum} and {maximum}.",
                   "es": "{field} debe estar entre {minimum} y {maximum}."},
    "hint_form": {"en": "{field} does not have an accepted form.", "es": "{field} no tiene una forma aceptada."},
    "hint_open_step": {"en": "Write tools can't run inside another undo step (a console run or edit() block).",
                       "es": "Las herramientas de escritura no pueden ejecutarse dentro de otro paso de deshacer "
                             "(una ejecución de la consola o un bloque edit())."},
}

_ORG = _APP = "KimBim"  # app/src/main.cpp


def _prefs_path():
    """Same file as Preferences::defaultPath() (QStandardPaths AppConfigLocation)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Preferences"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / _ORG / _APP / "preferences.json"


def language():
    """"en" or "es": KIMBIM_LANG, the app preference, the system locale, else en."""
    env = os.environ.get("KIMBIM_LANG", "").strip().lower()
    if env[:2] in ("en", "es"):
        return env[:2]
    try:
        pref = str(json.loads(_prefs_path().read_text(encoding="utf-8")).get("language", "")).lower()
        if pref[:2] in ("en", "es"):
            return pref[:2]
    except (OSError, ValueError, AttributeError):
        pass
    try:
        loc = (locale.getlocale()[0] or "").lower()
    except ValueError:
        loc = ""
    return "es" if loc.startswith("es") else "en"


def text(code, **fmt):
    """The message for `code` in the current language; an unknown code returns the code."""
    entry = MESSAGES.get(code)
    if entry is None:
        return code
    s = entry[language()]
    try:
        return s.format(**fmt)
    except (KeyError, IndexError):
        return s
