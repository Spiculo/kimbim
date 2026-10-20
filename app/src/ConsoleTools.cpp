// SPDX-License-Identifier: GPL-3.0-or-later
// The Python console (D82): MainWindow members kept in their own file. The code runs in the embedded
// interpreter (kimbim.console) on a worker thread; the window stays painted and a Stop button can
// interrupt it. Its edits come back like the app's own (one undo step, afterEdit).
#include "MainWindow.h"

#include "ConsolePanel.h"
#include "DockLayout.h"
#include "PythonEngine.h"

#include <DockManager.h>

#include <QAction>
#include <QApplication>
#include <QDialog>
#include <QDir>
#include <QEventLoop>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QMenu>
#include <QPushButton>
#include <QThread>
#include <QTimer>
#include <QVBoxLayout>

#include <thread>

namespace kimbim {

void MainWindow::buildConsoleActions()
{
    // Archicad keeps its Python palette under Window > Palettes: here View > Panels.
    auto* show = new QAction(tr("Python &console"), this);
    show->setObjectName(QStringLiteral("actionConsole"));
    show->setShortcut(QKeySequence(Qt::CTRL | Qt::ALT | Qt::Key_P));
    show->setToolTip(tr("Run Python on the open model (ifcopenshell and KimBim's commands)"));
    connect(show, &QAction::triggered, this, [this] {
        consolePanel();
        m_dock->raisePanel(QStringLiteral("console"));
        m_console->input()->setFocus();
    });
    if (auto* panels = findChild<QMenu*>(QStringLiteral("panelsMenu")))
        panels->addAction(show); // with the other panels opened on demand (D90)
    addAction(show); // the shortcut works before the menu was ever opened
    auto* script = new QAction(tr("Run Python scrip&t..."), this);
    script->setObjectName(QStringLiteral("actionRunScript"));
    script->setToolTip(tr("Run a .py file in the Python console"));
    connect(script, &QAction::triggered, this, &MainWindow::runScriptDialog);
    if (QMenu* file = qobject_cast<QMenu*>(m_recentMenu->parentWidget())) {
        QAction* after = nullptr; // just after Recent files, before the separator
        const QList<QAction*> actions = file->actions();
        const int at = int(actions.indexOf(m_recentMenu->menuAction()));
        if (at >= 0 && at + 1 < actions.size())
            after = actions.at(at + 1);
        file->insertAction(after, script);
    }
}

ConsolePanel* MainWindow::consolePanel()
{
    if (m_console)
        return m_console;
    m_console = new ConsolePanel(this);
    m_dock->addPanel(QStringLiteral("console"), tr("Console"), m_console);
    connect(m_console, &ConsolePanel::runRequested, this, [this](const QString& code) { runConsole(code); });
    connect(m_console, &ConsolePanel::runFileRequested, this, &MainWindow::runScriptDialog);
    return m_console;
}

QJsonObject MainWindow::runConsole(const QString& code)
{
    return runConsoleCall("console_run", code);
}

QJsonObject MainWindow::runConsoleFile(const QString& path)
{
    return runConsoleCall("console_run_file", path);
}

void MainWindow::runScriptDialog()
{
    if (m_quiet)
        return;
    const QString path = QFileDialog::getOpenFileName(this, tr("Run Python script"), QString(), tr("Python script (*.py)"));
    if (path.isEmpty())
        return;
    consolePanel();
    m_dock->raisePanel(QStringLiteral("console"));
    m_console->appendInput(QStringLiteral("# %1").arg(QDir::toNativeSeparators(path)));
    runConsoleFile(path);
}

QJsonObject MainWindow::runConsoleCall(const char* fn, const QString& arg)
{
    consolePanel();
    m_recoveryTimer.stop(); // nothing else reaches the bridge while the script runs
    const QString selection = QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(m_selection)).toJson(QJsonDocument::Compact));
    QJsonObject r;
    QString error;
    const QByteArray name(fn);
    QThread* worker = QThread::create([&] {
        r = PythonEngine::instance().callJson(name.constData(), {arg, selection}, &error).object();
    });

    // A short script just runs (input held back meanwhile); a long one shows a modal dialog with Stop.
    QDialog running(this);
    running.setWindowTitle(QStringLiteral("KimBim"));
    running.setModal(true);
    running.setWindowModality(Qt::ApplicationModal); // the console may float in its own window
    running.setWindowFlag(Qt::WindowCloseButtonHint, false);
    auto* label = new QLabel(tr("Running the script..."), &running);
    auto* stop = new QPushButton(tr("Stop"), &running);
    stop->setObjectName(QStringLiteral("consoleStop"));
    stop->setToolTip(tr("Interrupt the script at its next line (KeyboardInterrupt)"));
    stop->setShortcut(QKeySequence(Qt::CTRL | Qt::Key_C));
    auto* layout = new QVBoxLayout(&running);
    layout->addWidget(label);
    auto* row = new QHBoxLayout;
    row->addStretch();
    row->addWidget(stop);
    layout->addLayout(row);
    connect(stop, &QPushButton::clicked, &running, [label, stop] {
        label->setText(tr("Stopping: the script stops at its next line of Python..."));
        stop->setEnabled(false);
        // Taking the GIL can wait for a long call in C to return: never on the UI thread.
        std::thread([] { PythonEngine::instance().callJson("console_stop", {}); }).detach();
    });

    QApplication::setOverrideCursor(Qt::BusyCursor);
    {
        QEventLoop loop;
        connect(worker, &QThread::finished, &loop, &QEventLoop::quit);
        if (!m_quiet)
            QTimer::singleShot(400, &loop, &QEventLoop::quit);
        worker->start();
        loop.exec(QEventLoop::ExcludeUserInputEvents);
    }
    if (!worker->isFinished()) {
        QEventLoop loop;
        connect(worker, &QThread::finished, &loop, &QEventLoop::quit);
        if (!worker->isFinished()) {
            QApplication::restoreOverrideCursor();
            running.show();
            loop.exec();
            running.hide();
            QApplication::setOverrideCursor(Qt::BusyCursor);
        }
    }
    worker->wait();
    delete worker;
    QApplication::restoreOverrideCursor();
    restartRecoveryTimer();

    if (r.isEmpty())
        r = QJsonObject{{"ok", false}, {"error", error.isEmpty() ? tr("The console returned nothing") : error}};
    if (!r.value("ok").toBool()) {
        m_console->appendOutput(r.value("error").toString(), true);
        return r;
    }
    m_console->appendOutput(r.value("output").toString(), false);
    m_console->appendOutput(r.value("traceback").toString(), true);
    if (r.value("edited").toBool())
        afterEdit(r); // redraws what changed, undo/redo state, panels: like the app's own edits
    if (r.value("select").isArray()) {
        QStringList guids;
        for (const auto& g : r.value("select").toArray())
            guids << g.toString();
        applySelection(guids, QStringLiteral("replace"));
    }
    return r;
}

} // namespace kimbim
