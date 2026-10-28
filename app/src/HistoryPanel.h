// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <QWidget>

class QLabel;
class QListWidget;
class QPushButton;
class QTreeWidget;

namespace kimbim {

// Versions of the current design option (newest first) and the result of a Compare: elements
// added / modified / removed. The viewport colours them; clicking one selects it.
class HistoryPanel : public QWidget {
    Q_OBJECT
public:
    explicit HistoryPanel(QWidget* parent = nullptr);

    void setVersions(const QJsonArray& versions); // app_bridge.history()["versions"]
    void setChanges(const QJsonObject& compare);  // app_bridge.compare(); empty clears
    int changeCount() const { return m_changeCount; }
    QListWidget* versions() const { return m_versions; }

    static QColor addedColor() { return QColor(60, 175, 90); }
    static QColor modifiedColor() { return QColor(235, 150, 40); }

signals:
    void compareRequested(const QString& revA, const QString& revB); // revB "WORKING" = the open model
    void endCompareRequested();
    void elementActivated(const QString& guid);
    void beforeAfterRequested(const QString& guid); // the selected change, between the compared versions
    void versionChecksRequested(const QString& rev); // M6: the checks recorded with the selected version

private:
    void updateButtons();

    QListWidget* m_versions;
    QTreeWidget* m_changes;
    QPushButton* m_compareCurrent;
    QPushButton* m_compareTwo;
    QPushButton* m_end;
    QPushButton* m_beforeAfter;
    QPushButton* m_versionChecks;
    QLabel* m_legend;
    int m_changeCount = 0;
};

} // namespace kimbim
