// SPDX-License-Identifier: GPL-3.0-or-later
// D95: cut planes in any direction, wired to the 3D view, the panel and saved views.
#include <QAction>
#include <QDoubleSpinBox>
#include <QJsonObject>
#include <QLabel>
#include <QStandardPaths>
#include <QTableWidget>
#include <QToolButton>
#include <DockManager.h>
#include <QtTest>

#include "CutPlanesPanel.h"
#include "DockLayout.h"
#include "MainWindow.h"
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
