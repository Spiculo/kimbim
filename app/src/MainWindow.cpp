// SPDX-License-Identifier: GPL-3.0-or-later
#define _USE_MATH_DEFINES
#include "MainWindow.h"
#include "DockLayout.h"
#include <DockManager.h>
#include <DockWidget.h>
#include "Scene.h"
#include "Icons.h"
#include "StatusStrip.h"
#include "ToolOptionsBar.h"
#include "ToolPalette.h"
#include "ViewCube.h"
#include "TitleBar.h"
#include "ViewHost.h"

#include <QApplication>
#include <QScreen>
#include <QCloseEvent>
#include <QShowEvent>
#include <QSettings>
#include <QStandardPaths>
#include <QFile>
#include <QDoubleSpinBox>
#include <QLabel>
#include <QPainter>
#include <QPixmap>
#include <QToolBar>
#include <QFileDialog>
#include <QFileInfo>
#include <algorithm>

#include <QElapsedTimer>
#include <QInputDialog>
#include <QToolTip>
#include <QHBoxLayout>
#include <QSlider>
#include <QSpinBox>
#include <QVBoxLayout>
#include <QListWidget>
#include <QDir>
#include <QFormLayout>
#include <QDialogButtonBox>
#include <QDialog>
#include <QMenu>
#include <QActionGroup>
#include <QPainter>
#include <QPainterPath>
#include <QToolButton>
#include <QSignalBlocker>
#include <cmath>
#include <optional>
#include <gp_Ax2.hxx>
#include <gp_Dir.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>
#include <memory>
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
#include <QPointer>
#include <QProgressDialog>
#include <QEventLoop>
#include <QTabBar>
#include <QTabWidget>
#include <QTimer>
#include <QHeaderView>
#include <QTableWidget>
#include <QCheckBox>
#include <QDateTime>
#include <QPushButton>

#include <limits>

#include "CombineDialog.h"
#include "Graphics.h"
#include "GraphicsDialogs.h"
#include "PenGrid.h"
#include "Cuts.h"
#include "DrawingView.h"
#include "DrawingsPanel.h"
#include "SheetExport.h"
#include "SheetsPanel.h"
#include "SchedulesDialog.h"
#include "ElementBatch.h"
#include "HistoryPanel.h"
#include "LayersPanel.h"
#include "LevelsBar.h"
#include "LevelsDialog.h"
#include "InputAidsController.h"
#include "MeasureController.h"
#include "HostTool.h"
#include "PolygonTool.h"
#include "GripTool.h"
#include "ModifyTool.h"
#include "RotateTool.h"
#include "TwoPointTool.h"
#include "WallTool.h"
#include "MeshChunk.h"
#include "ModelLoader.h"
#include "ModelTreePanel.h"
#include "PreferencesDialog.h"
#include "ProjectSettingsDialog.h"
#include "PropertiesPanel.h"
#include "PythonEngine.h"
#include "Viewport.h"
#include "DraftTool.h"

namespace kimbim {

void readDrafting(const QJsonObject& o, Viewport::Annotation* a); // D84, DraftTools.cpp
void readStairSymbols(const QJsonObject& data, QVector<Viewport::Annotation>* list); // D88, StairTools.cpp

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
    , m_prefs(quiet ? QString() : Preferences::defaultPath())
    , m_scene(new Scene(this))
    , m_viewport(new Viewport(m_scene))
    , m_tree(new ModelTreePanel(this))
    , m_properties(new PropertiesPanel(this))
    , m_loader(new ModelLoader(chunkSize))
{
    m_prefs.load();
    applyViewPreferences(); // D92: the field of view and the home view, before any view is used
    qRegisterMetaType<kimbim::MeshChunk>();
    // D71: the bottom bar (pen, layers, zoom, selection, messages) replaces the status bar.
    m_status = new StatusStrip(this);
    auto* bottom = new QToolBar(tr("Status"), this);
    bottom->setObjectName(QStringLiteral("statusToolbar"));
    bottom->setMovable(false);
    bottom->setFloatable(false);
    bottom->addWidget(m_status);
    addToolBar(Qt::BottomToolBarArea, bottom);
    statusBar()->hide();
    connect(m_status, &StatusStrip::activeLayerRequested, this, &MainWindow::setActiveLayer);
    connect(m_status, &StatusStrip::purposeRequested, this, [this](const QString& name) {
        if (name != m_viewport->graphics().purpose())
            setPurpose(name);
    });
    connect(m_status, &StatusStrip::graphicsPopupRequested, this, &MainWindow::editPurposePieces);
    connect(m_status, &StatusStrip::statusForNewRequested, this, &MainWindow::setStatusForNew);
    connect(m_status, &StatusStrip::penRequested, this, [this] {
        const Graphics& g = m_viewport->graphics();
        const int pen = PenGrid::pick(m_status->findChild<QWidget*>(QStringLiteral("penButton")), g.pens(),
            g.penNames(), g.currentPen());
        if (pen > 0)
            setCurrentPen(pen);
    });
    connect(m_status, &StatusStrip::layerVisibilityToggled, this, &MainWindow::setLayerVisible);
    setWindowTitle(QStringLiteral("KimBim"));
    resize(1280, 800);
    // The plan-cut height slider at the right edge of the active model view (owner feedback).
    m_cutColumn = new QWidget(this);
    auto* cutColumn = new QVBoxLayout(m_cutColumn);
    cutColumn->setContentsMargins(4, 6, 4, 6);
    m_cutLabel = new QLabel(m_cutColumn);
    m_cutLabel->setAlignment(Qt::AlignHCenter);
    m_cutSlider = new QSlider(Qt::Vertical, m_cutColumn);
    m_cutSlider->setObjectName(QStringLiteral("planCutSlider"));
    m_cutSlider->setToolTip(tr("Plan cut height above the active level (drag to cut the model)"));
    m_cutSlider->setRange(0, 300);
    m_cutSlider->setValue(120);
    m_cutSlider->setTickPosition(QSlider::TicksLeft);
    m_cutSlider->setTickInterval(50);
    cutColumn->addWidget(m_cutLabel);
    cutColumn->addWidget(m_cutSlider, 1, Qt::AlignHCenter);
    // D71: the 3D view is the first center tab; plans, drawings and sheets open next to it, and any
    // tab can be dragged out to its own window.
    m_dock = new DockLayout(this);
    auto* host = new ViewHost(m_viewport);
    m_hosts.insert(QStringLiteral("3d"), host);
    host->adoptChrome(nullptr, m_cutColumn);
    m_dock->addView(QStringLiteral("3d"), tr("3D"), host, false);
    connect(m_dock, &DockLayout::currentChanged, this, &MainWindow::activateView);
    connect(m_dock, &DockLayout::closeRequested, this, &MainWindow::closeView);
    // D75: one row of chrome instead of the native title bar, a menu row and a top toolbar.
    TitleBar::install(this);
    m_titleBar = new TitleBar(this);
    setMenuWidget(m_titleBar);
    m_menuBar = m_titleBar->menuBar();
    buildMenus();
    buildDocks();
    buildCutsToolbar();    // the level and the cuts, after the menus
    buildModelingToolbar();
    buildVersions();       // the Versions menu and the title bar's Versions button
    buildPalette();
    m_status->showMessage(tr("Ready"));

    m_loader->moveToThread(&m_thread);
    connect(&m_thread, &QThread::finished, m_loader, &QObject::deleteLater);
    connect(m_loader, &ModelLoader::opened, this, &MainWindow::onOpened);
    connect(m_loader, &ModelLoader::chunkReady, this, &MainWindow::onChunk);
    connect(m_loader, &ModelLoader::finished, this, &MainWindow::onFinished);
    connect(m_loader, &ModelLoader::failed, this, &MainWindow::onFailed);
    m_thread.start();

    // Selection sync: viewport -> tree + properties, tree -> viewport + properties.
    onEachView([this](Viewport* v) { connect(v, &Viewport::selectionChanged, this, [this](const QStringList& guids) {
        m_tree->selectGuids(guids);
        setSelection(guids);
    }); });
    connect(m_tree, &ModelTreePanel::guidsSelected, this, [this](const QStringList& guids) {
        m_viewport->selectGuids(guids);
        setSelection(guids);
    });
    connect(m_properties, &PropertiesPanel::propertyEdited, this, &MainWindow::applyPropertyEdit);
    connect(m_properties, &PropertiesPanel::statusEdited, this, [this](const QString& s) {
        // after the drop-down's own signal: setRenovationStatus rebuilds the panel
        QMetaObject::invokeMethod(this, [this, s] { setRenovationStatus(s); }, Qt::QueuedConnection);
    });
    connect(m_properties, &PropertiesPanel::nameEdited, this, &MainWindow::applyName);
    connect(m_properties, &PropertiesPanel::propertyRemoved, this, &MainWindow::removeProperty);
    connect(m_properties, &PropertiesPanel::addPropertyRequested, this, &MainWindow::addPropertyDialog);
    connect(m_properties, &PropertiesPanel::addPropertySetRequested, this, &MainWindow::addPropertySetDialog);
    connect(m_properties, &PropertiesPanel::typeEditRequested, this, &MainWindow::typeEditDialog);
    connect(m_properties, &PropertiesPanel::resetToTypeRequested, this, &MainWindow::resetToType);
    connect(m_tree, &ModelTreePanel::isolateRequested, m_viewport, &Viewport::isolate);
    onEachView([this](Viewport* v) { connect(v, &Viewport::dragMoved, this, &MainWindow::dragMoveTo); });
    onEachView([this](Viewport* v) { connect(v, &Viewport::elementDoubleClicked, this, &MainWindow::activateElement); });
    connect(m_tree, &ModelTreePanel::guidActivated, this, &MainWindow::activateElement);
    onEachView([this](Viewport* v) { connect(v, &Viewport::zoomChanged, this, [this, v](double z) {
        if (v == m_viewport)
            m_status->setZoom(z);
    }); });
    onEachView([this](Viewport* v) { connect(v, &Viewport::dragReleased, this, &MainWindow::dragFinished); });
    onEachView([this](Viewport* v) { connect(v, &Viewport::hovered, this, [this](const QString& guid, const QPoint& at) {
        const QString hint = guid.isEmpty() ? QString() : m_tree->hintFor(guid);
        if (hint.isEmpty())
            QToolTip::hideText();
        else
            QToolTip::showText(at, hint, m_viewport);
    }); });
    connect(m_tree, &ModelTreePanel::hideRequested, this, [this](const QStringList& g) { m_viewport->setHidden(g, true); });
    connect(m_tree, &ModelTreePanel::showAllRequested, m_viewport, &Viewport::showAll);

    QString error;
    if (!PythonEngine::instance().start(&error))
        showError(tr("KimBim cannot start"), error);
    bridge("set_app_paths", {QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation)});
    bridge("set_author", {m_prefs.authorName(), m_prefs.authorEmail()});
    applyDrawingPrefs();
    m_sinceVersion.start();
    connect(&m_recoveryTimer, &QTimer::timeout, this, [this] {
        if (isDirty())
            writeRecovery();
    });
    restartRecoveryTimer();
    // The window layout of the last session (D71); tests and the self-test start from the default,
    // where the model view gets most of the width.
    m_dock->setSideWidths(216, 280); // D90: two columns of tools on the left; icon tabs need less on the right
    m_dock->captureDefault();
    if (!m_quiet) {
        QByteArray state = m_prefs.layout();
        if (state.isEmpty()) // once: the layout saved by the first D71 build
            state = QSettings().value(QStringLiteral("layout/state")).toByteArray();
        m_dock->restoreLayout(state);
        restoreGeometry(m_prefs.windowGeometry()); // D75: size, position and maximized
    }
    // A corrupt layout or saved geometry (tens of thousands of pixels wide) would make Qt allocate a
    // ~4 GB backing store and die; catch it once the window is shown and fall back to a sane size.
    clampWindowSize();
    QTimer::singleShot(0, this, &MainWindow::clampWindowSize);
}

void MainWindow::clampWindowSize()
{
    QScreen* s = screen();
    const QRect avail = s ? s->availableGeometry() : QRect(0, 0, 1920, 1080);
    const int capW = avail.width() * 4, capH = avail.height() * 4;
    if (m_clamping || (width() <= capW && height() <= capH && minimumWidth() <= capW && minimumHeight() <= capH))
        return;
    qWarning("KimBim: the window asked for %dx%d (minimum %dx%d); back to 1280x800", width(), height(),
        minimumWidth(), minimumHeight());
    m_clamping = true;
    m_dock->restoreLayout(QByteArray()); // the default layout: resets the splitter sizes
    setContentsMargins(0, 0, 0, 0);      // a maximized window's frame margins (TitleBar) count in its minimum
    setMinimumSize(0, 0);
    resize(1280, 800);
    move(std::max(0, avail.x() + (avail.width() - width()) / 2), std::max(0, avail.y() + (avail.height() - height()) / 2));
    m_clamping = false;
}

void MainWindow::applyDrawingPrefs()
{
    bridge("set_drawing_timeout", {QString::number(m_prefs.drawingTimeout())});
    bridge("set_drawing_hlr", {m_prefs.drawingHlr()});
}

void MainWindow::resizeEvent(QResizeEvent* event)
{
    // A corrupt layout asks for a window of tens of thousands of pixels during layout, before the first
    // paint; catch it here (the ~4 GB backing store would otherwise fail in createDIB and crash).
    QMainWindow::resizeEvent(event);
    QScreen* s = screen();
    const QRect avail = s ? s->availableGeometry() : QRect(0, 0, 1920, 1080);
    if (event->size().width() > avail.width() * 4 || event->size().height() > avail.height() * 4)
        clampWindowSize();
}

MainWindow::~MainWindow()
{
    for (QThread* t : std::as_const(m_drawingThreads))
        t->wait(); // a drawing being generated: its result is dropped
    stopLoading();
    m_thread.quit();
    m_thread.wait();
    // The 3D views go while the window still has its native handles: destroying the window destroys
    // its child windows, and a view torn down after that can't release its OpenGL context (D71).
    for (ViewHost* host : std::as_const(m_hosts))
        delete host->viewport();
    m_hosts.clear();
    m_viewport = nullptr;
}

void MainWindow::buildMenus()
{
    QMenu* file = m_menuBar->addMenu(tr("&File"));
    QAction* newProjectAction = file->addAction(tr("&New project..."));
    newProjectAction->setObjectName(QStringLiteral("actionNewProject"));
    newProjectAction->setShortcut(QKeySequence::New);
    connect(newProjectAction, &QAction::triggered, this, &MainWindow::newProjectDialog);
    QAction* open = file->addAction(tr("&Open..."));
    open->setObjectName(QStringLiteral("actionOpen"));
    open->setShortcut(QKeySequence::Open);
    connect(open, &QAction::triggered, this, &MainWindow::openDialog);
    QAction* openProjectAction = file->addAction(tr("Open project &folder..."));
    openProjectAction->setObjectName(QStringLiteral("actionOpenProject"));
    connect(openProjectAction, &QAction::triggered, this, &MainWindow::openProjectDialog);
    m_recentMenu = file->addMenu(tr("&Recent files"));
    m_recentMenu->setObjectName(QStringLiteral("recentMenu"));
    connect(m_recentMenu, &QMenu::aboutToShow, this, &MainWindow::fillRecentMenu);
    file->addSeparator();
    QAction* saveAction = file->addAction(tr("&Save"));
    saveAction->setObjectName(QStringLiteral("actionSave"));
    saveAction->setShortcut(QKeySequence::Save);
    connect(saveAction, &QAction::triggered, this, [this] { save(); });
    QAction* saveAs = file->addAction(tr("Save &As..."));
    saveAs->setObjectName(QStringLiteral("actionSaveAs"));
    saveAs->setShortcut(QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_S));
    connect(saveAs, &QAction::triggered, this, &MainWindow::saveAsDialog);
    QAction* saveFolder = file->addAction(tr("Save as project f&older..."));
    saveFolder->setObjectName(QStringLiteral("actionSaveAsFolder"));
    connect(saveFolder, &QAction::triggered, this, &MainWindow::saveAsFolderDialog);
    QAction* saveTemplate = file->addAction(tr("Save as &template..."));
    saveTemplate->setObjectName(QStringLiteral("actionSaveAsTemplate"));
    connect(saveTemplate, &QAction::triggered, this, &MainWindow::saveAsTemplateDialog);
    QAction* exportIfcAction = file->addAction(tr("&Export IFC..."));
    exportIfcAction->setObjectName(QStringLiteral("actionExportIfc"));
    connect(exportIfcAction, &QAction::triggered, this, &MainWindow::exportIfcDialog);
    file->addSeparator();
    QAction* settingsAction = file->addAction(tr("Project se&ttings..."));
    settingsAction->setObjectName(QStringLiteral("actionProjectSettings"));
    connect(settingsAction, &QAction::triggered, this, &MainWindow::projectSettingsDialog);
    file->addSeparator();
    QAction* info = file->addAction(tr("Project &info..."));
    info->setObjectName(QStringLiteral("actionProjectInfo"));
    connect(info, &QAction::triggered, this, &MainWindow::projectInfoDialog);
    QAction* pdf = file->addAction(tr("Export sheet as &PDF..."));
    pdf->setObjectName(QStringLiteral("actionExportSheetPdf"));
    connect(pdf, &QAction::triggered, this, [this] { exportSheetDialog(true); });
    QAction* svgExport = file->addAction(tr("Export sheet as S&VG..."));
    svgExport->setObjectName(QStringLiteral("actionExportSheetSvg"));
    connect(svgExport, &QAction::triggered, this, [this] { exportSheetDialog(false); });
    QAction* dxfExport = file->addAction(tr("Export &DXF..."));
    dxfExport->setObjectName(QStringLiteral("actionExportDxf"));
    dxfExport->setToolTip(tr("Drawings and sheets to DXF files, several at once"));
    connect(dxfExport, &QAction::triggered, this, &MainWindow::exportDxfDialog);
    addUnderlayActions(file); // D85: Place underlay..., Underlays... (Underlays.cpp)
    QAction* schedule = file->addAction(tr("&Room schedule..."));
    schedule->setObjectName(QStringLiteral("actionRoomSchedule"));
    connect(schedule, &QAction::triggered, this, &MainWindow::roomScheduleDialog);
    QAction* schedules = file->addAction(tr("Sc&hedules..."));
    schedules->setObjectName(QStringLiteral("actionSchedules"));
    schedules->setToolTip(tr("Doors, windows, walls, slabs, columns, beams, rooms or your own schedules, with quantities"));
    connect(schedules, &QAction::triggered, this, [this] { openSchedules(); });
    file->addSeparator();
    file->addSeparator();
    QAction* quit = file->addAction(tr("&Quit"));
    quit->setShortcut(QKeySequence::Quit);
    connect(quit, &QAction::triggered, this, &QWidget::close);

    QMenu* editMenu = m_menuBar->addMenu(tr("&Edit"));
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
    editMenu->addSeparator();
    // Slice 17: Archicad's Edit menu and shortcuts.
    auto editAction = [&](const QString& text, const char* name, const QKeySequence& key, auto slot) {
        QAction* a = editMenu->addAction(text);
        a->setObjectName(QLatin1String(name));
        if (!key.isEmpty())
            a->setShortcut(key);
        connect(a, &QAction::triggered, this, slot);
        return a;
    };
    editAction(tr("&Copy"), "actionCopy", QKeySequence::Copy, [this] { copyToClipboard(); });
    editAction(tr("&Paste"), "actionPaste", QKeySequence::Paste, [this] { paste(); });
    editAction(tr("D&uplicate"), "actionDuplicate", QKeySequence(Qt::CTRL | Qt::Key_D), [this] { duplicateSelection(); });
    editAction(tr("&Mirror"), "actionMirror", QKeySequence(Qt::CTRL | Qt::Key_M), [this](bool on) { setTool(on ? Tool::Mirror : Tool::None); })
        ->setToolTip(tr("Mirror the selection: click two points of the mirror line (hold Ctrl on the second click to mirror a copy)"));
    editAction(tr("Multi&ply..."), "actionMultiply", QKeySequence(Qt::CTRL | Qt::Key_U), [this] { multiplyDialog(); });
    editAction(tr("&Offset..."), "actionOffset", QKeySequence(), [this] { offsetDialog(); });
    // D78: selection tools (Archicad's Find & Select; Revit's Select All Instances).
    editMenu->addSeparator();
    editAction(tr("Select &similar"), "actionSelectSimilar", QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_A),
        [this] { selectSimilar(QStringLiteral("type")); })
        ->setToolTip(tr("Select every element of the selected elements' types (untyped: same class and predefined type)"));
    editAction(tr("Select all of this c&lass"), "actionSelectClass", QKeySequence(), [this] { selectSimilar(QStringLiteral("class")); })
        ->setToolTip(tr("Select every element of the selected elements' IFC classes"));
    editAction(tr("&Find && Select..."), "actionFindSelect", QKeySequence(Qt::CTRL | Qt::Key_F), [this] {
        findSelectPanel();
        m_dock->raisePanel(QStringLiteral("findselect"));
    });

    editMenu->addSeparator();
    QAction* prefsAction = editMenu->addAction(tr("&Preferences..."));
    prefsAction->setObjectName(QStringLiteral("actionPreferences"));
    prefsAction->setShortcut(QKeySequence::Preferences);
    prefsAction->setMenuRole(QAction::PreferencesRole);
    connect(prefsAction, &QAction::triggered, this, &MainWindow::preferencesDialog);

    QMenu* view = m_menuBar->addMenu(tr("&View"));
    m_viewMenu = view;
    QAction* planView = view->addAction(tr("&Plan view"));
    planView->setObjectName(QStringLiteral("actionPlanView"));
    planView->setShortcut(Qt::Key_P);
    connect(planView, &QAction::triggered, this, [this] { setPlanView(true); });
    QAction* view3D = view->addAction(tr("&3D view"));
    view3D->setObjectName(QStringLiteral("action3DView"));
    view3D->setShortcut(Qt::Key_3);
    connect(view3D, &QAction::triggered, this, [this] { setPlanView(false); });
    QAction* elevations = view->addAction(tr("Create floor plans and &elevations"));
    elevations->setObjectName(QStringLiteral("actionCreateDrawings"));
    elevations->setToolTip(tr("Add a floor plan for every level and the North, South, East and West elevations the model is missing"));
    connect(elevations, &QAction::triggered, this, [this] {
        const QJsonObject r = bridge("create_drawings");
        if (!r.value("ok").toBool()) {
            m_status->showMessage(tr("Could not add them: %1").arg(r.value("error").toString()));
            return;
        }
        afterEdit(r);
        m_status->showMessage(tr("%n drawing(s) added", nullptr, r.value("created").toInt()));
    });
    QAction* through = view->addAction(tr("Select &hidden elements too"));
    through->setObjectName(QStringLiteral("actionSelectThrough"));
    through->setCheckable(true);
    through->setToolTip(tr("Box selection also takes elements hidden behind others (same as holding Alt while dragging)"));
    connect(through, &QAction::toggled, this, [this](bool on) {
        for (ViewHost* h : std::as_const(m_hosts))
            h->viewport()->setSelectThrough(on);
    });
    QAction* linesOnly = view->addAction(tr("&Lines only"));
    linesOnly->setObjectName(QStringLiteral("actionLinesOnly"));
    linesOnly->setShortcut(Qt::Key_L);
    linesOnly->setCheckable(true);
    linesOnly->setToolTip(tr("Show the model as a line drawing (hidden lines removed), e.g. for plans"));
    connect(linesOnly, &QAction::toggled, m_viewport, &Viewport::setLinesOnly);
    QAction* trueWeights = view->addAction(tr("&True line weights"));
    trueWeights->setObjectName(QStringLiteral("actionTrueLineWeights"));
    trueWeights->setCheckable(true);
    trueWeights->setChecked(m_prefs.trueLineWeights());
    trueWeights->setToolTip(tr("Draw lines as thick as their pens (otherwise every line is thin)"));
    connect(trueWeights, &QAction::toggled, this, &MainWindow::setTrueLineWeights);
    view->addSeparator();
    QAction* fit = view->addAction(tr("&Fit all"));
    fit->setShortcut(Qt::Key_F);
    connect(fit, &QAction::triggered, this, [this] { m_viewport->fitAll(); });
    { // D76: preset views and perspective for the active view (the view cube lives in Viewport).
        QMenu* views = view->addMenu(tr("&Views"));
        views->setObjectName(QStringLiteral("menuViews"));
        for (const StandardView& sv : standardViews()) {
            QAction* a = views->addAction(standardViewLabel(sv.orientation));
            a->setObjectName(QStringLiteral("actionView") + QLatin1String(sv.id));
            a->setShortcut(sv.shortcut);
            connect(a, &QAction::triggered, this, [this, o = sv.orientation] {
                if (m_viewport)
                    m_viewport->setStandardView(o);
            });
            if (sv.orientation == V3d_Xpos)
                views->addSeparator();
        }
        views->addSeparator();
        QAction* home = views->addAction(tr("&Home view"));
        home->setObjectName(QStringLiteral("actionHomeView"));
        home->setShortcut(Qt::Key_Home);
        home->setToolTip(tr("The default isometric view, fitted (the house beside the view cube)"));
        connect(home, &QAction::triggered, this, [this] {
            if (m_viewport)
                m_viewport->homeView();
        });
        // D92: the user can make the current view the home view (kept in the preferences).
        QAction* setHome = views->addAction(tr("Set current view as &home"));
        setHome->setObjectName(QStringLiteral("actionSetHomeView"));
        setHome->setToolTip(tr("The Home view button and shortcut turn to this direction from now on"));
        connect(setHome, &QAction::triggered, this, [this] {
            if (!m_viewport || m_viewport->isPlanView())
                return;
            m_viewport->useCurrentViewAsHome();
            const gp_Dir d = m_viewport->currentViewDirection(), u = m_viewport->currentViewUp();
            m_prefs.setValue(QStringLiteral("home_view"),
                QJsonArray{d.X(), d.Y(), d.Z(), u.X(), u.Y(), u.Z()});
            m_prefs.save();
            m_status->showMessage(tr("The current view is now the home view"));
        });
        QAction* perspective = view->addAction(tr("P&erspective"));
        perspective->setObjectName(QStringLiteral("actionPerspective"));
        perspective->setCheckable(true);
        perspective->setShortcut(QKeySequence(Qt::SHIFT | Qt::Key_P));
        perspective->setToolTip(tr("Show this 3D view in perspective instead of parallel projection (plans stay parallel)"));
        connect(perspective, &QAction::triggered, this, [this, perspective] {
            if (m_viewport && !m_viewport->isPlanView())
                m_viewport->setPerspective(!m_viewport->isPerspective());
            perspective->setChecked(m_viewport && m_viewport->isPerspective());
        });
        // Each view keeps its own camera: the check follows the active one. (Plan views ignore both.)
        connect(view, &QMenu::aboutToShow, this, [this, perspective] {
            perspective->setChecked(m_viewport && m_viewport->isPerspective());
        });
    }
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

    // D73: pens, line types, element styles, visibility, overrides, layer combinations and purposes.
    QMenu* graphics = m_menuBar->addMenu(tr("&Graphics"));
    auto editor = [this, graphics](const char* name, const QString& text, auto make) {
        QAction* a = graphics->addAction(text);
        a->setObjectName(QLatin1String(name));
        connect(a, &QAction::triggered, this, [this, make] {
            std::unique_ptr<GraphicsDialog> dialog(make(bridge("graphics_tables")));
            if (dialog->exec() != QDialog::Accepted)
                return;
            if (const QJsonObject c = dialog->changes(); !c.isEmpty())
                setGraphics(QString::fromUtf8(QJsonDocument(c).toJson(QJsonDocument::Compact)));
        });
        return a;
    };
    editor("actionPenSets", tr("&Pen sets..."), [this](const QJsonObject& r) { return new PenSetsDialog(r, this); });
    editor("actionLineTypes", tr("&Line types..."), [this](const QJsonObject& r) { return new LineTypesDialog(r, this); });
    editor("actionElementStyles", tr("&Element styles..."), [this](const QJsonObject& r) { return new ElementStylesDialog(r, this); });
    graphics->addSeparator();
    editor("actionVisibilitySets", tr("&Visibility sets..."), [this](const QJsonObject& r) { return new VisibilitySetsDialog(r, this); });
    editor("actionOverrides", tr("Graphic &overrides..."), [this](const QJsonObject& r) { return new OverridesDialog(r, this); });
    editor("actionRenovationFilters", tr("&Renovation filters..."), [this](const QJsonObject& r) { return new RenovationFiltersDialog(r, this); });
    editor("actionLayerCombinations", tr("Layer &combinations..."), [this](const QJsonObject& r) {
        const QStringList layers = bridge("layer_members").value("layers").toObject().keys();
        return new LayerCombinationsDialog(r, layers, QStringList(m_hiddenLayers.begin(), m_hiddenLayers.end()),
            QStringList(m_lockedLayers.begin(), m_lockedLayers.end()), this);
    });
    graphics->addSeparator();
    editor("actionPurposes", tr("P&urposes..."), [this](const QJsonObject& r) { return new PurposesDialog(r, this); });
    m_graphicsMenu = graphics;
    QMenu* help = m_menuBar->addMenu(tr("&Help"));
    m_helpMenu = help;
    QAction* about = help->addAction(tr("&About KimBim"));
    connect(about, &QAction::triggered, this, &MainWindow::showAbout);
}

void MainWindow::buildDocks()
{
    // D71: the panels are tabs in one area on the right (it can auto-hide or float).
    m_history = new HistoryPanel(this);
    m_layersPanel = new LayersPanel(this);
    m_drawingsPanel = new DrawingsPanel(this);
    m_sheetsPanel = new SheetsPanel(this);
    m_dock->addPanel(QStringLiteral("tree"), tr("Model"), m_tree);
    m_dock->addPanel(QStringLiteral("properties"), tr("Properties"), m_properties);
    m_dock->addPanel(QStringLiteral("layers"), tr("Layers"), m_layersPanel);
    m_dock->addPanel(QStringLiteral("history"), tr("History"), m_history);
    m_dock->addPanel(QStringLiteral("drawings"), tr("Drawings"), m_drawingsPanel);
    m_dock->addPanel(QStringLiteral("sheets"), tr("Sheets"), m_sheetsPanel);
    connect(m_history, &HistoryPanel::compareRequested, this, [this](const QString& a, const QString& b) { compareWith(a, b); });
    connect(m_history, &HistoryPanel::endCompareRequested, this, &MainWindow::endCompare);
    connect(m_history, &HistoryPanel::beforeAfterRequested, this, [this](const QString& guid) {
        if (!m_compareA.isEmpty())
            beforeAfterDialog(guid, m_compareA, m_compareB);
    });
    connect(m_history, &HistoryPanel::elementActivated, this, [this](const QString& guid) {
        m_viewport->selectGuids({guid});
        m_tree->selectGuids({guid});
        setSelection({guid});
    });
    connect(m_drawingsPanel, &DrawingsPanel::openRequested, this, [this](const QString& g) { openDrawing(g); });
    connect(m_sheetsPanel, &SheetsPanel::newRequested, this, &MainWindow::newSheetDialog);
    connect(m_sheetsPanel, &SheetsPanel::openRequested, this, [this](const QString& n) { openSheet(n); });
    connect(m_sheetsPanel, &SheetsPanel::placeRequested, this, [this](const QString& n) {
        const QString drawing = m_drawingsPanel->selectedDrawing();
        if (drawing.isEmpty()) {
            m_status->showMessage(tr("Select a drawing in the Drawings panel first"));
            return;
        }
        placeOnSheet(n, drawing);
    });
    connect(m_sheetsPanel, &SheetsPanel::purposeRequested, this, &MainWindow::setSheetPurpose);
    connect(m_sheetsPanel, &SheetsPanel::legendRequested, this, &MainWindow::placeLegend);
    connect(m_sheetsPanel, &SheetsPanel::symbolRequested, this, &MainWindow::placeSheetSymbol); // D87
    connect(m_sheetsPanel, &SheetsPanel::deleteRequested, this, [this](const QString& n) {
        const QJsonObject r = bridge("delete_sheet", {n});
        if (!r.value("ok").toBool())
            m_status->showMessage(tr("Could not delete it: %1").arg(r.value("error").toString()));
        afterEdit(r);
    });
    connect(m_drawingsPanel, &DrawingsPanel::renameRequested, this, [this](const QString& g, const QString& name) {
        const QJsonObject r = bridge("rename_drawing", {g, name});
        if (!r.value("ok").toBool())
            m_status->showMessage(tr("Could not rename it: %1").arg(r.value("error").toString()));
        afterEdit(r);
    });
    connect(m_drawingsPanel, &DrawingsPanel::deleteRequested, this, [this](const QString& g) {
        const QJsonObject r = bridge("delete_drawing", {g});
        if (!r.value("ok").toBool())
            m_status->showMessage(tr("Could not delete it: %1").arg(r.value("error").toString()));
        afterEdit(r);
    });
    m_dock->raisePanel(QStringLiteral("tree"));
    connect(m_layersPanel, &LayersPanel::visibilityToggled, this, &MainWindow::setLayerVisible);
    connect(m_layersPanel, &LayersPanel::lockToggled, this, &MainWindow::setLayerLocked);
    connect(m_layersPanel, &LayersPanel::activeRequested, this, &MainWindow::setActiveLayer);
    connect(m_layersPanel, &LayersPanel::assignRequested, this, &MainWindow::assignSelectionToLayer);
    connect(m_layersPanel, &LayersPanel::createRequested, this, [this] {
        bool ok = false;
        const QString name = QInputDialog::getText(this, tr("New layer"), tr("Layer name:"), QLineEdit::Normal, QString(), &ok);
        if (ok && !name.trimmed().isEmpty())
            createLayer(name.trimmed());
    });
    connect(m_layersPanel, &LayersPanel::deleteRequested, this, [this](const QString& name) {
        const QJsonObject r = bridge("delete_layer", {name});
        if (!r.value("ok").toBool())
            m_status->showMessage(r.value("error").toString());
        m_hiddenLayers.remove(name);
        m_lockedLayers.remove(name);
        afterEdit(r);
    });
    connect(m_layersPanel, &LayersPanel::renameRequested, this, [this](const QString& from, const QString& to) {
        const QJsonObject r = bridge("rename_layer", {from, to});
        if (!r.value("ok").toBool())
            m_status->showMessage(r.value("error").toString());
        else {
            if (m_hiddenLayers.remove(from))
                m_hiddenLayers.insert(to);
            if (m_lockedLayers.remove(from))
                m_lockedLayers.insert(to);
        }
        afterEdit(r);
    });
    connect(m_layersPanel, &LayersPanel::viewRequested, this, &MainWindow::applyView);
    connect(m_layersPanel, &LayersPanel::saveViewRequested, this, [this] {
        bool ok = false;
        const QString name = QInputDialog::getText(this, tr("Save view"), tr("View name:"), QLineEdit::Normal, m_currentView, &ok);
        if (ok && !name.trimmed().isEmpty())
            saveView(name.trimmed());
    });
    connect(m_layersPanel, &LayersPanel::deleteViewRequested, this, [this](const QString& name) {
        const QJsonObject r = bridge("delete_view", {name});
        if (m_currentView == name)
            m_currentView.clear();
        afterEdit(r);
    });
}

void MainWindow::buildCutsToolbar()
{
    // D75: in the title bar, after the menus.
    m_levels = new LevelsBar(m_titleBar);
    m_titleBar->addControl(m_levels);
    connect(m_levels, &LevelsBar::addLevelRequested, this, &MainWindow::addLevelDialog);
    connect(m_levels, &LevelsBar::levelsDialogRequested, this, &MainWindow::levelsDialog);
    connect(m_levels, &LevelsBar::newModelRequested, this, [this] {
        bool ok = false;
        const QString name = QInputDialog::getText(this, tr("New model"),
            tr("Model name (e.g. Apartment A). Draw it, then place it on levels with Place model:"), QLineEdit::Normal,
            QString(), &ok);
        if (ok && !name.trimmed().isEmpty())
            createModel(name.trimmed());
    });
    connect(m_levels, &LevelsBar::activeStoreyChanged, this, [this](const QString& storey, double elevation) {
        if (ViewHost* host = m_hosts.value(m_dock->current()); host && !host->storey().isEmpty() && host->storey() != storey) {
            openPlanTab(storey); // a plan tab shows one level: another level is another tab
            return;
        }
        updateCutSliderRange();
        m_viewport->setWorkPlaneZ(elevation);
        // A plan tab keeps its level and its camera (D71); only a 3D view put in plan mode follows.
        if (m_viewport->isPlanView() && m_hosts.value(m_dock->current()) && m_hosts.value(m_dock->current())->storey().isEmpty())
            m_viewport->setPlanView(elevation);
        if (m_viewport->isDrawingMode()) {
            m_wallTool->finish();
            m_polygonTool->cancel();
            m_viewport->setDrawingMode(true, elevation);
            refreshSnapData();
        }
        applyCuts();
        refreshLayers(); // models show only while one is active
        refreshAnnotations(); // each level has its own
    });
    auto cutButton = [this](QAction* action) {
        auto* b = new QToolButton(m_titleBar);
        b->setDefaultAction(action);
        b->setAutoRaise(true);
        m_titleBar->addControl(b);
    };
    m_titleBar->addControlSeparator();
    cutButton(m_planCut);
    m_cutHeight = new QDoubleSpinBox(m_titleBar);
    m_cutHeight->setObjectName(QStringLiteral("planCutHeight"));
    m_cutHeight->setRange(-1000.0, 10000.0);
    m_cutHeight->setDecimals(2);
    m_cutHeight->setSingleStep(0.1);
    m_cutHeight->setSuffix(QStringLiteral(" m"));
    m_cutHeight->setValue(1.2); // typical plan cut height above a floor
    m_cutHeight->setToolTip(tr("Plan cut height"));
    m_cutHeight->setMaximumWidth(fontMetrics().horizontalAdvance(QStringLiteral("-000.00 m")) + 64); // not as wide as -1000..10000
    m_titleBar->addControl(m_cutHeight);
    connect(m_cutHeight, &QDoubleSpinBox::valueChanged, this, [this](double metres) {
        {
            const QSignalBlocker block(m_cutSlider);
            m_cutSlider->setValue(int(std::lround(metres * 100)));
        }
        m_cutLabel->setText(formatLength(metres));
        if (m_planCut->isChecked())
            applyCuts();
        if (!m_assemblyType.isEmpty())
            refreshAnnotations(); // D88: the stairs' break lines are at the cut
    });
    connect(m_cutSlider, &QSlider::valueChanged, this, [this](int centimetres) {
        m_cutHeight->setValue(centimetres / 100.0); // updates the label and the cut
        if (!m_planCut->isChecked())
            m_planCut->setChecked(true); // using the slider means cutting
    });
    m_cutLabel->setText(formatLength(m_cutHeight->value()));
    cutButton(m_sectionBox);
}

void MainWindow::setPlanCutHeight(double metres)
{
    m_cutHeight->setValue(metres);
}

double MainWindow::planCutHeight() const
{
    return m_cutHeight->value();
}

void MainWindow::updateCutSliderRange()
{
    // From the level up to the next level (or 4 m), in centimetres.
    const QSignalBlocker block(m_cutSlider);
    m_cutSlider->setRange(0, int(std::lround(std::max(heightToNextLevel(), 1.0) * 100)));
    m_cutSlider->setValue(int(std::lround(m_cutHeight->value() * 100)));
}

void MainWindow::applyCuts()
{
    CutSettings& mine = m_cuts[m_viewport]; // the active view's cuts follow the controls
    mine.planCut = m_planCut->isChecked();
    mine.box = m_sectionBox->isChecked();
    mine.height = m_cutHeight->value();
    mine.bounds = m_boxBounds;
    CutState state;
    state.planCut = m_planCut->isChecked();
    // The cut height is measured from the active level (like a plan's view range).
    state.height = (m_levels ? m_levels->activeElevation() : 0.0) + m_cutHeight->value();
    state.box = m_sectionBox->isChecked();
    state.bounds = m_boxBounds;
    m_viewport->clearClipPlanes();
    m_viewport->addClipPlanes(makePlanes(state));
    m_viewport->setSectionHeight(state.planCut ? std::optional<double>(state.height) : std::nullopt);
}

void MainWindow::showAbout()
{
    QMessageBox::about(this, tr("About KimBim"),
        tr("KimBim %1\nOpen-source native BIM for architects, with version control built in.\n"
           "License: GPL-3.0-or-later")
            .arg(QStringLiteral(KIMBIM_VERSION)));
}

void MainWindow::showError(const QString& title, const QString& message)
{
    m_status->showMessage(message);
    if (!m_quiet)
        QMessageBox::critical(this, title, message);
}

void MainWindow::openDialog()
{
    const QString path = QFileDialog::getOpenFileName(this, tr("Open"), QString(),
        tr("KimBim and IFC files (*.kim *.ifc);;KimBim projects (*.kim);;IFC files (*.ifc)"));
    if (!path.isEmpty())
        openPath(path);
}

void MainWindow::openFile(const QString& path)
{
    stopLoading();
    closePlanTabs(); // the old model's levels
    m_viewport->clear();
    m_tree->clear();
    m_properties->clear();
    m_selection.clear();
    m_path = path;
    m_loading = true;
    m_loadedElements = 0;
    m_loadTimer.start();
    m_status->showMessage(tr("Opening %1...").arg(QFileInfo(path).fileName()));
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
    bridge("close_document"); // the lock and the working folder go
    if (!m_quiet) {
        m_prefs.setLayout(m_dock->saveLayout()); // D71: the next session's layout (D72: in preferences)
        m_prefs.setWindowGeometry(saveGeometry());
        m_prefs.save();
    }
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

QJsonObject MainWindow::bridgeInBackground(const char* fn, const QStringList& args, const QString& label)
{
    // A worker thread runs the call; a window-modal progress dialog keeps the window repainting while
    // blocking input, so nothing else reaches the bridge meanwhile (the recovery timer waits too).
    m_recoveryTimer.stop();
    QJsonObject r;
    QString error;
    const QByteArray name(fn);
    QThread* worker = QThread::create([&] { r = PythonEngine::instance().callJson(name.constData(), args, &error).object(); });
    QProgressDialog progress(label, QString(), 0, 0, this);
    progress.setWindowTitle(QStringLiteral("KimBim"));
    progress.setWindowModality(Qt::WindowModal);
    progress.setCancelButton(nullptr); // the Python call can't be interrupted
    progress.setMinimumDuration(m_quiet ? std::numeric_limits<int>::max() : 300);
    QEventLoop loop;
    connect(worker, &QThread::finished, &loop, &QEventLoop::quit);
    QApplication::setOverrideCursor(Qt::WaitCursor);
    worker->start();
    loop.exec(QEventLoop::ExcludeUserInputEvents);
    worker->wait();
    delete worker;
    QApplication::restoreOverrideCursor();
    restartRecoveryTimer();
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
    QStringList expanded = guids;
    expandAssemblies(expanded); // D88: a flight, landing or plan symbol selects its stair
    for (const QString& g : QStringList(expanded))
        if (const auto it = m_instanceOf.constFind(g); it != m_instanceOf.constEnd())
            for (const QString& m : m_instanceMembers.value(*it))
                if (!expanded.contains(m))
                    expanded << m;
    if (expanded.size() != guids.size()) { // a click on an instance takes the whole instance
        QStringList shown = expanded;
        for (const QString& g : expanded)
            if (m_assemblyType.contains(g))
                shown << g + QStringLiteral("~symbol") << g + QStringLiteral("~above");
        m_viewport->selectGuids(shown);
        m_tree->selectGuids(expanded);
    }
    expanded.removeIf([](const QString& g) { return g.contains(QLatin1Char('~')); });
    m_selection = expanded;
    // The bottom bar's summary: "1 Wall", "2 Walls", or "5 element(s)" for several kinds.
    QSet<QString> kinds;
    QStringList counted; // a stair counts once, not with its flights and landings (D88)
    for (const QString& g : expanded) {
        if (m_assemblyOf.contains(g))
            continue;
        counted << g;
        kinds.insert(m_assemblyType.value(g, m_viewport->typeOf(g)));
    }
    if (counted.isEmpty())
        m_status->setSelection(QString());
    else if (kinds.size() == 1)
        m_status->setSelection(QStringLiteral("%1 %2").arg(counted.size()).arg(counted.size() == 1
            ? ModelTreePanel::plainName(*kinds.constBegin()) : ModelTreePanel::plainPlural(*kinds.constBegin())));
    else
        m_status->setSelection(tr("%n element(s)", nullptr, int(counted.size())));
    refreshProperties();
    if (!guids.isEmpty())
        m_status->showMessage(tr("%n element(s) selected", nullptr, int(guids.size())));
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
    // The Dimensions group is live geometry, not a property set: it edits the elements' shape.
    if (pset == QLatin1String("KIMBIM_Annotation") && (prop == QLatin1String("Text") || prop == QLatin1String("Size"))) {
        bool all = true;
        for (const QString& g : std::as_const(m_selection)) {
            const QString v = value.isDouble() ? QString::number(value.toDouble(), 'g', 17) : value.toString();
            const QJsonObject r = bridge(prop == QLatin1String("Size") ? "set_annotation_size" : "set_annotation_text", {g, v});
            if (!r.value("ok").toBool())
                m_status->showMessage(tr("Could not change %1").arg(prop) + QStringLiteral(": ") + r.value("error").toString());
            all = all && r.value("ok").toBool();
            afterEdit(r);
        }
        return all;
    }
    const bool dimension = pset == QLatin1String("Dimensions");
    const bool parameter = pset == QLatin1String("Parameters"); // D86: a library object's (its type follows)
    const QJsonObject r = dimension || parameter
        ? bridge(parameter ? "set_object_parameter" : "set_dimension", {jsonList(m_selection), prop,
              value.isDouble() ? QString::number(value.toDouble(), 'g', 17) : value.toString()})
        : bridge("set_property", {jsonList(m_selection), pset, prop, jsonValue(value)});
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
        m_status->showMessage(tr("%1 changed on the type: %n element(s) updated", nullptr, r.value("elements").toInt()).arg(prop));
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

bool MainWindow::newFromTemplate(const QString& path)
{
    if (!prepareToOpen())
        return false;
    const QJsonObject r = bridge("new_from_template", {path});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not create the project"), r.value("error").toString());
        return false;
    }
    if (!r.value("path").toString().isEmpty()) { // an office template: load it like a file
        endCompare();
        openFile(r.value("path").toString());
        return true;
    }
    resetForNewModel(); // the old newProject() body after its bridge call
    return true;
}

bool MainWindow::newProject()
{
    return newFromTemplate(QStringLiteral("builtin"));
}

void MainWindow::resetForNewModel()
{
    closePlanTabs(); // the old model's levels
    m_viewport->clear();
    m_properties->clear();
    m_selection.clear();
    m_path.clear();
    m_tree->setTree(bridge("spatial_tree"));
    refreshLevels();
    m_types->clear();
    m_warnedInconsistent = false;
    afterEdit();
    refreshProject();
    loadProjectSettings();
    m_currentView.clear();
    refreshLayers();
    refreshAnnotations();
    refreshDrawings();
    refreshSheets();
    m_status->showMessage(tr("New project"));
}

void MainWindow::refreshLevels()
{
    const int before = m_levels->count();
    const QJsonArray storeys = bridge("storeys").value("storeys").toArray();
    QStringList keep; // plan tabs of levels that still exist (deleted or undone levels: their tabs go)
    for (const auto& s : storeys)
        keep << QStringLiteral("plan:") + s.toObject().value("guid").toString();
    closePlanTabs(keep);
    m_levels->setStoreys(storeys);
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

void MainWindow::levelsDialog()
{
    // D79 (Archicad's Story Settings): edited in the dialog, applied on OK as one undo step.
    const QJsonObject table = bridge("levels_table");
    const QString unit = m_settings.value("length_unit").toString(QStringLiteral("m"));
    const double factor = unit == QLatin1String("mm") ? 1000.0 : unit == QLatin1String("cm") ? 100.0 : 1.0;
    LevelsDialog dialog(table.value("levels").toArray(), unit, factor, m_settings.value("length_decimals").toInt(2), this);
    if (dialog.exec() != QDialog::Accepted || !dialog.table().modified())
        return;
    const QJsonObject r = bridge("edit_storeys",
        {QString::fromUtf8(QJsonDocument(dialog.table().changes()).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not change the levels"), r.value("error").toString());
        return;
    }
    afterEdit(r);
    m_status->showMessage(tr("Levels changed"));
}

void MainWindow::setPlanView(bool plan)
{
    // D71: a plan is its level's tab; 3 goes back to the 3D tab.
    if (plan)
        openPlanTab(m_levels->activeStorey());
    else
        m_dock->raise(QStringLiteral("3d"));
}

void MainWindow::buildModelingToolbar()
{
    // The tools' fields (type, heights, roof, length): a strip above the active view (D71).
    m_toolOptions = new ToolOptionsBar(this);
    ToolOptionsBar* bar = m_toolOptions;
    // File Edit View Model Graphics Versions Help (D75): Model goes before Graphics.
    auto* model = new QMenu(tr("&Model"), m_menuBar);
    m_menuBar->insertMenu(m_graphicsMenu->menuAction(), model);
    m_wallTool = new WallTool(this);
    m_polygonTool = new PolygonTool(this);
    m_hostTool = new HostTool(this);
    m_twoPointTool = new TwoPointTool(this);
    m_rotateTool = new RotateTool(this);
    m_gripTool = new GripTool(this);
    m_measure = new MeasureController([this](double m) { return formatLength(m); }, this);
    connect(m_measure, &MeasureController::message, this, [this](const QString& text) {
        if (m_tool == Tool::Measure)
            m_status->showMessage(text);
    });

    struct Def {
        Tool tool;
        const char* name;
        QString text;
        QKeyCombination key;
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
        {Tool::Split, "actionSplitTool", tr("Spli&t"), QKeyCombination(Qt::SHIFT, Qt::Key_S),
            tr("Split a wall or beam in two where you click; doors and windows stay where they are (Ctrl: pieces unjoined)")},
        {Tool::Trim, "actionTrimTool", tr("Trim/e&xtend"), QKeyCombination(Qt::SHIFT, Qt::Key_T),
            tr("Trim or extend walls and beams to a boundary, or two to their corner; click the side to keep")},
        {Tool::Join, "actionJoinTool", tr("&Join"), QKeyCombination(Qt::SHIFT, Qt::Key_J),
            tr("Join two walls that meet (L or T), merge two in line of the same type, or unjoin them")},
        {Tool::Stair, "actionStairTool", tr("S&tair"), Qt::Key_T,
            tr("Draw a stair (straight, L, U or by sketch) or a ramp; a stair goes up to the next level")},
        {Tool::Railing, "actionRailingTool", tr("Ra&iling"), QKeyCombination::fromCombined(0),
            tr("Railings on both sides of a clicked stair or ramp (they follow it), or along a clicked path")},
        {Tool::SlabOpening, "actionSlabOpeningTool", tr("Slab &opening"), Qt::Key_O,
            tr("Cut a hole in the selected slab: draw its outline like a slab")},
        {Tool::PlaceModel, "actionPlaceModelTool", tr("Place mo&del"), Qt::Key_U,
            tr("Place a model (an apartment drawn once) on this level: click where its origin goes; Shift turns it 90 degrees")},
        {Tool::Text, "actionTextTool", tr("Te&xt label"), Qt::Key_A, tr("Put a text label on the plan: click where it goes")},
        {Tool::Dimension, "actionDimensionTool", tr("Dimensi&on"), Qt::Key_Q,
            tr("Dimension: click the two points to measure, then where the dimension line goes")},
        {Tool::Mark, "actionMarkTool", tr("Mar&k"), Qt::Key_X, tr("Mark something on the plan: a circle with a tag")},
        {Tool::Leader, "actionLeaderTool", tr("&Leader"), QKeyCombination(Qt::SHIFT, Qt::Key_A),
            tr("Leader: click what it points at, then where its text goes")},
        {Tool::Roof, "actionRoofTool", tr("Roo&f"), QKeyCombination(Qt::SHIFT, Qt::Key_R),
            tr("Roof: draw its eaves outline like a slab; flat, shed, gable or hip with the pitch from the toolbar")},
        {Tool::Room, "actionRoomTool", tr("R&oom"), Qt::Key_Z,
            tr("Room: click inside walls; the room takes the shape they enclose and shows its name, number and area")},
        {Tool::Section, "actionSectionTool", tr("Sect&ion"), Qt::Key_V,
            tr("Section: click the two ends of the section line, then the side it looks at")},
        {Tool::Elevation, "actionElevationTool", tr("&Elevation"), QKeyCombination(Qt::SHIFT, Qt::Key_V),
            tr("Elevation: click the two ends of the elevation line, then the side it looks at")},
        {Tool::Measure, "actionMeasureTool", tr("Mea&sure"), QKeyCombination(Qt::SHIFT, Qt::Key_M),
            tr("Measure distances, angles and areas: click points (they snap); Enter stops, Esc clears. Changes nothing")},
        {Tool::Line, "actionLineTool", tr("L&ine"), QKeyCombination(Qt::SHIFT, Qt::Key_L),
            tr("Draw a 2D line on the plan: click its two ends, or type a length (length<angle)")},
        {Tool::Polyline, "actionPolylineTool", tr("&Polyline"), QKeyCombination(Qt::SHIFT, Qt::Key_Y),
            tr("Draw a 2D polyline: click points; click the first point to close it, Enter or double click to end it")},
        {Tool::ArcCircle, "actionArcTool", tr("&Arc/circle"), QKeyCombination(Qt::SHIFT, Qt::Key_C),
            tr("Draw a 2D circle (centre and radius) or arc (three points, or centre, start and end)")},
        {Tool::Rectangle, "actionRectangleTool", tr("Rec&tangle"), QKeyCombination(Qt::SHIFT, Qt::Key_E),
            tr("Draw a 2D rectangle: click two opposite corners, or type width;height")},
        {Tool::Fill, "actionFillTool", tr("&Fill"), QKeyCombination(Qt::SHIFT, Qt::Key_F),
            tr("Draw a fill (hatch): click its outline; Alt+click inside a closed polyline, rectangle or circle to fill it")},
        // D87: the annotation pack (MarkupTools.cpp)
        {Tool::Tag, "actionTagTool", tr("Ta&g"), QKeyCombination(Qt::SHIFT, Qt::Key_G),
            tr("Tag an element: click a door, window, wall or room; the tag shows its values and follows it")},
        {Tool::NorthArrow, "actionNorthArrowTool", tr("&North arrow"), QKeyCombination::fromCombined(0),
            tr("Place a north arrow: it points to the project's true north")},
        {Tool::ScaleBar, "actionScaleBarTool", tr("Scale &bar"), QKeyCombination::fromCombined(0), tr("Place a scale bar of the drawing scale")},
        {Tool::Cloud, "actionCloudTool", tr("Revision &cloud"), QKeyCombination::fromCombined(0),
            tr("Draw a revision cloud: click its outline; the revision goes in its triangle")},
        {Tool::AngleDimension, "actionAngleDimensionTool", tr("An&gle dimension"), QKeyCombination::fromCombined(0),
            tr("Angle dimension: click the vertex, a point on each side, then where the arc goes")},
        {Tool::RadialDimension, "actionRadialDimensionTool", tr("&Radius/diameter"), QKeyCombination::fromCombined(0),
            tr("Radius or diameter: click the centre, a point on the circle, then where the text goes")},
        {Tool::LevelDimension, "actionLevelDimensionTool", tr("&Level/spot elevation"), QKeyCombination::fromCombined(0),
            tr("Level dimension or spot elevation: click the point (it measures the slab below, or the level)")},
        {Tool::Object, "actionObjectTool", tr("O&bject"), QKeyCombination(Qt::SHIFT, Qt::Key_O),
            tr("Place a library object (furniture, sanitary, kitchen, trees...): pick it in the Library panel, click where it goes; Tab turns it 90 degrees")},
    };
    for (const Def& d : defs) {
        // shown in the tool palette (D71) and the Model menu; the palette gives it its icon (D90)
        auto* a = new QAction(d.text, this);
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
    QAction* tagAllAction = model->addAction(tr("Tag &all untagged")); // D87
    tagAllAction->setObjectName(QStringLiteral("actionTagAll"));
    tagAllAction->setToolTip(tr("Tag the doors, windows and walls of this level that the view shows and have no tag"));
    connect(tagAllAction, &QAction::triggered, this, [this] {
        if (!m_levels->activeStorey().isEmpty())
            tagAll();
    });
    model->addSeparator();
    model->addAction(m_levels->addLevelAction()); // D75: also in the level drop-down
    model->addAction(m_levels->levelsAction());   // D79: the levels table, also in the drop-down
    model->addAction(m_levels->newModelAction());
    QAction* copyAction = model->addAction(tr("Copy to &level..."));
    copyAction->setObjectName(QStringLiteral("actionCopyToLevel"));
    connect(copyAction, &QAction::triggered, this, &MainWindow::copyToLevelDialog);
    QAction* updateModels = model->addAction(tr("&Update model instances"));
    updateModels->setObjectName(QStringLiteral("actionUpdateModelInstances"));
    updateModels->setToolTip(tr("Apply the model's changes to every place it is used"));
    connect(updateModels, &QAction::triggered, this, &MainWindow::updateModelInstances);
    QAction* explode = model->addAction(tr("E&xplode model instance"));
    explode->setObjectName(QStringLiteral("actionExplodeInstance"));
    explode->setToolTip(tr("Unlink the selected instance: its elements become ordinary elements you can edit one by one"));
    connect(explode, &QAction::triggered, this, &MainWindow::explodeSelectedInstance);
    QAction* heightAction = model->addAction(tr("Wall &height..."));
    heightAction->setObjectName(QStringLiteral("actionWallHeight"));
    connect(heightAction, &QAction::triggered, this, &MainWindow::wallHeightDialog);
    QAction* checkAction = model->addAction(tr("Chec&k model...")); // D81: the Checks panel (Checks.cpp)
    checkAction->setObjectName(QStringLiteral("actionCheckModel"));
    checkAction->setToolTip(tr("Schema validation, IDS, clash detection and model checks"));
    connect(checkAction, &QAction::triggered, this, [this] { checksPanel(); });
    QAction* sizeAction = model->addAction(tr("Door/window si&ze..."));
    sizeAction->setObjectName(QStringLiteral("actionOpeningSize"));
    connect(sizeAction, &QAction::triggered, this, &MainWindow::openingSizeDialog);
    QAction* slabFromWallsAction = model->addAction(tr("Slab from selected &walls"));
    slabFromWallsAction->setObjectName(QStringLiteral("actionSlabFromWalls"));
    connect(slabFromWallsAction, &QAction::triggered, this, [this] { slabFromWalls(m_selection); });
    QAction* trimAction = model->addAction(tr("&Trim walls to roof"));
    trimAction->setObjectName(QStringLiteral("actionTrimToRoof"));
    trimAction->setToolTip(tr("Select a roof and walls: the walls reach up to the roof and stop at its underside"));
    connect(trimAction, &QAction::triggered, this, [this] { trimWallsToRoof(m_selection); });
    QAction* releaseAction = model->addAction(tr("&Release walls from roof"));
    releaseAction->setObjectName(QStringLiteral("actionReleaseFromRoof"));
    connect(releaseAction, &QAction::triggered, this, [this] { releaseWallsFromRoof(m_selection); });
    // D74: renovation status (Archicad keeps it under a menu; the views' right button navigates).
    model->addSeparator();
    QMenu* reno = model->addMenu(tr("Renovation &status"));
    reno->setObjectName(QStringLiteral("renovationMenu"));
    for (const QString& k : renovationKeys())
        connect(reno->addAction(renovationLabel(k)), &QAction::triggered, this, [this, k] { setRenovationStatus(k); });
    reno->addSeparator();
    QMenu* unmarkedMenu = reno->addMenu(tr("Mark unmarked elements as"));
    for (const QString& k : {QStringLiteral("existing"), QStringLiteral("demolish")})
        connect(unmarkedMenu->addAction(renovationLabel(k)), &QAction::triggered, this, [this, k] { markUnmarked(k); });

    m_types = new QComboBox(bar);
    m_types->setObjectName(QStringLiteral("typeCombo"));
    m_types->setToolTip(tr("Type"));
    m_types->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    m_types->setMinimumContentsLength(16);
    bar->addField(m_types);
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
    bar->addField(m_wallHeight);
    m_roofKind = new QComboBox(bar);
    m_roofKind->setObjectName(QStringLiteral("roofKind"));
    m_roofKind->addItem(tr("Flat"), QStringLiteral("flat"));
    m_roofKind->addItem(tr("Shed"), QStringLiteral("shed"));
    m_roofKind->addItem(tr("Gable"), QStringLiteral("gable"));
    m_roofKind->addItem(tr("Hip"), QStringLiteral("hip"));
    m_roofKind->setCurrentIndex(2);
    m_roofKind->setToolTip(tr("Roof kind"));
    m_roofPitch = new QDoubleSpinBox(bar);
    m_roofPitch->setObjectName(QStringLiteral("roofPitch"));
    m_roofPitch->setRange(1.0, 85.0);
    m_roofPitch->setDecimals(1);
    m_roofPitch->setValue(30.0);
    m_roofPitch->setSuffix(QStringLiteral("°"));
    m_roofPitch->setToolTip(tr("Roof pitch"));
    auto* roofBox = new QWidget(bar);
    auto* roofRow = new QHBoxLayout(roofBox);
    roofRow->setContentsMargins(0, 0, 0, 0);
    roofRow->addWidget(m_roofKind);
    roofRow->addWidget(m_roofPitch);
    bar->addField(roofBox);
    roofBox->setVisible(false);
    m_lengthInput = new QLineEdit(bar);
    m_lengthInput->setObjectName(QStringLiteral("lengthInput"));
    m_lengthInput->setPlaceholderText(tr("Length (m)"));
    m_lengthInput->setMaximumWidth(110);
    bar->addField(m_lengthInput);
    m_measureCopy = new QToolButton(bar);
    m_measureCopy->setObjectName(QStringLiteral("measureCopy"));
    m_measureCopy->setText(tr("Copy"));
    m_measureCopy->setToolTip(tr("Copy the measurement to the clipboard"));
    bar->addField(m_measureCopy);
    connect(m_measureCopy, &QToolButton::clicked, this, [this] { m_measure->copyToClipboard(); });
    setupModifyTools(bar); // D80
    setupDraftTools(bar);  // D84
    setupMarkupTools(bar); // D87
    setupLibrary(model);   // D86
    setupStairTools(bar);  // D88
    m_hosts.value(QStringLiteral("3d"))->adoptChrome(m_toolOptions, nullptr);
    connect(m_lengthInput, &QLineEdit::returnPressed, this, [this] {
        bool ok = false;
        double value = QLocale().toDouble(m_lengthInput->text(), &ok);
        if (!ok)
            value = QLocale::c().toDouble(QString(m_lengthInput->text()).replace(QLatin1Char(','), QLatin1Char('.')), &ok);
        bool typed = false;
        if (isDraftTool(m_tool)) { // D84: lengths, length<angle, radii, width;height
            if (m_draftTool->typeInput(m_lengthInput->text()))
                m_lengthInput->clear();
            m_viewport->setFocus();
            return;
        }
        if (m_tool == Tool::Wall)
            typed = m_wallTool->typeLength(value);
        else if (ok && m_tool == Tool::Rotate)
            typed = m_rotateTool->typeAngle(value); // degrees
        else if (ok && m_tool == Tool::Object) {
            setObjectAngle(value); // D86: degrees
            typed = true;
        }
        else if (ok && m_tool == Tool::Stretch)
            typed = m_gripTool->typeLength(value);
        else if (ok)
            typed = m_twoPointTool->typeLength(value);
        if (ok && typed)
            m_lengthInput->clear();
        m_viewport->setFocus();
    });
    setTool(Tool::None);

    onEachView([this](Viewport* v) { connect(v, &Viewport::workPointMoved, this, [this, v](QPointF p, double tolerance, Qt::KeyboardModifiers mods) {
        const bool ortho = mods & Qt::ShiftModifier;
        switch (m_tool) {
        case Tool::Wall:
            m_wallTool->setTolerance(tolerance);
            m_wallTool->setOrtho(ortho);
            showSnap(m_wallTool->move(p));
            break;
        case Tool::Slab:
        case Tool::Roof:
            m_polygonTool->setTolerance(tolerance);
            m_polygonTool->setOrtho(ortho);
            m_polygonTool->move(p);
            break;
        case Tool::Door:
        case Tool::Window:
            m_hostTool->setTolerance(tolerance);
            m_hostTool->move(p);
            break;
        case Tool::Railing:
            stairPointer(p, tolerance, mods, false); // D88
            break;
        case Tool::Stair:
            if (stairPointer(p, tolerance, mods, false)) // D88: a stair by sketch
                break;
            [[fallthrough]];
        case Tool::Beam:
        case Tool::Grid:
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
        case Tool::PlaceModel:
        case Tool::Text:
        case Tool::Dimension:
        case Tool::Mark:
        case Tool::Leader:
        case Tool::Room:
        case Tool::Mirror:
        case Tool::Section:
        case Tool::Elevation:
            m_twoPointTool->setTolerance(tolerance);
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
            if (draftGripActive()) { // D84: the drafting point follows the mouse
                QVector<QPointF> pts = m_gripPoints;
                const QPointF from = m_gripPoints[(m_gripIndex + 1) % m_gripPoints.size()];
                pts[m_gripIndex] = m_draftTool->snapper().snap(p, tolerance, &from, ortho).point;
                QVector<Viewport::PreviewBox> boxes;
                for (int i = 0; i + 1 < pts.size(); ++i)
                    boxes.push_back({pts[i], pts[i + 1], 0.02, m_levels->activeElevation(), m_levels->activeElevation() + 0.02});
                m_viewport->setPreviewBoxes(boxes);
                break;
            }
            m_gripTool->setTolerance(tolerance);
            m_gripTool->setOrtho(ortho);
            m_gripTool->move(p);
            break;
        case Tool::Measure:
            m_measure->pointer(v, p, m_levels->activeElevation(), tolerance, ortho, false);
            break;
        case Tool::Split:
        case Tool::Trim:
        case Tool::Join:
            m_modifyTool->setTolerance(tolerance);
            m_modifyTool->move(p);
            break;
        case Tool::Line:
        case Tool::Polyline:
        case Tool::ArcCircle:
        case Tool::Rectangle:
        case Tool::Fill:
        case Tool::Cloud:
            draftPointer(p, tolerance, mods, false);
            break;
        case Tool::Tag:
        case Tool::NorthArrow:
        case Tool::ScaleBar:
        case Tool::AngleDimension:
        case Tool::RadialDimension:
        case Tool::LevelDimension:
            markupPointer(p, tolerance, false);
            break;
        case Tool::Object:
            m_twoPointTool->setTolerance(tolerance);
            m_objectHover = m_twoPointTool->snapper().snap(p, tolerance).point;
            updateToolPreview();
            break;
        case Tool::None:
            break;
        }
    }); });
    onEachView([this](Viewport* v) { connect(v, &Viewport::workPointClicked, this, [this, v](QPointF p, double tolerance, Qt::KeyboardModifiers mods) {
        const bool ortho = mods & Qt::ShiftModifier;
        switch (m_tool) {
        case Tool::Wall:
            m_wallTool->setTolerance(tolerance);
            m_wallTool->setOrtho(ortho);
            m_wallTool->click(p);
            break;
        case Tool::Slab:
        case Tool::Roof:
            m_polygonTool->setTolerance(tolerance);
            m_polygonTool->setOrtho(ortho);
            m_polygonTool->click(p);
            break;
        case Tool::Door:
        case Tool::Window:
            m_hostTool->setTolerance(tolerance);
            m_hostTool->click(p);
            break;
        case Tool::Railing:
            stairPointer(p, tolerance, mods, true); // D88
            break;
        case Tool::Stair:
            if (stairPointer(p, tolerance, mods, true)) // D88: a stair by sketch
                break;
            [[fallthrough]];
        case Tool::Beam:
        case Tool::Grid:
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
        case Tool::Room:
            roomAt(p);
            break;
        case Tool::PlaceModel:
            m_twoPointTool->setTolerance(tolerance);
            placeModelAt(m_twoPointTool->snapper().snap(p, tolerance).point, ortho);
            break;
        case Tool::Text:
        case Tool::Dimension:
        case Tool::Mark:
        case Tool::Leader:
            m_twoPointTool->setTolerance(tolerance);
            annotationClick(m_twoPointTool->snapper().snap(p, tolerance).point, mods);
            break;
        case Tool::Section:
        case Tool::Elevation:
            m_twoPointTool->setTolerance(tolerance);
            drawingClick(m_twoPointTool->snapper().snap(p, tolerance).point);
            break;
        case Tool::Mirror: {
            m_twoPointTool->setTolerance(tolerance);
            m_annotationPoints << m_twoPointTool->snapper().snap(p, tolerance).point;
            if (m_annotationPoints.size() == 1) {
                m_status->showMessage(tr("Mirror: click the second point of the mirror line (Ctrl: mirror a copy)"));
            } else {
                const QVector<QPointF> pts = m_annotationPoints;
                m_annotationPoints.clear();
                mirrorSelection(pts[0], pts[1], mods & Qt::ControlModifier);
                setTool(Tool::None);
            }
            break;
        }
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
            if (!m_gripTool->isDragging() && draftGripClick(p, tolerance, ortho))
                break; // D84: a drafting shape's point
            m_gripTool->setTolerance(tolerance);
            m_gripTool->setOrtho(ortho);
            m_gripTool->click(p);
            break;
        case Tool::Measure:
            m_measure->pointer(v, p, m_levels->activeElevation(), tolerance, ortho, true);
            break;
        case Tool::Split:
        case Tool::Trim:
        case Tool::Join:
            m_modifyTool->setTolerance(tolerance);
            m_modifyTool->click(p, mods);
            break;
        case Tool::Line:
        case Tool::Polyline:
        case Tool::ArcCircle:
        case Tool::Rectangle:
        case Tool::Fill:
        case Tool::Cloud:
            draftPointer(p, tolerance, mods, true);
            break;
        case Tool::Tag:
        case Tool::NorthArrow:
        case Tool::ScaleBar:
        case Tool::AngleDimension:
        case Tool::RadialDimension:
        case Tool::LevelDimension:
            markupPointer(p, tolerance, true);
            break;
        case Tool::Object:
            m_twoPointTool->setTolerance(tolerance);
            placeObjectAt(m_twoPointTool->snapper().snap(p, tolerance).point, ortho);
            break;
        case Tool::None:
            break;
        }
    }); });
    onEachView([this](Viewport* v) { connect(v, &Viewport::drawingEnded, this, [this] {
        // Esc / right click: stop the current shape, or leave the tool when nothing is in progress.
        if (m_tool == Tool::Wall && m_wallTool->isDrawing())
            m_wallTool->finish();
        else if ((m_tool == Tool::Slab || m_tool == Tool::SlabOpening || m_tool == Tool::Roof) && m_polygonTool->isDrawing())
            m_polygonTool->cancel();
        else if ((m_tool == Tool::Beam || m_tool == Tool::Grid || m_tool == Tool::Move || m_tool == Tool::Stair)
            && m_twoPointTool->isDrawing())
            m_twoPointTool->cancel();
        else if (isDraftTool(m_tool) && m_draftTool->isDrawing())
            m_draftTool->escape(); // D84: a polyline ends open, anything else is dropped
        else if ((m_tool == Tool::Stair || m_tool == Tool::Railing) && m_pathTool->isDrawing())
            m_pathTool->escape(); // D88: a walking line or a path of two points or more is used
        else if (m_tool == Tool::Rotate && m_rotateTool->stage() > 0)
            m_rotateTool->cancel();
        else if (m_tool == Tool::Stretch && draftGripActive()) {
            m_gripIndex = -1;
            m_viewport->setPreviewBoxes({});
        } else if (m_tool == Tool::Stretch && m_gripTool->isDragging())
            m_gripTool->cancel();
        else if (isMarkupTool(m_tool) && (!m_annotationPoints.isEmpty() || !m_tagElement.isEmpty())) {
            m_annotationPoints.clear(); // D87: start the dimension or tag again
            m_tagElement.clear();
            updateMarkupPreview();
            startMarkupTool(m_tool);
        } else if (m_tool == Tool::Measure && m_measure->tool()->isMeasuring())
            m_measure->clear(); // D79: Esc clears the measurement; again leaves the tool
        else if ((m_tool == Tool::Trim || m_tool == Tool::Join) && m_modifyTool->stage() > 0) {
            m_modifyTool->cancel(); // a new boundary / first element
            m_status->showMessage(m_modifyTool->hint());
        }
        else
            setTool(Tool::None);
    }); });
    onEachView([this](Viewport* v) { connect(v, &Viewport::drawingConfirmed, this, [this] {
        if (m_tool == Tool::Wall)
            m_wallTool->finish();
        else if (m_tool == Tool::Slab || m_tool == Tool::SlabOpening || m_tool == Tool::Roof)
            m_polygonTool->finish();
        else if (m_tool == Tool::Measure)
            m_measure->finish();
        else if (isDraftTool(m_tool))
            m_draftTool->finish();
        else if (m_tool == Tool::Stair || m_tool == Tool::Railing)
            m_pathTool->finish(); // D88
    }); });
    onEachView([this](Viewport* v) { connect(v, &Viewport::lengthKeyTyped, this, [this](const QString& text) {
        if (m_lengthInput->isHidden() || m_toolOptions->isHidden())
            return;
        m_lengthInput->setFocus();
        m_lengthInput->insert(text);
    }); });
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
        else if (m_tool == Tool::Roof)
            createRoof(outline);
        else
            createSlab(outline);
    });
    connect(m_polygonTool, &PolygonTool::rejected, this, [this](const QString& why) { m_status->showMessage(why); });
    connect(m_hostTool, &HostTool::openingRequested, this, &MainWindow::insertOpening);
    setupInputAids(); // D89: tracker, guides (after the tool dispatch above: it reads what the tools snapped)
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
    case Tool::PlaceModel:
        source = "models";
        break;
    case Tool::Text:
    case Tool::Dimension:
    case Tool::Mark:
    case Tool::Leader:
    case Tool::Room:
    case Tool::Mirror:
    case Tool::Section:
    case Tool::Elevation:
        break;
    case Tool::Grid:
    case Tool::Measure:
    case Tool::Railing:
        break;
    case Tool::Split:
    case Tool::Trim:
    case Tool::Join:
    case Tool::Line:
    case Tool::Polyline:
    case Tool::ArcCircle:
    case Tool::Rectangle:
    case Tool::Fill:
    case Tool::Tag:
    case Tool::NorthArrow:
    case Tool::ScaleBar:
    case Tool::Cloud:
    case Tool::AngleDimension:
    case Tool::RadialDimension:
    case Tool::LevelDimension:
    case Tool::Object:
    case Tool::None:
        break;
    }
    const QString current = currentType().value("guid").toString();
    const QSignalBlocker block(m_types);
    m_types->clear();
    if (!source)
        return;
    const QJsonObject listing = bridge(source, args);
    for (const auto& t : listing.value(listing.contains("models") ? "models" : "types").toArray()) {
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
    const QVector<SnapPoint> points = Snapper::parsePoints(data); // D84: drafting shapes' points
    for (Snapper* s : {&m_wallTool->snapper(), &m_polygonTool->snapper(), &m_twoPointTool->snapper(),
             &m_rotateTool->snapper(), &m_gripTool->snapper(), &m_measure->tool()->snapper(), &m_modifyTool->snapper(),
             &m_draftTool->snapper()}) {
        s->setWalls(walls);
        s->setGridLines(lines);
        s->setPoints(points);
    }
    if (m_tool == Tool::Split || m_tool == Tool::Trim || m_tool == Tool::Join) // D80: beams too
        m_modifyTool->setTargets(data, bridge("modify_targets", {m_levels->activeStorey()}));
    m_hostTool->setWalls(walls);
    QVector<Viewport::GridLine> shown;
    for (const SnapLine& l : lines)
        shown.push_back({l.a, l.b, l.tag});
    m_viewport->setGridLines(shown, m_levels->activeElevation());
    refreshUnderlays(); // D85: and their snap points
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
    case Tool::Railing:
        updateStairPreview(); // D88 (StairTools.cpp)
        return;
    case Tool::SlabOpening:
    case Tool::Roof:
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
    case Tool::Measure: // draws its own path (MeasureController)
        break;
    case Tool::Split:
    case Tool::Trim:
    case Tool::Join:
        updateModifyPreview();
        return;
    case Tool::Line:
    case Tool::Polyline:
    case Tool::ArcCircle:
    case Tool::Rectangle:
    case Tool::Fill:
    case Tool::Cloud:
        updateDraftPreview();
        return;
    case Tool::Tag:
    case Tool::NorthArrow:
    case Tool::ScaleBar:
    case Tool::AngleDimension:
    case Tool::RadialDimension:
    case Tool::LevelDimension:
        updateMarkupPreview();
        return;
    case Tool::Object:
        updateObjectPreview();
        return;
    case Tool::None:
        break;
    }
    m_viewport->setPreviewBoxes(boxes);
}

void MainWindow::showSnap(const Snap& snap)
{
    static const char* const names[] = {"", QT_TR_NOOP("endpoint"), QT_TR_NOOP("midpoint"), QT_TR_NOOP("perpendicular"),
        QT_TR_NOOP("on wall"), QT_TR_NOOP("angle"), QT_TR_NOOP("grid"), QT_TR_NOOP("grid crossing"), QT_TR_NOOP("on grid line"),
        QT_TR_NOOP("wall face end"), QT_TR_NOOP("on wall face"), QT_TR_NOOP("centre"), QT_TR_NOOP("underlay endpoint"),
        QT_TR_NOOP("underlay midpoint"), QT_TR_NOOP("underlay crossing"), QT_TR_NOOP("on underlay line"),
        QT_TR_NOOP("intersection"), QT_TR_NOOP("guide crossing"), QT_TR_NOOP("on guide"), QT_TR_NOOP("parallel"),
        QT_TR_NOOP("tracker"), QT_TR_NOOP("typed")}; // D89
    QString text = tr("Wall: click the next point, type a length, Esc to finish");
    const auto preview = m_tool == Tool::Wall ? m_wallTool->preview() : m_twoPointTool->preview();
    if (preview) {
        const QPointF d = preview->second - preview->first;
        text = tr("Length %1").arg(formatLength(std::hypot(d.x(), d.y())));
    }
    if (snap.kind != Snap::None)
        text += QStringLiteral("  ·  ") + tr(names[snap.kind]);
    m_status->showMessage(text);
}

void MainWindow::setTool(Tool tool)
{
    // However setTool ends, the options strip shows only while a tool is active (D71).
    struct ShowOptions {
        MainWindow* w;
        ~ShowOptions() { w->m_toolOptions->setActive(w->m_tool != Tool::None); }
    } showOptions{this};
    if (m_inputAids)
        m_inputAids->reset(); // D89: typed values and guides belong to the tool
    if (tool != Tool::None && m_levels->activeStorey().isEmpty()) {
        showError(tr("Cannot model"), tr("The model has no level. Add a level first."));
        tool = Tool::None;
    }
    m_wallTool->finish();
    m_polygonTool->cancel();
    m_twoPointTool->cancel();
    m_draftTool->cancel();
    m_rotateTool->cancel();
    m_gripTool->cancel();
    m_measure->stop();
    m_columnHover.reset();
    m_objectHover.reset();
    m_annotationPoints.clear();
    m_tool = tool;
    m_measureCopy->setVisible(tool == Tool::Measure);
    startModifyTool(tool); // D80: its mode list in the options bar
    startDraftTool(tool);  // D84: line type, arc mode, fill pattern
    startStairTool(tool);  // D88: stair or ramp, shape, sizes; railing mode
    startMarkupTool(tool); // D87: tag style, shape, leader; radius/diameter, level/spot; revision
    m_twoPointTool->snapper().setFaceSnapping(tool == Tool::Dimension); // dimensions measure wall faces
    for (auto it = m_toolActions.constBegin(); it != m_toolActions.constEnd(); ++it) {
        const QSignalBlocker block(it.value());
        it.value()->setChecked(it.key() == int(tool));
    }
    m_wallHeight->setVisible(tool == Tool::Wall || tool == Tool::Column || tool == Tool::Beam || tool == Tool::Roof);
    m_wallHeight->setToolTip(tool == Tool::Roof ? tr("Eaves height above the level") : tr("Wall height"));
    m_roofKind->parentWidget()->setVisible(tool == Tool::Roof);
    m_lengthInput->setVisible(tool == Tool::Wall || tool == Tool::Beam || tool == Tool::Grid || tool == Tool::Move
        || tool == Tool::Rotate || tool == Tool::Stretch || isDraftTool(tool) || tool == Tool::Object);
    m_lengthInput->setPlaceholderText(tool == Tool::Rotate || tool == Tool::Object ? tr("Angle (degrees)") : tr("Length (m)"));
    if (m_objectTurn)
        m_objectTurn->setEnabled(tool == Tool::Object); // Tab moves the focus otherwise
    const bool typed = tool == Tool::Wall || tool == Tool::Slab || tool == Tool::Door || tool == Tool::Window
        || tool == Tool::Column || tool == Tool::Beam || tool == Tool::PlaceModel;
    m_types->setVisible(typed);
    const bool needsSlab = tool == Tool::SlabOpening
        && (m_selection.size() != 1 || m_viewport->typeOf(m_selection.first()) != QLatin1String("IfcSlab"));
    if (((tool == Tool::Move || tool == Tool::Rotate) && m_selection.isEmpty()) || needsSlab) {
        m_status->showMessage(needsSlab ? tr("Select one slab first, then draw the opening")
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
        m_status->clearMessage();
        return;
    }
    refreshSnapData();
    m_viewport->setDrawingMode(true, m_levels->activeElevation());
    m_viewport->setFocus();
    switch (tool) {
    case Tool::Wall:
        m_status->showMessage(tr("Wall: click the start point"));
        break;
    case Tool::Slab:
        m_status->showMessage(tr("Slab: click the outline's points; click the first point or press Enter to close"));
        break;
    case Tool::Column:
        m_status->showMessage(tr("Column: click to place it"));
        break;
    case Tool::Beam:
    case Tool::Grid:
        m_status->showMessage(tr("Click the first point"));
        break;
    case Tool::Move:
        m_status->showMessage(tr("Move: click a base point, then where it goes (Ctrl: detach joined walls)"));
        break;
    case Tool::Rotate:
        m_status->showMessage(tr("Rotate: click the centre, then a reference direction, then the new direction"));
        break;
    case Tool::Stretch:
        m_gripIndex = -1;
        m_status->showMessage(tr("Stretch: click near a wall end or a point of a line, arc or fill, then its new position"));
        break;
    case Tool::Measure:
        m_status->showMessage(m_measure->text());
        break;
    case Tool::Split:
    case Tool::Trim:
    case Tool::Join:
        m_status->showMessage(m_modifyTool->hint());
        break;
    case Tool::Line:
    case Tool::Polyline:
    case Tool::ArcCircle:
    case Tool::Rectangle:
    case Tool::Fill:
        m_status->showMessage(m_draftTool->hint());
        break;
    case Tool::Cloud:
    case Tool::Tag:
    case Tool::NorthArrow:
    case Tool::ScaleBar:
    case Tool::AngleDimension:
    case Tool::RadialDimension:
    case Tool::LevelDimension:
        startMarkupTool(tool); // D87: its first step's hint
        break;
    case Tool::Object:
        refreshLibrary();
        m_status->showMessage(tr("Object: click where it goes (Tab: turn 90 degrees, type an angle + Enter; Shift: turned for this click)"));
        break;
    case Tool::Stair:
    case Tool::Railing:
        startStairTool(tool); // D88: its hint
        break;
    case Tool::SlabOpening:
        m_status->showMessage(tr("Slab opening: draw the hole's outline; click the first point or press Enter to close"));
        break;
    case Tool::Text:
        m_status->showMessage(tr("Text: click where the label goes"));
        break;
    case Tool::Dimension:
        m_status->showMessage(tr("Dimension: click the first point to measure"));
        break;
    case Tool::Mark:
        m_status->showMessage(tr("Mark: click what to mark"));
        break;
    case Tool::Leader:
        m_status->showMessage(tr("Leader: click what it points at"));
        break;
    case Tool::Room:
        m_status->showMessage(tr("Room: click inside the walls that enclose it"));
        break;
    case Tool::Roof:
        m_status->showMessage(tr("Roof: click the eaves outline's points; click the first point or press Enter to close"));
        break;
    case Tool::Mirror:
        m_status->showMessage(m_selection.isEmpty() ? tr("Mirror: select what to mirror first")
                                                       : tr("Mirror: click the first point of the mirror line"));
        break;
    case Tool::Section:
        m_status->showMessage(tr("Section: click where the section line starts"));
        break;
    case Tool::Elevation:
        m_status->showMessage(tr("Elevation: click where the elevation line starts"));
        break;
    case Tool::PlaceModel:
        m_status->showMessage(m_types->count() ? tr("Place model: click where its origin goes (Shift: turned 90 degrees)")
                                                  : tr("There are no models yet: use New model... next to the levels"));
        break;
    default:
        m_status->showMessage(tr("Click on a wall to place it"));
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
        m_status->showMessage(tr("Could not move: %1").arg(r.value("error").toString()));
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
        m_status->showMessage(tr("Could not rotate: %1").arg(r.value("error").toString()));
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
        m_status->showMessage(tr("Could not stretch: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::setWallHeight(const QStringList& walls, double height)
{
    const QJsonObject r = bridge("set_wall_height", {jsonList(walls), QString::number(height, 'g', 17)});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not change the height: %1").arg(r.value("error").toString()));
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
        m_status->showMessage(tr("Select one door or window on the active level"));
        return false;
    }
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge("edit_opening", {guid, num(info.value("along").toDouble()), num(width), num(height), num(sill)});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not resize: %1").arg(r.value("error").toString()));
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
        m_status->showMessage(tr("Select one or more walls first"));
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
        m_status->showMessage(tr("Select one door or window on the active level"));
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
        m_status->showMessage(tr("Could not cut the opening: %1").arg(r.value("error").toString()));
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
    m_status->showMessage(tr("%n element(s) copied", nullptr, int(r.value("guids").toArray().size())));
    return true;
}

void MainWindow::copyToLevelDialog()
{
    if (m_selection.isEmpty()) {
        m_status->showMessage(tr("Select what to copy first"));
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

void MainWindow::buildVersions()
{
    // D75: everything about versions in one place: the Versions menu, which is also the title bar's
    // Versions button (it shows the current design option).
    QMenu* menu = new QMenu(tr("&Versions"), m_menuBar);
    menu->setObjectName(QStringLiteral("versionsMenu"));
    m_menuBar->insertMenu(m_helpMenu->menuAction(), menu);
    m_versionsMenu = menu;
    QAction* enable = menu->addAction(tr("&Enable versioning..."));
    enable->setObjectName(QStringLiteral("actionEnableVersioning"));
    enable->setToolTip(tr("Save the project as a .kim file, which keeps its versions and design options"));
    connect(enable, &QAction::triggered, this, &MainWindow::enableVersioningDialog);
    m_unversionedActions << enable;
    m_projectActions << menu->addSection(tr("Design options"));
    // refreshProject puts the options here, before New option...
    QAction* newOption = menu->addAction(tr("&New option..."));
    m_newOptionAction = newOption;
    m_projectActions << newOption;
    newOption->setObjectName(QStringLiteral("actionNewOption"));
    connect(newOption, &QAction::triggered, this, &MainWindow::newOptionDialog);
    QAction* deleteOptionAction = menu->addAction(tr("&Delete option..."));
    m_projectActions << deleteOptionAction;
    deleteOptionAction->setObjectName(QStringLiteral("actionDeleteOption"));
    connect(deleteOptionAction, &QAction::triggered, this, &MainWindow::deleteOptionDialog);
    QAction* combineAction = menu->addAction(tr("&Combine options..."));
    m_projectActions << combineAction;
    combineAction->setObjectName(QStringLiteral("actionCombineOptions"));
    combineAction->setToolTip(tr("Bring another design option's work into this one, choosing where both changed the same thing"));
    connect(combineAction, &QAction::triggered, this, &MainWindow::combineDialog);
    m_projectActions << menu->addSeparator();
    // Save version stays visible: in an unversioned project its shortcut says to enable versioning.
    QAction* saveVersionAction = menu->addAction(tr("Save &version..."));
    saveVersionAction->setObjectName(QStringLiteral("actionSaveVersion"));
    saveVersionAction->setShortcut(QKeySequence(Qt::CTRL | Qt::ALT | Qt::Key_S));
    connect(saveVersionAction, &QAction::triggered, this, &MainWindow::saveVersionDialog);
    QAction* milestoneAction = menu->addAction(tr("&Milestone..."));
    m_projectActions << milestoneAction;
    milestoneAction->setObjectName(QStringLiteral("actionAddMilestone"));
    milestoneAction->setToolTip(tr("Name the latest saved version (Concept, Schematic design, Tender...)"));
    connect(milestoneAction, &QAction::triggered, this, &MainWindow::milestoneDialog);
    QAction* objectHistoryAction = menu->addAction(tr("&Object history..."));
    m_projectActions << objectHistoryAction;
    objectHistoryAction->setObjectName(QStringLiteral("actionObjectHistory"));
    objectHistoryAction->setToolTip(tr("The versions that changed the selected element"));
    connect(objectHistoryAction, &QAction::triggered, this, &MainWindow::objectHistoryDialog);
    QAction* historyPanel = menu->addAction(tr("&History and compare"));
    m_projectActions << historyPanel;
    historyPanel->setObjectName(QStringLiteral("actionShowHistory"));
    historyPanel->setToolTip(tr("The History panel: the versions, and comparing two of them"));
    connect(historyPanel, &QAction::triggered, this, [this] { m_dock->raisePanel(QStringLiteral("history")); });
    for (QAction* a : std::as_const(m_projectActions))
        a->setVisible(false); // shown once the project is versioned

    m_optionGroup = new QActionGroup(this);
    m_versionsButton = new QToolButton(m_titleBar);
    m_versionsButton->setObjectName(QStringLiteral("versionsButton"));
    m_versionsButton->setAutoRaise(true);
    m_versionsButton->setPopupMode(QToolButton::InstantPopup);
    m_versionsButton->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    m_versionsButton->setMenu(menu);
    const QColor text = palette().color(QPalette::WindowText);
    QIcon icon; // a branch: the design options
    for (const qreal dpr : {1.0, 1.5, 2.0}) {
        QPixmap branch(QSize(16, 16) * dpr);
        branch.setDevicePixelRatio(dpr);
        branch.fill(Qt::transparent);
        QPainter p(&branch);
        p.setRenderHint(QPainter::Antialiasing);
        p.setPen(QPen(text, 1.3));
        p.drawLine(QPointF(5, 5.1), QPointF(5, 10.9));
        p.drawEllipse(QPointF(5, 3.5), 1.6, 1.6);
        p.drawEllipse(QPointF(5, 12.5), 1.6, 1.6);
        p.drawEllipse(QPointF(11.5, 4.5), 1.6, 1.6);
        QPainterPath arc(QPointF(11.5, 6.1));
        arc.cubicTo(QPointF(11.5, 9.5), QPointF(5, 8), QPointF(5, 10.9));
        p.drawPath(arc);
        p.end();
        icon.addPixmap(branch);
    }
    m_versionsButton->setIcon(icon);
    m_titleBar->setTrailing(m_versionsButton);
    updateVersionsButton();
}

void MainWindow::updateVersionsButton()
{
    if (m_versioned) {
        m_versionsButton->setText(m_currentOption);
        m_versionsButton->setToolTip(tr("Design option %1: switch options, save versions, history").arg(m_currentOption));
    } else {
        m_versionsButton->setText(tr("Versions"));
        m_versionsButton->setToolTip(tr("This project keeps no versions yet: enable versioning to save versions and design options"));
    }
}

void MainWindow::enableVersioningDialog()
{
    if (m_versioned || m_quiet)
        return;
    QString path = QFileDialog::getSaveFileName(this, tr("Enable versioning"), m_document.value("path").toString(),
        tr("KimBim project (*.kim)"));
    if (path.isEmpty())
        return;
    if (QFileInfo(path).suffix().compare(QLatin1String("kim"), Qt::CaseInsensitive) != 0)
        path += QStringLiteral(".kim");
    saveAs(path); // a .kim keeps the history: its first version is the model as it is
}

void MainWindow::buildPalette()
{
    // The View group's two commands that aren't drawing tools.
    auto* newPlan = new QAction(tr("New &plan tab"), this);
    newPlan->setObjectName(QStringLiteral("actionNewPlanTab"));
    newPlan->setToolTip(tr("Open the active level's floor plan in its own tab"));
    connect(newPlan, &QAction::triggered, this, [this] { openPlanTab(m_levels->activeStorey()); });
    auto* newSheet = new QAction(tr("New &sheet"), this);
    newSheet->setObjectName(QStringLiteral("actionNewSheet"));
    newSheet->setToolTip(tr("Add a sheet and open it"));
    connect(newSheet, &QAction::triggered, this,
        [this] { newSheetDialog(m_settings.value("sheet_paper").toString(QStringLiteral("A1"))); });
    // Mirror is a tool like the others: it shows as active while it is.
    QAction* mirror = findChild<QAction*>(QStringLiteral("actionMirror"));
    mirror->setCheckable(true);
    m_toolActions.insert(int(Tool::Mirror), mirror);

    auto act = [this](const char* name) { return findChild<QAction*>(QLatin1String(name)); };
    auto tool = [this](Tool t) { return m_toolActions.value(int(t)); };
    m_palette = new ToolPalette(this);
    m_palette->addGroup(QStringLiteral("3d"), tr("3D"), {tool(Tool::Wall), tool(Tool::Slab), tool(Tool::Column),
        tool(Tool::Beam), tool(Tool::Door), tool(Tool::Window), tool(Tool::Stair), tool(Tool::Railing), tool(Tool::Roof), tool(Tool::Room),
        tool(Tool::SlabOpening), tool(Tool::PlaceModel), tool(Tool::Object)});
    m_palette->addGroup(QStringLiteral("plane"), tr("Plane"), {tool(Tool::Text), tool(Tool::Dimension),
        tool(Tool::Leader), tool(Tool::Mark), tool(Tool::Grid), tool(Tool::Line), tool(Tool::Polyline),
        tool(Tool::ArcCircle), tool(Tool::Rectangle), tool(Tool::Fill), tool(Tool::Tag), tool(Tool::AngleDimension),
        tool(Tool::RadialDimension), tool(Tool::LevelDimension), tool(Tool::NorthArrow), tool(Tool::ScaleBar),
        tool(Tool::Cloud)});
    m_palette->addGroup(QStringLiteral("view"), tr("View"), {tool(Tool::Section), tool(Tool::Elevation),
        newPlan, newSheet});
    m_palette->addGroup(QStringLiteral("edit"), tr("Edit"), {tool(Tool::Move), tool(Tool::Rotate),
        tool(Tool::Stretch), tool(Tool::Split), tool(Tool::Trim), tool(Tool::Join), mirror, act("actionCopyToLevel"), tool(Tool::Measure)});
    // D90: related tools share one flyout button (the last one used shows on it).
    m_palette->addFlyout(QStringLiteral("plane"), {tool(Tool::Dimension), tool(Tool::AngleDimension),
        tool(Tool::RadialDimension), tool(Tool::LevelDimension)});
    m_palette->addFlyout(QStringLiteral("plane"), {tool(Tool::Line), tool(Tool::Polyline), tool(Tool::ArcCircle),
        tool(Tool::Rectangle)});
    m_palette->addFlyout(QStringLiteral("plane"), {tool(Tool::NorthArrow), tool(Tool::ScaleBar), tool(Tool::Cloud)});
    m_palette->addFlyout(QStringLiteral("view"), {tool(Tool::Section), tool(Tool::Elevation)});
    m_palette->setMode(ToolPalette::modeFromKey(m_prefs.value(QStringLiteral("palette_mode")).toString()));
    connect(m_palette, &ToolPalette::modeChanged, this, [this](ToolPalette::Mode mode) {
        m_prefs.setValue(QStringLiteral("palette_mode"), ToolPalette::modeKey(mode));
        if (!m_quiet)
            m_prefs.save();
    });
    ads::CDockWidget* toolsDock = m_dock->addLeft(QStringLiteral("tools"), tr("Tools"), m_palette);
    m_palette->contextMenu()->addSeparator();
    QAction* floatTools = m_palette->contextMenu()->addAction(tr("&Float"));
    floatTools->setObjectName(QStringLiteral("actionFloatTools"));
    connect(floatTools, &QAction::triggered, toolsDock, [toolsDock] { toolsDock->setFloating(); });
    QAction* hideTools = m_palette->contextMenu()->addAction(tr("&Auto-hide"));
    hideTools->setObjectName(QStringLiteral("actionAutoHideTools"));
    connect(hideTools, &QAction::triggered, toolsDock, [toolsDock] { toolsDock->setAutoHide(!toolsDock->isAutoHide()); });
    // View > Panels: a panel closed with its x comes back from here (D71).
    m_viewMenu->addSeparator();
    QMenu* panels = m_viewMenu->addMenu(tr("&Panels"));
    panels->setObjectName(QStringLiteral("panelsMenu"));
    for (const char* key : {"tools", "tree", "properties", "layers", "history", "drawings", "sheets"})
        if (ads::CDockWidget* d = m_dock->manager()->findDockWidget(QLatin1String(key)))
            panels->addAction(d->toggleViewAction());
    // D90: the panels used now and then cost no tab until opened (then closable): from here, the
    // Panels button of the panel area and their own commands.
    panels->addSeparator();
    const std::pair<const char*, const char*> rare[] = {{"actionFindSelect", "panel-findselect"},
        {"actionCheckModel", "panel-checks"}, {"actionObjectLibrary", "panel-library"}, {"actionSchedules", "panel-schedules"}};
    for (const auto& [name, icon] : rare)
        if (QAction* a = act(name)) {
            a->setIcon(themedIcon(QLatin1String(icon)));
            panels->addAction(a);
        }
    buildConsoleActions(); // D82
    if (QAction* console = act("actionConsole"))
        console->setIcon(themedIcon(QStringLiteral("panel-console")));
    m_dock->setPanelsMenu(panels);
}

void MainWindow::newSheetDialog(const QString& paper)
{
    bool ok = m_quiet;
    const QString title = m_quiet ? QString()
        : QInputDialog::getText(this, tr("New sheet"), tr("Title:"), QLineEdit::Normal, QString(), &ok);
    if (ok) {
        const QString number = addSheet(paper, title);
        if (!number.isEmpty())
            openSheet(number);
    }
}

void MainWindow::refreshProject()
{
    const QJsonObject s = bridge("project_state");
    m_versioned = s.value("versioned").toBool();
    for (QAction* a : std::as_const(m_projectActions))
        a->setVisible(m_versioned);
    for (QAction* a : std::as_const(m_unversionedActions))
        a->setVisible(!m_versioned);
    for (QAction* a : std::as_const(m_optionActions)) { // may be the action being triggered: later
        m_versionsMenu->removeAction(a);
        m_optionGroup->removeAction(a);
        a->setParent(nullptr);
        a->deleteLater();
    }
    m_optionActions.clear();
    QString option;
    if (!m_versioned) {
        m_projectFolder.clear();
        m_history->setVersions({});
        endCompare();
    } else {
        m_projectFolder = s.value("folder").toString();
        option = s.value("option").toString();
        for (const auto& o : s.value("options").toArray()) {
            const QString name = o.toString();
            auto* a = new QAction(name, m_versionsMenu);
            a->setObjectName(QStringLiteral("option:") + name);
            a->setCheckable(true);
            a->setChecked(name == option);
            m_optionGroup->addAction(a);
            m_versionsMenu->insertAction(m_newOptionAction, a);
            connect(a, &QAction::triggered, this, [this, name] {
                if (name != m_currentOption && !switchOption(name))
                    refreshProject(); // the check goes back to the current option
            });
            m_optionActions << a;
        }
        m_history->setVersions(bridge("history", {QStringLiteral("200")}).value("versions").toArray());
    }
    m_currentOption = option;
    updateVersionsButton();
    const QJsonObject doc = documentState();
    QString name = doc.value("untitled").toBool() ? tr("Untitled") : doc.value("name").toString();
    if (m_versioned)
        name += QStringLiteral(" (%1)").arg(option);
    if (doc.value("read_only").toBool())
        name += QStringLiteral(" [%1]").arg(tr("read-only"));
    setWindowTitle(QStringLiteral("KimBim — %1[*]").arg(name));
    setWindowModified(isDirty());
}

bool MainWindow::openPath(const QString& path)
{
    const QFileInfo info(path);
    if (info.isDir())
        return openProject(path);
    if (info.suffix().compare(QLatin1String("kim"), Qt::CaseInsensitive) == 0)
        return openKim(path);
    return openIfc(path);
}

// Before opening another file: the unsaved-work question, and the open file's recovery copy goes (the
// user saved or discarded). The open document stays attached until the new one has opened, so a file
// that fails to open (locked, damaged, cancelled) changes nothing.
bool MainWindow::prepareToOpen()
{
    if (!maybeSave())
        return false;
    stopLoading();
    bridge("clear_recovery");
    return true;
}

bool MainWindow::closeDocument()
{
    if (!maybeSave())
        return false;
    stopLoading();
    bridge("close_document");
    return true;
}

// A lock held by someone else: ask (quiet mode: read-only).
bool MainWindow::askReadOnly(const QJsonObject& r)
{
    if (!r.contains("locked"))
        return false;
    if (m_quiet)
        return true;
    return QMessageBox::question(this, tr("File in use"),
               tr("%1\nOpen it read-only?").arg(r.value("error").toString()),
               QMessageBox::Open | QMessageBox::Cancel, QMessageBox::Open) == QMessageBox::Open;
}

bool MainWindow::openKim(const QString& path, bool readOnly)
{
    if (!prepareToOpen())
        return false;
    QJsonObject r = bridge("open_kim", {path, readOnly ? QStringLiteral("1") : QString()});
    if (!r.value("ok").toBool() && askReadOnly(r))
        r = bridge("open_kim", {path, QStringLiteral("1")});
    if (!r.value("ok").toBool()) {
        if (!r.contains("locked"))
            showError(tr("Could not open the file"), r.value("error").toString());
        return false;
    }
    endCompare();
    openFile(r.value("path").toString());
    rememberRecent(path);
    return true;
}

MainWindow::LargeIfc MainWindow::askLargeIfc(const QString& path, double mb)
{
    const QString file = QFileInfo(path).fileName();
    if (m_quiet)
        return m_largeIfcAnswer ? m_largeIfcAnswer(file, mb) : LargeIfc::MakeKim;
    QMessageBox box(QMessageBox::Question, tr("Open IFC"),
        tr("%1 is a large model (%2 MB).").arg(file, QLocale().toString(mb, 'f', mb < 10.0 ? 1 : 0)), QMessageBox::Cancel, this);
    box.setInformativeText(tr("Making a KimBim project from it can take several minutes.\n\n"
        "Editing the IFC directly opens it at once, without version history, options, compare or "
        "combine, and project settings (cut height, layer states, drawing scale, units) aren't kept. "
        "You can make a .kim later with File > Save As."));
    QPushButton* make = box.addButton(tr("Make a .kim project"), QMessageBox::AcceptRole);
    QPushButton* direct = box.addButton(tr("Edit the IFC directly"), QMessageBox::AcceptRole);
    box.setDefaultButton(make);
    box.exec();
    return box.clickedButton() == make ? LargeIfc::MakeKim
        : box.clickedButton() == direct ? LargeIfc::EditIfc : LargeIfc::Cancel;
}

bool MainWindow::openIfc(const QString& path)
{
    bool direct = m_prefs.openIfc() == QLatin1String("edit_ifc");
    QJsonObject beside;
    if (!direct) {
        // asked before anything changes, so Cancel leaves the open document as it was
        beside = bridge("kim_beside", {path});
        const double mb = QFileInfo(path).size() / 1e6, limit = m_prefs.largeIfcMb();
        if (!beside.value("exists").toBool() && limit > 0.0 && mb > limit) {
            const LargeIfc answer = askLargeIfc(path, mb);
            if (answer == LargeIfc::Cancel)
                return false;
            direct = answer == LargeIfc::EditIfc;
        }
    }
    if (!prepareToOpen())
        return false;
    if (direct) {
        openFile(path);
        rememberRecent(path);
        m_askImportStatus = true; // once it has loaded
        return true;
    }
    QString kim = beside.value("kim").toString();
    if (beside.value("exists").toBool()) {
        auto answer = QMessageBox::Open;
        if (!m_quiet) {
            QMessageBox box(QMessageBox::Question, tr("Open IFC"),
                tr("%1 already exists next to %2.").arg(QFileInfo(kim).fileName(), QFileInfo(path).fileName()),
                QMessageBox::Open | QMessageBox::Cancel, this);
            QPushButton* make = box.addButton(tr("Make a new one"), QMessageBox::AcceptRole);
            box.setDefaultButton(QMessageBox::Open);
            box.exec();
            answer = box.clickedButton() == make ? QMessageBox::Save
                : box.clickedButton() == box.button(QMessageBox::Open) ? QMessageBox::Open : QMessageBox::Cancel;
        }
        if (answer == QMessageBox::Open)
            return openKim(kim);
        if (answer == QMessageBox::Cancel)
            return false;
        kim = beside.value("free").toString();
    }
    const QString label = tr("Making %1...").arg(QFileInfo(kim).fileName());
    m_status->showMessage(label);
    const QJsonObject r = bridgeInBackground("import_ifc", {path, kim},
        label + QLatin1Char('\n') + tr("Large models can take several minutes."));
    if (!r.value("ok").toBool()) {
        showError(tr("Could not make the project file"), r.value("error").toString());
        return false;
    }
    endCompare();
    openFile(r.value("path").toString());
    rememberRecent(kim);
    m_askImportStatus = true; // once loaded; the .kim's first version stays the IFC as it was
    return true;
}

bool MainWindow::openProject(const QString& folder, bool readOnly)
{
    if (!prepareToOpen())
        return false;
    QJsonObject r = bridge("open_folder", {folder, readOnly ? QStringLiteral("1") : QString()});
    if (!r.value("ok").toBool() && askReadOnly(r))
        r = bridge("open_folder", {folder, QStringLiteral("1")});
    if (!r.value("ok").toBool()) {
        if (!r.contains("locked"))
            showError(tr("Could not open the project"), r.value("error").toString());
        return false;
    }
    endCompare();
    openFile(r.value("path").toString());
    rememberRecent(folder);
    return true;
}

void MainWindow::rememberRecent(const QString& path)
{
    m_prefs.addRecent(QDir::toNativeSeparators(QFileInfo(path).absoluteFilePath()));
    m_prefs.save();
}

void MainWindow::fillRecentMenu()
{
    m_recentMenu->clear();
    for (const QString& p : m_prefs.recent())
        m_recentMenu->addAction(p, this, [this, p] { openPath(p); });
    if (m_recentMenu->isEmpty())
        m_recentMenu->addAction(tr("(none)"))->setEnabled(false);
}

void MainWindow::openProjectDialog()
{
    const QString folder = QFileDialog::getExistingDirectory(this, tr("Open a KimBim project folder"));
    if (!folder.isEmpty())
        openProject(folder);
}

bool MainWindow::saveVersion(const QString& message)
{
    if (!commitVersion(message))
        return false; // (the bridge packs a .kim when its history changes)
    refreshProject();
    return true;
}

bool MainWindow::commitVersion(const QString& message)
{
    const QJsonObject r = bridge("save_version", {message});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("No version saved: %1").arg(r.value("error").toString()));
        refreshProject();
        return false;
    }
    m_savesSinceVersion = 0;
    m_sinceVersion.restart();
    afterEdit();
    refreshProject();
    m_status->showMessage(tr("Version saved: %1 added, %2 modified, %3 removed")
                                 .arg(r.value("added").toInt()).arg(r.value("modified").toInt()).arg(r.value("removed").toInt()));
    return true;
}

void MainWindow::saveVersionDialog()
{
    if (!m_versioned) {
        m_status->showMessage(tr("Enable versioning first (Versions menu)"));
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
        m_status->showMessage(tr("Could not compare: %1").arg(r.value("error").toString()));
        return false;
    }
    QHash<QString, QColor> colors;
    for (const auto& v : r.value("added").toArray())
        colors.insert(v.toObject().value("guid").toString(), HistoryPanel::addedColor());
    for (const auto& v : r.value("modified").toArray())
        colors.insert(v.toObject().value("guid").toString(), HistoryPanel::modifiedColor());
    m_viewport->setElementColors(colors);
    m_compareA = revA;
    m_compareB = revB;
    m_history->setChanges(r);
    m_status->showMessage(tr("Compare: %1 added, %2 modified, %3 removed")
                                 .arg(r.value("added").toArray().size()).arg(r.value("modified").toArray().size())
                                 .arg(r.value("removed").toArray().size()));
    return true;
}

void MainWindow::endCompare()
{
    m_viewport->clearElementColors();
    m_compareA.clear();
    m_compareB.clear();
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
    m_status->showMessage(tr("Now working on option %1").arg(name));
    return true;
}

bool MainWindow::addMilestone(const QString& name, const QString& message)
{
    const QJsonObject r = bridge("create_milestone", {name, message});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not add the milestone"), r.value("error").toString());
        return false;
    }
    refreshProject();
    m_status->showMessage(tr("Milestone %1 marks the latest version").arg(name));
    return true;
}

void MainWindow::milestoneDialog()
{
    if (hasUnversionedWork() && !m_quiet) {
        const auto answer = QMessageBox::question(this, tr("Milestone"),
            tr("A milestone names a saved version. Save a version of your changes first?"),
            QMessageBox::Save | QMessageBox::Cancel, QMessageBox::Save);
        if (answer != QMessageBox::Save)
            return;
        saveVersionDialog();
        if (hasUnversionedWork())
            return;
    }
    QDialog dialog(this);
    dialog.setWindowTitle(tr("Milestone"));
    auto* form = new QFormLayout(&dialog);
    auto* name = new QComboBox(&dialog);
    name->setEditable(true);
    name->addItems({tr("Concept"), tr("Schematic design"), tr("Design development"), tr("Permit"), tr("Tender"),
        tr("Construction")});
    name->setMinimumWidth(260);
    auto* note = new QLineEdit(&dialog);
    form->addRow(tr("Name:"), name);
    form->addRow(tr("Note:"), note);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    form->addRow(buttons);
    if (dialog.exec() == QDialog::Accepted && !name->currentText().trimmed().isEmpty())
        addMilestone(name->currentText().trimmed(), note->text().trimmed());
}

bool MainWindow::combineOptions(const QString& option, const QJsonObject& choices)
{
    const QJsonObject r = bridge("combine_options",
        {option, QString::fromUtf8(QJsonDocument(choices).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not combine the options"), r.value("error").toString());
        return false;
    }
    const QString status = r.value("status").toString();
    if (status == QLatin1String("up_to_date")) {
        m_status->showMessage(tr("This option already contains everything in %1").arg(option));
        return true;
    }
    endCompare();
    openFile(r.value("path").toString());
    // Colour what the other option brought (green) and what was chosen in a conflict (orange) once
    // the combined model is shown.
    QHash<QString, QColor> colors;
    for (const auto& g : r.value("from_theirs").toArray())
        colors.insert(g.toString(), HistoryPanel::addedColor());
    for (const auto& g : r.value("resolved").toArray())
        colors.insert(g.toString(), HistoryPanel::modifiedColor());
    auto connection = std::make_shared<QMetaObject::Connection>();
    *connection = connect(this, &MainWindow::loadFinished, this, [this, colors, connection, status, option](int, bool stopped) {
        disconnect(*connection);
        if (stopped)
            return;
        m_viewport->setElementColors(colors);
        refreshProject();
        m_status->showMessage(status == QLatin1String("fast_forward")
                ? tr("This option now has %1's latest version").arg(option)
                : tr("Combined with %1: review it (changes from %1 in green, your choices in orange), then Save version or Discard").arg(option));
    });
    return true;
}

void MainWindow::combineDialog()
{
    if (!m_versioned) {
        m_status->showMessage(tr("Combining needs a versioned project with design options"));
        return;
    }
    if (hasUnversionedWork() && !resolveUnsavedForSwitch())
        return;
    QStringList others;
    for (const auto& o : bridge("options").value("options").toArray())
        if (o.toString() != m_currentOption)
            others << o.toString();
    if (others.isEmpty()) {
        m_status->showMessage(tr("There is no other option to combine with"));
        return;
    }
    CombineDialog dialog([this](const char* fn, const QStringList& args) { return bridge(fn, args); }, others, this);
    connect(&dialog, &CombineDialog::elementActivated, this, [this](const QString& guid) {
        m_viewport->selectGuids({guid});
        setSelection({guid});
    });
    if (dialog.exec() == QDialog::Accepted)
        combineOptions(dialog.option(), dialog.resolutions());
}

bool MainWindow::deleteOption(const QString& name)
{
    const QJsonObject r = bridge("delete_option", {name});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not delete the option"), r.value("error").toString());
        return false;
    }
    refreshProject();
    m_status->showMessage(tr("Option %1 deleted").arg(name));
    return true;
}

void MainWindow::deleteOptionDialog()
{
    QStringList others;
    for (const auto& o : bridge("options").value("options").toArray())
        if (o.toString() != m_currentOption && o.toString() != QLatin1String("main"))
            others << o.toString();
    if (others.isEmpty()) {
        m_status->showMessage(tr("No other option to delete (the current one and main can't be deleted)"));
        return;
    }
    bool ok = false;
    const QString name = QInputDialog::getItem(this, tr("Delete option"), tr("Option to delete:"), others, 0, false, &ok);
    if (!ok)
        return;
    if (QMessageBox::warning(this, tr("Delete option"),
            tr("Delete the design option %1 and its versions? Milestones on it are kept.").arg(name),
            QMessageBox::Yes | QMessageBox::Cancel, QMessageBox::Cancel)
        == QMessageBox::Yes)
        deleteOption(name);
}

QJsonObject MainWindow::objectHistory(const QString& guid)
{
    return bridge("element_history", {guid});
}

QJsonObject MainWindow::beforeAfter(const QString& guid, const QString& revA, const QString& revB)
{
    return bridge("before_after", {guid, revA, revB});
}

void MainWindow::objectHistoryDialog()
{
    if (m_selection.size() != 1) {
        m_status->showMessage(tr("Select one element to see its history"));
        return;
    }
    const QString guid = m_selection.first();
    const QJsonObject r = objectHistory(guid);
    if (!r.value("ok").toBool()) {
        showError(tr("Object history"), r.value("error").toString());
        return;
    }
    QDialog dialog(this);
    dialog.setObjectName(QStringLiteral("objectHistoryDialog"));
    dialog.setWindowTitle(tr("Object history"));
    auto* layout = new QVBoxLayout(&dialog);
    auto* table = new QTableWidget(&dialog);
    const QStringList headers = {tr("Version"), tr("Change"), tr("Author"), tr("Date")};
    table->setColumnCount(int(headers.size()));
    table->setHorizontalHeaderLabels(headers);
    table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    table->setSelectionMode(QAbstractItemView::SingleSelection);
    const QJsonArray versions = r.value("versions").toArray();
    table->setRowCount(int(versions.size()));
    const QHash<QString, QString> changes = {{QStringLiteral("added"), tr("added")}, {QStringLiteral("modified"), tr("modified")},
        {QStringLiteral("removed"), tr("removed")}, {QStringLiteral("unsaved"), tr("unsaved changes")}};
    for (int i = 0; i < versions.size(); ++i) {
        const QJsonObject v = versions[i].toObject();
        QStringList marks;
        for (const auto& m : v.value("milestones").toArray())
            marks << m.toString();
        QString title = v.value("message").toString();
        if (!marks.isEmpty())
            title = QStringLiteral("◆ %1 — %2").arg(marks.join(QStringLiteral(", ")), title);
        auto* first = new QTableWidgetItem(v.value("change").toString() == QLatin1String("unsaved") ? tr("(not saved yet)") : title);
        first->setData(Qt::UserRole, v.value("id").toString());
        table->setItem(i, 0, first);
        table->setItem(i, 1, new QTableWidgetItem(changes.value(v.value("change").toString())));
        table->setItem(i, 2, new QTableWidgetItem(v.value("author").toString()));
        const qint64 t = v.value("time").toInteger();
        table->setItem(i, 3, new QTableWidgetItem(t ? QLocale().toString(QDateTime::fromSecsSinceEpoch(t), QLocale::ShortFormat) : QString()));
    }
    table->horizontalHeader()->setStretchLastSection(true);
    table->resizeColumnsToContents();
    table->setMinimumSize(560, 260);
    layout->addWidget(new QLabel(tr("Versions that changed this element (or its properties), newest first:"), &dialog));
    layout->addWidget(table);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Close, &dialog);
    QPushButton* compareButton = buttons->addButton(tr("Before/after with current..."), QDialogButtonBox::ActionRole);
    compareButton->setEnabled(false);
    connect(table, &QTableWidget::itemSelectionChanged, &dialog, [table, compareButton] {
        const auto items = table->selectedItems();
        compareButton->setEnabled(!items.isEmpty() && table->item(items.first()->row(), 0)->data(Qt::UserRole).toString() != QLatin1String("WORKING"));
    });
    connect(compareButton, &QPushButton::clicked, &dialog, [this, table, guid] {
        const auto items = table->selectedItems();
        if (!items.isEmpty())
            beforeAfterDialog(guid, table->item(items.first()->row(), 0)->data(Qt::UserRole).toString(), QStringLiteral("WORKING"));
    });
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    layout->addWidget(buttons);
    dialog.exec();
}

void MainWindow::beforeAfterDialog(const QString& guid, const QString& revA, const QString& revB)
{
    const QJsonObject r = beforeAfter(guid, revA, revB);
    if (!r.value("ok").toBool()) {
        showError(tr("Before/after"), r.value("error").toString());
        return;
    }
    QDialog dialog(this);
    dialog.setObjectName(QStringLiteral("beforeAfterDialog"));
    dialog.setWindowTitle(tr("Before/after"));
    auto* layout = new QVBoxLayout(&dialog);
    auto* only = new QCheckBox(tr("Only what changed"), &dialog);
    only->setChecked(true);
    auto* table = new QTableWidget(&dialog);
    const auto label = [](const QString& rev) {
        return rev == QLatin1String("WORKING") ? tr("Current") : rev.left(8);
    };
    table->setColumnCount(3);
    table->setHorizontalHeaderLabels({tr("Field"), tr("Before (%1)").arg(label(revA)), tr("After (%1)").arg(label(revB))});
    table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    const QJsonArray rows = r.value("rows").toArray();
    table->setRowCount(int(rows.size()));
    for (int i = 0; i < rows.size(); ++i) {
        const QJsonObject row = rows[i].toObject();
        const bool changed = row.value("changed").toBool();
        const QStringList cells = {row.value("field").toString(), row.value("before").toString(), row.value("after").toString()};
        for (int c = 0; c < 3; ++c) {
            auto* item = new QTableWidgetItem(cells[c]);
            if (changed && c > 0)
                item->setBackground(HistoryPanel::modifiedColor().lighter(160));
            table->setItem(i, c, item);
        }
        table->item(i, 0)->setData(Qt::UserRole, changed);
    }
    const auto filter = [table, only] {
        for (int i = 0; i < table->rowCount(); ++i)
            table->setRowHidden(i, only->isChecked() && !table->item(i, 0)->data(Qt::UserRole).toBool());
    };
    connect(only, &QCheckBox::toggled, &dialog, filter);
    filter();
    table->horizontalHeader()->setStretchLastSection(true);
    table->resizeColumnsToContents();
    table->setMinimumSize(640, 320);
    if (!r.value("before_exists").toBool())
        layout->addWidget(new QLabel(tr("The element did not exist in the earlier version."), &dialog));
    if (!r.value("after_exists").toBool())
        layout->addWidget(new QLabel(tr("The element was deleted in the later version."), &dialog));
    layout->addWidget(only);
    layout->addWidget(table);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Close, &dialog);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    layout->addWidget(buttons);
    dialog.exec();
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
    if (!hasUnversionedWork())
        return true;
    if (m_quiet)
        return false; // never a modal dialog in quiet mode
    const auto answer = QMessageBox::warning(this, tr("Unsaved changes"),
        tr("Save a version of your changes before switching options?"),
        QMessageBox::Save | QMessageBox::Discard | QMessageBox::Cancel, QMessageBox::Save);
    if (answer == QMessageBox::Save) {
        saveVersionDialog();
        return !hasUnversionedWork();
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

static QPointF dragTarget(Snapper& snapper, QPointF start, QPointF current, double tolerance, Qt::KeyboardModifiers m)
{
    return snapper.snap(current, tolerance, &start, m & Qt::ShiftModifier).point;
}

void MainWindow::dragMoveTo(QPointF start, QPointF current, double tolerance, Qt::KeyboardModifiers modifiers)
{
    if (m_selection.isEmpty())
        return;
    const QPointF delta = dragTarget(m_twoPointTool->snapper(), start, current, tolerance, modifiers) - start;
    // Preview: the selection's footprint where it would go, plus the drag line.
    double x0, y0, z0, x1, y1, z1;
    const Bnd_Box box = m_viewport->boundsOf(m_selection);
    QVector<Viewport::PreviewBox> boxes;
    if (!box.IsVoid()) {
        box.Get(x0, y0, z0, x1, y1, z1);
        const QPointF a(x0 + delta.x(), y0 + delta.y()), b(x1 + delta.x(), y0 + delta.y()),
            c(x1 + delta.x(), y1 + delta.y()), d(x0 + delta.x(), y1 + delta.y());
        for (const auto& [p, q] : {std::pair{a, b}, std::pair{b, c}, std::pair{c, d}, std::pair{d, a}})
            boxes.push_back({p, q, 0.04, z0, z1});
    }
    boxes.push_back({start, start + delta, 0.03, m_levels->activeElevation(), m_levels->activeElevation() + 0.02});
    m_viewport->setPreviewBoxes(boxes);
    m_status->showMessage(tr("Move %1 (Ctrl: copy, Alt: detach joined walls, Shift: straight)")
                                 .arg(formatLength(std::hypot(delta.x(), delta.y()))));
}

bool MainWindow::dragFinished(QPointF start, QPointF current, double tolerance, Qt::KeyboardModifiers modifiers)
{
    m_viewport->setPreviewBoxes({});
    const QPointF delta = dragTarget(m_twoPointTool->snapper(), start, current, tolerance, modifiers) - start;
    if (std::hypot(delta.x(), delta.y()) < 1e-4)
        return false;
    if (modifiers & Qt::ControlModifier) // Archicad: Ctrl while dragging makes a copy
        return copySelection(delta);
    return moveSelection(delta, modifiers & Qt::AltModifier);
}

void MainWindow::refreshLayers()
{
    const QJsonObject state = bridge("layer_members"); // one pass over the model per edit
    const QJsonObject members = state.value("layers").toObject();
    QJsonArray listing;
    for (auto it = members.constBegin(); it != members.constEnd(); ++it) // QJsonObject keys are sorted
        listing.append(QJsonObject{{"name", it.key()}, {"count", it.value().toArray().size()}});
    QSet<QString> hidden, locked;
    for (auto it = members.constBegin(); it != members.constEnd(); ++it)
        for (const auto& g : it.value().toArray()) {
            if (m_hiddenLayers.contains(it.key()))
                hidden.insert(g.toString());
            if (m_lockedLayers.contains(it.key()))
                locked.insert(g.toString());
        }
    const QJsonObject inModels = bridge("model_elements");
    const QString active = m_levels->activeStorey();
    if (m_levels->activeIsModel()) { // drawing a model: only that model
        const QJsonArray mine = inModels.value("models").toObject().value(active).toArray();
        QSet<QString> keep;
        for (const auto& g : mine)
            keep.insert(g.toString());
        for (const QString& g : m_viewport->guids())
            if (!keep.contains(g))
                hidden.insert(g);
    } else {
        for (const auto& g : inModels.value("guids").toArray())
            hidden.insert(g.toString());
    }
    m_instanceOf.clear();
    m_instanceMembers.clear();
    const QJsonObject instances = bridge("instance_members").value("instances").toObject();
    for (auto it = instances.constBegin(); it != instances.constEnd(); ++it)
        for (const auto& g : it.value().toArray()) {
            m_instanceOf.insert(g.toString(), it.key());
            m_instanceMembers[it.key()] << g.toString();
        }
    m_viewport->setLayerState(hidden, locked);
    m_layersPanel->setLayers(listing, state.value("active").toString(), m_hiddenLayers, m_lockedLayers);
    m_status->setLayers(members.keys(), state.value("active").toString(), m_hiddenLayers);
    QStringList names;
    for (const auto& v : bridge("views").value("views").toArray())
        names << v.toObject().value("name").toString();
    m_layersPanel->setViews(names, m_currentView);
    refreshGraphics(); // new and changed elements get the purpose's styles
    refreshUnderlays(); // D85: their layers' states
}

void MainWindow::refreshGraphics()
{
    m_viewport->setGraphics(Graphics::fromJson(bridge("graphics_state")), m_prefs.trueLineWeights());
    const Graphics& g = m_viewport->graphics();
    const LineStyle pen = g.pen(g.currentPen());
    m_status->setPen(g.currentPen(), pen.color, pen.weight);
    m_status->setPurposes(g.purposes(), g.purpose());
    m_status->setStatusForNew(m_settings.value("status_for_new").toString(QStringLiteral("new")));
    if (m_sheetsPanel)
        m_sheetsPanel->setPurposes(g.purposes(), m_settings.value("sheet_purposes").toObject());
}

bool MainWindow::customizePurpose(const QString& penSet, const QString& visibility, const QString& overrides,
    const QString& layers, const QString& renovation)
{
    const QJsonObject reply = bridge("graphics_tables");
    QString name = reply.value("purpose").toString();
    QJsonObject purposes = reply.value("tables").toObject().value("purposes").toObject();
    QStringList builtins;
    for (const auto& b : reply.value("builtins").toObject().value("purposes").toArray())
        builtins << b.toString();
    const QString keep = purposes.value(name).toObject().value("renovation").toString(QStringLiteral("Everything"));
    if (builtins.contains(name)) // the built-ins stay as they are
        name = tr("%1 (modified)").arg(name);
    purposes.insert(name, QJsonObject{{"pen_set", penSet}, {"visibility", visibility}, {"overrides", overrides},
        {"layers", layers.isEmpty() ? QJsonValue() : QJsonValue(layers)},
        {"renovation", renovation.isEmpty() ? keep : renovation}});
    if (!setGraphics(QString::fromUtf8(QJsonDocument(QJsonObject{{"purposes", purposes}}).toJson(QJsonDocument::Compact))))
        return false;
    return setPurpose(name);
}

void MainWindow::editPurposePieces()
{
    const QJsonObject reply = bridge("graphics_tables");
    const QJsonObject tables = reply.value("tables").toObject();
    const QJsonObject current = tables.value("purposes").toObject().value(reply.value("purpose").toString()).toObject();
    QDialog dialog(this);
    dialog.setWindowTitle(tr("Purpose: %1").arg(reply.value("purpose").toString()));
    auto* form = new QFormLayout(&dialog);
    auto combo = [&](const QString& table, const QString& value, bool none) {
        auto* c = new QComboBox(&dialog);
        if (none)
            c->addItem(tr("(keep the layers as they are)"), QString());
        for (const QString& k : tables.value(table).toObject().keys())
            c->addItem(k, k);
        c->setCurrentIndex(std::max(0, c->findData(value)));
        return c;
    };
    QComboBox* pens = combo(QStringLiteral("pen_sets"), current.value("pen_set").toString(), false);
    QComboBox* vis = combo(QStringLiteral("visibility_sets"), current.value("visibility").toString(), false);
    QComboBox* ovr = combo(QStringLiteral("override_sets"), current.value("overrides").toString(), false);
    QComboBox* lay = combo(QStringLiteral("layer_combinations"), current.value("layers").toString(), true);
    QComboBox* reno = combo(QStringLiteral("renovation_filters"), current.value("renovation").toString(QStringLiteral("Everything")), false);
    form->addRow(tr("Pen set:"), pens);
    form->addRow(tr("Visibility set:"), vis);
    form->addRow(tr("Graphic overrides:"), ovr);
    form->addRow(tr("Layer combination:"), lay);
    form->addRow(tr("Renovation filter:"), reno);
    // D74: what this purpose changes, as a key (the same rows a sheet's legend prints).
    auto* legendTitle = new QLabel(tr("Legend"), &dialog);
    QFont bold = legendTitle->font();
    bold.setBold(true);
    legendTitle->setFont(bold);
    form->addRow(legendTitle);
    const Graphics& g = m_viewport->graphics();
    if (g.legend().isEmpty())
        form->addRow(new QLabel(tr("Everything is drawn with its element styles"), &dialog));
    for (const LegendEntry& e : g.legend()) {
        QPixmap swatch(30, 14);
        swatch.fill(Qt::transparent);
        if (const ElementStyle* s = g.style(e.style)) {
            QPainter p(&swatch);
            p.fillRect(swatch.rect().adjusted(1, 1, -1, -1), s->fill.isValid() ? s->fill : s->surface.value_or(QColor(Qt::transparent)));
            QPen pen(s->cut.color, 2, s->cut.dash.isEmpty() ? Qt::SolidLine : Qt::DashLine);
            p.setPen(pen);
            p.drawRect(swatch.rect().adjusted(1, 1, -2, -2));
        }
        auto* icon = new QLabel(&dialog);
        icon->setPixmap(swatch);
        form->addRow(icon, new QLabel(e.source == QLatin1String("renovation") ? renovationLabel(e.key) : e.label, &dialog));
    }
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    form->addRow(buttons);
    if (dialog.exec() == QDialog::Accepted)
        customizePurpose(pens->currentData().toString(), vis->currentData().toString(), ovr->currentData().toString(),
            lay->currentData().toString(), reno->currentData().toString());
}

bool MainWindow::setSheetPurpose(const QString& number, const QString& purpose)
{
    const QJsonObject r = bridge("set_sheet_purpose", {number, purpose});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(r.value("error").toString());
        return false;
    }
    m_settings = bridge("project_settings").value("settings").toObject();
    if (m_drawingViews.contains(QStringLiteral("sheet:") + number))
        regenerateDrawing(QStringLiteral("sheet:") + number);
    refreshGraphics();
    setWindowModified(isDirty());
    return true;
}

bool MainWindow::setRenovationStatus(const QString& status)
{
    if (m_selection.isEmpty()) {
        m_status->showMessage(tr("Select the elements first"));
        return false;
    }
    const QJsonObject r = bridge("set_status", {jsonList(m_selection), status});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(r.value("error").toString());
        return false;
    }
    afterEdit(r); // restyles through the graphics (a status may hide or restyle the elements)
    refreshProperties();
    return true;
}

bool MainWindow::setStatusForNew(const QString& status)
{
    const QJsonObject r = bridge("set_status_for_new", {status});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(r.value("error").toString());
        return false;
    }
    m_settings = bridge("project_settings").value("settings").toObject();
    m_status->setStatusForNew(status);
    setWindowModified(isDirty());
    return true;
}

bool MainWindow::markUnmarked(const QString& status)
{
    if (bridge("unmarked").value("count").toInt() == 0) {
        m_status->showMessage(tr("Every element already has a renovation status"));
        return false;
    }
    const QJsonObject r = bridge("mark_unmarked", {status});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(r.value("error").toString());
        return false;
    }
    afterEdit(r);
    m_status->showMessage(tr("%n element(s) marked", nullptr, r.value("changed").toInt()));
    return true;
}

void MainWindow::askImportStatus()
{
    if (!m_prefs.askImportStatus())
        return;
    const int count = bridge("unmarked").value("count").toInt();
    if (count == 0)
        return;
    QString answer = m_importStatusAnswer;
    if (!m_quiet) {
        QMessageBox box(QMessageBox::Question, tr("Renovation status"),
            tr("%n element(s) have no renovation status. Mark them as:", nullptr, count), QMessageBox::NoButton, this);
        QPushButton* existing = box.addButton(renovationLabel(QStringLiteral("existing")), QMessageBox::AcceptRole);
        QPushButton* demolish = box.addButton(renovationLabel(QStringLiteral("demolish")), QMessageBox::AcceptRole);
        QPushButton* leave = box.addButton(tr("Leave them (they count as New)"), QMessageBox::RejectRole);
        box.setDefaultButton(leave);
        box.setEscapeButton(leave);
        auto* again = new QCheckBox(tr("Don't ask again"), &box);
        box.setCheckBox(again);
        box.exec();
        if (again->isChecked()) {
            m_prefs.setValue(QStringLiteral("ask_import_status"), false);
            m_prefs.save();
        }
        answer = box.clickedButton() == existing ? QStringLiteral("existing")
            : box.clickedButton() == demolish    ? QStringLiteral("demolish")
                                                 : QString();
    }
    if (!answer.isEmpty())
        markUnmarked(answer);
}

bool MainWindow::setCurrentPen(int pen)
{
    const QJsonObject r = bridge("set_current_pen", {QString::number(pen)});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(r.value("error").toString());
        return false;
    }
    m_settings = bridge("project_settings").value("settings").toObject();
    const QStringList notes = m_viewport->annotationGuids();
    for (const QString& g : m_viewport->selectedGuids())
        if (notes.contains(g)) // the annotations' pens are model data: undoable, and the drawings follow
            afterEdit(bridge("set_annotation_pen", {g, QString::number(pen)}));
    refreshGraphics();
    refreshAnnotations();
    setWindowModified(isDirty());
    return true;
}

void MainWindow::regenerateOpenDrawings()
{
    for (const QString& guid : m_drawingViews.keys())
        regenerateDrawing(guid);
}

bool MainWindow::setPurpose(const QString& name)
{
    const QJsonObject r = bridge("set_purpose", {name});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(r.value("error").toString());
        return false;
    }
    m_settings = bridge("project_settings").value("settings").toObject();
    m_hiddenLayers.clear();
    m_lockedLayers.clear();
    for (const auto& v : r.value("hidden_layers").toArray())
        m_hiddenLayers.insert(v.toString());
    for (const auto& v : r.value("locked_layers").toArray())
        m_lockedLayers.insert(v.toString());
    refreshLayers(); // the purpose's layer combination; then the graphics
    refreshAnnotations();
    regenerateOpenDrawings();
    setWindowModified(isDirty());
    return true;
}

bool MainWindow::setGraphics(const QString& changesJson)
{
    const QJsonObject r = bridge("set_graphics", {changesJson});
    if (!r.value("ok").toBool()) {
        if (m_quiet)
            m_status->showMessage(r.value("error").toString());
        else
            showError(tr("Could not change the graphics"), r.value("error").toString());
        return false;
    }
    m_settings = bridge("project_settings").value("settings").toObject();
    refreshGraphics();
    refreshAnnotations();
    regenerateOpenDrawings();
    setWindowModified(isDirty());
    return true;
}

void MainWindow::setTrueLineWeights(bool on)
{
    m_prefs.setValue(QStringLiteral("true_line_weights"), on);
    m_prefs.save();
    refreshGraphics();
    refreshAnnotations();
}

void MainWindow::applyViewPreferences()
{
    Viewport::setFieldOfView(m_prefs.fieldOfView()); // D92
    const QJsonArray home = m_prefs.value(QStringLiteral("home_view")).toArray();
    if (home.size() == 6)
        Viewport::setHomeView(gp_Dir(home.at(0).toDouble(), home.at(1).toDouble(), home.at(2).toDouble()),
            gp_Dir(home.at(3).toDouble(), home.at(4).toDouble(), home.at(5).toDouble()));
    else
        Viewport::setHomeView(viewDirection(HomeOrientation), viewUp(HomeOrientation));
    if (m_viewport && m_viewport->isPerspective())
        m_viewport->setPerspective(true); // re-apply the field of view to the open camera
}

void MainWindow::refreshAnnotations()
{
    QVector<Viewport::Annotation> list;
    for (const auto& v : bridge("annotations", {m_levels->activeStorey()}).value("annotations").toArray()) {
        const QJsonObject o = v.toObject();
        Viewport::Annotation a{o.value("guid").toString(), o.value("kind").toString(), o.value("text").toString(), {},
            o.value("size").toDouble(2.5), o.value("pen").toInt(0)};
        for (const auto& p : o.value("points").toArray())
            a.points << QPointF(p.toArray().at(0).toDouble(), p.toArray().at(1).toDouble());
        readDrafting(o, &a); // D84 (DraftTools.cpp)
        list << a;
    }
    // Room stamps (Slice 18): kind "room", the stamp point first, then the outline.
    for (const auto& v : bridge("rooms", {m_levels->activeStorey()}).value("rooms").toArray()) {
        const QJsonObject o = v.toObject();
        const QJsonArray label = o.value("label").toArray();
        // D87: the stamp's text is the room stamp tag style's (name, number and area by default).
        const QString stamp = o.contains("stamp") ? o.value("stamp").toString()
            : o.value("name").toString() + QLatin1Char('\n') + o.value("number").toString() + QLatin1Char('\n')
                + QLocale().toString(o.value("area").toDouble(), 'f', 2) + QStringLiteral(" m²");
        Viewport::Annotation a{o.value("guid").toString(), QStringLiteral("room"), stamp,
            {QPointF(label.at(0).toDouble(), label.at(1).toDouble())}};
        for (const auto& p : o.value("points").toArray())
            a.points << QPointF(p.toArray().at(0).toDouble(), p.toArray().at(1).toDouble());
        list << a;
    }
    readStairSymbols(stairSymbolData(), &list); // D88: plan symbols of the level's stairs and ramps
    m_viewport->setAnnotations(list, m_levels->activeElevation());
    if (!m_selection.isEmpty())
        m_viewport->selectGuids(m_selection);
}

bool MainWindow::addAnnotation(const QString& kind, const QVector<QPointF>& points, const QString& text)
{
    QJsonArray pts;
    for (const QPointF& p : points)
        pts.append(QJsonArray{p.x(), p.y()});
    const QJsonObject r = bridge("add_annotation", {m_levels->activeStorey(), kind,
        QString::fromUtf8(QJsonDocument(pts).toJson(QJsonDocument::Compact)), text});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not add it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

void MainWindow::annotationClick(QPointF p, Qt::KeyboardModifiers modifiers)
{
    if (m_tool == Tool::Leader) {
        m_annotationPoints << p;
        if (m_annotationPoints.size() == 1) {
            m_status->showMessage(tr("Leader: click where its text goes"));
            return;
        }
        const QVector<QPointF> pts = m_annotationPoints;
        m_annotationPoints.clear();
        bool ok = false;
        const QString text = m_quiet ? QStringLiteral("Note")
            : QInputDialog::getText(this, tr("Leader"), tr("Text:"), QLineEdit::Normal, QString(), &ok);
        if ((ok || m_quiet) && !text.trimmed().isEmpty())
            addAnnotation(QStringLiteral("leader"), pts, text.trimmed());
        m_status->showMessage(tr("Leader: click what it points at"));
        return;
    }
    if (m_tool == Tool::Dimension) {
        // Slice 15: Shift+click adds another point to the chain; a plain click after two points
        // places the dimension line (Archicad builds chains the same way, one click per point).
        const bool chainMore = m_annotationPoints.size() >= 2 && (modifiers & Qt::ShiftModifier);
        m_annotationPoints << p;
        if (m_annotationPoints.size() == 1)
            m_status->showMessage(tr("Dimension: click the second point"));
        else if (m_annotationPoints.size() == 2 || chainMore)
            m_status->showMessage(tr("Dimension: Shift+click to add a point, or click where the dimension line goes"));
        else {
            const QVector<QPointF> pts = m_annotationPoints;
            m_annotationPoints.clear();
            addAnnotation(QStringLiteral("dimension"), pts, QString());
            m_status->showMessage(tr("Dimension: click the first point to measure"));
        }
        return;
    }
    const bool mark = m_tool == Tool::Mark;
    bool ok = false;
    const QString text = QInputDialog::getText(this, mark ? tr("Mark") : tr("Text label"),
        mark ? tr("Tag (e.g. A, 1, R2):") : tr("Text:"), QLineEdit::Normal, QString(), &ok);
    if (ok && !text.trimmed().isEmpty())
        addAnnotation(mark ? QStringLiteral("mark") : QStringLiteral("text"), {p}, text.trimmed());
}

// ---------------------------------------------------------------- drawings (Slice 14)

void MainWindow::drawingClick(QPointF p)
{
    const bool section = m_tool == Tool::Section;
    m_annotationPoints << p;
    if (m_annotationPoints.size() == 1) {
        m_status->showMessage(section ? tr("Section: click where the section line ends")
                                         : tr("Elevation: click where the elevation line ends"));
    } else if (m_annotationPoints.size() == 2) {
        m_status->showMessage(tr("Click the side the drawing looks at"));
    } else {
        const QVector<QPointF> pts = m_annotationPoints;
        m_annotationPoints.clear();
        createDrawing(section ? QStringLiteral("section") : QStringLiteral("elevation"), pts[0], pts[1], pts[2]);
        m_status->showMessage(section ? tr("Section: click where the section line starts")
                                         : tr("Elevation: click where the elevation line starts"));
    }
}

bool MainWindow::createDrawing(const QString& kind, QPointF p1, QPointF p2, QPointF look)
{
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge(kind == QLatin1String("section") ? "create_section" : "create_elevation",
        {num(p1.x()), num(p1.y()), num(p2.x()), num(p2.y()), num(look.x()), num(look.y()), QStringLiteral("-1")});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not add it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

QString MainWindow::drawingGuid(const QString& name)
{
    for (const auto& v : bridge("drawings").value("drawings").toArray())
        if (v.toObject().value("name").toString() == name)
            return v.toObject().value("guid").toString();
    return QString();
}

void MainWindow::refreshDrawings()
{
    const QJsonArray list = bridge("drawings").value("drawings").toArray();
    m_drawingsPanel->setDrawings(list);
    QVector<Viewport::Annotation> markers;
    QHash<QString, QJsonObject> byGuid;
    for (const auto& v : list) {
        const QJsonObject d = v.toObject();
        byGuid.insert(d.value("guid").toString(), d);
        if (d.value("kind").toString() == QLatin1String("plan"))
            continue; // floor plans have no marker
        Viewport::Annotation m{d.value("guid").toString(), d.value("kind").toString(), d.value("name").toString(), {}};
        for (const auto& p : d.value("points").toArray())
            m.points << QPointF(p.toArray().at(0).toDouble(), p.toArray().at(1).toDouble());
        const QJsonArray look = d.value("look").toArray();
        m.points << QPointF(look.at(0).toDouble(), look.at(1).toDouble());
        markers << m;
    }
    m_viewport->setDrawingMarkers(markers, m_levels->activeElevation());
    for (const QString& key : m_dock->viewKeys()) {
        auto* view = qobject_cast<DrawingView*>(m_dock->view(key));
        if (!view || view->guid().startsWith(QLatin1String("sheet:")))
            continue; // sheets are refreshed by refreshSheets()
        const auto it = byGuid.constFind(view->guid());
        if (it == byGuid.constEnd()) { // deleted (or undone): its tab goes too
            closeView(key);
            continue;
        }
        m_dock->setTitle(key, it->value("name").toString());
        view->setStale(it->value("stale").toBool());
    }
}

bool MainWindow::openDrawing(const QString& guid)
{
    if (m_drawingViews.contains(guid)) {
        m_dock->raise(guid);
        return true;
    }
    QString name;
    for (const auto& v : bridge("drawings").value("drawings").toArray())
        if (v.toObject().value("guid").toString() == guid)
            name = v.toObject().value("name").toString();
    if (name.isEmpty())
        return false;
    auto* view = new DrawingView(guid);
    connect(view, &DrawingView::regenerateRequested, this, &MainWindow::regenerateDrawing);
    m_drawingViews.insert(guid, view);
    view->setStale(true);
    m_dock->addView(guid, name, view, true, newViewPlacement());
    m_dock->raise(guid); // brings it up to date (activateView)
    if (!m_generating.contains(guid) && !view->hasDrawing())
        regenerateDrawing(guid);
    return true;
}

void MainWindow::showModelTab()
{
    m_dock->raise(QStringLiteral("3d"));
}

QString MainWindow::currentViewKey() const
{
    return m_dock->current();
}

void MainWindow::activateView(const QString& key)
{
    if (auto* view = qobject_cast<DrawingView*>(m_dock->view(key))) {
        m_status->setZoom(-1); // drawings show their own zoom
        setTool(Tool::None); // the tools draw in model views
        if (view->isStale() || !view->hasDrawing())
            regenerateDrawing(view->guid()); // a drawing brought to the front is brought up to date
        return;
    }
    ViewHost* host = m_hosts.value(key);
    if (!host)
        return;
    const bool switched = host->viewport() != m_viewport;
    if (switched) {
        setTool(Tool::None); // a tool doesn't carry over to another view
        m_viewport = host->viewport();
        const CutSettings cut = m_cuts.value(m_viewport); // this view's own cuts into the controls
        const QSignalBlocker b1(m_planCut), b2(m_sectionBox), b3(m_cutHeight), b4(m_cutSlider);
        m_planCut->setChecked(cut.planCut);
        m_sectionBox->setChecked(cut.box);
        m_cutHeight->setValue(cut.height);
        m_boxBounds = cut.bounds;
    }
    host->adoptChrome(m_toolOptions, m_cutColumn);
    m_status->setZoom(m_viewport->zoomPercent());
    if (!host->storey().isEmpty() && host->storey() != m_levels->activeStorey())
        m_levels->setActive(host->storey()); // a plan tab's level is the active level
    if (switched) {
        updateCutSliderRange();
        m_cutLabel->setText(formatLength(m_cutHeight->value()));
        m_viewport->setWorkPlaneZ(m_levels->activeElevation());
        applyCuts();
        refreshAnnotations(); // this view's level notes, grid and markers
        refreshDrawings();
        refreshSnapData();
    }
}

void MainWindow::activateElement(const QString& guid)
{
    if (m_tree->ifcTypeOf(guid) == QLatin1String("IfcBuildingStorey")) {
        openPlanTab(guid);
        return;
    }
    m_viewport->selectGuids({guid});
    m_tree->selectGuids({guid});
    setSelection({guid});
    m_dock->raisePanel(QStringLiteral("properties")); // slides out if auto-hidden, raised if floating
}

void MainWindow::onEachView(const std::function<void(Viewport*)>& connect)
{
    m_viewConnectors << connect;
    for (ViewHost* h : std::as_const(m_hosts))
        connect(h->viewport());
}

Viewport* MainWindow::modelView() const
{
    return m_hosts.value(QStringLiteral("3d"))->viewport();
}

Viewport* MainWindow::openPlanTab(const QString& storey)
{
    const QString key = QStringLiteral("plan:") + storey;
    if (ViewHost* host = m_hosts.value(key)) {
        m_dock->raise(key);
        return host->viewport();
    }
    double elevation = 0.0;
    QString name;
    for (const auto& v : bridge("storeys").value("storeys").toArray()) {
        const QJsonObject s = v.toObject();
        if (s.value("guid").toString() == storey) {
            elevation = s.value("elevation").toDouble();
            name = s.value("name").toString();
        }
    }
    if (name.isEmpty())
        return nullptr; // not a level of this model
    auto* view = new Viewport(m_scene);
    view->setSelectThrough(modelView()->selectThrough());
    auto* host = new ViewHost(view);
    host->setStorey(storey);
    m_hosts.insert(key, host);
    for (const auto& c : std::as_const(m_viewConnectors))
        c(view);
    view->setPlanView(elevation);
    CutSettings cut;
    cut.planCut = true; // a plan is a horizontal cut
    cut.height = m_cutHeight->value();
    m_cuts.insert(view, cut);
    m_dock->addView(key, tr("%1 plan").arg(name), host, true, newViewPlacement());
    m_dock->raise(key); // activateView(): the level, the cut, the chrome, the annotations
    return view;
}

void MainWindow::closePlanTabs(const QStringList& keep)
{
    for (const QString& key : m_hosts.keys())
        if (key.startsWith(QLatin1String("plan:")) && !keep.contains(key))
            closeView(key);
}

void MainWindow::closeView(const QString& key)
{
    if (key == QLatin1String("3d"))
        return; // the 3D tab stays
    if (auto* view = qobject_cast<DrawingView*>(m_dock->view(key)))
        m_drawingViews.remove(view->guid());
    if (ViewHost* host = m_hosts.value(key)) { // a plan tab
        if (host->viewport() == m_viewport)
            m_dock->raise(QStringLiteral("3d")); // the 3D tab takes over (and the tool stops)
        m_cuts.remove(host->viewport());
        m_hosts.remove(key);
        // The view goes now, while the scene it is part of exists; the dock deletes the tab later.
        delete host->viewport();
    }
    m_dock->removeView(key);
}

void MainWindow::regenerateDrawing(const QString& guid)
{
    DrawingView* view = m_drawingViews.value(guid);
    if (!view)
        return;
    if (m_generating.contains(guid)) {
        m_generateAgain.insert(guid); // the model changed while generating: once more when done
        return;
    }
    m_generating.insert(guid);
    view->setBusy(true);
    // Only the elements the drawing can see go to the serializer: hidden-line removal grows with
    // everything behind the cut (spike S6: an elevation 52 s with all elements, 3.4 s with the
    // visible ones). The 3D view renders that set here, on the GUI thread; without a view (tests,
    // headless) every element goes.
    QString include;
    QStringList planGuids, viewGuids;
    double planCutZ = 0, planFloorZ = 0;
    gp_Ax2 viewAxes;
    std::optional<gp_Pln> sectionPlane;
    // Frame the building, not the whole georeferenced site (hundreds of metres across): the site's
    // extent would make every drawing a speck on a huge sheet and its visible pass select nothing.
    // The box comes from the meshes of the building's elements: exact, where the placements Python
    // has stop at the highest storey's floor (a roof and the gables were cut off the drawing). The
    // placement box and then the whole model are the fallbacks.
    Bnd_Box bounds = m_viewport->boundsOf({});
    {
        const QJsonObject b = bridge("drawing_bounds");
        QStringList inside;
        for (const auto& g : b.value("guids").toArray())
            inside << g.toString();
        const Bnd_Box meshes = m_viewport->buildingBounds(inside);
        const QJsonArray lo = b.value("lo").toArray(), hi = b.value("hi").toArray();
        if (!meshes.IsVoid()) {
            bounds = meshes;
        } else if (lo.size() == 3 && hi.size() == 3) {
            Bnd_Box box;
            box.Add(gp_Pnt(lo.at(0).toDouble(), lo.at(1).toDouble(), lo.at(2).toDouble()));
            box.Add(gp_Pnt(hi.at(0).toDouble(), hi.at(1).toDouble(), hi.at(2).toDouble()));
            if (!box.IsVoid())
                bounds = box;
        }
    }
    QElapsedTimer includeTimer;
    includeTimer.start();
    for (const auto& v : bridge("drawings").value("drawings").toArray()) {
        const QJsonObject d = v.toObject();
        if (d.value("guid").toString() != guid)
            continue;
        if (bounds.IsVoid())
            break;
        if (d.value("kind").toString() == QLatin1String("plan")) {
            // A floor plan: everything the top-down camera sees below its cut. The plan is drawn from
            // the meshes (planGeometry) instead of the serializer's hidden-line pass, which is far too
            // slow on a detailed storey (measured ~0.5-1.5 s per element).
            const double elevation = d.value("elevation").toDouble();
            const double cut = d.value("cut").toDouble(1.10);
            const auto seen = m_viewport->visibleFromPlan(bounds, elevation, cut, 0.5);
            if (seen) {
                planGuids = QStringList(seen->begin(), seen->end());
                planGuids.sort();
                include = QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(planGuids)).toJson(QJsonDocument::Compact));
            }
            planCutZ = elevation + cut;
            planFloorZ = elevation - 0.5;
            break;
        }
        double x0, y0, z0, x1, y1, z1;
        bounds.Get(x0, y0, z0, x1, y1, z1);
        auto pt = [](const QJsonValue& p) { return QPointF(p.toArray().at(0).toDouble(), p.toArray().at(1).toDouble()); };
        const double depth = d.value("depth").isNull() ? -1.0 : d.value("depth").toDouble();
        QPointF a, b, lk;
        const QString side = d.value("side").toString();
        if (d.value("auto").toBool() && !side.isEmpty()) {
            // A template elevation follows the building's bounds (D61): place its line outside them.
            const double gap = 3.0;
            if (side == QLatin1String("north")) {
                a = QPointF(x1 + gap, y1 + gap); b = QPointF(x0 - gap, y1 + gap); lk = QPointF((x0 + x1) / 2, y0);
            } else if (side == QLatin1String("south")) {
                a = QPointF(x0 - gap, y0 - gap); b = QPointF(x1 + gap, y0 - gap); lk = QPointF((x0 + x1) / 2, y1);
            } else if (side == QLatin1String("east")) {
                a = QPointF(x1 + gap, y0 - gap); b = QPointF(x1 + gap, y1 + gap); lk = QPointF(x0, (y0 + y1) / 2);
            } else { // west
                a = QPointF(x0 - gap, y1 + gap); b = QPointF(x0 - gap, y0 - gap); lk = QPointF(x1, (y0 + y1) / 2);
            }
        } else {
            const QJsonArray pts = d.value("points").toArray(), look = d.value("look").toArray();
            if (pts.size() != 2 || look.size() != 2)
                break;
            a = pt(pts.at(0)); b = pt(pts.at(1)); lk = QPointF(look.at(0).toDouble(), look.at(1).toDouble());
        }
        // The drawing camera (drawgen.camera): X is the drawing's right, Y is up, it looks along -Z.
        const double dx = b.x() - a.x(), dy = b.y() - a.y(), len = std::hypot(dx, dy);
        if (len > 1e-6) {
            double nx = -dy / len, ny = dx / len;
            if ((lk.x() - a.x()) * nx + (lk.y() - a.y()) * ny < 0) {
                nx = -nx;
                ny = -ny;
            }
            const double zc0 = z0 - 1.0, zc1 = z1 + 1.0;
            viewAxes = gp_Ax2(gp_Pnt((a.x() + b.x()) / 2, (a.y() + b.y()) / 2, (zc0 + zc1) / 2),
                gp_Dir(-nx, -ny, 0), gp_Dir(ny, -nx, 0));
            if (d.value("kind").toString() == QLatin1String("section"))
                sectionPlane = gp_Pln(gp_Pnt(a.x(), a.y(), 0), gp_Dir(nx, ny, 0));
        }
        const auto seen = m_viewport->visibleFrom(a, b, lk, z0 - 1.0, z1 + 1.0, depth);
        if (seen) {
            viewGuids = QStringList(seen->begin(), seen->end());
            viewGuids.sort(); // a stable list keeps the drawing cache useful
            include = QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(viewGuids)).toJson(QJsonDocument::Compact));
        }
        break;
    }
    m_lastIncludeMs = double(includeTimer.nsecsElapsed()) / 1e6;
    m_lastDrawingVisible = include.isEmpty() ? -1 : int(QJsonDocument::fromJson(include.toUtf8()).array().size());
    // Plans and views (sections/elevations) are drawn from the meshes here; only an empty visible set
    // falls back to the serializer.
    QString geometry;
    QString mode;
    if (!planGuids.isEmpty()) {
        mode = QStringLiteral("plan");
        geometry = QString::fromUtf8(QJsonDocument(m_viewport->planGeometry(planGuids, planCutZ, planFloorZ))
                                         .toJson(QJsonDocument::Compact));
    } else if (!viewGuids.isEmpty()) {
        mode = QStringLiteral("view");
        geometry = QString::fromUtf8(QJsonDocument(m_viewport->viewGeometry(viewGuids, viewAxes,
                                         sectionPlane ? &*sectionPlane : nullptr, bounds)).toJson(QJsonDocument::Compact));
    }
    // The bridge snapshots the model and runs IfcOpenShell's serializer in a child process, which
    // can take seconds on real files (spike S6); waiting for it here would freeze the window.
    QPointer<MainWindow> self(this);
    QThread* worker = QThread::create([self, guid, include, geometry, mode] {
        QString error;
        const bool sheet = guid.startsWith(QLatin1String("sheet:"));
        const QString fn = mode == QLatin1String("plan") ? QStringLiteral("generate_plan_drawing")
            : mode == QLatin1String("view")               ? QStringLiteral("generate_view_drawing")
                                                          : QStringLiteral("generate_drawing");
        const QJsonObject result = sheet
            ? PythonEngine::instance().callJson("sheet_svg", {guid.mid(6)}, &error).object()
            : !geometry.isEmpty()
                  ? PythonEngine::instance().callJson(fn.toUtf8().constData(), {guid, geometry}, &error).object()
                  : PythonEngine::instance().callJson("generate_drawing", {guid, include}, &error).object();
        if (self)
            QMetaObject::invokeMethod(self, [self, guid, result, error] {
                if (self)
                    self->onDrawingGenerated(guid, result, error);
            }, Qt::QueuedConnection);
    });
    m_drawingThreads << worker;
    connect(worker, &QThread::finished, this, [this, worker] {
        m_drawingThreads.removeAll(worker);
        worker->deleteLater();
    });
    worker->start();
}

void MainWindow::onDrawingGenerated(const QString& guid, const QJsonObject& result, const QString& error)
{
    m_generating.remove(guid);
    DrawingView* view = m_drawingViews.value(guid);
    if (!view)
        return; // its tab was closed meanwhile
    view->setBusy(false);
    if (!error.isEmpty() || !result.value("ok").toBool()) {
        m_status->showMessage(tr("Could not generate the drawing: %1").arg(error.isEmpty() ? result.value("error").toString() : error));
        return;
    }
    view->setSvg(result.value("svg").toString().toUtf8());
    if (guid.startsWith(QLatin1String("sheet:"))) {
        refreshSheets(false); // the drawings' places, for dragging
        view->setStale(false);
        if (m_generateAgain.remove(guid) && m_dock->current() == guid)
            regenerateDrawing(guid);
        return;
    }
    refreshDrawings(); // stale again if the model changed while it was generated
    if (m_generateAgain.remove(guid) && view->isStale() && m_dock->current() == guid)
        regenerateDrawing(guid);
}

// ---------------------------------------------------------------- sheets (Slice 16)

QString MainWindow::addSheet(const QString& paper, const QString& title)
{
    const QJsonObject r = bridge("add_sheet", {paper, title});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not add it: %1").arg(r.value("error").toString()));
        return QString();
    }
    afterEdit(r);
    return r.value("number").toString();
}

bool MainWindow::placeOnSheet(const QString& number, const QString& drawingGuid)
{
    m_status->showMessage(tr("Placing the drawing..."));
    const QJsonObject r = bridge("place_drawing", {number, drawingGuid, QStringLiteral("-1"), QStringLiteral("-1"),
        QString::number(m_settings.value("drawing_scale").toInt(100))});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not place it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    openSheet(number);
    return true;
}

bool MainWindow::placeLegend(const QString& number)
{
    const QJsonObject r = bridge("place_legend", {number});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not place it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    openSheet(number);
    refreshSheets(true);
    return true;
}

bool MainWindow::openSheet(const QString& number)
{
    const QString key = QStringLiteral("sheet:") + number;
    if (m_drawingViews.contains(key)) {
        m_dock->raise(key);
        return true;
    }
    bool exists = false;
    for (const auto& v : bridge("sheets").value("sheets").toArray())
        exists = exists || v.toObject().value("number").toString() == number;
    if (!exists)
        return false;
    auto* view = new DrawingView(key);
    connect(view, &DrawingView::regenerateRequested, this, &MainWindow::regenerateDrawing);
    connect(view, &DrawingView::placedMoved, this, [this, number](const QString& drawing, QPointF topLeft) {
        const bool legend = drawing.startsWith(QLatin1String("legend:"));
        const bool symbol = drawing.startsWith(QLatin1String("symbol:")); // D87
        const QJsonObject r = bridge(symbol ? "move_sheet_symbol" : legend ? "move_legend" : "move_placed",
            {number, legend || symbol ? drawing.mid(7) : drawing,
            QString::number(topLeft.x(), 'f', 1), QString::number(topLeft.y(), 'f', 1)});
        if (!r.value("ok").toBool())
            m_status->showMessage(tr("Could not move it: %1").arg(r.value("error").toString()));
        afterEdit(r);
    });
    connect(view, &DrawingView::placedRemoveRequested, this, [this, number](const QString& drawing) {
        const bool legend = drawing.startsWith(QLatin1String("legend:"));
        const bool symbol = drawing.startsWith(QLatin1String("symbol:")); // D87
        const QJsonObject r = bridge(symbol ? "remove_sheet_symbol" : legend ? "remove_legend" : "remove_placed",
            {number, legend || symbol ? drawing.mid(7) : drawing});
        if (!r.value("ok").toBool())
            m_status->showMessage(tr("Could not remove it: %1").arg(r.value("error").toString()));
        afterEdit(r);
    });
    m_drawingViews.insert(key, view);
    view->setStale(true);
    m_dock->addView(key, tr("Sheet %1").arg(number), view, true, newViewPlacement());
    m_dock->raise(key);
    if (!m_generating.contains(key) && !view->hasDrawing())
        regenerateDrawing(key);
    return true;
}

void MainWindow::refreshSheets(bool changed)
{
    const QJsonArray list = bridge("sheets").value("sheets").toArray();
    m_sheetsPanel->setSheets(list);
    QHash<QString, QJsonObject> byNumber;
    for (const auto& v : list)
        byNumber.insert(v.toObject().value("number").toString(), v.toObject());
    for (const QString& key : m_dock->viewKeys()) {
        auto* view = qobject_cast<DrawingView*>(m_dock->view(key));
        if (!view || !view->guid().startsWith(QLatin1String("sheet:")))
            continue;
        const auto it = byNumber.constFind(view->guid().mid(6));
        if (it == byNumber.constEnd()) {
            closeView(key);
            continue;
        }
        QVector<DrawingView::Placed> placed;
        for (const auto& pv : it->value("views").toArray()) {
            const QJsonObject p = pv.toObject();
            placed.push_back({p.value("drawing").toString(),
                QRectF(p.value("x").toDouble(), p.value("y").toDouble(), p.value("w").toDouble(), p.value("h").toDouble())});
        }
        for (const auto& lv : it->value("legends").toArray()) { // D74: dragged and removed like drawings
            const QJsonObject l = lv.toObject();
            placed.push_back({QStringLiteral("legend:") + l.value("id").toString(),
                QRectF(l.value("x").toDouble(), l.value("y").toDouble(), l.value("w").toDouble(), l.value("h").toDouble())});
        }
        for (const auto& sv : it->value("symbols").toArray()) { // D87: north arrows, scale bars, clouds
            const QJsonObject l = sv.toObject();
            placed.push_back({QStringLiteral("symbol:") + l.value("id").toString(),
                QRectF(l.value("x").toDouble(), l.value("y").toDouble(), l.value("w").toDouble(), l.value("h").toDouble())});
        }
        view->setPlaced(placed);
        m_dock->setTitle(key, tr("Sheet %1").arg(it->value("number").toString()));
        if (changed && !m_generating.contains(view->guid()) && view->hasDrawing()) {
            view->setStale(true); // the model or the sheet changed: compose it again
            if (m_dock->current() == key)
                QMetaObject::invokeMethod(this, [this, g = view->guid()] { regenerateDrawing(g); }, Qt::QueuedConnection);
        }
    }
}

bool MainWindow::exportSheet(const QString& number, const QString& path)
{
    if (path.endsWith(QLatin1String(".svg"), Qt::CaseInsensitive)) {
        const QJsonObject r = bridge("export_sheet_svg", {number, path});
        if (!r.value("ok").toBool())
            showError(tr("Could not export the sheet"), r.value("error").toString());
        return r.value("ok").toBool();
    }
    const QJsonObject sheet = bridge("sheet_svg", {number});
    QString error;
    if (!sheet.value("ok").toBool()
        || !exportSvgToPdf(sheet.value("svg").toString().toUtf8(), sheet.value("width").toDouble(),
            sheet.value("height").toDouble(), path, &error)) {
        showError(tr("Could not export the sheet"), error.isEmpty() ? sheet.value("error").toString() : error);
        return false;
    }
    m_status->showMessage(tr("Sheet %1 exported to %2").arg(number, path));
    return true;
}

void MainWindow::exportSheetDialog(bool pdf)
{
    QString number = m_sheetsPanel->selectedSheet();
    if (auto* view = qobject_cast<DrawingView*>(m_dock->view(m_dock->current())); view && view->guid().startsWith(QLatin1String("sheet:")))
        number = view->guid().mid(6);
    if (number.isEmpty()) {
        showError(tr("No sheet"), tr("Add a sheet in the Sheets panel first."));
        return;
    }
    const QString path = QFileDialog::getSaveFileName(this, pdf ? tr("Export sheet as PDF") : tr("Export sheet as SVG"),
        number + (pdf ? QStringLiteral(".pdf") : QStringLiteral(".svg")), pdf ? tr("PDF (*.pdf)") : tr("SVG (*.svg)"));
    if (!path.isEmpty())
        exportSheet(number, path);
}

bool MainWindow::setProjectInfo(const QJsonObject& info)
{
    const QJsonObject r = bridge("set_project_info", {QString::fromUtf8(QJsonDocument(info).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool())
        showError(tr("Could not change the project info"), r.value("error").toString());
    afterEdit(r);
    return r.value("ok").toBool();
}

void MainWindow::setRoofKind(const QString& kind, double pitch)
{
    m_roofKind->setCurrentIndex(std::max(0, m_roofKind->findData(kind)));
    m_roofPitch->setValue(pitch);
}

bool MainWindow::createRoof(const QVector<QPointF>& outline)
{
    QJsonArray pts;
    for (const QPointF& p : outline)
        pts.append(QJsonArray{p.x(), p.y()});
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge("create_roof", {m_levels->activeStorey(),
        QString::fromUtf8(QJsonDocument(pts).toJson(QJsonDocument::Compact)), m_roofKind->currentData().toString(),
        num(m_roofPitch->value()), QStringLiteral("0.25"), num(m_wallHeight->value()), QString()});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not create the roof: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::trimWallsToRoof(const QStringList& selection)
{
    QString roof;
    QStringList walls;
    for (const QString& g : selection) {
        const QString type = m_viewport->typeOf(g);
        if (type == QLatin1String("IfcRoof"))
            roof = g;
        else if (type.startsWith(QLatin1String("IfcWall")))
            walls << g;
    }
    if (roof.isEmpty() || walls.isEmpty()) {
        m_status->showMessage(tr("Select a roof and the walls to trim to it"));
        return false;
    }
    const QJsonObject r = bridge("attach_walls_to_roof", {roof,
        QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(walls)).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not trim the walls: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    m_status->showMessage(tr("%n wall(s) trimmed to the roof", nullptr, int(walls.size())));
    return true;
}

bool MainWindow::releaseWallsFromRoof(const QStringList& selection)
{
    const QJsonObject r = bridge("detach_walls_from_roof",
        {QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(selection)).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(r.value("error").toString());
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::roomAt(QPointF p, const QString& name)
{
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    QString text = name;
    if (text.isEmpty() && !m_quiet) {
        bool ok = false;
        text = QInputDialog::getText(this, tr("Room"), tr("Name:"), QLineEdit::Normal, tr("Room"), &ok);
        if (!ok)
            return false;
    }
    const QJsonObject r = bridge("create_room", {m_levels->activeStorey(), num(p.x()), num(p.y()), text});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("No room here: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    m_status->showMessage(tr("Room: click inside the walls that enclose it"));
    return true;
}

void MainWindow::roomScheduleDialog()
{
    openSchedules(QStringLiteral("rooms")); // the room schedule is one of the schedules (D77)
}

SchedulesDialog* MainWindow::openSchedules(const QString& scheme)
{
    if (!m_schedules) {
        m_schedules = new SchedulesDialog(this);
        // A row click selects its elements in every view and the tree, like a click in the model.
        connect(m_schedules, &SchedulesDialog::selectRequested, this, [this](const QStringList& guids) {
            m_viewport->selectGuids(guids);
            m_tree->selectGuids(guids);
            setSelection(guids);
        });
        connect(m_schedules, &SchedulesDialog::edited, this, [this](const QJsonObject& r) { afterEdit(r); });
        connect(this, &MainWindow::loadFinished, m_schedules, [this] { m_schedules->modelChanged(); });
    }
    if (!scheme.isEmpty())
        m_schedules->showScheme(scheme);
    else
        m_schedules->refresh();
    if (!m_quiet) {
        m_schedules->show();
        m_schedules->raise();
        m_schedules->activateWindow();
    }
    return m_schedules;
}

void MainWindow::projectInfoDialog()
{
    const QJsonObject current = bridge("project_info");
    QDialog dialog(this);
    dialog.setWindowTitle(tr("Project info"));
    auto* form = new QFormLayout(&dialog);
    QLineEdit* fields[4];
    const char* keys[4] = {"number", "name", "client", "address"};
    const QString labels[4] = {tr("Project number:"), tr("Project name:"), tr("Client:"), tr("Address:")};
    for (int i = 0; i < 4; ++i) {
        fields[i] = new QLineEdit(current.value(QLatin1String(keys[i])).toString(), &dialog);
        fields[i]->setMinimumWidth(320);
        form->addRow(labels[i], fields[i]);
    }
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    form->addRow(buttons);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() != QDialog::Accepted)
        return;
    QJsonObject info;
    for (int i = 0; i < 4; ++i)
        info.insert(QLatin1String(keys[i]), fields[i]->text().trimmed());
    setProjectInfo(info);
}

// ---------------------------------------------------------------- everyday editing (Slice 17)

void MainWindow::afterCopy(const QJsonObject& result)
{
    afterEdit(result);
    QStringList copies;
    for (const auto& v : result.value("guids").toArray())
        copies << v.toString();
    if (!copies.isEmpty()) {
        m_viewport->selectGuids(copies);
        setSelection(copies);
    }
}

bool MainWindow::copySelection(QPointF delta)
{
    if (m_selection.isEmpty())
        return false;
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge("copy_elements", {jsonList(m_selection), num(delta.x()), num(delta.y()), QStringLiteral("0"), QString()});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not copy: %1").arg(r.value("error").toString()));
        return false;
    }
    afterCopy(r);
    return true;
}

void MainWindow::copyToClipboard()
{
    m_clipboard = m_selection;
    m_status->showMessage(tr("%n element(s) copied", nullptr, int(m_clipboard.size())));
}

bool MainWindow::paste()
{
    if (m_clipboard.isEmpty())
        return false;
    const QJsonObject r = bridge("copy_elements", {jsonList(m_clipboard), QStringLiteral("0"), QStringLiteral("0"),
        QStringLiteral("0"), m_levels->activeStorey()});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not paste: %1").arg(r.value("error").toString()));
        return false;
    }
    afterCopy(r);
    m_status->showMessage(tr("Pasted; drag the copies where they go"));
    return true;
}

bool MainWindow::duplicateSelection()
{
    if (m_selection.isEmpty())
        return false;
    const QJsonObject r = bridge("duplicate_elements", {jsonList(m_selection)});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not duplicate: %1").arg(r.value("error").toString()));
        return false;
    }
    afterCopy(r);
    return true;
}

bool MainWindow::mirrorSelection(QPointF a, QPointF b, bool copy)
{
    if (m_selection.isEmpty())
        return false;
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge("mirror_elements", {jsonList(m_selection), num(a.x()), num(a.y()), num(b.x()), num(b.y()),
        copy ? QStringLiteral("1") : QStringLiteral("0")});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not mirror: %1").arg(r.value("error").toString()));
        return false;
    }
    if (copy)
        afterCopy(r);
    else
        afterEdit(r);
    return true;
}

bool MainWindow::multiplySelection(const QString& kind, const QJsonObject& params)
{
    if (m_selection.isEmpty())
        return false;
    const QJsonObject r = bridge("array_elements", {jsonList(m_selection), kind,
        QString::fromUtf8(QJsonDocument(params).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not multiply: %1").arg(r.value("error").toString()));
        return false;
    }
    afterCopy(r);
    return true;
}

bool MainWindow::offsetSelection(double distance)
{
    if (m_selection.isEmpty())
        return false;
    const QJsonObject r = bridge("offset_elements", {jsonList(m_selection), QString::number(distance, 'g', 17)});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not offset: %1").arg(r.value("error").toString()));
        return false;
    }
    if (r.value("guids").toArray().isEmpty())
        afterEdit(r);
    else
        afterCopy(r);
    return true;
}

void MainWindow::multiplyDialog()
{
    if (m_selection.isEmpty()) {
        m_status->showMessage(tr("Select what to multiply first"));
        return;
    }
    QDialog dialog(this);
    dialog.setWindowTitle(tr("Multiply"));
    auto* form = new QFormLayout(&dialog);
    auto* kind = new QComboBox(&dialog);
    kind->addItem(tr("Linear (move each copy by a distance)"), QStringLiteral("linear"));
    kind->addItem(tr("Polar (rotate each copy around a centre)"), QStringLiteral("polar"));
    auto spin = [&](double lo, double hi, double value, int decimals) {
        auto* b = new QDoubleSpinBox(&dialog);
        b->setRange(lo, hi);
        b->setDecimals(decimals);
        b->setValue(value);
        return b;
    };
    auto* count = new QSpinBox(&dialog);
    count->setRange(1, 1000);
    count->setValue(3);
    QDoubleSpinBox *dx = spin(-1e4, 1e4, 1.0, 3), *dy = spin(-1e4, 1e4, 0.0, 3);
    QDoubleSpinBox *cx = spin(-1e5, 1e5, 0.0, 3), *cy = spin(-1e5, 1e5, 0.0, 3), *angle = spin(-360, 360, 90, 2);
    form->addRow(tr("Kind:"), kind);
    form->addRow(tr("Number of copies:"), count);
    form->addRow(tr("Distance X (m):"), dx);
    form->addRow(tr("Distance Y (m):"), dy);
    form->addRow(tr("Centre X (m):"), cx);
    form->addRow(tr("Centre Y (m):"), cy);
    form->addRow(tr("Angle per copy (degrees):"), angle);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    form->addRow(buttons);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    if (dialog.exec() != QDialog::Accepted)
        return;
    if (kind->currentData().toString() == QLatin1String("linear"))
        multiplySelection(QStringLiteral("linear"), {{"dx", dx->value()}, {"dy", dy->value()}, {"count", count->value()}});
    else
        multiplySelection(QStringLiteral("polar"), {{"cx", cx->value()}, {"cy", cy->value()},
            {"angle", angle->value() * M_PI / 180.0}, {"count", count->value()}});
}

void MainWindow::offsetDialog()
{
    if (m_selection.isEmpty()) {
        m_status->showMessage(tr("Select walls or slabs to offset first"));
        return;
    }
    bool ok = false;
    const double distance = QInputDialog::getDouble(this, tr("Offset"),
        tr("Distance (m): walls get a parallel copy to the left of their axis (negative: right); slabs grow (negative: shrink)"),
        0.5, -1000, 1000, 3, &ok);
    if (ok)
        offsetSelection(distance);
}

bool MainWindow::createModel(const QString& name)
{
    const QJsonObject r = bridge("create_model", {name});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not create the model"), r.value("error").toString());
        return false;
    }
    afterEdit(r);
    m_levels->setActive(r.value("guid").toString());
    m_status->showMessage(tr("Draw the model here, then place it on levels with Place model (U)"));
    return true;
}

bool MainWindow::placeModelAt(QPointF p, bool turned)
{
    if (m_levels->activeIsModel()) {
        m_status->showMessage(tr("Choose a building level to place the model on"));
        return false;
    }
    QJsonObject model = m_tool == Tool::PlaceModel ? currentType() : QJsonObject();
    if (model.isEmpty())
        model = bridge("models").value("models").toArray().first().toObject();
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge("place_model", {model.value("guid").toString(), m_levels->activeStorey(), num(p.x()),
        num(p.y()), num(turned ? M_PI / 2 : 0.0)});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not place it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::updateModelInstances()
{
    const QJsonArray models = bridge("models").value("models").toArray();
    QString guid;
    if (m_levels->activeIsModel())
        guid = m_levels->activeStorey();
    else if (models.size() == 1)
        guid = models.first().toObject().value("guid").toString();
    else if (!models.isEmpty()) {
        QStringList names;
        for (const auto& m : models)
            names << m.toObject().value("name").toString();
        bool ok = false;
        const QString choice = QInputDialog::getItem(this, tr("Update model instances"), tr("Model:"), names, 0, false, &ok);
        if (!ok)
            return false;
        guid = models.at(names.indexOf(choice)).toObject().value("guid").toString();
    }
    if (guid.isEmpty()) {
        m_status->showMessage(tr("There are no models yet"));
        return false;
    }
    const QJsonObject r = bridge("update_model_instances", {guid});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not update: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    m_status->showMessage(tr("%n instance(s) updated", nullptr, r.value("count").toInt()));
    return true;
}

bool MainWindow::explodeSelectedInstance()
{
    QString instance;
    for (const QString& g : std::as_const(m_selection))
        if (m_instanceOf.contains(g))
            instance = m_instanceOf.value(g);
    if (instance.isEmpty()) {
        m_status->showMessage(tr("Select a placed model first"));
        return false;
    }
    const QJsonObject r = bridge("explode_instance", {instance});
    if (!r.value("ok").toBool())
        return false;
    afterEdit(r);
    return true;
}

bool MainWindow::createLayer(const QString& name)
{
    const QJsonObject r = bridge("create_layer", {name});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not create the layer: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::assignSelectionToLayer(const QString& layer)
{
    const QJsonObject r = bridge("assign_layer", {jsonList(m_selection), layer});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not change the layer: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    m_status->showMessage(tr("%n element(s) moved to %1", nullptr, int(m_selection.size())).arg(layer));
    return true;
}

void MainWindow::setLayerVisible(const QString& layer, bool visible)
{
    if (visible)
        m_hiddenLayers.remove(layer);
    else
        m_hiddenLayers.insert(layer);
    saveLayerStates();
    refreshLayers();
}

void MainWindow::setLayerLocked(const QString& layer, bool locked)
{
    if (locked)
        m_lockedLayers.insert(layer);
    else
        m_lockedLayers.remove(layer);
    saveLayerStates();
    refreshLayers();
}

bool MainWindow::setActiveLayer(const QString& layer)
{
    const QJsonObject r = bridge("set_active_layer", {layer});
    refreshLayers();
    if (r.value("ok").toBool())
        m_status->showMessage(tr("New elements go on layer %1").arg(layer));
    return r.value("ok").toBool();
}

bool MainWindow::saveView(const QString& name)
{
    QJsonObject data{{"hidden", QJsonArray::fromStringList(QStringList(m_hiddenLayers.begin(), m_hiddenLayers.end()))},
        {"locked", QJsonArray::fromStringList(QStringList(m_lockedLayers.begin(), m_lockedLayers.end()))},
        {"level", m_levels->activeStorey()}, {"plan", m_viewport->isPlanView()},
        {"cut", m_planCut->isChecked() ? QJsonValue(m_cutHeight->value()) : QJsonValue()},
        {"linesOnly", m_viewport->linesOnly()}, {"purpose", m_viewport->graphics().purpose()}};
    const QJsonObject r = bridge("save_view", {name, QString::fromUtf8(QJsonDocument(data).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not save the view: %1").arg(r.value("error").toString()));
        return false;
    }
    m_currentView = name;
    afterEdit(r);
    return true;
}

bool MainWindow::applyView(const QString& name)
{
    for (const auto& v : bridge("views").value("views").toArray()) {
        const QJsonObject o = v.toObject();
        if (o.value("name").toString() != name)
            continue;
        const QJsonObject data = o.value("data").toObject();
        if (!data.value("purpose").toString().isEmpty()) // D73; the view's own layer states win below
            bridge("set_purpose", {data.value("purpose").toString()});
        m_settings = bridge("project_settings").value("settings").toObject();
        m_hiddenLayers.clear();
        m_lockedLayers.clear();
        for (const auto& l : data.value("hidden").toArray())
            m_hiddenLayers.insert(l.toString());
        for (const auto& l : data.value("locked").toArray())
            m_lockedLayers.insert(l.toString());
        if (!data.value("level").toString().isEmpty())
            m_levels->setActive(data.value("level").toString());
        if (data.contains("linesOnly"))
            findChild<QAction*>(QStringLiteral("actionLinesOnly"))->setChecked(data.value("linesOnly").toBool());
        if (data.value("cut").isDouble()) {
            m_cutHeight->setValue(data.value("cut").toDouble());
            m_planCut->setChecked(true);
        } else if (data.contains("cut")) {
            m_planCut->setChecked(false);
        }
        if (data.contains("plan"))
            setPlanView(data.value("plan").toBool());
        applyCuts();
        m_currentView = name;
        saveLayerStates();
        refreshLayers();
        refreshAnnotations();
        regenerateOpenDrawings();
        m_status->showMessage(tr("View %1").arg(name));
        return true;
    }
    return false;
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
        m_status->showMessage(tr("Could not place it: %1").arg(r.value("error").toString()));
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
        m_status->showMessage(tr("Could not create it: %1").arg(r.value("error").toString()));
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
        m_status->showMessage(tr("Could not create the slab: %1").arg(r.value("error").toString()));
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
        m_status->showMessage(tr("Could not place it: %1").arg(r.value("error").toString()));
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
        m_status->showMessage(tr("Could not create the wall: %1").arg(r.value("error").toString()));
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
    { StepTimer _(m_timings, "refreshLayers"); refreshLayers(); }
    { StepTimer _(m_timings, "refreshAnnotations"); refreshAnnotations(); }
    { StepTimer _(m_timings, "refreshDrawings"); refreshDrawings(); }
    { StepTimer _(m_timings, "refreshSheets"); refreshSheets(); }
    StepTimer stateTimer(m_timings, "stateAndNames");
    const QJsonObject s = bridge("state");
    m_undo->setEnabled(s.value("can_undo").toBool());
    m_redo->setEnabled(s.value("can_redo").toBool());
    setWindowModified(s.value("dirty").toBool());
    m_tree->updateNames(bridge("spatial_tree")); // names can change through edits and undo
    // Defer the panel rebuild: this can run from inside the panel's own itemChanged handler.
    QMetaObject::invokeMethod(this, &MainWindow::refreshProperties, Qt::QueuedConnection);
    if (m_schedules)
        m_schedules->modelChanged();
}

bool MainWindow::nativeEvent(const QByteArray& eventType, void* message, qintptr* result)
{
    if (TitleBar::nativeEvent(this, m_titleBar, eventType, message, result)) // D75: the custom title bar
        return true;
    return QMainWindow::nativeEvent(eventType, message, result);
}

bool MainWindow::isDirty() const
{
    QString error;
    return PythonEngine::instance().callJson("state", {}, &error).object().value("dirty").toBool();
}

QJsonObject MainWindow::documentState()
{
    m_document = bridge("document_state");
    return m_document;
}

bool MainWindow::hasUnversionedWork()
{
    return bridge("project_state").value("unversioned").toBool();
}

bool MainWindow::save()
{
    const QJsonObject doc = documentState();
    if (doc.value("read_only").toBool() || doc.value("untitled").toBool()) {
        if (m_quiet)
            return false; // never a dialog in quiet mode
        saveAsDialog();
        return !isDirty();
    }
    maybeAutoVersion();
    const QJsonObject r = bridge("save_document");
    if (!r.value("ok").toBool()) {
        showError(tr("Could not save"), r.value("error").toString());
        return false;
    }
    afterSave();
    return true;
}

// D72: an automatic version every N saves or N minutes, when the preference asks for it.
void MainWindow::maybeAutoVersion()
{
    if (!m_versioned || m_prefs.autoVersion() == QLatin1String("off") || !hasUnversionedWork())
        return;
    ++m_savesSinceVersion;
    const bool due = m_prefs.autoVersion() == QLatin1String("saves")
        ? m_savesSinceVersion >= m_prefs.autoVersionEvery()
        : m_sinceVersion.elapsed() >= qint64(m_prefs.autoVersionEvery()) * 60000;
    if (due)
        commitVersion(tr("Automatic version"));
}

void MainWindow::afterSave()
{
    afterEdit();
    refreshProject();
    m_status->showMessage(tr("Saved %1").arg(documentState().value("name").toString()));
}

bool MainWindow::saveAs(const QString& path)
{
    const bool ifc = QFileInfo(path).suffix().compare(QLatin1String("ifc"), Qt::CaseInsensitive) == 0;
    // Saving a model as a .kim for the first time makes its first version: minutes on large models.
    const QJsonObject r = ifc ? bridge("save_as_ifc", {path})
        : bridgeInBackground("save_as_kim", {path}, tr("Saving %1...").arg(QFileInfo(path).fileName()));
    if (!r.value("ok").toBool()) {
        showError(tr("Could not save"), r.value("error").toString());
        return false;
    }
    m_path = path;
    rememberRecent(path);
    afterSave();
    return true;
}

void MainWindow::saveAsDialog()
{
    QString selected;
    const QString path = QFileDialog::getSaveFileName(this, tr("Save As"), m_document.value("path").toString(),
        tr("KimBim project (*.kim);;IFC file (*.ifc)"), &selected);
    if (!path.isEmpty())
        saveAs(path);
}

bool MainWindow::saveAsFolder(const QString& folder)
{
    const QJsonObject r = bridgeInBackground("save_as_folder", {folder}, tr("Saving %1...").arg(QFileInfo(folder).fileName()));
    if (!r.value("ok").toBool()) {
        showError(tr("Could not save the project folder"), r.value("error").toString());
        return false;
    }
    rememberRecent(folder);
    afterSave();
    return true;
}

bool MainWindow::enableVersioning(const QString& folder, const QString& message)
{
    const QJsonObject r = bridgeInBackground("save_as_folder", {folder, message.isEmpty() ? tr("Initial import") : message},
        tr("Saving the first version..."));
    if (!r.value("ok").toBool()) {
        showError(tr("Could not enable versioning"), r.value("error").toString());
        return false;
    }
    afterSave();
    m_status->showMessage(tr("Versioning enabled: first version saved"));
    return true;
}

bool MainWindow::exportIfc(const QString& path)
{
    const QJsonObject r = bridge("export_ifc", {path});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not export"), r.value("error").toString());
        return false;
    }
    m_status->showMessage(tr("Exported %1").arg(QFileInfo(path).fileName()));
    return true;
}

void MainWindow::saveAsFolderDialog()
{
    const QString folder = QFileDialog::getExistingDirectory(this, tr("Choose an empty folder for the project"));
    if (!folder.isEmpty())
        saveAsFolder(folder);
}

void MainWindow::exportIfcDialog()
{
    const QString path = QFileDialog::getSaveFileName(this, tr("Export IFC"), QString(), tr("IFC files (*.ifc)"));
    if (!path.isEmpty())
        exportIfc(path);
}

void MainWindow::newProjectDialog()
{
    const QJsonObject listing = bridge("templates", {m_prefs.templatesFolder()});
    const QJsonArray list = listing.value("templates").toArray();
    if (list.size() <= 1 || m_quiet) {
        newProject();
        return;
    }
    QDialog dialog(this);
    dialog.setWindowTitle(tr("New project"));
    auto* layout = new QVBoxLayout(&dialog);
    layout->addWidget(new QLabel(tr("Start from a template:"), &dialog));
    auto* choices = new QListWidget(&dialog);
    choices->setObjectName(QStringLiteral("templateList"));
    for (const auto& v : list) {
        const QJsonObject t = v.toObject();
        auto* item = new QListWidgetItem(t.value("builtin").toBool() ? tr("KimBim default")
            : QStringLiteral("%1  (%2)").arg(t.value("name").toString(), t.value("modified").toString()), choices);
        item->setData(Qt::UserRole, t.value("path").toString());
    }
    choices->setCurrentRow(0);
    layout->addWidget(choices);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    connect(choices, &QListWidget::itemDoubleClicked, &dialog, &QDialog::accept);
    layout->addWidget(buttons);
    if (dialog.exec() == QDialog::Accepted && choices->currentItem())
        newFromTemplate(choices->currentItem()->data(Qt::UserRole).toString());
}

bool MainWindow::saveAsTemplate(const QString& name, bool replace)
{
    QJsonObject r = bridge("save_template", {m_prefs.templatesFolder(), name, replace ? QStringLiteral("1") : QString()});
    if (!r.value("ok").toBool() && r.value("exists").toBool() && !m_quiet
        && QMessageBox::question(this, tr("Save as template"), tr("A template called %1 exists. Replace it?").arg(name))
               == QMessageBox::Yes)
        r = bridge("save_template", {m_prefs.templatesFolder(), name, QStringLiteral("1")});
    if (!r.value("ok").toBool()) {
        if (!r.value("exists").toBool())
            showError(tr("Could not save the template"), r.value("error").toString());
        return false;
    }
    m_status->showMessage(tr("Template %1 saved").arg(name));
    return true;
}

void MainWindow::saveAsTemplateDialog()
{
    bool ok = false;
    const QString name = QInputDialog::getText(this, tr("Save as template"),
        tr("Template name (saved in %1):").arg(QDir::toNativeSeparators(m_prefs.templatesFolder())),
        QLineEdit::Normal, QString(), &ok);
    if (ok && !name.trimmed().isEmpty())
        saveAsTemplate(name.trimmed());
}

void MainWindow::projectSettingsDialog()
{
    ProjectSettingsDialog dialog(m_settings, bridge("project_settings").value("kept").toBool(), this);
    if (dialog.exec() == QDialog::Accepted && !dialog.changes().isEmpty() && setProjectSettings(dialog.changes()))
        m_status->showMessage(tr("Project settings changed"));
}

void MainWindow::preferencesDialog()
{
    PreferencesDialog dialog(m_prefs, this);
    if (dialog.exec() != QDialog::Accepted)
        return;
    m_prefs.save();
    Viewport::setScrollMode(Viewport::scrollModeFrom(m_prefs.scrollNavigation())); // D89
    applyViewPreferences(); // D92: the field of view and the home view
    bridge("set_author", {m_prefs.authorName(), m_prefs.authorEmail()});
    applyDrawingPrefs();
    restartRecoveryTimer();
    applyLibraryPaths(); // D86: the office library may have changed
}

void MainWindow::restartRecoveryTimer()
{
    m_recoveryTimer.stop();
    if (!m_quiet && m_prefs.recoveryMinutes() > 0)
        m_recoveryTimer.start(m_prefs.recoveryMinutes() * 60000);
}

bool MainWindow::writeRecovery()
{
    return bridge("write_recovery").value("ok").toBool();
}

QJsonArray MainWindow::recoveries()
{
    return bridge("recoveries").value("items").toArray();
}

bool MainWindow::recoverFrom(const QString& id)
{
    if (!prepareToOpen())
        return false;
    const QJsonObject r = bridge("recover", {id});
    if (!r.value("ok").toBool()) {
        showError(tr("Could not recover the work"), r.value("error").toString());
        return false;
    }
    openFile(r.value("path").toString());
    return true;
}

void MainWindow::offerRecovery()
{
    if (m_quiet)
        return; // never a dialog in quiet mode
    for (const auto& v : recoveries()) {
        const QJsonObject item = v.toObject();
        const QString what = item.value("name").toString().isEmpty() ? tr("an untitled project") : item.value("name").toString();
        const QString when = QLocale().toString(QDateTime::fromSecsSinceEpoch(qint64(item.value("time").toDouble())), QLocale::ShortFormat);
        const auto answer = QMessageBox::question(this, tr("Recover unsaved work"),
            tr("KimBim closed unexpectedly. Recover your work on %1 from %2?").arg(what, when),
            QMessageBox::Yes | QMessageBox::Discard, QMessageBox::Yes);
        if (answer == QMessageBox::Yes)
            return void(recoverFrom(item.value("id").toString()));
        bridge("discard_recovery", {item.value("id").toString()});
    }
}

void MainWindow::loadProjectSettings()
{
    m_settings = bridge("project_settings").value("settings").toObject();
    m_hiddenLayers.clear();
    m_lockedLayers.clear();
    for (const auto& l : m_settings.value("hidden_layers").toArray())
        m_hiddenLayers.insert(l.toString());
    for (const auto& l : m_settings.value("locked_layers").toArray())
        m_lockedLayers.insert(l.toString());
    const QSignalBlocker block(m_cutHeight);
    m_cutHeight->setValue(m_settings.value("plan_cut_height").toDouble(1.2));
    m_cutLabel->setText(formatLength(m_cutHeight->value()));
}

bool MainWindow::setProjectSettings(const QJsonObject& changes)
{
    const QJsonObject r = bridge("set_project_settings",
        {QString::fromUtf8(QJsonDocument(changes).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(r.value("error").toString());
        return false;
    }
    m_settings = r.value("settings").toObject();
    setWindowModified(isDirty());
    refreshGraphics();
    return true;
}

QString MainWindow::formatLength(double metres) const
{
    const QString unit = m_settings.value("length_unit").toString(QStringLiteral("m"));
    const double factor = unit == QLatin1String("mm") ? 1000.0 : unit == QLatin1String("cm") ? 100.0 : 1.0;
    return QLocale().toString(metres * factor, 'f', m_settings.value("length_decimals").toInt(2))
        + QLatin1Char(' ') + unit;
}

void MainWindow::saveLayerStates()
{
    if (!bridge("document_state").value("kept").toBool())
        return; // an IFC edited directly keeps no settings: showing a layer isn't unsaved work there
    QStringList hidden(m_hiddenLayers.begin(), m_hiddenLayers.end()), locked(m_lockedLayers.begin(), m_lockedLayers.end());
    hidden.sort();
    locked.sort();
    setProjectSettings({{"hidden_layers", QJsonArray::fromStringList(hidden)},
                        {"locked_layers", QJsonArray::fromStringList(locked)}});
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
    refreshLevels();
    m_types->clear();
    m_warnedInconsistent = false;
    m_undo->setEnabled(false);
    m_redo->setEnabled(false);
    QString error;
    const QJsonObject tree = PythonEngine::instance().callJson("spatial_tree", {}, &error).object();
    m_tree->setTree(tree);
    loadProjectSettings();
    m_currentView.clear();
    refreshProject();
    refreshLayers();
    refreshAnnotations();
    refreshDrawings();
    refreshSheets();
    m_status->showMessage(tr("Loading %1 (%2)...").arg(QFileInfo(m_path).fileName(), info.value("schema").toString()));
}

void MainWindow::onChunk(const MeshChunk& chunk)
{
    if (!m_loading)
        return; // a stopped load's late chunk
    const bool first = m_viewport->batchCount() == 0;
    m_viewport->addBatch(new ElementBatch(chunk));
    m_loadedElements += chunk.elementCount();
    m_status->showMessage(tr("Loading... %n element(s)", nullptr, m_loadedElements));
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
        m_status->showMessage(tr("%n element(s) loaded in %1 s", nullptr, elements)
                                     .arg(double(m_loadTimer.elapsed()) / 1000.0, 0, 'f', 1));
    }
    emit loadFinished(elements, stopped);
    if (std::exchange(m_askImportStatus, false) && !stopped) // D74: after the other load-finished work
        QMetaObject::invokeMethod(this, &MainWindow::askImportStatus, Qt::QueuedConnection);
}

void MainWindow::onFailed(const QString& error)
{
    m_loading = false;
    showError(tr("Could not open the model"), error);
    emit loadFailed(error);
}

} // namespace kimbim
