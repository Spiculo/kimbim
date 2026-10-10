// SPDX-License-Identifier: GPL-3.0-or-later
// D86: the object library in the main window (doc 14 §8): the Library panel and the Object tool.
// The objects, their types and plan symbols are python/kimcad/library.py's; one undo step each.
#include <QAction>
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

namespace kimcad {

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

bool MainWindow::placeObjectAt(QPointF p, bool turned)
{
    LibraryPanel* panel = libraryPanel();
    if (panel->currentObject().isEmpty()) {
        m_status->showMessage(tr("Pick an object in the Library panel first"));
        m_dock->raisePanel(QStringLiteral("library"));
        return false;
    }
    const double angle = (m_objectAngle + (turned ? 90.0 : 0.0)) * M_PI / 180.0;
    const QJsonObject r = bridge("place_object", {m_levels->activeStorey(), panel->currentObject(),
        compactJson(panel->currentParams()), num(p.x()), num(p.y()), num(angle)});
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
        const double a = m_objectAngle * M_PI / 180.0;
        const QPointF ux(std::cos(a), std::sin(a)), uy(-std::sin(a), std::cos(a));
        const QPointF mid = *m_objectHover + uy * (d / 2); // the plan box: along x through its middle
        boxes.push_back({mid, mid + ux * w, d, z, z + h});
    }
    m_viewport->setPreviewBoxes(boxes);
}

} // namespace kimcad
