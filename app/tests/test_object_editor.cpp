// SPDX-License-Identifier: GPL-3.0-or-later
// D101: the Object Editor dialog: the object's fields, its parameters and materials as tables, its parts,
// components and symbol as a tree, the live preview at the Try values, and saving to the project or the
// office library. A draft with errors marks the fields, keeps the last preview and disables both saves.
#include <Bnd_Box.hxx>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QMenu>
#include <QMessageBox>
#include <QPushButton>
#include <QSpinBox>
#include <QStandardPaths>
#include <QTableWidget>
#include <QTemporaryDir>
#include <QTreeWidget>
#include <QTreeWidgetItemIterator>
#include <QtTest>

#include "JsonTreeEditor.h"
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

kimbim::JsonTreeEditor* partsTree(const kimbim::ObjectEditorDialog& d)
{
    return d.findChild<kimbim::JsonTreeEditor*>(QStringLiteral("editorParts"));
}

// The node of the parts tree at `path` (pathOf), or nullptr.
QTreeWidgetItem* node(const kimbim::ObjectEditorDialog& d, const QString& path)
{
    kimbim::JsonTreeEditor* tree = partsTree(d);
    for (QTreeWidgetItemIterator it(tree->findChild<QTreeWidget*>()); *it; ++it)
        if (tree->pathOf(*it) == path)
            return *it;
    return nullptr;
}

QJsonObject draftPart(const kimbim::ObjectEditorDialog& d, const QString& id)
{
    for (const auto& p : d.draft().value("parts").toArray())
        if (p.toObject().value("id").toString() == id)
            return p.toObject();
    return {};
}

double topOf(const kimbim::ObjectEditorDialog& d)
{
    const Bnd_Box box = preview(d)->boundsOf({});
    if (box.IsVoid())
        return 0.0;
    double x0, y0, z0, x1, y1, z1;
    box.Get(x0, y0, z0, x1, y1, z1);
    return z1;
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
        QTreeWidgetItem* count = nullptr; // the formula that names the old key: its row is red
        for (QTreeWidgetItemIterator it(partsTree(d)->findChild<QTreeWidget*>()); *it; ++it)
            if (partsTree(d)->pathOf(*it).startsWith(QLatin1String("parts.leg")) && !(*it)->text(2).isEmpty())
                count = *it;
        QVERIFY(count);
        QVERIFY(count->text(2).contains(QLatin1String("unknown name 'legs'")));
        QVERIFY(count->toolTip(1).contains(QLatin1String("unknown name 'legs'")));
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

        kimbim::ObjectEditorDialog again(&w, QStringLiteral("office:chair_copy")); // its own file: saved over without asking
        QVERIFY(again.saveTo(QStringLiteral("office")));
        setOfficeFolder(QString());
    }

    void officeObjectWithAnotherIdAsks()
    {
        QTemporaryDir dir;
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        setOfficeFolder(dir.path());
        for (const char* id : {"stool", "bench"}) {
            kimbim::ObjectEditorDialog d(&w, QStringLiteral("new"));
            d.findChild<QLineEdit*>(QStringLiteral("editorId"))->setText(QLatin1String(id));
            QVERIFY(d.saveTo(QStringLiteral("office")));
        }
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("office:stool"));
        d.findChild<QLineEdit*>(QStringLiteral("editorId"))->setText(QStringLiteral("bench"));
        QVERIFY(!d.saveTo(QStringLiteral("office"))); // another object's file: asks (quiet: no)
        QVERIFY(d.saveTo(QStringLiteral("office"), true));
        setOfficeFolder(QString());
    }

    void jsonTreeRoundTrips()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("chair"));
        kimbim::JsonTreeEditor* tree = partsTree(d);
        QVERIFY(tree);
        const QJsonObject draft = d.draft();
        const QJsonObject roots{{"parts", draft.value("parts")}, {"components", draft.value("components")},
            {"symbol", draft.value("symbol")}};
        tree->setRoots(roots);
        QCOMPARE(QJsonDocument(tree->roots()), QJsonDocument(roots));
        QCOMPARE(d.draft(), draft);
    }

    void editingAFieldUpdatesThePreview()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("chair"));
        QTRY_VERIFY(preview(d)->elementCount() > 0);
        const double top = topOf(d);
        QTreeWidgetItem* dz = node(d, QStringLiteral("parts.seat_square.box.dz"));
        QVERIFY(dz);
        QCOMPARE(dz->text(1), QStringLiteral("0.04"));
        dz->setText(1, QStringLiteral("0.5")); // the seat's top rises past the back's
        QTRY_COMPARE(draftPart(d, QStringLiteral("seat_square")).value("box").toObject().value("dz"), QJsonValue(0.5));
        QTRY_VERIFY(topOf(d) > top + 0.01);
    }

    void badFormulaMarksItsRow()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("chair"));
        QTRY_VERIFY(button(d, "editorSaveProject")->isEnabled());
        const QString path = QStringLiteral("components.leg_tapered.parts.post.cone.h");
        QTreeWidgetItem* h = node(d, path);
        QVERIFY(h);
        h->setText(1, QStringLiteral("seat_h -"));
        QTRY_VERIFY(!h->text(2).isEmpty());
        QVERIFY(d.errorPaths().contains(path));
        QVERIFY(!button(d, "editorSaveProject")->isEnabled());
    }

    void addPartFromTemplate()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::ObjectEditorDialog d(&w, QStringLiteral("new"));
        QTRY_VERIFY(button(d, "editorSaveProject")->isEnabled());
        QMenu* menu = button(d, "partsAddPart")->menu();
        QVERIFY(menu);
        QAction* cylinder = nullptr;
        for (QAction* a : menu->actions())
            if (a->text() == QLatin1String("Cylinder"))
                cylinder = a;
        QVERIFY(cylinder);
        cylinder->trigger();
        QVERIFY(node(d, QStringLiteral("parts.part")));
        QVERIFY(node(d, QStringLiteral("parts.part.cylinder.r")));
        QVERIFY(node(d, QStringLiteral("parts.part.cylinder.h")));
        QCOMPARE(draftPart(d, QStringLiteral("part")).value("cylinder").toObject().value("r"), QJsonValue(0.1));
        cylinder->trigger(); // a second one: its id is made unique
        QVERIFY(node(d, QStringLiteral("parts.part2")));
        QVERIFY(d.isDirty());
        QTest::qWait(500); // past the check's pause
        QTRY_VERIFY2(d.errorPaths().isEmpty() && button(d, "editorSaveProject")->isEnabled(),
            qPrintable(d.errorPaths().join(QLatin1Char(','))));
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
