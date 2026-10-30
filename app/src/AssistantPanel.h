// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <QWidget>

#include <functional>

class QComboBox;
class QLabel;
class QLineEdit;
class QPushButton;
class QShowEvent;
class QTextBrowser;
class QTimer;
class QToolButton;

namespace kimbim {

// D102 phase 3: the Assistant. A chat with the architect's own model provider, using the same catalogue and
// live session as the CLI; the model's steps appear as they happen, tool calls as compact lines and
// snapshots inline.
class AssistantPanel : public QWidget {
    Q_OBJECT
public:
    explicit AssistantPanel(QWidget* parent = nullptr);
    void setConfigProvider(std::function<QJsonObject()> provider) { m_config = std::move(provider); }
    void clear();
    void send(const QString& text = QString());
    QString sessionId() const { return m_session; }
    void refreshSessions(); // D111: the project's stored sessions in the picker

protected:
    void showEvent(QShowEvent* event) override;

private:
    void append(const QString& html);
    void appendMessage(const QString& who, const QString& text);
    void pollProgress();
    void renderProgress(const QJsonArray& entries);
    void renderCall(const QJsonObject& call);
    void addImage(const QString& path);
    void finish(const QJsonObject& answer, const QString& error);
    QJsonObject conversation() const;
    void newSession();
    void selectSession(int index);
    void resumeSession(const QString& id);
    void renameSession();
    void forkSession();
    void archiveSession();
    void deleteSession();
    void ensureSession(const QString& title);
    QJsonObject call(const char* fn, const QStringList& args = {}, QString* error = nullptr);

    QTextBrowser* m_view = nullptr;
    QComboBox* m_sessions = nullptr;
    QPushButton* m_new = nullptr;
    QToolButton* m_more = nullptr;
    QLineEdit* m_input = nullptr;
    QPushButton* m_send = nullptr;
    QPushButton* m_clear = nullptr;
    QLabel* m_status = nullptr;
    QTimer* m_progress = nullptr;
    QJsonArray m_history;
    QString m_session; // the stored session this conversation is (D111)
    std::function<QJsonObject()> m_config;
    bool m_busy = false;
    int m_images = 0;
    int m_turn = 0;
    int m_seq = 0;
    int m_steps = 0;
};

} // namespace kimbim
