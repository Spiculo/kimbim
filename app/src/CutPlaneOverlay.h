// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <AIS_InteractiveObject.hxx>
#include <gp_Dir.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>

namespace kimbim {

// D95: the selected cut plane in a 3D view: a translucent rectangle on the plane and a handle
// along its normal that the view drags. Display only (nothing is selectable).
class CutPlaneOverlay : public AIS_InteractiveObject {
public:
    CutPlaneOverlay(const gp_Pln& plane, double halfSize);
    void Compute(const Handle(PrsMgr_PresentationManager)& thePrsMgr,
        const Handle(Prs3d_Presentation)& thePrs, const int theMode) override;
    void ComputeSelection(const Handle(SelectMgr_Selection)& theSel, const int theMode) override;

    const gp_Pln& plane() const { return m_plane; }
    gp_Pnt centre() const { return m_plane.Location(); }
    gp_Dir normal() const { return m_plane.Axis().Direction(); }
    double halfSize() const { return m_halfSize; }
    gp_Pnt handleTip() const;

private:
    gp_Pln m_plane;
    double m_halfSize;
};

} // namespace kimbim
