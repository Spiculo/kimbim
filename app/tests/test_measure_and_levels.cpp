// SPDX-License-Identifier: GPL-3.0-or-later
// D79: the measure tool (its values, and that it leaves the model alone) and the levels table.
#include <QAction>
#include <QApplication>
#include <QClipboard>
#include <QCheckBox>
#include <QComboBox>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QStandardPaths>
#include <QTableWidget>
#include <QTimer>
#include <QToolButton>
#include <QtTest>

#include <cmath>

#include "LevelsBar.h"
#include "LevelsDialog.h"
#include "MainWindow.h"
#include "MeasureController.h"
#include "MeasureTool.h"
#include "PythonEngine.h"
#include "StatusStrip.h"
#include "Viewport.h"

using kimbim::LevelsTable;
using kimbim::MeasurePoint;
using kimbim::MeasureTool;

namespace {

QJsonObject engine(const char* fn, const QStringList& args = {})
{
    QString error;
    return kimbim::PythonEngine::instance().callJson(fn, args, &error).object();
}

QString metres(double m)
{
    return QString::number(m, 'f', 2) + QStringLiteral(" m");
}

QJsonArray levels(std::initializer_list<std::tuple<const char*, double, int>> rows)
{
    QJsonArray out;
    for (const auto& [name, elevation, elements] : rows)
        out.append(QJsonObject{{"guid", QStringLiteral("g-%1").arg(QLatin1String(name))}, {"name", QLatin1String(name)},
            {"elevation", elevation}, {"show", true}, {"elements", elements}});
    return out;
}

} // namespace

class TestMeasureAndLevels : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { QStandardPaths::setTestModeEnabled(true); }

    void distanceAndItsComponents()
    {
        const auto r = MeasureTool::compute({{1, 1, 0}, {4, 5, 0}});
        QCOMPARE(r.points, 2);
        QCOMPARE(r.distance, 5.0);
        QCOMPARE(r.dx, 3.0);
        QCOMPARE(r.dy, 4.0);
        QCOMPARE(r.dz, 0.0);
        QVERIFY(!r.angle && !r.area);
        const auto up = MeasureTool::compute({{0, 0, 0}, {2, 3, 6}}); // 3D: 2-3-6-7
        QCOMPARE(up.distance, 7.0);
        QCOMPARE(up.dz, 6.0);
    }

    void angleBetweenTheLastTwoSegments()
    {
        auto r = MeasureTool::compute({{0, 0, 0}, {4, 0, 0}, {4, 3, 0}});
        QVERIFY(r.angle);
        QVERIFY(std::abs(*r.angle - 90.0) < 1e-9);
        QCOMPARE(r.distance, 3.0); // the last segment
        QCOMPARE(r.total, 7.0);
        r = MeasureTool::compute({{0, 0, 0}, {1, 0, 0}, {2, 1, 0}, {3, 1, 0}}); // last two: 45 degrees off straight
        QVERIFY(std::abs(*r.angle - 135.0) < 1e-9);
    }

    void areaAndPerimeterOfAKnownPolygon()
    {
        // 4 x 3 rectangle: 12 m², 14 m.
        auto r = MeasureTool::compute({{0, 0, 0}, {4, 0, 0}, {4, 3, 0}, {0, 3, 0}});
        QVERIFY(std::abs(*r.area - 12.0) < 1e-9);
        QVERIFY(std::abs(*r.perimeter - 14.0) < 1e-9);
        // An L (6 x 4 minus 3 x 2 = 18 m²), clockwise and above the ground.
        r = MeasureTool::compute({{0, 0, 3}, {0, 4, 3}, {3, 4, 3}, {3, 2, 3}, {6, 2, 3}, {6, 0, 3}});
        QVERIFY(std::abs(*r.area - 18.0) < 1e-9);
        QVERIFY(std::abs(*r.perimeter - 20.0) < 1e-9);
        // A wall face (vertical): 5 m long, 3 m high.
        r = MeasureTool::compute({{0, 0, 0}, {5, 0, 0}, {5, 0, 3}, {0, 0, 3}});
        QVERIFY(std::abs(*r.area - 15.0) < 1e-9);
        const QString text = MeasureTool::describe(r, metres);
        QVERIFY2(text.contains(QStringLiteral("15")) && text.contains(QStringLiteral("16.00 m")), qPrintable(text));
    }

    // D92: the readout and the label use the project's area unit when the app supplies one.
    void areaUsesTheProjectsUnit()
    {
        const auto r = MeasureTool::compute({{0, 0, 0}, {4, 0, 0}, {4, 3, 0}, {0, 3, 0}});
        const QString text = MeasureTool::describe(r, metres, [](double a) { return QString::number(a, 'f', 2) + QStringLiteral(" cm²"); });
        QVERIFY2(text.contains(QStringLiteral("12.00 cm²")), qPrintable(text));
        QVERIFY(MeasureTool::describe(r, metres).contains(QStringLiteral("12.00 m²"))); // default unchanged
    }

    // D92: a level's elevation change can move the levels above it.
    void levelsTableMoveAbove()
    {
        LevelsTable t(levels({{"L1", 0.0, 0}, {"L2", 3.0, 0}, {"L3", 6.0, 0}}));
        QVERIFY(!t.moveAbove());
        QVERIFY(!t.changes().value("move_above").toBool());
        t.setMoveAbove(true);
        QVERIFY(t.moveAbove());
        QVERIFY(t.changes().value("move_above").toBool());
    }

    // D92 (Revit): when asked, an inserted level goes in the middle of the gap and the levels
    // around it stay; otherwise the levels above make room (Archicad).
    void insertingBetweenLevelsFitsInTheGap()
    {
        LevelsTable t(levels({{"L1", 0.0, 0}, {"L3", 6.0, 0}}));
        QVERIFY(!t.fitBetween());
        t.setFitBetween(true);
        QCOMPARE(t.insertAbove(0, "L2"), 1);
        QCOMPARE(t.rows()[1].elevation, 3.0);
        QCOMPARE(t.rows()[2].elevation, 6.0); // L3 stayed
        QCOMPARE(t.insertBelow(2, "L2b"), 2);
        QCOMPARE(t.rows()[2].elevation, 4.5);
        QCOMPARE(t.rows()[3].elevation, 6.0);

        LevelsTable push(levels({{"L1", 0.0, 0}, {"L3", 6.0, 0}}));
        QCOMPARE(push.insertAbove(0, "L2"), 1);
        QCOMPARE(push.rows()[2].elevation, 12.0); // the default: L3 makes room by the gap
    }

    void clicksSnapAndEscClears()
    {
        MeasureTool tool;
        tool.setTolerance(0.1);
        tool.snapper().setWalls({{QStringLiteral("w"), {0, 0}, {5, 0}, 0.2}});
        QSignalSpy changed(&tool, &MeasureTool::changed);
        tool.click({0.04, 0.03}, 0.0); // snaps to the wall's end
        QCOMPARE(tool.points().size(), 1);
        QCOMPARE(tool.points()[0].x, 0.0);
        // In 3D, over the wall's top near its other end: the end, up there.
        tool.move({9, 9}, 0.0, MeasurePoint{4.97, 0.05, 3.0});
        QVERIFY(tool.hover());
        QCOMPARE(tool.hover()->x, 5.0);
        QCOMPARE(tool.hover()->z, 3.0);
        QCOMPARE(tool.readout().dz, 3.0);
        // On a face with no snap near: the surface point itself.
        tool.move({9, 9}, 0.0, MeasurePoint{2.33, 1.71, 1.25});
        QCOMPARE(tool.hover()->z, 1.25);
        tool.click({9, 9}, 0.0, MeasurePoint{2.33, 1.71, 1.25});
        tool.finish();
        QVERIFY(tool.isFinished() && !tool.hover());
        QCOMPARE(tool.path().size(), 2);
        tool.clear();
        QVERIFY(!tool.isMeasuring());
        QVERIFY(changed.count() >= 5);
    }

    // The tool in the app: values in the bottom bar and on the clipboard, the model untouched.
    void measuringLeavesTheModelUnchanged()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QJsonObject before = engine("state");
        QAction* a = w.findChild<QAction*>(QStringLiteral("actionMeasureTool"));
        QVERIFY(a);
        QCOMPARE(a->shortcut(), QKeySequence(Qt::SHIFT | Qt::Key_M));
        a->trigger();
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::Measure);
        kimbim::Viewport* v = w.viewport();
        emit v->workPointClicked(QPointF(0, 0), 0.01, Qt::NoModifier);
        emit v->workPointMoved(QPointF(3, 4), 0.01, Qt::NoModifier);
        QCOMPARE(w.measure()->tool()->readout().distance, 5.0);
        QVERIFY(v->hasToolOverlay());
        emit v->workPointClicked(QPointF(3, 4), 0.01, Qt::NoModifier);
        emit v->workPointClicked(QPointF(0, 4), 0.01, Qt::NoModifier);
        const auto r = w.measure()->tool()->readout();
        QVERIFY(std::abs(*r.area - 6.0) < 1e-9 && std::abs(*r.angle - std::atan2(4.0, 3.0) * 180 / M_PI) < 1e-9);
        auto* status = w.findChild<kimbim::StatusStrip*>();
        QVERIFY(status && status->message().contains(QStringLiteral("Area")));
        auto* copy = w.findChild<QToolButton*>(QStringLiteral("measureCopy"));
        QVERIFY(copy && !copy->isHidden());
        copy->click();
        QCOMPARE(QGuiApplication::clipboard()->text(), w.measure()->text());
        emit v->drawingEnded(); // Esc clears the path, the tool stays
        QVERIFY(!w.measure()->tool()->isMeasuring());
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::Measure);
        emit v->drawingEnded(); // again: leaves it
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::None);
        QVERIFY(!v->hasToolOverlay());
        const QJsonObject after = engine("state");
        QCOMPARE(after.value("dirty").toBool(), before.value("dirty").toBool());
        QVERIFY(!after.value("can_undo").toBool());
        QVERIFY(!w.isDirty());
    }

    void levelsTableEdits()
    {
        LevelsTable t(levels({{"L2", 3.0, 4}, {"L1", 0.0, 10}, {"L3", 6.0, 0}}));
        QCOMPARE(t.count(), 3);
        QCOMPARE(t.rows()[0].name, QString("L1")); // lowest first
        QCOMPARE(t.heightToNext(0), 3.0);
        QCOMPARE(t.heightToNext(2), -1.0);
        QVERIFY(!t.modified());
        // Height to next: every level above moves.
        t.setHeightToNext(0, 3.5);
        QCOMPARE(t.rows()[1].elevation, 3.5);
        QCOMPARE(t.rows()[2].elevation, 6.5);
        // Elevation: that level only, rows stay sorted.
        QCOMPARE(t.setElevation(2, 2.0), 1);
        QCOMPARE(t.rows()[1].name, QString("L3"));
        QCOMPARE(t.rows()[2].elevation, 3.5);
        QVERIFY(t.modified());
        // Insert above the top: 3 m up (no height to next there).
        QCOMPARE(t.insertAbove(2, "Roof"), 3);
        QCOMPARE(t.rows()[3].elevation, 6.5);
        // Insert below L1 (height 2 to L3): the new level takes L1's place, the rest go up 2 m.
        QCOMPARE(t.insertBelow(0, "Basement"), 0);
        QCOMPARE(t.rows()[0].elevation, 0.0);
        QCOMPARE(t.rows()[1].elevation, 2.0);
        QCOMPARE(t.rows()[4].elevation, 8.5);
        // Deleting a level with elements needs a choice.
        QVERIFY(!t.remove(1));                         // L1 has 10
        QVERIFY(t.remove(1, "move", t.neighbourFor(1))); // moved to... no saved level below: L3
        QCOMPARE(t.rows()[1].elements, 10);            // L3 holds them now
        QVERIFY(t.remove(t.count() - 1));              // Roof: new and empty
        const QJsonObject c = t.changes();
        QCOMPARE(c.value("levels").toArray().size(), 3);
        const QJsonObject d = c.value("deleted").toArray().at(0).toObject();
        QCOMPARE(d.value("guid").toString(), QString("g-L1"));
        QCOMPARE(d.value("elements").toString(), QString("move"));
        QCOMPARE(d.value("move_to").toString(), QString("g-L3"));
    }

    // Model > Levels... opens the table; OK applies it as one undo step.
    void theDialogEditsTheLevels()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.addLevel(QStringLiteral("Level 2"), 3.0));
        QAction* a = w.findChild<QAction*>(QStringLiteral("actionLevels"));
        QVERIFY(a);
        bool seen = false;
        QTimer::singleShot(0, &w, [&] {
            auto* d = qobject_cast<kimbim::LevelsDialog*>(QApplication::activeModalWidget());
            if (!d)
                return;
            seen = true;
            QVERIFY(d->findChild<QCheckBox*>(QStringLiteral("fitBetween"))); // D92
            QCOMPARE(d->grid()->rowCount(), 2);
            QCOMPARE(d->grid()->item(0, 0)->text(), QString("Level 2")); // highest first
            d->grid()->item(0, 0)->setText(QStringLiteral("Roof"));     // edit in place
            d->selectRow(1);
            d->insertAbove();
            QCOMPARE(d->table().count(), 3);
            d->accept();
        });
        a->trigger();
        QVERIFY(seen);
        const QJsonArray rows = engine("levels_table").value("levels").toArray();
        QCOMPARE(rows.size(), 3);
        QCOMPARE(rows.at(1).toObject().value("name").toString(), QString("Roof"));
        QCOMPARE(rows.at(2).toObject().value("elevation").toDouble(), 6.0); // 3 m above the top level
        QCOMPARE(w.levelsBar()->count(), 3);
        w.findChild<QAction*>(QStringLiteral("actionUndo"))->trigger(); // one step
        QCOMPARE(engine("levels_table").value("levels").toArray().size(), 2);
        QCOMPARE(w.levelsBar()->count(), 2);
    }
};

QTEST_MAIN(TestMeasureAndLevels)
#include "test_measure_and_levels.moc"
