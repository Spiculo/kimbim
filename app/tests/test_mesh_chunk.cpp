// SPDX-License-Identifier: GPL-3.0-or-later
#include <QtTest>

#include "MeshChunk.h"

namespace {

QByteArray floats(std::initializer_list<float> v)
{
    QByteArray b(int(v.size() * sizeof(float)), Qt::Uninitialized);
    std::memcpy(b.data(), std::data(v), b.size());
    return b;
}

QByteArray uints(std::initializer_list<uint32_t> v)
{
    QByteArray b(int(v.size() * sizeof(uint32_t)), Qt::Uninitialized);
    std::memcpy(b.data(), std::data(v), b.size());
    return b;
}

// Element A: 3 vertices, 1 triangle. Element B: 4 vertices, 2 triangles (chunk-local indices).
const QByteArray kMeta = R"({"guids":["A","B"],"types":["IfcWall","IfcSlab"],"voff":[0,3,7],"toff":[0,1,3]})";
QByteArray verts() { return floats({0,0,0, 1,0,0, 0,1,0,  0,0,1, 1,0,1, 1,1,1, 0,1,1}); }
QByteArray tris() { return uints({0,1,2,  3,4,5, 3,5,6}); }

} // namespace

class TestMeshChunk : public QObject {
    Q_OBJECT
private slots:
    void parsesAValidChunk()
    {
        QString error;
        auto c = kimbim::MeshChunk::parse(kMeta, verts(), tris(), &error);
        QVERIFY2(c.has_value(), qPrintable(error));
        QCOMPARE(c->elementCount(), 2);
        QCOMPARE(c->guids, QStringList({"A", "B"}));
        QCOMPARE(c->types.at(1), QString("IfcSlab"));
        QCOMPARE(c->vertexCount(), 7);
        QCOMPARE(c->triangleCount(), 3);
        QCOMPARE(c->toff.at(1), 1u);
        QCOMPARE(c->verts.at(3 * 4 + 2), 1.0f); // z of vertex 4
    }

    void rejectsInconsistentData()
    {
        QString error;
        QVERIFY(!kimbim::MeshChunk::parse(kMeta, verts().left(10), tris(), &error)); // not whole floats
        QVERIFY(!kimbim::MeshChunk::parse(kMeta, verts(), tris().left(24), &error)); // offsets beyond data
        QVERIFY(!kimbim::MeshChunk::parse(kMeta, verts(), uints({0,1,2, 3,4,5, 3,5,99}), &error)); // index out of range
        QVERIFY(error.contains("index"));
        QVERIFY(!kimbim::MeshChunk::parse(R"({"guids":["A"],"types":["IfcWall","IfcSlab"],"voff":[0,3,7],"toff":[0,1,3]})",
            verts(), tris(), &error)); // counts disagree
        QVERIFY(!kimbim::MeshChunk::parse("not json", verts(), tris(), &error));
    }
};

QTEST_MAIN(TestMeshChunk)
#include "test_mesh_chunk.moc"
