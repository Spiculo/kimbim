// SPDX-License-Identifier: GPL-3.0-or-later
#include <QSignalSpy>
#include <QtTest>

#include "RotateTool.h"

#include <cmath>

using kimcad::RotateTool;

class TestRotateTool : public QObject {
    Q_OBJECT
private slots:
    void centreReferenceTarget()
    {
        RotateTool tool;
        QSignalSpy done(&tool, &RotateTool::rotationFinished);
        tool.click({1, 1});  // centre
        tool.click({3, 1});  // reference direction: 0 degrees
        tool.move({1, 4});   // 90 degrees
        QVERIFY(std::abs(tool.currentAngle() - M_PI / 2) < 1e-9);
        tool.click({1, 4});
        QCOMPARE(done.count(), 1);
        QCOMPARE(done.last().at(0).toPointF(), QPointF(1, 1));
        QVERIFY(std::abs(done.last().at(1).toDouble() - M_PI / 2) < 1e-9);
        QCOMPARE(tool.stage(), 0); // ready again
    }

    void anglesSnapTo15DegreesUnlessFreeAndOrthoTo90()
    {
        RotateTool tool;
        tool.click({0, 0});
        tool.click({1, 0});
        tool.move({std::cos(0.53), std::sin(0.53)}); // 30.4 degrees -> 30
        QVERIFY(std::abs(tool.currentAngle() - M_PI / 6) < 1e-9);
        tool.setOrtho(true);
        tool.move({std::cos(1.2), std::sin(1.2)}); // 68.8 -> 90
        QVERIFY(std::abs(tool.currentAngle() - M_PI / 2) < 1e-9);
    }

    void typedDegreesAndCancel()
    {
        RotateTool tool;
        QSignalSpy done(&tool, &RotateTool::rotationFinished);
        QVERIFY(!tool.typeAngle(45));
        tool.click({0, 0});
        tool.click({1, 0});
        QVERIFY(tool.typeAngle(-45));
        QVERIFY(std::abs(done.last().at(1).toDouble() + M_PI / 4) < 1e-9);
        tool.click({0, 0});
        tool.cancel();
        QCOMPARE(tool.stage(), 0);
    }
};

QTEST_MAIN(TestRotateTool)
#include "test_rotate_tool.moc"
