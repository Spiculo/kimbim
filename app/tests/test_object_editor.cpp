// SPDX-License-Identifier: GPL-3.0-or-later
// D101: the Object Editor dialog: the object's fields, its parameters and materials as tables, its parts,
// components and symbol as a tree, the live preview at the Try values, and saving to the project or the
// office library. A draft with errors marks the fields, keeps the last preview and disables both saves.
#include <Bnd_Box.hxx>
#include <QAction>
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
#include <cmath>

#include "JsonTreeEditor.h"
#include "LibraryPanel.h"
#include "MainWindow.h"
#include "ObjectEditorDialog.h"
#include "PropertiesPanel.h"
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

// The heading of the Library panel category that lists object `id`, or "".
QString categoryOf(kimbim::LibraryPanel* panel, const QString& id)
{
    QTreeWidget* tree = panel->tree();
    for (int i = 0; i < tree->topLevelItemCount(); ++i)
        for (int j = 0; j < tree->topLevelItem(i)->childCount(); ++j)
            if (tree->topLevelItem(i)->child(j)->data(0, Qt::UserRole + 1).toString() == id)
                return tree->topLevelItem(i)->text(0);
    return {};
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

    // D101, doc 16 §9: the Object Editor makes a 3-leg chair, saves it to the office library, the Object
    // tool places it, the 3D and the plan show three legs; Update from library after the file changes.
    void threeLegChairEndToEnd()
    {
        QTemporaryDir dir;
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::LibraryPanel* panel = w.libraryPanel(); // it sends the (empty) preferences' paths: first
        setOfficeFolder(dir.path());
        bool edited = false;
        QTimer::singleShot(0, &w, [&] {
            auto* d = qobject_cast<kimbim::ObjectEditorDialog*>(QApplication::activeModalWidget());
            if (!d) {
                if (QWidget* other = QApplication::activeModalWidget())
                    other->close();
                return;
            }
            // The chair's legs follow `legs` on a circle; splayed 8° under a round seat, each foot sticks
            // out past the seat. Without its drawn symbol the plan is the parts' outline (doc 16 §3).
            QJsonObject draft = d->draft();
            draft.remove(QStringLiteral("symbol"));
            d->setDraft(draft);
            auto* table = d->findChild<QTableWidget*>(QStringLiteral("editorParams"));
            const auto setDefault = [&](const char* key, const char* value) {
                table->item(paramRow(*d, QLatin1String(key)), 4)->setText(QLatin1String(value));
            };
            setDefault("legs", "3");
            setDefault("layout", "circle");
            setDefault("seat_shape", "round");
            setDefault("splay", "8");
            edited = draftParam(*d, QStringLiteral("legs")).value("default").toInt() == 3
                && draftParam(*d, QStringLiteral("layout")).value("default").toString() == QLatin1String("circle");
            d->saveTo(QStringLiteral("office"));
        });
        QVERIFY(w.openObjectEditor(QStringLiteral("chair")));
        QVERIFY(edited);
        QVERIFY(QFile::exists(dir.filePath(QStringLiteral("chair_copy.kimobj"))));
        QVERIFY(panel->objectIds().contains(QStringLiteral("office:chair_copy"))); // the listing follows

        QVERIFY(panel->selectObject(QStringLiteral("office:chair_copy")));
        w.setTool(kimbim::MainWindow::Tool::Object);
        const QStringList before = w.viewport()->guids();
        QVERIFY(w.placeObjectAt(QPointF(1, 1)));
        w.setTool(kimbim::MainWindow::Tool::None);
        QStringList made;
        for (const QString& g : w.viewport()->guids())
            if (!before.contains(g))
                made << g;
        QCOMPARE(made.size(), 1);

        // 3D: the solids of the placed type's Body, counted by their building material. The legs are the
        // only parts of the frame material (Steel; no arms), the seat and back are Timber, so the count
        // is the legs' and does not depend on how many other parts the chair has.
        const QJsonObject legs = w.runConsole(QStringLiteral(
            "import ifcopenshell.util.element as U\n"
            "t = U.get_type(ifc.by_guid('%1'))\n"
            "body = next(m.MappedRepresentation for m in t.RepresentationMaps if m.MappedRepresentation.RepresentationIdentifier == 'Body')\n"
            "names = [s.Name for i in body.Items for st in i.StyledByItem for s in (getattr(st, 'Styles', None) or ())]\n"
            "names.count('Steel'), len(body.Items)").arg(made[0]));
        QVERIFY2(legs.value("ok").toBool(), qPrintable(legs.value("traceback").toString()));
        QCOMPARE(legs.value("output").toString(), QStringLiteral("(3, 5)\n")); // 3 legs, the seat, the back

        // Plan: the placed type's symbol (its stored definition) is one outline, the round seat with a bump
        // where each splayed foot sticks out past it: three runs of points outside the seat's circle.
        const QJsonObject of = kimbim::PythonEngine::instance()
            .callJson("object_settings_of", {QStringLiteral("[\"%1\"]").arg(made[0])}).object();
        QVERIFY(of.value("source").toString().startsWith(QLatin1String("type:")));
        const QJsonObject symbol = kimbim::PythonEngine::instance()
            .callJson("object_symbol", {of.value("key").toString(), QString(), of.value("source").toString()}).object();
        const QJsonArray lines = symbol.value("symbol").toArray();
        QCOMPARE(lines.size(), 1);
        const double cx = 0.45 / 2, cy = 0.5 / 2, r = 0.45 / 2; // the chair's width and depth
        QJsonArray ring = lines.at(0).toArray();
        ring.removeLast(); // closed: the first point again
        QList<bool> outside;
        for (const auto& p : ring)
            outside << (std::hypot(p.toArray().at(0).toDouble() - cx, p.toArray().at(1).toDouble() - cy) > r + 1e-3);
        int runs = 0;
        for (int i = 0; i < outside.size(); ++i)
            runs += outside[i] && !outside[(i + outside.size() - 1) % outside.size()] ? 1 : 0;
        QCOMPARE(runs, 3);

        // The office edits the file (width 0.5): Update from library offers the placed chair, then it is 0.5.
        QFile file(dir.filePath(QStringLiteral("chair_copy.kimobj")));
        QVERIFY(file.open(QIODevice::ReadOnly));
        QJsonObject def = QJsonDocument::fromJson(file.readAll()).object();
        file.close();
        QJsonArray params = def.value("params").toArray();
        for (int i = 0; i < params.size(); ++i)
            if (params[i].toObject().value("key").toString() == QLatin1String("width")) {
                QJsonObject p = params[i].toObject();
                p.insert("default", 0.5);
                params[i] = p;
            }
        def.insert("params", params);
        QVERIFY(file.open(QIODevice::WriteOnly | QIODevice::Truncate));
        file.write(QJsonDocument(def).toJson());
        file.close();
        setOfficeFolder(dir.path()); // read again
        const QJsonObject pending = kimbim::PythonEngine::instance().callJson("library_updates", {QString()}).object();
        QCOMPARE(pending.value("outdated").toInt(), 1);
        w.setUpdateAnswerForTests(true);
        w.offerLibraryUpdate(pending.value("outdated").toInt());
        QCOMPARE(kimbim::PythonEngine::instance().callJson("library_updates", {QString()}).object().value("outdated").toInt(), 0);
        // The placed chair's type now carries the new definition: its width default is 0.5. Its own width
        // stays 0.45: Update from library keeps every value whose key and kind still exist (D99).
        const QJsonObject stored = w.runConsole(QStringLiteral(
            "import ifcopenshell.util.element as U\n"
            "from kimbim import library\n"
            "t = U.get_type(ifc.by_guid('%1'))\n"
            "library.definition_of_type(t).param('width').default, library._params_of_type(t)[1]['width']").arg(made[0]));
        QVERIFY2(stored.value("ok").toBool(), qPrintable(stored.value("traceback").toString()));
        QCOMPARE(stored.value("output").toString(), QStringLiteral("(0.5, 0.45)\n"));
        setOfficeFolder(QString());
    }

    // D101: an object saved to the project is listed under Project; undo takes it away, listing too.
    void projectObjectUndo()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        kimbim::LibraryPanel* panel = w.libraryPanel();
        QTimer::singleShot(0, &w, [&] {
            auto* d = qobject_cast<kimbim::ObjectEditorDialog*>(QApplication::activeModalWidget());
            if (!d) {
                if (QWidget* other = QApplication::activeModalWidget())
                    other->close();
                return;
            }
            d->findChild<QLineEdit*>(QStringLiteral("editorId"))->setText(QStringLiteral("crate"));
            d->saveTo(QStringLiteral("project"));
        });
        QSignalSpy asked(panel, &kimbim::LibraryPanel::newObjectRequested);
        panel->findChild<QPushButton*>(QStringLiteral("libraryNewObject"))->click(); // opens the editor on "new"
        QCOMPARE(asked.count(), 1);
        QCOMPARE(categoryOf(panel, QStringLiteral("project:crate")), QStringLiteral("Project"));
        w.findChild<QAction*>(QStringLiteral("actionUndo"))->trigger();
        QVERIFY(!panel->objectIds().contains(QStringLiteral("project:crate")));
        w.findChild<QAction*>(QStringLiteral("actionRedo"))->trigger();
        QVERIFY(panel->objectIds().contains(QStringLiteral("project:crate")));
    }

    // D101: Customise a copy (Properties, beside Edit..., and the Model menu) opens the editor on the
    // selection's type; it starts from the type's values.
    void customiseACopyOfThePlacedType()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.chooseObject(QStringLiteral("chair"), QJsonObject{{"width", 0.6}}));
        const QStringList before = w.viewport()->guids();
        QVERIFY(w.placeObjectAt(QPointF(1, 1)));
        w.setTool(kimbim::MainWindow::Tool::None);
        QStringList made;
        for (const QString& g : w.viewport()->guids())
            if (!before.contains(g))
                made << g;
        QCOMPARE(made.size(), 1);
        w.setSelection(made);
        auto* copy = w.propertiesPanel()->findChild<QPushButton*>(QStringLiteral("objectCustomiseCopy"));
        QVERIFY(copy);
        QVERIFY(copy->isEnabled());
        QCOMPARE(copy->text(), QStringLiteral("Customise a copy..."));
        QString title;
        double width = 0;
        const auto look = [&] {
            QTimer::singleShot(0, &w, [&] {
                auto* d = qobject_cast<kimbim::ObjectEditorDialog*>(QApplication::activeModalWidget());
                if (!d) {
                    if (QWidget* other = QApplication::activeModalWidget())
                        other->close();
                    return;
                }
                title = d->windowTitle();
                width = draftParam(*d, QStringLiteral("width")).value("default").toDouble();
                d->reject(); // unchanged: no question
            });
        };
        look();
        copy->click();
        QVERIFY(title.startsWith(QStringLiteral("Object editor")));
        QCOMPARE(width, 0.6); // the type's values are the copy's defaults
        title.clear();
        look();
        w.findChild<QAction*>(QStringLiteral("actionCustomiseObjectCopy"))->trigger();
        QVERIFY(title.startsWith(QStringLiteral("Object editor")));
        w.setSelection({}); // nothing selected: no editor
        QVERIFY(!w.customiseObjectCopy());
    }
};

QTEST_MAIN(TestObjectEditor)
#include "test_object_editor.moc"
