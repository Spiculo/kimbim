# Slice 2: Desktop App Shell and IFC Viewer (M0 + M1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kimbim-app`, a native Qt 6 desktop application for Windows and Linux in English and Spanish. It opens an IFC file, shows it progressively in an OCCT 3D viewport that stays interactive at 100k elements, and offers a model tree, a properties panel, two-way selection, hide/isolate, a plan cut and a section box.

**Architecture:**
- **C++ Qt 6 application** (`app/`) built with CMake from the pixi environment (D04, D25).
- **Embedded CPython** (D22) runs `kimbim.app_bridge`, which owns the IfcOpenShell model and answers JSON queries (tree, properties) plus binary mesh chunks. The C++ side never parses IFC.
- **Viewport:** OCCT V3d/AIS in a native child widget, navigated through `AIS_ViewController`.
- **Batched presentation (D42):** each `ElementBatch` AIS object draws about 1,000 elements, with one `ElementOwner` selection owner and one `Select3D_SensitivePrimitiveArray` per element. Picking, highlighting and visibility stay per element.
- **Background loading:** meshing runs on a worker thread that holds the GIL per chunk; batches appear progressively.

**Tech Stack:** C++17, Qt 6.12 (Widgets, LinguistTools, Test), OCCT 8.0.1 `novtk` (D43), CPython 3.12 embedding, ifcopenshell 0.9 (hybrid kernel, D38), CMake + Ninja, MSVC 2022 / GCC via conda-forge `cxx-compiler`, pixi.

**Spec:** `docs/04-app-features.md` (sections 1–4, 12), `docs/05-geometry-rendering-drawings.md`, `docs/01-architecture.md`, roadmap M0/M1 in `docs/07-roadmap.md`, decisions D22, D38, D42, D43, D29.

**Plan style note:** every task gives exact files, interfaces (signatures), tests, commands and expected results. The C++ bodies for the OCCT and Qt glue are written during execution, test first, because they depend on exact OCCT 8.0 signatures that only the compiler can confirm. The tests and interfaces here are binding.

## Global Constraints

- License `GPL-3.0-or-later`; SPDX header on every `.py`, `.rs`, `.cpp`, `.h` (extend `tools/check_spdx.py`).
- Windows and Linux. Build only through pixi tasks; no system Qt or OCCT.
- **Never one AIS object per IFC element.** Batches of ≤ 1,000 elements with per-element owners (D42).
- OCCT `novtk` build only; the environment must not contain Mesa `opengl32.dll` (D43, `tests/python/test_environment.py`).
- Display tessellation uses ifcopenshell `hybrid-cgal-simple-opencascade` in world coordinates (D38).
- Every user-visible C++ string goes through `tr()`. English and Spanish `.ts` files ship, and the build fails on unfinished Spanish translations (D29).
- The GUI thread never runs tessellation. Meshing runs on a worker thread (doc 01, threading rule 1).
- Model data is never translated; IFC class names and properties show as stored (doc 04 §12).

## Review Focus

1. **Opening a schema-invalid or unreadable IFC** must show an error dialog (or a self-test JSON error) and leave the app usable, with no crash. Test: Task 2 (bridge), Task 5 (self-test with a broken file).
2. **Elements with no geometry** (spaces without body, grids, annotations) must still appear in the tree and properties without breaking meshing. Test: Task 3.
3. **Non-ASCII names** (Spanish, CJK) in the tree, properties and file paths (`Proyecto ñ/modelo.ifc`) must work end to end. Test: Task 2, Task 5.
4. **Closing the app while meshing runs** must stop the worker cleanly, without a hang or a crash on exit. Test: Task 5 (self-test `--quit-during-load`).
5. **Hide → isolate → show all** sequences, and selecting a hidden element from the tree, must keep counts consistent. Test: Task 6.

---

## File Structure

```text
CMakeLists.txt                      # top level: find Qt6, OpenCASCADE, Python3; add app/
app/
  CMakeLists.txt                    # kimbim-app executable + kimbim_core static lib + tests
  src/main.cpp                      # args (--version, --lang, --open, --self-test), translator, window
  src/MainWindow.{h,cpp}            # menus, docks, toolbar, status bar; wires everything
  src/Translations.{h,cpp}          # installTranslator(lang) -> bool
  src/PythonEngine.{h,cpp}          # embedded CPython: start(), call JSON functions, mesh chunks
  src/MeshChunk.{h,cpp}             # parsed chunk: element ids, offsets, float verts, int tris
  src/ModelLoader.{h,cpp}           # QThread worker pulling chunks; signals chunkReady/finished/failed
  src/Viewport.{h,cpp}              # OCCT view in a native QWidget + AIS_ViewController navigation
  src/ElementBatch.{h,cpp}          # AIS object: many elements, per-element owners/visibility
  src/ModelTreePanel.{h,cpp}        # spatial tree + search filter; selection signals
  src/PropertiesPanel.{h,cpp}       # attributes + property sets of the selected element
  src/SelfTest.{h,cpp}              # --self-test: open, load, measure, print JSON, exit
  translations/kimbim_en.ts, kimbim_es.ts
  tests/test_translations.cpp, test_python_engine.cpp, test_mesh_chunk.cpp
python/kimbim/app_bridge.py         # model session for the app (open, tree, properties, mesh chunks)
tests/python/test_app_bridge.py
tools/check_translations.py         # fail on unfinished/empty Spanish translations
```

---

### Task 1: App skeleton, i18n, build tasks

**Files:** create `CMakeLists.txt`, `app/CMakeLists.txt`, `app/src/main.cpp`, `app/src/MainWindow.{h,cpp}`, `app/src/Translations.{h,cpp}`, `app/translations/kimbim_{en,es}.ts`, `app/tests/test_translations.cpp`, `tools/check_translations.py`; modify `pixi.toml`, `tools/check_spdx.py` (add `app` dir and `.cpp`/`.h`), `.gitignore` (`/build/`).

**Interfaces:**
- `bool kimbim::installTranslator(QCoreApplication&, const QString& lang)` loads the embedded `:/i18n/kimbim_<lang>.qm`. It returns false for unknown languages, and English is the source language.
- `kimbim-app --version` prints `KimBim 0.1.0` and exits 0. `--lang es|en` overrides the system locale.
- pixi tasks:
  - `app-configure`: `cmake -S . -B build/app -G Ninja -DCMAKE_BUILD_TYPE=Release`
  - `app-build`: `cmake --build build/app`, depends on `app-configure`
  - `app-test`: `ctest --test-dir build/app --output-on-failure`, depends on `app-build`
  - `app`: `build/app/app/kimbim-app`, depends on `app-build`, with env `KIMBIM_PYTHON_PATH=$PIXI_PROJECT_ROOT/python`
  - `check-translations`

- [ ] **Step 1: Failing test** `app/tests/test_translations.cpp` (Qt Test):

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include <QtTest>
#include "Translations.h"

class TestTranslations : public QObject {
    Q_OBJECT
private slots:
    void spanishMenusAreTranslated() {
        QVERIFY(kimbim::installTranslator(*QCoreApplication::instance(), "es"));
        QCOMPARE(QCoreApplication::translate("MainWindow", "&File"), QString("&Archivo"));
        QCOMPARE(QCoreApplication::translate("MainWindow", "&Open IFC..."), QString("&Abrir IFC..."));
    }
    void unknownLanguageIsRejected() {
        QVERIFY(!kimbim::installTranslator(*QCoreApplication::instance(), "xx"));
    }
};
QTEST_MAIN(TestTranslations)
#include "test_translations.moc"
```

Also `tools/check_translations.py` (pytest-free script): parse `app/translations/kimbim_es.ts`, and fail if any `<translation type="unfinished">` exists or any translation is empty.

- [ ] **Step 2:** `pixi run app-test` fails (no CMake project).
- [ ] **Step 3: Implement.**
  - CMake: `qt_standard_project_setup()`, `qt_add_executable(kimbim-app ...)`, a static library `kimbim_core` for everything except `main.cpp`, and `qt_add_translations(kimbim_core TS_FILES ... RESOURCE_PREFIX /i18n)`.
  - `MainWindow` has the File menu (`&Open IFC...`, `&Quit`), the View menu (`&Fit all`), and Help (`&About KimBim`). Status bar text: `tr("Ready")`.
  - Run `lupdate` to produce the `.ts` files, then fill in the Spanish translations.
- [ ] **Step 4:** `pixi run app-test` passes (2/2). `pixi run app -- --version` prints `KimBim 0.1.0`. `pixi run check-translations` passes.
- [ ] **Step 5:** commit `feat(app): Qt 6 application skeleton with English/Spanish translations`.

### Task 2: Embedded Python engine and app bridge (open, tree, properties)

**Files:** create `python/kimbim/app_bridge.py`, `tests/python/test_app_bridge.py`, `app/src/PythonEngine.{h,cpp}`, `app/tests/test_python_engine.cpp`.

**Interfaces:**
- Python `kimbim.app_bridge`, a module-level single session:
  - `open_model(path: str) -> str`. Returns JSON `{"ok": true, "schema", "project", "elements": int}` or `{"ok": false, "error": str}`. It never raises.
  - `spatial_tree() -> str`: JSON node `{"guid", "type", "name", "children": [...]}`. The root is IfcProject. Elements appear under their container (or aggregate), sorted by type then name.
  - `properties(guid: str) -> str`: JSON `{"guid", "type", "name", "attributes": {..scalar attrs..}, "psets": {pset: {prop: value}}}`, or `{"error"}` if unknown.
- C++ `kimbim::PythonEngine` (QObject, singleton per app):
  - `bool start(QString* error)` sets PYTHONHOME from `CONDA_PREFIX`, prepends `KIMBIM_PYTHON_PATH` to `sys.path`, and imports `kimbim.app_bridge`.
  - `QJsonDocument callJson(const char* fn, const QStringList& args)` calls a bridge function holding the GIL and parses the returned JSON.
  - `void stop()` finalizes Python on exit.

- [ ] **Step 1: Failing Python tests** `tests/python/test_app_bridge.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
import json

from conftest import build_model

from kimbim import app_bridge


def test_open_tree_properties(tmp_path):
    f = build_model(walls=2)
    f.by_type("IfcWall")[0].Name = "Muro Ñandú 墙"
    p = tmp_path / "Proyecto ñ" / "modelo.ifc"
    p.parent.mkdir()
    f.write(str(p))
    info = json.loads(app_bridge.open_model(str(p)))
    assert info["ok"] and info["schema"] == "IFC4" and info["elements"] >= 2
    tree = json.loads(app_bridge.spatial_tree())
    assert tree["type"] == "IfcProject"
    names = []

    def walk(n):
        names.append(n["name"])
        for c in n["children"]:
            walk(c)

    walk(tree)
    assert "Muro Ñandú 墙" in names and "Level 1" in names
    wall = f.by_type("IfcWall")[0]
    props = json.loads(app_bridge.properties(wall.GlobalId))
    assert props["type"] == "IfcWall" and props["psets"]["Pset_WallCommon"]["FireRating"] == "EI30"


def test_open_errors_are_reported_not_raised(tmp_path):
    bad = tmp_path / "bad.ifc"
    bad.write_text("not an ifc file")
    info = json.loads(app_bridge.open_model(str(bad)))
    assert info["ok"] is False and info["error"]
    assert json.loads(app_bridge.properties("nope"))["error"]
```

- [ ] **Step 2: Failing C++ test** `app/tests/test_python_engine.cpp`. It writes a small IFC by calling Python (`conftest.build_model`, through a helper in `app_bridge`: `_write_test_model(path)`), then asserts `callJson("open_model", {path})["ok"] == true` and that the tree root type is `IfcProject`.
- [ ] **Step 3:** run both test suites and see them fail. Implement. Run them and see them pass.
- [ ] **Step 4:** commit `feat(app): embedded Python engine and app bridge (open, tree, properties)`.

### Task 3: Mesh chunks (Python producer, C++ parser)

**Files:** modify `python/kimbim/app_bridge.py`, `tests/python/test_app_bridge.py`; create `app/src/MeshChunk.{h,cpp}`, `app/tests/test_mesh_chunk.cpp`.

**Interfaces:**
- Python:
  - `start_meshing(threads: int = 0) -> str` creates the iterator (hybrid kernel, world coordinates, all threads when 0). Returns `{"ok", "total"}`.
  - `next_mesh_chunk(max_elements: int = 1000) -> tuple[str, bytes, bytes] | None` returns `(meta_json, verts_f32_le, tris_u32_le)`. `meta = {"guids": [...], "types": [...], "voff": [...], "toff": [...]}`, with offsets per element (length n+1) and triangle indices local to the chunk. Returns `None` when finished. Elements without triangles are skipped.
- C++:
  - `struct MeshChunk { QStringList guids, types; std::vector<uint32_t> voff, toff; std::vector<float> verts; std::vector<uint32_t> tris; }`
  - `std::optional<MeshChunk> MeshChunk::parse(const QByteArray& meta, const QByteArray& verts, const QByteArray& tris, QString* error)` validates sizes and offsets.
  - `PythonEngine::nextMeshChunk(int max, MeshChunk* out, QString* error) -> bool`

- [ ] **Step 1: Failing tests.**
  - Python: `test_mesh_chunks_cover_all_elements_with_geometry`. A model with 3 walls and an `IfcSpace` without representation yields chunks whose guids are exactly the 3 walls. Every triangle index is below its chunk's vertex count. `max_elements=2` gives 2 chunks.
  - C++ `test_mesh_chunk.cpp`: `parse` accepts a hand-built 2-element chunk, and rejects mismatched sizes and out-of-range indices.
- [ ] **Step 2:** see them fail. Implement. See them pass. Commit `feat: mesh chunks from IfcOpenShell to the app`.

### Task 4: Viewport with batched elements (D42)

**Files:** create `app/src/Viewport.{h,cpp}`, `app/src/ElementBatch.{h,cpp}`, `app/src/SelfTest.{h,cpp}`; modify `main.cpp`, `app/CMakeLists.txt`.

**Interfaces:**
- `class ElementBatch : public AIS_InteractiveObject`:
  - Constructed `(const MeshChunk&)`. It keeps the vertex and index arrays and builds flat-shaded triangles.
  - `int elementCount() const`, `QString guid(int i) const`
  - `void setHidden(int i, bool)`, `bool isHidden(int i) const`. Changing visibility recomputes the presentation and selection.
  - `Handle(ElementOwner) owner(int i) const`. `ElementOwner : SelectMgr_EntityOwner` stores the batch and element index and highlights only that element's triangles.
- `class Viewport : public QWidget, protected AIS_ViewController` (native window, `WA_PaintOnScreen`):
  - `void addBatch(Handle(ElementBatch))`, `void fitAll()`, `void clear()`
  - `QString pickedGuid() const`
  - Signals: `selectionChanged(QStringList guids)`, `hovered(QString guid)`.
  - `void selectGuids(const QStringList&)`, `void setHidden(const QStringList&, bool)`, `void isolate(const QStringList&)`, `void showAll()`
  - `int visibleElementCount() const`, `double measureFps(int frames)`
- Self-test: `kimbim-app --self-test <ifc> [--frames N]` opens the model, loads all chunks, fits, orbits N frames, and picks the screen center. It prints JSON `{"ok", "elements", "batches", "triangles", "load_s", "fps", "picked"}` and exits 0, or 1 with `{"ok": false, "error"}`.

- [ ] **Step 1: Failing check.** Running `pixi run app -- --self-test <fixture.ifc>` fails because `--self-test` is unknown.
- [ ] **Step 2: Implement** the viewport, batch, owner and self-test.
- [ ] **Step 3: Verify.**
  - Self-test on the conftest fixture: `elements == 2`, `batches == 1`, `picked` is a wall guid.
  - Self-test on Duplex: `elements ≥ 280`, `fps ≥ 30`.
  - Self-test on the 110k synthetic model, when present: `batches == 110` (or ≤ 115) and `fps ≥ 25` on the integrated GPU.
  - Record the numbers in the ledger.
- [ ] **Step 4:** commit `feat(app): OCCT viewport with batched elements and per-element picking`.

### Task 5: Main window: open, progressive loading, tree, properties, selection sync

**Files:** create `app/src/ModelLoader.{h,cpp}`, `app/src/ModelTreePanel.{h,cpp}`, `app/src/PropertiesPanel.{h,cpp}`; modify `MainWindow`, `SelfTest`.

**Interfaces:**
- `ModelLoader : QObject`, moved to a `QThread`:
  - `start(path)`, then signals `opened(QJsonObject info)`, `chunkReady(MeshChunk)`, `finished(int elements)`, `failed(QString)`.
  - `requestStop()` makes it stop after the current chunk.
- `ModelTreePanel`:
  - `setTree(QJsonObject)`, `selectGuid(QString)`, `setFilter(QString)`
  - Signals `guidsSelected(QStringList)`, `isolateRequested(QStringList)`
- `PropertiesPanel::show(QJsonObject props)`
- Selection sync:
  - Clicking in the viewport selects the tree item and shows its properties.
  - Clicking a tree item selects and highlights it in the viewport and shows its properties.
- Self-test flags:
  - `--quit-during-load`: request quit after the first chunk, which must exit 0 within 5 s.
  - A broken file must give `{"ok": false}` with exit 1, and no crash.

- [ ] Tests:
  1. Self-test on a broken IFC returns `ok:false`, exit 1.
  2. `--quit-during-load` on Duplex exits 0 in under 5 s.
  3. Self-test on the fixture inside `Proyecto ñ/` passes.
  4. A Qt Test `test_model_tree.cpp` covers `ModelTreePanel` fed with a tree JSON: `selectGuid` selects the right item, the filter hides non-matching leaves, and parents of matches stay visible.

  Implement, then commit `feat(app): open IFC with progressive loading, model tree, properties, selection sync`.

### Task 6: Visibility: hide, isolate, show all, storey isolate

**Files:** modify `Viewport`, `ModelTreePanel` (context menu "Isolate", "Hide", "Show all"), `MainWindow` (toolbar actions, keyboard shortcuts H / I / Shift+H).

- [ ] Test: Qt Test `test_visibility.cpp` builds two `ElementBatch`es from hand-made chunks (no GL needed for counts) and drives a `VisibilityState` helper, the pure logic Viewport uses:
  - hide 1 → visible = n − 1;
  - isolate {a, b} → 2;
  - show all → n;
  - isolating a storey's guids keeps exactly those;
  - selecting a hidden guid un-hides it.

  Implement `VisibilityState` (pure C++, unit-tested) and wire it to the batches. Commit `feat(app): hide, isolate, show all`.

### Task 7: Cuts: plan cut and section box

**Files:** create `app/src/Cuts.{h,cpp}`; modify `Viewport`, `MainWindow` (View → `Plan cut` toggle with a height slider; `Section box` toggle around the selection, or the model if nothing is selected).

**Interfaces:**
- `struct CutState { bool planCut; double height; bool box; Bnd_Box bounds; }`
- `std::vector<Handle(Graphic3d_ClipPlane)> makePlanes(const CutState&)` gives 1 plane for the plan cut and 6 for the box, with capping enabled.

- [ ] Test: Qt Test `test_cuts.cpp`:
  - a plan cut at height h gives 1 plane with normal (0, 0, −1) through z = h;
  - a box over bounds (0..10)³ gives 6 planes, each facing inward;
  - turning off removes the planes.
- [ ] Self-test `--plan-cut <h>` prints `planes: 1`.

  Commit `feat(app): plan cut and section box`.

### Task 8: Search, CI, docs

**Files:** modify `ModelTreePanel` (search box: name, type or GUID), `.github/workflows/ci.yml`, `README.md`, `docs/07-roadmap.md`, `docs/decisions.md`, `tools/check_spdx.py`.

- **CI:**
  - Both OSs: `pixi run app-test` and `pixi run check-translations`.
  - Linux: also run the self-test on the fixture under `xvfb-run`, using Mesa llvmpipe from the OS. That's fine on CI and is the only place software rendering is allowed.
- **Docs:**
  - README "Try the app" section.
  - Roadmap: M0 ✅; M1 ✅ minus walk and colour-by.
  - Decisions: D44 (bridge = embedded Python with a JSON/bytes protocol; the C++ side never parses IFC) and D45 (native-window OCCT viewport through `AIS_ViewController`).
- [ ] Final verification: `pixi run test`, `pixi run app-test`, `pixi run golden`, the self-test on Duplex and the 110k model. Commit `ci/docs: desktop app build, translations check, Linux GUI smoke test`.
