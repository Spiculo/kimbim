// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QtTest>

#include "ModifyTool.h"

using kimbim::ModifyTool;

namespace {

void load(ModifyTool& tool)
{
    tool.setTolerance(0.1);
    const QJsonObject snap = QJsonDocument::fromJson(R"({"walls":[
        {"guid":"A","x1":0,"y1":0,"x2":10,"y2":0,"thickness":0.3},
        {"guid":"B","x1":5,"y1":-2,"x2":5,"y2":4,"thickness":0.2}],
        "grid":[{"guid":"G","tag":"1","x1":8,"y1":-5,"x2":8,"y2":5}]})").object();
    const QJsonObject beams = QJsonDocument::fromJson(
        R"({"beams":[{"guid":"M","x1":0,"y1":6,"x2":6,"y2":6,"width":0.2}]})").object();
    tool.setTargets(snap, beams);
    tool.snapper().setWalls(kimbim::Snapper::parse(snap));
}

} // namespace

class TestModifyTool : public QObject {
    Q_OBJECT
private slots:
    void splitWhereClickedOnTheAxis()
    {
        ModifyTool tool;
        load(tool);
        QSignalSpy split(&tool, &ModifyTool::splitRequested);
        tool.click({3.0, 0.12}); // on A's face: the split point is on its axis
        QCOMPARE(split.count(), 1);
        QCOMPARE(split.last().at(0).toString(), QString("A"));
        QCOMPARE(split.last().at(1).toPointF(), QPointF(3.0, 0.0));
        QVERIFY(split.last().at(2).toBool());
        tool.click({2.0, 6.0}, Qt::ControlModifier); // a beam, Ctrl: pieces unjoined
        QCOMPARE(split.last().at(0).toString(), QString("M"));
        QVERIFY(!split.last().at(2).toBool());
        tool.click({20.0, 20.0}); // nothing there
        QCOMPARE(split.count(), 2);
        tool.move({7.0, 0.0});
        QVERIFY(tool.splitPoint());
    }

    void trimToABoundaryKeepsItPicked()
    {
        ModifyTool tool;
        load(tool);
        tool.setMode(ModifyTool::Mode::Trim);
        QSignalSpy trim(&tool, &ModifyTool::trimRequested);
        tool.click({8.0, 3.0}); // the grid line is the boundary
        QCOMPARE(tool.stage(), 1);
        tool.click({9.0, 0.0}); // A, keep the east side
        QCOMPARE(trim.count(), 1);
        QCOMPARE(trim.last().at(0).toString(), QString("A"));
        QCOMPARE(trim.last().at(1).toPointF(), QPointF(9.0, 0.0));
        QCOMPARE(trim.last().at(2).toString(), QString()); // a line, not an element
        QCOMPARE(trim.last().at(3).toPointF(), QPointF(8, -5));
        tool.click({2.0, 6.0}); // and the beam, with the same boundary
        QCOMPARE(trim.count(), 2);
        QCOMPARE(trim.last().at(0).toString(), QString("M"));
        tool.cancel(); // Esc: a new boundary
        QCOMPARE(tool.stage(), 0);
        tool.click({5.0, 3.0}); // wall B as the boundary
        tool.click({1.0, 0.0});
        QCOMPARE(trim.last().at(2).toString(), QString("B"));
    }

    void cornerJoinAndUnjoinTakeTwoPicks()
    {
        ModifyTool tool;
        load(tool);
        tool.setMode(ModifyTool::Mode::Corner);
        QSignalSpy corner(&tool, &ModifyTool::cornerRequested);
        tool.click({1.0, 0.0});
        tool.click({1.0, 0.0}); // the same one again: ignored
        QCOMPARE(corner.count(), 0);
        tool.click({5.0, 3.0}, Qt::ControlModifier);
        QCOMPARE(corner.count(), 1);
        QCOMPARE(corner.last().at(0).toString(), QString("A"));
        QCOMPARE(corner.last().at(2).toString(), QString("B"));
        QVERIFY(!corner.last().at(4).toBool());
        QCOMPARE(tool.stage(), 0);
        tool.setMode(ModifyTool::Mode::Join);
        QSignalSpy join(&tool, &ModifyTool::joinRequested);
        tool.click({8.0, 2.0}); // a grid line is no element to join
        QCOMPARE(tool.stage(), 0);
        tool.click({1.0, 0.0});
        tool.click({5.0, 3.0});
        QCOMPARE(join.count(), 1);
        tool.setMode(ModifyTool::Mode::Unjoin);
        QSignalSpy unjoin(&tool, &ModifyTool::unjoinRequested);
        tool.click({1.0, 0.0});
        tool.click({5.0, 3.0});
        QCOMPARE(unjoin.count(), 1);
        QVERIFY(!tool.hint().isEmpty());
    }
};

QTEST_MAIN(TestModifyTool)
#include "test_modify_tool.moc"
