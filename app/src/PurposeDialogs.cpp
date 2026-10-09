// SPDX-License-Identifier: GPL-3.0-or-later
// The Graphics menu's layer combinations and purposes editors (D73).
#include "GraphicsDialogs.h"

#include <QCheckBox>
#include <QComboBox>
#include <QFormLayout>
#include <QHeaderView>
#include <QJsonArray>
#include <QLabel>
#include <QPushButton>
#include <QTableWidget>
#include <QVBoxLayout>

namespace kimcad {

// ---------------- LayerCombinationsDialog ----------------

LayerCombinationsDialog::LayerCombinationsDialog(const QJsonObject& reply, const QStringList& layers,
    const QStringList& hidden, const QStringList& locked, QWidget* parent)
    : NamedSetsDialog(reply, QStringLiteral("layer_combinations"), QStringLiteral("layers"), parent)
    , m_layers(layers)
    , m_hiddenNow(hidden)
    , m_lockedNow(locked)
{
    setWindowTitle(tr("Layer combinations"));
    buildPicker();
    m_states = new QTableWidget(int(layers.size()), 3, this);
    m_states->setObjectName(QStringLiteral("layerStates"));
    m_states->setHorizontalHeaderLabels({tr("Layer"), tr("Shown"), tr("Locked")});
    m_states->verticalHeader()->hide();
    m_states->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_layout->addWidget(m_states);
    auto* current = new QPushButton(tr("From current layers"), this);
    current->setObjectName(QStringLiteral("fromCurrent"));
    m_layout->addWidget(current);
    m_layout->addWidget(new QLabel(tr("A purpose can switch to a layer combination (Graphics > Purposes)."), this));
    finishLayout();
    resize(460, 480);
    connect(current, &QPushButton::clicked, this, &LayerCombinationsDialog::takeCurrent);
    selectSet(table(m_key).keys().value(0));
}

void LayerCombinationsDialog::setIn(const QString& list, const QString& layer, bool in)
{
    QJsonObject combo = currentValue();
    QStringList names;
    for (const auto& v : combo.value(list).toArray())
        names << v.toString();
    names.removeAll(layer);
    if (in)
        names << layer;
    names.sort();
    combo.insert(list, QJsonArray::fromStringList(names));
    for (const char* other : {"hidden", "locked"})
        if (!combo.contains(QLatin1String(other)))
            combo.insert(QLatin1String(other), QJsonArray());
    setCurrentValue(combo);
    showSet(currentSet());
}

void LayerCombinationsDialog::setShown(const QString& layer, bool shown)
{
    setIn(QStringLiteral("hidden"), layer, !shown);
}

void LayerCombinationsDialog::setLocked(const QString& layer, bool locked)
{
    setIn(QStringLiteral("locked"), layer, locked);
}

void LayerCombinationsDialog::takeCurrent()
{
    QStringList hidden = m_hiddenNow, locked = m_lockedNow;
    hidden.sort();
    locked.sort();
    setCurrentValue(QJsonObject{{"hidden", QJsonArray::fromStringList(hidden)}, {"locked", QJsonArray::fromStringList(locked)}});
    showSet(currentSet());
}

void LayerCombinationsDialog::showSet(const QString&)
{
    if (!m_states)
        return;
    const QJsonObject combo = currentValue();
    const QJsonArray hidden = combo.value("hidden").toArray(), locked = combo.value("locked").toArray();
    m_loading = true;
    for (int r = 0; r < m_layers.size(); ++r) {
        const QString layer = m_layers[r];
        auto* name = new QTableWidgetItem(layer);
        name->setFlags(name->flags() & ~Qt::ItemIsEditable);
        m_states->setItem(r, 0, name);
        auto box = [&](int col, bool on, bool shownColumn) {
            auto* b = new QCheckBox(m_states);
            b->setChecked(on);
            connect(b, &QCheckBox::toggled, this, [this, layer, shownColumn](bool v) {
                if (m_loading)
                    return;
                // after this click: the table's boxes are rebuilt
                QMetaObject::invokeMethod(this, [this, layer, shownColumn, v] {
                    shownColumn ? setShown(layer, v) : setLocked(layer, v);
                }, Qt::QueuedConnection);
            });
            m_states->setCellWidget(r, col, b);
        };
        box(1, !hidden.contains(layer), true);
        box(2, locked.contains(layer), false);
    }
    m_loading = false;
}

// ---------------- PurposesDialog ----------------

PurposesDialog::PurposesDialog(const QJsonObject& reply, QWidget* parent)
    : NamedSetsDialog(reply, QStringLiteral("purposes"), QString(), parent)
{
    setWindowTitle(tr("Purposes"));
    buildPicker();
    auto* form = new QFormLayout;
    auto combo = [&](const char* name, const QStringList& items, bool none) {
        auto* c = new QComboBox(this);
        c->setObjectName(QLatin1String(name));
        if (none)
            c->addItem(tr("(keep the layers as they are)"), QString());
        for (const QString& i : items)
            c->addItem(i, i);
        connect(c, &QComboBox::currentIndexChanged, this, [this] {
            if (!m_loading)
                setPieces(m_penSet->currentData().toString(), m_visibility->currentData().toString(),
                    m_overrides->currentData().toString(), m_layers->currentData().toString(),
                    m_renovation->currentData().toString());
        });
        return c;
    };
    m_penSet = combo("penSetOf", table("pen_sets").keys(), false);
    m_visibility = combo("visibilityOf", table("visibility_sets").keys(), false);
    m_overrides = combo("overridesOf", table("override_sets").keys(), false);
    m_layers = combo("layersOf", table("layer_combinations").keys(), true);
    m_renovation = combo("renovationOf", table("renovation_filters").keys(), false);
    form->addRow(tr("Pen set:"), m_penSet);
    form->addRow(tr("Visibility set:"), m_visibility);
    form->addRow(tr("Graphic overrides:"), m_overrides);
    form->addRow(tr("Layer combination:"), m_layers);
    form->addRow(tr("Renovation filter:"), m_renovation);
    m_layout->addLayout(form);
    m_layout->addWidget(new QLabel(tr("Pick the purpose in the bottom bar: it restyles the views, drawings and sheets."), this));
    finishLayout();
    selectSet(reply.value("purpose").toString());
}

void PurposesDialog::setPieces(const QString& penSet, const QString& visibility, const QString& overrides, const QString& layers,
    const QString& renovation)
{
    const QString keep = currentValue().value("renovation").toString(QStringLiteral("Everything"));
    setCurrentValue(QJsonObject{{"pen_set", penSet}, {"visibility", visibility}, {"overrides", overrides},
        {"layers", layers.isEmpty() ? QJsonValue() : QJsonValue(layers)},
        {"renovation", renovation.isEmpty() ? keep : renovation}});
    showSet(currentSet());
}

void PurposesDialog::showSet(const QString&)
{
    if (!m_penSet)
        return;
    const QJsonObject p = currentValue();
    m_loading = true;
    auto pick = [](QComboBox* c, const QString& value) { c->setCurrentIndex(std::max(0, c->findData(value))); };
    pick(m_penSet, p.value("pen_set").toString());
    pick(m_visibility, p.value("visibility").toString());
    pick(m_overrides, p.value("overrides").toString());
    pick(m_layers, p.value("layers").toString());
    pick(m_renovation, p.value("renovation").toString(QStringLiteral("Everything")));
    m_loading = false;
}

} // namespace kimcad
