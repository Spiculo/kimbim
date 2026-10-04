// SPDX-License-Identifier: GPL-3.0-or-later
// ElementBatch logic that needs no OpenGL: element lookup, visibility, bounds, selection owners.
#include <QtTest>

#include <SelectMgr_Selection.hxx>

#include "ElementBatch.h"

namespace {

// Three unit "boxes" (one triangle each, enough for bounds/selection), along X.
kimcad::MeshChunk threeElements()
{
    kimcad::MeshChunk c;
    c.guids = {"A", "B", "C"};
    c.types = {"IfcWall", "IfcWall", "IfcSlab"};
    for (int e = 0; e < 3; ++e) {
        const float x = float(e) * 10.0f;
        const float v[] = {x, 0, 0, x + 1, 0, 0, x, 1, 1};
        c.verts.insert(c.verts.end(), std::begin(v), std::end(v));
        const uint32_t base = uint32_t(e * 3);
        c.tris.insert(c.tris.end(), {base, base + 1, base + 2});
    }
    c.voff = {0, 3, 6, 9};
    c.toff = {0, 1, 2, 3};
    return c;
}

int selectionEntities(const Handle(kimcad::ElementBatch)& batch)
{
    Handle(SelectMgr_Selection) sel = new SelectMgr_Selection(0);
    batch->ComputeSelection(sel, 0);
    return sel->Entities().Size();
}

} // namespace

class TestElementBatch : public QObject {
    Q_OBJECT
private slots:
    void indexesElementsByGuid()
    {
        Handle(kimcad::ElementBatch) b = new kimcad::ElementBatch(threeElements());
        QCOMPARE(b->elementCount(), 3);
        QCOMPARE(b->indexOf("B"), 1);
        QCOMPARE(b->indexOf("nope"), -1);
        QCOMPARE(b->guid(2), QString("C"));
        QCOMPARE(b->type(2), QString("IfcSlab"));
        QCOMPARE(b->owner(1)->index(), 1);
        QCOMPARE(b->triangleCount(), 3);
    }

    void selectionHasOneOwnerPerVisibleElement()
    {
        Handle(kimcad::ElementBatch) b = new kimcad::ElementBatch(threeElements());
        QCOMPARE(selectionEntities(b), 3);
        b->setHidden(1, true);
        QVERIFY(b->isHidden(1));
        QCOMPARE(b->visibleCount(), 2);
        QCOMPARE(selectionEntities(b), 2);
        b->setHidden(1, false);
        QCOMPARE(b->visibleCount(), 3);
    }

    void boundsFollowVisibility()
    {
        Handle(kimcad::ElementBatch) b = new kimcad::ElementBatch(threeElements());
        double x0, y0, z0, x1, y1, z1;
        b->visibleBounds().Get(x0, y0, z0, x1, y1, z1);
        QCOMPARE(x0, 0.0);
        QCOMPARE(x1, 21.0);
        b->setHidden(2, true);
        b->visibleBounds().Get(x0, y0, z0, x1, y1, z1);
        QCOMPARE(x1, 11.0);
        b->elementBounds(0).Get(x0, y0, z0, x1, y1, z1);
        QCOMPARE(x1, 1.0);
    }
};

QTEST_MAIN(TestElementBatch)
#include "test_element_batch.moc"
