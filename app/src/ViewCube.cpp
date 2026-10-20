// SPDX-License-Identifier: GPL-3.0-or-later
#include "ViewCube.h"

#include <Graphic3d_ArrayOfSegments.hxx>
#include <Graphic3d_ArrayOfTriangles.hxx>
#include <Graphic3d_AspectFillArea3d.hxx>
#include <Graphic3d_AspectLine3d.hxx>
#include <Graphic3d_TransformPers.hxx>
#include <Prs3d_Presentation.hxx>
#include <V3d.hxx>

#include <QCoreApplication>

#include <cmath>

namespace kimbim {

namespace {

// Layout in logical pixels from the view's top-right corner (D76).
constexpr int CubeSize = 56;          // side of the box
constexpr int CubeCenter = 76;        // the cube's centre, right and down from the corner
constexpr int CubeHalfExtent = 56;    // half the square the turning cube (and its edges) stays in
constexpr int HomeCenterX = 142;      // the home button's centre
constexpr int HomeCenterY = 24;
constexpr int HomeHalf = 13;

const char* const Context = "ViewCube";

QString translated(const char* text)
{
    return QCoreApplication::translate(Context, text);
}

TCollection_AsciiString ascii(const QString& s)
{
    return TCollection_AsciiString(s.toUtf8().constData());
}

class HomeButton : public AIS_InteractiveObject {
public:
    explicit HomeButton(double dpr)
        : m_dpr(dpr)
    {
        SetTransformPersistence(new Graphic3d_TransformPers(Graphic3d_TMF_2d, Aspect_TOTP_RIGHT_UPPER,
            NCollection_Vec2<int>(int(std::lround(HomeCenterX * dpr)), int(std::lround(HomeCenterY * dpr)))));
        SetZLayer(Graphic3d_ZLayerId_TopOSD);
        SetInfiniteState(true); // never part of Fit all
    }
    void Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int) override
    {
        const double s = m_dpr;
        auto p = [s](double x, double y) { return gp_Pnt(x * s, y * s, 0); };
        // Background: a light rounded square (an octagon), so the icon reads as a button.
        const double r = HomeHalf, c = 4;
        const gp_Pnt ring[8] = {p(-r + c, -r), p(r - c, -r), p(r, -r + c), p(r, r - c), p(r - c, r), p(-r + c, r), p(-r, r - c), p(-r, -r + c)};
        Handle(Graphic3d_ArrayOfTriangles) bg = new Graphic3d_ArrayOfTriangles(8 * 3);
        for (int i = 0; i < 8; ++i) {
            bg->AddVertex(p(0, 0));
            bg->AddVertex(ring[i]);
            bg->AddVertex(ring[(i + 1) % 8]);
        }
        Handle(Graphic3d_AspectFillArea3d) fill = new Graphic3d_AspectFillArea3d();
        fill->SetInteriorStyle(Aspect_IS_SOLID);
        fill->SetInteriorColor(Quantity_Color(0.98, 0.98, 0.99, Quantity_TOC_RGB));
        fill->SetShadingModel(Graphic3d_TypeOfShadingModel_Unlit);
        fill->SetFaceCulling(Graphic3d_TypeOfBackfacingModel_DoubleSided);
        Handle(Graphic3d_Group) g = prs->NewGroup();
        g->SetGroupPrimitivesAspect(fill);
        g->AddPrimitiveArray(bg);
        // The house: walls and a roof, as lines.
        const gp_Pnt house[] = {p(-6, -7), p(6, -7), p(6, -7), p(6, 1), p(-6, -7), p(-6, 1), p(-9, 0), p(0, 8),
            p(0, 8), p(9, 0), p(-2, -7), p(-2, -2), p(-2, -2), p(2, -2), p(2, -2), p(2, -7)};
        Handle(Graphic3d_ArrayOfSegments) lines = new Graphic3d_ArrayOfSegments(int(std::size(house)) + 16);
        for (const gp_Pnt& v : house)
            lines->AddVertex(v);
        for (int i = 0; i < 8; ++i) {
            lines->AddVertex(ring[i]);
            lines->AddVertex(ring[(i + 1) % 8]);
        }
        Handle(Graphic3d_Group) l = prs->NewGroup();
        l->SetGroupPrimitivesAspect(new Graphic3d_AspectLine3d(Quantity_Color(0.25, 0.28, 0.33, Quantity_TOC_RGB), Aspect_TOL_SOLID, float(1.5 * s)));
        l->AddPrimitiveArray(lines);
    }
    void ComputeSelection(const Handle(SelectMgr_Selection)&, const int) override {} // the Viewport hit-tests it

private:
    double m_dpr;
};

} // namespace

const QVector<StandardView>& standardViews()
{
    // Alt+digit: free in the app (tools use single letters, P and 3 switch plan/3D) and typed the
    // same on every keyboard layout (Ctrl+Alt is AltGr on Spanish keyboards).
    static const QVector<StandardView> views = {
        {V3d_Zpos, "Top", QT_TRANSLATE_NOOP("ViewCube", "Top"), QKeySequence(Qt::ALT | Qt::Key_1)},
        {V3d_Zneg, "Bottom", QT_TRANSLATE_NOOP("ViewCube", "Bottom"), QKeySequence(Qt::ALT | Qt::Key_2)},
        {V3d_Yneg, "Front", QT_TRANSLATE_NOOP("ViewCube", "Front"), QKeySequence(Qt::ALT | Qt::Key_3)},
        {V3d_Ypos, "Back", QT_TRANSLATE_NOOP("ViewCube", "Back"), QKeySequence(Qt::ALT | Qt::Key_4)},
        {V3d_Xneg, "Left", QT_TRANSLATE_NOOP("ViewCube", "Left"), QKeySequence(Qt::ALT | Qt::Key_5)},
        {V3d_Xpos, "Right", QT_TRANSLATE_NOOP("ViewCube", "Right"), QKeySequence(Qt::ALT | Qt::Key_6)},
        {V3d_XnegYnegZpos, "SW", QT_TRANSLATE_NOOP("ViewCube", "South-west isometric"), QKeySequence(Qt::ALT | Qt::Key_7)},
        {V3d_XposYnegZpos, "SE", QT_TRANSLATE_NOOP("ViewCube", "South-east isometric"), QKeySequence(Qt::ALT | Qt::Key_8)},
        {V3d_XposYposZpos, "NE", QT_TRANSLATE_NOOP("ViewCube", "North-east isometric"), QKeySequence(Qt::ALT | Qt::Key_9)},
        {V3d_XnegYposZpos, "NW", QT_TRANSLATE_NOOP("ViewCube", "North-west isometric"), QKeySequence(Qt::ALT | Qt::Key_0)},
    };
    return views;
}

QString standardViewLabel(V3d_TypeOfOrientation orientation)
{
    for (const StandardView& v : standardViews())
        if (v.orientation == orientation)
            return translated(v.label);
    return {};
}

gp_Dir viewDirection(V3d_TypeOfOrientation orientation)
{
    return V3d::GetProjAxis(orientation);
}

gp_Dir viewUp(V3d_TypeOfOrientation orientation)
{
    const gp_Dir d = viewDirection(orientation);
    return std::abs(d.Z()) > 0.999 ? gp::DY() : gp::DZ();
}

ViewCube::ViewCube(double dpr)
{
    SetSize(CubeSize * dpr);
    SetBoxColor(Quantity_Color(0.90, 0.91, 0.93, Quantity_TOC_RGB));
    SetTextColor(Quantity_Color(0.20, 0.22, 0.26, Quantity_TOC_RGB));
    SetInnerColor(Quantity_Color(0.75, 0.77, 0.80, Quantity_TOC_RGB));
    SetFontHeight(11 * dpr);
    SetDrawAxes(false);
    SetBoxSideLabel(V3d_Zpos, ascii(translated("Top")));
    SetBoxSideLabel(V3d_Zneg, ascii(translated("Bottom")));
    SetBoxSideLabel(V3d_Yneg, ascii(translated("Front")));
    SetBoxSideLabel(V3d_Ypos, ascii(translated("Back")));
    SetBoxSideLabel(V3d_Xneg, ascii(translated("Left")));
    SetBoxSideLabel(V3d_Xpos, ascii(translated("Right")));
    SetTransformPersistence(new Graphic3d_TransformPers(Graphic3d_TMF_TriedronPers, Aspect_TOTP_RIGHT_UPPER,
        NCollection_Vec2<int>(int(std::lround(CubeCenter * dpr)), int(std::lround(CubeCenter * dpr)))));
    SetZLayer(Graphic3d_ZLayerId_Topmost);
    SetAutoStartAnimation(false); // HandleClick below decides
    SetInfiniteState(true);       // never part of Fit all
}

void ViewCube::HandleClick(const Handle(AIS_ViewCubeOwner)& owner)
{
    if (onClick && !owner.IsNull())
        onClick(owner->MainOrientation());
}

Handle(AIS_InteractiveObject) makeHomeButton(double devicePixelRatio)
{
    return new HomeButton(devicePixelRatio);
}

QRect viewCubeRect(const QSize& widget)
{
    return QRect(widget.width() - CubeCenter - CubeHalfExtent, CubeCenter - CubeHalfExtent, 2 * CubeHalfExtent, 2 * CubeHalfExtent);
}

QRect homeButtonRect(const QSize& widget)
{
    return QRect(widget.width() - HomeCenterX - HomeHalf, HomeCenterY - HomeHalf, 2 * HomeHalf, 2 * HomeHalf);
}

} // namespace kimbim
