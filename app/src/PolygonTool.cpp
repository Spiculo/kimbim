// SPDX-License-Identifier: GPL-3.0-or-later
#include "PolygonTool.h"

#include <algorithm>
#include <cmath>
#include <numeric>

namespace kimcad {

namespace {

double cross(QPointF o, QPointF a, QPointF b)
{
    return (a.x() - o.x()) * (b.y() - o.y()) - (a.y() - o.y()) * (b.x() - o.x());
}

double signedArea(const QVector<QPointF>& p)
{
    double a = 0;
    for (int i = 0; i < p.size(); ++i)
        a += p[i].x() * p[(i + 1) % p.size()].y() - p[(i + 1) % p.size()].x() * p[i].y();
    return a / 2;
}

bool segmentsCross(QPointF a, QPointF b, QPointF c, QPointF d)
{
    auto orient = [](QPointF p, QPointF q, QPointF r) {
        const double v = cross(p, q, r);
        return std::abs(v) < 1e-12 ? 0 : (v > 0 ? 1 : -1);
    };
    return orient(a, b, c) * orient(a, b, d) < 0 && orient(c, d, a) * orient(c, d, b) < 0;
}

bool inTriangle(QPointF p, QPointF a, QPointF b, QPointF c)
{
    const double d1 = cross(a, b, p), d2 = cross(b, c, p), d3 = cross(c, a, p);
    const bool neg = d1 < -1e-12 || d2 < -1e-12 || d3 < -1e-12;
    const bool pos = d1 > 1e-12 || d2 > 1e-12 || d3 > 1e-12;
    return !(neg && pos);
}

} // namespace

PolygonTool::PolygonTool(QObject* parent)
    : QObject(parent)
{
}

Snap PolygonTool::snapAt(QPointF p) const
{
    if (m_points.isEmpty())
        return m_snapper.snap(p, m_tolerance);
    // Closing on the first point wins over everything else.
    if (m_points.size() >= 3 && std::hypot(p.x() - m_points.first().x(), p.y() - m_points.first().y()) <= m_tolerance)
        return Snap{m_points.first(), Snap::Endpoint, {}};
    const QPointF from = m_points.last();
    return m_snapper.snap(p, m_tolerance, &from, m_ortho);
}

Snap PolygonTool::move(QPointF p)
{
    const Snap s = snapAt(p);
    m_hover = s.point;
    emit previewChanged();
    return s;
}

void PolygonTool::click(QPointF p)
{
    const Snap s = snapAt(p);
    if (!m_points.isEmpty()) {
        if (m_points.size() >= 3 && s.point == m_points.first()) {
            finish();
            return;
        }
        if (std::hypot(s.point.x() - m_points.last().x(), s.point.y() - m_points.last().y()) < 1e-3)
            return; // double click on the same point
    }
    m_points << s.point;
    emit previewChanged();
}

void PolygonTool::finish()
{
    const QVector<QPointF> polygon = m_points;
    cancel();
    if (polygon.size() < 3)
        return;
    if (!isSimple(polygon)) {
        emit rejected(tr("The outline crosses itself"));
        return;
    }
    emit polygonFinished(polygon);
}

void PolygonTool::cancel()
{
    m_points.clear();
    m_hover.reset();
    emit previewChanged();
}

bool PolygonTool::isSimple(const QVector<QPointF>& p)
{
    const int n = int(p.size());
    if (n < 3 || std::abs(signedArea(p)) < 1e-9)
        return false;
    for (int i = 0; i < n; ++i)
        for (int j = i + 1; j < n; ++j) {
            if (j == i + 1 || (i == 0 && j == n - 1))
                continue;
            if (segmentsCross(p[i], p[(i + 1) % n], p[j], p[(j + 1) % n]))
                return false;
        }
    return true;
}

std::vector<uint32_t> PolygonTool::triangulate(const QVector<QPointF>& polygon)
{
    std::vector<uint32_t> out;
    if (!isSimple(polygon))
        return out;
    std::vector<uint32_t> idx(size_t(polygon.size()));
    std::iota(idx.begin(), idx.end(), 0u);
    if (signedArea(polygon) < 0)
        std::reverse(idx.begin(), idx.end()); // work counter-clockwise
    size_t guard = idx.size() * idx.size();
    while (idx.size() > 3 && guard-- > 0) {
        bool clipped = false;
        for (size_t i = 0; i < idx.size(); ++i) {
            const uint32_t a = idx[(i + idx.size() - 1) % idx.size()], b = idx[i], c = idx[(i + 1) % idx.size()];
            if (cross(polygon[int(a)], polygon[int(b)], polygon[int(c)]) <= 1e-12)
                continue; // reflex corner
            bool ear = true;
            for (uint32_t k : idx)
                if (k != a && k != b && k != c && inTriangle(polygon[int(k)], polygon[int(a)], polygon[int(b)], polygon[int(c)])) {
                    ear = false;
                    break;
                }
            if (!ear)
                continue;
            out.insert(out.end(), {a, b, c});
            idx.erase(idx.begin() + std::ptrdiff_t(i));
            clipped = true;
            break;
        }
        if (!clipped)
            break;
    }
    if (idx.size() == 3)
        out.insert(out.end(), {idx[0], idx[1], idx[2]});
    return out;
}

} // namespace kimcad
