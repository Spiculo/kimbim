// SPDX-License-Identifier: GPL-3.0-or-later
#include <QtTest>

#include "Cuts.h"
#include "CutPlanes.h"

namespace {

// OCCT's own test: is a point kept (not clipped) by every plane?
bool kept(const std::vector<Handle(Graphic3d_ClipPlane)>& planes, double x, double y, double z)
{
    for (const auto& p : planes)
        if (p->ProbePoint(NCollection_Vec4<double>(x, y, z, 1.0)) == Graphic3d_ClipState_Out)
            return false;
    return true;
}

} // namespace

class TestCuts : public QObject {
    Q_OBJECT
private slots:
    void planCutKeepsWhatIsBelowTheHeight()
    {
        kimbim::CutState s;
        s.planCut = true;
        s.height = 1.2;
        const auto planes = kimbim::makePlanes(s);
        QCOMPARE(int(planes.size()), 1);
        QVERIFY(kept(planes, 5, 5, 1.0));
        QVERIFY(!kept(planes, 5, 5, 1.5));
        QVERIFY(planes.front()->IsCapping()); // cut faces are filled
    }

    void sectionBoxKeepsOnlyTheInside()
    {
        kimbim::CutState s;
        s.box = true;
        s.bounds.Update(0, 0, 0, 10, 10, 10);
        const auto planes = kimbim::makePlanes(s);
        QCOMPARE(int(planes.size()), 6);
        QVERIFY(kept(planes, 5, 5, 5));
        QVERIFY(!kept(planes, -1, 5, 5));
        QVERIFY(!kept(planes, 5, 11, 5));
        QVERIFY(!kept(planes, 5, 5, 10.5));
    }

    void bothCutsCombine()
    {
        kimbim::CutState s;
        s.planCut = true;
        s.height = 3;
        s.box = true;
        s.bounds.Update(0, 0, 0, 10, 10, 10);
        const auto planes = kimbim::makePlanes(s);
        QCOMPARE(int(planes.size()), 7);
        QVERIFY(kept(planes, 5, 5, 2));
        QVERIFY(!kept(planes, 5, 5, 4)); // inside the box but above the plan cut
    }


    // D95: a vertical cut keeps the side its normal points to; sliding it along the normal works.
    void verticalCutPlaneKeepsTheNormalSide()
    {
        const kimbim::CutPlane p = kimbim::verticalCutPlane(QStringLiteral("A"), QPointF(0, 0), QPointF(0, 5), QPointF(1, 0), 0);
        QCOMPARE(p.kind, kimbim::CutPlane::Kind::Vertical);
        QVERIFY(p.normal.X() > 0.99);
        QVERIFY(p.contains(gp_Pnt(1, 2, 0)));
        QVERIFY(!p.contains(gp_Pnt(-1, 2, 0)));
        QVERIFY(p.contains(gp_Pnt(0, 2, 8))); // a vertical plane spans every height
        kimbim::CutPlane q = p;
        q.flip();
        QVERIFY(q.contains(gp_Pnt(-1, 2, 0)));
        QVERIFY(!q.contains(gp_Pnt(1, 2, 0)));
        const double before = p.offset();
        kimbim::CutPlane moved = p;
        moved.translate(2.0); // along its normal
        QVERIFY(std::abs(moved.offset() - (before + 2.0)) < 1e-9);
        moved.setOffset(0.0);
        QVERIFY(moved.contains(gp_Pnt(0, 9, 0), 1e-9));
        QVERIFY(!moved.contains(gp_Pnt(-0.5, 9, 0)));
    }

    // A horizontal user cut is independent of the plan cut, and an oblique one tilts about its line.
    void horizontalAndObliquePlanes()
    {
        const kimbim::CutPlane h = kimbim::horizontalCutPlane(QStringLiteral("H"), 2.5);
        QVERIFY(h.contains(gp_Pnt(3, 4, 2.0)));
        QVERIFY(!h.contains(gp_Pnt(3, 4, 3.0)));

        kimbim::CutPlane o = kimbim::obliqueCutPlane(QStringLiteral("O"), QPointF(0, 0), QPointF(0, 5),
            QPointF(1, 0), 30, 0);
        QCOMPARE(o.kind, kimbim::CutPlane::Kind::Oblique);
        QVERIFY(std::abs(std::abs(o.normal.Z()) - 0.5) < 1e-9);
        const gp_Pnt in = o.point.Translated(gp_Vec(o.normal));
        QVERIFY(o.contains(in));
        QVERIFY(!o.contains(o.point.Translated(gp_Vec(o.normal) * -1.0)));
        o.setAngle(0); // back to vertical
        QVERIFY(std::abs(o.normal.Z()) < 1e-9);
        QVERIFY(o.contains(gp_Pnt(2, 2, 0)));
    }

    // From a face the plane lies on the face and keeps the side away from the camera.
    void faceCutKeepsAwayFromTheCamera()
    {
        const kimbim::CutPlane p = kimbim::faceCutPlane(QStringLiteral("F"), gp_Pnt(0, 0, 1),
            gp_Dir(0, 0, 1), gp_Pnt(0, 0, 10));
        QVERIFY(p.normal.Z() < -0.99);
        QVERIFY(p.contains(gp_Pnt(1, 1, 0)));
        QVERIFY(!p.contains(gp_Pnt(1, 1, 2)));
        QCOMPARE(p.kind, kimbim::CutPlane::Kind::Horizontal);
    }

    void planesCombineWithPlanAndBoxAndRespectTheLimit()
    {
        kimbim::CutState s;
        s.planCut = true;
        s.height = 3;
        s.box = true;
        s.bounds.Update(0, 0, 0, 10, 10, 10);
        for (int i = 0; i < 4; ++i) {
            kimbim::CutPlane p = kimbim::verticalCutPlane(QStringLiteral("V%1").arg(i),
                QPointF(i, -5), QPointF(i, 5), QPointF(i + 1, 0), 0);
            s.planes.push_back(p);
        }
        QCOMPARE(kimbim::planeCount(s), 11);
        QCOMPARE(int(kimbim::makePlanes(s).size()), 11); // no limit: four planes + plan + box
        QCOMPARE(int(kimbim::makePlanes(s, 8).size()), 8);
        QCOMPARE(kimbim::maxUserPlanes(8, true, true), 1);
        QCOMPARE(kimbim::maxUserPlanes(16, true, true), 9);
        // a disabled plane asks for no clip plane
        s.planes[0].enabled = false;
        QCOMPARE(kimbim::planeCount(s), 10);
    }

    void cutPlaneJsonRoundTrip()
    {
        kimbim::CutPlane p = kimbim::obliqueCutPlane(QStringLiteral("Oblique 2"), QPointF(1, 2),
            QPointF(4, 6), QPointF(5, 2), 22.5, 1.2);
        p.enabled = false;
        bool ok = false;
        const kimbim::CutPlane back = kimbim::cutPlaneFromJson(kimbim::cutPlaneToJson(p), &ok);
        QVERIFY(ok);
        QCOMPARE(QString::fromStdString(back.name), QString("Oblique 2"));
        QCOMPARE(back.enabled, false);
        QCOMPARE(back.kind, kimbim::CutPlane::Kind::Oblique);
        QVERIFY(back.point.Distance(p.point) < 1e-9);
        QVERIFY(std::abs(back.normal.Dot(p.normal) - 1.0) < 1e-9);
        QVERIFY(std::abs(back.angle - 22.5) < 1e-9);
    }

    void offMeansNoPlanesAndEmptyBoxIsIgnored()
    {
        kimbim::CutState s;
        QVERIFY(kimbim::makePlanes(s).empty());
        s.box = true; // no bounds -> nothing to box
        QVERIFY(kimbim::makePlanes(s).empty());
    }
};

QTEST_MAIN(TestCuts)
#include "test_cuts.moc"
