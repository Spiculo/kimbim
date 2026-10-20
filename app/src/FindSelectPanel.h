// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonObject>
#include <QStringList>
#include <QVector>
#include <QWidget>

class QComboBox;
class QCheckBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QVBoxLayout;

namespace kimbim {

// Find & Select (D78, Archicad's palette): criteria rows (class, kind, type, name, property value,
// layer, level, renovation status, material) joined by AND/OR over a scope (the whole model, the
// active level, the current selection); Select replaces the selection, Add and Remove change it.
// Criteria sets and selection sets are saved by name in the project settings (versioned). The panel
// only edits and asks; the main window runs the query (kimbim.queries) and selects.
class FindSelectPanel : public QWidget {
    Q_OBJECT
public:
    enum class How { Replace, Add, Remove };
    explicit FindSelectPanel(QWidget* parent = nullptr);

    // What the rows offer: {"kinds", "classes", "types", "layers", "levels": [{guid, name}],
    // "materials", "properties", "statuses"} (query_choices).
    void setChoices(const QJsonObject& choices);
    // The saved criteria sets ({name: criteria}) and selection sets ({name: [guids]}).
    void setSaved(const QJsonObject& criteria, const QJsonObject& sets);

    // {"match": "all"|"any", "rows": [{"field", "op", "value"[, "property"]}]}
    QJsonObject criteria() const;
    void setCriteria(const QJsonObject& criteria);
    QString scope() const; // "model", "level" or "selection"
    void setScope(const QString& scope);
    bool includeHidden() const; // D92: find elements on hidden or locked layers too
    int rowCount() const { return int(m_rows.size()); }
    void addRow(const QString& field = QStringLiteral("ifc_class"), const QString& op = QStringLiteral("equals"),
        const QString& value = QString(), const QString& property = QString());
    void clearRows();
    void setResult(const QString& text);
    QString result() const;
    QStringList savedCriteriaNames() const;
    QStringList savedSetNames() const;

    // The buttons, for tests and shortcuts.
    void find(How how);
    void saveCriteria(const QString& name);
    void loadCriteria(const QString& name);
    void saveSet(const QString& name);
    void recallSet(const QString& name, How how);

signals:
    void findRequested(const QJsonObject& query, FindSelectPanel::How how); // criteria + "scope"
    void saveCriteriaRequested(const QString& name, const QJsonObject& criteria);
    void deleteCriteriaRequested(const QString& name);
    void saveSetRequested(const QString& name);
    void recallSetRequested(const QString& name, FindSelectPanel::How how);
    void deleteSetRequested(const QString& name);
    void refreshRequested(); // shown: the choices and saved sets may be stale

protected:
    void showEvent(QShowEvent* event) override;

private:
    struct Row {
        QWidget* widget = nullptr;
        QComboBox* field = nullptr;
        QLineEdit* property = nullptr;
        QComboBox* op = nullptr;
        QComboBox* value = nullptr;
    };
    void fillOps(Row& row, const QString& keep);
    void fillValues(Row& row, const QString& keep);
    void removeRow(QWidget* rowWidget);
    QString selectedSet() const;

    QComboBox* m_match;
    QComboBox* m_scope;
    QCheckBox* m_includeHidden;
    QVBoxLayout* m_rowsLayout;
    QVector<Row> m_rows;
    QComboBox* m_saved;
    QLineEdit* m_setName;
    QListWidget* m_sets;
    QLabel* m_result;
    QJsonObject m_choices, m_savedCriteria;
};

} // namespace kimbim
