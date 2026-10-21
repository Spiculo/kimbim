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
        if (w.arc) { // D97: along the arc, across it from the body's middle
            const SnapArc& arc = *w.arc;
            const double length = arc.length();
            QPointF q;
            double t = 0;
            if (length < width || !arc.project(p, &q, &t))
                continue;
            const double turn = arc.sweep >= 0 ? 1.0 : -1.0;
            const double left = (arc.r - std::hypot(p.x() - arc.c.x(), p.y() - arc.c.y())) * turn;
            const double across = std::abs(left - w.centre);
            if (across > w.thickness / 2 + tolerance || across >= bestDistance)
                continue;
            double along = grid > 0 ? std::round(t * length / grid) * grid : t * length;
            along = std::clamp(along, width / 2, length - width / 2);
            const double a = arc.a0 + arc.sweep * along / length;
            bestDistance = across;
            const QPointF onArc = arc.at(along / length), towardsCentre = (arc.c - onArc) / arc.r;
            best = Host{w.guid, along, onArc + towardsCentre * (w.centre * turn), a + turn * M_PI / 2, w.thickness};
            continue;
        }
        const QPointF d = w.b - w.a;
        const double length = std::hypot(d.x(), d.y());
        if (length < width || length <= 0)
            continue; // the opening wouldn't fit
        const QPointF u = d / length;
        const double t = (p.x() - w.a.x()) * u.x() + (p.y() - w.a.y()) * u.y();
        // D97: from the body's middle (a wall drawn by a face has its body beside the axis)
        const double across = std::abs(-(p.x() - w.a.x()) * u.y() + (p.y() - w.a.y()) * u.x() - w.centre);
        if (t < -tolerance || t > length + tolerance || across > w.thickness / 2 + tolerance)
            continue;
        if (across >= bestDistance)
            continue;
        double along = grid > 0 ? std::round(t / grid) * grid : t;
        along = std::clamp(along, width / 2, length - width / 2);
        bestDistance = across;
        // the preview's middle: on the body (beside the axis for a wall drawn by a face)
        best = Host{w.guid, along, w.a + u * along + QPointF(-u.y(), u.x()) * w.centre, std::atan2(u.y(), u.x()),
            w.thickness};
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
