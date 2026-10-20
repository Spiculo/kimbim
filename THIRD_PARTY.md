# Third-party components

KimBim is GPL-3.0-or-later. These are the components it uses, how each is linked, and its license. See [docs/06](docs/06-reuse-and-licensing.md) for the compatibility rules.

| Component | License | Use | Linking |
|-----------|---------|-----|---------|
| IfcOpenShell 0.9 (conda-forge) | LGPL-3.0-or-later | IFC parsing, writing, validation, geometry | Dynamic (Python module and shared libraries) |
| Python | PSF-2.0 | Runtime | Separate interpreter |
| blake3 (Python) | Apache-2.0 / CC0-1.0 | Content hashes | Dynamic |
| NumPy | BSD-3-Clause | Required by `ifcopenshell.api` | Dynamic |
| lark | MIT | Parser used by IfcOpenShell utilities | Dynamic |
| openpyxl (and et_xmlfile) | MIT | Schedules exported to XLSX (D77) | Dynamic |
| IfcTester 0.9 (PyPI) | LGPL-3.0-or-later | IDS checks and their HTML/JSON report (D81) | Dynamic (Python module) |
| xmlschema, elementpath | MIT | IfcTester: reading .ids files | Dynamic |
| python-dateutil | Apache-2.0 / BSD-3-Clause | IfcTester | Dynamic |
| pystache | MIT | IfcTester's HTML report | Dynamic |
| odfpy | Apache-2.0 | IfcTester's ODS report (installed, not offered) | Dynamic |
| bcf-client | LGPL-3.0-or-later | IfcTester's BCF report (installed, not offered yet) | Dynamic |
| Flask | BSD-3-Clause | IfcTester's web app (installed as its dependency, never started) | Dynamic |
| ezdxf (and pyparsing, fonttools) | MIT | Drawings and sheets exported to DXF (D83) | Dynamic |
| pypdfium2 (and PDFium) | Apache-2.0 / BSD-3-Clause (PDFium: BSD-3-Clause, Apache-2.0) | PDF underlay pages rendered to images (D85) | Dynamic |
| Git | GPL-2.0-only (program) | `git fast-import`, repack, branch | Separate program |
| gix (gitoxide) | MIT OR Apache-2.0 | Reading the Git object database | Static (Rust) |
| rayon | MIT OR Apache-2.0 | Parallel reads | Static (Rust) |
| thiserror | MIT OR Apache-2.0 | Error types | Static (Rust) |
| PyO3 | MIT OR Apache-2.0 | Python ↔ Rust bindings | Static (Rust) |
| maturin | MIT OR Apache-2.0 | Build tool | Build only |
| pytest | MIT | Tests | Development only |
| tempfile | MIT OR Apache-2.0 | Rust tests | Development only |
| pixi | BSD-3-Clause | Environment manager | Development only |
| Qt Advanced Docking System 4.5.0 (commit 87cffe5) | LGPL-2.1-or-later | Dockable, floating and auto-hide panels and tabs in the app (D71) | Static (C++), built from source with CMake FetchContent |
