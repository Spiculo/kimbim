// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QByteArray>
#include <QObject>
#include <QPointer>
#include <QStringList>

class QMainWindow;
class QWidget;
namespace ads {
class CDockManager;
class CDockWidget;
class CDockAreaWidget;
}

namespace kimcad {

// The main window's docking (D71, Qt Advanced Docking System): center views as tabs that can be
// dragged out to their own windows and docked back, tabbed panels on the right, tools on the left,
// and the layout saved and restored.
class DockLayout : public QObject {
    Q_OBJECT
public:
    explicit DockLayout(QMainWindow* window);
    ads::CDockManager* manager() const { return m_manager; }

    // Center views (3D, plans, drawings, sheets), keyed ("3d", "plan:<guid>", "<drawing guid>", "sheet:A01").
    ads::CDockWidget* addView(const QString& key, const QString& title, QWidget* widget, bool closable);
    QWidget* view(const QString& key) const;     // nullptr if none
    QString keyOf(const QWidget* widget) const;  // "" if none
    QStringList viewKeys() const;                // in creation order
    void setTitle(const QString& key, const QString& title);
    void removeView(const QString& key);         // deletes the dock and its widget
    void raise(const QString& key);              // makes it current (emits currentChanged)
    QString current() const;                     // key of the current center view

    // Side areas: panels on the right (tabbed), the tool palette on the left.
    ads::CDockWidget* addPanel(const QString& key, const QString& title, QWidget* widget);
    ads::CDockWidget* addLeft(const QString& key, const QString& title, QWidget* widget);
    void raisePanel(const QString& key);         // shows it even when auto-hidden or floating
    bool isPanelShown(const QString& key) const;

    // Layout memory.
    QByteArray saveLayout() const;
    void captureDefault();                       // the layout to fall back to
    bool restoreLayout(const QByteArray& state); // false (and the default applied) if unusable

signals:
    void currentChanged(const QString& key);
    void closeRequested(const QString& key);

private:
    ads::CDockWidget* makeDock(const QString& key, const QString& title, QWidget* widget);
    bool onSomeScreen() const;

    ads::CDockManager* m_manager;
    QPointer<ads::CDockAreaWidget> m_center, m_panels;
    QStringList m_views;
    QString m_current;
    QByteArray m_default;
};

} // namespace kimcad
