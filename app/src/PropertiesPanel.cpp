// SPDX-License-Identifier: GPL-3.0-or-later
#include "PropertiesPanel.h"

#include <QHeaderView>
#include <QJsonArray>
#include <QJsonValue>
#include <QTreeWidget>
#include <QVBoxLayout>

namespace kimcad {

namespace {

QString valueText(const QJsonValue& v)
{
    switch (v.type()) {
    case QJsonValue::Bool:
        return v.toBool() ? PropertiesPanel::tr("Yes") : PropertiesPanel::tr("No");
    case QJsonValue::Double:
        return QString::number(v.toDouble(), 'g', 12);
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

} // namespace

PropertiesPanel::PropertiesPanel(QWidget* parent)
    : QWidget(parent)
    , m_tree(new QTreeWidget(this))
{
    m_tree->setColumnCount(2);
    m_tree->setHeaderLabels({tr("Property"), tr("Value")});
    m_tree->header()->setSectionResizeMode(0, QHeaderView::ResizeToContents);
    m_tree->setUniformRowHeights(true);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addWidget(m_tree);
}

void PropertiesPanel::clear()
{
    m_tree->clear();
}

void PropertiesPanel::showProperties(const QJsonObject& props)
{
    m_tree->clear();
    if (props.contains("error")) {
        new QTreeWidgetItem(m_tree, {tr("Error"), props.value("error").toString()});
        return;
    }
    auto* element = new QTreeWidgetItem(m_tree, {tr("Element"), props.value("type").toString()});
    const QJsonObject attrs = props.value("attributes").toObject();
    for (auto it = attrs.begin(); it != attrs.end(); ++it)
        new QTreeWidgetItem(element, {it.key(), valueText(it.value())}); // IFC names are never translated
    element->setExpanded(true);
    const QJsonObject psets = props.value("psets").toObject();
    for (auto p = psets.begin(); p != psets.end(); ++p) {
        auto* group = new QTreeWidgetItem(m_tree, {p.key(), QString()});
        const QJsonObject values = p.value().toObject();
        for (auto v = values.begin(); v != values.end(); ++v)
            new QTreeWidgetItem(group, {v.key(), valueText(v.value())});
        group->setExpanded(true);
    }
}

} // namespace kimcad
