// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QObject>
#include <QPointF>
#include <QString>
#include <QVector>

#include <functional>
#include <optional>

#include "Snapper.h"

namespace kimbim {

// A point in world metres (the measure tool works in 3D: plan snaps on the work plane, or a point
// picked on an element's surface in a 3D view).
struct MeasurePoint {
    double x = 0, y = 0, z = 0;
    QPointF plan() const { return {x, y}; }
    bool operator==(const MeasurePoint& o) const { return x == o.x && y == o.y && z == o.z; }
};

// What the measure tool shows for a path of points (D79, Archicad's Measure): the last segment
// (length, dx, dy, dz), the total length, the angle between the last two segments, and for three or
// more points the area and perimeter of the closed polygon.
struct MeasureReadout {
    int points = 0;
    double distance = 0, dx = 0, dy = 0, dz = 0; // the last segment
    double total = 0;                            // along the path
    std::optional<double> angle;                 // degrees, 0..180, between the last two segments
    std::optional<double> area, perimeter;       // closed polygon (m², m), from 3 points
};

// The measure tool (D79): click points, the path and its readout follow the mouse; Enter or a double
// click freezes it, Esc clears it. It never edits the model. Pure logic: the app feeds it snapped
// work-plane points (and the height of a surface under the mouse in 3D views).
class MeasureTool : public QObject {
    Q_OBJECT
public:
    explicit MeasureTool(QObject* parent = nullptr);

    Snapper& snapper() { return m_snapper; }
    void setTolerance(double metres) { m_tolerance = metres; }
    void setOrtho(bool ortho) { m_ortho = ortho; }

    // `p` on the work plane at height `z`; `surface`: a point on an element under the mouse (3D
    // views), used when no object snap is closer (Archicad snaps to faces).
    Snap move(QPointF p, double z, const std::optional<MeasurePoint>& surface = std::nullopt);
    void click(QPointF p, double z, const std::optional<MeasurePoint>& surface = std::nullopt);
    void finish(); // Enter / double click: stop following the mouse, keep the readout
    void clear();  // Esc: start again

    bool isMeasuring() const { return !m_points.isEmpty(); }
    bool isFinished() const { return m_finished; }
    const QVector<MeasurePoint>& points() const { return m_points; }
    std::optional<MeasurePoint> hover() const { return m_hover; }
    QVector<MeasurePoint> path() const; // the points plus the hover point while measuring

    static MeasureReadout compute(const QVector<MeasurePoint>& path);
    // One line for the bottom bar and the clipboard; `length` formats metres in the project's unit and
    // `area` square metres in the project's area unit (D92; empty: m²).
    static QString describe(const MeasureReadout& r, const std::function<QString(double)>& length,
        const std::function<QString(double)>& area = {});
    MeasureReadout readout() const { return compute(path()); }

signals:
    void changed();

private:
    MeasurePoint resolve(QPointF p, double z, const std::optional<MeasurePoint>& surface, Snap* snap) const;

    Snapper m_snapper;
    double m_tolerance = 0.1;
    bool m_ortho = false;
    bool m_finished = false;
    QVector<MeasurePoint> m_points;
    std::optional<MeasurePoint> m_hover;
};

} // namespace kimbim
