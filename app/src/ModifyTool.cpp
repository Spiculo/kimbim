// SPDX-License-Identifier: GPL-3.0-or-later
#include "ModifyTool.h"

#include <QJsonArray>

#include <algorithm>
#include <cmath>
#include <limits>

namespace kimbim {

namespace {

double distanceToSegment(QPointF p, QPointF a, QPointF b, double* t = nullptr)
{
    const QPointF d = b - a;
    const double len2 = d.x() * d.x() + d.y() * d.y();
    double u = len2 > 0 ? ((p.x() - a.x()) * d.x() + (p.y() - a.y()) * d.y()) / len2 : 0.0;
    u = std::clamp(u, 0.0, 1.0);
    if (t)
        *t = u;
    const QPointF q = a + d * u;
    return std::hypot(p.x() - q.x(), p.y() - q.y());
}

} // namespace

ModifyTool::ModifyTool(QObject* parent)
    : QObject(parent)
{
}

void ModifyTool::setTargets(const QJsonObject& snapData, const QJsonObject& beams)
{
    m_targets.clear();
    for (const SnapWall& w : Snapper::parse(snapData))
        m_targets.push_back({w.guid, QStringLiteral("wall"), w.a, w.b, w.thickness});
    for (const auto& v : beams.value("beams").toArray()) {
        const QJsonObject o = v.toObject();
        m_targets.push_back({o.value("guid").toString(), QStringLiteral("beam"),
            QPointF(o.value("x1").toDouble(), o.value("y1").toDouble()),
            QPointF(o.value("x2").toDouble(), o.value("y2").toDouble()), o.value("width").toDouble()});
    }
    for (const SnapLine& l : Snapper::parseGrid(snapData))
        m_targets.push_back({QString(), QStringLiteral("grid"), l.a, l.b, 0.0});
}

void ModifyTool::setMode(Mode mode)
{
    m_mode = mode;
    cancel();
}

std::optional<ModifyTool::Target> ModifyTool::pick(QPointF p, bool boundary) const
{
    std::optional<Target> best;
    double bestDistance = std::numeric_limits<double>::max();
    for (const Target& t : m_targets) {
        if (t.kind == QLatin1String("grid") && !boundary)
            continue;
        const double d = distanceToSegment(p, t.a, t.b);
        // Elements are picked anywhere on their footprint; grid lines near the line.
        const double reach = t.width / 2 + m_tolerance;
        if (d <= reach && d - t.width / 2 < bestDistance) {
            bestDistance = d - t.width / 2;
            best = t;
        }
    }
    return best;
}

QPointF ModifyTool::onAxis(const Target& t, QPointF p) const
{
    // A snapped point (end, middle, crossing) projected onto the element's axis.
    const QPointF s = m_snapper.snap(p, m_tolerance).point;
    double u = 0;
    distanceToSegment(s, t.a, t.b, &u);
    return t.a + (t.b - t.a) * u;
}

void ModifyTool::move(QPointF p)
{
    const bool boundary = m_mode == Mode::Trim && !m_first;
    m_hover = pick(p, boundary);
    m_splitPoint.reset();
    if (m_hover && m_mode == Mode::Split)
        m_splitPoint = onAxis(*m_hover, p);
    emit previewChanged();
}

void ModifyTool::click(QPointF p, Qt::KeyboardModifiers mods)
{
    const bool join = !(mods & Qt::ControlModifier);
    const bool boundary = m_mode == Mode::Trim && !m_first;
    const std::optional<Target> t = pick(p, boundary);
    if (!t)
        return;
    switch (m_mode) {
    case Mode::Split:
        emit splitRequested(t->guid, onAxis(*t, p), join);
        break;
    case Mode::Trim:
        if (!m_first) {
            m_first = t;
            m_firstPoint = p;
        } else if (t->guid != m_first->guid || t->kind != m_first->kind) {
            // The boundary stays picked: click the next element to trim or extend (Esc: a new boundary).
            emit trimRequested(t->guid, p, m_first->guid, m_first->a, m_first->b, join);
        }
        break;
    case Mode::Corner:
    case Mode::Join:
    case Mode::Unjoin:
        if (!m_first) {
            m_first = t;
            m_firstPoint = p;
        } else if (t->guid != m_first->guid) {
            const Target first = *m_first;
            const QPointF firstPoint = m_firstPoint;
            m_first.reset();
            if (m_mode == Mode::Corner)
                emit cornerRequested(first.guid, firstPoint, t->guid, p, join);
            else if (m_mode == Mode::Join)
                emit joinRequested(first.guid, t->guid);
            else
                emit unjoinRequested(first.guid, t->guid);
        }
        break;
    }
    emit previewChanged();
}

void ModifyTool::cancel()
{
    m_first.reset();
    m_hover.reset();
    m_splitPoint.reset();
    emit previewChanged();
}

QString ModifyTool::hint() const
{
    switch (m_mode) {
    case Mode::Split:
        return tr("Split: click a wall or beam where it splits (Ctrl: leave the pieces unjoined)");
    case Mode::Trim:
        return m_first ? tr("Trim/extend: click the walls or beams to trim or extend, on the side to keep (Ctrl: don't join; Esc: new boundary)")
                       : tr("Trim/extend: click the boundary (a wall, beam or grid line)");
    case Mode::Corner:
        return m_first ? tr("Corner: click the second wall or beam, on the side to keep (Ctrl: don't join)")
                       : tr("Corner: click the first wall or beam, on the side to keep");
    case Mode::Join:
        return m_first ? tr("Join: click the second wall (in line and of the same type: they merge)")
                       : tr("Join: click the first wall or beam");
    case Mode::Unjoin:
        return m_first ? tr("Unjoin: click the second wall") : tr("Unjoin: click the first of two joined walls");
    }
    return {};
}

} // namespace kimbim
