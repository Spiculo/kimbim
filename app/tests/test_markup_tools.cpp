// SPDX-License-Identifier: GPL-3.0-or-later
// D87: the annotation pack in the main window: a tag placed by clicking a wall, Tag all, a north
// arrow, an angle dimension and a revision cloud drawn through the tools.
#include <QAction>
#include <QComboBox>
#include <QLineEdit>
#include <QStandardPaths>
#include <QToolButton>
#include <QtTest>

#include "MainWindow.h"
#include "Viewport.h"
#include "WallTool.h"

using kimcad::MainWindow;

class TestMarkupTools : public QObject {
    Q_OBJECT
private slots:
    void initTestCase() { QStandardPaths::setTestModeEnabled(true); }

    void tagsAndSymbolsThroughTheTools()
    {
        MainWindow w(nullptr, /*quiet=*/true);
        QVERIFY(w.newProject());
        w.findChild<QAction*>(QStringLiteral("actionPlanView"))->trigger();
        kimcad::Viewport* v = w.viewport();
        w.setTool(MainWindow::Tool::Wall);
        QVERIFY(w.createWall({QPointF(0, 0), QPointF(6, 0), {}, {}}));
        QVERIFY(w.createWall({QPointF(0, 4), QPointF(6, 4), {}, {}}));
        QVERIFY(w.createWall({QPointF(8, 0), QPointF(8, 4), {}, {}}));
        w.setTool(MainWindow::Tool::None);
        const int before = v->annotationCount();

        // Tag: a click on a wall tags it with the wall style (its type in a box).
        w.setTool(MainWindow::Tool::Tag);
        auto* style = w.findChild<QComboBox*>(QStringLiteral("tagStyle"));
        QVERIFY(style && style->isVisibleTo(&w) && style->findData(QStringLiteral("door")) > 0);
        emit v->workPointClicked(QPointF(3, 0.05), 0.1, Qt::NoModifier);
        QCOMPARE(v->annotationCount() - before, 1);
        // With the leader: the element, then where the tag goes.
        w.findChild<QToolButton*>(QStringLiteral("tagLeader"))->setChecked(true);
        emit v->workPointClicked(QPointF(3, 4.02), 0.1, Qt::NoModifier);
        QCOMPARE(v->annotationCount() - before, 1); // waiting for the place
        emit v->workPointClicked(QPointF(4, 5.5), 0.1, Qt::NoModifier);
        QCOMPARE(v->annotationCount() - before, 2);
        QVERIFY(v->annotationPoints(v->annotationGuids().last()).first() == QPointF(4, 5.5));
        emit v->workPointClicked(QPointF(30, 30), 0.1, Qt::NoModifier); // nothing there
        QCOMPARE(v->annotationCount() - before, 2);
        w.setTool(MainWindow::Tool::None);

        // Tag all: the one wall left; again, nothing.
        w.findChild<QAction*>(QStringLiteral("actionTagAll"))->trigger();
        QCOMPARE(v->annotationCount() - before, 3);
        QCOMPARE(w.tagAll(), 0);

        // A north arrow (one click), an angle (four), a revision cloud (drawn like a fill).
        w.setTool(MainWindow::Tool::NorthArrow);
        emit v->workPointClicked(QPointF(12, 2), 0.01, Qt::NoModifier);
        QCOMPARE(v->annotationCount() - before, 4);
        w.setTool(MainWindow::Tool::AngleDimension);
        for (const QPointF p : {QPointF(20, 0), QPointF(22, 0), QPointF(20, 2), QPointF(21, 1)})
            emit v->workPointClicked(p, 0.001, Qt::NoModifier);
        QCOMPARE(v->annotationCount() - before, 5);
        QVERIFY(v->annotationTexts().contains(QString()));
        w.setTool(MainWindow::Tool::Cloud);
        w.findChild<QLineEdit*>(QStringLiteral("markupText"))->setText(QStringLiteral("B"));
        for (const QPointF p : {QPointF(0, -5), QPointF(4, -5), QPointF(4, -2), QPointF(0, -5)})
            emit v->workPointClicked(p, 0.01, Qt::NoModifier);
        QCOMPARE(v->annotationCount() - before, 6);
        QVERIFY(v->annotationTexts().contains(QStringLiteral("B")));
        w.setTool(MainWindow::Tool::None);
        // Symbols belong to the plan.
        v->set3DView();
        QCOMPARE(v->annotationCount() - before, 0);
    }
};

QTEST_MAIN(TestMarkupTools)
#include "test_markup_tools.moc"
