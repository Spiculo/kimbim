// SPDX-License-Identifier: GPL-3.0-or-later
#define _USE_MATH_DEFINES
#include "SelfTest.h"

#include <QAction>
#include <QApplication>
#include <QJsonArray>
#include <QScreen>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QTimer>

#include <cstdio>

#include "DrawingView.h"
#include "MainWindow.h"
#include "HostTool.h"
#include "TwoPointTool.h"
#include "WallTool.h"

#include <QRegularExpression>

#include <cmath>
#include <utility>

#include "ModelTreePanel.h"
#include "PythonEngine.h"
#include "Viewport.h"

namespace kimcad {

namespace {

int report(const QJsonObject& result)
{
    std::printf("%s\n", QJsonDocument(result).toJson(QJsonDocument::Compact).constData());
    std::fflush(stdout);
    return result.value("ok").toBool() ? 0 : 1;
}

int fail(const QString& error)
{
    return report(QJsonObject{{"ok", false}, {"error", error}});
}

} // namespace

// Drives the real MainWindow (background loader thread, progressive batches), then measures.
static void takeScreenshots(MainWindow& window, const QString& path, QJsonObject* result)
{
    window.viewport()->fitAll();
    for (int i = 0; i < 10; ++i)
        QApplication::processEvents();
    // grabWindow captures the composited screen, including the OpenGL viewport.
    const QPixmap shot = window.screen()->grabWindow(window.winId());
    result->insert(QStringLiteral("screenshot"), shot.save(path) ? path : QString());
    // The window grab needs a composited screen (blank when the screen is locked or off);
    // the OCCT dump renders the 3D view directly and always works.
    QString viewportShot = path;
    viewportShot.replace(QStringLiteral(".png"), QStringLiteral("-viewport.png"));
    result->insert(QStringLiteral("viewport_screenshot"), window.viewport()->dumpImage(viewportShot) ? viewportShot : QString());
}

// Slice 4: draw a wall polyline on a new project through the real wall tool (plane points, no mouse).
static int runDrawWalls(const SelfTestOptions& options)
{
    MainWindow window(nullptr, /*quiet=*/true, options.chunkSize);
    window.show();
    QApplication::processEvents();
    if (!window.newProject())
        return fail(QStringLiteral("new project failed"));
    window.setWallToolActive(true);
    QVector<QPointF> points;
    for (const QString& pair : options.drawWalls.split(QRegularExpression(QStringLiteral("[; ]")), Qt::SkipEmptyParts)) {
        const QStringList xy = pair.split(QLatin1Char(','));
        if (xy.size() != 2)
            return fail(QStringLiteral("bad point: ") + pair);
        points << QPointF(xy[0].toDouble(), xy[1].toDouble());
    }
    window.wallTool()->setTolerance(0.05);
    for (const QPointF& p : points) {
        window.wallTool()->move(p);
        window.wallTool()->click(p);
        QApplication::processEvents();
    }
    window.wallTool()->finish();
    window.setWallToolActive(false);
    window.viewport()->fitAll();
    QApplication::processEvents();
    auto count = [](const char* cls) {
        QString error;
        return PythonEngine::instance().callJson("count_entities", {QString::fromLatin1(cls)}, &error)
            .object().value("count").toInt();
    };
    const int walls = count("IfcWall");
    const int joins = count("IfcRelConnectsPathElements");
    const int elements = window.viewport()->elementCount();
    QJsonObject result{{"ok", walls == int(points.size()) - 1 && elements == walls && window.isDirty()},
        {"walls", walls}, {"joins", joins}, {"elements", elements}};
    if (!options.screenshot.isEmpty())
        takeScreenshots(window, options.screenshot, &result);
    window.close();
    return report(result);
}

// Architect feedback: how long a preview update and a wall placement take in the real window.
static int runBenchTools(const SelfTestOptions& options)
{
    MainWindow window(nullptr, /*quiet=*/true, options.chunkSize);
    window.show();
    QApplication::processEvents();
    if (!window.newProject())
        return fail(QStringLiteral("new project failed"));
    window.setTool(MainWindow::Tool::Wall);
    window.wallTool()->setTolerance(0.05);
    QElapsedTimer t;
    double moveMs = 0, clickMs = 0;
    int moves = 0, clicks = 0;
    window.wallTool()->click(QPointF(0, 0));
    for (int i = 1; i <= 12; ++i) {
        for (int k = 0; k < 10; ++k) { // the mouse travelling to the next point
            t.start();
            window.wallTool()->move(QPointF(i * 2.0 - 1.0 + k * 0.1, (i % 2) * 0.5 + k * 0.03));
            QApplication::processEvents();
            moveMs += double(t.nsecsElapsed()) / 1e6;
            ++moves;
        }
        t.start();
        window.wallTool()->click(QPointF(i * 2.0, (i % 2) * 3.0));
        QApplication::processEvents();
        clickMs += double(t.nsecsElapsed()) / 1e6;
        ++clicks;
    }
    window.setTool(MainWindow::Tool::None);
    QJsonObject steps;
    for (auto it = window.timings().constBegin(); it != window.timings().constEnd(); ++it)
        steps.insert(it.key(), it.value() / clicks);
    QJsonObject result{{"ok", true}, {"move_ms", moveMs / moves}, {"click_ms", clickMs / clicks}, {"steps_ms", steps},
        {"walls", window.viewport()->elementCount()}};
    window.close();
    return report(result);
}

// Slice 5: a small house through the real tools: 8 x 6 m walls, slab from walls, door and window.
static int runHouse(const SelfTestOptions& options)
{
    MainWindow window(nullptr, /*quiet=*/true, options.chunkSize);
    window.show();
    QApplication::processEvents();
    if (!window.newProject())
        return fail(QStringLiteral("new project failed"));
    window.setTool(MainWindow::Tool::Wall);
    window.wallTool()->setTolerance(0.05);
    for (const QPointF& p : {QPointF(0, 0), QPointF(8, 0), QPointF(8, 6), QPointF(0, 6), QPointF(0, 0)}) {
        window.wallTool()->move(p);
        window.wallTool()->click(p);
    }
    window.setTool(MainWindow::Tool::None);
    QStringList walls;
    for (const QString& g : window.viewport()->guids())
        walls << g;
    window.slabFromWalls(walls);
    window.setTool(MainWindow::Tool::Door);
    window.hostTool()->setTolerance(0.05);
    window.hostTool()->click(QPointF(4.0, 0.0));
    window.setTool(MainWindow::Tool::Window);
    window.hostTool()->setTolerance(0.05);
    window.hostTool()->click(QPointF(4.0, 6.0));
    // Slice 6: grid lines on the wall axes, a column and a beam on the middle line, then move and
    // rotate everything (joined walls stay joined, doors and windows go along).
    window.setTool(MainWindow::Tool::Grid);
    for (const auto& [a, b] : {std::pair{QPointF(0, -1), QPointF(0, 7)}, std::pair{QPointF(8, -1), QPointF(8, 7)},
             std::pair{QPointF(-1, 0), QPointF(9, 0)}, std::pair{QPointF(-1, 6), QPointF(9, 6)}}) {
        window.twoPointTool()->click(a);
        window.twoPointTool()->click(b);
    }
    window.setTool(MainWindow::Tool::Column);
    window.columnAt(QPointF(4.0, 3.0));
    window.setTool(MainWindow::Tool::Beam);
    window.twoPointTool()->click(QPointF(0.0, 3.0));
    window.twoPointTool()->click(QPointF(8.0, 3.0));
    window.setTool(MainWindow::Tool::None);
    const int gridLines = window.gridLineCount();
    window.setSelection(window.viewport()->guids());
    const bool moved = window.moveSelection(QPointF(1.0, 0.0));
    const bool rotated = window.rotateSelection(QPointF(0.0, 0.0), M_PI / 2);
    window.viewport()->fitAll();
    QApplication::processEvents();
    auto count = [](const char* cls) {
        QString error;
        return PythonEngine::instance().callJson("count_entities", {QString::fromLatin1(cls)}, &error)
            .object().value("count").toInt();
    };
    const int nWalls = count("IfcWall"), slabs = count("IfcSlab"), doors = count("IfcDoor"), windows = count("IfcWindow"),
              openings = count("IfcOpeningElement"), columns = count("IfcColumn"), beams = count("IfcBeam"),
              joins = count("IfcRelConnectsPathElements"), elements = window.viewport()->elementCount();
    QJsonObject result{{"ok", nWalls == 4 && slabs == 1 && doors == 1 && windows == 1 && openings == 2 && columns == 1
                                  && beams == 1 && gridLines == 4 && joins == 4 && moved && rotated && elements == 9},
        {"walls", nWalls}, {"slabs", slabs}, {"doors", doors}, {"windows", windows}, {"openings", openings},
        {"columns", columns}, {"beams", beams}, {"grid", gridLines}, {"joins", joins}, {"elements", elements}};
    if (!options.screenshot.isEmpty())
        takeScreenshots(window, options.screenshot, &result);
    window.close();
    return report(result);
}

int runSelfTest(const SelfTestOptions& options)
{
    QString error;
    if (!PythonEngine::instance().start(&error))
        return fail(error);
    if (options.benchTools)
        return runBenchTools(options);
    if (options.house)
        return runHouse(options);
    if (!options.drawWalls.isEmpty())
        return runDrawWalls(options);

    QTemporaryDir tmp;
    QString path = options.path;
    if (path == QLatin1String(":occlusion:")) { // a short wall fully hidden behind a tall one
        path = tmp.filePath(QStringLiteral("occlusion.ifc"));
        if (!PythonEngine::instance().callJson("_write_occlusion_model", {path}, &error).object().value("ok").toBool())
            return fail(error);
    }
    if (path == QLatin1String(":fixture:")) {
        QDir().mkpath(tmp.filePath(QStringLiteral("Proyecto ñ")));
        path = tmp.filePath(QStringLiteral("Proyecto ñ/fixture.ifc"));
        if (!PythonEngine::instance().callJson("_write_test_model", {path}, &error).object().value("ok").toBool())
            return fail(error);
    }

    MainWindow window(nullptr, /*quiet=*/true, options.chunkSize);
    window.show();
    QApplication::processEvents();

    QEventLoop loop;
    QString loadError;
    bool stopped = false;
    QElapsedTimer timer, quitTimer;
    qint64 quitMs = -1;
    QObject::connect(&window, &MainWindow::loadFailed, &loop, [&](const QString& e) { loadError = e; loop.quit(); });
    QObject::connect(&window, &MainWindow::loadFinished, &loop, [&](int, bool s) {
        stopped = s;
        if (!options.quitDuringLoad) // in quit mode only the close ends the test
            loop.quit();
    });
    if (options.quitDuringLoad) {
        QObject::connect(&window, &MainWindow::firstChunkShown, &loop, [&] {
            QTimer::singleShot(0, &loop, [&] {
                quitTimer.start();
                window.close(); // must stop the loader thread promptly
                quitMs = quitTimer.elapsed();
                loop.quit();
            });
        });
    }
    QTimer::singleShot(20 * 60 * 1000, &loop, [&] { loadError = QStringLiteral("timeout"); loop.quit(); });
    timer.start();
    window.openFile(path);
    loop.exec();

    if (!loadError.isEmpty())
        return fail(loadError);
    if (options.quitDuringLoad)
        return report(QJsonObject{{"ok", quitMs >= 0 && quitMs < 5000 && !window.isLoading()},
            {"quit_during_load", true}, {"quit_ms", double(quitMs)}});

    Viewport* viewport = window.viewport();
    const double loadS = double(timer.elapsed()) / 1000.0;
    if (options.linesOnly)
        window.findChild<QAction*>(QStringLiteral("actionLinesOnly"))->setChecked(true);
    if (options.planView)
        window.findChild<QAction*>(QStringLiteral("actionPlanView"))->trigger();
    QApplication::processEvents();
    const double fps = viewport->measureFps(options.frames);

    QJsonObject result{{"ok", !stopped},
        {"elements", viewport->elementCount()},
        {"batches", viewport->batchCount()},
        {"triangles", double(viewport->triangleCount())},
        {"load_s", loadS},
        {"fps", fps}};
    const Bnd_Box bounds = viewport->boundsOf({});
    if (!bounds.IsVoid()) {
        double x0, y0, z0, x1, y1, z1;
        bounds.Get(x0, y0, z0, x1, y1, z1);
        result.insert(QStringLiteral("zmin"), z0);
        result.insert(QStringLiteral("zmax"), z1);
    }

    // Pick check: project an element's centre to the screen, pick there, expect that element back.
    // Elements can hide each other, so try up to 20; "missed" (hit nothing) must stay 0.
    const double dpr = viewport->devicePixelRatioF();
    const int w = int(viewport->width() * dpr), h = int(viewport->height() * dpr);
    int tried = 0, matched = 0, missed = 0;
    QString picked;
    for (const QString& guid : viewport->guids()) {
        if (tried >= 20)
            break;
        int x = 0, y = 0;
        if (!viewport->projectCenterOf(guid, &x, &y) || x < 0 || y < 0 || x >= w || y >= h)
            continue;
        ++tried;
        const QString got = viewport->pickAt(x, y);
        if (got.isEmpty())
            ++missed;
        if (got == guid) {
            ++matched;
            if (picked.isEmpty())
                picked = got;
        }
    }
    result.insert(QStringLiteral("pick_tried"), tried);
    result.insert(QStringLiteral("pick_matched"), matched);
    result.insert(QStringLiteral("pick_missed"), missed);
    result.insert(QStringLiteral("picked"), picked);

    // Selection sync: a viewport selection must select the same element in the tree.
    if (!picked.isEmpty()) {
        viewport->selectGuids({picked});
        emit viewport->selectionChanged(viewport->selectedGuids());
        QApplication::processEvents();
        result.insert(QStringLiteral("tree_follows_selection"), window.treePanel()->currentGuid() == picked);
    }
    if (options.boxSelect) {
        // Box selection takes elements fully inside the box: a box over the whole view selects all.
        const int n = viewport->selectInRectangle(1, 1, w - 2, h - 2, AIS_SelectionScheme_Replace, options.selectThrough);
        QApplication::processEvents();
        result.insert(QStringLiteral("box_selected"), n);
        result.insert(QStringLiteral("tree_selected"), int(window.treePanel()->selectedGuids().size()));
    }
    if (options.planCut >= 0) {
        window.setPlanCutHeight(options.planCut);
        if (QAction* cut = window.findChild<QAction*>(QStringLiteral("actionPlanCut")))
            cut->setChecked(true);
        QApplication::processEvents();
        result.insert(QStringLiteral("plan_cut"), options.planCut);
        result.insert(QStringLiteral("planes"), viewport->clipPlaneCount());
        result.insert(QStringLiteral("fps_with_cut"), viewport->measureFps(options.frames));
    }
    if (options.createElevations) {
        window.findChild<QAction*>(QStringLiteral("actionCreateElevations"))->trigger();
        window.findChild<QAction*>(QStringLiteral("actionPlanView"))->trigger();
        QApplication::processEvents();
    }
    if (!options.openDrawing.isEmpty()) { // Slice 14: a section or elevation, generated in the background
        const QString guid = window.drawingGuid(options.openDrawing);
        QElapsedTimer drawingTimer;
        drawingTimer.start();
        bool shown = !guid.isEmpty() && window.openDrawing(guid);
        DrawingView* view = shown ? window.drawingView(guid) : nullptr;
        while (view && !view->hasDrawing() && drawingTimer.elapsed() < 10 * 60 * 1000)
            QApplication::processEvents(QEventLoop::AllEvents, 50);
        shown = view && view->hasDrawing();
        result.insert(QStringLiteral("drawing_shown"), shown);
        result.insert(QStringLiteral("drawing_visible"), window.lastDrawingVisibleCount());
        result.insert(QStringLiteral("drawing_s"), double(drawingTimer.elapsed()) / 1000.0);
        if (shown) {
            result.insert(QStringLiteral("drawing_paper_mm"), QJsonArray{view->paperSize().width(), view->paperSize().height()});
            view->fit();
        }
        result.insert(QStringLiteral("ok"), result.value("ok").toBool() && shown);
        QApplication::processEvents();
    }
    if (!options.screenshot.isEmpty())
        takeScreenshots(window, options.screenshot, &result);
    return report(result);
}

} // namespace kimcad
