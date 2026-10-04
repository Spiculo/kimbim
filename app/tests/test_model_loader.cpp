// SPDX-License-Identifier: GPL-3.0-or-later
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QtTest>

#include "ModelLoader.h"
#include "PythonEngine.h"

class TestModelLoader : public QObject {
    Q_OBJECT
private slots:
    void initTestCase()
    {
        qRegisterMetaType<kimcad::MeshChunk>();
        QString error;
        QVERIFY2(kimcad::PythonEngine::instance().start(&error), qPrintable(error));
    }

    void loadsAllChunks()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath(QStringLiteral("m.ifc"));
        kimcad::PythonEngine::instance().callJson("_write_test_model", {path});
        kimcad::ModelLoader loader(1);
        QSignalSpy chunks(&loader, &kimcad::ModelLoader::chunkReady);
        QSignalSpy finished(&loader, &kimcad::ModelLoader::finished);
        loader.load(path);
        QCOMPARE(chunks.count(), 2);
        QCOMPARE(finished.count(), 1);
        QCOMPARE(finished.first().at(1).toBool(), false);
    }

    // Closing right after File->Open: the stop request arrives before the worker starts load().
    // The load must honour it instead of running to the end (the close would wait for it).
    void stopRequestedBeforeLoadStartsIsHonoured()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath(QStringLiteral("m.ifc"));
        kimcad::PythonEngine::instance().callJson("_write_test_model", {path});
        kimcad::ModelLoader loader(1);
        QSignalSpy chunks(&loader, &kimcad::ModelLoader::chunkReady);
        QSignalSpy finished(&loader, &kimcad::ModelLoader::finished);
        loader.requestStop();
        loader.load(path);
        QCOMPARE(chunks.count(), 0);
        QCOMPARE(finished.count(), 1);
        QCOMPARE(finished.first().at(1).toBool(), true);
        // and the next load works normally once re-armed
        loader.reset();
        loader.load(path);
        QCOMPARE(chunks.count(), 2);
    }
};

QTEST_MAIN(TestModelLoader)
#include "test_model_loader.moc"
