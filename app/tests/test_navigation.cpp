// SPDX-License-Identifier: GPL-3.0-or-later
// Revit/ArchiCAD navigation preset (owner choice, D48); view cube, preset views, perspective (D76).
#include <QApplication>
#include <QMouseEvent>
#include <QNativeGestureEvent>
#include <QPointingDevice>
#include <QWheelEvent>
#include <QSet>
#include <QSignalSpy>
#include <QtTest>

#include <cmath>

#include "ElementBatch.h"
#include "ViewCube.h"
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

    // D76: every preset view looks from its side or corner; Top has north up, the others Z up.
    void presetViewsLookFromTheirSide()
    {
        kimcad::Viewport v;
        v.addBatch(batch(3));
        QCOMPARE(kimcad::standardViews().size(), qsizetype(10));
        for (const kimcad::StandardView& sv : kimcad::standardViews()) {
            v.setStandardView(sv.orientation, false);
            QVERIFY2(sameDir(eyeDir(v), kimcad::viewDirection(sv.orientation)), sv.id);
            const gp_Dir up = v.view()->Camera()->Up();
            const gp_Dir eye = kimcad::viewDirection(sv.orientation);
            if (std::abs(eye.Z()) > 0.999) {
                QVERIFY2(sameDir(up, gp::DY()), sv.id); // north up
            } else { // upright: Z up, no roll
                QVERIFY2(up.Z() > 0, sv.id);
                QVERIFY2(std::abs(up.Dot(gp::DZ().Crossed(eye))) < 1e-6, sv.id);
            }
            QVERIFY2(!v.isAnimating(), sv.id); // no window: applied at once
        }
        v.setStandardView(V3d_Yneg, false); // Front: from the south, looking north
        QVERIFY(v.view()->Camera()->Direction().Y() > 0.999);
        v.setStandardView(V3d_Zpos, false); // Top: looking down, north up
        QVERIFY(v.view()->Camera()->Direction().Z() < -0.999);
        QVERIFY(v.view()->Camera()->Up().Y() > 0.999);
        v.setStandardView(V3d_XnegYnegZpos, false); // south-west isometric: eye at -X, -Y, +Z
        const gp_Dir sw = eyeDir(v);
        QVERIFY(sw.X() < 0 && sw.Y() < 0 && sw.Z() > 0);
    }

    void homeIsTheDefaultIsometric()
    {
        kimcad::Viewport v;
        QVERIFY(sameDir(eyeDir(v), kimcad::viewDirection(kimcad::HomeOrientation)));
        v.setStandardView(V3d_Xneg, false);
        QVERIFY(!sameDir(eyeDir(v), kimcad::viewDirection(kimcad::HomeOrientation)));
        v.homeView(false);
        QVERIFY(sameDir(eyeDir(v), kimcad::viewDirection(kimcad::HomeOrientation)));
    }

    // Plans look straight down: presets and perspective wait for the 3D view.
    void planViewsIgnorePresetsAndStayOrthographic()
    {
        kimcad::Viewport v;
        v.setPerspective(true);
        QVERIFY(!v.view()->Camera()->IsOrthographic());
        v.setPlanView(0.0);
        QVERIFY(v.view()->Camera()->IsOrthographic());
        QVERIFY(v.isPerspective()); // the view's setting is kept
        v.setStandardView(V3d_Yneg, false);
        QVERIFY(v.view()->Camera()->Direction().Z() < -0.999);
        QVERIFY(!v.viewCubeShown());
        QVERIFY(v.viewCubeRect().isEmpty());
        v.set3DView();
        QVERIFY(!v.view()->Camera()->IsOrthographic());
        QVERIFY(v.viewCubeShown());
    }

    void perspectiveToggles()
    {
        kimcad::Viewport v;
        QVERIFY(!v.isPerspective());
        QVERIFY(v.view()->Camera()->IsOrthographic());
        const double scale = v.view()->Camera()->Scale();
        v.setPerspective(true);
        QVERIFY(v.isPerspective());
        QCOMPARE(v.view()->Camera()->ProjectionType(), Graphic3d_Camera::Projection_Perspective);
        QCOMPARE(v.view()->Camera()->FOVy(), 45.0);
        QVERIFY(std::abs(v.view()->Camera()->Scale() - scale) < 1e-6 * scale); // same size at the target
        v.setStandardView(V3d_Xpos, false); // presets keep the projection
        QVERIFY(!v.view()->Camera()->IsOrthographic());
        v.setPerspective(false);
        QVERIFY(v.view()->Camera()->IsOrthographic());
        // Navigation is the same in both (D48).
        v.setPerspective(true);
        QCOMPARE(v.gestureFor(Aspect_VKeyMouse_MiddleButton, Aspect_VKeyFlags_NONE), AIS_MouseGesture_Pan);
        QCOMPARE(v.gestureFor(Aspect_VKeyMouse_MiddleButton, Aspect_VKeyFlags_SHIFT), AIS_MouseGesture_RotateOrbit);
    }

    // Each view has its own camera (D71): one view's perspective doesn't change another's.
    void perspectiveIsPerView()
    {
        kimcad::Viewport a;
        kimcad::Viewport b(a.scene());
        a.setPerspective(true);
        QVERIFY(!a.view()->Camera()->IsOrthographic());
        QVERIFY(b.view()->Camera()->IsOrthographic());
        b.setStandardView(V3d_Zpos, false);
        QVERIFY(!sameDir(eyeDir(a), eyeDir(b)));
    }

    // Clicks on the cube or its home button never reach selection or start a box/gesture.
    void cubeClicksKeepTheSelection()
    {
        kimcad::Viewport v;
        v.resize(500, 400);
        v.addBatch(batch(4));
        v.selectGuids({"g1"});
        QSignalSpy changed(&v, &kimcad::Viewport::selectionChanged);
        for (const QPoint at : {v.viewCubeRect().center(), v.viewCubeRect().topLeft() + QPoint(3, 3), v.homeButtonRect().center()}) {
            QVERIFY(v.viewCubeRect().contains(at) || v.homeButtonRect().contains(at));
            QTest::mousePress(&v, Qt::LeftButton, Qt::NoModifier, at);
            QCOMPARE(v.pressedButtons(), Aspect_VKeyMouse(Aspect_VKeyMouse_NONE)); // no box selection started
            QTest::mouseRelease(&v, Qt::LeftButton, Qt::NoModifier, at);
            QTest::mouseDClick(&v, Qt::LeftButton, Qt::NoModifier, at);
            QTest::mousePress(&v, Qt::LeftButton, Qt::ControlModifier, at);
            QTest::mouseRelease(&v, Qt::LeftButton, Qt::ControlModifier, at);
        }
        QCOMPARE(v.selectedGuids(), QStringList({"g1"}));
        QCOMPARE(changed.count(), 0);
        // The home button turns the view home (no window: at once).
        v.setStandardView(V3d_Zpos, false);
        QTest::mouseClick(&v, Qt::LeftButton, Qt::NoModifier, v.homeButtonRect().center());
        QVERIFY(sameDir(eyeDir(v), kimcad::viewDirection(kimcad::HomeOrientation)));
        // Outside the cube a left press still starts the box selection gesture.
        QTest::mousePress(&v, Qt::LeftButton, Qt::NoModifier, QPoint(40, 360));
        QCOMPARE(v.pressedButtons(), Aspect_VKeyMouse(Aspect_VKeyMouse_LeftButton));
        QTest::mouseRelease(&v, Qt::LeftButton, Qt::NoModifier, QPoint(40, 360));
    }

    void cubeDragOrbits()
    {
        kimcad::Viewport v;
        v.resize(500, 400);
        const gp_Dir before = eyeDir(v);
        const QPoint at = v.viewCubeRect().center();
        QTest::mousePress(&v, Qt::LeftButton, Qt::NoModifier, at);
        QMouseEvent move(QEvent::MouseMove, QPointF(at + QPoint(30, 0)), v.mapToGlobal(QPointF(at + QPoint(30, 0))), Qt::NoButton,
            Qt::LeftButton, Qt::NoModifier);
        QApplication::sendEvent(&v, &move);
        QTest::mouseRelease(&v, Qt::LeftButton, Qt::NoModifier, at + QPoint(30, 0));
        const gp_Dir after = eyeDir(v);
        QVERIFY(!sameDir(before, after));
        QVERIFY(std::abs(before.Z() - after.Z()) < 1e-6); // a horizontal drag turns around Z only
    }

    // Preset shortcuts must not clash with each other (the app's other shortcuts: test_main_window).
    void presetShortcutsAreDistinct()
    {
        QSet<QString> keys;
        for (const kimcad::StandardView& sv : kimcad::standardViews()) {
            QVERIFY(!sv.shortcut.isEmpty());
            keys.insert(sv.shortcut.toString());
        }
        QCOMPARE(keys.size(), kimcad::standardViews().size());
    }

private:
    static gp_Dir eyeDir(const kimcad::Viewport& v) { return v.view()->Camera()->Direction().Reversed(); }
    static bool sameDir(const gp_Dir& a, const gp_Dir& b) { return a.Dot(b) > 0.9999; }
private slots:
    // D89 Tab cycling (Revit): Tab steps through the elements under the resting cursor; the click
    // selects the highlighted one instead of the front one.
    void tabCyclesThroughOverlappingElements()
    {
        kimcad::Viewport v;
        v.resize(300, 300);
        v.addBatch(batch(3));
        v.setPickProvider([](const QPointF&) { return QStringList{"g0", "g1", "g2"}; }); // front to back
        QMouseEvent move(QEvent::MouseMove, QPointF(50, 50), v.mapToGlobal(QPointF(50, 50)), Qt::NoButton, Qt::NoButton, Qt::NoModifier);
        QApplication::sendEvent(&v, &move);
        QTest::keyClick(&v, Qt::Key_Tab);
        QCOMPARE(v.cycleCandidate(), QString("g1"));
        QTest::keyClick(&v, Qt::Key_Tab);
        QCOMPARE(v.cycleCandidate(), QString("g2"));
        QTest::keyClick(&v, Qt::Key_Tab);
        QCOMPARE(v.cycleCandidate(), QString("g0"));
        QTest::keyClick(&v, Qt::Key_Backtab);
        QCOMPARE(v.cycleCandidate(), QString("g2"));
        QTest::keyClick(&v, Qt::Key_Backtab);
        QCOMPARE(v.cycleCandidate(), QString("g1"));
        QSignalSpy changed(&v, &kimcad::Viewport::selectionChanged);
        QTest::mouseClick(&v, Qt::LeftButton, Qt::NoModifier, QPoint(51, 50));
        QCOMPARE(v.selectedGuids(), QStringList({"g1"}));
        QCOMPARE(changed.count(), 1);
        QCOMPARE(v.pressedButtons(), Aspect_VKeyMouse(Aspect_VKeyMouse_NONE)); // no box selection started
        QVERIFY(v.cycleCandidate().isEmpty());
        // Ctrl adds the cycled element; moving away forgets the cycle.
        QTest::keyClick(&v, Qt::Key_Tab);
        QTest::keyClick(&v, Qt::Key_Tab);
        QCOMPARE(v.cycleCandidate(), QString("g2"));
        QTest::mouseClick(&v, Qt::LeftButton, Qt::ControlModifier, QPoint(50, 50));
        const QStringList both = v.selectedGuids();
        QCOMPARE(QSet<QString>(both.begin(), both.end()), QSet<QString>({"g1", "g2"}));
        QTest::keyClick(&v, Qt::Key_Tab);
        QMouseEvent away(QEvent::MouseMove, QPointF(120, 50), v.mapToGlobal(QPointF(120, 50)), Qt::NoButton, Qt::NoButton, Qt::NoModifier);
        QApplication::sendEvent(&v, &away);
        QVERIFY(v.cycleCandidate().isEmpty());
    }

    // D89 touchpad: pixel deltas (two-finger scroll) pan, a notched wheel zooms, per the preference.
    void touchpadScrollPansWheelZooms()
    {
        using kimcad::Viewport;
        Viewport v;
        v.resize(400, 300);
        v.addBatch(batch(3));
        v.fitAll();
        Viewport::setScrollMode(Viewport::ScrollMode::Auto);
        const Handle(Graphic3d_Camera)& cam = v.view()->Camera();
        auto wheel = [&](QPoint pixel, QPoint angle, Qt::KeyboardModifiers mods = Qt::NoModifier) {
            QWheelEvent e(QPointF(200, 150), v.mapToGlobal(QPointF(200, 150)), pixel, angle, Qt::NoButton, mods, Qt::NoScrollPhase, false);
            QApplication::sendEvent(&v, &e);
        };
        const gp_Pnt c0 = cam->Center();
        const double s0 = cam->Scale();
        wheel(QPoint(20, 30), QPoint(0, 0));
        QCOMPARE(v.lastScrollAction(), Viewport::ScrollAction::Pan);
        QVERIFY(cam->Center().Distance(c0) > 1e-6);
        QCOMPARE(cam->Scale(), s0);
        QTest::qWait(350); // past the touchpad stream
        const double s1 = cam->Scale();
        wheel(QPoint(), QPoint(0, 120));
        QCOMPARE(v.lastScrollAction(), Viewport::ScrollAction::Zoom);
        QVERIFY(cam->Scale() < s1); // zoomed in
        // "Scrolling zooms": pixel deltas zoom too; "scrolling pans": the wheel pans.
        Viewport::setScrollMode(Viewport::ScrollMode::Zoom);
        wheel(QPoint(0, 30), QPoint(0, 90));
        QCOMPARE(v.lastScrollAction(), Viewport::ScrollAction::Zoom);
        Viewport::setScrollMode(Viewport::ScrollMode::Pan);
        wheel(QPoint(), QPoint(0, 120));
        QCOMPARE(v.lastScrollAction(), Viewport::ScrollAction::Pan);
        wheel(QPoint(0, 30), QPoint(0, 90), Qt::ControlModifier); // Ctrl+scroll (Windows' pinch) zooms
        QCOMPARE(v.lastScrollAction(), Viewport::ScrollAction::Zoom);
        const gp_Dir d0 = cam->Direction();
        wheel(QPoint(40, 0), QPoint(0, 0), Qt::ShiftModifier); // Shift+two fingers orbits in 3D
        QCOMPARE(v.lastScrollAction(), Viewport::ScrollAction::Orbit);
        QVERIFY(!cam->Direction().IsEqual(d0, 1e-6));
        v.setPlanView(0.0);
        wheel(QPoint(40, 0), QPoint(0, 0), Qt::ShiftModifier); // plans never orbit
        QCOMPARE(v.lastScrollAction(), Viewport::ScrollAction::Pan);
        Viewport::setScrollMode(Viewport::ScrollMode::Auto);
        QCOMPARE(Viewport::scrollModeFrom("pan"), Viewport::ScrollMode::Pan);
        QCOMPARE(Viewport::scrollModeFrom("zoom"), Viewport::ScrollMode::Zoom);
        QCOMPARE(Viewport::scrollModeFrom("whatever"), Viewport::ScrollMode::Auto);
    }

    void pinchZooms()
    {
        kimcad::Viewport v;
        v.resize(400, 300);
        v.addBatch(batch(3));
        v.fitAll();
        const double s0 = v.view()->Camera()->Scale();
        QNativeGestureEvent pinch(Qt::ZoomNativeGesture, QPointingDevice::primaryPointingDevice(), 2, QPointF(200, 150),
            QPointF(200, 150), v.mapToGlobal(QPointF(200, 150)), 0.25, QPointF());
        QApplication::sendEvent(&v, &pinch);
        QVERIFY(std::abs(v.view()->Camera()->Scale() - s0 / 1.25) < 1e-9 * s0);
        QNativeGestureEvent out(Qt::ZoomNativeGesture, QPointingDevice::primaryPointingDevice(), 2, QPointF(200, 150),
            QPointF(200, 150), v.mapToGlobal(QPointF(200, 150)), -0.2, QPointF());
        QApplication::sendEvent(&v, &out);
        QVERIFY(std::abs(v.view()->Camera()->Scale() - s0 / 1.25 / 0.8) < 1e-9 * s0);
    }

private:
    static Handle(kimcad::ElementBatch) batch(int n)
    {
        kimcad::MeshChunk c;
        c.voff.push_back(0);
        c.toff.push_back(0);
        for (int e = 0; e < n; ++e) {
            c.guids << QStringLiteral("g%1").arg(e);
            c.types << QStringLiteral("IfcWall");
            const float x = float(e);
            const float vtx[] = {x, 0, 0, x + 0.5f, 0, 0, x, 0.5f, 1};
            c.verts.insert(c.verts.end(), std::begin(vtx), std::end(vtx));
            const uint32_t base = uint32_t(e * 3);
            c.tris.insert(c.tris.end(), {base, base + 1, base + 2});
            c.voff.push_back(uint32_t(c.verts.size() / 3));
            c.toff.push_back(uint32_t(c.tris.size() / 3));
        }
        return new kimcad::ElementBatch(std::move(c));
    }
};

QTEST_MAIN(TestNavigation)
#include "test_navigation.moc"
