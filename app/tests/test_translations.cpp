// SPDX-License-Identifier: GPL-3.0-or-later
#include <QtTest>

#include "Translations.h"

class TestTranslations : public QObject {
    Q_OBJECT
private slots:
    void spanishMenusAreTranslated()
    {
        QVERIFY(kimcad::installTranslator(*QCoreApplication::instance(), "es"));
        QCOMPARE(QCoreApplication::translate("kimcad::MainWindow", "&File"), QString("&Archivo"));
        QCOMPARE(QCoreApplication::translate("kimcad::MainWindow", "&Open IFC..."), QString("&Abrir IFC..."));
        QCOMPARE(QCoreApplication::translate("kimcad::MainWindow", "Ready"), QString("Listo"));
    }
    void englishIsTheSourceLanguage()
    {
        QVERIFY(kimcad::installTranslator(*QCoreApplication::instance(), "en"));
    }
    void unknownLanguageIsRejected()
    {
        QVERIFY(!kimcad::installTranslator(*QCoreApplication::instance(), "xx"));
    }
};

QTEST_MAIN(TestTranslations)
#include "test_translations.moc"
