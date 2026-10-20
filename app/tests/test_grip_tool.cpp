// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QtTest>

#include "GripTool.h"

using kimbim::GripTool;

class TestGripTool : public QObject {
    Q_OBJECT
private slots:
    void grabAnEndAndDropItSomewhereElse()
    {
        GripTool tool;
        tool.setTolerance(0.1);
        tool.snapper().setWalls(kimbim::Snapper::parse(QJsonDocument::fromJson(
            R"({"walls":[{"guid":"A","x1":0,"y1":0,"x2":4,"y2":0,"thickness":0.2}]})").object()));
        QSignalSpy done(&tool, &GripTool::stretchRequested);
        tool.click({2, 0});        // not an end: nothing grabbed
        QVERIFY(!tool.isDragging());
        tool.click({3.96, 0.05});  // grabs A's end
        QVERIFY(tool.isDragging());
        tool.move({6, 0.02});      // 0 degree snap from the fixed end
        QCOMPARE(tool.preview()->second, QPointF(6, 0));
        tool.click({6, 0.02});
        QCOMPARE(done.count(), 1);
        QCOMPARE(done.last().at(0).toString(), QString("A"));
        QCOMPARE(done.last().at(1).toPointF(), QPointF(0, 0)); // the start stays
        QCOMPARE(done.last().at(2).toPointF(), QPointF(6, 0));
        QVERIFY(!tool.isDragging());
    }

    void grabbingTheStartMovesTheStart()
    {
        GripTool tool;
        tool.setTolerance(0.1);
        tool.snapper().setWalls(kimbim::Snapper::parse(QJsonDocument::fromJson(
            R"({"walls":[{"guid":"A","x1":0,"y1":0,"x2":4,"y2":0,"thickness":0.2}]})").object()));
        QSignalSpy done(&tool, &GripTool::stretchRequested);
        tool.click({0.02, 0.0});
        QVERIFY(tool.typeLength(5.0)); // the wall becomes 5 m long, from the fixed end
        QCOMPARE(done.last().at(1).toPointF(), QPointF(-1, 0));
        QCOMPARE(done.last().at(2).toPointF(), QPointF(4, 0));
    }
};

QTEST_MAIN(TestGripTool)
#include "test_grip_tool.moc"
