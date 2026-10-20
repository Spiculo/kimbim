// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonArray>
#include <QJsonDocument>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QPushButton>
#include <QtTest>

#include "Graphics.h"
#include "GraphicsDialogs.h"
#include "PythonEngine.h"
#include "PenGrid.h"

namespace {
// The graphics_tables reply (the built-ins), as the Graphics menu passes it to the editors.
QJsonObject tablesFromBridge()
{
    QString error;
    kimbim::PythonEngine::instance().start(&error);
    kimbim::PythonEngine::instance().callJson("set_project_settings", {QStringLiteral("{}")}, &error);
    return kimbim::PythonEngine::instance().callJson("graphics_tables", {}, &error).object();
}
} // namespace

class TestGraphics : public QObject {
    Q_OBJECT
private slots:
    void parsesStylesHiddenAndPens()
    {
        const QByteArray json = R"({"ok": true, "purpose": "Working", "current_pen": 26, "annotation_pen": 23,
            "pens": {"26": {"color": "#e02020", "weight": 0.5}},
            "styles": [{"cut": {"color": "#111111", "weight": 0.5, "dash": []},
                        "projection": {"color": "#222222", "weight": 0.18, "dash": [3.0, 1.5]},
                        "fill": "#333333", "surface": "#445566", "transparency": 0.5}],
            "elements": {"W1": 0}, "hidden": ["F1"]})";
        const auto g = kimbim::Graphics::fromJson(QJsonDocument::fromJson(json).object());
        QCOMPARE(g.purpose(), QString("Working"));
        QCOMPARE(g.currentPen(), 26);
        const kimbim::ElementStyle* s = g.styleOf("W1");
        QVERIFY(s);
        QCOMPARE(s->cut.color, QColor("#111111"));
        QCOMPARE(s->projection.dash, (QVector<double>{3.0, 1.5}));
        QCOMPARE(s->fill, QColor("#333333"));
        QCOMPARE(*s->surface, QColor("#445566"));
        QCOMPARE(*s->transparency, 0.5);
        QVERIFY(!g.styleOf("nope"));
        QVERIFY(g.isHidden("F1"));
        QCOMPARE(g.pen(26).color, QColor("#e02020"));
        QCOMPARE(g.pen(99).color, QColor(Qt::black)); // missing: fallback
        QCOMPARE(g.pen(99).weight, 0.18);
    }
    void badInputGivesAnEmptyState()
    {
        const auto g = kimbim::Graphics::fromJson(QJsonObject{{"ok", false}});
        QVERIFY(g.isEmpty());
        QCOMPARE(g.currentPen(), 23);
        const auto bad = kimbim::Graphics::fromJson(QJsonDocument::fromJson(
            R"({"ok": true, "styles": [], "elements": {"W1": 5}})").object());
        QVERIFY(!bad.styleOf("W1")); // index out of range is ignored
    }
    void pixelsAndPatterns()
    {
        QCOMPARE(kimbim::Graphics::pixels(0.5, false), 1.0f);
        QCOMPARE(kimbim::Graphics::pixels(0.5, true), 2.0f);
        QCOMPARE(kimbim::Graphics::pixels(0.13, true), 1.0f);
        QCOMPARE(kimbim::Graphics::pixels(5.0, true), 6.0f);
        QCOMPARE(kimbim::Graphics::pattern({}), uint16_t(0xFFFF));
        QVERIFY(kimbim::Graphics::pattern({3.0, 1.5}) != 0xFFFF);
        QVERIFY(kimbim::Graphics::pattern({3.0, 1.5}) != 0);
    }
    void parsesPenNames()
    {
        // (built in code: a raw string literal here made moc skip the whole file)
        const QJsonObject state{{"ok", true},
            {"pens", QJsonObject{{"23", QJsonObject{{"color", "#000000"}, {"weight", 0.18}}}}},
            {"pen_names", QJsonObject{{"23", "Annotations"}}}};
        const auto g = kimbim::Graphics::fromJson(state);
        QCOMPARE(g.penNames().value(23), QString("Annotations"));
        QCOMPARE(g.pens().value(23).weight, 0.18);
    }
    void penGridClicksReportThePen()
    {
        kimbim::PenGrid grid;
        grid.resize(16 * 20, 16 * 20);
        QSignalSpy clicked(&grid, &kimbim::PenGrid::penClicked);
        QTest::mouseClick(&grid, Qt::LeftButton, {}, QPoint(20 * 7 + 10, 20 * 1 + 10)); // row 1, col 7 = pen 23
        QCOMPARE(clicked.count(), 1);
        QCOMPARE(clicked.at(0).at(0).toInt(), 23);
        QCOMPARE(grid.current(), 23);
        QTest::mouseClick(&grid, Qt::LeftButton, {}, QPoint(10, 10)); // cell 0: no pen
        QCOMPARE(clicked.count(), 1);
        QCOMPARE(kimbim::PenGrid::penAt(QSize(320, 320), QPoint(319, 319)), 255);
    }
    void penSetsDialogReportsOnlyChangedTables()
    {
        kimbim::PenSetsDialog d(tablesFromBridge(), nullptr);
        QVERIFY(d.changes().isEmpty());
        d.selectSet(QStringLiteral("Permit"));
        d.selectPen(10);
        QCOMPARE(d.findChild<QDoubleSpinBox*>(QStringLiteral("penWeight"))->value(), 0.5);
        d.setPenColor(QColor("#123456"));
        const QJsonObject c = d.changes();
        QCOMPARE(c.keys(), QStringList{"pen_sets"});
        QCOMPARE(c.value("pen_sets").toObject().value("Permit").toObject().value("pens").toObject()
                     .value("10").toObject().value("color").toString(), QString("#123456"));
    }
    void penSetsCanBeCopiedRenamedAndDeleted()
    {
        kimbim::PenSetsDialog d(tablesFromBridge(), nullptr);
        d.selectSet(QStringLiteral("Permit"));
        QVERIFY(d.copySetAs(QStringLiteral("Office")));
        QVERIFY(!d.copySetAs(QStringLiteral("Office"))); // names are unique
        QVERIFY(d.renameSetTo(QStringLiteral("Office B&W")));
        d.selectSet(QStringLiteral("Working"));
        QVERIFY(d.renameSetTo(QStringLiteral("Daily")));
        const QJsonObject c = d.changes();
        QVERIFY(c.value("pen_sets").toObject().contains("Office B&W"));
        QVERIFY(!c.value("pen_sets").toObject().contains("Working"));
        // the purposes that used the renamed set follow it
        QCOMPARE(c.value("purposes").toObject().value("Working").toObject().value("pen_set").toString(), QString("Daily"));
        d.selectSet(QStringLiteral("Daily"));
        QVERIFY(d.deleteCurrentSet());
        QVERIFY(c.value("purposes").toObject().contains("Working"));
        QVERIFY(d.changes().value("purposes").toObject().value("Working").toObject().value("pen_set").toString() != "Daily");
    }
    void theLastPenSetCannotBeDeleted()
    {
        QJsonObject reply = tablesFromBridge();
        QJsonObject tables = reply.value("tables").toObject();
        tables.insert("pen_sets", QJsonObject{{"Only", tables.value("pen_sets").toObject().value("Permit")}});
        QJsonObject purposes;
        for (const QString& name : tables.value("purposes").toObject().keys()) {
            QJsonObject p = tables.value("purposes").toObject().value(name).toObject();
            p.insert("pen_set", "Only");
            purposes.insert(name, p);
        }
        tables.insert("purposes", purposes);
        reply.insert("tables", tables);
        kimbim::PenSetsDialog d(reply, nullptr);
        QVERIFY(!d.findChild<QPushButton*>(QStringLiteral("deleteSet"))->isEnabled());
        QVERIFY(!d.deleteCurrentSet());
    }
    void lineTypesRefuseBadPatterns()
    {
        kimbim::LineTypesDialog d(tablesFromBridge(), nullptr);
        QVERIFY(!d.setPattern(QStringLiteral("Dashed"), QStringLiteral("3 1.5 2"))); // dashes and gaps in pairs
        QVERIFY(!d.okEnabled());
        QVERIFY(!d.setPattern(QStringLiteral("Dashed"), QStringLiteral("3 -1")));
        QVERIFY(d.setPattern(QStringLiteral("Dashed"), QStringLiteral("4 2")));
        QVERIFY(d.okEnabled());
        QCOMPARE(d.changes().value("line_types").toObject().value("Dashed").toArray(), (QJsonArray{4.0, 2.0}));
        QVERIFY(!d.setPattern(QStringLiteral("Solid"), QStringLiteral("1 1"))); // Solid stays solid
        QVERIFY(d.addLineType(QStringLiteral("Long dash"), QStringLiteral("10 2")));
        QVERIFY(!d.addLineType(QStringLiteral("Long dash"), QStringLiteral("10 2")));
        QVERIFY(d.changes().value("line_types").toObject().contains("Long dash"));
    }
    void elementStylesChangeAPenAndALine()
    {
        kimbim::ElementStylesDialog d(tablesFromBridge(), nullptr);
        QVERIFY(d.changes().isEmpty());
        d.setCutPen(QStringLiteral("walls"), 7);
        d.setProjectionLine(QStringLiteral("furniture"), QStringLiteral("Dashed"));
        const QJsonObject styles = d.changes().value("element_styles").toObject();
        QCOMPARE(styles.value("walls").toObject().value("cut").toObject().value("pen").toInt(), 7);
        QCOMPARE(styles.value("furniture").toObject().value("projection").toObject().value("line").toString(), QString("Dashed"));
        QCOMPARE(styles.keys().size(), 19); // every kind stays in the table
    }
    void visibilityHidesKindsAndKeepsRules()
    {
        kimbim::VisibilitySetsDialog d(tablesFromBridge(), nullptr);
        d.selectSet(QStringLiteral("Everything"));
        d.setKindHidden(QStringLiteral("furniture"), true);
        d.addRule(QJsonObject{{"name", "Not load-bearing"},
            {"when", QJsonObject{{"property", "LoadBearing"}, {"op", "false"}}}, {"then", QJsonObject{{"hide", true}}}});
        const QJsonObject set = d.changes().value("visibility_sets").toObject().value("Everything").toObject();
        QCOMPARE(set.value("hidden_kinds").toArray(), QJsonArray{"furniture"});
        QCOMPARE(set.value("rules").toArray().size(), 1);
        d.setKindHidden(QStringLiteral("furniture"), false);
        QVERIFY(d.changes().value("visibility_sets").toObject().value("Everything").toObject()
                    .value("hidden_kinds").toArray().isEmpty());
    }
    void overrideRulesKeepTheirOrder()
    {
        kimbim::OverridesDialog d(tablesFromBridge(), nullptr);
        d.selectSet(QStringLiteral("Fire rating"));
        d.moveRule(3, 0);
        d.setRuleEnabled(1, false);
        const QJsonArray rules = d.changes().value("override_sets").toObject().value("Fire rating").toObject()
                                     .value("rules").toArray();
        QCOMPARE(rules.at(0).toObject().value("name").toString(), QString("30 min"));
        QCOMPARE(rules.at(1).toObject().value("enabled").toBool(true), false);
        QCOMPARE(rules.size(), 4);
    }
    void ruleEditorRoundTrips()
    {
        kimbim::RuleEditor e(QStringList{"walls", "slabs"}, QStringList{"Solid", "Dashed"});
        const QJsonObject rule{{"name", "x"}, {"when", QJsonObject{{"kind", "walls"}, {"property", "FireRating"},
            {"op", "contains"}, {"value", "60"}}}, {"then", QJsonObject{{"pen", 26}, {"surface", "#e05040"}, {"line", "Dashed"}}}};
        e.setRule(rule);
        QCOMPARE(e.rule(), rule);
        const QJsonObject hide{{"name", "h"}, {"when", QJsonObject{{"layer", "A-Furniture"}}}, {"then", QJsonObject{{"hide", true}}},
            {"enabled", false}};
        e.setRule(hide);
        QCOMPARE(e.rule(), hide);
    }
    void purposesPickTheirPieces()
    {
        kimbim::PurposesDialog d(tablesFromBridge(), nullptr);
        d.selectSet(QStringLiteral("Permit"));
        d.setPieces(QStringLiteral("Presentation"), QStringLiteral("No furniture"), QStringLiteral("None"),
            QStringLiteral("All visible"));
        const QJsonObject p = d.changes().value("purposes").toObject().value("Permit").toObject();
        QCOMPARE(p.value("pen_set").toString(), QString("Presentation"));
        QCOMPARE(p.value("visibility").toString(), QString("No furniture"));
        QCOMPARE(p.value("layers").toString(), QString("All visible"));
        d.setPieces(QStringLiteral("Permit"), QStringLiteral("No furniture"), QStringLiteral("None"), QString());
        QVERIFY(d.changes().value("purposes").toObject().value("Permit").toObject().value("layers").isNull());
    }
    // D74: the renovation filter editor writes valid tables.
    void renovationFilterEditorWritesValidTables()
    {
        kimbim::RenovationFiltersDialog d(tablesFromBridge(), nullptr);
        d.selectSet(QStringLiteral("Demolition plan"));
        d.setShow(QStringLiteral("new"), QStringLiteral("as_is"));
        d.setShow(QStringLiteral("existing"), QStringLiteral("override"));
        d.setOverridePen(QStringLiteral("existing"), 31);
        d.setOverrideLine(QStringLiteral("existing"), QStringLiteral("Dotted"));
        d.setOverrideFill(QStringLiteral("existing"), 33);
        d.setOverrideSurface(QStringLiteral("existing"), QColor("#102030"));
        const QJsonObject flt = d.changes().value("renovation_filters").toObject().value("Demolition plan").toObject();
        QCOMPARE(flt.value("new").toObject(), (QJsonObject{{"show", "as_is"}}));
        const QJsonObject ex = flt.value("existing").toObject();
        QCOMPARE(ex.value("show").toString(), QString("override"));
        QCOMPARE(ex.value("pen").toInt(), 31);
        QCOMPARE(ex.value("line").toString(), QString("Dotted"));
        QCOMPARE(ex.value("fill").toInt(), 33);
        QCOMPARE(ex.value("surface").toString(), QString("#102030"));
        d.setShow(QStringLiteral("existing"), QStringLiteral("hide")); // hiding drops the override fields
        QCOMPARE(d.changes().value("renovation_filters").toObject().value("Demolition plan").toObject()
                     .value("existing").toObject(), (QJsonObject{{"show", "hide"}}));
        QString error;
        const QJsonObject r = kimbim::PythonEngine::instance()
                                  .callJson("set_graphics", {QString::fromUtf8(QJsonDocument(d.changes()).toJson())}, &error)
                                  .object();
        QVERIFY2(r.value("ok").toBool(), qPrintable(r.value("error").toString()));
    }
    void purposesHaveARenovationFilter()
    {
        kimbim::PurposesDialog d(tablesFromBridge(), nullptr);
        d.selectSet(QStringLiteral("Working"));
        auto* c = d.findChild<QComboBox*>(QStringLiteral("renovationOf"));
        QVERIFY(c);
        QCOMPARE(c->currentData().toString(), QString("Everything"));
        c->setCurrentIndex(c->findData(QStringLiteral("New plan")));
        QCOMPARE(d.changes().value("purposes").toObject().value("Working").toObject().value("renovation").toString(),
            QString("New plan"));
        d.setPieces(QStringLiteral("Permit"), QStringLiteral("Everything"), QStringLiteral("None"), QString());
        QCOMPARE(d.changes().value("purposes").toObject().value("Working").toObject().value("renovation").toString(),
            QString("New plan")); // the four-piece call keeps the filter
    }
    void legendParsed()
    {
        const auto g = kimbim::Graphics::fromJson(QJsonObject{{"ok", true}, {"styles", QJsonArray{}}, {"legend", QJsonArray{
            QJsonObject{{"label", "To be demolished"}, {"source", "renovation"}, {"key", "demolish"}, {"style", 0}}}}});
        QCOMPARE(g.legend().size(), 1);
        QCOMPARE(g.legend().first().key, QString("demolish"));
        QCOMPARE(g.legend().first().source, QString("renovation"));
        QCOMPARE(g.legend().first().style, 0);
    }
    void layerCombinationsTakeTheCurrentLayers()
    {
        kimbim::LayerCombinationsDialog d(tablesFromBridge(), {"A-Wall", "A-Furniture"}, {"A-Furniture"}, {"A-Wall"}, nullptr);
        d.selectSet(QStringLiteral("All visible"));
        d.takeCurrent();
        QJsonObject c = d.changes().value("layer_combinations").toObject().value("All visible").toObject();
        QCOMPARE(c.value("hidden").toArray(), QJsonArray{"A-Furniture"});
        QCOMPARE(c.value("locked").toArray(), QJsonArray{"A-Wall"});
        d.setShown(QStringLiteral("A-Furniture"), true);
        d.setLocked(QStringLiteral("A-Wall"), false);
        c = d.changes().value("layer_combinations").toObject().value("All visible").toObject();
        QVERIFY(c.value("hidden").toArray().isEmpty() && c.value("locked").toArray().isEmpty());
    }
};

QTEST_MAIN(TestGraphics)
#include "test_graphics.moc"
