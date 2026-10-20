// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonArray>
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
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QCOMPARE(panel.itemCount(), 7);
        QVERIFY(panel.selectGuid("W1"));
        QCOMPARE(panel.currentGuid(), QString("W1"));
        QVERIFY(!panel.selectGuid("unknown"));
        QCOMPARE(panel.displayName("W2"), QString("Wall")); // unnamed elements show a plain name
    }

    // D71: less noise. Project › Site › Building in one row, no Type column, elements grouped by
    // category under their level.
    void singleChildSpatialRowsAreMerged()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QCOMPARE(panel.tree()->topLevelItemCount(), 1);
        QTreeWidgetItem* top = panel.tree()->topLevelItem(0);
        QCOMPARE(top->text(0), QString("Edificio"));
        QCOMPARE(panel.itemFor("P"), top);
        QCOMPARE(panel.itemFor("S"), top);
        QVERIFY(top->toolTip(0).contains("Casa") && top->toolTip(0).contains("Sitio"));
        QCOMPARE(panel.itemFor("L1")->parent(), top);
        QCOMPARE(panel.tree()->columnCount(), 1);
    }

    void elementsAreGroupedByCategoryUnderALevel()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QTreeWidgetItem* level = panel.itemFor("L1");
        QCOMPARE(level->childCount(), 2);
        QCOMPARE(level->child(0)->text(0), QString("Doors (1)"));
        QCOMPARE(level->child(1)->text(0), QString("Walls (2)"));
        QCOMPARE(panel.itemFor("W1")->parent(), level->child(1));
        panel.tree()->clearSelection();
        level->child(1)->setSelected(true); // a group row selects nothing itself
        QVERIFY(panel.selectedGuids().isEmpty());
        QStringList g = panel.descendantGuids("L1");
        g.sort();
        QCOMPARE(g, QStringList({"D1", "L1", "W1", "W2"}));
    }

    void twoBuildingsAreNotMerged()
    {
        QJsonObject root = sampleTree();
        QJsonArray sites = root["children"].toArray();
        QJsonObject site = sites[0].toObject();
        QJsonArray buildings = site["children"].toArray();
        buildings.append(QJsonObject{{"guid", "B2"}, {"type", "IfcBuilding"}, {"name", "Anexo"}, {"children", QJsonArray()}});
        site["children"] = buildings;
        sites[0] = site;
        root["children"] = sites;
        kimbim::ModelTreePanel panel;
        panel.setTree(root);
        QTreeWidgetItem* top = panel.tree()->topLevelItem(0);
        QCOMPARE(top->text(0), QString("Sitio")); // Casa › Sitio merged, then two buildings
        QCOMPARE(top->childCount(), 2);
    }

    void typeStillSearchableAndInTheHint()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QVERIFY(panel.hintFor("W1").contains("IfcWall"));
        QCOMPARE(panel.ifcTypeOf("W2"), QString("IfcWall"));
        QCOMPARE(kimbim::ModelTreePanel::plainName("IfcWallStandardCase"), QString("Wall"));
        QCOMPARE(kimbim::ModelTreePanel::plainPlural("IfcSpace"), QString("Rooms"));
    }

    void doubleClickActivates()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QSignalSpy spy(&panel, &kimbim::ModelTreePanel::guidActivated);
        emit panel.tree()->itemDoubleClicked(panel.itemFor("W1"), 0);
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.first().first().toString(), QString("W1"));
        emit panel.tree()->itemDoubleClicked(panel.itemFor("L1")->child(0), 0); // a category row
        QCOMPARE(spy.count(), 1);
    }

    void expandedGroupsSurviveARefresh()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QTreeWidgetItem* walls = panel.itemFor("L1")->child(1);
        walls->setExpanded(true);
        panel.refreshTree(sampleTree());
        QVERIFY(panel.itemFor("L1")->child(1)->isExpanded());
    }

    void userSelectionEmitsGuids()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QSignalSpy spy(&panel, &kimbim::ModelTreePanel::guidsSelected);
        panel.tree()->setCurrentItem(panel.itemFor("D1"));
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.first().first().toStringList(), QStringList({"D1"}));
        // programmatic selection (from the viewport) must NOT echo back
        panel.selectGuid("W1");
        QCOMPARE(spy.count(), 1);
    }

    void filterKeepsMatchesAndTheirParents()
    {
        kimbim::ModelTreePanel panel;
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
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        const QIcon wall = panel.itemFor("W1")->icon(0);
        QVERIFY(!wall.pixmap(16).isNull());
        QCOMPARE(panel.itemFor("W2")->icon(0).cacheKey(), kimbim::iconFor("IfcWallStandardCase").cacheKey());
        QVERIFY(panel.itemFor("D1")->icon(0).cacheKey() != wall.cacheKey());
        QVERIFY(!panel.itemFor("L1")->icon(0).isNull());
        QVERIFY(!kimbim::iconFor("IfcFurnishingElement").pixmap(16).isNull()); // a generic icon
    }

    void hoverHintNamesTypeAndLevel()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        const QString hint = panel.hintFor("W1");
        QVERIFY(hint.contains("Muro Ñandú") && hint.contains("IfcWall") && hint.contains("Planta baja"));
        QVERIFY(panel.hintFor("nope").isEmpty());
    }

    void storeyGuidsCollectsDescendants()
    {
        kimbim::ModelTreePanel panel;
        panel.setTree(sampleTree());
        QStringList g = panel.descendantGuids("L1");
        g.sort();
        QCOMPARE(g, QStringList({"D1", "L1", "W1", "W2"}));
    }
};

QTEST_MAIN(TestModelTree)
#include "test_model_tree.moc"
