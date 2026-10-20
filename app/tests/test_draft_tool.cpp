// SPDX-License-Identifier: GPL-3.0-or-later
// D84: the 2D drafting tools: DraftTool's clicks and typed values, then the main window drawing
// lines, arcs, rectangles and fills on the plan through the tools.
#include <QAction>
#include <QComboBox>
#include <QLineEdit>
#include <QSignalSpy>
#include <QSpinBox>
#include <QStandardPaths>
#include <QtTest>

#include <cmath>

#include "DraftTool.h"
#include "MainWindow.h"
#include "Viewport.h"

using kimbim::DraftTool;
using kimbim::MainWindow;

class TestDraftTool : public QObject {
    Q_OBJECT
private slots:
    void initTestCase()
    {
        QStandardPaths::setTestModeEnabled(true);
        qRegisterMetaType<QVector<QPointF>>();
    }

    void lineTakesTwoClicksOrATypedLength()
    {
        DraftTool tool;
        tool.setTolerance(0.01);
        QSignalSpy done(&tool, &DraftTool::shapeFinished);
        tool.click({0, 0});
        tool.click({3, 0});
        QCOMPARE(done.count(), 1);
        QCOMPARE(done.last().at(0).toString(), QStringLiteral("line"));
        QCOMPARE(done.last().at(1).value<QVector<QPointF>>().last(), QPointF(3, 0));
        QVERIFY(!tool.isDrawing());
        tool.click({0, 0});
        tool.move({1, 1}); // the direction: 45 degrees (an angle snap)
        QVERIFY(tool.typeInput(QStringLiteral("2")));
        const QPointF end = done.last().at(1).value<QVector<QPointF>>().last();
        QVERIFY(std::abs(end.x() - std::sqrt(2.0)) < 1e-9 && std::abs(end.y() - std::sqrt(2.0)) < 1e-9);
        tool.click({0, 0});
        QVERIFY(tool.typeInput(QStringLiteral("2<90"))); // length<angle
        QVERIFY(std::abs(done.last().at(1).value<QVector<QPointF>>().last().y() - 2) < 1e-9);
        QVERIFY(!tool.typeInput(QStringLiteral("abc")));
    }

    void polylineClosesOnItsStartOrEndsOpen()
    {
        DraftTool tool;
        tool.setMode(DraftTool::Mode::Polyline);
        tool.setTolerance(0.05);
        QSignalSpy done(&tool, &DraftTool::shapeFinished);
        for (const QPointF p : {QPointF(0, 0), QPointF(4, 0), QPointF(4, 3), QPointF(0.01, 0.02)})
            tool.click(p);
        QCOMPARE(done.count(), 1);
        QCOMPARE(done.last().at(2).toBool(), true); // closed
        QCOMPARE(done.last().at(1).value<QVector<QPointF>>().size(), 3);
        tool.click({0, 0});
        tool.click({2, 0});
        tool.escape(); // Esc ends it open, like the wall tool
        QCOMPARE(done.count(), 2);
        QCOMPARE(done.last().at(2).toBool(), false);
        tool.click({0, 0});
        tool.escape(); // one point: dropped
        QCOMPARE(done.count(), 2);
    }

    void rectangleCircleAndArcs()
    {
        DraftTool tool;
        tool.setTolerance(0.01);
        QSignalSpy done(&tool, &DraftTool::shapeFinished);
        tool.setMode(DraftTool::Mode::Rectangle);
        tool.click({1, 1});
        tool.move({0, 0});
        QVERIFY(tool.typeInput(QStringLiteral("3;2"))); // towards the mouse: down and left
        QCOMPARE(done.last().at(0).toString(), QStringLiteral("rectangle"));
        QCOMPARE(done.last().at(1).value<QVector<QPointF>>().last(), QPointF(-2, -1));
        tool.setMode(DraftTool::Mode::Circle);
        tool.click({5, 5});
        QVERIFY(tool.typeInput(QStringLiteral("1.5"))); // the radius
        const auto circle = done.last().at(1).value<QVector<QPointF>>();
        QCOMPARE(done.last().at(0).toString(), QStringLiteral("circle"));
        QVERIFY(std::abs(std::hypot(circle[1].x() - 5, circle[1].y() - 5) - 1.5) < 1e-9);
        tool.setMode(DraftTool::Mode::Arc3);
        QSignalSpy rejected(&tool, &DraftTool::rejected);
        for (const QPointF p : {QPointF(0, 0), QPointF(1, 0), QPointF(2, 0)})
            tool.click(p);
        QCOMPARE(rejected.count(), 1); // three points in a line
        for (const QPointF p : {QPointF(0, 0), QPointF(1, 1), QPointF(2, 0)})
            tool.click(p);
        QCOMPARE(done.last().at(0).toString(), QStringLiteral("arc"));
        tool.setMode(DraftTool::Mode::ArcCentre);
        tool.click({0, 0});
        tool.click({1, 0});
        QVERIFY(tool.typeInput(QStringLiteral("90"))); // a quarter, counter-clockwise
        const auto arc = done.last().at(1).value<QVector<QPointF>>();
        QVERIFY(std::abs(arc[2].x()) < 1e-9 && std::abs(arc[2].y() - 1) < 1e-9);
        QVERIFY(std::abs(arc[1].x() - std::sqrt(0.5)) < 1e-9); // through the middle of the quarter
    }

    void fillRefusesACrossingOutline()
    {
        DraftTool tool;
        tool.setMode(DraftTool::Mode::Fill);
        tool.setTolerance(0.01);
        QSignalSpy done(&tool, &DraftTool::shapeFinished);
        QSignalSpy rejected(&tool, &DraftTool::rejected);
        for (const QPointF p : {QPointF(0, 0), QPointF(2, 2), QPointF(2, 0), QPointF(0, 2)})
            tool.click(p);
        tool.finish();
        QCOMPARE(rejected.count(), 1);
        for (const QPointF p : {QPointF(0, 0), QPointF(2, 0), QPointF(2, 2)})
            tool.click(p);
        tool.finish(); // Enter closes a fill
        QCOMPARE(done.count(), 1);
        QCOMPARE(done.last().at(0).toString(), QStringLiteral("fill"));
    }

    void snapsToDraftingPoints()
    {
        kimbim::Snapper s;
        s.setGrid(0.5);
        s.setPoints({{QPointF(1.23, 4.56), kimbim::Snap::Endpoint, {}}, {QPointF(3.01, 3.01), kimbim::Snap::Centre, {}}});
        QCOMPARE(s.snap(QPointF(1.25, 4.55), 0.1).point, QPointF(1.23, 4.56));
        QCOMPARE(s.snap(QPointF(1.25, 4.55), 0.1).kind, kimbim::Snap::Endpoint);
        QCOMPARE(s.snap(QPointF(3.05, 3.0), 0.1).kind, kimbim::Snap::Centre);
        QCOMPARE(s.snap(QPointF(2.1, 2.1), 0.1).kind, kimbim::Snap::Grid);
    }

    void windowDrawsShapesThroughTheTools()
    {
        MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.findChild<QAction*>(QStringLiteral("actionPlanView"))->trigger(); // P: the plan tab
        kimbim::Viewport* v = w.viewport();
        const int before = v->annotationCount();
        w.setTool(MainWindow::Tool::Line);
        emit v->workPointClicked(QPointF(0, 0), 0.01, Qt::NoModifier);
        emit v->workPointClicked(QPointF(4, 0), 0.01, Qt::NoModifier);
        QCOMPARE(w.viewport()->draftingCount(), 1);
        // A typed length: the options bar's field.
        emit w.viewport()->workPointClicked(QPointF(0, 1), 0.01, Qt::NoModifier);
        emit w.viewport()->workPointMoved(QPointF(1, 1), 0.01, Qt::NoModifier);
        auto* length = w.findChild<QLineEdit*>(QStringLiteral("lengthInput"));
        QVERIFY(length && length->isVisibleTo(&w));
        length->setText(QStringLiteral("2.5"));
        emit length->returnPressed();
        QCOMPARE(w.viewport()->draftingCount(), 2);

        w.setTool(MainWindow::Tool::Rectangle);
        emit w.viewport()->workPointClicked(QPointF(10, 0), 0.01, Qt::NoModifier);
        emit w.viewport()->workPointClicked(QPointF(13, 2), 0.01, Qt::NoModifier);
        QCOMPARE(w.viewport()->draftingCount(), 3);

        w.setTool(MainWindow::Tool::ArcCircle);
        auto* mode = w.findChild<QComboBox*>(QStringLiteral("draftArcMode"));
        QVERIFY(mode && mode->isVisibleTo(&w));
        mode->setCurrentIndex(1); // three points
        for (const QPointF p : {QPointF(0, 5), QPointF(1, 6), QPointF(2, 5)})
            emit w.viewport()->workPointClicked(p, 0.01, Qt::NoModifier);
        QCOMPARE(w.viewport()->draftingCount(), 4);

        // A fill with a pattern and a background pen; then Alt+click fills the rectangle.
        w.setTool(MainWindow::Tool::Fill);
        auto* pattern = w.findChild<QComboBox*>(QStringLiteral("draftPattern"));
        QVERIFY(pattern && pattern->findText(QStringLiteral("Brick")) >= 0);
        pattern->setCurrentText(QStringLiteral("Brick"));
        w.findChild<QSpinBox*>(QStringLiteral("draftBackground"))->setValue(5);
        for (const QPointF p : {QPointF(0, -5), QPointF(4, -5), QPointF(4, -2), QPointF(0, -2), QPointF(0, -5)})
            emit w.viewport()->workPointClicked(p, 0.01, Qt::NoModifier);
        QCOMPARE(w.viewport()->draftingCount(), 5);
        emit w.viewport()->workPointClicked(QPointF(11, 1), 0.01, Qt::AltModifier);
        QCOMPARE(w.viewport()->draftingCount(), 6);
        w.setTool(MainWindow::Tool::None);
        QCOMPARE(v->annotationCount() - before, 6);

        // Snaps: a line's end snaps the next shape.
        w.setTool(MainWindow::Tool::Line);
        emit w.viewport()->workPointClicked(QPointF(4.02, 0.03), 0.1, Qt::NoModifier); // the first line's end
        emit w.viewport()->workPointClicked(QPointF(8, 0), 0.1, Qt::NoModifier);
        w.setTool(MainWindow::Tool::None);
        QCOMPARE(w.viewport()->draftingCount(), 7);

        const QString snapped = w.viewport()->annotationGuids().last();
        QCOMPARE(w.viewport()->annotationPoints(snapped).first(), QPointF(4, 0)); // exactly on the end

        // Grips: the Stretch tool picks up that line's far end and puts it down elsewhere.
        w.setTool(MainWindow::Tool::Stretch);
        emit w.viewport()->workPointClicked(QPointF(8.02, 0.01), 0.1, Qt::NoModifier);
        QVERIFY(w.draftGripActive());
        emit w.viewport()->workPointClicked(QPointF(8, 2), 0.001, Qt::NoModifier);
        QVERIFY(!w.draftGripActive());
        w.setTool(MainWindow::Tool::None);
        QCOMPARE(w.viewport()->annotationPoints(snapped).last(), QPointF(8, 2));

        // Drafting is selectable and deletable like any annotation; undo brings it back.
        const QStringList guids = w.viewport()->annotationGuids();
        const QString last = guids.last();
        QCOMPARE(w.viewport()->typeOf(last), QStringLiteral("IfcAnnotation"));
        w.setSelection({last});
        QVERIFY(w.deleteSelection());
        QCOMPARE(w.viewport()->draftingCount(), 6);
        w.findChild<QAction*>(QStringLiteral("actionUndo"))->trigger();
        QCOMPARE(w.viewport()->draftingCount(), 7);
        // Not in 3D: drafting belongs to the plan.
        QVERIFY(w.viewport()->isPlanView());
        w.viewport()->set3DView();
        QCOMPARE(w.viewport()->draftingCount(), 0);
    }
};

QTEST_MAIN(TestDraftTool)
#include "test_draft_tool.moc"
