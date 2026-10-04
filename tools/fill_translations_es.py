# SPDX-License-Identifier: GPL-3.0-or-later
"""Fill app/translations/kimcad_es.ts from the Spanish glossary below.

Workflow: `pixi run cmake --build build/app --target update_translations` (lupdate), then
`python tools/fill_translations_es.py`, then `pixi run check-translations`.
Architect vocabulary (docs/00): version = "versión", design option = "opción de diseño".
"""
import pathlib
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
TS = ROOT / "app" / "translations" / "kimcad_es.ts"

ES = {
    "&File": "&Archivo",
    "&Open IFC...": "&Abrir IFC...",
    "&Quit": "&Salir",
    "&View": "&Ver",
    "&Fit all": "&Encuadrar todo",
    "&Help": "A&yuda",
    "&About KIMCAD": "&Acerca de KIMCAD",
    "About KIMCAD": "Acerca de KIMCAD",
    "Ready": "Listo",
    "KIMCAD %1\nOpen-source native BIM for architects, with version control built in.\nLicense: GPL-3.0-or-later":
        "KIMCAD %1\nBIM nativo de código abierto para arquitectos, con control de versiones integrado.\n"
        "Licencia: GPL-3.0 o posterior",
}


def main():
    tree = ET.parse(TS)
    filled = missing = 0
    for msg in tree.getroot().iter("message"):
        src = msg.findtext("source")
        tr = msg.find("translation")
        if tr is None or tr.get("type") in ("obsolete", "vanished"):
            continue
        if src in ES:
            tr.text = ES[src]
            tr.attrib.pop("type", None)
            filled += 1
        elif tr.get("type") == "unfinished" or not (tr.text or "").strip():
            missing += 1
            print(f"no Spanish for: {src!r}")
    ET.indent(tree)
    tree.write(TS, encoding="utf-8", xml_declaration=True)
    print(f"filled {filled}, missing {missing}")


if __name__ == "__main__":
    main()
