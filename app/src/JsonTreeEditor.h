// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonObject>
#include <QList>
#include <QPair>
#include <QWidget>

class QPushButton;
class QTreeWidget;
class QTreeWidgetItem;

namespace kimbim {

// The Object Editor's Parts tab (D101, doc 16 §6): a library object's parts, components and plan symbol
// as a tree of their JSON. Columns Key, Value, Error. A leaf's value is edited as text: what reads as a
// number, true/false, null, a list or an object is that, anything else is text (a formula). A list of
// numbers or texts is one leaf (`[0, 0.1]`). A part in a `parts` list is named by its id, as the check's
// field paths name it (`parts.leg.cone.h`); other list items by their index (`symbol[0]`).
class JsonTreeEditor : public QWidget {
    Q_OBJECT
public:
    explicit JsonTreeEditor(QWidget* parent = nullptr);

    // `parts` (a list), `components` (an object) and `symbol` (a list, or absent). A root it doesn't give
    // shows empty and comes back from roots() only once something is added to it.
    void setRoots(const QJsonObject& roots);
    QJsonObject roots() const;
    // Marks the nodes of these field paths: the message in the Error column and as the tooltip, the row
    // red. A path with no node of its own marks its nearest node. Clears the marks of the last call.
    void markErrors(const QList<QPair<QString, QString>>& pathMessages);
    QString pathOf(QTreeWidgetItem* item) const;

    void addPart(const QString& shape); // object_part_template's shape, into the selected node's parts list
    void addComponent(const QString& name);
    void addField(const QString& key, const QString& value); // on the selected object node
    // Appends an item to the selected list node, or to the list of the selected item: a parameter on a
    // `params` list (`what` unused), a plan symbol item of kind `what` (object_symbol_template) on the
    // `symbol` list, else `what` read as JSON. False when nothing was added (no list, an unknown kind, text
    // that is not JSON).
    bool addItem(const QString& what);

signals:
    void changed();

private:
    QTreeWidgetItem* addNode(QTreeWidgetItem* parent, const QString& key, const QJsonValue& v, int at = -1);
    QJsonValue valueOf(QTreeWidgetItem* item) const;
    void relabel(QTreeWidgetItem* list) const; // the item labels of a list: [i], or a part's id
    QTreeWidgetItem* partsListOf(QTreeWidgetItem* item) const;
    void move(int by);
    void updateButtons();

    QTreeWidget* m_tree;
    QPushButton* m_addPart;
    QPushButton* m_addField;
    QPushButton* m_addItem;
    QPushButton* m_remove;
    QPushButton* m_up;
    QPushButton* m_down;
};

} // namespace kimbim
