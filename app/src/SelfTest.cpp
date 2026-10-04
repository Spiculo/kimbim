// SPDX-License-Identifier: GPL-3.0-or-later
#include "SelfTest.h"

#include <QApplication>
#include <QElapsedTimer>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>

#include <cstdio>

#include "ElementBatch.h"
#include "MeshChunk.h"
#include "PythonEngine.h"
#include "Viewport.h"

namespace kimcad {

namespace {

int report(QJsonObject result)
{
    const bool ok = result.value("ok").toBool();
    std::printf("%s\n", QJsonDocument(result).toJson(QJsonDocument::Compact).constData());
    std::fflush(stdout);
    return ok ? 0 : 1;
}

int fail(const QString& error)
{
    return report(QJsonObject{{"ok", false}, {"error", error}});
}

} // namespace

int runSelfTest(const SelfTestOptions& options)
{
    QString error;
    PythonEngine& py = PythonEngine::instance();
    if (!py.start(&error))
        return fail(error);

    QTemporaryDir tmp;
    QString path = options.path;
    if (path == QLatin1String(":fixture:")) {
        path = tmp.filePath(QStringLiteral("Proyecto ñ/fixture.ifc"));
        QDir().mkpath(tmp.filePath(QStringLiteral("Proyecto ñ")));
        if (!py.callJson("_write_test_model", {path}, &error).object().value("ok").toBool())
            return fail(error);
    }

    QElapsedTimer timer;
    timer.start();
    const QJsonObject info = py.callJson("open_model", {path}, &error).object();
    if (!info.value("ok").toBool())
        return fail(info.value("error").toString(error));

    Viewport viewport;
    viewport.resize(1280, 800);
    viewport.show();
    QApplication::processEvents();

    const QJsonObject started = py.callJson("start_meshing", {QStringLiteral("0")}, &error).object();
    if (!started.value("ok").toBool())
        return fail(started.value("error").toString(error));
    bool done = false;
    while (!done) {
        MeshChunk chunk;
        if (!fetchMeshChunk(py, 1000, &chunk, &done, &error))
            return fail(error);
        if (!done)
            viewport.addBatch(new ElementBatch(std::move(chunk)));
        QApplication::processEvents();
        if (options.quitDuringLoad && viewport.batchCount() > 0)
            return report(QJsonObject{{"ok", true}, {"quit_during_load", true}, {"batches", viewport.batchCount()}});
    }
    viewport.fitAll();
    QApplication::processEvents();
    const double loadS = double(timer.elapsed()) / 1000.0;

    const double fps = viewport.measureFps(options.frames);

    QJsonObject result{{"ok", true},
        {"schema", info.value("schema")},
        {"elements", viewport.elementCount()},
        {"batches", viewport.batchCount()},
        {"triangles", double(viewport.triangleCount())},
        {"load_s", loadS},
        {"fps", fps}};

    // Pick check: project an element's centre to the screen, pick there, expect that element back.
    // Elements can hide each other, so try up to 20 and report how many picked back to themselves.
    const double dpr = viewport.devicePixelRatioF();
    const int w = int(viewport.width() * dpr), h = int(viewport.height() * dpr);
    int tried = 0, matched = 0, missed = 0;
    QString picked;
    for (const QString& guid : viewport.guids()) {
        if (tried >= 20)
            break;
        int x = 0, y = 0;
        if (!viewport.projectCenterOf(guid, &x, &y) || x < 0 || y < 0 || x >= w || y >= h)
            continue;
        ++tried;
        const QString got = viewport.pickAt(x, y);
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
    result.insert(QStringLiteral("pick_missed"), missed); // hit nothing (a front element hit counts as occlusion)
    result.insert(QStringLiteral("picked"), picked);
    if (options.planCut >= 0)
        result.insert(QStringLiteral("plan_cut"), options.planCut);
    return report(result);
}

} // namespace kimcad
