// SPDX-License-Identifier: GPL-3.0-or-later
#include "SheetsPanel.h"

#include <QHBoxLayout>
#include <QJsonObject>
#include <QListWidget>
#include <QMenu>
#include <QPushButton>
#include <QVBoxLayout>

namespace kimcad {

namespace {
constexpr int NumberRole = Qt::UserRole;
}

SheetsPanel::SheetsPanel(QWidget* parent)
    : QWidget(parent)
    , m_list(new QListWidget(this))
{
    m_list->setObjectName(QStringLiteral("sheetsList"));
    m_list->setToolTip(tr("Double-click a sheet to open it"));
    auto* add = new QPushButton(tr("New"), this);
    auto* menu = new QMenu(add);
    menu->addAction(tr("A1 sheet"), this, [this] { emit newRequested(QStringLiteral("A1")); });
    menu->addAction(tr("A3 sheet"), this, [this] { emit newRequested(QStringLiteral("A3")); });
    add->setMenu(menu);
    auto* place = new QPushButton(tr("Place drawing"), this);
    place->setToolTip(tr("Place the drawing selected in the Drawings panel on this sheet"));
    auto* open = new QPushButton(tr("Open"), this);
    auto* remove = new QPushButton(tr("Delete"), this);
    auto* buttons = new QHBoxLayout;
    for (QPushButton* b : {add, place, open, remove})
        buttons->addWidget(b);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(2, 2, 2, 2);
    layout->addWidget(m_list, 1);
    layout->addLayout(buttons);
    connect(m_list, &QListWidget::itemDoubleClicked, this,
        [this](QListWidgetItem* item) { emit openRequested(item->data(NumberRole).toString()); });
    connect(open, &QPushButton::clicked, this, [this] {
        if (!selectedSheet().isEmpty())
            emit openRequested(selectedSheet());
    });
    connect(place, &QPushButton::clicked, this, [this] {
        if (!selectedSheet().isEmpty())
            emit placeRequested(selectedSheet());
    });
    connect(remove, &QPushButton::clicked, this, [this] {
        if (!selectedSheet().isEmpty())
            emit deleteRequested(selectedSheet());
    });
}

void SheetsPanel::setSheets(const QJsonArray& sheets)
{
    const QString current = selectedSheet();
    m_list->clear();
    for (const auto& v : sheets) {
        const QJsonObject s = v.toObject();
        auto* item = new QListWidgetItem(QStringLiteral("%1  %2  (%3)").arg(s.value("number").toString(),
            s.value("title").toString(), s.value("paper").toString()), m_list);
        item->setData(NumberRole, s.value("number").toString());
        if (s.value("number").toString() == current)
            m_list->setCurrentItem(item);
    }
    if (!m_list->currentItem() && m_list->count())
        m_list->setCurrentRow(0);
}

QString SheetsPanel::selectedSheet() const
{
    const QListWidgetItem* item = m_list->currentItem();
    return item ? item->data(NumberRole).toString() : QString();
}

int SheetsPanel::count() const
{
    return m_list->count();
}

} // namespace kimcad
