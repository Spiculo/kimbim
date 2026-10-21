// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QMetaType>
#include <QObject>
#include <QPointF>

#include <optional>
#include <utility>

#include "Snapper.h"

namespace kimbim {

// One wall to create: axis from p1 to p2 (metres, on the active level) and the walls to join at
// each end (empty: none).
struct WallSegment {
    QPointF p1, p2;
    QString joinStart, joinEnd;
    std::optional<QPointF> through; // D97: a curved wall's point on its arc
};

// Draws walls as a click-click polyline (pure logic: the viewport feeds it points on the level's
// work plane). Every click after the first requests a wall from the previous point; the chain joins
// each wall to the previous one, and ends that land on existing walls join them (L or T).
// A typed length places the next point along the current mouse direction.
class WallTool : public QObject {
    Q_OBJECT
public:
    explicit WallTool(QObject* parent = nullptr);

    Snapper& snapper() { return m_snapper; }
    void setTolerance(double metres) { m_tolerance = metres; }
    void setOrtho(bool ortho) { m_ortho = ortho; }
    bool isDrawing() const { return m_drawing; }

    Snap move(QPointF p);
    void click(QPointF p);
    bool typeLength(double metres);
    void finish();
    void cancel() { finish(); }
    // The app reports the wall it created for the last request, so the next one joins it.
    void setLastWall(const QString& guid) { m_lastWall = guid; }
    std::optional<std::pair<QPointF, QPointF>> preview() const;
    // D97: Archicad's Curved geometry method: start, end, then a point on the arc (the end starts the
    // next wall of the chain).
    void setCurved(bool on);
    bool curved() const { return m_curved; }
    // The curved wall being drawn, as points along its arc (empty unless both ends are placed).
    QVector<QPointF> arcPreview() const;
    // Points along the arc from `a` through `through` to `b` (`n` segments); just a and b if in a line.
    static QVector<QPointF> arcPoints(QPointF a, QPointF through, QPointF b, int n = 24);

signals:
    void wallRequested(const kimbim::WallSegment& segment);
    void previewChanged();
    void finished();

private:
    Snap snapAt(QPointF p) const;
    void request(QPointF end, const QString& joinEnd);

    Snapper m_snapper;
    double m_tolerance = 0.1;
    bool m_ortho = false;
    bool m_drawing = false;
    QPointF m_start;
    QString m_startJoin; // wall under the first click of the chain
    QString m_lastWall;  // wall created by the previous segment
    std::optional<QPointF> m_hover;
    bool m_curved = false;
    std::optional<QPointF> m_end; // D97: a curved wall's end, waiting for its point on the arc
};

} // namespace kimbim

Q_DECLARE_METATYPE(kimbim::WallSegment)
