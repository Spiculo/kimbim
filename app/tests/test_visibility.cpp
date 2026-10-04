// SPDX-License-Identifier: GPL-3.0-or-later
// Visibility logic on the real Viewport, without showing a window (no OpenGL drawing needed).
#include <QtTest>

#include "ElementBatch.h"
#include "Viewport.h"

namespace {

// n elements, one triangle each, guids prefix+i.
Handle(kimcad::ElementBatch) batch(const QString& prefix, int n)
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
    return new kimcad::ElementBatch(std::move(c));
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
