// SPDX-License-Identifier: GPL-3.0-or-later
// The rule editors of the Graphics menu (D73): visibility sets and graphic override sets.
#include "GraphicsDialogs.h"

#include <QCheckBox>
#include <QColorDialog>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QPushButton>
#include <QSpinBox>
#include <QVBoxLayout>

#include <algorithm>

namespace kimbim {

// ---------------- RuleEditor ----------------

RuleEditor::RuleEditor(const QStringList& kinds, const QStringList& lineTypes, QWidget* parent)
    : QWidget(parent)
{
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    auto* when = new QFormLayout;
    m_name = new QLineEdit(this);
    m_enabled = new QCheckBox(tr("On"), this);
    m_enabled->setChecked(true);
    m_kind = new QComboBox(this);
    m_kind->addItem(tr("Any"), QString());
    for (const QString& k : kinds)
        m_kind->addItem(kindLabel(k), k);
    m_class = new QLineEdit(this);
    m_class->setPlaceholderText(QStringLiteral("IfcWall"));
    m_property = new QLineEdit(this);
    m_property->setPlaceholderText(tr("FireRating, or Pset_WallCommon.FireRating"));
    m_op = new QComboBox(this);
    const QList<std::pair<QString, QString>> ops{{"equals", tr("is")}, {"not_equals", tr("is not")},
        {"contains", tr("contains")}, {"exists", tr("is set")}, {"missing", tr("is not set")}, {"true", tr("is true")},
        {"false", tr("is false")}, {"less", tr("is less than")}, {"more", tr("is more than")}};
    for (const auto& [op, label] : ops)
        m_op->addItem(label, op);
    m_value = new QLineEdit(this);
    m_layer = new QLineEdit(this);
    m_material = new QLineEdit(this);
    auto* propRow = new QHBoxLayout;
    propRow->addWidget(m_property, 2);
    propRow->addWidget(m_op);
    propRow->addWidget(m_value, 1);
    when->addRow(tr("Name:"), m_name);
    when->addRow(QString(), m_enabled);
    when->addRow(tr("Element kind:"), m_kind);
    when->addRow(tr("IFC class:"), m_class);
    when->addRow(tr("Property:"), propRow);
    when->addRow(tr("Layer:"), m_layer);
    when->addRow(tr("Material contains:"), m_material);
    layout->addLayout(when);

    m_effects = new QWidget(this);
    auto* then = new QFormLayout(m_effects);
    then->setContentsMargins(0, 0, 0, 0);
    auto pen = [this] {
        auto* sp = new QSpinBox(this);
        sp->setRange(0, 255);
        sp->setSpecialValueText(QStringLiteral("—"));
        return sp;
    };
    m_pen = pen();
    m_cutPen = pen();
    m_projectionPen = pen();
    m_fill = pen();
    m_line = new QComboBox(this);
    m_line->addItem(QStringLiteral("—"), QString());
    for (const QString& l : lineTypes)
        m_line->addItem(l, l);
    m_surface = new QLineEdit(this);
    m_surface->setPlaceholderText(QStringLiteral("#rrggbb"));
    auto* pick = new QPushButton(QStringLiteral("..."), this);
    auto* surfaceRow = new QHBoxLayout;
    surfaceRow->addWidget(m_surface, 1);
    surfaceRow->addWidget(pick);
    m_transparency = new QDoubleSpinBox(this);
    m_transparency->setRange(-0.1, 1.0);
    m_transparency->setSingleStep(0.1);
    m_transparency->setDecimals(2);
    m_transparency->setSpecialValueText(QStringLiteral("—"));
    m_transparency->setValue(-0.1);
    m_hide = new QCheckBox(tr("Hide the element"), this);
    then->addRow(tr("Pen (cut and projection):"), m_pen);
    then->addRow(tr("Cut pen:"), m_cutPen);
    then->addRow(tr("Projection pen:"), m_projectionPen);
    then->addRow(tr("Line type:"), m_line);
    then->addRow(tr("Cut fill pen:"), m_fill);
    then->addRow(tr("3D surface:"), surfaceRow);
    then->addRow(tr("3D transparency:"), m_transparency);
    then->addRow(QString(), m_hide);
    then->insertRow(0, new QLabel(tr("Then:"), m_effects));
    layout->addWidget(m_effects);

    auto notify = [this] {
        if (!m_loading)
            emit changed();
    };
    for (QLineEdit* e : {m_name, m_class, m_property, m_value, m_layer, m_material, m_surface})
        connect(e, &QLineEdit::textEdited, this, notify);
    for (QComboBox* c : {m_kind, m_op, m_line})
        connect(c, &QComboBox::currentIndexChanged, this, notify);
    for (QSpinBox* sp : {m_pen, m_cutPen, m_projectionPen, m_fill})
        connect(sp, &QSpinBox::valueChanged, this, notify);
    connect(m_transparency, &QDoubleSpinBox::valueChanged, this, notify);
    connect(m_hide, &QCheckBox::toggled, this, notify);
    connect(m_enabled, &QCheckBox::toggled, this, notify);
    connect(pick, &QPushButton::clicked, this, [this] {
        const QColor c = QColorDialog::getColor(QColor(m_surface->text()), this, tr("3D surface"));
        if (c.isValid()) {
            m_surface->setText(c.name());
            emit changed();
        }
    });
}

void RuleEditor::setHideOnly(bool on)
{
    m_hideOnly = on;
    m_effects->setVisible(!on);
}

void RuleEditor::setRule(const QJsonObject& rule)
{
    m_loading = true;
    const QJsonObject when = rule.value("when").toObject(), then = rule.value("then").toObject();
    m_name->setText(rule.value("name").toString());
    m_enabled->setChecked(rule.value("enabled").toBool(true));
    const QJsonValue kind = when.value("kind");
    const QString k = kind.isArray() ? kind.toArray().at(0).toString() : kind.toString();
    m_kind->setCurrentIndex(std::max(0, m_kind->findData(k)));
    m_class->setText(when.value("ifc_class").toString());
    m_property->setText(when.value("property").toString());
    m_op->setCurrentIndex(std::max(0, m_op->findData(when.value("op").toString(QStringLiteral("equals")))));
    m_value->setText(when.value("value").toString());
    m_layer->setText(when.value("layer").toString());
    m_material->setText(when.value("material").toString());
    m_pen->setValue(then.value("pen").toInt(0));
    m_cutPen->setValue(then.value("cut_pen").toInt(0));
    m_projectionPen->setValue(then.value("projection_pen").toInt(0));
    m_fill->setValue(then.value("fill").toInt(0));
    m_line->setCurrentIndex(std::max(0, m_line->findData(then.value("line").toString())));
    m_surface->setText(then.value("surface").toString());
    m_transparency->setValue(then.contains("transparency") ? then.value("transparency").toDouble() : -0.1);
    m_hide->setChecked(then.value("hide").toBool(false));
    m_loading = false;
}

QJsonObject RuleEditor::rule() const
{
    QJsonObject when, then;
    if (const QString k = m_kind->currentData().toString(); !k.isEmpty())
        when.insert("kind", k);
    auto text = [](QJsonObject& o, const char* key, const QLineEdit* e) {
        if (!e->text().trimmed().isEmpty())
            o.insert(QLatin1String(key), e->text().trimmed());
    };
    text(when, "ifc_class", m_class);
    if (!m_property->text().trimmed().isEmpty()) {
        when.insert("property", m_property->text().trimmed());
        const QString op = m_op->currentData().toString();
        when.insert("op", op);
        static const QStringList noValue{"exists", "missing", "true", "false"};
        if (!noValue.contains(op))
            when.insert("value", m_value->text().trimmed());
    }
    text(when, "layer", m_layer);
    text(when, "material", m_material);
    if (m_hideOnly) {
        then.insert("hide", true);
    } else {
        auto pen = [&then](const char* key, const QSpinBox* sp) {
            if (sp->value() > 0)
                then.insert(QLatin1String(key), sp->value());
        };
        pen("pen", m_pen);
        pen("cut_pen", m_cutPen);
        pen("projection_pen", m_projectionPen);
        if (const QString l = m_line->currentData().toString(); !l.isEmpty())
            then.insert("line", l);
        pen("fill", m_fill);
        const QString surface = m_surface->text().trimmed();
        if (surface.startsWith(QLatin1Char('#')) && QColor(surface).isValid())
            then.insert("surface", QColor(surface).name());
        if (m_transparency->value() >= 0.0)
            then.insert("transparency", m_transparency->value());
        if (m_hide->isChecked())
            then.insert("hide", true);
    }
    QJsonObject rule{{"name", m_name->text().trimmed()}, {"when", when}, {"then", then}};
    if (!m_enabled->isChecked())
        rule.insert("enabled", false);
    return rule;
}

// ---------------- RulesDialog ----------------

RulesDialog::RulesDialog(const QJsonObject& reply, const QString& key, const QString& reference, bool hideOnly, QWidget* parent)
    : NamedSetsDialog(reply, key, reference, parent)
    , m_hideOnly(hideOnly)
{
}

void RulesDialog::buildRules()
{
    auto* body = new QHBoxLayout;
    auto* left = new QVBoxLayout;
    m_rules = new QListWidget(this);
    m_rules->setObjectName(QStringLiteral("rules"));
    left->addWidget(new QLabel(m_hideOnly ? tr("Also hide elements that match:") : tr("Rules (the first that matches wins):"), this));
    left->addWidget(m_rules, 1);
    auto* buttons = new QHBoxLayout;
    auto button = [&](const char* name, const QString& text) {
        auto* b = new QPushButton(text, this);
        b->setObjectName(QLatin1String(name));
        buttons->addWidget(b);
        return b;
    };
    QPushButton* add = button("addRule", tr("Add"));
    QPushButton* remove = button("deleteRule", tr("Delete"));
    QPushButton* up = button("ruleUp", tr("Up"));
    QPushButton* down = button("ruleDown", tr("Down"));
    left->addLayout(buttons);
    body->addLayout(left, 1);
    QStringList kinds;
    for (const auto& k : m_reply.value("kinds").toArray())
        kinds << k.toString();
    m_editor = new RuleEditor(kinds, table("line_types").keys(), this);
    m_editor->setHideOnly(m_hideOnly);
    body->addWidget(m_editor, 2);
    m_layout->addLayout(body);
    connect(add, &QPushButton::clicked, this, [this] {
        addRule(QJsonObject{{"name", tr("New rule")}, {"when", QJsonObject{}},
            {"then", m_hideOnly ? QJsonObject{{"hide", true}} : QJsonObject{{"pen", 26}}}});
    });
    connect(remove, &QPushButton::clicked, this, [this] { deleteRule(m_rules->currentRow()); });
    connect(up, &QPushButton::clicked, this, [this] { moveRule(m_rules->currentRow(), m_rules->currentRow() - 1); });
    connect(down, &QPushButton::clicked, this, [this] { moveRule(m_rules->currentRow(), m_rules->currentRow() + 1); });
    connect(m_rules, &QListWidget::currentRowChanged, this, &RulesDialog::showRule);
    connect(m_rules, &QListWidget::itemChanged, this, [this](QListWidgetItem* item) {
        if (!m_loading)
            setRuleEnabled(m_rules->row(item), item->checkState() == Qt::Checked);
    });
    connect(m_editor, &RuleEditor::changed, this, [this] {
        const int i = m_rules->currentRow();
        QJsonArray list = rules();
        if (i < 0 || i >= list.size())
            return;
        const QJsonObject r = m_editor->rule();
        list[i] = r;
        setRules(list);
        m_loading = true;
        m_rules->item(i)->setText(r.value("name").toString());
        m_rules->item(i)->setCheckState(r.value("enabled").toBool(true) ? Qt::Checked : Qt::Unchecked);
        m_loading = false;
    });
}

void RulesDialog::setRules(const QJsonArray& list)
{
    QJsonObject set = currentValue();
    set.insert("rules", list);
    setCurrentValue(set);
}

void RulesDialog::showSet(const QString&)
{
    if (!m_rules)
        return;
    m_loading = true;
    m_rules->clear();
    for (const auto& r : rules()) {
        auto* item = new QListWidgetItem(r.toObject().value("name").toString(), m_rules);
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(r.toObject().value("enabled").toBool(true) ? Qt::Checked : Qt::Unchecked);
    }
    m_loading = false;
    m_rules->setCurrentRow(m_rules->count() > 0 ? 0 : -1);
    showRule(m_rules->currentRow());
}

void RulesDialog::showRule(int i)
{
    const QJsonArray list = rules();
    m_editor->setEnabled(i >= 0 && i < list.size());
    if (i >= 0 && i < list.size())
        m_editor->setRule(list.at(i).toObject());
}

void RulesDialog::addRule(const QJsonObject& rule)
{
    QJsonArray list = rules();
    list.append(rule);
    setRules(list);
    showSet(currentSet());
    m_rules->setCurrentRow(int(list.size()) - 1);
}

bool RulesDialog::deleteRule(int i)
{
    QJsonArray list = rules();
    if (i < 0 || i >= list.size())
        return false;
    list.removeAt(i);
    setRules(list);
    showSet(currentSet());
    return true;
}

bool RulesDialog::moveRule(int from, int to)
{
    QJsonArray list = rules();
    if (from < 0 || from >= list.size() || to < 0 || to >= list.size() || from == to)
        return false;
    const QJsonValue r = list.takeAt(from);
    list.insert(to, r);
    setRules(list);
    showSet(currentSet());
    m_rules->setCurrentRow(to);
    return true;
}

bool RulesDialog::setRuleEnabled(int i, bool enabled)
{
    QJsonArray list = rules();
    if (i < 0 || i >= list.size())
        return false;
    QJsonObject r = list.at(i).toObject();
    if (enabled)
        r.remove("enabled");
    else
        r.insert("enabled", false);
    list[i] = r;
    setRules(list);
    m_loading = true;
    m_rules->item(i)->setCheckState(enabled ? Qt::Checked : Qt::Unchecked);
    m_loading = false;
    if (m_rules->currentRow() == i)
        showRule(i);
    return true;
}

// ---------------- VisibilitySetsDialog ----------------

VisibilitySetsDialog::VisibilitySetsDialog(const QJsonObject& reply, QWidget* parent)
    : RulesDialog(reply, QStringLiteral("visibility_sets"), QStringLiteral("visibility"), true, parent)
{
    setWindowTitle(tr("Visibility sets"));
    buildPicker();
    m_layout->addWidget(new QLabel(tr("Hidden element kinds:"), this));
    m_kinds = new QListWidget(this);
    m_kinds->setObjectName(QStringLiteral("hiddenKinds"));
    for (const auto& k : reply.value("kinds").toArray()) {
        auto* item = new QListWidgetItem(kindLabel(k.toString()), m_kinds);
        item->setData(Qt::UserRole, k.toString());
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(Qt::Unchecked);
    }
    m_kinds->setMaximumHeight(180);
    m_layout->addWidget(m_kinds);
    buildRules();
    finishLayout();
    resize(760, 620);
    connect(m_kinds, &QListWidget::itemChanged, this, [this](QListWidgetItem* item) {
        if (!m_loading)
            setKindHidden(item->data(Qt::UserRole).toString(), item->checkState() == Qt::Checked);
    });
    selectSet(reply.value("tables").toObject().value("purposes").toObject()
                  .value(reply.value("purpose").toString()).toObject().value("visibility").toString());
}

void VisibilitySetsDialog::showSet(const QString& name)
{
    RulesDialog::showSet(name);
    if (!m_kinds)
        return;
    const QJsonArray hidden = currentValue().value("hidden_kinds").toArray();
    m_loading = true;
    for (int i = 0; i < m_kinds->count(); ++i)
        m_kinds->item(i)->setCheckState(
            hidden.contains(m_kinds->item(i)->data(Qt::UserRole).toString()) ? Qt::Checked : Qt::Unchecked);
    m_loading = false;
}

void VisibilitySetsDialog::setKindHidden(const QString& kind, bool hidden)
{
    QJsonObject set = currentValue();
    const QJsonArray was = set.value("hidden_kinds").toArray();
    QJsonArray kinds;
    for (int i = 0; i < m_kinds->count(); ++i) { // kept in the kinds' order
        const QString k = m_kinds->item(i)->data(Qt::UserRole).toString();
        if (k == kind ? hidden : was.contains(k))
            kinds.append(k);
    }
    set.insert("hidden_kinds", kinds);
    if (!set.contains("rules"))
        set.insert("rules", QJsonArray());
    setCurrentValue(set);
    showSet(currentSet());
}

// ---------------- OverridesDialog ----------------

OverridesDialog::OverridesDialog(const QJsonObject& reply, QWidget* parent)
    : RulesDialog(reply, QStringLiteral("override_sets"), QStringLiteral("overrides"), false, parent)
{
    setWindowTitle(tr("Graphic overrides"));
    buildPicker();
    buildRules();
    finishLayout();
    resize(760, 560);
    selectSet(reply.value("tables").toObject().value("purposes").toObject()
                  .value(reply.value("purpose").toString()).toObject().value("overrides").toString());
}

} // namespace kimbim
