// SPDX-License-Identifier: GPL-3.0-or-later
#include "HostTool.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace kimbim {

HostTool::HostTool(QObject* parent)
    : QObject(parent)
{
}

std::optional<Host> HostTool::locate(const QVector<SnapWall>& walls, QPointF p, double width, double tolerance, double grid)
{
    std::optional<Host> best;
    double bestDistance = std::numeric_limits<double>::max();
    for (const SnapWall& w : walls) {
        const QPointF d = w.b - w.a;
        const double length = std::hypot(d.x(), d.y());
        if (length < width || length <= 0)
            continue; // the opening wouldn't fit
        const QPointF u = d / length;
        const double t = (p.x() - w.a.x()) * u.x() + (p.y() - w.a.y()) * u.y();
        const double across = std::abs(-(p.x() - w.a.x()) * u.y() + (p.y() - w.a.y()) * u.x());
        if (t < -tolerance || t > length + tolerance || across > w.thickness / 2 + tolerance)
            continue;
        if (across >= bestDistance)
            continue;
        double along = grid > 0 ? std::round(t / grid) * grid : t;
        along = std::clamp(along, width / 2, length - width / 2);
        bestDistance = across;
        best = Host{w.guid, along, w.a + u * along, std::atan2(u.y(), u.x()), w.thickness};
    }
    return best;
}

std::optional<Host> HostTool::move(QPointF p)
{
    m_hover = locate(m_walls, p, m_width, m_tolerance);
    emit previewChanged();
    return m_hover;
}

void HostTool::click(QPointF p)
{
    if (const auto host = locate(m_walls, p, m_width, m_tolerance))
        emit openingRequested(*host);
}

} // namespace kimbim
