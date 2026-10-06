// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QObject>
#include <QPointF>

#include <optional>
#include <utility>

#include "Snapper.h"

namespace kimcad {

// One segment from two snapped clicks (beams, grid lines, the move tool's base and target).
// A typed length places the second point along the mouse direction. Pure logic.
class TwoPointTool : public QObject {
    Q_OBJECT
public:
    explicit TwoPointTool(QObject* parent = nullptr);

    Snapper& snapper() { return m_snapper; }
    void setTolerance(double metres) { m_tolerance = metres; }
    double tolerance() const { return m_tolerance; }
    void setOrtho(bool ortho) { m_ortho = ortho; }
    bool isDrawing() const { return m_start.has_value(); }
    std::optional<QPointF> start() const { return m_start; }

    Snap move(QPointF p);
    void click(QPointF p);
    bool typeLength(double metres);
    void cancel();
    std::optional<std::pair<QPointF, QPointF>> preview() const;
    std::optional<QPointF> hover() const { return m_hover; }

signals:
    void segmentFinished(QPointF p1, QPointF p2);
    void previewChanged();

private:
    Snap snapAt(QPointF p) const;

    Snapper m_snapper;
    double m_tolerance = 0.1;
    bool m_ortho = false;
    std::optional<QPointF> m_start;
    std::optional<QPointF> m_hover;
};

} // namespace kimcad
