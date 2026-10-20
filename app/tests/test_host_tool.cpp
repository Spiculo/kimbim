// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QtTest>

#include "HostTool.h"

#include <cmath>

using kimbim::Host;
using kimbim::HostTool;

namespace {

QVector<kimbim::SnapWall> walls()
{
    return kimbim::Snapper::parse(QJsonDocument::fromJson(R"({"walls":[
        {"guid":"A","x1":0,"y1":0,"x2":4,"y2":0,"thickness":0.3},
        {"guid":"B","x1":4,"y1":0,"x2":4,"y2":3,"thickness":0.3},
        {"guid":"C","x1":10,"y1":0,"x2":10.5,"y2":0,"thickness":0.2}]})").object());
}

} // namespace

class TestHostTool : public QObject {
    Q_OBJECT
private slots:
    void findsTheWallAndThePositionAlongIt()
    {
        const auto host = HostTool::locate(walls(), QPointF(1.0, 0.1), 0.9, 0.05);
        QVERIFY(host);
        QCOMPARE(host->wallGuid, QString("A"));
        QVERIFY(std::abs(host->along - 1.0) < 1e-9);
        QVERIFY(std::abs(host->centre.y()) < 1e-9);
        QVERIFY(std::abs(host->angle) < 1e-9);
        const auto onB = HostTool::locate(walls(), QPointF(4.12, 1.5), 0.9, 0.05);
        QVERIFY(onB && onB->wallGuid == "B");
        QVERIFY(std::abs(onB->angle - M_PI / 2) < 1e-9);
    }

    void openingsStayInsideTheWall()
    {
        const auto nearStart = HostTool::locate(walls(), QPointF(0.1, 0.0), 0.9, 0.05);
        QVERIFY(nearStart);
        QVERIFY(std::abs(nearStart->along - 0.45) < 1e-9);
        const auto nearEnd = HostTool::locate(walls(), QPointF(3.99, -0.1), 0.9, 0.05);
        QVERIFY(nearEnd);
        QVERIFY(std::abs(nearEnd->along - 3.55) < 1e-9);
    }

    void awayFromWallsOrTooShortGivesNothing()
    {
        QVERIFY(!HostTool::locate(walls(), QPointF(2.0, 0.5), 0.9, 0.05));    // off the wall
        QVERIFY(!HostTool::locate(walls(), QPointF(10.2, 0.0), 0.9, 0.05));   // wall C is 0.5 m long
    }

    void clickRequestsAnOpening()
    {
        HostTool tool;
        tool.setWalls(walls());
        tool.setWidth(0.9);
        tool.setTolerance(0.05);
        QSignalSpy requested(&tool, &HostTool::openingRequested);
        tool.click(QPointF(2.0, 3.0)); // nowhere
        QCOMPARE(requested.count(), 0);
        QVERIFY(!tool.move(QPointF(2.0, 3.0)));
        QVERIFY(tool.move(QPointF(2.0, 0.05)));
        tool.click(QPointF(2.0, 0.05));
        QCOMPARE(requested.count(), 1);
        const Host h = requested.last().at(0).value<Host>();
        QCOMPARE(h.wallGuid, QString("A"));
    }
};

QTEST_MAIN(TestHostTool)
#include "test_host_tool.moc"
