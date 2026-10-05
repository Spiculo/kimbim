// SPDX-License-Identifier: GPL-3.0-or-later
// ElementBatch logic that needs no OpenGL: element lookup, visibility, bounds, selection owners.
#include <QtTest>

#include <array>
#include <vector>

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

// One element from quads (4 corner indices each, any winding), unwelded like OCCT output:
// every triangle gets its own 3 vertices.
kimcad::MeshChunk fromQuads(const std::vector<std::array<std::array<float, 3>, 4>>& quads)
{
    kimcad::MeshChunk c;
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

kimcad::MeshChunk unitCube()
{
    // 6 faces, outward winding.
    return fromQuads({{{{0, 0, 0}, {0, 1, 0}, {1, 1, 0}, {1, 0, 0}}},
        {{{0, 0, 1}, {1, 0, 1}, {1, 1, 1}, {0, 1, 1}}},
        {{{0, 0, 0}, {1, 0, 0}, {1, 0, 1}, {0, 0, 1}}},
        {{{0, 1, 0}, {0, 1, 1}, {1, 1, 1}, {1, 1, 0}}},
        {{{0, 0, 0}, {0, 0, 1}, {0, 1, 1}, {0, 1, 0}}},
        {{{1, 0, 0}, {1, 1, 0}, {1, 1, 1}, {1, 0, 1}}}});
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
    // Slice 4b: border lines. Feature edges = boundary + creases; triangulation diagonals and
    // coplanar seams are not drawn. Meshes are unwelded, so edges pair up by position.
    void cubeHasTwelveFeatureEdges()
    {
        QCOMPARE(int(kimcad::ElementBatch::featureEdges(unitCube(), 0).size()), 12);
    }

    void flatQuadHasOnlyItsBorder()
    {
        QCOMPARE(int(kimcad::ElementBatch::featureEdges(fromQuads({{{{0, 0, 0}, {1, 0, 0}, {1, 1, 0}, {0, 1, 0}}}}), 0).size()), 4);
        // Two coplanar quads sharing an edge: the seam is not drawn (2 + 2 + 1 + 1 border pieces).
        const auto two = fromQuads({{{{0, 0, 0}, {1, 0, 0}, {1, 1, 0}, {0, 1, 0}}}, {{{1, 0, 0}, {2, 0, 0}, {2, 1, 0}, {1, 1, 0}}}});
        QCOMPARE(int(kimcad::ElementBatch::featureEdges(two, 0).size()), 6);
    }

    void inconsistentWindingIsNotACrease()
    {
        // Second quad wound the other way (common in exported meshes): still coplanar, no seam.
        const auto flipped = fromQuads({{{{0, 0, 0}, {1, 0, 0}, {1, 1, 0}, {0, 1, 0}}}, {{{1, 0, 0}, {1, 1, 0}, {2, 1, 0}, {2, 0, 0}}}});
        QCOMPARE(int(kimcad::ElementBatch::featureEdges(flipped, 0).size()), 6);
    }

    void acceptsShadedIdAndLinesModes()
    {
        Handle(kimcad::ElementBatch) b = new kimcad::ElementBatch(unitCube());
        QVERIFY(b->AcceptDisplayMode(kimcad::ElementBatch::Shaded));
        QVERIFY(b->AcceptDisplayMode(kimcad::ElementBatch::Ids));
        QVERIFY(b->AcceptDisplayMode(kimcad::ElementBatch::LinesOnly));
        QVERIFY(!b->AcceptDisplayMode(3));
    }

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
