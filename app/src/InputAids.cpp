// SPDX-License-Identifier: GPL-3.0-or-later
#include "InputAids.h"

#include <cmath>

namespace kimcad {

namespace {
bool same(QPointF a, QPointF b)
{
    return std::hypot(a.x() - b.x(), a.y() - b.y()) < 1e-9;
}
} // namespace

void InputAids::setGuidesEnabled(bool on)
{
    m_enabled = on;
    if (!on)
        clearGuides();
}

void InputAids::clearGuides()
{
    m_guides.clear();
    m_hover.reset();
    m_hoverUsed = false;
}

void InputAids::hover(const std::optional<Guide>& point)
{
    if (point && m_hover && same(point->at, m_hover->at))
        return; // still resting on it
    m_hover = point;
    m_hoverUsed = false;
}

bool InputAids::acquireHovered()
{
    if (!m_enabled || !m_hover || m_hoverUsed)
        return false;
    m_hoverUsed = true;
    for (int i = 0; i < m_guides.size(); ++i)
        if (same(m_guides[i].at, m_hover->at)) { // hovering an acquired point again releases it
            m_guides.removeAt(i);
            return true;
        }
    acquire(*m_hover);
    return true;
}

void InputAids::acquire(const Guide& g)
{
    if (!m_enabled)
        return;
    if (m_guides.size() >= kMaxGuides)
        m_guides.removeFirst();
    m_guides.push_back(g);
}

void InputAids::record(const std::optional<QPointF>& from, QPointF point, int kind)
{
    ++m_serial;
    m_from = from;
    m_point = point;
    m_kind = kind;
}

} // namespace kimcad
