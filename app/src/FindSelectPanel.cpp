// SPDX-License-Identifier: GPL-3.0-or-later
#include "FindSelectPanel.h"

#include "GraphicsDialogs.h"
#include "PropertiesPanel.h"

#include <QComboBox>
#include <QCompleter>
#include <QCoreApplication>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QScrollArea>
#include <QToolButton>
#include <QVBoxLayout>

namespace kimbim {

namespace {

struct Choice {
    const char* key;
    const char* label;
};

// The fields and, per field, the operators kimbim.queries accepts (FIELD_OPS).
const Choice kFields[] = {
    {"ifc_class", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "IFC class")},
    {"kind", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "Element kind")},
    {"type", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "Type")},
    {"name", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "Name")},
    {"property", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "Property")},
    {"layer", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "Layer")},
    {"level", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "Level")},
    {"status", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "Renovation status")},
    {"material", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "Material")},
};

const Choice kOps[] = {
    {"equals", "="},
    {"not_equals", "≠"},
    {"contains", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "contains")},
    {"less", "<"},
    {"more", ">"},
    {"exists", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "has a value")},
    {"missing", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "has none")},
    {"true", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "is true")},
    {"false", QT_TRANSLATE_NOOP("kimbim::FindSelectPanel", "is false")},
};

QStringList opsFor(const QString& field)
{
    if (field == QLatin1String("kind") || field == QLatin1String("ifc_class") || field == QLatin1String("level")
        || field == QLatin1String("status"))
        return {"equals", "not_equals"};
    if (field == QLatin1String("name"))
        return {"equals", "not_equals", "contains"};
    if (field == QLatin1String("type") || field == QLatin1String("layer") || field == QLatin1String("material"))
        return {"equals", "not_equals", "contains", "exists", "missing"};
    return {"equals", "not_equals", "contains", "less", "more", "exists", "missing", "true", "false"};
}

bool needsValue(const QString& op)
{
    return op != QLatin1String("exists") && op != QLatin1String("missing") && op != QLatin1String("true")
        && op != QLatin1String("false");
}

QStringList strings(const QJsonValue& v)
{
    QStringList out;
    for (const auto& x : v.toArray())
        out << x.toString();
    return out;
}

} // namespace

FindSelectPanel::FindSelectPanel(QWidget* parent)
    : QWidget(parent)
    , m_match(new QComboBox(this))
    , m_scope(new QComboBox(this))
    , m_rowsLayout(new QVBoxLayout)
    , m_saved(new QComboBox(this))
    , m_setName(new QLineEdit(this))
    , m_sets(new QListWidget(this))
    , m_result(new QLabel(this))
{
    setObjectName(QStringLiteral("findSelectPanel"));
    auto button = [this](const QString& text, const QString& tip, const char* name) {
        auto* b = new QToolButton(this); // compact: the panel is narrow
        b->setText(text);
        b->setToolTip(tip);
        b->setObjectName(QLatin1String(name));
        return b;
    };

    // Saved criteria: pick one to load it, or type a name and save.
    m_saved->setObjectName(QStringLiteral("savedCriteria"));
    m_saved->setEditable(true);
    m_saved->setInsertPolicy(QComboBox::NoInsert);
    m_saved->lineEdit()->setPlaceholderText(tr("Criteria set name"));
    QToolButton* saveCriteriaButton = button(tr("Save"), tr("Save these criteria under this name (in the project)"), "saveCriteria");
    QToolButton* deleteCriteriaButton = button(tr("Delete"), tr("Delete this saved criteria set"), "deleteCriteria");
    auto shrink = [](QComboBox* c) { // the panel is narrow: combos give way instead of clipping buttons
        c->setMinimumContentsLength(6);
        c->setSizeAdjustPolicy(QComboBox::AdjustToMinimumContentsLengthWithIcon);
    };
    shrink(m_saved);
    shrink(m_match);
    shrink(m_scope);
    auto* savedRow = new QHBoxLayout;
    savedRow->addWidget(m_saved, 1);
    savedRow->addWidget(saveCriteriaButton);
    savedRow->addWidget(deleteCriteriaButton);
    connect(m_saved, qOverload<int>(&QComboBox::activated), this, [this](int i) { loadCriteria(m_saved->itemText(i)); });
    connect(saveCriteriaButton, &QToolButton::clicked, this, [this] { saveCriteria(m_saved->currentText().trimmed()); });
    connect(deleteCriteriaButton, &QToolButton::clicked, this, [this] {
        const QString name = m_saved->currentText().trimmed();
        if (m_savedCriteria.contains(name))
            emit deleteCriteriaRequested(name);
    });

    m_match->setObjectName(QStringLiteral("matchCombo"));
    m_match->addItem(tr("All of these (AND)"), QStringLiteral("all"));
    m_match->addItem(tr("Any of these (OR)"), QStringLiteral("any"));
    m_scope->setObjectName(QStringLiteral("scopeCombo"));
    m_scope->addItem(tr("Whole model"), QStringLiteral("model"));
    m_scope->addItem(tr("Active level"), QStringLiteral("level"));
    m_scope->addItem(tr("Current selection"), QStringLiteral("selection"));
    auto* matchRow = new QHBoxLayout;
    matchRow->addWidget(new QLabel(tr("Match"), this));
    matchRow->addWidget(m_match, 1);
    auto* scopeRow = new QHBoxLayout;
    scopeRow->addWidget(new QLabel(tr("In"), this));
    scopeRow->addWidget(m_scope, 1);

    auto* rowsHost = new QWidget(this);
    m_rowsLayout->setContentsMargins(0, 0, 0, 0);
    m_rowsLayout->addStretch(1);
    rowsHost->setLayout(m_rowsLayout);
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setWidget(rowsHost);
    scroll->setFrameShape(QFrame::NoFrame);
    QToolButton* addRowButton = button(tr("+ Criterion"), tr("Add a criterion row"), "addCriterion");
    connect(addRowButton, &QToolButton::clicked, this, [this] { addRow(); });

    QToolButton* select = button(tr("Select"), tr("Select the matching elements (replaces the selection)"), "findSelect");
    QToolButton* add = button(tr("Add"), tr("Add the matching elements to the selection"), "findAdd");
    QToolButton* remove = button(tr("Remove"), tr("Remove the matching elements from the selection"), "findRemove");
    connect(select, &QToolButton::clicked, this, [this] { find(How::Replace); });
    connect(add, &QToolButton::clicked, this, [this] { find(How::Add); });
    connect(remove, &QToolButton::clicked, this, [this] { find(How::Remove); });
    auto* addRowLine = new QHBoxLayout;
    addRowLine->addWidget(addRowButton);
    addRowLine->addStretch(1);
    auto* actions = new QHBoxLayout;
    for (QToolButton* b : {select, add, remove})
        actions->addWidget(b);
    m_result->setObjectName(QStringLiteral("findResult"));

    auto* criteriaBox = new QGroupBox(tr("Find && Select"), this);
    auto* criteriaLayout = new QVBoxLayout(criteriaBox);
    criteriaLayout->addLayout(savedRow);
    criteriaLayout->addLayout(matchRow);
    criteriaLayout->addWidget(scroll, 1);
    criteriaLayout->addLayout(addRowLine);
    criteriaLayout->addLayout(scopeRow);
    criteriaLayout->addLayout(actions);
    criteriaLayout->addWidget(m_result);

    // Selection sets: saved selections (GlobalIds in the project).
    m_sets->setObjectName(QStringLiteral("selectionSets"));
    m_setName->setObjectName(QStringLiteral("setName"));
    m_setName->setPlaceholderText(tr("Selection set name"));
    QToolButton* saveSetButton = button(tr("Save selection"), tr("Save the selected elements under this name"), "saveSet");
    QToolButton* recall = button(tr("Select"), tr("Select the elements of this set (replaces the selection)"), "recallSet");
    QToolButton* recallAdd = button(tr("Add"), tr("Add the elements of this set to the selection"), "recallSetAdd");
    QToolButton* deleteSet = button(tr("Delete"), tr("Delete this selection set (the elements stay)"), "deleteSet");
    connect(saveSetButton, &QToolButton::clicked, this, [this] {
        saveSet(m_setName->text().trimmed().isEmpty() ? selectedSet() : m_setName->text().trimmed());
    });
    connect(recall, &QToolButton::clicked, this, [this] { recallSet(selectedSet(), How::Replace); });
    connect(recallAdd, &QToolButton::clicked, this, [this] { recallSet(selectedSet(), How::Add); });
    connect(deleteSet, &QToolButton::clicked, this, [this] {
        if (!selectedSet().isEmpty())
            emit deleteSetRequested(selectedSet());
    });
    connect(m_sets, &QListWidget::itemDoubleClicked, this, [this] { recallSet(selectedSet(), How::Replace); });
    auto* setsBox = new QGroupBox(tr("Selection sets"), this);
    auto* setsLayout = new QVBoxLayout(setsBox);
    auto* nameRow = new QHBoxLayout;
    nameRow->addWidget(m_setName, 1);
    nameRow->addWidget(saveSetButton);
    setsLayout->addLayout(nameRow);
    setsLayout->addWidget(m_sets, 1);
    auto* setButtons = new QHBoxLayout;
    setButtons->addStretch(1);
    for (QToolButton* b : {recall, recallAdd, deleteSet})
        setButtons->addWidget(b);
    setsLayout->addLayout(setButtons);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addWidget(criteriaBox, 3);
    layout->addWidget(setsBox, 1);
    addRow();
}

void FindSelectPanel::showEvent(QShowEvent* event)
{
    QWidget::showEvent(event);
    emit refreshRequested();
}

void FindSelectPanel::setChoices(const QJsonObject& choices)
{
    m_choices = choices;
    for (Row& r : m_rows)
        fillValues(r, r.value->currentData().isValid() ? r.value->currentData().toString() : r.value->currentText());
}

void FindSelectPanel::setSaved(const QJsonObject& criteria, const QJsonObject& sets)
{
    m_savedCriteria = criteria;
    const QString text = m_saved->currentText();
    m_saved->blockSignals(true);
    m_saved->clear();
    m_saved->addItems(criteria.keys());
    m_saved->setCurrentText(text);
    m_saved->blockSignals(false);
    const QString current = selectedSet();
    m_sets->clear();
    for (auto it = sets.constBegin(); it != sets.constEnd(); ++it) {
        auto* item = new QListWidgetItem(tr("%1 (%n element(s))", nullptr, int(it.value().toArray().size())).arg(it.key()), m_sets);
        item->setData(Qt::UserRole, it.key());
        if (it.key() == current)
            m_sets->setCurrentItem(item);
    }
}

QStringList FindSelectPanel::savedCriteriaNames() const
{
    return m_savedCriteria.keys();
}

QStringList FindSelectPanel::savedSetNames() const
{
    QStringList out;
    for (int i = 0; i < m_sets->count(); ++i)
        out << m_sets->item(i)->data(Qt::UserRole).toString();
    return out;
}

QString FindSelectPanel::selectedSet() const
{
    const QListWidgetItem* item = m_sets->currentItem();
    return item ? item->data(Qt::UserRole).toString() : QString();
}

void FindSelectPanel::addRow(const QString& field, const QString& op, const QString& value, const QString& property)
{
    Row r;
    r.widget = new QWidget(this);
    r.field = new QComboBox(r.widget);
    r.field->setMinimumContentsLength(6);
    r.field->setSizeAdjustPolicy(QComboBox::AdjustToMinimumContentsLengthWithIcon);
    for (const Choice& c : kFields)
        r.field->addItem(QCoreApplication::translate("kimbim::FindSelectPanel", c.label), QString::fromLatin1(c.key));
    r.field->setCurrentIndex(std::max(0, r.field->findData(field)));
    r.property = new QLineEdit(r.widget);
    r.property->setPlaceholderText(tr("Pset.Property"));
    r.property->setText(property);
    r.op = new QComboBox(r.widget);
    r.value = new QComboBox(r.widget);
    r.value->setMinimumContentsLength(8);
    r.value->setSizeAdjustPolicy(QComboBox::AdjustToMinimumContentsLengthWithIcon);
    auto* remove = new QToolButton(r.widget);
    remove->setText(QStringLiteral("×"));
    remove->setToolTip(tr("Remove this criterion"));
    // Two lines, as the panel is narrow: what and how, then the property name and the value.
    auto* v = new QVBoxLayout(r.widget);
    v->setContentsMargins(0, 0, 0, 6);
    v->setSpacing(2);
    auto* top = new QHBoxLayout;
    top->addWidget(r.field, 1);
    top->addWidget(r.op);
    top->addWidget(remove);
    auto* bottom = new QHBoxLayout;
    bottom->addWidget(r.property, 1);
    bottom->addWidget(r.value, 1);
    v->addLayout(top);
    v->addLayout(bottom);
    m_rowsLayout->insertWidget(m_rowsLayout->count() - 1, r.widget);
    m_rows.append(r);
    Row& row = m_rows.last();
    fillOps(row, op);
    fillValues(row, value);
    QWidget* key = r.widget;
    connect(r.field, qOverload<int>(&QComboBox::currentIndexChanged), this, [this, key] {
        for (Row& x : m_rows)
            if (x.widget == key) {
                fillOps(x, x.op->currentData().toString());
                fillValues(x, QString());
            }
    });
    connect(r.op, qOverload<int>(&QComboBox::currentIndexChanged), this, [this, key] {
        for (Row& x : m_rows)
            if (x.widget == key)
                x.value->setEnabled(needsValue(x.op->currentData().toString()));
    });
    connect(remove, &QToolButton::clicked, this, [this, key] { removeRow(key); });
}

void FindSelectPanel::removeRow(QWidget* rowWidget)
{
    for (int i = 0; i < m_rows.size(); ++i)
        if (m_rows[i].widget == rowWidget) {
            m_rows[i].widget->deleteLater();
            m_rows.removeAt(i);
            return;
        }
}

void FindSelectPanel::clearRows()
{
    for (Row& r : m_rows)
        delete r.widget;
    m_rows.clear();
}

void FindSelectPanel::fillOps(Row& row, const QString& keep)
{
    const QString field = row.field->currentData().toString();
    row.property->setVisible(field == QLatin1String("property"));
    row.op->blockSignals(true);
    row.op->clear();
    for (const QString& op : opsFor(field))
        for (const Choice& c : kOps)
            if (op == QLatin1String(c.key))
                row.op->addItem(QCoreApplication::translate("kimbim::FindSelectPanel", c.label), op);
    row.op->setCurrentIndex(std::max(0, row.op->findData(keep)));
    row.op->blockSignals(false);
    row.value->setEnabled(needsValue(row.op->currentData().toString()));
}

void FindSelectPanel::fillValues(Row& row, const QString& keep)
{
    const QString field = row.field->currentData().toString();
    QComboBox* v = row.value;
    v->blockSignals(true);
    v->clear();
    // Fixed lists (kind, level, status) carry their key as data; the others are free text with
    // suggestions from the model.
    const bool fixed = field == QLatin1String("kind") || field == QLatin1String("level") || field == QLatin1String("status");
    v->setEditable(!fixed);
    if (field == QLatin1String("kind")) {
        const QStringList kinds = strings(m_choices.value("kinds"));
        for (const QString& k : kinds.isEmpty() ? QStringList{"walls", "slabs", "doors", "windows"} : kinds)
            v->addItem(kindLabel(k), k);
    } else if (field == QLatin1String("status")) {
        for (const QString& s : renovationKeys())
            v->addItem(renovationLabel(s), s);
    } else if (field == QLatin1String("level")) {
        for (const auto& lv : m_choices.value("levels").toArray())
            v->addItem(lv.toObject().value("name").toString(), lv.toObject().value("guid").toString());
    } else {
        const char* key = field == QLatin1String("ifc_class") ? "classes"
            : field == QLatin1String("type")                  ? "types"
            : field == QLatin1String("layer")                 ? "layers"
            : field == QLatin1String("material")              ? "materials"
                                                              : nullptr;
        if (key)
            v->addItems(strings(m_choices.value(QLatin1String(key))));
    }
    if (fixed) {
        int i = v->findData(keep);
        if (i < 0)
            i = v->findText(keep);
        v->setCurrentIndex(std::max(0, i));
    } else {
        v->setCurrentText(keep);
    }
    v->blockSignals(false);
    if (field == QLatin1String("property")) { // the model's property names as you type
        auto* completer = new QCompleter(strings(m_choices.value("properties")), row.property);
        completer->setCaseSensitivity(Qt::CaseInsensitive);
        completer->setFilterMode(Qt::MatchContains);
        row.property->setCompleter(completer);
    }
}

QJsonObject FindSelectPanel::criteria() const
{
    QJsonArray rows;
    for (const Row& r : m_rows) {
        const QString field = r.field->currentData().toString(), op = r.op->currentData().toString();
        QJsonObject row{{"field", field}, {"op", op}};
        if (needsValue(op)) {
            const QString text = r.value->isEditable() ? r.value->currentText().trimmed() : r.value->currentData().toString();
            bool number = false;
            const double d = text.toDouble(&number);
            row.insert("value", (op == QLatin1String("less") || op == QLatin1String("more")) && number ? QJsonValue(d) : QJsonValue(text));
        }
        if (field == QLatin1String("property"))
            row.insert("property", r.property->text().trimmed());
        rows.append(row);
    }
    return {{"match", m_match->currentData().toString()}, {"rows", rows}};
}

void FindSelectPanel::setCriteria(const QJsonObject& criteria)
{
    clearRows();
    m_match->setCurrentIndex(std::max(0, m_match->findData(criteria.value("match").toString("all"))));
    for (const auto& v : criteria.value("rows").toArray()) {
        const QJsonObject r = v.toObject();
        const QJsonValue value = r.value("value");
        addRow(r.value("field").toString(), r.value("op").toString(QStringLiteral("equals")),
            value.isDouble() ? QString::number(value.toDouble()) : value.toString(), r.value("property").toString());
    }
}

QString FindSelectPanel::scope() const
{
    return m_scope->currentData().toString();
}

void FindSelectPanel::setScope(const QString& scope)
{
    m_scope->setCurrentIndex(std::max(0, m_scope->findData(scope)));
}

void FindSelectPanel::setResult(const QString& text)
{
    m_result->setText(text);
}

QString FindSelectPanel::result() const
{
    return m_result->text();
}

void FindSelectPanel::find(How how)
{
    QJsonObject query = criteria();
    query.insert("scope", scope());
    emit findRequested(query, how);
}

void FindSelectPanel::saveCriteria(const QString& name)
{
    if (name.isEmpty()) {
        setResult(tr("Type a name for the criteria set first"));
        return;
    }
    emit saveCriteriaRequested(name, criteria());
}

void FindSelectPanel::loadCriteria(const QString& name)
{
    if (!m_savedCriteria.contains(name))
        return;
    m_saved->setCurrentText(name);
    setCriteria(m_savedCriteria.value(name).toObject());
}

void FindSelectPanel::saveSet(const QString& name)
{
    if (name.isEmpty()) {
        setResult(tr("Type a name for the selection set first"));
        return;
    }
    emit saveSetRequested(name);
    m_setName->clear();
}

void FindSelectPanel::recallSet(const QString& name, How how)
{
    if (!name.isEmpty())
        emit recallSetRequested(name, how);
}

} // namespace kimbim
