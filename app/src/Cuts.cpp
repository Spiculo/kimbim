// SPDX-License-Identifier: GPL-3.0-or-later
#include "Cuts.h"

#include <Graphic3d_MaterialAspect.hxx>
#include <gp_Dir.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>

namespace kimbim {

namespace {

Handle(Graphic3d_ClipPlane) plane(const gp_Pnt& through, const gp_Dir& keepTowards)
{
    Handle(Graphic3d_ClipPlane) p = new Graphic3d_ClipPlane(gp_Pln(through, keepTowards));
    p->SetCapping(true);
    p->SetUseObjectMaterial(true); // cut faces take each element's own colour
    return p;
}

} // namespace

std::vector<Handle(Graphic3d_ClipPlane)> makePlanes(const CutState& state)
{
    std::vector<Handle(Graphic3d_ClipPlane)> planes;
    if (state.planCut)
        planes.push_back(plane(gp_Pnt(0, 0, state.height), gp_Dir(0, 0, -1))); // keep below
    if (state.box && !state.bounds.IsVoid()) {
        double x0, y0, z0, x1, y1, z1;
        state.bounds.Get(x0, y0, z0, x1, y1, z1);
        planes.push_back(plane(gp_Pnt(x0, 0, 0), gp_Dir(1, 0, 0)));
        planes.push_back(plane(gp_Pnt(x1, 0, 0), gp_Dir(-1, 0, 0)));
        planes.push_back(plane(gp_Pnt(0, y0, 0), gp_Dir(0, 1, 0)));
        planes.push_back(plane(gp_Pnt(0, y1, 0), gp_Dir(0, -1, 0)));
        planes.push_back(plane(gp_Pnt(0, 0, z0), gp_Dir(0, 0, 1)));
        planes.push_back(plane(gp_Pnt(0, 0, z1), gp_Dir(0, 0, -1)));
    }
    return planes;
}

} // namespace kimbim
