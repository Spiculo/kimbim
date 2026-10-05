// SPDX-License-Identifier: GPL-3.0-or-later
#include "PropertiesPanel.h"

#include <QHeaderView>
#include <QJsonArray>
#include <QLocale>
#include <QMenu>
#include <QTreeWidget>
#include <QVBoxLayout>

namespace kimcad {

namespace {

enum Role { PsetRole = Qt::UserRole, PropRole, KindRole };
enum Kind { Text = 0, Number = 1, Bool = 2, ReadOnly = 3, NameKind = 4 };

QString valueText(const QJsonValue& v)
{
    switch (v.type()) {
    case QJsonValue::Double:
        return QLocale().toString(v.toDouble(), 'g', 12);
    case QJsonValue::String:
        return v.toString();
    case QJsonValue::Array: {
        QStringList parts;
        for (const auto& x : v.toArray())
            parts << valueText(x);
        return QStringLiteral("(%1)").arg(parts.join(QStringLiteral(", ")));
    }
    case QJsonValue::Null:
        return QStringLiteral("—");
    default:
        return {};
    }
}

Kind kindOf(const QJsonObject& p)
{
    if (!p.value("editable").toBool())
        return ReadOnly;
    const QJsonValue v = p.value("value");
    const QString t = p.value("ifc_type").toString();
    if (v.isBool() || t == QLatin1String("IfcBoolean") || t == QLatin1String("IfcLogical"))
        return Bool;
    if (v.isDouble())
        return Number;
    return Text;
}

} // namespace

PropertiesPanel::PropertiesPanel(QWidget* parent)
    : QWidget(parent)
    , m_tree(new QTreeWidget(this))
{
    m_tree->setColumnCount(2);
    m_tree->setHeaderLabels({tr("Property"), tr("Value")});
    // Long Revit pset/type names must not push the Value column off screen: fixed, resizable widths.
    m_tree->header()->setSectionResizeMode(0, QHeaderView::Interactive);
    m_tree->header()->setStretchLastSection(true);
    m_tree->setColumnWidth(0, 170);
    m_tree->setTextElideMode(Qt::ElideMiddle);
    m_tree->setIndentation(12);
    m_tree->setUniformRowHeights(true);
    m_tree->setEditTriggers(QAbstractItemView::DoubleClicked | QAbstractItemView::EditKeyPressed
        | QAbstractItemView::SelectedClicked);
    m_tree->setContextMenuPolicy(Qt::CustomContextMenu);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addWidget(m_tree);
    connect(m_tree, &QTreeWidget::itemChanged, this, &PropertiesPanel::onItemChanged);
    connect(m_tree, &QTreeWidget::customContextMenuRequested, this, &PropertiesPanel::showContextMenu);
}

void PropertiesPanel::clear()
{
    m_building = true;
    m_tree->clear();
    m_name = nullptr;
    m_building = false;
}

void PropertiesPanel::showError(const QString& message)
{
    clear();
    m_building = true;
    new QTreeWidgetItem(m_tree, {tr("Error"), message});
    m_building = false;
}

void PropertiesPanel::showMulti(const QJsonObject& merged)
{
    if (merged.contains("error")) {
        showError(merged.value("error").toString());
        return;
    }
    clear();
    m_building = true;
    const int count = merged.value("count").toInt();
    QStringList types;
    for (const auto& t : merged.value("types").toArray())
        types << t.toString();
    auto* element = new QTreeWidgetItem(m_tree,
        {count > 1 ? tr("%n element(s)", nullptr, count) : tr("Element"), types.join(QStringLiteral(", "))});
    const QJsonObject name = merged.value("name").toObject();
    m_name = new QTreeWidgetItem(element, {QStringLiteral("Name"), QString()});
    m_name->setData(1, KindRole, NameKind);
    m_name->setFlags(m_name->flags() | Qt::ItemIsEditable);
    if (name.value("varies").toBool()) {
        m_name->setText(1, variesText());
        QFont italic = m_name->font(1);
        italic.setItalic(true);
        m_name->setFont(1, italic);
    } else {
        m_name->setText(1, name.value("value").toString());
    }
    if (count == 1 && !merged.value("guids").toArray().isEmpty())
        new QTreeWidgetItem(element, {QStringLiteral("GlobalId"), merged.value("guids").toArray().first().toString()});
    element->setExpanded(true);

    const QJsonObject psets = merged.value("psets").toObject();
    for (auto p = psets.begin(); p != psets.end(); ++p) {
        auto* group = new QTreeWidgetItem(m_tree, {p.key(), QString()});
        group->setData(0, PsetRole, p.key());
        const QJsonObject props = p.value().toObject();
        for (auto v = props.begin(); v != props.end(); ++v) {
            const QJsonObject prop = v.value().toObject();
            const Kind kind = kindOf(prop);
            auto* item = new QTreeWidgetItem(group, {v.key(), QString()});
            item->setData(0, PsetRole, p.key());
            item->setData(0, PropRole, v.key());
            item->setData(1, KindRole, kind);
            item->setToolTip(1, prop.value("ifc_type").toString());
            const bool varies = prop.value("varies").toBool();
            if (kind == Bool) {
                item->setFlags((item->flags() | Qt::ItemIsUserCheckable) & ~Qt::ItemIsEditable);
                item->setCheckState(1, varies ? Qt::PartiallyChecked
                                              : (prop.value("value").toBool() ? Qt::Checked : Qt::Unchecked));
            } else {
                if (kind != ReadOnly)
                    item->setFlags(item->flags() | Qt::ItemIsEditable);
                else
                    item->setFlags(item->flags() & ~Qt::ItemIsEditable);
                item->setText(1, varies ? variesText() : valueText(prop.value("value")));
            }
            if (varies) {
                QFont italic = item->font(1);
                italic.setItalic(true);
                item->setFont(1, italic);
            }
        }
        group->setExpanded(true);
    }
    m_building = false;
}

QTreeWidgetItem* PropertiesPanel::itemFor(const QString& pset, const QString& prop) const
{
    for (int g = 0; g < m_tree->topLevelItemCount(); ++g) {
        QTreeWidgetItem* group = m_tree->topLevelItem(g);
        for (int i = 0; i < group->childCount(); ++i) {
            QTreeWidgetItem* item = group->child(i);
            if (item->data(0, PsetRole).toString() == pset && item->data(0, PropRole).toString() == prop)
                return item;
        }
    }
    return nullptr;
}

void PropertiesPanel::onItemChanged(QTreeWidgetItem* item, int column)
{
    if (m_building || column != 1)
        return;
    const int kind = item->data(1, KindRole).toInt();
    if (kind == NameKind) {
        if (item->text(1) != variesText())
            emit nameEdited(item->text(1));
        return;
    }
    const QString pset = item->data(0, PsetRole).toString();
    const QString prop = item->data(0, PropRole).toString();
    if (pset.isEmpty() || prop.isEmpty() || kind == ReadOnly)
        return;
    if (kind == Bool) {
        if (item->checkState(1) != Qt::PartiallyChecked)
            emit propertyEdited(pset, prop, QJsonValue(item->checkState(1) == Qt::Checked));
        return;
    }
    const QString text = item->text(1);
    if (text == variesText())
        return;
    if (kind == Number) {
        bool ok = false;
        const double d = QLocale().toDouble(text, &ok);
        const double c = ok ? d : QLocale::c().toDouble(text, &ok);
        if (ok) {
            emit propertyEdited(pset, prop, QJsonValue(c));
            return;
        }
    }
    emit propertyEdited(pset, prop, QJsonValue(text)); // the bridge converts to the property's IFC type
}

void PropertiesPanel::showContextMenu(const QPoint& pos)
{
    QTreeWidgetItem* item = m_tree->itemAt(pos);
    QMenu menu(this);
    const QString pset = item ? item->data(0, PsetRole).toString() : QString();
    const QString prop = item ? item->data(0, PropRole).toString() : QString();
    if (!pset.isEmpty())
        menu.addAction(tr("Add property to %1...").arg(pset), this, [this, pset] { emit addPropertyRequested(pset); });
    if (!prop.isEmpty() && item->data(1, KindRole).toInt() != ReadOnly)
        menu.addAction(tr("Remove property %1").arg(prop), this, [this, pset, prop] { emit propertyRemoved(pset, prop); });
    if (m_name) {
        if (!menu.isEmpty())
            menu.addSeparator();
        menu.addAction(tr("Add property set..."), this, [this] { emit addPropertySetRequested(); });
    }
    if (!menu.isEmpty())
        menu.exec(m_tree->viewport()->mapToGlobal(pos));
}

} // namespace kimcad
