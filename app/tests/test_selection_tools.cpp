// SPDX-License-Identifier: GPL-3.0-or-later
// D78: select similar, Find & Select and selection sets in the main window; crossing vs window box.
#include <QAction>
#include <QComboBox>
#include <QJsonArray>
#include <QJsonObject>
#include <QPushButton>
#include <QStandardPaths>
#include <QtTest>

#include "DockLayout.h"
#include "FindSelectPanel.h"
#include "MainWindow.h"
#include "Viewport.h"
#include "WallTool.h"

#include <DockManager.h>

namespace {

QAction* action(kimbim::MainWindow& w, const char* name)
{
    QAction* a = w.findChild<QAction*>(QString::fromLatin1(name));
    if (!a)
        qFatal("missing action %s", name);
    return a;
}

QStringList sorted(QStringList l)
{
    l.sort();
    return l;
}

// A new project with three walls and a slab; returns {walls..., slab}.
QStringList build(kimbim::MainWindow& w)
{
    if (!w.newProject())
        return {};
    const QStringList before = w.viewport()->guids();
    w.createWall({QPointF(0, 0), QPointF(5, 0), {}, {}});
    w.createWall({QPointF(0, 2), QPointF(5, 2), {}, {}});
    w.createWall({QPointF(0, 4), QPointF(5, 4), {}, {}});
    w.createSlab({QPointF(0, 0), QPointF(5, 0), QPointF(5, 4), QPointF(0, 4)});
    QStringList made;
    for (const QString& g : w.viewport()->guids())
        if (!before.contains(g))
            made << g;
    return made;
}

} // namespace

class TestSelectionTools : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { QStandardPaths::setTestModeEnabled(true); }

    void selectSimilarTakesTheTypeOrTheClassOfVisibleElements()
    {
        kimbim::MainWindow w(nullptr, true);
        const QStringList made = build(w);
        QCOMPARE(made.size(), 4);
        QStringList walls;
        for (const QString& g : made)
            if (w.viewport()->typeOf(g) == QLatin1String("IfcWall"))
                walls << g;
        QCOMPARE(walls.size(), 3);
        QVERIFY(!w.selectSimilar("type")); // nothing selected: nothing to compare with
        w.viewport()->selectGuids({walls[0]});
        w.setSelection({walls[0]});
        action(w, "actionSelectSimilar")->trigger(); // the walls share the default wall type
        QCOMPARE(sorted(w.selection()), sorted(walls));
        QCOMPARE(sorted(w.viewport()->selectedGuids()), sorted(walls));
        // Hidden elements are left out.
        w.viewport()->setHidden({walls[2]}, true);
        w.viewport()->selectGuids({walls[0]});
        w.setSelection({walls[0]});
        action(w, "actionSelectClass")->trigger();
        QCOMPARE(sorted(w.selection()), sorted(QStringList{walls[0], walls[1]}));
    }

    void shortcutsAreFreeAndDocumented()
    {
        kimbim::MainWindow w(nullptr, true);
        QCOMPARE(action(w, "actionSelectSimilar")->shortcut(), QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_A));
        QCOMPARE(action(w, "actionFindSelect")->shortcut(), QKeySequence(Qt::CTRL | Qt::Key_F));
        QHash<QString, QStringList> owners;
        for (QAction* a : w.findChildren<QAction*>())
            for (const QKeySequence& k : a->shortcuts())
                owners[k.toString()] << a->objectName();
        for (const char* name : {"actionSelectSimilar", "actionFindSelect"}) {
            const QString key = action(w, name)->shortcut().toString();
            QVERIFY2(owners.value(key).size() == 1, qPrintable(key + QLatin1String(": ") + owners.value(key).join(',')));
        }
    }

    void thePanelSelectsAddsAndRemoves()
    {
        kimbim::MainWindow w(nullptr, true);
        const QStringList made = build(w);
        QCOMPARE(made.size(), 4);
        action(w, "actionFindSelect")->trigger();
        kimbim::FindSelectPanel* panel = w.findSelectPanel();
        QVERIFY(panel);
        QVERIFY(w.dockLayout()->manager()->findDockWidget(QStringLiteral("findselect")));
        QCOMPARE(panel->rowCount(), 1);
        panel->clearRows();
        panel->addRow("ifc_class", "equals", "IfcSlab");
        panel->find(kimbim::FindSelectPanel::How::Replace);
        QCOMPARE(w.selection(), QStringList{made[3]});
        QVERIFY(panel->result().startsWith(QStringLiteral("1 ")));
        panel->clearRows();
        panel->addRow("kind", "equals", "walls");
        panel->find(kimbim::FindSelectPanel::How::Add);
        QCOMPARE(sorted(w.selection()), sorted(made));
        panel->clearRows();
        panel->addRow("ifc_class", "equals", "IfcSlab");
        panel->find(kimbim::FindSelectPanel::How::Remove);
        QCOMPARE(sorted(w.selection()), sorted(made.mid(0, 3)));
        // Scope: the current selection; OR of two rows.
        panel->clearRows();
        panel->addRow("ifc_class", "equals", "IfcSlab");
        panel->addRow("ifc_class", "equals", "IfcWall");
        panel->findChild<QComboBox*>("matchCombo")->setCurrentIndex(1); // any
        panel->setScope("selection");
        panel->find(kimbim::FindSelectPanel::How::Replace);
        QCOMPARE(sorted(w.selection()), sorted(made.mid(0, 3)));
        QCOMPARE(panel->criteria().value("match").toString(), QString("any"));
        // A bad row is refused and said so; the selection stays.
        panel->clearRows();
        panel->addRow("property", "equals", "x"); // no property name
        panel->find(kimbim::FindSelectPanel::How::Replace);
        QCOMPARE(sorted(w.selection()), sorted(made.mid(0, 3)));
        QVERIFY(panel->result().contains(QStringLiteral("property name")));
    }

    void criteriaAndSelectionSetsAreSavedInTheProject()
    {
        kimbim::MainWindow w(nullptr, true);
        const QStringList made = build(w);
        kimbim::FindSelectPanel* panel = w.findSelectPanel();
        panel->clearRows();
        panel->addRow("ifc_class", "equals", "IfcSlab");
        panel->saveCriteria("Slabs");
        QCOMPARE(panel->savedCriteriaNames(), QStringList{"Slabs"});
        QCOMPARE(w.projectSettings().value("selection_criteria").toObject().value("Slabs").toObject(), panel->criteria());
        panel->clearRows();
        panel->loadCriteria("Slabs");
        QCOMPARE(panel->rowCount(), 1);
        panel->find(kimbim::FindSelectPanel::How::Replace);
        QCOMPARE(w.selection(), QStringList{made[3]});

        w.viewport()->selectGuids(made.mid(0, 2));
        w.setSelection(made.mid(0, 2));
        panel->saveSet("Two walls");
        QCOMPARE(panel->savedSetNames(), QStringList{"Two walls"});
        QCOMPARE(w.projectSettings().value("selection_sets").toObject().value("Two walls").toArray().size(), 2);
        w.setSelection({});
        panel->recallSet("Two walls", kimbim::FindSelectPanel::How::Replace);
        QCOMPARE(sorted(w.selection()), sorted(made.mid(0, 2)));
        QVERIFY(w.deleteSelectionSet("Two walls"));
        QVERIFY(panel->savedSetNames().isEmpty());
        QVERIFY(w.deleteSelectionCriteria("Slabs"));
        QVERIFY(panel->savedCriteriaNames().isEmpty());
    }

    void boxDirectionDecidesCrossing()
    {
        QVERIFY(kimbim::Viewport::isCrossingBox(100, 20));  // right to left: crossing
        QVERIFY(!kimbim::Viewport::isCrossingBox(20, 100)); // left to right: window
    }
};

QTEST_MAIN(TestSelectionTools)
#include "test_selection_tools.moc"
