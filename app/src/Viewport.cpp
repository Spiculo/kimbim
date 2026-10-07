// SPDX-License-Identifier: GPL-3.0-or-later
#include "Viewport.h"
#include "PolygonTool.h"

#include <Aspect_DisplayConnection.hxx>
#include <Graphic3d_ClipPlane.hxx>
#include <gp_Pln.hxx>
#include <OpenGl_GraphicDriver.hxx>
#include <Prs3d_Drawer.hxx>
#include <Standard_Failure.hxx>
#include <TCollection_ExtendedString.hxx>
#include <Graphic3d_AspectLine3d.hxx>
#include <Graphic3d_ArrayOfSegments.hxx>
#include <Prs3d_TextAspect.hxx>
#include <Prs3d_Text.hxx>
#include <V3d_ImageDumpOptions.hxx>
#include <Image_PixMap.hxx>
#include <V3d_DirectionalLight.hxx>
#include <V3d_AmbientLight.hxx>
#include <Graphic3d_Camera.hxx>
#include <SelectMgr_EntityOwner.hxx>
#include <SelectMgr_Selection.hxx>
#include <Select3D_SensitivePoint.hxx>
#include <Select3D_SensitiveSegment.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>
#ifdef _WIN32
#include <WNT_Window.hxx>
#else
#include <Xw_Window.hxx>
#endif

#include <QElapsedTimer>
#include <QGuiApplication>
#include <QKeyEvent>
#include <QThread>
#include <QTimer>
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

namespace {

// One display connection per process, shared by every view (on X11 each one is a connection to the X
// server). Opening a connection can fail for a moment on a busy server (CI's Xvfb did, aborting the
// app with an uncaught OCCT exception), so it is retried a few times before giving up.
Handle(Aspect_DisplayConnection) sharedDisplay()
{
    static Handle(Aspect_DisplayConnection) display;
    if (!display.IsNull())
        return display;
    for (int attempt = 0;; ++attempt) {
        try {
            display = new Aspect_DisplayConnection();
            return display;
        } catch (const Standard_Failure& e) {
            if (attempt >= 9)
                throw;
            qWarning("KIMCAD: no display connection yet (%s), retrying", e.what());
            QThread::msleep(200);
        }
    }
}

} // namespace

Viewport::Viewport(QWidget* parent)
    : QWidget(parent)
{
    setAttribute(Qt::WA_PaintOnScreen);
    setAttribute(Qt::WA_NoSystemBackground);
    setAttribute(Qt::WA_NativeWindow);
    setMouseTracking(true);
    m_hoverTimer = new QTimer(this);
    m_hoverTimer->setSingleShot(true);
    m_hoverTimer->setInterval(450);
    connect(m_hoverTimer, &QTimer::timeout, this, [this] {
        if (m_drawingMode)
            return;
        Handle(ElementOwner) owner = Handle(ElementOwner)::DownCast(m_context->DetectedOwner());
        const QString guid = owner.IsNull() || !owner->batch() ? QString() : owner->batch()->guid(owner->index());
        emit hovered(guid, mapToGlobal(m_hoverPos.toPoint()));
    });
    setFocusPolicy(Qt::StrongFocus);
    setMinimumSize(200, 200);

    Handle(OpenGl_GraphicDriver) driver = new OpenGl_GraphicDriver(sharedDisplay(), false);
    // No vsync by default: the view only redraws when something changes, so this never spins, and a
    // frame takes ~1 ms. With vsync each redraw blocked the UI until the next screen refresh (33 ms
    // on 30 Hz laptop panels), so drawing tools lagged behind the mouse (owner feedback).
    // KIMCAD_VSYNC=1 turns it back on (e.g. if orbiting tears on some screen).
    if (qEnvironmentVariableIntValue("KIMCAD_VSYNC") != 1)
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
    const Quantity_Color background(0.93, 0.94, 0.95, Quantity_TOC_RGB);
    m_view->SetBackgroundColor(background);
    ElementBatch::setBackground(background); // lines-only faces blend into it
    m_view->SetProj(V3d_XposYnegZpos);
    m_context->HighlightStyle(Prs3d_TypeOfHighlight_Dynamic)->SetColor(Quantity_Color(0.98, 0.75, 0.20, Quantity_TOC_RGB));
    m_context->HighlightStyle(Prs3d_TypeOfHighlight_Selected)->SetColor(Quantity_Color(0.15, 0.50, 0.95, Quantity_TOC_RGB));
    applyNavigationPreset();
}

void Viewport::setPlanView(double elevation)
{
    const bool wasPlan = m_planView;
    m_planView = true;
    m_planElevation = elevation;
    m_view->Camera()->SetProjectionType(Graphic3d_Camera::Projection_Orthographic);
    m_view->SetProj(V3d_Zpos); // looking down, north (+Y) up
    applyNavigationPreset();
    if (!wasPlan && !m_markerData.isEmpty())
        displayAnnotations(); // section/elevation markers belong to the plan
    if (ensureWindow())
        fitAll();
    update();
}

void Viewport::set3DView()
{
    const bool wasPlan = m_planView;
    m_planView = false;
    m_view->SetProj(V3d_XposYnegZpos);
    applyNavigationPreset();
    if (wasPlan && !m_markerData.isEmpty())
        displayAnnotations();
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
    // Alt+drag selects through: hidden elements inside the box too.
    gestures.Bind(Aspect_VKeyMouse_LeftButton | Aspect_VKeyFlags_ALT, AIS_MouseGesture_SelectRectangle);
    auto& schemes = ChangeMouseSelectionSchemes();
    schemes.Clear();
    schemes.Bind(Aspect_VKeyMouse_LeftButton, AIS_SelectionScheme_Replace);
    schemes.Bind(Aspect_VKeyMouse_LeftButton | Aspect_VKeyFlags_CTRL, AIS_SelectionScheme_Add);
    schemes.Bind(Aspect_VKeyMouse_LeftButton | Aspect_VKeyFlags_SHIFT, AIS_SelectionScheme_XOR);
    schemes.Bind(Aspect_VKeyMouse_LeftButton | Aspect_VKeyFlags_ALT, AIS_SelectionScheme_Replace);
    SetRotationMode(AIS_RotationMode_PickLast);
    SetStickToRayOnZoom(true); // wheel zoom goes toward the point under the cursor
}

AIS_SelectionScheme Viewport::selectionSchemeFor(Aspect_VKeyMouse button, Aspect_VKeyFlags flags) const
{
    AIS_SelectionScheme scheme = AIS_SelectionScheme_UNKNOWN;
    MouseSelectionSchemes().Find(button | flags, scheme);
    return scheme;
}

QSet<QString> Viewport::selectedSet() const
{
    const QStringList list = selectedGuids();
    return QSet<QString>(list.begin(), list.end());
}

std::optional<QSet<QString>> Viewport::visibleIn(int x0, int y0, int x1, int y1)
{
    if (!ensureWindow() || m_nextIdBase > ElementBatch::maxId())
        return std::nullopt;
    int w = 0, h = 0;
    m_view->Window()->Size(w, h);
    if (w <= 0 || h <= 0)
        return std::nullopt;
    return idsInImage(w, h, x0, y0, x1, y1);
}

std::optional<QSet<QString>> Viewport::idsInImage(int w, int h, int x0, int y0, int x1, int y1)
{
    // Draw every element in its id colour on black, without highlights or lines, into an
    // offscreen image of the view; clip planes still apply, hidden elements are not drawn.
    const Quantity_Color background = m_view->BackgroundColor();
    // A mid grey that is never a valid id; how it comes back tells whether the buffer sRGB-encodes.
    m_view->SetBackgroundColor(Quantity_Color(128 / 255.0, 128 / 255.0, 128 / 255.0, Quantity_TOC_RGB));
    if (!m_preview.IsNull())
        m_context->Erase(m_preview, false);
    m_context->ClearDetected(false);
    m_context->UnhilightSelected(false);
    for (const auto& b : m_batches)
        m_context->SetDisplayMode(b, ElementBatch::Ids, false);
    Image_PixMap image;
    V3d_ImageDumpOptions options;
    options.Width = w;
    options.Height = h;
    options.BufferType = Graphic3d_BT_RGB;
    const bool ok = m_view->ToPixMap(image, options);
    const int mode = m_linesOnly ? ElementBatch::LinesOnly : ElementBatch::Shaded;
    for (const auto& b : m_batches)
        m_context->SetDisplayMode(b, mode, false);
    m_view->SetBackgroundColor(background);
    if (!m_preview.IsNull())
        m_context->Display(m_preview, 0, -1, false);
    m_context->HilightSelected(false);
    update();
    if (!ok)
        return std::nullopt;

    const bool bgr = image.Format() == Image_Format_BGR || image.Format() == Image_Format_BGR32;
    // Calibrate: background pixels read ~128 (stored as is) or ~188 (sRGB-encoded on output).
    auto pixel = [&](int x, int y) {
        const uint8_t* p = image.RawValue(image.IsTopDown() ? size_t(y) : size_t(h - 1 - y), size_t(x));
        return bgr ? std::array<int, 3>{p[2], p[1], p[0]} : std::array<int, 3>{p[0], p[1], p[2]};
    };
    int linearHits = 0, srgbHits = 0;
    for (int y = 0; y < h; y += 7)
        for (int x = 0; x < w; x += 7) {
            const auto c = pixel(x, y);
            if (std::abs(c[0] - 128) <= 2 && c[0] == c[1] && c[1] == c[2])
                ++linearHits;
            else if (std::abs(c[0] - 188) <= 2 && c[0] == c[1] && c[1] == c[2])
                ++srgbHits;
        }
    std::array<int, 256> toLinear{};
    for (int i = 0; i < 256; ++i) {
        const double c = i / 255.0;
        const double l = srgbHits > linearHits ? (c <= 0.04045 ? c / 12.92 : std::pow((c + 0.055) / 1.055, 2.4)) : c;
        toLinear[size_t(i)] = int(std::lround(l * 255.0));
    }
    QSet<int> ids;
    const int xa = std::clamp(std::min(x0, x1), 0, w - 1), xb = std::clamp(std::max(x0, x1), 0, w - 1);
    const int ya = std::clamp(std::min(y0, y1), 0, h - 1), yb = std::clamp(std::max(y0, y1), 0, h - 1);
    for (int y = ya; y <= yb; ++y) {
        const size_t row = image.IsTopDown() ? size_t(y) : size_t(h - 1 - y);
        for (int x = xa; x <= xb; ++x) {
            const uint8_t* p = image.RawValue(row, size_t(x));
            const int r = bgr ? p[2] : p[0], g = p[1], b = bgr ? p[0] : p[2];
            const int id = ElementBatch::idFromRgb(toLinear[size_t(r)], toLinear[size_t(g)], toLinear[size_t(b)]);
            if (id > 0)
                ids.insert(id);
        }
    }
    QSet<QString> out;
    for (int id : std::as_const(ids)) {
        const auto it = std::upper_bound(m_idBases.begin(), m_idBases.end(), id - 1);
        if (it == m_idBases.begin())
            continue;
        const size_t b = size_t(std::distance(m_idBases.begin(), it) - 1);
        const int index = id - 1 - m_idBases[b];
        if (index < m_batches[b]->elementCount() && !m_batches[b]->isRetired(index))
            out.insert(m_batches[b]->guid(index));
    }
    return out;
}

std::optional<QSet<QString>> Viewport::visibleFrom(QPointF p1, QPointF p2, QPointF look, double z0, double z1, double depth)
{
    const QPointF d = p2 - p1;
    const double len = std::hypot(d.x(), d.y());
    if (!ensureWindow() || m_batches.empty() || m_nextIdBase > ElementBatch::maxId() || len < 1e-6 || z1 <= z0)
        return std::nullopt;
    const QPointF u = d / len;
    QPointF n(-u.y(), u.x());
    if (QPointF::dotProduct(look - p1, n) < 0)
        n = -n;
    // Keep only what the drawing can see: behind the cut line, within the line's ends (and the
    // depth); the view's own cuts (plan cut, section box) are set aside meanwhile.
    std::vector<Handle(Graphic3d_ClipPlane)> planes;
    auto keep = [&](QPointF at, QPointF towards) {
        planes.push_back(new Graphic3d_ClipPlane(gp_Pln(gp_Pnt(at.x(), at.y(), 0), gp_Dir(towards.x(), towards.y(), 0))));
    };
    keep(p1, n);
    keep(p1, u);
    keep(p2, -u);
    if (depth >= 0)
        keep(p1 + n * depth, -n);
    for (const auto& b : m_batches) {
        for (const auto& plane : m_clipPlanes)
            b->RemoveClipPlane(plane);
        for (const auto& plane : planes)
            b->AddClipPlane(plane);
    }
    Handle(Graphic3d_Camera) saved = new Graphic3d_Camera();
    saved->Copy(m_view->Camera());
    const Handle(Graphic3d_Camera)& camera = m_view->Camera();
    const QPointF mid = (p1 + p2) / 2;
    const double zm = (z0 + z1) / 2, height = z1 - z0;
    camera->SetProjectionType(Graphic3d_Camera::Projection_Orthographic);
    camera->SetUp(gp_Dir(0, 0, 1));
    camera->SetCenter(gp_Pnt(mid.x(), mid.y(), zm));
    camera->SetEye(gp_Pnt(mid.x() - n.x() * 10, mid.y() - n.y() * 10, zm));
    // An ortho camera's scale is its larger side; the image has the drawing's proportions.
    camera->SetScale(std::max(len, height) * 1.02);
    const int w = len >= height ? 2048 : std::max(64, int(std::lround(2048 * len / height)));
    const int h = len >= height ? std::max(64, int(std::lround(2048 * height / len))) : 2048;
    camera->SetAspect(double(w) / h);
    m_view->ZFitAll();
    const auto ids = idsInImage(w, h, 0, 0, w - 1, h - 1);
    for (const auto& b : m_batches) {
        for (const auto& plane : planes)
            b->RemoveClipPlane(plane);
        for (const auto& plane : m_clipPlanes)
            b->AddClipPlane(plane);
    }
    m_view->Camera()->Copy(saved);
    m_view->Invalidate();
    update();
    return ids;
}

void Viewport::keepOnlyVisible(const QSet<QString>& before, AIS_SelectionScheme scheme, int x0, int y0, int x1, int y1)
{
    const auto visible = visibleIn(x0, y0, x1, y1);
    if (!visible)
        return; // cannot tell: keep the select-through result
    const QSet<QString> after = selectedSet();
    // Replace: the result is what the box took, minus what can't be seen. Add/toggle: undo the
    // change for hidden elements (they keep the state they had before the drag).
    const QSet<QString> touched = scheme == AIS_SelectionScheme_Replace ? after : (before - after) + (after - before);
    for (const QString& g : touched) {
        if (visible->contains(g))
            continue;
        const auto it = m_locate.constFind(g);
        if (it != m_locate.constEnd())
            m_context->AddOrRemoveSelected(m_batches[size_t(it->batch)]->owner(it->index), false);
    }
    m_context->UpdateCurrentViewer();
}

void Viewport::handleSelectionPoly(const Handle(AIS_InteractiveContext)& ctx, const Handle(V3d_View)& view)
{
    const auto& points = myUI.Selection.Points;
    const bool rectangle = myUI.Selection.Tool == AIS_ViewSelectionTool_RubberBand && points.Size() == 2;
    const bool through = m_selectThrough || (LastMouseFlags() & Aspect_VKeyFlags_ALT) != 0;
    if (!rectangle || through) {
        AIS_ViewController::handleSelectionPoly(ctx, view);
        return;
    }
    const NCollection_Vec2<int> a = points.First(), b = points.Last();
    const AIS_SelectionScheme scheme = myUI.Selection.Scheme;
    const QSet<QString> before = selectedSet();
    m_quietSelection = true; // one notification, after hidden elements were dropped
    AIS_ViewController::handleSelectionPoly(ctx, view);
    m_quietSelection = false;
    // We are inside the paint pass: render the id image afterwards.
    QMetaObject::invokeMethod(this, [this, before, scheme, a, b] {
        keepOnlyVisible(before, scheme == AIS_SelectionScheme_UNKNOWN ? AIS_SelectionScheme_Replace : scheme, a.x(), a.y(), b.x(), b.y());
        emit selectionChanged(selectedGuids());
    }, Qt::QueuedConnection);
}

int Viewport::selectInRectangle(int x0, int y0, int x1, int y1, AIS_SelectionScheme scheme, bool through)
{
    if (!ensureWindow())
        return 0;
    const QSet<QString> before = selectedSet();
    m_context->SelectRectangle(NCollection_Vec2<int>(std::min(x0, x1), std::min(y0, y1)),
        NCollection_Vec2<int>(std::max(x0, x1), std::max(y0, y1)), m_view, scheme);
    m_context->UpdateCurrentViewer();
    if (!through && !m_selectThrough)
        keepOnlyVisible(before, scheme, x0, y0, x1, y1);
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
    // One full redraw per paint (one buffer swap). Invalidating the immediate layer here as well
    // made every paint swap twice, waiting two vsyncs, so tool previews lagged behind the mouse;
    // not invalidating at all left the window blank after it was shown or uncovered.
    m_view->Invalidate();
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
    QVector<PreviewBox> boxes;
    if (axis && thickness > 0 && height > 0)
        boxes.push_back({axis->first, axis->second, thickness, m_workZ, m_workZ + height});
    setPreviewBoxes(boxes);
}

namespace {

// Grid axes as dashed lines with text tags; display only (no selection modes).
class GridLinesPrs : public AIS_InteractiveObject {
public:
    GridLinesPrs(QVector<Viewport::GridLine> lines, double z)
        : m_lines(std::move(lines))
        , m_z(z)
    {
    }
    void Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int) override
    {
        if (m_lines.isEmpty())
            return;
        Handle(Graphic3d_ArrayOfSegments) arr = new Graphic3d_ArrayOfSegments(int(m_lines.size()) * 2);
        for (const auto& l : m_lines) {
            arr->AddVertex(gp_Pnt(l.a.x(), l.a.y(), m_z));
            arr->AddVertex(gp_Pnt(l.b.x(), l.b.y(), m_z));
        }
        Handle(Graphic3d_Group) lines = prs->NewGroup();
        lines->SetGroupPrimitivesAspect(new Graphic3d_AspectLine3d(Quantity_Color(0.35, 0.45, 0.65, Quantity_TOC_RGB), Aspect_TOL_DASH, 1.0));
        lines->AddPrimitiveArray(arr);
        Handle(Prs3d_TextAspect) text = new Prs3d_TextAspect();
        text->SetColor(Quantity_Color(0.15, 0.25, 0.55, Quantity_TOC_RGB));
        text->SetHeight(14);
        Handle(Graphic3d_Group) labels = prs->NewGroup();
        for (const auto& l : m_lines)
            for (const QPointF& p : {l.a, l.b})
                Prs3d_Text::Draw(labels, text, TCollection_ExtendedString(l.tag.toUtf8().constData(), true), gp_Pnt(p.x(), p.y(), m_z));
    }
    void ComputeSelection(const Handle(SelectMgr_Selection)&, const int) override {}

private:
    QVector<Viewport::GridLine> m_lines;
    double m_z;
};

} // namespace

namespace {

// Cut sections: filled outlines (unlit, dark) plus bold borders, drawn just below the cut plane.
class SectionPrs : public AIS_InteractiveObject {
public:
    SectionPrs(std::vector<std::vector<gp_Pnt2d>> loops, double z)
        : m_loops(std::move(loops))
        , m_z(z)
    {
    }
    void Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int) override
    {
        int triangles = 0, segments = 0;
        std::vector<std::vector<uint32_t>> tris;
        for (const auto& loop : m_loops) {
            QVector<QPointF> poly;
            for (const auto& p : loop)
                poly << QPointF(p.X(), p.Y());
            tris.push_back(PolygonTool::triangulate(poly));
            triangles += int(tris.back().size() / 3);
            segments += int(loop.size());
        }
        const double z = m_z - 1e-4;
        if (triangles > 0) {
            Handle(Graphic3d_ArrayOfTriangles) fill = new Graphic3d_ArrayOfTriangles(triangles * 3);
            for (size_t l = 0; l < m_loops.size(); ++l)
                for (uint32_t i : tris[l])
                    fill->AddVertex(gp_Pnt(m_loops[l][i].X(), m_loops[l][i].Y(), z));
            Handle(Graphic3d_Group) g = prs->NewGroup();
            Handle(Graphic3d_AspectFillArea3d) aspect = new Graphic3d_AspectFillArea3d();
            aspect->SetInteriorStyle(Aspect_IS_SOLID);
            aspect->SetInteriorColor(Quantity_Color(0.25, 0.25, 0.27, Quantity_TOC_RGB));
            aspect->SetShadingModel(Graphic3d_TypeOfShadingModel_Unlit);
            aspect->SetFaceCulling(Graphic3d_TypeOfBackfacingModel_DoubleSided);
            g->SetGroupPrimitivesAspect(aspect);
            g->AddPrimitiveArray(fill);
        }
        if (segments > 0) {
            Handle(Graphic3d_ArrayOfSegments) lines = new Graphic3d_ArrayOfSegments(segments * 2);
            for (const auto& loop : m_loops)
                for (size_t i = 0; i < loop.size(); ++i) {
                    lines->AddVertex(gp_Pnt(loop[i].X(), loop[i].Y(), z));
                    lines->AddVertex(gp_Pnt(loop[(i + 1) % loop.size()].X(), loop[(i + 1) % loop.size()].Y(), z));
                }
            Handle(Graphic3d_Group) g = prs->NewGroup();
            g->SetGroupPrimitivesAspect(new Graphic3d_AspectLine3d(Quantity_NOC_BLACK, Aspect_TOL_SOLID, 2.0));
            g->AddPrimitiveArray(lines);
        }
    }
    void ComputeSelection(const Handle(SelectMgr_Selection)&, const int) override {}

private:
    std::vector<std::vector<gp_Pnt2d>> m_loops;
    double m_z;
};

} // namespace

void Viewport::setSectionHeight(std::optional<double> z)
{
    m_sectionZ = z;
    rebuildSection();
}

void Viewport::rebuildSection()
{
    if (!m_section.IsNull()) {
        m_context->Remove(m_section, false);
        m_section.Nullify();
    }
    m_sectionElements = 0;
    if (!m_sectionZ) {
        update();
        return;
    }
    std::vector<std::vector<gp_Pnt2d>> loops;
    for (const auto& b : m_batches)
        for (int i = 0; i < b->elementCount(); ++i) {
            if (b->isHidden(i))
                continue;
            auto element = b->sectionLoops(i, *m_sectionZ);
            if (element.empty())
                continue;
            ++m_sectionElements;
            for (auto& l : element)
                loops.push_back(std::move(l));
        }
    if (!loops.empty()) {
        m_section = new SectionPrs(std::move(loops), *m_sectionZ);
        m_context->Display(m_section, 0, -1, false);
    }
    update();
}

namespace {

// The owner of an annotation's sensitive entities: carries its guid for selection.
class AnnotationOwner : public SelectMgr_EntityOwner {
public:
    AnnotationOwner(const Handle(SelectMgr_SelectableObject)& prs, const QString& guid)
        : SelectMgr_EntityOwner(prs, 5)
        , m_guid(guid)
    {
    }
    const QString& guid() const { return m_guid; }

private:
    QString m_guid;
};

// One plan annotation: lines (dimension, mark circle) and its text, on top of the model.
class AnnotationPrs : public AIS_InteractiveObject {
public:
    AnnotationPrs(Viewport::Annotation a, double z)
        : m_a(std::move(a))
        , m_z(z)
    {
        SetZLayer(Graphic3d_ZLayerId_Topmost);
    }
    const QString& guid() const { return m_a.guid; }
    // Null until the annotation is selectable (not on a locked layer).
    const Handle(SelectMgr_EntityOwner)& owner() const { return m_owner; }

    void Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int) override
    {
        const bool marker = isMarker();
        const Quantity_Color ink = m_a.kind == QLatin1String("mark") ? Quantity_Color(0.75, 0.15, 0.1, Quantity_TOC_RGB)
            : marker ? Quantity_Color(0.1, 0.3, 0.75, Quantity_TOC_RGB)
                     : Quantity_Color(0.1, 0.1, 0.12, Quantity_TOC_RGB);
        const std::vector<std::pair<gp_Pnt, gp_Pnt>> segs = segments();
        if (!segs.empty()) {
            Handle(Graphic3d_ArrayOfSegments) arr = new Graphic3d_ArrayOfSegments(int(segs.size()) * 2);
            for (const auto& s : segs) {
                arr->AddVertex(s.first);
                arr->AddVertex(s.second);
            }
            Handle(Graphic3d_Group) lines = prs->NewGroup();
            lines->SetGroupPrimitivesAspect(new Graphic3d_AspectLine3d(ink, Aspect_TOL_SOLID, 1.5));
            lines->AddPrimitiveArray(arr);
        }
        Handle(Prs3d_TextAspect) text = new Prs3d_TextAspect();
        text->SetColor(ink);
        if (marker) {
            text->SetHeight(14); // markers are symbols: screen-sized
        } else {
            // Slice 15: text size is in millimetres on paper; drawings print it at that size. On
            // screen it stays readable at any zoom, in proportion (2.5 mm -> 15 px).
            text->SetHeight(std::clamp(m_a.size * 6.0, 8.0, 72.0));
        }
        if (marker || m_a.kind == QLatin1String("dimension") || m_a.kind == QLatin1String("mark")) {
            text->SetHorizontalJustification(Graphic3d_HTA_CENTER); // centred on the line / in the circle
            text->SetVerticalJustification(Graphic3d_VTA_CENTER);
        } else if (m_a.kind == QLatin1String("leader")) {
            text->SetVerticalJustification(Graphic3d_VTA_CENTER);
        }
        Handle(Graphic3d_Group) group = prs->NewGroup();
        for (const auto& [value, at] : labels())
            Prs3d_Text::Draw(group, text, TCollection_ExtendedString(value.toUtf8().constData(), true), at);
    }

    void ComputeSelection(const Handle(SelectMgr_Selection)& selection, const int mode) override
    {
        if (mode != 0)
            return;
        if (m_owner.IsNull())
            m_owner = new AnnotationOwner(this, m_a.guid);
        const Handle(SelectMgr_EntityOwner)& owner = m_owner;
        for (const auto& s : segments())
            selection->Add(new Select3D_SensitiveSegment(owner, s.first, s.second));
        Handle(Select3D_SensitivePoint) point = new Select3D_SensitivePoint(owner, anchor());
        point->SetSensitivityFactor(12);
        selection->Add(point);
    }

private:
    gp_Pnt at(QPointF p) const { return gp_Pnt(p.x(), p.y(), m_z); }
    bool isMarker() const
    {
        return (m_a.kind == QLatin1String("section") || m_a.kind == QLatin1String("elevation")) && m_a.points.size() == 3;
    }
    // A marker's line direction u and the unit normal n towards the side it looks at.
    bool markerFrame(QPointF* u, QPointF* n) const
    {
        const QPointF a = m_a.points[0], b = m_a.points[1], d = b - a;
        const double len = std::hypot(d.x(), d.y());
        if (len < 1e-9)
            return false;
        *u = d / len;
        *n = QPointF(-u->y(), u->x());
        if (QPointF::dotProduct(m_a.points[2] - a, *n) < 0)
            *n = -*n;
        return true;
    }

    // A dimension chain's measured points and their projections on the dimension line (parallel to
    // first-last, through the last point given); false if degenerate.
    bool chain(QVector<QPointF>* measured, QVector<QPointF>* onLine, QPointF* u, QPointF* n) const
    {
        if (m_a.kind != QLatin1String("dimension") || m_a.points.size() < 3)
            return false;
        *measured = m_a.points.mid(0, m_a.points.size() - 1);
        const QPointF a = measured->first(), b = measured->last(), o = m_a.points.last(), d = b - a;
        const double len = std::hypot(d.x(), d.y());
        if (len < 1e-9)
            return false;
        *u = d / len;
        *n = QPointF(-u->y(), u->x());
        const double off = QPointF::dotProduct(o - a, *n);
        onLine->clear();
        for (const QPointF& p : *measured)
            *onLine << p + *n * (off - QPointF::dotProduct(p - a, *n));
        if (off < 0)
            *n = -*n; // n points away from what is measured
        return true;
    }

    std::vector<std::pair<QString, gp_Pnt>> labels() const
    {
        std::vector<std::pair<QString, gp_Pnt>> out;
        QVector<QPointF> measured, onLine;
        QPointF u, n;
        if (chain(&measured, &onLine, &u, &n)) { // one measurement per segment, just off the line
            const QStringList texts = m_a.text.split(QLatin1Char(' '), Qt::SkipEmptyParts);
            for (int i = 0; i + 1 < onLine.size(); ++i)
                out.push_back({i < texts.size() ? texts[i] : QString(), at((onLine[i] + onLine[i + 1]) / 2 + n * 0.12)});
            return out;
        }
        out.push_back({m_a.text, anchor()});
        return out;
    }

    gp_Pnt anchor() const
    {
        if (m_a.kind == QLatin1String("dimension")) {
            const auto l = labels();
            return l.empty() ? gp_Pnt(0, 0, m_z) : l.front().second;
        }
        if (m_a.kind == QLatin1String("leader") && m_a.points.size() >= 2)
            return at(m_a.points.last() + QPointF(0.1, 0));
        QPointF u, n;
        if (isMarker() && markerFrame(&u, &n)) { // the name beside the start of the line, behind it
            return m_a.kind == QLatin1String("section") ? at(m_a.points[0] - u * 0.6)
                                                        : at((m_a.points[0] + m_a.points[1]) / 2 - n * 0.6);
        }
        return m_a.points.isEmpty() ? gp_Pnt(0, 0, m_z) : at(m_a.points.first());
    }

    std::vector<std::pair<gp_Pnt, gp_Pnt>> segments() const
    {
        std::vector<std::pair<gp_Pnt, gp_Pnt>> out;
        QVector<QPointF> measured, onLine;
        QPointF u, n;
        if (chain(&measured, &onLine, &u, &n)) {
            for (int i = 0; i < measured.size(); ++i)
                out.push_back({at(measured[i]), at(onLine[i])});
            out.push_back({at(onLine.first()), at(onLine.last())});
            const double t = 0.12; // architectural ticks at every point of the chain
            for (const QPointF& p : onLine)
                out.push_back({at(p - (u + n) * t), at(p + (u + n) * t)});
        } else if (m_a.kind == QLatin1String("leader") && m_a.points.size() >= 2) {
            for (int i = 0; i + 1 < m_a.points.size(); ++i)
                out.push_back({at(m_a.points[i]), at(m_a.points[i + 1])});
            const QPointF tip = m_a.points[0], d = m_a.points[1] - tip;
            const double len = std::hypot(d.x(), d.y());
            if (len > 1e-9) { // the arrowhead
                const QPointF v = d / len, w(-v.y(), v.x());
                out.push_back({at(tip), at(tip + v * 0.25 + w * 0.08)});
                out.push_back({at(tip), at(tip + v * 0.25 - w * 0.08)});
            }
        } else if (QPointF u, n; isMarker() && markerFrame(&u, &n)) {
            const QPointF a = m_a.points[0], b = m_a.points[1];
            if (m_a.kind == QLatin1String("section")) {
                out.push_back({at(a), at(b)});
                // Archicad-style: a flag at each end with an arrow towards the side looked at.
                for (const QPointF& e : {a, b}) {
                    const QPointF tip = e + n * 0.8;
                    out.push_back({at(e), at(tip)});
                    out.push_back({at(tip), at(tip - n * 0.25 + u * 0.15)});
                    out.push_back({at(tip), at(tip - n * 0.25 - u * 0.15)});
                }
            } else { // elevation (Archicad): the marker, a triangle pointing where it looks, and the
                     // ends of its range as short ticks, without the full line
                for (const QPointF& e : {a, b})
                    out.push_back({at(e), at(e + n * 0.4)});
                const QPointF m = (a + b) / 2, tip = m + n * 0.6, l = m - u * 0.4, r = m + u * 0.4;
                out.push_back({at(l), at(r)});
                out.push_back({at(l), at(tip)});
                out.push_back({at(tip), at(r)});
            }
        } else if (m_a.kind == QLatin1String("mark") && !m_a.points.isEmpty()) {
            const QPointF c = m_a.points.first();
            const int n = 32;
            const double r = 0.4;
            for (int i = 0; i < n; ++i) {
                const double t0 = 2 * M_PI * i / n, t1 = 2 * M_PI * (i + 1) / n;
                out.push_back({at(c + QPointF(std::cos(t0), std::sin(t0)) * r), at(c + QPointF(std::cos(t1), std::sin(t1)) * r)});
            }
        }
        return out;
    }

    Viewport::Annotation m_a;
    double m_z;
    Handle(SelectMgr_EntityOwner) m_owner;
};

} // namespace

void Viewport::setAnnotations(const QVector<Annotation>& annotations, double z)
{
    m_annotationData = annotations;
    m_annotationZ = z;
    displayAnnotations();
}

void Viewport::displayAnnotations()
{
    for (const auto& prs : std::as_const(m_annotations))
        m_context->Remove(prs, false);
    m_annotations.clear();
    // Section and elevation markers are plan symbols, as in Archicad: not in the 3D view.
    for (const QVector<Annotation>* list : {&m_annotationData, &m_markerData}) {
        if (list == &m_markerData && !m_planView)
            continue;
        for (const Annotation& a : *list) {
            if (m_layerHidden.contains(a.guid))
                continue;
            Handle(AnnotationPrs) prs = new AnnotationPrs(a, m_annotationZ + 0.02);
            m_context->Display(prs, 0, m_layerLocked.contains(a.guid) ? -1 : 0, false);
            m_annotations.insert(a.guid, prs);
        }
    }
    update();
}

void Viewport::setDrawingMarkers(const QVector<Annotation>& markers, double z)
{
    m_markerData = markers;
    m_annotationZ = z;
    displayAnnotations();
}

int Viewport::annotationCount() const
{
    int n = 0;
    for (const Annotation& a : m_annotationData)
        n += m_annotations.contains(a.guid);
    return n;
}

int Viewport::markerCount() const
{
    int n = 0;
    for (const Annotation& a : m_markerData)
        n += m_annotations.contains(a.guid);
    return n;
}

QStringList Viewport::annotationGuids() const
{
    QStringList out;
    for (const Annotation& a : m_annotationData)
        if (m_annotations.contains(a.guid))
            out << a.guid;
    return out;
}

QStringList Viewport::annotationTexts() const
{
    QStringList out;
    for (const Annotation& a : m_annotationData)
        if (m_annotations.contains(a.guid))
            out << a.text;
    return out;
}

void Viewport::setGridLines(const QVector<GridLine>& lines, double z)
{
    if (!m_grid.IsNull()) {
        m_context->Remove(m_grid, false);
        m_grid.Nullify();
    }
    m_gridLineCount = int(lines.size());
    if (!lines.isEmpty()) {
        m_grid = new GridLinesPrs(lines, z);
        m_context->Display(m_grid, 0, -1, false);
    }
    update();
}

void Viewport::setPreviewBoxes(const QVector<PreviewBox>& boxes)
{
    if (!m_preview.IsNull()) {
        m_context->Remove(m_preview, false);
        m_preview.Nullify();
    }
    MeshChunk c;
    c.voff.push_back(0);
    c.toff.push_back(0);
    for (const PreviewBox& box : boxes) {
        const QPointF a = box.a, b = box.b;
        const double len = std::hypot(b.x() - a.x(), b.y() - a.y());
        if (len <= 1e-6 || box.width <= 0 || box.z1 <= box.z0)
            continue;
        const QPointF n(-(b.y() - a.y()) / len * box.width / 2, (b.x() - a.x()) / len * box.width / 2);
        const QPointF corners[4] = {a - n, b - n, b + n, a + n};
        const uint32_t base = uint32_t(c.verts.size() / 3);
        for (double z : {box.z0, box.z1})
            for (const QPointF& p : corners)
                c.verts.insert(c.verts.end(), {float(p.x()), float(p.y()), float(z)});
        // 12 triangles: bottom, top, 4 sides (8 corners: 0-3 bottom, 4-7 top).
        for (uint32_t t : {0u, 2u, 1u, 0u, 3u, 2u, 4u, 5u, 6u, 4u, 6u, 7u, 0u, 1u, 5u, 0u, 5u, 4u,
                 1u, 2u, 6u, 1u, 6u, 5u, 2u, 3u, 7u, 2u, 7u, 6u, 3u, 0u, 4u, 3u, 4u, 7u})
            c.tris.push_back(base + t);
    }
    if (!c.tris.empty()) {
        c.guids << QStringLiteral("preview");
        c.types << QStringLiteral("IfcWall");
        c.voff.push_back(uint32_t(c.verts.size() / 3));
        c.toff.push_back(uint32_t(c.tris.size() / 3));
        m_preview = new ElementBatch(std::move(c));
        m_preview->setShowEdges(false);
        m_preview->SetZLayer(Graphic3d_ZLayerId_Top);
        m_context->Display(m_preview, 0, -1, false); // shown, never selectable
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
        if (e->key() == Qt::Key_Return || e->key() == Qt::Key_Enter) {
            emit drawingConfirmed();
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

void Viewport::leaveEvent(QEvent* e)
{
    m_hoverTimer->stop();
    emit hovered(QString(), QPoint());
    QWidget::leaveEvent(e);
}

void Viewport::mouseDoubleClickEvent(QMouseEvent* e)
{
    if (m_drawingMode && e->button() == Qt::LeftButton) {
        emit drawingConfirmed();
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
    // OCCT expects the button that changed (it keeps the set of held buttons itself).
    if (e->button() == Qt::LeftButton && !(e->modifiers() & (Qt::ShiftModifier | Qt::AltModifier))) {
        // Pressing on an element that is already selected may start a drag-move.
        const NCollection_Vec2<int> px = toPixels(e->position());
        const QString guid = pickAt(px.x(), px.y());
        QPointF start;
        double tolerance = 0;
        if (!guid.isEmpty() && selectedGuids().contains(guid) && workPoint(e->position(), &start, &tolerance)) {
            m_dragCandidate = true;
            m_dragging = false;
            m_dragPressPos = e->position();
            m_dragStart = start;
            return;
        }
    }
    if (PressMouseButton(toPixels(e->position()), toButtons(e->button()), toFlags(e->modifiers()), false))
        update();
}

void Viewport::mouseReleaseEvent(QMouseEvent* e)
{
    if (m_dragCandidate && e->button() == Qt::LeftButton) {
        QPointF p;
        double tolerance = 0;
        const bool moved = m_dragging && workPoint(e->position(), &p, &tolerance);
        m_dragCandidate = m_dragging = false;
        if (moved) {
            emit dragReleased(m_dragStart, p, tolerance, e->modifiers());
        } else { // a plain click on a selected element: select just it, like any click
            const NCollection_Vec2<int> px = toPixels(e->position());
            selectGuids({pickAt(px.x(), px.y())});
            emit selectionChanged(selectedGuids());
        }
        return;
    }
    if (m_drawingMode && (e->button() == Qt::LeftButton || e->button() == Qt::RightButton))
        return;
    // The released button, not the ones still held: passing the held set kept pan/orbit running
    // after release until a modifier key changed (owner bug report).
    if (ReleaseMouseButton(toPixels(e->position()), toButtons(e->button()), toFlags(e->modifiers()), false))
        update();
}

void Viewport::mouseMoveEvent(QMouseEvent* e)
{
    if (m_dragCandidate) {
        if (!m_dragging && (e->position() - m_dragPressPos).manhattanLength() < 5)
            return; // not a drag yet
        m_dragging = true;
        QPointF p;
        double tolerance = 0;
        if (workPoint(e->position(), &p, &tolerance))
            emit dragMoved(m_dragStart, p, tolerance, e->modifiers());
        return;
    }
    if (!m_drawingMode && e->buttons() == Qt::NoButton) { // rest the mouse on an element for a hint
        m_hoverPos = e->position();
        m_hoverTimer->start();
    } else {
        m_hoverTimer->stop();
    }
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
    if (!m_quietSelection)
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
    applyColors(batch);
    applyLayerState(batch);
    batch->setIdBase(m_nextIdBase);
    m_idBases.push_back(m_nextIdBase);
    m_nextIdBase += batch->elementCount();
    const int mode = m_linesOnly ? ElementBatch::LinesOnly : ElementBatch::Shaded;
    batch->SetDisplayMode(mode); // the object's own mode, so later redisplays keep it
    m_context->Display(batch, mode, 0, false);
    if (m_sectionZ)
        rebuildSection();
    update();
}

void Viewport::setLinesOnly(bool on)
{
    m_linesOnly = on;
    const int mode = on ? ElementBatch::LinesOnly : ElementBatch::Shaded;
    for (const auto& b : m_batches)
        m_context->SetDisplayMode(b, mode, false);
    update();
}

void Viewport::clear()
{
    for (const auto& prs : std::as_const(m_annotations))
        m_context->Remove(prs, false);
    m_annotations.clear();
    m_annotationData.clear();
    m_markerData.clear();
    m_context->RemoveAll(false);
    m_batches.clear();
    m_locate.clear();
    m_idBases.clear();
    m_grid.Nullify();
    m_gridLineCount = 0;
    m_section.Nullify();
    m_sectionElements = 0;
    m_preview.Nullify();
    m_nextIdBase = 0;
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

void Viewport::applyColors(const Handle(ElementBatch)& batch) const
{
    for (int i = 0; i < batch->elementCount(); ++i) {
        const auto it = m_colors.constFind(batch->guid(i));
        batch->setColorOverride(i, it == m_colors.constEnd()
                ? std::nullopt
                : std::optional<Quantity_Color>(Quantity_Color(it->redF(), it->greenF(), it->blueF(), Quantity_TOC_sRGB)));
    }
}

void Viewport::setElementColors(const QHash<QString, QColor>& colors)
{
    m_colors = colors;
    std::vector<int> touched;
    for (size_t b = 0; b < m_batches.size(); ++b) {
        applyColors(m_batches[b]);
        touched.push_back(int(b));
    }
    redisplay(touched);
}

void Viewport::applyLayerState(const Handle(ElementBatch)& batch) const
{
    for (int i = 0; i < batch->elementCount(); ++i) {
        batch->setLayerHidden(i, m_layerHidden.contains(batch->guid(i)));
        batch->setLocked(i, m_layerLocked.contains(batch->guid(i)));
    }
}

void Viewport::setLayerState(const QSet<QString>& hiddenGuids, const QSet<QString>& lockedGuids)
{
    m_layerHidden = hiddenGuids;
    m_layerLocked = lockedGuids;
    // Hidden or locked elements can't stay selected.
    for (const QString& g : selectedGuids())
        if (hiddenGuids.contains(g) || lockedGuids.contains(g)) {
            const auto it = m_locate.constFind(g);
            if (it != m_locate.constEnd())
                m_context->AddOrRemoveSelected(m_batches[size_t(it->batch)]->owner(it->index), false);
        }
    std::vector<int> touched;
    for (size_t b = 0; b < m_batches.size(); ++b) {
        applyLayerState(m_batches[b]);
        touched.push_back(int(b));
    }
    redisplay(touched);
    displayAnnotations();
}

bool Viewport::isLocked(const QString& guid) const
{
    const auto it = m_locate.constFind(guid);
    return it != m_locate.constEnd() && m_batches[size_t(it->batch)]->isLocked(it->index);
}

int Viewport::coloredCount() const
{
    int n = 0;
    for (auto it = m_colors.constBegin(); it != m_colors.constEnd(); ++it)
        n += m_locate.contains(it.key()) ? 1 : 0;
    return n;
}

QString Viewport::typeOf(const QString& guid) const
{
    const auto it = m_locate.constFind(guid);
    if (it == m_locate.constEnd())
        return m_annotations.contains(guid) ? QStringLiteral("IfcAnnotation") : QString();
    return m_batches[size_t(it->batch)]->type(it->index);
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
        else if (Handle(AnnotationOwner) note = Handle(AnnotationOwner)::DownCast(m_context->SelectedOwner()); !note.IsNull())
            out << note->guid();
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
        else if (const auto note = m_annotations.constFind(g); note != m_annotations.constEnd()) {
            const Handle(SelectMgr_EntityOwner)& owner = Handle(AnnotationPrs)::DownCast(*note)->owner();
            if (!owner.IsNull())
                m_context->AddOrRemoveSelected(owner, false);
        }
    }
    m_context->UpdateCurrentViewer();
    update();
}

void Viewport::redisplay(const std::vector<int>& batches)
{
    if (m_sectionZ && !batches.empty())
        rebuildSection();
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
