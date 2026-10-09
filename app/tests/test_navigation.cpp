// SPDX-License-Identifier: GPL-3.0-or-later
// Revit/ArchiCAD navigation preset (owner choice, D48); view cube, preset views, perspective (D76).
#include <QApplication>
#include <QMouseEvent>
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
