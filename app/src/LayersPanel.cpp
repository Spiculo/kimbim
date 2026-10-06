// SPDX-License-Identifier: GPL-3.0-or-later
#include "LayersPanel.h"

#include <QComboBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QJsonObject>
#include <QLabel>
#include <QPushButton>
#include <QTreeWidget>
#include <QVBoxLayout>

namespace kimcad {

namespace {
enum Column { NameCol = 0, ShownCol = 1, LockedCol = 2, CountCol = 3 };
constexpr int NameRole = Qt::UserRole;
} // namespace

LayersPanel::LayersPanel(QWidget* parent)
    : QWidget(parent)
    , m_list(new QTreeWidget(this))
    , m_views(new QComboBox(this))
{
    m_list->setObjectName(QStringLiteral("layerList"));
    m_list->setRootIsDecorated(false);
    m_list->setHeaderLabels({tr("Layer"), tr("Shown"), tr("Locked"), tr("Elements")});
    m_list->header()->setSectionResizeMode(NameCol, QHeaderView::Stretch);
    for (int c : {ShownCol, LockedCol, CountCol})
        m_list->header()->setSectionResizeMode(c, QHeaderView::ResizeToContents);
    m_list->setToolTip(tr("Double-click a layer to make it active: new elements go on it"));

    auto button = [this](const QString& text, const QString& tip) {
        auto* b = new QPushButton(text, this);
        b->setToolTip(tip);
        return b;
    };
    QPushButton* add = button(tr("New"), tr("New layer"));
    QPushButton* remove = button(tr("Delete"), tr("Delete the selected layer (its elements stay, without a layer)"));
    QPushButton* assign = button(tr("Move selection here"), tr("Put the selected elements on this layer"));
    QPushButton* active = button(tr("Make active"), tr("New elements go on this layer"));
    auto* layerButtons = new QHBoxLayout;
    for (QPushButton* b : {add, remove, assign, active})
        layerButtons->addWidget(b);

    m_views->setObjectName(QStringLiteral("viewCombo"));
    QPushButton* saveView = button(tr("Save view..."), tr("Save the current layer states, level, plan/3D and cut as a view"));
    QPushButton* deleteView = button(tr("Delete view"), tr("Delete the chosen view"));
    auto* viewRow = new QHBoxLayout;
    viewRow->addWidget(new QLabel(tr("View"), this));
    viewRow->addWidget(m_views, 1);
    viewRow->addWidget(saveView);
    viewRow->addWidget(deleteView);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addLayout(viewRow);
    layout->addWidget(m_list, 1);
    layout->addLayout(layerButtons);

    connect(m_list, &QTreeWidget::itemChanged, this, &LayersPanel::onItemChanged);
    connect(m_list, &QTreeWidget::itemDoubleClicked, this, [this](QTreeWidgetItem* item, int column) {
        if (column == NameCol)
            emit activeRequested(item->data(NameCol, NameRole).toString());
    });
    connect(add, &QPushButton::clicked, this, &LayersPanel::createRequested);
    connect(remove, &QPushButton::clicked, this, [this] {
        if (!selectedLayer().isEmpty())
            emit deleteRequested(selectedLayer());
    });
    connect(assign, &QPushButton::clicked, this, [this] {
        if (!selectedLayer().isEmpty())
            emit assignRequested(selectedLayer());
    });
    connect(active, &QPushButton::clicked, this, [this] {
        if (!selectedLayer().isEmpty())
            emit activeRequested(selectedLayer());
    });
    connect(m_views, &QComboBox::activated, this, [this](int index) {
        if (index > 0)
            emit viewRequested(m_views->itemText(index));
    });
    connect(saveView, &QPushButton::clicked, this, &LayersPanel::saveViewRequested);
    connect(deleteView, &QPushButton::clicked, this, [this] {
        if (m_views->currentIndex() > 0)
            emit deleteViewRequested(m_views->currentText());
    });
}

void LayersPanel::setLayers(const QJsonArray& layers, const QString& active, const QSet<QString>& hidden,
    const QSet<QString>& locked)
{
    const QString keep = selectedLayer();
    m_filling = true;
    m_list->clear();
    for (const auto& v : layers) {
        const QJsonObject o = v.toObject();
        const QString name = o.value("name").toString();
        auto* item = new QTreeWidgetItem(m_list);
        item->setText(NameCol, name == active ? tr("%1 (active)").arg(name) : name);
        item->setData(NameCol, NameRole, name);
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable | Qt::ItemIsEditable);
        item->setCheckState(ShownCol, hidden.contains(name) ? Qt::Unchecked : Qt::Checked);
        item->setCheckState(LockedCol, locked.contains(name) ? Qt::Checked : Qt::Unchecked);
        item->setText(CountCol, QString::number(o.value("count").toInt()));
        if (name == active) {
            QFont bold = item->font(NameCol);
            bold.setBold(true);
            item->setFont(NameCol, bold);
        }
        if (name == keep)
            m_list->setCurrentItem(item);
    }
    m_filling = false;
}

void LayersPanel::setViews(const QStringList& names, const QString& current)
{
    const QSignalBlocker block(m_views);
    m_views->clear();
    m_views->addItem(tr("(choose a view)"));
    m_views->addItems(names);
    const int index = m_views->findText(current);
    m_views->setCurrentIndex(index > 0 ? index : 0);
}

QString LayersPanel::selectedLayer() const
{
    const QTreeWidgetItem* item = m_list->currentItem();
    return item ? item->data(NameCol, NameRole).toString() : QString();
}

void LayersPanel::onItemChanged(QTreeWidgetItem* item, int column)
{
    if (m_filling)
        return;
    const QString name = item->data(NameCol, NameRole).toString();
    if (column == ShownCol)
        emit visibilityToggled(name, item->checkState(ShownCol) == Qt::Checked);
    else if (column == LockedCol)
        emit lockToggled(name, item->checkState(LockedCol) == Qt::Checked);
    else if (column == NameCol) {
        const QString typed = item->text(NameCol).trimmed();
        if (!typed.isEmpty() && typed != name && !typed.endsWith(tr("(active)")))
            emit renameRequested(name, typed);
    }
}

} // namespace kimcad
