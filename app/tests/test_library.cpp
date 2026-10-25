// SPDX-License-Identifier: GPL-3.0-or-later
// D86: the Library panel and the Object tool: list and search objects, place one with the tool
// (turned with Tab or a typed angle), edit its parameters in Properties, undo it as one step.
#include <QAction>
#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QJsonDocument>
#include <QLineEdit>
#include <QMenu>
#include <QSignalSpy>
#include <QStandardPaths>
#include <QTreeWidget>
#include <QtTest>

#include "LibraryPanel.h"
#include "MainWindow.h"
#include "ObjectSettingsDialog.h"
#include "PythonEngine.h"
#include "StatusStrip.h"
#include "ToolPalette.h"
#include "Viewport.h"

namespace {

QAction* action(kimbim::MainWindow& w, const char* name)
{
    QAction* a = w.findChild<QAction*>(QString::fromLatin1(name));
    if (!a)
        qFatal("missing action %s", name);
    return a;
}

QStringList added(const QStringList& before, const QStringList& now)
{
    QStringList out;
    for (const QString& g : now)
        if (!before.contains(g))
            out << g;
    return out;
}

QString saveVersion(const QString& key, const QString& name, const QJsonObject& values)
{
    return kimbim::PythonEngine::instance()
        .callJson("save_object_version", {key, name, QString::fromUtf8(QJsonDocument(values).toJson(QJsonDocument::Compact))})
        .object().value("id").toString();
}

QJsonObject versionNamed(const QString& key, const QString& name)
{
    const QJsonObject r = kimbim::PythonEngine::instance().callJson("object_versions", {key}).object();
    for (const auto& v : r.value("versions").toArray())
        if (v.toObject().value("name").toString() == name)
            return v.toObject();
    return {};
}

QString itemText(kimbim::LibraryPanel* panel, const QString& id)
{
    QTreeWidget* tree = panel->tree();
    for (int i = 0; i < tree->topLevelItemCount(); ++i)
        for (int j = 0; j < tree->topLevelItem(i)->childCount(); ++j)
            if (tree->topLevelItem(i)->child(j)->data(0, Qt::UserRole + 1).toString() == id)
                return tree->topLevelItem(i)->child(j)->text(0);
    return {};
}

double placedWidth(const QString& guid)
{
    const QJsonObject multi = kimbim::PythonEngine::instance()
        .callJson("properties_multi", {QStringLiteral("[\"%1\"]").arg(guid)}).object();
    return multi.value("psets").toObject().value("Parameters").toObject().value("Width").toObject().value("value").toDouble();
}

} // namespace

class TestLibrary : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { QStandardPaths::setTestModeEnabled(true); }

    void panelListsAndSearches()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        action(w, "actionObjectLibrary")->trigger();
        kimbim::LibraryPanel* panel = w.libraryPanel();
        QVERIFY(panel->visibleObjectCount() >= 21);
        panel->findChild<QLineEdit*>(QStringLiteral("librarySearch"))->setText(QStringLiteral("bed"));
        QCOMPARE(panel->visibleObjectCount(), 2); // single and double bed
        panel->setFilter(QString());
        QVERIFY(panel->selectObject(QStringLiteral("sofa")));
        QCOMPARE(panel->currentObject(), QStringLiteral("sofa"));
        QVERIFY(!panel->findChild<QWidget*>(QStringLiteral("libraryPlace"))); // no inline form or Place button
        QVERIFY(!panel->findChild<kimbim::ParameterForm*>());
        QSignalSpy place(panel, &kimbim::LibraryPanel::placeRequested);
        QSignalSpy settings(panel, &kimbim::LibraryPanel::settingsRequested);
        QTreeWidgetItem* sofa = panel->tree()->currentItem();
        QVERIFY(sofa);
        emit panel->tree()->itemClicked(sofa, 0); // a click places
        QCOMPARE(place.count(), 1);
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::Object);
        w.setTool(kimbim::MainWindow::Tool::None);
        // a right click: the Object settings dialog (asked for; the window opens it)
        QObject::disconnect(panel, &kimbim::LibraryPanel::settingsRequested, &w, nullptr);
        emit panel->tree()->customContextMenuRequested(panel->tree()->visualItemRect(sofa).center());
        QCOMPARE(settings.count(), 1);
        QCOMPARE(settings.at(0).at(0).toString(), QStringLiteral("sofa"));
        QVERIFY(!kimbim::LibraryPanel::symbolIcon(QJsonArray{QJsonArray{QJsonArray{0, 0}, QJsonArray{1, 1}}}, 1, 1).isNull());
    }

    void objectToolPlacesTurnsAndUndoes()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.toolPalette()->findChildren<QObject*>().size() > 0);
        QVERIFY(w.chooseObject(QStringLiteral("table"), QJsonObject{{"width", 1.2}}));
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::Object);
        QVERIFY(action(w, "actionTurnObject")->isEnabled());
        const QStringList before = w.viewport()->guids();
        emit w.viewport()->workPointMoved(QPointF(2, 3), 0.01, Qt::NoModifier); // the preview follows
        emit w.viewport()->workPointClicked(QPointF(2, 3), 0.01, Qt::NoModifier);
        QStringList made = added(before, w.viewport()->guids());
        QCOMPARE(made.size(), 1);
        QCOMPARE(w.viewport()->typeOf(made[0]), QStringLiteral("IfcFurniture"));
        const QJsonObject props = kimbim::PythonEngine::instance().callJson("properties", {made[0]}).object();
        QVERIFY(props.value("name").toString() == QLatin1String("Table"));
        QCOMPARE(placedWidth(made[0]), 1.2); // the custom values

        action(w, "actionTurnObject")->trigger(); // Tab
        QCOMPARE(w.objectAngle(), 90.0);
        w.setObjectAngle(-45);
        QCOMPARE(w.objectAngle(), 315.0);
        const QStringList before2 = w.viewport()->guids();
        emit w.viewport()->workPointClicked(QPointF(6, 3), 0.01, Qt::NoModifier);
        QCOMPARE(added(before2, w.viewport()->guids()).size(), 1);

        // Parameters in Properties: the selected table gets a new width (a new type; the other keeps its own).
        w.setTool(kimbim::MainWindow::Tool::None);
        QVERIFY(!action(w, "actionTurnObject")->isEnabled()); // Tab is the focus key again
        w.setSelection({made[0]});
        QVERIFY(w.applyPropertyEdit(QStringLiteral("Parameters"), QStringLiteral("Width"), 1.8));
        const QJsonObject multi = kimbim::PythonEngine::instance().callJson("properties_multi", {QStringLiteral("[\"%1\"]").arg(made[0])}).object();
        QCOMPARE(multi.value("psets").toObject().value("Parameters").toObject().value("Width").toObject().value("value").toDouble(), 1.8);

        // Undo: the edit, then the second table, each one step.
        action(w, "actionUndo")->trigger();
        action(w, "actionUndo")->trigger();
        QCOMPARE(added(before, w.viewport()->guids()).size(), 1);
        action(w, "actionUndo")->trigger();
        QVERIFY(added(before, w.viewport()->guids()).isEmpty());
    }
    void parameterFormShowsNewKindsAndHidesByCondition()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ParameterForm form;
        form.setObject(QStringLiteral("chair"));
        auto* layout = form.findChild<QComboBox*>(QStringLiteral("param_layout"));
        QVERIFY(layout);
        QVERIFY(form.findChild<QWidget*>(QStringLiteral("param_radius"))->isHidden());
        layout->setCurrentIndex(layout->findData(QStringLiteral("circle")));
        QCOMPARE(form.values().value("layout").toString(), QStringLiteral("circle"));
        QCoreApplication::processEvents(); // the form is rebuilt queued
        QVERIFY(!form.findChild<QWidget*>(QStringLiteral("param_radius"))->isHidden());
        auto* arms = form.findChild<QCheckBox*>(QStringLiteral("param_arms"));
        QVERIFY(arms);
        arms->setChecked(true);
        QCOMPARE(form.values().value("arms").toBool(), true);
        QCoreApplication::processEvents();
        auto* splay = form.findChild<QDoubleSpinBox*>(QStringLiteral("param_splay"));
        QVERIFY(splay && splay->suffix() == QStringLiteral("°"));
    }

    void clickPlacesTheLastVersionUsed()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QString id = saveVersion(QStringLiteral("chair"), QStringLiteral("Dining"), {{"width", 0.5}});
        QVERIFY(!id.isEmpty());
        kimbim::LibraryPanel* panel = w.libraryPanel();
        QCOMPARE(itemText(panel, QStringLiteral("chair")), QStringLiteral("Chair")); // Default: the name alone
        w.setObjectVersion(QStringLiteral("chair"), id);
        QCOMPARE(w.currentObjectVersion(), id);
        QVERIFY(itemText(panel, QStringLiteral("chair")).contains(QStringLiteral("Dining")));
        w.setTool(kimbim::MainWindow::Tool::Object);
        const QStringList before = w.viewport()->guids();
        QVERIFY(w.placeObjectAt(QPointF(1, 1)));
        const QStringList made = added(before, w.viewport()->guids());
        QCOMPARE(made.size(), 1);
        QCOMPARE(versionNamed(QStringLiteral("chair"), QStringLiteral("Dining")).value("uses").toInt(), 1); // its type
        QCOMPARE(placedWidth(made[0]), 0.5);

        // Another object, then a plain click on the chair again: the last version used.
        QVERIFY(w.chooseObject(QStringLiteral("table")));
        QVERIFY(w.currentObjectVersion().isEmpty());
        w.setTool(kimbim::MainWindow::Tool::None);
        QVERIFY(panel->selectObject(QStringLiteral("chair")));
        emit panel->tree()->itemClicked(panel->tree()->currentItem(), 0);
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::Object);
        QCOMPARE(w.currentObjectVersion(), id);
        const QJsonObject last = kimbim::PythonEngine::instance().callJson("object_versions", {QStringLiteral("chair")})
            .object().value("last").toObject();
        QCOMPARE(last.value("version").toString(), id);
    }

    void customValuesAreRememberedAsCustom()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.chooseObject(QStringLiteral("chair"), QJsonObject{{"width", 0.6}}));
        QVERIFY(w.currentObjectVersion().isEmpty());
        QStringList before = w.viewport()->guids();
        QVERIFY(w.placeObjectAt(QPointF(1, 1)));
        QCOMPARE(placedWidth(added(before, w.viewport()->guids()).value(0)), 0.6);
        const QJsonObject last = kimbim::PythonEngine::instance().callJson("object_versions", {QStringLiteral("chair")})
            .object().value("last").toObject();
        QCOMPARE(last.value("values").toObject().value("width").toDouble(), 0.6);

        // The listing again (and another object chosen in between): the chair is Custom, and places 0.6.
        QVERIFY(w.chooseObject(QStringLiteral("table")));
        w.setTool(kimbim::MainWindow::Tool::None);
        kimbim::LibraryPanel* panel = w.libraryPanel();
        w.applyLibraryPaths(); // the listing again
        QVERIFY(itemText(panel, QStringLiteral("chair")).contains(QStringLiteral("Custom")));
        QVERIFY(panel->selectObject(QStringLiteral("chair")));
        emit panel->tree()->itemClicked(panel->tree()->currentItem(), 0);
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::Object);
        before = w.viewport()->guids();
        QVERIFY(w.placeObjectAt(QPointF(3, 1)));
        QCOMPARE(placedWidth(added(before, w.viewport()->guids()).value(0)), 0.6);
    }

    void comboSwitchesTheVersion()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QString id = saveVersion(QStringLiteral("chair"), QStringLiteral("Dining"), {{"width", 0.5}});
        auto* combo = w.findChild<QComboBox*>(QStringLiteral("objectVersionCombo"));
        QVERIFY(combo);
        QVERIFY(w.chooseObject(QStringLiteral("chair")));
        QVERIFY(!combo->isHidden());
        QCOMPARE(combo->itemText(0), QStringLiteral("Default"));
        const int dining = combo->findText(QStringLiteral("Dining"));
        QVERIFY(dining > 0);
        QVERIFY(combo->findText(QStringLiteral("Settings...")) < 0);
        combo->setCurrentIndex(dining);
        QCOMPARE(w.currentObjectVersion(), id);
        QVERIFY(itemText(w.libraryPanel(), QStringLiteral("chair")).contains(QStringLiteral("Dining")));

        // The quick switcher: the same versions, plus Settings...
        QMenu menu;
        w.fillObjectVersionMenu(&menu);
        QStringList texts;
        for (QAction* a : menu.actions())
            if (!a->isSeparator())
                texts << a->text();
        QVERIFY(texts.contains(QStringLiteral("Default")));
        QVERIFY(texts.contains(QStringLiteral("Dining")));
        QCOMPARE(texts.last(), QStringLiteral("Settings..."));
        for (QAction* a : menu.actions())
            if (a->text() == QLatin1String("Default"))
                a->trigger();
        QVERIFY(w.currentObjectVersion().isEmpty());
        QCOMPARE(combo->currentIndex(), 0);

        w.setTool(kimbim::MainWindow::Tool::None);
        QVERIFY(combo->isHidden());
    }

    void rightClickWhilePlacingOpensTheSwitcherNotEnd()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.chooseObject(QStringLiteral("chair")));
        kimbim::Viewport* view = w.viewport();
        QSignalSpy context(view, &kimbim::Viewport::drawingContextRequested);
        QSignalSpy ended(view, &kimbim::Viewport::drawingEnded);
        QTest::mousePress(view, Qt::RightButton, {}, QPoint(10, 10));
        QTest::mouseRelease(view, Qt::RightButton, {}, QPoint(10, 10));
        QCOMPARE(context.count(), 1);
        QCOMPARE(ended.count(), 0);
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::Object);
        for (QMenu* m : w.findChildren<QMenu*>(QStringLiteral("objectVersionMenu")))
            m->close();
        QTest::keyClick(view, Qt::Key_Escape); // Esc still ends
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::None);
        QCOMPARE(ended.count(), 1);

        // Other tools: a right click still ends.
        w.setTool(kimbim::MainWindow::Tool::Wall);
        QTest::mousePress(view, Qt::RightButton, {}, QPoint(10, 10));
        QCOMPARE(ended.count(), 2);
        QCOMPARE(context.count(), 1);
    }

    void boolParameterEditsFromProperties()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.chooseObject(QStringLiteral("chair"), QJsonObject{}));
        const QStringList before = w.viewport()->guids();
        emit w.viewport()->workPointClicked(QPointF(1, 1), 0.01, Qt::NoModifier);
        const QStringList made = added(before, w.viewport()->guids());
        QCOMPARE(made.size(), 1);
        w.setTool(kimbim::MainWindow::Tool::None);
        w.setSelection(made);
        QVERIFY(w.applyPropertyEdit(QStringLiteral("Parameters"), QStringLiteral("Arms"), QJsonValue(true)));
        const QJsonObject props = kimbim::PythonEngine::instance()
            .callJson("properties_multi", {QStringLiteral("[\"%1\"]").arg(made[0])}).object();
        QCOMPARE(props.value("psets").toObject().value("Parameters").toObject().value("Arms").toObject().value("value").toBool(), true);
    }

    void updateLibraryObjectsWithNothingOutdatedIsNotAnError()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.chooseObject(QStringLiteral("chair"), QJsonObject{}));
        emit w.viewport()->workPointClicked(QPointF(1, 1), 0.01, Qt::NoModifier);
        w.setTool(kimbim::MainWindow::Tool::None);
        action(w, "actionUpdateLibraryObjects")->trigger();
        QCOMPARE(w.statusStrip()->message(), QStringLiteral("The placed objects already match the library"));
    }
};

QTEST_MAIN(TestLibrary)
#include "test_library.moc"
