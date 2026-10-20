// SPDX-License-Identifier: GPL-3.0-or-later
#include "Cuts.h"

#include <Graphic3d_MaterialAspect.hxx>
#include <gp.hxx>
#include <gp_Vec.hxx>

#include <algorithm>
#include <cmath>

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

bool CutPlane::contains(const gp_Pnt& p, double tolerance) const
{
    return gp_Vec(point, p).Dot(gp_Vec(normal)) >= -tolerance;
}

void CutPlane::setAngle(double degrees)
{
    if (kind != Kind::Oblique)
        return;
    angle = degrees;
    // Base normal: horizontal, perpendicular to the line, on the side the normal is now.
    gp_Dir base = direction.Crossed(gp::DZ());
    if (base.Dot(normal) < 0)
        base.Reverse();
    // The rotation goes from `base` towards direction x base (up for a +X line).
    const gp_Dir up = direction.Crossed(base);
    const double a = angle * M_PI / 180.0;
    const gp_Vec n = gp_Vec(base) * std::cos(a) + gp_Vec(up) * std::sin(a);
    if (n.Magnitude() > 1e-9)
        normal = gp_Dir(n);
}

int planeCount(const CutState& state)
{
    int n = state.planCut ? 1 : 0;
    if (state.box && !state.bounds.IsVoid())
        n += 6;
    for (const CutPlane& p : state.planes)
        if (p.enabled)
            ++n;
    return n;
}

int maxUserPlanes(int driverLimit, bool planCut, bool box)
{
    const int fixed = (planCut ? 1 : 0) + (box ? 6 : 0);
    if (driverLimit <= 0)
        return 1 << 20;
    return std::max(0, driverLimit - fixed);
}

std::vector<Handle(Graphic3d_ClipPlane)> makePlanes(const CutState& state, int limit)
{
    std::vector<Handle(Graphic3d_ClipPlane)> planes;
    if (state.planCut && (limit <= 0 || int(planes.size()) < limit))
        planes.push_back(plane(gp_Pnt(0, 0, state.height), gp_Dir(0, 0, -1))); // keep below
    if (state.box && !state.bounds.IsVoid()) {
        double x0, y0, z0, x1, y1, z1;
        state.bounds.Get(x0, y0, z0, x1, y1, z1);
        const gp_Pnt points[] = {gp_Pnt(x0, 0, 0), gp_Pnt(x1, 0, 0), gp_Pnt(0, y0, 0),
            gp_Pnt(0, y1, 0), gp_Pnt(0, 0, z0), gp_Pnt(0, 0, z1)};
        const gp_Dir dirs[] = {gp_Dir(1, 0, 0), gp_Dir(-1, 0, 0), gp_Dir(0, 1, 0),
            gp_Dir(0, -1, 0), gp_Dir(0, 0, 1), gp_Dir(0, 0, -1)};
        for (int i = 0; i < 6; ++i)
            if (limit <= 0 || int(planes.size()) < limit)
                planes.push_back(plane(points[i], dirs[i]));
    }
    for (const CutPlane& p : state.planes)
        if (p.enabled && (limit <= 0 || int(planes.size()) < limit))
            planes.push_back(plane(p.point, p.normal));
    return planes;
}

} // namespace kimbim
