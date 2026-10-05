// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QHash>
#include <QJsonObject>
#include <QStringList>
#include <QWidget>

class QLineEdit;
class QTreeWidget;
class QTreeWidgetItem;

namespace kimcad {

// Spatial tree (project > site > building > storey > elements) with a search filter.
class ModelTreePanel : public QWidget {
    Q_OBJECT
public:
    explicit ModelTreePanel(QWidget* parent = nullptr);

    void setTree(const QJsonObject& root);
    void clear();
    bool selectGuid(const QString& guid); // programmatic: does not emit guidsSelected
    void selectGuids(const QStringList& guids); // programmatic multi-selection, no echo
    QStringList selectedGuids() const;
    void updateNames(const QJsonObject& root); // refresh labels after renames/undo, keeping expansion
    QString currentGuid() const;
    void setFilter(const QString& text);
    QStringList descendantGuids(const QString& guid) const; // the node and everything below it

    int itemCount() const { return m_items.size(); }
    QTreeWidgetItem* itemFor(const QString& guid) const { return m_items.value(guid); }
    QString displayName(const QString& guid) const;
    QTreeWidget* tree() const { return m_tree; }

signals:
    void guidsSelected(const QStringList& guids);
    void isolateRequested(const QStringList& guids);
    void hideRequested(const QStringList& guids);
    void showAllRequested();

private:
    QTreeWidgetItem* addNode(const QJsonObject& node, QTreeWidgetItem* parent);
    bool applyFilter(QTreeWidgetItem* item, const QString& text);
    void showContextMenu(const QPoint& pos);

    QLineEdit* m_search;
    QTreeWidget* m_tree;
    QHash<QString, QTreeWidgetItem*> m_items;
    bool m_programmatic = false;
};

} // namespace kimcad
