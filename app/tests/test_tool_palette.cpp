// SPDX-License-Identifier: GPL-3.0-or-later
// D71: the left tool palette, the tool options strip and the bottom bar.
#include <QAction>
#include <QToolButton>
#include <QtTest>

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
        p.setCompact(true);
        for (QToolButton* b : buttons)
            QCOMPARE(b->toolButtonStyle(), Qt::ToolButtonIconOnly);
    }
};

QTEST_MAIN(TestToolPalette)
#include "test_tool_palette.moc"
