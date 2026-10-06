// SPDX-License-Identifier: GPL-3.0-or-later
// MainWindow wiring: visibility actions act on the viewport selection (no window shown).
#include <QAction>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QtTest>

#include <cmath>

#include "ElementBatch.h"
#include "LevelsBar.h"
#include "HostTool.h"
#include "MainWindow.h"
#include "PolygonTool.h"
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

    void shortcutsAreTheDocumentedOnes()
    {
        kimcad::MainWindow w(nullptr, true);
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
        QCOMPARE(action(w, "actionSlabOpeningTool")->shortcut(), QKeySequence(Qt::Key_O));
        QVERIFY(action(w, "actionLinesOnly")->isCheckable());
    }
};

QTEST_MAIN(TestMainWindow)
#include "test_main_window.moc"
