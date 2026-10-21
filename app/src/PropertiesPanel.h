// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonObject>
#include <QList>
#include <QJsonValue>
#include <QWidget>

class QAction;
class QComboBox;
class QTreeWidget;
class QTreeWidgetItem;

namespace kimbim {

// D74: the renovation statuses in the order shown ("existing", "demolish", "new") and their names.
QStringList renovationKeys();
QString renovationLabel(const QString& key);

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
    QComboBox* statusCombo() const { return m_status; } // D74: none when nothing selected has a status
    QComboBox* materialCombo() const { return m_material; } // D96: none when the selection takes no material
    QString variesText() const { return tr("(varies)"); }
    QString fromTypeText() const { return tr("Inherited from the element's type"); }
    // The context-menu actions for an item (parented to `parent`, or to the panel).
    QList<QAction*> actionsFor(QTreeWidgetItem* item, QObject* parent = nullptr);

signals:
    void propertyEdited(const QString& pset, const QString& prop, const QJsonValue& value);
    void propertyRemoved(const QString& pset, const QString& prop);
    void nameEdited(const QString& name);
    void statusEdited(const QString& status); // D74: "existing", "demolish" or "new"
    void materialEdited(const QString& kind, const QString& name); // D96: "material" or "composite"
    void addPropertyRequested(const QString& pset); // empty pset: add a new property set
    void addPropertySetRequested();
    void typeEditRequested(const QString& pset, const QString& prop);   // change the value on the type (D50)
    void resetToTypeRequested(const QString& pset, const QString& prop); // drop the element's override

private:
    void onItemChanged(QTreeWidgetItem* item, int column);
    void showContextMenu(const QPoint& pos);

    QTreeWidget* m_tree;
    QTreeWidgetItem* m_name = nullptr;
    QComboBox* m_status = nullptr;
    QComboBox* m_material = nullptr;
    bool m_building = false;
};

} // namespace kimbim
