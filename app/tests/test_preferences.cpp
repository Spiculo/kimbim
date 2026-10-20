// SPDX-License-Identifier: GPL-3.0-or-later
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QComboBox>
#include <QCheckBox>
#include <QLabel>
#include <QLineEdit>
#include <QSpinBox>
#include <QtTest>

#include "Preferences.h"
#include "PreferencesDialog.h"

class TestPreferences : public QObject {
    Q_OBJECT
private slots:
    void defaultsWhenThereIsNoFile()
    {
        QTemporaryDir tmp;
        kimbim::Preferences p(tmp.filePath("preferences.json"));
        QVERIFY(p.load());
        QCOMPARE(p.language(), QString("auto"));
        QCOMPARE(p.newViews(), QString("tab"));
        QCOMPARE(p.openIfc(), QString("make_kim"));
        QCOMPARE(p.autoVersion(), QString("off"));
        QCOMPARE(p.autoVersionEvery(), 10);
        QCOMPARE(p.recoveryMinutes(), 5);
        QCOMPARE(p.largeIfcMb(), 5.0);
        QVERIFY(p.templatesFolder().endsWith(QStringLiteral("KimBim Templates")));
        QVERIFY(p.recent().isEmpty());
    }

    void roundTripKeepsUnknownKeys()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath("sub/preferences.json");
        {
            kimbim::Preferences p(path);
            p.setValue("new_views", "window");
            p.setValue("from_a_newer_kimbim", 42);
            p.setLayout(QByteArray("\x01\x02layout", 8));
            p.setWindowGeometry(QByteArray("\x03geometry", 9));
            QVERIFY(p.save());
        }
        kimbim::Preferences q(path);
        QVERIFY(q.load());
        QCOMPARE(q.newViews(), QString("window"));
        QCOMPARE(q.value("from_a_newer_kimbim").toInt(), 42);
        QCOMPARE(q.layout(), QByteArray("\x01\x02layout", 8));
        QCOMPARE(q.windowGeometry(), QByteArray("\x03geometry", 9));
    }

    void aGarbledFileIsKeptAsideAndDefaultsUsed()
    {
        QTemporaryDir tmp;
        const QString path = tmp.filePath("preferences.json");
        QFile f(path);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write("{ not json");
        f.close();
        kimbim::Preferences p(path);
        QVERIFY(!p.load());
        QCOMPARE(p.newViews(), QString("tab"));
        QVERIFY(QFile::exists(path + ".bad"));
    }

    void recentFilesAreMostRecentFirstWithoutDuplicates()
    {
        kimbim::Preferences p;
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
        kimbim::Preferences p;
        p.setValue("new_views", "sideways");
        p.setValue("recovery_minutes", -3);
        p.setValue("auto_version_every", "lots");
        p.setValue("large_ifc_mb", -1);
        QCOMPARE(p.newViews(), QString("tab"));
        QCOMPARE(p.recoveryMinutes(), 5);
        QCOMPARE(p.autoVersionEvery(), 10);
        QCOMPARE(p.largeIfcMb(), 5.0);
        QCOMPARE(p.scrollNavigation(), QString("auto")); // D89
        p.setValue("scroll_navigation", "sideways");
        QCOMPARE(p.scrollNavigation(), QString("auto"));
        QCOMPARE(p.fieldOfView(), 45.0); // D92
        p.setValue("field_of_view", 500);
        QCOMPARE(p.fieldOfView(), 45.0);
        QVERIFY(p.titleBarLevels() && p.titleBarCut() && p.titleBarVersions()); // D92
        p.setValue("title_bar_versions", false);
        QVERIFY(!p.titleBarVersions());
    }

    void theDialogWritesWhatTheUserPicked()
    {
        kimbim::Preferences p;
        kimbim::PreferencesDialog d(p, nullptr);
        QVERIFY(!d.findChild<QLabel*>("restartNote")->isVisibleTo(&d));
        d.findChild<QComboBox*>("language")->setCurrentIndex(2); // auto, en, es
        QVERIFY(d.findChild<QLabel*>("restartNote")->isVisibleTo(&d));
        d.findChild<QComboBox*>("newViews")->setCurrentIndex(1);
        d.findChild<QComboBox*>("openIfc")->setCurrentIndex(1);
        d.findChild<QComboBox*>("autoVersion")->setCurrentIndex(1);
        d.findChild<QSpinBox*>("autoVersionEvery")->setValue(3);
        d.findChild<QSpinBox*>("recoveryMinutes")->setValue(0);
        d.findChild<QSpinBox*>("largeIfcMb")->setValue(20);
        d.findChild<QComboBox*>("scrollNavigation")->setCurrentIndex(2); // auto, zoom, pan (D89)
        d.findChild<QSpinBox*>("fieldOfView")->setValue(60); // D92
        d.findChild<QCheckBox*>("titleBarVersions")->setChecked(false); // D92
        d.findChild<QCheckBox*>("titleBarLevels")->setChecked(false);
        d.findChild<QLineEdit*>("authorName")->setText("Felipe");
        d.findChild<QLineEdit*>("templatesFolder")->setText("Z:/Plantillas");
        d.apply();
        QCOMPARE(p.language(), QString("es"));
        QCOMPARE(p.newViews(), QString("window"));
        QCOMPARE(p.openIfc(), QString("edit_ifc"));
        QCOMPARE(p.autoVersion(), QString("saves"));
        QCOMPARE(p.autoVersionEvery(), 3);
        QCOMPARE(p.recoveryMinutes(), 0);
        QCOMPARE(p.largeIfcMb(), 20.0);
        QCOMPARE(p.scrollNavigation(), QString("pan"));
        QCOMPARE(p.fieldOfView(), 60.0);
        QVERIFY(!p.titleBarLevels() && !p.titleBarVersions());
        QCOMPARE(p.authorName(), QString("Felipe"));
        QCOMPARE(p.templatesFolder(), QString("Z:/Plantillas"));
    }
};

QTEST_MAIN(TestPreferences)
#include "test_preferences.moc"
