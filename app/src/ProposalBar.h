// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonArray>
#include <QStringList>
#include <QWidget>

class QComboBox;
class QLabel;
class QPushButton;

namespace kimbim {

// D102 phase 2: the review bar for ready agent proposals. One compact row with the proposal, its change
// count and Review / Accept / Reject; hidden when there is nothing to review.
class ProposalBar : public QWidget {
    Q_OBJECT
public:
    explicit ProposalBar(QWidget* parent = nullptr);
    void setProposals(const QJsonArray& proposals);
    QString currentTask() const;
    // Owner: "a way to hide this review question." The bar stays hidden while the same proposal waits
    // and comes back by itself when the set changes (a new one arrives, or one is accepted/rejected).
    void hideUntilChanged();
    void showAgain();

signals:
    void reviewRequested(const QString& task);
    void acceptRequested(const QString& task);
    void rejectRequested(const QString& task);
    void proposalsChanged(bool any); // the host bar (a toolbar) shows or hides with it

private:
    QComboBox* m_choice = nullptr;
    QLabel* m_note = nullptr;
    QPushButton* m_review = nullptr;
    QPushButton* m_accept = nullptr;
    QPushButton* m_reject = nullptr;
    QPushButton* m_hide = nullptr;
    QJsonArray m_proposals;
    QStringList m_ids; // the proposals the bar is currently showing, to notice a change
    bool m_dismissed = false;
};

} // namespace kimbim
