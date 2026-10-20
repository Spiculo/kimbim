// SPDX-License-Identifier: GPL-3.0-or-later
// D89: the view's part of the input aids: their overlays, Tab cycling through overlapping elements,
// touchpad navigation (two-finger scroll, pinch).
#include "Viewport.h"

#include <QElapsedTimer>
#include <QMouseEvent>
#include <QNativeGestureEvent>
#include <QWheelEvent>

#include <Graphic3d_Camera.hxx>

#include <cmath>

namespace kimbim {

namespace {
Viewport::ScrollMode g_scrollMode = Viewport::ScrollMode::Auto;
QElapsedTimer g_touchpadSeen; // a touchpad scroll stream keeps panning even when one event looks like a wheel
} // namespace

void Viewport::setAidOverlay(AidOverlay which, const Handle(AIS_InteractiveObject)& overlay)
{
    const int key = int(which);
    if (const auto it = m_aidOverlays.constFind(key); it != m_aidOverlays.constEnd()) {
        m_context->Remove(*it, false);
        m_aidOverlays.remove(key);
    }
    if (!overlay.IsNull()) {
        m_context->Display(overlay, 0, -1, false); // shown, never selectable
        keepHere(overlay);
        m_aidOverlays.insert(key, overlay);
    }
    update();
}

// --- Tab cycling ---

QStringList Viewport::elementsAt(const QPointF& widgetPos)
{
    if (m_pickProvider)
        return m_pickProvider(widgetPos);
    QStringList out;
    if (!ensureWindow())
        return out;
    const NCollection_Vec2<int> px = toPixels(widgetPos);
    m_context->MoveTo(px.x(), px.y(), m_view, false);
    for (m_context->InitDetected(); m_context->MoreDetected(); m_context->NextDetected()) {
        Handle(ElementOwner) owner = Handle(ElementOwner)::DownCast(m_context->DetectedCurrentOwner());
        if (owner.IsNull() || !owner->batch())
            continue; // the view cube, notes
        const QString guid = owner->batch()->guid(owner->index());
        if (!out.contains(guid) && !isLocked(guid))
            out << guid;
    }
    return out;
}

QString Viewport::cycleNext(const QPointF& widgetPos, bool backwards)
{
    const bool samePlace = !m_cycleList.isEmpty() && (widgetPos - m_cyclePos).manhattanLength() <= 4;
    if (!samePlace) {
        m_cycleList = elementsAt(widgetPos);
        m_cyclePos = widgetPos;
        m_cycleIndex = 0; // the first is what hovering already shows; Tab goes on from there
    }
    if (m_cycleList.isEmpty()) {
        m_cycleGuid.clear();
        return {};
    }
    const int n = int(m_cycleList.size());
    m_cycleIndex = ((m_cycleIndex + (backwards ? -1 : 1)) % n + n) % n;
    m_cycleGuid = m_cycleList[m_cycleIndex];
    highlightCycled();
    return m_cycleGuid;
}

void Viewport::highlightCycled()
{
    if (m_pickProvider || m_view->Window().IsNull())
        return;
    // Walk OCCT's detected owners (front to back) until the cycled element is the highlighted one.
    const NCollection_Vec2<int> px = toPixels(m_cyclePos);
    m_context->MoveTo(px.x(), px.y(), m_view, false);
    for (int i = 0; i < 64; ++i) {
        Handle(ElementOwner) owner = Handle(ElementOwner)::DownCast(m_context->DetectedOwner());
        if (!owner.IsNull() && owner->batch() && owner->batch()->guid(owner->index()) == m_cycleGuid)
            break;
        if (m_context->HilightNextDetected(m_view, false) <= 0)
            break;
    }
    update();
}

bool Viewport::cycleClick(QMouseEvent* e)
{
    if (m_cycleGuid.isEmpty() || m_drawingMode || e->button() != Qt::LeftButton
        || (e->position() - m_cyclePos).manhattanLength() > 4)
        return false;
    const QString guid = std::exchange(m_cycleGuid, QString());
    m_cycleList.clear();
    // The click's selection modifiers (D48): plain replaces, Ctrl adds, Shift toggles.
    QStringList selection = selectedGuids();
    if (e->modifiers() & Qt::ShiftModifier) {
        if (!selection.removeAll(guid))
            selection << guid;
    } else if (e->modifiers() & Qt::ControlModifier) {
        if (!selection.contains(guid))
            selection << guid;
    } else {
        selection = {guid};
    }
    selectGuids(selection);
    emit selectionChanged(selectedGuids());
    m_cycleClick = true;
    return true;
}

// --- Touchpad ---

void Viewport::setScrollMode(ScrollMode mode)
{
    g_scrollMode = mode;
}

Viewport::ScrollMode Viewport::scrollMode()
{
    return g_scrollMode;
}

Viewport::ScrollMode Viewport::scrollModeFrom(const QString& preference)
{
    if (preference == QLatin1String("zoom"))
        return ScrollMode::Zoom;
    if (preference == QLatin1String("pan"))
        return ScrollMode::Pan;
    return ScrollMode::Auto;
}

bool Viewport::touchpadScroll(QWheelEvent* e)
{
    if (g_scrollMode == ScrollMode::Zoom || (e->modifiers() & Qt::ControlModifier))
        return false; // a mouse wheel, or Ctrl+scroll / Windows' pinch (sent as Ctrl+wheel): zoom
    bool touchpad = g_scrollMode == ScrollMode::Pan;
    if (!touchpad) { // Auto: what a touchpad sends and a notched wheel does not
        touchpad = !e->pixelDelta().isNull() || e->angleDelta().x() != 0 || e->phase() != Qt::NoScrollPhase
            || (g_touchpadSeen.isValid() && g_touchpadSeen.elapsed() < 300);
        if (touchpad)
            g_touchpadSeen.start();
    }
    if (!touchpad)
        return false;
    // Pixels when the platform gives them; otherwise 120 angle units (one notch) = 40 pixels.
    QPointF d = !e->pixelDelta().isNull() ? QPointF(e->pixelDelta()) : QPointF(e->angleDelta()) / 3.0;
    if (e->inverted())
        d = -d;
    if ((e->modifiers() & Qt::ShiftModifier) && !m_planView) {
        if (d.x() == 0 && e->angleDelta().x() == 0 && e->pixelDelta().isNull())
            d = QPointF(d.y(), 0); // some platforms turn Shift+scroll into a sideways scroll
        orbitBy(-d.x(), -d.y());
        m_lastScroll = ScrollAction::Orbit;
    } else {
        panByPixels(d.x(), d.y());
        m_lastScroll = ScrollAction::Pan;
    }
    e->accept();
    return true;
}

void Viewport::panByPixels(double dx, double dy)
{
    AbortViewAnimation();
    const Handle(Graphic3d_Camera)& camera = m_view->Camera();
    const double perPixel = camera->ViewDimensions().Y() / std::max(1, height());
    const gp_Dir up = camera->Up();
    const gp_Dir right = camera->Direction().Crossed(up);
    // Scrolling moves the content with the fingers: the camera goes the other way.
    const gp_Vec shift = gp_Vec(right) * (-dx * perPixel) + gp_Vec(up) * (dy * perPixel);
    camera->SetEyeAndCenter(camera->Eye().Translated(shift), camera->Center().Translated(shift));
    m_view->Invalidate();
    update();
}

void Viewport::zoomByFactor(double factor, const QPointF& widgetPos)
{
    if (!(factor > 0) || !std::isfinite(factor))
        return;
    AbortViewAnimation();
    const Handle(Graphic3d_Camera)& camera = m_view->Camera();
    const double perPixel = camera->ViewDimensions().Y() / std::max(1, height());
    const gp_Dir up = camera->Up();
    const gp_Dir right = camera->Direction().Crossed(up);
    // The point under the cursor stays put: move towards it by (1 - 1/factor) of its offset.
    const gp_Vec offset = gp_Vec(right) * ((widgetPos.x() - width() / 2.0) * perPixel)
        + gp_Vec(up) * ((height() / 2.0 - widgetPos.y()) * perPixel);
    const gp_Vec shift = offset * (1.0 - 1.0 / factor);
    camera->SetEyeAndCenter(camera->Eye().Translated(shift), camera->Center().Translated(shift));
    camera->SetScale(camera->Scale() / factor);
    m_view->Invalidate();
    update();
}

bool Viewport::event(QEvent* e)
{
    if (e->type() == QEvent::NativeGesture) {
        auto* g = static_cast<QNativeGestureEvent*>(e);
        switch (g->gestureType()) {
        case Qt::ZoomNativeGesture: // pinch: value() is the scale change since the last event
            zoomByFactor(1.0 + g->value(), g->position());
            m_lastScroll = ScrollAction::Zoom;
            return true;
        case Qt::SmartZoomNativeGesture: // two-finger double tap
            fitAll();
            return true;
        case Qt::PanNativeGesture:
            panByPixels(g->delta().x(), g->delta().y());
            m_lastScroll = ScrollAction::Pan;
            return true;
        default:
            break;
        }
    }
    return QWidget::event(e);
}

} // namespace kimbim
