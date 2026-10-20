// SPDX-License-Identifier: GPL-3.0-or-later
// D89: the window's side of the input aids: which tools get the tracker, the tools' own typed
// values, the guide actions, the scroll preference.
#include <QAction>
#include <QLineEdit>
#include <QLocale>
#include <QMenu>

#include "DraftTool.h"
#include "GripTool.h"
#include "InputAidsController.h"
#include "LevelsBar.h"
#include "MainWindow.h"
#include "MeasureController.h"
#include "ModifyTool.h"
#include "PolygonTool.h"
#include "RotateTool.h"
#include "StatusStrip.h"
#include "ToolOptionsBar.h"
#include "TwoPointTool.h"
#include "Viewport.h"
#include "WallTool.h"

namespace kimbim {

void MainWindow::setupInputAids()
{
    InputAidsController::Hooks hooks;
    hooks.active = [this] { return trackerTool(); };
    hooks.classic = [this](const Tracker& t) { return trackerClassic(t); };
    hooks.planZ = [this] { return m_levels->activeElevation(); };
    m_inputAids = new InputAidsController(std::move(hooks), this);
    for (Snapper* s : {&m_wallTool->snapper(), &m_polygonTool->snapper(), &m_twoPointTool->snapper(), &m_rotateTool->snapper(),
             &m_gripTool->snapper(), &m_measure->tool()->snapper(), &m_modifyTool->snapper(), &m_draftTool->snapper()})
        s->setAids(m_inputAids->aids());
    onEachView([this](Viewport* v) { m_inputAids->attach(v); });
    if (m_viewMenu) {
        m_viewMenu->addSeparator();
        QAction* guides = m_viewMenu->addAction(tr("Temporary &guides"));
        guides->setObjectName(QStringLiteral("actionGuides"));
        guides->setCheckable(true);
        guides->setChecked(true);
        guides->setShortcut(Qt::Key_F11);
        guides->setToolTip(tr("Rest the cursor on a snap point to draw guide lines through it (again: remove it)"));
        connect(guides, &QAction::toggled, m_inputAids, &InputAidsController::setGuidesEnabled);
        QAction* clear = m_viewMenu->addAction(tr("&Clear guides"));
        clear->setObjectName(QStringLiteral("actionClearGuides"));
        connect(clear, &QAction::triggered, m_inputAids, &InputAidsController::clearGuides);
    }
    Viewport::setScrollMode(Viewport::scrollModeFrom(m_prefs.scrollNavigation()));
}

bool MainWindow::trackerTool() const
{
    switch (m_tool) {
    case Tool::Wall:
    case Tool::Slab:
    case Tool::Roof:
    case Tool::SlabOpening:
    case Tool::Beam:
    case Tool::Grid:
    case Tool::Stair:
    case Tool::Column:
    case Tool::PlaceModel:
    case Tool::Text:
    case Tool::Dimension:
    case Tool::Mark:
    case Tool::Leader:
    case Tool::Mirror:
    case Tool::Section:
    case Tool::Elevation:
    case Tool::Move:
    case Tool::Rotate:
    case Tool::Stretch:
    case Tool::Measure:
    case Tool::Line:
    case Tool::Polyline:
    case Tool::ArcCircle:
    case Tool::Rectangle:
    case Tool::Fill:
    case Tool::Cloud:
    case Tool::NorthArrow:
    case Tool::ScaleBar:
    case Tool::AngleDimension:
    case Tool::RadialDimension:
    case Tool::LevelDimension:
        return true;
    default: // doors and windows slide along a wall; rooms, tags, split/trim/join pick elements
        return false;
    }
}

bool MainWindow::trackerClassic(const Tracker& t)
{
    if (m_tool == Tool::Rotate && m_rotateTool->stage() == 2) { // the rotation angle, whatever field took it
        for (const Tracker::Field f : {Tracker::Length, Tracker::Angle, Tracker::X, Tracker::Y})
            if (const auto v = t.value(f))
                return m_rotateTool->typeAngle(*v);
        return false;
    }
    // A lone length: the options bar's length field, as before the tracker (each tool's own meaning:
    // a wall along the mouse, a circle's radius, a stretched wall's new length...).
    if (!t.lengthOnly() || m_lengthInput->isHidden() || m_toolOptions->isHidden())
        return false;
    m_lengthInput->setText(QLocale().toString(*t.value(Tracker::Length), 'g', 12));
    emit m_lengthInput->returnPressed();
    if (m_lengthInput->text().isEmpty())
        return true;
    m_lengthInput->clear();
    return false;
}

} // namespace kimbim
