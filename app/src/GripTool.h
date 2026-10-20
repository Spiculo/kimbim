// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QObject>
#include <QPointF>

#include <optional>
#include <utility>

#include "Snapper.h"

namespace kimbim {

// Stretch a wall: click near one of its ends to grab it, click again where it should go (snapped
// from the end that stays, so angles and grid points work), or type the new length. Pure logic.
class GripTool : public QObject {
    Q_OBJECT
public:
    explicit GripTool(QObject* parent = nullptr);

    Snapper& snapper() { return m_snapper; }
    void setTolerance(double metres) { m_tolerance = metres; }
    void setOrtho(bool ortho) { m_ortho = ortho; }
    bool isDragging() const { return !m_wall.isEmpty(); }
    double thickness() const { return m_thickness; }

    void move(QPointF p);
    void click(QPointF p);
    bool typeLength(double metres);
    void cancel();
    // The wall's new axis (start, end) while dragging.
    std::optional<std::pair<QPointF, QPointF>> preview() const;

signals:
    void stretchRequested(const QString& wall, QPointF p1, QPointF p2);
    void previewChanged();

private:
    QPointF target(QPointF p) const;
    void finish(QPointF moving);

    Snapper m_snapper;
    double m_tolerance = 0.1;
    bool m_ortho = false;
    QString m_wall;
    bool m_movingStart = false;
    QPointF m_fixed, m_original;
    double m_thickness = 0;
    std::optional<QPointF> m_hover;
};

} // namespace kimbim
