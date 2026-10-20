// SPDX-License-Identifier: GPL-3.0-or-later
#define _USE_MATH_DEFINES
#include "SelfTest.h"

#include <QAction>
#include <QApplication>
#include <QJsonArray>
#include <QScreen>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QEventLoop>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QTimer>
#include <QImage>
#include <QSet>
#include <QMouseEvent>
#include <QWheelEvent>

#include <Graphic3d_Camera.hxx>

#include <cstdio>
#include <tuple>

#include "ConsolePanel.h"
#include "DockLayout.h"
#include "ChecksPanel.h"
#include "FindSelectPanel.h"
#include "LibraryPanel.h"
#include "DrawingView.h"
#include <DockManager.h>
#include <DockWidget.h>
#include "MainWindow.h"
#include "SchedulesDialog.h"
#include <QTableWidget>
#include "HostTool.h"
#include "TwoPointTool.h"
#include "WallTool.h"
#include "InputAidsController.h"
#include <QKeyEvent>

#include <QRegularExpression>

#include <cmath>
#include <utility>

#include "LevelsBar.h"
#include "LevelsDialog.h"
#include "MeasureController.h"
#include "ModelTreePanel.h"
#include "PythonEngine.h"
#include "ViewCube.h"
#include "Viewport.h"

namespace kimbim {

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

// D76: plays a preset turn to its end; true if it was animated (took more than one frame) and ended.
static bool waitForTurn(Viewport* viewport)
{
    const bool started = viewport->isAnimating(); // a turn starts at once (a click, a menu action)
    QElapsedTimer t;
    t.start();
    while (viewport->isAnimating() && t.elapsed() < 3000)
        QApplication::processEvents(QEventLoop::AllEvents, 10);
    QApplication::processEvents();
    return started && !viewport->isAnimating();
}

static gp_Dir eyeDirection(Viewport* viewport) // target -> eye
{
    return viewport->view()->Camera()->Direction().Reversed();
}

static bool boxSeen(Viewport* viewport) // the model's centre is on screen
{
    const Bnd_Box box = viewport->boundsOf({});
    if (box.IsVoid())
        return false;
    double x0, y0, z0, x1, y1, z1;
    box.Get(x0, y0, z0, x1, y1, z1);
    int x = 0, y = 0;
    viewport->view()->Convert((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2, x, y);
    const double dpr = viewport->devicePixelRatioF();
    return x >= 0 && y >= 0 && x < viewport->width() * dpr && y < viewport->height() * dpr;
}

// Shows the window, at --window-size or --maximized when given (D75: the title bar at different widths).
static void showWindow(MainWindow& window, const SelfTestOptions& options)
{
    if (options.windowSize.isValid())
        window.resize(options.windowSize);
    if (options.maximized)
        window.showMaximized();
    else
        window.show();
    QApplication::processEvents();
}

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
    showWindow(window, options);
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
    showWindow(window, options);
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
    showWindow(window, options);
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

    if (options.realOpen)
        return runRealOpen(options, path);

    MainWindow window(nullptr, /*quiet=*/true, options.chunkSize);
    showWindow(window, options);

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
    QJsonObject underlay;
    if (!options.underlay.isEmpty()) { // D85
        const QStringList parts = options.underlay.split(QLatin1Char(';'));
        QJsonObject o;
        if (parts.size() > 1)
            o.insert("opacity", parts[1].toDouble());
        if (parts.size() > 3) {
            o.insert("x", parts[2].toDouble());
            o.insert("y", parts[3].toDouble());
        }
        QElapsedTimer t;
        t.start();
        const QJsonObject r = window.placeUnderlay(parts[0], o);
        underlay = QJsonObject{{"ok", r.value("ok").toBool()}, {"error", r.value("error").toString()}, {"ms", double(t.elapsed())},
            {"shown", window.viewport()->underlayCount()}, {"segments", double(window.viewport()->underlaySegmentCount())}};
        if (window.viewport()->isPlanView())
            window.viewport()->fitAll();
    }
    // D76: perspective and preset views through their menu actions, the turn played to its end.
    QJsonObject navigation;
    if (options.perspective) {
        window.findChild<QAction*>(QStringLiteral("actionPerspective"))->trigger();
        viewport->fitAll(); // nearer parts look bigger in perspective: bring the whole model in
        navigation.insert(QStringLiteral("perspective"), !viewport->view()->Camera()->IsOrthographic());
    }
    if (!options.view.isEmpty()) {
        QAction* a = window.findChild<QAction*>(options.view == QLatin1String("Home") ? QStringLiteral("actionHomeView")
                                                                                       : QStringLiteral("actionView") + options.view);
        if (!a)
            return fail(QStringLiteral("no such view: ") + options.view);
        QApplication::processEvents();
        a->trigger();
        const gp_Dir want = viewDirection(options.view == QLatin1String("Home") ? HomeOrientation : [&] {
            for (const StandardView& sv : standardViews())
                if (options.view == QLatin1String(sv.id))
                    return sv.orientation;
            return HomeOrientation;
        }());
        const bool animated = waitForTurn(viewport);
        navigation.insert(QStringLiteral("view_animated"), animated);
        navigation.insert(QStringLiteral("view_ok"), eyeDirection(viewport).IsParallel(want, 1e-3)
            && eyeDirection(viewport).Dot(want) > 0 && boxSeen(viewport));
    }
    QApplication::processEvents();
    const double fps = viewport->measureFps(options.frames);

    QJsonObject result{{"ok", !stopped},
        {"elements", viewport->elementCount()},
        {"batches", viewport->batchCount()},
        {"triangles", double(viewport->triangleCount())},
        {"load_s", loadS},
        {"fps", fps}};
    for (auto it = navigation.constBegin(); it != navigation.constEnd(); ++it)
        result.insert(it.key(), it.value());
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
        // D78: a thin strip across the middle holds nothing fully (window, left to right) but crosses
        // the fitted model (crossing, right to left).
        if (!options.selectThrough) {
            const int y = h / 2;
            result.insert(QStringLiteral("box_window_strip"),
                viewport->selectInRectangle(1, y - 2, w - 2, y + 2, AIS_SelectionScheme_Replace));
            result.insert(QStringLiteral("box_crossing_strip"),
                viewport->selectInRectangle(w - 2, y - 2, 1, y + 2, AIS_SelectionScheme_Replace));
            viewport->selectInRectangle(1, 1, w - 2, h - 2, AIS_SelectionScheme_Replace); // as before
            QApplication::processEvents();
        }
    }
    if (options.perspective && !viewport->isPlanView()) {
        // D76: the wheel dollies the perspective camera towards the cursor.
        const double before = viewport->view()->Camera()->Distance();
        const QPointF at(viewport->width() / 2.0, viewport->height() / 2.0);
        QWheelEvent wheel(at, viewport->mapToGlobal(at), QPoint(), QPoint(0, 240), Qt::NoButton, Qt::NoModifier, Qt::NoScrollPhase, false);
        QApplication::sendEvent(viewport, &wheel);
        for (int i = 0; i < 10; ++i)
            QApplication::processEvents();
        result.insert(QStringLiteral("perspective_dolly"), viewport->view()->Camera()->Distance() < before * 0.99
            && !viewport->view()->Camera()->IsOrthographic());
    }
    if (options.cubeClick) {
        // D76: click the cube's top face like a mouse does, then the home button; the selection stays.
        const QStringList guids = viewport->guids();
        if (!guids.isEmpty())
            viewport->selectGuids({guids.first()});
        const QStringList before = viewport->selectedGuids();
        const QRect r = viewport->viewCubeRect();
        QPointF top(-1, -1);
        for (int y = r.top(); y <= r.bottom() && top.x() < 0; y += 2)
            for (int x = r.left(); x <= r.right(); x += 2) {
                V3d_TypeOfOrientation o;
                if (viewport->viewCubeOrientationAt(QPointF(x, y), &o) && o == V3d_Zpos) {
                    top = QPointF(x, y + 4); // a little inside the face, past its edge band
                    break;
                }
            }
        auto click = [viewport](QPointF at) {
            QMouseEvent press(QEvent::MouseButtonPress, at, viewport->mapToGlobal(at), Qt::LeftButton, Qt::LeftButton, Qt::NoModifier);
            QApplication::sendEvent(viewport, &press);
            QMouseEvent release(QEvent::MouseButtonRelease, at, viewport->mapToGlobal(at), Qt::LeftButton, Qt::NoButton, Qt::NoModifier);
            QApplication::sendEvent(viewport, &release);
            return waitForTurn(viewport);
        };
        result.insert(QStringLiteral("cube_found_top"), top.x() >= 0);
        QElapsedTimer turn;
        turn.start();
        const bool topAnimated = top.x() >= 0 && click(top);
        result.insert(QStringLiteral("cube_turn_ms"), double(turn.elapsed()));
        result.insert(QStringLiteral("cube_top"), topAnimated && eyeDirection(viewport).Z() > 0.999);
        const bool homeAnimated = click(viewport->homeButtonRect().center());
        result.insert(QStringLiteral("cube_home"), homeAnimated
            && eyeDirection(viewport).IsParallel(viewDirection(HomeOrientation), 1e-3) && eyeDirection(viewport).Dot(viewDirection(HomeOrientation)) > 0);
        result.insert(QStringLiteral("cube_selection_kept"), !before.isEmpty() && viewport->selectedGuids() == before);
    }
    if (options.popOut) {
        // D71: a tab dragged out moves its view to a new top-level window (a new native window).
        // The view must keep drawing there and after it is docked back.
        auto drawsSomething = [&](Viewport* v) {
            const QString file = QDir::temp().filePath(QStringLiteral("kimbim-popout.png"));
            if (!v->dumpImage(file))
                return false;
            const QImage image(file);
            QSet<QRgb> colours;
            for (int y = 0; y < image.height() && colours.size() < 3; y += 7)
                for (int x = 0; x < image.width() && colours.size() < 3; x += 7)
                    colours.insert(image.pixel(x, y));
            return colours.size() >= 2 && !v->pickAt(v->width() / 2, v->height() / 2).isNull();
        };
        DockLayout* dock = window.dockLayout();
        const QByteArray docked = dock->saveLayout();
        ads::CDockWidget* tab = dock->manager()->findDockWidget(QStringLiteral("3d"));
        tab->setFloating(); // what dragging the tab out does
        QApplication::processEvents();
        result.insert(QStringLiteral("pop_out_floating"), tab->isFloating());
        viewport->fitAll();
        QApplication::processEvents();
        const bool outside = tab->isFloating() && drawsSomething(viewport);
        dock->restoreLayout(docked); // docked back
        QApplication::processEvents();
        viewport->fitAll();
        QApplication::processEvents();
        const bool back = drawsSomething(viewport);
        result.insert(QStringLiteral("pop_out_outside"), outside);
        result.insert(QStringLiteral("pop_out"), outside && back);
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
    if (options.benchEdit) {
        // D71: an edit's refresh with one view (3D) or with a plan tab open and active (its cut on).
        if (options.planTab)
            window.openPlanTab(window.levelsBar()->activeStorey());
        QApplication::processEvents();
        QString wall;
        for (const QString& g : window.viewport()->guids())
            if (window.viewport()->typeOf(g).startsWith(QLatin1String("IfcWall"))) {
                wall = g;
                break;
            }
        const int edits = 6;
        double total = 0;
        bool moved = !wall.isEmpty();
        window.resetTimings();
        for (int i = 0; moved && i < edits; ++i) {
            window.setSelection({wall});
            QElapsedTimer t;
            t.start();
            moved = window.moveSelection(QPointF(i % 2 ? -0.1 : 0.1, 0.0), /*detach=*/true);
            QApplication::processEvents();
            total += double(t.nsecsElapsed()) / 1e6;
        }
        QJsonObject steps;
        for (auto it = window.timings().constBegin(); it != window.timings().constEnd(); ++it)
            steps.insert(it.key(), it.value() / edits);
        result.insert(QStringLiteral("edit_ms"), total / edits);
        result.insert(QStringLiteral("edit_steps_ms"), steps);
        result.insert(QStringLiteral("edit_views"), options.planTab ? 2 : 1);
        result.insert(QStringLiteral("ok"), result.value("ok").toBool() && moved);
    }
    if (options.benchModify) {
        // D80: split a long straight wall in the middle, trim one piece at a quarter, undo both.
        QApplication::processEvents();
        auto timed = [](auto&& edit) {
            QElapsedTimer t;
            t.start();
            const bool ok = edit();
            QApplication::processEvents();
            return std::pair<bool, double>(ok, double(t.nsecsElapsed()) / 1e6);
        };
        struct Candidate {
            QString guid;
            double x0, y0, x1, y1;
        };
        QVector<Candidate> candidates;
        for (const QString& g : window.viewport()->guids()) {
            if (!window.viewport()->typeOf(g).startsWith(QLatin1String("IfcWall")))
                continue;
            double x0, y0, z0, x1, y1, z1;
            window.viewport()->boundsOf({g}).Get(x0, y0, z0, x1, y1, z1);
            const double lx = x1 - x0, ly = y1 - y0;
            if (std::max(lx, ly) > 4.0 && std::min(lx, ly) < 0.6) // long and axis-aligned
                candidates.push_back({g, x0, y0, x1, y1});
        }
        bool split = false, trimmed = false;
        double splitMs = 0, trimMs = 0, undoMs = 0;
        for (const Candidate& c : candidates) {
            const bool alongX = c.x1 - c.x0 > c.y1 - c.y0;
            const QPointF mid((c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2);
            const QStringList before = window.viewport()->guids();
            window.resetTimings();
            std::tie(split, splitMs) = timed([&] { return window.splitElement(c.guid, mid); });
            if (!split)
                continue; // e.g. a door in the middle
            QJsonObject steps;
            for (auto it = window.timings().constBegin(); it != window.timings().constEnd(); ++it)
                steps.insert(it.key(), it.value());
            result.insert(QStringLiteral("split_steps_ms"), steps);
            QString piece;
            for (const QString& g : window.viewport()->guids())
                if (!before.contains(g) && window.viewport()->typeOf(g).startsWith(QLatin1String("IfcWall")))
                    piece = g;
            const QPointF keep = alongX ? QPointF(c.x0 + 0.1 * (c.x1 - c.x0), mid.y()) : QPointF(mid.x(), c.y0 + 0.1 * (c.y1 - c.y0));
            const QPointF cut = alongX ? QPointF(c.x0 + 0.25 * (c.x1 - c.x0), mid.y()) : QPointF(mid.x(), c.y0 + 0.25 * (c.y1 - c.y0));
            const QPointF n = alongX ? QPointF(0, 1) : QPointF(1, 0);
            for (const QString& g : {c.guid, piece}) {
                std::tie(trimmed, trimMs) = timed([&] { return window.trimElement(g, keep, QString(), cut - n, cut + n); });
                if (trimmed)
                    break;
            }
            QAction* undo = window.findChild<QAction*>(QStringLiteral("actionUndo"));
            std::tie(std::ignore, undoMs) = timed([&] { undo->trigger(); return true; });
            if (trimmed)
                undo->trigger();
            break;
        }
        result.insert(QStringLiteral("modify_candidates"), int(candidates.size()));
        result.insert(QStringLiteral("split_ms"), splitMs);
        result.insert(QStringLiteral("trim_ms"), trimMs);
        result.insert(QStringLiteral("modify_undo_ms"), undoMs);
        result.insert(QStringLiteral("ok"), result.value("ok").toBool() && split && trimmed);
    }
    if (options.createDrawings) {
        window.findChild<QAction*>(QStringLiteral("actionCreateDrawings"))->trigger();
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
        result.insert(QStringLiteral("drawing_include_ms"), window.lastDrawingIncludeMs());
        result.insert(QStringLiteral("drawing_s"), double(drawingTimer.elapsed()) / 1000.0);
        if (shown) {
            result.insert(QStringLiteral("drawing_paper_mm"), QJsonArray{view->paperSize().width(), view->paperSize().height()});
            if (!options.screenshot.isEmpty()) { // the drawing's SVG beside the screenshot, for checks
                QString path = options.screenshot;
                path.replace(QStringLiteral(".png"), QStringLiteral("-drawing.svg"));
                QFile out(path);
                const bool saved = out.open(QIODevice::WriteOnly) && out.write(view->svg()) == view->svg().size();
                result.insert(QStringLiteral("drawing_svg"), saved ? path : QString());
            }
            view->fit();
        }
        result.insert(QStringLiteral("ok"), result.value("ok").toBool() && shown);
        QApplication::processEvents();
    }
    if (!options.schedule.isEmpty()) { // D77: the schedule window, its first row selected in the model
        QElapsedTimer scheduleTimer;
        scheduleTimer.start();
        SchedulesDialog* s = window.openSchedules(options.schedule);
        result.insert(QStringLiteral("schedule_s"), double(scheduleTimer.elapsed()) / 1000.0);
        result.insert(QStringLiteral("schedule_rows"), s->dataRows());
        if (s->dataRows() > 0)
            s->table()->selectRow(0);
        result.insert(QStringLiteral("schedule_selected"), int(window.selection().size()));
        s->show();
        for (int i = 0; i < 10; ++i)
            QApplication::processEvents();
        if (!options.screenshot.isEmpty()) {
            QString path = options.screenshot;
            path.replace(QStringLiteral(".png"), QStringLiteral("-schedule.png"));
            result.insert(QStringLiteral("schedule_screenshot"), s->grab().save(path) ? path : QString());
        }
    }
    if (!options.measure.isEmpty()) { // D79: clicks on the work plane, the last point followed by the mouse
        if (QAction* a = window.findChild<QAction*>(QStringLiteral("actionMeasureTool")))
            a->trigger();
        const QStringList pts = options.measure.split(QLatin1Char(' '), Qt::SkipEmptyParts);
        for (int i = 0; i < pts.size(); ++i) {
            const QStringList xy = pts[i].split(QLatin1Char(','));
            const QPointF p(xy.value(0).toDouble(), xy.value(1).toDouble());
            if (i + 1 < pts.size())
                emit window.viewport()->workPointClicked(p, 0.05, Qt::NoModifier);
            else
                emit window.viewport()->workPointMoved(p, 0.05, Qt::NoModifier);
        }
        result.insert(QStringLiteral("measure"), window.measure()->text());
        for (int i = 0; i < 5; ++i)
            QApplication::processEvents();
    }
    if (options.tracker) { // D89: a wall half drawn along a guide, the tracker beside the cursor
        if (QAction* a = window.findChild<QAction*>(QStringLiteral("actionPlanView")))
            a->trigger();
        window.setTool(MainWindow::Tool::Wall);
        Viewport* v = window.viewport();
        const QVector<SnapWall> walls = window.wallTool()->snapper().walls();
        const QPointF corner = walls.isEmpty() ? QPointF(0, 0) : walls.first().a;
        const QPointF start = corner + QPointF(2.0, -2.5);
        if (!v->view()->Window().IsNull()) { // closer, around the corner
            int px = 0, py = 0;
            v->view()->Convert(corner.x() + 2, corner.y() - 1, window.levelsBar()->activeElevation(), px, py);
            const QPointF at = QPointF(px, py) / v->devicePixelRatioF();
            v->panByPixels(v->width() / 2.0 - at.x(), v->height() / 2.0 - at.y());
            v->zoomByFactor(1.6, QPointF(v->width() / 2.0, v->height() / 2.0));
        }
        emit v->workPointMoved(corner + QPointF(0.01, 0.01), 0.1, Qt::NoModifier); // rest on a wall end...
        window.inputAids()->aids()->acquireHovered();                           // ...long enough
        emit v->workPointClicked(start, 0.1, Qt::NoModifier);
        emit v->workPointMoved(QPointF(corner.x() + 3.4, corner.y() + 0.04), 0.1, Qt::NoModifier); // on the guide
        result.insert(QStringLiteral("tracker_guides"), int(window.inputAids()->aids()->guides().size()));
        result.insert(QStringLiteral("tracker_snap"), window.inputAids()->aids()->lastKind());
        for (int i = 0; i < 10; ++i)
            QApplication::processEvents();
        if (!options.screenshot.isEmpty()) {
            QString path = options.screenshot;
            path.replace(QStringLiteral(".png"), QStringLiteral("-tracker-viewport.png"));
            result.insert(QStringLiteral("tracker_screenshot"), v->dumpImage(path) ? path : QString());
        }
        for (const QChar c : QStringLiteral("5<30")) { // typed: the length, then the angle locks the direction
            QKeyEvent key(QEvent::KeyPress, c.isDigit() ? Qt::Key_0 + c.digitValue() : Qt::Key_Less, Qt::NoModifier, QString(c));
            QApplication::sendEvent(v, &key);
        }
        for (int i = 0; i < 10; ++i)
            QApplication::processEvents();
        if (!options.screenshot.isEmpty()) {
            QString path = options.screenshot;
            path.replace(QStringLiteral(".png"), QStringLiteral("-tracker-typed-viewport.png"));
            result.insert(QStringLiteral("tracker_typed_screenshot"), v->dumpImage(path) ? path : QString());
        }
        QKeyEvent enter(QEvent::KeyPress, Qt::Key_Return, Qt::NoModifier);
        QApplication::sendEvent(v, &enter);
        result.insert(QStringLiteral("tracker_drawing"), window.wallTool()->isDrawing());
        window.setTool(MainWindow::Tool::None);
    }
    if (options.levelsDialog) { // D79: the levels table, shown beside the window
        QString error;
        const QJsonObject table = PythonEngine::instance().callJson("levels_table", {}, &error).object();
        auto* d = new LevelsDialog(table.value("levels").toArray(), QStringLiteral("m"), 1.0, 2, &window);
        d->show();
        for (int i = 0; i < 10; ++i)
            QApplication::processEvents();
        result.insert(QStringLiteral("levels_rows"), d->table().count());
        if (!options.screenshot.isEmpty()) {
            QString path = options.screenshot;
            path.replace(QStringLiteral(".png"), QStringLiteral("-levels.png"));
            result.insert(QStringLiteral("levels_screenshot"), d->grab().save(path) ? path : QString());
        }
    }
    if (!options.findSelect.isEmpty()) { // D78: the panel, one criterion, Select
        if (QAction* a = window.findChild<QAction*>(QStringLiteral("actionFindSelect")))
            a->trigger();
        FindSelectPanel* panel = window.findSelectPanel();
        panel->clearRows();
        panel->addRow(QStringLiteral("ifc_class"), QStringLiteral("equals"), options.findSelect);
        panel->find(FindSelectPanel::How::Replace);
        for (int i = 0; i < 5; ++i)
            QApplication::processEvents();
        result.insert(QStringLiteral("find_selected"), int(window.selection().size()));
    }
    if (!options.library.isEmpty()) { // D86: the Library panel, the Object tool, one placement
        if (QAction* a = window.findChild<QAction*>(QStringLiteral("actionObjectLibrary")))
            a->trigger();
        const bool chosen = window.chooseObject(options.library);
        const bool placed = chosen && window.placeObjectAt(QPointF(1.0, 1.0));
        for (int i = 0; i < 5; ++i)
            QApplication::processEvents();
        result.insert(QStringLiteral("library_placed"), placed);
        if (!options.screenshot.isEmpty()) {
            QString path = options.screenshot;
            path.replace(QStringLiteral(".png"), QStringLiteral("-library.png"));
            result.insert(QStringLiteral("library_screenshot"), window.libraryPanel()->grab().save(path) ? path : QString());
        }
    }
    if (!options.checks.isEmpty()) { // D81: the Checks panel, the first issue clicked
        if (QAction* a = window.findChild<QAction*>(QStringLiteral("actionCheckModel")))
            a->trigger();
        ChecksPanel* panel = window.checksPanel();
        const QStringList checks = options.checks.split(QLatin1Char(','), Qt::SkipEmptyParts);
        if (checks.contains(QStringLiteral("clash")) && panel->clashSetNames().isEmpty())
            window.saveClashSet(QStringLiteral("Walls x slabs"),
                {{"a", QJsonObject{{"classes", QJsonArray{"IfcWall"}}}}, {"b", QJsonObject{{"classes", QJsonArray{"IfcSlab"}}}},
                    {"mode", "hard"}, {"tolerance", 0.002}});
        QElapsedTimer t;
        t.start();
        result.insert(QStringLiteral("checks_ok"), window.runChecks(checks));
        result.insert(QStringLiteral("checks_ms"), double(t.elapsed()));
        result.insert(QStringLiteral("check_issues"), panel->issueCount());
        result.insert(QStringLiteral("check_summary"), panel->summary());
        if (panel->activateIssue(0))
            result.insert(QStringLiteral("check_selected"), int(window.selection().size()));
        for (int i = 0; i < 10; ++i)
            QApplication::processEvents();
        if (!options.screenshot.isEmpty()) { // before the general screenshots, which fit all
            QString path = options.screenshot;
            path.replace(QStringLiteral(".png"), QStringLiteral("-checks.png"));
            result.insert(QStringLiteral("checks_screenshot"), window.screen()->grabWindow(window.winId()).save(path) ? path : QString());
            path.replace(QStringLiteral(".png"), QStringLiteral("-viewport.png")); // the 3D view zoomed to the issue
            result.insert(QStringLiteral("checks_viewport_screenshot"), window.viewport()->dumpImage(path) ? path : QString());
        }
    }
    if (!options.console.isEmpty()) { // D82: the console panel raised, the code typed and run
        if (QAction* a = window.findChild<QAction*>(QStringLiteral("actionConsole")))
            a->trigger();
        ConsolePanel* panel = window.consolePanel();
        panel->input()->setPlainText(QString(options.console).replace(QStringLiteral("\\n"), QStringLiteral("\n"))); // "\n" typed on the command line
        panel->run();
        panel->input()->setPlainText(QStringLiteral("with edit():"));
        for (int i = 0; i < 10; ++i)
            QApplication::processEvents();
        result.insert(QStringLiteral("console_output"), panel->outputText());
    }
    if (!underlay.isEmpty())
        result.insert(QStringLiteral("underlay"), underlay);
    if (!options.screenshot.isEmpty())
        takeScreenshots(window, options.screenshot, &result);
    return report(result);
}

} // namespace kimbim
