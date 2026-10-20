// SPDX-License-Identifier: GPL-3.0-or-later
#include "MeasureOverlay.h"

#include <Graphic3d_ArrayOfPoints.hxx>
#include <Graphic3d_ArrayOfSegments.hxx>
#include <Graphic3d_AspectLine3d.hxx>
#include <Graphic3d_AspectMarker3d.hxx>
#include <Graphic3d_Group.hxx>
#include <Prs3d_Text.hxx>
#include <Prs3d_TextAspect.hxx>
#include <TCollection_ExtendedString.hxx>

namespace kimbim {

MeasureOverlay::MeasureOverlay(QVector<MeasurePoint> path, QString label)
    : m_path(std::move(path))
    , m_label(std::move(label))
{
    SetZLayer(Graphic3d_ZLayerId_Topmost); // never hidden behind the model
    SetInfiniteState(true);                // never part of fit-all bounds
}

void MeasureOverlay::Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int)
{
    if (m_path.isEmpty())
        return;
    const Quantity_Color colour(0.85, 0.2, 0.55, Quantity_TOC_RGB); // magenta: not a pen colour of the model
    auto at = [](const MeasurePoint& p) { return gp_Pnt(p.x, p.y, p.z); };
    const int n = int(m_path.size());
    if (n >= 2) {
        Handle(Graphic3d_ArrayOfSegments) segments = new Graphic3d_ArrayOfSegments(2 * (n - 1));
        for (int i = 1; i < n; ++i) {
            segments->AddVertex(at(m_path[i - 1]));
            segments->AddVertex(at(m_path[i]));
        }
        Handle(Graphic3d_Group) lines = prs->NewGroup();
        lines->SetGroupPrimitivesAspect(new Graphic3d_AspectLine3d(colour, Aspect_TOL_SOLID, 2.0));
        lines->AddPrimitiveArray(segments);
    }
    if (n >= 3) { // the closing edge of the measured area
        Handle(Graphic3d_ArrayOfSegments) closing = new Graphic3d_ArrayOfSegments(2);
        closing->AddVertex(at(m_path.last()));
        closing->AddVertex(at(m_path.first()));
        Handle(Graphic3d_Group) dashed = prs->NewGroup();
        dashed->SetGroupPrimitivesAspect(new Graphic3d_AspectLine3d(colour, Aspect_TOL_DASH, 1.0));
        dashed->AddPrimitiveArray(closing);
    }
    Handle(Graphic3d_ArrayOfPoints) dots = new Graphic3d_ArrayOfPoints(n);
    for (const MeasurePoint& p : std::as_const(m_path))
        dots->AddVertex(at(p));
    Handle(Graphic3d_Group) marks = prs->NewGroup();
    marks->SetGroupPrimitivesAspect(new Graphic3d_AspectMarker3d(Aspect_TOM_O_POINT, colour, 1.5));
    marks->AddPrimitiveArray(dots);
    if (!m_label.isEmpty()) {
        Handle(Prs3d_TextAspect) text = new Prs3d_TextAspect();
        text->SetColor(colour);
        text->SetHeight(15);
        text->Aspect()->SetDisplayType(Aspect_TODT_SUBTITLE); // a box behind the text: readable on any background
        text->Aspect()->SetColorSubTitle(Quantity_Color(1.0, 1.0, 1.0, Quantity_TOC_RGB));
        Handle(Graphic3d_Group) label = prs->NewGroup();
        Prs3d_Text::Draw(label, text, TCollection_ExtendedString(m_label.toUtf8().constData(), true), at(m_path.last()));
    }
}

} // namespace kimbim
