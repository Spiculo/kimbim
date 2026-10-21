// SPDX-License-Identifier: GPL-3.0-or-later
#include "Snapper.h"
#include "InputAids.h"
#include "Underlay.h"

#include <array>

#include <QJsonArray>

#include <cmath>
#include <limits>

namespace kimbim {

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
            QPointF(w.value("x2").toDouble(), w.value("y2").toDouble()), w.value("thickness").toDouble(),
            w.value("centre").toDouble()});
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
    if (m_snapStep > 0) { // D98: the snap grid's nodes, in its own frame
        const double c = std::cos(m_gridAngle), s = std::sin(m_gridAngle);
        const QPointF d = p - m_gridOrigin;
        const double u = std::round((d.x() * c + d.y() * s) / m_snapStep) * m_snapStep;
        const double v = std::round((-d.x() * s + d.y() * c) / m_snapStep) * m_snapStep;
        return m_gridOrigin + QPointF(u * c - v * s, u * s + v * c);
    }
    if (m_grid <= 0)
        return p;
    return QPointF(std::round(p.x() / m_grid) * m_grid, std::round(p.y() / m_grid) * m_grid);
}

double Snapper::gridLength(double length) const
{
    return m_grid > 0 ? std::round(length / m_grid) * m_grid : length;
}

namespace {

// Where lines a + s*u and b + t*v cross (false: parallel); s and t returned.
bool crossLines(QPointF a, QPointF u, QPointF b, QPointF v, double* s, double* t)
{
    const double den = u.x() * v.y() - u.y() * v.x();
    if (std::abs(den) < 1e-12)
        return false;
    const QPointF w = b - a;
    *s = (w.x() * v.y() - w.y() * v.x()) / den;
    *t = (w.x() * u.y() - w.y() * u.x()) / den;
    return true;
}

double distanceToSegment(QPointF p, QPointF a, QPointF b)
{
    bool inside = false;
    return dist(p, project(p, a, b, &inside));
}

} // namespace

std::optional<QPointF> Snapper::wallDirection(const QString& guid) const
{
    if (guid.isEmpty())
        return std::nullopt;
    for (const SnapWall& w : m_walls)
        if (w.guid == guid) {
            const QPointF d = w.b - w.a;
            const double len = std::hypot(d.x(), d.y());
            if (len > 1e-12)
                return d / len;
        }
    return std::nullopt;
}

Snap Snapper::snap(QPointF p, double tolerance, const QPointF* from, bool ortho) const
{
    const Snap s = compute(p, tolerance, from, ortho);
    if (m_aids) { // D89
        m_aids->record(from ? std::optional<QPointF>(*from) : std::nullopt, s.point, s.kind);
        if (tolerance >= 0) {
            switch (s.kind) {
            case Snap::Endpoint:
            case Snap::Midpoint:
            case Snap::GridCross:
            case Snap::Intersection:
            case Snap::FaceEnd:
            case Snap::Centre:
            case Snap::UnderlayEnd:
            case Snap::UnderlayMid:
            case Snap::UnderlayCross:
            case Snap::Division:
                m_aids->hover(InputAids::Guide{s.point, wallDirection(s.wallGuid)});
                break;
            default:
                m_aids->hover(std::nullopt);
            }
        }
    }
    return s;
}

// D89: the temporary guides' crossings (lines = false) or the guide lines and parallels (true).
bool Snapper::guideSnap(QPointF p, double tolerance, const QPointF* from, bool lines, Snap* out) const
{
    if (!m_aids || m_aids->guides().isEmpty())
        return false;
    struct Line {
        QPointF a, u;
        int owner; // guide index; -1: through the previous point; -2: a wall axis (a + s*u, s in 0..1)
        QString guid;
    };
    QVector<Line> guideLines;
    const auto& guides = m_aids->guides();
    for (int i = 0; i < guides.size(); ++i) {
        const auto& g = guides[i];
        guideLines.push_back({g.at, QPointF(1, 0), i, {}});
        guideLines.push_back({g.at, QPointF(0, 1), i, {}});
        if (g.direction && std::abs(g.direction->x()) > 1e-9 && std::abs(g.direction->y()) > 1e-9)
            guideLines.push_back({g.at, *g.direction, i, {}}); // the element's extension
    }
    if (lines) {
        double bestDistance = tolerance;
        bool found = false;
        for (const Line& l : std::as_const(guideLines)) {
            const QPointF w = p - l.a;
            const double along = w.x() * l.u.x() + w.y() * l.u.y();
            const QPointF foot = l.a + l.u * along;
            if (dist(p, foot) <= bestDistance) {
                bestDistance = dist(p, foot);
                *out = Snap{l.a + l.u * gridLength(along), Snap::GuideLine, {}};
                found = true;
            }
        }
        if (found)
            return true;
        if (from) { // drawing parallel to an acquired wall
            const QPointF v = p - *from;
            const double length = std::hypot(v.x(), v.y());
            double bestAngle = kAngleTolerance;
            for (const auto& g : guides) {
                if (!g.direction || length <= 0)
                    continue;
                const double along = v.x() * g.direction->x() + v.y() * g.direction->y();
                const double angle = std::acos(std::min(1.0, std::abs(along) / length));
                if (angle <= bestAngle) {
                    bestAngle = angle;
                    *out = Snap{*from + *g.direction * gridLength(along), Snap::Parallel, {}};
                    found = true;
                }
            }
        }
        return found;
    }
    // Crossings: guide x guide (different points), guide x the previous point's horizontal/vertical,
    // guide x a wall axis near the cursor.
    if (from) {
        guideLines.push_back({*from, QPointF(1, 0), -1, {}});
        guideLines.push_back({*from, QPointF(0, 1), -1, {}});
    }
    for (const SnapWall& w : m_walls)
        if (distanceToSegment(p, w.a, w.b) <= tolerance)
            guideLines.push_back({w.a, w.b - w.a, -2, w.guid});
    double bestDistance = tolerance;
    bool found = false;
    for (int i = 0; i < guideLines.size(); ++i)
        for (int j = i + 1; j < guideLines.size(); ++j) {
            const Line& l = guideLines[i];
            const Line& m = guideLines[j];
            if (l.owner == m.owner || (l.owner < 0 && m.owner < 0))
                continue; // a point's own lines cross at the point; walls and the previous point need a guide
            double s = 0, t = 0;
            if (!crossLines(l.a, l.u, m.a, m.u, &s, &t))
                continue;
            if ((l.owner == -2 && (s < 0 || s > 1)) || (m.owner == -2 && (t < 0 || t > 1)))
                continue; // off the wall
            const QPointF x = l.a + l.u * s;
            if (dist(p, x) <= bestDistance) {
                bestDistance = dist(p, x);
                *out = Snap{x, Snap::GuideCross, l.owner == -2 ? l.guid : m.owner == -2 ? m.guid : QString()};
                found = true;
            }
        }
    return found;
}

Snap Snapper::compute(QPointF p, double tolerance, const QPointF* from, bool ortho) const
{
    // D89: a typed point is exact: only the wall it lies on is looked for (joins), nothing moves it.
    const bool exact = tolerance < 0;
    if (exact)
        tolerance = 1e-6;
    // D89: tracker locks hold the cursor.
    if (!exact && m_aids && m_aids->locks().any()) {
        const InputAids::Locks& lock = m_aids->locks();
        if (lock.x || lock.y)
            return Snap{QPointF(lock.x.value_or(p.x()), lock.y.value_or(p.y())), Snap::Tracked, {}};
        if (from) {
            const QPointF v = p - *from;
            const double angle = lock.angle.value_or(std::atan2(v.y(), v.x()));
            const QPointF d(std::cos(angle), std::sin(angle));
            const double length
                = lock.length.value_or(gridLength(lock.angle ? v.x() * d.x() + v.y() * d.y() : std::hypot(v.x(), v.y())));
            return Snap{*from + d * length, Snap::Tracked, {}};
        }
    }
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
    if (s.kind == Snap::None) { // D89: wall x wall and wall x grid-axis crossings near the cursor
        struct Seg {
            QPointF a, b;
            QString guid;
        };
        QVector<Seg> near;
        for (const SnapWall& w : m_walls)
            if (distanceToSegment(p, w.a, w.b) <= tolerance)
                near.push_back({w.a, w.b, w.guid});
        for (const SnapLine& l : m_lines)
            if (distanceToSegment(p, l.a, l.b) <= tolerance)
                near.push_back({l.a, l.b, {}});
        double bestDistance = tolerance;
        for (int i = 0; i < near.size(); ++i)
            for (int j = i + 1; j < near.size(); ++j) {
                if (near[i].guid.isEmpty() && near[j].guid.isEmpty())
                    continue; // grid crossings above
                double si = 0, sj = 0;
                if (!crossLines(near[i].a, near[i].b - near[i].a, near[j].a, near[j].b - near[j].a, &si, &sj)
                    || si < 0 || si > 1 || sj < 0 || sj > 1)
                    continue;
                const QPointF x = near[i].a + (near[i].b - near[i].a) * si;
                if (dist(p, x) <= bestDistance) {
                    bestDistance = dist(p, x);
                    s = Snap{x, Snap::Intersection, near[i].guid.isEmpty() ? near[j].guid : near[i].guid};
                }
            }
    }
    // Wall faces (Slice 15): the axis offset by half the thickness on each side.
    auto faces = [](const SnapWall& w) {
        const QPointF d = w.b - w.a;
        const double len = std::hypot(d.x(), d.y());
        const QPointF u = len > 1e-12 ? QPointF(-d.y() / len, d.x() / len) : QPointF();
        const QPointF n = u * (w.thickness / 2), c = u * w.centre;
        return std::array<std::pair<QPointF, QPointF>, 2>{
            std::pair{w.a + c + n, w.b + c + n}, std::pair{w.a + c - n, w.b + c - n}};
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
    if (s.kind == Snap::None && (m_divisions > 2 || m_distance > 0)) // D98: special snap points
        s = best(Snap::Division, [&](const SnapWall& w, QPointF* q) {
            const QPointF d = w.b - w.a;
            const double len = std::hypot(d.x(), d.y());
            if (len < 1e-9)
                return false;
            double bestD = std::numeric_limits<double>::max();
            auto consider = [&](double t) {
                if (t <= 0 || t >= 1)
                    return;
                const QPointF c = w.a + d * t;
                if (dist(p, c) < bestD) {
                    bestD = dist(p, c);
                    *q = c;
                }
            };
            for (int k = 1; m_divisions > 2 && k < m_divisions; ++k)
                consider(double(k) / m_divisions);
            if (m_distance > 0) {
                consider(m_distance / len);
                consider(1.0 - m_distance / len);
            }
            return bestD < std::numeric_limits<double>::max();
        });
    if (s.kind == Snap::None)
        s = points(Snap::Centre, s);
    if (s.kind == Snap::None && m_underlays) { // D85: tracing a survey
        QPointF q;
        if (m_underlays->endpoint(p, tolerance, &q))
            s = Snap{q, Snap::UnderlayEnd, {}};
        else if (m_underlays->crossing(p, tolerance, &q))
            s = Snap{q, Snap::UnderlayCross, {}};
        else if (m_underlays->midpoint(p, tolerance, &q))
            s = Snap{q, Snap::UnderlayMid, {}};
    }
    if (s.kind == Snap::None && !exact)
        guideSnap(p, tolerance, from, false, &s); // D89: where temporary guides cross
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
    if (s.kind == Snap::None && !exact)
        guideSnap(p, tolerance, from, true, &s); // D89: along a temporary guide, parallel to an acquired wall
    if (s.kind == Snap::None && m_underlays) {
        QPointF q;
        if (m_underlays->onLine(p, tolerance, &q))
            s = Snap{q, Snap::OnUnderlay, {}};
    }
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
    if (exact)
        return Snap{p, Snap::Typed, {}};

    if (from && (m_snapStep <= 0 || ortho)) { // grid snap replaces the 15 degree steps (ortho stays)
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

} // namespace kimbim
