// SPDX-License-Identifier: GPL-3.0-or-later
#include <QLabel>
#include <QMainWindow>
#include <QSignalSpy>
#include <QtTest>

#include <DockManager.h>
#include <DockWidget.h>
#include <DockWidgetTab.h>
#include <ElidingLabel.h>
#include <QApplication>

#include "DockLayout.h"

class TestDockLayout : public QObject {
    Q_OBJECT
private slots:
    void viewsAreKeyedTabsInTheCenter()
    {
        QMainWindow w;
        kimcad::DockLayout layout(&w);
        auto* model = new QLabel("3D");
        layout.addView("3d", "3D", model, false);
        layout.addView("plan:L1", "Level 1 plan", new QLabel("plan"), true);
        QCOMPARE(layout.viewKeys(), QStringList({"3d", "plan:L1"}));
        QCOMPARE(layout.view("3d"), model);
        QCOMPARE(layout.keyOf(model), QString("3d"));
        QSignalSpy current(&layout, &kimcad::DockLayout::currentChanged);
        layout.raise("plan:L1");
        QCOMPARE(layout.current(), QString("plan:L1"));
        QCOMPARE(current.count(), 1);
        layout.setTitle("plan:L1", "Planta 1");
        QCOMPARE(layout.manager()->findDockWidget("plan:L1")->windowTitle(), QString("Planta 1"));
    }

    void the3DViewCannotBeClosedOthersAsk()
    {
        QMainWindow w;
        kimcad::DockLayout layout(&w);
        layout.addView("3d", "3D", new QLabel, false);
        layout.addView("D1", "Section 1", new QLabel, true);
        QVERIFY(!layout.manager()->findDockWidget("3d")->features().testFlag(ads::CDockWidget::DockWidgetClosable));
        QSignalSpy close(&layout, &kimcad::DockLayout::closeRequested);
        layout.manager()->findDockWidget("D1")->requestCloseDockWidget(); // what the tab's x does
        QCOMPARE(close.count(), 1);
        QCOMPARE(close.first().first().toString(), QString("D1"));
        QVERIFY(layout.view("D1")); // the app decides; nothing is closed behind its back
        layout.removeView("D1");
        QVERIFY(!layout.view("D1"));
        QCOMPARE(layout.viewKeys(), QStringList({"3d"}));
    }

    void panelsAreTabbedOnTheRightAndCanBeRaised()
    {
        QMainWindow w;
        kimcad::DockLayout layout(&w);
        layout.addView("3d", "3D", new QLabel, false);
        layout.addPanel("tree", "Model", new QLabel);
        layout.addPanel("properties", "Properties", new QLabel);
        layout.raisePanel("tree");
        QVERIFY(layout.isPanelShown("tree"));
        QVERIFY(!layout.isPanelShown("properties"));
        layout.raisePanel("properties");
        QVERIFY(layout.isPanelShown("properties"));
        QCOMPARE(layout.manager()->findDockWidget("tree")->dockAreaWidget(),
                 layout.manager()->findDockWidget("properties")->dockAreaWidget()); // one tabbed area
    }

    // Owner's screen (dark palette): ADS draws inactive tab titles in palette(dark), unreadable there.
    void inactiveTabTitlesAreReadableOnADarkPalette()
    {
        const QPalette before = QApplication::palette();
        QPalette dark;
        dark.setColor(QPalette::Window, QColor(32, 32, 32));
        dark.setColor(QPalette::WindowText, QColor(230, 230, 230));
        dark.setColor(QPalette::Dark, QColor(20, 20, 20));
        dark.setColor(QPalette::PlaceholderText, QColor(160, 160, 160));
        QApplication::setPalette(dark);
        {
            QMainWindow w;
            kimcad::DockLayout layout(&w);
            layout.addView("3d", "3D", new QLabel, false);
            layout.addPanel("tree", "Model", new QLabel);
            layout.addPanel("properties", "Properties", new QLabel);
            layout.raisePanel("tree");
            w.show();
            QCoreApplication::processEvents();
            auto* title = layout.manager()->findDockWidget("properties")->tabWidget()->findChild<ads::CElidingLabel*>();
            QVERIFY(title);
            title->ensurePolished();
            const QColor text = title->palette().color(QPalette::WindowText);
            QVERIFY2(text.lightnessF() - 0.125 > 0.35, qPrintable(text.name())); // well above the dark background
        }
        QApplication::setPalette(before);
    }

    void layoutRoundTripsAndFallsBack()
    {
        QMainWindow w;
        kimcad::DockLayout layout(&w);
        layout.addView("3d", "3D", new QLabel, false);
        layout.addPanel("tree", "Model", new QLabel);
        layout.captureDefault();
        const QByteArray state = layout.saveLayout();
        QVERIFY(!state.isEmpty());
        QVERIFY(layout.restoreLayout(state));
        QVERIFY(!layout.restoreLayout(QByteArray("not a layout"))); // falls back to the default
        QVERIFY(layout.view("3d"));
    }
};

QTEST_MAIN(TestDockLayout)
#include "test_dock_layout.moc"
