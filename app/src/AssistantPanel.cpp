// SPDX-License-Identifier: GPL-3.0-or-later
#include "AssistantPanel.h"

#include "PythonEngine.h"

#include <QHBoxLayout>
#include <QImage>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QTextBrowser>
#include <QTextCursor>
#include <QTextDocument>
#include <QThread>
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

void AssistantPanel::clear()
{
    if (m_busy)
        return;
    m_history = QJsonArray();
    m_view->clear();
    append(QStringLiteral("<p style='color:#777'>%1</p>")
               .arg(escaped(tr("Conversation cleared."))));
}

void AssistantPanel::send(const QString& text)
{
    const QString prompt = (text.isEmpty() ? m_input->text() : text).trimmed();
    if (prompt.isEmpty() || m_busy)
        return;
    m_input->clear();
    appendMessage(tr("You"), prompt);
    m_history.append(QJsonObject{{QStringLiteral("role"), QStringLiteral("user")},
                                 {QStringLiteral("content"), prompt}});
    m_busy = true;
    m_send->setEnabled(false);
    m_status->setText(tr("Thinking..."));
    const QJsonObject config = m_config ? m_config() : QJsonObject();
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

void AssistantPanel::finish(const QJsonObject& answer, const QString& error)
{
    m_busy = false;
    m_send->setEnabled(true);
    m_status->clear();
    if (!error.isEmpty()) {
        appendMessage(tr("Assistant"), tr("Could not ask the model: %1").arg(error));
        return;
    }
    if (!answer.value(QStringLiteral("ok")).toBool()) {
        const QJsonObject problem = answer.value(QStringLiteral("error")).toObject();
        const QString text = problem.value(QStringLiteral("message")).toString();
        const QString hint = problem.value(QStringLiteral("hint")).toString();
        appendMessage(tr("Assistant"), hint.isEmpty() ? text : text + QStringLiteral("\n") + hint);
        m_history.removeLast(); // the question did not reach the model: let the user ask again
        return;
    }
    const QJsonObject result = answer.value(QStringLiteral("result")).toObject();
    for (const QJsonValue& value : result.value(QStringLiteral("tool_calls")).toArray()) {
        const QJsonObject call = value.toObject();
        append(QStringLiteral("<p style='color:#666;margin-left:12px'>• %1</p>")
                   .arg(escaped(call.value(QStringLiteral("summary")).toString())));
        const QString shot = call.value(QStringLiteral("snapshot")).toString();
        if (!shot.isEmpty()) {
            const QUrl uri(QStringLiteral("kimbim-snapshot://%1").arg(++m_images));
            const QImage image(shot);
            if (!image.isNull()) {
                m_view->document()->addResource(QTextDocument::ImageResource, uri, image);
                append(QStringLiteral("<p><img src='%1' width='520'></p>").arg(uri.toString()));
            }
        }
    }
    const QString text = result.value(QStringLiteral("text")).toString();
    if (!text.isEmpty()) {
        appendMessage(tr("Assistant"), text);
        m_history.append(QJsonObject{{QStringLiteral("role"), QStringLiteral("assistant")},
                                     {QStringLiteral("content"), text}});
    }
}

} // namespace kimbim
