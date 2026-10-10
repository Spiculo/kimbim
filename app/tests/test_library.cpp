// SPDX-License-Identifier: GPL-3.0-or-later
// D86: the Library panel and the Object tool: list and search objects, place one with the tool
// (turned with Tab or a typed angle), edit its parameters in Properties, undo it as one step.
#include <QAction>
#include <QLineEdit>
#include <QStandardPaths>
#include <QtTest>

#include "LibraryPanel.h"
#include "MainWindow.h"
#include "PythonEngine.h"
#include "ToolPalette.h"
#include "Viewport.h"

namespace {

QAction* action(kimcad::MainWindow& w, const char* name)
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

} // namespace

class TestLibrary : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { QStandardPaths::setTestModeEnabled(true); }

    void panelListsAndSearches()
    {
        kimcad::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        action(w, "actionObjectLibrary")->trigger();
        kimcad::LibraryPanel* panel = w.libraryPanel();
        QVERIFY(panel->visibleObjectCount() >= 21);
        panel->findChild<QLineEdit*>(QStringLiteral("librarySearch"))->setText(QStringLiteral("bed"));
        QCOMPARE(panel->visibleObjectCount(), 2); // single and double bed
        panel->setFilter(QString());
        QVERIFY(panel->selectObject(QStringLiteral("sofa")));
        QCOMPARE(panel->currentParams().value("seats").toInt(), 3);
        QVERIFY(!kimcad::LibraryPanel::symbolIcon(QJsonArray{QJsonArray{QJsonArray{0, 0}, QJsonArray{1, 1}}}, 1, 1).isNull());
    }

    void objectToolPlacesTurnsAndUndoes()
    {
        kimcad::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.toolPalette()->findChildren<QObject*>().size() > 0);
        QVERIFY(w.chooseObject(QStringLiteral("table"), QJsonObject{{"width", 1.2}}));
        QCOMPARE(w.tool(), kimcad::MainWindow::Tool::Object);
        QVERIFY(action(w, "actionTurnObject")->isEnabled());
        const QStringList before = w.viewport()->guids();
        emit w.viewport()->workPointMoved(QPointF(2, 3), 0.01, Qt::NoModifier); // the preview follows
        emit w.viewport()->workPointClicked(QPointF(2, 3), 0.01, Qt::NoModifier);
        QStringList made = added(before, w.viewport()->guids());
        QCOMPARE(made.size(), 1);
        QCOMPARE(w.viewport()->typeOf(made[0]), QStringLiteral("IfcFurniture"));
        const QJsonObject props = kimcad::PythonEngine::instance().callJson("properties", {made[0]}).object();
        QVERIFY(props.value("name").toString() == QLatin1String("Table"));

        action(w, "actionTurnObject")->trigger(); // Tab
        QCOMPARE(w.objectAngle(), 90.0);
        w.setObjectAngle(-45);
        QCOMPARE(w.objectAngle(), 315.0);
        const QStringList before2 = w.viewport()->guids();
        emit w.viewport()->workPointClicked(QPointF(6, 3), 0.01, Qt::NoModifier);
        QCOMPARE(added(before2, w.viewport()->guids()).size(), 1);

        // Parameters in Properties: the selected table gets a new width (a new type; the other keeps its own).
        w.setTool(kimcad::MainWindow::Tool::None);
        QVERIFY(!action(w, "actionTurnObject")->isEnabled()); // Tab is the focus key again
        w.setSelection({made[0]});
        QVERIFY(w.applyPropertyEdit(QStringLiteral("Parameters"), QStringLiteral("Width"), 1.8));
        const QJsonObject multi = kimcad::PythonEngine::instance().callJson("properties_multi", {QStringLiteral("[\"%1\"]").arg(made[0])}).object();
        QCOMPARE(multi.value("psets").toObject().value("Parameters").toObject().value("Width").toObject().value("value").toDouble(), 1.8);

        // Undo: the edit, then the second table, each one step.
        action(w, "actionUndo")->trigger();
        action(w, "actionUndo")->trigger();
        QCOMPARE(added(before, w.viewport()->guids()).size(), 1);
        action(w, "actionUndo")->trigger();
        QVERIFY(added(before, w.viewport()->guids()).isEmpty());
    }
};

QTEST_MAIN(TestLibrary)
#include "test_library.moc"
