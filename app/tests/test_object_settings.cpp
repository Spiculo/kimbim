// SPDX-License-Identifier: GPL-3.0-or-later
// D100: the Object settings dialog: saved versions on the left, the app's own 3D preview (or the plan
// symbol) in the middle, the object's parameters on the right. A value that doesn't build keeps the
// last preview, shows why and disables Place.
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QListWidget>
#include <QMenu>
#include <QPushButton>
#include <QStandardPaths>
#include <QtTest>

#include "MainWindow.h"
#include "ObjectSettingsDialog.h"
#include "PythonEngine.h"
#include "Viewport.h"

namespace {

QString saveVersion(const QString& name, const QJsonObject& values)
{
    const QJsonObject r = kimbim::PythonEngine::instance()
        .callJson("save_object_version", {QStringLiteral("chair"), name,
            QString::fromUtf8(QJsonDocument(values).toJson(QJsonDocument::Compact))})
        .object();
    return r.value("id").toString();
}

QStringList versionNames(const kimbim::ObjectSettingsDialog& d)
{
    QStringList out;
    auto* list = d.findChild<QListWidget*>(QStringLiteral("objectSettingsVersions"));
    for (int i = 0; i < list->count(); ++i)
        out << list->item(i)->text();
    return out;
}

} // namespace

class TestObjectSettings : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { QStandardPaths::setTestModeEnabled(true); }

    void opensWithVersionsPreviewAndControls()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(!saveVersion(QStringLiteral("Dining"), {{"width", 0.5}}).isEmpty());
        kimbim::ObjectSettingsDialog d(&w, QStringLiteral("chair"), kimbim::ObjectSettingsDialog::Mode::Place);
        const QStringList names = versionNames(d);
        QCOMPARE(names.value(0), QStringLiteral("Default"));
        QVERIFY(names.contains(QStringLiteral("Dining")));
        auto* preview = d.findChild<kimbim::Viewport*>(QStringLiteral("objectSettingsPreview"));
        QVERIFY(preview);
        QTRY_VERIFY(preview->elementCount() > 0);
        QCOMPARE(d.findChild<QPushButton*>(QStringLiteral("objectSettingsAccept"))->text(), QStringLiteral("Place"));
        QVERIFY(d.valid());

        QVERIFY(d.findChild<QWidget*>(QStringLiteral("param_legs"))->isHidden());
        auto* layout = d.findChild<QComboBox*>(QStringLiteral("param_layout"));
        QVERIFY(layout);
        layout->setCurrentIndex(layout->findData(QStringLiteral("circle")));
        QCOMPARE(d.values().value("layout").toString(), QStringLiteral("circle"));
        QTRY_VERIFY(d.findChild<QWidget*>(QStringLiteral("param_legs")) // the form is rebuilt queued
            && !d.findChild<QWidget*>(QStringLiteral("param_legs"))->isHidden());
    }

    void selectingAVersionLoadsItsValues()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QString id = saveVersion(QStringLiteral("Dining"), {{"width", 0.5}});
        kimbim::ObjectSettingsDialog d(&w, QStringLiteral("chair"), kimbim::ObjectSettingsDialog::Mode::Place);
        QVERIFY(d.versionId().isEmpty()); // Default
        d.selectVersion(id);
        QCOMPARE(d.values().value("width").toDouble(), 0.5);
        QCOMPARE(d.versionId(), id);
        QCOMPARE(d.findChild<QListWidget*>(QStringLiteral("objectSettingsVersions"))->currentItem()->text(), QStringLiteral("Dining"));
        auto* width = d.findChild<QDoubleSpinBox*>(QStringLiteral("param_width"));
        QVERIFY(width);
        QCOMPARE(width->value(), 0.5);
        width->setValue(0.6);
        QCOMPARE(d.values().value("width").toDouble(), 0.6);
        QVERIFY(d.versionId().isEmpty()); // edited since it was picked: unsaved values
        d.selectVersion(QString());
        QCOMPARE(d.values().value("width").toDouble(), 0.45);
    }

    void badValueKeepsPreviewAndDisablesAccept() // Review Focus 5
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ObjectSettingsDialog d(&w, QStringLiteral("chair"), kimbim::ObjectSettingsDialog::Mode::Edit);
        auto* preview = d.findChild<kimbim::Viewport*>(QStringLiteral("objectSettingsPreview"));
        auto* accept = d.findChild<QPushButton*>(QStringLiteral("objectSettingsAccept"));
        auto* error = d.findChild<QLabel*>(QStringLiteral("objectSettingsError"));
        QCOMPARE(accept->text(), QStringLiteral("Apply"));
        QTRY_VERIFY(preview->elementCount() > 0);
        const int elements = preview->elementCount();
        const qint64 triangles = preview->triangleCount();
        QVERIFY(accept->isEnabled());

        d.findChild<QDoubleSpinBox*>(QStringLiteral("param_width"))->setValue(0.0);
        QTRY_VERIFY(!accept->isEnabled());
        QVERIFY(!d.valid());
        QVERIFY(!error->text().isEmpty());
        QCOMPARE(preview->elementCount(), elements); // the last good shape stays
        QCOMPARE(preview->triangleCount(), triangles);

        d.findChild<QDoubleSpinBox*>(QStringLiteral("param_width"))->setValue(0.5);
        QTRY_VERIFY(accept->isEnabled());
        QVERIFY(d.valid());
        QVERIFY(error->text().isEmpty());
        QCOMPARE(preview->elementCount(), elements); // replaced, not added
    }

    void saveAsMakesAVersion()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ObjectSettingsDialog d(&w, QStringLiteral("chair"), kimbim::ObjectSettingsDialog::Mode::Place);
        d.setValues({{"height", 1.05}, {"seat", 0.75}});
        QVERIFY(d.saveAs(QStringLiteral("Bar stool")));
        QVERIFY(versionNames(d).contains(QStringLiteral("Bar stool")));
        QVERIFY(!d.versionId().isEmpty());
        const QJsonArray versions = kimbim::PythonEngine::instance()
            .callJson("object_versions", {QStringLiteral("chair")}).object().value("versions").toArray();
        QCOMPARE(versions.size(), 1);
        QCOMPARE(versions[0].toObject().value("name").toString(), QStringLiteral("Bar stool"));
        QCOMPARE(versions[0].toObject().value("id").toString(), d.versionId());
        QCOMPARE(versions[0].toObject().value("values").toObject().value("height").toDouble(), 1.05);
        QVERIFY(!d.saveAs(QStringLiteral("  "))); // a name is needed
    }

    void versionMenuRenamesDeletesAndNeedsAnOfficeFolderToMove()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QString id = saveVersion(QStringLiteral("Dining"), {{"width", 0.5}});
        kimbim::ObjectSettingsDialog d(&w, QStringLiteral("chair"), kimbim::ObjectSettingsDialog::Mode::Place);
        QMenu menu;
        d.fillVersionMenu(&menu, id);
        const QList<QAction*> actions = menu.actions();
        QCOMPARE(actions.size(), 3);
        QAction* move = actions.at(2);
        QVERIFY(!move->isEnabled()); // no office library folder in the preferences
        QVERIFY(!move->toolTip().isEmpty());
        QVERIFY(d.renameVersion(id, QStringLiteral("Dinner")));
        QVERIFY(versionNames(d).contains(QStringLiteral("Dinner")));
        QVERIFY(d.deleteVersion(id));
        QCOMPARE(versionNames(d), QStringList{QStringLiteral("Default")});
    }

    void planToggleShowsTheSymbol()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ObjectSettingsDialog d(&w, QStringLiteral("chair"), kimbim::ObjectSettingsDialog::Mode::Place);
        auto* plan = d.findChild<QWidget*>(QStringLiteral("objectSettingsPlan"));
        auto* preview = d.findChild<QWidget*>(QStringLiteral("objectSettingsPreview"));
        QVERIFY(plan && preview);
        QVERIFY(!plan->isVisibleTo(&d) && preview->isVisibleTo(&d));
        d.findChild<QPushButton*>(QStringLiteral("objectSettingsTogglePlan"))->click();
        QVERIFY(plan->isVisibleTo(&d) && !preview->isVisibleTo(&d));
        QTRY_VERIFY(plan->property("symbolCurves").toInt() > 0);
        d.findChild<QPushButton*>(QStringLiteral("objectSettingsToggle3D"))->click();
        QVERIFY(!plan->isVisibleTo(&d) && preview->isVisibleTo(&d));
    }
};

QTEST_MAIN(TestObjectSettings)
#include "test_object_settings.moc"
