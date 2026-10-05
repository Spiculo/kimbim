// SPDX-License-Identifier: GPL-3.0-or-later
#include "ModelTreePanel.h"

#include <QHeaderView>
#include <QJsonArray>
#include <QLineEdit>
#include <QMenu>
#include <QTreeWidget>
#include <QVBoxLayout>

namespace kimcad {

namespace {
constexpr int GuidRole = Qt::UserRole;
}

ModelTreePanel::ModelTreePanel(QWidget* parent)
    : QWidget(parent)
    , m_search(new QLineEdit(this))
    , m_tree(new QTreeWidget(this))
{
    m_search->setPlaceholderText(tr("Search name, type or GlobalId"));
    m_search->setClearButtonEnabled(true);
    m_tree->setColumnCount(2);
    m_tree->setHeaderLabels({tr("Name"), tr("Type")});
    m_tree->header()->setStretchLastSection(false);
    m_tree->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_tree->header()->setSectionResizeMode(1, QHeaderView::Interactive);
    m_tree->setColumnWidth(1, 130);
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
}

void ModelTreePanel::setTree(const QJsonObject& root)
{
    clear();
    if (root.contains("guid"))
        addNode(root, nullptr)->setExpanded(true);
    // expand down to storeys so elements are one click away
    for (QTreeWidgetItem* item : std::as_const(m_items))
        if (item->text(1) == QLatin1String("IfcSite") || item->text(1) == QLatin1String("IfcBuilding"))
            item->setExpanded(true);
}

QTreeWidgetItem* ModelTreePanel::addNode(const QJsonObject& node, QTreeWidgetItem* parent)
{
    const QString type = node.value("type").toString();
    const QString name = node.value("name").toString();
    auto* item = parent ? new QTreeWidgetItem(parent) : new QTreeWidgetItem(m_tree);
    item->setText(0, name.isEmpty() ? type : name);
    item->setText(1, type);
    item->setData(0, GuidRole, node.value("guid").toString());
    item->setToolTip(0, node.value("guid").toString());
    m_items.insert(node.value("guid").toString(), item);
    for (const auto& child : node.value("children").toArray())
        addNode(child.toObject(), item);
    return item;
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

QStringList ModelTreePanel::selectedGuids() const
{
    QStringList out;
    for (QTreeWidgetItem* item : m_tree->selectedItems())
        out << item->data(0, GuidRole).toString();
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
        out << item->data(0, GuidRole).toString();
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
        || item->text(1).contains(text, Qt::CaseInsensitive)
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
