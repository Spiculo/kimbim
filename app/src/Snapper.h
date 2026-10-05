// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonObject>
#include <QPointF>
#include <QString>
#include <QVector>

namespace kimcad {

// A wall's axis on the active level (from app_bridge.snap_data), in metres.
struct SnapWall {
    QString guid;
    QPointF a, b;
    double thickness = 0.0;
};

struct Snap {
    enum Kind { None, Endpoint, Midpoint, Perpendicular, OnWall, Angle, Grid };
    QPointF point;
    Kind kind = None;
    QString wallGuid; // the wall an object snap landed on
    bool onWall() const { return kind == Endpoint || kind == Midpoint || kind == Perpendicular || kind == OnWall; }
};

// Plan snapping for drawing tools (pure geometry, no view). Priority: wall endpoint > midpoint >
// perpendicular from the previous point > anywhere on a wall > angle (15 degree steps from the
// previous point; 0/90 with ortho) > grid.
class Snapper {
public:
    static QVector<SnapWall> parse(const QJsonObject& snapData);
    void setWalls(QVector<SnapWall> walls) { m_walls = std::move(walls); }
    const QVector<SnapWall>& walls() const { return m_walls; }
    void setGrid(double step) { m_grid = step; }
    double grid() const { return m_grid; }

    // `tolerance` in metres (the app converts ~10 screen pixels); `from` is the previous point.
    Snap snap(QPointF p, double tolerance, const QPointF* from = nullptr, bool ortho = false) const;

private:
    QPointF onGrid(QPointF p) const;
    double gridLength(double length) const;

    QVector<SnapWall> m_walls;
    double m_grid = 0.01; // 10 mm
};

} // namespace kimcad
