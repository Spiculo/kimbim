// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <AIS_InteractiveObject.hxx>
#include <AIS_ViewCube.hxx>
#include <V3d_TypeOfOrientation.hxx>
#include <gp_Dir.hxx>

#include <QKeySequence>
#include <QRect>
#include <QSize>
#include <QString>
#include <QVector>

#include <functional>

namespace kimcad {

// Preset views and the view cube (D76). Directions are from the target towards the eye, Z up,
// north = +Y: "Front" looks north from the south side, as on Archicad's and Revit's cubes.
struct StandardView {
    V3d_TypeOfOrientation orientation;
    const char* id;    // object name suffix: actionView<id>
    const char* label; // translated in the "ViewCube" context
    QKeySequence shortcut;
};
const QVector<StandardView>& standardViews(); // Top, Bottom, Front, Back, Left, Right, SW, SE, NE, NW
QString standardViewLabel(V3d_TypeOfOrientation orientation);
constexpr V3d_TypeOfOrientation HomeOrientation = V3d_XposYnegZpos; // the default view: south-east isometric
gp_Dir viewDirection(V3d_TypeOfOrientation orientation); // target -> eye
gp_Dir viewUp(V3d_TypeOfOrientation orientation);        // north up in Top/Bottom, Z up otherwise

// OCCT's view cube (AIS_ViewCube) in the view's top-right corner. Clicks go to `onClick` instead of
// the cube's own animation, so the Viewport animates (and fits) every preset the same way.
class ViewCube : public AIS_ViewCube {
public:
    explicit ViewCube(double devicePixelRatio);
    std::function<void(V3d_TypeOfOrientation)> onClick;
    void HandleClick(const Handle(AIS_ViewCubeOwner)& owner) override;
};

// The home button beside the cube: a small house drawn on screen (2D, not selectable).
Handle(AIS_InteractiveObject) makeHomeButton(double devicePixelRatio);

// Where they are, in widget (logical) pixels, for a widget of this size.
QRect viewCubeRect(const QSize& widget);
QRect homeButtonRect(const QSize& widget);

} // namespace kimcad
