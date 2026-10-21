// SPDX-License-Identifier: GPL-3.0-or-later
// D83: the Export DXF dialog (File > Export DXF...): items, options, the worker thread, progress,
// errors, cancel; and one real export through the Python engine.
#include <QCheckBox>
#include <QComboBox>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QMutex>
#include <QProgressBar>
#include <QPushButton>
#include <QSemaphore>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QThread>
#include <QTreeWidget>
#include <QtTest>

#include "DxfExportDialog.h"
#include "PythonEngine.h"

namespace {
QJsonObject targets()
{
    return QJsonDocument::fromJson(R"({"ok": true,
        "drawings": [{"guid": "G1", "name": "Level 1 Floor Plan", "kind": "plan", "file": "Level 1 Floor Plan.dxf"},
                     {"guid": "G2", "name": "Section 1", "kind": "section", "file": "Section 1.dxf"}],
        "sheets": [{"number": "A01", "title": "Plans", "file": "A01 Plans.dxf"}]})").object();
}

struct Call {
    QByteArray fn;
    QStringList args;
    bool mainThread;
};
} // namespace

class TestDxfExport : public QObject {
    Q_OBJECT
private slots:
    void listsDrawingsAndSheetsAllTicked()
    {
        kimbim::DxfExportDialog dialog(targets(), [](const char*, const QStringList&) { return QJsonObject(); });
        QCOMPARE(dialog.tree()->topLevelItemCount(), 2);
        QCOMPARE(dialog.tree()->topLevelItem(0)->childCount(), 2);
        QCOMPARE(dialog.tree()->topLevelItem(1)->childCount(), 1);
        QCOMPARE(dialog.tree()->topLevelItem(0)->child(0)->text(1), QString("Level 1 Floor Plan.dxf"));
        const QJsonArray all = dialog.checkedItems();
        QCOMPARE(all.size(), 3);
        QCOMPARE(all.at(0).toObject().value("drawing").toString(), QString("G1"));
        QCOMPARE(all.at(2).toObject().value("sheet").toString(), QString("A01"));
        QVERIFY(!dialog.exportButton()->isEnabled()); // no folder yet
        dialog.setFolder(QDir::tempPath());
        QVERIFY(dialog.exportButton()->isEnabled());
        dialog.setAllChecked(false);
        QVERIFY(!dialog.exportButton()->isEnabled()); // nothing ticked
        dialog.setChecked("A01", true);
        QCOMPARE(dialog.checkedItems().size(), 1);
        QCOMPARE(dialog.layerMode(), QString("layer"));
        dialog.setLayerMode("kind");
        QCOMPARE(dialog.options().value("layers").toString(), QString("kind"));
        dialog.findChild<QCheckBox*>("dxfDimensions")->setChecked(false);
        QCOMPARE(dialog.options().value("dimensions").toString(), QString("exploded"));
        // D92: the new export options are in the dialog.
        dialog.setLayerMode("iso");
        QCOMPARE(dialog.options().value("layers").toString(), QString("iso"));
        dialog.setLayerMode("pen");
        QCOMPARE(dialog.layerMode(), QString("pen"));
        QCOMPARE(dialog.options().value("colour").toString(), QString("exact"));
        dialog.findChild<QComboBox*>("dxfColour")->setCurrentIndex(1);
        QCOMPARE(dialog.options().value("colour").toString(), QString("aci"));
        QCOMPARE(dialog.options().value("poche").toBool(), true);
        dialog.findChild<QCheckBox*>("dxfPoche")->setChecked(false);
        QCOMPARE(dialog.options().value("poche").toBool(), false);
    }

    void exportsOnAWorkerThreadWithProgressAndErrors()
    {
        QTemporaryDir dir;
        QMutex mutex;
        QList<Call> calls;
        QThread* gui = QThread::currentThread();
        kimbim::DxfExportDialog dialog(targets(), [&](const char* fn, const QStringList& args) {
            QMutexLocker lock(&mutex);
            calls.append({fn, args, QThread::currentThread() == gui});
            if (args.value(0) == "G2")
                return QJsonObject{{"ok", false}, {"error", "could not generate Section 1"}};
            return QJsonObject{{"ok", true}, {"path", args.value(1)}};
        });
        dialog.setFolder(dir.filePath("out")); // made by the dialog
        dialog.setLayerMode("kind");
        QSignalSpy progress(&dialog, &kimbim::DxfExportDialog::progressed);
        QSignalSpy finished(&dialog, &kimbim::DxfExportDialog::finished);
        dialog.start();
        QVERIFY(dialog.isRunning());
        QVERIFY(!dialog.exportButton()->isEnabled());
        QVERIFY(finished.wait(5000));
        QVERIFY(!dialog.isRunning());
        QCOMPARE(calls.size(), 3);
        for (const Call& c : calls)
            QVERIFY2(!c.mainThread, "the export must not run on the GUI thread");
        QCOMPARE(calls.at(0).fn, QByteArray("export_drawing_dxf"));
        QCOMPARE(calls.at(2).fn, QByteArray("export_sheet_dxf"));
        QCOMPARE(calls.at(0).args.at(1), QDir(dir.filePath("out")).filePath("Level 1 Floor Plan.dxf"));
        QCOMPARE(QJsonDocument::fromJson(calls.at(0).args.at(2).toUtf8()).object().value("layers").toString(), QString("kind"));
        QVERIFY(QDir(dir.filePath("out")).exists());
        QCOMPARE(progress.size(), 3);
        QCOMPARE(dialog.progressBar()->value(), 3);
        QCOMPARE(dialog.files().size(), 2);
        QCOMPARE(dialog.errors().size(), 1);
        QVERIFY(dialog.errors().first().contains("Section 1.dxf"));
        QVERIFY(dialog.statusLabel()->text().contains("could not generate Section 1"));
        QVERIFY(dialog.exportButton()->isEnabled()); // can export again
    }

    void cancelStopsAfterTheCurrentFile()
    {
        QTemporaryDir dir;
        QSemaphore entered, release;
        std::atomic<int> count{0};
        kimbim::DxfExportDialog dialog(targets(), [&](const char*, const QStringList& args) {
            ++count;
            entered.release();
            release.acquire(); // the first file is "being written" until the test lets it go
            return QJsonObject{{"ok", true}, {"path", args.value(1)}};
        });
        dialog.setFolder(dir.path());
        QSignalSpy finished(&dialog, &kimbim::DxfExportDialog::finished);
        dialog.start();
        QVERIFY(entered.tryAcquire(1, 5000));
        dialog.reject(); // Escape while exporting cancels instead of closing
        QVERIFY(dialog.isRunning());
        release.release(3);
        QVERIFY(finished.wait(5000));
        QCOMPARE(count.load(), 1);
        QCOMPARE(dialog.files().size(), 1);
        QVERIFY(dialog.statusLabel()->text().startsWith("Cancelled"));
    }

    void realExportThroughPython()
    {
        QString error;
        auto& py = kimbim::PythonEngine::instance();
        QVERIFY2(py.start(&error), qPrintable(error));
        QVERIFY(py.callJson("new_project", {"DXF test"}, &error).object().value("ok").toBool());
        QVERIFY(py.callJson("create_drawings", {}, &error).object().value("ok").toBool());
        const QJsonObject t = py.callJson("dxf_targets", {}, &error).object();
        QVERIFY(!t.value("drawings").toArray().isEmpty());
        QTemporaryDir dir;
        kimbim::DxfExportDialog dialog(t, [](const char* fn, const QStringList& args) {
            QString e;
            return kimbim::PythonEngine::instance().callJson(fn, args, &e).object();
        });
        dialog.setAllChecked(false);
        QString south;
        for (const auto& v : t.value("drawings").toArray())
            if (v.toObject().value("name").toString() == "South Elevation")
                south = v.toObject().value("guid").toString();
        QVERIFY(!south.isEmpty());
        dialog.setChecked(south, true);
        dialog.setFolder(dir.path());
        QSignalSpy finished(&dialog, &kimbim::DxfExportDialog::finished);
        dialog.start();
        QVERIFY(finished.wait(60000));
        QVERIFY2(dialog.errors().isEmpty(), qPrintable(dialog.errors().join("; ")));
        QFile file(QDir(dir.path()).filePath("South Elevation.dxf"));
        QVERIFY(file.open(QIODevice::ReadOnly));
        const QByteArray head = file.read(64);
        QVERIFY(head.contains("SECTION"));
        file.seek(0);
        QVERIFY(file.readAll().contains("$INSUNITS"));
    }
};

QTEST_MAIN(TestDxfExport)
#include "test_dxf_export.moc"
