// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <Bnd_Box.hxx>
#include <Graphic3d_ClipPlane.hxx>
#include <gp_Dir.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>

#include <string>
#include <vector>

namespace kimbim {

// D95: a user cut plane. The kept half-space is where (x - point) . normal >= 0.
struct CutPlane {
    enum class Kind { Horizontal, Vertical, Oblique };

    std::string name;
    bool enabled = true;  // clips the model
    bool visible = true;  // draws its face and handle in the view (enabled or not)
    Kind kind = Kind::Oblique;
    gp_Pnt point{0, 0, 0};
    gp_Dir normal{0, 0, -1};  // points into the kept region
    gp_Dir direction{1, 0, 0}; // the plane's line direction (horizontal for vertical/oblique)
    double angle = 0;          // oblique tilt in degrees about `direction`

    gp_Pln plane() const { return gp_Pln(point, normal); }
    bool contains(const gp_Pnt& p, double tolerance = 1e-6) const;
    void flip() { normal.Reverse(); }
    // The plane equation n.x = offset; setting it slides the plane along its normal.
    double offset() const { return point.XYZ().Dot(normal.XYZ()); }
    void setOffset(double value) { point = gp_Pnt(normal.XYZ() * value); }
    void translate(double distance) { point.Translate(gp_Vec(normal) * distance); }
    // Oblique planes tilt about their line; vertical/horizontal planes ignore the call.
    void setAngle(double degrees);
};

// Cuts are view state (docs/05): never stored in model history.
struct CutState {
    bool planCut = false;
    double height = 0;  // plan cut: keep everything below this height (model units)
    bool box = false;
    Bnd_Box bounds;     // section box: keep only what is inside
    std::vector<CutPlane> planes; // D95: user planes, in panel order
};

// Clipping planes with capping (filled cut faces). OCCT keeps the half-space where the plane
// equation is >= 0, so every plane's normal points into the kept region. A positive `limit`
// truncates the list (the driver's clip-plane count); 0 means no limit.
std::vector<Handle(Graphic3d_ClipPlane)> makePlanes(const CutState& state, int limit = 0);

// How many clip planes the state needs (plan cut, the box's six sides and the enabled planes).
int planeCount(const CutState& state);
// How many user planes fit beside the plan cut and the box with this driver limit.
int maxUserPlanes(int driverLimit, bool planCut, bool box);

} // namespace kimbim
