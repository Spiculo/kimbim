// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QtTest>

#include "WallTool.h"

using kimbim::WallSegment;
using kimbim::WallTool;


namespace {

WallSegment segment(const QSignalSpy& spy, int i)
{
    return spy.at(i).at(0).value<WallSegment>();
}

} // namespace

class TestWallTool : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { qRegisterMetaType<WallSegment>(); }

    void clicksMakeAChainedPolyline()
    {
        WallTool tool;
        tool.setTolerance(0.05);
        QSignalSpy walls(&tool, &WallTool::wallRequested);
        int n = 0;
        // The app answers every request with the created wall's guid.
        connect(&tool, &WallTool::wallRequested, &tool, [&](const WallSegment&) { tool.setLastWall(QString("W%1").arg(n++)); });
        tool.click(QPointF(0, 0));
        QVERIFY(tool.isDrawing());
        QCOMPARE(walls.count(), 0);
        tool.click(QPointF(5, 0));
        tool.click(QPointF(5, 4));
        QCOMPARE(walls.count(), 2);
        QCOMPARE(segment(walls, 0).p1, QPointF(0, 0));
        QCOMPARE(segment(walls, 0).p2, QPointF(5, 0));
        QVERIFY(segment(walls, 0).joinStart.isEmpty());
        QCOMPARE(segment(walls, 1).p1, QPointF(5, 0));
        QCOMPARE(segment(walls, 1).joinStart, QString("W0")); // continues from the previous wall
        tool.finish();
        QVERIFY(!tool.isDrawing());
        QVERIFY(!tool.preview());
    }

    void startingOrEndingOnAWallJoinsIt()
    {
        WallTool tool;
        tool.setTolerance(0.1);
        tool.snapper().setWalls(kimbim::Snapper::parse(QJsonDocument::fromJson(
            R"({"walls":[{"guid":"A","x1":0,"y1":0,"x2":4,"y2":0,"thickness":0.2}]})").object()));
        QSignalSpy walls(&tool, &WallTool::wallRequested);
        tool.click(QPointF(4.02, 0.03));  // at A's end
        tool.click(QPointF(4.0, 3.0));
        QCOMPARE(segment(walls, 0).p1, QPointF(4, 0));
        QCOMPARE(segment(walls, 0).joinStart, QString("A"));
        tool.cancel();
        tool.click(QPointF(1.5, 3.0));
        tool.click(QPointF(1.5, 0.05)); // onto A's middle part -> T
        QCOMPARE(segment(walls, 1).joinEnd, QString("A"));
        QCOMPARE(segment(walls, 1).p2, QPointF(1.5, 0));
    }

    void typedLengthFollowsTheMouseDirection()
    {
        WallTool tool;
        tool.setTolerance(0.01);
        QSignalSpy walls(&tool, &WallTool::wallRequested);
        QVERIFY(!tool.typeLength(2.0)); // nothing started
        tool.click(QPointF(1, 1));
        QVERIFY(!tool.typeLength(2.0)); // no direction yet
        tool.move(QPointF(1, 3.7));     // pointing +Y
        QVERIFY(tool.typeLength(2.5));
        QCOMPARE(walls.count(), 1);
        QVERIFY(qFuzzyCompare(segment(walls, 0).p2.y(), 3.5));
        QVERIFY(qAbs(segment(walls, 0).p2.x() - 1.0) < 1e-9);
        QVERIFY(tool.isDrawing()); // the chain continues from the new end
        QVERIFY(!tool.typeLength(0.0));
    }

    void zeroLengthClicksAreIgnoredAndPreviewFollows()
    {
        WallTool tool;
        tool.setTolerance(0.05);
        QSignalSpy walls(&tool, &WallTool::wallRequested);
        tool.click(QPointF(2, 2));
        tool.click(QPointF(2.0001, 2)); // same point (double click)
        QCOMPARE(walls.count(), 0);
        tool.move(QPointF(3, 2));
        QVERIFY(tool.preview());
        QCOMPARE(tool.preview()->second, QPointF(3, 2));
    }

    void cancelEmitsFinished()
    {
        WallTool tool;
        QSignalSpy finished(&tool, &WallTool::finished);
        tool.click(QPointF(0, 0));
        tool.cancel();
        QCOMPARE(finished.count(), 1);
        QVERIFY(!tool.isDrawing());
    }
};

QTEST_MAIN(TestWallTool)
#include "test_wall_tool.moc"
