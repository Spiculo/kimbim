// SPDX-License-Identifier: GPL-3.0-or-later
// D85: underlays in a view. DXF linework is one Graphic3d_ArrayOfSegments per underlay (vertex colours,
// one draw call however many lines); a PDF page or image is one textured quad. The placement is the
// object's local transformation, so moving or turning an underlay re-uses what is on the graphics card.
#include "Viewport.h"

#include <Graphic3d_ArrayOfSegments.hxx>
#include <Graphic3d_ArrayOfTriangles.hxx>
#include <Graphic3d_AspectFillArea3d.hxx>
#include <Graphic3d_AspectLine3d.hxx>
#include <Graphic3d_Texture2D.hxx>
#include <Graphic3d_TextureParams.hxx>
#include <Graphic3d_TextureSet.hxx>
#include <Image_PixMap.hxx>
#include <Prs3d_Presentation.hxx>
#include <gp_Ax1.hxx>
#include <gp_Trsf.hxx>

#include <cstring>

namespace kimcad {

namespace {

constexpr double kLift = 0.005; // metres above the level: over its floor's top face, under everything else
constexpr double kPi = 3.14159265358979323846;

// The view's background (Viewport's constructor): faded linework blends towards it.
const QColor kBackground = QColor::fromRgbF(0.93f, 0.94f, 0.95f);

gp_Trsf placementTrsf(const UnderlayPlacement& p, double z)
{
    gp_Trsf scale, turn, move;
    scale.SetScaleFactor(p.scale > 0 ? p.scale : 1.0);
    turn.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), p.rotation * kPi / 180.0);
    move.SetTranslation(gp_Vec(p.at.x(), p.at.y(), z + kLift));
    return move * turn * scale;
}

class UnderlayLinesPrs : public AIS_InteractiveObject {
public:
    UnderlayLinesPrs(std::shared_ptr<const UnderlayLines> lines, const Underlay& u)
        : m_lines(std::move(lines))
        , m_u(u)
    {
    }
    void Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int) override
    {
        const int n = m_lines ? m_lines->count() : 0;
        if (n == 0)
            return;
        // Vertices relative to the placement's base point, in drawing units (small numbers, float-safe);
        // the transformation scales, turns and moves them.
        const double ox = m_lines->origin.x() - m_u.placement.base.x(), oy = m_lines->origin.y() - m_u.placement.base.y();
        const QColor tint = m_u.tint.isEmpty() ? QColor() : QColor(m_u.tint);
        Handle(Graphic3d_ArrayOfSegments) arr = new Graphic3d_ArrayOfSegments(n * 2, 0, Graphic3d_ArrayFlags_VertexColor);
        const float* c = m_lines->coords.data();
        const unsigned char* rgb = m_lines->colours.data();
        QRgb lastSource = 0xffffffff;
        Quantity_Color last;
        for (int i = 0; i < n; ++i, c += 4, rgb += 3) {
            const QRgb source = qRgb(rgb[0], rgb[1], rgb[2]);
            if (source != lastSource) { // runs of one colour are the rule
                const QColor shown = underlayColour(QColor(source), m_u.greyscale, tint, m_u.opacity, kBackground);
                last = Quantity_Color(shown.redF(), shown.greenF(), shown.blueF(), Quantity_TOC_sRGB);
                lastSource = source;
            }
            arr->AddVertex(gp_Pnt(ox + c[0], oy + c[1], 0.0), last);
            arr->AddVertex(gp_Pnt(ox + c[2], oy + c[3], 0.0), last);
        }
        Handle(Graphic3d_Group) group = prs->NewGroup();
        group->SetGroupPrimitivesAspect(new Graphic3d_AspectLine3d(Quantity_NOC_BLACK, Aspect_TOL_SOLID, 1.0));
        group->AddPrimitiveArray(arr);
    }
    void ComputeSelection(const Handle(SelectMgr_Selection)&, const int) override {}

private:
    std::shared_ptr<const UnderlayLines> m_lines;
    Underlay m_u;
};

class UnderlayImagePrs : public AIS_InteractiveObject {
public:
    UnderlayImagePrs(const QImage& image, const Underlay& u)
        : m_image(image)
        , m_u(u)
    {
    }
    void Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int) override
    {
        if (m_image.isNull() || m_u.size.isEmpty())
            return;
        // Faded towards the background on the CPU, as the linework is: an opaque texture needs no
        // transparency sorting, and the model is drawn over it anyway.
        QImage img = m_image.convertToFormat(QImage::Format_RGBA8888);
        const double a = std::clamp(m_u.opacity, 0.05, 1.0);
        if (a < 0.999) {
            const int br = kBackground.red(), bg = kBackground.green(), bb = kBackground.blue();
            for (int y = 0; y < img.height(); ++y) {
                uchar* p = img.scanLine(y);
                for (int x = 0; x < img.width(); ++x, p += 4) {
                    p[0] = uchar(p[0] * a + br * (1 - a));
                    p[1] = uchar(p[1] * a + bg * (1 - a));
                    p[2] = uchar(p[2] * a + bb * (1 - a));
                    p[3] = 255;
                }
            }
        }
        Handle(Image_PixMap) pix = new Image_PixMap();
        if (!pix->InitTrash(Image_Format_RGBA, size_t(img.width()), size_t(img.height())))
            return;
        pix->SetTopDown(false); // rows bottom-up, as OpenGL takes them
        for (int y = 0; y < img.height(); ++y)
            std::memcpy(pix->ChangeData() + pix->SizeRowBytes() * size_t(img.height() - 1 - y), img.constScanLine(y), size_t(img.width()) * 4);
        Handle(Graphic3d_Texture2D) texture = new Graphic3d_Texture2D(pix);
        texture->DisableRepeat();
        texture->GetParams()->SetFilter(Graphic3d_TOTF_TRILINEAR);
        texture->SetMipmapsGeneration(true); // a page shown smaller than its pixels stays legible
        Handle(Graphic3d_AspectFillArea3d) aspect = new Graphic3d_AspectFillArea3d();
        aspect->SetInteriorStyle(Aspect_IS_SOLID);
        aspect->SetShadingModel(Graphic3d_TypeOfShadingModel_Unlit);
        aspect->SetDistinguishOff();
        aspect->SetInteriorColor(Quantity_NOC_WHITE); // unlit: white times the texture
        aspect->SetTextureSet(new Graphic3d_TextureSet(Handle(Graphic3d_TextureMap)(texture)));
        aspect->SetTextureMapOn();
        aspect->SetEdgeOff();
        // The page in drawing units around the base point, y up (page/image rows run down).
        const double w = m_u.size.width(), h = m_u.size.height(), bx = m_u.placement.base.x(), by = m_u.placement.base.y();
        const gp_Pnt corners[4] = {gp_Pnt(-bx, by - h, 0), gp_Pnt(w - bx, by - h, 0), gp_Pnt(w - bx, by, 0), gp_Pnt(-bx, by, 0)};
        const gp_Pnt2d uv[4] = {gp_Pnt2d(0, 0), gp_Pnt2d(1, 0), gp_Pnt2d(1, 1), gp_Pnt2d(0, 1)};
        Handle(Graphic3d_ArrayOfTriangles) tris = new Graphic3d_ArrayOfTriangles(4, 6, Graphic3d_ArrayFlags_VertexTexel);
        for (int i = 0; i < 4; ++i)
            tris->AddVertex(corners[i], uv[i]);
        tris->AddEdges(1, 2, 3);
        tris->AddEdges(1, 3, 4);
        Handle(Graphic3d_Group) group = prs->NewGroup();
        group->SetGroupPrimitivesAspect(aspect);
        group->AddPrimitiveArray(tris);
    }
    void ComputeSelection(const Handle(SelectMgr_Selection)&, const int) override {}

private:
    QImage m_image;
    Underlay m_u;
};

} // namespace

void Viewport::setUnderlays(const QVector<UnderlayView>& underlays)
{
    QSet<QString> keep;
    for (const UnderlayView& v : underlays) {
        const Underlay& u = v.underlay;
        if (u.isRaster() ? v.image.isNull() : !v.lines)
            continue;
        keep.insert(u.id);
        const QString key = u.displayKey() + QLatin1Char('|')
            + QString::number(u.isRaster() ? v.image.cacheKey() : qint64(quintptr(v.lines.get())))
            + QLatin1Char('|') + QString::number(u.size.width()) + QLatin1Char('x') + QString::number(u.size.height());
        UnderlayShown& shown = m_underlays[u.id];
        if (shown.prs.IsNull() || shown.key != key) {
            if (!shown.prs.IsNull())
                m_context->Remove(shown.prs, false);
            if (u.isRaster())
                shown.prs = new UnderlayImagePrs(v.image, u);
            else
                shown.prs = new UnderlayLinesPrs(v.lines, u);
            shown.key = key;
            shown.segments = u.isRaster() ? 0 : v.lines->count();
            shown.prs->SetLocalTransformation(placementTrsf(u.placement, v.z));
            m_context->Display(shown.prs, 0, -1, false);
            keepHere(shown.prs);
        } else {
            m_context->SetLocation(shown.prs, TopLoc_Location(placementTrsf(u.placement, v.z)));
        }
    }
    for (auto it = m_underlays.begin(); it != m_underlays.end();) {
        if (!keep.contains(it.key())) {
            if (!it->prs.IsNull())
                m_context->Remove(it->prs, false);
            it = m_underlays.erase(it);
        } else {
            ++it;
        }
    }
    update();
}

qint64 Viewport::underlaySegmentCount() const
{
    qint64 n = 0;
    for (const auto& u : m_underlays)
        n += u.segments;
    return n;
}

void Viewport::removeUnderlays()
{
    for (const auto& u : std::as_const(m_underlays))
        if (!u.prs.IsNull())
            m_context->Remove(u.prs, false);
    m_underlays.clear();
}

} // namespace kimcad
