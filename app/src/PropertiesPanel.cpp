// SPDX-License-Identifier: GPL-3.0-or-later
#include "PropertiesPanel.h"

#include <QComboBox>
#include <QCoreApplication>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QJsonArray>
#include <QLocale>
#include <QMenu>
#include <QPalette>
#include <QPushButton>
#include <QTreeWidget>
#include <QVBoxLayout>

namespace kimbim {

QStringList renovationKeys()
{
    return {QStringLiteral("existing"), QStringLiteral("demolish"), QStringLiteral("new"),
            QStringLiteral("temporary"), QStringLiteral("auxiliary")};
}

QString renovationLabel(const QString& key)
{
    if (key == QLatin1String("existing"))
        return QCoreApplication::translate("Renovation", "Existing");
    if (key == QLatin1String("demolish"))
        return QCoreApplication::translate("Renovation", "To be demolished");
    if (key == QLatin1String("temporary"))
        return QCoreApplication::translate("Renovation", "Temporary");
    if (key == QLatin1String("auxiliary"))
        return QCoreApplication::translate("Renovation", "Auxiliary");
    return QCoreApplication::translate("Renovation", "New");
}

namespace {

enum Role { PsetRole = Qt::UserRole, PropRole, KindRole, SourceRole };
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
    case QJsonValue::Bool: // a read-only on/off (D100: a library object's summary)
        return v.toBool() ? QCoreApplication::translate("kimbim::PropertiesPanel", "Yes")
                          : QCoreApplication::translate("kimbim::PropertiesPanel", "No");
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
    m_tree->clear(); // deletes the status drop-down (an item widget) too
    m_name = nullptr;
    m_status = nullptr;
    m_material = nullptr;
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
    // D99: placed objects whose library definition changed since they were placed.
    if (const int outdated = merged.value("library_update").toInt(); outdated > 0) {
        auto* row = new QTreeWidgetItem(element, {tr("Library"), QString()});
        row->setFlags(row->flags() & ~Qt::ItemIsEditable);
        auto* button = new QPushButton(tr("Update from library (%n)", nullptr, outdated), m_tree);
        button->setObjectName(QStringLiteral("libraryUpdate"));
        button->setToolTip(tr("The library has a newer version of this object; values that still exist are kept"));
        connect(button, &QPushButton::clicked, this, &PropertiesPanel::updateFromLibraryRequested);
        m_tree->setItemWidget(row, 1, button);
    }
    if (count == 1 && !merged.value("guids").toArray().isEmpty())
        new QTreeWidgetItem(element, {QStringLiteral("GlobalId"), merged.value("guids").toArray().first().toString()});
    // D74: the renovation status (not for annotations, which have none).
    const QJsonObject status = merged.value("status").toObject();
    if (status.value("varies").toBool() || status.value("value").isString()) {
        auto* item = new QTreeWidgetItem(element, {tr("Renovation status"), QString()});
        m_status = new QComboBox(m_tree);
        m_status->setObjectName(QStringLiteral("renovationStatus"));
        if (status.value("varies").toBool())
            m_status->addItem(variesText(), QString());
        for (const QString& k : renovationKeys())
            m_status->addItem(renovationLabel(k), k);
        m_status->setCurrentIndex(std::max(0, m_status->findData(status.value("value").toString())));
        connect(m_status, &QComboBox::currentIndexChanged, this, [this](int i) {
            const QString key = m_status ? m_status->itemData(i).toString() : QString();
            if (!m_building && !key.isEmpty())
                emit statusEdited(key);
        });
        m_tree->setItemWidget(item, 1, m_status);
    }
    // D96: the element's composite (walls, slabs) or building material, changed from a list.
    const QJsonObject material = merged.value("material").toObject();
    if (!material.isEmpty()) {
        const QString kind = material.value("kind").toString();
        auto* item = new QTreeWidgetItem(element, {kind == QLatin1String("composite") ? tr("Composite") : tr("Building material"), QString()});
        m_material = new QComboBox(m_tree);
        m_material->setObjectName(QStringLiteral("elementMaterial"));
        if (material.value("varies").toBool())
            m_material->addItem(variesText(), QString());
        else if (material.value("value").toString().isEmpty())
            m_material->addItem(tr("(none)"), QString());
        for (const auto& c : material.value("choices").toArray())
            m_material->addItem(c.toString(), c.toString());
        m_material->setCurrentIndex(std::max(0, m_material->findData(material.value("value").toString())));
        m_material->setEnabled(material.value("editable").toBool());
        if (!m_material->isEnabled())
            m_material->setToolTip(tr("Set by the element's profile or layers: edit them in Graphics > Composites"));
        connect(m_material, &QComboBox::currentIndexChanged, this, [this, kind](int i) {
            const QString name = m_material ? m_material->itemData(i).toString() : QString();
            if (!m_building && !name.isEmpty())
                emit materialEdited(kind, name);
        });
        m_tree->setItemWidget(item, 1, m_material);
    }
    // M2: the classification references assigned to the selection.
    const QJsonArray classifications = merged.value("classifications").toArray();
    if (!classifications.isEmpty()) {
        auto* group = new QTreeWidgetItem(element, {tr("Classifications"), QString()});
        group->setData(0, SourceRole, QStringLiteral("classification"));
        for (const auto& value : classifications) {
            const QJsonObject c = value.toObject();
            new QTreeWidgetItem(group, {c.value("system").toString(),
                QStringLiteral("%1  %2").arg(c.value("identification").toString(), c.value("name").toString())});
        }
        group->setExpanded(true);
    }
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
            item->setToolTip(1, prop.value("source").toString() == QLatin1String("dimension")
                    ? tr("Metres, measured from the model; editing it changes the element")
                    : prop.value("ifc_type").toString());
            const bool varies = prop.value("varies").toBool();
            // D97: a value picked from a list (reference line, surfaces): a drop-down in the cell.
            if (kind != ReadOnly && prop.value("choices").isArray()) {
                auto* combo = new QComboBox(m_tree);
                combo->setObjectName(QStringLiteral("choice:%1/%2").arg(p.key(), v.key()));
                if (varies)
                    combo->addItem(variesText(), QString());
                for (const auto& c : prop.value("choices").toArray())
                    combo->addItem(c.toString(), c.toString());
                combo->setCurrentIndex(std::max(0, combo->findData(prop.value("value").toString())));
                const QString pset = p.key(), name = v.key();
                connect(combo, &QComboBox::currentIndexChanged, this, [this, combo, pset, name](int i) {
                    const QString value = combo->itemData(i).toString();
                    if (!m_building && !value.isEmpty())
                        emit propertyEdited(pset, name, QJsonValue(value));
                });
                item->setFlags(item->flags() & ~Qt::ItemIsEditable);
                m_tree->setItemWidget(item, 1, combo);
                continue;
            }
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
            // D50: where the value comes from. Inherited values are dimmed; overrides name the type value.
            const QString source = prop.value("source").toString();
            item->setData(0, SourceRole, source);
            const QString ifcType = prop.value("ifc_type").toString();
            if (source == QLatin1String("type")) {
                const QBrush dim = palette().brush(QPalette::Disabled, QPalette::Text);
                item->setForeground(0, dim);
                item->setForeground(1, dim);
                item->setToolTip(1, QStringLiteral("%1\n%2").arg(fromTypeText(), ifcType));
            } else if (source == QLatin1String("override")) {
                item->setToolTip(1, QStringLiteral("%1\n%2")
                                        .arg(tr("Overrides the type value: %1").arg(valueText(prop.value("type_value"))), ifcType));
            } else if (source == QLatin1String("mixed")) {
                item->setToolTip(1, QStringLiteral("%1\n%2").arg(tr("Some selected elements use their type's value"), ifcType));
            } else {
                item->setForeground(1, palette().brush(QPalette::Active, QPalette::Text));
            }
        }
        // D100: a library object's Parameters are a summary; Edit... opens the Object settings dialog
        // (off when the selection holds more than one type).
        if (p.key() == QLatin1String("Parameters") && merged.contains("object_settings")) {
            group->setData(0, SourceRole, QStringLiteral("parameter")); // no pset: nothing to add to it
            for (int i = 1; i < group->childCount(); ++i) // the type first (JSON objects come sorted)
                if (group->child(i)->data(0, PropRole).toString() == QLatin1String("Type"))
                    group->insertChild(0, group->takeChild(i));
            auto* row = new QTreeWidgetItem(group, {QString(), QString()});
            row->setFlags(row->flags() & ~Qt::ItemIsEditable);
            auto* buttons = new QWidget(m_tree);
            auto* layout = new QHBoxLayout(buttons);
            layout->setContentsMargins(0, 0, 0, 0);
            auto* button = new QPushButton(tr("Edit..."), buttons);
            button->setObjectName(QStringLiteral("objectSettingsEdit"));
            const bool enabled = merged.value("object_settings").toObject().value("enabled").toBool();
            button->setEnabled(enabled);
            button->setToolTip(enabled ? tr("Change these objects' settings, or move them to another saved version")
                                       : tr("The selection holds objects of more than one type"));
            connect(button, &QPushButton::clicked, this, &PropertiesPanel::objectSettingsRequested);
            // D101: the Object Editor on a copy of the selection's type (its values as the defaults)
            auto* copy = new QPushButton(tr("Customise a copy..."), buttons);
            copy->setObjectName(QStringLiteral("objectCustomiseCopy"));
            copy->setEnabled(enabled);
            copy->setToolTip(enabled ? tr("A new library object made from this one in the Object Editor")
                                     : tr("The selection holds objects of more than one type"));
            connect(copy, &QPushButton::clicked, this, &PropertiesPanel::customiseCopyRequested);
            layout->addWidget(button);
            layout->addWidget(copy);
            layout->addStretch();
            m_tree->setItemWidget(row, 1, buttons);
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

QList<QAction*> PropertiesPanel::actionsFor(QTreeWidgetItem* item, QObject* parent)
{
    if (!parent)
        parent = this;
    QList<QAction*> out;
    auto add = [&](const char* name, const QString& text, auto slot) {
        auto* a = new QAction(text, parent);
        a->setObjectName(QLatin1String(name));
        connect(a, &QAction::triggered, this, slot);
        out << a;
    };
    const QString pset = item ? item->data(0, PsetRole).toString() : QString();
    const QString prop = item ? item->data(0, PropRole).toString() : QString();
    const QString source = item ? item->data(0, SourceRole).toString() : QString();
    const bool editable = item && item->data(1, KindRole).toInt() != ReadOnly;
    const bool fromType = source == QLatin1String("type") || source == QLatin1String("override")
        || source == QLatin1String("mixed");
    if (!prop.isEmpty() && editable && fromType)
        add("editTypeValue", tr("Edit type value..."), [this, pset, prop] { emit typeEditRequested(pset, prop); });
    if (!prop.isEmpty() && (source == QLatin1String("override") || source == QLatin1String("mixed")))
        add("resetToType", tr("Reset to type value"), [this, pset, prop] { emit resetToTypeRequested(pset, prop); });
    // Measured dimensions and a library object's Parameters summary (D100) are no property set: no
    // property to add or remove.
    const bool dimension = source == QLatin1String("dimension") || source == QLatin1String("parameter")
        || pset == QLatin1String("Dimensions");
    if (!pset.isEmpty() && !dimension)
        add("addProperty", tr("Add property to %1...").arg(pset), [this, pset] { emit addPropertyRequested(pset); });
    if (!prop.isEmpty() && editable && !dimension && source != QLatin1String("type")) // inherited values have nothing to remove
        add("removeProperty", tr("Remove property %1").arg(prop), [this, pset, prop] { emit propertyRemoved(pset, prop); });
    if (m_name)
        add("addPropertySet", tr("Add property set..."), [this] { emit addPropertySetRequested(); });
    return out;
}

void PropertiesPanel::showContextMenu(const QPoint& pos)
{
    QMenu menu(this);
    menu.addActions(actionsFor(m_tree->itemAt(pos), &menu));
    if (!menu.isEmpty())
        menu.exec(m_tree->viewport()->mapToGlobal(pos));
}

} // namespace kimbim
