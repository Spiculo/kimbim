// SPDX-License-Identifier: GPL-3.0-or-later
#include <QApplication>
#include <QCommandLineParser>
#include <cstdio>

#include "MainWindow.h"
#include "Translations.h"

int main(int argc, char* argv[])
{
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("KIMCAD"));
    QApplication::setApplicationVersion(QStringLiteral(KIMCAD_VERSION));

    QCommandLineParser parser;
    parser.addHelpOption();
    QCommandLineOption version(QStringLiteral("version"), QStringLiteral("Print the version and exit."));
    QCommandLineOption lang(QStringLiteral("lang"), QStringLiteral("User interface language: en or es."),
        QStringLiteral("lang"));
    parser.addOption(version);
    parser.addOption(lang);
    parser.process(app);

    if (parser.isSet(version)) {
        std::printf("KIMCAD %s\n", KIMCAD_VERSION);
        return 0;
    }
    kimcad::installTranslator(app, kimcad::pickLanguage(parser.value(lang)));

    kimcad::MainWindow window;
    window.show();
    return app.exec();
}
