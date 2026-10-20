// SPDX-License-Identifier: GPL-3.0-or-later
// D89: the tracker (typed length, angle, relative and absolute x/y), temporary guides, intersections.
#include <QJsonDocument>
#include <QJsonObject>
#include <QtTest>

#include "InputAids.h"
#include "Snapper.h"
#include "Tracker.h"

#include <cmath>
#include <memory>

using kimbim::InputAids;
using kimbim::Snap;
using kimbim::Snapper;
using kimbim::Tracker;

namespace {

Snapper withWalls(std::shared_ptr<InputAids> aids = {})
{
    Snapper s;
    s.setWalls(Snapper::parse(QJsonDocument::fromJson(R"({"walls":[
        {"guid":"A","x1":0,"y1":0,"x2":4,"y2":0,"thickness":0.2},
        {"guid":"B","x1":4,"y1":0,"x2":4,"y2":3,"thickness":0.2},
        {"guid":"C","x1":2,"y1":-2,"x2":2,"y2":2,"thickness":0.2}]})").object()));
    s.setAids(std::move(aids));
    return s;
}

bool near(const QPointF& a, const QPointF& b, double eps = 1e-9)
{
    return std::hypot(a.x() - b.x(), a.y() - b.y()) <= eps;
}

} // namespace

class TestInputAids : public QObject {
    Q_OBJECT
private slots:
    void trackerFieldsAndTab()
    {
        Tracker t;
        QCOMPARE(t.fields(), QVector<Tracker::Field>({Tracker::X, Tracker::Y})); // no anchor: absolute x, y
        QVERIFY(t.absolute());
        t.setAnchor(QPointF(1, 1));
        QCOMPARE(t.focus(), Tracker::Length);
        QVERIFY(!t.absolute());
        QVERIFY(t.key(Qt::Key_Tab, QString()));
        QCOMPARE(t.focus(), Tracker::Angle);
        t.key(Qt::Key_Tab, QString());
        QCOMPARE(t.focus(), Tracker::X);
        t.key(Qt::Key_Tab, QString());
        QCOMPARE(t.focus(), Tracker::Y);
        t.key(Qt::Key_Tab, QString());
        QCOMPARE(t.focus(), Tracker::Length);
        t.key(Qt::Key_Backtab, QString());
        QCOMPARE(t.focus(), Tracker::Y);
    }

    void trackerPolar()
    {
        Tracker t;
        t.setAnchor(QPointF(1, 1));
        t.setCursor(QPointF(4, 1));
        QCOMPARE(t.live(Tracker::Length), 3.0);
        QCOMPARE(t.live(Tracker::Angle), 0.0);
        t.type(QStringLiteral("2,5"));
        QVERIFY(t.lengthOnly());
        QVERIFY(near(*t.target(), QPointF(3.5, 1)));
        t.type(QStringLiteral("<90")); // AutoCAD's length<angle
        QVERIFY(!t.lengthOnly());
        QVERIFY(near(*t.target(), QPointF(1, 3.5)));
        QVERIFY(t.locks().angle && std::abs(*t.locks().angle - M_PI / 2) < 1e-12);
        t.clear();
        QVERIFY(!t.hasInput() && !t.target());
        // An angle alone keeps the cursor's distance along that direction.
        t.setCursor(QPointF(1, 4));
        t.type(QStringLiteral("\t45"));
        QVERIFY(near(*t.target(), QPointF(1, 1) + QPointF(1, 1) * (3 * std::sqrt(0.5) * std::sqrt(0.5))));
    }

    void trackerRelativeAndAbsoluteXY()
    {
        Tracker t;
        t.setAnchor(QPointF(1, 1));
        t.setCursor(QPointF(3, 2));
        t.type(QStringLiteral("\t\t2\t-1")); // dx 2, dy -1
        QVERIFY(near(*t.target(), QPointF(3, 0)));
        t.clear();
        t.type(QStringLiteral("#5;6")); // absolute
        QVERIFY(t.absolute());
        QVERIFY(near(*t.target(), QPointF(5, 6)));
        t.clear();
        t.type(QStringLiteral("a7")); // 'a' toggles absolute too; y keeps the cursor's
        QVERIFY(near(*t.target(), QPointF(7, 2)));
        // Without an anchor x, y are absolute.
        Tracker first;
        first.type(QStringLiteral("2\t3"));
        QVERIFY(near(*first.target(), QPointF(2, 3)));
    }

    void typedPointIsExactAndFindsItsWall()
    {
        const Snapper s = withWalls();
        const Snap typed = s.snap(QPointF(1.23456, 0.7), -1);
        QCOMPARE(typed.kind, Snap::Typed);
        QVERIFY(near(typed.point, QPointF(1.23456, 0.7)));
        const Snap onEnd = s.snap(QPointF(4, 3), -1);
        QCOMPARE(onEnd.kind, Snap::Endpoint);
        QCOMPARE(onEnd.wallGuid, QString("B"));
    }

    void locksHoldTheCursor()
    {
        auto aids = std::make_shared<InputAids>();
        const Snapper s = withWalls(aids);
        const QPointF from(10, 10);
        InputAids::Locks l;
        l.angle = M_PI / 2;
        aids->setLocks(l);
        Snap snap = s.snap(QPointF(10.3, 12.0), 0.1, &from);
        QCOMPARE(snap.kind, Snap::Tracked);
        QVERIFY(near(snap.point, QPointF(10, 12)));
        l.length = 1.5;
        aids->setLocks(l);
        QVERIFY(near(s.snap(QPointF(10.3, 12.0), 0.1, &from).point, QPointF(10, 11.5)));
        aids->setLocks({});
        QVERIFY(s.snap(QPointF(10.3, 12.0), 0.1, &from).kind != Snap::Tracked);
    }

    void wallCrossingIsAnIntersection()
    {
        const Snapper s = withWalls();
        const Snap snap = s.snap(QPointF(2.04, 0.05), 0.1); // walls A and C cross at (2, 0) = A's middle too
        QCOMPARE(snap.kind, Snap::Intersection);
        QVERIFY(near(snap.point, QPointF(2, 0)));
    }

    void guideAcquiredByRestingThenExtensionLine()
    {
        auto aids = std::make_shared<InputAids>();
        const Snapper s = withWalls(aids);
        // Rest on wall B's end (4, 3): acquired once, not twice.
        QCOMPARE(s.snap(QPointF(4.02, 2.97), 0.1).kind, Snap::Endpoint);
        QVERIFY(aids->hovered().has_value());
        QVERIFY(aids->acquireHovered());
        QVERIFY(!aids->acquireHovered());
        QCOMPARE(aids->guides().size(), 1);
        // Far from any wall, near the horizontal through (4, 3): exactly y = 3.
        Snap g = s.snap(QPointF(9.031, 3.04), 0.1);
        QCOMPARE(g.kind, Snap::GuideLine);
        QVERIFY(near(g.point, QPointF(9.03, 3.0), 1e-9));
        // Vertical through it, from a previous point: where the guide crosses the previous point's horizontal.
        const QPointF from(-5, 7);
        Snap x = s.snap(QPointF(4.05, 7.03), 0.1, &from);
        QCOMPARE(x.kind, Snap::GuideCross);
        QVERIFY(near(x.point, QPointF(4, 7)));
        // Two guides: their lines cross.
        aids->acquire({QPointF(8, 8), std::nullopt});
        Snap c = s.snap(QPointF(8.04, 3.05), 0.1);
        QCOMPARE(c.kind, Snap::GuideCross);
        QVERIFY(near(c.point, QPointF(8, 3)));
        // A diagonal wall's end casts its extension; parallel to it from a previous point.
        auto aids2 = std::make_shared<InputAids>();
        Snapper d;
        d.setWalls(Snapper::parse(QJsonDocument::fromJson(R"({"walls":[{"guid":"D","x1":0,"y1":0,"x2":3,"y2":3,"thickness":0.2}]})").object()));
        d.setAids(aids2);
        d.snap(QPointF(3.01, 3.01), 0.1);
        QVERIFY(aids2->acquireHovered());
        Snap ext = d.snap(QPointF(6.05, 5.97), 0.1);
        QCOMPARE(ext.kind, Snap::GuideLine);
        QVERIFY(std::abs(ext.point.x() - ext.point.y()) < 1e-9);
        const QPointF f(20, 0);
        Snap par = d.snap(QPointF(22, 2.05), 0.01, &f);
        QCOMPARE(par.kind, Snap::Parallel);
        QVERIFY(std::abs((par.point.x() - 20) - par.point.y()) < 1e-9);
        // Resting on an acquired point again releases it; Esc/toggle clears all.
        d.snap(QPointF(30, 30), 0.1);
        d.snap(QPointF(3.0, 3.01), 0.1);
        QVERIFY(aids2->acquireHovered());
        QVERIFY(aids2->guides().isEmpty());
        aids->clearGuides();
        QVERIFY(aids->guides().isEmpty());
    }

    void atMostAFewGuides()
    {
        InputAids aids;
        for (int i = 0; i < 6; ++i)
            aids.acquire({QPointF(i, 0), std::nullopt});
        QCOMPARE(aids.guides().size(), InputAids::kMaxGuides);
        QCOMPARE(aids.guides().first().at, QPointF(6 - InputAids::kMaxGuides, 0));
        aids.setGuidesEnabled(false);
        QVERIFY(aids.guides().isEmpty());
        aids.acquire({QPointF(1, 1), std::nullopt});
        QVERIFY(aids.guides().isEmpty());
    }

    void lastSnapIsRecorded()
    {
        auto aids = std::make_shared<InputAids>();
        const Snapper s = withWalls(aids);
        const int before = aids->serial();
        const QPointF from(0, 5);
        s.snap(QPointF(7, 5.02), 0.1, &from);
        QCOMPARE(aids->serial(), before + 1);
        QCOMPARE(*aids->lastFrom(), from);
        s.snap(QPointF(7, 5.02), 0.1);
        QVERIFY(!aids->lastFrom());
    }
};

QTEST_GUILESS_MAIN(TestInputAids)
#include "test_input_aids.moc"
