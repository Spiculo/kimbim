// SPDX-License-Identifier: GPL-3.0-or-later
#include <QApplication>
#include <QCommandLineParser>
#include <cstdio>

#include "MainWindow.h"
#include "Preferences.h"
#include "SelfTest.h"
#include "SheetExport.h"
#include "Translations.h"

int main(int argc, char* argv[])
{
    // Exporting a sheet needs no window: run without a display (CI, scripts).
    for (int i = 1; i < argc; ++i)
        if (qstrcmp(argv[i], "--export-sheet") == 0 && qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM"))
            qputenv("QT_QPA_PLATFORM", "offscreen");
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("KIMCAD"));
    QApplication::setOrganizationName(QStringLiteral("KIMCAD")); // QSettings: the window layout (D71)
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
    QCommandLineOption chunk(QStringLiteral("chunk"), QStringLiteral("Self-test: elements per mesh chunk."),
        QStringLiteral("n"), QStringLiteral("1000"));
    parser.addOption(chunk);
    QCommandLineOption boxSelect(QStringLiteral("box-select"), QStringLiteral("Self-test: box-select the whole view."));
    parser.addOption(boxSelect);
    QCommandLineOption popOut(QStringLiteral("pop-out"),
        QStringLiteral("Self-test: move the 3D view to its own window and back; it must keep drawing."));
    parser.addOption(popOut);
    QCommandLineOption benchEdit(QStringLiteral("bench-edit"),
        QStringLiteral("Self-test: time moving a wall of the loaded model (ms per edit and per refresh step)."));
    parser.addOption(benchEdit);
    QCommandLineOption planTab(QStringLiteral("plan-tab"), QStringLiteral("Self-test: with --bench-edit, edit in a plan tab."));
    parser.addOption(planTab);
    QCommandLineOption drawWalls(QStringLiteral("draw-walls"),
        QStringLiteral("Self-test: on a new project, draw walls through these points (\"x,y;x,y;...\", metres)."),
        QStringLiteral("points"));
    parser.addOption(drawWalls);
    QCommandLineOption planView(QStringLiteral("plan-view"), QStringLiteral("Self-test: switch to the plan view."));
    parser.addOption(planView);
    QCommandLineOption linesOnly(QStringLiteral("lines-only"), QStringLiteral("Self-test: lines-only display."));
    parser.addOption(linesOnly);
    QCommandLineOption selectThrough(QStringLiteral("select-through"), QStringLiteral("Self-test: box selection includes hidden elements."));
    parser.addOption(selectThrough);
    QCommandLineOption house(QStringLiteral("house"), QStringLiteral("Self-test: model a small house with the tools."));
    parser.addOption(house);
    QCommandLineOption benchTools(QStringLiteral("bench-tools"), QStringLiteral("Self-test: time tool previews and wall placement."));
    parser.addOption(benchTools);
    QCommandLineOption createDrawings(QStringLiteral("create-drawings"),
        QStringLiteral("Self-test: View > Create floor plans and elevations after loading."));
    parser.addOption(createDrawings);
    QCommandLineOption openDrawing(QStringLiteral("open-drawing"),
        QStringLiteral("Self-test: open this drawing (by name) in its tab and wait for it."), QStringLiteral("name"));
    parser.addOption(openDrawing);
    QCommandLineOption screenshot(QStringLiteral("screenshot"), QStringLiteral("Self-test: save a PNG of the window."),
        QStringLiteral("png"));
    parser.addOption(screenshot);
    QCommandLineOption exportSheet(QStringLiteral("export-sheet"),
        QStringLiteral("Export sheet <number> of the IFC file to <out.pdf|out.svg> and exit (no window)."),
        QStringLiteral("number"));
    parser.addOption(exportSheet);
    parser.addPositionalArgument(QStringLiteral("file"), QStringLiteral("IFC file to open."), QStringLiteral("[file.ifc]"));
    parser.process(app);

    if (parser.isSet(version)) {
        std::printf("KIMCAD %s\n", KIMCAD_VERSION);
        return 0;
    }
    kimcad::Preferences prefs(kimcad::Preferences::defaultPath()); // D72: the language preference
    prefs.load();
    const QString language = parser.isSet(lang) ? parser.value(lang)
        : prefs.language() == QLatin1String("auto") ? QString() : prefs.language();
    kimcad::installTranslator(app, kimcad::pickLanguage(language));

    if (parser.isSet(exportSheet)) {
        const QStringList args = parser.positionalArguments();
        if (args.size() != 2) {
            std::fprintf(stderr, "usage: kimcad-app --export-sheet NUMBER model.ifc out.pdf\n");
            return 2;
        }
        return kimcad::exportSheetCommand(args.at(0), parser.value(exportSheet), args.at(1));
    }

    if (parser.isSet(selfTest)) {
        kimcad::SelfTestOptions options;
        options.path = parser.value(selfTest);
        options.frames = parser.value(frames).toInt();
        options.quitDuringLoad = parser.isSet(quitDuringLoad);
        options.planCut = parser.isSet(planCut) ? parser.value(planCut).toDouble() : -1;
        options.chunkSize = qMax(1, parser.value(chunk).toInt());
        options.boxSelect = parser.isSet(boxSelect);
        options.popOut = parser.isSet(popOut);
        options.benchEdit = parser.isSet(benchEdit);
        options.planTab = parser.isSet(planTab);
        options.drawWalls = parser.value(drawWalls);
        options.planView = parser.isSet(planView);
        options.linesOnly = parser.isSet(linesOnly);
        options.selectThrough = parser.isSet(selectThrough);
        options.house = parser.isSet(house);
        options.benchTools = parser.isSet(benchTools);
        options.screenshot = parser.value(screenshot);
        options.openDrawing = parser.value(openDrawing);
        options.createDrawings = parser.isSet(createDrawings);
        return kimcad::runSelfTest(options);
    }

    kimcad::MainWindow window;
    window.show();
    if (!parser.positionalArguments().isEmpty())
        window.openPath(parser.positionalArguments().first());
    else
        window.offerRecovery();
    return app.exec();
}
