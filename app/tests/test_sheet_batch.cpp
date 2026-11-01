// SPDX-License-Identifier: GPL-3.0-or-later
// Batch PDF publishing: every sheet (or a chosen list) becomes a PDF in one folder.
#include <QDir>
#include <QFile>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QtTest>

#include "PythonEngine.h"
#include "SheetExport.h"

class TestSheetBatch : public QObject {
    Q_OBJECT
private slots:
    void exportsAllSheetsAsPdf()
    {
        QTemporaryDir tmp;
        QVERIFY(tmp.isValid());
        const QString ifc = tmp.filePath(QStringLiteral("house.ifc"));
        QString error;
        auto& py = kimbim::PythonEngine::instance();
        QVERIFY2(py.start(&error), qPrintable(error));
        const QJsonObject made = py.callJson("_write_sample_house", {ifc}, &error).object();
        QVERIFY2(made.value("ok").toBool(), qPrintable(made.value("error").toString() + error));
        QVERIFY(py.callJson("open_model", {ifc}, &error).object().value("ok").toBool());
        const QJsonObject added = py.callJson("add_sheet", {QStringLiteral("A3"), QStringLiteral("Details")},
            &error).object();
        QVERIFY2(added.value("ok").toBool(), qPrintable(added.value("error").toString() + error));
        QVERIFY(py.callJson("save", {ifc}, &error).object().value("ok").toBool());
        py.callJson("close_document", {}, &error);

        const QString folder = tmp.filePath(QStringLiteral("pdf"));
        QCOMPARE(kimbim::exportSheetsCommand(ifc, folder, {}), 0);
        const QDir out(folder);
        const QStringList pdfs = out.entryList({QStringLiteral("*.pdf")}, QDir::Files);
        QCOMPARE(pdfs.size(), 2);
        for (const QString& name : pdfs) {
            QFile file(out.filePath(name));
            QVERIFY(file.open(QIODevice::ReadOnly));
            QCOMPARE(file.read(5), QByteArrayLiteral("%PDF-"));
        }
        QVERIFY(pdfs.contains(QStringLiteral("A01.pdf")));
    }

    void exportsOnlyTheChosenSheets()
    {
        QTemporaryDir tmp;
        QVERIFY(tmp.isValid());
        const QString ifc = tmp.filePath(QStringLiteral("house.ifc"));
        QString error;
        auto& py = kimbim::PythonEngine::instance();
        QVERIFY2(py.start(&error), qPrintable(error));
        QVERIFY(py.callJson("_write_sample_house", {ifc}, &error).object().value("ok").toBool());
        QVERIFY(py.callJson("open_model", {ifc}, &error).object().value("ok").toBool());
        QVERIFY(py.callJson("add_sheet", {QStringLiteral("A3"), QStringLiteral("Details")}, &error)
                    .object().value("ok").toBool());
        QVERIFY(py.callJson("save", {ifc}, &error).object().value("ok").toBool());
        py.callJson("close_document", {}, &error);

        const QString folder = tmp.filePath(QStringLiteral("one"));
        QCOMPARE(kimbim::exportSheetsCommand(ifc, folder, {QStringLiteral("A02")}), 0);
        const QStringList pdfs = QDir(folder).entryList({QStringLiteral("*.pdf")}, QDir::Files);
        QCOMPARE(pdfs, QStringList{QStringLiteral("A02.pdf")});

        QCOMPARE(kimbim::exportSheetsCommand(ifc, tmp.filePath(QStringLiteral("none")),
                     {QStringLiteral("Z99")}), 1);
    }
};

QTEST_MAIN(TestSheetBatch)
#include "test_sheet_batch.moc"
