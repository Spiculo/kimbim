# KIMCAD

**Open-source native BIM for architects, with version control built in.**

KIMCAD is a desktop BIM application for Windows and Linux built on open standards (IFC). Model your building, cut through it, manage object data, reuse libraries and produce drawings. Then save versions, explore design options, compare them and combine them, the way software developers use Git, but for buildings.

> Status: **early development.** Slice 1 works: versioned IFC projects from the command line. The desktop app comes next. Design docs: [docs/README.md](docs/README.md).

## Try it (command line)

Requires [pixi](https://pixi.sh). Works on Windows and Linux.

```bash
pixi install                      # environment from conda-forge (IfcOpenShell, Rust, Git, ...)
pixi run build                    # build the Rust engine (kimcad._core)

pixi run kimcad init my-house                       # create a project
pixi run kimcad -C my-house commit model.ifc -m "Import from Revit"
pixi run kimcad -C my-house status edited.ifc       # what would change
pixi run kimcad -C my-house commit edited.ifc -m "Fire ratings"
pixi run kimcad -C my-house log
pixi run kimcad -C my-house diff                    # last version vs its parent
pixi run kimcad -C my-house export v1.ifc --rev HEAD~1
pixi run kimcad -C my-house branch option-b         # a design option
```

Each version stores the model as canonical, object-level records in a standard Git repository (`my-house/.git`). A one-property edit on a 10,000-object Revit model is stored as **one changed record**. Exports are lossless and byte-identical on Windows and Linux. See [docs/11](docs/11-spike-results.md) for how that was validated.

Development: see [CONTRIBUTING.md](CONTRIBUTING.md).

- Built on [IfcOpenShell](https://ifcopenshell.org), [OpenCASCADE](https://dev.opencascade.org), [Qt](https://www.qt.io) and Rust.
- Local-first: no server, no account, no network required.
- License: GPL-3.0-or-later.
- Languages: English and Spanish.

The original specification (v0.1) is kept in [doc.md](doc.md). The `docs/` folder supersedes it.
