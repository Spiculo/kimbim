// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QPointF>
#include <QVector>

namespace kimbim {

// D110: a section/elevation marker's path. Vertices are plan points (world metres); a segment's
// bulge is tan(sweep / 4), the DXF convention (0 = straight, 1 = a half circle, > 1 = a major arc).
struct MarkerSegment {
    QPointF a, b;
};

// The path as straight segments, arcs sampled at no more than `maxTurnDeg` degrees per segment.
QVector<MarkerSegment> markerSegments(const QVector<QPointF>& points, const QVector<double>& bulges,
    double maxTurnDeg = 10.0);

// The same path as a polyline for drawing and picking in plan.
QVector<QPointF> markerOutline(const QVector<QPointF>& points, const QVector<double>& bulges,
    double maxTurnDeg = 10.0);

// The bulge of the circular arc from `a` to `b` through `through` (2 x sagitta / chord).
double bulgeThrough(const QPointF& a, const QPointF& b, const QPointF& through);

// Points of one arc segment, the first point included and the last too.
QVector<QPointF> sampleArc(const QPointF& a, const QPointF& b, double bulge, double maxTurnDeg = 10.0);

} // namespace kimbim
