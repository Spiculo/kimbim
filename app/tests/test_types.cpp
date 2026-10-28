// SPDX-License-Identifier: GPL-3.0-or-later
// M2: the type manager and classifications dialogs exist in the Model menu and list the model's data.
#include <QAction>
#include <QComboBox>
#include <QJsonObject>
#include <QListWidget>
#include <QSignalSpy>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QTreeWidget>
#include <QtTest>

#include "ClassificationsDialog.h"
#include "MainWindow.h"
#include "PythonEngine.h"
#include "TypeManagerDialog.h"

class TestTypes : public QObject {
    Q_OBJECT
private slots:
    void initTestCase()
    {
        QStandardPaths::setTestModeEnabled(true);
        QString error;
        QVERIFY2(kimbim::PythonEngine::instance().start(&error), qPrintable(error));
        QVERIFY(m_tmp.isValid());
        m_house = m_tmp.filePath(QStringLiteral("house.ifc"));
        const QJsonObject made = kimbim::PythonEngine::instance().callJson("_write_test_model", {m_house}, &error).object();
        QVERIFY2(made.value("ok").toBool(), qPrintable(made.value("error").toString() + error));
    }

    void dialogsListTheModel()
    {
        kimbim::MainWindow w(nullptr, /*quiet=*/true);
        w.resize(1300, 800);
        w.show();
        QSignalSpy done(&w, &kimbim::MainWindow::loadFinished);
        w.openFile(m_house);
        QVERIFY(done.wait(60000));

        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionTypeManager")));
        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionClassifications")));
        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionPushRemote")));
        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionPullRemote")));
        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionCurtainWallTool")));
        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionAddSlabEdge")));
        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionSlabSlope")));

        kimbim::TypeManagerDialog manager(w.selection(), &w);
        QVERIFY(manager.types());
        manager.refresh();
        QVERIFY(manager.types()->columnCount() == 3);

        const QJsonObject made = kimbim::PythonEngine::instance().callJson("create_system",
            {QStringLiteral("Local"), QStringLiteral("Office"), QStringLiteral("2026")}).object();
        QVERIFY2(made.value("ok").toBool(), qPrintable(made.value("error").toString()));
        const QJsonObject code = kimbim::PythonEngine::instance().callJson("add_reference",
            {QStringLiteral("Local"), QStringLiteral("W.01"), QStringLiteral("Walls")}).object();
        QVERIFY2(code.value("ok").toBool(), qPrintable(code.value("error").toString()));

        kimbim::ClassificationsDialog classifications(w.selection(), &w);
        QVERIFY(classifications.systems());
        classifications.setSystem(QStringLiteral("Local"));
        classifications.refresh();
        QCOMPARE(classifications.systems()->currentText(), QStringLiteral("Local"));
        QVERIFY(classifications.references()->count() >= 1);
    }

private:
    QTemporaryDir m_tmp;
    QString m_house;
};

QTEST_MAIN(TestTypes)
#include "test_types.moc"
