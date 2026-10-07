// SPDX-License-Identifier: GPL-3.0-or-later
#include "HistoryPanel.h"

#include <QDateTime>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QListWidget>
#include <QPushButton>
#include <QTreeWidget>
#include <QVBoxLayout>

namespace kimcad {

namespace {
constexpr int IdRole = Qt::UserRole;
constexpr int GuidRole = Qt::UserRole + 1;
} // namespace

HistoryPanel::HistoryPanel(QWidget* parent)
    : QWidget(parent)
    , m_versions(new QListWidget(this))
    , m_changes(new QTreeWidget(this))
    , m_compareCurrent(new QPushButton(tr("Compare with current"), this))
    , m_compareTwo(new QPushButton(tr("Compare the two selected"), this))
    , m_end(new QPushButton(tr("End compare"), this))
    , m_legend(new QLabel(this))
{
    m_versions->setObjectName(QStringLiteral("versionList"));
    m_versions->setSelectionMode(QAbstractItemView::ExtendedSelection);
    m_changes->setObjectName(QStringLiteral("changeList"));
    m_changes->setHeaderLabels({tr("Change"), tr("Type")});
    m_changes->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_legend->setText(QStringLiteral("<span style='color:%1'>&#9632;</span> %2 &nbsp; <span style='color:%3'>&#9632;</span> %4")
                          .arg(addedColor().name(), tr("added"), modifiedColor().name(), tr("modified")));
    auto* buttons = new QHBoxLayout;
    buttons->addWidget(m_compareCurrent);
    buttons->addWidget(m_compareTwo);
    buttons->addWidget(m_end);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->addWidget(new QLabel(tr("Versions"), this));
    layout->addWidget(m_versions, 2);
    layout->addLayout(buttons);
    layout->addWidget(m_legend);
    layout->addWidget(m_changes, 3);

    connect(m_versions, &QListWidget::itemSelectionChanged, this, &HistoryPanel::updateButtons);
    connect(m_compareCurrent, &QPushButton::clicked, this, [this] {
        const auto items = m_versions->selectedItems();
        if (items.size() == 1)
            emit compareRequested(items.first()->data(IdRole).toString(), QStringLiteral("WORKING"));
    });
    connect(m_compareTwo, &QPushButton::clicked, this, [this] {
        auto items = m_versions->selectedItems();
        if (items.size() != 2)
            return;
        // Newest first in the list: the lower row is the older version.
        if (m_versions->row(items[0]) < m_versions->row(items[1]))
            std::swap(items[0], items[1]);
        emit compareRequested(items[0]->data(IdRole).toString(), items[1]->data(IdRole).toString());
    });
    connect(m_end, &QPushButton::clicked, this, &HistoryPanel::endCompareRequested);
    connect(m_changes, &QTreeWidget::itemActivated, this, [this](QTreeWidgetItem* item) {
        const QString guid = item->data(0, GuidRole).toString();
        if (!guid.isEmpty())
            emit elementActivated(guid);
    });
    setChanges({});
}

void HistoryPanel::setVersions(const QJsonArray& versions)
{
    m_versions->clear();
    for (const auto& v : versions) {
        const QJsonObject o = v.toObject();
        const QString when = QLocale().toString(QDateTime::fromSecsSinceEpoch(o.value("time").toInteger()), QLocale::ShortFormat);
        auto* item = new QListWidgetItem(QStringLiteral("%1\n%2 · %3 · %4")
                                             .arg(o.value("message").toString().section(QLatin1Char('\n'), 0, 0),
                                                 o.value("author").toString(), when, o.value("short").toString()),
            m_versions);
        item->setData(IdRole, o.value("id").toString());
        item->setToolTip(o.value("message").toString());
    }
    updateButtons();
}

void HistoryPanel::setChanges(const QJsonObject& compare)
{
    m_changes->clear();
    m_changeCount = 0;
    const bool comparing = !compare.isEmpty();
    m_legend->setVisible(comparing);
    m_end->setEnabled(comparing);
    if (!comparing)
        return;
    const struct {
        const char* key;
        QString title;
        QColor color;
    } groups[] = {{"added", tr("Added"), addedColor()}, {"modified", tr("Modified"), modifiedColor()},
        {"removed", tr("Removed"), QColor(150, 150, 150)}};
    for (const auto& group : groups) {
        const QJsonArray items = compare.value(QLatin1String(group.key)).toArray();
        auto* top = new QTreeWidgetItem(m_changes, {QStringLiteral("%1 (%2)").arg(group.title).arg(items.size())});
        top->setForeground(0, group.color);
        for (const auto& v : items) {
            const QJsonObject o = v.toObject();
            const QString name = o.value("name").toString();
            auto* item = new QTreeWidgetItem(top, {name.isEmpty() ? o.value("guid").toString() : name, o.value("type").toString()});
            item->setData(0, GuidRole, o.value("guid").toString());
            ++m_changeCount;
        }
        top->setExpanded(items.size() <= 50);
    }
    if (const int other = compare.value("other").toInt())
        new QTreeWidgetItem(m_changes, {tr("%n other record(s) (relationships, shared data)", nullptr, other)});
}

void HistoryPanel::updateButtons()
{
    const int selected = int(m_versions->selectedItems().size());
    m_compareCurrent->setEnabled(selected == 1);
    m_compareTwo->setEnabled(selected == 2);
}

} // namespace kimcad
