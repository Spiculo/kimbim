// SPDX-License-Identifier: GPL-3.0-or-later
#include "Viewport.h"
#include "CutPlanes.h"
#include "Graphics.h"
#include "PolygonTool.h"
#include "ViewCube.h"

#include <AIS_RubberBand.hxx>
#include <Aspect_DisplayConnection.hxx>
#include <Graphic3d_ClipPlane.hxx>
#include <gp_Pln.hxx>
#include <OpenGl_GraphicDriver.hxx>
#include <Prs3d_Drawer.hxx>
#include <Standard_Failure.hxx>
#include <TCollection_ExtendedString.hxx>
#include <Graphic3d_AspectLine3d.hxx>
#include <Graphic3d_ArrayOfSegments.hxx>
#include <Graphic3d_AspectFillArea3d.hxx>
#include <Graphic3d_ArrayOfTriangles.hxx>
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
#include <gp_Trsf.hxx>
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
#include <array>
#include <cmath>
#include <QJsonArray>
#include <QJsonObject>
#include <HLRAlgo_Projector.hxx>
#include <HLRBRep_PolyAlgo.hxx>
#include <HLRBRep_PolyHLRToShape.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRep_Tool.hxx>
#include <TopLoc_Location.hxx>
#include <GCPnts_QuasiUniformDeflection.hxx>
#include <gp_Ax3.hxx>
#include <gp_Vec.hxx>
#include <cmath>
#include <set>

namespace kimbim {

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
    : Viewport(new Scene, parent)
{
    m_scene->setParent(this); // owned: this view is its only one
}

Viewport::Viewport(Scene* scene, QWidget* parent)
    : QWidget(parent)
    , m_scene(scene)
    , m_context(scene->context())
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

    m_view = m_scene->createView();
    const Quantity_Color background(0.93, 0.94, 0.95, Quantity_TOC_RGB);
    m_view->SetBackgroundColor(background);
    ElementBatch::setBackground(background); // lines-only faces blend into it
    m_view->SetProj(HomeOrientation);
    m_animation = new AIS_AnimationCamera("kimbimViewAnimation", m_view);
    SetViewAnimation(m_animation); // played in handleViewRedraw, stopped by mouse input
    applyNavigationPreset();
    connect(m_scene, &Scene::redrawRequested, this, qOverload<>(&QWidget::update));
    connect(m_scene, &Scene::viewsChanged, this, &Viewport::keepOverlaysHere); // views opened later
    connect(m_scene, &Scene::elementsAltered, this, [this] {
        if (!m_sectionPlanes.empty())
            rebuildSections();
    });
}

void Viewport::setPlanView(double elevation)
{
    const bool wasPlan = m_planView;
    m_planView = true;
    m_planElevation = elevation;
    AbortViewAnimation();
    eraseViewCube(); // D76: plans have no cube
    m_view->Camera()->SetProjectionType(Graphic3d_Camera::Projection_Orthographic);
    m_view->SetProj(V3d_Zpos); // looking down, north (+Y) up
    applyNavigationPreset();
    if (!wasPlan && (!m_markerData.isEmpty() || !m_annotationData.isEmpty()))
        displayAnnotations(); // section/elevation markers and drafting (D84) belong to the plan
    if (ensureWindow())
        fitAll();
    update();
}

void Viewport::set3DView()
{
    const bool wasPlan = m_planView;
    m_planView = false;
    AbortViewAnimation();
    m_view->SetProj(HomeOrientation);
    applyProjection(); // this view's perspective setting comes back
    applyNavigationPreset();
    if (wasPlan && (!m_markerData.isEmpty() || !m_annotationData.isEmpty()))
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
    if (!ensureWindow() || m_scene->nextIdBase > ElementBatch::maxId())
        return std::nullopt;
    int w = 0, h = 0;
    m_view->Window()->Size(w, h);
    if (w <= 0 || h <= 0)
        return std::nullopt;
    return idsInImage(w, h, x0, y0, x1, y1);
}

std::optional<QSet<QString>> Viewport::idsInImage(int w, int h, int x0, int y0, int x1, int y1)
{
    const auto ids = renderIds(w, h);
    if (!ids)
        return std::nullopt;
    QSet<int> seen;
    const int xa = std::clamp(std::min(x0, x1), 0, w - 1), xb = std::clamp(std::max(x0, x1), 0, w - 1);
    const int ya = std::clamp(std::min(y0, y1), 0, h - 1), yb = std::clamp(std::max(y0, y1), 0, h - 1);
    for (int y = ya; y <= yb; ++y)
        for (int x = xa; x <= xb; ++x) {
            const int id = ids->at(x, y);
            if (id > 0)
                seen.insert(id);
        }
    QSet<QString> out;
    for (int id : std::as_const(seen)) {
        const QString g = guidOfId(id);
        if (!g.isEmpty())
            out.insert(g);
    }
    return out;
}

int Viewport::IdImage::at(int x, int y) const
{
    if (x < 0 || y < 0 || x >= width || y >= height)
        return 0;
    // Image_PixMap's RawValue already counts rows from the top whatever the memory order (it walks
    // TopToDown): flipping the row again here read the image upside down.
    const uint8_t* p = image->RawValue(size_t(y), size_t(x));
    const int r = bgr ? p[2] : p[0], g = p[1], b = bgr ? p[0] : p[2];
    return ElementBatch::idFromRgb(toLinear[size_t(r)], toLinear[size_t(g)], toLinear[size_t(b)]);
}

std::optional<Viewport::IdImage> Viewport::renderIds(int w, int h)
{
    // Draw every element in its id colour on grey, without highlights or lines, into an offscreen
    // image of the view; clip planes still apply, hidden elements are not drawn. Everything that is
    // not an element (annotations and room labels, the grid, the view cube, previews, underlays) is
    // left out of this view meanwhile: it would cover the elements behind it.
    const Quantity_Color background = m_view->BackgroundColor();
    // A mid grey that is never a valid id; how it comes back tells whether the buffer sRGB-encodes.
    m_view->SetBackgroundColor(Quantity_Color(128 / 255.0, 128 / 255.0, 128 / 255.0, Quantity_TOC_RGB));
    const int viewId = m_view->View()->Identification();
    NCollection_List<Handle(AIS_InteractiveObject)> shown;
    m_context->DisplayedObjects(shown);
    std::vector<Handle(AIS_InteractiveObject)> setAside;
    for (const Handle(AIS_InteractiveObject)& o : shown) {
        if (!Handle(ElementBatch)::DownCast(o).IsNull())
            continue;
        if (!o->ViewAffinity().IsNull() && !o->ViewAffinity()->IsVisible(viewId))
            continue; // not shown in this view anyway
        m_context->SetViewAffinity(o, m_view, false);
        setAside.push_back(o);
    }
    m_context->ClearDetected(false);
    m_context->UnhilightSelected(false);
    for (const auto& b : m_scene->batches)
        m_context->SetDisplayMode(b, ElementBatch::Ids, false);
    IdImage out;
    out.image = std::make_shared<Image_PixMap>();
    out.width = w;
    out.height = h;
    V3d_ImageDumpOptions options;
    options.Width = w;
    options.Height = h;
    options.BufferType = Graphic3d_BT_RGB;
    const bool ok = m_view->ToPixMap(*out.image, options);
    const int mode = m_scene->linesOnly ? ElementBatch::LinesOnly : ElementBatch::Shaded;
    for (const auto& b : m_scene->batches)
        m_context->SetDisplayMode(b, mode, false);
    m_view->SetBackgroundColor(background);
    for (const auto& o : setAside)
        m_context->SetViewAffinity(o, m_view, true);
    m_context->HilightSelected(false);
    update();
    if (!ok)
        return std::nullopt;

    const Image_PixMap& image = *out.image;
    out.bgr = image.Format() == Image_Format_BGR || image.Format() == Image_Format_BGR32;
    // Calibrate: background pixels read ~128 (stored as is) or ~188 (sRGB-encoded on output).
    int linearHits = 0, srgbHits = 0;
    for (int y = 0; y < h; y += 7)
        for (int x = 0; x < w; x += 7) {
            const uint8_t* p = image.RawValue(size_t(y), size_t(x));
            if (std::abs(p[0] - 128) <= 2 && p[0] == p[1] && p[1] == p[2])
                ++linearHits;
            else if (std::abs(p[0] - 188) <= 2 && p[0] == p[1] && p[1] == p[2])
                ++srgbHits;
        }
    for (int i = 0; i < 256; ++i) {
        const double c = i / 255.0;
        const double l = srgbHits > linearHits ? (c <= 0.04045 ? c / 12.92 : std::pow((c + 0.055) / 1.055, 2.4)) : c;
        out.toLinear[size_t(i)] = int(std::lround(l * 255.0));
    }
    return out;
}

QString Viewport::guidOfId(int id) const
{
    if (id <= 0)
        return QString();
    const auto it = std::upper_bound(m_scene->idBases.begin(), m_scene->idBases.end(), id - 1);
    if (it == m_scene->idBases.begin())
        return QString();
    const size_t b = size_t(std::distance(m_scene->idBases.begin(), it) - 1);
    const int index = id - 1 - m_scene->idBases[b];
    if (index < m_scene->batches[b]->elementCount() && !m_scene->batches[b]->isRetired(index))
        return m_scene->batches[b]->guid(index);
    return QString();
}

// The id image for a width x height span (metres): 2048 pixels on its long side, more for a long or
// wide drawing (a site elevation is hundreds of metres by a dozen: 2048 x 64 pixels would merge
// every element), aiming at 3 cm a pixel, at most 8192 pixels a side and 16 Mpixels in all.
static std::pair<int, int> idImageSize(double width, double height)
{
    width = std::max(width, 1e-3);
    height = std::max(height, 1e-3);
    const double longest = std::max(width, height);
    double ppm = std::max(2048.0 / longest, std::min(1.0 / 0.03, 8192.0 / longest));
    ppm = std::min(ppm, std::sqrt(16.0e6 / (width * height)));
    return {std::clamp(int(std::lround(width * ppm)), 64, 8192), std::clamp(int(std::lround(height * ppm)), 64, 8192)};
}

// An orthographic Graphic3d_Camera's scale is the image's smaller side: its height for a wide image,
// its width for a tall one. The scale that shows a width x height span (metres) at this aspect.
static double orthoScale(double width, double height, double aspect)
{
    return aspect >= 1.0 ? std::max(height, width / aspect) : std::max(width, height * aspect);
}

std::optional<QSet<QString>> Viewport::visibleFrom(QPointF p1, QPointF p2, QPointF look, double z0, double z1, double depth)
{
    const QPointF d = p2 - p1;
    const double len = std::hypot(d.x(), d.y());
    if (!ensureWindow() || m_scene->batches.empty() || m_scene->nextIdBase > ElementBatch::maxId() || len < 1e-6 || z1 <= z0)
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
    for (const auto& plane : m_clipPlanes)
        m_view->RemoveClipPlane(plane);
    for (const auto& b : m_scene->batches)
        for (const auto& plane : planes)
            b->AddClipPlane(plane);
    Handle(Graphic3d_Camera) saved = new Graphic3d_Camera();
    saved->Copy(m_view->Camera());
    const Handle(Graphic3d_Camera)& camera = m_view->Camera();
    const QPointF mid = (p1 + p2) / 2;
    const double zm = (z0 + z1) / 2, height = z1 - z0;
    camera->SetProjectionType(Graphic3d_Camera::Projection_Orthographic);
    camera->SetUp(gp_Dir(0, 0, 1));
    camera->SetCenter(gp_Pnt(mid.x(), mid.y(), zm));
    camera->SetEye(gp_Pnt(mid.x() - n.x() * 10, mid.y() - n.y() * 10, zm));
    // The image has the drawing's proportions.
    const auto [w, h] = idImageSize(len, height);
    camera->SetScale(orthoScale(len * 1.02, height * 1.02, double(w) / h));
    camera->SetAspect(double(w) / h);
    m_view->ZFitAll();
    const auto ids = idsInImage(w, h, 0, 0, w - 1, h - 1);
    for (const auto& b : m_scene->batches)
        for (const auto& plane : planes)
            b->RemoveClipPlane(plane);
    for (const auto& plane : m_clipPlanes)
        m_view->AddClipPlane(plane);
    m_view->Camera()->Copy(saved);
    m_view->Invalidate();
    update();
    return ids;
}

std::optional<QSet<QString>> Viewport::visibleFromPlan(const Bnd_Box& bounds, double elevation, double cut, double floor)
{
    if (!ensureWindow() || m_scene->batches.empty() || m_scene->nextIdBase > ElementBatch::maxId() || bounds.IsVoid())
        return std::nullopt;
    double x0, y0, z0, x1, y1, z1;
    bounds.Get(x0, y0, z0, x1, y1, z1);
    const double cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const double cutZ = elevation + cut, floorZ = elevation - floor;
    // Keep what the plan cuts and projects: below the cut plane, down to the floor.
    std::vector<Handle(Graphic3d_ClipPlane)> planes;
    planes.push_back(new Graphic3d_ClipPlane(gp_Pln(gp_Pnt(0, 0, cutZ), gp_Dir(0, 0, -1))));
    planes.push_back(new Graphic3d_ClipPlane(gp_Pln(gp_Pnt(0, 0, floorZ), gp_Dir(0, 0, 1))));
    for (const auto& plane : m_clipPlanes)
        m_view->RemoveClipPlane(plane);
    for (const auto& b : m_scene->batches)
        for (const auto& plane : planes)
            b->AddClipPlane(plane);
    Handle(Graphic3d_Camera) saved = new Graphic3d_Camera();
    saved->Copy(m_view->Camera());
    const Handle(Graphic3d_Camera)& camera = m_view->Camera();
    const double w = std::max(x1 - x0, 1e-3), h = std::max(y1 - y0, 1e-3);
    camera->SetProjectionType(Graphic3d_Camera::Projection_Orthographic);
    camera->SetUp(gp_Dir(0, 1, 0)); // north up, looking straight down
    camera->SetCenter(gp_Pnt(cx, cy, elevation));
    camera->SetEye(gp_Pnt(cx, cy, cutZ + 10.0));
    const auto [px, py] = idImageSize(w, h);
    camera->SetScale(orthoScale(w * 1.02, h * 1.02, double(px) / py));
    camera->SetAspect(double(px) / py);
    m_view->ZFitAll();
    const auto ids = idsInImage(px, py, 0, 0, px - 1, py - 1);
    for (const auto& b : m_scene->batches)
        for (const auto& plane : planes)
            b->RemoveClipPlane(plane);
    for (const auto& plane : m_clipPlanes)
        m_view->AddClipPlane(plane);
    m_view->Camera()->Copy(saved);
    m_view->Invalidate();
    update();
    return ids;
}

QJsonObject Viewport::planGeometry(const QStringList& guids, double cutZ, double floorZ) const
{
    const QSet<QString> wanted(guids.begin(), guids.end());
    QJsonArray cut, proj;
    bool any = false;
    double x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    auto loops_json = [&](const std::vector<std::vector<gp_Pnt2d>>& loops) {
        QJsonArray out;
        for (const auto& loop : loops) {
            QJsonArray pts;
            for (const auto& p : loop) {
                pts.append(QJsonArray{p.X(), p.Y()});
                if (!any) {
                    x0 = x1 = p.X();
                    y0 = y1 = p.Y();
                    any = true;
                } else {
                    x0 = std::min(x0, p.X());
                    x1 = std::max(x1, p.X());
                    y0 = std::min(y0, p.Y());
                    y1 = std::max(y1, p.Y());
                }
            }
            out.append(pts);
        }
        return out;
    };
    for (const auto& b : m_scene->batches) {
        for (int i = 0; i < b->elementCount(); ++i) {
            if (b->isHidden(i))
                continue;
            const QString g = b->guid(i);
            if (!wanted.contains(g))
                continue;
            const auto c = b->sectionLoops(i, cutZ); // the element crosses the cut: draw it as cut
            if (!c.empty()) {
                cut.append(QJsonObject{{"guid", g}, {"loops", loops_json(c)}});
                continue;
            }
            const Bnd_Box bb = b->elementBounds(i); // below the cut: draw its top outline in projection
            if (bb.IsVoid())
                continue;
            double bx0, by0, bz0, bx1, by1, bz1;
            bb.Get(bx0, by0, bz0, bx1, by1, bz1);
            const double zTop = std::min(bz1, cutZ) - 1e-3;
            if (zTop <= floorZ)
                continue;
            const auto p = b->sectionLoops(i, zTop);
            if (p.empty())
                continue;
            proj.append(QJsonObject{{"guid", g}, {"loops", loops_json(p)}});
        }
    }
    return QJsonObject{{"cut", cut}, {"proj", proj}, {"bounds", QJsonArray{x0, y0, x1, y1}}};
}

QJsonObject Viewport::viewGeometry(const QStringList& guids, const gp_Ax2& view, const gp_Pln* section, const Bnd_Box& bounds)
{
    const QSet<QString> wanted(guids.begin(), guids.end());
    const gp_Ax3 ax3(view);
    const gp_Dir toward(ax3.Direction());
    auto to_view = [&](const gp_Pnt& p) {
        const gp_Vec d(ax3.Location(), p);
        return QPointF(d.Dot(gp_Vec(ax3.XDirection())), d.Dot(gp_Vec(ax3.YDirection())));
    };
    // Hidden-line removal by depth: render the front-most element per pixel from the drawing camera (id
    // colours), then keep only the parts of each projected edge whose pixel belongs to that element.
    // Without a window (headless) every facing edge is kept.
    std::optional<IdImage> ids;
    double cx = 0, cy = 0, spanX = 1, spanY = 1; // the image's centre and size in view metres
    if (ensureWindow() && !m_scene->batches.empty() && m_scene->nextIdBase <= ElementBatch::maxId()
        && !bounds.IsVoid()) {
        double x0, y0, z0, x1, y1, z1;
        bounds.Get(x0, y0, z0, x1, y1, z1);
        double vx0 = 1e30, vy0 = 1e30, vx1 = -1e30, vy1 = -1e30;
        for (double xx : {x0, x1})
            for (double yy : {y0, y1})
                for (double zz : {z0, z1}) {
                    const QPointF v = to_view(gp_Pnt(xx, yy, zz));
                    vx0 = std::min(vx0, v.x());
                    vx1 = std::max(vx1, v.x());
                    vy0 = std::min(vy0, v.y());
                    vy1 = std::max(vy1, v.y());
                }
        // A margin: the edges on the bounds' rim still land inside the image.
        const double vw = std::max(vx1 - vx0, 1e-3) * 1.04, vh = std::max(vy1 - vy0, 1e-3) * 1.04;
        const auto [iw, ih] = idImageSize(vw, vh);
        const double aspect = double(iw) / ih;
        const double scale = orthoScale(vw, vh, aspect);
        spanX = aspect >= 1.0 ? scale * aspect : scale;
        spanY = aspect >= 1.0 ? scale : scale / aspect;
        cx = (vx0 + vx1) / 2;
        cy = (vy0 + vy1) / 2;
        Handle(Graphic3d_Camera) saved = new Graphic3d_Camera();
        saved->Copy(m_view->Camera());
        const Handle(Graphic3d_Camera)& cam = m_view->Camera();
        // Centred on the bounds (a section line need not be): right is the view's X, up its Y.
        const gp_Pnt centre(ax3.Location().XYZ() + gp_XYZ(ax3.XDirection().XYZ()) * cx + gp_XYZ(ax3.YDirection().XYZ()) * cy);
        cam->SetProjectionType(Graphic3d_Camera::Projection_Orthographic);
        cam->SetUp(gp_Dir(ax3.YDirection()));
        cam->SetCenter(centre);
        cam->SetEye(gp_Pnt(centre.XYZ() + toward.XYZ() * 10.0));
        cam->SetScale(scale);
        cam->SetAspect(aspect);
        std::vector<Handle(Graphic3d_ClipPlane)> planes;
        if (section != nullptr)
            planes.push_back(new Graphic3d_ClipPlane(*section));
        for (const auto& plane : m_clipPlanes)
            m_view->RemoveClipPlane(plane);
        for (const auto& b : m_scene->batches)
            for (const auto& plane : planes)
                b->AddClipPlane(plane);
        m_view->ZFitAll(); // the depth range of this camera, not the 3D view's
        ids = renderIds(iw, ih);
        for (const auto& b : m_scene->batches)
            for (const auto& plane : planes)
                b->RemoveClipPlane(plane);
        for (const auto& plane : m_clipPlanes)
            m_view->AddClipPlane(plane);
        m_view->Camera()->Copy(saved);
        m_view->Invalidate();
        update();
    }
    // A view point -> image pixel, from the camera set above (no window round trip: the window is a
    // different size, and its integer pixels lose precision).
    auto to_pixel = [&](const QPointF& v) {
        return QPointF((((v.x() - cx) / spanX) + 0.5) * ids->width, (0.5 - (v.y() - cy) / spanY) * ids->height);
    };
    // An edge lies on its element's rim, where half the pixels belong to what is beside or behind it:
    // the element is seen at a point when it owns a pixel within one pixel of it.
    auto owns = [&](double px, double py, int id) {
        const int x = int(std::floor(px)), y = int(std::floor(py));
        for (int dy = -1; dy <= 1; ++dy)
            for (int dx = -1; dx <= 1; ++dx)
                if (ids->at(x + dx, y + dy) == id)
                    return true;
        return false;
    };
    QJsonArray proj;
    for (const auto& b : m_scene->batches) {
        for (int i = 0; i < b->elementCount(); ++i) {
            if (b->isHidden(i))
                continue;
            const QString g = b->guid(i);
            if (!wanted.contains(g))
                continue;
            const int myId = b->idBase() + i + 1;
            QJsonArray lines;
            for (const auto& [a, e] : ElementBatch::featureEdgesFacing(b->chunk(), i, toward)) {
                const QPointF pa = to_view(a), pb = to_view(e);
                if (!ids) {
                    lines.append(QJsonArray{pa.x(), pa.y(), pb.x(), pb.y()});
                    continue;
                }
                const QPointF ia = to_pixel(pa), ib = to_pixel(pb);
                const int n = std::max(2, int(std::ceil(std::hypot(ia.x() - ib.x(), ia.y() - ib.y()))));
                int run = -1;
                for (int k = 0; k <= n; ++k) {
                    const double t = double(k) / n;
                    const bool v = owns(ia.x() + (ib.x() - ia.x()) * t, ia.y() + (ib.y() - ia.y()) * t, myId);
                    if (v && run < 0)
                        run = k;
                    if ((!v || k == n) && run >= 0) {
                        const int end = v ? k : k - 1;
                        if (end > run) {
                            const double t0 = double(run) / n, t1 = double(end) / n;
                            const QPointF q0 = pa + (pb - pa) * t0, q1 = pa + (pb - pa) * t1;
                            lines.append(QJsonArray{q0.x(), q0.y(), q1.x(), q1.y()});
                        }
                        run = -1;
                    }
                }
            }
            if (!lines.isEmpty())
                proj.append(QJsonObject{{"guid", g}, {"lines", lines}});
        }
    }
    return finishViewGeometry(ax3, proj, section);
}

QJsonObject Viewport::finishViewGeometry(const gp_Ax3& ax3, const QJsonArray& proj, const gp_Pln* section) const
{
    QJsonArray cut;
    if (section != nullptr) { // the cut plane: filled poché per element (always visible)
        for (const auto& b : m_scene->batches) {
            for (int i = 0; i < b->elementCount(); ++i) {
                if (b->isHidden(i))
                    continue;
                const auto loops = ElementBatch::sectionLoopsPlane(b->chunk(), i, *section);
                if (loops.empty())
                    continue;
                QJsonArray jloops;
                for (const auto& loop : loops) {
                    QJsonArray pts;
                    for (const auto& p : loop) {
                        const gp_Vec d(ax3.Location(), p);
                        pts.append(QJsonArray{d.Dot(gp_Vec(ax3.XDirection())), d.Dot(gp_Vec(ax3.YDirection()))});
                    }
                    jloops.append(pts);
                }
                cut.append(QJsonObject{{"guid", b->guid(i)}, {"loops", jloops}});
            }
        }
    }
    const gp_Dir xd = ax3.XDirection(), yd = ax3.YDirection(), zd = ax3.Direction();
    const gp_Pnt o = ax3.Location();
    // Row-major view->world matrix (the `plane` the SVG overlays read): columns x, y, z, origin.
    const QJsonArray vm = {xd.X(), yd.X(), zd.X(), o.X(), xd.Y(), yd.Y(), zd.Y(), o.Y(),
        xd.Z(), yd.Z(), zd.Z(), o.Z(), 0, 0, 0, 1};
    return QJsonObject{{"proj", proj}, {"cut", cut}, {"view", vm}};
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
        const auto it = m_scene->locate.constFind(g);
        if (it != m_scene->locate.constEnd())
            m_context->AddOrRemoveSelected(m_scene->batches[size_t(it->batch)]->owner(it->index), false);
    }
    m_context->UpdateCurrentViewer();
}

void Viewport::handleSelectionPoly(const Handle(AIS_InteractiveContext)& ctx, const Handle(V3d_View)& view)
{
    const auto& points = myUI.Selection.Points;
    const bool rectangle = myUI.Selection.Tool == AIS_ViewSelectionTool_RubberBand && points.Size() == 2;
    const bool through = m_selectThrough || (LastMouseFlags() & Aspect_VKeyFlags_ALT) != 0;
    // D78: right to left is a crossing box (dashed band), left to right a window box (solid band).
    const bool crossing = rectangle && isCrossingBox(points.First().x(), points.Last().x());
    if (rectangle && !myRubberBand.IsNull())
        myRubberBand->SetLineType(crossing ? Aspect_TOL_DASH : Aspect_TOL_SOLID);
    struct OverlapScope { // the selector takes touched elements only for this crossing box
        const Handle(AIS_InteractiveContext)& c;
        OverlapScope(const Handle(AIS_InteractiveContext)& ctx, bool on) : c(ctx) { c->MainSelector()->AllowOverlapDetection(on); }
        ~OverlapScope() { c->MainSelector()->AllowOverlapDetection(false); }
    } overlap(ctx, crossing);
    if (!rectangle || through) {
        AIS_ViewController::handleSelectionPoly(ctx, view);
        return;
    }
    const NCollection_Vec2<int> a = points.First(), b = points.Last();
    const AIS_SelectionScheme scheme = myUI.Selection.Scheme;
    const QSet<QString> before = selectedSet();
    m_scene->quietSelection = true; // one notification, after hidden elements were dropped
    AIS_ViewController::handleSelectionPoly(ctx, view);
    m_scene->quietSelection = false;
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
    m_context->MainSelector()->AllowOverlapDetection(isCrossingBox(x0, x1));
    m_context->SelectRectangle(NCollection_Vec2<int>(std::min(x0, x1), std::min(y0, y1)),
        NCollection_Vec2<int>(std::max(x0, x1), std::max(y0, y1)), m_view, scheme);
    m_context->MainSelector()->AllowOverlapDetection(false);
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
    // This view's own overlays leave the shared context; the elements stay for the other views.
    for (const Handle(AIS_InteractiveObject)& o :
         {Handle(AIS_InteractiveObject)(m_preview), Handle(AIS_InteractiveObject)(m_grid),
             Handle(AIS_InteractiveObject)(m_cube), m_home})
        if (!o.IsNull())
            m_context->Remove(o, false);
    for (const auto& a : std::as_const(m_annotations))
        m_context->Remove(a, false);
    removeUnderlays();
    if (m_scene)
        m_scene->removeView(m_view);
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
        Handle(Xw_Window) window = new Xw_Window(m_scene->viewer()->Driver()->GetDisplayConnection(), Aspect_Drawable(winId()));
#endif
        m_view->SetWindow(window);
        if (!window->IsMapped())
            window->Map();
        m_view->MustBeResized();
        return true;
    } catch (const Standard_Failure& e) {
        // Never let an OCCT exception escape into a Qt event handler (it aborts the app).
        qWarning("KimBim: cannot attach the 3D view to its window: %s", e.what());
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
    ensureViewCube();
    m_view->Invalidate();
    FlushViewEvents(m_context, m_view, true);
    // Wheel zoom is applied while flushing the view events: report it after.
    if (const double zoom = zoomPercent(); std::abs(zoom - m_lastZoom) > 0.5) {
        m_lastZoom = zoom;
        emit zoomChanged(zoom);
    }
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

// Cut sections: filled outlines (unlit) plus bold borders, drawn just inside the kept half-space.
// D73: one part per style (the element's fill pen and cut line); no fill colour = outline only.
struct SectionPart {
    std::vector<std::vector<gp_Pnt>> loops;
    std::optional<Quantity_Color> fill;
    Quantity_Color line;
    float width = 2.0f;
    uint16_t pattern = 0xFFFF;
};

class SectionPrs : public AIS_InteractiveObject {
public:
    SectionPrs(std::vector<SectionPart> parts, const gp_Pln& plane)
        : m_parts(std::move(parts))
        , m_plane(plane)
    {
    }
    void Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int) override
    {
        gp_Pnt origin;
        gp_Dir u, v;
        planeBasis(m_plane, &origin, &u, &v);
        const gp_Dir n = m_plane.Axis().Direction();
        // A hair inside the kept half-space, so the fill never z-fights with the cut faces.
        const gp_Vec lift = gp_Vec(n) * 1e-4;
        auto liftPnt = [&](const gp_Pnt& p) {
            const gp_Vec d(origin, p);
            return gp_Pnt(origin.XYZ() + u.XYZ() * d.Dot(gp_Vec(u)) + v.XYZ() * d.Dot(gp_Vec(v)) + lift.XYZ());
        };
        for (const SectionPart& part : m_parts) {
            int triangles = 0, segments = 0;
            std::vector<std::vector<uint32_t>> tris;
            for (const auto& loop : part.loops) {
                QVector<QPointF> poly;
                for (const auto& p : loop) {
                    const gp_Vec d(origin, p);
                    poly << QPointF(d.Dot(gp_Vec(u)), d.Dot(gp_Vec(v)));
                }
                tris.push_back(part.fill ? PolygonTool::triangulate(poly) : std::vector<uint32_t>{});
                triangles += int(tris.back().size() / 3);
                segments += int(loop.size());
            }
            if (triangles > 0) {
                Handle(Graphic3d_ArrayOfTriangles) fill = new Graphic3d_ArrayOfTriangles(triangles * 3);
                for (size_t l = 0; l < part.loops.size(); ++l)
                    for (uint32_t i : tris[l]) {
                        const gp_Pnt p = liftPnt(part.loops[l][i]);
                        fill->AddVertex(p);
                    }
                Handle(Graphic3d_Group) g = prs->NewGroup();
                Handle(Graphic3d_AspectFillArea3d) aspect = new Graphic3d_AspectFillArea3d();
                aspect->SetInteriorStyle(Aspect_IS_SOLID);
                aspect->SetInteriorColor(*part.fill);
                aspect->SetShadingModel(Graphic3d_TypeOfShadingModel_Unlit);
                aspect->SetFaceCulling(Graphic3d_TypeOfBackfacingModel_DoubleSided);
                g->SetGroupPrimitivesAspect(aspect);
                g->AddPrimitiveArray(fill);
            }
            if (segments > 0) {
                Handle(Graphic3d_ArrayOfSegments) lines = new Graphic3d_ArrayOfSegments(segments * 2);
                for (const auto& loop : part.loops)
                    for (size_t i = 0; i < loop.size(); ++i) {
                        lines->AddVertex(liftPnt(loop[i]));
                        lines->AddVertex(liftPnt(loop[(i + 1) % loop.size()]));
                    }
                Handle(Graphic3d_AspectLine3d) aspect = new Graphic3d_AspectLine3d(part.line, Aspect_TOL_SOLID, part.width);
                if (part.pattern != 0xFFFF)
                    aspect->SetLinePattern(part.pattern);
                Handle(Graphic3d_Group) g = prs->NewGroup();
                g->SetGroupPrimitivesAspect(aspect);
                g->AddPrimitiveArray(lines);
            }
        }
    }
    void ComputeSelection(const Handle(SelectMgr_Selection)&, const int) override {}

private:
    std::vector<SectionPart> m_parts;
    gp_Pln m_plane;
};

bool samePlane(const gp_Pln& a, const gp_Pln& b)
{
    const gp_Dir na = a.Axis().Direction(), nb = b.Axis().Direction();
    return na.Dot(nb) > 1 - 1e-9
        && std::abs(gp_Vec(a.Location(), b.Location()).Dot(gp_Vec(na))) < 1e-7;
}

// Keep the part of a section loop inside another cut's kept half-space (Sutherland-Hodgman).
std::vector<gp_Pnt> clipLoop(const std::vector<gp_Pnt>& loop, const gp_Pln& clip)
{
    const gp_Pnt o = clip.Location();
    const gp_Dir n = clip.Axis().Direction();
    auto side = [&](const gp_Pnt& p) { return gp_Vec(o, p).Dot(gp_Vec(n)); };
    std::vector<gp_Pnt> out;
    for (size_t i = 0; i < loop.size(); ++i) {
        const gp_Pnt& a = loop[i];
        const gp_Pnt& b = loop[(i + 1) % loop.size()];
        const double da = side(a), db = side(b);
        if (da >= -1e-9)
            out.push_back(a);
        if ((da > 1e-9 && db < -1e-9) || (da < -1e-9 && db > 1e-9)) {
            const double t = da / (da - db);
            out.emplace_back(a.X() + t * (b.X() - a.X()), a.Y() + t * (b.Y() - a.Y()),
                a.Z() + t * (b.Z() - a.Z()));
        }
    }
    // Consecutive duplicates make triangulation unhappy.
    std::vector<gp_Pnt> clean;
    for (const gp_Pnt& p : out)
        if (clean.empty() || clean.back().Distance(p) > 1e-9)
            clean.push_back(p);
    if (clean.size() > 1 && clean.front().Distance(clean.back()) < 1e-9)
        clean.pop_back();
    return clean.size() >= 3 ? clean : std::vector<gp_Pnt>{};
}

} // namespace

void Viewport::setSectionHeight(std::optional<double> z)
{
    if (!z) {
        setSectionPlanes({}, {});
        return;
    }
    const gp_Pln plane(gp_Pnt(0, 0, *z), gp_Dir(0, 0, -1)); // keep below
    setSectionPlanes({plane}, {plane});
}

void Viewport::setSectionPlanes(const std::vector<gp_Pln>& keepRegion, const std::vector<gp_Pln>& sectionPlanes)
{
    m_sectionKeep = keepRegion;
    m_sectionPlanes = sectionPlanes;
    rebuildSections();
}

void Viewport::rebuildSections()
{
    for (const auto& prs : std::as_const(m_sections))
        m_context->Remove(prs, false);
    m_sections.clear();
    m_sectionElements = 0;
    m_sectionPlaneCount = 0;
    if (m_sectionPlanes.empty()) {
        update();
        return;
    }
    // One part per style: elements without a style keep the dark fill and bold black outline.
    const Graphics& g = m_scene->graphics;
    auto occ = [](const QColor& c) { return Quantity_Color(c.redF(), c.greenF(), c.blueF(), Quantity_TOC_sRGB); };
    QSet<QString> cutElements;
    for (const gp_Pln& section : m_sectionPlanes) {
        std::vector<SectionPart> parts;
        QHash<QString, size_t> partOf; // style key -> index in parts
        int loopCount = 0;
        for (const auto& b : m_scene->batches)
            for (int i = 0; i < b->elementCount(); ++i) {
                if (b->isHidden(i))
                    continue;
                auto element = ElementBatch::sectionLoopsPlane(b->chunk(), i, section);
                if (element.empty())
                    continue;
                std::vector<std::vector<gp_Pnt>> clipped;
                for (auto& loop : element) {
                    for (const gp_Pln& clip : m_sectionKeep) {
                        if (samePlane(section, clip))
                            continue;
                        loop = clipLoop(loop, clip);
                        if (loop.empty())
                            break;
                    }
                    if (!loop.empty())
                        clipped.push_back(std::move(loop));
                }
                if (clipped.empty())
                    continue;
                cutElements.insert(b->guid(i));
                const ElementStyle* st = g.styleOf(b->guid(i));
                SectionPart part;
                part.fill = Quantity_Color(0.25, 0.25, 0.27, Quantity_TOC_RGB);
                part.line = Quantity_Color(Quantity_NOC_BLACK);
                if (st) {
                    part.fill = st->fill.isValid() ? std::optional<Quantity_Color>(occ(st->fill)) : std::nullopt;
                    part.line = occ(st->cut.color);
                    part.width = std::max(Graphics::pixels(st->cut.weight, true), 1.0f); // cuts stay bold
                    part.pattern = Graphics::pattern(st->cut.dash);
                }
                const QString key = st ? QStringLiteral("%1|%2|%3|%4|%5").arg(st->fill.isValid() ? st->fill.name() : QString(),
                    st->cut.color.name()).arg(part.width).arg(part.pattern).arg(0) : QStringLiteral("default");
                auto it = partOf.constFind(key);
                if (it == partOf.constEnd()) {
                    it = partOf.insert(key, parts.size());
                    parts.push_back(part);
                }
                for (auto& l : clipped) {
                    parts[*it].loops.push_back(std::move(l));
                    ++loopCount;
                }
            }
        if (loopCount > 0) {
            Handle(SectionPrs) prs = new SectionPrs(std::move(parts), section);
            m_context->Display(prs, 0, -1, false);
            keepHere(prs);
            m_sections.push_back(prs);
            ++m_sectionPlaneCount;
        }
    }
    m_sectionElements = cutElements.size();
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
    // `ink`: the pen's colour and width (D73); nullopt keeps the kind's own colours (markers, rooms).
    AnnotationPrs(Viewport::Annotation a, double z, std::optional<std::pair<Quantity_Color, float>> ink = std::nullopt,
        std::optional<Quantity_Color> background = std::nullopt)
        : m_a(std::move(a))
        , m_z(z)
        , m_ink(std::move(ink))
        , m_background(std::move(background))
    {
        SetZLayer(Graphic3d_ZLayerId_Topmost);
    }
    const QString& guid() const { return m_a.guid; }
    // Null until the annotation is selectable (not on a locked layer).
    const Handle(SelectMgr_EntityOwner)& owner() const { return m_owner; }

    void Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int) override
    {
        const bool marker = isMarker();
        const bool room = m_a.kind == QLatin1String("room");
        const Quantity_Color ink = m_ink ? m_ink->first
            : m_a.kind == QLatin1String("mark") ? Quantity_Color(0.75, 0.15, 0.1, Quantity_TOC_RGB)
            : room ? Quantity_Color(0.1, 0.45, 0.3, Quantity_TOC_RGB)
            : marker ? Quantity_Color(0.1, 0.3, 0.75, Quantity_TOC_RGB)
                     : Quantity_Color(0.1, 0.1, 0.12, Quantity_TOC_RGB);
        if (m_a.isDrafting() && m_a.area.size() >= 3 && (m_a.solid || m_background)) {
            // D84: the fill's area, just under its lines (solid: the pen's colour; else its background pen)
            const std::vector<uint32_t> tris = PolygonTool::triangulate(m_a.area);
            if (!tris.empty()) {
                Handle(Graphic3d_ArrayOfTriangles) fill = new Graphic3d_ArrayOfTriangles(int(tris.size()));
                for (uint32_t i : tris)
                    fill->AddVertex(gp_Pnt(m_a.area[int(i)].x(), m_a.area[int(i)].y(), m_z - 0.004));
                Handle(Graphic3d_AspectFillArea3d) aspect = new Graphic3d_AspectFillArea3d();
                aspect->SetInteriorStyle(Aspect_IS_SOLID);
                aspect->SetInteriorColor(m_a.solid ? ink : *m_background);
                aspect->SetShadingModel(Graphic3d_TypeOfShadingModel_Unlit);
                aspect->SetFaceCulling(Graphic3d_TypeOfBackfacingModel_DoubleSided);
                Handle(Graphic3d_Group) g = prs->NewGroup();
                g->SetGroupPrimitivesAspect(aspect);
                g->AddPrimitiveArray(fill);
            }
        }
        for (const QVector<QPointF>& solid : m_a.solids) { // D87: filled in the pen's colour
            const std::vector<uint32_t> tris = PolygonTool::triangulate(solid);
            if (tris.empty())
                continue;
            Handle(Graphic3d_ArrayOfTriangles) fill = new Graphic3d_ArrayOfTriangles(int(tris.size()));
            for (uint32_t i : tris)
                fill->AddVertex(gp_Pnt(solid[int(i)].x(), solid[int(i)].y(), m_z - 0.001));
            Handle(Graphic3d_AspectFillArea3d) aspect = new Graphic3d_AspectFillArea3d();
            aspect->SetInteriorStyle(Aspect_IS_SOLID);
            aspect->SetInteriorColor(ink);
            aspect->SetShadingModel(Graphic3d_TypeOfShadingModel_Unlit);
            aspect->SetFaceCulling(Graphic3d_TypeOfBackfacingModel_DoubleSided);
            Handle(Graphic3d_Group) g = prs->NewGroup();
            g->SetGroupPrimitivesAspect(aspect);
            g->AddPrimitiveArray(fill);
        }
        if (!m_a.hatch.isEmpty()) { // solid hatch lines, thin, in the pen's colour
            Handle(Graphic3d_ArrayOfSegments) arr = new Graphic3d_ArrayOfSegments(int(m_a.hatch.size()) * 2);
            for (const QLineF& l : m_a.hatch) {
                arr->AddVertex(gp_Pnt(l.x1(), l.y1(), m_z - 0.002));
                arr->AddVertex(gp_Pnt(l.x2(), l.y2(), m_z - 0.002));
            }
            Handle(Graphic3d_Group) g = prs->NewGroup();
            g->SetGroupPrimitivesAspect(new Graphic3d_AspectLine3d(ink, Aspect_TOL_SOLID, 1.0f));
            g->AddPrimitiveArray(arr);
        }
        const std::vector<std::pair<gp_Pnt, gp_Pnt>> segs = segments();
        if (!segs.empty()) {
            Handle(Graphic3d_ArrayOfSegments) arr = new Graphic3d_ArrayOfSegments(int(segs.size()) * 2);
            for (const auto& s : segs) {
                arr->AddVertex(s.first);
                arr->AddVertex(s.second);
            }
            Handle(Graphic3d_Group) lines = prs->NewGroup();
            const float width = m_ink ? std::max(m_ink->second, 1.0f) : (room ? 1.0f : 1.5f);
            Handle(Graphic3d_AspectLine3d) aspect = new Graphic3d_AspectLine3d(ink, room ? Aspect_TOL_DOT : Aspect_TOL_SOLID, width);
            if (!m_a.dash.isEmpty()) // D84: the drafting shape's line type
                aspect->SetLinePattern(Graphics::pattern(m_a.dash));
            lines->SetGroupPrimitivesAspect(aspect);
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
        if (marker || room || m_a.kind == QLatin1String("dimension") || m_a.kind == QLatin1String("mark")) {
            text->SetHorizontalJustification(Graphic3d_HTA_CENTER); // centred on the line / in the circle
            text->SetVerticalJustification(Graphic3d_VTA_CENTER);
        } else if (m_a.kind == QLatin1String("leader")) {
            text->SetVerticalJustification(Graphic3d_VTA_CENTER);
        }
        if (m_a.symbol) { // D87: each label at its place, sized like the annotations' text
            for (const Viewport::Annotation::Label& l : m_a.labels) {
                if (l.text.isEmpty())
                    continue;
                Handle(Prs3d_TextAspect) aspect = new Prs3d_TextAspect();
                aspect->SetColor(ink);
                aspect->SetHeight(std::clamp(l.size * 6.0, 8.0, 72.0));
                aspect->SetHorizontalJustification(l.anchor < 0 ? Graphic3d_HTA_LEFT
                        : l.anchor > 0                            ? Graphic3d_HTA_RIGHT
                                                                  : Graphic3d_HTA_CENTER);
                aspect->SetVerticalJustification(Graphic3d_VTA_CENTER);
                Handle(Graphic3d_Group) group = prs->NewGroup();
                Prs3d_Text::Draw(group, aspect, TCollection_ExtendedString(l.text.toUtf8().constData(), true), at(l.at));
            }
            return;
        }
        if (m_a.isDrafting() && !m_a.labelAt) // lines, arcs, circles, fills without their area: no text
            return;
        if (m_a.isDrafting()) {
            text->SetHorizontalJustification(Graphic3d_HTA_CENTER);
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
        // A room is picked by its stamp only: its outline lies on the wall faces.
        if (m_a.kind != QLatin1String("room"))
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
        if (m_a.symbol && !m_a.labels.isEmpty())
            return at(m_a.labels.first().at);
        if (m_a.isDrafting()) // the area label, or the first point
            return m_a.labelAt ? at(*m_a.labelAt) : (m_a.points.isEmpty() ? gp_Pnt(0, 0, m_z) : at(m_a.points.first()));
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
        if (m_a.isDrafting() || m_a.symbol) {
            for (const auto& curve : m_a.curves)
                for (int i = 0; i + 1 < curve.size(); ++i)
                    out.push_back({at(curve[i]), at(curve[i + 1])});
            return out;
        }
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
        } else if (m_a.kind == QLatin1String("room") && m_a.points.size() >= 4) { // the outline, after the stamp point
            for (int i = 1; i < m_a.points.size(); ++i)
                out.push_back({at(m_a.points[i]), at(m_a.points[i + 1 < m_a.points.size() ? i + 1 : 1])});
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
    std::optional<std::pair<Quantity_Color, float>> m_ink;
    std::optional<Quantity_Color> m_background;
    Handle(SelectMgr_EntityOwner) m_owner;
};

} // namespace

bool Viewport::Annotation::isDrafting() const
{
    return kind == QLatin1String("line") || kind == QLatin1String("polyline") || kind == QLatin1String("arc")
        || kind == QLatin1String("circle") || kind == QLatin1String("fill");
}

QVector<QPointF> Viewport::annotationPoints(const QString& guid) const
{
    for (const Annotation& a : m_annotationData)
        if (a.guid == guid)
            return a.points;
    return {};
}

int Viewport::draftingCount() const
{
    int n = 0;
    for (const Annotation& a : m_annotationData)
        n += a.isDrafting() && m_annotations.contains(a.guid);
    return n;
}

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
        const Graphics& g = m_scene->graphics;
        for (const Annotation& a : *list) {
            if (m_scene->layerHidden.contains(a.guid) || g.isHidden(a.guid))
                continue;
            if ((a.isDrafting() || a.symbol) && !m_planView)
                continue; // D84, D87: 2D drafting and symbols belong to the plan, as in Archicad
            // D73: text, dimensions, marks and leaders take their pen (or the annotations kind's pen).
            std::optional<std::pair<Quantity_Color, float>> ink;
            const bool ownColours = a.kind == QLatin1String("room") || a.kind == QLatin1String("section")
                || a.kind == QLatin1String("elevation");
            if (!ownColours && !g.isEmpty()) {
                const LineStyle pen = g.pen(a.pen > 0 ? a.pen : g.annotationPen());
                ink = std::make_pair(Quantity_Color(pen.color.redF(), pen.color.greenF(), pen.color.blueF(), Quantity_TOC_sRGB),
                    Graphics::pixels(pen.weight, m_scene->trueWeights));
            }
            std::optional<Quantity_Color> background;
            if (a.backgroundPen > 0 && !g.isEmpty()) {
                const QColor c = g.pen(a.backgroundPen).color;
                background = Quantity_Color(c.redF(), c.greenF(), c.blueF(), Quantity_TOC_sRGB);
            } else if (a.backgroundPen > 0) {
                background = Quantity_Color(Quantity_NOC_WHITE);
            }
            Handle(AnnotationPrs) prs = new AnnotationPrs(a, m_annotationZ + 0.02, ink, background);
            m_context->Display(prs, 0, m_scene->layerLocked.contains(a.guid) ? -1 : 0, false);
            keepHere(prs);
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
        keepHere(m_grid);
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
        keepHere(m_preview);
    }
    update();
}

void Viewport::setToolOverlay(const Handle(AIS_InteractiveObject)& overlay)
{
    if (!m_toolOverlay.IsNull())
        m_context->Remove(m_toolOverlay, false);
    m_toolOverlay = overlay;
    if (!m_toolOverlay.IsNull()) {
        m_context->Display(m_toolOverlay, 0, -1, false); // shown, never selectable
        keepHere(m_toolOverlay);
    }
    update();
}

bool Viewport::surfacePointAt(const QPointF& widgetPos, gp_Pnt* out)
{
    if (!ensureWindow())
        return false;
    const NCollection_Vec2<int> px = toPixels(widgetPos);
    const Handle(SelectMgr_ViewerSelector)& selector = m_context->MainSelector();
    selector->Pick(px.x(), px.y(), m_view); // no hover highlight while drawing
    for (int i = 1; i <= selector->NbPicked(); ++i) {
        if (Handle(ElementOwner)::DownCast(selector->Picked(i)).IsNull())
            continue; // the view cube, notes, markers: not a surface to measure
        *out = selector->PickedPoint(i);
        return true;
    }
    return false;
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
    } else if (e->key() == Qt::Key_Tab || e->key() == Qt::Key_Backtab) { // D89: Tab cycling
        cycleNext(m_pointer, e->key() == Qt::Key_Backtab || (e->modifiers() & Qt::ShiftModifier));
        return;
    } else if (e->key() == Qt::Key_Escape && !m_cycleGuid.isEmpty()) {
        m_cycleGuid.clear();
        m_cycleList.clear();
        m_context->ClearDetected(false);
        update();
        return;
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
    if (e->button() == Qt::LeftButton && viewCubeShown()
        && (homeButtonRect().contains(e->position().toPoint()) || viewCubeRect().contains(e->position().toPoint()))) {
        mousePressEvent(e); // a second click on the cube is a click, never an element's double click
        return;
    }
    if (m_drawingMode && e->button() == Qt::LeftButton) {
        emit drawingConfirmed();
        return;
    }
    if (e->button() == Qt::LeftButton && ensureWindow()) {
        const NCollection_Vec2<int> at = toPixels(e->position());
        m_context->MoveTo(at.x(), at.y(), m_view, false);
        QString guid;
        if (Handle(ElementOwner) owner = Handle(ElementOwner)::DownCast(m_context->DetectedOwner()); !owner.IsNull())
            guid = owner->batch()->guid(owner->index());
        else if (Handle(AnnotationOwner) note = Handle(AnnotationOwner)::DownCast(m_context->DetectedOwner()); !note.IsNull())
            guid = note->guid();
        if (!guid.isEmpty()) {
            emit elementDoubleClicked(guid);
            return;
        }
    }
    QWidget::mouseDoubleClickEvent(e);
}

void Viewport::mousePressEvent(QMouseEvent* e)
{
    AbortViewAnimation(); // any click stops a preset turn where it is
    // D76: the view cube and home button take left clicks before tools and selection.
    if (e->button() == Qt::LeftButton && viewCubeShown()) {
        const QPoint at = e->position().toPoint();
        if (homeButtonRect().contains(at) || viewCubeRect().contains(at)) {
            m_cubePress = homeButtonRect().contains(at) ? CubePress::Home : CubePress::Cube;
            m_cubePressPos = e->position();
            m_cubeDragging = false;
            return;
        }
    }
    if (cycleClick(e))
        return; // D89: the element Tab highlighted
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
    if (m_cycleClick && e->button() == Qt::LeftButton) {
        m_cycleClick = false;
        return;
    }
    if (m_cubePress != CubePress::None && e->button() == Qt::LeftButton) {
        const CubePress press = std::exchange(m_cubePress, CubePress::None);
        V3d_TypeOfOrientation orientation = HomeOrientation;
        if (press == CubePress::Home && homeButtonRect().contains(e->position().toPoint()))
            homeView();
        else if (press == CubePress::Cube && !m_cubeDragging && viewCubeOrientationAt(e->position(), &orientation))
            setStandardView(orientation);
        m_cubeDragging = false;
        return;
    }
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
    m_pointer = e->position();
    if (!m_cycleGuid.isEmpty() && (e->position() - m_cyclePos).manhattanLength() > 4) { // D89: left the spot
        m_cycleGuid.clear();
        m_cycleList.clear();
    }
    if (m_cubePress != CubePress::None) {
        if (!(e->buttons() & Qt::LeftButton)) {
            m_cubePress = CubePress::None; // the release went elsewhere
        } else {
            // Dragging the cube orbits the view (Revit); the home button just waits for the release.
            const QPointF d = e->position() - m_cubePressPos;
            if (m_cubePress == CubePress::Cube && (m_cubeDragging || d.manhattanLength() >= 4)) {
                m_cubeDragging = true;
                m_cubePressPos = e->position();
                orbitBy(d.x(), d.y());
            }
            return;
        }
    }
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
    AbortViewAnimation();
    if (touchpadScroll(e)) // D89: two-finger scroll pans
        return;
    m_lastScroll = ScrollAction::Zoom;
    if (m_view->Window().IsNull()) { // headless: no redraw would apply the controller's zoom
        const QPoint d = e->angleDelta().isNull() ? e->pixelDelta() : e->angleDelta() / 8;
        zoomByFactor(std::pow(1.1, (d.y() != 0 ? d.y() : d.x()) / 15.0), e->position());
        return;
    }
    if (UpdateZoom(Aspect_ScrollDelta(toPixels(e->position()), e->angleDelta().y() / 8.0)))
        update();
}

void Viewport::OnSelectionChanged(const Handle(AIS_InteractiveContext)&, const Handle(V3d_View)&)
{
    if (!m_scene->quietSelection)
        emit selectionChanged(selectedGuids());
}

void Viewport::addBatch(const Handle(ElementBatch)& batch)
{
    const int b = int(m_scene->batches.size());
    m_scene->batches.push_back(batch);
    for (int i = 0; i < batch->elementCount(); ++i)
        m_scene->locate.insert(batch->guid(i), Scene::Loc{b, i});
    applyColors(batch);
    applyLayerState(batch);
    applyGraphics(batch);
    batch->setIdBase(m_scene->nextIdBase);
    m_scene->idBases.push_back(m_scene->nextIdBase);
    m_scene->nextIdBase += batch->elementCount();
    const int mode = m_scene->linesOnly ? ElementBatch::LinesOnly : ElementBatch::Shaded;
    batch->SetDisplayMode(mode); // the object's own mode, so later redisplays keep it
    m_context->Display(batch, mode, 0, false);
    m_scene->elementsChanged(); // every view with a plan cut rebuilds its poché, and repaints
}

void Viewport::setLinesOnly(bool on)
{
    m_scene->linesOnly = on;
    const int mode = on ? ElementBatch::LinesOnly : ElementBatch::Shaded;
    for (const auto& b : m_scene->batches)
        m_context->SetDisplayMode(b, mode, false);
    m_scene->changed();
}

void Viewport::clear()
{
    for (const auto& prs : std::as_const(m_annotations))
        m_context->Remove(prs, false);
    m_annotations.clear();
    m_annotationData.clear();
    m_markerData.clear();
    m_context->RemoveAll(false);
    m_scene->batches.clear();
    m_scene->locate.clear();
    m_scene->idBases.clear();
    m_grid.Nullify();
    m_gridLineCount = 0;
    m_underlays.clear(); // RemoveAll above took them
    m_sections.clear(); // RemoveAll above took them
    m_sectionElements = 0;
    m_sectionPlaneCount = 0;
    m_preview.Nullify();
    m_scene->nextIdBase = 0;
    m_scene->changed();
}

void Viewport::fitAll()
{
    if (!ensureWindow())
        return;
    m_view->FitAll(0.05, false);
    m_view->ZFitAll();
    m_fitScale = m_view->Scale();
    update();
}

void Viewport::fitTo(const QStringList& guids)
{
    Bnd_Box box = boundsOf(guids);
    if (box.IsVoid() || !ensureWindow())
        return;
    box.Enlarge(0.5); // a little of what is around (metres)
    m_view->FitAll(box, 0.1, false);
    m_view->ZFitAll();
    update();
}

double Viewport::zoomPercent() const
{
    return m_fitScale > 0 ? 100.0 * m_view->Scale() / m_fitScale : 100.0;
}

QStringList Viewport::guids() const
{
    QStringList out;
    for (const auto& b : m_scene->batches)
        for (int i = 0; i < b->elementCount(); ++i)
            if (!b->isRetired(i))
                out << b->guid(i);
    return out;
}

void Viewport::applyColors(const Handle(ElementBatch)& batch) const
{
    for (int i = 0; i < batch->elementCount(); ++i) {
        const auto it = m_scene->colors.constFind(batch->guid(i));
        batch->setColorOverride(i, it == m_scene->colors.constEnd()
                ? std::nullopt
                : std::optional<Quantity_Color>(Quantity_Color(it->redF(), it->greenF(), it->blueF(), Quantity_TOC_sRGB)));
    }
}

void Viewport::setElementColors(const QHash<QString, QColor>& colors)
{
    m_scene->colors = colors;
    std::vector<int> touched;
    for (size_t b = 0; b < m_scene->batches.size(); ++b) {
        applyColors(m_scene->batches[b]);
        touched.push_back(int(b));
    }
    redisplay(touched);
}

bool Viewport::applyLayerState(const Handle(ElementBatch)& batch) const
{
    bool changed = false;
    for (int i = 0; i < batch->elementCount(); ++i) {
        const bool hidden = m_scene->layerHidden.contains(batch->guid(i));
        const bool locked = m_scene->layerLocked.contains(batch->guid(i));
        if (batch->isLayerHidden(i) == hidden && batch->isLocked(i) == locked)
            continue;
        batch->setLayerHidden(i, hidden);
        batch->setLocked(i, locked);
        changed = true;
    }
    return changed;
}

bool Viewport::applyGraphics(const Handle(ElementBatch)& batch) const
{
    const Graphics& g = m_scene->graphics;
    auto occ = [](const QColor& c) { return Quantity_Color(c.redF(), c.greenF(), c.blueF(), Quantity_TOC_sRGB); };
    auto sameLine = [](const std::optional<BatchLine>& a, const std::optional<BatchLine>& b) {
        return a.has_value() == b.has_value()
            && (!a || (a->color.IsEqual(b->color) && a->width == b->width && a->pattern == b->pattern));
    };
    auto sameColor = [](const std::optional<Quantity_Color>& a, const std::optional<Quantity_Color>& b) {
        return a.has_value() == b.has_value() && (!a || a->IsEqual(*b));
    };
    bool changed = false;
    for (int i = 0; i < batch->elementCount(); ++i) {
        const QString guid = batch->guid(i);
        const bool hidden = g.isHidden(guid);
        std::optional<BatchLine> line;
        std::optional<Quantity_Color> surface;
        double alpha = 0.0;
        if (const ElementStyle* s = g.styleOf(guid)) {
            line = BatchLine{occ(s->projection.color), Graphics::pixels(s->projection.weight, m_scene->trueWeights),
                Graphics::pattern(s->projection.dash)};
            if (s->surface)
                surface = occ(*s->surface);
            alpha = s->transparency.value_or(0.0);
        }
        if (batch->isGraphicsHidden(i) == hidden && sameLine(batch->lineStyle(i), line)
            && sameColor(batch->surface(i), surface) && batch->transparency(i) == alpha)
            continue;
        batch->setGraphicsHidden(i, hidden);
        batch->setLineStyle(i, line);
        batch->setSurface(i, surface, alpha);
        changed = true;
    }
    return changed;
}

void Viewport::setGraphics(const Graphics& graphics, bool trueWeights)
{
    m_scene->graphics = graphics;
    m_scene->trueWeights = trueWeights;
    for (const QString& g : selectedGuids()) // hidden elements can't stay selected
        if (graphics.isHidden(g)) {
            const auto it = m_scene->locate.constFind(g);
            if (it != m_scene->locate.constEnd())
                m_context->AddOrRemoveSelected(m_scene->batches[size_t(it->batch)]->owner(it->index), false);
        }
    std::vector<int> touched; // only batches whose styles changed: an edit mustn't redraw the whole model
    for (size_t b = 0; b < m_scene->batches.size(); ++b)
        if (applyGraphics(m_scene->batches[b]))
            touched.push_back(int(b));
    redisplay(touched); // also rebuilds every view's poché
    if (touched.empty())
        m_scene->elementsChanged(); // the poché's fills and lines may still have changed
    displayAnnotations();
}

bool Viewport::isElementHidden(const QString& guid) const
{
    const auto it = m_scene->locate.constFind(guid);
    return it != m_scene->locate.constEnd() && m_scene->batches[size_t(it->batch)]->isHidden(it->index);
}

void Viewport::setLayerState(const QSet<QString>& hiddenGuids, const QSet<QString>& lockedGuids)
{
    m_scene->layerHidden = hiddenGuids;
    m_scene->layerLocked = lockedGuids;
    // Hidden or locked elements can't stay selected.
    for (const QString& g : selectedGuids())
        if (hiddenGuids.contains(g) || lockedGuids.contains(g)) {
            const auto it = m_scene->locate.constFind(g);
            if (it != m_scene->locate.constEnd())
                m_context->AddOrRemoveSelected(m_scene->batches[size_t(it->batch)]->owner(it->index), false);
        }
    std::vector<int> touched;
    for (size_t b = 0; b < m_scene->batches.size(); ++b)
        if (applyLayerState(m_scene->batches[b])) // only batches whose layer state actually changed
            touched.push_back(int(b));
    redisplay(touched);
    displayAnnotations();
}

bool Viewport::isLocked(const QString& guid) const
{
    const auto it = m_scene->locate.constFind(guid);
    return it != m_scene->locate.constEnd() && m_scene->batches[size_t(it->batch)]->isLocked(it->index);
}

int Viewport::coloredCount() const
{
    int n = 0;
    for (auto it = m_scene->colors.constBegin(); it != m_scene->colors.constEnd(); ++it)
        n += m_scene->locate.contains(it.key()) ? 1 : 0;
    return n;
}

QString Viewport::typeOf(const QString& guid) const
{
    const auto it = m_scene->locate.constFind(guid);
    if (it == m_scene->locate.constEnd())
        return m_annotations.contains(guid) ? QStringLiteral("IfcAnnotation") : QString();
    return m_scene->batches[size_t(it->batch)]->type(it->index);
}

bool Viewport::retire(const QString& guid, std::vector<int>* touched)
{
    auto it = m_scene->locate.find(guid);
    if (it == m_scene->locate.end())
        return false;
    const auto& batch = m_scene->batches[size_t(it->batch)];
    Handle(ElementOwner) owner = batch->owner(it->index);
    const bool wasSelected = owner->IsSelected();
    if (wasSelected)
        m_context->AddOrRemoveSelected(owner, false);
    batch->retire(it->index);
    touched->push_back(it->batch);
    m_scene->locate.erase(it);
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
        const Scene::Loc loc = m_scene->locate.value(g);
        m_context->AddOrRemoveSelected(m_scene->batches[size_t(loc.batch)]->owner(loc.index), false);
    }
    m_scene->changed();
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
    for (const auto& b : m_scene->batches)
        n += b->visibleCount();
    return n;
}

qint64 Viewport::triangleCount() const
{
    qint64 n = 0;
    for (const auto& b : m_scene->batches)
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
        auto it = m_scene->locate.constFind(g);
        if (it == m_scene->locate.constEnd())
            continue;
        if (m_scene->batches[size_t(it->batch)]->isGraphicsHidden(it->index))
            continue; // hidden by the purpose (D73): selecting doesn't reveal it
        if (m_scene->batches[size_t(it->batch)]->isHidden(it->index)) { // selecting a hidden element reveals it
            m_scene->batches[size_t(it->batch)]->setHidden(it->index, false);
            unhide.push_back(it->batch);
        }
    }
    redisplay(unhide);
    for (const QString& g : guids) {
        auto it = m_scene->locate.constFind(g);
        if (it != m_scene->locate.constEnd()) {
            if (!m_scene->batches[size_t(it->batch)]->isGraphicsHidden(it->index))
                m_context->AddOrRemoveSelected(m_scene->batches[size_t(it->batch)]->owner(it->index), false);
        } else if (const auto note = m_annotations.constFind(g); note != m_annotations.constEnd()) {
            const Handle(SelectMgr_EntityOwner)& owner = Handle(AnnotationPrs)::DownCast(*note)->owner();
            if (!owner.IsNull())
                m_context->AddOrRemoveSelected(owner, false);
        }
    }
    m_context->UpdateCurrentViewer();
    m_scene->changed();
}

void Viewport::redisplay(const std::vector<int>& batches)
{
    std::set<int> unique(batches.begin(), batches.end());
    for (int b : unique) {
        m_context->Redisplay(m_scene->batches[size_t(b)], false, true);
        m_context->RecomputeSelectionOnly(m_scene->batches[size_t(b)]);
    }
    if (!unique.empty())
        m_scene->elementsChanged(); // every view with a plan cut rebuilds its poché, and repaints
}

void Viewport::setHidden(const QStringList& guids, bool hidden)
{
    std::vector<int> touched;
    for (const QString& g : guids) {
        auto it = m_scene->locate.constFind(g);
        if (it == m_scene->locate.constEnd())
            continue;
        const auto& batch = m_scene->batches[size_t(it->batch)];
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
    for (size_t b = 0; b < m_scene->batches.size(); ++b) {
        const auto& batch = m_scene->batches[b];
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
    for (size_t b = 0; b < m_scene->batches.size(); ++b) {
        const auto& batch = m_scene->batches[b];
        if (batch->visibleCount() == batch->elementCount())
            continue;
        for (int i = 0; i < batch->elementCount(); ++i)
            batch->setHidden(i, false);
        touched.push_back(int(b));
    }
    redisplay(touched);
}

// Cuts belong to this view (D71): a plan tab's cut doesn't cut the 3D tab.
void Viewport::addClipPlanes(const std::vector<Handle(Graphic3d_ClipPlane)>& planes)
{
    for (const auto& plane : planes) {
        m_clipPlanes.push_back(plane);
        m_view->AddClipPlane(plane);
    }
    update();
}

void Viewport::clearClipPlanes()
{
    for (const auto& plane : m_clipPlanes)
        m_view->RemoveClipPlane(plane);
    m_clipPlanes.clear();
    update();
}

int Viewport::viewClipPlaneCount() const
{
    return m_view->ClipPlanes().IsNull() ? 0 : m_view->ClipPlanes()->Size();
}

// Overlays (grid, annotations, markers, poché, previews) belong to this view only.
void Viewport::keepHere(const Handle(AIS_InteractiveObject)& obj)
{
    if (obj.IsNull())
        return;
    for (auto it = m_scene->viewer()->DefinedViewIterator(); it.More(); it.Next())
        m_context->SetViewAffinity(obj, it.Value(), it.Value() == m_view);
}

void Viewport::keepOverlaysHere()
{
    keepHere(m_preview);
    keepHere(m_grid);
    for (const auto& s : std::as_const(m_sections))
        keepHere(s);
    keepHere(m_cube);
    keepHere(m_home);
    for (const auto& a : std::as_const(m_annotations))
        keepHere(a);
    for (const auto& u : std::as_const(m_underlays))
        keepHere(u.prs);
}

bool Viewport::showsOverlay(const Handle(AIS_InteractiveObject)& obj, const Handle(V3d_View)& view) const
{
    return !obj.IsNull() && !view.IsNull() && obj->ViewAffinity()->IsVisible(view->View()->Identification());
}

Bnd_Box Viewport::boundsOf(const QStringList& guids) const
{
    Bnd_Box box;
    if (guids.isEmpty()) {
        for (const auto& b : m_scene->batches)
            box.Add(b->visibleBounds());
        return box;
    }
    for (const QString& g : guids) {
        auto it = m_scene->locate.constFind(g);
        if (it != m_scene->locate.constEnd())
            box.Add(m_scene->batches[size_t(it->batch)]->elementBounds(it->index));
    }
    return box;
}

Bnd_Box Viewport::buildingBounds(const QStringList& guids) const
{
    // The elements' mesh boxes (exact: roofs and gables included, unlike the placements), less the
    // few far-flung ones a georeferenced model carries (site furniture, survey markers, an element
    // left at the project origin): keep the elements whose centre lies near the core of the others.
    std::vector<Bnd_Box> boxes;
    boxes.reserve(size_t(guids.size()));
    for (const QString& g : guids) {
        auto it = m_scene->locate.constFind(g);
        if (it == m_scene->locate.constEnd())
            continue;
        const Bnd_Box b = m_scene->batches[size_t(it->batch)]->elementBounds(it->index);
        if (!b.IsVoid())
            boxes.push_back(b);
    }
    Bnd_Box box;
    if (boxes.empty())
        return box;
    std::vector<double> cx, cy;
    cx.reserve(boxes.size());
    cy.reserve(boxes.size());
    for (const auto& b : boxes) {
        double x0, y0, z0, x1, y1, z1;
        b.Get(x0, y0, z0, x1, y1, z1);
        cx.push_back((x0 + x1) / 2);
        cy.push_back((y0 + y1) / 2);
    }
    auto quantile = [](std::vector<double> v, double q) {
        const size_t k = std::min(v.size() - 1, size_t(q * double(v.size() - 1) + 0.5));
        std::nth_element(v.begin(), v.begin() + std::ptrdiff_t(k), v.end());
        return v[k];
    };
    const double qx0 = quantile(cx, 0.05), qx1 = quantile(cx, 0.95);
    const double qy0 = quantile(cy, 0.05), qy1 = quantile(cy, 0.95);
    const double margin = std::max(15.0, 0.5 * std::max(qx1 - qx0, qy1 - qy0));
    for (size_t i = 0; i < boxes.size(); ++i)
        if (cx[i] >= qx0 - margin && cx[i] <= qx1 + margin && cy[i] >= qy0 - margin && cy[i] <= qy1 + margin)
            box.Add(boxes[i]);
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
    // The first element under the point; the view cube in front of it doesn't count (D76).
    for (m_context->InitDetected(); m_context->MoreDetected(); m_context->NextDetected()) {
        const Handle(SelectMgr_EntityOwner) detected = m_context->DetectedCurrentOwner();
        if (!Handle(AIS_ViewCubeOwner)::DownCast(detected).IsNull())
            continue;
        Handle(ElementOwner) owner = Handle(ElementOwner)::DownCast(detected);
        return owner.IsNull() ? QString() : owner->batch()->guid(owner->index());
    }
    return {};
}

bool Viewport::projectCenterOf(const QString& guid, int* x, int* y) const
{
    auto it = m_scene->locate.constFind(guid);
    if (it == m_scene->locate.constEnd() || m_view->Window().IsNull())
        return false;
    const Bnd_Box box = m_scene->batches[size_t(it->batch)]->elementBounds(it->index);
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

// D76: view cube, preset views and perspective.

void Viewport::ensureViewCube()
{
    if (m_planView || m_view->Window().IsNull())
        return;
    const double dpr = devicePixelRatioF();
    if (m_cube.IsNull() || std::abs(dpr - m_cubeDpr) > 1e-3) { // first paint, or moved to another screen
        for (const Handle(AIS_InteractiveObject)& o : {Handle(AIS_InteractiveObject)(m_cube), m_home})
            if (!o.IsNull())
                m_context->Remove(o, false);
        Handle(ViewCube) cube = new ViewCube(dpr);
        QPointer<Viewport> self(this);
        // A click OCCT hands to the cube (inside its own selection pass): turn after it.
        cube->onClick = [self](V3d_TypeOfOrientation o) {
            QMetaObject::invokeMethod(self, [self, o] { if (self) self->setStandardView(o); }, Qt::QueuedConnection);
        };
        m_cube = cube;
        m_home = makeHomeButton(dpr);
        m_cubeDpr = dpr;
    }
    if (!m_context->IsDisplayed(m_cube)) { // also after clear(), which empties the shared context
        m_context->Display(m_cube, 0, 0, false);
        keepHere(m_cube);
    }
    if (!m_context->IsDisplayed(m_home)) {
        m_context->Display(m_home, 0, -1, false);
        keepHere(m_home);
    }
}

void Viewport::eraseViewCube()
{
    for (const Handle(AIS_InteractiveObject)& o : {Handle(AIS_InteractiveObject)(m_cube), m_home})
        if (!o.IsNull() && m_context->IsDisplayed(o))
            m_context->Erase(o, false);
}

QRect Viewport::viewCubeRect() const
{
    return viewCubeShown() ? kimbim::viewCubeRect(size()) : QRect();
}

QRect Viewport::homeButtonRect() const
{
    return viewCubeShown() ? kimbim::homeButtonRect(size()) : QRect();
}

bool Viewport::viewCubeOrientationAt(const QPointF& pos, V3d_TypeOfOrientation* orientation)
{
    if (!viewCubeShown() || !ensureWindow() || m_cube.IsNull() || !m_context->IsDisplayed(m_cube))
        return false;
    const NCollection_Vec2<int> px = toPixels(pos);
    m_context->MoveTo(px.x(), px.y(), m_view, false);
    for (m_context->InitDetected(); m_context->MoreDetected(); m_context->NextDetected()) {
        Handle(AIS_ViewCubeOwner) owner = Handle(AIS_ViewCubeOwner)::DownCast(m_context->DetectedCurrentOwner());
        if (!owner.IsNull() && owner->Selectable() == m_cube) {
            *orientation = owner->MainOrientation();
            return true;
        }
    }
    return false;
}

void Viewport::handleViewRedraw(const Handle(AIS_InteractiveContext)& ctx, const Handle(V3d_View)& view)
{
    AIS_ViewController::handleViewRedraw(ctx, view);
    if (isAnimating() && m_animation->ElapsedTime() >= m_animation->OwnDuration()) {
        // The controller keeps replaying a finished animation: end it on its last camera.
        m_animation->Stop();
        if (!m_animation->CameraEnd().IsNull())
            m_view->Camera()->Copy(m_animation->CameraEnd());
        m_view->Invalidate();
        setAskNextFrame();
    }
    if (toAskNextFrame()) // a preset turn is playing: draw its next frame
        QMetaObject::invokeMethod(this, qOverload<>(&QWidget::update), Qt::QueuedConnection);
}

bool Viewport::isAnimating() const
{
    return !m_animation.IsNull() && !m_animation->IsStopped();
}

void Viewport::applyProjection()
{
    const Handle(Graphic3d_Camera)& camera = m_view->Camera();
    const auto type = m_perspective && !m_planView ? Graphic3d_Camera::Projection_Perspective : Graphic3d_Camera::Projection_Orthographic;
    if (camera->ProjectionType() == type)
        return;
    // Keep what is seen at the target: an orthographic scale becomes a perspective distance and back.
    const double scale = camera->Scale();
    camera->SetProjectionType(type);
    if (type == Graphic3d_Camera::Projection_Perspective)
        camera->SetFOVy(45.0); // a normal lens (about 70 degrees across a wide window)
    camera->SetScale(scale);
    m_view->Invalidate();
}

void Viewport::setPerspective(bool on)
{
    AbortViewAnimation();
    m_perspective = on;
    applyProjection();
    update();
}

void Viewport::setStandardView(V3d_TypeOfOrientation orientation, bool animate)
{
    if (!m_planView)
        goTo(orientation, animate, false);
}

void Viewport::homeView(bool animate)
{
    if (!m_planView)
        goTo(HomeOrientation, animate, true);
}

namespace {

// Whether any part of the box is inside the camera's view (for perspective, a box reaching behind
// the eye counts as seen).
bool boxInView(const Handle(Graphic3d_Camera)& camera, const Bnd_Box& box)
{
    double x0, y0, z0, x1, y1, z1;
    box.Get(x0, y0, z0, x1, y1, z1);
    double minX = 1e300, minY = 1e300, maxX = -1e300, maxY = -1e300;
    const gp_Vec forward(camera->Direction());
    for (int i = 0; i < 8; ++i) {
        const gp_Pnt p(i & 1 ? x1 : x0, i & 2 ? y1 : y0, i & 4 ? z1 : z0);
        if (!camera->IsOrthographic() && gp_Vec(camera->Eye(), p).Dot(forward) <= 0)
            return true;
        const gp_Pnt n = camera->Project(p);
        minX = std::min(minX, n.X());
        maxX = std::max(maxX, n.X());
        minY = std::min(minY, n.Y());
        maxY = std::max(maxY, n.Y());
    }
    return maxX >= -1 && minX <= 1 && maxY >= -1 && minY <= 1;
}

} // namespace

void Viewport::goTo(V3d_TypeOfOrientation orientation, bool animate, bool fit)
{
    AbortViewAnimation();
    const Handle(Graphic3d_Camera)& camera = m_view->Camera();
    // Same target, distance and zoom, seen from the preset's side.
    Handle(Graphic3d_Camera) end = new Graphic3d_Camera();
    end->Copy(camera);
    const gp_Pnt center = end->Center();
    end->SetEyeAndCenter(center.Translated(gp_Vec(viewDirection(orientation)) * end->Distance()), center);
    end->SetUp(viewUp(orientation));
    end->OrthogonalizeUp();
    const Bnd_Box box = boundsOf({});
    if (!box.IsVoid() && (fit || !boxInView(end, box))) {
        // Fit all on the end camera, with Fit all's margin.
        Handle(Graphic3d_Camera) saved = new Graphic3d_Camera();
        saved->Copy(camera);
        camera->Copy(end);
        m_view->FitAll(box, 0.05, false);
        end->Copy(camera);
        camera->Copy(saved);
        m_fitScale = end->Scale();
    }
    animateTo(end, animate);
}

void Viewport::animateTo(const Handle(Graphic3d_Camera)& end, bool animate)
{
    if (!animate || m_animationSeconds <= 0 || m_view->Window().IsNull() || !isVisible()) {
        m_view->Camera()->Copy(end);
        m_view->Invalidate();
        update();
        return;
    }
    Handle(Graphic3d_Camera) start = new Graphic3d_Camera();
    start->Copy(m_view->Camera());
    m_animation->SetView(m_view);
    m_animation->SetCameraStart(start);
    m_animation->SetCameraEnd(end);
    m_animation->SetOwnDuration(m_animationSeconds);
    m_animation->StartTimer(0.0, 1.0, true, false);
    update();
}

void Viewport::orbitBy(double dx, double dy)
{
    AbortViewAnimation();
    const Handle(Graphic3d_Camera)& camera = m_view->Camera();
    const gp_Pnt center = camera->Center();
    const double perPixel = 0.6 * M_PI / 180.0;
    // Like turning the cube by hand: right turns the model to the right, down tips its top towards you.
    gp_Trsf yaw;
    yaw.SetRotation(gp_Ax1(center, gp::DZ()), -dx * perPixel);
    camera->Transform(yaw);
    const gp_Dir side = camera->Direction().Crossed(camera->Up());
    gp_Trsf pitch;
    pitch.SetRotation(gp_Ax1(center, side), -dy * perPixel);
    Handle(Graphic3d_Camera) next = new Graphic3d_Camera();
    next->Copy(camera);
    next->Transform(pitch);
    if (std::abs(next->Direction().Z()) < 0.995) // never past straight down or up
        camera->Copy(next);
    m_view->Invalidate();
    update();
}

} // namespace kimbim
