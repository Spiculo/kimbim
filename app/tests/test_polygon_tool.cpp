// SPDX-License-Identifier: GPL-3.0-or-later
#include <QSignalSpy>
#include <QtTest>

#include "PolygonTool.h"

#include <cmath>

using kimcad::PolygonTool;



namespace {

double triangulatedArea(const QVector<QPointF>& pts, const std::vector<uint32_t>& tris)
{
    double area = 0;
    for (size_t i = 0; i + 2 < tris.size(); i += 3) {
        const QPointF a = pts[int(tris[i])], b = pts[int(tris[i + 1])], c = pts[int(tris[i + 2])];
        area += std::abs((b.x() - a.x()) * (c.y() - a.y()) - (c.x() - a.x()) * (b.y() - a.y())) / 2;
    }
    return area;
}

} // namespace

class TestPolygonTool : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { qRegisterMetaType<QVector<QPointF>>(); }

    void clickingTheFirstPointClosesTheOutline()
    {
        PolygonTool tool;
        tool.setTolerance(0.05);
        QSignalSpy done(&tool, &PolygonTool::polygonFinished);
        for (const QPointF& p : {QPointF(0, 0), QPointF(4, 0), QPointF(4, 3), QPointF(0, 3), QPointF(0.02, 0.01)})
            tool.click(p);
        QCOMPARE(done.count(), 1);
        const auto pts = done.last().at(0).value<QVector<QPointF>>();
        QCOMPARE(pts.size(), 4);
        QCOMPARE(pts.first(), QPointF(0, 0));
        QVERIFY(!tool.isDrawing());
    }

    void enterFinishesWithThreeOrMorePoints()
    {
        PolygonTool tool;
        QSignalSpy done(&tool, &PolygonTool::polygonFinished);
        tool.click({0, 0});
        tool.click({2, 0});
        tool.finish(); // only 2 points: nothing
        QCOMPARE(done.count(), 0);
        tool.click({0, 0});
        tool.click({2, 0});
        tool.click({2, 2});
        tool.finish();
        QCOMPARE(done.count(), 1);
        QCOMPARE(done.last().at(0).value<QVector<QPointF>>().size(), 3);
    }

    void crossingOutlinesAreRejected()
    {
        PolygonTool tool;
        QSignalSpy done(&tool, &PolygonTool::polygonFinished);
        QSignalSpy rejected(&tool, &PolygonTool::rejected);
        for (const QPointF& p : {QPointF(0, 0), QPointF(2, 2), QPointF(2, 0), QPointF(0, 2)})
            tool.click(p);
        tool.finish();
        QCOMPARE(done.count(), 0);
        QCOMPARE(rejected.count(), 1);
    }

    void cancelDropsThePoints()
    {
        PolygonTool tool;
        QSignalSpy done(&tool, &PolygonTool::polygonFinished);
        tool.click({0, 0});
        tool.click({1, 0});
        tool.cancel();
        QVERIFY(!tool.isDrawing());
        QVERIFY(tool.points().isEmpty());
        QCOMPARE(done.count(), 0);
    }

    void earClippingHandlesSquaresLShapesAndBothWindings()
    {
        const QVector<QPointF> square{{0, 0}, {4, 0}, {4, 3}, {0, 3}};
        auto t = PolygonTool::triangulate(square);
        QCOMPARE(int(t.size()), 6);
        QVERIFY(qFuzzyCompare(triangulatedArea(square, t), 12.0));
        const QVector<QPointF> ell{{0, 0}, {4, 0}, {4, 2}, {2, 2}, {2, 4}, {0, 4}};
        t = PolygonTool::triangulate(ell);
        QCOMPARE(int(t.size()), 12);
        QVERIFY(qFuzzyCompare(triangulatedArea(ell, t), 12.0));
        QVector<QPointF> cw(ell.rbegin(), ell.rend());
        QVERIFY(qFuzzyCompare(triangulatedArea(cw, PolygonTool::triangulate(cw)), 12.0));
        QVERIFY(PolygonTool::isSimple(ell));
        QVERIFY(!PolygonTool::isSimple({{0, 0}, {2, 2}, {2, 0}, {0, 2}}));
    }
};

QTEST_MAIN(TestPolygonTool)
#include "test_polygon_tool.moc"
