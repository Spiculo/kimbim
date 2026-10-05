// SPDX-License-Identifier: GPL-3.0-or-later
#include "Snapper.h"

#include <QJsonArray>

#include <cmath>
#include <limits>

namespace kimcad {

namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kAngleStep = 15.0 * kPi / 180.0;
constexpr double kAngleTolerance = 3.0 * kPi / 180.0; // how close to a 15 degree step to stick

double dist(QPointF a, QPointF b)
{
    return std::hypot(a.x() - b.x(), a.y() - b.y());
}

// Closest point on segment ab to p, and whether it lies strictly inside (not at an end).
QPointF project(QPointF p, QPointF a, QPointF b, bool* inside)
{
    const QPointF d = b - a;
    const double len2 = d.x() * d.x() + d.y() * d.y();
    if (len2 <= 0) {
        *inside = false;
        return a;
    }
    const double t = ((p.x() - a.x()) * d.x() + (p.y() - a.y()) * d.y()) / len2;
    *inside = t > 0 && t < 1;
    const double c = std::clamp(t, 0.0, 1.0);
    return a + d * c;
}

} // namespace

QVector<SnapWall> Snapper::parse(const QJsonObject& snapData)
{
    QVector<SnapWall> out;
    for (const auto& v : snapData.value("walls").toArray()) {
        const QJsonObject w = v.toObject();
        out.push_back({w.value("guid").toString(), QPointF(w.value("x1").toDouble(), w.value("y1").toDouble()),
            QPointF(w.value("x2").toDouble(), w.value("y2").toDouble()), w.value("thickness").toDouble()});
    }
    return out;
}

QPointF Snapper::onGrid(QPointF p) const
{
    if (m_grid <= 0)
        return p;
    return QPointF(std::round(p.x() / m_grid) * m_grid, std::round(p.y() / m_grid) * m_grid);
}

double Snapper::gridLength(double length) const
{
    return m_grid > 0 ? std::round(length / m_grid) * m_grid : length;
}

Snap Snapper::snap(QPointF p, double tolerance, const QPointF* from, bool ortho) const
{
    // Object snaps, best kind first; within a kind the closest wins.
    auto best = [&](Snap::Kind kind, auto&& candidate) -> Snap {
        Snap s;
        double bestDistance = std::numeric_limits<double>::max();
        for (const SnapWall& w : m_walls) {
            QPointF q;
            if (!candidate(w, &q))
                continue;
            const double d = dist(p, q);
            if (d <= tolerance && d < bestDistance) {
                bestDistance = d;
                s = Snap{q, kind, w.guid};
            }
        }
        return s;
    };
    Snap s = best(Snap::Endpoint, [&](const SnapWall& w, QPointF* q) {
        *q = dist(p, w.a) <= dist(p, w.b) ? w.a : w.b;
        return true;
    });
    if (s.kind == Snap::None)
        s = best(Snap::Midpoint, [&](const SnapWall& w, QPointF* q) {
            *q = (w.a + w.b) / 2;
            return true;
        });
    if (s.kind == Snap::None && from)
        s = best(Snap::Perpendicular, [&](const SnapWall& w, QPointF* q) {
            bool inside = false;
            *q = project(*from, w.a, w.b, &inside);
            return inside;
        });
    if (s.kind == Snap::None)
        s = best(Snap::OnWall, [&](const SnapWall& w, QPointF* q) {
            bool inside = false;
            *q = project(p, w.a, w.b, &inside);
            return inside;
        });
    if (s.kind != Snap::None)
        return s;

    if (from) {
        const QPointF v = p - *from;
        const double length = std::hypot(v.x(), v.y());
        if (length > 0) {
            const double angle = std::atan2(v.y(), v.x());
            const double step = ortho ? kPi / 2 : kAngleStep;
            const double snapped = std::round(angle / step) * step;
            if (ortho || std::abs(angle - snapped) <= kAngleTolerance) {
                const QPointF d(std::cos(snapped), std::sin(snapped));
                const double along = ortho ? v.x() * d.x() + v.y() * d.y() : length;
                return Snap{*from + d * gridLength(along), Snap::Angle, {}};
            }
        }
    }
    return Snap{onGrid(p), Snap::Grid, {}};
}

} // namespace kimcad
