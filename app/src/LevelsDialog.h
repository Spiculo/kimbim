// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonArray>
#include <QJsonObject>
#include <QString>
#include <QVector>

class QTableWidget;
class QPushButton;

namespace kimcad {

// The levels table's data (D79, Archicad's Story Settings), without widgets: edits made in the
// dialog, sent to the engine as one change (app_bridge.edit_storeys, one undo step). Rows are kept
// lowest first; elevations in metres.
class LevelsTable {
public:
    struct Row {
        QString guid; // "" for a level inserted in the dialog
        QString name;
        double elevation = 0;
        bool show = true;
        int elements = 0;
        int key = 0; // the row's own id inside the dialog
    };
    struct Deleted {
        QString guid, elements, moveTo; // elements: "delete" or "move" (to moveTo); "" when empty
    };

    // From app_bridge.levels_table's "levels".
    explicit LevelsTable(const QJsonArray& levels = {});
    const QVector<Row>& rows() const { return m_rows; }
    int count() const { return int(m_rows.size()); }
    // Height to the next level up; nullopt-like -1 for the top level.
    double heightToNext(int i) const;

    void setName(int i, const QString& name);
    void setShown(int i, bool show);
    // Archicad: a new elevation moves that level only; a new height to the next level moves every
    // level above it by the difference. Returns the row's new index (rows stay sorted).
    int setElevation(int i, double metres);
    void setHeightToNext(int i, double metres);
    // Insert a level above / below row i: the new level's height is row i's height to the next
    // (or 3 m at the top), and the levels above make room (Archicad). Returns the new row's index.
    int insertAbove(int i, const QString& name);
    int insertBelow(int i, const QString& name);
    // elements: "delete" (with the level, Archicad) or "move" (to moveTo, a level that stays).
    bool remove(int i, const QString& elements = QString(), const QString& moveTo = QString());
    // The closest level that stays (below first) for row i's elements; "" when there is none.
    QString neighbourFor(int i) const;

    bool modified() const;
    QJsonObject changes() const; // app_bridge.edit_storeys' argument

private:
    void sort();
    int m_nextKey = 0;
    QVector<Row> m_rows, m_original;
    QVector<Deleted> m_deleted;
};

// Model > Levels... (and the level drop-down's menu): the table, edited in place.
class LevelsDialog : public QDialog {
    Q_OBJECT
public:
    // Lengths are shown in the project's unit: `factor` units per metre (1000 for mm), `decimals`.
    LevelsDialog(const QJsonArray& levels, const QString& unit, double factor, int decimals, QWidget* parent = nullptr);
    LevelsTable& table() { return m_table; }
    QTableWidget* grid() const { return m_grid; }
    int currentRow() const;         // the selected level's index in table() (lowest is 0), -1 if none
    void selectRow(int tableIndex); // select a level by its index in table()
    void insertAbove();
    void insertBelow();
    // Delete the selected level; with elements on it, asks whether to delete them too or move them
    // (quiet: `quietChoice` "delete"/"move"/"" answers instead, for tests).
    void deleteSelected(const QString& quietChoice = QStringLiteral("ask"));

private:
    void fill();
    void edited(int row, int column);
    QString lengthText(double metres) const;
    bool parseLength(const QString& text, double* metres) const;

    LevelsTable m_table;
    QTableWidget* m_grid;
    QPushButton* m_delete;
    QString m_unit;
    double m_factor;
    int m_decimals;
    bool m_filling = false;
};

} // namespace kimcad
