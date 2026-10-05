// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonObject>
#include <QJsonValue>
#include <QWidget>

class QTreeWidget;
class QTreeWidgetItem;

namespace kimcad {

// Properties of the selection (one or many elements, M2): name, property sets and quantities.
// Values shared by all selected elements are shown; differing ones show "(varies)". Editing a
// value applies it to every selected element (bulk edit). IFC names and values are never translated.
class PropertiesPanel : public QWidget {
    Q_OBJECT
public:
    explicit PropertiesPanel(QWidget* parent = nullptr);

    void showMulti(const QJsonObject& merged); // from app_bridge.properties_multi
    void showError(const QString& message);
    void clear();

    QTreeWidget* tree() const { return m_tree; }
    QTreeWidgetItem* itemFor(const QString& pset, const QString& prop) const;
    QTreeWidgetItem* nameItem() const { return m_name; }
    QString variesText() const { return tr("(varies)"); }

signals:
    void propertyEdited(const QString& pset, const QString& prop, const QJsonValue& value);
    void propertyRemoved(const QString& pset, const QString& prop);
    void nameEdited(const QString& name);
    void addPropertyRequested(const QString& pset); // empty pset: add a new property set
    void addPropertySetRequested();

private:
    void onItemChanged(QTreeWidgetItem* item, int column);
    void showContextMenu(const QPoint& pos);

    QTreeWidget* m_tree;
    QTreeWidgetItem* m_name = nullptr;
    bool m_building = false;
};

} // namespace kimcad
