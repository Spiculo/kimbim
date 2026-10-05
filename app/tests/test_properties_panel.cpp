// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonDocument>
#include <QJsonObject>
#include <QSignalSpy>
#include <QTreeWidgetItem>
#include <QtTest>

#include "PropertiesPanel.h"

namespace {

QJsonObject sample()
{
    return QJsonDocument::fromJson(R"({"count":2,"guids":["a","b"],"types":["IfcWall"],
        "name":{"value":"Muro","varies":false},
        "psets":{"P":{
          "Txt":{"value":"a","varies":false,"ifc_type":"IfcLabel","editable":true},
          "Num":{"value":1.5,"varies":false,"ifc_type":"IfcReal","editable":true},
          "Flag":{"value":true,"varies":false,"ifc_type":"IfcBoolean","editable":true},
          "Var":{"value":null,"varies":true,"ifc_type":"IfcLabel","editable":true},
          "Area":{"value":12.0,"varies":false,"ifc_type":"IfcQuantityArea","editable":false}}}})")
        .object();
}

} // namespace

class TestPropertiesPanel : public QObject {
    Q_OBJECT
private slots:
    void editsEmitTypedValues()
    {
        kimcad::PropertiesPanel panel;
        panel.showMulti(sample());
        QSignalSpy spy(&panel, &kimcad::PropertiesPanel::propertyEdited);

        panel.itemFor("P", "Txt")->setText(1, "b");
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.last().at(0).toString(), QString("P"));
        QCOMPARE(spy.last().at(1).toString(), QString("Txt"));
        QCOMPARE(spy.last().at(2).value<QJsonValue>(), QJsonValue("b"));

        panel.itemFor("P", "Num")->setText(1, "2.5");
        QCOMPARE(spy.last().at(2).value<QJsonValue>(), QJsonValue(2.5)); // number stays a number

        panel.itemFor("P", "Flag")->setCheckState(1, Qt::Unchecked);
        QCOMPARE(spy.last().at(2).value<QJsonValue>(), QJsonValue(false)); // bool stays a bool
    }

    void variesIsShownAndCanBeOverwritten()
    {
        kimcad::PropertiesPanel panel;
        panel.showMulti(sample());
        QTreeWidgetItem* var = panel.itemFor("P", "Var");
        QCOMPARE(var->text(1), panel.variesText());
        QVERIFY(var->font(1).italic());
        QSignalSpy spy(&panel, &kimcad::PropertiesPanel::propertyEdited);
        var->setText(1, "x");
        QCOMPARE(spy.last().at(2).value<QJsonValue>(), QJsonValue("x"));
    }

    void quantitiesAreReadOnlyAndNameIsEditable()
    {
        kimcad::PropertiesPanel panel;
        panel.showMulti(sample());
        QVERIFY(!(panel.itemFor("P", "Area")->flags() & Qt::ItemIsEditable));
        QSignalSpy names(&panel, &kimcad::PropertiesPanel::nameEdited);
        panel.nameItem()->setText(1, "Muro nuevo");
        QCOMPARE(names.count(), 1);
        QCOMPARE(names.last().at(0).toString(), QString("Muro nuevo"));
    }

    void rebuildingDoesNotEmit()
    {
        kimcad::PropertiesPanel panel;
        QSignalSpy spy(&panel, &kimcad::PropertiesPanel::propertyEdited);
        panel.showMulti(sample());
        panel.showMulti(sample());
        QCOMPARE(spy.count(), 0);
    }
};

QTEST_MAIN(TestPropertiesPanel)
#include "test_properties_panel.moc"
