// SPDX-License-Identifier: GPL-3.0-or-later
// Revit/ArchiCAD navigation preset (owner choice, D48).
#include <QtTest>

#include "Viewport.h"

#include <Graphic3d_Camera.hxx>
#include <gp_Pnt.hxx>

class TestNavigation : public QObject {
    Q_OBJECT
private slots:
    // Slice 4: plan view looks straight down; Shift+middle pans instead of orbiting there.
    void planViewDisablesOrbit()
    {
        kimcad::Viewport v;
        QVERIFY(!v.isPlanView());
        v.setPlanView(3.0);
        QVERIFY(v.isPlanView());
        QCOMPARE(v.planElevation(), 3.0);
        QCOMPARE(v.gestureFor(Aspect_VKeyMouse_MiddleButton, Aspect_VKeyFlags_SHIFT), AIS_MouseGesture_Pan);
        QVERIFY(v.view()->Camera()->IsOrthographic());
        v.set3DView();
        QVERIFY(!v.isPlanView());
        QCOMPARE(v.gestureFor(Aspect_VKeyMouse_MiddleButton, Aspect_VKeyFlags_SHIFT), AIS_MouseGesture_RotateOrbit);
    }

    void pointOnPlaneNeedsAWindow()
    {
        kimcad::Viewport v;
        gp_Pnt p;
        QVERIFY(!v.pointOnPlane(10, 10, 0.0, &p)); // headless: no projection to intersect
    }

    void middlePansShiftMiddleOrbitsLeftBoxSelects()
    {
        kimcad::Viewport v;
        QCOMPARE(v.gestureFor(Aspect_VKeyMouse_MiddleButton, Aspect_VKeyFlags_NONE), AIS_MouseGesture_Pan);
        QCOMPARE(v.gestureFor(Aspect_VKeyMouse_MiddleButton, Aspect_VKeyFlags_SHIFT), AIS_MouseGesture_RotateOrbit);
        QCOMPARE(v.gestureFor(Aspect_VKeyMouse_LeftButton, Aspect_VKeyFlags_NONE), AIS_MouseGesture_SelectRectangle);
    }

    void rightButtonIsLeftForContextMenus()
    {
        kimcad::Viewport v;
        QCOMPARE(v.gestureFor(Aspect_VKeyMouse_RightButton, Aspect_VKeyFlags_NONE), AIS_MouseGesture_NONE);
    }

    void orbitsAroundThePickedPoint()
    {
        kimcad::Viewport v;
        QCOMPARE(v.rotationMode(), AIS_RotationMode_PickLast);
    }
};

QTEST_MAIN(TestNavigation)
#include "test_navigation.moc"
