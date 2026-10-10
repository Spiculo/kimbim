// SPDX-License-Identifier: GPL-3.0-or-later
// D81: the Checks panel on the sample house: schema, model checks and a clash set run in the
// background; clicking an issue selects its elements and zooms to them; IDS files and their report.
#include <QAction>
#include <QFile>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonObject>
#include <QMenu>
#include <QPushButton>
#include <QSignalSpy>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QTreeWidget>
#include <QtTest>

#include "ChecksPanel.h"
#include "DockLayout.h"
#include "MainWindow.h"
#include "PythonEngine.h"
#include "Viewport.h"

namespace {

QStringList sorted(QStringList l)
{
    l.sort();
    return l;
}

const char* idsText(); // below the test class: moc does not read raw strings

} // namespace

class TestChecks : public QObject {
    Q_OBJECT
private slots:
    void initTestCase()
    {
        QStandardPaths::setTestModeEnabled(true);
        QString error;
        QVERIFY2(kimcad::PythonEngine::instance().start(&error), qPrintable(error));
        QVERIFY(m_tmp.isValid());
        m_house = m_tmp.filePath(QStringLiteral("house.ifc"));
        const QJsonObject made = kimcad::PythonEngine::instance().callJson("_write_sample_house", {m_house}, &error).object();
        QVERIFY2(made.value("ok").toBool(), qPrintable(made.value("error").toString() + error));
    }

    void checksOnTheHouseAndClickingAnIssue()
    {
        kimcad::MainWindow w(nullptr, /*quiet=*/true);
        w.resize(1300, 800);
        w.show();
        QSignalSpy done(&w, &kimcad::MainWindow::loadFinished);
        w.openFile(m_house);
        QVERIFY(done.wait(60000));

        QAction* check = w.findChild<QAction*>(QStringLiteral("actionCheckModel"));
        QVERIFY(check);
        check->trigger(); // Model > Check model... opens the panel
        kimcad::ChecksPanel* panel = w.findChild<kimcad::ChecksPanel*>();
        QVERIFY(panel);
        QVERIFY(w.findChild<QMenu*>(QStringLiteral("panelsMenu"))->actions().size() >= 1);

        // A clash set (kept in the project settings): the house's floor slabs overlap the upper walls.
        QVERIFY(w.saveClashSet(QStringLiteral("Walls × slabs"),
            {{"a", QJsonObject{{"classes", QJsonArray{"IfcWall"}}}}, {"b", QJsonObject{{"classes", QJsonArray{"IfcSlab"}}}},
                {"mode", "hard"}, {"tolerance", 0.002}}));
        QCOMPARE(panel->clashSetNames(), QStringList{QStringLiteral("Walls × slabs")});
        QVERIFY(w.projectSettings().value("clash_sets").toObject().contains(QStringLiteral("Walls × slabs")));

        panel->setChecked(QStringLiteral("ids"), false); // no IDS files yet
        QCOMPARE(panel->checkedChecks(), (QStringList{"schema", "clash", "model"}));
        QSignalSpy asked(panel, &kimcad::ChecksPanel::runRequested);
        panel->findChild<QPushButton*>(QStringLiteral("runChecks"))->click(); // runs them, one worker each
        QCOMPARE(asked.count(), 1);
        QTreeWidget* results = panel->results();
        QCOMPARE(results->topLevelItemCount(), 3);
        QVERIFY2(results->topLevelItem(0)->text(0).contains(QStringLiteral("no issues")), qPrintable(results->topLevelItem(0)->text(0)));
        QVERIFY2(results->topLevelItem(2)->text(0).contains(QStringLiteral("no issues")), qPrintable(results->topLevelItem(2)->text(0)));
        QCOMPARE(panel->issueCount(), 8); // each floor slab overlaps the 4 exterior walls below it (they run 3 m up)
        QVERIFY(panel->issueText(0).contains(QStringLiteral("intersect")));

        // Clicking an issue selects both elements and zooms to them.
        const double zoom = w.viewport()->zoomPercent();
        const QStringList guids = panel->issueGuids(0);
        QCOMPARE(guids.size(), 2);
        QVERIFY(panel->activateIssue(0));
        QCOMPARE(sorted(w.selection()), sorted(guids));
        QCOMPARE(sorted(w.viewport()->selectedGuids()), sorted(guids));
        if (QGuiApplication::platformName() != QLatin1String("offscreen")) // no OpenGL window there: nothing to fit
            QVERIFY2(w.viewport()->zoomPercent() > zoom, qPrintable(QString::number(w.viewport()->zoomPercent())));
        QVERIFY(w.isDirty()); // the clash set is unsaved project work

        // IDS: the file's XML goes into the project settings; failures list their elements.
        const QString idsPath = m_tmp.filePath(QStringLiteral("office.ids"));
        QFile f(idsPath);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write(idsText());
        f.close();
        QVERIFY(w.addIdsFile(idsPath));
        QCOMPARE(panel->idsFiles(), QStringList{QStringLiteral("office.ids")});
        QVERIFY(w.projectSettings().value("ids_files").toObject().value("office.ids").toString().contains("Office rules"));
        QVERIFY(w.runChecks({QStringLiteral("ids")}));
        QCOMPARE(results->topLevelItemCount(), 1);
        QVERIFY(panel->issueCount() >= 1); // the door has no Pset_DoorCommon.FireRating
        QVERIFY(panel->issueText(0).contains(QStringLiteral("IfcDoor")));
        const QString report = m_tmp.filePath(QStringLiteral("report.html"));
        QVERIFY(w.exportIdsReport(report));
        QVERIFY(QFile::exists(report));
        QVERIFY(w.removeIdsFile(QStringLiteral("office.ids")));
        QVERIFY(panel->idsFiles().isEmpty());
        QVERIFY(w.deleteClashSet(QStringLiteral("Walls × slabs")));
        QVERIFY(panel->clashSetNames().isEmpty());
    }

    void clashSetSides()
    {
        using kimcad::ClashSetDialog;
        QCOMPARE(ClashSetDialog::parseSide(QStringLiteral("IfcWall, ifcSlab")),
            (QJsonObject{{"classes", QJsonArray{"IfcWall", "IfcSlab"}}}));
        const QJsonObject criteria{{"criteria", "Fire walls"}};
        QCOMPARE(ClashSetDialog::parseSide(ClashSetDialog::sideText(criteria)), criteria);
        const QJsonObject set{{"selection_set", "Core"}};
        QCOMPARE(ClashSetDialog::parseSide(ClashSetDialog::sideText(set)), set);
        QVERIFY(ClashSetDialog::parseSide(QStringLiteral("walls")).isEmpty());
        ClashSetDialog d({"IfcWall", "IfcSlab"}, {"Fire walls"}, {});
        d.setSet(QStringLiteral("x"), {{"a", criteria}, {"mode", "clearance"}, {"clearance", 0.1}});
        QCOMPARE(d.set().value("a").toObject(), criteria);
        QVERIFY(!d.set().contains("b")); // A against itself
        QCOMPARE(d.set().value("mode").toString(), QStringLiteral("clearance"));
        QCOMPARE(d.set().value("clearance").toDouble(), 0.1);
    }

private:
    QTemporaryDir m_tmp;
    QString m_house;
};

QTEST_MAIN(TestChecks)
#include "test_checks.moc"

namespace {

const char* idsText()
{
    return R"(<?xml version="1.0" encoding="UTF-8"?>
<ids xmlns="http://standards.buildingsmart.org/IDS" xmlns:xs="http://www.w3.org/2001/XMLSchema"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <info><title>Office rules</title></info>
  <specifications>
    <specification name="Doors have a fire rating" ifcVersion="IFC4">
      <applicability minOccurs="0" maxOccurs="unbounded"><entity><name><simpleValue>IFCDOOR</simpleValue></name></entity></applicability>
      <requirements>
        <property dataType="IFCLABEL"><propertySet><simpleValue>Pset_DoorCommon</simpleValue></propertySet>
          <baseName><simpleValue>FireRating</simpleValue></baseName></property>
      </requirements>
    </specification>
    <specification name="Walls have a name" ifcVersion="IFC4">
      <applicability minOccurs="1" maxOccurs="unbounded"><entity><name><simpleValue>IFCWALL</simpleValue></name></entity></applicability>
      <requirements><attribute><name><simpleValue>Name</simpleValue></name></attribute></requirements>
    </specification>
  </specifications>
</ids>
)";
}

} // namespace
