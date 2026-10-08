// SPDX-License-Identifier: GPL-3.0-or-later
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QtTest>

#include "Preferences.h"

class TestPreferences : public QObject {
    Q_OBJECT
private slots:
    void defaultsWhenThereIsNoFile()
    {
        QTemporaryDir tmp;
        kimcad::Preferences p(tmp.filePath("preferences.json"));
        QVERIFY(p.load());
        QCOMPARE(p.language(), QString("auto"));
        QCOMPARE(p.newViews(), QString("tab"));
        QCOMPARE(p.openIfc(), QString("make_kim"));
        QCOMPARE(p.autoVersion(), QString("off"));
        QCOMPARE(p.autoVersionEvery(), 10);
        QCOMPARE(p.recoveryMinutes(), 5);
        QVERIFY(p.templatesFolder().endsWith(QStringLiteral("KIMCAD Templates")));
        QVERIFY(p.recent().isEmpty());
    }

    void roundTripKeepsUnknownKeys()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath("sub/preferences.json");
        {
            kimcad::Preferences p(path);
            p.setValue("new_views", "window");
            p.setValue("from_a_newer_kimcad", 42);
            p.setLayout(QByteArray("\x01\x02layout", 8));
            QVERIFY(p.save());
        }
        kimcad::Preferences q(path);
        QVERIFY(q.load());
        QCOMPARE(q.newViews(), QString("window"));
        QCOMPARE(q.value("from_a_newer_kimcad").toInt(), 42);
        QCOMPARE(q.layout(), QByteArray("\x01\x02layout", 8));
    }

    void aGarbledFileIsKeptAsideAndDefaultsUsed()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath("preferences.json");
        QFile f(path);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write("{ not json");
        f.close();
        kimcad::Preferences p(path);
        QVERIFY(!p.load());
        QCOMPARE(p.newViews(), QString("tab"));
        QVERIFY(QFile::exists(path + ".bad"));
    }

    void recentFilesAreMostRecentFirstWithoutDuplicates()
    {
        kimcad::Preferences p;
        for (int i = 0; i < 12; ++i)
            p.addRecent(QStringLiteral("C:/p/%1.kim").arg(i));
        p.addRecent("C:/p/5.kim");
        const QStringList r = p.recent();
        QCOMPARE(r.size(), 10);
        QCOMPARE(r.first(), QString("C:/p/5.kim"));
        QCOMPARE(r.count("C:/p/5.kim"), 1);
        QVERIFY(!p.save()); // in memory only
    }

    void badValuesFallBackToDefaults()
    {
        kimcad::Preferences p;
        p.setValue("new_views", "sideways");
        p.setValue("recovery_minutes", -3);
        p.setValue("auto_version_every", "lots");
        QCOMPARE(p.newViews(), QString("tab"));
        QCOMPARE(p.recoveryMinutes(), 5);
        QCOMPARE(p.autoVersionEvery(), 10);
    }
};

QTEST_MAIN(TestPreferences)
#include "test_preferences.moc"
