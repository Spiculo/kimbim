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
    m_list->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(m_list, &QListWidget::customContextMenuRequested, this, [this](const QPoint& at) {
        const QListWidgetItem* item = m_list->itemAt(at);
        if (!item)
            return;
        QMenu menu(this);
        const QString number = item->data(NumberRole).toString();
        QMenu* purposes = purposeMenu(number);
        purposes->setParent(&menu, purposes->windowFlags());
        menu.addMenu(purposes);
        menu.addAction(tr("Place legend"), this, [this, number] { emit legendRequested(number); });
        menu.addAction(tr("Place north arrow"), this, [this, number] { emit symbolRequested(number, QStringLiteral("north")); });
        menu.addAction(tr("Place scale bar"), this, [this, number] { emit symbolRequested(number, QStringLiteral("scalebar")); });
        menu.addAction(tr("Place revision cloud"), this, [this, number] { emit symbolRequested(number, QStringLiteral("cloud")); });
        menu.exec(m_list->viewport()->mapToGlobal(at));
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

void SheetsPanel::setPurposes(const QStringList& names, const QJsonObject& sheetPurposes)
{
    m_purposes = names;
    m_sheetPurposes = sheetPurposes;
}

QMenu* SheetsPanel::purposeMenu(const QString& number)
{
    auto* menu = new QMenu(tr("Purpose"));
    const QString current = m_sheetPurposes.value(number).toString();
    QAction* follow = menu->addAction(tr("Current (as the views)"));
    follow->setCheckable(true);
    follow->setChecked(current.isEmpty());
    connect(follow, &QAction::triggered, this, [this, number] { emit purposeRequested(number, QString()); });
    menu->addSeparator();
    for (const QString& p : std::as_const(m_purposes)) {
        QAction* a = menu->addAction(p);
        a->setCheckable(true);
        a->setChecked(p == current);
        connect(a, &QAction::triggered, this, [this, number, p] { emit purposeRequested(number, p); });
    }
    return menu;
}

} // namespace kimcad
