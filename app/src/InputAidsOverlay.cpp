// SPDX-License-Identifier: GPL-3.0-or-later
#include "InputAidsOverlay.h"

#include <Graphic3d_ArrayOfSegments.hxx>
#include <Graphic3d_AspectLine3d.hxx>
#include <Graphic3d_Group.hxx>
#include <Graphic3d_TransformPers.hxx>
#include <Prs3d_Text.hxx>
#include <Prs3d_TextAspect.hxx>
#include <TCollection_ExtendedString.hxx>

namespace kimcad {

namespace {
const Quantity_Color kGuideColour(0.10, 0.55, 0.85, Quantity_TOC_RGB); // blue: Archicad's guide colour family
} // namespace

GuidesOverlay::GuidesOverlay(QVector<QPointF> points, QVector<QLineF> lines, double crossSize, double z)
    : m_points(std::move(points))
    , m_lines(std::move(lines))
    , m_cross(crossSize)
    , m_z(z)
{
    SetZLayer(Graphic3d_ZLayerId_Topmost);
    SetInfiniteState(true); // never part of fit-all bounds
}

void GuidesOverlay::Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int)
{
    auto at = [this](QPointF p) { return gp_Pnt(p.x(), p.y(), m_z); };
    if (!m_points.isEmpty()) {
        Handle(Graphic3d_ArrayOfSegments) crosses = new Graphic3d_ArrayOfSegments(4 * int(m_points.size()));
        for (const QPointF& p : std::as_const(m_points)) {
            crosses->AddVertex(at(p - QPointF(m_cross, 0)));
            crosses->AddVertex(at(p + QPointF(m_cross, 0)));
            crosses->AddVertex(at(p - QPointF(0, m_cross)));
            crosses->AddVertex(at(p + QPointF(0, m_cross)));
        }
        Handle(Graphic3d_Group) g = prs->NewGroup();
        g->SetGroupPrimitivesAspect(new Graphic3d_AspectLine3d(kGuideColour, Aspect_TOL_SOLID, 2.0));
        g->AddPrimitiveArray(crosses);
    }
    if (!m_lines.isEmpty()) {
        Handle(Graphic3d_ArrayOfSegments) dashed = new Graphic3d_ArrayOfSegments(2 * int(m_lines.size()));
        for (const QLineF& l : std::as_const(m_lines)) {
            dashed->AddVertex(at(l.p1()));
            dashed->AddVertex(at(l.p2()));
        }
        Handle(Graphic3d_Group) g = prs->NewGroup();
        g->SetGroupPrimitivesAspect(new Graphic3d_AspectLine3d(kGuideColour, Aspect_TOL_DASH, 1.0));
        g->AddPrimitiveArray(dashed);
    }
}

TrackerOverlay::TrackerOverlay(QVector<Box> boxes, QPoint at, double pixelRatio)
    : m_boxes(std::move(boxes))
    , m_ratio(pixelRatio)
{
    SetZLayer(Graphic3d_ZLayerId_TopOSD);
    SetInfiniteState(true);
    SetTransformPersistence(new Graphic3d_TransformPers(Graphic3d_TMF_2d, Aspect_TOTP_LEFT_LOWER, NCollection_Vec2<int>(at.x(), at.y())));
}

void TrackerOverlay::Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int)
{
    double x = 0;
    for (const Box& b : std::as_const(m_boxes)) {
        Handle(Prs3d_TextAspect) text = new Prs3d_TextAspect();
        text->SetColor(b.focused ? Quantity_Color(1, 1, 1, Quantity_TOC_RGB) : Quantity_Color(0.15, 0.15, 0.18, Quantity_TOC_RGB));
        text->SetHeight(13 * m_ratio);
        text->Aspect()->SetDisplayType(Aspect_TODT_SUBTITLE); // a box behind the text
        text->Aspect()->SetColorSubTitle(b.focused ? kGuideColour : Quantity_Color(1.0, 1.0, 0.92, Quantity_TOC_RGB));
        const QString shown = b.typed && b.focused ? b.text + QStringLiteral("|") : b.text;
        Handle(Graphic3d_Group) g = prs->NewGroup();
        Prs3d_Text::Draw(g, text, TCollection_ExtendedString(shown.toUtf8().constData(), true), gp_Pnt(x, 0, 0));
        x += (12 + 8.5 * shown.size()) * m_ratio;
    }
}

} // namespace kimcad
