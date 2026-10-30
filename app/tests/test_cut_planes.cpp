// SPDX-License-Identifier: GPL-3.0-or-later
// D95: cut planes in any direction, wired to the 3D view, the panel and saved views.
#include <QAction>
#include <QDoubleSpinBox>
#include <QJsonObject>
#include <QLabel>
#include <QPushButton>
#include <QStandardPaths>
#include <QTableWidget>
#include <QToolButton>
#include <DockManager.h>
#include <DockWidget.h>
#include <QtTest>

#include "CutPlanesPanel.h"
#include "DockLayout.h"
#include "DrawingView.h"
#include "DrawingsPanel.h"
#include "LevelsBar.h"
#include "MainWindow.h"
#include "PythonEngine.h"
#include "WallTool.h"
#include "Viewport.h"

class TestCutPlanes : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { QStandardPaths::setTestModeEnabled(true); }

    void verticalObliqueAndHorizontalCutsClipTheView()
    {
        kimbim::MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        QVERIFY(w.addVerticalCut({0, 0}, {0, 5}, {1, 0}, 0));
        QCOMPARE(w.cutPlanes().size(), 1);
        QCOMPARE(w.cutPlanes().front().kind, kimbim::CutPlane::Kind::Vertical);
        QCOMPARE(w.viewport()->clipPlaneCount(), 1);

        QVERIFY(w.addObliqueCut({2, 0}, {2, 5}, {-1, 0}, 35, 0));
        QCOMPARE(w.cutPlanes().size(), 2);
        QCOMPARE(w.viewport()->clipPlaneCount(), 2);
        QVERIFY(std::abs(std::abs(w.cutPlanes()[1].normal.Z()) - std::sin(35 * M_PI / 180)) < 1e-9);

        QVERIFY(w.addHorizontalCut(2.7));
        QCOMPARE(w.cutPlanes().size(), 3);
        QCOMPARE(w.viewport()->clipPlaneCount(), 3);
        QCOMPARE(w.selectedCutPlane(), 2);

        // Each user plane gets a poché pass; the empty model has no section loops.
        QCOMPARE(w.viewport()->sectionPlaneCount(), 0);
        QVERIFY(w.close());
    }

    void fourUserPlanesFitWithThePlanCutAndTheBox()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        w.setTool(kimbim::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.wallTool()->finish();
        w.setTool(kimbim::MainWindow::Tool::None);
        w.findChild<QAction*>(QStringLiteral("actionPlanCut"))->setChecked(true);
        w.findChild<QAction*>(QStringLiteral("actionSectionBox"))->setChecked(true);
        for (int i = 0; i < 4; ++i)
            QVERIFY2(w.addVerticalCut({-1, -2.0 + i}, {6, -2.0 + i}, {0, 1}, 0), "the fourth user plane must fit");
        QCOMPARE(w.cutPlanes().size(), 4);
        QCOMPARE(w.viewport()->clipPlaneCount(), 1 + 6 + 4);
    }

    void aCutThroughAWallDrawsPoche()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        w.setTool(kimbim::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.wallTool()->finish();
        w.setTool(kimbim::MainWindow::Tool::None);
        QVERIFY(w.viewport()->elementCount() >= 1);
        QVERIFY(w.addVerticalCut({-1, 0.05}, {6, 0.05}, {0, 1}, 0)); // cuts the wall lengthwise (inside it whatever its reference line)
        QVERIFY(w.viewport()->sectionElementCount() >= 1);
        // The plan cut adds its own section, clipped against the vertical cut.
        w.findChild<QAction*>(QStringLiteral("actionPlanCut"))->setChecked(true);
        QVERIFY(w.viewport()->sectionElementCount() >= 1);
        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionPlanCut"))->isChecked());
    }

    void cutsFromAFaceKeepTheGivenSide()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.addFaceCut(gp_Pnt(1, 2, 3), gp_Dir(0, 0, 1)));
        QCOMPARE(w.cutPlanes().size(), 1);
        QVERIFY(w.cutPlanes().front().normal.Z() > 0.99);
        QVERIFY(w.cutPlanes().front().contains(gp_Pnt(1, 2, 4)));
        QVERIFY(!w.cutPlanes().front().contains(gp_Pnt(1, 2, 2)));
        QVERIFY(w.addFaceCut(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)));
        QCOMPARE(w.viewport()->clipPlaneCount(), 2);
    }

    void editsFlipMoveTiltAndDelete()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.addVerticalCut({0, 0}, {0, 5}, {1, 0}, 0)); // keeps +X
        QVERIFY(w.cutPlanes().front().normal.X() > 0.99);
        QVERIFY(w.flipCutPlane(0));
        QVERIFY(w.cutPlanes().front().normal.X() < -0.99);
        QVERIFY(w.setCutPlaneOffset(0, 1.5));
        QVERIFY(std::abs(w.cutPlanes().front().offset() - 1.5) < 1e-9);
        QVERIFY(!w.setCutPlaneAngle(0, 20)); // a vertical plane has no tilt
        QVERIFY(w.addObliqueCut({2, 0}, {2, 5}, {-1, 0}, 20, 0));
        QVERIFY(w.setCutPlaneAngle(1, 40));
        QVERIFY(std::abs(w.cutPlanes()[1].angle - 40) < 1e-9);
        QVERIFY(w.setCutPlaneEnabled(1, false));
        QCOMPARE(w.viewport()->clipPlaneCount(), 1);
        QVERIFY(w.setCutPlaneEnabled(1, true));
        QCOMPARE(w.viewport()->clipPlaneCount(), 2);
        QVERIFY(w.removeCutPlane(0));
        QCOMPARE(w.cutPlanes().size(), 1);
        QCOMPARE(w.cutPlanes().front().kind, kimbim::CutPlane::Kind::Oblique);
    }

    void visibleHidesThePlaneWithoutTurningTheCutOff()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.addVerticalCut({0, 0}, {0, 5}, {1, 0}, 0));
        QCOMPARE(w.viewport()->clipPlaneCount(), 1);
        QVERIFY(w.viewport()->hasCutPlaneOverlay());

        QVERIFY(w.setCutPlaneVisible(0, false)); // hidden: still cuts, no blue plane
        QCOMPARE(w.viewport()->clipPlaneCount(), 1);
        QVERIFY(!w.viewport()->hasCutPlaneOverlay());
        QCOMPARE(w.viewport()->sectionPlaneCount(), 0);

        QVERIFY(w.setCutPlaneVisible(0, true));
        QVERIFY(w.viewport()->hasCutPlaneOverlay());
        QVERIFY(w.setCutPlaneEnabled(0, false)); // off but visible: the plane can still be found
        QCOMPARE(w.viewport()->clipPlaneCount(), 0);
        QVERIFY(w.viewport()->hasCutPlaneOverlay());
        QVERIFY(w.setCutPlaneEnabled(0, true));
    }

    void onlyTheSelectedCutDrawsItsFace()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        w.setTool(kimbim::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.wallTool()->finish();
        w.setTool(kimbim::MainWindow::Tool::None);
        QVERIFY(w.addVerticalCut({-1, 0.05}, {6, 0.05}, {0, 1}, 0));   // keep y >= 0.05
        QVERIFY(w.cutPlanes()[0].normal.Y() > 0.99);
        QCOMPARE(w.viewport()->sectionPlaneCount(), 1); // the only cut, selected: its face
        QVERIFY(w.addVerticalCut({-1, 0.15}, {6, 0.15}, {0, -1}, 0));  // keep y <= 0.15
        QVERIFY(w.cutPlanes()[1].normal.Y() < -0.99);
        QCOMPARE(w.viewport()->clipPlaneCount(), 2);
        QCOMPARE(w.selectedCutPlane(), 1);
        QCOMPARE(w.viewport()->sectionPlaneCount(), 1); // only the selected cut's face
        QVERIFY(w.selectCutPlane(0));
        QCOMPARE(w.viewport()->sectionPlaneCount(), 1);
        QVERIFY(w.setCutPlaneVisible(0, false));
        QCOMPARE(w.viewport()->sectionPlaneCount(), 0);
        QCOMPARE(w.viewport()->clipPlaneCount(), 2); // both still cut
    }

    void theSelectToolReturnsToTheControls()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        auto* select = w.findChild<QAction*>(QStringLiteral("actionSelectTool"));
        QVERIFY(select);
        QVERIFY(select->isChecked()); // selection is the starting mode
        w.findChild<QAction*>(QStringLiteral("actionWallTool"))->trigger();
        QVERIFY(!select->isChecked());
        select->trigger();
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::None);
        QVERIFY(select->isChecked());
    }

    void aSectionCanBeMadeFromAnObliqueCutPlane()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        w.setTool(kimbim::MainWindow::Tool::Wall);
        w.wallTool()->click({0, 0});
        w.wallTool()->click({5, 0});
        w.wallTool()->finish();
        w.setTool(kimbim::MainWindow::Tool::None);
        QVERIFY(w.addObliqueCut({-1, -2}, {6, -2}, {0, 1}, 30, 0));
        QCOMPARE(w.selectedCutPlane(), 0);
        auto* dock = w.dockLayout()->manager()->findDockWidget(QStringLiteral("cutplanes"));
        QVERIFY(dock);
        auto* make = dock->widget()->findChild<QPushButton*>(QStringLiteral("cutSection"));
        QVERIFY(make && make->isEnabled());
        const int before = w.drawingsPanel()->count();
        make->click();
        QCOMPARE(w.drawingsPanel()->count(), before + 1);
        const QString guid = w.drawingGuid(QStringLiteral("Section 1"));
        QVERIFY(!guid.isEmpty());
        QJsonObject d;
        for (const auto& v : kimbim::PythonEngine::instance().callJson("drawings", {}, nullptr)
                                  .object().value("drawings").toArray())
            if (v.toObject().value("guid").toString() == guid)
                d = v.toObject();
        QCOMPARE(d.value("points").toArray().size(), 2);
        QVERIFY(std::abs(d.value("tilt").toDouble() - 30.0) < 1e-6);
        QVERIFY(w.openDrawing(guid));
        QTRY_VERIFY_WITH_TIMEOUT(w.drawingView(guid)->hasDrawing(), 60000);
        QVERIFY(!w.drawingView(guid)->svg().isEmpty());
    }

    void cutPlanesTravelWithSavedViews()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.addVerticalCut({0, 0}, {0, 5}, {1, 0}, 0));
        QVERIFY(w.setCutPlaneOffset(0, 0.75));
        QVERIFY(w.addObliqueCut({2, 0}, {2, 5}, {-1, 0}, 25, 0));
        QVERIFY(w.setCutPlaneAngle(1, 30));
        QVERIFY(w.saveView(QStringLiteral("Cutaway")));

        QVERIFY(w.removeCutPlane(1));
        QVERIFY(w.removeCutPlane(0));
        QCOMPARE(w.cutPlanes().size(), 0);
        QCOMPARE(w.viewport()->clipPlaneCount(), 0);

        QVERIFY(w.applyView(QStringLiteral("Cutaway")));
        QCOMPARE(w.cutPlanes().size(), 2);
        QCOMPARE(w.cutPlanes().front().kind, kimbim::CutPlane::Kind::Vertical);
        QVERIFY(std::abs(w.cutPlanes().front().offset() - 0.75) < 1e-9);
        QCOMPARE(w.cutPlanes()[1].kind, kimbim::CutPlane::Kind::Oblique);
        QVERIFY(std::abs(w.cutPlanes()[1].angle - 30) < 1e-9);
        QCOMPARE(w.viewport()->clipPlaneCount(), 2);

        // The panel lists them too.
        auto* dock = w.dockLayout()->manager()->findDockWidget(QStringLiteral("cutplanes"));
        QVERIFY(dock);
        QTableWidget* table = dock->widget()->findChild<QTableWidget*>(QStringLiteral("cutPlanesTable"));
        QVERIFY(table);
        QCOMPARE(table->rowCount(), 2);
    }


    void theViewMenuToolsCreateThePlanes()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());

        // Vertical cut: two clicks for the line, a third for the kept side.
        w.findChild<QAction*>(QStringLiteral("actionCutVertical"))->trigger();
        QVERIFY(w.viewport()->isDrawingMode());
        w.viewport()->workPointClicked(QPointF(0, 0), 0.01, Qt::NoModifier);
        w.viewport()->workPointClicked(QPointF(0, 6), 0.01, Qt::NoModifier);
        QCOMPARE(w.cutPlanes().size(), 0);
        w.viewport()->workPointClicked(QPointF(1, 3), 0.01, Qt::NoModifier);
        QCOMPARE(w.cutPlanes().size(), 1);
        QCOMPARE(w.cutPlanes().front().kind, kimbim::CutPlane::Kind::Vertical);
        QVERIFY(w.cutPlanes().front().contains(gp_Pnt(1, 3, 1)));
        QVERIFY(!w.viewport()->isDrawingMode()); // one cut, then back to the controls
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::None);

        // Oblique cut: the same three clicks, tilted about the line (30 deg in quiet mode).
        w.findChild<QAction*>(QStringLiteral("actionCutOblique"))->trigger();
        w.viewport()->workPointClicked(QPointF(3, 0), 0.01, Qt::NoModifier);
        w.viewport()->workPointClicked(QPointF(3, 6), 0.01, Qt::NoModifier);
        w.viewport()->workPointClicked(QPointF(4, 3), 0.01, Qt::NoModifier);
        QCOMPARE(w.cutPlanes().size(), 2);
        QCOMPARE(w.cutPlanes()[1].kind, kimbim::CutPlane::Kind::Oblique);
        QVERIFY(std::abs(w.cutPlanes()[1].angle - 30) < 1e-9);

        // Esc leaves the cut tool.
        w.viewport()->drawingEnded();
        QVERIFY(!w.viewport()->isDrawingMode());
        QCOMPARE(w.tool(), kimbim::MainWindow::Tool::None);

        // Horizontal cut at the plan-cut height (no dialog in quiet mode).
        w.setPlanCutHeight(1.6);
        w.findChild<QAction*>(QStringLiteral("actionCutHorizontal"))->trigger();
        QCOMPARE(w.cutPlanes().size(), 3);
        QCOMPARE(w.cutPlanes()[2].kind, kimbim::CutPlane::Kind::Horizontal);
        QVERIFY(std::abs(w.cutPlanes()[2].point.Z() - (w.levelsBar()->activeElevation() + 1.6)) < 1e-9);

        // From a face: the view's picked point and normal add the plane (kept side as given).
        w.findChild<QAction*>(QStringLiteral("actionCutFromFace"))->trigger();
        w.viewport()->facePicked(2.0, 3.0, 2.0, 0.0, 0.0, 1.0);
        QCOMPARE(w.cutPlanes().size(), 4);
        QCOMPARE(w.cutPlanes()[3].kind, kimbim::CutPlane::Kind::Horizontal);
        QVERIFY(w.cutPlanes()[3].normal.Z() > 0.99);
        w.viewport()->drawingEnded(); // Esc leaves face picking
    }

    void planTabsKeepTheirOwnPlanCut()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.addVerticalCut({0, 0}, {0, 6}, {1, 0}, 0));
        kimbim::Viewport* plan = w.openPlanTab(w.levelsBar()->activeStorey());
        QVERIFY(plan);
        QCOMPARE(plan->clipPlaneCount(), 1); // its plan cut, not the 3D view's user plane
        QCOMPARE(plan->sectionPlaneCount(), 0);
        QCOMPARE(w.cutPlanes().size(), 1); // the 3D view's list is unchanged
    }

    void thePlanCutButtonHasTheCutPlanesFlyout()
    {
        kimbim::MainWindow w(nullptr, true);
        QVERIFY(w.newProject());
        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionCutVertical")));
        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionCutHorizontal")));
        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionCutOblique")));
        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionCutFromFace")));
        QVERIFY(w.findChild<QAction*>(QStringLiteral("actionCutPlanesPanel")));
        QToolButton* button = w.findChild<QToolButton*>(QStringLiteral("planCutButton"));
        QVERIFY(button);
        QVERIFY(button->menu());
        QVERIFY(w.dockLayout()->manager()->findDockWidget(QStringLiteral("cutplanes")));
    }
};

QTEST_MAIN(TestCutPlanes)
#include "test_cut_planes.moc"
