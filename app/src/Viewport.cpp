// SPDX-License-Identifier: GPL-3.0-or-later
#include "Viewport.h"

#include <Aspect_DisplayConnection.hxx>
#include <Graphic3d_ClipPlane.hxx>
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
    if (PressMouseButton(toPixels(e->position()), toButtons(e->button()), toFlags(e->modifiers()), false))
        update();
}

void Viewport::mouseReleaseEvent(QMouseEvent* e)
{
    if (m_drawingMode && (e->button() == Qt::LeftButton || e->button() == Qt::RightButton))
        return;
    // The released button, not the ones still held: passing the held set kept pan/orbit running
    // after release until a modifier key changed (owner bug report).
    if (ReleaseMouseButton(toPixels(e->position()), toButtons(e->button()), toFlags(e->modifiers()), false))
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
    batch->setIdBase(m_nextIdBase);
    m_idBases.push_back(m_nextIdBase);
    m_nextIdBase += batch->elementCount();
    const int mode = m_linesOnly ? ElementBatch::LinesOnly : ElementBatch::Shaded;
    batch->SetDisplayMode(mode); // the object's own mode, so later redisplays keep it
    m_context->Display(batch, mode, 0, false);
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
    m_context->RemoveAll(false);
    m_batches.clear();
    m_locate.clear();
    m_idBases.clear();
    m_grid.Nullify();
    m_gridLineCount = 0;
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
