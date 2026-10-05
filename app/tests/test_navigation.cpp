// SPDX-License-Identifier: GPL-3.0-or-later
// Revit/ArchiCAD navigation preset (owner choice, D48).
#include <QApplication>
#include <QMouseEvent>
#include <QtTest>

#include "Viewport.h"

#include <Graphic3d_Camera.hxx>
#include <gp_Pnt.hxx>

class TestNavigation : public QObject {
    Q_OBJECT
private slots:
    // Owner bug report: pan/orbit kept going after releasing the mouse button until Shift was let go.
    void releasingTheButtonEndsTheGesture()
    {
        kimcad::Viewport v;
        v.resize(200, 200);
        QTest::mousePress(&v, Qt::MiddleButton, Qt::ShiftModifier, QPoint(50, 50));
        QCOMPARE(v.pressedButtons(), Aspect_VKeyMouse(Aspect_VKeyMouse_MiddleButton));
        QTest::mouseRelease(&v, Qt::MiddleButton, Qt::ShiftModifier, QPoint(60, 50));
        QCOMPARE(v.pressedButtons(), Aspect_VKeyMouse(Aspect_VKeyMouse_NONE)); // Shift is still held
        QTest::mousePress(&v, Qt::MiddleButton, Qt::NoModifier, QPoint(50, 50));
        QTest::mouseRelease(&v, Qt::MiddleButton, Qt::NoModifier, QPoint(70, 50));
        QCOMPARE(v.pressedButtons(), Aspect_VKeyMouse(Aspect_VKeyMouse_NONE));
    }

    // The same with the exact event sequence a real mouse produces (moves before and after).
    void orbitStopsOnReleaseWhileShiftIsHeld()
    {
        kimcad::Viewport v;
        v.resize(200, 200);
        auto send = [&](QEvent::Type type, QPointF pos, Qt::MouseButton button, Qt::MouseButtons buttons) {
            QMouseEvent e(type, pos, v.mapToGlobal(pos), button, buttons, Qt::ShiftModifier);
            QApplication::sendEvent(&v, &e);
        };
        send(QEvent::MouseButtonPress, {50, 50}, Qt::MiddleButton, Qt::MiddleButton);
        send(QEvent::MouseMove, {60, 55}, Qt::NoButton, Qt::MiddleButton);
        QCOMPARE(v.activeGesture(), AIS_MouseGesture_RotateOrbit);
        send(QEvent::MouseButtonRelease, {60, 55}, Qt::MiddleButton, Qt::NoButton);
        send(QEvent::MouseMove, {80, 60}, Qt::NoButton, Qt::NoButton); // Shift still held
        QCOMPARE(v.pressedButtons(), Aspect_VKeyMouse(Aspect_VKeyMouse_NONE));
        QCOMPARE(v.activeGesture(), AIS_MouseGesture_NONE);
    }

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
