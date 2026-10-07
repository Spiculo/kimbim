// SPDX-License-Identifier: GPL-3.0-or-later
#include "DrawingsPanel.h"

#include <QHBoxLayout>
#include <QJsonObject>
#include <QListWidget>
#include <QPushButton>
#include <QVBoxLayout>

namespace kimcad {

namespace {
constexpr int GuidRole = Qt::UserRole;
}

DrawingsPanel::DrawingsPanel(QWidget* parent)
    : QWidget(parent)
    , m_list(new QListWidget(this))
    , m_open(new QPushButton(tr("Open"), this))
    , m_rename(new QPushButton(tr("Rename"), this))
    , m_delete(new QPushButton(tr("Delete"), this))
{
    m_list->setObjectName(QStringLiteral("drawingsList"));
    m_list->setToolTip(tr("Double-click a drawing to open it"));
    auto* buttons = new QHBoxLayout;
    buttons->addWidget(m_open);
    buttons->addWidget(m_rename);
    buttons->addWidget(m_delete);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(2, 2, 2, 2);
    layout->addWidget(m_list, 1);
    layout->addLayout(buttons);

    connect(m_list, &QListWidget::itemDoubleClicked, this,
        [this](QListWidgetItem* item) { emit openRequested(item->data(GuidRole).toString()); });
    connect(m_open, &QPushButton::clicked, this, [this] {
        if (!selectedDrawing().isEmpty())
            emit openRequested(selectedDrawing());
    });
    connect(m_rename, &QPushButton::clicked, this, [this] {
        if (QListWidgetItem* item = m_list->currentItem())
            m_list->editItem(item);
    });
    connect(m_list, &QListWidget::itemChanged, this, [this](QListWidgetItem* item) {
        if (!m_filling)
            emit renameRequested(item->data(GuidRole).toString(), item->text().trimmed());
    });
    connect(m_delete, &QPushButton::clicked, this, [this] {
        if (!selectedDrawing().isEmpty())
            emit deleteRequested(selectedDrawing());
    });
}

void DrawingsPanel::setDrawings(const QJsonArray& drawings)
{
    m_filling = true;
    const QString current = selectedDrawing();
    m_list->clear();
    for (const auto& v : drawings) {
        const QJsonObject d = v.toObject();
        auto* item = new QListWidgetItem(d.value("name").toString(), m_list);
        item->setData(GuidRole, d.value("guid").toString());
        item->setFlags(item->flags() | Qt::ItemIsEditable);
        item->setToolTip(d.value("kind").toString() == QLatin1String("section") ? tr("Section") : tr("Elevation"));
        if (item->data(GuidRole).toString() == current)
            m_list->setCurrentItem(item);
    }
    m_filling = false;
}

QString DrawingsPanel::selectedDrawing() const
{
    const QListWidgetItem* item = m_list->currentItem();
    return item ? item->data(GuidRole).toString() : QString();
}

int DrawingsPanel::count() const
{
    return m_list->count();
}

} // namespace kimcad
