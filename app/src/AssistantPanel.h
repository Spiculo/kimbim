// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <QWidget>

#include <functional>

class QLabel;
class QLineEdit;
class QPushButton;
class QTextBrowser;

namespace kimbim {

// D102 phase 3: the Assistant. A chat with the architect's own model provider, using the same catalogue and
// live session as the CLI; tool calls appear as compact lines, snapshots inline.
class AssistantPanel : public QWidget {
    Q_OBJECT
public:
    explicit AssistantPanel(QWidget* parent = nullptr);
    void setConfigProvider(std::function<QJsonObject()> provider) { m_config = std::move(provider); }
    void clear();
    void send(const QString& text = QString());

private:
    void append(const QString& html);
    void appendMessage(const QString& who, const QString& text);
    void finish(const QJsonObject& answer, const QString& error);
    QJsonObject conversation() const;

    QTextBrowser* m_view = nullptr;
    QLineEdit* m_input = nullptr;
    QPushButton* m_send = nullptr;
    QPushButton* m_clear = nullptr;
    QLabel* m_status = nullptr;
    QJsonArray m_history;
    std::function<QJsonObject()> m_config;
    bool m_busy = false;
    int m_images = 0;
};

} // namespace kimbim
