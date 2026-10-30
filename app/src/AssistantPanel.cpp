// SPDX-License-Identifier: GPL-3.0-or-later
#include "AssistantPanel.h"

#include "PythonEngine.h"

#include <QComboBox>
#include <QHBoxLayout>
#include <QImage>
#include <QInputDialog>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QMenu>
#include <QMessageBox>
#include <QPushButton>
#include <QShowEvent>
#include <QSignalBlocker>
#include <QTextBrowser>
#include <QTextCursor>
#include <QTextDocument>
#include <QThread>
#include <QTimer>
#include <QToolButton>
#include <QUrl>
#include <QVBoxLayout>

namespace kimbim {

namespace {
QString escaped(const QString& text)
{
    return text.toHtmlEscaped().replace(QLatin1Char('\n'), QStringLiteral("<br>"));
}
} // namespace

AssistantPanel::AssistantPanel(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("assistantPanel"));
    setMinimumSize(0, 0);
    setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Expanding);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(4, 4, 4, 4);
    // D111: a stored session is a conversation the architect can come back to, not panel memory.
    auto* sessions = new QHBoxLayout;
    m_sessions = new QComboBox(this);
    m_sessions->setObjectName(QStringLiteral("assistantSessions"));
    m_sessions->setSizeAdjustPolicy(QComboBox::AdjustToMinimumContentsLengthWithIcon);
    m_sessions->setMinimumContentsLength(12);
    m_new = new QPushButton(tr("New"), this);
    m_new->setObjectName(QStringLiteral("assistantNewSession"));
    m_more = new QToolButton(this);
    m_more->setObjectName(QStringLiteral("assistantSessionMenu"));
    m_more->setText(QStringLiteral("…"));
    m_more->setPopupMode(QToolButton::InstantPopup);
    auto* menu = new QMenu(m_more);
    menu->addAction(tr("Rename…"), this, &AssistantPanel::renameSession);
    menu->addAction(tr("Fork"), this, &AssistantPanel::forkSession);
    menu->addAction(tr("Archive"), this, &AssistantPanel::archiveSession);
    menu->addSeparator();
    menu->addAction(tr("Delete…"), this, &AssistantPanel::deleteSession);
    m_more->setMenu(menu);
    sessions->addWidget(m_sessions, 1);
    sessions->addWidget(m_new);
    sessions->addWidget(m_more);
    layout->addLayout(sessions);
    m_view = new QTextBrowser(this);
    m_view->setObjectName(QStringLiteral("assistantTranscript"));
    m_view->setOpenExternalLinks(true);
    m_view->setMinimumSize(0, 0);
    m_view->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Expanding);
    layout->addWidget(m_view, 1);
    auto* row = new QHBoxLayout;
    m_input = new QLineEdit(this);
    m_input->setObjectName(QStringLiteral("assistantInput"));
    m_input->setPlaceholderText(tr("Ask the assistant to read or change the model..."));
    m_send = new QPushButton(tr("Send"), this);
    m_send->setObjectName(QStringLiteral("assistantSend"));
    m_clear = new QPushButton(tr("Clear"), this);
    m_clear->setObjectName(QStringLiteral("assistantClear"));
    row->addWidget(m_input, 1);
    row->addWidget(m_send);
    row->addWidget(m_clear);
    layout->addLayout(row);
    m_status = new QLabel(this);
    m_status->setObjectName(QStringLiteral("assistantStatus"));
    layout->addWidget(m_status);
    connect(m_send, &QPushButton::clicked, this, [this] { send(); });
    connect(m_input, &QLineEdit::returnPressed, this, [this] { send(); });
    connect(m_clear, &QPushButton::clicked, this, &AssistantPanel::clear);
    connect(m_new, &QPushButton::clicked, this, &AssistantPanel::newSession);
    connect(m_sessions, &QComboBox::activated, this, &AssistantPanel::selectSession);
    m_progress = new QTimer(this);
    m_progress->setInterval(150);
    connect(m_progress, &QTimer::timeout, this, &AssistantPanel::pollProgress);
    append(QStringLiteral("<p style='color:#777'>%1</p>")
               .arg(escaped(tr("Changes go in a task the architect reviews. Set the provider and API key in "
                               "Preferences › Assistant."))));
}

void AssistantPanel::append(const QString& html)
{
    QTextCursor cursor(m_view->document());
    cursor.movePosition(QTextCursor::End);
    cursor.insertHtml(html);
    m_view->setTextCursor(cursor);
    m_view->ensureCursorVisible();
}

void AssistantPanel::appendMessage(const QString& who, const QString& text)
{
    const QString colour = who == QLatin1String("you") ? QStringLiteral("#1f4e79") : QStringLiteral("#333333");
    append(QStringLiteral("<p><b style='color:%1'>%2</b><br>%3</p>").arg(colour, escaped(who), escaped(text)));
}

QJsonObject AssistantPanel::conversation() const
{
    return {{QStringLiteral("messages"), m_history}};
}

QJsonObject AssistantPanel::call(const char* fn, const QStringList& args, QString* error)
{
    QString problem;
    const QJsonObject answer = PythonEngine::instance().callJson(fn, args, &problem).object();
    if (error)
        *error = problem;
    return answer;
}

void AssistantPanel::showEvent(QShowEvent* event)
{
    QWidget::showEvent(event);
    refreshSessions();
}

void AssistantPanel::refreshSessions()
{
    if (m_busy)
        return;
    const QJsonObject answer = call("agent_sessions", {QString(), QStringLiteral("true")});
    if (!answer.value(QStringLiteral("ok")).toBool())
        return;
    const QJsonArray list = answer.value(QStringLiteral("result")).toObject()
                                .value(QStringLiteral("sessions")).toArray();
    const QString keep = m_session;
    const QSignalBlocker blocker(m_sessions);
    m_sessions->clear();
    int chosen = -1;
    for (const QJsonValue& value : list) {
        const QJsonObject entry = value.toObject();
        const QString id = entry.value(QStringLiteral("id")).toString();
        QString title = entry.value(QStringLiteral("title")).toString();
        if (title.isEmpty())
            title = tr("Untitled session");
        const QString status = entry.value(QStringLiteral("status")).toString();
        if (status == QLatin1String("archived"))
            title += QStringLiteral(" (%1)").arg(tr("archived"));
        else if (status == QLatin1String("ready"))
            title += QStringLiteral(" (%1)").arg(tr("review"));
        m_sessions->addItem(title, id);
        if (id == keep)
            chosen = m_sessions->count() - 1;
        else if (chosen < 0 && keep.isEmpty() && status != QLatin1String("archived"))
            chosen = m_sessions->count() - 1; // the newest session, after a restart
    }
    if (!keep.isEmpty() && chosen < 0)
        m_session.clear(); // the selected session was deleted: the next question starts a new one
    if (chosen >= 0)
        m_sessions->setCurrentIndex(chosen);
    if (keep.isEmpty() && chosen >= 0) {
        const QString id = m_sessions->itemData(chosen).toString();
        if (!id.isEmpty())
            resumeSession(id);
    }
}

void AssistantPanel::ensureSession(const QString& title)
{
    if (!m_session.isEmpty())
        return;
    const QJsonObject config = m_config ? m_config() : QJsonObject();
    QString problem;
    const QJsonObject answer = call("agent_session_new",
                                    {QString(), title.left(80),
                                     config.value(QStringLiteral("provider")).toString(),
                                     config.value(QStringLiteral("model")).toString()}, &problem);
    if (!answer.value(QStringLiteral("ok")).toBool()) {
        const QJsonObject error = answer.value(QStringLiteral("error")).toObject();
        m_status->setText(problem.isEmpty() ? error.value(QStringLiteral("message")).toString() : problem);
        return;
    }
    m_session = answer.value(QStringLiteral("result")).toObject().value(QStringLiteral("id")).toString();
    refreshSessions();
}

void AssistantPanel::newSession()
{
    if (m_busy)
        return;
    m_session.clear();
    m_history = QJsonArray();
    m_view->clear();
    append(QStringLiteral("<p style='color:#777'>%1</p>")
               .arg(escaped(tr("New conversation. Clear starts another one; the old one stays in the list."))));
    ensureSession(tr("New session"));
    refreshSessions();
}

void AssistantPanel::selectSession(int index)
{
    if (index < 0 || m_busy)
        return;
    const QString id = m_sessions->itemData(index).toString();
    if (id.isEmpty() || id == m_session)
        return;
    resumeSession(id);
}

void AssistantPanel::resumeSession(const QString& id)
{
    QString problem;
    const QJsonObject answer = call("agent_session_load", {id}, &problem);
    if (!answer.value(QStringLiteral("ok")).toBool()) {
        const QJsonObject error = answer.value(QStringLiteral("error")).toObject();
        m_status->setText(problem.isEmpty() ? error.value(QStringLiteral("message")).toString() : problem);
        return;
    }
    const QJsonObject result = answer.value(QStringLiteral("result")).toObject();
    m_session = result.value(QStringLiteral("session")).toObject().value(QStringLiteral("id")).toString();
    m_history = result.value(QStringLiteral("messages")).toArray();
    m_view->clear();
    const QJsonArray transcript = result.value(QStringLiteral("transcript")).toArray();
    for (const QJsonValue& value : transcript) {
        const QJsonObject entry = value.toObject();
        const QString role = entry.value(QStringLiteral("role")).toString();
        if (role == QLatin1String("user")) {
            appendMessage(tr("You"), entry.value(QStringLiteral("text")).toString());
        } else if (role == QLatin1String("assistant")) {
            appendMessage(tr("Assistant"), entry.value(QStringLiteral("text")).toString());
        } else if (role == QLatin1String("tool")) {
            renderCall(entry);
        } else if (role == QLatin1String("status")) {
            const QString text = entry.value(QStringLiteral("text")).toString().trimmed();
            if (!text.isEmpty())
                append(QStringLiteral("<p style='color:#777;font-style:italic'>%1</p>").arg(escaped(text)));
        }
    }
    if (transcript.isEmpty())
        append(QStringLiteral("<p style='color:#777'>%1</p>")
                   .arg(escaped(tr("Continue this conversation."))));
    m_status->clear();
}

void AssistantPanel::renameSession()
{
    if (m_busy || m_session.isEmpty())
        return;
    bool ok = false;
    const QString current = m_sessions->currentText();
    const QString title = QInputDialog::getText(this, tr("Rename session"), tr("Title:"), QLineEdit::Normal,
                                                current, &ok);
    if (!ok || title.trimmed().isEmpty())
        return;
    call("agent_session_rename", {m_session, title.trimmed()});
    refreshSessions();
}

void AssistantPanel::forkSession()
{
    if (m_busy || m_session.isEmpty())
        return;
    QString problem;
    const QJsonObject answer = call("agent_session_fork", {m_session, QString()}, &problem);
    if (!answer.value(QStringLiteral("ok")).toBool())
        return;
    const QString id = answer.value(QStringLiteral("result")).toObject().value(QStringLiteral("id")).toString();
    if (!id.isEmpty()) {
        m_session = id;
        refreshSessions();
        resumeSession(id);
    }
}

void AssistantPanel::archiveSession()
{
    if (m_busy || m_session.isEmpty())
        return;
    const QString id = m_session;
    call("agent_session_archive", {id});
    if (m_session == id)
        newSession();
    else
        refreshSessions();
}

void AssistantPanel::deleteSession()
{
    if (m_busy || m_session.isEmpty())
        return;
    const QString id = m_session;
    if (QMessageBox::question(this, tr("Delete session"),
                              tr("Delete this conversation and its worktree? Its design option is kept."))
        != QMessageBox::Yes)
        return;
    QString problem;
    QJsonObject answer = call("agent_session_delete", {id, QStringLiteral("false"), QStringLiteral("false")},
                              &problem);
    if (!answer.value(QStringLiteral("ok")).toBool()
        && answer.value(QStringLiteral("error")).toObject().value(QStringLiteral("code")).toString()
               == QLatin1String("session_review")) {
        if (QMessageBox::warning(this, tr("Proposal waiting"),
                                 tr("This session's proposal is waiting for review. Delete it anyway?"),
                                 QMessageBox::Yes | QMessageBox::No)
            != QMessageBox::Yes)
            return;
        answer = call("agent_session_delete", {id, QStringLiteral("true"), QStringLiteral("false")}, &problem);
    }
    if (!answer.value(QStringLiteral("ok")).toBool()) {
        const QJsonObject error = answer.value(QStringLiteral("error")).toObject();
        m_status->setText(problem.isEmpty() ? error.value(QStringLiteral("message")).toString() : problem);
        return;
    }
    m_session.clear();
    newSession();
}

void AssistantPanel::clear()
{
    if (m_busy)
        return;
    newSession();
}

void AssistantPanel::send(const QString& text)
{
    const QString prompt = (text.isEmpty() ? m_input->text() : text).trimmed();
    if (prompt.isEmpty() || m_busy)
        return;
    ensureSession(prompt);
    if (m_session.isEmpty())
        return;
    m_input->clear();
    appendMessage(tr("You"), prompt);
    m_history.append(QJsonObject{{QStringLiteral("role"), QStringLiteral("user")},
                                 {QStringLiteral("content"), prompt}});
    m_busy = true;
    m_send->setEnabled(false);
    m_status->setText(tr("Thinking..."));
    m_steps = 0;
    m_seq = 0;
    m_turn = PythonEngine::instance().callJson("assistant_begin", {}).object()
                 .value(QStringLiteral("result")).toObject().value(QStringLiteral("turn")).toInt();
    m_progress->start();
    QJsonObject config = m_config ? m_config() : QJsonObject();
    config.insert(QStringLiteral("session"), m_session);
    const QString messages = QString::fromUtf8(QJsonDocument(m_history).toJson(QJsonDocument::Compact));
    const QString settings = QString::fromUtf8(QJsonDocument(config).toJson(QJsonDocument::Compact));
    QThread* thread = QThread::create([this, messages, settings] {
        QString error;
        const QJsonObject answer = PythonEngine::instance().callJson("assistant_chat", {messages, settings}, &error)
                                       .object();
        QMetaObject::invokeMethod(this, [this, answer, error] { finish(answer, error); }, Qt::QueuedConnection);
    });
    connect(thread, &QThread::finished, thread, &QThread::deleteLater);
    thread->start();
}

void AssistantPanel::pollProgress()
{
    if (!m_busy)
        return;
    const QJsonObject result = PythonEngine::instance()
                                   .callJson("assistant_progress", {QString::number(m_turn), QString::number(m_seq)})
                                   .object().value(QStringLiteral("result")).toObject();
    if (m_turn != 0 && result.value(QStringLiteral("turn")).toInt() != m_turn)
        return;
    renderProgress(result.value(QStringLiteral("entries")).toArray());
    if (m_steps > 0)
        m_status->setText(tr("Working... %1 step(s)").arg(m_steps));
}

void AssistantPanel::renderProgress(const QJsonArray& entries)
{
    for (const QJsonValue& value : entries) {
        const QJsonObject entry = value.toObject();
        m_seq = qMax(m_seq, entry.value(QStringLiteral("seq")).toInt());
        const QString kind = entry.value(QStringLiteral("kind")).toString();
        if (kind == QLatin1String("tool")) {
            renderCall(entry);
            ++m_steps;
        } else if (kind == QLatin1String("message")) {
            const QString text = entry.value(QStringLiteral("text")).toString().trimmed();
            if (!text.isEmpty())
                appendMessage(tr("Assistant"), text);
        } else if (kind == QLatin1String("status")) {
            const QString text = entry.value(QStringLiteral("text")).toString().trimmed();
            if (!text.isEmpty())
                append(QStringLiteral("<p style='color:#777;font-style:italic'>%1</p>").arg(escaped(text)));
        }
    }
}

void AssistantPanel::renderCall(const QJsonObject& call)
{
    const QString colour = call.value(QStringLiteral("ok")).toBool(true) ? QStringLiteral("#666666")
                                                                        : QStringLiteral("#a33333");
    append(QStringLiteral("<p style='color:%1;margin-left:12px'>• %2</p>")
               .arg(colour, escaped(call.value(QStringLiteral("summary")).toString())));
    const QString shot = call.value(QStringLiteral("snapshot")).toString();
    if (!shot.isEmpty())
        addImage(shot);
}

void AssistantPanel::addImage(const QString& path)
{
    const QImage image(path);
    if (image.isNull())
        return;
    const QUrl uri(QStringLiteral("kimbim-snapshot://%1").arg(++m_images));
    m_view->document()->addResource(QTextDocument::ImageResource, uri, image);
    append(QStringLiteral("<p><img src='%1' width='520'></p>").arg(uri.toString()));
}

void AssistantPanel::finish(const QJsonObject& answer, const QString& error)
{
    m_progress->stop();
    pollProgress(); // the last calls may have arrived with the answer
    m_busy = false;
    m_send->setEnabled(true);
    m_status->clear();
    if (!error.isEmpty()) {
        appendMessage(tr("Assistant"), tr("Could not ask the model: %1").arg(error));
        if (m_steps == 0)
            m_history.removeLast(); // the question did not reach the model: let the user ask again
        return;
    }
    if (!answer.value(QStringLiteral("ok")).toBool()) {
        const QJsonObject problem = answer.value(QStringLiteral("error")).toObject();
        const QString text = problem.value(QStringLiteral("message")).toString();
        const QString hint = problem.value(QStringLiteral("hint")).toString();
        const QString shown = hint.isEmpty() ? text : text + QStringLiteral("\n") + hint;
        appendMessage(tr("Assistant"), shown);
        if (m_steps == 0) {
            m_history.removeLast(); // the question did not reach the model: let the user ask again
        } else { // it ran tools before failing: keep the turn in the conversation
            m_history.append(QJsonObject{{QStringLiteral("role"), QStringLiteral("assistant")},
                                         {QStringLiteral("content"), shown}});
        }
        return;
    }
    const QJsonObject result = answer.value(QStringLiteral("result")).toObject();
    if (m_steps == 0) { // a provider reported no progress: show its calls now, as before
        for (const QJsonValue& value : result.value(QStringLiteral("tool_calls")).toArray()) {
            renderCall(value.toObject());
            ++m_steps;
        }
    }
    const QString text = result.value(QStringLiteral("text")).toString();
    if (!text.isEmpty()) {
        appendMessage(tr("Assistant"), text);
        m_history.append(QJsonObject{{QStringLiteral("role"), QStringLiteral("assistant")},
                                     {QStringLiteral("content"), text}});
    } else if (m_steps > 0) {
        m_history.append(QJsonObject{{QStringLiteral("role"), QStringLiteral("assistant")},
                                     {QStringLiteral("content"), tr("Done.")}});
    }
    refreshSessions();
}

} // namespace kimbim
