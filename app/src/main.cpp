// SPDX-License-Identifier: GPL-3.0-or-later
#include <QApplication>
#include <QCommandLineParser>
#include <cstdio>

#include "MainWindow.h"
#include "SelfTest.h"
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
    QCommandLineOption selfTest(QStringLiteral("self-test"),
        QStringLiteral("Open an IFC (or :fixture:), load it, measure, print JSON and exit."), QStringLiteral("ifc"));
    QCommandLineOption frames(QStringLiteral("frames"), QStringLiteral("Self-test: orbit frames to measure."),
        QStringLiteral("n"), QStringLiteral("60"));
    QCommandLineOption quitDuringLoad(QStringLiteral("quit-during-load"),
        QStringLiteral("Self-test: stop after the first chunk (shutdown while loading)."));
    QCommandLineOption planCut(QStringLiteral("plan-cut"), QStringLiteral("Self-test: plan cut height."),
        QStringLiteral("height"));
    parser.addOption(version);
    parser.addOption(lang);
    parser.addOption(selfTest);
    parser.addOption(frames);
    parser.addOption(quitDuringLoad);
    parser.addOption(planCut);
    parser.process(app);

    if (parser.isSet(version)) {
        std::printf("KIMCAD %s\n", KIMCAD_VERSION);
        return 0;
    }
    kimcad::installTranslator(app, kimcad::pickLanguage(parser.value(lang)));

    if (parser.isSet(selfTest)) {
        kimcad::SelfTestOptions options;
        options.path = parser.value(selfTest);
        options.frames = parser.value(frames).toInt();
        options.quitDuringLoad = parser.isSet(quitDuringLoad);
        options.planCut = parser.isSet(planCut) ? parser.value(planCut).toDouble() : -1;
        return kimcad::runSelfTest(options);
    }

    kimcad::MainWindow window;
    window.show();
    return app.exec();
}
