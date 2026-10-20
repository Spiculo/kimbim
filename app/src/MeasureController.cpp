// SPDX-License-Identifier: GPL-3.0-or-later
#include "MeasureController.h"

#include <QClipboard>
#include <QGuiApplication>

#include "MeasureOverlay.h"
#include "Viewport.h"

namespace kimbim {

MeasureController::MeasureController(std::function<QString(double)> length, std::function<QString(double)> area, QObject* parent)
    : QObject(parent)
    , m_length(std::move(length))
    , m_area(std::move(area))
{
    connect(&m_tool, &MeasureTool::changed, this, &MeasureController::redraw);
}

void MeasureController::pointer(Viewport* view, QPointF p, double z, double tolerance, bool ortho, bool click)
{
    if (view != m_view) { // the path is drawn in the view being measured in
        if (m_view)
            m_view->setToolOverlay({});
        m_view = view;
    }
    m_tool.setTolerance(tolerance);
    m_tool.setOrtho(ortho);
    std::optional<MeasurePoint> surface;
    gp_Pnt hit;
    if (view && !view->isPlanView() && view->surfacePointAt(view->pointerPos(), &hit))
        surface = MeasurePoint{hit.X(), hit.Y(), hit.Z()};
    if (click)
        m_tool.click(p, z, surface);
    else
        m_tool.move(p, z, surface);
}

void MeasureController::stop()
{
    const QSignalBlocker quiet(&m_tool);
    m_tool.clear();
    if (m_view)
        m_view->setToolOverlay({});
    m_view.clear();
}

QString MeasureController::text() const
{
    return MeasureTool::describe(m_tool.readout(), m_length, m_area);
}

void MeasureController::copyToClipboard() const
{
    if (QClipboard* c = QGuiApplication::clipboard())
        c->setText(text());
}

void MeasureController::redraw()
{
    emit message(text());
    if (!m_view)
        return;
    const QVector<MeasurePoint> path = m_tool.path();
    if (path.isEmpty()) {
        m_view->setToolOverlay({});
        return;
    }
    const MeasureReadout r = m_tool.readout();
    QString label;
    if (r.points >= 2) {
        label = m_length(r.distance);
        if (r.area) // D92: the project's area unit when the app supplies one
            label += QStringLiteral("  ") + (m_area ? m_area(*r.area)
                                                    : tr("%1 m²").arg(QLocale().toString(*r.area, 'f', 2)));
    }
    m_view->setToolOverlay(new MeasureOverlay(path, label));
}

} // namespace kimbim
