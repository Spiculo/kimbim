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
    "&Hide selected": "&Ocultar selección",
    "&Isolate selected": "A&islar selección",
    "&Show all": "&Mostrar todo",
    "&Plan cut": "&Corte en planta",
    "Section &box": "Caja de &sección",
    "Cuts": "Cortes",
    "Plan cut height": "Altura del corte en planta",
    "&Save": "&Guardar",
    "Save &As...": "Guardar &como...",
    "&Edit": "&Edición",
    "&Undo": "&Deshacer",
    "&Redo": "&Rehacer",
    "Could not change %1": "No se pudo cambiar %1",
    "Could not save": "No se pudo guardar",
    "Saved %1": "Guardado %1",
    "Save IFC": "Guardar IFC",
    "Unsaved changes": "Cambios sin guardar",
    "The model has unsaved changes. Save them?": "El modelo tiene cambios sin guardar. ¿Guardarlos?",
    "Add property": "Añadir propiedad",
    "Property name in %1:": "Nombre de la propiedad en %1:",
    "Value:": "Valor:",
    "Add property set": "Añadir conjunto de propiedades",
    "Property set (standard or custom):": "Conjunto de propiedades (estándar o propio):",
    "(varies)": "(varía)",
    "Add property to %1...": "Añadir propiedad a %1...",
    "Remove property %1": "Quitar la propiedad %1",
    "Add property set...": "Añadir conjunto de propiedades...",
    "%n element(s)": ("%n elemento", "%n elementos"),
    "Inherited from the element's type": "Heredado del tipo del elemento",
    "Overrides the type value: %1": "Sustituye el valor del tipo: %1",
    "Some selected elements use their type's value": "Algunos elementos seleccionados usan el valor de su tipo",
    "Edit type value...": "Editar valor del tipo...",
    "Reset to type value": "Volver al valor del tipo",
    "Edit type value": "Editar valor del tipo",
    "%1 on type %2:": "%1 en el tipo %2:",
    "%1 changed on the type: %n element(s) updated": ("%1 cambiado en el tipo: %n elemento actualizado", "%1 cambiado en el tipo: %n elementos actualizados"),
    "This changes %1 for %n element(s) of this type, including elements that are not selected.": ("Esto cambia %1 en %n elemento de este tipo, incluidos los no seleccionados.", "Esto cambia %1 en %n elementos de este tipo, incluidos los no seleccionados."),
    "%n selected element(s) have no type and will not change.": ("%n elemento seleccionado no tiene tipo y no cambiará.", "%n elementos seleccionados no tienen tipo y no cambiarán."),
    "&Delete": "&Eliminar",
    "Could not delete": "No se pudo eliminar",
    "Could not update the 3D view": "No se pudo actualizar la vista 3D",
    "Add level...": "Añadir nivel...",
    "Level": "Nivel",
    "Levels": "Niveles",
    "&New project": "&Nuevo proyecto",
    "&Plan view": "Vista en &planta",
    "&3D view": "Vista &3D",
    "Untitled": "Sin título",
    "Could not create the project": "No se pudo crear el proyecto",
    "New project": "Proyecto nuevo",
    "Could not add the level": "No se pudo añadir el nivel",
    "Add level": "Añadir nivel",
    "Name:": "Nombre:",
    "Level %1": "Nivel %1",
    "Elevation (m):": "Cota (m):",
    "Modeling": "Modelado",
    "&Wall": "&Muro",
    "Draw walls: click points, type a length + Enter, Esc to finish. Shift: right angles.": "Dibujar muros: haga clic en puntos, escriba una longitud + Intro, Esc para terminar. Mayús: ángulos rectos.",
    "Wall type": "Tipo de muro",
    "Wall height": "Altura del muro",
    "Length (m)": "Longitud (m)",
    "endpoint": "extremo",
    "midpoint": "punto medio",
    "perpendicular": "perpendicular",
    "on wall": "sobre muro",
    "angle": "ángulo",
    "grid": "rejilla",
    "Wall: click the next point, type a length, Esc to finish": "Muro: haga clic en el siguiente punto, escriba una longitud, Esc para terminar",
    "Length %1 m": "Longitud %1 m",
    "Cannot draw walls": "No se pueden dibujar muros",
    "The model has no level. Add a level first.": "El modelo no tiene niveles. Añada un nivel primero.",
    "Wall: click the start point": "Muro: haga clic en el punto inicial",
    "Could not create the wall: %1": "No se pudo crear el muro: %1",
    "&Lines only": "Solo &líneas",
    "Show the model as a line drawing (hidden lines removed), e.g. for plans": "Mostrar el modelo como dibujo de líneas (sin líneas ocultas), p. ej. para plantas",
    # plural forms: (singular, plural)
    "Loading... %n element(s)": ("Cargando... %n elemento", "Cargando... %n elementos"),
    "%n element(s) selected": ("%n elemento seleccionado", "%n elementos seleccionados"),
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
