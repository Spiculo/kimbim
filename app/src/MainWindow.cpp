// SPDX-License-Identifier: GPL-3.0-or-later
#define _USE_MATH_DEFINES
#include "MainWindow.h"

#include <QApplication>
#include <QCloseEvent>
#include <QDockWidget>
#include <QDoubleSpinBox>
#include <QLabel>
#include <QToolBar>
#include <QFileDialog>
#include <QFileInfo>
#include <algorithm>

#include <QElapsedTimer>
#include <QInputDialog>
#include <QVBoxLayout>
#include <QListWidget>
#include <QDir>
#include <QFormLayout>
#include <QDialogButtonBox>
#include <QDialog>
#include <QMenu>
#include <QSignalBlocker>
#include <cmath>
#include <QLocale>
#include <QComboBox>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLineEdit>
#include <QTreeWidgetItem>
#include <QJsonObject>
#include <QMenuBar>
#include <QMessageBox>
#include <QStatusBar>

#include "Cuts.h"
#include "ElementBatch.h"
#include "HistoryPanel.h"
#include "LevelsBar.h"
#include "HostTool.h"
#include "PolygonTool.h"
#include "GripTool.h"
#include "RotateTool.h"
#include "TwoPointTool.h"
#include "WallTool.h"
#include "MeshChunk.h"
#include "ModelLoader.h"
#include "ModelTreePanel.h"
#include "PropertiesPanel.h"
#include "PythonEngine.h"
#include "Viewport.h"

namespace kimcad {

namespace {
// Adds the time spent in a scope to a named counter.
struct StepTimer {
    QHash<QString, double>& into;
    const char* name;
    QElapsedTimer t;
    StepTimer(QHash<QString, double>& h, const char* n) : into(h), name(n) { t.start(); }
    ~StepTimer() { into[QLatin1String(name)] += double(t.nsecsElapsed()) / 1e6; }
};
} // namespace

MainWindow::MainWindow(QWidget* parent, bool quiet, int chunkSize)
    : QMainWindow(parent)
    , m_quiet(quiet)
    , m_viewport(new Viewport(this))
    , m_tree(new ModelTreePanel(this))
    , m_properties(new PropertiesPanel(this))
    , m_loader(new ModelLoader(chunkSize))
{
    qRegisterMetaType<kimcad::MeshChunk>();
    setWindowTitle(QStringLiteral("KIMCAD"));
    resize(1280, 800);
    setCentralWidget(m_viewport);
    buildMenus();
    buildDocks();
    buildCutsToolbar();
    buildModelingToolbar();
    buildProjectToolbar();
    statusBar()->showMessage(tr("Ready"));

    m_loader->moveToThread(&m_thread);
    connect(&m_thread, &QThread::finished, m_loader, &QObject::deleteLater);
    connect(m_loader, &ModelLoader::opened, this, &MainWindow::onOpened);
    connect(m_loader, &ModelLoader::chunkReady, this, &MainWindow::onChunk);
    connect(m_loader, &ModelLoader::finished, this, &MainWindow::onFinished);
    connect(m_loader, &ModelLoader::failed, this, &MainWindow::onFailed);
    m_thread.start();

    // Selection sync: viewport -> tree + properties, tree -> viewport + properties.
    connect(m_viewport, &Viewport::selectionChanged, this, [this](const QStringList& guids) {
        m_tree->selectGuids(guids);
        setSelection(guids);
    });
    connect(m_tree, &ModelTreePanel::guidsSelected, this, [this](const QStringList& guids) {
        m_viewport->selectGuids(guids);
        setSelection(guids);
    });
    connect(m_properties, &PropertiesPanel::propertyEdited, this, &MainWindow::applyPropertyEdit);
    connect(m_properties, &PropertiesPanel::nameEdited, this, &MainWindow::applyName);
    connect(m_properties, &PropertiesPanel::propertyRemoved, this, &MainWindow::removeProperty);
    connect(m_properties, &PropertiesPanel::addPropertyRequested, this, &MainWindow::addPropertyDialog);
    connect(m_properties, &PropertiesPanel::addPropertySetRequested, this, &MainWindow::addPropertySetDialog);
    connect(m_properties, &PropertiesPanel::typeEditRequested, this, &MainWindow::typeEditDialog);
    connect(m_properties, &PropertiesPanel::resetToTypeRequested, this, &MainWindow::resetToType);
    connect(m_tree, &ModelTreePanel::isolateRequested, m_viewport, &Viewport::isolate);
    connect(m_tree, &ModelTreePanel::hideRequested, this, [this](const QStringList& g) { m_viewport->setHidden(g, true); });
    connect(m_tree, &ModelTreePanel::showAllRequested, m_viewport, &Viewport::showAll);

    QString error;
    if (!PythonEngine::instance().start(&error))
        showError(tr("KIMCAD cannot start"), error);
}

MainWindow::~MainWindow()
{
    stopLoading();
    m_thread.quit();
    m_thread.wait();
}

void MainWindow::buildMenus()
{
    QMenu* file = menuBar()->addMenu(tr("&File"));
    QAction* newProjectAction = file->addAction(tr("&New project"));
    newProjectAction->setObjectName(QStringLiteral("actionNewProject"));
    newProjectAction->setShortcut(QKeySequence::New);
    connect(newProjectAction, &QAction::triggered, this, [this] { newProject(); });
    QAction* open = file->addAction(tr("&Open IFC..."));
    open->setShortcut(QKeySequence::Open);
    connect(open, &QAction::triggered, this, &MainWindow::openDialog);
    QAction* openProjectAction = file->addAction(tr("Open &project..."));
    openProjectAction->setObjectName(QStringLiteral("actionOpenProject"));
    connect(openProjectAction, &QAction::triggered, this, &MainWindow::openProjectDialog);
    QAction* saveAction = file->addAction(tr("&Save"));
    saveAction->setObjectName(QStringLiteral("actionSave"));
    saveAction->setShortcut(QKeySequence::Save);
    connect(saveAction, &QAction::triggered, this, [this] { save(); });
    QAction* saveAs = file->addAction(tr("Save &As..."));
    saveAs->setObjectName(QStringLiteral("actionSaveAs"));
    saveAs->setShortcut(QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_S));
    connect(saveAs, &QAction::triggered, this, &MainWindow::saveAsDialog);
    file->addSeparator();
    QAction* enable = file->addAction(tr("Enable &versioning..."));
    enable->setObjectName(QStringLiteral("actionEnableVersioning"));
    connect(enable, &QAction::triggered, this, &MainWindow::enableVersioningDialog);
    QAction* saveVersionAction = file->addAction(tr("Save &version..."));
    saveVersionAction->setObjectName(QStringLiteral("actionSaveVersion"));
    saveVersionAction->setShortcut(QKeySequence(Qt::CTRL | Qt::ALT | Qt::Key_S));
    connect(saveVersionAction, &QAction::triggered, this, &MainWindow::saveVersionDialog);
    file->addSeparator();
    QAction* quit = file->addAction(tr("&Quit"));
    quit->setShortcut(QKeySequence::Quit);
    connect(quit, &QAction::triggered, this, &QWidget::close);

    QMenu* editMenu = menuBar()->addMenu(tr("&Edit"));
    m_undo = editMenu->addAction(tr("&Undo"));
    m_undo->setObjectName(QStringLiteral("actionUndo"));
    m_undo->setShortcut(QKeySequence::Undo);
    m_undo->setEnabled(false);
    connect(m_undo, &QAction::triggered, this, [this] { afterEdit(bridge("undo")); });
    m_redo = editMenu->addAction(tr("&Redo"));
    m_redo->setObjectName(QStringLiteral("actionRedo"));
    m_redo->setShortcuts({QKeySequence(Qt::CTRL | Qt::Key_Y), QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_Z)});
    m_redo->setEnabled(false);
    connect(m_redo, &QAction::triggered, this, [this] { afterEdit(bridge("redo")); });
    editMenu->addSeparator();
    QAction* del = editMenu->addAction(tr("&Delete"));
    del->setObjectName(QStringLiteral("actionDelete"));
    del->setShortcut(QKeySequence::Delete);
    connect(del, &QAction::triggered, this, &MainWindow::deleteSelection);

    QMenu* view = menuBar()->addMenu(tr("&View"));
    QAction* planView = view->addAction(tr("&Plan view"));
    planView->setObjectName(QStringLiteral("actionPlanView"));
    planView->setShortcut(Qt::Key_P);
    connect(planView, &QAction::triggered, this, [this] { setPlanView(true); });
    QAction* view3D = view->addAction(tr("&3D view"));
    view3D->setObjectName(QStringLiteral("action3DView"));
    view3D->setShortcut(Qt::Key_3);
    connect(view3D, &QAction::triggered, this, [this] { setPlanView(false); });
    QAction* through = view->addAction(tr("Select &hidden elements too"));
    through->setObjectName(QStringLiteral("actionSelectThrough"));
    through->setCheckable(true);
    through->setToolTip(tr("Box selection also takes elements hidden behind others (same as holding Alt while dragging)"));
    connect(through, &QAction::toggled, m_viewport, &Viewport::setSelectThrough);
    QAction* linesOnly = view->addAction(tr("&Lines only"));
    linesOnly->setObjectName(QStringLiteral("actionLinesOnly"));
    linesOnly->setShortcut(Qt::Key_L);
    linesOnly->setCheckable(true);
    linesOnly->setToolTip(tr("Show the model as a line drawing (hidden lines removed), e.g. for plans"));
    connect(linesOnly, &QAction::toggled, m_viewport, &Viewport::setLinesOnly);
    view->addSeparator();
    QAction* fit = view->addAction(tr("&Fit all"));
    fit->setShortcut(Qt::Key_F);
    connect(fit, &QAction::triggered, m_viewport, &Viewport::fitAll);
    view->addSeparator();
    QAction* hide = view->addAction(tr("&Hide selected"));
    hide->setObjectName(QStringLiteral("actionHideSelected"));
    hide->setShortcut(Qt::Key_H);
    connect(hide, &QAction::triggered, this, [this] { m_viewport->setHidden(m_viewport->selectedGuids(), true); });
    QAction* isolate = view->addAction(tr("&Isolate selected"));
    isolate->setObjectName(QStringLiteral("actionIsolateSelected"));
    isolate->setShortcut(Qt::Key_I);
    connect(isolate, &QAction::triggered, this, [this] {
        const QStringList selected = m_viewport->selectedGuids();
        if (!selected.isEmpty())
            m_viewport->isolate(selected);
    });
    QAction* showAll = view->addAction(tr("&Show all"));
    showAll->setObjectName(QStringLiteral("actionShowAll"));
    showAll->setShortcut(Qt::SHIFT | Qt::Key_H);
    connect(showAll, &QAction::triggered, m_viewport, &Viewport::showAll);
    view->addSeparator();
    m_planCut = view->addAction(tr("&Plan cut"));
    m_planCut->setObjectName(QStringLiteral("actionPlanCut"));
    m_planCut->setCheckable(true);
    m_planCut->setShortcut(Qt::Key_C);
    connect(m_planCut, &QAction::toggled, this, &MainWindow::applyCuts);
    m_sectionBox = view->addAction(tr("Section &box"));
    m_sectionBox->setObjectName(QStringLiteral("actionSectionBox"));
    m_sectionBox->setCheckable(true);
    m_sectionBox->setShortcut(Qt::Key_B);
    connect(m_sectionBox, &QAction::toggled, this, [this](bool on) {
        if (on) { // box around the selection, or around everything visible
            m_boxBounds = m_viewport->boundsOf(m_viewport->selectedGuids());
            if (!m_boxBounds.IsVoid())
                m_boxBounds.Enlarge(0.1);
        }
        applyCuts();
    });

    QMenu* help = menuBar()->addMenu(tr("&Help"));
    QAction* about = help->addAction(tr("&About KIMCAD"));
    connect(about, &QAction::triggered, this, &MainWindow::showAbout);
}

void MainWindow::buildDocks()
{
    auto* treeDock = new QDockWidget(tr("Model"), this);
    treeDock->setObjectName(QStringLiteral("ModelDock"));
    treeDock->setWidget(m_tree);
    addDockWidget(Qt::LeftDockWidgetArea, treeDock);
    auto* propsDock = new QDockWidget(tr("Properties"), this);
    propsDock->setObjectName(QStringLiteral("PropertiesDock"));
    propsDock->setWidget(m_properties);
    addDockWidget(Qt::RightDockWidgetArea, propsDock);
    m_history = new HistoryPanel(this);
    auto* historyDock = new QDockWidget(tr("History"), this);
    historyDock->setObjectName(QStringLiteral("HistoryDock"));
    historyDock->setWidget(m_history);
    addDockWidget(Qt::RightDockWidgetArea, historyDock);
    tabifyDockWidget(propsDock, historyDock);
    propsDock->raise();
    connect(m_history, &HistoryPanel::compareRequested, this, [this](const QString& a, const QString& b) { compareWith(a, b); });
    connect(m_history, &HistoryPanel::endCompareRequested, this, &MainWindow::endCompare);
    connect(m_history, &HistoryPanel::elementActivated, this, [this](const QString& guid) {
        m_viewport->selectGuids({guid});
        m_tree->selectGuids({guid});
        setSelection({guid});
    });
    resizeDocks({treeDock, propsDock}, {340, 360}, Qt::Horizontal);
}

void MainWindow::buildCutsToolbar()
{
    QToolBar* levels = addToolBar(tr("Levels"));
    levels->setObjectName(QStringLiteral("levelsToolbar"));
    m_levels = new LevelsBar(levels);
    levels->addWidget(m_levels);
    connect(m_levels, &LevelsBar::addLevelRequested, this, &MainWindow::addLevelDialog);
    connect(m_levels, &LevelsBar::activeStoreyChanged, this, [this](const QString&, double elevation) {
        if (m_viewport->isPlanView())
            m_viewport->setPlanView(elevation);
        if (m_viewport->isDrawingMode()) {
            m_wallTool->finish();
            m_polygonTool->cancel();
            m_viewport->setDrawingMode(true, elevation);
            refreshSnapData();
        }
        applyCuts();
    });
    QToolBar* bar = addToolBar(tr("Cuts"));
    bar->setObjectName(QStringLiteral("CutsToolbar"));
    bar->addAction(m_planCut);
    m_cutHeight = new QDoubleSpinBox(bar);
    m_cutHeight->setObjectName(QStringLiteral("planCutHeight"));
    m_cutHeight->setRange(-1000.0, 10000.0);
    m_cutHeight->setDecimals(2);
    m_cutHeight->setSingleStep(0.1);
    m_cutHeight->setSuffix(QStringLiteral(" m"));
    m_cutHeight->setValue(1.2); // typical plan cut height above a floor
    m_cutHeight->setToolTip(tr("Plan cut height"));
    bar->addWidget(m_cutHeight);
    connect(m_cutHeight, &QDoubleSpinBox::valueChanged, this, [this] {
        if (m_planCut->isChecked())
            applyCuts();
    });
    bar->addSeparator();
    bar->addAction(m_sectionBox);
}

void MainWindow::setPlanCutHeight(double metres)
{
    m_cutHeight->setValue(metres);
}

void MainWindow::applyCuts()
{
    CutState state;
    state.planCut = m_planCut->isChecked();
    // The cut height is measured from the active level (like a plan's view range).
    state.height = (m_levels ? m_levels->activeElevation() : 0.0) + m_cutHeight->value();
    state.box = m_sectionBox->isChecked();
    state.bounds = m_boxBounds;
    m_viewport->clearClipPlanes();
    m_viewport->addClipPlanes(makePlanes(state));
}

void MainWindow::showAbout()
{
    QMessageBox::about(this, tr("About KIMCAD"),
        tr("KIMCAD %1\nOpen-source native BIM for architects, with version control built in.\n"
           "License: GPL-3.0-or-later")
            .arg(QStringLiteral(KIMCAD_VERSION)));
}

void MainWindow::showError(const QString& title, const QString& message)
{
    statusBar()->showMessage(message);
    if (!m_quiet)
        QMessageBox::critical(this, title, message);
}

void MainWindow::openDialog()
{
    if (!maybeSave())
        return;
    const QString path = QFileDialog::getOpenFileName(this, tr("Open IFC"), QString(), tr("IFC files (*.ifc)"));
    if (!path.isEmpty())
        openFile(path);
}

void MainWindow::openFile(const QString& path)
{
    stopLoading();
    m_viewport->clear();
    m_tree->clear();
    m_properties->clear();
    m_selection.clear();
    m_path = path;
    m_loading = true;
    m_loadedElements = 0;
    m_loadTimer.start();
    statusBar()->showMessage(tr("Opening %1...").arg(QFileInfo(path).fileName()));
    m_loader->reset();
    QMetaObject::invokeMethod(m_loader, "load", Qt::QueuedConnection, Q_ARG(QString, path));
}

void MainWindow::stopLoading()
{
    if (!m_loading)
        return;
    m_loader->requestStop();
    // The loader stops after its current chunk; drain its queued signals so they don't hit a new model.
    while (m_loading)
        QApplication::processEvents(QEventLoop::AllEvents, 50);
}

void MainWindow::closeEvent(QCloseEvent* event)
{
    if (!maybeSave()) {
        event->ignore();
        return;
    }
    stopLoading();
    event->accept();
}

QJsonObject MainWindow::bridge(const char* fn, const QStringList& args)
{
    QString error;
    QJsonObject r = PythonEngine::instance().callJson(fn, args, &error).object();
    if (r.isEmpty() && !error.isEmpty())
        r = QJsonObject{{"ok", false}, {"error", error}};
    return r;
}

namespace {

QString jsonList(const QStringList& list)
{
    return QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(list)).toJson(QJsonDocument::Compact));
}

// One JSON value as text: serialize a one-element array and strip the brackets.
QString jsonValue(const QJsonValue& v)
{
    return QString::fromUtf8(QJsonDocument(QJsonArray{v}).toJson(QJsonDocument::Compact)).mid(1).chopped(1);
}

} // namespace

void MainWindow::setSelection(const QStringList& guids)
{
    m_selection = guids;
    refreshProperties();
    if (!guids.isEmpty())
        statusBar()->showMessage(tr("%n element(s) selected", nullptr, int(guids.size())));
}

void MainWindow::refreshProperties()
{
    if (m_selection.isEmpty()) {
        m_properties->clear();
        return;
    }
    m_properties->showMulti(bridge("properties_multi", {jsonList(m_selection)}));
}

bool MainWindow::applyPropertyEdit(const QString& pset, const QString& prop, const QJsonValue& value)
{
    if (m_selection.isEmpty())
        return false;
    const QJsonObject r = bridge("set_property", {jsonList(m_selection), pset, prop, jsonValue(value)});
    if (!r.value("ok").toBool())
        showError(tr("Could not change %1").arg(prop), r.value("error").toString());
    afterEdit(r);
    return r.value("ok").toBool();
}

bool MainWindow::applyName(const QString& name)
{
    if (m_selection.isEmpty())
        return false;
    const QJsonObject r = bridge("set_name", {jsonList(m_selection), name});
    afterEdit();
    return r.value("ok").toBool();
}

bool MainWindow::removeProperty(const QString& pset, const QString& prop)
{
    if (m_selection.isEmpty())
        return false;
    const QJsonObject r = bridge("remove_property", {jsonList(m_selection), pset, prop});
    afterEdit();
    return r.value("ok").toBool();
}

bool MainWindow::applyTypeEdit(const QString& pset, const QString& prop, const QJsonValue& value)
{
    if (m_selection.isEmpty())
        return false;
    const QJsonObject r = bridge("set_type_property", {jsonList(m_selection), pset, prop, jsonValue(value)});
    if (!r.value("ok").toBool())
        showError(tr("Could not change %1").arg(prop), r.value("error").toString());
    else
        statusBar()->showMessage(tr("%1 changed on the type: %n element(s) updated", nullptr, r.value("elements").toInt()).arg(prop));
    afterEdit();
    return r.value("ok").toBool();
}

bool MainWindow::resetToType(const QString& pset, const QString& prop)
{
    if (m_selection.isEmpty())
        return false;
    const QJsonObject r = bridge("reset_to_type", {jsonList(m_selection), pset, prop});
    afterEdit();
    return r.value("ok").toBool();
}

void MainWindow::typeEditDialog(const QString& pset, const QString& prop)
{
    const QJsonObject usage = bridge("type_usage", {jsonList(m_selection), pset, prop});
    QStringList typeNames;
    for (const auto& t : usage.value("types").toArray())
        typeNames << t.toObject().value("name").toString();
    if (typeNames.isEmpty())
        return;
    QTreeWidgetItem* item = m_properties->itemFor(pset, prop);
    const QString current = item && item->text(1) != m_properties->variesText() ? item->text(1) : QString();
    bool ok = false;
    const QString value = QInputDialog::getText(this, tr("Edit type value"),
        tr("%1 on type %2:").arg(prop, typeNames.join(QStringLiteral(", "))), QLineEdit::Normal, current, &ok);
    if (!ok)
        return;
    QString message = tr("This changes %1 for %n element(s) of this type, including elements that are not selected.",
        nullptr, usage.value("elements").toInt()).arg(prop);
    if (const int untyped = usage.value("untyped").toInt())
        message += QStringLiteral("\n") + tr("%n selected element(s) have no type and will not change.", nullptr, untyped);
    if (!m_quiet
        && QMessageBox::question(this, tr("Edit type value"), message, QMessageBox::Ok | QMessageBox::Cancel)
            != QMessageBox::Ok)
        return;
    applyTypeEdit(pset, prop, QJsonValue(value));
}

bool MainWindow::newProject()
{
    if (!maybeSave())
        return false;
    stopLoading();
    const QJsonObject r = bridge("new_project", {tr("Untitled")});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not create the project"), r.value("error").toString());
        return false;
    }
    m_viewport->clear();
    m_properties->clear();
    m_selection.clear();
    m_path.clear();
    m_tree->setTree(bridge("spatial_tree"));
    refreshLevels();
    m_types->clear();
    m_warnedInconsistent = false;
    setWindowTitle(QStringLiteral("KIMCAD — %1[*]").arg(tr("Untitled")));
    afterEdit();
    refreshProject();
    statusBar()->showMessage(tr("New project"));
    return true;
}

void MainWindow::refreshLevels()
{
    const int before = m_levels->count();
    m_levels->setStoreys(bridge("storeys").value("storeys").toArray());
    if (before != m_levels->count() && before > 0)
        m_tree->refreshTree(bridge("spatial_tree")); // a level was added or undone
}

bool MainWindow::addLevel(const QString& name, double elevation)
{
    const QJsonObject r = bridge("add_storey", {name, QString::number(elevation, 'g', 17)});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not add the level"), r.value("error").toString());
        return false;
    }
    afterEdit(r);
    m_levels->setActive(r.value("guid").toString());
    return true;
}

void MainWindow::addLevelDialog()
{
    double highest = 0.0;
    bool any = false;
    for (const auto& s : bridge("storeys").value("storeys").toArray()) {
        highest = any ? std::max(highest, s.toObject().value("elevation").toDouble()) : s.toObject().value("elevation").toDouble();
        any = true;
    }
    bool ok = false;
    const QString name = QInputDialog::getText(this, tr("Add level"), tr("Name:"), QLineEdit::Normal,
        tr("Level %1").arg(m_levels->count() + 1), &ok);
    if (!ok || name.trimmed().isEmpty())
        return;
    const double elevation = QInputDialog::getDouble(this, tr("Add level"), tr("Elevation (m):"),
        any ? highest + 3.0 : 0.0, -1000.0, 10000.0, 2, &ok);
    if (ok)
        addLevel(name.trimmed(), elevation);
}

void MainWindow::setPlanView(bool plan)
{
    if (plan) {
        m_viewport->setPlanView(m_levels->activeElevation());
        m_planCut->setChecked(true); // a plan is a horizontal cut
    } else {
        m_viewport->set3DView();
    }
    applyCuts();
}

void MainWindow::buildModelingToolbar()
{
    QToolBar* bar = addToolBar(tr("Modeling"));
    bar->setObjectName(QStringLiteral("modelingToolbar"));
    QMenu* model = menuBar()->addMenu(tr("&Model"));
    m_wallTool = new WallTool(this);
    m_polygonTool = new PolygonTool(this);
    m_hostTool = new HostTool(this);
    m_twoPointTool = new TwoPointTool(this);
    m_rotateTool = new RotateTool(this);
    m_gripTool = new GripTool(this);

    struct Def {
        Tool tool;
        const char* name;
        QString text;
        Qt::Key key;
        QString tip;
    };
    const Def defs[] = {
        {Tool::Wall, "actionWallTool", tr("&Wall"), Qt::Key_W,
            tr("Draw walls: click points, type a length + Enter, Esc to finish. Shift: right angles.")},
        {Tool::Slab, "actionSlabTool", tr("&Slab"), Qt::Key_S,
            tr("Draw a slab outline: click points, click the first point or press Enter to close, Esc to cancel")},
        {Tool::Door, "actionDoorTool", tr("&Door"), Qt::Key_D, tr("Place doors: click on a wall")},
        {Tool::Window, "actionWindowTool", tr("Wi&ndow"), Qt::Key_N, tr("Place windows: click on a wall")},
        {Tool::Column, "actionColumnTool", tr("&Column"), Qt::Key_K,
            tr("Place columns: click a point (snaps to grid crossings); Shift turns it 90 degrees")},
        {Tool::Beam, "actionBeamTool", tr("&Beam"), Qt::Key_J,
            tr("Draw a beam: click its two ends; its top is at the level plus the height field")},
        {Tool::Grid, "actionGridTool", tr("&Grid line"), Qt::Key_G,
            tr("Draw a grid line: click its two ends (tags A, B... and 1, 2... are automatic)")},
        {Tool::Move, "actionMoveTool", tr("&Move"), Qt::Key_M,
            tr("Move the selection: click a base point, then where it goes; joined walls follow (Ctrl: detach)")},
        {Tool::Rotate, "actionRotateTool", tr("&Rotate"), Qt::Key_R,
            tr("Rotate the selection: click the centre, a reference, then the new direction (or type degrees)")},
        {Tool::Stretch, "actionStretchTool", tr("S&tretch wall"), Qt::Key_E,
            tr("Stretch a wall: click near one of its ends, then click its new position (or type the length)")},
        {Tool::Stair, "actionStairTool", tr("S&tair"), Qt::Key_T,
            tr("Draw a stair: click where it starts, then the direction it climbs; it goes up to the next level")},
        {Tool::SlabOpening, "actionSlabOpeningTool", tr("Slab &opening"), Qt::Key_O,
            tr("Cut a hole in the selected slab: draw its outline like a slab")},
    };
    for (const Def& d : defs) {
        QAction* a = bar->addAction(d.text);
        a->setObjectName(QLatin1String(d.name));
        a->setShortcut(d.key);
        a->setCheckable(true);
        a->setToolTip(d.tip);
        model->addAction(a);
        const Tool tool = d.tool;
        connect(a, &QAction::triggered, this, [this, tool](bool on) { setTool(on ? tool : Tool::None); });
        m_toolActions.insert(int(d.tool), a);
    }
    model->addSeparator();
    QAction* copyAction = model->addAction(tr("Copy to &level..."));
    copyAction->setObjectName(QStringLiteral("actionCopyToLevel"));
    connect(copyAction, &QAction::triggered, this, &MainWindow::copyToLevelDialog);
    QAction* heightAction = model->addAction(tr("Wall &height..."));
    heightAction->setObjectName(QStringLiteral("actionWallHeight"));
    connect(heightAction, &QAction::triggered, this, &MainWindow::wallHeightDialog);
    QAction* sizeAction = model->addAction(tr("Door/window si&ze..."));
    sizeAction->setObjectName(QStringLiteral("actionOpeningSize"));
    connect(sizeAction, &QAction::triggered, this, &MainWindow::openingSizeDialog);
    QAction* slabFromWallsAction = model->addAction(tr("Slab from selected &walls"));
    slabFromWallsAction->setObjectName(QStringLiteral("actionSlabFromWalls"));
    connect(slabFromWallsAction, &QAction::triggered, this, [this] { slabFromWalls(m_selection); });

    m_types = new QComboBox(bar);
    m_types->setObjectName(QStringLiteral("typeCombo"));
    m_types->setToolTip(tr("Type"));
    m_types->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    m_types->setMinimumContentsLength(16);
    bar->addWidget(m_types);
    connect(m_types, &QComboBox::currentIndexChanged, this, [this] {
        m_hostTool->setWidth(currentType().value("width").toDouble(0.9));
        updateToolPreview();
    });
    m_wallHeight = new QDoubleSpinBox(bar);
    m_wallHeight->setObjectName(QStringLiteral("wallHeight"));
    m_wallHeight->setRange(0.1, 100.0);
    m_wallHeight->setDecimals(2);
    m_wallHeight->setSingleStep(0.1);
    m_wallHeight->setValue(3.0);
    m_wallHeight->setSuffix(QStringLiteral(" m"));
    m_wallHeight->setToolTip(tr("Wall height"));
    m_wallHeightAction = bar->addWidget(m_wallHeight);
    m_lengthInput = new QLineEdit(bar);
    m_lengthInput->setObjectName(QStringLiteral("lengthInput"));
    m_lengthInput->setPlaceholderText(tr("Length (m)"));
    m_lengthInput->setMaximumWidth(110);
    m_lengthAction = bar->addWidget(m_lengthInput);
    connect(m_lengthInput, &QLineEdit::returnPressed, this, [this] {
        bool ok = false;
        double value = QLocale().toDouble(m_lengthInput->text(), &ok);
        if (!ok)
            value = QLocale::c().toDouble(QString(m_lengthInput->text()).replace(QLatin1Char(','), QLatin1Char('.')), &ok);
        bool typed = false;
        if (m_tool == Tool::Wall)
            typed = m_wallTool->typeLength(value);
        else if (ok && m_tool == Tool::Rotate)
            typed = m_rotateTool->typeAngle(value); // degrees
        else if (ok && m_tool == Tool::Stretch)
            typed = m_gripTool->typeLength(value);
        else if (ok)
            typed = m_twoPointTool->typeLength(value);
        if (ok && typed)
            m_lengthInput->clear();
        m_viewport->setFocus();
    });
    setTool(Tool::None);

    connect(m_viewport, &Viewport::workPointMoved, this, [this](QPointF p, double tolerance, Qt::KeyboardModifiers mods) {
        const bool ortho = mods & Qt::ShiftModifier;
        switch (m_tool) {
        case Tool::Wall:
            m_wallTool->setTolerance(tolerance);
            m_wallTool->setOrtho(ortho);
            showSnap(m_wallTool->move(p));
            break;
        case Tool::Slab:
            m_polygonTool->setTolerance(tolerance);
            m_polygonTool->setOrtho(ortho);
            m_polygonTool->move(p);
            break;
        case Tool::Door:
        case Tool::Window:
            m_hostTool->setTolerance(tolerance);
            m_hostTool->move(p);
            break;
        case Tool::Beam:
        case Tool::Grid:
        case Tool::Stair:
            m_twoPointTool->setTolerance(tolerance);
            m_twoPointTool->setOrtho(ortho);
            showSnap(m_twoPointTool->move(p));
            break;
        case Tool::SlabOpening:
            m_polygonTool->setTolerance(tolerance);
            m_polygonTool->setOrtho(ortho);
            m_polygonTool->move(p);
            break;
        case Tool::Column:
            m_twoPointTool->setTolerance(tolerance);
            m_columnHover = m_twoPointTool->snapper().snap(p, tolerance).point;
            updateToolPreview();
            break;
        case Tool::Move:
            m_twoPointTool->setTolerance(tolerance);
            m_twoPointTool->setOrtho(ortho);
            m_twoPointTool->move(p);
            break;
        case Tool::Rotate:
            m_rotateTool->setTolerance(tolerance);
            m_rotateTool->setOrtho(ortho);
            m_rotateTool->move(p);
            break;
        case Tool::Stretch:
            m_gripTool->setTolerance(tolerance);
            m_gripTool->setOrtho(ortho);
            m_gripTool->move(p);
            break;
        case Tool::None:
            break;
        }
    });
    connect(m_viewport, &Viewport::workPointClicked, this, [this](QPointF p, double tolerance, Qt::KeyboardModifiers mods) {
        const bool ortho = mods & Qt::ShiftModifier;
        switch (m_tool) {
        case Tool::Wall:
            m_wallTool->setTolerance(tolerance);
            m_wallTool->setOrtho(ortho);
            m_wallTool->click(p);
            break;
        case Tool::Slab:
            m_polygonTool->setTolerance(tolerance);
            m_polygonTool->setOrtho(ortho);
            m_polygonTool->click(p);
            break;
        case Tool::Door:
        case Tool::Window:
            m_hostTool->setTolerance(tolerance);
            m_hostTool->click(p);
            break;
        case Tool::Beam:
        case Tool::Grid:
        case Tool::Stair:
            m_twoPointTool->setTolerance(tolerance);
            m_twoPointTool->setOrtho(ortho);
            m_twoPointTool->click(p);
            break;
        case Tool::SlabOpening:
            m_polygonTool->setTolerance(tolerance);
            m_polygonTool->setOrtho(ortho);
            m_polygonTool->click(p);
            break;
        case Tool::Column:
            m_twoPointTool->setTolerance(tolerance);
            columnAt(p, ortho);
            break;
        case Tool::Move:
            m_detach = mods & Qt::ControlModifier;
            m_twoPointTool->setTolerance(tolerance);
            m_twoPointTool->setOrtho(ortho);
            m_twoPointTool->click(p);
            break;
        case Tool::Rotate:
            m_detach = mods & Qt::ControlModifier;
            m_rotateTool->setTolerance(tolerance);
            m_rotateTool->setOrtho(ortho);
            m_rotateTool->click(p);
            break;
        case Tool::Stretch:
            m_gripTool->setTolerance(tolerance);
            m_gripTool->setOrtho(ortho);
            m_gripTool->click(p);
            break;
        case Tool::None:
            break;
        }
    });
    connect(m_viewport, &Viewport::drawingEnded, this, [this] {
        // Esc / right click: stop the current shape, or leave the tool when nothing is in progress.
        if (m_tool == Tool::Wall && m_wallTool->isDrawing())
            m_wallTool->finish();
        else if ((m_tool == Tool::Slab || m_tool == Tool::SlabOpening) && m_polygonTool->isDrawing())
            m_polygonTool->cancel();
        else if ((m_tool == Tool::Beam || m_tool == Tool::Grid || m_tool == Tool::Move || m_tool == Tool::Stair)
            && m_twoPointTool->isDrawing())
            m_twoPointTool->cancel();
        else if (m_tool == Tool::Rotate && m_rotateTool->stage() > 0)
            m_rotateTool->cancel();
        else if (m_tool == Tool::Stretch && m_gripTool->isDragging())
            m_gripTool->cancel();
        else
            setTool(Tool::None);
    });
    connect(m_viewport, &Viewport::drawingConfirmed, this, [this] {
        if (m_tool == Tool::Wall)
            m_wallTool->finish();
        else if (m_tool == Tool::Slab || m_tool == Tool::SlabOpening)
            m_polygonTool->finish();
    });
    connect(m_viewport, &Viewport::lengthKeyTyped, this, [this](const QString& text) {
        if (!m_lengthAction->isVisible())
            return;
        m_lengthInput->setFocus();
        m_lengthInput->insert(text);
    });
    connect(m_wallTool, &WallTool::previewChanged, this, &MainWindow::updateToolPreview);
    connect(m_polygonTool, &PolygonTool::previewChanged, this, &MainWindow::updateToolPreview);
    connect(m_hostTool, &HostTool::previewChanged, this, &MainWindow::updateToolPreview);
    connect(m_twoPointTool, &TwoPointTool::previewChanged, this, &MainWindow::updateToolPreview);
    connect(m_twoPointTool, &TwoPointTool::segmentFinished, this, [this](QPointF a, QPointF b) {
        if (m_tool == Tool::Move)
            moveSelection(b - a, m_detach);
        else if (m_tool == Tool::Stair)
            createStair(a, b);
        else
            createSegment(a, b);
    });
    connect(m_rotateTool, &RotateTool::previewChanged, this, &MainWindow::updateToolPreview);
    connect(m_gripTool, &GripTool::previewChanged, this, &MainWindow::updateToolPreview);
    connect(m_rotateTool, &RotateTool::rotationFinished, this, [this](QPointF c, double a) { rotateSelection(c, a, m_detach); });
    connect(m_gripTool, &GripTool::stretchRequested, this, &MainWindow::stretchWall);
    connect(m_wallTool, &WallTool::wallRequested, this, &MainWindow::createWall);
    connect(m_polygonTool, &PolygonTool::polygonFinished, this, [this](const QVector<QPointF>& outline) {
        if (m_tool == Tool::SlabOpening)
            addSlabOpening(outline);
        else
            createSlab(outline);
    });
    connect(m_polygonTool, &PolygonTool::rejected, this, [this](const QString& why) { statusBar()->showMessage(why); });
    connect(m_hostTool, &HostTool::openingRequested, this, &MainWindow::insertOpening);
}

QJsonObject MainWindow::currentType() const
{
    return m_types->currentData().toJsonObject();
}

void MainWindow::refreshTypes()
{
    const char* source = nullptr;
    QStringList args;
    switch (m_tool) {
    case Tool::Wall:
        source = "wall_types";
        break;
    case Tool::Slab:
        source = "slab_types";
        break;
    case Tool::Door:
        source = "opening_types";
        args << QStringLiteral("door");
        break;
    case Tool::Window:
        source = "opening_types";
        args << QStringLiteral("window");
        break;
    case Tool::Column:
        source = "column_types";
        break;
    case Tool::Beam:
        source = "beam_types";
        break;
    case Tool::Grid:
    case Tool::None:
        break;
    }
    const QString current = currentType().value("guid").toString();
    const QSignalBlocker block(m_types);
    m_types->clear();
    if (!source)
        return;
    for (const auto& t : bridge(source, args).value("types").toArray()) {
        const QJsonObject o = t.toObject();
        m_types->addItem(o.value("name").toString(), o);
        if (o.value("guid").toString() == current)
            m_types->setCurrentIndex(m_types->count() - 1);
    }
    m_hostTool->setWidth(currentType().value("width").toDouble(0.9));
}

void MainWindow::refreshSnapData()
{
    const QJsonObject data = bridge("snap_data", {m_levels->activeStorey()});
    const QVector<SnapWall> walls = Snapper::parse(data);
    const QVector<SnapLine> lines = Snapper::parseGrid(data);
    for (Snapper* s : {&m_wallTool->snapper(), &m_polygonTool->snapper(), &m_twoPointTool->snapper(),
             &m_rotateTool->snapper(), &m_gripTool->snapper()}) {
        s->setWalls(walls);
        s->setGridLines(lines);
    }
    m_hostTool->setWalls(walls);
    QVector<Viewport::GridLine> shown;
    for (const SnapLine& l : lines)
        shown.push_back({l.a, l.b, l.tag});
    m_viewport->setGridLines(shown, m_levels->activeElevation());
}

void MainWindow::updateToolPreview()
{
    const double z = m_levels ? m_levels->activeElevation() : 0.0;
    const QJsonObject type = currentType();
    QVector<Viewport::PreviewBox> boxes;
    switch (m_tool) {
    case Tool::Wall:
        m_viewport->setWallPreview(m_wallTool->preview(), type.value("thickness").toDouble(), m_wallHeight->value());
        return;
    case Tool::Stair:
        if (const auto seg = m_twoPointTool->preview())
            boxes.push_back({seg->first, seg->second, 1.0, z, z + heightToNextLevel()});
        break;
    case Tool::SlabOpening:
    case Tool::Slab: {
        // The outline as thin walls of the slab's depth, its top at the level.
        QVector<QPointF> pts = m_polygonTool->points();
        if (const auto hover = m_polygonTool->hover(); hover && !pts.isEmpty())
            pts << *hover;
        const double depth = std::max(type.value("thickness").toDouble(), 0.05);
        for (int i = 0; i + 1 < pts.size(); ++i)
            boxes.push_back({pts[i], pts[i + 1], 0.05, z - depth, z});
        break;
    }
    case Tool::Column:
        if (m_columnHover) {
            const double w = type.value("width").toDouble(0.3), d = type.value("depth").toDouble(0.3);
            boxes.push_back({*m_columnHover - QPointF(w / 2, 0), *m_columnHover + QPointF(w / 2, 0), d, z, z + m_wallHeight->value()});
        }
        break;
    case Tool::Beam:
        if (const auto seg = m_twoPointTool->preview()) {
            const double top = z + m_wallHeight->value();
            boxes.push_back({seg->first, seg->second, type.value("width").toDouble(0.2), top - type.value("depth").toDouble(0.4), top});
        }
        break;
    case Tool::Grid:
    case Tool::Move:
        if (const auto seg = m_twoPointTool->preview())
            boxes.push_back({seg->first, seg->second, 0.03, z, z + 0.02});
        break;
    case Tool::Rotate:
        if (const auto c = m_rotateTool->centre()) {
            if (const auto r = m_rotateTool->reference())
                boxes.push_back({*c, *r, 0.03, z, z + 0.02});
            if (const auto h = m_rotateTool->hover())
                boxes.push_back({*c, *h, 0.03, z, z + 0.02});
        }
        break;
    case Tool::Stretch:
        if (const auto axis = m_gripTool->preview())
            boxes.push_back({axis->first, axis->second, std::max(m_gripTool->thickness(), 0.05), z, z + m_wallHeight->value()});
        break;
    case Tool::Door:
    case Tool::Window:
        if (const auto host = m_hostTool->hover()) {
            const double w = type.value("width").toDouble(0.9);
            const QPointF u(std::cos(host->angle), std::sin(host->angle));
            const double sill = type.value("sill").toDouble();
            boxes.push_back({host->centre - u * (w / 2), host->centre + u * (w / 2), host->thickness + 0.06,
                z + sill, z + sill + type.value("height").toDouble(2.1)});
        }
        break;
    case Tool::None:
        break;
    }
    m_viewport->setPreviewBoxes(boxes);
}

void MainWindow::showSnap(const Snap& snap)
{
    static const char* const names[] = {"", QT_TR_NOOP("endpoint"), QT_TR_NOOP("midpoint"), QT_TR_NOOP("perpendicular"),
        QT_TR_NOOP("on wall"), QT_TR_NOOP("angle"), QT_TR_NOOP("grid"), QT_TR_NOOP("grid crossing"), QT_TR_NOOP("on grid line")};
    QString text = tr("Wall: click the next point, type a length, Esc to finish");
    const auto preview = m_tool == Tool::Wall ? m_wallTool->preview() : m_twoPointTool->preview();
    if (preview) {
        const QPointF d = preview->second - preview->first;
        text = tr("Length %1 m").arg(QLocale().toString(std::hypot(d.x(), d.y()), 'f', 3));
    }
    if (snap.kind != Snap::None)
        text += QStringLiteral("  ·  ") + tr(names[snap.kind]);
    statusBar()->showMessage(text);
}

void MainWindow::setTool(Tool tool)
{
    if (tool != Tool::None && m_levels->activeStorey().isEmpty()) {
        showError(tr("Cannot model"), tr("The model has no level. Add a level first."));
        tool = Tool::None;
    }
    m_wallTool->finish();
    m_polygonTool->cancel();
    m_twoPointTool->cancel();
    m_rotateTool->cancel();
    m_gripTool->cancel();
    m_columnHover.reset();
    m_tool = tool;
    for (auto it = m_toolActions.constBegin(); it != m_toolActions.constEnd(); ++it) {
        const QSignalBlocker block(it.value());
        it.value()->setChecked(it.key() == int(tool));
    }
    m_wallHeightAction->setVisible(tool == Tool::Wall || tool == Tool::Column || tool == Tool::Beam);
    m_lengthAction->setVisible(tool == Tool::Wall || tool == Tool::Beam || tool == Tool::Grid || tool == Tool::Move
        || tool == Tool::Rotate || tool == Tool::Stretch);
    m_lengthInput->setPlaceholderText(tool == Tool::Rotate ? tr("Angle (degrees)") : tr("Length (m)"));
    const bool typed = tool == Tool::Wall || tool == Tool::Slab || tool == Tool::Door || tool == Tool::Window
        || tool == Tool::Column || tool == Tool::Beam;
    m_types->setVisible(typed);
    const bool needsSlab = tool == Tool::SlabOpening
        && (m_selection.size() != 1 || m_viewport->typeOf(m_selection.first()) != QLatin1String("IfcSlab"));
    if (((tool == Tool::Move || tool == Tool::Rotate) && m_selection.isEmpty()) || needsSlab) {
        statusBar()->showMessage(needsSlab ? tr("Select one slab first, then draw the opening")
                                           : tr("Select something first, then move or rotate it"));
        tool = Tool::None;
        m_tool = tool;
        for (QAction* a : std::as_const(m_toolActions)) {
            const QSignalBlocker block(a);
            a->setChecked(false);
        }
        m_viewport->setDrawingMode(false);
        return;
    }
    refreshTypes();
    if (tool == Tool::None) {
        m_viewport->setDrawingMode(false);
        statusBar()->clearMessage();
        return;
    }
    refreshSnapData();
    m_viewport->setDrawingMode(true, m_levels->activeElevation());
    m_viewport->setFocus();
    switch (tool) {
    case Tool::Wall:
        statusBar()->showMessage(tr("Wall: click the start point"));
        break;
    case Tool::Slab:
        statusBar()->showMessage(tr("Slab: click the outline's points; click the first point or press Enter to close"));
        break;
    case Tool::Column:
        statusBar()->showMessage(tr("Column: click to place it"));
        break;
    case Tool::Beam:
    case Tool::Grid:
        statusBar()->showMessage(tr("Click the first point"));
        break;
    case Tool::Move:
        statusBar()->showMessage(tr("Move: click a base point, then where it goes (Ctrl: detach joined walls)"));
        break;
    case Tool::Rotate:
        statusBar()->showMessage(tr("Rotate: click the centre, then a reference direction, then the new direction"));
        break;
    case Tool::Stretch:
        statusBar()->showMessage(tr("Stretch: click near a wall end, then its new position"));
        break;
    case Tool::Stair:
        statusBar()->showMessage(tr("Stair: click where it starts, then the direction it climbs"));
        break;
    case Tool::SlabOpening:
        statusBar()->showMessage(tr("Slab opening: draw the hole's outline; click the first point or press Enter to close"));
        break;
    default:
        statusBar()->showMessage(tr("Click on a wall to place it"));
        break;
    }
}

bool MainWindow::moveSelection(QPointF delta, bool detach)
{
    if (m_selection.isEmpty())
        return false;
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    // Doors and windows on their own slide along their walls; anything else moves freely.
    bool onlyOpenings = true;
    for (const QString& g : std::as_const(m_selection)) {
        const QString type = m_viewport->typeOf(g);
        if (type != QLatin1String("IfcDoor") && type != QLatin1String("IfcWindow"))
            onlyOpenings = false;
    }
    const QJsonObject r = onlyOpenings
        ? bridge("slide_openings", {jsonList(m_selection), num(delta.x()), num(delta.y())})
        : bridge("move_elements", {jsonList(m_selection), num(delta.x()), num(delta.y()), QStringLiteral("0"),
              detach ? QStringLiteral("1") : QStringLiteral("0")});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not move: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::rotateSelection(QPointF centre, double radians, bool detach)
{
    if (m_selection.isEmpty())
        return false;
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge("rotate_elements", {jsonList(m_selection), num(centre.x()), num(centre.y()), num(radians),
        detach ? QStringLiteral("1") : QStringLiteral("0")});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not rotate: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::stretchWall(const QString& wall, QPointF p1, QPointF p2)
{
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge("set_wall_axis", {wall, num(p1.x()), num(p1.y()), num(p2.x()), num(p2.y())});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not stretch: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::setWallHeight(const QStringList& walls, double height)
{
    const QJsonObject r = bridge("set_wall_height", {jsonList(walls), QString::number(height, 'g', 17)});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not change the height: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

QJsonObject MainWindow::openingInfo(const QString& guid)
{
    for (const auto& o : bridge("snap_data", {m_levels->activeStorey()}).value("openings").toArray())
        if (o.toObject().value("guid").toString() == guid)
            return o.toObject();
    return {};
}

bool MainWindow::resizeOpening(const QString& guid, double width, double height, double sill)
{
    const QJsonObject info = openingInfo(guid);
    if (info.isEmpty()) {
        statusBar()->showMessage(tr("Select one door or window on the active level"));
        return false;
    }
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge("edit_opening", {guid, num(info.value("along").toDouble()), num(width), num(height), num(sill)});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not resize: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

void MainWindow::wallHeightDialog()
{
    QStringList walls;
    for (const QString& g : std::as_const(m_selection))
        if (m_viewport->typeOf(g) == QLatin1String("IfcWall"))
            walls << g;
    if (walls.isEmpty()) {
        statusBar()->showMessage(tr("Select one or more walls first"));
        return;
    }
    bool ok = false;
    const double height = QInputDialog::getDouble(this, tr("Wall height"), tr("Height (m):"), m_wallHeight->value(), 0.1, 100.0, 2, &ok);
    if (ok)
        setWallHeight(walls, height);
}

void MainWindow::openingSizeDialog()
{
    const QJsonObject info = m_selection.size() == 1 ? openingInfo(m_selection.first()) : QJsonObject();
    if (info.isEmpty()) {
        statusBar()->showMessage(tr("Select one door or window on the active level"));
        return;
    }
    QDialog dialog(this);
    dialog.setWindowTitle(tr("Door/window size"));
    auto* form = new QFormLayout(&dialog);
    auto spin = [&](double value) {
        auto* box = new QDoubleSpinBox(&dialog);
        box->setRange(0.0, 20.0);
        box->setDecimals(3);
        box->setSingleStep(0.05);
        box->setSuffix(QStringLiteral(" m"));
        box->setValue(value);
        return box;
    };
    QDoubleSpinBox* width = spin(info.value("width").toDouble());
    QDoubleSpinBox* height = spin(info.value("height").toDouble());
    QDoubleSpinBox* sill = spin(info.value("sill").toDouble());
    form->addRow(tr("Width:"), width);
    form->addRow(tr("Height:"), height);
    form->addRow(tr("Sill height:"), sill);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    form->addRow(buttons);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() == QDialog::Accepted)
        resizeOpening(m_selection.first(), width->value(), height->value(), sill->value());
}

double MainWindow::heightToNextLevel()
{
    const double here = m_levels->activeElevation();
    double next = 0;
    bool found = false;
    for (const auto& s : bridge("storeys").value("storeys").toArray()) {
        const double e = s.toObject().value("elevation").toDouble();
        if (e > here + 1e-6 && (!found || e < next)) {
            next = e;
            found = true;
        }
    }
    return found ? next - here : m_wallHeight->value();
}

bool MainWindow::createStair(QPointF start, QPointF towards)
{
    const QPointF d = towards - start;
    if (std::hypot(d.x(), d.y()) < 1e-6)
        return false;
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge("create_stair", {m_levels->activeStorey(), num(start.x()), num(start.y()),
        num(std::atan2(d.y(), d.x())), num(1.0), num(heightToNextLevel())});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not create the stair: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    statusBar()->showMessage(tr("Stair: %1 risers of %2 m").arg(r.value("risers").toInt())
                                 .arg(QLocale().toString(r.value("riser").toDouble(), 'f', 3)));
    return true;
}

bool MainWindow::addSlabOpening(const QVector<QPointF>& outline)
{
    if (m_selection.size() != 1)
        return false;
    QJsonArray pts;
    for (const QPointF& p : outline)
        pts.append(QJsonArray{p.x(), p.y()});
    const QJsonObject r = bridge("add_slab_opening", {m_selection.first(),
        QString::fromUtf8(QJsonDocument(pts).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not cut the opening: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::copyToLevel(const QStringList& guids, const QString& storey)
{
    const QJsonObject r = bridge("copy_to_storey", {jsonList(guids), storey});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not copy"), r.value("error").toString());
        return false;
    }
    afterEdit(r);
    statusBar()->showMessage(tr("%n element(s) copied", nullptr, int(r.value("guids").toArray().size())));
    return true;
}

void MainWindow::copyToLevelDialog()
{
    if (m_selection.isEmpty()) {
        statusBar()->showMessage(tr("Select what to copy first"));
        return;
    }
    QStringList names, guids;
    for (const auto& s : bridge("storeys").value("storeys").toArray()) {
        const QJsonObject o = s.toObject();
        names << QStringLiteral("%1 (%2 m)").arg(o.value("name").toString(), QLocale().toString(o.value("elevation").toDouble(), 'f', 2));
        guids << o.value("guid").toString();
    }
    bool ok = false;
    const QString choice = QInputDialog::getItem(this, tr("Copy to level"), tr("Copy the selection to:"), names, 0, false, &ok);
    if (ok)
        copyToLevel(m_selection, guids.value(names.indexOf(choice)));
}

void MainWindow::buildProjectToolbar()
{
    m_projectBar = addToolBar(tr("Project"));
    m_projectBar->setObjectName(QStringLiteral("projectToolbar"));
    m_projectBar->addWidget(new QLabel(tr("Option"), m_projectBar));
    m_options = new QComboBox(m_projectBar);
    m_options->setObjectName(QStringLiteral("optionCombo"));
    m_options->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    m_projectBar->addWidget(m_options);
    QAction* newOption = m_projectBar->addAction(tr("New option..."));
    newOption->setObjectName(QStringLiteral("actionNewOption"));
    connect(newOption, &QAction::triggered, this, &MainWindow::newOptionDialog);
    connect(m_options, &QComboBox::activated, this, [this](int index) {
        const QString wanted = m_options->itemText(index);
        if (!switchOption(wanted))
            refreshProject(); // put the combo back on the current option
    });
    m_projectBar->setVisible(false);
}

void MainWindow::refreshProject()
{
    const QJsonObject s = bridge("project_state");
    m_versioned = s.value("versioned").toBool();
    m_projectBar->setVisible(m_versioned);
    if (!m_versioned) {
        m_projectFolder.clear();
        m_history->setVersions({});
        endCompare();
        return;
    }
    m_projectFolder = s.value("folder").toString();
    const QString option = s.value("option").toString();
    {
        const QSignalBlocker block(m_options);
        m_options->clear();
        for (const auto& o : s.value("options").toArray())
            m_options->addItem(o.toString());
        m_options->setCurrentText(option);
    }
    m_history->setVersions(bridge("history", {QStringLiteral("200")}).value("versions").toArray());
    setWindowTitle(QStringLiteral("KIMCAD — %1 (%2)[*]").arg(QFileInfo(m_projectFolder).fileName(), option));
    setWindowModified(s.value("dirty").toBool());
}

bool MainWindow::enableVersioning(const QString& folder, const QString& message)
{
    const QJsonObject r = bridge("enable_versioning", {folder, message.isEmpty() ? tr("Initial import") : message});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not enable versioning"), r.value("error").toString());
        return false;
    }
    m_path = QDir(folder).filePath(QStringLiteral(".kimcad/working.ifc"));
    afterEdit();
    refreshProject();
    statusBar()->showMessage(tr("Versioning enabled: first version saved"));
    return true;
}

void MainWindow::enableVersioningDialog()
{
    if (m_versioned) {
        statusBar()->showMessage(tr("This model is already versioned"));
        return;
    }
    const QString folder = QFileDialog::getExistingDirectory(this, tr("Choose an empty folder for the project"));
    if (!folder.isEmpty())
        enableVersioning(folder);
}

bool MainWindow::openProject(const QString& folder)
{
    if (!maybeSave())
        return false;
    const QJsonObject r = bridge("open_project", {folder});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not open the project"), r.value("error").toString());
        return false;
    }
    endCompare();
    openFile(r.value("path").toString()); // meshes the working copy; the project stays open
    return true;
}

void MainWindow::openProjectDialog()
{
    const QString folder = QFileDialog::getExistingDirectory(this, tr("Open a KIMCAD project folder"));
    if (!folder.isEmpty())
        openProject(folder);
}

bool MainWindow::saveVersion(const QString& message)
{
    const QJsonObject r = bridge("save_version", {message});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("No version saved: %1").arg(r.value("error").toString()));
        refreshProject();
        return false;
    }
    afterEdit();
    refreshProject();
    statusBar()->showMessage(tr("Version saved: %1 added, %2 modified, %3 removed")
                                 .arg(r.value("added").toInt()).arg(r.value("modified").toInt()).arg(r.value("removed").toInt()));
    return true;
}

void MainWindow::saveVersionDialog()
{
    if (!m_versioned) {
        statusBar()->showMessage(tr("Enable versioning first (File menu)"));
        return;
    }
    const QJsonObject changes = bridge("version_changes");
    QDialog dialog(this);
    dialog.setWindowTitle(tr("Save version"));
    auto* layout = new QVBoxLayout(&dialog);
    layout->addWidget(new QLabel(tr("%1 added, %2 modified, %3 removed since the last version")
                                     .arg(changes.value("added").toInt()).arg(changes.value("modified").toInt())
                                     .arg(changes.value("removed").toInt()), &dialog));
    auto* list = new QListWidget(&dialog);
    for (const auto& v : changes.value("items").toArray()) {
        const QJsonObject o = v.toObject();
        list->addItem(QStringLiteral("%1 · %2 · %3").arg(o.value("kind").toString(), o.value("type").toString(),
            o.value("name").toString().isEmpty() ? o.value("guid").toString() : o.value("name").toString()));
    }
    layout->addWidget(list);
    layout->addWidget(new QLabel(tr("What changed (the version's message):"), &dialog));
    auto* message = new QLineEdit(&dialog);
    layout->addWidget(message);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Save | QDialogButtonBox::Cancel, &dialog);
    layout->addWidget(buttons);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() == QDialog::Accepted)
        saveVersion(message->text());
}

QJsonArray MainWindow::history()
{
    return bridge("history", {QStringLiteral("200")}).value("versions").toArray();
}

bool MainWindow::compareWith(const QString& revA, const QString& revB)
{
    const QJsonObject r = bridge("compare", {revA, revB});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not compare: %1").arg(r.value("error").toString()));
        return false;
    }
    QHash<QString, QColor> colors;
    for (const auto& v : r.value("added").toArray())
        colors.insert(v.toObject().value("guid").toString(), HistoryPanel::addedColor());
    for (const auto& v : r.value("modified").toArray())
        colors.insert(v.toObject().value("guid").toString(), HistoryPanel::modifiedColor());
    m_viewport->setElementColors(colors);
    m_history->setChanges(r);
    statusBar()->showMessage(tr("Compare: %1 added, %2 modified, %3 removed")
                                 .arg(r.value("added").toArray().size()).arg(r.value("modified").toArray().size())
                                 .arg(r.value("removed").toArray().size()));
    return true;
}

void MainWindow::endCompare()
{
    m_viewport->clearElementColors();
    m_history->setChanges({});
}

int MainWindow::compareChangeCount() const
{
    return m_history->changeCount();
}

bool MainWindow::createOption(const QString& name)
{
    const QJsonObject r = bridge("create_option", {name});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not create the option"), r.value("error").toString());
        return false;
    }
    refreshProject();
    statusBar()->showMessage(tr("Now working on option %1").arg(name));
    return true;
}

void MainWindow::newOptionDialog()
{
    bool ok = false;
    const QString name = QInputDialog::getText(this, tr("New design option"), tr("Name of the option:"), QLineEdit::Normal,
        QString(), &ok);
    if (ok && !name.trimmed().isEmpty())
        createOption(name.trimmed());
}

bool MainWindow::resolveUnsavedForSwitch()
{
    if (!isDirty())
        return true;
    if (m_quiet)
        return false; // never a modal dialog in quiet mode
    const auto answer = QMessageBox::warning(this, tr("Unsaved changes"),
        tr("Save a version of your changes before switching options?"),
        QMessageBox::Save | QMessageBox::Discard | QMessageBox::Cancel, QMessageBox::Save);
    if (answer == QMessageBox::Save) {
        saveVersionDialog();
        return !isDirty();
    }
    if (answer == QMessageBox::Discard)
        return bridge("discard_changes").value("ok").toBool();
    return false;
}

bool MainWindow::switchOption(const QString& name)
{
    if (!resolveUnsavedForSwitch())
        return false;
    const QJsonObject r = bridge("switch_option", {name});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not switch options"), r.value("error").toString());
        return false;
    }
    endCompare();
    openFile(r.value("path").toString());
    return true;
}

bool MainWindow::discardChanges()
{
    const QJsonObject r = bridge("discard_changes");
    if (!r.value("ok").toBool())
        return false;
    endCompare();
    openFile(r.value("path").toString());
    return true;
}

int MainWindow::gridLineCount() const
{
    return m_viewport->gridLineCount();
}

static QJsonObject firstType(const QJsonObject& listing)
{
    const QJsonArray types = listing.value("types").toArray();
    return types.isEmpty() ? QJsonObject() : types.first().toObject();
}

bool MainWindow::columnAt(QPointF p, bool turned)
{
    const Snap s = m_twoPointTool->snapper().snap(p, m_twoPointTool->tolerance());
    QJsonObject type = m_tool == Tool::Column ? currentType() : QJsonObject();
    if (type.isEmpty())
        type = firstType(bridge("column_types"));
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge("create_column", {m_levels->activeStorey(), type.value("guid").toString(), num(s.point.x()),
        num(s.point.y()), num(m_wallHeight->value()), num(turned ? M_PI / 2 : 0.0)});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not place it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::createSegment(QPointF p1, QPointF p2)
{
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    QJsonObject r;
    if (m_tool == Tool::Grid) {
        r = bridge("add_grid_axis", {m_levels->activeStorey(), num(p1.x()), num(p1.y()), num(p2.x()), num(p2.y()), QString()});
    } else {
        QJsonObject type = m_tool == Tool::Beam ? currentType() : QJsonObject();
        if (type.isEmpty())
            type = firstType(bridge("beam_types"));
        r = bridge("create_beam", {m_levels->activeStorey(), type.value("guid").toString(), num(p1.x()), num(p1.y()),
            num(p2.x()), num(p2.y()), num(m_levels->activeElevation() + m_wallHeight->value())});
    }
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not create it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::createSlab(const QVector<QPointF>& outline)
{
    QJsonArray pts;
    for (const QPointF& p : outline)
        pts.append(QJsonArray{p.x(), p.y()});
    QJsonObject type = m_tool == Tool::Slab ? currentType() : QJsonObject();
    if (type.isEmpty()) {
        const QJsonArray types = bridge("slab_types").value("types").toArray();
        if (types.isEmpty())
            return false;
        type = types.first().toObject();
    }
    const QJsonObject r = bridge("create_slab", {m_levels->activeStorey(), type.value("guid").toString(),
        QString::fromUtf8(QJsonDocument(pts).toJson(QJsonDocument::Compact)), QStringLiteral("0")});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not create the slab: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::slabFromWalls(const QStringList& walls)
{
    const QJsonObject outline = bridge("slab_outline_from_walls", {jsonList(walls)});
    if (!outline.value("ok").toBool()) {
        showError(tr("Cannot make a slab from these walls"), outline.value("error").toString());
        return false;
    }
    QVector<QPointF> pts;
    for (const auto& p : outline.value("points").toArray())
        pts << QPointF(p.toArray().at(0).toDouble(), p.toArray().at(1).toDouble());
    return createSlab(pts);
}

bool MainWindow::insertOpening(const Host& host)
{
    const QString kind = m_tool == Tool::Window ? QStringLiteral("window") : QStringLiteral("door");
    QJsonObject type = currentType();
    if (type.isEmpty()) {
        const QJsonArray types = bridge("opening_types", {kind}).value("types").toArray();
        if (types.isEmpty())
            return false;
        type = types.first().toObject();
    }
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge("insert_opening", {kind, host.wallGuid, type.value("guid").toString(), num(host.along),
        num(type.value("width").toDouble()), num(type.value("height").toDouble()), num(type.value("sill").toDouble())});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not place it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    refreshSnapData();
    return true;
}

bool MainWindow::createWall(const WallSegment& s)
{
    QJsonObject type = m_tool == Tool::Wall ? currentType() : QJsonObject();
    if (type.isEmpty()) {
        const QJsonArray types = bridge("wall_types").value("types").toArray();
        if (types.isEmpty())
            return false;
        type = types.first().toObject();
    }
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    StepTimer createTimer(m_timings, "bridgeCreateWall");
    const QJsonObject r = bridge("create_wall", {m_levels->activeStorey(), type.value("guid").toString(),
        num(s.p1.x()), num(s.p1.y()), num(s.p2.x()), num(s.p2.y()), num(m_wallHeight->value()), s.joinStart, s.joinEnd});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not create the wall: %1").arg(r.value("error").toString()));
        return false;
    }
    m_wallTool->setLastWall(r.value("guid").toString());
    afterEdit(r);
    refreshSnapData();
    return true;
}

bool MainWindow::deleteSelection()
{
    if (m_selection.isEmpty())
        return false;
    const QJsonObject r = bridge("delete_elements", {jsonList(m_selection)});
    if (!r.value("ok").toBool())
        showError(tr("Could not delete"), r.value("error").toString());
    afterEdit(r);
    return r.value("ok").toBool();
}

bool MainWindow::treeHasGuid(const QString& guid) const
{
    return m_tree->itemFor(guid) != nullptr;
}

void MainWindow::applyGeometry(const QJsonObject& geometry)
{
    QStringList changed, removed;
    for (const auto& g : geometry.value("changed").toArray())
        changed << g.toString();
    for (const auto& g : geometry.value("removed").toArray())
        removed << g.toString();
    if (changed.isEmpty() && removed.isEmpty())
        return;
    m_viewport->removeElements(removed);
    if (!changed.isEmpty()) {
        MeshChunk chunk;
        bool none = false;
        QString error;
        bool fetched = false;
        {
            StepTimer _(m_timings, "fetchMeshes");
            fetched = fetchElementMeshes(PythonEngine::instance(), changed, &chunk, &none, &error);
        }
        if (!fetched)
            showError(tr("Could not update the 3D view"), error);
        else if (!none) {
            StepTimer _(m_timings, "replaceElements");
            m_viewport->replaceElements(chunk);
        }
    }
    {
        StepTimer _(m_timings, "refreshTree");
        m_tree->refreshTree(bridge("spatial_tree")); // elements can appear or disappear
    }
    QStringList kept;
    for (const QString& g : std::as_const(m_selection))
        if (!removed.contains(g))
            kept << g;
    m_tree->selectGuids(kept);
    if (kept != m_selection)
        setSelection(kept);
}


void MainWindow::afterEdit(const QJsonObject& result)
{
    { StepTimer _(m_timings, "applyGeometry"); applyGeometry(result.value("geometry").toObject()); }
    { StepTimer _(m_timings, "refreshLevels"); refreshLevels(); }
    if (!m_warnedInconsistent && bridge("state").value("inconsistent").toBool()) {
        m_warnedInconsistent = true;
        showError(tr("The model may be inconsistent"),
            tr("An edit failed and could not be undone. Save a copy if you need it, then reopen the file."));
    }
    { StepTimer _(m_timings, "refreshSnapData"); refreshSnapData(); } // undo/redo can add or remove walls and grid lines
    StepTimer stateTimer(m_timings, "stateAndNames");
    const QJsonObject s = bridge("state");
    m_undo->setEnabled(s.value("can_undo").toBool());
    m_redo->setEnabled(s.value("can_redo").toBool());
    setWindowModified(s.value("dirty").toBool());
    m_tree->updateNames(bridge("spatial_tree")); // names can change through edits and undo
    // Defer the panel rebuild: this can run from inside the panel's own itemChanged handler.
    QMetaObject::invokeMethod(this, &MainWindow::refreshProperties, Qt::QueuedConnection);
}

bool MainWindow::isDirty() const
{
    QString error;
    return PythonEngine::instance().callJson("state", {}, &error).object().value("dirty").toBool();
}

bool MainWindow::save()
{
    if (m_versioned) { // the file is only a working copy: saving means saving a version
        if (m_quiet)
            return saveVersion(tr("Saved from KIMCAD")) || !isDirty();
        saveVersionDialog();
        return !isDirty();
    }
    if (m_path.isEmpty()) {
        saveAsDialog();
        return !isDirty();
    }
    return saveAs(m_path);
}

bool MainWindow::saveAs(const QString& path)
{
    const QJsonObject r = bridge("save", {path});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not save"), r.value("error").toString());
        return false;
    }
    m_path = path;
    setWindowTitle(QStringLiteral("KIMCAD — %1[*]").arg(QFileInfo(path).fileName()));
    afterEdit();
    statusBar()->showMessage(tr("Saved %1").arg(QFileInfo(path).fileName()));
    return true;
}

void MainWindow::saveAsDialog()
{
    const QString path = QFileDialog::getSaveFileName(this, tr("Save IFC"), m_path, tr("IFC files (*.ifc)"));
    if (!path.isEmpty())
        saveAs(path);
}

bool MainWindow::maybeSave()
{
    if (m_quiet || !isDirty())
        return true; // quiet/self-test mode never shows a modal dialog
    const auto answer = QMessageBox::warning(this, tr("Unsaved changes"),
        tr("The model has unsaved changes. Save them?"),
        QMessageBox::Save | QMessageBox::Discard | QMessageBox::Cancel, QMessageBox::Save);
    if (answer == QMessageBox::Save)
        return save();
    return answer == QMessageBox::Discard;
}

void MainWindow::addPropertyDialog(const QString& pset)
{
    bool ok = false;
    const QString prop = QInputDialog::getText(this, tr("Add property"), tr("Property name in %1:").arg(pset),
        QLineEdit::Normal, QString(), &ok);
    if (!ok || prop.trimmed().isEmpty())
        return;
    const QString value = QInputDialog::getText(this, tr("Add property"), tr("Value:"), QLineEdit::Normal, QString(), &ok);
    if (ok)
        applyPropertyEdit(pset, prop.trimmed(), QJsonValue(value));
}

void MainWindow::addPropertySetDialog()
{
    QString ifcClass;
    const QJsonObject m = bridge("properties_multi", {jsonList(m_selection)});
    if (!m.value("types").toArray().isEmpty())
        ifcClass = m.value("types").toArray().first().toString();
    QStringList names;
    for (const auto& n : bridge("pset_templates", {ifcClass}).value("names").toArray())
        names << n.toString();
    bool ok = false;
    const QString pset = QInputDialog::getItem(this, tr("Add property set"), tr("Property set (standard or custom):"),
        names, 0, /*editable=*/true, &ok);
    if (ok && !pset.trimmed().isEmpty())
        addPropertyDialog(pset.trimmed());
}


void MainWindow::onOpened(const QJsonObject& info)
{
    setWindowTitle(QStringLiteral("KIMCAD — %1[*]").arg(QFileInfo(m_path).fileName()));
    setWindowModified(false);
    refreshLevels();
    m_types->clear();
    m_warnedInconsistent = false;
    m_undo->setEnabled(false);
    m_redo->setEnabled(false);
    QString error;
    const QJsonObject tree = PythonEngine::instance().callJson("spatial_tree", {}, &error).object();
    m_tree->setTree(tree);
    refreshProject();
    statusBar()->showMessage(tr("Loading %1 (%2)...").arg(QFileInfo(m_path).fileName(), info.value("schema").toString()));
}

void MainWindow::onChunk(const MeshChunk& chunk)
{
    if (!m_loading)
        return; // a stopped load's late chunk
    const bool first = m_viewport->batchCount() == 0;
    m_viewport->addBatch(new ElementBatch(chunk));
    m_loadedElements += chunk.elementCount();
    statusBar()->showMessage(tr("Loading... %n element(s)", nullptr, m_loadedElements));
    if (first) {
        m_viewport->fitAll();
        emit firstChunkShown();
    }
}

void MainWindow::onFinished(int elements, bool stopped)
{
    m_loading = false;
    if (!stopped) {
        m_viewport->fitAll();
        statusBar()->showMessage(tr("%n element(s) loaded in %1 s", nullptr, elements)
                                     .arg(double(m_loadTimer.elapsed()) / 1000.0, 0, 'f', 1));
    }
    emit loadFinished(elements, stopped);
}

void MainWindow::onFailed(const QString& error)
{
    m_loading = false;
    showError(tr("Could not open the model"), error);
    emit loadFailed(error);
}

} // namespace kimcad
