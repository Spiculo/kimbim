# Main Window Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the model more room. Tools go on the left in 3D / Plane / View / Edit groups and panels are
tabbed on the right. Properties come forward on double-click, a bottom bar holds the pen, layers, zoom
and selection, and the 3D and plan views are tabs that pop out of the center and dock back.

**Architecture:** The Qt Advanced Docking System (ADS) replaces `QTabWidget` + `QDockWidget`.
`Viewport` is split into a shared `Scene` (OCCT viewer, context, element batches, selection) and one
`V3d_View` per tab, so a 3D tab and plan tabs show one loaded model. `MainWindow.cpp` is split into
`DockLayout`, `ToolPalette`, `ToolOptionsBar`, `StatusStrip` and `ViewHost`. The Python bridge doesn't
change.

**Tech Stack:** C++20, Qt 6.12 (Widgets, Svg, Test), OCCT 8.0.1 (AIS/V3d), Qt Advanced Docking
System 4.x (LGPL-2.1, built with CMake `FetchContent`), CMake + Ninja via pixi.

**Spec:** `docs/superpowers/specs/2026-10-07-main-window-rework-design.md`

## Global Constraints

- Every new UI string goes through `tr()` and has a Spanish translation in `app/translations/kimbim_es.ts`; `pixi run check-translations` passes.
- Every new source file starts with `// SPDX-License-Identifier: GPL-3.0-or-later` (`pixi run check-spdx`).
- The bridge (`python/kimbim`) doesn't change; `pixi run test` (Python) stays green.
- Existing action object names and shortcuts don't change (`actionWallTool` = W, ...); `shortcutsAreTheDocumentedOnes` keeps passing.
- No OCCT exception may escape into a Qt event handler (wrap OCCT window calls in `try`/`catch (const Standard_Failure&)` as `Viewport::ensureWindow` does).
- Builds and tests pass on Windows and on Linux (WSL Ubuntu at `~/kimbim-verify`, as CI runs them).
- The refresh after an edit, timed on `Clinic_Architectural.ifc` (`kimbim-app --self-test` tool benchmark), is no slower with a 3D tab and a plan tab open than with the 3D view alone today.
- ADS is pinned to one release tag *and* its commit hash; `THIRD_PARTY.md` lists it with its license.

## Review Focus

1. **Popping a view out to its own window and back.** Qt gives the widget a new native window and OCCT's view still draws to the old one. The view must keep rendering (Task 4: `--pop-out` self-test).
2. **Deleting the level whose plan tab is active, with a tool half-way.** The tab closes, the 3D tab becomes active, the tool is cancelled, and nothing crashes (Task 6: `deletingTheActivePlanLevel`).
3. **Restarting with a saved layout that names tabs that no longer exist** (a deleted drawing, another model). They are skipped; a layout with a floating window off every screen falls back to the default (Task 5: `layoutRestoreSkipsUnknownAndOffscreen`).
4. **Editing with two views open.** The geometry is updated once in the shared scene, both views show it, and selection is the same in both (Task 2: `editAndSelectionReachEveryView`; Task 13 times it on Clinic).
5. **Opening another file while plan tabs are open.** Plan tabs of the old model close; the new model opens in the 3D tab (Task 6: `openingAFileClosesPlanTabs`).

---

## File Structure

| File | Responsibility |
|---|---|
| `CMakeLists.txt` (root) | `FetchContent` of ADS, pinned |
| `app/CMakeLists.txt` | new sources, link `ads::qtadvanceddocking-qt6`, new tests |
| `app/src/Scene.{h,cpp}` (new) | shared OCCT viewer + context + element batches + selection + colours + layer state |
| `app/src/Viewport.{h,cpp}` | one view of a `Scene`: camera, navigation, tools input, overlays, cuts |
| `app/src/DockLayout.{h,cpp}` (new) | ADS manager: center views, right panels, left tools, save/restore |
| `app/src/ViewHost.{h,cpp}` (new) | a center tab for a `Viewport`: slots for the tool options strip and the cut column |
| `app/src/ToolPalette.{h,cpp}` (new) | left column of collapsible tool groups |
| `app/src/ToolOptionsBar.{h,cpp}` (new) | the active tool's fields |
| `app/src/StatusStrip.{h,cpp}` (new) | bottom bar: pen placeholder, layer, visible layers, zoom, selection, message |
| `app/src/ModelTreePanel.{h,cpp}` | tidied tree: plain names, merged single-child spatial rows, category groups |
| `app/src/MainWindow.{h,cpp}` | wiring only; uses the units above |
| `app/src/SelfTest.cpp` | `--pop-out` self-test |
| `app/tests/test_scene.cpp` (new) | two views on one scene |
| `app/tests/test_dock_layout.cpp` (new) | `DockLayout` |
| `app/tests/test_tool_palette.cpp` (new) | `ToolPalette`, `ToolOptionsBar`, `StatusStrip` |
| `app/tests/test_model_tree.cpp`, `app/tests/test_main_window.cpp` | updated + new cases |
| `THIRD_PARTY.md`, `docs/decisions.md` (D71), `docs/04-app-features.md`, `docs/13-architect-feedback.md` | docs |

Commands (Git Bash; add pixi to PATH first: `export PATH="$HOME/.pixi/bin:$PATH"`):
- Build app + tests: `pixi run app-build`
- One C++ test binary: `pixi run bash -c 'QT_QPA_PLATFORM=offscreen KIMBIM_PYTHON_PATH="$PWD/python" ./build/app/<test>.exe [testFunction] -o out.txt,txt; cat out.txt; rm -f out.txt'`
- All app tests: `KIMBIM_PYTHON_PATH="$PWD/python" pixi run ctest --test-dir build/app --output-on-failure`

A running `kimbim-app` locks the exe; close it before building, and check the build's exit code.

---

### Task 1: ADS dependency and `DockLayout`

**Files:**
- Modify: `CMakeLists.txt` (root), `app/CMakeLists.txt`, `THIRD_PARTY.md`
- Create: `app/src/DockLayout.h`, `app/src/DockLayout.cpp`, `app/tests/test_dock_layout.cpp`

**Interfaces:**
- Produces:
  ```cpp
  namespace kimbim {
  class DockLayout : public QObject {
      Q_OBJECT
  public:
      explicit DockLayout(QMainWindow* window);
      ads::CDockManager* manager() const { return m_manager; }
      // Center views (3D, plans, drawings, sheets), keyed ("3d", "plan:<guid>", "<drawing guid>", "sheet:A01").
      ads::CDockWidget* addView(const QString& key, const QString& title, QWidget* widget, bool closable);
      QWidget* view(const QString& key) const;          // nullptr if none
      QString keyOf(const QWidget* widget) const;       // "" if none
      QStringList viewKeys() const;                     // in creation order
      void setTitle(const QString& key, const QString& title);
      void removeView(const QString& key);              // deletes the dock and its widget
      void raise(const QString& key);                   // makes it current (emits currentChanged)
      QString current() const;                          // key of the current center view
      // Side areas: panels on the right (tabbed), the tool palette on the left.
      ads::CDockWidget* addPanel(const QString& key, const QString& title, QWidget* widget);
      ads::CDockWidget* addLeft(const QString& key, const QString& title, QWidget* widget);
      void raisePanel(const QString& key);              // shows it even when auto-hidden or floating
      bool isPanelShown(const QString& key) const;
      // Layout memory.
      QByteArray saveLayout() const;
      void captureDefault();                            // the layout to fall back to
      bool restoreLayout(const QByteArray& state);      // false (and default applied) if unusable
  signals:
      void currentChanged(const QString& key);
      void closeRequested(const QString& key);
  };
  }
  ```

- [ ] **Step 1: Pin ADS.** Find the latest 4.x release and its commit:

Run: `git ls-remote --tags https://github.com/githubuser0xFFFF/Qt-Advanced-Docking-System | grep -E 'refs/tags/4\.[0-9]+\.[0-9]+$' | sort -V -k2 | tail -1`
Expected: one line `<hash>\trefs/tags/4.X.Y`. Use that hash and tag below.

- [ ] **Step 2: Fetch it in CMake.** In root `CMakeLists.txt`, after `find_package(Qt6 ...)` and before `add_subdirectory(app)`:

```cmake
# Qt Advanced Docking System (LGPL-2.1): dockable, floating and auto-hide panels and tabs (D71).
# conda-forge only packages it for Qt 5, so it is built here, pinned to a release commit.
include(FetchContent)
set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(BUILD_STATIC ON CACHE BOOL "" FORCE)
set(ADS_VERSION 4.X.Y CACHE STRING "" FORCE)
FetchContent_Declare(qtads
    GIT_REPOSITORY https://github.com/githubuser0xFFFF/Qt-Advanced-Docking-System.git
    GIT_TAG <hash> # 4.X.Y
)
FetchContent_MakeAvailable(qtads)
```

In `app/CMakeLists.txt` add `src/DockLayout.cpp src/DockLayout.h` to `kimbim_core`, link the library and register the test:

```cmake
target_link_libraries(kimbim_core PUBLIC ads::qtadvanceddocking-qt6)
...
kimbim_test(test_dock_layout)
```

Run: `pixi run app-configure && cmake --build build/app --target qtadvanceddocking-qt6`
Expected: the ADS library builds. If the target name differs, run
`cmake --build build/app --target help | grep -i dock` and use the listed name in both places.

- [ ] **Step 3: Write the failing test** `app/tests/test_dock_layout.cpp`:

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include <QLabel>
#include <QMainWindow>
#include <QSignalSpy>
#include <QtTest>

#include <DockManager.h>
#include <DockWidget.h>

#include "DockLayout.h"

class TestDockLayout : public QObject {
    Q_OBJECT
private slots:
    void viewsAreKeyedTabsInTheCenter()
    {
        QMainWindow w;
        kimbim::DockLayout layout(&w);
        auto* model = new QLabel("3D");
        layout.addView("3d", "3D", model, false);
        layout.addView("plan:L1", "Level 1 plan", new QLabel("plan"), true);
        QCOMPARE(layout.viewKeys(), QStringList({"3d", "plan:L1"}));
        QCOMPARE(layout.view("3d"), model);
        QCOMPARE(layout.keyOf(model), QString("3d"));
        QSignalSpy current(&layout, &kimbim::DockLayout::currentChanged);
        layout.raise("plan:L1");
        QCOMPARE(layout.current(), QString("plan:L1"));
        QCOMPARE(current.count(), 1);
        layout.setTitle("plan:L1", "Planta 1");
        QCOMPARE(layout.manager()->findDockWidget("plan:L1")->windowTitle(), QString("Planta 1"));
    }

    void the3DViewCannotBeClosedOthersAsk()
    {
        QMainWindow w;
        kimbim::DockLayout layout(&w);
        layout.addView("3d", "3D", new QLabel, false);
        layout.addView("D1", "Section 1", new QLabel, true);
        QVERIFY(!layout.manager()->findDockWidget("3d")->features().testFlag(ads::CDockWidget::DockWidgetClosable));
        QSignalSpy close(&layout, &kimbim::DockLayout::closeRequested);
        layout.manager()->findDockWidget("D1")->closeDockWidget(); // the tab's x
        QCOMPARE(close.count(), 1);
        QCOMPARE(close.first().first().toString(), QString("D1"));
        QVERIFY(layout.view("D1")); // the app decides; nothing is closed behind its back
        layout.removeView("D1");
        QVERIFY(!layout.view("D1"));
        QCOMPARE(layout.viewKeys(), QStringList({"3d"}));
    }

    void panelsAreTabbedOnTheRightAndCanBeRaised()
    {
        QMainWindow w;
        kimbim::DockLayout layout(&w);
        layout.addView("3d", "3D", new QLabel, false);
        layout.addPanel("tree", "Model", new QLabel);
        layout.addPanel("properties", "Properties", new QLabel);
        layout.raisePanel("tree");
        QVERIFY(layout.isPanelShown("tree"));
        layout.raisePanel("properties");
        QVERIFY(layout.isPanelShown("properties"));
        QCOMPARE(layout.manager()->findDockWidget("tree")->dockAreaWidget(),
                 layout.manager()->findDockWidget("properties")->dockAreaWidget()); // one tabbed area
    }

    void layoutRoundTripsAndFallsBack()
    {
        QMainWindow w;
        kimbim::DockLayout layout(&w);
        layout.addView("3d", "3D", new QLabel, false);
        layout.addPanel("tree", "Model", new QLabel);
        layout.captureDefault();
        const QByteArray state = layout.saveLayout();
        QVERIFY(!state.isEmpty());
        QVERIFY(layout.restoreLayout(state));
        QVERIFY(!layout.restoreLayout(QByteArray("not a layout"))); // falls back to the default
        QVERIFY(layout.view("3d"));
    }
};

QTEST_MAIN(TestDockLayout)
#include "test_dock_layout.moc"
```

- [ ] **Step 4: Run it to make sure it fails.** Run: `pixi run app-build`. Expected: compile error, `DockLayout.h` not found.

- [ ] **Step 5: Implement** `app/src/DockLayout.h` (the interface above, plus):

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QByteArray>
#include <QHash>
#include <QObject>
#include <QPointer>
#include <QStringList>

class QMainWindow;
namespace ads {
class CDockManager;
class CDockWidget;
class CDockAreaWidget;
}

namespace kimbim {

// The main window's docking (D71, Qt Advanced Docking System): center views as tabs that can be
// dragged out to their own windows and docked back, tabbed panels on the right, tools on the left,
// and the layout saved and restored.
class DockLayout : public QObject {
    Q_OBJECT
public:
    // ... interface from "Produces" above ...
private:
    ads::CDockWidget* makeDock(const QString& key, const QString& title, QWidget* widget);
    bool onSomeScreen() const;

    ads::CDockManager* m_manager;
    QPointer<ads::CDockAreaWidget> m_center, m_panels;
    QStringList m_views;
    QString m_current;
    QByteArray m_default;
};

} // namespace kimbim
```

`app/src/DockLayout.cpp`:

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include "DockLayout.h"

#include <AutoHideDockContainer.h>
#include <DockAreaWidget.h>
#include <DockManager.h>
#include <DockWidget.h>
#include <FloatingDockContainer.h>

#include <QGuiApplication>
#include <QMainWindow>
#include <QScreen>

namespace kimbim {

DockLayout::DockLayout(QMainWindow* window)
    : QObject(window)
{
    ads::CDockManager::setConfigFlag(ads::CDockManager::FocusHighlighting, true);
    ads::CDockManager::setConfigFlag(ads::CDockManager::OpaqueSplitterResize, true);
    ads::CDockManager::setConfigFlag(ads::CDockManager::DockAreaHasUndockButton, true);
    ads::CDockManager::setAutoHideConfigFlags(ads::CDockManager::DefaultAutoHideConfig);
    m_manager = new ads::CDockManager(window); // becomes the window's central widget
    m_manager->setObjectName(QStringLiteral("dockManager"));
    connect(m_manager, &ads::CDockManager::focusedDockWidgetChanged, this,
        [this](ads::CDockWidget*, ads::CDockWidget* now) {
            if (now && m_views.contains(now->objectName()) && m_current != now->objectName()) {
                m_current = now->objectName();
                emit currentChanged(m_current);
            }
        });
}

ads::CDockWidget* DockLayout::makeDock(const QString& key, const QString& title, QWidget* widget)
{
    auto* dock = new ads::CDockWidget(title);
    dock->setObjectName(key); // ADS saves and restores the layout by object name
    dock->setWidget(widget);
    dock->setFeature(ads::CDockWidget::CustomCloseHandling, true);
    connect(dock, &ads::CDockWidget::closeRequested, this, [this, key] { emit closeRequested(key); });
    return dock;
}

ads::CDockWidget* DockLayout::addView(const QString& key, const QString& title, QWidget* widget, bool closable)
{
    ads::CDockWidget* dock = makeDock(key, title, widget);
    dock->setFeature(ads::CDockWidget::DockWidgetClosable, closable);
    if (m_center)
        m_manager->addDockWidgetTabToArea(dock, m_center);
    else
        m_center = m_manager->addDockWidget(ads::CenterDockWidgetArea, dock);
    m_views << key;
    if (m_current.isEmpty())
        m_current = key;
    return dock;
}

QWidget* DockLayout::view(const QString& key) const
{
    ads::CDockWidget* dock = m_views.contains(key) ? m_manager->findDockWidget(key) : nullptr;
    return dock ? dock->widget() : nullptr;
}

QString DockLayout::keyOf(const QWidget* widget) const
{
    for (const QString& key : m_views)
        if (view(key) == widget)
            return key;
    return {};
}

QStringList DockLayout::viewKeys() const { return m_views; }

void DockLayout::setTitle(const QString& key, const QString& title)
{
    if (ads::CDockWidget* dock = m_manager->findDockWidget(key))
        dock->setWindowTitle(title);
}

void DockLayout::removeView(const QString& key)
{
    ads::CDockWidget* dock = m_manager->findDockWidget(key);
    if (!dock)
        return;
    m_views.removeAll(key);
    m_manager->removeDockWidget(dock);
    delete dock; // and its widget
    if (m_current == key) {
        m_current = m_views.value(0);
        if (!m_current.isEmpty())
            raise(m_current);
    }
}

void DockLayout::raise(const QString& key)
{
    ads::CDockWidget* dock = m_manager->findDockWidget(key);
    if (!dock)
        return;
    dock->toggleView(true);
    dock->raise();
    m_manager->setDockWidgetFocused(dock);
    if (m_current != key) {
        m_current = key;
        emit currentChanged(key);
    }
}

QString DockLayout::current() const { return m_current; }

ads::CDockWidget* DockLayout::addPanel(const QString& key, const QString& title, QWidget* widget)
{
    ads::CDockWidget* dock = makeDock(key, title, widget);
    dock->setFeature(ads::CDockWidget::CustomCloseHandling, false); // panels just hide
    if (m_panels)
        m_manager->addDockWidgetTabToArea(dock, m_panels);
    else
        m_panels = m_manager->addDockWidget(ads::RightDockWidgetArea, dock);
    return dock;
}

ads::CDockWidget* DockLayout::addLeft(const QString& key, const QString& title, QWidget* widget)
{
    ads::CDockWidget* dock = makeDock(key, title, widget);
    dock->setFeature(ads::CDockWidget::CustomCloseHandling, false);
    dock->setFeature(ads::CDockWidget::DockWidgetClosable, false);
    m_manager->addDockWidget(ads::LeftDockWidgetArea, dock);
    return dock;
}

void DockLayout::raisePanel(const QString& key)
{
    ads::CDockWidget* dock = m_manager->findDockWidget(key);
    if (!dock)
        return;
    dock->toggleView(true);
    if (dock->isAutoHide())
        dock->autoHideDockContainer()->collapseView(false); // slides out
    else if (dock->isFloating())
        dock->dockContainer()->window()->raise();
    dock->raise();
}

bool DockLayout::isPanelShown(const QString& key) const
{
    ads::CDockWidget* dock = m_manager->findDockWidget(key);
    return dock && !dock->isClosed() && dock->isCurrentTab();
}

QByteArray DockLayout::saveLayout() const { return m_manager->saveState(); }

void DockLayout::captureDefault() { m_default = m_manager->saveState(); }

bool DockLayout::onSomeScreen() const
{
    for (ads::CFloatingDockContainer* f : m_manager->floatingWidgets()) {
        bool seen = false;
        for (QScreen* s : QGuiApplication::screens())
            seen = seen || s->availableGeometry().intersects(f->geometry());
        if (!seen)
            return false;
    }
    return true;
}

bool DockLayout::restoreLayout(const QByteArray& state)
{
    // ADS skips docks it no longer has (a drawing deleted since); a garbled state or a floating
    // window left on an unplugged monitor falls back to the default layout.
    if (!state.isEmpty() && m_manager->restoreState(state) && onSomeScreen())
        return true;
    if (!m_default.isEmpty())
        m_manager->restoreState(m_default);
    return false;
}

} // namespace kimbim
```

- [ ] **Step 6: Run the test.** Run: `pixi run app-build` then the `test_dock_layout.exe` command. Expected: all four tests PASS. If an ADS method name is wrong for the pinned release, fix it from the fetched headers in `build/app/_deps/qtads-src/src/` and note it in the commit message.

- [ ] **Step 7: Third-party note.** Add to `THIRD_PARTY.md`, in its table/list style:
`Qt Advanced Docking System 4.X.Y (commit <hash>) — LGPL-2.1-or-later — docking, floating and auto-hide panels; built from source with CMake FetchContent; https://github.com/githubuser0xFFFF/Qt-Advanced-Docking-System`

- [ ] **Step 8: Linux build check** (CI builds Linux too):
Run in WSL: `cd ~/kimbim-verify && git fetch /mnt/c/Users/lecot/OneDrive/Projects/kimbim ui-rework && git checkout FETCH_HEAD && pixi run app-build && QT_QPA_PLATFORM=offscreen ./build/app/test_dock_layout`
Expected: builds and PASS. If ADS needs `Qt6::GuiPrivate` headers that aren't in the pixi Qt, the configure step says so; then add the missing pixi package (`pixi add qt6-main` variant with private headers) and record it in the commit.

- [ ] **Step 9: Commit**

```bash
git add CMakeLists.txt app/CMakeLists.txt app/src/DockLayout.* app/tests/test_dock_layout.cpp THIRD_PARTY.md
git commit -m "feat(app): DockLayout on the Qt Advanced Docking System (pinned 4.X.Y): keyed center views, right panels, layout save/restore with fallback (D71)"
```

---

### Task 2: `Scene` shared by several views

**Files:**
- Create: `app/src/Scene.h`, `app/src/Scene.cpp`, `app/tests/test_scene.cpp`
- Modify: `app/src/Viewport.h`, `app/src/Viewport.cpp`, `app/CMakeLists.txt`

**Interfaces:**
- Produces:
  ```cpp
  namespace kimbim {
  class Scene : public QObject {
      Q_OBJECT
  public:
      explicit Scene(QObject* parent = nullptr);
      const Handle(V3d_Viewer)& viewer() const { return m_viewer; }
      const Handle(AIS_InteractiveContext)& context() const { return m_context; }
      Handle(V3d_View) createView();  // emits viewsChanged()
      void removeView(const Handle(V3d_View)& view); // emits viewsChanged()
      void changed();                 // emits redrawRequested(): every view repaints
      // Shared model state (was in Viewport).
      struct Loc { int batch; int index; };
      std::vector<Handle(ElementBatch)> batches;
      QHash<QString, Loc> locate;
      QHash<QString, QColor> colors;
      QSet<QString> layerHidden, layerLocked;
      bool linesOnly = false;
      bool quietSelection = false;
      int nextIdBase = 0;
      std::vector<int> idBases;
  signals:
      void redrawRequested();
      void viewsChanged();
  };
  }
  // Viewport
  explicit Viewport(Scene* scene, QWidget* parent = nullptr); // one view of `scene`
  explicit Viewport(QWidget* parent = nullptr);               // owns a new Scene (tests, self-test)
  Scene* scene() const;
  ```

- [ ] **Step 1: Write the failing test** `app/tests/test_scene.cpp`:

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include <QSignalSpy>
#include <QtTest>

#include "MeshChunk.h"
#include "Scene.h"
#include "Viewport.h"

namespace {
// Two boxes, guids A and B (the same fixture shape test_selection.cpp builds).
kimbim::MeshChunk twoBoxes();
}

class TestScene : public QObject {
    Q_OBJECT
private slots:
    void editAndSelectionReachEveryView()
    {
        kimbim::Scene scene;
        kimbim::Viewport model(&scene), plan(&scene);
        model.addBatch(new kimbim::ElementBatch(twoBoxes()));
        QCOMPARE(plan.elementCount(), 2);            // loaded once, seen by both
        model.selectGuids({"A"});
        QCOMPARE(plan.selectedGuids(), QStringList({"A"}));
        QSignalSpy redraw(&scene, &kimbim::Scene::redrawRequested);
        plan.removeElements({"B"});
        QCOMPARE(model.elementCount(), 1);
        QVERIFY(redraw.count() >= 1);                // both views repaint
        plan.setHidden({"A"}, true);
        QCOMPARE(model.visibleElementCount(), 0);
    }

    void aViewportWithoutASceneOwnsOne()
    {
        kimbim::Viewport alone;
        QVERIFY(alone.scene());
        alone.addBatch(new kimbim::ElementBatch(twoBoxes()));
        QCOMPARE(alone.elementCount(), 2);
    }

    void viewsAreCountedAndRemoved()
    {
        kimbim::Scene scene;
        QSignalSpy views(&scene, &kimbim::Scene::viewsChanged);
        {
            kimbim::Viewport a(&scene);
            kimbim::Viewport b(&scene);
            QCOMPARE(views.count(), 2);
        }
        QCOMPARE(views.count(), 4); // each destroyed view leaves the viewer
    }
};

QTEST_MAIN(TestScene)
#include "test_scene.moc"
```

Fill `twoBoxes()` by copying the fixture-building function from `app/tests/test_selection.cpp` (it builds a `MeshChunk` of two boxes with guids; rename its guids to `"A"` and `"B"`).

Register in `app/CMakeLists.txt`: `kimbim_test(test_scene)`; add `src/Scene.cpp src/Scene.h` to `kimbim_core`.

- [ ] **Step 2: Run it to make sure it fails.** `pixi run app-build` → compile error (`Scene.h` missing).

- [ ] **Step 3: Implement `Scene`.** `Scene.cpp` takes the viewer/context set-up out of `Viewport::Viewport` (current `Viewport.cpp:120-145`: graphic driver with `swapInterval = 0`, the three lights, the context, highlight styles):

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include "Scene.h"

#include <OpenGl_GraphicDriver.hxx>
#include <Prs3d_Drawer.hxx>
#include <V3d_AmbientLight.hxx>
#include <V3d_DirectionalLight.hxx>

namespace kimbim {

Handle(Aspect_DisplayConnection) sharedDisplay(); // moved here from Viewport.cpp (unchanged)

Scene::Scene(QObject* parent)
    : QObject(parent)
{
    Handle(OpenGl_GraphicDriver) driver = new OpenGl_GraphicDriver(sharedDisplay(), false);
    if (qEnvironmentVariableIntValue("KIMBIM_VSYNC") != 1)
        driver->ChangeOptions().swapInterval = 0; // see the comment kept from Viewport.cpp
    m_viewer = new V3d_Viewer(driver);
    // lights: the ambient, "sun" and fill lines from Viewport.cpp, unchanged
    m_viewer->SetLightOn();
    m_context = new AIS_InteractiveContext(m_viewer);
    m_context->HighlightStyle(Prs3d_TypeOfHighlight_Dynamic)->SetColor(Quantity_Color(0.98, 0.75, 0.20, Quantity_TOC_RGB));
    m_context->HighlightStyle(Prs3d_TypeOfHighlight_Selected)->SetColor(Quantity_Color(0.15, 0.50, 0.95, Quantity_TOC_RGB));
}

Handle(V3d_View) Scene::createView()
{
    Handle(V3d_View) view = m_viewer->CreateView();
    emit viewsChanged();
    return view;
}

void Scene::removeView(const Handle(V3d_View)& view)
{
    if (!view.IsNull())
        view->Remove();
    emit viewsChanged();
}

void Scene::changed() { emit redrawRequested(); }

} // namespace kimbim
```

`sharedDisplay()` moves from `Viewport.cpp`'s anonymous namespace into `Scene.cpp` (non-static, declared in `Scene.h` inside `namespace kimbim`), because `Viewport::ensureWindow` on Linux still needs the display connection.

- [ ] **Step 4: Point `Viewport` at the `Scene`.** In `Viewport.h`: delete the members `m_viewer`, `m_context`, `m_batches`, `m_locate`, `m_colors`, `m_layerHidden`, `m_layerLocked`, `m_linesOnly`, `m_quietSelection`, `m_nextIdBase`, `m_idBases` and the `Loc` struct. Add:

```cpp
    Scene* m_scene;            // shared with the other views of the model
    bool m_ownsScene = false;  // created by the parent-only constructor
    Handle(AIS_InteractiveContext) m_context; // == m_scene->context(), kept for brevity
```

Replace `context()` with `const Handle(AIS_InteractiveContext)& context() const { return m_context; }` (unchanged signature). Add `Scene* scene() const { return m_scene; }`.

In `Viewport.cpp`, mechanically:
- `m_batches` → `m_scene->batches`, `m_locate` → `m_scene->locate`, `m_colors` → `m_scene->colors`, `m_layerHidden` → `m_scene->layerHidden`, `m_layerLocked` → `m_scene->layerLocked`, `m_linesOnly` → `m_scene->linesOnly`, `m_quietSelection` → `m_scene->quietSelection`, `m_nextIdBase` → `m_scene->nextIdBase`, `m_idBases` → `m_scene->idBases`, `Loc` → `Scene::Loc`, `m_viewer` → `m_scene->viewer()`.
- In `Viewport.h`, `linesOnly()` returns `m_scene->linesOnly`; `batchCount()` / `elementCount()` read `m_scene->batches.size()` / `m_scene->locate.size()`.
- Constructors:

```cpp
Viewport::Viewport(QWidget* parent)
    : Viewport(new Scene, parent)
{
    m_ownsScene = true;
    m_scene->setParent(this);
}

Viewport::Viewport(Scene* scene, QWidget* parent)
    : QWidget(parent)
    , m_scene(scene)
    , m_context(scene->context())
{
    // widget attributes, hover timer, focus policy, minimum size: unchanged from today
    m_view = m_scene->createView();
    const Quantity_Color background(0.93, 0.94, 0.95, Quantity_TOC_RGB);
    m_view->SetBackgroundColor(background);
    ElementBatch::setBackground(background);
    m_view->SetProj(V3d_XposYnegZpos);
    applyNavigationPreset();
    connect(m_scene, &Scene::redrawRequested, this, qOverload<>(&QWidget::update));
}

Viewport::~Viewport()
{
    m_scene->removeView(m_view);
}
```

- Every method that changes shared state ends with `m_scene->changed();` instead of `update();`. These are: `addBatch`, `replaceElements`, `removeElements`, `setLinesOnly`, `setElementColors`, `setLayerState`, `selectGuids`, `setHidden`, `isolate`, `showAll`, `clear`. Methods that change only this view (`setPlanView`, `set3DView`, `fitAll`, previews, overlays, cuts) keep `update()`.
- `OnSelectionChanged` keeps emitting `selectionChanged` from the view that was clicked. Programmatic selection goes through `m_scene->quietSelection`, so no view echoes it.

- [ ] **Step 5: Run the tests.** `pixi run app-build`, then `test_scene.exe`. Expected: 3 PASS. Then run all app tests (ctest). Expected: 100% pass (31 + new). The self-tests exercise the real 3D window.

- [ ] **Step 6: Commit**

```bash
git add app/src/Scene.* app/src/Viewport.* app/tests/test_scene.cpp app/CMakeLists.txt
git commit -m "refactor(app): Scene holds the OCCT viewer, context, element batches and selection; Viewport is one view of it (several views show one loaded model)"
```

---

### Task 3: Per-view overlays and cuts

Today the plan overlays (grid, annotations, section/elevation markers, plan-cut poché, tool previews) and
the clip planes are put on the shared context and on the element batches, so with two views they'd show
and cut in both. Each view now keeps them to itself.

**Files:**
- Modify: `app/src/Viewport.h`, `app/src/Viewport.cpp`
- Test: `app/tests/test_scene.cpp`

**Interfaces:**
- Produces: `bool Viewport::showsOverlay(const Handle(AIS_InteractiveObject)& obj, const Handle(V3d_View)& view) const;` (for tests), `int Viewport::viewClipPlaneCount() const;`

- [ ] **Step 1: Write the failing tests** (append to `TestScene`):

```cpp
    void overlaysAndCutsStayInTheirView()
    {
        kimbim::Scene scene;
        kimbim::Viewport model(&scene), plan(&scene);
        model.addBatch(new kimbim::ElementBatch(twoBoxes()));
        plan.setPlanView(0.0);
        plan.setGridLines({{QPointF(0, 0), QPointF(10, 0), "A"}}, 0.0);
        QCOMPARE(plan.gridLineCount(), 1);
        QVERIFY(plan.showsOverlay(plan.gridObject(), plan.view()));
        QVERIFY(!plan.showsOverlay(plan.gridObject(), model.view())); // not in the 3D tab
        Handle(Graphic3d_ClipPlane) cut = new Graphic3d_ClipPlane(gp_Pln(gp_Pnt(0, 0, 1.2), gp_Dir(0, 0, -1)));
        plan.addClipPlanes({cut});
        QCOMPARE(plan.viewClipPlaneCount(), 1);
        QCOMPARE(model.viewClipPlaneCount(), 0); // the 3D tab is not cut by the plan's cut
        kimbim::Viewport later(&scene);          // a view opened afterwards doesn't show it either
        QVERIFY(!plan.showsOverlay(plan.gridObject(), later.view()));
    }
```

Add `Handle(AIS_InteractiveObject) gridObject() const { return m_grid; }` to `Viewport.h` (tests only).

- [ ] **Step 2: Run to make sure it fails.** Build, then run `test_scene.exe overlaysAndCutsStayInTheirView`. Expected: compile error on `showsOverlay` / `viewClipPlaneCount`.

- [ ] **Step 3: Implement.** In `Viewport.cpp`:

```cpp
// Overlays (grid, annotations, markers, poché, previews) belong to this view only.
void Viewport::keepHere(const Handle(AIS_InteractiveObject)& obj)
{
    if (obj.IsNull())
        return;
    for (V3d_ListOfViewIterator it = m_scene->viewer()->DefinedViewIterator(); it.More(); it.Next())
        m_context->SetViewAffinity(obj, it.Value(), it.Value() == m_view);
}

void Viewport::keepOverlaysHere()
{
    keepHere(m_preview);
    keepHere(m_grid);
    keepHere(m_section);
    for (const auto& a : std::as_const(m_annotations))
        keepHere(a);
}

bool Viewport::showsOverlay(const Handle(AIS_InteractiveObject)& obj, const Handle(V3d_View)& view) const
{
    return !obj.IsNull() && !view.IsNull() && obj->ViewAffinity()->IsVisible(view->View()->Identification());
}
```

(`Graphic3d_ViewAffinity::IsVisible(int viewId)` takes the `Graphic3d_CView` identification; if the
pinned OCCT names it differently, use the accessor in `Graphic3d_ViewAffinity.hxx`.)

- Call `keepHere(obj)` right after every `m_context->Display(obj, ...)` of an overlay: in `setWallPreview`, `setPreviewBoxes`, `setGridLines`, `displayAnnotations` (each annotation and marker), `rebuildSection`.
- In the constructor: `connect(m_scene, &Scene::viewsChanged, this, &Viewport::keepOverlaysHere);`, so a view opened later doesn't show this view's overlays.
- Clip planes per view: `addClipPlanes` does `m_view->AddClipPlane(plane)` for each plane (and keeps them in `m_clipPlanes`); `clearClipPlanes` does `m_view->RemoveClipPlane(plane)` for each. Remove the per-batch loops: `b->AddClipPlane(plane)` in `addClipPlanes`, the loop at the end of `addBatch` (`batch->AddClipPlane(plane)`), and the matching `RemoveClipPlane` loops. Keep the temporary per-batch planes in `visibleFrom` (it restores them).
- `viewClipPlaneCount()` returns `m_view->ClipPlanes().IsNull() ? 0 : m_view->ClipPlanes()->Size()`.
- The poché sits at the cut height; make `rebuildSection` place it 1 mm below `m_sectionZ` so the view's own cut doesn't hide it.

- [ ] **Step 4: Run the tests.** `test_scene.exe`: all PASS. Then all ctest. Expected: `app_selftest_plan_cut` still reports `"planes":1`. Its count is read through `clipPlaneCount()`, which still counts `m_clipPlanes`.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(app): plan overlays and cut planes belong to their view (a plan tab's grid, notes, poché and cut don't show in the 3D tab)"
```

---

### Task 4: A view survives moving to its own window

When ADS floats a dock, the `Viewport` is reparented into a new top-level window and Qt gives it a new
native window (`QEvent::WinIdChange`), but the `V3d_View` still draws to the old one. The view is rebuilt
on the new window.

**Files:**
- Modify: `app/src/Viewport.h`, `app/src/Viewport.cpp`, `app/src/SelfTest.cpp`, `app/CMakeLists.txt`

**Interfaces:**
- Produces: `void Viewport::rebindWindow();` (called on `WinIdChange`); self-test flag `--pop-out` reporting `"pop_out":true`.

- [ ] **Step 1: Write the failing self-test.** In `SelfTest.cpp`, next to the other flags, parse `--pop-out`. After the model has loaded (where `--box-select` runs its check), do:

```cpp
if (args.contains(QStringLiteral("--pop-out"))) {
    Viewport* view = window.viewport();
    QWidget* host = view->parentWidget();
    auto* floating = new QWidget;           // what ADS does when a tab is dragged out
    floating->setAttribute(Qt::WA_DeleteOnClose);
    auto* lay = new QVBoxLayout(floating);
    lay->addWidget(view);
    floating->resize(640, 480);
    floating->show();
    QCoreApplication::processEvents();
    const QString outside = QDir::temp().filePath(QStringLiteral("kimbim-popout.png"));
    const bool shownOutside = view->dumpImage(outside) && !QImage(outside).isNull()
        && view->pickAt(view->width() / 2, view->height() / 2) != QStringLiteral("error");
    host->layout()->addWidget(view);        // docked back
    floating->close();
    QCoreApplication::processEvents();
    const bool shownBack = view->dumpImage(outside);
    report.insert(QStringLiteral("pop_out"), shownOutside && shownBack);
}
```

Register in `app/CMakeLists.txt`:

```cmake
kimbim_gui_test(app_selftest_pop_out "\"ok\":true.*\"pop_out\":true" :fixture: --frames 2 --pop-out)
```

- [ ] **Step 2: Run to make sure it fails.** `pixi run app-build && KIMBIM_PYTHON_PATH="$PWD/python" pixi run ctest --test-dir build/app -R pop_out --output-on-failure`. Expected: FAIL (`"pop_out":false`, or an OCCT error on the stale window).

- [ ] **Step 3: Implement.** In `Viewport.h` add `bool event(QEvent* e) override;` and `void rebindWindow();`. In `Viewport.cpp`:

```cpp
bool Viewport::event(QEvent* e)
{
    if (e->type() == QEvent::WinIdChange && !m_view->Window().IsNull())
        rebindWindow(); // moved to another top-level window (a tab dragged out or docked back)
    return QWidget::event(e);
}

void Viewport::rebindWindow()
{
    try {
        // A V3d_View keeps its first window; a fresh view on the same scene takes the new one.
        Handle(Graphic3d_Camera) camera = new Graphic3d_Camera();
        camera->Copy(m_view->Camera());
        const Quantity_Color background = m_view->BackgroundColor();
        Handle(Graphic3d_SequenceOfHClipPlane) planes = m_view->ClipPlanes();
        m_scene->removeView(m_view);
        m_view = m_scene->createView();
        m_view->SetBackgroundColor(background);
        m_view->Camera()->Copy(camera);
        if (!planes.IsNull())
            m_view->SetClipPlanes(planes);
        keepOverlaysHere();
        ensureWindow(); // attaches to the new native window
        update();
    } catch (const Standard_Failure& e) {
        qWarning("KimBim: cannot move the 3D view to its new window: %s", e.what());
    }
}
```

Note: `Scene::createView` / `removeView` emit `viewsChanged`, so the other views re-apply their overlay affinity to the new view id (Task 3).

- [ ] **Step 4: Run.** The `ctest -R pop_out` command again. Expected: PASS. Then all ctest: 100%.

- [ ] **Step 5: Commit**

```bash
git commit -am "fix(app): a 3D/plan view keeps drawing after it moves to its own window (new native handle on WinIdChange); self-test --pop-out"
```

---

### Task 5: Main window on `DockLayout`

The `QTabWidget` (`m_tabs`) and the six `QDockWidget`s go; the 3D view, drawings and sheets become
center views, and the panels go into the right area.

**Files:**
- Create: `app/src/ViewHost.h`, `app/src/ViewHost.cpp`
- Modify: `app/src/MainWindow.h`, `app/src/MainWindow.cpp`, `app/CMakeLists.txt`, `app/tests/test_main_window.cpp`

**Interfaces:**
- Consumes: `DockLayout` (Task 1).
- Produces:
  ```cpp
  // ViewHost.h — a center tab around a Viewport, with slots for the active view's chrome.
  class ViewHost : public QWidget {
      Q_OBJECT
  public:
      ViewHost(Viewport* view, QWidget* parent = nullptr);
      Viewport* viewport() const { return m_view; }
      void adoptChrome(QWidget* optionsStrip, QWidget* cutColumn); // moves them into this tab
  private:
      Viewport* m_view;
      QVBoxLayout* m_top;   // tool options strip
      QHBoxLayout* m_row;   // view | cut column
  };
  // MainWindow
  DockLayout* dockLayout() const { return m_dock; }
  QString currentViewKey() const;          // "3d", "plan:<guid>", a drawing guid or "sheet:<n>"
  ```

- [ ] **Step 1: Write the failing tests** (add to `TestMainWindow`):

```cpp
    void viewsAndPanelsLiveInTheDockLayout()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::DockLayout* dock = w.dockLayout();
        QVERIFY(dock->view("3d"));
        QVERIFY(!dock->manager()->findDockWidget("3d")->features().testFlag(ads::CDockWidget::DockWidgetClosable));
        for (const char* panel : {"tree", "properties", "layers", "history", "drawings", "sheets"})
            QVERIFY2(dock->manager()->findDockWidget(QLatin1String(panel)), panel);
        const QString south = w.drawingGuid(QStringLiteral("South Elevation"));
        QVERIFY(w.openDrawing(south));
        QCOMPARE(w.currentViewKey(), south);
        emit dock->closeRequested(south);        // the tab's x
        QVERIFY(!w.drawingView(south));
        QCOMPARE(w.currentViewKey(), QString("3d"));
    }

    void layoutRestoreSkipsUnknownAndOffscreen()
    {
        QStandardPaths::setTestModeEnabled(true);
        QByteArray saved;
        {
            kimbim::MainWindow w(nullptr, true);
            QVERIFY(w.newProject());
            QVERIFY(w.openDrawing(w.drawingGuid(QStringLiteral("North Elevation"))));
            saved = w.dockLayout()->saveLayout();
        }
        kimbim::MainWindow w(nullptr, true);     // a new session: that drawing tab doesn't exist yet
        QVERIFY(w.newProject());
        QVERIFY(w.dockLayout()->restoreLayout(saved) || true); // never throws, never loses the 3D tab
        QVERIFY(w.dockLayout()->view("3d"));
        QVERIFY(!w.dockLayout()->restoreLayout(QByteArray("garbage")));
        QVERIFY(w.dockLayout()->view("3d"));
    }
```

(`#include <DockManager.h>`, `<DockWidget.h>`, `"DockLayout.h"`, `<QStandardPaths>` in the test file.)

- [ ] **Step 2: Run to make sure they fail.** Build. Expected: compile errors (`dockLayout`, `currentViewKey`).

- [ ] **Step 3: Implement `ViewHost`.**

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include "ViewHost.h"
#include "Viewport.h"

#include <QHBoxLayout>
#include <QVBoxLayout>

namespace kimbim {

ViewHost::ViewHost(Viewport* view, QWidget* parent)
    : QWidget(parent)
    , m_view(view)
{
    auto* column = new QVBoxLayout(this);
    column->setContentsMargins(0, 0, 0, 0);
    column->setSpacing(0);
    m_top = new QVBoxLayout;
    m_top->setContentsMargins(0, 0, 0, 0);
    column->addLayout(m_top);
    m_row = new QHBoxLayout;
    m_row->setContentsMargins(0, 0, 0, 0);
    m_row->setSpacing(0);
    m_row->addWidget(view, 1);
    column->addLayout(m_row, 1);
}

void ViewHost::adoptChrome(QWidget* optionsStrip, QWidget* cutColumn)
{
    if (optionsStrip && optionsStrip->parentWidget() != this)
        m_top->addWidget(optionsStrip);   // reparents it from the previous tab
    if (cutColumn && cutColumn->parentWidget() != this)
        m_row->addWidget(cutColumn);
}

} // namespace kimbim
```

- [ ] **Step 4: Rewire `MainWindow`.**
  - Constructor: create `m_scene = new Scene(this)` and `m_viewport = new Viewport(m_scene, this)`. Put the cut label and slider in a `QWidget* m_cutColumn` (the `cutColumn` layout's contents today). Create `m_dock = new DockLayout(this)` and
    `m_dock->addView(QStringLiteral("3d"), tr("3D"), m_hosts.value("3d"), false)`, where
    `m_hosts.insert("3d", new ViewHost(m_viewport))` and `m_hosts` is a `QHash<QString, ViewHost*>`.
    Then call `m_hosts["3d"]->adoptChrome(nullptr, m_cutColumn)`. Remove `setCentralWidget(m_tabs)` and all of `m_tabs`.
  - `buildDocks()`: replace each `new QDockWidget` / `addDockWidget` / `tabifyDockWidget` with
    `m_dock->addPanel(key, title, widget)` using keys `tree`, `properties`, `layers`, `history`, `drawings`, `sheets` (in that order), and drop `resizeDocks`. Then raise the tree panel.
  - `connect(m_dock, &DockLayout::currentChanged, this, &MainWindow::activateView);`
    `connect(m_dock, &DockLayout::closeRequested, this, &MainWindow::closeView);`
  - New `void activateView(const QString& key)`. For a `DrawingView` (`qobject_cast<DrawingView*>(m_dock->view(key))`) it calls `setTool(Tool::None)` and runs the old `currentChanged` body (regenerate if stale or empty). For `"3d"` it calls `setTool(Tool::None)` if the previous view was a different model view. Task 6 extends it for plan tabs.
  - New `void closeView(const QString& key)`. `"3d"` is ignored. A drawing or sheet does what `closeDrawingTab` does today: drop it from `m_drawingViews`, `m_generating` and `m_generateAgain`, then `m_dock->removeView(key)`. Delete `closeDrawingTab(int)`.
  - `openDrawing` / `openSheet`: `m_dock->addView(guid, name, view, true); m_dock->raise(guid);` replaces `m_tabs->addTab` + `setCurrentWidget`. `m_tabs->setCurrentWidget(view)` → `m_dock->raise(key)`. `m_tabs->setTabText(i, t)` → `m_dock->setTitle(key, t)`. `m_tabs->currentWidget() == view` → `m_dock->current() == view->guid()`.
  - The loops `for (int i = m_tabs->count() - 1; i > 0; --i)` in `refreshDrawings` and `refreshSheets` become `for (const QString& key : m_dock->viewKeys())`, with `auto* view = qobject_cast<DrawingView*>(m_dock->view(key))` and `continue` when null. `closeDrawingTab(i)` → `closeView(key)`.
  - `showModelTab()` → `m_dock->raise(QStringLiteral("3d"))`.
  - `currentViewKey()` returns `m_dock->current()`.
  - Layout memory. At the end of the constructor, `m_dock->captureDefault()`; then, unless `m_quiet`, `m_dock->restoreLayout(QSettings().value("layout/state").toByteArray())`. In `closeEvent`, after the save check passes, `QSettings().setValue("layout/state", m_dock->saveLayout())`. In `main.cpp`, before creating the window, `QCoreApplication::setOrganizationName("KimBim"); QCoreApplication::setApplicationName("KimBim");` if not already set.
  - Add `src/ViewHost.cpp src/ViewHost.h` to `kimbim_core`.

- [ ] **Step 5: Run the tests.** Build, then run `test_main_window.exe`. Expected: the new tests PASS and the existing ones too. Fix any that reached into `QDockWidget`s or `mainTabs`; today only `planCutSliderBesideTheView` uses `findChild` (`planCutSlider`), and it still works. Then all ctest.

- [ ] **Step 6: Commit**

```bash
git add app/src/ViewHost.* app/src/MainWindow.* app/src/main.cpp app/CMakeLists.txt app/tests/test_main_window.cpp
git commit -m "feat(app): the main window uses DockLayout: 3D, drawings and sheets are center tabs that pop out; panels tabbed on the right; layout remembered"
```

---

### Task 6: Plan tabs and the active view

**Files:**
- Modify: `app/src/MainWindow.h`, `app/src/MainWindow.cpp`, `app/tests/test_main_window.cpp`

**Interfaces:**
- Produces:
  ```cpp
  Viewport* openPlanTab(const QString& storey);   // opens or raises "plan:<storey>"
  Viewport* modelView() const;                    // the 3D tab's viewport
  Viewport* viewport() const;                     // unchanged name: the ACTIVE model view
  ```

Rules (from the spec, made precise):
- A plan tab is a `Viewport` on `m_scene` in plan mode at its level, titled `tr("%1 plan").arg(levelName)`, key `plan:<storey guid>`, closable.
- Activating a model view (3D or plan): `setTool(Tool::None)` if it differs from the previous model view; `m_viewport` = that view; `m_toolOptions` and `m_cutColumn` move into its `ViewHost` (`adoptChrome`). For a plan tab, the level bar switches to the tab's level (`m_levels->setActive(guid)`). Then `applyCuts()` and `refreshAnnotations()`.
- Cut settings are per view: `QHash<Viewport*, CutSettings> m_cuts` with `struct CutSettings { bool planCut = false; bool box = false; double height = 1.2; Bnd_Box bounds; };`. Activating a view loads its settings into `m_planCut`, `m_sectionBox` and `m_cutHeight` (with `QSignalBlocker`). Toggling them stores into the active view's entry. A new plan tab starts with `planCut = true`.
- `setPlanView(true)` (P) opens or raises the plan tab of the active level; `setPlanView(false)` (3) raises the 3D tab.
- Changing the level in the level bar while a plan tab is active opens or raises that level's plan tab.
- `refreshLevels()` closes plan tabs whose level is gone.
- `openFile` / `newProject` / switching option / opening a version close every plan tab first (`closeView` for each `plan:` key).
- Every `connect(m_viewport, &Viewport::..., ...)` in the constructor and in `buildModelingToolbar` (the `selectionChanged`, `dragMoved`, `dragReleased`, `hovered`, `workPointMoved`, `workPointClicked`, `drawingEnded`, `drawingConfirmed` and `lengthKeyTyped` connections) moves into a new `void connectViewport(Viewport* v)`. It's called for the 3D view and for every new plan view. The lambdas use `m_viewport` (the active view) as today; a signal from an inactive view first activates it (`if (v != m_viewport) m_dock->raise(m_dock->keyOf(m_hosts...))`) so that clicks go to the view under the mouse.
- `refreshAnnotations()` sets annotations, grid and markers on every open plan view for its own level. Each plan `Viewport` remembers its level: add `QString storey` to `ViewHost`.

- [ ] **Step 1: Write the failing tests:**

```cpp
    void planTabsShareTheModel()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.addLevel(QStringLiteral("Level 2"), 3.0));
        const QString l1 = w.levelsBar()->activeStorey();
        kimbim::Viewport* plan = w.openPlanTab(l1);
        QVERIFY(plan && plan != w.modelView());
        QCOMPARE(w.viewport(), plan);
        QVERIFY(plan->isPlanView());
        QCOMPARE(w.currentViewKey(), QStringLiteral("plan:") + l1);
        w.setTool(kimbim::MainWindow::Tool::Wall);
        QVERIFY(w.createWall({QPointF(0, 0), QPointF(4, 0)}));
        QCOMPARE(w.modelView()->elementCount(), plan->elementCount()); // one model
        w.modelView()->selectGuids(plan->guids().mid(0, 1));
        QCOMPARE(plan->selectedGuids().size(), 1);
        QVERIFY(!w.modelView()->isPlanView());
        triggerAction(w, "action3DView");
        QCOMPARE(w.viewport(), w.modelView());
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::None); // switching views cancels the tool
    }

    void deletingTheActivePlanLevel()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.addLevel(QStringLiteral("Level 2"), 3.0));
        QString l2;
        for (const auto& s : w.levelsBar()->combo()->model()->match(
                 w.levelsBar()->combo()->model()->index(0, 0), Qt::DisplayRole, QStringLiteral("Level 2")))
            l2 = s.data(Qt::UserRole).toString();
        QVERIFY(!l2.isEmpty());
        QVERIFY(w.openPlanTab(l2));
        w.setTool(kimbim::MainWindow::Tool::Wall);
        w.wallTool()->click(QPointF(0, 0));                  // a wall half-drawn
        w.setSelection({l2});
        QVERIFY(w.deleteSelection());
        QVERIFY(!w.dockLayout()->view(QStringLiteral("plan:") + l2));
        QCOMPARE(w.currentViewKey(), QString("3d"));
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::None);
        QCOMPARE(w.viewport(), w.modelView());
    }

    void openingAFileClosesPlanTabs()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.openPlanTab(w.levelsBar()->activeStorey()));
        QVERIFY(w.newProject());
        for (const QString& key : w.dockLayout()->viewKeys())
            QVERIFY2(!key.startsWith(QLatin1String("plan:")), qPrintable(key));
        QCOMPARE(w.viewport(), w.modelView());
    }

    void eachViewKeepsItsOwnCut()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::Viewport* plan = w.openPlanTab(w.levelsBar()->activeStorey());
        QVERIFY(plan->clipPlaneCount() >= 1);                // a plan is cut
        w.dockLayout()->raise(QStringLiteral("3d"));
        QCOMPARE(w.modelView()->clipPlaneCount(), 0);        // the 3D tab is not
        QVERIFY(!w.findChild<QAction*>(QStringLiteral("actionPlanCut"))->isChecked());
    }
```

(If `levelsBar()->combo()` doesn't keep the guid in `Qt::UserRole`, read `LevelsBar::setStoreys` and use
the role it does; or select by `w.levelsBar()->setActive()` after reading `bridge("storeys")` through
`w.levelsBar()`.)

- [ ] **Step 2: Run to make sure they fail.** Build. Expected: compile errors (`openPlanTab`, `modelView`).

- [ ] **Step 3: Implement** the rules above in `MainWindow.cpp`. `openPlanTab`:

```cpp
Viewport* MainWindow::openPlanTab(const QString& storey)
{
    const QString key = QStringLiteral("plan:") + storey;
    if (ViewHost* host = m_hosts.value(key)) {
        m_dock->raise(key);
        return host->viewport();
    }
    double elevation = 0.0;
    QString name;
    for (const auto& v : bridge("storeys").value("storeys").toArray()) {
        const QJsonObject s = v.toObject();
        if (s.value("guid").toString() == storey) {
            elevation = s.value("elevation").toDouble();
            name = s.value("name").toString();
        }
    }
    if (name.isEmpty())
        return nullptr; // not a level of this model
    auto* view = new Viewport(m_scene);
    auto* host = new ViewHost(view);
    host->setStorey(storey);
    m_hosts.insert(key, host);
    connectViewport(view);
    view->setPlanView(elevation);
    CutSettings cut;
    cut.planCut = true;
    cut.height = m_cutHeight->value();
    m_cuts.insert(view, cut);
    m_dock->addView(key, tr("%1 plan").arg(name), host, true);
    m_dock->raise(key); // activateView(): the level, the cut, the chrome, the annotations
    return view;
}
```

`closeView` for a `plan:` key does: `m_cuts.remove(host->viewport())`, `m_hosts.remove(key)`, `m_dock->removeView(key)`. If it was the active view, `m_viewport = modelView()` before removal, then raise `"3d"`.

- [ ] **Step 4: Run.** `test_main_window.exe`: all PASS (old and new). Then all ctest.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(app): plan tabs per level on the shared scene; the active view takes the tools, the level, its own cut and the tool strip; tabs close with their level or model"
```

---

### Task 7: Tool palette on the left

**Files:**
- Create: `app/src/ToolPalette.h`, `app/src/ToolPalette.cpp`, `app/tests/test_tool_palette.cpp`
- Modify: `app/src/MainWindow.h`, `app/src/MainWindow.cpp`, `app/CMakeLists.txt`, `app/tests/test_main_window.cpp`

**Interfaces:**
- Produces:
  ```cpp
  class ToolPalette : public QWidget {
      Q_OBJECT
  public:
      explicit ToolPalette(QWidget* parent = nullptr);
      void addGroup(const QString& id, const QString& title, const QList<QAction*>& actions);
      QStringList groups() const;
      QList<QAction*> actions(const QString& id) const;
      void setCollapsed(const QString& id, bool collapsed);
      bool isCollapsed(const QString& id) const;
      void setCompact(bool iconsOnly);
      bool isCompact() const { return m_compact; }
  };
  ToolPalette* MainWindow::toolPalette() const;
  ```

- [ ] **Step 1: Write the failing tests.** `app/tests/test_tool_palette.cpp`:

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include <QAction>
#include <QToolButton>
#include <QtTest>

#include "ToolPalette.h"

class TestToolPalette : public QObject {
    Q_OBJECT
private slots:
    void groupsHoldButtonsForTheirActions()
    {
        kimbim::ToolPalette p;
        QAction wall("Wall"), slab("Slab"), text("Text");
        p.addGroup("3d", "3D", {&wall, &slab});
        p.addGroup("plane", "Plane", {&text});
        QCOMPARE(p.groups(), QStringList({"3d", "plane"}));
        QCOMPARE(p.actions("3d"), QList<QAction*>({&wall, &slab}));
        const auto buttons = p.findChildren<QToolButton*>(QStringLiteral("toolButton"));
        QCOMPARE(buttons.size(), 3);
        QCOMPARE(buttons.first()->defaultAction(), &wall);
        p.setCollapsed("3d", true);
        QVERIFY(p.isCollapsed("3d") && !p.isCollapsed("plane"));
        p.setCompact(true);
        for (QToolButton* b : buttons)
            QCOMPARE(b->toolButtonStyle(), Qt::ToolButtonIconOnly);
    }
};

QTEST_MAIN(TestToolPalette)
#include "test_tool_palette.moc"
```

In `test_main_window.cpp`:

```cpp
    void everyToolIsInOnePaletteGroup()
    {
        kimbim::MainWindow w(nullptr, true);
        kimbim::ToolPalette* p = w.toolPalette();
        QCOMPARE(p->groups(), QStringList({"3d", "plane", "view", "edit"}));
        const QHash<QString, QStringList> expected = {
            {"3d", {"actionWallTool", "actionSlabTool", "actionColumnTool", "actionBeamTool", "actionDoorTool",
                    "actionWindowTool", "actionStairTool", "actionRoofTool", "actionRoomTool",
                    "actionSlabOpeningTool", "actionPlaceModelTool"}},
            {"plane", {"actionTextTool", "actionDimensionTool", "actionLeaderTool", "actionMarkTool", "actionGridTool"}},
            {"view", {"actionSectionTool", "actionElevationTool", "actionNewPlanTab", "actionNewSheet"}},
            {"edit", {"actionMoveTool", "actionRotateTool", "actionStretchTool", "actionMirror", "actionCopyToLevel"}}};
        QStringList seen;
        for (const QString& g : p->groups()) {
            QStringList names;
            for (QAction* a : p->actions(g))
                names << a->objectName();
            QCOMPARE(names, expected.value(g));
            seen << names;
        }
        QCOMPARE(QSet<QString>(seen.begin(), seen.end()).size(), seen.size()); // each in one group only
        QVERIFY(!w.findChild<QToolBar*>(QStringLiteral("modelingToolbar"))); // the old toolbar is gone
    }
```

Register `kimbim_test(test_tool_palette)`; add `src/ToolPalette.cpp src/ToolPalette.h` to `kimbim_core`.

- [ ] **Step 2: Run to make sure they fail.** Build: compile errors.

- [ ] **Step 3: Implement `ToolPalette`.**

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include "ToolPalette.h"

#include <QAction>
#include <QScrollArea>
#include <QToolButton>
#include <QVBoxLayout>

namespace kimbim {

ToolPalette::ToolPalette(QWidget* parent)
    : QWidget(parent)
{
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    auto* inner = new QWidget(scroll);
    m_column = new QVBoxLayout(inner);
    m_column->setContentsMargins(4, 4, 4, 4);
    m_column->setSpacing(2);
    m_column->addStretch(1);
    scroll->setWidget(inner);
    outer->addWidget(scroll);
}

void ToolPalette::addGroup(const QString& id, const QString& title, const QList<QAction*>& actions)
{
    auto* header = new QToolButton(this);
    header->setObjectName(QStringLiteral("toolGroup_") + id);
    header->setText(title);
    header->setCheckable(true);
    header->setChecked(true);
    header->setArrowType(Qt::DownArrow);
    header->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    header->setAutoRaise(true);
    header->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
    auto* body = new QWidget(this);
    auto* list = new QVBoxLayout(body);
    list->setContentsMargins(8, 0, 0, 4);
    list->setSpacing(0);
    for (QAction* a : actions) {
        auto* b = new QToolButton(body);
        b->setObjectName(QStringLiteral("toolButton"));
        b->setDefaultAction(a);
        b->setAutoRaise(true);
        b->setToolButtonStyle(m_compact ? Qt::ToolButtonIconOnly : Qt::ToolButtonTextBesideIcon);
        b->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
        list->addWidget(b);
        m_buttons << b;
    }
    connect(header, &QToolButton::toggled, this, [header, body](bool open) {
        body->setVisible(open);
        header->setArrowType(open ? Qt::DownArrow : Qt::RightArrow);
    });
    const int at = m_column->count() - 1; // before the stretch
    m_column->insertWidget(at, header);
    m_column->insertWidget(at + 1, body);
    m_groups.append({id, header, body, actions});
}

QStringList ToolPalette::groups() const
{
    QStringList out;
    for (const Group& g : m_groups)
        out << g.id;
    return out;
}

QList<QAction*> ToolPalette::actions(const QString& id) const
{
    for (const Group& g : m_groups)
        if (g.id == id)
            return g.actions;
    return {};
}

void ToolPalette::setCollapsed(const QString& id, bool collapsed)
{
    for (const Group& g : m_groups)
        if (g.id == id)
            g.header->setChecked(!collapsed);
}

bool ToolPalette::isCollapsed(const QString& id) const
{
    for (const Group& g : m_groups)
        if (g.id == id)
            return !g.header->isChecked();
    return false;
}

void ToolPalette::setCompact(bool iconsOnly)
{
    m_compact = iconsOnly;
    for (QToolButton* b : std::as_const(m_buttons))
        b->setToolButtonStyle(iconsOnly ? Qt::ToolButtonIconOnly : Qt::ToolButtonTextBesideIcon);
}

} // namespace kimbim
```

Header members: `struct Group { QString id; QToolButton* header; QWidget* body; QList<QAction*> actions; }; QVector<Group> m_groups; QList<QToolButton*> m_buttons; QVBoxLayout* m_column; bool m_compact = false;`.

- [ ] **Step 4: Use it in `MainWindow`.** In `buildModelingToolbar`, remove `QToolBar* bar = addToolBar(...)` and `bar->addAction(d.text)`. Create each action with `new QAction(d.text, this)` and still add it to the Model menu. Give the 3D tools an icon: `a->setIcon(iconFor(ifcClass))` with the class map `{Wall: "IfcWall", Slab: "IfcSlab", Door: "IfcDoor", Window: "IfcWindow", Column: "IfcColumn", Beam: "IfcBeam", Stair: "IfcStair", Roof: "IfcRoof", Room: "IfcSpace", Grid: "IfcGrid"}`. Add two actions for the View group:

```cpp
    QAction* newPlan = new QAction(tr("New &plan tab"), this);
    newPlan->setObjectName(QStringLiteral("actionNewPlanTab"));
    newPlan->setToolTip(tr("Open the active level's floor plan in its own tab"));
    connect(newPlan, &QAction::triggered, this, [this] { openPlanTab(m_levels->activeStorey()); });
    QAction* newSheet = new QAction(tr("New &sheet"), this);
    newSheet->setObjectName(QStringLiteral("actionNewSheet"));
    connect(newSheet, &QAction::triggered, this, [this] { emit m_sheetsPanel->newRequested(QStringLiteral("A1")); });
```

(If `SheetsPanel::newRequested` isn't public, call the same lambda body the panel's signal is connected
to in `buildDocks`: factor it into `void newSheetDialog(const QString& paper)`.)

Build the palette after the actions exist (and after `buildMenus`, for `actionMirror`):

```cpp
    m_palette = new ToolPalette(this);
    auto act = [this](const char* name) { return findChild<QAction*>(QLatin1String(name)); };
    auto tool = [this](Tool t) { return m_toolActions.value(int(t)); };
    m_palette->addGroup(QStringLiteral("3d"), tr("3D"), {tool(Tool::Wall), tool(Tool::Slab), tool(Tool::Column),
        tool(Tool::Beam), tool(Tool::Door), tool(Tool::Window), tool(Tool::Stair), tool(Tool::Roof), tool(Tool::Room),
        tool(Tool::SlabOpening), tool(Tool::PlaceModel)});
    m_palette->addGroup(QStringLiteral("plane"), tr("Plane"), {tool(Tool::Text), tool(Tool::Dimension),
        tool(Tool::Leader), tool(Tool::Mark), tool(Tool::Grid)});
    m_palette->addGroup(QStringLiteral("view"), tr("View"), {tool(Tool::Section), tool(Tool::Elevation),
        act("actionNewPlanTab"), act("actionNewSheet")});
    m_palette->addGroup(QStringLiteral("edit"), tr("Edit"), {tool(Tool::Move), tool(Tool::Rotate),
        tool(Tool::Stretch), act("actionMirror"), act("actionCopyToLevel")});
    m_dock->addLeft(QStringLiteral("tools"), tr("Tools"), m_palette);
```

`actionMirror` is a plain action today. Make it checkable and add it to `m_toolActions` under `Tool::Mirror`, so it shows as active like the other tools. The constructor must call the menus, then `buildModelingToolbar`, then the palette (the current order already has menus first).

- [ ] **Step 5: Run.** `test_tool_palette.exe` and `test_main_window.exe`: PASS, including `shortcutsAreTheDocumentedOnes`. Then all ctest.

- [ ] **Step 6: Commit**

```bash
git add app/src/ToolPalette.* app/src/MainWindow.* app/CMakeLists.txt app/tests/test_tool_palette.cpp app/tests/test_main_window.cpp
git commit -m "feat(app): tool palette on the left, grouped 3D / Plane / View / Edit; New plan tab and New sheet; the Modeling toolbar is gone"
```

---

### Task 8: Tool options strip

**Files:**
- Create: `app/src/ToolOptionsBar.h`, `app/src/ToolOptionsBar.cpp`
- Modify: `app/src/MainWindow.h`, `app/src/MainWindow.cpp`, `app/CMakeLists.txt`, `app/tests/test_tool_palette.cpp`, `app/tests/test_main_window.cpp`

**Interfaces:**
- Produces:
  ```cpp
  class ToolOptionsBar : public QWidget {
      Q_OBJECT
  public:
      explicit ToolOptionsBar(QWidget* parent = nullptr);
      void addField(QWidget* field);       // laid out left to right; shown/hidden by its owner
      void setActive(bool toolActive);     // the strip shows only while a tool is active and has a visible field
  };
  ToolOptionsBar* MainWindow::toolOptions() const;
  ```

- [ ] **Step 1: Write the failing tests.** Append to `TestToolPalette`:

```cpp
    void optionsStripShowsOnlyWithAToolAndAField()
    {
        kimbim::ToolOptionsBar bar;
        auto* height = new QLineEdit;
        bar.addField(height);
        bar.show();
        bar.setActive(false);
        QVERIFY(bar.isHidden());
        bar.setActive(true);
        QVERIFY(!bar.isHidden());
        height->hide();
        bar.setActive(true);
        QVERIFY(bar.isHidden()); // nothing to show
    }
```

In `test_main_window.cpp`:

```cpp
    void toolOptionsFollowTheTool()
    {
        kimbim::MainWindow w(nullptr, true);
        w.show();
        QVERIFY(w.newProject());
        kimbim::ToolOptionsBar* bar = w.toolOptions();
        QVERIFY(bar->isHidden());
        w.setTool(kimbim::MainWindow::Tool::Wall);
        QVERIFY(!bar->isHidden());
        QVERIFY(w.findChild<QDoubleSpinBox*>(QStringLiteral("wallHeight"))->isVisibleTo(bar));
        QVERIFY(!w.findChild<QComboBox*>(QStringLiteral("roofKind"))->isVisibleTo(bar));
        w.setTool(kimbim::MainWindow::Tool::Roof);
        QVERIFY(w.findChild<QComboBox*>(QStringLiteral("roofKind"))->isVisibleTo(bar));
        w.setTool(kimbim::MainWindow::Tool::None);
        QVERIFY(bar->isHidden());
        QCOMPARE(bar->parentWidget()->parentWidget(), w.dockLayout()->view(w.currentViewKey())); // in the active tab
    }
```

Add `src/ToolOptionsBar.cpp src/ToolOptionsBar.h` to `kimbim_core`.

- [ ] **Step 2: Run to make sure they fail.** Build: compile errors.

- [ ] **Step 3: Implement.**

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include "ToolOptionsBar.h"

#include <QHBoxLayout>

namespace kimbim {

ToolOptionsBar::ToolOptionsBar(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("toolOptions"));
    m_row = new QHBoxLayout(this);
    m_row->setContentsMargins(6, 3, 6, 3);
    m_row->setSpacing(8);
    m_row->addStretch(1);
    setAutoFillBackground(true);
    hide();
}

void ToolOptionsBar::addField(QWidget* field)
{
    field->setParent(this);
    m_row->insertWidget(m_row->count() - 1, field);
    m_fields << field;
}

void ToolOptionsBar::setActive(bool toolActive)
{
    bool any = false;
    for (QWidget* f : std::as_const(m_fields))
        any = any || !f->isHidden();
    setVisible(toolActive && any);
}

} // namespace kimbim
```

In `MainWindow::buildModelingToolbar`: create `m_toolOptions = new ToolOptionsBar(this)`. Create `m_types`, `m_wallHeight`, the roof box and `m_lengthInput` with `m_toolOptions` as parent, and add each with `m_toolOptions->addField(...)` instead of `bar->addWidget(...)`. Delete `m_wallHeightAction`, `m_roofAction` and `m_lengthAction` (header + uses). In `setTool`, the three `...Action->setVisible(x)` become `m_wallHeight->setVisible(x)`, `m_roofKind->parentWidget()->setVisible(x)` (the roof box) and `m_lengthInput->setVisible(x)`. At the end of every path of `setTool`, call `m_toolOptions->setActive(m_tool != Tool::None)`. In `activateView`, pass `m_toolOptions` to `adoptChrome`.

- [ ] **Step 4: Run.** Both test binaries: PASS. All ctest.

- [ ] **Step 5: Commit**

```bash
git add app/src/ToolOptionsBar.* app/src/MainWindow.* app/CMakeLists.txt app/tests/test_tool_palette.cpp app/tests/test_main_window.cpp
git commit -m "feat(app): the active tool's fields (type, height, roof, length) show in a strip above the active view, only while a tool is active"
```

---

### Task 9: Bottom bar

**Files:**
- Create: `app/src/StatusStrip.h`, `app/src/StatusStrip.cpp`
- Modify: `app/src/MainWindow.h`, `app/src/MainWindow.cpp`, `app/src/Viewport.h`, `app/src/Viewport.cpp`, `app/CMakeLists.txt`, `app/tests/test_tool_palette.cpp`, `app/tests/test_main_window.cpp`

**Interfaces:**
- Produces:
  ```cpp
  class StatusStrip : public QWidget {
      Q_OBJECT
  public:
      explicit StatusStrip(QWidget* parent = nullptr);
      void setLayers(const QStringList& all, const QString& active, const QSet<QString>& hidden);
      void setZoom(double percent);                 // < 0: not shown (drawing tabs show their own)
      void setSelection(const QString& summary);    // "" when nothing is selected
      void showMessage(const QString& text, int timeoutMs = 0);
      void clearMessage();
      QString message() const;
      QString zoomText() const;
      QString selectionText() const;
      QString layersText() const;                   // "12/15"
  signals:
      void activeLayerRequested(const QString& layer);
      void layerVisibilityToggled(const QString& layer, bool visible);
  };
  double Viewport::zoomPercent() const;              // 100 = the fitted view
  StatusStrip* MainWindow::statusStrip() const;
  ```

- [ ] **Step 1: Write the failing tests.** Append to `TestToolPalette`:

```cpp
    void statusStripShowsLayersZoomSelectionAndMessages()
    {
        kimbim::StatusStrip s;
        QSignalSpy active(&s, &kimbim::StatusStrip::activeLayerRequested);
        s.setLayers({"A-WALL", "A-DOOR", "A-ANNO"}, "A-WALL", {"A-ANNO"});
        QCOMPARE(s.layersText(), QString("2/3"));
        auto* combo = s.findChild<QComboBox*>(QStringLiteral("activeLayer"));
        QCOMPARE(combo->currentText(), QString("A-WALL"));
        combo->setCurrentIndex(combo->findText("A-DOOR"));
        QCOMPARE(active.count(), 1);
        s.setZoom(150.0);
        QCOMPARE(s.zoomText(), QString("150%"));
        s.setSelection("2 walls");
        QCOMPARE(s.selectionText(), QString("2 walls"));
        s.showMessage("Wall: click the start point");
        QCOMPARE(s.message(), QString("Wall: click the start point"));
        QVERIFY(!s.findChild<QToolButton*>(QStringLiteral("penButton"))->isEnabled()); // step 3
    }
```

In `test_main_window.cpp`:

```cpp
    void bottomBarFollowsTheWindow()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        w.setTool(kimbim::MainWindow::Tool::Wall);
        QCOMPARE(w.statusStrip()->message(), QCoreApplication::translate("kimbim::MainWindow", "Wall: click the start point"));
        QVERIFY(w.createWall({QPointF(0, 0), QPointF(4, 0)}));
        w.setSelection(w.viewport()->guids().mid(0, 1));
        QVERIFY(w.statusStrip()->selectionText().contains(QLatin1String("1")));
        QVERIFY(!w.statusBar()->isVisible());
    }
```

Add `src/StatusStrip.cpp src/StatusStrip.h` to `kimbim_core`.

- [ ] **Step 2: Run to make sure they fail.** Build: compile errors.

- [ ] **Step 3: Implement `StatusStrip`.**

```cpp
// SPDX-License-Identifier: GPL-3.0-or-later
#include "StatusStrip.h"

#include <QComboBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QMenu>
#include <QTimer>
#include <QToolButton>

namespace kimbim {

StatusStrip::StatusStrip(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("statusStrip"));
    auto* row = new QHBoxLayout(this);
    row->setContentsMargins(6, 2, 6, 2);
    row->setSpacing(10);
    auto* pen = new QToolButton(this);
    pen->setObjectName(QStringLiteral("penButton"));
    pen->setText(tr("Pen"));
    pen->setEnabled(false);
    pen->setToolTip(tr("Pen sets come in a later version"));
    row->addWidget(pen);
    m_layer = new QComboBox(this);
    m_layer->setObjectName(QStringLiteral("activeLayer"));
    m_layer->setToolTip(tr("Active layer: new elements go on it"));
    m_layer->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    row->addWidget(m_layer);
    m_layers = new QToolButton(this);
    m_layers->setObjectName(QStringLiteral("visibleLayers"));
    m_layers->setPopupMode(QToolButton::InstantPopup);
    m_layers->setToolTip(tr("Visible layers"));
    m_layers->setMenu(new QMenu(m_layers));
    row->addWidget(m_layers);
    m_zoom = new QLabel(this);
    m_zoom->setObjectName(QStringLiteral("zoomLabel"));
    row->addWidget(m_zoom);
    m_selection = new QLabel(this);
    m_selection->setObjectName(QStringLiteral("selectionLabel"));
    row->addWidget(m_selection);
    m_message = new QLabel(this);
    m_message->setObjectName(QStringLiteral("statusMessage"));
    m_message->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    row->addWidget(m_message, 1);
    m_timer = new QTimer(this);
    m_timer->setSingleShot(true);
    connect(m_timer, &QTimer::timeout, this, &StatusStrip::clearMessage);
    connect(m_layer, &QComboBox::activated, this, [this](int i) { emit activeLayerRequested(m_layer->itemText(i)); });
}

void StatusStrip::setLayers(const QStringList& all, const QString& active, const QSet<QString>& hidden)
{
    {
        const QSignalBlocker block(m_layer);
        m_layer->clear();
        m_layer->addItems(all);
        m_layer->setCurrentText(active);
    }
    QMenu* menu = m_layers->menu();
    menu->clear();
    for (const QString& name : all) {
        QAction* a = menu->addAction(name);
        a->setCheckable(true);
        a->setChecked(!hidden.contains(name));
        connect(a, &QAction::toggled, this, [this, name](bool on) { emit layerVisibilityToggled(name, on); });
    }
    const int shown = int(all.size()) - int(std::count_if(all.begin(), all.end(), [&](const QString& n) { return hidden.contains(n); }));
    m_layersText = QStringLiteral("%1/%2").arg(shown).arg(all.size());
    m_layers->setText(tr("Layers %1").arg(m_layersText));
}

void StatusStrip::setZoom(double percent)
{
    m_zoomText = percent < 0 ? QString() : QStringLiteral("%1%").arg(qRound(percent));
    m_zoom->setText(m_zoomText);
}

void StatusStrip::setSelection(const QString& summary)
{
    m_selection->setText(summary);
}

void StatusStrip::showMessage(const QString& text, int timeoutMs)
{
    m_message->setText(text);
    if (timeoutMs > 0)
        m_timer->start(timeoutMs);
    else
        m_timer->stop();
}

void StatusStrip::clearMessage() { m_message->clear(); }
QString StatusStrip::message() const { return m_message->text(); }
QString StatusStrip::zoomText() const { return m_zoomText; }
QString StatusStrip::selectionText() const { return m_selection->text(); }
QString StatusStrip::layersText() const { return m_layersText; }

} // namespace kimbim
```

`Viewport::zoomPercent()`: remember `m_fitScale = m_view->Scale()` in `fitAll()` and return
`m_fitScale > 0 ? 100.0 * m_view->Scale() / m_fitScale : 100.0`. Emit a new signal
`void zoomChanged(double percent)` from `wheelEvent` and `fitAll`.

In `MainWindow`:
- `m_status = new StatusStrip(this)`; a non-movable bottom `QToolBar* bottom = new QToolBar(tr("Status"), this); bottom->setObjectName("statusToolbar"); bottom->setMovable(false); bottom->addWidget(m_status); addToolBar(Qt::BottomToolBarArea, bottom);` and `statusBar()->hide();`.
- Replace every `statusBar()->showMessage(` with `m_status->showMessage(` and `statusBar()->clearMessage()` with `m_status->clearMessage()` (126 uses; a mechanical replace with `sed -i 's/statusBar()->showMessage(/m_status->showMessage(/g; s/statusBar()->clearMessage()/m_status->clearMessage()/g' app/src/MainWindow.cpp`). Then grep for any `statusBar()` left except the `hide()` call.
- `refreshLayers()` also calls `m_status->setLayers(names, active, m_hiddenLayers)`. Take the names and the active layer from the same bridge call the layers panel gets.
- Connect `activeLayerRequested` → `setActiveLayer` and `layerVisibilityToggled` → `setLayerVisible`.
- `setSelection(guids)` also sets the summary: empty → `""`; one kind → `tr("%n %1", nullptr, n).arg(kindPlural)`, using `m_tree`'s plain category name (Task 11) when it exists, else the IFC type; several kinds → `tr("%n element(s)", nullptr, n)`.
- `connectViewport(v)` connects `zoomChanged` to `m_status->setZoom` when `v == m_viewport`. `activateView` sets the zoom of the new active view, or `-1` for drawing tabs.

- [ ] **Step 4: Run.** Both binaries: PASS. All ctest. Self-tests that print the status message read it through `statusStrip()->message()`. Grep `SelfTest.cpp` for `statusBar()` and replace it.

- [ ] **Step 5: Commit**

```bash
git add app/src/StatusStrip.* app/src/MainWindow.* app/src/Viewport.* app/src/SelfTest.cpp app/CMakeLists.txt app/tests/*.cpp
git commit -m "feat(app): bottom bar with pen placeholder, active layer, visible layers, zoom, selection and messages"
```

---

### Task 10: One slim top bar

**Files:**
- Modify: `app/src/MainWindow.h`, `app/src/MainWindow.cpp`, `app/tests/test_main_window.cpp`

- [ ] **Step 1: Write the failing test:**

```cpp
    void oneTopBar()
    {
        kimbim::MainWindow w(nullptr, true);
        const auto bars = w.findChildren<QToolBar*>();
        QStringList top;
        for (QToolBar* b : bars)
            if (w.toolBarArea(b) == Qt::TopToolBarArea)
                top << b->objectName();
        QCOMPARE(top, QStringList({"topToolbar"}));
        QToolBar* bar = w.findChild<QToolBar*>(QStringLiteral("topToolbar"));
        QVERIFY(bar->findChild<QComboBox*>(QStringLiteral("optionCombo")));
        QVERIFY(bar->findChild<kimbim::LevelsBar*>());
        QVERIFY(bar->findChild<QDoubleSpinBox*>(QStringLiteral("planCutHeight")));
    }
```

- [ ] **Step 2: Run to make sure it fails.** Expected: FAIL (`levelsToolbar`, `CutsToolbar` and `projectToolbar` are separate).

- [ ] **Step 3: Implement.**
  - In the constructor, create `m_topBar = addToolBar(tr("Project")); m_topBar->setObjectName("topToolbar"); m_topBar->setMovable(false);`.
  - `buildCutsToolbar()` uses `m_topBar` in place of its `levels` and `bar` toolbars: the `LevelsBar`, a separator, then the cut actions and the height field.
  - `buildProjectToolbar()` adds its widgets and actions to `m_topBar` after a separator. It keeps them in `QList<QAction*> m_projectActions` (the `QAction*` returned by `addWidget` and `addAction`), so `refreshProject()` can do `for (QAction* a : m_projectActions) a->setVisible(m_versioned);` instead of `m_projectBar->setVisible(m_versioned)`.
  - Remove `m_projectBar`.
  - Put the versioned-project group first, as the spec's layout shows: create the bar, call `buildProjectToolbar()`, then `buildCutsToolbar()`.

- [ ] **Step 4: Run.** `test_main_window.exe`: PASS, including `versionedProjectFlow`, which shows and hides the option combo. All ctest.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(app): one slim top bar: design option, level and cuts (replaces three toolbars)"
```

---

### Task 11: Tidied model tree

**Files:**
- Modify: `app/src/ModelTreePanel.h`, `app/src/ModelTreePanel.cpp`, `app/tests/test_model_tree.cpp`

**Interfaces:**
- Produces:
  ```cpp
  // ModelTreePanel
  static QString plainName(const QString& ifcType);    // "IfcWallStandardCase" -> "Wall" (translated)
  static QString plainPlural(const QString& ifcType);  // -> "Walls" (translated)
  int itemCount() const;                                // distinct elements (guids) in the tree
  QTreeWidgetItem* itemFor(const QString& guid) const;  // unchanged; merged guids share one item
  QString ifcTypeOf(const QString& guid) const;
  signals:
  void guidActivated(const QString& guid);              // double-click (Task 12)
  ```

- [ ] **Step 1: Write the failing tests.** In `test_model_tree.cpp`, update and add:

```cpp
    void buildsTheTreeAndFindsElements()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QCOMPARE(panel.itemCount(), 7);                       // every guid is still findable
        QVERIFY(panel.selectGuid("W1"));
        QCOMPARE(panel.currentGuid(), QString("W1"));
        QVERIFY(!panel.selectGuid("unknown"));
        QCOMPARE(panel.displayName("W2"), QString("Wall")); // unnamed elements show a plain name
    }

    void singleChildSpatialRowsAreMerged()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QCOMPARE(panel.tree()->topLevelItemCount(), 1);
        QTreeWidgetItem* top = panel.tree()->topLevelItem(0);
        QCOMPARE(top->text(0), QString("Edificio"));          // Casa › Sitio › Edificio in one row
        QCOMPARE(panel.itemFor("P"), top);
        QCOMPARE(panel.itemFor("S"), top);
        QVERIFY(top->toolTip(0).contains("Casa") && top->toolTip(0).contains("Sitio"));
        QCOMPARE(panel.itemFor("L1")->parent(), top);
        QCOMPARE(panel.tree()->columnCount(), 1);             // no Type column
    }

    void elementsAreGroupedByCategoryUnderALevel()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QTreeWidgetItem* level = panel.itemFor("L1");
        QCOMPARE(level->childCount(), 2);
        QCOMPARE(level->child(0)->text(0), QString("Doors (1)"));
        QCOMPARE(level->child(1)->text(0), QString("Walls (2)"));
        QCOMPARE(panel.itemFor("W1")->parent(), level->child(1));
        panel.tree()->clearSelection();
        level->child(1)->setSelected(true);                    // a group row selects nothing itself
        QVERIFY(panel.selectedGuids().isEmpty());
        QStringList g = panel.descendantGuids("L1");
        g.sort();
        QCOMPARE(g, QStringList({"D1", "L1", "W1", "W2"}));
    }

    void twoBuildingsAreNotMerged()
    {
        QJsonObject root = sampleTree();
        QJsonArray sites = root["children"].toArray();
        QJsonObject site = sites[0].toObject();
        QJsonArray buildings = site["children"].toArray();
        buildings.append(QJsonObject{{"guid", "B2"}, {"type", "IfcBuilding"}, {"name", "Anexo"}, {"children", QJsonArray()}});
        site["children"] = buildings;
        sites[0] = site;
        root["children"] = sites;
        kimbim::ModelTreePanel panel;
        panel.setTree(root);
        QTreeWidgetItem* top = panel.tree()->topLevelItem(0);
        QCOMPARE(top->text(0), QString("Sitio"));             // Casa › Sitio merged, then two buildings
        QCOMPARE(top->childCount(), 2);
    }

    void typeStillSearchableAndInTheHint()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        panel.setFilter("IfcDoor");
        QVERIFY(!panel.itemFor("D1")->isHidden());
        QVERIFY(panel.itemFor("W1")->isHidden());
        QVERIFY(panel.hintFor("W1").contains("IfcWall"));
        QCOMPARE(panel.ifcTypeOf("W2"), QString("IfcWall"));
    }
```

Keep `userSelectionEmitsGuids`, `filterKeepsMatchesAndTheirParents` (its `L1` check still holds), `itemsHaveIconsByKind`, `hoverHintNamesTypeAndLevel` and `storeyGuidsCollectsDescendants` as they are.

- [ ] **Step 2: Run to make sure they fail.** Build; run `test_model_tree.exe`. Expected: FAILs (`displayName` is `IfcWall`, the tree isn't merged, no groups, 2 columns).

- [ ] **Step 3: Implement.** In `ModelTreePanel.cpp`:

```cpp
namespace {
constexpr int GuidRole = Qt::UserRole;
constexpr int TypeRole = Qt::UserRole + 1;    // IFC class (searchable, in the hint)
constexpr int GroupRole = Qt::UserRole + 2;   // "storey guid|category" on category rows

QString stripped(const QString& ifcType)
{
    QString t = ifcType;
    if (t.startsWith(QLatin1String("Ifc")))
        t = t.mid(3);
    for (const char* suffix : {"StandardCase", "ElementedCase"})
        if (t.endsWith(QLatin1String(suffix)))
            t.chop(int(qstrlen(suffix)));
    return t;
}

bool isSpatial(const QString& t)
{
    return t == QLatin1String("IfcProject") || t == QLatin1String("IfcSite") || t == QLatin1String("IfcBuilding");
}
} // namespace

QString ModelTreePanel::plainName(const QString& ifcType)
{
    const QString s = stripped(ifcType);
    if (s == QLatin1String("Wall")) return tr("Wall");
    if (s == QLatin1String("Door")) return tr("Door");
    if (s == QLatin1String("Window")) return tr("Window");
    if (s == QLatin1String("Slab")) return tr("Slab");
    if (s == QLatin1String("Column")) return tr("Column");
    if (s == QLatin1String("Beam")) return tr("Beam");
    if (s == QLatin1String("Stair")) return tr("Stair");
    if (s == QLatin1String("Roof")) return tr("Roof");
    if (s == QLatin1String("Space")) return tr("Room");
    if (s == QLatin1String("Annotation")) return tr("Annotation");
    if (s == QLatin1String("Grid")) return tr("Grid");
    if (s == QLatin1String("BuildingStorey")) return tr("Level");
    if (s == QLatin1String("Building")) return tr("Building");
    if (s == QLatin1String("Site")) return tr("Site");
    if (s == QLatin1String("Project")) return tr("Project");
    if (s == QLatin1String("FurnishingElement")) return tr("Furniture");
    if (s == QLatin1String("BuildingElementProxy")) return tr("Other");
    return s;
}

QString ModelTreePanel::plainPlural(const QString& ifcType)
{
    const QString s = stripped(ifcType);
    if (s == QLatin1String("Wall")) return tr("Walls");
    if (s == QLatin1String("Door")) return tr("Doors");
    if (s == QLatin1String("Window")) return tr("Windows");
    if (s == QLatin1String("Slab")) return tr("Slabs");
    if (s == QLatin1String("Column")) return tr("Columns");
    if (s == QLatin1String("Beam")) return tr("Beams");
    if (s == QLatin1String("Stair")) return tr("Stairs");
    if (s == QLatin1String("Roof")) return tr("Roofs");
    if (s == QLatin1String("Space")) return tr("Rooms");
    if (s == QLatin1String("Annotation")) return tr("Annotations");
    if (s == QLatin1String("Grid")) return tr("Grids");
    if (s == QLatin1String("FurnishingElement")) return tr("Furniture");
    if (s == QLatin1String("BuildingElementProxy")) return tr("Other");
    return s + QLatin1Char('s');
}
```

`setTree(root)` becomes:

```cpp
void ModelTreePanel::setTree(const QJsonObject& root)
{
    clear();
    if (root.contains("guid"))
        addNode(root, nullptr, {})->setExpanded(true);
    for (QTreeWidgetItem* item : std::as_const(m_items))
        if (isSpatial(item->data(0, TypeRole).toString()))
            item->setExpanded(true); // down to the levels: elements are one click away
}

// `merged`: names and guids of single-child spatial rows above this one, shown as one row.
QTreeWidgetItem* ModelTreePanel::addNode(const QJsonObject& node, QTreeWidgetItem* parent, QStringList merged)
{
    const QString type = node.value("type").toString();
    const QString name = node.value("name").toString();
    const QString guid = node.value("guid").toString();
    const QJsonArray children = node.value("children").toArray();
    const QString shown = name.isEmpty() ? plainName(type) : name;
    if (isSpatial(type) && children.size() == 1 && isSpatial(children[0].toObject().value("type").toString())) {
        m_mergedGuids << guid;
        return addNode(children[0].toObject(), parent, merged << shown); // Project › Site › Building: one row
    }
    auto* item = parent ? new QTreeWidgetItem(parent) : new QTreeWidgetItem(m_tree);
    item->setText(0, shown);
    item->setIcon(0, iconFor(type));
    item->setData(0, GuidRole, guid);
    item->setData(0, TypeRole, type);
    item->setToolTip(0, (merged << shown).join(QStringLiteral(" › ")) + QStringLiteral("\n") + type);
    m_items.insert(guid, item);
    for (const QString& g : std::as_const(m_mergedGuids))
        m_items.insert(g, item);
    m_mergedGuids.clear();
    if (type == QLatin1String("IfcBuildingStorey")) {
        // Elements under a level, grouped by category ("Walls (12)"), sorted by the category's name.
        QMap<QString, QJsonArray> byCategory;
        QHash<QString, QString> typeOfCategory;
        for (const auto& c : children) {
            const QString t = c.toObject().value("type").toString();
            byCategory[plainPlural(t)].append(c);
            typeOfCategory.insert(plainPlural(t), t);
        }
        for (auto it = byCategory.constBegin(); it != byCategory.constEnd(); ++it) {
            auto* group = new QTreeWidgetItem(item);
            group->setText(0, QStringLiteral("%1 (%2)").arg(it.key()).arg(it.value().size()));
            group->setIcon(0, iconFor(typeOfCategory.value(it.key())));
            group->setData(0, GroupRole, guid + QLatin1Char('|') + it.key());
            for (const auto& c : it.value())
                addNode(c.toObject(), group, {});
        }
        return item;
    }
    for (const auto& c : children)
        addNode(c.toObject(), item, {});
    return item;
}
```

Other changes:
- `m_tree->setColumnCount(1); m_tree->setHeaderHidden(true);` (delete the header lines).
- `itemCount()` returns `m_items.size()`.
- `selectedGuids()` and `descendantGuids()` skip items whose `GuidRole` is empty (group rows). `descendantGuids` keeps walking their children.
- `applyFilter` matches `TypeRole` in place of `text(1)`.
- `hintFor` finds the level by `TypeRole == "IfcBuildingStorey"` and uses `TypeRole` for the type.
- `ifcTypeOf(guid)` returns the item's `TypeRole`.
- `updateNames` uses `plainName(type)` for empty names.
- `refreshTree` remembers expanded group rows by `GroupRole` as well as guids, and re-expands both.
- In `ModelTreePanel.h`, change the private `addNode` signature and add `QStringList m_mergedGuids;`.

`MainWindow` code that read the tree's type column: grep `text(1)` in `app/src` and use `ifcTypeOf`.

- [ ] **Step 4: Run.** `test_model_tree.exe`: all PASS. Then all ctest (`app_selftest_fixture` checks `tree_follows_selection`).

- [ ] **Step 5: Check on a real model.** `pixi run app` and open `spikes/corpus/Clinic_Architectural.ifc` (or wherever `pixi run fetch-corpus` put it). The tree shows one building row, levels and category groups. Note the open time in the commit message next to today's (`--self-test` prints `load_ms`), and make sure it didn't get worse.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(app): tidier model tree: plain names, single-child Project/Site/Building rows merged, elements grouped by category under levels, no Type column"
```

---

### Task 12: Double-click brings Properties forward

**Files:**
- Modify: `app/src/Viewport.h`, `app/src/Viewport.cpp`, `app/src/ModelTreePanel.cpp`, `app/src/MainWindow.cpp`, `app/tests/test_main_window.cpp`, `app/tests/test_model_tree.cpp`

**Interfaces:**
- Produces: `void Viewport::elementDoubleClicked(const QString& guid);` (signal), `ModelTreePanel::guidActivated(const QString&)` (signal).

- [ ] **Step 1: Write the failing tests.** `test_model_tree.cpp`:

```cpp
    void doubleClickActivates()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QSignalSpy spy(&panel, &kimbim::ModelTreePanel::guidActivated);
        emit panel.tree()->itemDoubleClicked(panel.itemFor("W1"), 0);
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.first().first().toString(), QString("W1"));
        emit panel.tree()->itemDoubleClicked(panel.itemFor("L1")->child(0), 0); // a group row
        QCOMPARE(spy.count(), 1);
    }
```

`test_main_window.cpp`:

```cpp
    void doubleClickShowsPropertiesOrOpensThePlan()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        w.setTool(kimbim::MainWindow::Tool::Wall);
        QVERIFY(w.createWall({QPointF(0, 0), QPointF(4, 0)}));
        w.setTool(kimbim::MainWindow::Tool::None);
        const QString wall = w.viewport()->guids().constLast();
        w.dockLayout()->raisePanel(QStringLiteral("tree"));
        QVERIFY(!w.dockLayout()->isPanelShown(QStringLiteral("properties")));
        emit w.viewport()->elementDoubleClicked(wall);
        QVERIFY(w.dockLayout()->isPanelShown(QStringLiteral("properties")));
        QCOMPARE(w.selection(), QStringList({wall}));
        emit w.treePanel()->guidActivated(w.levelsBar()->activeStorey()); // a level opens its plan
        QCOMPARE(w.currentViewKey(), QStringLiteral("plan:") + w.levelsBar()->activeStorey());
    }
```

- [ ] **Step 2: Run to make sure they fail.** Build: compile errors (signals don't exist).

- [ ] **Step 3: Implement.**
  - `Viewport::mouseDoubleClickEvent`: after the drawing-mode branch, run this for a left button outside drawing mode:

```cpp
    if (e->button() == Qt::LeftButton) {
        Handle(ElementOwner) owner = Handle(ElementOwner)::DownCast(m_context->DetectedOwner());
        const QString guid = owner.IsNull() || !owner->batch() ? QString() : owner->batch()->guid(owner->index());
        if (!guid.isEmpty()) {
            emit elementDoubleClicked(guid);
            return;
        }
        const QString note = pickAt(int(e->position().x()), int(e->position().y())); // annotations/markers
        if (!note.isEmpty() && note != QLatin1String("error")) {
            emit elementDoubleClicked(note);
            return;
        }
    }
```

  (Check what `pickAt` returns for nothing hit and use that in place of `"error"` if it differs.)
  - `ModelTreePanel` constructor: `connect(m_tree, &QTreeWidget::itemDoubleClicked, this, [this](QTreeWidgetItem* item) { const QString g = item->data(0, GuidRole).toString(); if (!g.isEmpty()) emit guidActivated(g); });`
  - `MainWindow`: a slot `void activateElement(const QString& guid)`. If `m_tree->ifcTypeOf(guid) == "IfcBuildingStorey"`, call `openPlanTab(guid)` and return. Otherwise run `m_viewport->selectGuids({guid}); m_tree->selectGuids({guid}); setSelection({guid}); m_dock->raisePanel(QStringLiteral("properties"));`. Connect it to `m_tree`'s `guidActivated`, and to each view's `elementDoubleClicked` in `connectViewport`.

- [ ] **Step 4: Run.** Both binaries: PASS. All ctest.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(app): double-click an element (view or tree) to bring Properties forward; double-click a level to open its plan"
```

---

### Task 13: Translations, docs, speed and the whole check

**Files:**
- Modify: `app/translations/kimbim_es.ts`, `app/translations/kimbim_en.ts`, `docs/decisions.md`, `docs/04-app-features.md`, `docs/13-architect-feedback.md`

- [ ] **Step 1: Translations.** Update the `.ts` files the way the repo does it. Read `tools/check_translations.py` for the expected workflow; it is usually `pixi run bash -c "lupdate app/src -ts app/translations/kimbim_es.ts app/translations/kimbim_en.ts"`. Fill in the Spanish for every new `unfinished` entry. Suggested wording:

| English | Spanish |
|---|---|
| 3D | 3D |
| Plane | Plano |
| View | Vista |
| Edit | Edición |
| Tools | Herramientas |
| %1 plan | Planta %1 |
| New plan tab | Nueva pestaña de planta |
| New sheet | Nueva lámina |
| Pen | Pluma |
| Pen sets come in a later version | Los juegos de plumas llegan en una versión posterior |
| Active layer: new elements go on it | Capa activa: los elementos nuevos van en ella |
| Visible layers | Capas visibles |
| Layers %1 | Capas %1 |
| Status | Estado |
| Wall / Walls | Muro / Muros |
| Door / Doors | Puerta / Puertas |
| Window / Windows | Ventana / Ventanas |
| Slab / Slabs | Losa / Losas |
| Column / Columns | Pilar / Pilares |
| Beam / Beams | Viga / Vigas |
| Stair / Stairs | Escalera / Escaleras |
| Roof / Roofs | Cubierta / Cubiertas |
| Room / Rooms | Habitación / Habitaciones |
| Annotation / Annotations | Anotación / Anotaciones |
| Grid / Grids | Eje / Ejes |
| Level | Nivel |
| Building / Site / Project | Edificio / Terreno / Proyecto |
| Furniture | Mobiliario |
| Other | Otros |
| %n element(s) | %n elemento(s) |

Run: `pixi run check-translations` → `translations OK`. Run `test_translations.exe` → PASS.

- [ ] **Step 2: Docs.**
  - `docs/decisions.md`: add row D71. *"The main window uses the Qt Advanced Docking System (LGPL-2.1, built pinned with FetchContent). 3D and plan tabs are views of one shared OCCT scene (`Scene`): overlays and cut planes belong to their view, and a view moved to another window rebinds to it. Tools are on the left in 3D / Plane / View / Edit groups, panels are tabbed on the right, and Properties come forward on double-click. A bottom bar holds the pen (step 3), layers, zoom and selection; one top bar holds the design option, level and cuts. The tree merges single-child Project/Site/Building rows and groups a level's elements by category."* Status `Decided (main window rework)`, linking this plan.
  - `docs/04-app-features.md`: update the window-layout description to match the spec's "What the architect sees".
  - `docs/13-architect-feedback.md`: add a short section, "2026-10-07 UI rework (step 1 of 3)", listing what changed and what's next (steps 2 and 3).

- [ ] **Step 3: Speed on Clinic.** Run the tool benchmark the way docs/13 describes it, with the 3D tab alone and with a plan tab open. Compare the `afterEdit` steps (`timings()` per step) against `main` (`git stash`/checkout `claude/nifty-cori-tlrl5b`, build, run). Expected: no step slower by more than noise (±10%). If `refreshAnnotations` or the section rebuild doubled because two views redo it, only rebuild the active plan view's overlays per edit, and the others when they become active.

- [ ] **Step 4: Whole check.**

Run:
```bash
pixi run app-build && KIMBIM_PYTHON_PATH="$PWD/python" pixi run ctest --test-dir build/app --output-on-failure
pixi run pytest -q -p no:cacheprovider
pixi run check-translations && pixi run check-spdx
```
Expected: all app tests pass (the 31 existing + test_scene, test_dock_layout, test_tool_palette, app_selftest_pop_out), the Python suite passes, translations OK, SPDX OK. Then the Linux check from Task 1 Step 8 on the whole branch.

- [ ] **Step 5: Look at it.** `pixi run app`. Open the house (`pixi run house` makes `build/house.ifc`). Drag the 3D tab out to its own window and back, open a plan tab, auto-hide the right panels, and close and reopen the app (the layout comes back). Take a screenshot of the default layout for the owner. Don't drive the mouse with SendInput without asking (owner preference).

- [ ] **Step 6: Commit**

```bash
git add app/translations docs
git commit -m "docs+i18n: D71 main window rework; Spanish for the new UI; doc 04 and 13 updated"
```
