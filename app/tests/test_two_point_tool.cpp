// SPDX-License-Identifier: GPL-3.0-or-later
#include <QSignalSpy>
#include <QtTest>

#include "TwoPointTool.h"

using kimcad::TwoPointTool;

class TestTwoPointTool : public QObject {
    Q_OBJECT
private slots:
    void twoClicksMakeOneSegment()
    {
        TwoPointTool tool;
        tool.setTolerance(0.05);
        QSignalSpy done(&tool, &TwoPointTool::segmentFinished);
        tool.click({1, 1});
        QVERIFY(tool.isDrawing());
        tool.move({4, 1.03}); // snaps to 0 degrees from the first point
        QVERIFY(tool.preview());
        QCOMPARE(tool.preview()->second, QPointF(4, 1));
        tool.click({4, 1.03});
        QCOMPARE(done.count(), 1);
        QCOMPARE(done.last().at(0).toPointF(), QPointF(1, 1));
        QCOMPARE(done.last().at(1).toPointF(), QPointF(4, 1));
        QVERIFY(!tool.isDrawing()); // ready for the next segment
    }

    void sameSpotTwiceIsIgnoredAndCancelResets()
    {
        TwoPointTool tool;
        QSignalSpy done(&tool, &TwoPointTool::segmentFinished);
        tool.click({2, 2});
        tool.click({2.0001, 2});
        QCOMPARE(done.count(), 0);
        QVERIFY(tool.isDrawing());
        tool.cancel();
        QVERIFY(!tool.isDrawing());
        QVERIFY(!tool.preview());
    }

    void typedDistanceFollowsTheMouse()
    {
        TwoPointTool tool;
        QSignalSpy done(&tool, &TwoPointTool::segmentFinished);
        tool.click({0, 0});
        tool.move({0, 5});
        QVERIFY(tool.typeLength(2.5));
        QCOMPARE(done.count(), 1);
        QCOMPARE(done.last().at(1).toPointF(), QPointF(0, 2.5));
    }
};

QTEST_MAIN(TestTwoPointTool)
#include "test_two_point_tool.moc"
