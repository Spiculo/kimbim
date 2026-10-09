// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonArray>
#include <QJsonObject>
#include <QStringList>

class QCheckBox;
class QComboBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QPushButton;
class QTableWidget;
class QTableWidgetItem;

namespace kimcad {

// Schedules and quantities (doc 14 §15, D77), after Archicad's Interactive Schedule: a window (not
// modal) with a table of the elements a scheme lists. Clicking rows selects their elements in the
// model; editing a Name, Mark or property cell writes it back as one undo step; "Merge identical
// items" groups rows and sums their quantities. Schemes are project settings (kimcad.schedules).
class SchedulesDialog : public QDialog {
    Q_OBJECT
public:
    explicit SchedulesDialog(QWidget* parent = nullptr);

    void showScheme(const QString& id); // picks the scheme and fills the table
    void refresh();                     // recomputes the current schedule
    // After an edit elsewhere: refresh at once when the last run was quick, else mark the table stale
    // (refreshed when the window is next activated or with Refresh).
    void modelChanged();

    QString currentScheme() const;
    QTableWidget* table() const { return m_table; }
    QComboBox* schemeBox() const { return m_scheme; }
    QCheckBox* mergeBox() const { return m_merge; }
    QStringList guidsOfRow(int row) const;
    int dataRows() const { return m_rows; } // rows above the total row
    double lastSeconds() const { return m_seconds; }

    // A built-in English label (from the Python side) in the UI language; custom labels as typed.
    static QString translatedLabel(const QString& english);
    static QString translatedSchemeName(const QString& english);

signals:
    void selectRequested(const QStringList& guids);
    void edited(const QJsonObject& result); // a bridge edit result, for the window's afterEdit

protected:
    bool event(QEvent* e) override;

private:
    QJsonObject bridge(const char* fn, const QStringList& args = {}) const;
    void reloadSchemes(const QString& select);
    void fill(const QJsonObject& data);
    void onItemChanged(QTableWidgetItem* item);
    void editScheme(bool create);
    void deleteScheme();
    void exportSchedule();

    QComboBox* m_scheme;
    QCheckBox* m_merge;
    QTableWidget* m_table;
    QLabel* m_status;
    QPushButton* m_delete;
    QJsonArray m_schemes;
    QJsonArray m_columns;
    int m_rows = 0;
    double m_seconds = 0.0;
    bool m_filling = false;
    bool m_stale = false;
};

// Editing a schedule scheme: name, IFC classes, fields in order, and which fields identical items share.
class ScheduleSchemeDialog : public QDialog {
    Q_OBJECT
public:
    ScheduleSchemeDialog(const QJsonObject& scheme, QWidget* parent = nullptr);
    QJsonObject scheme() const;

private:
    QJsonObject bridge(const char* fn, const QStringList& args = {}) const;
    void reloadFields();
    void addField();

    QJsonObject m_scheme;
    QLineEdit* m_name;
    QListWidget* m_classes;
    QListWidget* m_available;
    QListWidget* m_fields;
};

} // namespace kimcad
