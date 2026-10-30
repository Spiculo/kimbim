// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonObject>
#include <QStringList>

#include <functional>

class QLabel;
class QPushButton;
class QTabWidget;
class QTableWidget;
class QTreeWidget;
class QTreeWidgetItem;

namespace kimbim {

// Reviewing an agent proposal like a merge in an IDE: every element the agent changed, the field-by-field
// before/after of the selected one, and the conflicts (common version / base option / agent option) with a
// choice per conflict. Accept applies it; Reject deletes the agent's option.
class ProposalDialog : public QDialog {
    Q_OBJECT
public:
    using Bridge = std::function<QJsonObject(const char*, const QStringList&)>;

    ProposalDialog(Bridge bridge, const QJsonObject& proposal, QWidget* parent = nullptr);

    QJsonObject resolutions() const { return m_resolutions; }
    QJsonObject preview() const { return m_preview; }
    bool rejected() const { return m_rejected; }
    QTreeWidget* changeTree() const { return m_changes; }
    QTableWidget* conflictTable() const { return m_conflicts; }
    QPushButton* acceptButton() const { return m_accept; }

signals:
    void elementActivated(const QString& guid); // Show in 3D

private:
    void showElement(QTreeWidgetItem* item);
    void refreshConflicts();
    void updateAccept();
    void confirmReject();

    Bridge m_bridge;
    QJsonObject m_proposal;
    QString m_baseRev;
    QString m_option;
    QTabWidget* m_tabs;
    QTreeWidget* m_changes;
    QTableWidget* m_details;
    QLabel* m_detailNote;
    QPushButton* m_show;
    QTableWidget* m_conflicts;
    QLabel* m_conflictStatus;
    QPushButton* m_accept;
    QJsonObject m_resolutions;
    QJsonObject m_preview;
    bool m_refreshing = false;
    bool m_refreshQueued = false;
    bool m_rejected = false;
};

} // namespace kimbim
