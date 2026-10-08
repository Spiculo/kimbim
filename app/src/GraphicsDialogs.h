// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QHash>
#include <QJsonArray>
#include <QJsonObject>
#include <QString>

#include "Graphics.h"

#include <optional>

class QCheckBox;
class QComboBox;
class QListWidget;
class QSpinBox;
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

// One rule (D73): a condition (element kind, IFC class, a property, layer, material) and an effect
// (pens, line type, fill, 3D surface and transparency, or hide). Empty fields are left out.
class RuleEditor : public QWidget {
    Q_OBJECT
public:
    RuleEditor(const QStringList& kinds, const QStringList& lineTypes, QWidget* parent = nullptr);
    void setRule(const QJsonObject& rule);
    QJsonObject rule() const;
    void setHideOnly(bool on); // visibility sets: every matching rule hides, so no effect fields

signals:
    void changed();

private:
    QLineEdit *m_name, *m_class, *m_property, *m_value, *m_layer, *m_material, *m_surface;
    QComboBox *m_kind, *m_op, *m_line;
    QSpinBox *m_pen, *m_cutPen, *m_projectionPen, *m_fill;
    QDoubleSpinBox* m_transparency;
    QCheckBox *m_hide, *m_enabled;
    QWidget* m_effects;
    bool m_hideOnly = false;
    bool m_loading = false;
};

// A named set of rules (visibility sets, override sets): the rule list (ticked = enabled) and the
// rule editor.
class RulesDialog : public NamedSetsDialog {
    Q_OBJECT
public:
    void addRule(const QJsonObject& rule);
    bool deleteRule(int i);
    bool moveRule(int from, int to);
    bool setRuleEnabled(int i, bool enabled);

protected:
    RulesDialog(const QJsonObject& reply, const QString& key, const QString& reference, bool hideOnly, QWidget* parent);
    void buildRules(); // the list, its buttons and the editor
    void showSet(const QString& name) override;
    QJsonArray rules() const { return currentValue().value("rules").toArray(); }
    void setRules(const QJsonArray& rules);

private:
    void showRule(int i);
    QListWidget* m_rules = nullptr;
    RuleEditor* m_editor = nullptr;
    bool m_hideOnly;
    bool m_loading = false;
};

// Graphics > Visibility sets: the element kinds hidden, and hide rules (e.g. LoadBearing = false).
class VisibilitySetsDialog : public RulesDialog {
    Q_OBJECT
public:
    VisibilitySetsDialog(const QJsonObject& reply, QWidget* parent);
    void setKindHidden(const QString& kind, bool hidden);

protected:
    void showSet(const QString& name) override;

private:
    QListWidget* m_kinds = nullptr;
    bool m_loading = false;
};

// Graphics > Overrides: ordered rules; the first that matches an element wins.
class OverridesDialog : public RulesDialog {
    Q_OBJECT
public:
    OverridesDialog(const QJsonObject& reply, QWidget* parent);
};

// Graphics > Layer combinations: which layers are shown and locked, by name.
class LayerCombinationsDialog : public NamedSetsDialog {
    Q_OBJECT
public:
    LayerCombinationsDialog(const QJsonObject& reply, const QStringList& layers, const QStringList& hidden,
        const QStringList& locked, QWidget* parent);
    void setShown(const QString& layer, bool shown);
    void setLocked(const QString& layer, bool locked);
    void takeCurrent(); // the layers as they are now (the ones given)

protected:
    void showSet(const QString& name) override;

private:
    void setIn(const QString& list, const QString& layer, bool in);
    QStringList m_layers, m_hiddenNow, m_lockedNow;
    QTableWidget* m_states = nullptr;
    bool m_loading = false;
};

// Graphics > Purposes: each purpose's pen set, visibility set, override set and layer combination.
class PurposesDialog : public NamedSetsDialog {
    Q_OBJECT
public:
    PurposesDialog(const QJsonObject& reply, QWidget* parent);
    // An empty layers name means none (the purpose leaves the layers as they are).
    void setPieces(const QString& penSet, const QString& visibility, const QString& overrides, const QString& layers);

protected:
    void showSet(const QString& name) override;

private:
    QComboBox *m_penSet = nullptr, *m_visibility = nullptr, *m_overrides = nullptr, *m_layers = nullptr;
    bool m_loading = false;
};

} // namespace kimcad
