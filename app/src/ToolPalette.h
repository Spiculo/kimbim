// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QList>
#include <QStringList>
#include <QVector>
#include <QWidget>

class QAction;
class QActionGroup;
class QGridLayout;
class QMenu;
class QScrollArea;
class QToolButton;
class QVBoxLayout;

namespace kimcad {

// The tools on the left (D71, D90: Archicad's Toolbox): collapsible groups (3D, Plane, View, Edit) of
// buttons in a grid whose column count follows the panel's width. Related tools can share one
// **flyout** button (press and hold, or click its corner triangle, for the others); the button shows
// the last one used. Three looks from the context menu: icons only, icons and labels (default), a
// one-column list. The actions stay the window's (shortcuts, menus); a group lists all of its
// actions, flyout members included, in the order they were given.
class ToolPalette : public QWidget {
    Q_OBJECT
public:
    enum class Mode { Icons, IconsAndLabels, List };

    explicit ToolPalette(QWidget* parent = nullptr);
    void addGroup(const QString& id, const QString& title, const QList<QAction*>& actions);
    // Folds `members` (actions of group `id`) into one flyout button where the first of them is.
    void addFlyout(const QString& id, const QList<QAction*>& members);
    QStringList groups() const;
    QList<QAction*> actions(const QString& id) const;
    QList<QToolButton*> buttons(const QString& id) const; // one per tool or flyout, in order
    QToolButton* buttonFor(const QAction* action) const;  // the button that shows it (its flyout's)
    void setCollapsed(const QString& id, bool collapsed);
    bool isCollapsed(const QString& id) const;
    void setMode(Mode mode);
    Mode mode() const { return m_mode; }
    void setCompact(bool iconsOnly) { setMode(iconsOnly ? Mode::Icons : Mode::IconsAndLabels); }
    bool isCompact() const { return m_mode == Mode::Icons; }
    int columns() const { return m_columns; }
    QMenu* contextMenu() const { return m_menu; } // the looks; the window adds its own entries

    static QString modeKey(Mode mode);               // "icons", "labels", "list"
    static Mode modeFromKey(const QString& key);     // anything else: icons and labels

signals:
    void modeChanged(kimcad::ToolPalette::Mode mode);

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;
    void contextMenuEvent(QContextMenuEvent* event) override;

private:
    struct Group {
        QString id;
        QToolButton* header = nullptr;
        QWidget* body = nullptr;
        QGridLayout* grid = nullptr;
        QList<QAction*> actions;
        QList<QList<QAction*>> items; // a tool, or a flyout's members
        QList<QToolButton*> buttons;
    };
    Group* group(const QString& id);
    const Group* group(const QString& id) const;
    void rebuild(Group& g);
    void relayout(bool force = false);
    void styleButton(QToolButton* b) const;
    void styleHeader(QToolButton* h) const;

    QVector<Group> m_groups;
    QVBoxLayout* m_column;
    QScrollArea* m_scroll;
    QMenu* m_menu;
    QActionGroup* m_looks;
    Mode m_mode = Mode::IconsAndLabels;
    int m_columns = 0;
};

} // namespace kimcad
