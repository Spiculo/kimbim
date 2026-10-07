// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonObject>
#include <QStringList>

#include <functional>

class QComboBox;
class QLabel;
class QPushButton;
class QTableWidget;

namespace kimcad {

// Combine options (Slice 22, M5): choose the option to bring into the current one, see what it
// brings and each conflict (common version, this option, the other option), choose per conflict,
// then Combine. The combined model opens as unsaved work to review in 3D before Save version.
class CombineDialog : public QDialog {
    Q_OBJECT
public:
    using Bridge = std::function<QJsonObject(const char*, const QStringList&)>;
    CombineDialog(Bridge bridge, const QStringList& otherOptions, QWidget* parent = nullptr);

    QString option() const;
    void setOption(const QString& option);
    QJsonObject resolutions() const { return m_resolutions; } // conflict id -> choice
    // Choose for the conflict in `row` (0-based) one of its options ("ours", "theirs", ...).
    bool choose(int row, const QString& choice);
    QJsonObject preview() const { return m_preview; }
    QTableWidget* table() const { return m_table; }
    QPushButton* combineButton() const { return m_combine; }

signals:
    void elementActivated(const QString& guid);

private:
    void refresh();

    Bridge m_bridge;
    QComboBox* m_option;
    QLabel* m_status;
    QTableWidget* m_table;
    QPushButton* m_combine;
    QJsonObject m_resolutions;
    QJsonObject m_preview;
    bool m_refreshing = false;
    bool m_refreshQueued = false; // a choice queued a refresh; a direct refresh() makes it unneeded
};

} // namespace kimcad
