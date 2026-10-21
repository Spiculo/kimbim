// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QMetaType>
#include <QObject>
#include <QPointF>
#include <QVector>

#include <optional>

#include "Snapper.h"

namespace kimbim {

// Where a door/window goes: the wall, its centre's distance from the wall axis start (metres), the
// centre point on the axis and the wall direction (radians).
struct Host {
    QString wallGuid;
    double along = 0;
    QPointF centre; // the opening's middle on the wall body (plan, metres)
    double angle = 0;
    double thickness = 0;
};

// Places hosted elements (doors, windows) in walls: the wall under the cursor, the position along
// it rounded to the grid and kept so the opening fits inside the wall. Pure logic.
class HostTool : public QObject {
    Q_OBJECT
public:
    explicit HostTool(QObject* parent = nullptr);

    static std::optional<Host> locate(const QVector<SnapWall>& walls, QPointF p, double width, double tolerance,
        double grid = 0.01);

    void setWalls(QVector<SnapWall> walls) { m_walls = std::move(walls); }
    void setWidth(double metres) { m_width = metres; }
    double width() const { return m_width; }
    void setTolerance(double metres) { m_tolerance = metres; }
    std::optional<Host> move(QPointF p);
    void click(QPointF p);
    std::optional<Host> hover() const { return m_hover; }

signals:
    void openingRequested(const kimbim::Host& host);
    void previewChanged();

private:
    QVector<SnapWall> m_walls;
    double m_width = 0.9;
    double m_tolerance = 0.1;
    std::optional<Host> m_hover;
};

} // namespace kimbim

Q_DECLARE_METATYPE(kimbim::Host)
