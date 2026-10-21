// SPDX-License-Identifier: GPL-3.0-or-later
#include "WallTool.h"

#include <cmath>

namespace kimbim {

namespace {
constexpr double kMinLength = 0.001; // metres: shorter segments (double clicks) are ignored
} // namespace

WallTool::WallTool(QObject* parent)
    : QObject(parent)
{
}

Snap WallTool::snapAt(QPointF p) const
{
    return m_drawing ? m_snapper.snap(p, m_tolerance, &m_start, m_ortho) : m_snapper.snap(p, m_tolerance);
}

Snap WallTool::move(QPointF p)
{
    const Snap s = snapAt(p);
    m_hover = s.point;
    emit previewChanged();
    return s;
}

void WallTool::setCurved(bool on)
{
    m_curved = on;
    m_end.reset();
    emit previewChanged();
}

QVector<QPointF> WallTool::arcPoints(QPointF a, QPointF through, QPointF b, int n)
{
    const double d = 2 * (a.x() * (through.y() - b.y()) + through.x() * (b.y() - a.y()) + b.x() * (a.y() - through.y()));
    if (std::abs(d) < 1e-12)
        return {a, b};
    auto sq = [](QPointF p) { return p.x() * p.x() + p.y() * p.y(); };
    const QPointF c((sq(a) * (through.y() - b.y()) + sq(through) * (b.y() - a.y()) + sq(b) * (a.y() - through.y())) / d,
        (sq(a) * (b.x() - through.x()) + sq(through) * (a.x() - b.x()) + sq(b) * (through.x() - a.x())) / d);
    const double r = std::hypot(a.x() - c.x(), a.y() - c.y());
    const double a0 = std::atan2(a.y() - c.y(), a.x() - c.x()), a2 = std::atan2(b.y() - c.y(), b.x() - c.x());
    const double cross = (through.x() - a.x()) * (b.y() - a.y()) - (through.y() - a.y()) * (b.x() - a.x());
    double sweep = a2 - a0;
    if (cross > 0) // counter-clockwise
        sweep = std::fmod(std::fmod(sweep, 2 * M_PI) + 2 * M_PI, 2 * M_PI);
    else
        sweep = -std::fmod(std::fmod(a0 - a2, 2 * M_PI) + 2 * M_PI, 2 * M_PI);
    QVector<QPointF> out;
    for (int i = 0; i <= n; ++i)
        out << c + QPointF(std::cos(a0 + sweep * i / n), std::sin(a0 + sweep * i / n)) * r;
    return out;
}

QVector<QPointF> WallTool::arcPreview() const
{
    if (!m_curved || !m_drawing || !m_end || !m_hover)
        return {};
    return arcPoints(m_start, *m_hover, *m_end);
}

void WallTool::click(QPointF p)
{
    const Snap s = snapAt(p);
    if (m_drawing && m_curved) { // D97: the end, then the point on the arc
        if (!m_end) {
            if (std::hypot(s.point.x() - m_start.x(), s.point.y() - m_start.y()) < kMinLength)
                return;
            m_end = s.point;
            emit previewChanged();
            return;
        }
        const QPointF end = *m_end;
        m_end.reset();
        WallSegment segment{m_start, end, QString(), QString(), s.point};
        m_start = end;
        m_startJoin.clear();
        m_lastWall.clear();
        emit wallRequested(segment);
        emit previewChanged();
        return;
    }
    if (!m_drawing) {
        m_drawing = true;
        m_start = s.point;
        m_startJoin = s.onWall() ? s.wallGuid : QString();
        m_lastWall.clear();
        m_hover.reset();
        emit previewChanged();
        return;
    }
    if (std::hypot(s.point.x() - m_start.x(), s.point.y() - m_start.y()) < kMinLength)
        return;
    request(s.point, s.onWall() ? s.wallGuid : QString());
}

bool WallTool::typeLength(double metres)
{
    if (!m_drawing || !m_hover || metres <= 0)
        return false;
    const QPointF d = *m_hover - m_start;
    const double length = std::hypot(d.x(), d.y());
    if (length < kMinLength)
        return false;
    request(m_start + d * (metres / length), QString());
    return true;
}

void WallTool::request(QPointF end, const QString& joinEnd)
{
    const WallSegment segment{m_start, end, m_lastWall.isEmpty() ? m_startJoin : m_lastWall, joinEnd};
    m_start = end;
    m_startJoin.clear();
    m_lastWall.clear(); // the receiver sets it while handling the request
    emit wallRequested(segment);
    emit previewChanged();
}

void WallTool::finish()
{
    const bool was = m_drawing;
    m_drawing = false;
    m_end.reset();
    m_hover.reset();
    m_startJoin.clear();
    m_lastWall.clear();
    emit previewChanged();
    if (was)
        emit finished();
}

std::optional<std::pair<QPointF, QPointF>> WallTool::preview() const
{
    if (!m_drawing || !m_hover)
        return std::nullopt;
    if (m_curved && m_end) // D97: the arc is previewed by arcPreview()
        return std::nullopt;
    return std::make_pair(m_start, *m_hover);
}

} // namespace kimbim
