// SPDX-License-Identifier: GPL-3.0-or-later
// Multi-selection (owner quirk report 2026-10-05: "can't multi-select").
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QTreeWidget>
#include <QtTest>

#include "ElementBatch.h"
#include "ModelTreePanel.h"
#include "Viewport.h"

namespace {

Handle(kimbim::ElementBatch) batch(int n)
{
    kimbim::MeshChunk c;
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
    return new kimbim::ElementBatch(std::move(c));
}

QJsonObject tree()
{
    return QJsonDocument::fromJson(R"({"guid":"P","type":"IfcProject","name":"P","children":[
        {"guid":"g0","type":"IfcWall","name":"A","children":[]},
        {"guid":"g1","type":"IfcWall","name":"B","children":[]},
        {"guid":"g2","type":"IfcWall","name":"C","children":[]}]})")
        .object();
}

QStringList sorted(QStringList l)
{
    l.sort();
    return l;
}

} // namespace

class TestSelection : public QObject {
    Q_OBJECT
private slots:
    void modifiersFollowRevitAndArchicad()
    {
        kimbim::Viewport v;
        QCOMPARE(v.selectionSchemeFor(Aspect_VKeyMouse_LeftButton, Aspect_VKeyFlags_NONE), AIS_SelectionScheme_Replace);
        QCOMPARE(v.selectionSchemeFor(Aspect_VKeyMouse_LeftButton, Aspect_VKeyFlags_CTRL), AIS_SelectionScheme_Add);
        QCOMPARE(v.selectionSchemeFor(Aspect_VKeyMouse_LeftButton, Aspect_VKeyFlags_SHIFT), AIS_SelectionScheme_XOR);
    }

    void selectsSeveralElements()
    {
        kimbim::Viewport v;
        v.addBatch(batch(4));
        v.selectGuids({"g0", "g2"});
        QCOMPARE(sorted(v.selectedGuids()), QStringList({"g0", "g2"}));
    }

    void hidingDeselectsOnlyTheHiddenElements()
    {
        kimbim::Viewport v;
        v.addBatch(batch(4));
        v.selectGuids({"g0", "g1"});
        v.setHidden({"g0"}, true);
        QCOMPARE(v.selectedGuids(), QStringList({"g1"}));
    }

    void treeSelectsSeveralAndReportsThem()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(tree());
        panel.selectGuids({"g0", "g2"}); // programmatic: no echo
        QCOMPARE(sorted(panel.selectedGuids()), QStringList({"g0", "g2"}));
        QSignalSpy spy(&panel, &kimbim::ModelTreePanel::guidsSelected);
        panel.itemFor("g1")->setSelected(true); // user extends the selection
        QVERIFY(spy.count() >= 1);
        QCOMPARE(sorted(spy.last().first().toStringList()), QStringList({"g0", "g1", "g2"}));
    }
};

QTEST_MAIN(TestSelection)
#include "test_selection.moc"
