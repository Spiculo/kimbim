// SPDX-License-Identifier: GPL-3.0-or-later
#include "TwoPointTool.h"

#include <cmath>

namespace kimbim {

namespace {
constexpr double kMinLength = 0.001; // metres
} // namespace

TwoPointTool::TwoPointTool(QObject* parent)
    : QObject(parent)
{
}

Snap TwoPointTool::snapAt(QPointF p) const
{
    if (!m_start)
        return m_snapper.snap(p, m_tolerance);
    const QPointF from = *m_start;
    return m_snapper.snap(p, m_tolerance, &from, m_ortho);
}

Snap TwoPointTool::move(QPointF p)
{
    const Snap s = snapAt(p);
    m_hover = s.point;
    emit previewChanged();
    return s;
}

void TwoPointTool::click(QPointF p)
{
    const Snap s = snapAt(p);
    if (!m_start) {
        m_start = s.point;
        m_hover.reset();
        emit previewChanged();
        return;
    }
    if (std::hypot(s.point.x() - m_start->x(), s.point.y() - m_start->y()) < kMinLength)
        return;
    const QPointF a = *m_start;
    m_start.reset();
    m_hover.reset();
    emit previewChanged();
    emit segmentFinished(a, s.point);
}

bool TwoPointTool::typeLength(double metres)
{
    if (!m_start || !m_hover || metres <= 0)
        return false;
    const QPointF d = *m_hover - *m_start;
    const double length = std::hypot(d.x(), d.y());
    if (length < kMinLength)
        return false;
    const QPointF a = *m_start, b = *m_start + d * (metres / length);
    m_start.reset();
    m_hover.reset();
    emit previewChanged();
    emit segmentFinished(a, b);
    return true;
}

void TwoPointTool::cancel()
{
    m_start.reset();
    m_hover.reset();
    emit previewChanged();
}

std::optional<std::pair<QPointF, QPointF>> TwoPointTool::preview() const
{
    if (!m_start || !m_hover)
        return std::nullopt;
    return std::make_pair(*m_start, *m_hover);
}

} // namespace kimbim
