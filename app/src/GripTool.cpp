// SPDX-License-Identifier: GPL-3.0-or-later
#include "GripTool.h"

#include <cmath>
#include <limits>

namespace kimbim {

GripTool::GripTool(QObject* parent)
    : QObject(parent)
{
}

QPointF GripTool::target(QPointF p) const
{
    return m_snapper.snap(p, m_tolerance, &m_fixed, m_ortho).point;
}

void GripTool::move(QPointF p)
{
    if (!isDragging())
        return;
    m_hover = target(p);
    emit previewChanged();
}

void GripTool::click(QPointF p)
{
    if (isDragging()) {
        finish(target(p));
        return;
    }
    double best = std::numeric_limits<double>::max();
    for (const SnapWall& w : m_snapper.walls())
        for (const bool start : {true, false}) {
            const QPointF end = start ? w.a : w.b;
            const double d = std::hypot(p.x() - end.x(), p.y() - end.y());
            if (d <= m_tolerance && d < best) {
                best = d;
                m_wall = w.guid;
                m_movingStart = start;
                m_original = end;
                m_fixed = start ? w.b : w.a;
                m_thickness = w.thickness;
            }
        }
    m_hover.reset();
    emit previewChanged();
}

bool GripTool::typeLength(double metres)
{
    if (!isDragging() || metres <= 0)
        return false;
    const QPointF towards = m_hover.value_or(m_original);
    const QPointF d = towards - m_fixed;
    const double length = std::hypot(d.x(), d.y());
    if (length < 1e-9)
        return false;
    finish(m_fixed + d * (metres / length));
    return true;
}

void GripTool::finish(QPointF moving)
{
    if (std::hypot(moving.x() - m_fixed.x(), moving.y() - m_fixed.y()) < 1e-3)
        return; // a wall needs a length
    const QString wall = m_wall;
    const QPointF p1 = m_movingStart ? moving : m_fixed, p2 = m_movingStart ? m_fixed : moving;
    cancel();
    emit stretchRequested(wall, p1, p2);
}

void GripTool::cancel()
{
    m_wall.clear();
    m_hover.reset();
    emit previewChanged();
}

std::optional<std::pair<QPointF, QPointF>> GripTool::preview() const
{
    if (!isDragging() || !m_hover)
        return std::nullopt;
    return m_movingStart ? std::make_pair(*m_hover, m_fixed) : std::make_pair(m_fixed, *m_hover);
}

} // namespace kimbim
