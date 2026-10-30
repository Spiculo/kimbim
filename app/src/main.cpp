// SPDX-License-Identifier: GPL-3.0-or-later
#include <QApplication>
#include <QCommandLineParser>
#include <cstdio>

#include "MainWindow.h"
#include "Preferences.h"
#include "SelfTest.h"
#include "SheetExport.h"
#include "SnapshotServer.h"
#include "Translations.h"

int main(int argc, char* argv[])
{
    // Exporting a sheet needs no window: run without a display (CI, scripts).
    for (int i = 1; i < argc; ++i)
        if (qstrcmp(argv[i], "--export-sheet") == 0 && qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM"))
            qputenv("QT_QPA_PLATFORM", "offscreen");
    // The 3D view is a native OpenGL window. Without this, Qt turns every one of its siblings (the
    // toolbars, the status strip) into native windows too; those then paint blank or get overdrawn by
    // the 3D surface on scaled displays (owner feedback: invisible status/proposal bars, black gap).
    QApplication::setAttribute(Qt::AA_DontCreateNativeWidgetSiblings);
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("KimBim"));
    QApplication::setOrganizationName(QStringLiteral("KimBim")); // QSettings: the window layout (D71)
    QApplication::setApplicationVersion(QStringLiteral(KIMBIM_VERSION));

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
    QCommandLineOption benchModify(QStringLiteral("bench-modify"),
        QStringLiteral("Self-test: time splitting a wall of the loaded model, trimming it, and undoing both (D80)."));
    parser.addOption(benchModify);
    QCommandLineOption planTab(QStringLiteral("plan-tab"), QStringLiteral("Self-test: with --bench-edit, edit in a plan tab."));
    parser.addOption(planTab);
    QCommandLineOption drawWalls(QStringLiteral("draw-walls"),
        QStringLiteral("Self-test: on a new project, draw walls through these points (\"x,y;x,y;...\", metres)."),
        QStringLiteral("points"));
    parser.addOption(drawWalls);
    QCommandLineOption planView(QStringLiteral("plan-view"), QStringLiteral("Self-test: switch to the plan view."));
    parser.addOption(planView);
    QCommandLineOption underlayOption(QStringLiteral("underlay"),
        QStringLiteral("Self-test: place this DXF, PDF or image on the active level (D85); \"file;opacity;x;y\" also takes those."),
        QStringLiteral("file"));
    parser.addOption(underlayOption);
    QCommandLineOption linesOnly(QStringLiteral("lines-only"), QStringLiteral("Self-test: lines-only display."));
    parser.addOption(linesOnly);
    QCommandLineOption triggerOption(QStringLiteral("trigger"),
        QStringLiteral("Self-test (--real-open): trigger these actions (object names, comma separated) before the screenshot."),
        QStringLiteral("actions"));
    parser.addOption(triggerOption);
    QCommandLineOption perspective(QStringLiteral("perspective"), QStringLiteral("Self-test: perspective camera (D76)."));
    parser.addOption(perspective);
    QCommandLineOption presetView(QStringLiteral("view"),
        QStringLiteral("Self-test: turn to a preset view: Top, Bottom, Front, Back, Left, Right, SW, SE, NE, NW or Home."),
        QStringLiteral("name"));
    parser.addOption(presetView);
    QCommandLineOption cubeClick(QStringLiteral("cube-click"),
        QStringLiteral("Self-test: click the view cube's top face, then its home button."));
    parser.addOption(cubeClick);
    QCommandLineOption scheduleOption(QStringLiteral("schedule"),
        QStringLiteral("Self-test: open this schedule (doors, windows, walls, slabs, columns, beams, rooms) after loading."),
        QStringLiteral("id"));
    parser.addOption(scheduleOption);
    QCommandLineOption findSelect(QStringLiteral("find-select"),
        QStringLiteral("Self-test: open Find & Select and select every element of this IFC class."), QStringLiteral("class"));
    parser.addOption(findSelect);
    QCommandLineOption libraryOption(QStringLiteral("library"),
        QStringLiteral("Self-test: open the Library panel on this object and place it at (1, 1) on the active level."), QStringLiteral("id"));
    parser.addOption(libraryOption);
    QCommandLineOption measureOption(QStringLiteral("measure"),
        QStringLiteral("Self-test: measure through these plan points (\"x,y x,y ...\", metres) in the 3D view."), QStringLiteral("points"));
    parser.addOption(measureOption);
    QCommandLineOption trackerOption(QStringLiteral("tracker"),
        QStringLiteral("Self-test: draw a wall in the plan with a temporary guide and the tracker (D89)."));
    parser.addOption(trackerOption);
    QCommandLineOption levelsDialog(QStringLiteral("levels-dialog"), QStringLiteral("Self-test: open the levels table."));
    parser.addOption(levelsDialog);
    QCommandLineOption checksOption(QStringLiteral("checks"),
        QStringLiteral("Self-test: run these checks (schema, ids, clash, model; comma separated) from the Checks panel; "
                       "clash adds a walls x slabs set. Clicks the first issue."), QStringLiteral("list"));
    parser.addOption(checksOption);
    QCommandLineOption consoleOption(QStringLiteral("console"),
        QStringLiteral("Self-test: open the Python console and run this code."), QStringLiteral("code"));
    parser.addOption(consoleOption);
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
    QCommandLineOption windowSize(QStringLiteral("window-size"), QStringLiteral("Self-test: the window's size."),
        QStringLiteral("WxH"));
    parser.addOption(windowSize);
    QCommandLineOption maximized(QStringLiteral("maximized"), QStringLiteral("Self-test: show the window maximized."));
    parser.addOption(maximized);
    QCommandLineOption realOpen(QStringLiteral("real-open"),
        QStringLiteral("Self-test: open the file as a person does (preferences, saved layout, questions) and check the window's size."));
    parser.addOption(realOpen);
    QCommandLineOption answer(QStringLiteral("answer"),
        QStringLiteral("Self-test: with --real-open, click the button containing this text when asked (repeatable)."), QStringLiteral("text"));
    parser.addOption(answer);
    QCommandLineOption minimizeOption(QStringLiteral("minimize"),
        QStringLiteral("Self-test: with --real-open, minimize the window while the model loads and restore it after."));
    parser.addOption(minimizeOption);
    QCommandLineOption exportSheet(QStringLiteral("export-sheet"),
        QStringLiteral("Export sheet <number> of the IFC file to <out.pdf|out.svg|out.dxf> and exit (no window)."),
        QStringLiteral("number"));
    parser.addOption(exportSheet);
    QCommandLineOption snapshotServer(QStringLiteral("snapshot-server"),
        QStringLiteral("Agent tools (D102): render snapshots for JSON requests read from stdin, one per line, "
                       "without showing a window; exits at the end of input."));
    parser.addOption(snapshotServer);
    parser.addPositionalArgument(QStringLiteral("file"), QStringLiteral("IFC file to open."), QStringLiteral("[file.ifc]"));
    parser.process(app);

    if (parser.isSet(version)) {
        std::printf("KimBim %s\n", KIMBIM_VERSION);
        return 0;
    }
    kimbim::Preferences prefs(kimbim::Preferences::defaultPath()); // D72: the language preference
    prefs.load();
    const QString language = parser.isSet(lang) ? parser.value(lang)
        : prefs.language() == QLatin1String("auto") ? QString() : prefs.language();
    kimbim::installTranslator(app, kimbim::pickLanguage(language));

    if (parser.isSet(exportSheet)) {
        const QStringList args = parser.positionalArguments();
        if (args.size() != 2) {
            std::fprintf(stderr, "usage: kimbim-app --export-sheet NUMBER model.ifc out.pdf\n");
            return 2;
        }
        return kimbim::exportSheetCommand(args.at(0), parser.value(exportSheet), args.at(1));
    }

    if (parser.isSet(snapshotServer))
        return kimbim::snapshotServerCommand();

    if (parser.isSet(selfTest)) {
        kimbim::SelfTestOptions options;
        options.path = parser.value(selfTest);
        options.frames = parser.value(frames).toInt();
        options.quitDuringLoad = parser.isSet(quitDuringLoad);
        options.planCut = parser.isSet(planCut) ? parser.value(planCut).toDouble() : -1;
        options.chunkSize = qMax(1, parser.value(chunk).toInt());
        options.boxSelect = parser.isSet(boxSelect);
        options.popOut = parser.isSet(popOut);
        options.benchEdit = parser.isSet(benchEdit);
        options.planTab = parser.isSet(planTab);
        options.benchModify = parser.isSet(benchModify);
        options.drawWalls = parser.value(drawWalls);
        options.planView = parser.isSet(planView);
        options.underlay = parser.value(underlayOption);
        options.linesOnly = parser.isSet(linesOnly);
        options.trigger = parser.value(triggerOption).split(QLatin1Char(','), Qt::SkipEmptyParts);
        options.perspective = parser.isSet(perspective);
        options.view = parser.value(presetView);
        options.cubeClick = parser.isSet(cubeClick);
        options.schedule = parser.value(scheduleOption);
        options.findSelect = parser.value(findSelect);
        options.library = parser.value(libraryOption);
        options.measure = parser.value(measureOption);
        options.tracker = parser.isSet(trackerOption);
        options.levelsDialog = parser.isSet(levelsDialog);
        options.checks = parser.value(checksOption);
        options.console = parser.value(consoleOption);
        options.selectThrough = parser.isSet(selectThrough);
        options.house = parser.isSet(house);
        options.benchTools = parser.isSet(benchTools);
        options.screenshot = parser.value(screenshot);
        if (const QStringList wh = parser.value(windowSize).split(QLatin1Char('x')); wh.size() == 2)
            options.windowSize = QSize(wh[0].toInt(), wh[1].toInt());
        options.maximized = parser.isSet(maximized);
        options.realOpen = parser.isSet(realOpen);
        options.answers = parser.values(answer);
        options.minimize = parser.isSet(minimizeOption);
        options.openDrawing = parser.value(openDrawing);
        options.createDrawings = parser.isSet(createDrawings);
        return kimbim::runSelfTest(options);
    }

    kimbim::MainWindow window;
    window.show();
    if (!parser.positionalArguments().isEmpty())
        window.openPath(parser.positionalArguments().first());
    else
        window.offerRecovery();
    return app.exec();
}
