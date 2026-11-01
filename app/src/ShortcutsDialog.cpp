// SPDX-License-Identifier: GPL-3.0-or-later
#include "ShortcutsDialog.h"

#include <QAction>
#include <QCoreApplication>
#include <QDialogButtonBox>
#include <QHeaderView>
#include <QHBoxLayout>
#include <QKeySequenceEdit>
#include <QLabel>
#include <QLineEdit>
#include <QMenu>
#include <QMenuBar>
#include <QMessageBox>
#include <QPushButton>
#include <QSet>
#include <QSettings>
#include <QTreeWidget>
#include <QVBoxLayout>

#include <algorithm>

namespace kimbim {

namespace {

constexpr const char* CONTEXT = "kimbim::ShortcutsDialog";
constexpr const char* DEFAULTS = "kimbimDefaultShortcuts";

QString cleaned(QString text)
{
    text.remove(QLatin1Char('&'));
    return text.trimmed();
}

QString actionId(QAction* action)
{
    return action ? action->objectName() : QString();
}

void walkMenu(QMenu* menu, const QString& group, QHash<QAction*, QString>* out)
{
    for (QAction* action : menu->actions()) {
        if (action->isSeparator())
            continue;
        if (QMenu* sub = action->menu())
            walkMenu(sub, group, out);
        else
            out->insert(action, group);
    }
}

QStringList groupsInOrder(QWidget* window, QHash<QAction*, QString>* menuGroup)
{
    QStringList order;
    QMenuBar* bar = window->findChild<QMenuBar*>(QStringLiteral("menuBar"));
    if (!bar)
        bar = window->findChild<QMenuBar*>();
    if (!bar)
        return order;
    for (QAction* top : bar->actions()) {
        QMenu* menu = top->menu();
        if (!menu)
            continue;
        const QString group = cleaned(menu->title());
        if (group.isEmpty())
            continue;
        if (!order.contains(group))
            order.append(group);
        walkMenu(menu, group, menuGroup);
    }
    return order;
}

QStringList portable(const QList<QKeySequence>& sequences)
{
    QStringList text;
    for (const QKeySequence& sequence : sequences)
        text.append(sequence.toString(QKeySequence::PortableText));
    return text;
}

QList<QKeySequence> fromPortable(const QStringList& text)
{
    QList<QKeySequence> sequences;
    for (const QString& one : text) {
        const QKeySequence sequence = QKeySequence::fromString(one, QKeySequence::PortableText);
        if (!sequence.isEmpty())
            sequences.append(sequence);
    }
    return sequences;
}

void rememberDefaults(QAction* action)
{
    if (!action->property(DEFAULTS).isValid())
        action->setProperty(DEFAULTS, portable(action->shortcuts()));
}

} // namespace

QList<ShortcutEntry> collectShortcuts(QWidget* window)
{
    QList<ShortcutEntry> entries;
    if (!window)
        return entries;

    QHash<QAction*, QString> menuGroup;
    QStringList order = groupsInOrder(window, &menuGroup);

    // The tools carry their own group: several are in the Model menu as well as the palette, and
    // "W" belongs with the other tools, not with a menu command.
    const QString tools = QCoreApplication::translate(CONTEXT, "Tools");
    const QString other = QCoreApplication::translate(CONTEXT, "Other");
    order.append(tools);
    order.append(other);

    QSet<QString> seen;
    for (QAction* action : window->findChildren<QAction*>()) {
        if (action->isSeparator() || action->shortcuts().isEmpty())
            continue;
        const QString command = cleaned(action->text());
        if (command.isEmpty())
            continue;
        QString group = menuGroup.value(action);
        if (action->objectName().endsWith(QLatin1String("Tool")))
            group = tools;
        if (group.isEmpty())
            group = other;

        QStringList keys;
        for (const QKeySequence& sequence : action->shortcuts())
            keys.append(sequence.toString(QKeySequence::NativeText));
        const QString keyText = keys.join(QStringLiteral(", "));
        const QString identity = group + QChar(0x1f) + command + QChar(0x1f) + keyText;
        if (seen.contains(identity))
            continue;
        seen.insert(identity);
        entries.append({group, command, keyText, action});
    }

    std::stable_sort(entries.begin(), entries.end(), [&order](const ShortcutEntry& a, const ShortcutEntry& b) {
        const int ga = order.indexOf(a.group);
        const int gb = order.indexOf(b.group);
        if (ga != gb)
            return ga < gb;
        return QString::localeAwareCompare(a.command, b.command) < 0;
    });
    return entries;
}

void applyShortcutOverrides(QWidget* window)
{
    if (!window)
        return;
    QSettings settings;
    for (QAction* action : window->findChildren<QAction*>()) {
        rememberDefaults(action);
        const QString id = actionId(action);
        if (id.isEmpty())
            continue;
        const QString saved = settings.value(QStringLiteral("shortcuts/") + id).toString();
        if (saved.isEmpty())
            continue;
        const QKeySequence sequence = QKeySequence::fromString(saved, QKeySequence::PortableText);
        if (!sequence.isEmpty())
            action->setShortcuts({sequence});
    }
}

void setShortcutOverride(QAction* action, const QKeySequence& keys)
{
    if (!action)
        return;
    rememberDefaults(action);
    if (keys.isEmpty()) {
        resetShortcutOverride(action);
        return;
    }
    action->setShortcuts({keys});
    const QString id = actionId(action);
    if (!id.isEmpty())
        QSettings().setValue(QStringLiteral("shortcuts/") + id, keys.toString(QKeySequence::PortableText));
}

void resetShortcutOverride(QAction* action)
{
    if (!action)
        return;
    const QString id = actionId(action);
    if (!id.isEmpty())
        QSettings().remove(QStringLiteral("shortcuts/") + id);
    rememberDefaults(action);
    action->setShortcuts(fromPortable(action->property(DEFAULTS).toStringList()));
}

ShortcutsDialog::ShortcutsDialog(QWidget* parent)
    : QDialog(parent)
{
    setObjectName(QStringLiteral("shortcutsDialog"));
    setWindowTitle(tr("Keyboard shortcuts"));
    resize(720, 580);

    auto* layout = new QVBoxLayout(this);
    m_search = new QLineEdit(this);
    m_search->setObjectName(QStringLiteral("shortcutsSearch"));
    m_search->setClearButtonEnabled(true);
    m_search->setPlaceholderText(tr("Search commands or keys"));
    layout->addWidget(m_search);

    m_table = new QTreeWidget(this);
    m_table->setObjectName(QStringLiteral("shortcutsTable"));
    m_table->setColumnCount(2);
    m_table->setHeaderLabels({tr("Command"), tr("Shortcut")});
    m_table->setRootIsDecorated(true);
    m_table->setAlternatingRowColors(true);
    m_table->setUniformRowHeights(true);
    m_table->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_table->header()->setSectionResizeMode(1, QHeaderView::ResizeToContents);
    layout->addWidget(m_table, 1);

    const QList<ShortcutEntry> entries = collectShortcuts(parent);
    QString currentGroup;
    QTreeWidgetItem* groupItem = nullptr;
    for (const ShortcutEntry& entry : entries) {
        if (!groupItem || entry.group != currentGroup) {
            currentGroup = entry.group;
            groupItem = new QTreeWidgetItem(m_table, {entry.group, QString()});
            QFont font = groupItem->font(0);
            font.setBold(true);
            groupItem->setFont(0, font);
            groupItem->setFirstColumnSpanned(true);
            groupItem->setExpanded(true);
            groupItem->setFlags(groupItem->flags() & ~Qt::ItemIsSelectable);
        }
        auto* item = new QTreeWidgetItem(groupItem, {entry.command, entry.keys});
        item->setData(0, Qt::UserRole, entry.group + QChar(0x1f) + entry.command + QChar(0x1f) + entry.keys);
        if (entry.action)
            item->setData(0, Qt::UserRole + 1, QVariant::fromValue<QObject*>(entry.action));
    }

    auto* buttonsRow = new QHBoxLayout;
    m_change = new QPushButton(tr("Change..."), this);
    m_change->setObjectName(QStringLiteral("shortcutsChange"));
    m_change->setEnabled(false);
    m_reset = new QPushButton(tr("Reset"), this);
    m_reset->setObjectName(QStringLiteral("shortcutsReset"));
    m_reset->setEnabled(false);
    buttonsRow->addWidget(m_change);
    buttonsRow->addWidget(m_reset);
    buttonsRow->addStretch(1);
    layout->addLayout(buttonsRow);

    auto* note = new QLabel(tr("Select a command to change its keys. Changes are saved for your user; "
                               "Reset restores the built-in shortcut."), this);
    note->setWordWrap(true);
    layout->addWidget(note);

    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Close, this);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);

    connect(m_search, &QLineEdit::textChanged, this, &ShortcutsDialog::filter);
    connect(m_table, &QTreeWidget::itemSelectionChanged, this, &ShortcutsDialog::refreshButtons);
    connect(m_table, &QTreeWidget::itemDoubleClicked, this, [this](QTreeWidgetItem*, int) { changeSelected(); });
    connect(m_change, &QPushButton::clicked, this, &ShortcutsDialog::changeSelected);
    connect(m_reset, &QPushButton::clicked, this, &ShortcutsDialog::resetSelected);
    m_search->setFocus();
}

QAction* ShortcutsDialog::selectedAction() const
{
    QTreeWidgetItem* item = m_table->currentItem();
    if (!item || item->childCount() > 0)
        return nullptr;
    return qobject_cast<QAction*>(item->data(0, Qt::UserRole + 1).value<QObject*>());
}

void ShortcutsDialog::refreshButtons()
{
    const QAction* action = selectedAction();
    m_change->setEnabled(action != nullptr);
    m_reset->setEnabled(action != nullptr);
}

void ShortcutsDialog::changeSelected()
{
    QAction* action = selectedAction();
    if (!action)
        return;

    QDialog editor(this);
    editor.setWindowTitle(tr("Shortcut for %1").arg(cleaned(action->text())));
    auto* layout = new QVBoxLayout(&editor);
    auto* edit = new QKeySequenceEdit(&editor);
    edit->setObjectName(QStringLiteral("shortcutEditor"));
    edit->setKeySequence(action->shortcuts().value(0));
    layout->addWidget(edit);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &editor);
    connect(buttons, &QDialogButtonBox::accepted, &editor, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &editor, &QDialog::reject);
    layout->addWidget(buttons);
    if (editor.exec() != QDialog::Accepted)
        return;
    const QKeySequence chosen = edit->keySequence();
    if (chosen.isEmpty())
        return;

    // A sequence that already belongs to another command would be ambiguous. The first match wins
    // for Qt, which is a surprising way to lose a shortcut, so ask for another one instead.
    if (QWidget* window = parentWidget()) {
        for (QAction* other : window->findChildren<QAction*>()) {
            if (other == action || other->shortcuts().isEmpty())
                continue;
            if (other->shortcuts().contains(chosen)) {
                QMessageBox::warning(this, tr("Shortcut already used"),
                    tr("%1 is already assigned to \"%2\".").arg(chosen.toString(QKeySequence::NativeText),
                        cleaned(other->text())));
                return;
            }
        }
    }
    setShortcutOverride(action, chosen);
    if (QTreeWidgetItem* item = m_table->currentItem())
        item->setText(1, chosen.toString(QKeySequence::NativeText));
}

void ShortcutsDialog::resetSelected()
{
    QAction* action = selectedAction();
    if (!action)
        return;
    resetShortcutOverride(action);
    QStringList keys;
    for (const QKeySequence& sequence : action->shortcuts())
        keys.append(sequence.toString(QKeySequence::NativeText));
    if (QTreeWidgetItem* item = m_table->currentItem())
        item->setText(1, keys.join(QStringLiteral(", ")));
}

void ShortcutsDialog::filter(const QString& text)
{
    const QString query = text.trimmed();
    for (int i = 0; i < m_table->topLevelItemCount(); ++i) {
        QTreeWidgetItem* group = m_table->topLevelItem(i);
        int visible = 0;
        for (int j = 0; j < group->childCount(); ++j) {
            QTreeWidgetItem* item = group->child(j);
            const bool match = query.isEmpty()
                || item->text(0).contains(query, Qt::CaseInsensitive)
                || item->text(1).contains(query, Qt::CaseInsensitive)
                || group->text(0).contains(query, Qt::CaseInsensitive);
            item->setHidden(!match);
            if (match)
                ++visible;
        }
        group->setHidden(visible == 0);
    }
}

} // namespace kimbim
