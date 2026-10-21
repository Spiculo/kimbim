// SPDX-License-Identifier: GPL-3.0-or-later
#include "LevelsBar.h"

#include <QComboBox>
#include <QHBoxLayout>
#include <QJsonObject>
#include <QAction>
#include <QMenu>
#include <QLocale>
#include <QToolButton>

#include <algorithm>

namespace kimbim {

namespace {
enum Role { GuidRole = Qt::UserRole, ElevationRole, ModelRole, WorksheetRole };
} // namespace

LevelsBar::LevelsBar(QWidget* parent)
    : QWidget(parent)
    , m_combo(new QComboBox(this))
    , m_menu(new QToolButton(this))
    , m_add(new QAction(tr("Add level..."), this))
    , m_newModel(new QAction(tr("New model..."), this))
    , m_newWorksheet(new QAction(tr("New worksheet..."), this))
    , m_levels(new QAction(tr("&Levels..."), this))
{
    m_combo->setObjectName(QStringLiteral("levelCombo"));
    m_combo->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    m_combo->setToolTip(tr("Active level"));
    m_add->setObjectName(QStringLiteral("actionAddLevel"));
    m_newModel->setObjectName(QStringLiteral("actionNewModel"));
    m_levels->setObjectName(QStringLiteral("actionLevels"));
    m_levels->setToolTip(tr("The levels table: names, elevations, heights; insert and delete levels"));
    m_newModel->setToolTip(tr("A model is a unit (an apartment, a core...) drawn once and placed on many levels"));
    m_newWorksheet->setObjectName(QStringLiteral("actionNewWorksheet"));
    m_newWorksheet->setToolTip(tr("A worksheet is a 2D drawing space for details, sketches and pictures (D98)"));
    auto* menu = new QMenu(m_menu);
    menu->addAction(m_add);
    menu->addAction(m_levels);
    menu->addAction(m_newModel);
    menu->addAction(m_newWorksheet);
    m_menu->setObjectName(QStringLiteral("levelMenu"));
    m_menu->setToolTip(tr("Levels and models"));
    m_menu->setAutoRaise(true);
    m_menu->setArrowType(Qt::DownArrow);
    m_menu->setPopupMode(QToolButton::InstantPopup);
    m_menu->setStyleSheet(QStringLiteral("QToolButton::menu-indicator { image: none; width: 0; }"));
    m_menu->setMenu(menu);
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    layout->addWidget(m_combo);
    layout->addWidget(m_menu);
    connect(m_newModel, &QAction::triggered, this, &LevelsBar::newModelRequested);
    connect(m_newWorksheet, &QAction::triggered, this, &LevelsBar::newWorksheetRequested);
    connect(m_combo, &QComboBox::currentIndexChanged, this, &LevelsBar::onIndexChanged);
    connect(m_add, &QAction::triggered, this, &LevelsBar::addLevelRequested);
    connect(m_levels, &QAction::triggered, this, &LevelsBar::levelsDialogRequested);
}

void LevelsBar::setStoreys(const QJsonArray& storeys)
{
    QList<QJsonObject> sorted;
    for (const auto& s : storeys)
        sorted << s.toObject();
    // levels first (by elevation), then models, then worksheets (D98), each by name
    auto group = [](const QJsonObject& s) { return s.value("worksheet").toBool() ? 2 : s.value("model").toBool() ? 1 : 0; };
    std::stable_sort(sorted.begin(), sorted.end(), [&group](const QJsonObject& a, const QJsonObject& b) {
        const int ga = group(a), gb = group(b);
        if (ga != gb)
            return ga < gb;
        return ga ? a.value("name").toString().localeAwareCompare(b.value("name").toString()) < 0
                  : a.value("elevation").toDouble() < b.value("elevation").toDouble();
    });
    m_filling = true;
    m_combo->clear();
    int keep = -1;
    int section = 0;
    for (const auto& s : sorted) {
        if (!s.value("show").toBool(true) && s.value("guid").toString() != m_active)
            continue; // D79: not shown in the level list
        const double elevation = s.value("elevation").toDouble();
        const bool model = s.value("model").toBool();
        const bool worksheet = s.value("worksheet").toBool();
        if (group(s) > section) {
            m_combo->insertSeparator(m_combo->count());
            section = group(s);
        }
        m_combo->addItem(worksheet ? tr("Worksheet: %1").arg(s.value("name").toString())
                : model ? tr("Model: %1").arg(s.value("name").toString())
                        : QStringLiteral("%1 (%2 m)").arg(s.value("name").toString(), QLocale().toString(elevation, 'f', 2)));
        m_combo->setItemData(m_combo->count() - 1, worksheet, WorksheetRole);
        m_combo->setItemData(m_combo->count() - 1, s.value("guid").toString(), GuidRole);
        m_combo->setItemData(m_combo->count() - 1, elevation, ElevationRole);
        m_combo->setItemData(m_combo->count() - 1, model, ModelRole);
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
    int n = 0;
    for (int i = 0; i < m_combo->count(); ++i)
        n += m_combo->itemData(i, GuidRole).isValid() ? 1 : 0;
    return n;
}

bool LevelsBar::activeIsModel() const
{
    return m_combo->currentData(ModelRole).toBool();
}

bool LevelsBar::activeIsWorksheet() const
{
    return m_combo->currentData(WorksheetRole).toBool();
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

} // namespace kimbim
