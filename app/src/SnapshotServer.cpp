// SPDX-License-Identifier: GPL-3.0-or-later
// D102: the windowless snapshot server (see SnapshotServer.h). The pictures come from the app's own
// MainWindow and OCCT renderer, so they look like the app: same materials, textures, pens and poché.
#include "SnapshotServer.h"

#ifdef _WIN32
// First: OCCT's headers include windows.h without the window functions (EnumWindows).
#include <windows.h>
#endif

#include <QApplication>
#include <QColor>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFileInfo>
#include <QHash>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPainter>
#include <QSet>
#include <QSvgRenderer>
#include <QTimer>

#include <Graphic3d_Camera.hxx>
#include <V3d_TypeOfOrientation.hxx>

#include <cstdio>
#include <iostream>
#include <memory>
#include <string>

#include "MainWindow.h"
#include "PythonEngine.h"
#include "ViewCube.h"
#include "Viewport.h"

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#else
#include <unistd.h>
#endif

namespace kimbim {

namespace {

// The app's selection colour (Scene.cpp: linear 0.15, 0.50, 0.95), as sRGB.
const QColor kHighlight(0x6c, 0xbc, 0xf9);
constexpr int kMaxSide = 8192;

// The replies go to a private copy of stdout; fd 1 itself is pointed at stderr, so nothing else
// printed by the process (Python, OCCT, Qt) can break the one-JSON-line-per-request protocol.
int g_protocolFd = -1;

void redirectStdout()
{
    std::fflush(stdout);
#ifdef _WIN32
    g_protocolFd = _dup(_fileno(stdout));
    _setmode(g_protocolFd, _O_BINARY);
    _dup2(_fileno(stderr), _fileno(stdout));
#else
    g_protocolFd = dup(fileno(stdout));
    dup2(fileno(stderr), fileno(stdout));
#endif
}

void reply(const QJsonObject& o)
{
    const QByteArray line = QJsonDocument(o).toJson(QJsonDocument::Compact) + '\n';
    const char* p = line.constData();
    qsizetype left = line.size();
    while (left > 0) {
#ifdef _WIN32
        const int n = _write(g_protocolFd, p, unsigned(left));
#else
        const auto n = write(g_protocolFd, p, size_t(left));
#endif
        if (n <= 0)
            return;
        p += n;
        left -= n;
    }
}

QJsonObject error(const QString& code, const QString& message)
{
    return {{"ok", false}, {"error", QJsonObject{{"code", code}, {"message", message}}}};
}

// Top-level windows of this process that are on screen (must stay 0: the owner's desktop is in use).
int windowsOnScreen()
{
#ifdef _WIN32
    struct Count {
        DWORD pid;
        int n;
    } count{GetCurrentProcessId(), 0};
    EnumWindows(
        [](HWND hwnd, LPARAM data) -> BOOL {
            auto* c = reinterpret_cast<Count*>(data);
            DWORD pid = 0;
            GetWindowThreadProcessId(hwnd, &pid);
            if (pid == c->pid && IsWindowVisible(hwnd))
                ++c->n;
            return TRUE;
        },
        reinterpret_cast<LPARAM>(&count));
    return count.n;
#else
    int n = 0;
    for (QWidget* w : QApplication::topLevelWidgets())
        if (w->isVisible() && !w->testAttribute(Qt::WA_DontShowOnScreen))
            ++n;
    return n;
#endif
}

QJsonArray xyz(const gp_XYZ& p)
{
    return QJsonArray{p.X(), p.Y(), p.Z()};
}

bool readXyz(const QJsonValue& v, gp_XYZ* out)
{
    const QJsonArray a = v.toArray();
    if (a.size() != 3 || !a[0].isDouble() || !a[1].isDouble() || !a[2].isDouble())
        return false;
    *out = gp_XYZ(a[0].toDouble(), a[1].toDouble(), a[2].toDouble());
    return true;
}

// [w, h] (default when absent); false if malformed or out of range.
bool readSize(const QJsonValue& v, QSize fallback, QSize* out)
{
    if (v.isUndefined() || v.isNull()) {
        *out = fallback;
        return fallback.isValid();
    }
    const QJsonArray a = v.toArray();
    if (a.size() != 2)
        return false;
    const int w = a[0].toInt(-1), h = a[1].toInt(-1);
    if (w < 1 || h < 1 || w > kMaxSide || h > kMaxSide)
        return false;
    *out = QSize(w, h);
    return true;
}

QStringList readGuids(const QJsonValue& v)
{
    QStringList out;
    for (const auto& g : v.toArray())
        out << g.toString();
    return out;
}

// D76 view-cube presets by their snapshot names.
bool presetOrientation(const QString& name, V3d_TypeOfOrientation* out)
{
    static const QHash<QString, V3d_TypeOfOrientation> presets = {
        {"top", V3d_Zpos}, {"bottom", V3d_Zneg}, {"front", V3d_Yneg}, {"back", V3d_Ypos},
        {"left", V3d_Xneg}, {"right", V3d_Xpos}, {"iso-se", V3d_XposYnegZpos}, {"iso-sw", V3d_XnegYnegZpos},
        {"iso-ne", V3d_XposYposZpos}, {"iso-nw", V3d_XnegYposZpos}};
    const auto it = presets.constFind(name);
    if (it == presets.constEnd())
        return false;
    *out = *it;
    return true;
}

class Server {
public:
    int run()
    {
        std::string line;
        while (std::getline(std::cin, line)) {
            const QByteArray bytes = QByteArray::fromStdString(line).trimmed();
            if (bytes.isEmpty())
                continue;
            QJsonParseError parseError;
            const QJsonDocument doc = QJsonDocument::fromJson(bytes, &parseError);
            if (!doc.isObject()) {
                reply(error("bad_request", QStringLiteral("not a JSON object: %1").arg(parseError.errorString())));
                continue;
            }
            const QJsonObject req = doc.object();
            const QString op = req.value("op").toString();
            if (op == QLatin1String("load"))
                reply(load(req));
            else if (op == QLatin1String("render3d"))
                reply(render3d(req));
            else if (op == QLatin1String("svg2png"))
                reply(svg2png(req));
            else
                reply(error("bad_request", QStringLiteral("unknown op: %1").arg(op)));
        }
        if (m_window) {
            m_window->close();
            m_window.reset();
        }
        return 0;
    }

private:
    std::unique_ptr<MainWindow> m_window;
    bool m_loaded = false;
    QString m_purpose; // the project's purpose after loading (a render without "purpose" uses it)

    // The app's main window, never on screen: Qt keeps it off the screen (no visible native window,
    // no taskbar button, no focus) while OCCT still gets a native handle and its OpenGL context.
    MainWindow* window()
    {
        if (!m_window) {
            m_window = std::make_unique<MainWindow>(nullptr, /*quiet=*/true);
            m_window->setAttribute(Qt::WA_DontShowOnScreen);
            m_window->setAttribute(Qt::WA_ShowWithoutActivating);
            m_window->resize(1280, 800);
            m_window->show();
            QApplication::processEvents();
        }
        return m_window.get();
    }

    QJsonObject load(const QJsonObject& req)
    {
        const QString model = req.value("model").toString();
        if (model.isEmpty() || !QFileInfo::exists(model))
            return error("bad_request", QStringLiteral("no such model: %1").arg(model));
        const QString settings = req.value("settings").toString();
        if (!settings.isEmpty() && !QFileInfo::exists(settings))
            return error("bad_request", QStringLiteral("no such settings file: %1").arg(settings));
        MainWindow* w = window();
        m_loaded = false;
        QEventLoop loop;
        QString loadError;
        bool stopped = false;
        const auto failed = QObject::connect(w, &MainWindow::loadFailed, &loop, [&](const QString& e) {
            loadError = e;
            loop.quit();
        });
        const auto finished = QObject::connect(w, &MainWindow::loadFinished, &loop, [&](int, bool s) {
            stopped = s;
            loop.quit();
        });
        QTimer::singleShot(20 * 60 * 1000, &loop, [&] {
            loadError = QStringLiteral("timeout");
            loop.quit();
        });
        w->openFile(model);
        loop.exec();
        QObject::disconnect(failed);
        QObject::disconnect(finished);
        if (!loadError.isEmpty())
            return error("load_failed", loadError);
        if (stopped)
            return error("load_failed", QStringLiteral("loading stopped"));
        if (!settings.isEmpty()) { // the project's purposes, pens and materials, as its open does
            QString e;
            const QJsonObject r = PythonEngine::instance().callJson("load_settings_file", {settings}, &e).object();
            if (!r.value("ok").toBool())
                return error("load_failed", e.isEmpty() ? r.value("error").toString() : e);
            w->reloadProjectSettings();
        }
        QApplication::processEvents();
        m_purpose = w->viewport()->graphics().purpose();
        m_loaded = true;
        return {{"ok", true}, {"elements", w->viewport()->elementCount()}, {"windows_on_screen", windowsOnScreen()}};
    }

    QJsonObject render3d(const QJsonObject& req)
    {
        if (!m_loaded)
            return error("not_loaded", QStringLiteral("load a model first"));
        const QString out = req.value("out").toString();
        if (out.isEmpty())
            return error("bad_request", QStringLiteral("out is required"));
        QSize size;
        if (!readSize(req.value("size"), QSize(1024, 768), &size))
            return error("bad_request", QStringLiteral("size must be [w, h], 1 to %1 pixels").arg(kMaxSide));
        const QString style = req.value("style").toString(QStringLiteral("shaded"));
        if (!QStringList{"shaded", "white", "lines", "textured"}.contains(style))
            return error("bad_request", QStringLiteral("unknown style: %1").arg(style));
        // The camera: a preset name, or {eye, target, up, fov}.
        const QJsonValue cameraValue = req.value("camera");
        V3d_TypeOfOrientation preset = V3d_XposYnegZpos;
        gp_XYZ eye, target, up(0, 0, 1);
        double fov = 0; // 0: orthographic
        bool explicitCamera = false;
        if (cameraValue.isObject()) {
            const QJsonObject c = cameraValue.toObject();
            if (!readXyz(c.value("eye"), &eye) || !readXyz(c.value("target"), &target)
                || (c.contains("up") && !readXyz(c.value("up"), &up)))
                return error("bad_request", QStringLiteral("camera needs eye and target as [x, y, z] (and up)"));
            fov = c.value("fov").toDouble(0);
            if ((eye - target).Modulus() < 1e-9 || up.Modulus() < 1e-9 || fov < 0 || fov >= 180)
                return error("bad_request", QStringLiteral("camera: eye and target must differ, up be non-zero, 0 < fov < 180"));
            if (gp_Vec(target - eye).IsParallel(gp_Vec(up), 1e-9))
                return error("bad_request", QStringLiteral("camera: up must not be along the view direction"));
            explicitCamera = true;
        } else if (!cameraValue.isUndefined() && !cameraValue.isNull()) {
            if (!presetOrientation(cameraValue.toString(), &preset))
                return error("bad_request", QStringLiteral("unknown camera preset: %1").arg(cameraValue.toString()));
        }
        QHash<QString, QColor> colours;
        const QJsonObject colourMap = req.value("colours").toObject();
        for (auto it = colourMap.constBegin(); it != colourMap.constEnd(); ++it) {
            const QColor c(it.value().toString());
            if (!c.isValid())
                return error("bad_request", QStringLiteral("bad colour for %1: %2").arg(it.key(), it.value().toString()));
            colours.insert(it.key(), c);
        }
        for (const QString& g : readGuids(req.value("highlight")))
            colours.insert(g, kHighlight);
        const QStringList frame = readGuids(req.value("frame"));
        const bool isolate = req.value("isolate").toBool(false);
        const QJsonValue cut = req.value("cut");
        if (!cut.isUndefined() && !cut.isNull() && !cut.isDouble())
            return error("bad_request", QStringLiteral("cut must be a height in metres or null"));

        MainWindow* w = window();
        Viewport* v = w->viewport();
        // Every picture starts from the loaded model: nothing left over from the previous one.
        const QString purpose = req.value("purpose").toString(m_purpose);
        if (purpose != v->graphics().purpose() && !w->setPurpose(purpose))
            return error("unknown_purpose", QStringLiteral("no such purpose: %1").arg(purpose));
        v->selectGuids({});
        v->showAll();
        v->setLinesOnly(style == QLatin1String("lines"));
        v->setWhiteModel(style == QLatin1String("white"));
        v->setElementColors(colours);
        const QStringList shown = v->guids();
        const QSet<QString> present(shown.begin(), shown.end());
        int framed = 0;
        for (const QString& g : frame)
            framed += present.contains(g) ? 1 : 0;
        if (!frame.isEmpty() && framed == 0)
            return error("not_found", QStringLiteral("none of the elements to frame is in the model"));
        if (isolate && !frame.isEmpty())
            v->isolate(frame);
        if (frame.isEmpty())
            framed = v->visibleElementCount();
        const int cutsBefore = w->cutPlanes().size();
        if (cut.isDouble() && !w->addHorizontalCut(cut.toDouble()))
            return error("render_failed", QStringLiteral("the cut could not be added"));
        w->selectCutPlane(-1); // the selected plane's handle is an editing aid, not the model
        QApplication::processEvents();

        const Handle(Graphic3d_Camera)& camera = v->view()->Camera();
        camera->SetAspect(double(size.width()) / size.height()); // fit for the picture, not the window
        if (explicitCamera && fov > 0) {
            camera->SetProjectionType(Graphic3d_Camera::Projection_Perspective);
            camera->SetFOVy(fov);
            camera->SetEyeAndCenter(gp_Pnt(eye), gp_Pnt(target));
            camera->SetUp(gp_Dir(up));
            camera->OrthogonalizeUp();
        } else {
            const gp_Dir dir = explicitCamera ? gp_Dir(eye - target) : viewDirection(preset);
            camera->SetProjectionType(Graphic3d_Camera::Projection_Orthographic);
            const gp_Pnt center = explicitCamera ? gp_Pnt(target) : camera->Center();
            camera->SetEyeAndCenter(center.Translated(gp_Vec(dir) * std::max(camera->Distance(), 1.0)), center);
            camera->SetUp(explicitCamera ? gp_Dir(up) : viewUp(preset));
            camera->OrthogonalizeUp();
            Bnd_Box box = v->boundsOf(frame);
            if (!box.IsVoid()) {
                if (!frame.isEmpty())
                    box.Enlarge(0.5); // a little of what is around (as Viewport::fitTo)
                v->view()->FitAll(box, 0.05, false);
            }
        }
        v->view()->ZFitAll();
        const QImage image = v->renderImage(size.width(), size.height());
        QJsonObject used{{"eye", xyz(camera->Eye().XYZ())}, {"target", xyz(camera->Center().XYZ())},
            {"up", xyz(camera->Up().XYZ())}, {"fov", camera->IsOrthographic() ? 0.0 : camera->FOVy()},
            {"projection", camera->IsOrthographic() ? "orthographic" : "perspective"}};
        while (w->cutPlanes().size() > cutsBefore)
            w->removeCutPlane(w->cutPlanes().size() - 1);
        if (image.isNull())
            return error("render_failed", QStringLiteral("the 3D view could not be rendered offscreen"));
        if (!image.save(out, "PNG"))
            return error("write_failed", QStringLiteral("cannot write %1").arg(out));
        return {{"ok", true}, {"out", out}, {"camera", used}, {"framed", framed},
            {"size", QJsonArray{size.width(), size.height()}}, {"highlight_colour", kHighlight.name()}};
    }

    QJsonObject svg2png(const QJsonObject& req)
    {
        const QString svg = req.value("svg").toString(), out = req.value("out").toString();
        if (svg.isEmpty() || out.isEmpty())
            return error("bad_request", QStringLiteral("svg and out are required"));
        QSvgRenderer renderer(svg);
        if (!renderer.isValid())
            return error("svg_invalid", QStringLiteral("cannot read the SVG %1").arg(svg));
        QSize size;
        if (!readSize(req.value("size"), renderer.defaultSize(), &size))
            return error("bad_request", QStringLiteral("size must be [w, h], 1 to %1 pixels").arg(kMaxSide));
        QImage image(size, QImage::Format_RGB32);
        image.fill(Qt::white);
        QPainter painter(&image);
        painter.setRenderHint(QPainter::Antialiasing);
        renderer.setAspectRatioMode(Qt::KeepAspectRatio);
        renderer.render(&painter, QRectF(0, 0, size.width(), size.height()));
        painter.end();
        if (!image.save(out, "PNG"))
            return error("write_failed", QStringLiteral("cannot write %1").arg(out));
        return {{"ok", true}, {"out", out}, {"size", QJsonArray{size.width(), size.height()}}};
    }
};

} // namespace

int snapshotServerCommand()
{
    qputenv("KIMBIM_NO_LIVE_AGENT", "1"); // the helper opens a private copy, never the user's project
    redirectStdout();
    QString e;
    if (!PythonEngine::instance().start(&e)) {
        reply(error("engine_failed", e));
        return 1;
    }
    Server server;
    return server.run();
}

} // namespace kimbim
