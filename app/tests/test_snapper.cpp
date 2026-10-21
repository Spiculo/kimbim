// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonDocument>
#include <QJsonObject>
#include <QtTest>

#include "Snapper.h"

#include <cmath>

using kimbim::Snap;
using kimbim::Snapper;

namespace {

Snapper withWalls()
{
    Snapper s;
    s.setWalls(Snapper::parse(QJsonDocument::fromJson(R"({"walls":[
        {"guid":"A","x1":0,"y1":0,"x2":4,"y2":0,"thickness":0.2},
        {"guid":"B","x1":4,"y1":0,"x2":4,"y2":3,"thickness":0.2}]})").object()));
    return s;
}

bool near(const QPointF& a, const QPointF& b, double eps = 1e-9)
{
    return std::hypot(a.x() - b.x(), a.y() - b.y()) <= eps;
}

} // namespace

class TestSnapper : public QObject {
    Q_OBJECT
private slots:
    void endpointWinsOverEverything()
    {
        const Snapper s = withWalls();
        const Snap snap = s.snap(QPointF(3.95, 0.04), 0.1);
        QCOMPARE(snap.kind, Snap::Endpoint);
        QVERIFY(near(snap.point, QPointF(4, 0)));
        QVERIFY(snap.wallGuid == "A" || snap.wallGuid == "B");
    }

    void midpointThenOnWall()
    {
        const Snapper s = withWalls();
        Snap mid = s.snap(QPointF(2.03, 0.05), 0.1);
        QCOMPARE(mid.kind, Snap::Midpoint);
        QVERIFY(near(mid.point, QPointF(2, 0)));
        QCOMPARE(mid.wallGuid, QString("A"));
        Snap on = s.snap(QPointF(1.0, 0.06), 0.1);
        QCOMPARE(on.kind, Snap::OnWall);
        QVERIFY(near(on.point, QPointF(1.0, 0.0)));
        QCOMPARE(on.wallGuid, QString("A"));
    }

    void perpendicularFromTheStartPoint()
    {
        const Snapper s = withWalls();
        const QPointF from(1.0, 2.0);
        // Near wall A but not at its middle/end: the foot of the perpendicular from `from` wins.
        const Snap snap = s.snap(QPointF(1.05, 0.07), 0.1, &from);
        QCOMPARE(snap.kind, Snap::Perpendicular);
        QVERIFY(near(snap.point, QPointF(1.0, 0.0)));
        QCOMPARE(snap.wallGuid, QString("A"));
    }

    void freePointsSnapToTheGrid()
    {
        Snapper s;
        s.setGrid(0.01);
        const Snap snap = s.snap(QPointF(1.23456, -0.0049), 0.1);
        QCOMPARE(snap.kind, Snap::Grid);
        QVERIFY(near(snap.point, QPointF(1.23, 0.0), 1e-9));
        QVERIFY(snap.wallGuid.isEmpty());
    }

    // D98: with grid snap on, free points land on the construction grid's nodes, also when it is turned.
    void gridSnapUsesTheConstructionGrid()
    {
        Snapper s;
        s.setSnapGrid(QPointF(0, 0), 0.0, 0.5);
        QVERIFY(near(s.snap(QPointF(1.3, 0.8), 0.01).point, QPointF(1.5, 1.0)));
        const QPointF from(0, 0); // no 15 degree steps: the node nearest the cursor
        const Snap angled = s.snap(QPointF(2.2, 0.31), 0.01, &from);
        QCOMPARE(angled.kind, Snap::Grid);
        QVERIFY(near(angled.point, QPointF(2.0, 0.5)));
        s.setSnapGrid(QPointF(1, 1), M_PI / 4, 1.0);
        const QPointF node = QPointF(1, 1) + QPointF(std::cos(M_PI / 4), std::sin(M_PI / 4)) * 2.0;
        QVERIFY(near(s.snap(node + QPointF(0.1, -0.05), 0.01).point, node, 1e-9));
        s.setSnapGrid(QPointF(0, 0), 0.0, 0.0); // off: the 10 mm grid again
        QVERIFY(near(s.snap(QPointF(1.234, 0.0), 0.001).point, QPointF(1.23, 0.0)));
        // object snaps still win
        Snapper w = withWalls();
        w.setSnapGrid(QPointF(0, 0), 0.0, 1.0);
        QCOMPARE(w.snap(QPointF(3.98, 0.02), 0.1).kind, Snap::Endpoint);
    }

    // D98: Archicad's special snap points: divisions of a wall and a distance from its ends.
    void specialSnapPoints()
    {
        Snapper s = withWalls(); // A: (0,0)-(4,0)
        QVERIFY(s.snap(QPointF(1.0, 0.05), 0.1).kind != Snap::Division); // off by default
        s.setSpecialPoints(4, 0.0);
        Snap d = s.snap(QPointF(1.03, 0.05), 0.1);
        QCOMPARE(d.kind, Snap::Division);
        QVERIFY(near(d.point, QPointF(1.0, 0.0)));
        QCOMPARE(d.wallGuid, QStringLiteral("A"));
        QCOMPARE(s.snap(QPointF(2.02, 0.0), 0.1).kind, Snap::Midpoint); // the middle stays a midpoint
        s.setSpecialPoints(0, 0.6);
        d = s.snap(QPointF(3.38, 0.02), 0.1);
        QCOMPARE(d.kind, Snap::Division);
        QVERIFY(near(d.point, QPointF(3.4, 0.0)));
        QVERIFY(near(s.snap(QPointF(0.62, 0.0), 0.1).point, QPointF(0.6, 0.0)));
        QCOMPARE(s.snap(QPointF(3.98, 0.02), 0.1).kind, Snap::Endpoint); // ends still win
    }

    void anglesSnapTo15DegreesAndOrthoForcesRightAngles()
    {
        Snapper s;
        s.setGrid(0.01);
        const QPointF from(0, 0);
        // 31 degrees, 2 m long -> 30 degrees, length on the grid.
        const double a = 31.0 * M_PI / 180.0;
        const Snap snap = s.snap(QPointF(2 * std::cos(a), 2 * std::sin(a)), 0.05, &from);
        QCOMPARE(snap.kind, Snap::Angle);
        QVERIFY(near(snap.point, QPointF(2 * std::cos(M_PI / 6), 2 * std::sin(M_PI / 6)), 1e-6));
        // 40 degrees is far from any 15 degree step: free direction, grid only.
        const double b = 37.5 * M_PI / 180.0;
        QCOMPARE(s.snap(QPointF(3 * std::cos(b), 3 * std::sin(b)), 0.05, &from).kind, Snap::Grid);
        // Ortho: always 0/90/180/270, the length is the projection rounded to the grid.
        const Snap ortho = s.snap(QPointF(2.004, 0.7), 0.05, &from, /*ortho=*/true);
        QCOMPARE(ortho.kind, Snap::Angle);
        QVERIFY(near(ortho.point, QPointF(2.0, 0.0), 1e-9));
    }

    // Slice 6: grid axes snap like walls: their crossings first, then anywhere along a line.
    void gridCrossingsAndLines()
    {
        Snapper s;
        s.setGridLines(Snapper::parseGrid(QJsonDocument::fromJson(R"({"grid":[
            {"guid":"G","tag":"A","x1":0,"y1":-1,"x2":0,"y2":7},
            {"guid":"G","tag":"1","x1":-1,"y1":0,"x2":9,"y2":0}]})").object()));
        const Snap cross = s.snap(QPointF(0.04, -0.03), 0.1);
        QCOMPARE(cross.kind, Snap::GridCross);
        QVERIFY(near(cross.point, QPointF(0, 0)));
        const Snap line = s.snap(QPointF(3.0, 0.06), 0.1);
        QCOMPARE(line.kind, Snap::GridLine);
        QVERIFY(near(line.point, QPointF(3.0, 0.0)));
        QVERIFY(line.wallGuid.isEmpty()); // grid lines are not walls to join
        QCOMPARE(s.snap(QPointF(3.0, 3.0), 0.1).kind, Snap::Grid);
    }

    void outsideToleranceNothingSticks()
    {
        const Snapper s = withWalls();
        QCOMPARE(s.snap(QPointF(2.5, 1.5), 0.1).kind, Snap::Grid);
    }

    // Slice 15: dimensions snap to wall faces (the dimension tool turns this on).
    void wallFacesWhenEnabled()
    {
        Snapper s;
        s.setWalls({kimbim::SnapWall{QStringLiteral("w"), QPointF(0, 0), QPointF(4, 0), 0.3}});
        QCOMPARE(s.snap(QPointF(0.02, 0.17), 0.1).kind, Snap::Grid); // off by default
        s.setFaceSnapping(true);
        const Snap corner = s.snap(QPointF(0.02, 0.17), 0.1);
        QCOMPARE(corner.kind, Snap::FaceEnd);
        QVERIFY(near(corner.point, QPointF(0, 0.15)));
        const Snap face = s.snap(QPointF(2.3, -0.12), 0.1);
        QCOMPARE(face.kind, Snap::OnFace);
        QVERIFY(near(face.point, QPointF(2.3, -0.15)));
        QCOMPARE(s.snap(QPointF(0.01, 0.01), 0.1).kind, Snap::Endpoint); // the axis end still wins
    }
};

QTEST_MAIN(TestSnapper)
#include "test_snapper.moc"
