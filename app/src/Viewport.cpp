// SPDX-License-Identifier: GPL-3.0-or-later
#include "Viewport.h"

#include <Aspect_DisplayConnection.hxx>
#include <Graphic3d_ClipPlane.hxx>
#include <OpenGl_GraphicDriver.hxx>
#include <Prs3d_Drawer.hxx>
#include <Standard_Failure.hxx>
#include <V3d_DirectionalLight.hxx>
#include <V3d_AmbientLight.hxx>
#include <Graphic3d_Camera.hxx>
#include <SelectMgr_EntityOwner.hxx>
#include <gp_Pnt.hxx>
#ifdef _WIN32
#include <WNT_Window.hxx>
#else
#include <Xw_Window.hxx>
#endif

#include <QElapsedTimer>
#include <QGuiApplication>
#include <QKeyEvent>
#include <QMouseEvent>
#include <QWheelEvent>

#include <algorithm>
#include <cmath>
#include <set>

namespace kimcad {

namespace {

Aspect_VKeyMouse toButtons(Qt::MouseButtons b)
{
    Aspect_VKeyMouse m = Aspect_VKeyMouse_NONE;
    if (b & Qt::LeftButton)
        m |= Aspect_VKeyMouse_LeftButton;
    if (b & Qt::MiddleButton)
        m |= Aspect_VKeyMouse_MiddleButton;
    if (b & Qt::RightButton)
        m |= Aspect_VKeyMouse_RightButton;
    return m;
}

Aspect_VKeyFlags toFlags(Qt::KeyboardModifiers mods)
{
    Aspect_VKeyFlags f = Aspect_VKeyFlags_NONE;
    if (mods & Qt::ShiftModifier)
        f |= Aspect_VKeyFlags_SHIFT;
    if (mods & Qt::ControlModifier)
        f |= Aspect_VKeyFlags_CTRL;
    if (mods & Qt::AltModifier)
        f |= Aspect_VKeyFlags_ALT;
    return f;
}

} // namespace

Viewport::Viewport(QWidget* parent)
    : QWidget(parent)
{
    setAttribute(Qt::WA_PaintOnScreen);
    setAttribute(Qt::WA_NoSystemBackground);
    setAttribute(Qt::WA_NativeWindow);
    setMouseTracking(true);
    setFocusPolicy(Qt::StrongFocus);
    setMinimumSize(200, 200);

    Handle(Aspect_DisplayConnection) display = new Aspect_DisplayConnection();
    Handle(OpenGl_GraphicDriver) driver = new OpenGl_GraphicDriver(display, false);
    // KIMCAD_NO_VSYNC=1: measure true frame cost in benchmarks (normal use keeps vsync: no tearing).
    if (qEnvironmentVariableIntValue("KIMCAD_NO_VSYNC") == 1)
        driver->ChangeOptions().swapInterval = 0;
    m_viewer = new V3d_Viewer(driver);
    // A fixed "sun" from the south-east above plus soft ambient and fill. A headlight along the
    // isometric view direction lights the top and both visible sides equally, so boxes look flat.
    Handle(V3d_AmbientLight) ambient = new V3d_AmbientLight(Quantity_Color(0.42, 0.42, 0.42, Quantity_TOC_RGB));
    Handle(V3d_DirectionalLight) sun = new V3d_DirectionalLight(gp_Dir(-0.3, 0.5, -0.8), Quantity_NOC_WHITE);
    sun->SetIntensity(0.75f);
    Handle(V3d_DirectionalLight) fill = new V3d_DirectionalLight(gp_Dir(0.6, -0.25, -0.35), Quantity_NOC_WHITE);
    fill->SetIntensity(0.25f);
    for (const Handle(V3d_Light)& light : {Handle(V3d_Light)(ambient), Handle(V3d_Light)(sun), Handle(V3d_Light)(fill)})
        m_viewer->AddLight(light);
    m_viewer->SetLightOn();
    m_context = new AIS_InteractiveContext(m_viewer);
    m_view = m_viewer->CreateView();
    m_view->SetBackgroundColor(Quantity_Color(0.93, 0.94, 0.95, Quantity_TOC_RGB));
    m_view->SetProj(V3d_XposYnegZpos);
    m_context->HighlightStyle(Prs3d_TypeOfHighlight_Dynamic)->SetColor(Quantity_Color(0.98, 0.75, 0.20, Quantity_TOC_RGB));
    m_context->HighlightStyle(Prs3d_TypeOfHighlight_Selected)->SetColor(Quantity_Color(0.15, 0.50, 0.95, Quantity_TOC_RGB));
    applyNavigationPreset();
}

void Viewport::setPlanView(double elevation)
{
    m_planView = true;
    m_planElevation = elevation;
    m_view->Camera()->SetProjectionType(Graphic3d_Camera::Projection_Orthographic);
    m_view->SetProj(V3d_Zpos); // looking down, north (+Y) up
    applyNavigationPreset();
    if (ensureWindow())
        fitAll();
    update();
}

void Viewport::set3DView()
{
    m_planView = false;
    m_view->SetProj(V3d_XposYnegZpos);
    applyNavigationPreset();
    if (ensureWindow())
        fitAll();
    update();
}

bool Viewport::pointOnPlane(int x, int y, double z, gp_Pnt* out)
{
    if (!ensureWindow())
        return false;
    double px = 0, py = 0, pz = 0, vx = 0, vy = 0, vz = 0;
    m_view->ConvertWithProj(x, y, px, py, pz, vx, vy, vz);
    if (std::abs(vz) < 1e-9)
        return false;
    const double t = (z - pz) / vz;
    *out = gp_Pnt(px + t * vx, py + t * vy, z);
    return true;
}

void Viewport::applyNavigationPreset()
{
    auto& gestures = ChangeMouseGestureMap();
    gestures.Clear();
    gestures.Bind(Aspect_VKeyMouse_MiddleButton, AIS_MouseGesture_Pan);
    // Plans are not orbited (Revit/ArchiCAD): Shift+middle pans there too.
    gestures.Bind(Aspect_VKeyMouse_MiddleButton | Aspect_VKeyFlags_SHIFT,
        m_planView ? AIS_MouseGesture_Pan : AIS_MouseGesture_RotateOrbit);
    // Left-drag draws a selection box; with Ctrl/Shift it adds/toggles like a click does.
    gestures.Bind(Aspect_VKeyMouse_LeftButton, AIS_MouseGesture_SelectRectangle);
    gestures.Bind(Aspect_VKeyMouse_LeftButton | Aspect_VKeyFlags_CTRL, AIS_MouseGesture_SelectRectangle);
    gestures.Bind(Aspect_VKeyMouse_LeftButton | Aspect_VKeyFlags_SHIFT, AIS_MouseGesture_SelectRectangle);
    auto& schemes = ChangeMouseSelectionSchemes();
    schemes.Clear();
    schemes.Bind(Aspect_VKeyMouse_LeftButton, AIS_SelectionScheme_Replace);
    schemes.Bind(Aspect_VKeyMouse_LeftButton | Aspect_VKeyFlags_CTRL, AIS_SelectionScheme_Add);
    schemes.Bind(Aspect_VKeyMouse_LeftButton | Aspect_VKeyFlags_SHIFT, AIS_SelectionScheme_XOR);
    SetRotationMode(AIS_RotationMode_PickLast);
    SetStickToRayOnZoom(true); // wheel zoom goes toward the point under the cursor
}

AIS_SelectionScheme Viewport::selectionSchemeFor(Aspect_VKeyMouse button, Aspect_VKeyFlags flags) const
{
    AIS_SelectionScheme scheme = AIS_SelectionScheme_UNKNOWN;
    MouseSelectionSchemes().Find(button | flags, scheme);
    return scheme;
}

int Viewport::selectInRectangle(int x0, int y0, int x1, int y1, AIS_SelectionScheme scheme)
{
    if (!ensureWindow())
        return 0;
    m_context->SelectRectangle(NCollection_Vec2<int>(std::min(x0, x1), std::min(y0, y1)),
        NCollection_Vec2<int>(std::max(x0, x1), std::max(y0, y1)), m_view, scheme);
    m_context->UpdateCurrentViewer();
    emit selectionChanged(selectedGuids());
    return m_context->NbSelected();
}

AIS_MouseGesture Viewport::gestureFor(Aspect_VKeyMouse button, Aspect_VKeyFlags flags) const
{
    AIS_MouseGesture gesture = AIS_MouseGesture_NONE;
    MouseGestureMap().Find(button | flags, gesture);
    return gesture;
}

Viewport::~Viewport()
{
    m_context->RemoveAll(false);
}

bool Viewport::ensureWindow()
{
    if (!m_view->Window().IsNull())
        return true;
    // Headless platforms have no native window for OpenGL: degrade instead of throwing.
    const QString platform = QGuiApplication::platformName();
    if (platform == QLatin1String("offscreen") || platform == QLatin1String("minimal"))
        return false;
    try {
#ifdef _WIN32
        Handle(WNT_Window) window = new WNT_Window(reinterpret_cast<Aspect_Handle>(winId()));
#else
        Handle(Xw_Window) window = new Xw_Window(m_viewer->Driver()->GetDisplayConnection(), Aspect_Drawable(winId()));
#endif
        m_view->SetWindow(window);
        if (!window->IsMapped())
            window->Map();
        m_view->MustBeResized();
        return true;
    } catch (const Standard_Failure& e) {
        // Never let an OCCT exception escape into a Qt event handler (it aborts the app).
        qWarning("KIMCAD: cannot attach the 3D view to its window: %s", e.what());
        return false;
    }
}

void Viewport::paintEvent(QPaintEvent*)
{
    if (!ensureWindow())
        return;
    m_view->InvalidateImmediate();
    FlushViewEvents(m_context, m_view, true);
}

void Viewport::resizeEvent(QResizeEvent*)
{
    if (!m_view->Window().IsNull())
        m_view->MustBeResized();
}

NCollection_Vec2<int> Viewport::toPixels(const QPointF& p) const
{
    const double r = devicePixelRatioF();
    return NCollection_Vec2<int>(int(std::lround(p.x() * r)), int(std::lround(p.y() * r)));
}

bool Viewport::workPoint(const QPointF& widgetPos, QPointF* point, double* tolerance)
{
    const NCollection_Vec2<int> px = toPixels(widgetPos);
    gp_Pnt a, b;
    if (!pointOnPlane(px.x(), px.y(), m_workZ, &a) || !pointOnPlane(px.x() + 10, px.y(), m_workZ, &b))
        return false;
    *point = QPointF(a.X(), a.Y());
    *tolerance = a.Distance(b);
    return true;
}

void Viewport::setDrawingMode(bool on, double workPlaneZ)
{
    m_drawingMode = on;
    m_workZ = workPlaneZ;
    if (on)
        m_context->ClearDetected(false); // no hover highlight while drawing
    else
        setWallPreview(std::nullopt, 0, 0);
    setCursor(on ? Qt::CrossCursor : Qt::ArrowCursor);
}

void Viewport::setWallPreview(const std::optional<std::pair<QPointF, QPointF>>& axis, double thickness, double height)
{
    if (!m_preview.IsNull()) {
        m_context->Remove(m_preview, false);
        m_preview.Nullify();
    }
    if (axis && thickness > 0 && height > 0) {
        const QPointF a = axis->first, b = axis->second;
        const double len = std::hypot(b.x() - a.x(), b.y() - a.y());
        if (len > 1e-6) {
            const QPointF n(-(b.y() - a.y()) / len * thickness / 2, (b.x() - a.x()) / len * thickness / 2);
            const QPointF corners[4] = {a - n, b - n, b + n, a + n};
            MeshChunk c;
            c.guids << QStringLiteral("preview");
            c.types << QStringLiteral("IfcWall");
            for (double z : {m_workZ, m_workZ + height})
                for (const QPointF& p : corners)
                    c.verts.insert(c.verts.end(), {float(p.x()), float(p.y()), float(z)});
            // 12 triangles: bottom, top, 4 sides (8 corners: 0-3 bottom, 4-7 top).
            const uint32_t t[] = {0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4,
                1, 2, 6, 1, 6, 5, 2, 3, 7, 2, 7, 6, 3, 0, 4, 3, 4, 7};
            c.tris.assign(std::begin(t), std::end(t));
            c.voff = {0, 8};
            c.toff = {0, 12};
            m_preview = new ElementBatch(std::move(c));
            m_context->Display(m_preview, 0, -1, false); // shown, never selectable
        }
    }
    update();
}

void Viewport::keyPressEvent(QKeyEvent* e)
{
    if (m_drawingMode) {
        if (e->key() == Qt::Key_Escape) {
            emit drawingEnded();
            return;
        }
        const QString text = e->text();
        if (!text.isEmpty() && (text.at(0).isDigit() || text == QLatin1String(".") || text == QLatin1String(","))) {
            emit lengthKeyTyped(text);
            return;
        }
    }
    QWidget::keyPressEvent(e);
}

void Viewport::mouseDoubleClickEvent(QMouseEvent* e)
{
    if (m_drawingMode && e->button() == Qt::LeftButton) {
        emit drawingEnded();
        return;
    }
    QWidget::mouseDoubleClickEvent(e);
}

void Viewport::mousePressEvent(QMouseEvent* e)
{
    if (m_drawingMode && (e->button() == Qt::LeftButton || e->button() == Qt::RightButton)) {
        if (e->button() == Qt::RightButton) {
            emit drawingEnded();
            return;
        }
        QPointF p;
        double tolerance = 0;
        if (workPoint(e->position(), &p, &tolerance))
            emit workPointClicked(p, tolerance, e->modifiers());
        return; // drawing clicks never reach selection
    }
    if (PressMouseButton(toPixels(e->position()), toButtons(e->buttons()), toFlags(e->modifiers()), false))
        update();
}

void Viewport::mouseReleaseEvent(QMouseEvent* e)
{
    if (m_drawingMode && (e->button() == Qt::LeftButton || e->button() == Qt::RightButton))
        return;
    if (ReleaseMouseButton(toPixels(e->position()), toButtons(e->buttons()), toFlags(e->modifiers()), false))
        update();
}

void Viewport::mouseMoveEvent(QMouseEvent* e)
{
    if (m_drawingMode) {
        QPointF p;
        double tolerance = 0;
        if (workPoint(e->position(), &p, &tolerance))
            emit workPointMoved(p, tolerance, e->modifiers());
        if (!(e->buttons() & Qt::MiddleButton))
            return; // no hover highlighting while drawing; middle-button navigation still works
    }
    if (UpdateMousePosition(toPixels(e->position()), toButtons(e->buttons()), toFlags(e->modifiers()), false))
        update();
}

void Viewport::wheelEvent(QWheelEvent* e)
{
    if (UpdateZoom(Aspect_ScrollDelta(toPixels(e->position()), e->angleDelta().y() / 8.0)))
        update();
}

void Viewport::OnSelectionChanged(const Handle(AIS_InteractiveContext)&, const Handle(V3d_View)&)
{
    emit selectionChanged(selectedGuids());
}

void Viewport::addBatch(const Handle(ElementBatch)& batch)
{
    const int b = int(m_batches.size());
    m_batches.push_back(batch);
    for (int i = 0; i < batch->elementCount(); ++i)
        m_locate.insert(batch->guid(i), Loc{b, i});
    for (const auto& plane : m_clipPlanes)
        batch->AddClipPlane(plane);
    m_context->Display(batch, 0, 0, false);
    update();
}

void Viewport::clear()
{
    m_context->RemoveAll(false);
    m_batches.clear();
    m_locate.clear();
    update();
}

void Viewport::fitAll()
{
    if (!ensureWindow())
        return;
    m_view->FitAll(0.05, false);
    m_view->ZFitAll();
    update();
}

QStringList Viewport::guids() const
{
    QStringList out;
    for (const auto& b : m_batches)
        for (int i = 0; i < b->elementCount(); ++i)
            if (!b->isRetired(i))
                out << b->guid(i);
    return out;
}

bool Viewport::retire(const QString& guid, std::vector<int>* touched)
{
    auto it = m_locate.find(guid);
    if (it == m_locate.end())
        return false;
    const auto& batch = m_batches[size_t(it->batch)];
    Handle(ElementOwner) owner = batch->owner(it->index);
    const bool wasSelected = owner->IsSelected();
    if (wasSelected)
        m_context->AddOrRemoveSelected(owner, false);
    batch->retire(it->index);
    touched->push_back(it->batch);
    m_locate.erase(it);
    return wasSelected;
}

void Viewport::replaceElements(const MeshChunk& chunk)
{
    if (chunk.elementCount() == 0)
        return;
    std::vector<int> touched;
    QStringList reselect;
    for (const QString& g : chunk.guids)
        if (retire(g, &touched))
            reselect << g;
    redisplay(touched);
    addBatch(new ElementBatch(chunk));
    for (const QString& g : reselect) {
        const Loc loc = m_locate.value(g);
        m_context->AddOrRemoveSelected(m_batches[size_t(loc.batch)]->owner(loc.index), false);
    }
    update();
}

void Viewport::removeElements(const QStringList& guids)
{
    std::vector<int> touched;
    for (const QString& g : guids)
        retire(g, &touched);
    redisplay(touched);
}

int Viewport::visibleElementCount() const
{
    int n = 0;
    for (const auto& b : m_batches)
        n += b->visibleCount();
    return n;
}

qint64 Viewport::triangleCount() const
{
    qint64 n = 0;
    for (const auto& b : m_batches)
        n += b->triangleCount();
    return n;
}

QStringList Viewport::selectedGuids() const
{
    QStringList out;
    for (m_context->InitSelected(); m_context->MoreSelected(); m_context->NextSelected()) {
        Handle(ElementOwner) owner = Handle(ElementOwner)::DownCast(m_context->SelectedOwner());
        if (!owner.IsNull())
            out << owner->batch()->guid(owner->index());
    }
    return out;
}

void Viewport::selectGuids(const QStringList& guids)
{
    m_context->ClearSelected(false);
    std::vector<int> unhide;
    for (const QString& g : guids) {
        auto it = m_locate.constFind(g);
        if (it == m_locate.constEnd())
            continue;
        if (m_batches[size_t(it->batch)]->isHidden(it->index)) { // selecting a hidden element reveals it
            m_batches[size_t(it->batch)]->setHidden(it->index, false);
            unhide.push_back(it->batch);
        }
    }
    redisplay(unhide);
    for (const QString& g : guids) {
        auto it = m_locate.constFind(g);
        if (it != m_locate.constEnd())
            m_context->AddOrRemoveSelected(m_batches[size_t(it->batch)]->owner(it->index), false);
    }
    m_context->UpdateCurrentViewer();
    update();
}

void Viewport::redisplay(const std::vector<int>& batches)
{
    std::set<int> unique(batches.begin(), batches.end());
    for (int b : unique) {
        m_context->Redisplay(m_batches[size_t(b)], false, true);
        m_context->RecomputeSelectionOnly(m_batches[size_t(b)]);
    }
    if (!unique.empty())
        update();
}

void Viewport::setHidden(const QStringList& guids, bool hidden)
{
    std::vector<int> touched;
    for (const QString& g : guids) {
        auto it = m_locate.constFind(g);
        if (it == m_locate.constEnd())
            continue;
        const auto& batch = m_batches[size_t(it->batch)];
        if (hidden) { // a hidden element can't stay selected; the rest of the selection stays
            Handle(ElementOwner) owner = batch->owner(it->index);
            if (owner->IsSelected())
                m_context->AddOrRemoveSelected(owner, false);
        }
        batch->setHidden(it->index, hidden);
        touched.push_back(it->batch);
    }
    redisplay(touched);
}

void Viewport::isolate(const QStringList& guids)
{
    QSet<QString> keep(guids.begin(), guids.end());
    m_context->ClearSelected(false);
    std::vector<int> touched;
    for (size_t b = 0; b < m_batches.size(); ++b) {
        const auto& batch = m_batches[b];
        bool changed = false;
        for (int i = 0; i < batch->elementCount(); ++i) {
            const bool hide = !keep.contains(batch->guid(i));
            if (batch->isHidden(i) != hide) {
                batch->setHidden(i, hide);
                changed = true;
            }
        }
        if (changed)
            touched.push_back(int(b));
    }
    redisplay(touched);
}

void Viewport::showAll()
{
    std::vector<int> touched;
    for (size_t b = 0; b < m_batches.size(); ++b) {
        const auto& batch = m_batches[b];
        if (batch->visibleCount() == batch->elementCount())
            continue;
        for (int i = 0; i < batch->elementCount(); ++i)
            batch->setHidden(i, false);
        touched.push_back(int(b));
    }
    redisplay(touched);
}

void Viewport::addClipPlanes(const std::vector<Handle(Graphic3d_ClipPlane)>& planes)
{
    for (const auto& plane : planes) {
        m_clipPlanes.push_back(plane);
        for (const auto& b : m_batches)
            b->AddClipPlane(plane);
    }
    update();
}

void Viewport::clearClipPlanes()
{
    for (const auto& plane : m_clipPlanes)
        for (const auto& b : m_batches)
            b->RemoveClipPlane(plane);
    m_clipPlanes.clear();
    update();
}

Bnd_Box Viewport::boundsOf(const QStringList& guids) const
{
    Bnd_Box box;
    if (guids.isEmpty()) {
        for (const auto& b : m_batches)
            box.Add(b->visibleBounds());
        return box;
    }
    for (const QString& g : guids) {
        auto it = m_locate.constFind(g);
        if (it != m_locate.constEnd())
            box.Add(m_batches[size_t(it->batch)]->elementBounds(it->index));
    }
    return box;
}

double Viewport::measureFps(int frames)
{
    if (!ensureWindow())
        return 0;
    Handle(Graphic3d_Camera) cam = m_view->Camera();
    const gp_Pnt center = cam->Center();
    const gp_Pnt eye = cam->Eye();
    const double dx = eye.X() - center.X(), dy = eye.Y() - center.Y(), dz = eye.Z() - center.Z();
    const double r = std::hypot(dx, dy), a0 = std::atan2(dy, dx);
    std::vector<double> ms;
    QElapsedTimer t;
    for (int i = 0; i < frames; ++i) {
        const double a = a0 + 2 * M_PI * i / std::max(frames, 1);
        cam->SetEye(gp_Pnt(center.X() + r * std::cos(a), center.Y() + r * std::sin(a), center.Z() + dz));
        t.start();
        m_view->Redraw();
        ms.push_back(double(t.nsecsElapsed()) / 1e6);
    }
    cam->SetEye(eye);
    m_view->Redraw();
    if (ms.empty())
        return 0;
    std::sort(ms.begin(), ms.end());
    const double median = ms[ms.size() / 2];
    return median > 0 ? 1000.0 / median : 0;
}

bool Viewport::dumpImage(const QString& path)
{
    if (!ensureWindow())
        return false;
    m_view->Redraw();
    return m_view->Dump(path.toUtf8().constData());
}

QString Viewport::pickAt(int x, int y)
{
    if (!ensureWindow())
        return {};
    m_context->MoveTo(x, y, m_view, false);
    if (!m_context->HasDetected())
        return {};
    Handle(ElementOwner) owner = Handle(ElementOwner)::DownCast(m_context->DetectedOwner());
    return owner.IsNull() ? QString() : owner->batch()->guid(owner->index());
}

bool Viewport::projectCenterOf(const QString& guid, int* x, int* y) const
{
    auto it = m_locate.constFind(guid);
    if (it == m_locate.constEnd() || m_view->Window().IsNull())
        return false;
    const Bnd_Box box = m_batches[size_t(it->batch)]->elementBounds(it->index);
    if (box.IsVoid())
        return false;
    double x0, y0, z0, x1, y1, z1;
    box.Get(x0, y0, z0, x1, y1, z1);
    int px = 0, py = 0;
    m_view->Convert((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2, px, py);
    *x = px;
    *y = py;
    return true;
}

} // namespace kimcad
