// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QList>
#include <QStringList>
#include <QVector>
#include <QWidget>

class QAction;
class QToolButton;
class QVBoxLayout;

namespace kimcad {

// The tools on the left (D71): collapsible groups (3D, Plane, View, Edit) of buttons for the tool
// actions, with their labels or, compact, icons only. The actions stay the window's (shortcuts, menus).
class ToolPalette : public QWidget {
    Q_OBJECT
public:
    explicit ToolPalette(QWidget* parent = nullptr);
    void addGroup(const QString& id, const QString& title, const QList<QAction*>& actions);
    QStringList groups() const;
    QList<QAction*> actions(const QString& id) const;
    void setCollapsed(const QString& id, bool collapsed);
    bool isCollapsed(const QString& id) const;
    void setCompact(bool iconsOnly);
    bool isCompact() const { return m_compact; }

private:
    struct Group {
        QString id;
        QToolButton* header;
        QWidget* body;
        QList<QAction*> actions;
    };
    QVector<Group> m_groups;
    QList<QToolButton*> m_buttons;
    QVBoxLayout* m_column;
    bool m_compact = false;
};

} // namespace kimcad
