// SPDX-License-Identifier: GPL-3.0-or-later
// D86: the object library in the main window (doc 14 §8): the Library panel and the Object tool.
// The objects, their types and plan symbols are python/kimbim/library.py's; one undo step each.
#include <QAction>
#include <QCheckBox>
#include <QFileDialog>
#include <QJsonArray>
#include <QJsonDocument>
#include <QMenu>

#include <cmath>

#include "DockLayout.h"
#include "LevelsBar.h"
#include "LibraryPanel.h"
#include "MainWindow.h"
#include "Snapper.h"
#include "StatusStrip.h"
#include "TwoPointTool.h"
#include "Viewport.h"
#include "WallTool.h"

namespace kimbim {

namespace {

QString compactJson(const QJsonObject& o)
{
    return QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Compact));
}

QString num(double v)
{
    return QString::number(v, 'g', 17);
}

} // namespace

void MainWindow::setupLibrary(QMenu* model)
{
    QAction* show = model->addAction(tr("Object &library"));
    show->setObjectName(QStringLiteral("actionObjectLibrary"));
    show->setToolTip(tr("The library of furniture, sanitary, kitchen and site objects, and the office library"));
    connect(show, &QAction::triggered, this, [this] {
        libraryPanel();
        m_dock->raisePanel(QStringLiteral("library"));
    });
    // Tab turns the object 90 degrees; enabled only while the Object tool is active (setTool), so
    // Tab moves the keyboard focus everywhere else.
    m_objectTurn = new QAction(tr("Turn object 90 degrees"), this);
    m_objectTurn->setObjectName(QStringLiteral("actionTurnObject"));
    m_objectTurn->setShortcut(Qt::Key_Tab);
    m_objectTurn->setShortcutContext(Qt::WindowShortcut);
    m_objectTurn->setEnabled(false);
    addAction(m_objectTurn);
    connect(m_objectTurn, &QAction::triggered, this, [this] { setObjectAngle(m_objectAngle + 90.0); });
}

void MainWindow::applyLibraryPaths()
{
    QJsonArray files;
    for (const auto& f : m_prefs.value(QStringLiteral("library_files")).toArray())
        files.append(f);
    const QJsonObject paths{{"folder", m_prefs.value(QStringLiteral("office_library")).toString()}, {"files", files}};
    const QJsonObject r = bridge("set_library_paths", {compactJson(paths)});
    m_libraryPathsSent = true;
    for (const auto& e : r.value("errors").toArray())
        m_status->showMessage(tr("Office library: %1").arg(e.toObject().value("file").toString() + QStringLiteral(": ")
            + e.toObject().value("error").toString()));
    if (m_library)
        m_library->setListing(bridge("library_objects"));
}

void MainWindow::refreshLibrary()
{
    if (!m_libraryPathsSent)
        applyLibraryPaths();
    libraryPanel();
}

LibraryPanel* MainWindow::libraryPanel()
{
    if (m_library)
        return m_library;
    m_library = new LibraryPanel(this);
    m_dock->addPanel(QStringLiteral("library"), tr("Library"), m_library);
    if (!m_libraryPathsSent)
        applyLibraryPaths(); // fills the panel
    else
        m_library->setListing(bridge("library_objects"));
    connect(m_library, &LibraryPanel::placeRequested, this, [this] { setTool(Tool::Object); });
    connect(m_library, &LibraryPanel::currentChanged, this, [this] {
        if (m_tool == Tool::Object)
            updateToolPreview();
    });
    connect(m_library, &LibraryPanel::officeLibraryRequested, this, [this] {
        const QString folder = QFileDialog::getExistingDirectory(this, tr("Office library"),
            m_prefs.value(QStringLiteral("office_library")).toString());
        if (folder.isEmpty())
            return;
        m_prefs.setValue(QStringLiteral("office_library"), folder);
        m_prefs.save();
        applyLibraryPaths();
    });
    connect(m_library, &LibraryPanel::ifcLibraryRequested, this, [this] {
        const QString path = QFileDialog::getOpenFileName(this, tr("Load IFC types"), QString(), tr("IFC files (*.ifc)"));
        if (path.isEmpty())
            return;
        QJsonArray files = m_prefs.value(QStringLiteral("library_files")).toArray();
        if (!files.contains(path))
            files.append(path);
        m_prefs.setValue(QStringLiteral("library_files"), files);
        m_prefs.save();
        applyLibraryPaths();
    });
    return m_library;
}

bool MainWindow::chooseObject(const QString& id, const QJsonObject& params)
{
    LibraryPanel* panel = libraryPanel();
    if (!panel->selectObject(id))
        return false;
    for (auto it = params.begin(); it != params.end(); ++it)
        panel->setParam(it.key(), it.value().toDouble());
    setTool(Tool::Object);
    return m_tool == Tool::Object;
}

void MainWindow::setObjectAngle(double degrees)
{
    m_objectAngle = std::fmod(degrees, 360.0);
    if (m_objectAngle < 0)
        m_objectAngle += 360.0;
    if (m_tool == Tool::Object) {
        m_status->showMessage(tr("Object angle: %1 degrees").arg(m_objectAngle, 0, 'f', 1));
        updateToolPreview();
    }
}

std::optional<MainWindow::ObjectFit> MainWindow::fitObjectToWall(QPointF p, double width, double depth) const
{
    // D97: the nearest wall face the cursor is in front of (within reach), the object's back against it,
    // its middle where the cursor is along the wall (front at y = 0, origin the left front corner).
    if (!m_objectFit || !m_objectFit->isChecked() || !m_wallTool)
        return std::nullopt;
    const double reach = std::max(0.6, depth);
    std::optional<ObjectFit> best;
    double bestDistance = reach;
    for (const SnapWall& w : m_wallTool->snapper().walls()) {
        if (w.arc)
            continue; // D97: a curved wall's face is no line to stand against
        const QPointF d = w.b - w.a;
        const double len = std::hypot(d.x(), d.y());
        if (len < 1e-9)
            continue;
        const QPointF along = d / len, left(-along.y(), along.x());
        for (const double side : {1.0, -1.0}) { // the face on the axis' left, then on its right
            const QPointF out = left * side; // away from the wall body
            const QPointF face = w.a + left * (w.centre + side * w.thickness / 2);
            const QPointF v = p - face;
            const double t = v.x() * along.x() + v.y() * along.y();
            const double dist = v.x() * out.x() + v.y() * out.y();
            if (t < 0 || t > len || dist < -0.02 || dist > bestDistance)
                continue;
            bestDistance = dist;
            const QPointF uy = -out; // the back faces the wall
            const QPointF ux(uy.y(), -uy.x());
            const QPointF onFace = face + along * t;
            ObjectFit fit;
            fit.origin = onFace - ux * (width / 2) - uy * depth;
            fit.angle = std::atan2(ux.y(), ux.x()) * 180.0 / M_PI;
            best = fit;
        }
    }
    return best;
}

bool MainWindow::placeObjectAt(QPointF p, bool turned)
{
    LibraryPanel* panel = libraryPanel();
    if (panel->currentObject().isEmpty()) {
        m_status->showMessage(tr("Pick an object in the Library panel first"));
        m_dock->raisePanel(QStringLiteral("library"));
        return false;
    }
    double angle = (m_objectAngle + (turned ? 90.0 : 0.0)) * M_PI / 180.0;
    const QJsonObject info = panel->currentInfo();
    const double width = info.value("width").toDouble(1.0);
    if (const auto fit = fitObjectToWall(p, width, info.value("depth").toDouble(width))) {
        p = fit->origin;
        angle = fit->angle * M_PI / 180.0;
    }
    const QJsonObject r = bridge("place_object", {m_levels->activeStorey(), panel->currentObject(),
        compactJson(panel->currentParams()), num(p.x()), num(p.y()), num(angle),
        m_objectGravity && m_objectGravity->isChecked() ? QStringLiteral("1") : QString()});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not place it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    m_status->showMessage(tr("%1 placed").arg(panel->currentName()));
    return true;
}

void MainWindow::updateObjectPreview()
{
    QVector<Viewport::PreviewBox> boxes;
    if (m_objectHover && m_library && !m_library->currentObject().isEmpty()) {
        const QJsonObject info = m_library->currentInfo();
        const double w = info.value("width").toDouble(1.0), d = info.value("depth").toDouble(w);
        const double h = info.value("height").toDouble(1.0), z = m_levels->activeElevation();
        double a = m_objectAngle * M_PI / 180.0;
        QPointF origin = *m_objectHover;
        if (const auto fit = fitObjectToWall(origin, w, d)) { // D97: against the wall
            origin = fit->origin;
            a = fit->angle * M_PI / 180.0;
        }
        const QPointF ux(std::cos(a), std::sin(a)), uy(-std::sin(a), std::cos(a));
        const QPointF mid = origin + uy * (d / 2); // the plan box: along x through its middle
        boxes.push_back({mid, mid + ux * w, d, z, z + h});
    }
    m_viewport->setPreviewBoxes(boxes);
}

} // namespace kimbim
