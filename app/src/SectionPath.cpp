// SPDX-License-Identifier: GPL-3.0-or-later
#include "SectionPath.h"

#include <algorithm>
#include <cmath>

namespace kimbim {

namespace {

QPointF leftNormal(const QPointF& a, const QPointF& b)
{
    const QPointF d = b - a;
    const double len = std::hypot(d.x(), d.y());
    if (len < 1e-12)
        return QPointF(0, 0);
    return QPointF(-d.y() / len, d.x() / len);
}

} // namespace

double bulgeThrough(const QPointF& a, const QPointF& b, const QPointF& through)
{
    const double len = std::hypot(b.x() - a.x(), b.y() - a.y());
    if (len < 1e-9)
        return 0.0;
    const QPointF n = leftNormal(a, b);
    const double sagitta = (through.x() - a.x()) * n.x() + (through.y() - a.y()) * n.y();
    return 2.0 * sagitta / len;
}

QVector<QPointF> sampleArc(const QPointF& a, const QPointF& b, double bulge, double maxTurnDeg)
{
    const double len = std::hypot(b.x() - a.x(), b.y() - a.y());
    if (len < 1e-9 || std::abs(bulge) < 1e-9)
        return {a, b};
    const QPointF n = leftNormal(a, b);
    const double sagitta = bulge * len / 2.0;
    const double radiusSigned = (len * len / 4.0 + sagitta * sagitta) / (2.0 * sagitta);
    const double radius = std::abs(radiusSigned);
    const QPointF mid = (a + b) / 2.0;
    const QPointF centre = mid + n * (sagitta - radiusSigned);
    const double start = std::atan2(a.y() - centre.y(), a.x() - centre.x());
    const double sweep = (bulge < 0 ? 1.0 : -1.0) * 4.0 * std::atan(std::abs(bulge));
    const double step = std::max(1e-3, maxTurnDeg) * M_PI / 180.0;
    const int steps = std::max(1, int(std::ceil(std::abs(sweep) / step)));
    QVector<QPointF> out;
    out.reserve(steps + 1);
    for (int i = 0; i <= steps; ++i) {
        const double angle = start + sweep * double(i) / steps;
        out << centre + QPointF(std::cos(angle), std::sin(angle)) * radius;
    }
    return out;
}

QVector<MarkerSegment> markerSegments(const QVector<QPointF>& points, const QVector<double>& bulges,
    double maxTurnDeg)
{
    QVector<MarkerSegment> out;
    for (int i = 0; i + 1 < points.size(); ++i) {
        const double bulge = i < bulges.size() ? bulges[i] : 0.0;
        if (std::abs(bulge) < 1e-9) {
            out.push_back({points[i], points[i + 1]});
            continue;
        }
        const QVector<QPointF> arc = sampleArc(points[i], points[i + 1], bulge, maxTurnDeg);
        for (int k = 0; k + 1 < arc.size(); ++k)
            out.push_back({arc[k], arc[k + 1]});
    }
    return out;
}

QVector<QPointF> markerOutline(const QVector<QPointF>& points, const QVector<double>& bulges,
    double maxTurnDeg)
{
    QVector<QPointF> out;
    if (points.isEmpty())
        return out;
    out << points.first();
    for (int i = 0; i + 1 < points.size(); ++i) {
        const double bulge = i < bulges.size() ? bulges[i] : 0.0;
        const QVector<QPointF> arc = std::abs(bulge) < 1e-9
            ? QVector<QPointF>{points[i], points[i + 1]}
            : sampleArc(points[i], points[i + 1], bulge, maxTurnDeg);
        for (int k = 1; k < arc.size(); ++k)
            out << arc[k];
    }
    return out;
}

} // namespace kimbim
