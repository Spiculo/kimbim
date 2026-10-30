// SPDX-License-Identifier: GPL-3.0-or-later
// D102 phase 2: the app hosts a live agent session; the CLI finds it, a task becomes a proposal, and the
// Review / Accept path combines it into the base option.
#include <QApplication>
#include <QComboBox>
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
#include <QTableWidget>
#include <QThread>
#include <QTimer>
#include <QTreeWidget>
#include <QtTest>

#include <DockManager.h>
#include <DockWidget.h>

#include "AssistantPanel.h"
#include "MainWindow.h"
#include "ProposalBar.h"
#include "ProposalDialog.h"
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
        // isVisible() on a widget inside a tool bar's QWidgetAction said true while the widget stayed
        // hidden (the owner saw no bar at all); the hidden flag is the one that decides painting.
        QTRY_VERIFY(bar->isVisible() && !bar->isHidden());
        // The owner can hide a proposal that is not being reviewed; the bar comes back on request and
        // by itself when the set of proposals changes (tested through the findable hide button).
        QPushButton* hide = w.findChild<QPushButton*>(QStringLiteral("proposalHide"));
        QVERIFY(hide);
        hide->click();
        QTRY_VERIFY(bar->isHidden());
        bar->showAgain();
        QTRY_VERIFY(!bar->isHidden());
        QPushButton* review = w.findChild<QPushButton*>(QStringLiteral("proposalReview"));
        QVERIFY(review);
        bool sawDialog = false, sawChanges = false, accepted = false;
        QTimer::singleShot(250, &w, [&] {
            auto* dialog = qobject_cast<kimbim::ProposalDialog*>(QApplication::activeModalWidget());
            if (!dialog)
                return;
            sawDialog = true;
            sawChanges = dialog->changeTree()->topLevelItemCount() > 0;
            auto* accept = dialog->acceptButton();
            if (accept && accept->isEnabled()) {
                accepted = true;
                accept->click(); // Review opens the IDE-like diff/merge window
            } else {
                dialog->reject(); // never leave the test hanging in a modal loop
            }
        });
        QSignalSpy reloaded(&w, &kimbim::MainWindow::loadFinished);
        review->click();
        QVERIFY(reloaded.wait(120000));
        QVERIFY(sawDialog);
        QVERIFY(sawChanges);
        QVERIFY(accepted);
        QTRY_VERIFY(!bar->isVisible());
        QTRY_VERIFY(kimbim::PythonEngine::instance().callJson("agent_proposals", {})
                        .object().value("proposals").toArray().isEmpty());
        QTRY_VERIFY(kimbim::PythonEngine::instance().callJson("properties", {wall})
                        .object().value("name").toString() == QLatin1String("Live wall"));
    }

    void proposalDialogShowsTheDiffAndResolvesConflicts()
    {
        const QJsonObject proposal{{QStringLiteral("title"), QStringLiteral("Widen windows")},
            {QStringLiteral("client"), QStringLiteral("Assistant")},
            {QStringLiteral("summary"), QStringLiteral("Widened the first floor windows.")},
            {QStringLiteral("option"), QStringLiteral("agent/widen")},
            {QStringLiteral("base_option"), QStringLiteral("main")},
            {QStringLiteral("base_version"), QStringLiteral("abc123")},
            {QStringLiteral("counts"), QJsonObject{{QStringLiteral("modified"), 1}}}};
        const auto bridge = [](const char* fn, const QStringList& args) -> QJsonObject {
            const QString name = QLatin1String(fn);
            if (name == QLatin1String("compare"))
                return {{QStringLiteral("ok"), true},
                    {QStringLiteral("added"), QJsonArray{}},
                    {QStringLiteral("modified"), QJsonArray{QJsonObject{{QStringLiteral("guid"), QStringLiteral("g1")},
                                                          {QStringLiteral("name"), QStringLiteral("Window")},
                                                          {QStringLiteral("type"), QStringLiteral("IfcWindow")}}}},
                    {QStringLiteral("removed"), QJsonArray{}}};
            if (name == QLatin1String("before_after"))
                return {{QStringLiteral("ok"), true}, {QStringLiteral("before_exists"), true},
                    {QStringLiteral("after_exists"), true},
                    {QStringLiteral("rows"), QJsonArray{QJsonObject{{QStringLiteral("field"), QStringLiteral("Width")},
                                                          {QStringLiteral("before"), QStringLiteral("1.2")},
                                                          {QStringLiteral("after"), QStringLiteral("1.7")},
                                                          {QStringLiteral("changed"), true}}}}};
            if (name == QLatin1String("combine_preview")) {
                const QJsonObject resolutions = QJsonDocument::fromJson(args.value(1).toUtf8()).object();
                const bool resolved = resolutions.contains(QStringLiteral("c1"));
                return {{QStringLiteral("ok"), true}, {QStringLiteral("status"), QStringLiteral("merge")},
                    {QStringLiteral("from_theirs"), QJsonArray{QStringLiteral("g1")}},
                    {QStringLiteral("conflicts"),
                        QJsonArray{QJsonObject{{QStringLiteral("id"), QStringLiteral("c1")},
                            {QStringLiteral("kind"), QStringLiteral("attribute")},
                            {QStringLiteral("ifc_type"), QStringLiteral("IfcWindow")},
                            {QStringLiteral("name"), QStringLiteral("Window")},
                            {QStringLiteral("attribute"), QStringLiteral("Width")},
                            {QStringLiteral("base_text"), QStringLiteral("1.2")},
                            {QStringLiteral("ours_text"), QStringLiteral("1.3")},
                            {QStringLiteral("theirs_text"), QStringLiteral("1.7")},
                            {QStringLiteral("options"), QJsonArray{QStringLiteral("ours"), QStringLiteral("theirs")}}}}},
                    {QStringLiteral("unresolved"), resolved ? QJsonArray{} : QJsonArray{QStringLiteral("c1")}}};
            }
            return {{QStringLiteral("ok"), false}, {QStringLiteral("error"), QStringLiteral("unexpected call")}};
        };
        kimbim::ProposalDialog dialog(bridge, proposal);
        QCOMPARE(dialog.changeTree()->topLevelItemCount(), 3);
        QTreeWidgetItem* modified = dialog.changeTree()->topLevelItem(1);
        QVERIFY(modified && modified->childCount() == 1);
        dialog.changeTree()->setCurrentItem(modified->child(0));
        QCOMPARE(dialog.findChild<QTableWidget*>(QStringLiteral("proposalDetails"))->rowCount(), 1);
        QCOMPARE(dialog.conflictTable()->rowCount(), 1);
        QVERIFY(!dialog.acceptButton()->isEnabled()); // c1 has no choice yet
        auto* box = qobject_cast<QComboBox*>(dialog.conflictTable()->cellWidget(0, 5));
        QVERIFY(box);
        box->setCurrentIndex(box->findData(QStringLiteral("theirs")));
        QCoreApplication::processEvents(); // the dialog refreshes the conflicts after a choice
        QVERIFY(dialog.acceptButton()->isEnabled());
        QCOMPARE(dialog.resolutions().value(QStringLiteral("c1")).toString(), QStringLiteral("theirs"));
    }

private:
    QTemporaryDir m_tmp;
    QString m_ifc, m_kim;
};

QTEST_MAIN(TestAgentLive)
#include "test_agent_live.moc"
