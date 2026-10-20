// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <Bnd_Box.hxx>
#include <Graphic3d_ClipPlane.hxx>

#include <vector>

namespace kimbim {

// Cuts are view state (docs/05): never stored in model history.
struct CutState {
    bool planCut = false;
    double height = 0;  // plan cut: keep everything below this height (model units)
    bool box = false;
    Bnd_Box bounds;     // section box: keep only what is inside
};

// Clipping planes with capping (filled cut faces). OCCT keeps the half-space where the plane
// equation is >= 0, so every plane's normal points into the kept region.
std::vector<Handle(Graphic3d_ClipPlane)> makePlanes(const CutState& state);

} // namespace kimbim
