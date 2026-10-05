// SPDX-License-Identifier: GPL-3.0-or-later
// Revit/ArchiCAD navigation preset (owner choice, D48).
#include <QtTest>

#include "Viewport.h"

class TestNavigation : public QObject {
    Q_OBJECT
private slots:
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
