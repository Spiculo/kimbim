// SPDX-License-Identifier: GPL-3.0-or-later
#include "Snapper.h"

#include <array>

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

QVector<SnapLine> Snapper::parseGrid(const QJsonObject& snapData)
{
    QVector<SnapLine> out;
    for (const auto& v : snapData.value("grid").toArray()) {
        const QJsonObject g = v.toObject();
        out.push_back({g.value("guid").toString(), g.value("tag").toString(),
            QPointF(g.value("x1").toDouble(), g.value("y1").toDouble()), QPointF(g.value("x2").toDouble(), g.value("y2").toDouble())});
    }
    return out;
}

QVector<SnapPoint> Snapper::parsePoints(const QJsonObject& snapData)
{
    QVector<SnapPoint> out;
    for (const auto& v : snapData.value("points").toArray()) {
        const QJsonObject o = v.toObject();
        const QString kind = o.value("kind").toString();
        out.push_back({QPointF(o.value("x").toDouble(), o.value("y").toDouble()),
            kind == QLatin1String("midpoint") ? int(Snap::Midpoint) : kind == QLatin1String("centre") ? int(Snap::Centre) : int(Snap::Endpoint),
            o.value("guid").toString()});
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
    // Drafting points of one kind (D84): the closest within the tolerance, if closer than `s`.
    auto points = [&](Snap::Kind kind, Snap s) -> Snap {
        double bestDistance = s.kind == kind ? dist(p, s.point) : tolerance;
        for (const SnapPoint& sp : m_points)
            if (sp.kind == kind && dist(p, sp.p) <= bestDistance) {
                bestDistance = dist(p, sp.p);
                s = Snap{sp.p, kind, {}};
            }
        return s;
    };
    Snap s = best(Snap::Endpoint, [&](const SnapWall& w, QPointF* q) {
        *q = dist(p, w.a) <= dist(p, w.b) ? w.a : w.b;
        return true;
    });
    if (s.kind == Snap::None || s.kind == Snap::Endpoint)
        s = points(Snap::Endpoint, s);
    if (s.kind == Snap::None) { // grid-axis crossings
        double bestDistance = tolerance;
        for (int i = 0; i < m_lines.size(); ++i)
            for (int j = i + 1; j < m_lines.size(); ++j) {
                const QPointF a = m_lines[i].a, b = m_lines[i].b, c = m_lines[j].a, d = m_lines[j].b;
                const double den = (b.x() - a.x()) * (d.y() - c.y()) - (b.y() - a.y()) * (d.x() - c.x());
                if (std::abs(den) < 1e-12)
                    continue;
                const double t = ((c.x() - a.x()) * (d.y() - c.y()) - (c.y() - a.y()) * (d.x() - c.x())) / den;
                const QPointF x = a + (b - a) * t;
                if (dist(p, x) <= bestDistance) {
                    bestDistance = dist(p, x);
                    s = Snap{x, Snap::GridCross, {}};
                }
            }
    }
    // Wall faces (Slice 15): the axis offset by half the thickness on each side.
    auto faces = [](const SnapWall& w) {
        const QPointF d = w.b - w.a;
        const double len = std::hypot(d.x(), d.y());
        const QPointF n = len > 1e-12 ? QPointF(-d.y() / len, d.x() / len) * (w.thickness / 2) : QPointF();
        return std::array<std::pair<QPointF, QPointF>, 2>{std::pair{w.a + n, w.b + n}, std::pair{w.a - n, w.b - n}};
    };
    if (s.kind == Snap::None && m_faces)
        s = best(Snap::FaceEnd, [&](const SnapWall& w, QPointF* q) {
            double bestD = std::numeric_limits<double>::max();
            for (const auto& [a, b] : faces(w))
                for (const QPointF& c : {a, b})
                    if (dist(p, c) < bestD) {
                        bestD = dist(p, c);
                        *q = c;
                    }
            return true;
        });
    if (s.kind == Snap::None)
        s = best(Snap::Midpoint, [&](const SnapWall& w, QPointF* q) {
            *q = (w.a + w.b) / 2;
            return true;
        });
    if (s.kind == Snap::None || s.kind == Snap::Midpoint)
        s = points(Snap::Midpoint, s);
    if (s.kind == Snap::None)
        s = points(Snap::Centre, s);
    if (s.kind == Snap::None && from)
        s = best(Snap::Perpendicular, [&](const SnapWall& w, QPointF* q) {
            bool inside = false;
            *q = project(*from, w.a, w.b, &inside);
            return inside;
        });
    if (s.kind == Snap::None && m_faces)
        s = best(Snap::OnFace, [&](const SnapWall& w, QPointF* q) {
            double bestD = std::numeric_limits<double>::max();
            bool any = false;
            for (const auto& [a, b] : faces(w)) {
                bool inside = false;
                const QPointF r = project(p, a, b, &inside);
                if (inside && dist(p, r) < bestD) {
                    bestD = dist(p, r);
                    *q = r;
                    any = true;
                }
            }
            return any;
        });
    if (s.kind == Snap::None)
        s = best(Snap::OnWall, [&](const SnapWall& w, QPointF* q) {
            bool inside = false;
            *q = project(p, w.a, w.b, &inside);
            return inside;
        });
    if (s.kind == Snap::None) { // anywhere along a grid axis
        double bestDistance = tolerance;
        for (const SnapLine& line : m_lines) {
            bool inside = false;
            const QPointF q = project(p, line.a, line.b, &inside);
            if (inside && dist(p, q) <= bestDistance) {
                bestDistance = dist(p, q);
                s = Snap{q, Snap::GridLine, {}};
            }
        }
    }
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
