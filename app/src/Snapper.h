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

// A grid axis (from app_bridge.snap_data "grid"), in metres.
struct SnapLine {
    QString guid, tag;
    QPointF a, b;
};

struct Snap {
    enum Kind { None, Endpoint, Midpoint, Perpendicular, OnWall, Angle, Grid, GridCross, GridLine, FaceEnd, OnFace };
    QPointF point;
    Kind kind = None;
    QString wallGuid; // the wall an object snap landed on
    bool onWall() const { return kind == Endpoint || kind == Midpoint || kind == Perpendicular || kind == OnWall; }
};

// Plan snapping for drawing tools (pure geometry, no view). Priority: wall endpoint > grid-axis
// crossing > midpoint > perpendicular from the previous point > anywhere on a wall > anywhere on a
// grid axis > angle (15 degree steps from the previous point; 0/90 with ortho) > grid.
class Snapper {
public:
    static QVector<SnapWall> parse(const QJsonObject& snapData);
    static QVector<SnapLine> parseGrid(const QJsonObject& snapData);
    void setGridLines(QVector<SnapLine> lines) { m_lines = std::move(lines); }
    const QVector<SnapLine>& gridLines() const { return m_lines; }
    void setWalls(QVector<SnapWall> walls) { m_walls = std::move(walls); }
    const QVector<SnapWall>& walls() const { return m_walls; }
    void setGrid(double step) { m_grid = step; }
    // Wall faces (axis +- half the thickness) as snap targets: their corners after the axis ends,
    // anywhere along them before "on wall". For dimensions (Slice 15), off by default.
    void setFaceSnapping(bool on) { m_faces = on; }
    bool faceSnapping() const { return m_faces; }
    double grid() const { return m_grid; }

    // `tolerance` in metres (the app converts ~10 screen pixels); `from` is the previous point.
    Snap snap(QPointF p, double tolerance, const QPointF* from = nullptr, bool ortho = false) const;

private:
    QPointF onGrid(QPointF p) const;
    double gridLength(double length) const;

    QVector<SnapWall> m_walls;
    QVector<SnapLine> m_lines;
    double m_grid = 0.01; // 10 mm
    bool m_faces = false;
};

} // namespace kimcad
