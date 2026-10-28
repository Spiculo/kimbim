// SPDX-License-Identifier: GPL-3.0-or-later
// D102 phase 2: the app hosts a live agent session; the CLI finds it, a task becomes a proposal, and the
// Review / Accept path combines it into the base option.
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QProcess>
#include <QProcessEnvironment>
#include <QPushButton>
#include <QSignalSpy>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QThread>
#include <QtTest>

#include <DockManager.h>
#include <DockWidget.h>

#include "AssistantPanel.h"
#include "MainWindow.h"
#include "ProposalBar.h"
#include "PythonEngine.h"
#include "Viewport.h"

namespace {

QString pythonExe()
{
    const QString prefix = qEnvironmentVariable("CONDA_PREFIX");
    if (!prefix.isEmpty()) {
        const QString exe = prefix + QStringLiteral("/python.exe");
        if (QFileInfo::exists(exe))
            return exe;
        const QString bin = prefix + QStringLiteral("/bin/python");
        if (QFileInfo::exists(bin))
            return bin;
    }
    return QStandardPaths::findExecutable(QStringLiteral("python"));
}

QJsonObject runKimbim(const QString& project, const QStringList& args)
{
    QProcess process;
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert(QStringLiteral("PYTHONPATH"), qEnvironmentVariable("KIMBIM_PYTHON_PATH"));
    process.setProcessEnvironment(env);
    process.setProgram(pythonExe());
    QStringList all{QStringLiteral("-m"), QStringLiteral("kimbim"), QStringLiteral("--project"), project};
    all += args;
    all << QStringLiteral("--json");
    process.setArguments(all);
    process.start();
    QElapsedTimer timer;
    timer.start();
    while (process.state() != QProcess::NotRunning && timer.elapsed() < 120000) {
        QCoreApplication::processEvents(); // the live server needs its poll timer while the CLI waits
        QThread::msleep(10);
    }
    if (process.state() != QProcess::NotRunning) {
        process.kill();
        return {};
    }
    const QJsonDocument doc = QJsonDocument::fromJson(process.readAllStandardOutput().trimmed());
    return doc.object();
}

} // namespace

class TestAgentLive : public QObject {
    Q_OBJECT
private slots:
    void initTestCase()
    {
        QStandardPaths::setTestModeEnabled(true);
        QVERIFY(m_tmp.isValid());
        qputenv("KIMBIM_DATA_DIR", m_tmp.filePath(QStringLiteral("data")).toUtf8());
        QString error;
        QVERIFY2(kimbim::PythonEngine::instance().start(&error), qPrintable(error));
        m_ifc = m_tmp.filePath(QStringLiteral("house.ifc"));
        m_kim = m_tmp.filePath(QStringLiteral("house.kim"));
        QVERIFY(kimbim::PythonEngine::instance().callJson("_write_sample_house", {m_ifc}, &error)
                    .object().value("ok").toBool());
        const QJsonObject imported = kimbim::PythonEngine::instance().callJson("import_ifc", {m_ifc, m_kim}, &error)
                                         .object();
        QVERIFY2(imported.value("ok").toBool(), qPrintable(imported.value("error").toString() + error));
        kimbim::PythonEngine::instance().callJson("close_document", {});
    }

    void cliTaskBecomesAProposalAndIsAccepted()
    {
        kimbim::MainWindow w(nullptr, /*quiet=*/true);
        w.resize(1280, 800);
        w.show();
        QSignalSpy loaded(&w, &kimbim::MainWindow::loadFinished);
        QVERIFY(w.openPath(m_kim));
        QVERIFY(loaded.wait(120000));
        QTRY_VERIFY(w.findChild<QLabel*>(QStringLiteral("agentStatus"))->isVisible());
        auto* assistantDock = w.dockLayout()->manager()->findDockWidget(QStringLiteral("assistant"));
        QVERIFY(assistantDock);
        QVERIFY(assistantDock->widget());

        QString wall;
        for (const QString& guid : w.viewport()->guids()) {
            const QJsonObject p = kimbim::PythonEngine::instance().callJson("properties", {guid}).object();
            if (p.value("type").toString() == QLatin1String("IfcWall")) {
                wall = guid;
                break;
            }
        }
        QVERIFY(!wall.isEmpty());

        const QJsonObject started = runKimbim(m_kim, {QStringLiteral("task"), QStringLiteral("start"),
                                                      QStringLiteral("--title"), QStringLiteral("Live walls")});
        QVERIFY2(started.value("ok").toBool(), qPrintable(QJsonDocument(started).toJson()));
        const QString task = started.value("result").toObject().value("id").toString();
        QVERIFY(!task.isEmpty());

        const QJsonObject renamed = runKimbim(m_kim, {QStringLiteral("elements"), QStringLiteral("rename"),
                                                      QStringLiteral("--elements"), QStringLiteral("{\"kind\":\"wall\"}"),
                                                      QStringLiteral("--name"), QStringLiteral("Live wall"),
                                                      QStringLiteral("--task"), task});
        QVERIFY2(renamed.value("ok").toBool(), qPrintable(QJsonDocument(renamed).toJson()));

        const QJsonObject finished = runKimbim(m_kim, {QStringLiteral("task"), QStringLiteral("finish"),
                                                       QStringLiteral("--summary"), QStringLiteral("renamed"),
                                                       QStringLiteral("--task"), task});
        QVERIFY2(finished.value("ok").toBool(), qPrintable(QJsonDocument(finished).toJson()));

        kimbim::ProposalBar* bar = w.findChild<kimbim::ProposalBar*>();
        QVERIFY(bar);
        QTRY_VERIFY(bar->isVisible());
        QPushButton* accept = w.findChild<QPushButton*>(QStringLiteral("proposalAccept"));
        QVERIFY(accept);
        QSignalSpy reloaded(&w, &kimbim::MainWindow::loadFinished);
        accept->click();
        QVERIFY(reloaded.wait(120000));
        QTRY_VERIFY(!bar->isVisible());
        QTRY_VERIFY(kimbim::PythonEngine::instance().callJson("agent_proposals", {})
                        .object().value("proposals").toArray().isEmpty());
        const QJsonObject props = kimbim::PythonEngine::instance().callJson("properties", {wall}).object();
        QCOMPARE(props.value("name").toString(), QStringLiteral("Live wall"));
    }

private:
    QTemporaryDir m_tmp;
    QString m_ifc, m_kim;
};

QTEST_MAIN(TestAgentLive)
#include "test_agent_live.moc"
