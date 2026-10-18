// SPDX-License-Identifier: GPL-3.0-or-later
// Checks (D81): schema validation, IDS, clash detection and model checks. MainWindow members kept in
// their own file; the checks themselves run in Python (kimcad.checks), on a worker thread.
#include "MainWindow.h"

#include "ChecksPanel.h"
#include "DockLayout.h"
#include "ModelTreePanel.h"
#include "PythonEngine.h"
#include "StatusStrip.h"
#include "Viewport.h"

#include <QAction>
#include <QApplication>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFileDialog>
#include <QFileInfo>
#include <QJsonDocument>
#include <QMenu>
#include <QPointer>
#include <QProgressDialog>

#include <DockManager.h>
#include <DockWidget.h>

#include <limits>

namespace kimcad {

namespace {

QString compact(const QJsonObject& o)
{
    return QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Compact));
}

QStringList strings(const QJsonValue& v)
{
    QStringList out;
    for (const auto& x : v.toArray())
        out << x.toString();
    return out;
}

QString checkTitle(const QString& check)
{
    if (check == QLatin1String("schema"))
        return MainWindow::tr("Schema validation");
    if (check == QLatin1String("ids"))
        return MainWindow::tr("IDS");
    if (check == QLatin1String("clash"))
        return MainWindow::tr("Clash detection");
    return MainWindow::tr("Model checks");
}

} // namespace

ChecksPanel* MainWindow::checksPanel()
{
    if (m_checks) {
        m_dock->raisePanel(QStringLiteral("checks"));
        return m_checks;
    }
    m_checks = new ChecksPanel(this);
    m_dock->addPanel(QStringLiteral("checks"), tr("Checks"), m_checks); // View > Panels: Check model... (D90)
    connect(m_checks, &ChecksPanel::refreshRequested, this, &MainWindow::refreshChecks);
    connect(m_checks, &ChecksPanel::runRequested, this,
        [this](const QStringList& checks, const QJsonObject& options) { runChecks(checks, options); });
    connect(m_checks, &ChecksPanel::issueActivated, this, &MainWindow::showIssue);
    connect(m_checks, &ChecksPanel::addIdsRequested, this, [this] {
        if (m_quiet)
            return;
        const QStringList paths = QFileDialog::getOpenFileNames(this, tr("Add IDS files"), QString(),
            tr("Information Delivery Specification (*.ids *.xml)"));
        for (const QString& p : paths)
            addIdsFile(p);
    });
    connect(m_checks, &ChecksPanel::removeIdsRequested, this, &MainWindow::removeIdsFile);
    connect(m_checks, &ChecksPanel::exportReportRequested, this, [this] {
        if (m_quiet)
            return;
        const QString path = QFileDialog::getSaveFileName(this, tr("IDS report"), QStringLiteral("ids-report.html"),
            tr("HTML report (*.html);;JSON report (*.json)"));
        if (!path.isEmpty())
            exportIdsReport(path);
    });
    connect(m_checks, &ChecksPanel::saveClashSetRequested, this, &MainWindow::saveClashSet);
    connect(m_checks, &ChecksPanel::deleteClashSetRequested, this, &MainWindow::deleteClashSet);
    refreshChecks();
    m_dock->raisePanel(QStringLiteral("checks"));
    return m_checks;
}

void MainWindow::refreshChecks()
{
    if (!m_checks)
        return;
    m_checks->setIdsFiles(m_settings.value("ids_files").toObject().keys());
    m_checks->setClashSets(m_settings.value("clash_sets").toObject());
    const QJsonObject choices = bridge("query_choices");
    m_checks->setChoices(strings(choices.value("classes")), m_settings.value("selection_criteria").toObject().keys(),
        m_settings.value("selection_sets").toObject().keys());
}

bool MainWindow::runChecks(const QStringList& checks, const QJsonObject& options)
{
    ChecksPanel* panel = checksPanel();
    if (!PythonEngine::instance().isRunning() || m_loading) {
        panel->setSummary(tr("Open a model first"));
        return false;
    }
    // One worker thread per check, behind a window-modal progress dialog: the window keeps painting,
    // nothing edits the model meanwhile, and Cancel stops the running check (kimcad.checks).
    m_recoveryTimer.stop();
    panel->clearResults();
    QProgressDialog progress(tr("Checking..."), tr("Cancel"), 0, int(checks.size()), this);
    progress.setWindowTitle(tr("Checks"));
    progress.setWindowModality(Qt::WindowModal);
    progress.setMinimumDuration(m_quiet ? std::numeric_limits<int>::max() : 0);
    bool cancelled = false;
    connect(&progress, &QProgressDialog::canceled, this, [&cancelled] {
        cancelled = true;
        PythonEngine::instance().callJson("cancel_checks", {});
    });
    QApplication::setOverrideCursor(Qt::BusyCursor);
    QElapsedTimer clock;
    clock.start();
    int issues = 0, errors = 0, ran = 0;
    const QString opts = compact(options);
    for (int i = 0; i < checks.size() && !cancelled; ++i) {
        progress.setLabelText(tr("Checking: %1 (%2 of %3)...").arg(checkTitle(checks[i])).arg(i + 1).arg(checks.size()));
        progress.setValue(i);
        QJsonObject r;
        QString error;
        const QByteArray check = checks[i].toUtf8();
        QThread* worker = QThread::create([&r, &error, check, opts] {
            r = PythonEngine::instance().callJson("run_check", {QString::fromUtf8(check), opts}, &error).object();
        });
        QEventLoop loop;
        connect(worker, &QThread::finished, &loop, &QEventLoop::quit);
        worker->start();
        // Shown at once (window-modal) unless quiet: then no user input reaches the window either.
        loop.exec(m_quiet ? QEventLoop::ExcludeUserInputEvents : QEventLoop::AllEvents);
        worker->wait();
        delete worker;
        if (r.isEmpty())
            r = QJsonObject{{"ok", false}, {"error", error.isEmpty() ? tr("no answer") : error}};
        r.insert("check", checks[i]);
        if (!r.contains("title"))
            r.insert("title", checkTitle(checks[i]));
        panel->addResult(r);
        if (r.value("ok").toBool()) {
            ++ran;
            issues += r.value("total").toInt();
            errors += r.value("counts").toObject().value("error").toInt();
            m_timings[QStringLiteral("check_") + checks[i]] += r.value("seconds").toDouble() * 1000.0;
        }
    }
    progress.setValue(int(checks.size()));
    QApplication::restoreOverrideCursor();
    restartRecoveryTimer();
    const double seconds = clock.elapsed() / 1000.0;
    QString summary = cancelled ? tr("Stopped after %1 s").arg(seconds, 0, 'f', 1)
                                : tr("%n issue(s)", nullptr, issues) + QStringLiteral(" · ")
            + tr("%n error(s)", nullptr, errors) + QStringLiteral(" · ") + tr("%1 s").arg(seconds, 0, 'f', 1);
    panel->setSummary(summary);
    m_status->showMessage(tr("Checks: %1").arg(summary));
    return !cancelled && ran == checks.size();
}

void MainWindow::showIssue(const QStringList& guids)
{
    // What can be selected is (hidden or locked elements are not); the view shows them all.
    applySelection(guids, QStringLiteral("replace"));
    if (!guids.isEmpty())
        m_viewport->fitTo(guids);
}

bool MainWindow::addIdsFile(const QString& path)
{
    const QJsonObject r = bridge("read_ids_file", {path});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not add the IDS file: %1").arg(r.value("error").toString()));
        if (m_checks)
            m_checks->setSummary(r.value("error").toString());
        return false;
    }
    QJsonObject table = m_settings.value("ids_files").toObject();
    table.insert(r.value("name").toString(), r.value("xml").toString());
    const bool ok = setProjectSettings({{"ids_files", table}});
    if (ok)
        m_status->showMessage(tr("IDS file %1 added to the project (%n specification(s))", nullptr,
            r.value("specifications").toInt()).arg(r.value("name").toString()));
    refreshChecks();
    return ok;
}

bool MainWindow::removeIdsFile(const QString& name)
{
    QJsonObject table = m_settings.value("ids_files").toObject();
    if (!table.contains(name))
        return false;
    table.remove(name);
    const bool ok = setProjectSettings({{"ids_files", table}});
    refreshChecks();
    return ok;
}

bool MainWindow::exportIdsReport(const QString& path)
{
    const QJsonObject r = bridge("export_ids_report", {path});
    const QString message = r.value("ok").toBool() ? tr("IDS report saved: %1").arg(QFileInfo(path).fileName())
                                                   : tr("Could not save the IDS report: %1").arg(r.value("error").toString());
    m_status->showMessage(message);
    if (m_checks)
        m_checks->setSummary(message);
    return r.value("ok").toBool();
}

bool MainWindow::saveClashSet(const QString& name, const QJsonObject& set, const QString& replaces)
{
    QJsonObject table = m_settings.value("clash_sets").toObject();
    if (!replaces.isEmpty() && replaces != name)
        table.remove(replaces);
    table.insert(name, set);
    const bool ok = setProjectSettings({{"clash_sets", table}});
    if (ok)
        m_status->showMessage(tr("Clash set %1 saved in the project").arg(name));
    refreshChecks();
    return ok;
}

bool MainWindow::deleteClashSet(const QString& name)
{
    QJsonObject table = m_settings.value("clash_sets").toObject();
    if (!table.contains(name))
        return false;
    table.remove(name);
    const bool ok = setProjectSettings({{"clash_sets", table}});
    refreshChecks();
    return ok;
}

} // namespace kimcad
