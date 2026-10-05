// SPDX-License-Identifier: GPL-3.0-or-later
#include "LevelsBar.h"

#include <QComboBox>
#include <QHBoxLayout>
#include <QJsonObject>
#include <QLabel>
#include <QLocale>
#include <QToolButton>

#include <algorithm>

namespace kimcad {

namespace {
enum Role { GuidRole = Qt::UserRole, ElevationRole };
} // namespace

LevelsBar::LevelsBar(QWidget* parent)
    : QWidget(parent)
    , m_combo(new QComboBox(this))
    , m_add(new QToolButton(this))
{
    m_combo->setObjectName(QStringLiteral("levelCombo"));
    m_combo->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    m_add->setText(tr("Add level..."));
    m_add->setObjectName(QStringLiteral("addLevel"));
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(4, 0, 4, 0);
    layout->addWidget(new QLabel(tr("Level"), this));
    layout->addWidget(m_combo);
    layout->addWidget(m_add);
    connect(m_combo, &QComboBox::currentIndexChanged, this, &LevelsBar::onIndexChanged);
    connect(m_add, &QToolButton::clicked, this, &LevelsBar::addLevelRequested);
}

void LevelsBar::setStoreys(const QJsonArray& storeys)
{
    QList<QJsonObject> sorted;
    for (const auto& s : storeys)
        sorted << s.toObject();
    std::stable_sort(sorted.begin(), sorted.end(), [](const QJsonObject& a, const QJsonObject& b) {
        return a.value("elevation").toDouble() < b.value("elevation").toDouble();
    });
    m_filling = true;
    m_combo->clear();
    int keep = -1;
    for (const auto& s : sorted) {
        const double elevation = s.value("elevation").toDouble();
        m_combo->addItem(QStringLiteral("%1 (%2 m)").arg(s.value("name").toString(), QLocale().toString(elevation, 'f', 2)));
        m_combo->setItemData(m_combo->count() - 1, s.value("guid").toString(), GuidRole);
        m_combo->setItemData(m_combo->count() - 1, elevation, ElevationRole);
        if (s.value("guid").toString() == m_active)
            keep = m_combo->count() - 1;
    }
    m_combo->setCurrentIndex(keep >= 0 ? keep : (m_combo->count() ? 0 : -1));
    m_filling = false;
    if (keep < 0) // the active level is new or gone: announce the replacement
        onIndexChanged(m_combo->currentIndex());
}

void LevelsBar::setActive(const QString& guid)
{
    const int index = m_combo->findData(guid, GuidRole);
    if (index >= 0)
        m_combo->setCurrentIndex(index);
}

QString LevelsBar::activeStorey() const
{
    return m_combo->currentData(GuidRole).toString();
}

double LevelsBar::activeElevation() const
{
    return m_combo->currentData(ElevationRole).toDouble();
}

int LevelsBar::count() const
{
    return m_combo->count();
}

void LevelsBar::onIndexChanged(int index)
{
    if (m_filling)
        return;
    const QString guid = index >= 0 ? m_combo->itemData(index, GuidRole).toString() : QString();
    if (guid == m_active && !guid.isEmpty())
        return;
    m_active = guid;
    emit activeStoreyChanged(guid, index >= 0 ? m_combo->itemData(index, ElevationRole).toDouble() : 0.0);
}

} // namespace kimcad
