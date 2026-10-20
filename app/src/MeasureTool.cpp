// SPDX-License-Identifier: GPL-3.0-or-later
#include "MeasureTool.h"

#include <QLocale>

#include <algorithm>
#include <cmath>

namespace kimbim {

namespace {
constexpr double kSamePoint = 1e-6; // metres: a click on the last point adds nothing
constexpr double kDegrees = 180.0 / 3.14159265358979323846;

double length(double x, double y, double z)
{
    return std::sqrt(x * x + y * y + z * z);
}
} // namespace

MeasureTool::MeasureTool(QObject* parent)
    : QObject(parent)
{
    m_snapper.setFaceSnapping(true); // wall faces are what one measures between (as dimensions do)
}

MeasurePoint MeasureTool::resolve(QPointF p, double z, const std::optional<MeasurePoint>& surface, Snap* snap) const
{
    // Over an element in 3D, snap from the surface point's plan position and keep its height: a wall
    // top's corner snaps to the corner, up there. Elsewhere, the work plane.
    const QPointF at = surface ? surface->plan() : p;
    const double height = surface ? surface->z : z;
    QPointF from;
    const bool chained = !m_points.isEmpty() && !m_finished;
    if (chained)
        from = m_points.last().plan();
    *snap = m_snapper.snap(at, m_tolerance, chained ? &from : nullptr, m_ortho);
    const bool objectSnap = snap->kind != Snap::None && snap->kind != Snap::Grid && snap->kind != Snap::Angle;
    if (surface && !objectSnap && !m_ortho)
        return *surface; // the face itself (Archicad snaps to surfaces)
    return {snap->point.x(), snap->point.y(), height};
}

Snap MeasureTool::move(QPointF p, double z, const std::optional<MeasurePoint>& surface)
{
    Snap s;
    const MeasurePoint q = resolve(p, z, surface, &s);
    if (!m_finished) {
        m_hover = q;
        emit changed();
    }
    return s;
}

void MeasureTool::click(QPointF p, double z, const std::optional<MeasurePoint>& surface)
{
    if (m_finished) // a click after a finished measurement starts a new one
        clear();
    Snap s;
    const MeasurePoint q = resolve(p, z, surface, &s);
    if (!m_points.isEmpty()) {
        const MeasurePoint& last = m_points.last();
        if (length(q.x - last.x, q.y - last.y, q.z - last.z) < kSamePoint)
            return;
    }
    m_points << q;
    m_hover.reset();
    emit changed();
}

void MeasureTool::finish()
{
    if (m_points.isEmpty())
        return;
    m_finished = true;
    m_hover.reset();
    emit changed();
}

void MeasureTool::clear()
{
    m_points.clear();
    m_hover.reset();
    m_finished = false;
    emit changed();
}

QVector<MeasurePoint> MeasureTool::path() const
{
    QVector<MeasurePoint> out = m_points;
    if (m_hover && !out.isEmpty() && !m_finished && !(out.last() == *m_hover))
        out << *m_hover;
    return out;
}

MeasureReadout MeasureTool::compute(const QVector<MeasurePoint>& path)
{
    MeasureReadout r;
    r.points = int(path.size());
    const int n = r.points;
    for (int i = 1; i < n; ++i)
        r.total += length(path[i].x - path[i - 1].x, path[i].y - path[i - 1].y, path[i].z - path[i - 1].z);
    if (n >= 2) {
        const MeasurePoint &a = path[n - 2], &b = path[n - 1];
        r.dx = b.x - a.x;
        r.dy = b.y - a.y;
        r.dz = b.z - a.z;
        r.distance = length(r.dx, r.dy, r.dz);
    }
    if (n >= 3) {
        // The angle at the second to last point, between the last two segments.
        const MeasurePoint &a = path[n - 3], &b = path[n - 2], &c = path[n - 1];
        const double ux = a.x - b.x, uy = a.y - b.y, uz = a.z - b.z;
        const double vx = c.x - b.x, vy = c.y - b.y, vz = c.z - b.z;
        const double lu = length(ux, uy, uz), lv = length(vx, vy, vz);
        if (lu > kSamePoint && lv > kSamePoint)
            r.angle = std::acos(std::clamp((ux * vx + uy * vy + uz * vz) / (lu * lv), -1.0, 1.0)) * kDegrees;
        // Closed polygon: Newell's normal gives the area of a planar polygon at any tilt.
        double nx = 0, ny = 0, nz = 0, perimeter = 0;
        for (int i = 0; i < n; ++i) {
            const MeasurePoint &p = path[i], &q = path[(i + 1) % n];
            nx += (p.y - q.y) * (p.z + q.z);
            ny += (p.z - q.z) * (p.x + q.x);
            nz += (p.x - q.x) * (p.y + q.y);
            perimeter += length(q.x - p.x, q.y - p.y, q.z - p.z);
        }
        r.area = length(nx, ny, nz) / 2;
        r.perimeter = perimeter;
    }
    return r;
}

QString MeasureTool::describe(const MeasureReadout& r, const std::function<QString(double)>& len)
{
    if (r.points < 2)
        return r.points == 1 ? tr("Measure: click the next point (Enter: stop, Esc: clear)")
                             : tr("Measure: click the first point");
    const QLocale l;
    QStringList parts;
    parts << tr("Distance %1 (dx %2, dy %3, dz %4)").arg(len(r.distance), len(r.dx), len(r.dy), len(r.dz));
    if (r.points > 2)
        parts << tr("Total %1").arg(len(r.total));
    if (r.angle)
        parts << tr("Angle %1°").arg(l.toString(*r.angle, 'f', 2));
    if (r.area && r.perimeter)
        parts << tr("Area %1 m²").arg(l.toString(*r.area, 'f', 2)) << tr("Perimeter %1").arg(len(*r.perimeter));
    return parts.join(QStringLiteral("  ·  "));
}

} // namespace kimbim
