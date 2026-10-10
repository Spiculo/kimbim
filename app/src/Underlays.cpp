// SPDX-License-Identifier: GPL-3.0-or-later
// D85: underlays. MainWindow members kept in their own file: File > Place underlay... and Underlays...,
// drawing them in the views (Viewport::setUnderlays), their snap index for every drawing tool, and
// calibrating or moving one by two clicks in the plan.
#include "MainWindow.h"

#include "DraftTool.h"
#include "GripTool.h"
#include "LevelsBar.h"
#include "MeasureController.h"
#include "MeasureOverlay.h"
#include "MeasureTool.h"
#include "ModifyTool.h"
#include "PolygonTool.h"
#include "PythonEngine.h"
#include "RotateTool.h"
#include "StatusStrip.h"
#include "TwoPointTool.h"
#include "Underlay.h"
#include "UnderlayDialogs.h"
#include "ViewHost.h"
#include "Viewport.h"
#include "WallTool.h"

#include <QAction>
#include <QApplication>
#include <QElapsedTimer>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QInputDialog>
#include <QJsonDocument>
#include <QMenu>

#include <cmath>
#include <cstring>

namespace kimcad {

namespace {
constexpr int kMaxTexture = 8192;

QString compact(const QJsonObject& o)
{
    return QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Compact));
}

// A PDF page rendered by Python (raw BGRX rows) or an image file, as a QImage.
QImage loadRaster(const QJsonObject& r)
{
    if (r.value("format").toString() == QLatin1String("image"))
        return QImage(r.value("path").toString());
    QFile f(r.value("path").toString());
    if (!f.open(QIODevice::ReadOnly))
        return {};
    const QByteArray data = f.readAll();
    const int w = r.value("width").toInt(), h = r.value("height").toInt(), stride = r.value("stride").toInt();
    if (w <= 0 || h <= 0 || stride < w * 4 || data.size() < qsizetype(stride) * h)
        return {};
    QImage img(w, h, QImage::Format_RGB32); // 0xffRRGGBB: B, G, R, X in memory, as PDFium writes
    for (int y = 0; y < h; ++y)
        std::memcpy(img.scanLine(y), data.constData() + qsizetype(stride) * y, size_t(w) * 4);
    return img;
}
} // namespace

void MainWindow::addUnderlayActions(QMenu* file)
{
    m_underlayPicker = std::make_shared<UnderlayPicker>();
    QAction* place = file->addAction(tr("Place &underlay..."));
    place->setObjectName(QStringLiteral("actionPlaceUnderlay"));
    place->setToolTip(tr("A DXF survey, a PDF page or a scanned image on the active level, to trace over"));
    connect(place, &QAction::triggered, this, [this] { placeUnderlayDialog(); });
    QAction* manage = file->addAction(tr("U&nderlays..."));
    manage->setObjectName(QStringLiteral("actionUnderlays"));
    manage->setToolTip(tr("Show, hide, fade, calibrate, move or remove underlays"));
    connect(manage, &QAction::triggered, this, &MainWindow::underlaysDialog);

    // Picking points for a calibration or a move: the active view is in drawing mode with no tool.
    onEachView([this](Viewport* v) {
        connect(v, &Viewport::workPointMoved, this, [this, v](QPointF p, double tolerance, Qt::KeyboardModifiers mods) {
            if (!m_underlayPicker->isActive())
                return;
            const Snap s = m_underlayPicker->move(p, tolerance, mods & Qt::ShiftModifier);
            QVector<MeasurePoint> path;
            const double z = m_levels->activeElevation();
            for (const QPointF& q : m_underlayPicker->points())
                path.push_back({q.x(), q.y(), z});
            path.push_back({s.point.x(), s.point.y(), z});
            QString label;
            if (!m_underlayPicker->points().isEmpty()) {
                const QPointF d = s.point - m_underlayPicker->points().first();
                label = formatLength(std::hypot(d.x(), d.y()));
            }
            v->setToolOverlay(new MeasureOverlay(path, label));
            m_status->showMessage(m_underlayPicker->hint());
        });
        connect(v, &Viewport::workPointClicked, this, [this](QPointF p, double tolerance, Qt::KeyboardModifiers mods) {
            if (!m_underlayPicker->isActive())
                return;
            if (m_underlayPicker->click(p, tolerance, mods & Qt::ShiftModifier))
                finishUnderlayPick();
            else
                m_status->showMessage(m_underlayPicker->hint());
        });
        connect(v, &Viewport::drawingEnded, this, [this, v] {
            if (!m_underlayPicker->isActive())
                return;
            m_underlayPicker->cancel();
            v->setToolOverlay({});
            v->setDrawingMode(false);
            m_status->showMessage(tr("Underlay: cancelled"));
        });
    });
}

void MainWindow::placeUnderlayDialog(const QString& given)
{
    if (m_levels->activeStorey().isEmpty()) {
        showError(tr("Place underlay"), tr("Open a model with a level first."));
        return;
    }
    const QString path = !given.isEmpty() ? given
        : QFileDialog::getOpenFileName(this, tr("Place underlay"), QString(),
            tr("Underlays (*.dxf *.pdf *.png *.jpg *.jpeg);;DXF drawings (*.dxf);;PDF files (*.pdf);;Images (*.png *.jpg *.jpeg)"));
    if (path.isEmpty())
        return;
    // Reading a large DXF takes seconds (ezdxf): off the window's thread, behind a progress dialog.
    const QJsonObject probe = bridgeInBackground("underlay_probe", {path}, tr("Reading %1...").arg(QFileInfo(path).fileName()));
    if (!probe.value("ok").toBool()) {
        showError(tr("Place underlay"), probe.value("error").toString());
        return;
    }
    QStringList layers;
    for (const auto& v : bridge("layers").value("layers").toArray())
        layers << v.toObject().value("name").toString();
    PlaceUnderlayDialog dialog(path, probe, layers, this);
    if (dialog.exec() != QDialog::Accepted)
        return;
    const QJsonObject r = placeUnderlay(path, dialog.options());
    if (!r.value("ok").toBool()) {
        showError(tr("Place underlay"), r.value("error").toString());
        return;
    }
    const Underlay u = Underlay::fromJson(r.value("underlay").toObject());
    if (u.isRaster())
        m_status->showMessage(tr("Placed %1. To set its scale, use File > Underlays... > Calibrate.").arg(u.name));
}

QJsonObject MainWindow::placeUnderlay(const QString& path, const QJsonObject& options)
{
    QJsonObject o = options;
    if (!o.contains("storey"))
        o.insert("storey", m_levels->activeStorey());
    const QJsonObject r = m_quiet ? bridge("add_underlay", {path, compact(o)})
                                  : bridgeInBackground("add_underlay", {path, compact(o)}, tr("Placing %1...").arg(QFileInfo(path).fileName()));
    if (r.value("ok").toBool()) {
        loadProjectSettings(); // the settings now hold it
        setWindowModified(isDirty());
        refreshLayers();       // its layer is listed; refreshes the underlays too
        m_status->showMessage(tr("Placed underlay %1").arg(r.value("underlay").toObject().value("name").toString()));
    }
    return r;
}

void MainWindow::underlaysDialog()
{
    QHash<QString, QString> levels;
    for (const auto& v : bridge("storeys").value("storeys").toArray())
        levels.insert(v.toObject().value("guid").toString(), v.toObject().value("name").toString());
    QStringList layers;
    for (const auto& v : bridge("layers").value("layers").toArray())
        layers << v.toObject().value("name").toString();
    auto* dialog = new UnderlaysDialog([this](const char* fn, const QStringList& args) { return bridge(fn, args); }, levels, layers, this);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setObjectName(QStringLiteral("underlaysDialog"));
    connect(dialog, &UnderlaysDialog::changed, this, [this] {
        loadProjectSettings();
        setWindowModified(isDirty());
        refreshLayers();
    });
    connect(dialog, &UnderlaysDialog::calibrateRequested, this, [this, dialog](const QString& id) {
        dialog->close();
        startUnderlayPick(id, UnderlayPicker::Calibrate);
    });
    connect(dialog, &UnderlaysDialog::moveRequested, this, [this, dialog](const QString& id) {
        dialog->close();
        startUnderlayPick(id, UnderlayPicker::Move);
    });
    connect(dialog, &UnderlaysDialog::placeRequested, this, [this, dialog] {
        dialog->close();
        placeUnderlayDialog();
    });
    dialog->show();
}

void MainWindow::refreshUnderlays()
{
    if (!m_underlayPicker || !m_levels)
        return;
    QElapsedTimer timer;
    timer.start();
    QVector<Underlay> all;
    bool any3d = false;
    for (const auto& v : bridge("underlays").value("underlays").toArray()) {
        Underlay u = Underlay::fromJson(v.toObject());
        if (!u.visible || u.missing || m_hiddenLayers.contains(u.layer))
            continue;
        any3d = any3d || u.show3d;
        all.push_back(u);
    }
    // Geometry, fetched once per file (and page and colouring for rasters).
    QHash<QString, std::shared_ptr<const UnderlayLines>> lines;
    QHash<QString, QImage> images;
    for (const Underlay& u : std::as_const(all)) {
        if (!u.isRaster()) {
            auto cached = m_underlayLines.value(u.file);
            if (!cached) {
                QList<QByteArray> parts;
                bool none = false;
                QString error;
                if (PythonEngine::instance().callParts("underlay_lines", {u.id}, &parts, &none, &error) && !none)
                    cached = UnderlayLines::fromParts(parts, &error);
                if (!cached)
                    m_status->showMessage(tr("Could not read underlay %1: %2").arg(u.name, error));
            }
            if (cached)
                lines.insert(u.file, cached);
        } else {
            const QString key = QStringLiteral("%1|%2|%3|%4|%5").arg(u.file).arg(u.page).arg(u.dpi).arg(u.greyscale).arg(u.tint);
            QImage img = m_underlayImages.value(key);
            if (img.isNull()) {
                const QJsonObject r = bridge("underlay_raster", {u.id});
                img = r.value("ok").toBool() ? loadRaster(r) : QImage();
                if (img.width() > kMaxTexture || img.height() > kMaxTexture)
                    img = img.scaled(kMaxTexture, kMaxTexture, Qt::KeepAspectRatio, Qt::SmoothTransformation);
                if (!img.isNull())
                    img = processUnderlayImage(img, u.greyscale, u.tint.isEmpty() ? QColor() : QColor(u.tint));
                else
                    m_status->showMessage(tr("Could not show underlay %1: %2").arg(u.name, r.value("error").toString()));
            }
            if (!img.isNull())
                images.insert(key, img);
        }
    }
    m_underlayLines = lines;
    m_underlayImages = images;
    auto view = [&](const Underlay& u, double z) {
        Viewport::UnderlayView v{u, lines.value(u.file), {}, z};
        if (u.isRaster())
            v.image = images.value(QStringLiteral("%1|%2|%3|%4|%5").arg(u.file).arg(u.page).arg(u.dpi).arg(u.greyscale).arg(u.tint));
        return v;
    };
    QHash<QString, double> elevations;
    if (any3d)
        for (const auto& s : bridge("storeys").value("storeys").toArray())
            elevations.insert(s.toObject().value("guid").toString(), s.toObject().value("elevation").toDouble());
    // Plans show their level's underlays; the 3D view those marked "also in 3D".
    for (auto it = m_hosts.constBegin(); it != m_hosts.constEnd(); ++it) {
        Viewport* vp = it.value()->viewport();
        QVector<Viewport::UnderlayView> shown;
        if (vp->isPlanView()) {
            const QString storey = it.key().startsWith(QLatin1String("plan:")) ? it.key().mid(5) : m_levels->activeStorey();
            for (const Underlay& u : std::as_const(all))
                if (u.storey == storey)
                    shown.push_back(view(u, vp->planElevation()));
        } else {
            for (const Underlay& u : std::as_const(all))
                if (u.show3d && elevations.contains(u.storey))
                    shown.push_back(view(u, elevations.value(u.storey)));
        }
        vp->setUnderlays(shown);
    }
    // Snapping: the active level's DXF linework, rebuilt only when it or its placement changed.
    QString key;
    for (const Underlay& u : std::as_const(all))
        if (!u.isRaster() && u.storey == m_levels->activeStorey() && lines.contains(u.file))
            key += u.id + compact(u.placementJson()) + QString::number(u.placement.base.x(), 'g', 17)
                + QString::number(u.placement.base.y(), 'g', 17) + QLatin1Char(';');
    if (key != m_underlaySnapKey) {
        std::shared_ptr<UnderlaySnapIndex> index;
        if (!key.isEmpty()) {
            index = std::make_shared<UnderlaySnapIndex>();
            for (const Underlay& u : std::as_const(all))
                if (!u.isRaster() && u.storey == m_levels->activeStorey() && lines.contains(u.file))
                    index->add(*lines.value(u.file), u.placement);
            index->build();
        }
        m_underlaySnap = index;
        m_underlaySnapKey = key;
    }
    for (Snapper* s : {&m_wallTool->snapper(), &m_polygonTool->snapper(), &m_twoPointTool->snapper(), &m_rotateTool->snapper(),
             &m_gripTool->snapper(), &m_measure->tool()->snapper(), &m_modifyTool->snapper(), &m_draftTool->snapper(),
             &m_underlayPicker->snapper()})
        s->setUnderlays(m_underlaySnap);
    if (qEnvironmentVariableIsSet("KIMCAD_TIMINGS") && !all.isEmpty())
        qInfo("underlays refreshed in %lld ms", static_cast<long long>(timer.elapsed()));
}

void MainWindow::startUnderlayPick(const QString& id, int mode)
{
    setTool(Tool::None);
    m_underlayPicker->start(id, UnderlayPicker::Mode(mode));
    Snapper& s = m_underlayPicker->snapper();
    s.setWalls(m_twoPointTool->snapper().walls());
    s.setGridLines(m_twoPointTool->snapper().gridLines());
    s.setPoints(m_twoPointTool->snapper().points());
    s.setUnderlays(m_underlaySnap);
    m_viewport->setDrawingMode(true, m_levels->activeElevation());
    m_viewport->setFocus();
    m_status->showMessage(m_underlayPicker->hint());
}

bool MainWindow::finishUnderlayPick(std::optional<double> distance)
{
    const QString id = m_underlayPicker->id();
    const QVector<QPointF> pts = m_underlayPicker->points();
    const auto mode = m_underlayPicker->mode();
    auto end = [this] {
        m_underlayPicker->cancel();
        m_viewport->setToolOverlay({});
        m_viewport->setDrawingMode(false);
    };
    if (id.isEmpty() || pts.size() < 2) {
        end();
        return false;
    }
    Underlay u;
    bool found = false;
    for (const auto& v : bridge("underlays").value("underlays").toArray())
        if (v.toObject().value("id").toString() == id) {
            u = Underlay::fromJson(v.toObject());
            found = true;
        }
    if (!found) {
        end();
        return false;
    }
    UnderlayPlacement placed;
    if (mode == UnderlayPicker::Calibrate) {
        const double measured = std::hypot(pts[1].x() - pts[0].x(), pts[1].y() - pts[0].y());
        if (measured < 1e-9) {
            end();
            m_status->showMessage(tr("Calibrate: the two points are the same"));
            return false;
        }
        if (!distance) {
            const QString unit = m_settings.value("length_unit").toString(QStringLiteral("m"));
            const double factor = unit == QLatin1String("mm") ? 1000.0 : unit == QLatin1String("cm") ? 100.0 : 1.0;
            bool ok = false;
            const double typed = QInputDialog::getDouble(this, tr("Calibrate underlay"),
                tr("Real distance between the two points (%1):").arg(unit), measured * factor, 1e-6, 1e9, 3, &ok);
            if (!ok) {
                end();
                return false;
            }
            distance = typed / factor;
        }
        placed = u.placement.calibrated(pts[0], pts[1], *distance);
    } else {
        placed = u.placement.moved(pts[1] - pts[0]);
    }
    end();
    u.placement = placed;
    const QJsonObject r = bridge("set_underlay", {id, compact(u.placementJson())});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(r.value("error").toString());
        return false;
    }
    loadProjectSettings();
    setWindowModified(isDirty());
    refreshUnderlays();
    m_status->showMessage(mode == UnderlayPicker::Calibrate ? tr("Underlay %1 calibrated").arg(u.name) : tr("Underlay %1 moved").arg(u.name));
    return true;
}

} // namespace kimcad
