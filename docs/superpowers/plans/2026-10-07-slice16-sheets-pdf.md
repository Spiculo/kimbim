# Slice 16 (M4 exit) — Sheets, project info, PDF and SVG export

**Goal / M4 exit:** the sample two-storey house produces a plan, a section and an elevation on a sheet with a
title block, exported to PDF; CI checks it automatically (`pixi run m4`).

## Decisions (D62, D63)

- **A sheet is an `IfcDocumentInformation`** (Purpose `SHEET`, Identification = sheet number, Name = title,
  Scope = paper), as Bonsai stores sheets. Each placed drawing is an `IfcDocumentReference` to it:
  Identification = the drawing's GlobalId, Location `kimbim:drawing`, Description = `{x, y, scale}` (sheet mm,
  top-left; 1:n). The name is read from the drawing (an EXPRESS rule allows a Name or a referenced document,
  not both). Sheets are model data: versioned, undoable; their SVG is composed on demand.
- **Paper sizes** A1 (841 × 594) and A3 (420 × 297), landscape; **automatic numbering** A01, A02…
- **Project info in IFC's own fields** (where Archicad's IFC export puts them): number = `IfcProject.Name`,
  name = `IfcProject.LongName`, address = `IfcBuilding.BuildingAddress`, client = an `IfcActor` assigned to
  the project with the CLIENT role. *File › Project info…*.
- **Title block** (bottom right, 180 × 50 mm): project name, number, client, address, sheet title, sheet
  number, scale ("As indicated" when drawings differ), date, KimBim. Each placed drawing has a title line
  with its name and scale, as on Archicad layouts.
- **Composition**: each drawing's SVG is embedded in a `<g>` with translate/scale (QtSvg has no nested
  `<svg>`); drawings are auto-placed left to right, top to bottom, clear of each other and the title block.
- **PDF through Qt** (doc 05): `QPdfWriter` + `QSvgRenderer`, vector, page = the paper size. SVG export too.
  `kimbim-app --export-sheet NUMBER model.ifc out.pdf|out.svg` exports without a window (CI, scripts).

## Done

- [x] `kimbim/sheets.py`: project info, sheets, place/move/scale/remove drawings, `sheet_svg`, `export_sheet_svg`.
- [x] App: *Sheets* panel (New A1/A3, Place drawing, Open, Delete), sheets in tabs (drag a placed drawing to
  move it), *File › Project info…*, *Export sheet as PDF… / SVG…*; headless `--export-sheet`.
- [x] `tools/make_house.py` builds the M4 sheet (A3: ground floor plan, a section, the south elevation);
  `tools/check_m4.py` (`pixi run m4`, CI on Windows and Linux) checks one A3 page, vector content, fonts,
  and the three drawings and title block texts.
- [x] Tests: Python (project info in IFC fields, numbering, scale, undo, validation; the M4 sheet), app
  (`sheetsAndPdf`: sheet tab, PDF written).

## For the owner

- Print `build/m4/house-A01.pdf` (from `pixi run m4`) and judge it: line weights, text sizes, layout.
- Not yet: title block templates of your own, sheet sets/revisions, drawing scale setting per drawing view
  (placement scale exists; the drawing itself is generated at 1:100 and scaled), line weights by pen set.
