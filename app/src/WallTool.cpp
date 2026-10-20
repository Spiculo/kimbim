// SPDX-License-Identifier: GPL-3.0-or-later
#include "WallTool.h"

#include <cmath>

namespace kimbim {

namespace {
constexpr double kMinLength = 0.001; // metres: shorter segments (double clicks) are ignored
} // namespace

WallTool::WallTool(QObject* parent)
    : QObject(parent)
{
}

Snap WallTool::snapAt(QPointF p) const
{
    return m_drawing ? m_snapper.snap(p, m_tolerance, &m_start, m_ortho) : m_snapper.snap(p, m_tolerance);
}

Snap WallTool::move(QPointF p)
{
    const Snap s = snapAt(p);
    m_hover = s.point;
    emit previewChanged();
    return s;
}

void WallTool::click(QPointF p)
{
    const Snap s = snapAt(p);
    if (!m_drawing) {
        m_drawing = true;
        m_start = s.point;
        m_startJoin = s.onWall() ? s.wallGuid : QString();
        m_lastWall.clear();
        m_hover.reset();
        emit previewChanged();
        return;
    }
    if (std::hypot(s.point.x() - m_start.x(), s.point.y() - m_start.y()) < kMinLength)
        return;
    request(s.point, s.onWall() ? s.wallGuid : QString());
}

bool WallTool::typeLength(double metres)
{
    if (!m_drawing || !m_hover || metres <= 0)
        return false;
    const QPointF d = *m_hover - m_start;
    const double length = std::hypot(d.x(), d.y());
    if (length < kMinLength)
        return false;
    request(m_start + d * (metres / length), QString());
    return true;
}

void WallTool::request(QPointF end, const QString& joinEnd)
{
    const WallSegment segment{m_start, end, m_lastWall.isEmpty() ? m_startJoin : m_lastWall, joinEnd};
    m_start = end;
    m_startJoin.clear();
    m_lastWall.clear(); // the receiver sets it while handling the request
    emit wallRequested(segment);
    emit previewChanged();
}

void WallTool::finish()
{
    const bool was = m_drawing;
    m_drawing = false;
    m_hover.reset();
    m_startJoin.clear();
    m_lastWall.clear();
    emit previewChanged();
    if (was)
        emit finished();
}

std::optional<std::pair<QPointF, QPointF>> WallTool::preview() const
{
    if (!m_drawing || !m_hover)
        return std::nullopt;
    return std::make_pair(m_start, *m_hover);
}

} // namespace kimbim
