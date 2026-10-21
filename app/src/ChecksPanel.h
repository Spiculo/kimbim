// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonObject>
#include <QList>
#include <QStringList>
#include <QWidget>

class QCheckBox;
class QComboBox;
class QDoubleSpinBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QTreeWidget;
class QTreeWidgetItem;

namespace kimbim {

// Checks (D81, doc 14 §19): pick the checks (schema validation, IDS, clash detection, model checks),
// run them, and see the issues by check, then by group (a rule, an IDS specification, a clash set, a
// model check): severity, message, elements. Clicking an issue selects and shows its elements; a
// group, all of its elements. The IDS files and clash sets are project settings. The panel only
// shows and asks; the main window runs the checks (kimbim.checks) on a worker thread.
class ChecksPanel : public QWidget {
    Q_OBJECT
public:
    explicit ChecksPanel(QWidget* parent = nullptr);

    // "schema", "ids", "clash", "model": the ticked checks, in that order.
    QStringList checkedChecks() const;
    void setChecked(const QString& check, bool on);
    QJsonObject options() const; // {"express_rules": bool}
    void run();                  // the Run button

    // The project's IDS files (names) and clash sets ({name: set}).
    void setIdsFiles(const QStringList& names);
    QStringList idsFiles() const;
    void setClashSets(const QJsonObject& sets);
    QStringList clashSetNames() const;
    // What a clash set side can be: IFC classes, saved criteria sets (D78), selection sets.
    void setChoices(const QStringList& classes, const QStringList& criteria, const QStringList& sets);

    // Results: one run_check result per check (or {"ok": false, "check", "error"}).
    void clearResults();
    void addResult(const QJsonObject& result);
    int issueCount() const; // issue rows shown
    QStringList issueGuids(int n) const;
    QString issueText(int n) const;
    bool activateIssue(int n); // as a click on the n-th issue row (in display order)
    QTreeWidget* results() const { return m_results; }
    void setSummary(const QString& text);
    QString summary() const;

signals:
    void runRequested(const QStringList& checks, const QJsonObject& options);
    void addIdsRequested();
    void linkIdsRequested(); // D92: link an IDS file from a folder instead of embedding it
    void removeIdsRequested(const QString& name);
    void exportReportRequested();
    void saveClashSetRequested(const QString& name, const QJsonObject& set, const QString& replaces);
    void deleteClashSetRequested(const QString& name);
    void issueActivated(const QStringList& guids);
    void refreshRequested(); // shown: the IDS files, clash sets and choices may be stale

protected:
    void showEvent(QShowEvent* event) override;

private:
    void editClashSet(const QString& name);
    QList<QTreeWidgetItem*> issueItems() const;

    QCheckBox* m_schema;
    QCheckBox* m_rules;
    QCheckBox* m_ids;
    QCheckBox* m_clash;
    QCheckBox* m_model;
    QListWidget* m_idsList;
    QListWidget* m_clashList;
    QTreeWidget* m_results;
    QLabel* m_summary;
    QJsonObject m_clashSets;
    QStringList m_classes, m_criteria, m_sets;
};

// A clash set: a name, set A and set B (IFC classes, a criteria set or a selection set), hard
// clashes with a tolerance or clearance with a distance.
class ClashSetDialog : public QDialog {
    Q_OBJECT
public:
    ClashSetDialog(const QStringList& classes, const QStringList& criteria, const QStringList& sets, QWidget* parent = nullptr);
    void setSet(const QString& name, const QJsonObject& set);
    QString name() const;
    QJsonObject set() const; // {"a", "b"?, "mode", "tolerance"|"clearance"} (metres)
    // A side from its text: "Criteria: x", "Selection set: x", or IFC classes separated by commas.
    static QJsonObject parseSide(const QString& text);
    static QString sideText(const QJsonObject& side);

private:
    QLineEdit* m_name;
    QComboBox* m_a;
    QComboBox* m_b;
    QComboBox* m_mode;
    QDoubleSpinBox* m_distance;
};

} // namespace kimbim
