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
    "KIMCAD cannot start": "KIMCAD no puede iniciarse",
    "Model": "Modelo",
    "Properties": "Propiedades",
    "Open IFC": "Abrir IFC",
    "IFC files (*.ifc)": "Archivos IFC (*.ifc)",
    "Opening %1...": "Abriendo %1...",
    "Loading %1 (%2)...": "Cargando %1 (%2)...",
    "Could not open the model": "No se pudo abrir el modelo",
    "Search name, type or GlobalId": "Buscar nombre, tipo o GlobalId",
    "Name": "Nombre",
    "Type": "Tipo",
    "Isolate": "Aislar",
    "Hide": "Ocultar",
    "Show all": "Mostrar todo",
    "Yes": "Sí",
    "No": "No",
    "Property": "Propiedad",
    "Value": "Valor",
    "Error": "Error",
    "Element": "Elemento",
    # plural forms: (singular, plural)
    "Loading... %n element(s)": ("Cargando... %n elemento", "Cargando... %n elementos"),
    "%n element(s) loaded in %1 s": ("%n elemento cargado en %1 s", "%n elementos cargados en %1 s"),
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
            value = ES[src]
            if msg.get("numerus") == "yes":
                for child in list(tr):
                    tr.remove(child)
                tr.text = None
                for form in value if isinstance(value, tuple) else (value, value):
                    ET.SubElement(tr, "numerusform").text = form
            else:
                tr.text = value
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
