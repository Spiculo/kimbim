// SPDX-License-Identifier: GPL-3.0-or-later
#include "ModelTreePanel.h"

#include "Icons.h"

#include <QHeaderView>
#include <QJsonArray>
#include <QLineEdit>
#include <QMenu>
#include <QTreeWidget>
#include <QTreeWidgetItemIterator>
#include <QJsonArray>
#include <QMap>
#include <QVBoxLayout>

namespace kimcad {

namespace {
constexpr int GuidRole = Qt::UserRole;
constexpr int TypeRole = Qt::UserRole + 1;  // the IFC class (searchable, in the hint)
constexpr int GroupRole = Qt::UserRole + 2; // "storey guid|category" on category rows

QString stripped(const QString& ifcType)
{
    QString t = ifcType;
    if (t.startsWith(QLatin1String("Ifc")))
        t = t.mid(3);
    for (const char* suffix : {"StandardCase", "ElementedCase"})
        if (t.endsWith(QLatin1String(suffix)))
            t.chop(int(qstrlen(suffix)));
    return t;
}

bool isSpatial(const QString& t)
{
    return t == QLatin1String("IfcProject") || t == QLatin1String("IfcSite") || t == QLatin1String("IfcBuilding");
}
} // namespace

QString ModelTreePanel::plainName(const QString& ifcType)
{
    const QString s = stripped(ifcType);
    if (s == QLatin1String("Wall")) return tr("Wall");
    if (s == QLatin1String("Door")) return tr("Door");
    if (s == QLatin1String("Window")) return tr("Window");
    if (s == QLatin1String("Slab")) return tr("Slab");
    if (s == QLatin1String("Column")) return tr("Column");
    if (s == QLatin1String("Beam")) return tr("Beam");
    if (s == QLatin1String("Stair")) return tr("Stair");
    if (s == QLatin1String("Roof")) return tr("Roof");
    if (s == QLatin1String("Space")) return tr("Room");
    if (s == QLatin1String("Annotation")) return tr("Annotation");
    if (s == QLatin1String("Grid")) return tr("Grid");
    if (s == QLatin1String("BuildingStorey")) return tr("Level");
    if (s == QLatin1String("Building")) return tr("Building");
    if (s == QLatin1String("Site")) return tr("Site");
    if (s == QLatin1String("Project")) return tr("Project");
    if (s == QLatin1String("FurnishingElement")) return tr("Furniture");
    if (s == QLatin1String("BuildingElementProxy")) return tr("Other");
    return s;
}

QString ModelTreePanel::plainPlural(const QString& ifcType)
{
    const QString s = stripped(ifcType);
    if (s == QLatin1String("Wall")) return tr("Walls");
    if (s == QLatin1String("Door")) return tr("Doors");
    if (s == QLatin1String("Window")) return tr("Windows");
    if (s == QLatin1String("Slab")) return tr("Slabs");
    if (s == QLatin1String("Column")) return tr("Columns");
    if (s == QLatin1String("Beam")) return tr("Beams");
    if (s == QLatin1String("Stair")) return tr("Stairs");
    if (s == QLatin1String("Roof")) return tr("Roofs");
    if (s == QLatin1String("Space")) return tr("Rooms");
    if (s == QLatin1String("Annotation")) return tr("Annotations");
    if (s == QLatin1String("Grid")) return tr("Grids");
    if (s == QLatin1String("FurnishingElement")) return tr("Furniture");
    if (s == QLatin1String("BuildingElementProxy")) return tr("Other");
    return s + QLatin1Char('s');
}

ModelTreePanel::ModelTreePanel(QWidget* parent)
    : QWidget(parent)
    , m_search(new QLineEdit(this))
    , m_tree(new QTreeWidget(this))
{
    m_search->setPlaceholderText(tr("Search name, type or GlobalId"));
    m_search->setClearButtonEnabled(true);
    m_tree->setColumnCount(1); // the IFC class shows on hover (D71: less noise)
    m_tree->setHeaderHidden(true);
    m_tree->setIndentation(12); // deep spatial trees must leave room for names
    m_tree->setTextElideMode(Qt::ElideMiddle);
    m_tree->setContextMenuPolicy(Qt::CustomContextMenu);
    m_tree->setUniformRowHeights(true);
    m_tree->setSelectionMode(QAbstractItemView::ExtendedSelection); // Ctrl/Shift like the viewport

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addWidget(m_search);
    layout->addWidget(m_tree);

    connect(m_search, &QLineEdit::textChanged, this, &ModelTreePanel::setFilter);
    connect(m_tree, &QTreeWidget::itemSelectionChanged, this, [this] {
        if (!m_programmatic)
            emit guidsSelected(selectedGuids());
    });
    connect(m_tree, &QTreeWidget::customContextMenuRequested, this, &ModelTreePanel::showContextMenu);
}

void ModelTreePanel::clear()
{
    m_tree->clear();
    m_items.clear();
    m_mergedGuids.clear();
}

void ModelTreePanel::setTree(const QJsonObject& root)
{
    clear();
    if (root.contains("guid"))
        addNode(root, nullptr, {})->setExpanded(true);
    // expand down to the levels so elements are one click away
    for (QTreeWidgetItem* item : std::as_const(m_items))
        if (isSpatial(item->data(0, TypeRole).toString()))
            item->setExpanded(true);
}

QTreeWidgetItem* ModelTreePanel::addNode(const QJsonObject& node, QTreeWidgetItem* parent, QStringList merged)
{
    const QString type = node.value("type").toString();
    const QString name = node.value("name").toString();
    const QString guid = node.value("guid").toString();
    const QJsonArray children = node.value("children").toArray();
    const QString shown = name.isEmpty() ? plainName(type) : name;
    if (isSpatial(type) && children.size() == 1 && isSpatial(children[0].toObject().value("type").toString())) {
        m_mergedGuids << guid; // Project › Site › Building: one row
        return addNode(children[0].toObject(), parent, merged << shown);
    }
    auto* item = parent ? new QTreeWidgetItem(parent) : new QTreeWidgetItem(m_tree);
    item->setText(0, shown);
    item->setIcon(0, iconFor(type));
    item->setData(0, GuidRole, guid);
    item->setData(0, TypeRole, type);
    item->setToolTip(0, (merged << shown).join(QStringLiteral(" › ")) + QLatin1Char('\n') + type + QLatin1Char('\n') + guid);
    m_items.insert(guid, item);
    for (const QString& g : std::as_const(m_mergedGuids))
        m_items.insert(g, item);
    m_mergedGuids.clear();
    if (type == QLatin1String("IfcBuildingStorey")) {
        // A level's elements grouped by category ("Walls (12)"), the categories by name.
        QMap<QString, QJsonArray> byCategory;
        QHash<QString, QString> typeOfCategory;
        for (const auto& c : children) {
            const QString t = c.toObject().value("type").toString();
            byCategory[plainPlural(t)].append(c);
            typeOfCategory.insert(plainPlural(t), t);
        }
        for (auto it = byCategory.constBegin(); it != byCategory.constEnd(); ++it) {
            auto* group = new QTreeWidgetItem(item);
            group->setText(0, QStringLiteral("%1 (%2)").arg(it.key()).arg(it.value().size()));
            group->setIcon(0, iconFor(typeOfCategory.value(it.key())));
            group->setData(0, GroupRole, guid + QLatin1Char('|') + it.key());
            for (const auto& c : it.value())
                addNode(c.toObject(), group, {});
        }
        return item;
    }
    for (const auto& c : children)
        addNode(c.toObject(), item, {});
    return item;
}

QString ModelTreePanel::ifcTypeOf(const QString& guid) const
{
    const QTreeWidgetItem* item = m_items.value(guid);
    return item ? item->data(0, TypeRole).toString() : QString();
}

QString ModelTreePanel::displayName(const QString& guid) const
{
    QTreeWidgetItem* item = m_items.value(guid);
    return item ? item->text(0) : QString();
}

bool ModelTreePanel::selectGuid(const QString& guid)
{
    QTreeWidgetItem* item = m_items.value(guid);
    if (!item)
        return false;
    m_programmatic = true;
    m_tree->setCurrentItem(item);
    m_tree->scrollToItem(item);
    m_programmatic = false;
    return true;
}

void ModelTreePanel::refreshTree(const QJsonObject& root)
{
    // Expanded rows by guid, and category rows by "level|category".
    auto rowKey = [](const QTreeWidgetItem* item) {
        const QString group = item->data(0, GroupRole).toString();
        return group.isEmpty() ? item->data(0, GuidRole).toString() : group;
    };
    QSet<QString> expanded;
    for (QTreeWidgetItemIterator it(m_tree); *it; ++it)
        if ((*it)->isExpanded())
            expanded.insert(rowKey(*it));
    const QString filter = m_search->text();
    setTree(root);
    for (QTreeWidgetItemIterator it(m_tree); *it; ++it)
        if (expanded.contains(rowKey(*it)))
            (*it)->setExpanded(true);
    if (!filter.isEmpty()) { // re-apply the user's filter to the new items
        m_search->clear();
        m_search->setText(filter);
    }
}

void ModelTreePanel::selectGuids(const QStringList& guids)
{
    m_programmatic = true;
    m_tree->clearSelection();
    QTreeWidgetItem* first = nullptr;
    for (const QString& g : guids) {
        if (QTreeWidgetItem* item = m_items.value(g)) {
            item->setSelected(true);
            if (!first)
                first = item;
        }
    }
    if (first) {
        m_tree->setCurrentItem(first, 0, QItemSelectionModel::NoUpdate);
        m_tree->scrollToItem(first);
    }
    m_programmatic = false;
}

void ModelTreePanel::updateNames(const QJsonObject& node)
{
    if (QTreeWidgetItem* item = m_items.value(node.value("guid").toString())) {
        const QString name = node.value("name").toString();
        item->setText(0, name.isEmpty() ? plainName(node.value("type").toString()) : name);
    }
    for (const auto& child : node.value("children").toArray())
        updateNames(child.toObject());
}

QString ModelTreePanel::hintFor(const QString& guid) const
{
    const QTreeWidgetItem* item = m_items.value(guid);
    if (!item)
        return {};
    QString level;
    for (const QTreeWidgetItem* p = item->parent(); p; p = p->parent())
        if (p->data(0, TypeRole).toString() == QLatin1String("IfcBuildingStorey")) {
            level = p->text(0);
            break;
        }
    QStringList parts{item->text(0), item->data(0, TypeRole).toString()};
    if (!level.isEmpty())
        parts << level;
    return parts.join(QStringLiteral(" · "));
}

QStringList ModelTreePanel::selectedGuids() const
{
    QStringList out;
    for (QTreeWidgetItem* item : m_tree->selectedItems())
        if (const QString g = item->data(0, GuidRole).toString(); !g.isEmpty()) // not category rows
            out << g;
    return out;
}

QString ModelTreePanel::currentGuid() const
{
    QTreeWidgetItem* item = m_tree->currentItem();
    return item ? item->data(0, GuidRole).toString() : QString();
}

QStringList ModelTreePanel::descendantGuids(const QString& guid) const
{
    QStringList out;
    QTreeWidgetItem* start = m_items.value(guid);
    if (!start)
        return out;
    QList<QTreeWidgetItem*> stack{start};
    while (!stack.isEmpty()) {
        QTreeWidgetItem* item = stack.takeLast();
        if (const QString g = item->data(0, GuidRole).toString(); !g.isEmpty())
            out << g;
        for (int i = 0; i < item->childCount(); ++i)
            stack << item->child(i);
    }
    return out;
}

bool ModelTreePanel::applyFilter(QTreeWidgetItem* item, const QString& text)
{
    bool childMatches = false;
    for (int i = 0; i < item->childCount(); ++i)
        childMatches |= applyFilter(item->child(i), text);
    const bool matches = text.isEmpty() || item->text(0).contains(text, Qt::CaseInsensitive)
        || item->data(0, TypeRole).toString().contains(text, Qt::CaseInsensitive)
        || item->data(0, GuidRole).toString().contains(text, Qt::CaseInsensitive);
    item->setHidden(!(matches || childMatches));
    if (!text.isEmpty() && childMatches)
        item->setExpanded(true);
    return matches || childMatches;
}

void ModelTreePanel::setFilter(const QString& text)
{
    if (m_search->text() != text)
        m_search->setText(text); // re-enters via textChanged
    for (int i = 0; i < m_tree->topLevelItemCount(); ++i)
        applyFilter(m_tree->topLevelItem(i), text.trimmed());
}

void ModelTreePanel::showContextMenu(const QPoint& pos)
{
    QTreeWidgetItem* item = m_tree->itemAt(pos);
    if (!item)
        return;
    const QString guid = item->data(0, GuidRole).toString();
    QMenu menu(this);
    menu.addAction(tr("Isolate"), this, [this, guid] { emit isolateRequested(descendantGuids(guid)); });
    menu.addAction(tr("Hide"), this, [this, guid] { emit hideRequested(descendantGuids(guid)); });
    menu.addSeparator();
    menu.addAction(tr("Show all"), this, [this] { emit showAllRequested(); });
    menu.exec(m_tree->viewport()->mapToGlobal(pos));
}

} // namespace kimcad
