// SPDX-License-Identifier: GPL-3.0-or-later
// D71: the left tool palette, the tool options strip and the bottom bar.
#include <QAction>
#include <QComboBox>
#include <QLayout>
#include <QLineEdit>
#include <QMenu>
#include <QSignalSpy>
#include <QToolButton>
#include <QtTest>

#include "StatusStrip.h"
#include "ToolOptionsBar.h"
#include "ToolPalette.h"

class TestToolPalette : public QObject {
    Q_OBJECT
private slots:
    void groupsHoldButtonsForTheirActions()
    {
        kimbim::ToolPalette p;
        QAction wall("Wall"), slab("Slab"), text("Text");
        p.addGroup("3d", "3D", {&wall, &slab});
        p.addGroup("plane", "Plane", {&text});
        QCOMPARE(p.groups(), QStringList({"3d", "plane"}));
        QCOMPARE(p.actions("3d"), QList<QAction*>({&wall, &slab}));
        const auto buttons = p.findChildren<QToolButton*>(QStringLiteral("toolButton"));
        QCOMPARE(buttons.size(), 3);
        QCOMPARE(buttons.first()->defaultAction(), &wall);
        p.setCollapsed("3d", true);
        QVERIFY(p.isCollapsed("3d") && !p.isCollapsed("plane"));
        QVERIFY(buttons.first()->isHidden() || !buttons.first()->parentWidget()->isVisibleTo(&p));
        // Owner's screen: buttons read left to right (icon, then label), and the column stays narrow.
        for (QToolButton* b : buttons)
            QCOMPARE(b->toolButtonStyle(), Qt::ToolButtonTextBesideIcon);
        QVERIFY2(p.sizeHint().width() <= 220, qPrintable(QString::number(p.sizeHint().width())));
        p.setCompact(true);
        for (QToolButton* b : buttons)
            QCOMPARE(b->toolButtonStyle(), Qt::ToolButtonIconOnly);
    }

    // D90: an icon grid whose columns follow the width; flyouts; every tool gets an icon; three looks.
    void gridFlyoutsAndLooks()
    {
        kimbim::ToolPalette p;
        QAction dim("Dimension"), angle("Angle dimension"), radius("Radius"), text("Text"), odd("Odd");
        dim.setObjectName("actionDimensionTool");
        angle.setObjectName("actionAngleDimensionTool");
        radius.setObjectName("actionRadialDimensionTool");
        text.setObjectName("actionTextTool");
        odd.setObjectName("actionNoSuchIconTool");
        for (QAction* a : {&dim, &angle, &radius, &text, &odd})
            a->setCheckable(true);
        p.addGroup("plane", "Plane", {&dim, &text, &angle, &radius, &odd});
        p.addFlyout("plane", {&dim, &angle, &radius});
        QCOMPARE(p.actions("plane"), QList<QAction*>({&dim, &text, &angle, &radius, &odd})); // all, as given
        const QList<QToolButton*> buttons = p.buttons("plane");
        QCOMPARE(buttons.size(), 3); // the flyout where Dimension was, then Text, then Odd
        QCOMPARE(buttons.at(0)->defaultAction(), &dim);
        QVERIFY(buttons.at(0)->menu() && buttons.at(0)->menu()->actions().size() == 3);
        QCOMPARE(p.buttonFor(&angle), buttons.at(0));
        QCOMPARE(kimbim::ToolPalette::iconName(&angle), QString("tool-angle-dimension"));
        QVERIFY(!dim.icon().isNull() && !text.icon().isNull()); // from :/icons/tool-*.svg
        for (qreal dpr : {1.0, 1.25, 2.0}) {
            const QPixmap pm = text.icon().pixmap(QSize(16, 16), dpr);
            QVERIFY(!pm.isNull());
            QCOMPARE(pm.width(), qRound(16 * dpr));
            QImage img = pm.toImage();
            bool inked = false;
            for (int y = 0; y < img.height() && !inked; ++y)
                for (int x = 0; x < img.width() && !inked; ++x)
                    inked = qAlpha(img.pixel(x, y)) > 0;
            QVERIFY(inked);
        }
        angle.trigger(); // the last one used shows on the flyout
        QCOMPARE(buttons.at(0)->defaultAction(), &angle);
        radius.setChecked(true); // also when chosen by its shortcut
        QCOMPARE(buttons.at(0)->defaultAction(), &radius);

        p.resize(200, 600);
        p.show();
        QCoreApplication::processEvents();
        QCOMPARE(p.columns(), 2); // icons and labels: two columns at 200 px
        p.setMode(kimbim::ToolPalette::Mode::Icons);
        QVERIFY(p.columns() >= 5);
        p.setMode(kimbim::ToolPalette::Mode::List);
        QCOMPARE(p.columns(), 1);
        QCOMPARE(kimbim::ToolPalette::modeFromKey(kimbim::ToolPalette::modeKey(p.mode())), p.mode());
        QVERIFY(p.contextMenu()->findChild<QAction*>() || !p.contextMenu()->actions().isEmpty());
    }

    void optionsStripShowsOnlyWithAToolAndAField()
    {
        kimbim::ToolOptionsBar bar;
        auto* height = new QLineEdit;
        bar.addField(height);
        bar.show();
        bar.setActive(false);
        QVERIFY(bar.isHidden());
        bar.setActive(true);
        QVERIFY(!bar.isHidden());
        height->hide();
        bar.setActive(true);
        QVERIFY(bar.isHidden()); // nothing to show
    }

    void statusStripShowsLayersZoomSelectionAndMessages()
    {
        kimbim::StatusStrip s;
        QSignalSpy active(&s, &kimbim::StatusStrip::activeLayerRequested);
        QSignalSpy visible(&s, &kimbim::StatusStrip::layerVisibilityToggled);
        s.setLayers({"A-WALL", "A-DOOR", "A-ANNO"}, "A-WALL", {"A-ANNO"});
        QCOMPARE(s.layersText(), QString("2/3"));
        auto* combo = s.findChild<QComboBox*>(QStringLiteral("activeLayer"));
        QCOMPARE(combo->currentText(), QString("A-WALL"));
        emit combo->activated(combo->findText("A-DOOR"));
        QCOMPARE(active.count(), 1);
        QCOMPARE(active.first().first().toString(), QString("A-DOOR"));
        QAction* anno = s.findChild<QToolButton*>(QStringLiteral("visibleLayers"))->menu()->actions().at(2);
        QVERIFY(!anno->isChecked());
        anno->setChecked(true);
        QCOMPARE(visible.count(), 1);
        s.setZoom(150.0);
        QCOMPARE(s.zoomText(), QString("150%"));
        s.setZoom(-1);
        QCOMPARE(s.zoomText(), QString());
        s.setSelection("2 walls");
        QCOMPARE(s.selectionText(), QString("2 walls"));
        s.showMessage("Wall: click the start point");
        QCOMPARE(s.message(), QString("Wall: click the start point"));
        s.clearMessage();
        QVERIFY(s.message().isEmpty());
        auto* pen = s.findChild<QToolButton*>(QStringLiteral("penButton"));
        QVERIFY(pen->isEnabled()); // D73: the current pen
        QSignalSpy requested(&s, &kimbim::StatusStrip::penRequested);
        s.setPen(26, Qt::red, 0.5);
        QVERIFY(pen->text().startsWith(QStringLiteral("26")));
        pen->click();
        QCOMPARE(requested.count(), 1);
    }
};

QTEST_MAIN(TestToolPalette)
#include "test_tool_palette.moc"
