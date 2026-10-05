// SPDX-License-Identifier: GPL-3.0-or-later
// Visibility logic on the real Viewport, without showing a window (no OpenGL drawing needed).
#include <QtTest>

#include "ElementBatch.h"
#include "Viewport.h"

namespace {

// n elements, one triangle each, guids prefix+i.
kimcad::MeshChunk chunk(const QString& prefix, int n)
{
    kimcad::MeshChunk c;
    c.voff.push_back(0);
    c.toff.push_back(0);
    for (int e = 0; e < n; ++e) {
        c.guids << prefix + QString::number(e);
        c.types << QStringLiteral("IfcWall");
        const float x = float(e);
        const float v[] = {x, 0, 0, x + 0.5f, 0, 0, x, 0.5f, 1};
        c.verts.insert(c.verts.end(), std::begin(v), std::end(v));
        const uint32_t base = uint32_t(e * 3);
        c.tris.insert(c.tris.end(), {base, base + 1, base + 2});
        c.voff.push_back(uint32_t(c.verts.size() / 3));
        c.toff.push_back(uint32_t(c.tris.size() / 3));
    }
    return c;
}

Handle(kimcad::ElementBatch) batch(const QString& prefix, int n)
{
    return new kimcad::ElementBatch(chunk(prefix, n));
}

} // namespace

class TestVisibility : public QObject {
    Q_OBJECT
private slots:
    void hideIsolateShowAll()
    {
        kimcad::Viewport v;
        v.addBatch(batch("a", 3));
        v.addBatch(batch("b", 2));
        QCOMPARE(v.elementCount(), 5);
        QCOMPARE(v.visibleElementCount(), 5);

        v.setHidden({"a1"}, true);
        QCOMPARE(v.visibleElementCount(), 4);
        v.setHidden({"a1", "unknown"}, true); // idempotent, unknown guids ignored
        QCOMPARE(v.visibleElementCount(), 4);

        v.isolate({"a0", "b1"});
        QCOMPARE(v.visibleElementCount(), 2);

        v.showAll();
        QCOMPARE(v.visibleElementCount(), 5);
    }

    void isolatingAStoreyKeepsExactlyItsElements()
    {
        kimcad::Viewport v;
        v.addBatch(batch("a", 4));
        const QStringList storey{"a0", "a2", "storey-guid-without-geometry"};
        v.isolate(storey);
        QCOMPARE(v.visibleElementCount(), 2);
        QCOMPARE(v.boundsOf({}).IsVoid(), false); // visible bounds exist after isolate
    }

    void selectingAHiddenElementRevealsIt()
    {
        kimcad::Viewport v;
        v.addBatch(batch("a", 3));
        v.setHidden({"a2"}, true);
        QCOMPARE(v.visibleElementCount(), 2);
        v.selectGuids({"a2"});
        QCOMPARE(v.visibleElementCount(), 3);
        QCOMPARE(v.selectedGuids(), QStringList({"a2"}));
    }

    // OCCT exceptions must never escape into Qt event handlers (they abort the app). Without a
    // native window (headless "offscreen" platform), view operations degrade instead of throwing.
    void viewOperationsWithoutANativeWindowDoNotThrow()
    {
        kimcad::Viewport v;
        v.addBatch(batch("a", 2));
        v.fitAll();
        QCOMPARE(v.pickAt(1, 1), QString());
        QCOMPARE(v.selectInRectangle(0, 0, 10, 10, AIS_SelectionScheme_Replace), 0);
        QCOMPARE(v.measureFps(2), 0.0);
        QCOMPARE(v.dumpImage(QStringLiteral("unused.png")), false);
    }

    // Slice 4: edits replace or remove elements live; old instances never come back.
    void replacedElementsAreRetiredForGood()
    {
        kimcad::Viewport v;
        v.addBatch(batch("a", 3));
        v.replaceElements(chunk("a", 1)); // a0 has new geometry
        QCOMPARE(v.elementCount(), 3);
        QCOMPARE(v.guids().count("a0"), 1);
        QCOMPARE(v.visibleElementCount(), 3);
        v.showAll();
        QCOMPARE(v.visibleElementCount(), 3); // the retired a0 stays hidden
        v.isolate({"a0"});
        QCOMPARE(v.visibleElementCount(), 1);
        v.showAll();
        v.selectGuids({"a0"});
        QCOMPARE(v.selectedGuids(), QStringList{"a0"});
        v.replaceElements(chunk("a", 1)); // replacing keeps it selected
        QCOMPARE(v.selectedGuids(), QStringList{"a0"});
    }

    void removedElementsDisappear()
    {
        kimcad::Viewport v;
        v.addBatch(batch("a", 3));
        v.selectGuids({"a1", "a2"});
        v.removeElements({"a1", "unknown"});
        QCOMPARE(v.elementCount(), 2);
        QCOMPARE(v.visibleElementCount(), 2);
        QVERIFY(!v.guids().contains("a1"));
        QCOMPARE(v.selectedGuids(), QStringList{"a2"});
        v.showAll();
        QCOMPARE(v.visibleElementCount(), 2);
        v.replaceElements(chunk("a", 2)); // undo of a delete brings a1 back as new geometry
        QCOMPARE(v.elementCount(), 3);
        QVERIFY(v.guids().contains("a1"));
    }

    // Slice 4b: lines-only (hidden-line) display for plans; new batches follow the current mode.
    void linesOnlySwitchesEveryBatch()
    {
        kimcad::Viewport v;
        Handle(kimcad::ElementBatch) a = batch("a", 2);
        v.addBatch(a);
        QVERIFY(!v.linesOnly());
        v.setLinesOnly(true);
        QVERIFY(v.linesOnly());
        QCOMPARE(a->DisplayMode(), int(kimcad::ElementBatch::LinesOnly));
        Handle(kimcad::ElementBatch) b = batch("b", 1);
        v.addBatch(b);
        QCOMPARE(b->DisplayMode(), int(kimcad::ElementBatch::LinesOnly));
        v.setLinesOnly(false);
        QCOMPARE(a->DisplayMode(), int(kimcad::ElementBatch::Shaded));
        QCOMPARE(b->DisplayMode(), int(kimcad::ElementBatch::Shaded));
    }

    void hidingClearsSelection()
    {
        kimcad::Viewport v;
        v.addBatch(batch("a", 2));
        v.selectGuids({"a0"});
        v.setHidden({"a0"}, true);
        QVERIFY(v.selectedGuids().isEmpty());
    }
};

QTEST_MAIN(TestVisibility)
#include "test_visibility.moc"
