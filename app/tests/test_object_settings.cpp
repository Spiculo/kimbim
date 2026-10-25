// SPDX-License-Identifier: GPL-3.0-or-later
// D100: the Object settings dialog: saved versions on the left, the app's own 3D preview (or the plan
// symbol) in the middle, the object's parameters on the right. A value that doesn't build keeps the
// last preview, shows why and disables Place.
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QListWidget>
#include <QMenu>
#include <QPushButton>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QtTest>

#include "MainWindow.h"
#include "ObjectSettingsDialog.h"
#include "PythonEngine.h"
#include "Translations.h"
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

QJsonObject py(const char* fn, const QStringList& args = {})
{
    return kimbim::PythonEngine::instance().callJson(fn, args).object();
}

QStringList versionNames(const kimbim::ObjectSettingsDialog& d)
{
    QStringList out;
    auto* list = d.findChild<QListWidget*>(QStringLiteral("objectSettingsVersions"));
    for (int i = 0; i < list->count(); ++i)
        out << list->item(i)->text();
    return out;
}

// An office object file (D99) in `dir`: a box, optionally with one more parameter or a group heading.
void writeBlock(const QTemporaryDir& dir, const QString& id, const QJsonArray& extra = {}, const QJsonValue& group = {})
{
    QJsonArray params;
    for (const char* key : {"width", "depth", "height"}) {
        QJsonObject p{{"key", key}, {"kind", "length"}, {"label", key}, {"default", QString::fromLatin1(key) == "height" ? 0.45 : 0.4}};
        if (!group.isNull())
            p.insert("group", group);
        params.append(p);
    }
    for (const auto& p : extra)
        params.append(p);
    const QJsonObject block{{"format", "kimbim-object/1"}, {"id", id}, {"name", "Block"}, {"category", "furniture"},
        {"ifc", QJsonObject{{"IFC4", QJsonArray{"IfcFurnitureType", "NOTDEFINED", QJsonValue()}}}}, {"params", params},
        {"parts", QJsonArray{QJsonObject{{"id", "body"}, {"box", QJsonObject{{"dx", "width"}, {"dy", "depth"}, {"dz", "height"}}}}}}};
    QFile file(dir.filePath(id + QStringLiteral(".kimobj")));
    QVERIFY(file.open(QIODevice::WriteOnly));
    file.write(QJsonDocument(block).toJson());
}

void setOfficeFolder(const QString& folder)
{
    kimbim::PythonEngine::instance().callJson("set_library_paths",
        {QString::fromUtf8(QJsonDocument(QJsonObject{{"folder", folder}}).toJson(QJsonDocument::Compact))});
}

QStringList headings(const kimbim::ObjectSettingsDialog& d)
{
    QStringList out;
    for (const QLabel* l : d.findChildren<QLabel*>(QStringLiteral("paramGroup")))
        out << l->text();
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
        QCOMPARE(d.versionId(), kimbim::ObjectSettingsDialog::defaultId()); // Default: its own marker
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
        QCOMPARE(d.versionId(), kimbim::ObjectSettingsDialog::defaultId());
        // values edited from Default: unsaved, not Default (the form was rebuilt: its controls are new)
        d.findChild<QDoubleSpinBox*>(QStringLiteral("param_width"))->setValue(0.5);
        QVERIFY(d.versionId().isEmpty());
    }

    // Focus entering the versions list (the dialog shown, Tab) makes an item current without the user
    // picking it: the unsaved values stay. Picking an item in the list still selects that version.
    void focusInTheListKeepsUnsavedValues()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QString id = saveVersion(QStringLiteral("Dining"), {{"width", 0.5}});
        kimbim::ObjectSettingsDialog d(&w, QStringLiteral("chair"), kimbim::ObjectSettingsDialog::Mode::Edit);
        d.setValues({{"width", 0.6}});
        d.show();
        auto* list = d.findChild<QListWidget*>(QStringLiteral("objectSettingsVersions"));
        QFocusEvent focus(QEvent::FocusIn, Qt::TabFocusReason);
        QApplication::sendEvent(list, &focus);
        QCOMPARE(d.values().value("width").toDouble(), 0.6);
        QVERIFY(d.versionId().isEmpty());
        for (int i = 0; i < list->count(); ++i)
            if (list->item(i)->text() == QLatin1String("Dining"))
                list->setCurrentRow(i);
        QCOMPARE(d.versionId(), id);
        QCOMPARE(d.values().value("width").toDouble(), 0.5);
        list->setCurrentRow(0); // Default
        QCOMPARE(d.versionId(), kimbim::ObjectSettingsDialog::defaultId());
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

    // D100 final review: Delete on a version placed objects use is disabled, saying how many.
    void deleteIsDisabledForAUsedVersion()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QString id = saveVersion(QStringLiteral("Dining"), {{"width", 0.5}});
        const QString storey = kimbim::PythonEngine::instance().callJson("storeys", {}).object()
            .value("storeys").toArray().at(0).toObject().value("guid").toString();
        for (int i = 0; i < 2; ++i)
            QVERIFY(py("place_object", {storey, QStringLiteral("chair"), QString(), QString::number(i), QStringLiteral("0"),
                QStringLiteral("0"), QString(), id}).value("ok").toBool());
        kimbim::ObjectSettingsDialog d(&w, QStringLiteral("chair"), kimbim::ObjectSettingsDialog::Mode::Place);
        QMenu menu;
        d.fillVersionMenu(&menu, id);
        QAction* remove = menu.actions().at(1);
        QCOMPARE(remove->text(), QStringLiteral("Delete"));
        QVERIFY(!remove->isEnabled());
        QVERIFY2(remove->toolTip().contains(QStringLiteral("2 placed object")), qPrintable(remove->toolTip()));
        QVERIFY(menu.actions().at(0)->isEnabled()); // Rename still works
        const QString unused = saveVersion(QStringLiteral("Spare"), {{"width", 0.6}});
        kimbim::ObjectSettingsDialog again(&w, QStringLiteral("chair"), kimbim::ObjectSettingsDialog::Mode::Place);
        QMenu spare;
        again.fillVersionMenu(&spare, unused);
        QVERIFY(spare.actions().at(1)->isEnabled()); // nothing uses it
        QVERIFY(!spare.actions().at(1)->toolTip().contains(QStringLiteral("placed object")));
    }

    // D100 final review: a project copy of an office version is marked in the list.
    void officeCopyIsMarked()
    {
        QTemporaryDir dir;
        setOfficeFolder(dir.path());
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QString id = saveVersion(QStringLiteral("Cafe"), {{"width", 0.5}});
        const QString mine = saveVersion(QStringLiteral("Mine"), {{"width", 0.6}});
        QVERIFY(py("move_version_to_library", {id, QString()}).value("ok").toBool());
        kimbim::ObjectSettingsDialog d(&w, QStringLiteral("chair"), kimbim::ObjectSettingsDialog::Mode::Place);
        auto* list = d.findChild<QListWidget*>(QStringLiteral("objectSettingsVersions"));
        QString cafe, plain;
        for (int i = 0; i < list->count(); ++i) {
            if (list->item(i)->text() == QLatin1String("Cafe"))
                cafe = list->item(i)->toolTip();
            if (list->item(i)->text() == QLatin1String("Mine"))
                plain = list->item(i)->toolTip();
        }
        QVERIFY2(cafe.contains(QStringLiteral("office library")), qPrintable(cafe));
        QVERIFY2(!plain.isEmpty() && !plain.contains(QStringLiteral("office library")), qPrintable(plain));
        QVERIFY(!mine.isEmpty());
        setOfficeFolder(QString());
    }

    // D100 final review: Edit mode on placements of an unnamed type uses the definition stored on the
    // type, also when the library's has moved on (an outdated placement): no parameter it lacks.
    void editTypeUsesTheTypesOwnDefinition()
    {
        QTemporaryDir dir;
        writeBlock(dir, QStringLiteral("block"));
        setOfficeFolder(dir.path());
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QString storey = kimbim::PythonEngine::instance().callJson("storeys", {}).object()
            .value("storeys").toArray().at(0).toObject().value("guid").toString();
        const QJsonObject placed = py("place_object", {storey, QStringLiteral("office:block"), QStringLiteral("{\"height\": 0.3}"),
            QStringLiteral("0"), QStringLiteral("0"), QStringLiteral("0")});
        QVERIFY(placed.value("ok").toBool());
        writeBlock(dir, QStringLiteral("block"), {QJsonObject{{"key", "top"}, {"kind", "length"}, {"label", "Top"}, {"default", 0.02}}});
        setOfficeFolder(dir.path());
        const QJsonObject of = py("object_settings_of", {QStringLiteral("[\"%1\"]").arg(placed.value("guid").toString())});
        QCOMPARE(of.value("source").toString(), QStringLiteral("type:") + placed.value("type").toString());
        kimbim::ObjectSettingsDialog d(&w, QStringLiteral("office:block"), kimbim::ObjectSettingsDialog::Mode::Edit);
        QVERIFY(d.findChild<QWidget*>(QStringLiteral("param_top"))); // Default: the library's definition
        d.editType(of.value("source").toString(), of.value("values").toObject());
        QVERIFY(d.versionId().isEmpty());
        QVERIFY(!d.findChild<QWidget*>(QStringLiteral("param_top")));
        QCOMPARE(d.findChild<QDoubleSpinBox*>(QStringLiteral("param_height"))->value(), 0.3);
        d.findChild<QDoubleSpinBox*>(QStringLiteral("param_height"))->setValue(0.5);
        QVERIFY(!d.findChild<QWidget*>(QStringLiteral("param_top"))); // still the type's definition
        QTRY_VERIFY(d.findChild<kimbim::Viewport*>(QStringLiteral("objectSettingsPreview"))->elementCount() > 0);
        QVERIFY(d.valid());
        QVERIFY(!d.values().contains(QStringLiteral("top")));
        setOfficeFolder(QString());
    }

    void formFollowsTheVersionsOwnDefinition()
    {
        QTemporaryDir dir;
        writeBlock(dir, QStringLiteral("block"));
        setOfficeFolder(dir.path());
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        const QString id = kimbim::PythonEngine::instance()
            .callJson("save_object_version", {QStringLiteral("office:block"), QStringLiteral("Low"), QStringLiteral("{\"height\": 0.3}")})
            .object().value("id").toString();
        QVERIFY(!id.isEmpty());
        // the library's definition moves on: a new parameter the version's stored definition doesn't have
        writeBlock(dir, QStringLiteral("block"), {QJsonObject{{"key", "top"}, {"kind", "length"}, {"label", "Top"}, {"default", 0.02}}});
        setOfficeFolder(dir.path());
        {
            kimbim::ObjectSettingsDialog d(&w, QStringLiteral("office:block"), kimbim::ObjectSettingsDialog::Mode::Place);
            QVERIFY(d.findChild<QWidget*>(QStringLiteral("param_top"))); // Default: the library's definition
            d.selectVersion(id);
            QVERIFY(!d.findChild<QWidget*>(QStringLiteral("param_top")));
            QCOMPARE(d.findChild<QDoubleSpinBox*>(QStringLiteral("param_height"))->value(), 0.3);
            d.setValues({{"height", 0.5}}); // edited: still the version's definition
            QVERIFY(d.versionId().isEmpty());
            QVERIFY(!d.findChild<QWidget*>(QStringLiteral("param_top")));
            QTRY_VERIFY(d.findChild<kimbim::Viewport*>(QStringLiteral("objectSettingsPreview"))->elementCount() > 0);
            QVERIFY(d.valid());
            QTRY_VERIFY(d.findChild<QWidget*>(QStringLiteral("objectSettingsPlan"))->property("symbolCurves").toInt() > 0);
        }
        setOfficeFolder(QString()); // gone from the library: the version still has its controls and preview
        kimbim::ObjectSettingsDialog d(&w, QStringLiteral("office:block"), kimbim::ObjectSettingsDialog::Mode::Place);
        d.selectVersion(id);
        QCOMPARE(d.versionId(), id);
        QCOMPARE(d.findChild<QDoubleSpinBox*>(QStringLiteral("param_height"))->value(), 0.3);
        QTRY_VERIFY(d.findChild<kimbim::Viewport*>(QStringLiteral("objectSettingsPreview"))->elementCount() > 0);
        QVERIFY(d.valid());
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

    void groupHeadingsInSpanish() // last: the Spanish translator stays installed
    {
        QTemporaryDir dir;
        writeBlock(dir, QStringLiteral("grouped"), {}, QJsonObject{{"en", "Size"}, {"es", "Tamaño"}});
        setOfficeFolder(dir.path());
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(kimbim::installTranslator(*qApp, QStringLiteral("es")));
        {
            kimbim::ObjectSettingsDialog chair(&w, QStringLiteral("chair"), kimbim::ObjectSettingsDialog::Mode::Place);
            const QStringList h = headings(chair); // plain text in the bundled file: the app's translation
            QVERIFY2(h.contains(QStringLiteral("Patas")) && h.contains(QStringLiteral("Respaldo"))
                    && h.contains(QStringLiteral("Asiento")) && h.contains(QStringLiteral("Brazos")),
                qPrintable(h.join(QLatin1Char(','))));
        }
        kimbim::ObjectSettingsDialog block(&w, QStringLiteral("office:grouped"), kimbim::ObjectSettingsDialog::Mode::Place);
        QCOMPARE(headings(block), QStringList{QStringLiteral("Tamaño")}); // the object file's own Spanish
        kimbim::installTranslator(*qApp, QStringLiteral("en"));
        setOfficeFolder(QString());
    }
};

QTEST_MAIN(TestObjectSettings)
#include "test_object_settings.moc"
