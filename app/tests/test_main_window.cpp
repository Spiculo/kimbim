// SPDX-License-Identifier: GPL-3.0-or-later
// MainWindow wiring: visibility actions act on the viewport selection (no window shown).
#include <QAction>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QSlider>
#include <QTemporaryDir>
#include <QStandardPaths>
#include <QtTest>

#include <cmath>

#include "CombineDialog.h"
#include "DockLayout.h"
#include "ModelTreePanel.h"
#include "StatusStrip.h"
#include "ToolOptionsBar.h"
#include "ToolPalette.h"
#include <QComboBox>
#include <QLocale>
#include <QSpinBox>
#include <QLabel>
#include <QDoubleSpinBox>
#include <QMenu>
#include <QStatusBar>
#include <QToolBar>
#include <DockManager.h>
#include <DockWidget.h>
#include "DrawingView.h"
#include "PythonEngine.h"
#include <QPushButton>
#include <QTableWidget>
#include "DrawingsPanel.h"
#include "SheetsPanel.h"
#include "ElementBatch.h"
#include "LevelsBar.h"
#include "HostTool.h"
#include "Graphics.h"
#include "MainWindow.h"
#include "PolygonTool.h"
#include "ProjectSettingsDialog.h"
#include "GripTool.h"
#include "RotateTool.h"
#include "TwoPointTool.h"
#include "WallTool.h"
#include "PythonEngine.h"
#include "Viewport.h"

namespace {

Handle(kimcad::ElementBatch) batch(int n)
{
    kimcad::MeshChunk c;
    c.voff.push_back(0);
    c.toff.push_back(0);
    for (int e = 0; e < n; ++e) {
        c.guids << QStringLiteral("g%1").arg(e);
        c.types << QStringLiteral("IfcWall");
        const float x = float(e);
        const float v[] = {x, 0, 0, x + 0.5f, 0, 0, x, 0.5f, 1};
        c.verts.insert(c.verts.end(), std::begin(v), std::end(v));
        const uint32_t base = uint32_t(e * 3);
        c.tris.insert(c.tris.end(), {base, base + 1, base + 2});
        c.voff.push_back(uint32_t(c.verts.size() / 3));
        c.toff.push_back(uint32_t(c.tris.size() / 3));
    }
    return new kimcad::ElementBatch(std::move(c));
}

QAction* action(kimcad::MainWindow& w, const char* name)
{
    QAction* a = w.findChild<QAction*>(QString::fromLatin1(name));
    if (!a)
        qFatal("missing action %s", name);
    return a;
}

} // namespace

class TestMainWindow : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { QStandardPaths::setTestModeEnabled(true); }

    // D71: the 3D view, drawings and sheets are center tabs; the panels are tabbed on the right.
    void viewsAndPanelsLiveInTheDockLayout()
    {
        kimcad::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimcad::DockLayout* dock = w.dockLayout();
        QVERIFY(dock->view("3d"));
        QVERIFY(!dock->manager()->findDockWidget("3d")->features().testFlag(ads::CDockWidget::DockWidgetClosable));
        for (const char* panel : {"tree", "properties", "layers", "history", "drawings", "sheets"})
            QVERIFY2(dock->manager()->findDockWidget(QLatin1String(panel)), panel);
        QCOMPARE(w.currentViewKey(), QString("3d"));
        const QString south = w.drawingGuid(QStringLiteral("South Elevation"));
        QVERIFY(w.openDrawing(south));
        QCOMPARE(w.currentViewKey(), south);
        emit dock->closeRequested(south); // the tab's x
        QVERIFY(!w.drawingView(south));
        QVERIFY(!dock->view(south));
        QCOMPARE(w.currentViewKey(), QString("3d"));
        emit dock->closeRequested("3d"); // never closes
        QVERIFY(dock->view("3d"));
    }

    // The rework is for room: the model view gets most of the width; the side columns stay narrow.
    void theModelViewGetsMostOfTheWidth()
    {
        kimcad::MainWindow w(nullptr, true);
        w.resize(1600, 1000);
        w.show();
        QCoreApplication::processEvents();
        const int center = w.dockLayout()->view("3d")->width();
        QVERIFY2(center >= int(0.6 * w.width()), qPrintable(QStringLiteral("%1 of %2").arg(center).arg(w.width())));
    }

    // A panel closed with its x comes back from View > Panels.
    void closedPanelsComeBackFromTheViewMenu()
    {
        kimcad::MainWindow w(nullptr, true);
        w.show();
        ads::CDockWidget* tree = w.dockLayout()->manager()->findDockWidget("tree");
        tree->closeDockWidget();
        QVERIFY(tree->isClosed());
        QMenu* panels = w.findChild<QMenu*>(QStringLiteral("panelsMenu"));
        QVERIFY(panels && panels->actions().contains(tree->toggleViewAction()));
        tree->toggleViewAction()->trigger();
        QVERIFY(!tree->isClosed());
    }

    void layoutRestoreSkipsUnknownAndOffscreen()
    {
        QByteArray saved;
        {
            kimcad::MainWindow w(nullptr, true);
            QVERIFY(w.newProject());
            QVERIFY(w.openDrawing(w.drawingGuid(QStringLiteral("North Elevation"))));
            saved = w.dockLayout()->saveLayout();
        }
        kimcad::MainWindow w(nullptr, true); // a new session: that drawing tab doesn't exist here
        QVERIFY(w.newProject());
        w.dockLayout()->restoreLayout(saved); // never throws, never loses the 3D tab
        QVERIFY(w.dockLayout()->view("3d"));
        QVERIFY(!w.dockLayout()->restoreLayout(QByteArray("garbage")));
        QVERIFY(w.dockLayout()->view("3d"));
        QVERIFY(w.dockLayout()->manager()->findDockWidget("tree"));
    }

    // D71: plan tabs per level, views of the one loaded model.
    void planTabsShareTheModel()
    {
        kimcad::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QString l1 = w.levelsBar()->activeStorey();
        kimcad::Viewport* plan = w.openPlanTab(l1);
        QVERIFY(plan && plan != w.modelView());
        QCOMPARE(w.viewport(), plan);
        QVERIFY(plan->isPlanView());
        QCOMPARE(w.currentViewKey(), QStringLiteral("plan:") + l1);
        QCOMPARE(w.openPlanTab(l1), plan); // opened once, raised again
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        for (const QPointF& p : {QPointF(0, 0), QPointF(4, 0)})
            w.wallTool()->click(p);
        w.setTool(kimcad::MainWindow::Tool::None);
        QCOMPARE(w.modelView()->elementCount(), plan->elementCount()); // one model
        QVERIFY(plan->elementCount() > 0);
        w.modelView()->selectGuids(plan->guids().mid(0, 1));
        QCOMPARE(plan->selectedGuids().size(), 1);
        QVERIFY(!w.modelView()->isPlanView());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        action(w, "action3DView")->trigger();
        QCOMPARE(w.viewport(), w.modelView());
        QCOMPARE(w.tool(), kimcad::MainWindow::Tool::None); // switching views cancels the tool
        action(w, "actionPlanView")->trigger(); // P: the active level's plan tab
        QCOMPARE(w.viewport(), plan);
    }

    void deletingTheActivePlanLevel()
    {
        kimcad::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.addLevel(QStringLiteral("Level 2"), 3.0));
        const QString l2 = w.levelsBar()->activeStorey();
        QVERIFY(w.openPlanTab(l2));
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        w.wallTool()->click(QPointF(0, 0)); // a wall half-drawn
        action(w, "actionUndo")->trigger(); // the level goes (undoing Add level)
        QVERIFY(!w.dockLayout()->view(QStringLiteral("plan:") + l2));
        QCOMPARE(w.currentViewKey(), QString("3d"));
        QCOMPARE(w.tool(), kimcad::MainWindow::Tool::None);
        QCOMPARE(w.viewport(), w.modelView());
    }

    void openingAFileClosesPlanTabs()
    {
        kimcad::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.openPlanTab(w.levelsBar()->activeStorey()));
        QVERIFY(w.newProject());
        for (const QString& key : w.dockLayout()->viewKeys())
            QVERIFY2(!key.startsWith(QLatin1String("plan:")), qPrintable(key));
        QCOMPARE(w.viewport(), w.modelView());
    }

    void eachViewKeepsItsOwnCut()
    {
        kimcad::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimcad::Viewport* plan = w.openPlanTab(w.levelsBar()->activeStorey());
        QVERIFY(plan->clipPlaneCount() >= 1); // a plan is cut
        QVERIFY(action(w, "actionPlanCut")->isChecked());
        w.dockLayout()->raise(QStringLiteral("3d"));
        QCOMPARE(w.modelView()->clipPlaneCount(), 0); // the 3D tab is not
        QVERIFY(!action(w, "actionPlanCut")->isChecked());
        w.dockLayout()->raise(QStringLiteral("plan:") + w.levelsBar()->activeStorey());
        QVERIFY(action(w, "actionPlanCut")->isChecked());
    }

    // D71: tools on the left in four groups; each tool in exactly one.
    void everyToolIsInOnePaletteGroup()
    {
        kimcad::MainWindow w(nullptr, true);
        kimcad::ToolPalette* p = w.toolPalette();
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
                names << (a ? a->objectName() : QStringLiteral("(missing)"));
            QCOMPARE(names, expected.value(g));
            seen << names;
        }
        QCOMPARE(QSet<QString>(seen.begin(), seen.end()).size(), seen.size()); // each in one group only
        QVERIFY(!w.findChild<QToolBar*>(QStringLiteral("modelingToolbar"))); // the old toolbar is gone
        QVERIFY(w.dockLayout()->manager()->findDockWidget("tools"));
        action(w, "actionMirror")->trigger();
        QCOMPARE(w.tool(), kimcad::MainWindow::Tool::None); // nothing selected: refused, as before
    }

    void newPlanTabAndNewSheetFromThePalette()
    {
        kimcad::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        action(w, "actionNewPlanTab")->trigger();
        QCOMPARE(w.currentViewKey(), QStringLiteral("plan:") + w.levelsBar()->activeStorey());
        const int sheets = w.sheetsPanel()->count();
        action(w, "actionNewSheet")->trigger();
        QCOMPARE(w.sheetsPanel()->count(), sheets + 1);
    }

    // D71: the active tool's fields in a strip above the active view, only while a tool is active.
    void toolOptionsFollowTheTool()
    {
        kimcad::MainWindow w(nullptr, true);
        w.show();
        QVERIFY(w.newProject());
        kimcad::ToolOptionsBar* bar = w.toolOptions();
        QVERIFY(bar->isHidden());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        QVERIFY(!bar->isHidden());
        QVERIFY(w.findChild<QDoubleSpinBox*>(QStringLiteral("wallHeight"))->isVisibleTo(bar));
        QVERIFY(!w.findChild<QComboBox*>(QStringLiteral("roofKind"))->isVisibleTo(bar));
        w.setTool(kimcad::MainWindow::Tool::Roof);
        QVERIFY(w.findChild<QComboBox*>(QStringLiteral("roofKind"))->isVisibleTo(bar));
        w.setTool(kimcad::MainWindow::Tool::None);
        QVERIFY(bar->isHidden());
        QVERIFY(w.dockLayout()->view(w.currentViewKey())->isAncestorOf(bar)); // in the active tab
        QVERIFY(w.openPlanTab(w.levelsBar()->activeStorey()));
        QVERIFY(w.dockLayout()->view(w.currentViewKey())->isAncestorOf(bar)); // it moves with the active view
        QVERIFY(!w.findChild<QToolBar*>(QStringLiteral("toolFieldsToolbar")));
    }

    // D71: the bottom bar: pen, layers, zoom, selection, messages.
    void bottomBarFollowsTheWindow()
    {
        kimcad::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        QCOMPARE(w.statusStrip()->message(), QCoreApplication::translate("kimcad::MainWindow", "Wall: click the start point"));
        w.wallTool()->setTolerance(0.05);
        for (const QPointF& p : {QPointF(0, 0), QPointF(4, 0)})
            w.wallTool()->click(p);
        w.setTool(kimcad::MainWindow::Tool::None);
        QVERIFY(w.statusStrip()->selectionText().isEmpty());
        w.setSelection(w.viewport()->guids().mid(0, 1));
        QCOMPARE(w.statusStrip()->selectionText(), QStringLiteral("1 ") + kimcad::ModelTreePanel::plainName(QStringLiteral("IfcWall")));
        QVERIFY(!w.statusStrip()->layersText().isEmpty());
        QVERIFY(w.statusBar()->isHidden());
    }

    // D71: one slim top bar: design option, level and cuts.
    void oneTopBar()
    {
        kimcad::MainWindow w(nullptr, true);
        QStringList top;
        for (QToolBar* b : w.findChildren<QToolBar*>())
            if (w.toolBarArea(b) == Qt::TopToolBarArea)
                top << b->objectName();
        QCOMPARE(top, QStringList({"topToolbar"}));
        QToolBar* bar = w.findChild<QToolBar*>(QStringLiteral("topToolbar"));
        QVERIFY(bar->findChild<QComboBox*>(QStringLiteral("optionCombo")));
        QVERIFY(bar->findChild<kimcad::LevelsBar*>());
        QVERIFY(bar->findChild<QDoubleSpinBox*>(QStringLiteral("planCutHeight")));
    }

    // D71: double-click an element for its properties; a level for its plan.
    void doubleClickShowsPropertiesOrOpensThePlan()
    {
        kimcad::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        for (const QPointF& p : {QPointF(0, 0), QPointF(4, 0)})
            w.wallTool()->click(p);
        w.setTool(kimcad::MainWindow::Tool::None);
        const QString wall = w.viewport()->guids().constLast();
        w.dockLayout()->raisePanel(QStringLiteral("tree"));
        QVERIFY(!w.dockLayout()->isPanelShown(QStringLiteral("properties")));
        emit w.viewport()->elementDoubleClicked(wall);
        QVERIFY(w.dockLayout()->isPanelShown(QStringLiteral("properties")));
        QCOMPARE(w.selection(), QStringList({wall}));
        emit w.treePanel()->guidActivated(w.levelsBar()->activeStorey()); // a level opens its plan
        QCOMPARE(w.currentViewKey(), QStringLiteral("plan:") + w.levelsBar()->activeStorey());
    }

    void visibilityActionsUseTheSelection()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        kimcad::Viewport* v = w.viewport();
        v->addBatch(batch(4));

        v->selectGuids({"g1"});
        action(w, "actionHideSelected")->trigger();
        QCOMPARE(v->visibleElementCount(), 3);

        v->selectGuids({"g0", "g2"});
        action(w, "actionIsolateSelected")->trigger();
        QCOMPARE(v->visibleElementCount(), 2);

        action(w, "actionShowAll")->trigger();
        QCOMPARE(v->visibleElementCount(), 4);
    }

    void cutActionsAddAndRemoveClipPlanes()
    {
        kimcad::MainWindow w(nullptr, true);
        kimcad::Viewport* v = w.viewport();
        v->addBatch(batch(4));
        QCOMPARE(v->clipPlaneCount(), 0);
        w.setPlanCutHeight(0.5);
        action(w, "actionPlanCut")->setChecked(true);
        QCOMPARE(v->clipPlaneCount(), 1);
        action(w, "actionSectionBox")->setChecked(true); // nothing selected: box around the visible model
        QCOMPARE(v->clipPlaneCount(), 7);
        action(w, "actionPlanCut")->setChecked(false);
        QCOMPARE(v->clipPlaneCount(), 6);
        action(w, "actionSectionBox")->setChecked(false);
        QCOMPARE(v->clipPlaneCount(), 0);
    }

    // M2: bulk edit, undo/redo, save, unsaved-changes state (real engine, fixture model).
    void editUndoRedoSave()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath(QStringLiteral("modelo ñ.ifc"));
        auto& py = kimcad::PythonEngine::instance();
        QString error;
        QVERIFY(py.start(&error));
        py.callJson("_write_test_model", {path});

        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy done(&w, &kimcad::MainWindow::loadFinished);
        w.openFile(path);
        QVERIFY(done.wait(60000));
        const QStringList walls = w.viewport()->guids();
        QCOMPARE(walls.size(), 2);
        w.setSelection(walls);
        QVERIFY(!w.isDirty());

        auto fire = [&] {
            const QJsonObject m = py.callJson("properties_multi",
                {QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(walls)).toJson(QJsonDocument::Compact))}).object();
            return m["psets"].toObject()["Pset_WallCommon"].toObject()["FireRating"].toObject()["value"].toString();
        };
        QVERIFY(w.applyPropertyEdit("Pset_WallCommon", "FireRating", QJsonValue("EI90")));
        QCOMPARE(fire(), QString("EI90"));
        QVERIFY(w.isDirty());
        QVERIFY(w.windowTitle().contains("[*]") && w.isWindowModified());

        action(w, "actionUndo")->trigger();
        QCOMPARE(fire(), QString("EI30"));
        QVERIFY(!w.isDirty());
        action(w, "actionRedo")->trigger();
        QCOMPARE(fire(), QString("EI90"));

        const QString out = tmp.filePath(QStringLiteral("salida.ifc"));
        QVERIFY(w.saveAs(out));
        QVERIFY(!w.isDirty());
        QFile f(out);
        QVERIFY(f.open(QIODevice::ReadOnly));
        QVERIFY(f.readAll().contains("EI90"));

        QVERIFY(!w.applyPropertyEdit("Pset_WallCommon", "IsExternal", QJsonValue("maybe"))); // invalid boolean
        QVERIFY(!w.isDirty());

        QVERIFY(w.applyPropertyEdit("Pset_WallCommon", "FireRating", QJsonValue("EI120")));
        QVERIFY(w.isDirty());
        QVERIFY(w.close()); // quiet mode: never a modal dialog
    }

    // D50: a type edit reaches every element of the type (one undo step); reset brings the type value back.
    void typeEditAndResetToType()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath(QStringLiteral("tipos.ifc"));
        auto& py = kimcad::PythonEngine::instance();
        QString error;
        QVERIFY(py.start(&error));
        py.callJson("_write_test_model", {path});

        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy done(&w, &kimcad::MainWindow::loadFinished);
        w.openFile(path);
        QVERIFY(done.wait(60000));
        const QStringList walls = w.viewport()->guids();
        QCOMPARE(walls.size(), 2);

        auto u = [&](const QString& guid) {
            const QJsonObject m = py.callJson("properties_multi",
                {QString::fromUtf8(QJsonDocument(QJsonArray{guid}).toJson(QJsonDocument::Compact))}).object();
            return m["psets"].toObject()["Pset_WallCommon"].toObject()["ThermalTransmittance"].toObject();
        };
        w.setSelection({walls[0]});
        QVERIFY(w.applyTypeEdit("Pset_WallCommon", "ThermalTransmittance", QJsonValue(0.5)));
        QCOMPARE(u(walls[1])["value"].toDouble(), 0.5); // not selected, same type
        QVERIFY(w.isDirty());
        action(w, "actionUndo")->trigger();
        QCOMPARE(u(walls[1])["value"].toDouble(), 0.35);
        QVERIFY(!w.isDirty());

        QVERIFY(w.applyPropertyEdit("Pset_WallCommon", "ThermalTransmittance", QJsonValue(0.9)));
        QCOMPARE(u(walls[0])["source"].toString(), QString("override"));
        QVERIFY(w.resetToType("Pset_WallCommon", "ThermalTransmittance"));
        QCOMPARE(u(walls[0])["source"].toString(), QString("type"));
        QCOMPARE(u(walls[0])["value"].toDouble(), 0.35);
        QVERIFY(w.close());
    }

    // Slice 4: Delete removes the selection from the model, the view and the tree; undo brings it back.
    void deleteAndUndoUpdateViewAndTree()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath(QStringLiteral("borrar.ifc"));
        auto& py = kimcad::PythonEngine::instance();
        QString error;
        QVERIFY(py.start(&error));
        py.callJson("_write_test_model", {path});

        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy done(&w, &kimcad::MainWindow::loadFinished);
        w.openFile(path);
        QVERIFY(done.wait(60000));
        const QStringList walls = w.viewport()->guids();
        QCOMPARE(walls.size(), 2);
        w.viewport()->selectGuids({walls[0]});
        w.setSelection({walls[0]});
        action(w, "actionDelete")->trigger();
        QCOMPARE(w.viewport()->elementCount(), 1);
        QVERIFY(!w.viewport()->guids().contains(walls[0]));
        QVERIFY(!w.treeHasGuid(walls[0]));
        QVERIFY(w.selection().isEmpty());
        QVERIFY(w.isDirty());
        action(w, "actionUndo")->trigger();
        QCOMPARE(w.viewport()->elementCount(), 2);
        QVERIFY(w.viewport()->guids().contains(walls[0]));
        QVERIFY(w.treeHasGuid(walls[0]));
        QVERIFY(w.close());
    }

    // Slice 4: new project with one level; levels can be added and undone.
    void newProjectAndLevels()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        QCOMPARE(w.viewport()->elementCount(), 0);
        QCOMPARE(w.levelsBar()->count(), 1);
        QVERIFY(!w.isDirty());
        QVERIFY(w.windowTitle().contains(QObject::tr("Untitled")));
        QVERIFY(w.addLevel(QStringLiteral("Level 2"), 3.0));
        QCOMPARE(w.levelsBar()->count(), 2);
        QCOMPARE(w.levelsBar()->activeElevation(), 3.0);
        QVERIFY(w.isDirty());
        action(w, "actionUndo")->trigger();
        QCOMPARE(w.levelsBar()->count(), 1);
        QCOMPARE(w.levelsBar()->activeElevation(), 0.0);
        action(w, "actionPlanView")->trigger();
        QVERIFY(w.viewport()->isPlanView());
        action(w, "action3DView")->trigger();
        QVERIFY(!w.viewport()->isPlanView());
        QVERIFY(w.close());
    }

    // Slice 5: the real tools end to end: walls, a door (undo removes it and closes the hole),
    // a slab from the wall loop, and Esc leaving the tool.
    void wallsDoorSlabWithTheTools()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        for (const QPointF& p : {QPointF(0, 0), QPointF(8, 0), QPointF(8, 6), QPointF(0, 6), QPointF(0, 0)})
            w.wallTool()->click(p);
        QCOMPARE(w.viewport()->elementCount(), 4);
        const QStringList walls = w.viewport()->guids();

        w.setTool(kimcad::MainWindow::Tool::Door);
        QVERIFY(action(w, "actionDoorTool")->isChecked());
        QVERIFY(!action(w, "actionWallTool")->isChecked());
        w.hostTool()->setTolerance(0.05);
        w.hostTool()->click(QPointF(4.0, 0.02));
        QCOMPARE(w.viewport()->elementCount(), 5);
        action(w, "actionUndo")->trigger();
        QCOMPARE(w.viewport()->elementCount(), 4);
        action(w, "actionRedo")->trigger();
        QCOMPARE(w.viewport()->elementCount(), 5);

        w.setTool(kimcad::MainWindow::Tool::None);
        QVERIFY(w.slabFromWalls(walls));
        QCOMPARE(w.viewport()->elementCount(), 6);
        QVERIFY(!w.slabFromWalls(walls.mid(0, 2))); // not a closed loop: refused, nothing added
        QCOMPARE(w.viewport()->elementCount(), 6);

        w.setTool(kimcad::MainWindow::Tool::Slab);
        w.polygonTool()->click({10, 0});
        w.polygonTool()->click({12, 0});
        w.polygonTool()->click({12, 2});
        w.polygonTool()->finish(); // Enter
        QCOMPARE(w.viewport()->elementCount(), 7);
        w.setTool(kimcad::MainWindow::Tool::None);
        QVERIFY(!w.viewport()->isDrawingMode());
        QVERIFY(w.close());
    }

    // Slice 6: columns, beams and grid lines through the tools; undo removes them.
    void columnBeamGridWithTheTools()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Grid);
        w.twoPointTool()->click({0, -1});
        w.twoPointTool()->click({0, 7});
        QCOMPARE(w.gridLineCount(), 1);
        w.setTool(kimcad::MainWindow::Tool::Column);
        w.columnAt(QPointF(0.03, 0.02)); // snaps onto the grid line
        QCOMPARE(w.viewport()->elementCount(), 1);
        w.setTool(kimcad::MainWindow::Tool::Beam);
        w.twoPointTool()->click({0, 0});
        w.twoPointTool()->click({0, 5});
        QCOMPARE(w.viewport()->elementCount(), 2);
        action(w, "actionUndo")->trigger();
        QCOMPARE(w.viewport()->elementCount(), 1);
        action(w, "actionUndo")->trigger();
        action(w, "actionUndo")->trigger();
        QCOMPARE(w.viewport()->elementCount(), 0);
        QCOMPARE(w.gridLineCount(), 0);
        QVERIFY(w.close());
    }

    // Slice 6: editing through the tools: move a wall (its door follows), slide a door, rotate a
    // beam, stretch a wall, change a wall's height, resize a door; undo restores.
    void moveRotateStretchWithTheTools()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        for (const QPointF& p : {QPointF(0, 0), QPointF(8, 0), QPointF(8, 6), QPointF(0, 6), QPointF(0, 0)})
            w.wallTool()->click(p);
        const QStringList walls = w.viewport()->guids();
        w.setTool(kimcad::MainWindow::Tool::Door);
        w.hostTool()->setTolerance(0.05);
        w.hostTool()->click({4.0, 0.0});
        QString door;
        for (const QString& g : w.viewport()->guids())
            if (w.viewport()->typeOf(g) == QLatin1String("IfcDoor"))
                door = g;
        QVERIFY(!door.isEmpty());
        auto centre = [&](const QString& g) {
            double x0, y0, z0, x1, y1, z1;
            w.viewport()->boundsOf({g}).Get(x0, y0, z0, x1, y1, z1);
            return QVector<double>{(x0 + x1) / 2, (y0 + y1) / 2, z1, x1 - x0, y1 - y0};
        };
        const double doorY = centre(door)[1];
        // Batches are re-made as walls get joined, so find the south wall by where it is.
        QString south;
        for (const QString& g : walls)
            if (std::abs(centre(g)[1]) < 0.2 && centre(g)[3] > 7.0)
                south = g;
        QVERIFY(!south.isEmpty());

        // Move the south wall 1 m south: the door goes with it, the side walls follow.
        w.setSelection({south});
        w.setTool(kimcad::MainWindow::Tool::Move);
        w.twoPointTool()->click({4, 0});
        w.twoPointTool()->click({4, -1});
        QVERIFY(std::abs(centre(door)[1] - (doorY - 1.0)) < 0.01);
        action(w, "actionUndo")->trigger();
        QVERIFY(std::abs(centre(door)[1] - doorY) < 0.01);

        // Moving only the door slides it along its wall.
        w.setSelection({door});
        w.setTool(kimcad::MainWindow::Tool::Move);
        w.twoPointTool()->setOrtho(true); // Shift: straight along X
        w.twoPointTool()->click({4, 0});
        w.twoPointTool()->click({6, 0.5});
        w.twoPointTool()->setOrtho(false);
        QVERIFY(std::abs(centre(door)[0] - 6.0) < 0.01);
        QVERIFY(std::abs(centre(door)[1] - doorY) < 0.01);

        // Rotate a beam 90 degrees around its start.
        w.setTool(kimcad::MainWindow::Tool::Beam);
        w.twoPointTool()->click({10, 0});
        w.twoPointTool()->click({14, 0});
        const QString beam = w.viewport()->guids().last();
        w.setSelection({beam});
        w.setTool(kimcad::MainWindow::Tool::Rotate);
        w.rotateTool()->click({10, 0});
        w.rotateTool()->click({14, 0});
        w.rotateTool()->click({10, 4});
        QVERIFY(std::abs(centre(beam)[4] - 4.0) < 0.01); // now 4 m along Y
        QVERIFY(w.viewport()->guids().contains(beam));   // same element

        // Stretch a free wall's end from x = 24 to x = 26.
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->click({20, 0});
        w.wallTool()->click({24, 0});
        w.wallTool()->finish();
        const QString free = w.viewport()->guids().last();
        w.setTool(kimcad::MainWindow::Tool::Stretch);
        w.gripTool()->setTolerance(0.1);
        w.gripTool()->click({24, 0});
        w.gripTool()->click({26, 0});
        QVERIFY(std::abs(centre(free)[3] - 6.0) < 0.05);

        w.setTool(kimcad::MainWindow::Tool::None);
        QVERIFY(w.setWallHeight({free}, 4.5));
        QVERIFY(std::abs(centre(free)[2] - 4.5) < 0.01);
        QVERIFY(w.resizeOpening(door, 1.2, 2.2, 0.0));
        QVERIFY(std::abs(centre(door)[3] - 1.25) < 0.01);
        QVERIFY(!w.resizeOpening(door, 9.0, 2.2, 0.0)); // too wide: refused
        QVERIFY(w.close());
    }

    // Slice 7: a second floor: copy the walls (with their door) up, a stair to the next level, and a
    // stair hole in the upper floor slab.
    void secondFloorWithTheTools()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        const QString l1 = w.levelsBar()->activeStorey();
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        for (const QPointF& p : {QPointF(0, 0), QPointF(8, 0), QPointF(8, 6), QPointF(0, 6), QPointF(0, 0)})
            w.wallTool()->click(p);
        w.setTool(kimcad::MainWindow::Tool::Door);
        w.hostTool()->setTolerance(0.05);
        w.hostTool()->click({4.0, 0.0});
        w.setTool(kimcad::MainWindow::Tool::None);
        QStringList walls;
        for (const QString& g : w.viewport()->guids())
            if (w.viewport()->typeOf(g) == QLatin1String("IfcWall"))
                walls << g;
        QCOMPARE(walls.size(), 4);
        QVERIFY(w.addLevel(QStringLiteral("Level 2"), 3.0));
        const QString l2 = w.levelsBar()->activeStorey();
        QVERIFY(l2 != l1);
        QVERIFY(w.copyToLevel(walls, l2));
        QCOMPARE(w.viewport()->elementCount(), 10); // 4 walls + door, twice

        w.levelsBar()->setActive(l1);
        w.setTool(kimcad::MainWindow::Tool::Stair);
        w.twoPointTool()->click({1, 1});
        w.twoPointTool()->click({5, 1});
        QCOMPARE(w.viewport()->elementCount(), 11);
        double x0, y0, z0, x1, y1, z1;
        w.viewport()->boundsOf({w.viewport()->guids().last()}).Get(x0, y0, z0, x1, y1, z1);
        QVERIFY(std::abs(z1 - 3.0) < 0.01); // up to Level 2

        w.levelsBar()->setActive(l2);
        w.setTool(kimcad::MainWindow::Tool::Slab);
        for (const QPointF& p : {QPointF(0, 0), QPointF(8, 0), QPointF(8, 6), QPointF(0, 6)})
            w.polygonTool()->click(p);
        w.polygonTool()->finish();
        const QString slab = w.viewport()->guids().last();
        QCOMPARE(w.viewport()->typeOf(slab), QString("IfcSlab"));
        w.setSelection({slab});
        w.setTool(kimcad::MainWindow::Tool::SlabOpening);
        QVERIFY(action(w, "actionSlabOpeningTool")->isChecked());
        for (const QPointF& p : {QPointF(1, 0.5), QPointF(5.8, 0.5), QPointF(5.8, 1.6), QPointF(1, 1.6)})
            w.polygonTool()->click(p);
        w.polygonTool()->finish();
        w.viewport()->boundsOf({slab}).Get(x0, y0, z0, x1, y1, z1);
        QVERIFY(std::abs(z1 - 3.0) < 0.01);
        QVERIFY(w.isDirty());
        QVERIFY(w.close());
    }

    // Slice 8: versioned projects: enable, save versions, history, compare colours, options.
    void versionedProjectFlow()
    {
        QTemporaryDir tmp;
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.wallTool()->finish();
        w.wallTool()->click({0, 3});
        w.wallTool()->click({5, 3});
        w.setTool(kimcad::MainWindow::Tool::None);
        const QStringList walls = w.viewport()->guids();
        QCOMPARE(walls.size(), 2);

        QVERIFY(w.enableVersioning(tmp.filePath(QStringLiteral("proyecto ñ"))));
        QCOMPARE(w.history().size(), 1);
        QVERIFY(!w.isDirty());
        QVERIFY(w.windowTitle().contains(QStringLiteral("proyecto ñ")));
        const QString first = w.history().first().toObject().value("id").toString();

        w.setSelection({walls[0]});
        QVERIFY(w.applyName(QStringLiteral("Muro sur")));
        QVERIFY(w.isDirty());
        QVERIFY(w.saveVersion(QStringLiteral("Rename the south wall")));
        QCOMPARE(w.history().size(), 2);
        QVERIFY(!w.isDirty());

        QVERIFY(w.compareWith(first));
        QCOMPARE(w.viewport()->coloredCount(), 1);
        QCOMPARE(w.compareChangeCount(), 1);
        w.endCompare();
        QCOMPARE(w.viewport()->coloredCount(), 0);

        QVERIFY(w.createOption(QStringLiteral("Option B")));
        QVERIFY(w.windowTitle().contains(QStringLiteral("Option B")));
        w.setSelection({walls[1]});
        QVERIFY(w.deleteSelection());
        QVERIFY(w.saveVersion(QStringLiteral("B without the north wall")));
        QCOMPARE(w.viewport()->elementCount(), 1);

        QSignalSpy loaded(&w, &kimcad::MainWindow::loadFinished);
        QVERIFY(w.switchOption(QStringLiteral("main")));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(w.viewport()->elementCount(), 2); // main still has both walls
        QVERIFY(w.windowTitle().contains(QStringLiteral("main")));
        QVERIFY(!w.isDirty());
        QVERIFY(w.close());
    }

    // M5 exit (Slice 22): two design options are created, edited separately, compared and combined
    // with one conflict resolved in the UI.
    void m5ExitCombineOptions()
    {
        QTemporaryDir tmp;
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.wallTool()->finish();
        w.wallTool()->click({0, 3});
        w.wallTool()->click({5, 3});
        w.setTool(kimcad::MainWindow::Tool::None);
        const QStringList walls = w.viewport()->guids();
        QCOMPARE(walls.size(), 2);
        QVERIFY(w.enableVersioning(tmp.filePath(QStringLiteral("casa"))));

        // Option B: the south wall renamed, a third wall added.
        QVERIFY(w.createOption(QStringLiteral("Scheme B")));
        w.setSelection({walls[0]});
        QVERIFY(w.applyName(QStringLiteral("South wall (B)")));
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 6});
        w.wallTool()->click({5, 6});
        w.setTool(kimcad::MainWindow::Tool::None);
        QVERIFY(w.saveVersion(QStringLiteral("B: rename, third wall")));

        // main: the same wall renamed differently.
        QSignalSpy loaded(&w, &kimcad::MainWindow::loadFinished);
        QVERIFY(w.switchOption(QStringLiteral("main")));
        QVERIFY(loaded.wait(60000));
        w.setSelection({walls[0]});
        QVERIFY(w.applyName(QStringLiteral("South wall (A)")));
        QVERIFY(w.saveVersion(QStringLiteral("A: rename")));

        // Compared.
        QVERIFY(w.compareWith(QStringLiteral("Scheme B"), QStringLiteral("WORKING")));
        QCOMPARE(w.compareChangeCount(), 2); // the renamed wall and the third wall
        w.endCompare();

        // Combined in the dialog: one conflict, resolved by choosing the other option's name.
        auto bridge = [](const char* fn, const QStringList& args) {
            QString error;
            return kimcad::PythonEngine::instance().callJson(fn, args, &error).object();
        };
        kimcad::CombineDialog dialog(bridge, {QStringLiteral("Scheme B")});
        QCOMPARE(dialog.option(), QStringLiteral("Scheme B"));
        QCOMPARE(dialog.table()->rowCount(), 1);
        QVERIFY(dialog.table()->item(0, 0)->text().contains(QStringLiteral("IfcWall")));
        QVERIFY(!dialog.combineButton()->isEnabled()); // a choice is needed first
        QVERIFY(dialog.choose(0, QStringLiteral("theirs")));
        QVERIFY(dialog.combineButton()->isEnabled());
        loaded.clear();
        QVERIFY(w.combineOptions(dialog.option(), dialog.resolutions()));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(w.viewport()->elementCount(), 3); // both options' work
        QVERIFY(w.viewport()->coloredCount() >= 2); // what B brought (green), the choice (orange)
        QVERIFY(w.isDirty()); // reviewed before saving
        QVERIFY(w.saveVersion(QStringLiteral("Combine Scheme B")));
        const QJsonObject top = w.history().first().toObject();
        QCOMPARE(top.value("parents").toArray().size(), 2);
        QVERIFY(action(w, "actionCombineOptions"));
        QVERIFY(w.close());
    }

    // Slice 20: milestones, object history, before/after, deleting an option.
    void sheetRefreshedMidDragStillMovesTheDraggedDrawing()
    {
        // The drag kept an index into the placed drawings; a sheet refresh (a background generation
        // finishing) replaced them mid-drag, and paint/release read past the end of the list.
        kimcad::DrawingView view(QStringLiteral("sheet:A01"));
        view.resize(400, 300);
        view.setPlaced({{QStringLiteral("d1"), QRectF(0, 0, 50, 50)}, {QStringLiteral("d2"), QRectF(60, 0, 50, 50)}});
        QSignalSpy moved(&view, &kimcad::DrawingView::placedMoved);
        const QPointF from = (QPointF(80, 10) - view.toPaper(QPointF(0, 0))) * view.zoom(); // on d2
        QTest::mousePress(&view, Qt::LeftButton, {}, from.toPoint());
        view.setPlaced({{QStringLiteral("d1"), QRectF(0, 0, 50, 50)}}); // d2's plan was deleted meanwhile
        QTest::mouseMove(&view, (from + QPointF(20, 20)).toPoint());
        view.repaint();
        QTest::mouseRelease(&view, Qt::LeftButton, {}, (from + QPointF(20, 20)).toPoint());
        QCOMPARE(moved.size(), 1);
        QCOMPARE(moved.at(0).at(0).toString(), QStringLiteral("d2"));
    }

    void combineDialogPreviewsOncePerChoice()
    {
        // A choice queued a refresh and choose() refreshed again: the three-way merge ran twice.
        int previews = 0;
        kimcad::CombineDialog::Bridge bridge = [&previews](const char* fn, const QStringList&) {
            if (QByteArray(fn) == "combine_preview")
                ++previews;
            const QJsonObject conflict{{"id", "o/W#Name"}, {"kind", "attribute"}, {"attribute", "Name"},
                {"options", QJsonArray{"ours", "theirs"}}};
            return QJsonObject{{"ok", true}, {"status", "merge"}, {"conflicts", QJsonArray{conflict}},
                {"unresolved", QJsonArray{}}, {"from_theirs", QJsonArray{}}};
        };
        kimcad::CombineDialog dialog(bridge, {QStringLiteral("Scheme B")});
        QCoreApplication::processEvents();
        previews = 0;
        QVERIFY(dialog.choose(0, QStringLiteral("theirs")));
        QCoreApplication::processEvents();
        QCOMPARE(previews, 1);
    }

    void milestonesHistoryAndDeleteOption()
    {
        QTemporaryDir tmp;
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.setTool(kimcad::MainWindow::Tool::None);
        const QString wall = w.viewport()->guids().first();
        QVERIFY(w.enableVersioning(tmp.filePath(QStringLiteral("hitos"))));
        const QString first = w.history().first().toObject().value("id").toString();
        QVERIFY(w.addMilestone(QStringLiteral("Concept")));
        QCOMPARE(w.history().first().toObject().value("milestones").toArray().first().toString(), QStringLiteral("Concept"));
        w.setSelection({wall});
        QVERIFY(w.applyName(QStringLiteral("Muro sur")));
        QVERIFY(!w.addMilestone(QStringLiteral("Schematic design"))); // unsaved changes: save first
        QVERIFY(w.saveVersion(QStringLiteral("Rename")));
        const QJsonArray steps = w.objectHistory(wall).value("versions").toArray();
        QCOMPARE(steps.size(), 2);
        QCOMPARE(steps.first().toObject().value("change").toString(), QStringLiteral("modified"));
        const QJsonObject ba = w.beforeAfter(wall, first);
        QVERIFY(ba.value("ok").toBool());
        bool nameChanged = false;
        for (const auto& row : ba.value("rows").toArray())
            nameChanged |= row.toObject().value("field").toString() == QLatin1String("Name") && row.toObject().value("changed").toBool();
        QVERIFY(nameChanged);
        QVERIFY(w.compareWith(QStringLiteral("Concept"))); // milestones compare by name
        QCOMPARE(w.compareChangeCount(), 1);
        w.endCompare();
        QVERIFY(w.createOption(QStringLiteral("Scheme B")));
        QVERIFY(!w.deleteOption(QStringLiteral("Scheme B"))); // the current option
        QSignalSpy loaded(&w, &kimcad::MainWindow::loadFinished);
        QVERIFY(w.switchOption(QStringLiteral("main")));
        QVERIFY(loaded.wait(60000));
        QVERIFY(w.deleteOption(QStringLiteral("Scheme B")));
        QVERIFY(action(w, "actionAddMilestone") && action(w, "actionObjectHistory") && action(w, "actionDeleteOption"));
        QVERIFY(w.close());
    }

    // Feedback: the plan cut height is a slider at the right of the 3D view; using it turns the cut on.
    void planCutSliderBesideTheView()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        auto* slider = w.findChild<QSlider*>(QStringLiteral("planCutSlider"));
        QVERIFY(slider);
        QCOMPARE(slider->orientation(), Qt::Vertical);
        QCOMPARE(w.viewport()->clipPlaneCount(), 0);
        slider->setValue(150); // centimetres above the level
        QVERIFY(action(w, "actionPlanCut")->isChecked());
        QCOMPARE(w.viewport()->clipPlaneCount(), 1);
        QCOMPARE(w.planCutHeight(), 1.5);
        w.setPlanCutHeight(2.0); // the toolbar field drives the slider too
        QCOMPARE(slider->value(), 200);
        QVERIFY(w.close());
    }

    // Owner feedback: editing a length in the Properties panel changes the element.
    void editingDimensionsInThePanelChangesGeometry()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.setTool(kimcad::MainWindow::Tool::None);
        const QString wall = w.viewport()->guids().first();
        w.setSelection({wall});
        QVERIFY(w.applyPropertyEdit(QStringLiteral("Dimensions"), QStringLiteral("Length"), QJsonValue(6.5)));
        double x0, y0, z0, x1, y1, z1;
        w.viewport()->boundsOf({wall}).Get(x0, y0, z0, x1, y1, z1);
        QVERIFY(std::abs((x1 - x0) - 6.5) < 0.01);
        QVERIFY(w.applyPropertyEdit(QStringLiteral("Dimensions"), QStringLiteral("Height"), QJsonValue(4.0)));
        w.viewport()->boundsOf({wall}).Get(x0, y0, z0, x1, y1, z1);
        QVERIFY(std::abs(z1 - 4.0) < 0.01);
        QVERIFY(!w.applyPropertyEdit(QStringLiteral("Dimensions"), QStringLiteral("Thickness"), QJsonValue(0.5)));
        QVERIFY(w.close());
    }

    // Owner feedback: drag to move — pressing on a selected element and dragging moves the selection
    // (snapped: here 0.97 m becomes 1 m on the grid... the angle snap keeps it straight).
    void draggingASelectedElementMovesIt()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.setTool(kimcad::MainWindow::Tool::None);
        const QString wall = w.viewport()->guids().first();
        w.setSelection({wall});
        w.dragMoveTo(QPointF(2.5, 0.0), QPointF(2.52, -1.004), 0.05, Qt::NoModifier); // preview only
        QVERIFY(w.dragFinished(QPointF(2.5, 0.0), QPointF(2.52, -1.004), 0.05, Qt::NoModifier));
        double x0, y0, z0, x1, y1, z1;
        w.viewport()->boundsOf({wall}).Get(x0, y0, z0, x1, y1, z1);
        QVERIFY(std::abs((y0 + y1) / 2 - (-1.0)) < 0.01); // moved straight down 1 m (90 degree snap)
        QVERIFY(std::abs(x0 - (-0.15)) < 0.02 || std::abs(x0) < 0.02);
        QVERIFY(!w.dragFinished(QPointF(1, 1), QPointF(1, 1), 0.05, Qt::NoModifier)); // no movement
        QVERIFY(w.close());
    }

    // Owner feedback: layers as boundaries, views as collections of layers.
    void layersAndViews()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.wallTool()->finish();
        w.wallTool()->click({0, 3});
        w.wallTool()->click({5, 3});
        w.setTool(kimcad::MainWindow::Tool::None);
        QStringList walls = w.viewport()->guids();
        QVERIFY(w.columnAt(QPointF(8, 0)));
        QCOMPARE(w.viewport()->visibleElementCount(), 3);

        QVERIFY(w.createLayer(QStringLiteral("A-WALL")));
        w.setSelection(walls);
        QVERIFY(w.assignSelectionToLayer(QStringLiteral("A-WALL")));
        w.setLayerVisible(QStringLiteral("A-WALL"), false);
        QCOMPARE(w.viewport()->visibleElementCount(), 1);
        QVERIFY(w.saveView(QStringLiteral("Structure")));
        w.setLayerVisible(QStringLiteral("A-WALL"), true);
        QCOMPARE(w.viewport()->visibleElementCount(), 3);
        QVERIFY(w.applyView(QStringLiteral("Structure")));
        QCOMPARE(w.viewport()->visibleElementCount(), 1);
        w.setLayerVisible(QStringLiteral("A-WALL"), true);
        w.setLayerLocked(QStringLiteral("A-WALL"), true);
        QVERIFY(w.viewport()->isLocked(walls[0]));
        QVERIFY(w.close());
    }

    // Owner feedback: "models" — an apartment drawn once and placed on many levels.
    void modelsPlacedOnLevels()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        const QString level = w.levelsBar()->activeStorey();
        QVERIFY(w.createModel(QStringLiteral("Apartment A")));
        const QString model = w.levelsBar()->activeStorey();
        QVERIFY(model != level); // the new model is where we draw now
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.wallTool()->click({5, 3});
        w.wallTool()->finish();
        w.setTool(kimcad::MainWindow::Tool::None);
        const QStringList inModel = w.viewport()->guids();
        QCOMPARE(w.viewport()->visibleElementCount(), 2);
        w.levelsBar()->setActive(level);
        QCOMPARE(w.viewport()->visibleElementCount(), 0); // models aren't part of the building

        w.setTool(kimcad::MainWindow::Tool::PlaceModel);
        QVERIFY(w.placeModelAt(QPointF(10, 0), false));
        QVERIFY(w.placeModelAt(QPointF(10, 10), true));
        w.setTool(kimcad::MainWindow::Tool::None);
        QCOMPARE(w.viewport()->visibleElementCount(), 4);

        QString part;
        for (const QString& g : w.viewport()->guids())
            if (!inModel.contains(g))
                part = g;
        w.setSelection({part});
        QCOMPARE(w.selection().size(), 2); // a click on an instance takes the whole instance

        w.levelsBar()->setActive(model);
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 3});
        w.wallTool()->click({0, 0});
        w.wallTool()->finish();
        w.setTool(kimcad::MainWindow::Tool::None);
        QVERIFY(w.updateModelInstances());
        w.levelsBar()->setActive(level);
        QCOMPARE(w.viewport()->visibleElementCount(), 6);

        w.setSelection({part});
        QVERIFY(w.explodeSelectedInstance());
        w.setSelection({part});
        QCOMPARE(w.selection().size(), 1);
        QVERIFY(w.close());
    }

    // Owner feedback: architects put labels, dimensions and marks on the plan.
    void planAnnotations()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        QVERIFY(w.addAnnotation(QStringLiteral("text"), {QPointF(1, 2)}, QStringLiteral("Living room")));
        QVERIFY(w.addAnnotation(QStringLiteral("mark"), {QPointF(3, 3)}, QStringLiteral("A")));
        QCOMPARE(w.viewport()->annotationCount(), 2);

        // The dimension tool: click both ends, then where the dimension line goes.
        w.setTool(kimcad::MainWindow::Tool::Dimension);
        for (const QPointF p : {QPointF(0, 0), QPointF(4.5, 0), QPointF(2, -1)})
            emit w.viewport()->workPointClicked(p, 0.01, Qt::NoModifier);
        w.setTool(kimcad::MainWindow::Tool::None);
        QCOMPARE(w.viewport()->annotationCount(), 3);
        QVERIFY(w.viewport()->annotationTexts().contains(QStringLiteral("4.50")));

        // Slice 15: Shift+click chains more points; the Leader tool points at something.
        w.setTool(kimcad::MainWindow::Tool::Dimension);
        emit w.viewport()->workPointClicked(QPointF(0, 5), 0.01, Qt::NoModifier);
        emit w.viewport()->workPointClicked(QPointF(3, 5), 0.01, Qt::NoModifier);
        emit w.viewport()->workPointClicked(QPointF(7, 5), 0.01, Qt::ShiftModifier);
        emit w.viewport()->workPointClicked(QPointF(2, 6), 0.01, Qt::NoModifier);
        QVERIFY(w.viewport()->annotationTexts().contains(QStringLiteral("3.00 4.00")));
        w.setTool(kimcad::MainWindow::Tool::Leader);
        emit w.viewport()->workPointClicked(QPointF(1, 1), 0.01, Qt::NoModifier);
        emit w.viewport()->workPointClicked(QPointF(2, 2), 0.01, Qt::NoModifier);
        w.setTool(kimcad::MainWindow::Tool::None);
        QCOMPARE(w.viewport()->annotationCount(), 5);
        QVERIFY(w.viewport()->annotationTexts().contains(QStringLiteral("Note")));

        // Annotations are selectable, deletable, and live on a level.
        const QString label = w.viewport()->annotationGuids().first();
        w.viewport()->selectGuids({label});
        QCOMPARE(w.viewport()->selectedGuids(), QStringList{label});
        w.setSelection({label});
        QCOMPARE(w.viewport()->typeOf(label), QStringLiteral("IfcAnnotation"));
        QVERIFY(w.deleteSelection());
        QCOMPARE(w.viewport()->annotationCount(), 4);
        QVERIFY(w.addLevel(QStringLiteral("Level 2"), 3.0));
        QCOMPARE(w.viewport()->annotationCount(), 0); // each level has its own
        QVERIFY(w.close());
    }

    void sectionsAndElevations()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        // D61: a new project has Archicad's four template elevations, listed and marked in plan.
        QCOMPARE(w.drawingsPanel()->count(), 5);
        w.viewport()->set3DView();
        QCOMPARE(w.viewport()->markerCount(), 0); // plan symbols, not shown in 3D (Archicad)
        action(w, "actionPlanView")->trigger();
        QCOMPARE(w.viewport()->markerCount(), 4);
        QCOMPARE(w.viewport()->annotationCount(), 0); // markers are not plan annotations

        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        for (const QPointF& p : {QPointF(0, 0), QPointF(8, 0)})
            w.wallTool()->click(p);
        w.setTool(kimcad::MainWindow::Tool::None);

        // The Section tool (D61): two clicks for the line, a third for the side it looks at.
        w.setTool(kimcad::MainWindow::Tool::Section);
        for (const QPointF p : {QPointF(4, -2), QPointF(4, 6), QPointF(6, 0)})
            emit w.viewport()->workPointClicked(p, 0.01, Qt::NoModifier);
        w.setTool(kimcad::MainWindow::Tool::None);
        QCOMPARE(w.drawingsPanel()->count(), 6);
        QCOMPARE(w.viewport()->markerCount(), 5);
        const QString section = w.drawingGuid(QStringLiteral("Section 1"));
        QVERIFY(!section.isEmpty());

        // Open it in a tab: generated in the background, shown when ready.
        QVERIFY(w.openDrawing(section));
        kimcad::DrawingView* view = w.drawingView(section);
        QVERIFY(view);
        QTRY_VERIFY_WITH_TIMEOUT(view->hasDrawing(), 60000);
        QVERIFY(!view->isStale());
        QVERIFY(view->paperSize().width() > 5); // the wall's 300 mm cut at 1:100 plus margins

        // An edit makes it out of date; regenerating brings it back.
        w.showModelTab();
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        for (const QPointF& p : {QPointF(0, 3), QPointF(8, 3)})
            w.wallTool()->click(p);
        w.setTool(kimcad::MainWindow::Tool::None);
        QVERIFY(view->isStale());
        w.regenerateDrawing(section);
        QTRY_VERIFY_WITH_TIMEOUT(!view->isStale(), 60000);

        // Markers are selectable and deletable like other elements.
        w.viewport()->selectGuids({section});
        w.setSelection({section});
        QVERIFY(w.deleteSelection());
        QCOMPARE(w.drawingsPanel()->count(), 5);
        QVERIFY(!w.drawingView(section)); // its tab closed

        // Slice 15: the level's floor plan opens like any drawing.
        const QString plan = w.drawingGuid(QStringLiteral("Level 1 Floor Plan"));
        QVERIFY(!plan.isEmpty());
        QVERIFY(w.openDrawing(plan));
        QTRY_VERIFY_WITH_TIMEOUT(w.drawingView(plan)->hasDrawing(), 60000);
        w.showModelTab();

        // An opened IFC has no drawings; View > Create elevations adds the missing ones.
        const QString south = w.drawingGuid(QStringLiteral("South Elevation"));
        w.viewport()->selectGuids({south});
        w.setSelection({south});
        QVERIFY(w.deleteSelection());
        action(w, "actionCreateDrawings")->trigger();
        QCOMPARE(w.drawingsPanel()->count(), 5);
        QVERIFY(w.close());
    }

    void sheetsAndPdf()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        for (const QPointF& p : {QPointF(0, 0), QPointF(6, 0), QPointF(6, 4)})
            w.wallTool()->click(p);
        w.setTool(kimcad::MainWindow::Tool::None);
        QVERIFY(w.setProjectInfo(QJsonObject{{"number", "T-1"}, {"name", "Test house"}}));
        const QString number = w.addSheet(QStringLiteral("A3"), QStringLiteral("Plans"));
        QCOMPARE(number, QStringLiteral("A01"));
        QCOMPARE(w.sheetsPanel()->count(), 1);
        QVERIFY(w.placeOnSheet(number, w.drawingGuid(QStringLiteral("Level 1 Floor Plan"))));
        kimcad::DrawingView* sheet = w.sheetView(number);
        QVERIFY(sheet);
        QTRY_VERIFY_WITH_TIMEOUT(sheet->hasDrawing(), 60000);
        QCOMPARE(sheet->paperSize(), QSizeF(420, 297));
        QTemporaryDir dir;
        const QString pdf = dir.filePath(QStringLiteral("A01.pdf"));
        QVERIFY(w.exportSheet(number, pdf));
        QFile file(pdf);
        QVERIFY(file.open(QIODevice::ReadOnly));
        QVERIFY(file.read(5) == "%PDF-");
        QVERIFY(w.close());
    }

    void everydayEditing()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        for (const QPointF& p : {QPointF(0, 0), QPointF(5, 0)})
            w.wallTool()->click(p);
        w.setTool(kimcad::MainWindow::Tool::None);
        QCOMPARE(w.viewport()->elementCount(), 1);
        const QString wall = w.viewport()->guids().first();
        w.setSelection({wall});
        QVERIFY(w.duplicateSelection()); // Ctrl+D
        QCOMPARE(w.viewport()->elementCount(), 2);
        QVERIFY(w.selection() != QStringList{wall}); // the copy is selected
        w.setSelection({wall});
        w.copyToClipboard();
        QVERIFY(w.paste()); // Ctrl+V: in place on the active level
        QCOMPARE(w.viewport()->elementCount(), 3);
        w.setSelection({wall});
        QVERIFY(w.dragFinished(QPointF(2, 0), QPointF(2, 3), 0.01, Qt::ControlModifier)); // Ctrl+drag copies
        QCOMPARE(w.viewport()->elementCount(), 4);
        w.setSelection({wall});
        QVERIFY(w.multiplySelection(QStringLiteral("linear"), {{"dx", 0.0}, {"dy", 6.0}, {"count", 2}}));
        QCOMPARE(w.viewport()->elementCount(), 6);
        w.setSelection({wall});
        w.setTool(kimcad::MainWindow::Tool::Mirror); // Ctrl+M: two clicks; Ctrl on the second copies
        emit w.viewport()->workPointClicked(QPointF(0, -2), 0.01, Qt::NoModifier);
        emit w.viewport()->workPointClicked(QPointF(5, -2), 0.01, Qt::ControlModifier);
        QCOMPARE(w.viewport()->elementCount(), 7);
        w.setSelection({wall});
        QVERIFY(w.offsetSelection(1.0));
        QCOMPARE(w.viewport()->elementCount(), 8);
        QVERIFY(w.close());
    }

    void roomsAndSchedule()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        for (const QPointF& p : {QPointF(0, 0), QPointF(6, 0), QPointF(6, 4), QPointF(0, 4), QPointF(0, 0)})
            w.wallTool()->click(p);
        w.setTool(kimcad::MainWindow::Tool::None);
        QCOMPARE(w.viewport()->elementCount(), 4);
        const int before = w.viewport()->annotationCount();
        w.setTool(kimcad::MainWindow::Tool::Room); // Z: click inside the walls
        emit w.viewport()->workPointClicked(QPointF(20, 20), 0.01, Qt::NoModifier); // outside: nothing
        QCOMPARE(w.viewport()->annotationCount(), before);
        emit w.viewport()->workPointClicked(QPointF(3, 2), 0.01, Qt::NoModifier);
        QCOMPARE(w.viewport()->annotationCount(), before + 1);
        const QString stamp = w.viewport()->annotationTexts().last();
        QVERIFY2(stamp.startsWith(QStringLiteral("Room\n101\n")) && stamp.endsWith(QStringLiteral(" m²")), qPrintable(stamp));
        QVERIFY(action(w, "actionRoomSchedule"));
        QCOMPARE(action(w, "actionRoomTool")->shortcut(), QKeySequence(Qt::Key_Z));
        QVERIFY(w.close());
    }

    void roofsAndTrimToRoof()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        for (const QPointF& p : {QPointF(0, 0), QPointF(6, 0), QPointF(6, 4), QPointF(0, 4), QPointF(0, 0)})
            w.wallTool()->click(p);
        w.setTool(kimcad::MainWindow::Tool::None);
        const QStringList walls = w.viewport()->guids();
        QCOMPARE(walls.size(), 4);
        w.setTool(kimcad::MainWindow::Tool::Roof); // Shift+R: the eaves outline, like a slab
        w.setRoofKind(QStringLiteral("hip"), 35.0);
        w.polygonTool()->setTolerance(0.01);
        for (const QPointF& p : {QPointF(-0.5, -0.5), QPointF(6.5, -0.5), QPointF(6.5, 4.5), QPointF(-0.5, 4.5), QPointF(-0.5, -0.5)})
            w.polygonTool()->click(p);
        w.setTool(kimcad::MainWindow::Tool::None);
        QCOMPARE(w.viewport()->elementCount(), 5);
        QString roof;
        for (const QString& g : w.viewport()->guids())
            if (w.viewport()->typeOf(g) == QLatin1String("IfcRoof"))
                roof = g;
        QVERIFY(!roof.isEmpty());
        QVERIFY(!w.trimWallsToRoof(walls)); // no roof selected
        QVERIFY(w.trimWallsToRoof(QStringList(walls) << roof));
        QVERIFY(w.releaseWallsFromRoof(walls));
        QCOMPARE(action(w, "actionRoofTool")->shortcut(), QKeySequence(Qt::SHIFT | Qt::Key_R));
        QVERIFY(w.close());
    }

    void shortcutsAreTheDocumentedOnes()
    {
        kimcad::MainWindow w0(nullptr, true);
        QCOMPARE(action(w0, "actionDuplicate")->shortcut(), QKeySequence(Qt::CTRL | Qt::Key_D));
        QCOMPARE(action(w0, "actionMirror")->shortcut(), QKeySequence(Qt::CTRL | Qt::Key_M));
        QCOMPARE(action(w0, "actionMultiply")->shortcut(), QKeySequence(Qt::CTRL | Qt::Key_U));
        QCOMPARE(action(w0, "actionCopy")->shortcut(), QKeySequence(QKeySequence::Copy));
        kimcad::MainWindow w(nullptr, true);
        QCOMPARE(action(w, "actionSectionTool")->shortcut(), QKeySequence(Qt::Key_V));
        QCOMPARE(action(w, "actionLeaderTool")->shortcut(), QKeySequence(Qt::SHIFT | Qt::Key_A));
        QCOMPARE(action(w, "actionElevationTool")->shortcut(), QKeySequence(Qt::SHIFT | Qt::Key_V));
        QCOMPARE(action(w, "actionHideSelected")->shortcut(), QKeySequence(Qt::Key_H));
        QCOMPARE(action(w, "actionIsolateSelected")->shortcut(), QKeySequence(Qt::Key_I));
        QCOMPARE(action(w, "actionShowAll")->shortcut(), QKeySequence(Qt::SHIFT | Qt::Key_H));
        QCOMPARE(action(w, "actionUndo")->shortcut(), QKeySequence(QKeySequence::Undo));
        QCOMPARE(action(w, "actionSave")->shortcut(), QKeySequence(QKeySequence::Save));
        QCOMPARE(action(w, "actionDelete")->shortcut(), QKeySequence(QKeySequence::Delete));
        QCOMPARE(action(w, "actionNewProject")->shortcut(), QKeySequence(QKeySequence::New));
        QCOMPARE(action(w, "actionPlanView")->shortcut(), QKeySequence(Qt::Key_P));
        QCOMPARE(action(w, "actionLinesOnly")->shortcut(), QKeySequence(Qt::Key_L));
        QCOMPARE(action(w, "actionSlabTool")->shortcut(), QKeySequence(Qt::Key_S));
        QCOMPARE(action(w, "actionDoorTool")->shortcut(), QKeySequence(Qt::Key_D));
        QCOMPARE(action(w, "actionWindowTool")->shortcut(), QKeySequence(Qt::Key_N));
        QCOMPARE(action(w, "actionColumnTool")->shortcut(), QKeySequence(Qt::Key_K));
        QCOMPARE(action(w, "actionBeamTool")->shortcut(), QKeySequence(Qt::Key_J));
        QCOMPARE(action(w, "actionGridTool")->shortcut(), QKeySequence(Qt::Key_G));
        QCOMPARE(action(w, "actionMoveTool")->shortcut(), QKeySequence(Qt::Key_M));
        QCOMPARE(action(w, "actionRotateTool")->shortcut(), QKeySequence(Qt::Key_R));
        QCOMPARE(action(w, "actionStretchTool")->shortcut(), QKeySequence(Qt::Key_E));
        QCOMPARE(action(w, "actionStairTool")->shortcut(), QKeySequence(Qt::Key_T));
        QCOMPARE(action(w, "actionPlaceModelTool")->shortcut(), QKeySequence(Qt::Key_U));
        QCOMPARE(action(w, "actionTextTool")->shortcut(), QKeySequence(Qt::Key_A));
        QCOMPARE(action(w, "actionDimensionTool")->shortcut(), QKeySequence(Qt::Key_Q));
        QCOMPARE(action(w, "actionMarkTool")->shortcut(), QKeySequence(Qt::Key_X));
        QCOMPARE(action(w, "actionSlabOpeningTool")->shortcut(), QKeySequence(Qt::Key_O));
        QCOMPARE(action(w, "actionSaveVersion")->shortcut(), QKeySequence(Qt::CTRL | Qt::ALT | Qt::Key_S));
        QVERIFY(action(w, "actionLinesOnly")->isCheckable());
    }

    // D72: new views follow the "new_views" preference.
    void newViewsFollowThePreference()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        QCOMPARE(w.newViewPlacement(), kimcad::DockLayout::Placement::AfterCurrent);
        w.preferences().setValue("new_views", "window");
        QCOMPARE(w.newViewPlacement(), kimcad::DockLayout::Placement::Floating);
        w.openPlanTab(w.levelsBar()->activeStorey());
        const QString key = QStringLiteral("plan:") + w.levelsBar()->activeStorey();
        QVERIFY(w.dockLayout()->manager()->findDockWidget(key)->isFloating());
        QVERIFY(w.close());
    }

    // D72: a new project saved as .kim, edited, saved (no version), reopened; Save version packs too.
    void kimFileFlow()
    {
        QTemporaryDir tmp;
        const QString kim = tmp.filePath(QStringLiteral("Casa ñ.kim"));
        {
            kimcad::MainWindow w(nullptr, /*quiet=*/true);
            QVERIFY(w.newProject());
            w.setTool(kimcad::MainWindow::Tool::Wall);
            w.wallTool()->click({0, 0});
            w.wallTool()->click({5, 0});
            w.wallTool()->finish();
            w.setTool(kimcad::MainWindow::Tool::None);
            QVERIFY(w.saveAs(kim));
            QVERIFY(QFile::exists(kim) && QFile::exists(kim + ".lock"));
            QVERIFY(w.windowTitle().contains(QStringLiteral("Casa ñ.kim")));
            QCOMPARE(w.history().size(), 1);
            w.setSelection(w.viewport()->guids());
            QVERIFY(w.applyName(QStringLiteral("Muro")));
            QVERIFY(w.save());
            QVERIFY(!w.isDirty() && w.hasUnversionedWork());
            QCOMPARE(w.history().size(), 1);
            QVERIFY(w.saveVersion(QStringLiteral("Named the wall")));
            QVERIFY(!w.hasUnversionedWork());
            QVERIFY(w.close());
        }
        QVERIFY(!QFile::exists(kim + ".lock"));
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy loaded(&w, &kimcad::MainWindow::loadFinished);
        QVERIFY(w.openPath(kim));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(w.viewport()->elementCount(), 1);
        QCOMPARE(w.history().size(), 2);
        QCOMPARE(w.preferences().recent().first(), QDir::toNativeSeparators(kim));
        QVERIFY(w.close());
    }

    // D72: opening an IFC makes a .kim beside it (default) or edits the IFC (preference).
    void openingAnIfcFollowsThePreference()
    {
        QTemporaryDir tmp;
        const QString ifc = tmp.filePath(QStringLiteral("House.ifc"));
        {
            kimcad::MainWindow w(nullptr, /*quiet=*/true);
            QVERIFY(w.newProject());
            QVERIFY(w.exportIfc(ifc));
            QVERIFY(w.close());
        }
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy loaded(&w, &kimcad::MainWindow::loadFinished);
        QVERIFY(w.openPath(ifc));
        QVERIFY(loaded.wait(60000));
        QVERIFY(QFile::exists(tmp.filePath(QStringLiteral("House.kim"))));
        QCOMPARE(w.documentState().value("mode").toString(), QString("kim"));
        w.preferences().setValue("open_ifc", "edit_ifc");
        QVERIFY(w.openPath(ifc));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(w.documentState().value("mode").toString(), QString("plain"));
        QCOMPARE(w.documentState().value("name").toString(), QString("House.ifc"));
        QVERIFY(w.close());
    }

    // Making a .kim from a large IFC takes minutes with the Python decomposer (the Clinic: ~6 min):
    // it runs on a worker thread so the window keeps repainting meanwhile.
    void makingAKimKeepsTheWindowResponsive()
    {
        QTemporaryDir tmp;
        const QString ifc = tmp.filePath(QStringLiteral("House.ifc"));
        {
            kimcad::MainWindow w(nullptr, /*quiet=*/true);
            QVERIFY(w.newProject());
            QVERIFY(w.exportIfc(ifc));
            QVERIFY(w.close());
        }
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy loaded(&w, &kimcad::MainWindow::loadFinished);
        bool ranMeanwhile = false;
        QTimer::singleShot(0, &w, [&] { ranMeanwhile = true; }); // runs only if openPath turns the event loop
        QVERIFY(w.openPath(ifc));
        QVERIFY(ranMeanwhile);
        QVERIFY(loaded.wait(60000));
        QVERIFY(QFile::exists(tmp.filePath(QStringLiteral("House.kim"))));
        QCOMPARE(w.documentState().value("mode").toString(), QString("kim"));
        QVERIFY(w.close());
    }

    // A large IFC asks first: make a .kim (minutes), edit the IFC directly, or cancel. Small files, a
    // .kim already beside it and the "edit the IFC directly" preference don't ask.
    void aLargeIfcAsksBeforeMakingAKim()
    {
        QTemporaryDir tmp;
        const QString ifc = tmp.filePath(QStringLiteral("House.ifc"));
        const QString kim = tmp.filePath(QStringLiteral("House.kim"));
        {
            kimcad::MainWindow w(nullptr, /*quiet=*/true);
            QVERIFY(w.newProject());
            QVERIFY(w.exportIfc(ifc));
            QVERIFY(w.close());
        }
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy loaded(&w, &kimcad::MainWindow::loadFinished);
        int asked = 0;
        auto answer = kimcad::MainWindow::LargeIfc::Cancel;
        w.setLargeIfcAnswer([&](const QString& file, double mb) {
            ++asked;
            [&] { QCOMPARE(file, QString("House.ifc")); QVERIFY(mb > 0.0); }();
            return answer;
        });

        // below the limit (default 5 MB): no question, a .kim as the preference says
        QVERIFY(w.openPath(ifc));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(asked, 0);
        QVERIFY(QFile::exists(kim));
        QVERIFY(w.closeDocument());
        QVERIFY(QFile::remove(kim));

        w.preferences().setValue("large_ifc_mb", 0.001); // House.ifc is larger than 1 kB
        // Cancel: nothing opens, no .kim
        QVERIFY(!w.openPath(ifc));
        QCOMPARE(asked, 1);
        QVERIFY(!QFile::exists(kim));

        // Edit the IFC directly: opens at once as a plain IFC
        answer = kimcad::MainWindow::LargeIfc::EditIfc;
        QVERIFY(w.openPath(ifc));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(asked, 2);
        QVERIFY(!QFile::exists(kim));
        QCOMPARE(w.documentState().value("mode").toString(), QString("plain"));

        // Make a .kim
        answer = kimcad::MainWindow::LargeIfc::MakeKim;
        QVERIFY(w.openPath(ifc));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(asked, 3);
        QCOMPARE(w.documentState().value("mode").toString(), QString("kim"));

        // the .kim beside it now exists: opening the IFC offers it, no conversion question
        QVERIFY(w.openPath(ifc));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(asked, 3);

        // the "edit the IFC directly" preference doesn't ask
        w.preferences().setValue("open_ifc", "edit_ifc");
        QVERIFY(w.openPath(ifc));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(asked, 3);
        QCOMPARE(w.documentState().value("mode").toString(), QString("plain"));

        // 0 turns the question off
        QVERIFY(w.closeDocument());
        QVERIFY(QFile::remove(kim));
        w.preferences().setValue("open_ifc", "make_kim");
        w.preferences().setValue("large_ifc_mb", 0);
        QVERIFY(w.openPath(ifc));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(asked, 3);
        QVERIFY(QFile::exists(kim));
        QVERIFY(w.close());
    }

    // Draws one wall with the wall tool; returns its GlobalId.
    static QString drawWall(kimcad::MainWindow& w, QPointF a = QPointF(0, 0), QPointF b = QPointF(4, 0))
    {
        const QStringList before = w.viewport()->guids();
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->setTolerance(0.05);
        w.wallTool()->click(a);
        w.wallTool()->click(b);
        w.setTool(kimcad::MainWindow::Tool::None);
        for (const QString& g : w.viewport()->guids())
            if (!before.contains(g))
                return g;
        return {};
    }

    // D73: picking a purpose restyles the views.
    void purposesRestyleTheViews()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        const QString wall = drawWall(w);
        QVERIFY(!wall.isEmpty());
        QVERIFY(w.setPurpose(QStringLiteral("Permit")));
        const kimcad::ElementStyle* s = w.viewport()->graphics().styleOf(wall);
        QVERIFY(s);
        QCOMPARE(s->projection.color, QColor("#000000"));
        QCOMPARE(w.viewport()->graphics().purpose(), QString("Permit"));
        QVERIFY(w.isWindowModified()); // the purpose is a project setting: Ctrl+S saves it
        QVERIFY(w.setPurpose(QStringLiteral("Working")));
        QCOMPARE(w.viewport()->graphics().styleOf(wall)->projection.color, QColor("#8a6a4a"));
        QVERIFY(!w.setPurpose(QStringLiteral("Nope")));
    }

    // D73: elements drawn after switching purpose get the purpose's style.
    void newElementsGetThePurposeStyle()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        QVERIFY(w.setPurpose(QStringLiteral("Permit")));
        const QString wall = drawWall(w);
        QVERIFY(w.viewport()->graphics().styleOf(wall));
        QCOMPARE(w.viewport()->graphics().styleOf(wall)->cut.color, QColor("#000000"));
    }

    // D73: hidden kinds can't be selected and Show all doesn't reveal them.
    void hiddenKindsAreNotSelectableAndSurviveShowAll()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        const QString wall = drawWall(w);
        QVERIFY(w.setGraphics(QStringLiteral(R"({"visibility_sets": {"Everything": {"hidden_kinds": [], "rules": []},
            "No walls": {"hidden_kinds": ["walls"], "rules": []}},
            "purposes": {"Working": {"pen_set": "Working", "visibility": "Everything", "overrides": "None", "layers": null},
                         "NW": {"pen_set": "Working", "visibility": "No walls", "overrides": "None", "layers": null}}})")));
        w.viewport()->selectGuids({wall});
        QCOMPARE(w.viewport()->selectedGuids(), QStringList{wall});
        QVERIFY(w.setPurpose(QStringLiteral("NW")));
        QVERIFY(w.viewport()->graphics().isHidden(wall));
        QVERIFY(w.viewport()->selectedGuids().isEmpty()); // hiding deselects
        w.viewport()->selectGuids({wall});
        QVERIFY(w.viewport()->selectedGuids().isEmpty());
        w.viewport()->showAll();
        QVERIFY(w.viewport()->isElementHidden(wall));
        QVERIFY(w.setPurpose(QStringLiteral("Working")));
        QVERIFY(!w.viewport()->isElementHidden(wall));
    }

    void trueLineWeightsAreAPreference()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        QVERIFY(!w.preferences().trueLineWeights());
        auto* toggle = action(w, "actionTrueLineWeights");
        QVERIFY(toggle && toggle->isCheckable() && !toggle->isChecked());
        toggle->trigger();
        QVERIFY(w.preferences().trueLineWeights());
        QVERIFY(w.viewport()->scene()->trueWeights);
        toggle->trigger();
        QVERIFY(!w.preferences().trueLineWeights());
    }

    // D72: someone else's lock opens the file read-only (quiet mode answers "read-only").
    void aLockedKimOpensReadOnly()
    {
        QTemporaryDir tmp;
        const QString kim = tmp.filePath(QStringLiteral("a.kim"));
        {
            kimcad::MainWindow w(nullptr, /*quiet=*/true);
            QVERIFY(w.newProject());
            QVERIFY(w.saveAs(kim));
            QVERIFY(w.close());
        }
        QFile lock(kim + ".lock");
        QVERIFY(lock.open(QIODevice::WriteOnly));
        lock.write(R"({"user": "Ana", "account": "ana", "machine": "OTHER-PC", "pid": 4, "since": "2026-10-08T10:42"})");
        lock.close();
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy loaded(&w, &kimcad::MainWindow::loadFinished);
        QVERIFY(w.openPath(kim));
        QVERIFY(loaded.wait(60000));
        QVERIFY(w.documentState().value("read_only").toBool());
        QVERIFY(w.windowTitle().contains(QStringLiteral("read-only")));
        QVERIFY(!w.save());
        QVERIFY(w.close());
        QVERIFY(QFile::exists(kim + ".lock")); // Ana's lock is left alone
    }

    // D72: project settings are applied on open and saved with the .kim (layers, cut, scale, paper, units).
    void projectSettingsTravelWithTheKim()
    {
        QTemporaryDir tmp;
        const QString kim = tmp.filePath(QStringLiteral("ajustes.kim"));
        {
            kimcad::MainWindow w(nullptr, /*quiet=*/true);
            QVERIFY(w.newProject());
            QVERIFY(w.createLayer(QStringLiteral("A-WALL")));
            QVERIFY(w.setProjectSettings({{"plan_cut_height", 1.0}, {"sheet_paper", "A3"}, {"drawing_scale", 50},
                                          {"length_unit", "mm"}, {"length_decimals", 0}}));
            QVERIFY(w.isDirty());
            QCOMPARE(w.formatLength(3.5), QLocale().toString(3500.0, 'f', 0) + QStringLiteral(" mm"));
            QVERIFY(!w.setProjectSettings({{"drawing_scale", 0}})); // refused, nothing changes
            w.setLayerVisible(QStringLiteral("A-WALL"), false);
            QVERIFY(w.saveAs(kim));
            QVERIFY(w.close());
        }
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QSignalSpy loaded(&w, &kimcad::MainWindow::loadFinished);
        QVERIFY(w.openPath(kim));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(w.planCutHeight(), 1.0);
        QCOMPARE(w.projectSettings().value("hidden_layers").toArray(), QJsonArray({"A-WALL"}));
        QCOMPARE(w.projectSettings().value("sheet_paper").toString(), QString("A3"));
        QVERIFY(!w.isDirty());
        const QString number = w.addSheet(w.projectSettings().value("sheet_paper").toString(), QStringLiteral("S"));
        QVERIFY(!number.isEmpty());
        QVERIFY(w.close());
    }

    void projectSettingsDialogReportsOnlyChanges()
    {
        kimcad::ProjectSettingsDialog d({{"plan_cut_height", 1.2}, {"drawing_scale", 100}, {"sheet_paper", "A1"},
                                         {"length_unit", "m"}, {"length_decimals", 2}}, /*kept=*/false, nullptr);
        QVERIFY(d.findChild<QLabel*>("notKeptNote")->isVisibleTo(&d));
        d.findChild<QComboBox*>("sheetPaper")->setCurrentText("A3");
        d.findChild<QSpinBox*>("drawingScale")->setValue(50);
        QCOMPARE(d.changes(), QJsonObject({{"sheet_paper", "A3"}, {"drawing_scale", 50}}));
    }

    // D72: an IFC edited directly keeps no settings, so showing or hiding a layer isn't unsaved work.
    void layerStatesOfAnIfcEditedDirectlyAreNotUnsavedWork()
    {
        QTemporaryDir tmp;
        const QString ifc = tmp.filePath(QStringLiteral("directo.ifc"));
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        w.preferences().setValue("open_ifc", "edit_ifc");
        QVERIFY(w.newProject());
        QVERIFY(w.createLayer(QStringLiteral("A-WALL")));
        QVERIFY(w.saveAs(ifc));
        QVERIFY(!w.isDirty());
        w.setLayerVisible(QStringLiteral("A-WALL"), false);
        QVERIFY(!w.isDirty());
        QVERIFY(w.close());
    }

    // D72: an automatic version every N saves.
    void automaticVersionsEveryNSaves()
    {
        QTemporaryDir tmp;
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.wallTool()->finish();
        w.setTool(kimcad::MainWindow::Tool::None);
        QVERIFY(w.saveAs(tmp.filePath(QStringLiteral("auto.kim"))));
        w.preferences().setValue("auto_version", "saves");
        w.preferences().setValue("auto_version_every", 2);
        w.setSelection(w.viewport()->guids());
        QVERIFY(w.applyName(QStringLiteral("uno")));
        QVERIFY(w.save());
        QCOMPARE(w.history().size(), 1);
        QVERIFY(w.applyName(QStringLiteral("dos")));
        QVERIFY(w.save());
        QCOMPARE(w.history().size(), 2);
        QCOMPARE(w.history().first().toObject().value("message").toString(), QString("Automatic version"));
        QVERIFY(w.close());
    }

    // D72: the recovery copy of unsaved work comes back after a "crash".
    void recoveryCopyComesBack()
    {
        QString wall;
        {
            kimcad::MainWindow w(nullptr, /*quiet=*/true);
            QVERIFY(w.newProject());
            w.setTool(kimcad::MainWindow::Tool::Wall);
            w.wallTool()->click({0, 0});
            w.wallTool()->click({5, 0});
            w.wallTool()->finish();
            w.setTool(kimcad::MainWindow::Tool::None);
            wall = w.viewport()->guids().first();
            QVERIFY(w.writeRecovery());
            // A crash: the model goes away without the window closing (no close_document).
            QString error;
            kimcad::PythonEngine::instance().callJson("new_project", {QStringLiteral("x")}, &error);
        } // destroyed without close()
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        const QJsonArray items = w.recoveries();
        QVERIFY(!items.isEmpty());
        QSignalSpy loaded(&w, &kimcad::MainWindow::loadFinished);
        QVERIFY(w.recoverFrom(items.first().toObject().value("id").toString()));
        QVERIFY(loaded.wait(60000));
        QVERIFY(w.viewport()->guids().contains(wall));
        QVERIFY(w.isDirty());
        QVERIFY(w.close()); // quiet close discards: the copy is cleared
        QVERIFY(w.recoveries().isEmpty());
    }

    // D72: office templates: save one, start a project from it, first save makes its history.
    void projectsStartFromOfficeTemplates()
    {
        QTemporaryDir tmp;
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        w.preferences().setValue("templates_folder", tmp.filePath(QStringLiteral("Plantillas")));
        QVERIFY(w.newProject());
        w.setTool(kimcad::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.wallTool()->finish();
        w.setTool(kimcad::MainWindow::Tool::None);
        const QString original = w.viewport()->guids().first();
        QVERIFY(w.saveAsTemplate(QStringLiteral("Oficina")));
        QVERIFY(!w.saveAsTemplate(QStringLiteral("Oficina"))); // exists; quiet mode doesn't replace
        QVERIFY(w.saveAsTemplate(QStringLiteral("Oficina"), /*replace=*/true));
        const QString path = tmp.filePath(QStringLiteral("Plantillas/Oficina.kim"));
        QVERIFY(QFile::exists(path));

        QSignalSpy loaded(&w, &kimcad::MainWindow::loadFinished);
        QVERIFY(w.newFromTemplate(path));
        QVERIFY(loaded.wait(60000));
        QCOMPARE(w.viewport()->elementCount(), 1);
        QVERIFY(!w.viewport()->guids().contains(original)); // new ids
        QVERIFY(w.windowTitle().contains(QStringLiteral("Untitled")));
        QVERIFY(!w.save()); // untitled: quiet mode can't ask where
        QVERIFY(w.saveAs(tmp.filePath(QStringLiteral("nuevo.kim"))));
        QCOMPARE(w.history().first().toObject().value("message").toString(), QString("Created from Oficina"));
        QVERIFY(w.close());
    }

    // Final review: a file that fails to open leaves the open .kim as it was (lock held, still saves).
    void aFailedOpenLeavesTheOpenKimAttached()
    {
        QTemporaryDir tmp;
        const QString kim = tmp.filePath(QStringLiteral("a.kim"));
        const QString junk = tmp.filePath(QStringLiteral("junk.kim"));
        QFile bad(junk);
        QVERIFY(bad.open(QIODevice::WriteOnly));
        bad.write("not a zip");
        bad.close();
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        QVERIFY(w.saveAs(kim));
        QVERIFY(!w.openPath(junk));
        QVERIFY(QFile::exists(kim + ".lock"));
        QCOMPARE(w.documentState().value("name").toString(), QString("a.kim"));
        QVERIFY(w.save());
        QVERIFY(w.close());
    }
};

QTEST_MAIN(TestMainWindow)
#include "test_main_window.moc"
