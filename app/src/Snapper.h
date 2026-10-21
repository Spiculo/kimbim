// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonObject>
#include <QPointF>
#include <QString>
#include <QVector>

#include <memory>
#include <optional>

namespace kimbim {

class InputAids;
class UnderlaySnapIndex;

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

// A point of a 2D drafting shape (D84, from app_bridge.snap_data "points"): an end or corner, the
// middle of a segment, or a circle's or arc's centre.
struct SnapPoint {
    QPointF p;
    int kind = 1; // Snap::Endpoint, Snap::Midpoint or Snap::Centre
    QString guid;
};

struct Snap {
    enum Kind { None, Endpoint, Midpoint, Perpendicular, OnWall, Angle, Grid, GridCross, GridLine, FaceEnd, OnFace, Centre,
        UnderlayEnd, UnderlayMid, UnderlayCross, OnUnderlay, // D85: DXF underlay linework
        Intersection, GuideCross, GuideLine, Parallel, Tracked, Typed }; // D89: input aids
    QPointF point;
    Kind kind = None;
    QString wallGuid; // the wall an object snap landed on
    bool onWall() const { return kind == Endpoint || kind == Midpoint || kind == Perpendicular || kind == OnWall; }
};

// Plan snapping for drawing tools (pure geometry, no view). Priority: wall endpoint > grid-axis
// crossing > midpoint > perpendicular from the previous point > anywhere on a wall > anywhere on a
// grid axis > angle (15 degree steps from the previous point; 0/90 with ortho) > grid. D85: underlay
// endpoints, crossings and midpoints come after wall midpoints, anywhere on an underlay line after
// anywhere on a wall. D89: wall/grid crossings after grid crossings; with shared InputAids, tracker
// locks override everything, temporary-guide crossings come after the underlay points, guide lines
// and parallels after "on wall". A negative tolerance is an exact (typed) point: no snapping, only
// the wall it lies on (for joins).
class Snapper {
public:
    static QVector<SnapWall> parse(const QJsonObject& snapData);
    static QVector<SnapLine> parseGrid(const QJsonObject& snapData);
    static QVector<SnapPoint> parsePoints(const QJsonObject& snapData);
    // Drafting shapes' points (D84): ends with the wall ends, middles with the wall middles, centres next.
    void setPoints(QVector<SnapPoint> points) { m_points = std::move(points); }
    const QVector<SnapPoint>& points() const { return m_points; }
    void setGridLines(QVector<SnapLine> lines) { m_lines = std::move(lines); }
    const QVector<SnapLine>& gridLines() const { return m_lines; }
    void setWalls(QVector<SnapWall> walls) { m_walls = std::move(walls); }
    const QVector<SnapWall>& walls() const { return m_walls; }
    void setGrid(double step) { m_grid = step; }
    // D98: grid snap (Archicad's construction grid): a point no object snap takes rounds to the grid's
    // nodes, `step` apart along axes turned `angle` radians about `origin`, instead of 15 degree steps
    // and the 10 mm grid. A step of 0 turns it off. Lengths along guides and angles keep 10 mm.
    void setSnapGrid(QPointF origin, double angle, double step)
    {
        m_gridOrigin = origin;
        m_gridAngle = angle;
        m_snapStep = step;
    }
    double snapGridStep() const { return m_snapStep; }
    // D85: the active level's DXF underlay linework (shared by every tool's snapper); null: none.
    void setUnderlays(std::shared_ptr<const UnderlaySnapIndex> index) { m_underlays = std::move(index); }
    const std::shared_ptr<const UnderlaySnapIndex>& underlays() const { return m_underlays; }
    // Wall faces (axis +- half the thickness) as snap targets: their corners after the axis ends,
    // anywhere along them before "on wall". For dimensions (Slice 15), off by default.
    void setFaceSnapping(bool on) { m_faces = on; }
    bool faceSnapping() const { return m_faces; }
    double grid() const { return m_grid; }
    // D89: the window's shared input aids (guides, tracker locks, last snap); null: none.
    void setAids(std::shared_ptr<InputAids> aids) { m_aids = std::move(aids); }
    const std::shared_ptr<InputAids>& aids() const { return m_aids; }

    // `tolerance` in metres (the app converts ~10 screen pixels); `from` is the previous point.
    Snap snap(QPointF p, double tolerance, const QPointF* from = nullptr, bool ortho = false) const;

private:
    Snap compute(QPointF p, double tolerance, const QPointF* from, bool ortho) const;
    bool guideSnap(QPointF p, double tolerance, const QPointF* from, bool lines, Snap* out) const;
    std::optional<QPointF> wallDirection(const QString& guid) const;
    QPointF onGrid(QPointF p) const;
    double gridLength(double length) const;

    QVector<SnapWall> m_walls;
    QVector<SnapLine> m_lines;
    QVector<SnapPoint> m_points;
    double m_grid = 0.01; // 10 mm
    QPointF m_gridOrigin{0, 0};
    double m_gridAngle = 0.0;
    double m_snapStep = 0.0; // D98: grid snap off
    bool m_faces = false;
    std::shared_ptr<const UnderlaySnapIndex> m_underlays;
    std::shared_ptr<InputAids> m_aids;
};

} // namespace kimbim
