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
        kimcad::ToolPalette p;
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
        for (QToolButton* b : buttons) {
            QLayout* list = b->parentWidget()->layout();
            QVERIFY(list->itemAt(list->indexOf(b))->alignment() & Qt::AlignLeft);
        }
        QVERIFY2(p.sizeHint().width() <= 220, qPrintable(QString::number(p.sizeHint().width())));
        p.setCompact(true);
        for (QToolButton* b : buttons)
            QCOMPARE(b->toolButtonStyle(), Qt::ToolButtonIconOnly);
    }

    void optionsStripShowsOnlyWithAToolAndAField()
    {
        kimcad::ToolOptionsBar bar;
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
        kimcad::StatusStrip s;
        QSignalSpy active(&s, &kimcad::StatusStrip::activeLayerRequested);
        QSignalSpy visible(&s, &kimcad::StatusStrip::layerVisibilityToggled);
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
        QSignalSpy requested(&s, &kimcad::StatusStrip::penRequested);
        s.setPen(26, Qt::red, 0.5);
        QVERIFY(pen->text().startsWith(QStringLiteral("26")));
        pen->click();
        QCOMPARE(requested.count(), 1);
    }
};

QTEST_MAIN(TestToolPalette)
#include "test_tool_palette.moc"
