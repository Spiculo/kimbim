// SPDX-License-Identifier: GPL-3.0-or-later
// Several views (the 3D tab, plan tabs) of one loaded model (D71).
#include <QSignalSpy>
#include <QtTest>

#include "ElementBatch.h"
#include "Scene.h"
#include "Viewport.h"

namespace {

// n one-triangle elements g0, g1, ... (as test_selection.cpp builds them).
Handle(kimcad::ElementBatch) batch(int n)
{
    kimcad::MeshChunk c;
    c.voff.push_back(0);
    c.toff.push_back(0);
    for (int e = 0; e < n; ++e) {
        c.guids << QStringLiteral("g%1").arg(e);
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

class TestScene : public QObject {
    Q_OBJECT
private slots:
    void editAndSelectionReachEveryView()
    {
        kimcad::Scene scene;
        kimcad::Viewport model(&scene), plan(&scene);
        model.addBatch(batch(2));
        QCOMPARE(plan.elementCount(), 2); // loaded once, seen by both
        model.selectGuids({"g0"});
        QCOMPARE(plan.selectedGuids(), QStringList({"g0"}));
        QSignalSpy redraw(&scene, &kimcad::Scene::redrawRequested);
        plan.removeElements({"g1"});
        QCOMPARE(model.elementCount(), 1);
        QVERIFY(redraw.count() >= 1); // both views repaint
        plan.setHidden({"g0"}, true);
        QCOMPARE(model.visibleElementCount(), 0);
    }

    void aViewportWithoutASceneOwnsOne()
    {
        kimcad::Viewport alone;
        QVERIFY(alone.scene());
        alone.addBatch(batch(2));
        QCOMPARE(alone.elementCount(), 2);
    }

    void viewsAreCountedAndRemoved()
    {
        kimcad::Scene scene;
        QSignalSpy views(&scene, &kimcad::Scene::viewsChanged);
        {
            kimcad::Viewport a(&scene);
            kimcad::Viewport b(&scene);
            QCOMPARE(views.count(), 2);
        }
        QCOMPARE(views.count(), 4); // each destroyed view leaves the viewer
    }
};

QTEST_MAIN(TestScene)
#include "test_scene.moc"
