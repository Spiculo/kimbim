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

#include "ElementBatch.h"
#include "MainWindow.h"
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

    void shortcutsAreTheDocumentedOnes()
    {
        kimcad::MainWindow w(nullptr, true);
        QCOMPARE(action(w, "actionHideSelected")->shortcut(), QKeySequence(Qt::Key_H));
        QCOMPARE(action(w, "actionIsolateSelected")->shortcut(), QKeySequence(Qt::Key_I));
        QCOMPARE(action(w, "actionShowAll")->shortcut(), QKeySequence(Qt::SHIFT | Qt::Key_H));
        QCOMPARE(action(w, "actionUndo")->shortcut(), QKeySequence(QKeySequence::Undo));
        QCOMPARE(action(w, "actionSave")->shortcut(), QKeySequence(QKeySequence::Save));
        QCOMPARE(action(w, "actionDelete")->shortcut(), QKeySequence(QKeySequence::Delete));
    }
};

QTEST_MAIN(TestMainWindow)
#include "test_main_window.moc"
