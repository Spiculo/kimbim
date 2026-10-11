// SPDX-License-Identifier: GPL-3.0-or-later
#include "InputAidsController.h"

#include "InputAidsOverlay.h"
#include "Snapper.h"
#include "Viewport.h"

#include <QKeyEvent>
#include <QLineF>

#include <cmath>

namespace kimcad {

namespace {

double cross(QPointF a, QPointF b)
{
    return a.x() * b.y() - a.y() * b.x();
}

// The guide line from `from` to the cursor, a little past it.
QLineF towards(QPointF from, QPointF to, double extra)
{
    const QPointF d = to - from;
    const double len = std::hypot(d.x(), d.y());
    return len > 1e-9 ? QLineF(from, to + d / len * extra) : QLineF(from, to);
}

} // namespace

InputAidsController::InputAidsController(Hooks hooks, QObject* parent)
    : QObject(parent)
    , m_hooks(std::move(hooks))
    , m_aids(std::make_shared<InputAids>())
{
    m_acquire.setSingleShot(true);
    m_acquire.setInterval(InputAids::kAcquireMs);
    connect(&m_acquire, &QTimer::timeout, this, [this] {
        if (m_aids->acquireHovered()) {
            emit guidesChanged();
            rerun();
        }
    });
}

void InputAidsController::attach(Viewport* v)
{
    v->installEventFilter(this);
    connect(v, &Viewport::workPointMoved, this,
        [this, v](QPointF p, double tolerance, Qt::KeyboardModifiers mods) { moved(v, p, tolerance, mods); });
    connect(v, &Viewport::drawingEnded, this, [this] { // Esc: the shape and its guides
        m_tracker.clear();
        m_aids->setLocks({});
        clearGuides();
    });
    connect(v, &QObject::destroyed, this, [this] { m_view.clear(); });
}

void InputAidsController::moved(Viewport* v, QPointF p, double tolerance, Qt::KeyboardModifiers mods)
{
    if (m_committing || tolerance < 0)
        return;
    if (m_view && m_view != v)
        hide(m_view);
    m_view = v;
    m_raw = p;
    m_tolerance = tolerance;
    m_mods = mods;
    m_hasPointer = true;
    if (!m_hooks.active || !m_hooks.active()) {
        hide(v);
        return;
    }
    // The tool snapped during this move: its anchor (the previous point) and the snapped point.
    const bool snapped = m_aids->serial() != m_serial;
    m_serial = m_aids->serial();
    m_tracker.setAnchor(snapped ? m_aids->lastFrom() : std::nullopt);
    m_tracker.setCursor(snapped ? m_aids->lastPoint() : p);
    if (snapped && m_aids->hovered() && m_aids->guidesEnabled())
        m_acquire.start();
    else if (!m_aids->hovered())
        m_acquire.stop();
    refresh();
}

void InputAidsController::rerun()
{
    if (m_view && m_hasPointer)
        emit m_view->workPointMoved(m_raw, m_tolerance, m_mods);
}

void InputAidsController::inputChanged()
{
    m_aids->setLocks(m_tracker.locks());
    m_serial = -1;
    rerun();
    refresh();
}

void InputAidsController::refresh()
{
    Viewport* v = m_view;
    if (!v)
        return;
    if (!m_hooks.active || !m_hooks.active() || !v->isDrawingMode()) {
        hide(v);
        return;
    }
    const double z = m_hooks.planZ ? m_hooks.planZ() : 0.0;
    // Guides: the acquired points, and the guide lines the cursor is on.
    QVector<QPointF> points;
    for (const auto& g : m_aids->guides())
        points << g.at;
    QVector<QLineF> lines;
    const QPointF c = m_tracker.cursor();
    const auto anchor = m_tracker.anchor();
    const double extra = std::max(0.3, 3 * m_tolerance);
    const int kind = m_aids->lastKind();
    if (kind == Snap::GuideLine || kind == Snap::GuideCross) {
        for (const auto& g : m_aids->guides()) {
            QVector<QPointF> dirs{QPointF(1, 0), QPointF(0, 1)};
            if (g.direction)
                dirs << *g.direction;
            for (const QPointF& d : dirs)
                if (std::abs(cross(c - g.at, d)) < 1e-6 && std::hypot(c.x() - g.at.x(), c.y() - g.at.y()) > 1e-9) {
                    lines << towards(g.at, c, extra);
                    break;
                }
        }
        if (anchor && kind == Snap::GuideCross
            && (std::abs(c.x() - anchor->x()) < 1e-6 || std::abs(c.y() - anchor->y()) < 1e-6))
            lines << towards(*anchor, c, extra);
    } else if (anchor && (kind == Snap::Parallel || (kind == Snap::Tracked && m_aids->locks().angle))) {
        lines << towards(*anchor, c, extra);
    }
    if (points.isEmpty() && lines.isEmpty())
        v->setAidOverlay(Viewport::AidOverlay::Guides, {});
    else
        v->setAidOverlay(Viewport::AidOverlay::Guides, new GuidesOverlay(points, lines, std::max(0.05, 0.6 * m_tolerance), z));

    // The tracker beside the cursor.
    QVector<TrackerOverlay::Box> boxes;
    for (const Tracker::Field f : m_tracker.fields()) {
        const bool typed = !m_tracker.typed(f).isEmpty();
        QString label;
        switch (f) {
        case Tracker::Length:
            label = QStringLiteral("L ");
            break;
        case Tracker::Angle:
            label = QStringLiteral("A ");
            break;
        case Tracker::X:
            label = m_tracker.absolute() ? QStringLiteral("X ") : QStringLiteral("dx ");
            break;
        case Tracker::Y:
            label = m_tracker.absolute() ? QStringLiteral("Y ") : QStringLiteral("dy ");
            break;
        }
        QString value = typed ? m_tracker.typed(f) : QString::number(m_tracker.live(f), 'f', f == Tracker::Angle ? 1 : 3);
        if (f == Tracker::Angle)
            value += QChar(0x00B0);
        boxes.push_back({label + value, m_tracker.focus() == f, typed});
    }
    const double ratio = v->devicePixelRatioF();
    QPoint at(int(16 * ratio), int(16 * ratio));
    if (!v->view()->Window().IsNull()) { // beside the cursor's point, below right
        int px = 0, py = 0;
        v->view()->Convert(c.x(), c.y(), z, px, py);
        int w = 0, h = 0;
        v->view()->Window()->Size(w, h);
        at = QPoint(px + int(18 * ratio), h - py - int(36 * ratio));
    }
    v->setAidOverlay(Viewport::AidOverlay::Tracker, new TrackerOverlay(boxes, at, ratio));
    m_trackerShown = true;
}

void InputAidsController::hide(Viewport* v)
{
    if (!v)
        return;
    if (v->hasAidOverlay(Viewport::AidOverlay::Guides))
        v->setAidOverlay(Viewport::AidOverlay::Guides, {});
    if (v->hasAidOverlay(Viewport::AidOverlay::Tracker))
        v->setAidOverlay(Viewport::AidOverlay::Tracker, {});
    m_trackerShown = false;
}

bool InputAidsController::isTrackerKey(const QKeyEvent* e) const
{
    if (e->modifiers() & (Qt::ControlModifier | Qt::AltModifier | Qt::MetaModifier))
        return false;
    switch (e->key()) {
    case Qt::Key_Tab:
    case Qt::Key_Backtab:
        return true;
    case Qt::Key_Return:
    case Qt::Key_Enter:
    case Qt::Key_Escape:
    case Qt::Key_Backspace:
        return m_tracker.hasInput();
    default:
        break;
    }
    const QString text = e->text();
    if (text.size() != 1)
        return false;
    const QChar c = text.at(0);
    if (c.isDigit() || QStringLiteral(".,-<;#@").contains(c))
        return true;
    return (c == QLatin1Char('a') || c == QLatin1Char('A')) && m_tracker.hasInput();
}

bool InputAidsController::eventFilter(QObject* watched, QEvent* event)
{
    if (event->type() != QEvent::KeyPress && event->type() != QEvent::ShortcutOverride)
        return false;
    auto* v = qobject_cast<Viewport*>(watched);
    if (!v || !v->isDrawingMode() || !m_hooks.active || !m_hooks.active())
        return false;
    auto* e = static_cast<QKeyEvent*>(event);
    if (!isTrackerKey(e))
        return false;
    if (event->type() == QEvent::ShortcutOverride) { // a digit is a value here, not the "3" shortcut
        e->accept();
        return true;
    }
    if (m_view != v) {
        hide(m_view);
        m_view = v;
    }
    switch (e->key()) {
    case Qt::Key_Return:
    case Qt::Key_Enter:
        commit(v);
        return true;
    case Qt::Key_Escape:
        m_tracker.clear();
        inputChanged();
        return true;
    default:
        m_tracker.key(e->key(), e->text(), e->modifiers());
        inputChanged();
        return true;
    }
}

bool InputAidsController::commit(Viewport* v)
{
    bool done = m_hooks.classic && m_hooks.classic(m_tracker);
    if (!done) {
        const auto target = m_tracker.target();
        if (target) {
            m_aids->setLocks({});
            m_committing = true;
            emit v->workPointMoved(*target, -1.0, Qt::NoModifier);
            emit v->workPointClicked(*target, -1.0, Qt::NoModifier);
            m_committing = false;
            done = true;
        }
    }
    m_tracker.clear();
    m_aids->setLocks({});
    m_serial = -1;
    rerun(); // the tool's tolerance and preview from the mouse again
    refresh();
    return done;
}

void InputAidsController::reset()
{
    m_tracker.clear();
    m_aids->setLocks({});
    m_aids->clearGuides();
    m_acquire.stop();
    m_hasPointer = false;
    hide(m_view);
}

void InputAidsController::clearGuides()
{
    m_aids->clearGuides();
    m_acquire.stop();
    emit guidesChanged();
    refresh();
}

void InputAidsController::setGuidesEnabled(bool on)
{
    m_aids->setGuidesEnabled(on);
    m_acquire.stop();
    emit guidesChanged();
    refresh();
}

} // namespace kimcad
