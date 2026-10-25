// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonDocument>
#include <QJsonObject>
#include <QAction>
#include <QComboBox>
#include <QJsonArray>
#include <QPushButton>
#include <QSignalSpy>
#include <QStandardPaths>
#include <QTreeWidgetItem>
#include <QtTest>

#include "MainWindow.h"
#include "PropertiesPanel.h"
#include "Viewport.h"

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


QJsonObject withChoices()
{
    const QJsonObject ref{{"value", "Centre"}, {"varies", false}, {"ifc_type", "IfcLabel"}, {"editable", true},
        {"choices", QJsonArray{"Outside face", "Centre", "Inside face"}}};
    const QJsonObject side{{"value", QJsonValue()}, {"varies", true}, {"ifc_type", "IfcLabel"}, {"editable", true},
        {"choices", QJsonArray{"(material)", "Brick"}}};
    const QJsonObject material{{"kind", "composite"}, {"value", "Exterior 300"}, {"varies", false},
        {"choices", QJsonArray{"Exterior 300", "Generic 200"}}, {"editable", true}};
    return QJsonObject{{"count", 1}, {"guids", QJsonArray{"a"}}, {"types", QJsonArray{"IfcWall"}},
        {"name", QJsonObject{{"value", "W"}, {"varies", false}}}, {"material", material},
        {"psets", QJsonObject{{"Geometry", QJsonObject{{"Reference line", ref}}},
                              {"Surfaces", QJsonObject{{"Edges", side}}}}}};
}

} // namespace

class TestPropertiesPanel : public QObject {
    Q_OBJECT
private slots:
    void updateFromLibraryButton()
    {
        kimbim::PropertiesPanel panel;
        QSignalSpy spy(&panel, &kimbim::PropertiesPanel::updateFromLibraryRequested);
        QJsonObject merged{{"count", 1}, {"guids", QJsonArray{"g"}}, {"types", QJsonArray{"IfcFurniture"}},
                           {"name", QJsonObject{{"value", "Stool"}, {"varies", false}}},
                           {"psets", QJsonObject{}}, {"library_update", 1}};
        panel.showMulti(merged);
        auto* button = panel.findChild<QPushButton*>(QStringLiteral("libraryUpdate"));
        QVERIFY(button);
        button->click();
        QCOMPARE(spy.count(), 1);
        merged.remove("library_update");
        panel.showMulti(merged);
        QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete); // the old item widgets go
        QVERIFY(!panel.findChild<QPushButton*>(QStringLiteral("libraryUpdate")));
    }

    // D96/D97: list values (reference line, surfaces, the composite) are drop-downs.
    void choicesAreDropDowns()
    {
        kimbim::PropertiesPanel panel;
        panel.showMulti(withChoices());
        auto* ref = panel.findChild<QComboBox*>("choice:Geometry/Reference line");
        QVERIFY(ref);
        QCOMPARE(ref->currentText(), QString("Centre"));
        QSignalSpy spy(&panel, &kimbim::PropertiesPanel::propertyEdited);
        ref->setCurrentIndex(ref->findData("Inside face"));
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.last().at(1).toString(), QString("Reference line"));
        QCOMPARE(spy.last().at(2).value<QJsonValue>(), QJsonValue("Inside face"));
        auto* edges = panel.findChild<QComboBox*>("choice:Surfaces/Edges");
        QCOMPARE(edges->currentText(), panel.variesText()); // varies: nothing is sent until a value is picked
        QVERIFY(panel.materialCombo());
        QSignalSpy mat(&panel, &kimbim::PropertiesPanel::materialEdited);
        panel.materialCombo()->setCurrentIndex(panel.materialCombo()->findData("Generic 200"));
        QCOMPARE(mat.count(), 1);
        QCOMPARE(mat.last().at(0).toString(), QString("composite"));
    }

    void editsEmitTypedValues()
    {
        kimbim::PropertiesPanel panel;
        panel.showMulti(sample());
        QSignalSpy spy(&panel, &kimbim::PropertiesPanel::propertyEdited);

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
        kimbim::PropertiesPanel panel;
        panel.showMulti(sample());
        QTreeWidgetItem* var = panel.itemFor("P", "Var");
        QCOMPARE(var->text(1), panel.variesText());
        QVERIFY(var->font(1).italic());
        QSignalSpy spy(&panel, &kimbim::PropertiesPanel::propertyEdited);
        var->setText(1, "x");
        QCOMPARE(spy.last().at(2).value<QJsonValue>(), QJsonValue("x"));
    }

    void quantitiesAreReadOnlyAndNameIsEditable()
    {
        kimbim::PropertiesPanel panel;
        panel.showMulti(sample());
        QVERIFY(!(panel.itemFor("P", "Area")->flags() & Qt::ItemIsEditable));
        QSignalSpy names(&panel, &kimbim::PropertiesPanel::nameEdited);
        panel.nameItem()->setText(1, "Muro nuevo");
        QCOMPARE(names.count(), 1);
        QCOMPARE(names.last().at(0).toString(), QString("Muro nuevo"));
    }

    // D50: inherited (type) values look different and the menu offers the deliberate type actions.
    void typeSourcesAreShownAndOfferTypeActions()
    {
        const QJsonObject merged = QJsonDocument::fromJson(R"({"count":1,"guids":["a"],"types":["IfcWall"],
            "name":{"value":"W","varies":false},
            "psets":{"P":{
              "FromType":{"value":0.35,"varies":false,"ifc_type":"IfcReal","editable":true,"source":"type","type_value":0.35},
              "Over":{"value":0.5,"varies":false,"ifc_type":"IfcReal","editable":true,"source":"override","type_value":0.35},
              "Own":{"value":"x","varies":false,"ifc_type":"IfcLabel","editable":true,"source":"element","type_value":null}}}})")
                                       .object();
        kimbim::PropertiesPanel panel;
        panel.showMulti(merged);
        QTreeWidgetItem* fromType = panel.itemFor("P", "FromType");
        QTreeWidgetItem* over = panel.itemFor("P", "Over");
        QTreeWidgetItem* own = panel.itemFor("P", "Own");
        QVERIFY(fromType->foreground(1).color() != own->foreground(1).color()); // inherited values are dimmed
        QVERIFY(fromType->toolTip(1).contains(panel.fromTypeText()));
        QVERIFY(over->toolTip(1).contains(QLocale().toString(0.35)));          // shows the type value it overrides

        auto names = [&](QTreeWidgetItem* item) {
            QStringList out;
            for (QAction* a : panel.actionsFor(item))
                out << a->objectName();
            return out;
        };
        QVERIFY(names(fromType).contains("editTypeValue"));
        QVERIFY(!names(fromType).contains("resetToType"));
        QVERIFY(names(over).contains("editTypeValue") && names(over).contains("resetToType"));
        QVERIFY(!names(own).contains("editTypeValue") && !names(own).contains("resetToType"));

        QSignalSpy edits(&panel, &kimbim::PropertiesPanel::typeEditRequested);
        QSignalSpy resets(&panel, &kimbim::PropertiesPanel::resetToTypeRequested);
        for (QAction* a : panel.actionsFor(over))
            if (a->objectName() == "editTypeValue" || a->objectName() == "resetToType")
                a->trigger();
        QCOMPARE(edits.count(), 1);
        QCOMPARE(resets.count(), 1);
        QCOMPARE(resets.last().at(1).toString(), QString("Over"));
    }

    void rebuildingDoesNotEmit()
    {
        kimbim::PropertiesPanel panel;
        QSignalSpy spy(&panel, &kimbim::PropertiesPanel::propertyEdited);
        panel.showMulti(sample());
        panel.showMulti(sample());
        QCOMPARE(spy.count(), 0);
    }

    // D74: the renovation status drop-down, with mixed values shown as "(varies)".
    void statusShowsAndEmits()
    {
        kimbim::PropertiesPanel panel;
        QJsonObject m = sample();
        m.insert("status", QJsonObject{{"value", QJsonValue()}, {"varies", true}});
        panel.showMulti(m);
        QComboBox* c = panel.statusCombo();
        QVERIFY(c);
        QCOMPARE(c->currentText(), panel.variesText());
        QSignalSpy spy(&panel, &kimbim::PropertiesPanel::statusEdited);
        c->setCurrentIndex(c->findData(QStringLiteral("demolish")));
        QCOMPARE(spy.count(), 1);
        QCOMPARE(spy.first().first().toString(), QStringLiteral("demolish"));
        m.insert("status", QJsonObject{{"value", "existing"}, {"varies", false}});
        panel.showMulti(m); // rebuilding doesn't emit
        QCOMPARE(spy.count(), 1);
        QVERIFY(panel.statusCombo());
        QCOMPARE(panel.statusCombo()->currentData().toString(), QStringLiteral("existing"));
        QCOMPARE(panel.statusCombo()->findText(panel.variesText()), -1);
        panel.showMulti(sample()); // no status (annotations only): no row
        QVERIFY(!panel.statusCombo());
    }

    // D100: a library object's Parameters are a read-only summary (its type first) with Edit...,
    // which is off when the selection holds more than one type.
    void parametersAreASummaryWithEdit()
    {
        QStandardPaths::setTestModeEnabled(true);
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        auto place = [&](const QString& key, QPointF p) {
            const QStringList before = w.viewport()->guids();
            if (!w.chooseObject(key) || !w.placeObjectAt(p))
                return QString();
            for (const QString& g : w.viewport()->guids())
                if (!before.contains(g))
                    return g;
            return QString();
        };
        const QString chair = place(QStringLiteral("chair"), QPointF(1, 1));
        const QString table = place(QStringLiteral("table"), QPointF(4, 1));
        QVERIFY(!chair.isEmpty() && !table.isEmpty());
        w.setTool(kimbim::MainWindow::Tool::None);
        w.setSelection({chair});
        kimbim::PropertiesPanel* panel = w.propertiesPanel();
        QTreeWidgetItem* type = panel->itemFor(QStringLiteral("Parameters"), QStringLiteral("Type"));
        QVERIFY(type);
        QCOMPARE(type->parent()->indexOfChild(type), 0);
        QVERIFY(!type->text(1).isEmpty());
        int rows = 0;
        for (int i = 0; i < type->parent()->childCount(); ++i) {
            QTreeWidgetItem* row = type->parent()->child(i);
            QVERIFY(!(row->flags() & Qt::ItemIsEditable));
            QVERIFY(row->data(1, Qt::CheckStateRole).isNull()); // no check box either
            if (!row->data(0, Qt::UserRole + 1).toString().isEmpty())
                ++rows;
        }
        QVERIFY(rows <= 7); // the type and at most 6 parameters
        // No property set behind the summary: nothing to add to it or remove from it (D100 final review).
        for (QTreeWidgetItem* item : {type, type->parent(), type->parent()->child(1)}) {
            QStringList names;
            for (QAction* a : panel->actionsFor(item))
                names << a->objectName();
            QVERIFY2(!names.contains("addProperty") && !names.contains("removeProperty"), qPrintable(names.join(',')));
        }
        for (const QComboBox* c : panel->findChildren<QComboBox*>())
            QVERIFY(!c->objectName().startsWith(QLatin1String("choice:Parameters/"))); // no inline editors
        auto* edit = panel->findChild<QPushButton*>(QStringLiteral("objectSettingsEdit"));
        QVERIFY(edit);
        QVERIFY(edit->isEnabled());
        QSignalSpy spy(panel, &kimbim::PropertiesPanel::objectSettingsRequested);
        QObject::disconnect(panel, &kimbim::PropertiesPanel::objectSettingsRequested, &w, nullptr); // no modal dialog
        edit->click();
        QCOMPARE(spy.count(), 1);

        w.setSelection({chair, table});
        QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete); // the old item widgets go
        edit = panel->findChild<QPushButton*>(QStringLiteral("objectSettingsEdit"));
        QVERIFY(edit);
        QVERIFY(!edit->isEnabled());

        // A read-only on/off reads Yes or No.
        kimbim::PropertiesPanel standalone;
        standalone.showMulti(QJsonObject{{"count", 1}, {"guids", QJsonArray{"g"}}, {"types", QJsonArray{"IfcFurniture"}},
            {"name", QJsonObject{{"value", "Chair"}, {"varies", false}}}, {"object_settings", QJsonObject{{"enabled", true}}},
            {"psets", QJsonObject{{"Parameters", QJsonObject{{"Arms", QJsonObject{{"value", true}, {"varies", false},
                {"ifc_type", "IfcBoolean"}, {"editable", false}}}}}}}});
        QCOMPARE(standalone.itemFor(QStringLiteral("Parameters"), QStringLiteral("Arms"))->text(1), QStringLiteral("Yes"));
    }
};

QTEST_MAIN(TestPropertiesPanel)
#include "test_properties_panel.moc"
