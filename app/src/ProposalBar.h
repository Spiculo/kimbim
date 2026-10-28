// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonArray>
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

signals:
    void reviewRequested(const QString& task);
    void acceptRequested(const QString& task);
    void rejectRequested(const QString& task);

private:
    QComboBox* m_choice = nullptr;
    QLabel* m_note = nullptr;
    QPushButton* m_review = nullptr;
    QPushButton* m_accept = nullptr;
    QPushButton* m_reject = nullptr;
    QJsonArray m_proposals;
};

} // namespace kimbim
