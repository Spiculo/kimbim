// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QHash>
#include <QJsonArray>
#include <QJsonObject>
#include <QString>

#include "Graphics.h"

#include <optional>

class QComboBox;
class QDialogButtonBox;
class QDoubleSpinBox;
class QLineEdit;
class QPushButton;
class QTableWidget;
class QVBoxLayout;

namespace kimcad {

class PenGrid;

// The element kinds' names as the architect reads them ("walls" -> "Walls").
QString kindLabel(const QString& kind);
// A pen set's pens ({"pens": {"1": {...}}}) as line styles.
QHash<int, LineStyle> pensOf(const QJsonObject& penSet);

// The editors of the graphics tables (D73, Graphics menu). Each is built from graphics_tables' reply,
// edits a copy of the tables and reports only what changed (changes()), which MainWindow sends to
// set_graphics; Python validates it again.
class GraphicsDialog : public QDialog {
    Q_OBJECT
public:
    QJsonObject changes() const; // {table: whole table} for each table that differs from the reply's
    bool okEnabled() const;

protected:
    GraphicsDialog(const QJsonObject& reply, QWidget* parent);
    QJsonObject table(const QString& key) const { return m_tables.value(key).toObject(); }
    void setTable(const QString& key, const QJsonObject& t) { m_tables.insert(key, t); }
    // The pens of the current purpose's pen set (what pen buttons show).
    QHash<int, LineStyle> currentPens() const;
    void finishLayout(); // OK / Cancel at the bottom
    void setOkEnabled(bool on);

    QJsonObject m_reply;  // graphics_tables, as given
    QJsonObject m_tables; // the tables being edited
    QVBoxLayout* m_layout;

private:
    QDialogButtonBox* m_buttons = nullptr;
};

// A table of named sets (pen sets, visibility sets, override sets, layer combinations, purposes): the
// set drop-down with New, Copy, Rename and Delete. One set always remains. Renaming or deleting a set
// updates the purposes that use it (`reference`: their field naming it, e.g. "pen_set").
class NamedSetsDialog : public GraphicsDialog {
    Q_OBJECT
public:
    void selectSet(const QString& name);
    QString currentSet() const;
    bool newSet(const QString& name);    // a copy of the first set, renamed
    bool copySetAs(const QString& name); // a copy of the current set
    bool renameSetTo(const QString& name);
    bool deleteCurrentSet();             // false for the last one

protected:
    NamedSetsDialog(const QJsonObject& reply, const QString& key, const QString& reference, QWidget* parent);
    virtual void showSet(const QString& name) = 0; // fill the editor from that set
    QJsonObject currentValue() const;
    void setCurrentValue(const QJsonObject& value);
    void buildPicker(); // the drop-down and buttons; subclasses call it first

    QString m_key, m_reference;

private:
    void refresh(const QString& select);
    bool validName(const QString& name) const;
    QComboBox* m_combo = nullptr;
    QPushButton* m_delete = nullptr;
};

// Graphics > Pen sets: 255 pens per set in a 16 x 16 grid; a pen's colour, weight and name.
class PenSetsDialog : public NamedSetsDialog {
    Q_OBJECT
public:
    PenSetsDialog(const QJsonObject& reply, QWidget* parent);
    void selectPen(int pen);
    void setPenColor(const QColor& color);
    void setPenWeight(double weight);
    void setPenName(const QString& name);

protected:
    void showSet(const QString& name) override;

private:
    QJsonObject pen(int n) const;
    void setPen(int n, const QJsonObject& value);
    PenGrid* m_grid;
    QPushButton* m_color;
    QDoubleSpinBox* m_weight;
    QLineEdit* m_name;
    int m_pen = 1;
    bool m_loading = false;
};

// Graphics > Line types: a name and a dash pattern ("3 1.5": dash, gap... in mm on paper).
class LineTypesDialog : public GraphicsDialog {
    Q_OBJECT
public:
    LineTypesDialog(const QJsonObject& reply, QWidget* parent);
    bool setPattern(const QString& name, const QString& pattern); // false (and OK disabled) if invalid
    bool addLineType(const QString& name, const QString& pattern);
    bool deleteLineType(const QString& name);

private:
    static std::optional<QJsonArray> parse(const QString& pattern);
    void fill();
    void validate();
    QTableWidget* m_list;
    QHash<QString, QString> m_bad; // name -> the invalid text typed
    bool m_loading = false;
};

// Graphics > Element styles: per element kind, the cut and projection pens and line types and the cut
// fill pen.
class ElementStylesDialog : public GraphicsDialog {
    Q_OBJECT
public:
    ElementStylesDialog(const QJsonObject& reply, QWidget* parent);
    void setCutPen(const QString& kind, int pen);
    void setProjectionPen(const QString& kind, int pen);
    void setFillPen(const QString& kind, int pen);
    void setCutLine(const QString& kind, const QString& line);
    void setProjectionLine(const QString& kind, const QString& line);

private:
    void set(const QString& kind, const QString& part, const QString& field, const QJsonValue& value);
    void fill();
    QTableWidget* m_list;
    QStringList m_kinds;
};

} // namespace kimcad
