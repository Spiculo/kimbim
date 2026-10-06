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

    // Slice 4b: element ids drawn as colours for "only what you can see" box selection.
    // 6 bits per channel (value*4+2) survive +-1 of rounding; anything else decodes as "no element".
    void idColoursRoundTripWithNoise()
    {
        for (int id : {1, 2, 63, 64, 4095, 4096, 100000, 262143}) {
            const auto rgb = kimcad::ElementBatch::idRgb(id);
            for (int d : {-1, 0, 1})
                QCOMPARE(kimcad::ElementBatch::idFromRgb(rgb[0] + d, rgb[1] + d, rgb[2] - d), id);
        }
        QCOMPARE(kimcad::ElementBatch::idFromRgb(0, 0, 0), -1);       // black background
        QCOMPARE(kimcad::ElementBatch::idFromRgb(240, 240, 244), -1); // anything off the grid
        QCOMPARE(kimcad::ElementBatch::maxId(), 262143);
    }

    // Owner feedback: cut elements need their section drawn (OCCT capping doesn't show on these
    // meshes). The section of an element at height z = its closed outline(s) in plan.
    void sectionOfACubeIsItsSquare()
    {
        const auto loops = kimcad::ElementBatch::sectionLoops(unitCube(), 0, 0.5);
        QCOMPARE(int(loops.size()), 1);
        double area = 0;
        const auto& p = loops.front();
        for (size_t i = 0; i < p.size(); ++i)
            area += p[i].X() * p[(i + 1) % p.size()].Y() - p[(i + 1) % p.size()].X() * p[i].Y();
        QVERIFY(std::abs(std::abs(area) / 2 - 1.0) < 1e-9);
        QVERIFY(kimcad::ElementBatch::sectionLoops(unitCube(), 0, 1.5).empty()); // above it
        QCOMPARE(int(p.size()), 4); // collinear points from the triangulation are merged
    }

    // Slice 11: layers can hide elements (separately from the user's H/I hiding) and lock them
    // (locked elements can't be selected).
    void layerHiddenAndLockedElements()
    {
        Handle(kimcad::ElementBatch) b = new kimcad::ElementBatch(threeElements());
        b->setLayerHidden(0, true);
        QVERIFY(b->isHidden(0));
        QCOMPARE(b->visibleCount(), 2);
        b->setHidden(0, false); // "show all" doesn't show what a layer hides
        QVERIFY(b->isHidden(0));
        b->setLayerHidden(0, false);
        QVERIFY(!b->isHidden(0));
        QCOMPARE(b->visibleCount(), 3);
        b->setLocked(1, true);
        QCOMPARE(selectionEntities(b), 2);
        QVERIFY(b->isLocked(1));
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
