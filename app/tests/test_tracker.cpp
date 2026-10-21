// SPDX-License-Identifier: GPL-3.0-or-later
// D89: the tracker and temporary guides in the window, with typed keys sent to the view.
#include <QAction>
#include <QLineEdit>
#include <QSignalSpy>
#include <QtTest>

#include <cmath>

#include "InputAidsController.h"
#include "MainWindow.h"
#include "TwoPointTool.h"
#include "Viewport.h"
#include "WallTool.h"

using kimbim::MainWindow;
using kimbim::Tracker;
using kimbim::WallSegment;

namespace {

bool samePoint(const QPointF& a, const QPointF& b, double eps = 1e-9)
{
    return std::hypot(a.x() - b.x(), a.y() - b.y()) <= eps;
}

WallSegment segment(const QSignalSpy& spy, int i)
{
    return spy.at(i).at(0).value<WallSegment>();
}

} // namespace

class TestTracker : public QObject {
    Q_OBJECT
private slots:
    void typedValuesPlaceWallEnds()
    {
        MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.findChild<QAction*>(QStringLiteral("actionPlanView"))->trigger();
        kimbim::Viewport* v = w.viewport();
        w.setTool(MainWindow::Tool::Wall);
        QSignalSpy walls(w.wallTool(), &kimbim::WallTool::wallRequested);
        Tracker& t = w.inputAids()->tracker();

        emit v->workPointClicked(QPointF(1, 1), 0.01, Qt::NoModifier);
        emit v->workPointMoved(QPointF(4, 1.3), 0.01, Qt::NoModifier);
        QVERIFY(t.anchor() && samePoint(*t.anchor(), QPointF(1, 1)));
        QVERIFY(w.inputAids()->trackerShown());
        QVERIFY(v->hasAidOverlay(kimbim::Viewport::AidOverlay::Tracker));
        QCOMPARE(t.focus(), Tracker::Length);
        QVERIFY(std::abs(t.live(Tracker::Length) - std::hypot(3.0, 0.3)) < 0.02);

        // Length and angle ("4<90"): the angle locks the preview at once, Enter places the end.
        QTest::keyClicks(v, QStringLiteral("4<90"));
        QCOMPARE(t.typed(Tracker::Length), QStringLiteral("4"));
        QCOMPARE(t.typed(Tracker::Angle), QStringLiteral("90"));
        QVERIFY(w.wallTool()->preview() && samePoint(w.wallTool()->preview()->second, QPointF(1, 5)));
        QTest::keyClick(v, Qt::Key_Return);
        QCOMPARE(walls.count(), 1);
        QVERIFY(samePoint(segment(walls, 0).p1, QPointF(1, 1)));
        QVERIFY(samePoint(segment(walls, 0).p2, QPointF(1, 5)));
        QVERIFY(!t.hasInput());

        // Tab moves length -> angle -> dx -> dy; relative x/y from the last point.
        emit v->workPointMoved(QPointF(3, 6), 0.01, Qt::NoModifier);
        QVERIFY(samePoint(*t.anchor(), QPointF(1, 5)));
        QTest::keyClick(v, Qt::Key_Tab);
        QCOMPARE(t.focus(), Tracker::Angle);
        QTest::keyClick(v, Qt::Key_Tab);
        QCOMPARE(t.focus(), Tracker::X);
        QTest::keyClicks(v, QStringLiteral("3"));
        QTest::keyClick(v, Qt::Key_Tab);
        QCOMPARE(t.focus(), Tracker::Y);
        QTest::keyClicks(v, QStringLiteral("-2"));
        QTest::keyClick(v, Qt::Key_Return);
        QCOMPARE(walls.count(), 2);
        QVERIFY(samePoint(segment(walls, 1).p1, QPointF(1, 5)));
        QVERIFY(samePoint(segment(walls, 1).p2, QPointF(4, 3)));

        // Absolute coordinates: '#' then x ; y.
        emit v->workPointMoved(QPointF(5, 5), 0.01, Qt::NoModifier);
        QTest::keyClicks(v, QStringLiteral("#10;20"));
        QVERIFY(t.absolute());
        QTest::keyClick(v, Qt::Key_Return);
        QCOMPARE(walls.count(), 3);
        QVERIFY(samePoint(segment(walls, 2).p2, QPointF(10, 20)));

        // A lone length is the classic typed length: along the mouse.
        emit v->workPointMoved(QPointF(10, 25), 0.01, Qt::NoModifier);
        QTest::keyClicks(v, QStringLiteral("2.5"));
        QTest::keyClick(v, Qt::Key_Return);
        QCOMPARE(walls.count(), 4);
        QVERIFY(samePoint(segment(walls, 3).p2, QPointF(10, 22.5), 1e-9));
        // Backspace and Esc edit the typed value without ending the wall.
        QTest::keyClicks(v, QStringLiteral("12"));
        QTest::keyClick(v, Qt::Key_Backspace);
        QCOMPARE(t.typed(Tracker::Length), QStringLiteral("1"));
        QTest::keyClick(v, Qt::Key_Escape);
        QVERIFY(!t.hasInput());
        QVERIFY(w.wallTool()->isDrawing());
        // The options bar's length field still works (it is what a lone typed length goes through).
        auto* length = w.findChild<QLineEdit*>(QStringLiteral("lengthInput"));
        QVERIFY(length && !length->isHidden());
    }

    // D92: angles from east, from the previous segment or from north; typed lengths in metres or
    // the project unit.
    void angleModesAndTypedLengthUnits()
    {
        Tracker t;
        t.setAnchor(QPointF(0, 0));
        t.setCursor(QPointF(1, 1));
        QCOMPARE(t.live(Tracker::Angle), 45.0);
        t.setAngleMode(Tracker::Bearing);
        t.setCursor(QPointF(0, 1));
        QCOMPARE(t.live(Tracker::Angle), 0.0);
        t.setCursor(QPointF(1, 0));
        QCOMPARE(t.live(Tracker::Angle), 90.0);
        t.setAngleMode(Tracker::RelativeAngle);
        t.setReferenceAngle(3.14159265358979323846 / 2); // the previous segment went north
        QCOMPARE(t.live(Tracker::Angle), 270.0);         // east is -90 from north
        t.type(QStringLiteral("2<0")); // 0 relative to the north-going segment: north again
        const auto target = t.target();
        QVERIFY(target);
        QCOMPARE(target->x(), 0.0);
        QCOMPARE(target->y(), 2.0);

        Tracker u;
        u.setAnchor(QPointF(0, 0));
        u.setCursor(QPointF(1, 0));
        u.setLengthFactor(0.01); // centimetres
        u.type(QStringLiteral("250"));
        QCOMPARE(u.live(Tracker::Length), 100.0); // the mouse is 1 m away: 100 cm
        const auto end = u.target();
        QVERIFY(end);
        QCOMPARE(end->x(), 2.5);
        QCOMPARE(end->y(), 0.0);
    }

    void trackerModesAndTypedLengthUnitPreferences()
    {
        MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.findChild<QAction*>(QStringLiteral("actionPlanView"))->trigger();
        kimbim::Viewport* v = w.viewport();
        w.setTool(MainWindow::Tool::Wall);
        QSignalSpy walls(w.wallTool(), &kimbim::WallTool::wallRequested);

        w.preferences().setValue(QStringLiteral("tracker"), QStringLiteral("typing"));
        emit v->workPointClicked(QPointF(0, 0), 0.01, Qt::NoModifier);
        emit v->workPointMoved(QPointF(0, 3), 0.01, Qt::NoModifier);
        QVERIFY(!w.inputAids()->trackerShown()); // nothing typed yet
        QTest::keyClicks(v, QStringLiteral("250"));
        QVERIFY(w.inputAids()->trackerShown());

        w.preferences().setValue(QStringLiteral("typed_length_unit"), QStringLiteral("project"));
        QVERIFY(w.setProjectSettings({{"length_unit", "cm"}}));
        QTest::keyClick(v, Qt::Key_Return);
        QCOMPARE(walls.count(), 1);
        QVERIFY(samePoint(segment(walls, 0).p2, QPointF(0, 2.5))); // 250 cm along the mouse

        // Off: no tracker, and digits go to the options bar's length field as before.
        w.preferences().setValue(QStringLiteral("tracker"), QStringLiteral("off"));
        emit v->workPointMoved(QPointF(2, 2.5), 0.01, Qt::NoModifier);
        emit v->workPointMoved(QPointF(3, 2.5), 0.01, Qt::NoModifier);
        QVERIFY(!w.inputAids()->trackerShown());
        QTest::keyClicks(v, QStringLiteral("1"));
        auto* length = w.findChild<QLineEdit*>(QStringLiteral("lengthInput"));
        QVERIFY(length && length->text() == QStringLiteral("1"));
    }

    void guideAcquiredThenExtensionLineGivesTheExactCoordinate()
    {
        MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.findChild<QAction*>(QStringLiteral("actionPlanView"))->trigger();
        kimbim::Viewport* v = w.viewport();
        w.setTool(MainWindow::Tool::Wall);
        QSignalSpy walls(w.wallTool(), &kimbim::WallTool::wallRequested);
        emit v->workPointClicked(QPointF(0, 0), 0.01, Qt::NoModifier);
        emit v->workPointClicked(QPointF(4, 3), 0.01, Qt::NoModifier);
        QCOMPARE(walls.count(), 1);
        emit v->drawingEnded(); // Esc: the chain ends
        const auto& aids = w.inputAids()->aids();
        QVERIFY(aids->guides().isEmpty());

        // A new wall from (20, 0); rest on the first wall's end (4, 3) for half a second.
        emit v->workPointClicked(QPointF(20, 0), 0.05, Qt::NoModifier);
        emit v->workPointMoved(QPointF(4.01, 3.02), 0.1, Qt::NoModifier);
        QVERIFY(aids->hovered().has_value());
        QTRY_COMPARE_WITH_TIMEOUT(aids->guides().size(), 1, 3000);
        QVERIFY(samePoint(aids->guides().first().at, QPointF(4, 3)));
        QVERIFY(v->hasAidOverlay(kimbim::Viewport::AidOverlay::Guides));

        // Along the horizontal through (4, 3), far away: y is exactly 3.
        emit v->workPointMoved(QPointF(15.004, 3.03), 0.1, Qt::NoModifier);
        QVERIFY(samePoint(w.wallTool()->preview()->second, QPointF(15, 3)));
        QCOMPARE(aids->lastKind(), int(kimbim::Snap::GuideLine));
        emit v->workPointClicked(QPointF(15.004, 3.03), 0.1, Qt::NoModifier);
        QCOMPARE(walls.count(), 2);
        QCOMPARE(segment(walls, 1).p2.y(), 3.0);
        QVERIFY(samePoint(segment(walls, 1).p2, QPointF(15, 3)));

        // The toggle clears and stops guides; changing tools clears them too.
        QAction* toggle = w.findChild<QAction*>(QStringLiteral("actionGuides"));
        QVERIFY(toggle && toggle->isChecked());
        toggle->setChecked(false);
        QVERIFY(aids->guides().isEmpty());
        toggle->setChecked(true);
        aids->acquire({QPointF(1, 1), std::nullopt});
        w.setTool(MainWindow::Tool::None);
        QVERIFY(aids->guides().isEmpty());
        QVERIFY(!v->hasAidOverlay(kimbim::Viewport::AidOverlay::Tracker));
    }

    void everyPointToolTakesTypedPoints()
    {
        MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.findChild<QAction*>(QStringLiteral("actionPlanView"))->trigger();
        kimbim::Viewport* v = w.viewport();
        w.setTool(MainWindow::Tool::Beam);
        QSignalSpy segments(w.twoPointTool(), &kimbim::TwoPointTool::segmentFinished);
        emit v->workPointMoved(QPointF(7, 7), 0.05, Qt::NoModifier);
        Tracker& t = w.inputAids()->tracker();
        QVERIFY(!t.anchor());
        QCOMPARE(t.fields(), QVector<Tracker::Field>({Tracker::X, Tracker::Y})); // the first point: x, y
        QTest::keyClicks(v, QStringLiteral("2"));
        QTest::keyClick(v, Qt::Key_Tab);
        QTest::keyClicks(v, QStringLiteral("3"));
        QTest::keyClick(v, Qt::Key_Return);
        QVERIFY(w.twoPointTool()->start() && samePoint(*w.twoPointTool()->start(), QPointF(2, 3)));
        emit v->workPointMoved(QPointF(5, 3.2), 0.05, Qt::NoModifier);
        QTest::keyClicks(v, QStringLiteral("4<0"));
        QTest::keyClick(v, Qt::Key_Return);
        QCOMPARE(segments.count(), 1);
        QVERIFY(samePoint(segments.at(0).at(0).toPointF(), QPointF(2, 3)));
        QVERIFY(samePoint(segments.at(0).at(1).toPointF(), QPointF(6, 3)));

        // Not for tools that pick elements: digits are not taken there.
        w.setTool(MainWindow::Tool::Room);
        emit v->workPointMoved(QPointF(1, 1), 0.05, Qt::NoModifier);
        QVERIFY(!w.inputAids()->trackerShown());
    }
};

QTEST_MAIN(TestTracker)
#include "test_tracker.moc"
