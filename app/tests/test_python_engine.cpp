// SPDX-License-Identifier: GPL-3.0-or-later
#include <QJsonArray>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QtTest>

#include "PythonEngine.h"

class TestPythonEngine : public QObject {
    Q_OBJECT
private slots:
    void initTestCase()
    {
        QString error;
        QVERIFY2(kimcad::PythonEngine::instance().start(&error), qPrintable(error));
    }

    void opensModelAndAnswersQueries()
    {
        QTemporaryDir tmp;
        QVERIFY(QDir(tmp.path()).mkdir(QStringLiteral("Proyecto ñ")));
        const QString path = tmp.filePath(QStringLiteral("Proyecto ñ/modelo.ifc"));
        auto& py = kimcad::PythonEngine::instance();

        QString error;
        QJsonDocument written = py.callJson("_write_test_model", {path}, &error);
        QVERIFY2(written.object().value("ok").toBool(), qPrintable(error));

        QJsonObject info = py.callJson("open_model", {path}, &error).object();
        QVERIFY2(info.value("ok").toBool(), qPrintable(error + info.value("error").toString()));
        QCOMPARE(info.value("schema").toString(), QString("IFC4"));
        QVERIFY(info.value("elements").toInt() >= 2);

        QJsonObject tree = py.callJson("spatial_tree", {}, &error).object();
        QCOMPARE(tree.value("type").toString(), QString("IfcProject"));
        QVERIFY(!tree.value("children").toArray().isEmpty());
    }

    void reportsErrorsInsteadOfThrowing()
    {
        QString error;
        auto& py = kimcad::PythonEngine::instance();
        QJsonObject bad = py.callJson("open_model", {QStringLiteral("does/not/exist.ifc")}, &error).object();
        QCOMPARE(bad.value("ok").toBool(true), false);
        QJsonObject props = py.callJson("properties", {QStringLiteral("nope")}, &error).object();
        QVERIFY(props.contains("error"));
        QJsonDocument missing = py.callJson("no_such_function", {}, &error);
        QVERIFY(missing.isNull());
        QVERIFY(error.contains("no_such_function"));
    }
};

QTEST_MAIN(TestPythonEngine)
#include "test_python_engine.moc"
