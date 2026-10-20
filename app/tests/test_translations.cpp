// SPDX-License-Identifier: GPL-3.0-or-later
#include <QtTest>

#include "Translations.h"

class TestTranslations : public QObject {
    Q_OBJECT
private slots:
    void spanishMenusAreTranslated()
    {
        QVERIFY(kimbim::installTranslator(*QCoreApplication::instance(), "es"));
        QCOMPARE(QCoreApplication::translate("kimbim::MainWindow", "&File"), QString("&Archivo"));
        QCOMPARE(QCoreApplication::translate("kimbim::MainWindow", "&Open IFC..."), QString("&Abrir IFC..."));
        QCOMPARE(QCoreApplication::translate("kimbim::MainWindow", "Ready"), QString("Listo"));
    }
    void englishIsTheSourceLanguage()
    {
        QVERIFY(kimbim::installTranslator(*QCoreApplication::instance(), "en"));
    }
    void unknownLanguageIsRejected()
    {
        QVERIFY(!kimbim::installTranslator(*QCoreApplication::instance(), "xx"));
    }
};

QTEST_MAIN(TestTranslations)
#include "test_translations.moc"
