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
    "Select &hidden elements too": "Seleccionar también elementos &ocultos",
    "Box selection also takes elements hidden behind others (same as holding Alt while dragging)": "La selección por ventana también toma elementos ocultos detrás de otros (igual que mantener Alt al arrastrar)",
    "&Model": "&Modelo",
    "&Slab": "&Losa",
    "Draw a slab outline: click points, click the first point or press Enter to close, Esc to cancel": "Dibujar el contorno de una losa: haga clic en puntos, en el primero o pulse Intro para cerrar, Esc para cancelar",
    "&Door": "&Puerta",
    "Place doors: click on a wall": "Colocar puertas: haga clic en un muro",
    "Wi&ndow": "Ve&ntana",
    "Place windows: click on a wall": "Colocar ventanas: haga clic en un muro",
    "Slab from selected &walls": "Losa desde los &muros seleccionados",
    "Type": "Tipo",
    "Cannot model": "No se puede modelar",
    "Slab: click the outline's points; click the first point or press Enter to close": "Losa: haga clic en los puntos del contorno; en el primero o Intro para cerrar",
    "Click on a wall to place it": "Haga clic en un muro para colocarlo",
    "Could not create the slab: %1": "No se pudo crear la losa: %1",
    "Cannot make a slab from these walls": "No se puede crear una losa con estos muros",
    "Could not place it: %1": "No se pudo colocar: %1",
    "The model may be inconsistent": "El modelo puede estar inconsistente",
    "An edit failed and could not be undone. Save a copy if you need it, then reopen the file.": "Una edición falló y no se pudo deshacer. Guarde una copia si la necesita y vuelva a abrir el archivo.",
    "The outline crosses itself": "El contorno se cruza consigo mismo",
    "&Column": "&Pilar",
    "Place columns: click a point (snaps to grid crossings); Shift turns it 90 degrees": "Colocar pilares: haga clic en un punto (se ajusta a los cruces de ejes); Mayús lo gira 90 grados",
    "&Beam": "&Viga",
    "Draw a beam: click its two ends; its top is at the level plus the height field": "Dibujar una viga: haga clic en sus dos extremos; su cara superior queda en el nivel más el campo de altura",
    "&Grid line": "&Eje de rejilla",
    "Draw a grid line: click its two ends (tags A, B... and 1, 2... are automatic)": "Dibujar un eje: haga clic en sus dos extremos (las etiquetas A, B... y 1, 2... son automáticas)",
    "grid crossing": "cruce de ejes",
    "on grid line": "sobre eje",
    "Column: click to place it": "Pilar: haga clic para colocarlo",
    "Click the first point": "Haga clic en el primer punto",
    "Could not create it: %1": "No se pudo crear: %1",
    "&Move": "&Mover",
    "Move the selection: click a base point, then where it goes; joined walls follow (Ctrl: detach)": "Mover la selección: haga clic en un punto base y luego en el destino; los muros unidos acompañan (Ctrl: separar)",
    "&Rotate": "&Girar",
    "Rotate the selection: click the centre, a reference, then the new direction (or type degrees)": "Girar la selección: haga clic en el centro, una referencia y la nueva dirección (o escriba los grados)",
    "S&tretch wall": "&Estirar muro",
    "Stretch a wall: click near one of its ends, then click its new position (or type the length)": "Estirar un muro: haga clic cerca de un extremo y luego en su nueva posición (o escriba la longitud)",
    "Wall &height...": "&Altura del muro...",
    "Door/window si&ze...": "&Tamaño de puerta/ventana...",
    "Angle (degrees)": "Ángulo (grados)",
    "Select something first, then move or rotate it": "Seleccione algo primero y luego muévalo o gírelo",
    "Move: click a base point, then where it goes (Ctrl: detach joined walls)": "Mover: haga clic en un punto base y luego en el destino (Ctrl: separar los muros unidos)",
    "Rotate: click the centre, then a reference direction, then the new direction": "Girar: haga clic en el centro, luego en una dirección de referencia y luego en la nueva dirección",
    "Stretch: click near a wall end, then its new position": "Estirar: haga clic cerca del extremo de un muro y luego en su nueva posición",
    "Could not move: %1": "No se pudo mover: %1",
    "Could not rotate: %1": "No se pudo girar: %1",
    "Could not stretch: %1": "No se pudo estirar: %1",
    "Could not change the height: %1": "No se pudo cambiar la altura: %1",
    "Select one door or window on the active level": "Seleccione una puerta o ventana del nivel activo",
    "Could not resize: %1": "No se pudo cambiar el tamaño: %1",
    "Select one or more walls first": "Seleccione uno o más muros primero",
    "Wall height": "Altura del muro",
    "Height (m):": "Altura (m):",
    "Door/window size": "Tamaño de puerta/ventana",
    "Width:": "Ancho:",
    "Height:": "Alto:",
    "Sill height:": "Altura del alféizar:",
    "S&tair": "Es&calera",
    "Draw a stair: click where it starts, then the direction it climbs; it goes up to the next level": "Dibujar una escalera: haga clic donde empieza y luego en la dirección en que sube; llega al nivel siguiente",
    "Slab &opening": "&Hueco en losa",
    "Cut a hole in the selected slab: draw its outline like a slab": "Abrir un hueco en la losa seleccionada: dibuje su contorno como una losa",
    "Copy to &level...": "Copiar a &nivel...",
    "Select one slab first, then draw the opening": "Seleccione una losa primero y luego dibuje el hueco",
    "Stair: click where it starts, then the direction it climbs": "Escalera: haga clic donde empieza y luego en la dirección en que sube",
    "Slab opening: draw the hole's outline; click the first point or press Enter to close": "Hueco en losa: dibuje el contorno; haga clic en el primer punto o pulse Intro para cerrar",
    "Could not create the stair: %1": "No se pudo crear la escalera: %1",
    "Stair: %1 risers of %2 m": "Escalera: %1 contrahuellas de %2 m",
    "Could not cut the opening: %1": "No se pudo abrir el hueco: %1",
    "Could not copy": "No se pudo copiar",
    "%n element(s) copied": ("%n elemento copiado", "%n elementos copiados"),
    "Select what to copy first": "Seleccione primero lo que quiere copiar",
    "Copy to level": "Copiar a nivel",
    "Copy the selection to:": "Copiar la selección a:",
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
