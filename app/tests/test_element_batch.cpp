// SPDX-License-Identifier: GPL-3.0-or-later
// ElementBatch logic that needs no OpenGL: element lookup, visibility, bounds, selection owners.
#include <QtTest>

#include <array>
#include <vector>

#include <SelectMgr_Selection.hxx>

#include "ElementBatch.h"

namespace {

// Three unit "boxes" (one triangle each, enough for bounds/selection), along X.
kimbim::MeshChunk threeElements()
{
    kimbim::MeshChunk c;
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
    // 6 faces, outward winding.
    return fromQuads({{{{0, 0, 0}, {0, 1, 0}, {1, 1, 0}, {1, 0, 0}}},
        {{{0, 0, 1}, {1, 0, 1}, {1, 1, 1}, {0, 1, 1}}},
        {{{0, 0, 0}, {1, 0, 0}, {1, 0, 1}, {0, 0, 1}}},
        {{{0, 1, 0}, {0, 1, 1}, {1, 1, 1}, {1, 1, 0}}},
        {{{0, 0, 0}, {0, 0, 1}, {0, 1, 1}, {0, 1, 0}}},
        {{{1, 0, 0}, {1, 1, 0}, {1, 1, 1}, {1, 0, 1}}}});
}

int selectionEntities(const Handle(kimbim::ElementBatch)& batch)
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
        QCOMPARE(int(kimbim::ElementBatch::featureEdges(unitCube(), 0).size()), 12);
    }

    void flatQuadHasOnlyItsBorder()
    {
        QCOMPARE(int(kimbim::ElementBatch::featureEdges(fromQuads({{{{0, 0, 0}, {1, 0, 0}, {1, 1, 0}, {0, 1, 0}}}}), 0).size()), 4);
        // Two coplanar quads sharing an edge: the seam is not drawn (2 + 2 + 1 + 1 border pieces).
        const auto two = fromQuads({{{{0, 0, 0}, {1, 0, 0}, {1, 1, 0}, {0, 1, 0}}}, {{{1, 0, 0}, {2, 0, 0}, {2, 1, 0}, {1, 1, 0}}}});
        QCOMPARE(int(kimbim::ElementBatch::featureEdges(two, 0).size()), 6);
    }

    void inconsistentWindingIsNotACrease()
    {
        // Second quad wound the other way (common in exported meshes): still coplanar, no seam.
        const auto flipped = fromQuads({{{{0, 0, 0}, {1, 0, 0}, {1, 1, 0}, {0, 1, 0}}}, {{{1, 0, 0}, {1, 1, 0}, {2, 1, 0}, {2, 0, 0}}}});
        QCOMPARE(int(kimbim::ElementBatch::featureEdges(flipped, 0).size()), 6);
    }

    // Slice 4b: element ids drawn as colours for "only what you can see" box selection.
    // 6 bits per channel (value*4+2) survive +-1 of rounding; anything else decodes as "no element".
    void idColoursRoundTripWithNoise()
    {
        for (int id : {1, 2, 63, 64, 4095, 4096, 100000, 262143}) {
            const auto rgb = kimbim::ElementBatch::idRgb(id);
            for (int d : {-1, 0, 1})
                QCOMPARE(kimbim::ElementBatch::idFromRgb(rgb[0] + d, rgb[1] + d, rgb[2] - d), id);
        }
        QCOMPARE(kimbim::ElementBatch::idFromRgb(0, 0, 0), -1);       // black background
        QCOMPARE(kimbim::ElementBatch::idFromRgb(240, 240, 244), -1); // anything off the grid
        QCOMPARE(kimbim::ElementBatch::maxId(), 262143);
    }

    // Owner feedback: cut elements need their section drawn (OCCT capping doesn't show on these
    // meshes). The section of an element at height z = its closed outline(s) in plan.
    void sectionOfACubeIsItsSquare()
    {
        const auto loops = kimbim::ElementBatch::sectionLoops(unitCube(), 0, 0.5);
        QCOMPARE(int(loops.size()), 1);
        double area = 0;
        const auto& p = loops.front();
        for (size_t i = 0; i < p.size(); ++i)
            area += p[i].X() * p[(i + 1) % p.size()].Y() - p[(i + 1) % p.size()].X() * p[i].Y();
        QVERIFY(std::abs(std::abs(area) / 2 - 1.0) < 1e-9);
        QVERIFY(kimbim::ElementBatch::sectionLoops(unitCube(), 0, 1.5).empty()); // above it
        QCOMPARE(int(p.size()), 4); // collinear points from the triangulation are merged
    }


    // D95: the same outline pass on any plane: a vertical cut through a cube is a square, an
    // oblique one a closed loop whose points lie on the plane.
    void sectionOfACubeOnAnyPlane()
    {
        const auto vertical = kimbim::ElementBatch::sectionLoopsPlane(unitCube(), 0,
            gp_Pln(gp_Pnt(0.5, 0, 0), gp_Dir(1, 0, 0)));
        QCOMPARE(int(vertical.size()), 1);
        QVERIFY(vertical.front().size() >= 4);
        double area = 0;
        for (size_t i = 0; i < vertical.front().size(); ++i) {
            const gp_Pnt& p = vertical.front()[i];
            QVERIFY(std::abs(p.X() - 0.5) < 1e-9);
            const gp_Pnt& q = vertical.front()[(i + 1) % vertical.front().size()];
            area += p.Y() * q.Z() - q.Y() * p.Z();
        }
        QVERIFY(std::abs(std::abs(area) / 2 - 1.0) < 1e-9);

        const gp_Pln oblique(gp_Pnt(0.5, 0.5, 0.5), gp_Dir(1, 0.4, 0.3));
        const auto loops = kimbim::ElementBatch::sectionLoopsPlane(unitCube(), 0, oblique);
        QCOMPARE(int(loops.size()), 1);
        QVERIFY(loops.front().size() >= 4);
        for (const gp_Pnt& p : loops.front())
            QVERIFY(std::abs(gp_Vec(oblique.Location(), p).Dot(gp_Vec(oblique.Axis().Direction()))) < 1e-9);
    }

    // Slice 11: layers can hide elements (separately from the user's H/I hiding) and lock them
    // (locked elements can't be selected).
    void layerHiddenAndLockedElements()
    {
        Handle(kimbim::ElementBatch) b = new kimbim::ElementBatch(threeElements());
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

    // D73: border lines are drawn in one group per style (colour, width, pattern).
    void linesAreGroupedByStyle()
    {
        Handle(kimbim::ElementBatch) b = new kimbim::ElementBatch(threeElements());
        const kimbim::BatchLine red{Quantity_Color(1, 0, 0, Quantity_TOC_RGB), 2.0f, 0xFFFF};
        b->setLineStyle(0, red);
        b->setLineStyle(1, red);
        const Quantity_Color fallback(0.2, 0.2, 0.2, Quantity_TOC_RGB);
        auto buckets = b->lineBuckets(fallback);
        QCOMPARE(int(buckets.size()), 2); // red (A and B) and the default (C)
        b->setLineStyle(1, kimbim::BatchLine{Quantity_Color(1, 0, 0, Quantity_TOC_RGB), 2.0f, 0xF0F0});
        QCOMPARE(int(b->lineBuckets(fallback).size()), 3); // same colour, other pattern
        b->setHidden(2, true);
        QCOMPARE(int(b->lineBuckets(fallback).size()), 2); // hidden elements draw no lines
        b->setLineStyle(0, std::nullopt);
        b->setLineStyle(1, std::nullopt);
        QCOMPARE(int(b->lineBuckets(fallback).size()), 1);
    }

    // D73: hidden by the visibility set is a third kind of hidden: Show all doesn't reveal it.
    void graphicsHiddenSurvivesShowAll()
    {
        Handle(kimbim::ElementBatch) b = new kimbim::ElementBatch(threeElements());
        b->setGraphicsHidden(1, true);
        QVERIFY(b->isHidden(1) && b->isGraphicsHidden(1));
        QCOMPARE(b->visibleCount(), 2);
        b->setHidden(1, false); // Show all
        QVERIFY(b->isHidden(1));
        QCOMPARE(selectionEntities(b), 2);
        b->setGraphicsHidden(1, false);
        QVERIFY(!b->isHidden(1));
        QCOMPARE(b->visibleCount(), 3);
    }

    // D73: an override surface colour replaces the palette; Compare's colour still wins.
    void surfaceColoursAndCompareOverrides()
    {
        Handle(kimbim::ElementBatch) b = new kimbim::ElementBatch(threeElements());
        const Quantity_Color red(1, 0, 0, Quantity_TOC_RGB), green(0, 1, 0, Quantity_TOC_RGB);
        QVERIFY(!b->surfaceColor(0).IsEqual(red));
        b->setSurface(0, red);
        QVERIFY(b->surfaceColor(0).IsEqual(red));
        b->setColorOverride(0, green);
        QVERIFY(b->surfaceColor(0).IsEqual(green));
        b->setColorOverride(0, std::nullopt);
        b->setSurface(0, std::nullopt);
        QVERIFY(!b->surfaceColor(0).IsEqual(red));
    }

    // D96: each face takes its own surface (material) colour and transparency; an override colours
    // the whole element, and a face without a surface keeps the class colour.
    void faceSurfacesAndOverrides()
    {
        kimbim::MeshChunk c = threeElements();
        c.palette = {{1, 0, 0, 0}, {0, 0, 1, 0.6f}};
        c.faceColors = {0, 1, kimbim::MeshChunk::kNoColor};
        Handle(kimbim::ElementBatch) b = new kimbim::ElementBatch(c);
        const Quantity_Color red(1, 0, 0, Quantity_TOC_RGB), blue(0, 0, 1, Quantity_TOC_RGB);
        QVERIFY(b->triangleColor(0, 0).IsEqual(red));
        QCOMPARE(b->triangleTransparency(0, 0), 0.0);
        QVERIFY(b->triangleColor(1, 1).IsEqual(blue));
        QCOMPARE(b->triangleTransparency(1, 1), 0.6);
        QVERIFY(b->triangleColor(2, 2).IsEqual(b->surfaceColor(2))); // the class colour
        const Quantity_Color green(0, 1, 0, Quantity_TOC_RGB);
        b->setSurface(1, green); // a rule's colour, opaque
        QVERIFY(b->triangleColor(1, 1).IsEqual(green));
        QCOMPARE(b->triangleTransparency(1, 1), 0.0);
        b->setSurface(1, std::nullopt, 0.3); // a rule's transparency alone keeps the face colours
        QVERIFY(b->triangleColor(1, 1).IsEqual(blue));
        QCOMPARE(b->triangleTransparency(1, 1), 0.3);
    }

    void parsesFaceColoursFromTheBridge()
    {
        const QByteArray meta = R"({"guids":["A"],"types":["IfcWall"],"voff":[0,3],"toff":[0,1],"palette":[[0.5,0.25,1,0.2]]})";
        QByteArray verts(9 * int(sizeof(float)), 0), tris(3 * int(sizeof(uint32_t)), 0);
        const uint32_t idx[] = {0, 1, 2};
        std::memcpy(tris.data(), idx, sizeof idx);
        QString error;
        const uint16_t ok = 0, bad = 3;
        auto c = kimbim::MeshChunk::parse(meta, verts, tris, &error, QByteArray(reinterpret_cast<const char*>(&ok), 2));
        QVERIFY2(c.has_value(), qPrintable(error));
        QCOMPARE(c->palette.size(), size_t(1));
        QCOMPARE(c->surfaceOf(0)->transparency, 0.2f);
        QVERIFY(!kimbim::MeshChunk::parse(meta, verts, tris, &error, QByteArray(reinterpret_cast<const char*>(&bad), 2)));
        QVERIFY(!kimbim::MeshChunk::parse(meta, verts, tris, &error, QByteArray(4, 0))); // two colours, one triangle
        QVERIFY(kimbim::MeshChunk::parse(meta, verts, tris, &error)->faceColors.empty()); // colours are optional
    }

    // D96: textured surfaces: the palette row names the picture and its size; faces map from the box.
    void texturedSurfaces()
    {
        kimbim::MeshChunk c = threeElements();
        c.palette = {{1, 0, 0, 0}};
        c.palette[0].texture = QStringLiteral("brick.png");
        c.palette[0].texW = 0.5f;
        c.faceColors = {0, kimbim::MeshChunk::kNoColor, 0};
        Handle(kimbim::ElementBatch) b = new kimbim::ElementBatch(c);
        QCOMPARE(b->triangleTexture(0, 0), 0);
        QCOMPARE(b->triangleTexture(1, 1), -1);
        b->setSurface(2, Quantity_Color(0, 1, 0, Quantity_TOC_RGB)); // an override colours it plainly
        QCOMPARE(b->triangleTexture(2, 2), -1);
        auto uv = kimbim::ElementBatch::boxTexel(gp_Pnt(1.0, 2.0, 3.0), gp_Dir(0, -1, 0), 0.5, 0.25); // a wall facing -y
        QCOMPARE(uv.first, 2.0);  // x / 0.5
        QCOMPARE(uv.second, 12.0); // z / 0.25
        uv = kimbim::ElementBatch::boxTexel(gp_Pnt(1.0, 2.0, 3.0), gp_Dir(0, 0, 1), 1.0, 1.0); // a floor
        QCOMPARE(uv.second, 2.0);
    }

    void acceptsShadedIdLinesAndWhiteModes()
    {
        Handle(kimbim::ElementBatch) b = new kimbim::ElementBatch(unitCube());
        QVERIFY(b->AcceptDisplayMode(kimbim::ElementBatch::Shaded));
        QVERIFY(b->AcceptDisplayMode(kimbim::ElementBatch::Ids));
        QVERIFY(b->AcceptDisplayMode(kimbim::ElementBatch::LinesOnly));
        QVERIFY(b->AcceptDisplayMode(kimbim::ElementBatch::White)); // D96
        QVERIFY(!b->AcceptDisplayMode(4));
    }

    void indexesElementsByGuid()
    {
        Handle(kimbim::ElementBatch) b = new kimbim::ElementBatch(threeElements());
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
        Handle(kimbim::ElementBatch) b = new kimbim::ElementBatch(threeElements());
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
        Handle(kimbim::ElementBatch) b = new kimbim::ElementBatch(threeElements());
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
