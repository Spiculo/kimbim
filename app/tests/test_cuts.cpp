// SPDX-License-Identifier: GPL-3.0-or-later
#include <QtTest>

#include "Cuts.h"

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
