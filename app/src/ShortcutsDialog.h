// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QKeySequence>
#include <QList>
#include <QString>

class QAction;
class QLineEdit;
class QPushButton;
class QTreeWidget;

namespace kimbim {

// One row of the keyboard reference: where the command lives, what it does and its keys.
struct ShortcutEntry {
    QString group;
    QString command;
    QString keys;
    QAction* action = nullptr;
};

// Every visible command of `window` that has a shortcut, grouped by menu (tool actions under
// "Tools"). The app is shortcut-heavy and many commands are only reachable by key, so this is the
// one place a person can discover them.
QList<ShortcutEntry> collectShortcuts(QWidget* window);

// Apply saved rebindings (QSettings "shortcuts/<objectName>") and remember the built-in sequences
// as the reset target. Call once after the menus and tools exist.
void applyShortcutOverrides(QWidget* window);

// Rebind one command and persist it; an empty sequence restores the built-in one.
void setShortcutOverride(QAction* action, const QKeySequence& keys);
void resetShortcutOverride(QAction* action);

class ShortcutsDialog : public QDialog {
    Q_OBJECT
public:
    explicit ShortcutsDialog(QWidget* parent = nullptr);

    QLineEdit* search() const { return m_search; }
    QTreeWidget* table() const { return m_table; }

private:
    void filter(const QString& text);
    void refreshButtons();
    void changeSelected();
    void resetSelected();
    QAction* selectedAction() const;

    QLineEdit* m_search = nullptr;
    QTreeWidget* m_table = nullptr;
    QPushButton* m_change = nullptr;
    QPushButton* m_reset = nullptr;
};

} // namespace kimbim
