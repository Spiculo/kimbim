// SPDX-License-Identifier: GPL-3.0-or-later
#include <QComboBox>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSignalSpy>
#include <QToolButton>
#include <QtTest>

#include "LevelsBar.h"

namespace {

QJsonArray storeys(const char* json)
{
    return QJsonDocument::fromJson(json).array();
}

} // namespace

class TestLevelsBar : public QObject {
    Q_OBJECT
private slots:
    void listsLevelsByElevationAndStartsOnTheLowest()
    {
        kimcad::LevelsBar bar;
        QSignalSpy changed(&bar, &kimcad::LevelsBar::activeStoreyChanged);
        bar.setStoreys(storeys(R"([{"guid":"b","name":"Level 2","elevation":3.0},
                                   {"guid":"a","name":"Level 1","elevation":0.0}])"));
        QCOMPARE(bar.count(), 2);
        QCOMPARE(bar.activeStorey(), QString("a"));
        QCOMPARE(bar.activeElevation(), 0.0);
        QVERIFY(bar.combo()->itemText(0).startsWith("Level 1"));
        QCOMPARE(changed.count(), 1);
        QCOMPARE(changed.last().at(0).toString(), QString("a"));
    }

    void choosingALevelEmitsItsElevation()
    {
        kimcad::LevelsBar bar;
        bar.setStoreys(storeys(R"([{"guid":"a","name":"L1","elevation":0.0},{"guid":"b","name":"L2","elevation":3.0}])"));
        QSignalSpy changed(&bar, &kimcad::LevelsBar::activeStoreyChanged);
        bar.combo()->setCurrentIndex(1);
        QCOMPARE(changed.count(), 1);
        QCOMPARE(changed.last().at(1).toDouble(), 3.0);
        QCOMPARE(bar.activeStorey(), QString("b"));
    }

    void refreshingKeepsTheActiveLevelQuietly()
    {
        kimcad::LevelsBar bar;
        bar.setStoreys(storeys(R"([{"guid":"a","name":"L1","elevation":0.0},{"guid":"b","name":"L2","elevation":3.0}])"));
        bar.setActive("b");
        QSignalSpy changed(&bar, &kimcad::LevelsBar::activeStoreyChanged);
        bar.setStoreys(storeys(R"([{"guid":"a","name":"L1","elevation":0.0},{"guid":"b","name":"L2","elevation":3.0},
                                   {"guid":"c","name":"L3","elevation":6.0}])"));
        QCOMPARE(bar.activeStorey(), QString("b"));
        QCOMPARE(changed.count(), 0);
        bar.setStoreys(storeys(R"([{"guid":"a","name":"L1","elevation":0.0}])")); // b was undone
        QCOMPARE(bar.activeStorey(), QString("a"));
        QCOMPARE(changed.count(), 1);
    }

    void addButtonAsksForANewLevel()
    {
        kimcad::LevelsBar bar;
        QSignalSpy add(&bar, &kimcad::LevelsBar::addLevelRequested);
        bar.addButton()->click();
        QCOMPARE(add.count(), 1);
    }
};

QTEST_MAIN(TestLevelsBar)
#include "test_levels_bar.moc"
