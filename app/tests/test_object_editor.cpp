// SPDX-License-Identifier: GPL-3.0-or-later
// D101: the Object Editor dialog: the object's fields, its parameters and materials as tables, the live
// preview at the Try values, and saving to the project or the office library. A draft with errors marks
// the fields, keeps the last preview and disables both saves.
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QSpinBox>
#include <QStandardPaths>
#include <QTableWidget>
#include <QTemporaryDir>
#include <QtTest>

#include "MainWindow.h"
#include "ObjectEditorDialog.h"
#include "PythonEngine.h"
#include "Viewport.h"

namespace {

void setOfficeFolder(const QString& folder)
{
    kimbim::PythonEngine::instance().callJson("set_library_paths",
        {QString::fromUtf8(QJsonDocument(QJsonObject{{"folder", folder}}).toJson(QJsonDocument::Compact))});
}

kimbim::Viewport* preview(const kimbim::ObjectEditorDialog& d)
{
    return d.findChild<kimbim::Viewport*>(QStringLiteral("editorPreview"));
}

QPushButton* button(const kimbim::ObjectEditorDialog& d, const char* name)
{
    return d.findChild<QPushButton*>(QLatin1String(name));
}

// The row of parameter `key` in the Parameters table, or -1.
int paramRow(const kimbim::ObjectEditorDialog& d, const QString& key)
{
    auto* table = d.findChild<QTableWidget*>(QStringLiteral("editorParams"));
    for (int r = 0; r < table->rowCount(); ++r)
        if (table->item(r, 0) && table->item(r, 0)->text() == key)
            return r;
    return -1;
}

QJsonObject draftParam(const kimbim::ObjectEditorDialog& d, const QString& key)
{
    for (const auto& p : d.draft().value("params").toArray())
        if (p.toObject().value("key").toString() == key)
            return p.toObject();
    return {};
}

bool hasPathStarting(const kimbim::ObjectEditorDialog& d, const QString& prefix)
{
    for (const QString& p : d.errorPaths())
        if (p.startsWith(prefix))
            return true;
    return false;
}

} // namespace

class TestObjectEditor : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { QStandardPaths::setTestModeEnabled(true); }

    void newObjectPreviews()
    {
        QTemporaryDir dir;
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        setOfficeFolder(dir.path()); // after the window: it sends the (empty) preferences
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("new"));
        QCOMPARE(d.objectName(), QStringLiteral("objectEditorDialog"));
        QVERIFY(preview(d));
        QTRY_VERIFY(preview(d)->elementCount() > 0);
        QVERIFY2(d.errorPaths().isEmpty(), qPrintable(d.errorPaths().join(QLatin1Char(','))));
        QVERIFY(button(d, "editorSaveProject")->isEnabled());
        QVERIFY(button(d, "editorSaveOffice")->isEnabled());
        QCOMPARE(d.windowTitle(), QStringLiteral("Object editor — New object"));
        setOfficeFolder(QString());
    }

    void renamedKeyMarksTheFormula()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("chair"));
        QCOMPARE(d.windowTitle(), QStringLiteral("Object editor — Chair (copy)")); // a copy of a bundled object
        QTRY_VERIFY(preview(d)->elementCount() > 0);
        const int elements = preview(d)->elementCount();
        const qint64 triangles = preview(d)->triangleCount();
        const int row = paramRow(d, QStringLiteral("legs"));
        QVERIFY(row >= 0);
        auto* table = d.findChild<QTableWidget*>(QStringLiteral("editorParams"));
        table->item(row, 0)->setText(QStringLiteral("legz"));
        QTRY_VERIFY2(hasPathStarting(d, QStringLiteral("parts.leg")), qPrintable(d.errorPaths().join(QLatin1Char(','))));
        QVERIFY(!button(d, "editorSaveProject")->isEnabled());
        QVERIFY(!button(d, "editorSaveOffice")->isEnabled());
        QVERIFY(!d.findChild<QLabel*>(QStringLiteral("editorError"))->text().isEmpty());
        QCOMPARE(preview(d)->elementCount(), elements); // the last good shape stays
        QCOMPARE(preview(d)->triangleCount(), triangles);

        table->item(row, 0)->setText(QStringLiteral("legs")); // fixed: the errors go
        QTRY_VERIFY(d.errorPaths().isEmpty());
        QVERIFY(button(d, "editorSaveProject")->isEnabled());
    }

    void errorMarksTheParameterRow()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("chair"));
        QTRY_VERIFY(preview(d)->elementCount() > 0);
        const int row = paramRow(d, QStringLiteral("seat"));
        auto* table = d.findChild<QTableWidget*>(QStringLiteral("editorParams"));
        table->item(row, 6)->setText(QStringLiteral("height +")); // max: a broken formula
        QTRY_VERIFY(d.errorPaths().contains(QStringLiteral("params[%1].max").arg(row)));
        QVERIFY(!table->item(row, 6)->toolTip().isEmpty());
        QVERIFY(table->item(row, 0)->toolTip().isEmpty()); // only the cell of the field
    }

    void draftKeepsWhatTheTablesDoNotShow()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("chair"));
        const QJsonObject draft = d.draft();
        QCOMPARE(draft.value("id").toString(), QStringLiteral("chair_copy"));
        QVERIFY(draft.value("components").toObject().contains(QStringLiteral("leg_square")));
        QVERIFY(!draft.value("symbol").toArray().isEmpty());
        QVERIFY(!draft.value("parts").toArray().isEmpty());
        const QJsonObject layout = draftParam(d, QStringLiteral("layout"));
        QCOMPARE(layout.value("label").toObject().value("es").toString(), QStringLiteral("Disposición de las patas"));
        QCOMPARE(layout.value("options").toArray().at(1).toObject().value("label").toObject().value("es").toString(),
            QStringLiteral("En círculo"));
        QCOMPARE(draftParam(d, QStringLiteral("seat")).value("max").toString(), QStringLiteral("height"));
        QCOMPARE(draftParam(d, QStringLiteral("seat")).value("min").toDouble(), 0.2);
        QCOMPARE(draftParam(d, QStringLiteral("arms")).value("default"), QJsonValue(false));
        QCOMPARE(draft.value("materials").toObject().value("frame").toObject().value("default").toString(), QStringLiteral("Steel"));
        QVERIFY(!d.isDirty());
        d.setDraft(draft); // round trip
        QCOMPARE(d.draft(), draft);
    }

    void tryValuesDoNotChangeDefaults()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("chair"));
        auto* form = d.findChild<QWidget*>(QStringLiteral("editorTryValues"));
        QVERIFY(form);
        QTRY_VERIFY(form->findChild<QSpinBox*>(QStringLiteral("param_legs")));
        form->findChild<QSpinBox*>(QStringLiteral("param_legs"))->setValue(3);
        QTRY_VERIFY(preview(d)->elementCount() > 0);
        QCOMPARE(draftParam(d, QStringLiteral("legs")).value("default").toInt(), 4);
        QVERIFY(!d.isDirty());
    }

    void noOfficeFolderDisablesOfficeSave()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        setOfficeFolder(QString());
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("new"));
        QTRY_VERIFY(button(d, "editorSaveProject")->isEnabled());
        QVERIFY(!button(d, "editorSaveOffice")->isEnabled());
        QCOMPARE(button(d, "editorSaveOffice")->toolTip(), QStringLiteral("Set an office library folder in Preferences › Office library"));
    }

    void cancelAsksOnlyWhenDirty()
    {
        kimbim::MainWindow w; // not quiet: the question shows
        QVERIFY(w.newProject());
        {
            kimbim::ObjectEditorDialog d(&w, QStringLiteral("new"));
            d.show();
            d.reject();
            QVERIFY(!d.isVisible());
            QCOMPARE(d.result(), int(QDialog::Rejected));
        }
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("new"));
        d.show();
        d.findChild<QLineEdit*>(QStringLiteral("editorName"))->setText(QStringLiteral("Stool"));
        QVERIFY(d.isDirty());
        bool asked = false;
        QTimer::singleShot(0, &d, [&] {
            auto* box = qobject_cast<QMessageBox*>(QApplication::activeModalWidget());
            if (!box)
                return;
            asked = box->text() == QLatin1String("Discard the changes to this object?");
            box->button(QMessageBox::No)->click();
        });
        d.reject();
        QVERIFY(asked);
        QVERIFY(d.isVisible()); // No: the dialog stays open
        QTimer::singleShot(0, &d, [] {
            if (auto* box = qobject_cast<QMessageBox*>(QApplication::activeModalWidget()))
                box->button(QMessageBox::Yes)->click();
        });
        d.reject();
        QVERIFY(!d.isVisible());
    }

    void saveToOfficeWritesTheFile()
    {
        QTemporaryDir dir;
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        setOfficeFolder(dir.path());
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("chair"));
        auto* table = d.findChild<QTableWidget*>(QStringLiteral("editorParams"));
        table->item(paramRow(d, QStringLiteral("legs")), 4)->setText(QStringLiteral("3"));
        QCOMPARE(draftParam(d, QStringLiteral("legs")).value("default").toInt(), 3);
        QVERIFY(d.isDirty());
        QVERIFY(d.saveTo(QStringLiteral("office")));
        QCOMPARE(d.result(), int(QDialog::Accepted));
        QCOMPARE(d.outdatedAfterSave(), 0);
        QVERIFY(QFile::exists(dir.filePath(QStringLiteral("chair_copy.kimobj"))));
        bool listed = false;
        for (const auto& o : kimbim::PythonEngine::instance().callJson("library_objects", {}).object().value("objects").toArray())
            listed = listed || o.toObject().value("id").toString() == QLatin1String("office:chair_copy");
        QVERIFY(listed);

        kimbim::ObjectEditorDialog again(&w, QStringLiteral("office:chair_copy")); // quiet: no replace question
        QVERIFY(!again.saveTo(QStringLiteral("office")));
        QVERIFY(again.saveTo(QStringLiteral("office"), true));
        setOfficeFolder(QString());
    }

    void saveToProjectKeepsTheObject()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("new"));
        d.findChild<QLineEdit*>(QStringLiteral("editorId"))->setText(QStringLiteral("crate"));
        QVERIFY(d.saveTo(QStringLiteral("project")));
        QCOMPARE(d.outdatedAfterSave(), 0);
        bool listed = false;
        for (const auto& o : kimbim::PythonEngine::instance().callJson("library_objects", {}).object().value("objects").toArray())
            listed = listed || o.toObject().value("id").toString() == QLatin1String("project:crate");
        QVERIFY(listed);
    }
};

QTEST_MAIN(TestObjectEditor)
#include "test_object_editor.moc"
