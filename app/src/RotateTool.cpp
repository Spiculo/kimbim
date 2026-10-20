// SPDX-License-Identifier: GPL-3.0-or-later
#include "RotateTool.h"

#include <cmath>

namespace kimbim {

namespace {

constexpr double kPi = 3.14159265358979323846;

double normalised(double a)
{
    while (a <= -kPi)
        a += 2 * kPi;
    while (a > kPi)
        a -= 2 * kPi;
    return a;
}

} // namespace

RotateTool::RotateTool(QObject* parent)
    : QObject(parent)
{
}

double RotateTool::angleTo(QPointF p) const
{
    const QPointF r = m_reference - m_centre, t = p - m_centre;
    const double raw = normalised(std::atan2(t.y(), t.x()) - std::atan2(r.y(), r.x()));
    const double step = m_ortho ? kPi / 2 : kPi / 12;
    const double snapped = std::round(raw / step) * step;
    return normalised(m_ortho || std::abs(raw - snapped) <= 3.0 * kPi / 180 ? snapped : raw);
}

void RotateTool::move(QPointF p)
{
    m_hover = m_stage < 2 ? m_snapper.snap(p, m_tolerance).point : p;
    if (m_stage == 2)
        m_angle = angleTo(p);
    emit previewChanged();
}

void RotateTool::click(QPointF p)
{
    const QPointF snapped = m_snapper.snap(p, m_tolerance).point;
    switch (m_stage) {
    case 0:
        m_centre = snapped;
        m_stage = 1;
        break;
    case 1:
        if (std::hypot(snapped.x() - m_centre.x(), snapped.y() - m_centre.y()) < 1e-3)
            return; // the reference needs a direction
        m_reference = snapped;
        m_angle = 0;
        m_stage = 2;
        break;
    default: {
        const double angle = angleTo(p);
        const QPointF centre = m_centre;
        cancel();
        emit rotationFinished(centre, angle);
        return;
    }
    }
    m_hover.reset();
    emit previewChanged();
}

bool RotateTool::typeAngle(double degrees)
{
    if (m_stage != 2)
        return false;
    const QPointF centre = m_centre;
    cancel();
    emit rotationFinished(centre, normalised(degrees * kPi / 180));
    return true;
}

void RotateTool::cancel()
{
    m_stage = 0;
    m_angle = 0;
    m_hover.reset();
    emit previewChanged();
}

} // namespace kimbim
