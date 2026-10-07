// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QTreeWidget>
#include <QIcon>
#include <QtTest>

#include "Icons.h"
#include "ModelTreePanel.h"

namespace {

QJsonObject sampleTree()
{
    return QJsonDocument::fromJson(R"({"guid":"P","type":"IfcProject","name":"Casa","children":[
        {"guid":"S","type":"IfcSite","name":"Sitio","children":[
          {"guid":"B","type":"IfcBuilding","name":"Edificio","children":[
            {"guid":"L1","type":"IfcBuildingStorey","name":"Planta baja","children":[
              {"guid":"W1","type":"IfcWall","name":"Muro Ñandú","children":[]},
              {"guid":"W2","type":"IfcWall","name":"","children":[]},
              {"guid":"D1","type":"IfcDoor","name":"Puerta 1","children":[]}]}]}]}]})")
        .object();
}

} // namespace

class TestModelTree : public QObject {
    Q_OBJECT
private slots:
    void buildsTheTreeAndFindsElements()
    {
        kimcad::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QCOMPARE(panel.itemCount(), 7);
        QVERIFY(panel.selectGuid("W1"));
        QCOMPARE(panel.currentGuid(), QString("W1"));
        QVERIFY(!panel.selectGuid("unknown"));
        QCOMPARE(panel.displayName("W2"), QString("IfcWall")); // unnamed elements show their type
    }

    void userSelectionEmitsGuids()
    {
        kimcad::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QSignalSpy spy(&panel, &kimcad::ModelTreePanel::guidsSelected);
        panel.tree()->setCurrentItem(panel.itemFor("D1"));
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.first().first().toStringList(), QStringList({"D1"}));
        // programmatic selection (from the viewport) must NOT echo back
        panel.selectGuid("W1");
        QCOMPARE(spy.count(), 1);
    }

    void filterKeepsMatchesAndTheirParents()
    {
        kimcad::ModelTreePanel panel;
        panel.setTree(sampleTree());
        panel.setFilter("ñandú"); // case-insensitive, non-ASCII
        QVERIFY(!panel.itemFor("W1")->isHidden());
        QVERIFY(!panel.itemFor("L1")->isHidden()); // parent of a match stays visible
        QVERIFY(panel.itemFor("D1")->isHidden());
        panel.setFilter("IfcDoor"); // matches type
        QVERIFY(!panel.itemFor("D1")->isHidden());
        QVERIFY(panel.itemFor("W1")->isHidden());
        panel.setFilter("");
        QVERIFY(!panel.itemFor("W2")->isHidden());
    }

    // Owner feedback: objects get an icon (per kind of element) and a hint on hover.
    void itemsHaveIconsByKind()
    {
        kimcad::ModelTreePanel panel;
        panel.setTree(sampleTree());
        const QIcon wall = panel.itemFor("W1")->icon(0);
        QVERIFY(!wall.pixmap(16).isNull());
        QCOMPARE(panel.itemFor("W2")->icon(0).cacheKey(), kimcad::iconFor("IfcWallStandardCase").cacheKey());
        QVERIFY(panel.itemFor("D1")->icon(0).cacheKey() != wall.cacheKey());
        QVERIFY(!panel.itemFor("L1")->icon(0).isNull());
        QVERIFY(!kimcad::iconFor("IfcFurnishingElement").pixmap(16).isNull()); // a generic icon
    }

    void hoverHintNamesTypeAndLevel()
    {
        kimcad::ModelTreePanel panel;
        panel.setTree(sampleTree());
        const QString hint = panel.hintFor("W1");
        QVERIFY(hint.contains("Muro Ñandú") && hint.contains("IfcWall") && hint.contains("Planta baja"));
        QVERIFY(panel.hintFor("nope").isEmpty());
    }

    void storeyGuidsCollectsDescendants()
    {
        kimcad::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QStringList g = panel.descendantGuids("L1");
        g.sort();
        QCOMPARE(g, QStringList({"D1", "L1", "W1", "W2"}));
    }
};

QTEST_MAIN(TestModelTree)
#include "test_model_tree.moc"
