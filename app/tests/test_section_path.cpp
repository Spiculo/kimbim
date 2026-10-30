// SPDX-License-Identifier: GPL-3.0-or-later
// D110: marker paths, arcs and the bulges that carry them.
#include <QtTest>

#include <array>
#include <cmath>
#include <vector>

#include <QJsonArray>
#include <QJsonObject>
#include <Bnd_Box.hxx>

#include "ElementBatch.h"
#include "SectionPath.h"
#include "Viewport.h"

namespace {

// One element from quads (4 corner indices each), unwelded like OCCT output.
kimbim::MeshChunk fromQuads(const std::vector<std::array<std::array<float, 3>, 4>>& quads)
{
    kimbim::MeshChunk c;
    c.guids = {"Q"};
    c.types = {"IfcWall"};
    uint32_t n = 0;
    for (const auto& q : quads)
        for (const auto& tri : {std::array<int, 3>{0, 1, 2}, std::array<int, 3>{0, 2, 3}})
            for (int k : tri) {
                c.verts.insert(c.verts.end(), {q[size_t(k)][0], q[size_t(k)][1], q[size_t(k)][2]});
                c.tris.push_back(n++);
            }
    c.voff = {0, n};
    c.toff = {0, n / 3};
    return c;
}

kimbim::MeshChunk unitCube()
{
    return fromQuads({{{{0, 0, 0}, {0, 1, 0}, {1, 1, 0}, {1, 0, 0}}},
        {{{0, 0, 1}, {1, 0, 1}, {1, 1, 1}, {0, 1, 1}}},
        {{{0, 0, 0}, {1, 0, 0}, {1, 0, 1}, {0, 0, 1}}},
        {{{0, 1, 0}, {0, 1, 1}, {1, 1, 1}, {1, 1, 0}}},
        {{{0, 0, 0}, {0, 0, 1}, {0, 1, 1}, {0, 1, 0}}},
        {{{1, 0, 0}, {1, 1, 0}, {1, 1, 1}, {1, 0, 1}}}});
}

} // namespace

class TestSectionPath : public QObject {
    Q_OBJECT
private slots:
    void aPointOnTheArcGivesItsBulge()
    {
        // A half circle through the chord's midpoint above it: bulge 1.
        QCOMPARE(kimbim::bulgeThrough({0, 0}, {2, 0}, {1, 1}), 1.0);
        // A shallower arc (sagitta 0.5 on a 2 m chord): 2 * 0.5 / 2 = 0.5.
        QCOMPARE(kimbim::bulgeThrough({0, 0}, {2, 0}, {1, 0.5}), 0.5);
        // Below the chord: negative.
        QVERIFY(kimbim::bulgeThrough({0, 0}, {2, 0}, {1, -0.5}) < 0);
    }

    void anArcStartsEndsAndPassesThroughItsPoint()
    {
        const auto arc = kimbim::sampleArc({0, 0}, {2, 0}, 1.0);
        QVERIFY(arc.size() > 2);
        QVERIFY(std::hypot(arc.first().x(), arc.first().y()) < 1e-9);
        QVERIFY(std::hypot(arc.last().x() - 2.0, arc.last().y()) < 1e-9);
        const QPointF mid = arc[arc.size() / 2];
        QVERIFY(std::abs(mid.x() - 1.0) < 0.05);
        QVERIFY(std::abs(mid.y() - 1.0) < 0.05);
        // The outline of a one-segment curved path keeps the arc.
        const auto outline = kimbim::markerOutline({{0, 0}, {2, 0}}, {1.0});
        QVERIFY(outline.size() == arc.size());
        // A negative bulge arcs below the chord.
        const auto below = kimbim::sampleArc({0, 0}, {2, 0}, -1.0);
        const QPointF belowMid = below[below.size() / 2];
        QVERIFY(std::abs(belowMid.x() - 1.0) < 0.05);
        QVERIFY(std::abs(belowMid.y() + 1.0) < 0.05);
    }

    void aBentPathIsSegmentsAndAnOutline()
    {
        const QVector<QPointF> path{{0, 0}, {4, 0}, {4, 3}};
        const auto segments = kimbim::markerSegments(path, {0, 0});
        QCOMPARE(segments.size(), 2);
        QCOMPARE(segments[1].b, QPointF(4, 3));
        const auto outline = kimbim::markerOutline(path, {0, 0});
        QCOMPARE(outline.size(), 3);
        QCOMPARE(outline.last(), QPointF(4, 3));
    }

    void aCurveIsSampledEvenly()
    {
        // A 270 degree arc (bulge tan(270/4) = tan(67.5)) is sampled into many pieces, in order.
        const double b = std::tan(67.5 * M_PI / 180.0);
        const auto arc = kimbim::sampleArc({0, 0}, {1, 0}, b);
        QVERIFY(arc.size() >= 27); // at most 10 degrees per piece
        QVERIFY(std::hypot(arc.first().x(), arc.first().y()) < 1e-9);
        QVERIFY(std::hypot(arc.last().x() - 1.0, arc.last().y()) < 1e-9);
    }

    void aFoldedViewIsClippedAndLaidOutStripByStrip()
    {
        kimbim::Viewport v;
        v.addBatch(new kimbim::ElementBatch(unitCube()));
        Bnd_Box bounds;
        bounds.Add(gp_Pnt(0, 0, 0));
        bounds.Add(gp_Pnt(1, 1, 1));

        // Two perpendicular sections through the cube: x = 0.5 looking +X, then y = 0.5 looking +Y.
        kimbim::Viewport::FoldStrip first;
        first.view = gp_Ax2(gp_Pnt(0.5, 0.5, 0.5), gp_Dir(-1, 0, 0), gp_Dir(0, -1, 0));
        first.cut = gp_Pln(gp_Pnt(0.5, 0.5, 0), gp_Dir(1, 0, 0));
        first.width = 2.0;
        first.section = true;
        kimbim::Viewport::FoldStrip second;
        second.view = gp_Ax2(gp_Pnt(0.5, 0.5, 0.5), gp_Dir(0, -1, 0), gp_Dir(1, 0, 0));
        second.cut = gp_Pln(gp_Pnt(0.5, 0.5, 0), gp_Dir(0, 1, 0));
        second.width = 2.0;
        second.section = true;
        const QJsonObject g = v.viewGeometryFolded({"Q"}, {first, second}, bounds);

        QCOMPARE(g.value("strips").toArray().size(), 2);
        QCOMPARE(g.value("cut").toArray().size(), 2);
        QCOMPARE(g.value("proj").toArray().size(), 2); // one entry per strip
        for (const auto& e : g.value("cut").toArray()) {
            const QJsonObject entry = e.toObject();
            const int strip = entry.value("strip").toInt();
            QVERIFY(strip == 0 || strip == 1);
            for (const auto& l : entry.value("loops").toArray())
                for (const auto& p : l.toArray()) {
                    const double x = p.toArray().at(0).toDouble();
                    QVERIFY(x >= (strip == 0 ? -1e-6 : 2.0 - 1e-6));
                    QVERIFY(x <= (strip == 0 ? 2.0 + 1e-6 : 4.0 + 1e-6));
                }
        }
    }
};

QTEST_MAIN(TestSectionPath)
#include "test_section_path.moc"
