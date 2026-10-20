// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QObject>
#include <QPointF>

#include <optional>

#include "Snapper.h"

namespace kimbim {

// Rotation by three clicks: the centre, a reference direction, then the target direction. The
// angle snaps to 15 degree steps when close (always to 90 with ortho); a typed angle in degrees
// finishes it. Pure logic.
class RotateTool : public QObject {
    Q_OBJECT
public:
    explicit RotateTool(QObject* parent = nullptr);

    Snapper& snapper() { return m_snapper; }
    void setTolerance(double metres) { m_tolerance = metres; }
    void setOrtho(bool ortho) { m_ortho = ortho; }
    int stage() const { return m_stage; } // 0: centre, 1: reference, 2: target
    double currentAngle() const { return m_angle; }
    std::optional<QPointF> centre() const { return m_stage > 0 ? std::optional<QPointF>(m_centre) : std::nullopt; }
    std::optional<QPointF> reference() const { return m_stage > 1 ? std::optional<QPointF>(m_reference) : std::nullopt; }
    std::optional<QPointF> hover() const { return m_hover; }

    void move(QPointF p);
    void click(QPointF p);
    bool typeAngle(double degrees);
    void cancel();

signals:
    void rotationFinished(QPointF centre, double radians);
    void previewChanged();

private:
    double angleTo(QPointF p) const;

    Snapper m_snapper;
    double m_tolerance = 0.1;
    bool m_ortho = false;
    int m_stage = 0;
    QPointF m_centre, m_reference;
    double m_angle = 0;
    std::optional<QPointF> m_hover;
};

} // namespace kimbim
