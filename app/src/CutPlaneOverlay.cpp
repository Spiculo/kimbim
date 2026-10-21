// SPDX-License-Identifier: GPL-3.0-or-later
#include "CutPlaneOverlay.h"

#include <Aspect_TypeOfLine.hxx>
#include <Graphic3d_ArrayOfSegments.hxx>
#include <Graphic3d_ArrayOfTriangles.hxx>
#include <Graphic3d_AspectFillArea3d.hxx>
#include <Graphic3d_AspectLine3d.hxx>
#include <Graphic3d_Group.hxx>
#include <Prs3d_Presentation.hxx>

#include "CutPlanes.h"

namespace kimbim {

CutPlaneOverlay::CutPlaneOverlay(const gp_Pln& plane, double halfSize)
    : m_plane(plane)
    , m_halfSize(halfSize > 1e-6 ? halfSize : 1.0)
{
    SetDisplayMode(0);
}

gp_Pnt CutPlaneOverlay::handleTip() const
{
    return centre().Translated(gp_Vec(normal()) * (m_halfSize * 0.55));
}

void CutPlaneOverlay::Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs,
    const int)
{
    gp_Pnt origin;
    gp_Dir u, v;
    planeBasis(m_plane, &origin, &u, &v);
    const gp_Dir n = normal();
    const gp_Vec su = gp_Vec(u) * m_halfSize, sv = gp_Vec(v) * m_halfSize;
    const gp_Pnt corners[4] = {origin.Translated(-su - sv), origin.Translated(su - sv),
        origin.Translated(su + sv), origin.Translated(-su + sv)};

    Handle(Graphic3d_ArrayOfTriangles) fill = new Graphic3d_ArrayOfTriangles(6);
    for (int i : {0, 1, 2, 0, 2, 3})
        fill->AddVertex(corners[i]);
    Handle(Graphic3d_AspectFillArea3d) area = new Graphic3d_AspectFillArea3d();
    area->SetInteriorStyle(Aspect_IS_SOLID);
    area->SetInteriorColor(Quantity_ColorRGBA(0.16f, 0.52f, 0.92f, 0.30f)); // translucent
    area->SetShadingModel(Graphic3d_TypeOfShadingModel_Unlit);
    area->SetFaceCulling(Graphic3d_TypeOfBackfacingModel_DoubleSided);
    Handle(Graphic3d_Group) g = prs->NewGroup();
    g->SetGroupPrimitivesAspect(area);
    g->AddPrimitiveArray(fill);

    // Outline and the normal handle, in a strong blue that reads on the model.
    Handle(Graphic3d_ArrayOfSegments) lines = new Graphic3d_ArrayOfSegments(14);
    for (int i = 0; i < 4; ++i) {
        lines->AddVertex(corners[i]);
        lines->AddVertex(corners[(i + 1) % 4]);
    }
    lines->AddVertex(origin);
    lines->AddVertex(handleTip());
    // A small cross at the tip makes it easy to grab.
    const gp_Pnt tip = handleTip();
    const double k = m_halfSize * 0.06;
    lines->AddVertex(tip.Translated(-gp_Vec(u) * k));
    lines->AddVertex(tip.Translated(gp_Vec(u) * k));
    lines->AddVertex(tip.Translated(-gp_Vec(v) * k));
    lines->AddVertex(tip.Translated(gp_Vec(v) * k));
    Handle(Graphic3d_AspectLine3d) line = new Graphic3d_AspectLine3d(
        Quantity_Color(0.06, 0.38, 0.82, Quantity_TOC_RGB), Aspect_TOL_SOLID, 2.0f);
    Handle(Graphic3d_Group) gl = prs->NewGroup();
    gl->SetGroupPrimitivesAspect(line);
    gl->AddPrimitiveArray(lines);
}

void CutPlaneOverlay::ComputeSelection(const Handle(SelectMgr_Selection)&, const int) {}

} // namespace kimbim
