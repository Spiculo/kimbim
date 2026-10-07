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

// The model tree (D71: less noise): the spatial structure with single-child Project/Site/Building rows
// merged into one, plain names ("Wall", not IfcWallStandardCase; the IFC class on hover and in the
// search), and each level's elements grouped by category ("Walls (12)"). A search filter on top.
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
    // "Name · IfcClass · Level" for hover hints ("" for unknown elements).
    QString hintFor(const QString& guid) const;
    // Rebuild after elements were added/removed, keeping what the user had expanded.
    void refreshTree(const QJsonObject& root);
    QString displayName(const QString& guid) const;
    QTreeWidget* tree() const { return m_tree; }
    QString ifcTypeOf(const QString& guid) const; // "" if unknown
    static QString plainName(const QString& ifcType);   // "IfcWallStandardCase" -> "Wall" (translated)
    static QString plainPlural(const QString& ifcType); // -> "Walls" (translated)

signals:
    void guidsSelected(const QStringList& guids);
    void isolateRequested(const QStringList& guids);
    void hideRequested(const QStringList& guids);
    void showAllRequested();

private:
    // `merged`: the names of single-child spatial rows above this one, shown as one row with it.
    QTreeWidgetItem* addNode(const QJsonObject& node, QTreeWidgetItem* parent, QStringList merged);
    bool applyFilter(QTreeWidgetItem* item, const QString& text);
    void showContextMenu(const QPoint& pos);

    QLineEdit* m_search;
    QTreeWidget* m_tree;
    QHash<QString, QTreeWidgetItem*> m_items;
    bool m_programmatic = false;
    QStringList m_mergedGuids; // guids of the rows merged into the next one being added
};

} // namespace kimcad
