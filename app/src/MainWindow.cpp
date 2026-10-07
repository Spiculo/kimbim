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
#include <QSignalBlocker>
#include <cmath>
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
#include <QTabBar>
#include <QTabWidget>
#include <QTimer>
#include <QHeaderView>
#include <QTableWidget>
#include <QCheckBox>
#include <QDateTime>
#include <QPushButton>

#include "CombineDialog.h"
#include "Cuts.h"
#include "DrawingView.h"
#include "DrawingsPanel.h"
#include "SheetExport.h"
#include "SheetsPanel.h"
#include "ElementBatch.h"
#include "HistoryPanel.h"
#include "LayersPanel.h"
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
    // The 3D view with the plan-cut height slider at its right edge (owner feedback).
    auto* central = new QWidget(this);
    auto* row = new QHBoxLayout(central);
    row->setContentsMargins(0, 0, 0, 0);
    row->setSpacing(0);
    row->addWidget(m_viewport, 1);
    auto* cutColumn = new QVBoxLayout;
    cutColumn->setContentsMargins(4, 6, 4, 6);
    m_cutLabel = new QLabel(central);
    m_cutLabel->setAlignment(Qt::AlignHCenter);
    m_cutSlider = new QSlider(Qt::Vertical, central);
    m_cutSlider->setObjectName(QStringLiteral("planCutSlider"));
    m_cutSlider->setToolTip(tr("Plan cut height above the active level (drag to cut the model)"));
    m_cutSlider->setRange(0, 300);
    m_cutSlider->setValue(120);
    m_cutSlider->setTickPosition(QSlider::TicksLeft);
    m_cutSlider->setTickInterval(50);
    cutColumn->addWidget(m_cutLabel);
    cutColumn->addWidget(m_cutSlider, 1, Qt::AlignHCenter);
    row->addLayout(cutColumn);
    // The model is the first tab; drawings open next to it (Slice 14).
    m_tabs = new QTabWidget(this);
    m_tabs->setObjectName(QStringLiteral("mainTabs"));
    m_tabs->setDocumentMode(true);
    m_tabs->addTab(central, tr("Model"));
    m_tabs->setTabsClosable(true);
    m_tabs->tabBar()->setTabButton(0, QTabBar::RightSide, nullptr); // the model tab stays
    m_tabs->tabBar()->setTabButton(0, QTabBar::LeftSide, nullptr);
    connect(m_tabs, &QTabWidget::tabCloseRequested, this, &MainWindow::closeDrawingTab);
    connect(m_tabs, &QTabWidget::currentChanged, this, [this](int index) {
        auto* view = qobject_cast<DrawingView*>(m_tabs->widget(index));
        if (view && (view->isStale() || !view->hasDrawing()))
            regenerateDrawing(view->guid()); // a drawing brought to the front is brought up to date
    });
    setCentralWidget(m_tabs);
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
    connect(m_viewport, &Viewport::dragMoved, this, &MainWindow::dragMoveTo);
    connect(m_viewport, &Viewport::dragReleased, this, &MainWindow::dragFinished);
    connect(m_viewport, &Viewport::hovered, this, [this](const QString& guid, const QPoint& at) {
        const QString hint = guid.isEmpty() ? QString() : m_tree->hintFor(guid);
        if (hint.isEmpty())
            QToolTip::hideText();
        else
            QToolTip::showText(at, hint, m_viewport);
    });
    connect(m_tree, &ModelTreePanel::hideRequested, this, [this](const QStringList& g) { m_viewport->setHidden(g, true); });
    connect(m_tree, &ModelTreePanel::showAllRequested, m_viewport, &Viewport::showAll);

    QString error;
    if (!PythonEngine::instance().start(&error))
        showError(tr("KIMCAD cannot start"), error);
}

MainWindow::~MainWindow()
{
    for (QThread* t : std::as_const(m_drawingThreads))
        t->wait(); // a drawing being generated: its result is dropped
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
    QAction* info = file->addAction(tr("Project &info..."));
    info->setObjectName(QStringLiteral("actionProjectInfo"));
    connect(info, &QAction::triggered, this, &MainWindow::projectInfoDialog);
    QAction* pdf = file->addAction(tr("Export sheet as &PDF..."));
    pdf->setObjectName(QStringLiteral("actionExportSheetPdf"));
    connect(pdf, &QAction::triggered, this, [this] { exportSheetDialog(true); });
    QAction* svgExport = file->addAction(tr("Export sheet as S&VG..."));
    svgExport->setObjectName(QStringLiteral("actionExportSheetSvg"));
    connect(svgExport, &QAction::triggered, this, [this] { exportSheetDialog(false); });
    QAction* schedule = file->addAction(tr("&Room schedule..."));
    schedule->setObjectName(QStringLiteral("actionRoomSchedule"));
    connect(schedule, &QAction::triggered, this, &MainWindow::roomScheduleDialog);
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
    editAction(tr("&Mirror"), "actionMirror", QKeySequence(Qt::CTRL | Qt::Key_M), [this] { setTool(Tool::Mirror); })
        ->setToolTip(tr("Mirror the selection: click two points of the mirror line (hold Ctrl on the second click to mirror a copy)"));
    editAction(tr("Multi&ply..."), "actionMultiply", QKeySequence(Qt::CTRL | Qt::Key_U), [this] { multiplyDialog(); });
    editAction(tr("&Offset..."), "actionOffset", QKeySequence(), [this] { offsetDialog(); });

    QMenu* view = menuBar()->addMenu(tr("&View"));
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
            statusBar()->showMessage(tr("Could not add them: %1").arg(r.value("error").toString()));
            return;
        }
        afterEdit(r);
        statusBar()->showMessage(tr("%n drawing(s) added", nullptr, r.value("created").toInt()));
    });
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
    connect(m_history, &HistoryPanel::beforeAfterRequested, this, [this](const QString& guid) {
        if (!m_compareA.isEmpty())
            beforeAfterDialog(guid, m_compareA, m_compareB);
    });
    connect(m_history, &HistoryPanel::elementActivated, this, [this](const QString& guid) {
        m_viewport->selectGuids({guid});
        m_tree->selectGuids({guid});
        setSelection({guid});
    });
    m_layersPanel = new LayersPanel(this);
    auto* layersDock = new QDockWidget(tr("Layers"), this);
    layersDock->setObjectName(QStringLiteral("LayersDock"));
    layersDock->setWidget(m_layersPanel);
    addDockWidget(Qt::LeftDockWidgetArea, layersDock);
    tabifyDockWidget(treeDock, layersDock);
    m_drawingsPanel = new DrawingsPanel(this);
    auto* drawingsDock = new QDockWidget(tr("Drawings"), this);
    drawingsDock->setObjectName(QStringLiteral("DrawingsDock"));
    drawingsDock->setWidget(m_drawingsPanel);
    addDockWidget(Qt::LeftDockWidgetArea, drawingsDock);
    tabifyDockWidget(layersDock, drawingsDock);
    connect(m_drawingsPanel, &DrawingsPanel::openRequested, this, [this](const QString& g) { openDrawing(g); });
    m_sheetsPanel = new SheetsPanel(this);
    auto* sheetsDock = new QDockWidget(tr("Sheets"), this);
    sheetsDock->setObjectName(QStringLiteral("SheetsDock"));
    sheetsDock->setWidget(m_sheetsPanel);
    addDockWidget(Qt::LeftDockWidgetArea, sheetsDock);
    tabifyDockWidget(drawingsDock, sheetsDock);
    connect(m_sheetsPanel, &SheetsPanel::newRequested, this, [this](const QString& paper) {
        bool ok = m_quiet;
        const QString title = m_quiet ? QString()
            : QInputDialog::getText(this, tr("New sheet"), tr("Title:"), QLineEdit::Normal, QString(), &ok);
        if (ok) {
            const QString number = addSheet(paper, title);
            if (!number.isEmpty())
                openSheet(number);
        }
    });
    connect(m_sheetsPanel, &SheetsPanel::openRequested, this, [this](const QString& n) { openSheet(n); });
    connect(m_sheetsPanel, &SheetsPanel::placeRequested, this, [this](const QString& n) {
        const QString drawing = m_drawingsPanel->selectedDrawing();
        if (drawing.isEmpty()) {
            statusBar()->showMessage(tr("Select a drawing in the Drawings panel first"));
            return;
        }
        placeOnSheet(n, drawing);
    });
    connect(m_sheetsPanel, &SheetsPanel::deleteRequested, this, [this](const QString& n) {
        const QJsonObject r = bridge("delete_sheet", {n});
        if (!r.value("ok").toBool())
            statusBar()->showMessage(tr("Could not delete it: %1").arg(r.value("error").toString()));
        afterEdit(r);
    });
    connect(m_drawingsPanel, &DrawingsPanel::renameRequested, this, [this](const QString& g, const QString& name) {
        const QJsonObject r = bridge("rename_drawing", {g, name});
        if (!r.value("ok").toBool())
            statusBar()->showMessage(tr("Could not rename it: %1").arg(r.value("error").toString()));
        afterEdit(r);
    });
    connect(m_drawingsPanel, &DrawingsPanel::deleteRequested, this, [this](const QString& g) {
        const QJsonObject r = bridge("delete_drawing", {g});
        if (!r.value("ok").toBool())
            statusBar()->showMessage(tr("Could not delete it: %1").arg(r.value("error").toString()));
        afterEdit(r);
    });
    treeDock->raise();
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
            statusBar()->showMessage(r.value("error").toString());
        m_hiddenLayers.remove(name);
        m_lockedLayers.remove(name);
        afterEdit(r);
    });
    connect(m_layersPanel, &LayersPanel::renameRequested, this, [this](const QString& from, const QString& to) {
        const QJsonObject r = bridge("rename_layer", {from, to});
        if (!r.value("ok").toBool())
            statusBar()->showMessage(r.value("error").toString());
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
    resizeDocks({treeDock, propsDock}, {340, 360}, Qt::Horizontal);
}

void MainWindow::buildCutsToolbar()
{
    QToolBar* levels = addToolBar(tr("Levels"));
    levels->setObjectName(QStringLiteral("levelsToolbar"));
    m_levels = new LevelsBar(levels);
    levels->addWidget(m_levels);
    connect(m_levels, &LevelsBar::addLevelRequested, this, &MainWindow::addLevelDialog);
    connect(m_levels, &LevelsBar::newModelRequested, this, [this] {
        bool ok = false;
        const QString name = QInputDialog::getText(this, tr("New model"),
            tr("Model name (e.g. Apartment A). Draw it, then place it on levels with Place model:"), QLineEdit::Normal,
            QString(), &ok);
        if (ok && !name.trimmed().isEmpty())
            createModel(name.trimmed());
    });
    connect(m_levels, &LevelsBar::activeStoreyChanged, this, [this](const QString&, double elevation) {
        updateCutSliderRange();
        m_viewport->setWorkPlaneZ(elevation);
        if (m_viewport->isPlanView())
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
    connect(m_cutHeight, &QDoubleSpinBox::valueChanged, this, [this](double metres) {
        {
            const QSignalBlocker block(m_cutSlider);
            m_cutSlider->setValue(int(std::lround(metres * 100)));
        }
        m_cutLabel->setText(QLocale().toString(metres, 'f', 2) + QStringLiteral(" m"));
        if (m_planCut->isChecked())
            applyCuts();
    });
    connect(m_cutSlider, &QSlider::valueChanged, this, [this](int centimetres) {
        m_cutHeight->setValue(centimetres / 100.0); // updates the label and the cut
        if (!m_planCut->isChecked())
            m_planCut->setChecked(true); // using the slider means cutting
    });
    m_cutLabel->setText(QLocale().toString(m_cutHeight->value(), 'f', 2) + QStringLiteral(" m"));
    bar->addSeparator();
    bar->addAction(m_sectionBox);
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
    QStringList expanded = guids;
    for (const QString& g : guids)
        if (const auto it = m_instanceOf.constFind(g); it != m_instanceOf.constEnd())
            for (const QString& m : m_instanceMembers.value(*it))
                if (!expanded.contains(m))
                    expanded << m;
    if (expanded.size() != guids.size()) { // a click on an instance takes the whole instance
        m_viewport->selectGuids(expanded);
        m_tree->selectGuids(expanded);
    }
    m_selection = expanded;
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
    // The Dimensions group is live geometry, not a property set: it edits the elements' shape.
    if (pset == QLatin1String("KIMCAD_Annotation") && (prop == QLatin1String("Text") || prop == QLatin1String("Size"))) {
        bool all = true;
        for (const QString& g : std::as_const(m_selection)) {
            const QString v = value.isDouble() ? QString::number(value.toDouble(), 'g', 17) : value.toString();
            const QJsonObject r = bridge(prop == QLatin1String("Size") ? "set_annotation_size" : "set_annotation_text", {g, v});
            if (!r.value("ok").toBool())
                statusBar()->showMessage(tr("Could not change %1").arg(prop) + QStringLiteral(": ") + r.value("error").toString());
            all = all && r.value("ok").toBool();
            afterEdit(r);
        }
        return all;
    }
    const QJsonObject r = pset == QLatin1String("Dimensions")
        ? bridge("set_dimension", {jsonList(m_selection), prop,
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
    m_hiddenLayers.clear();
    m_lockedLayers.clear();
    m_currentView.clear();
    refreshLayers();
    refreshAnnotations();
    refreshDrawings();
    refreshSheets();
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
        {Tool::Stair, "actionStairTool", tr("S&tair"), Qt::Key_T,
            tr("Draw a stair: click where it starts, then the direction it climbs; it goes up to the next level")},
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
    m_roofAction = bar->addWidget(roofBox);
    m_roofAction->setVisible(false);
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
                statusBar()->showMessage(tr("Mirror: click the second point of the mirror line (Ctrl: mirror a copy)"));
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
        else if ((m_tool == Tool::Slab || m_tool == Tool::SlabOpening || m_tool == Tool::Roof) && m_polygonTool->isDrawing())
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
        else if (m_tool == Tool::Slab || m_tool == Tool::SlabOpening || m_tool == Tool::Roof)
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
        else if (m_tool == Tool::Roof)
            createRoof(outline);
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
    m_annotationPoints.clear();
    m_tool = tool;
    m_twoPointTool->snapper().setFaceSnapping(tool == Tool::Dimension); // dimensions measure wall faces
    for (auto it = m_toolActions.constBegin(); it != m_toolActions.constEnd(); ++it) {
        const QSignalBlocker block(it.value());
        it.value()->setChecked(it.key() == int(tool));
    }
    m_wallHeightAction->setVisible(tool == Tool::Wall || tool == Tool::Column || tool == Tool::Beam || tool == Tool::Roof);
    m_wallHeight->setToolTip(tool == Tool::Roof ? tr("Eaves height above the level") : tr("Wall height"));
    m_roofAction->setVisible(tool == Tool::Roof);
    m_lengthAction->setVisible(tool == Tool::Wall || tool == Tool::Beam || tool == Tool::Grid || tool == Tool::Move
        || tool == Tool::Rotate || tool == Tool::Stretch);
    m_lengthInput->setPlaceholderText(tool == Tool::Rotate ? tr("Angle (degrees)") : tr("Length (m)"));
    const bool typed = tool == Tool::Wall || tool == Tool::Slab || tool == Tool::Door || tool == Tool::Window
        || tool == Tool::Column || tool == Tool::Beam || tool == Tool::PlaceModel;
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
    case Tool::Text:
        statusBar()->showMessage(tr("Text: click where the label goes"));
        break;
    case Tool::Dimension:
        statusBar()->showMessage(tr("Dimension: click the first point to measure"));
        break;
    case Tool::Mark:
        statusBar()->showMessage(tr("Mark: click what to mark"));
        break;
    case Tool::Leader:
        statusBar()->showMessage(tr("Leader: click what it points at"));
        break;
    case Tool::Room:
        statusBar()->showMessage(tr("Room: click inside the walls that enclose it"));
        break;
    case Tool::Roof:
        statusBar()->showMessage(tr("Roof: click the eaves outline's points; click the first point or press Enter to close"));
        break;
    case Tool::Mirror:
        statusBar()->showMessage(m_selection.isEmpty() ? tr("Mirror: select what to mirror first")
                                                       : tr("Mirror: click the first point of the mirror line"));
        break;
    case Tool::Section:
        statusBar()->showMessage(tr("Section: click where the section line starts"));
        break;
    case Tool::Elevation:
        statusBar()->showMessage(tr("Elevation: click where the elevation line starts"));
        break;
    case Tool::PlaceModel:
        statusBar()->showMessage(m_types->count() ? tr("Place model: click where its origin goes (Shift: turned 90 degrees)")
                                                  : tr("There are no models yet: use New model... next to the levels"));
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
    QAction* deleteOptionAction = m_projectBar->addAction(tr("Delete option..."));
    deleteOptionAction->setObjectName(QStringLiteral("actionDeleteOption"));
    connect(deleteOptionAction, &QAction::triggered, this, &MainWindow::deleteOptionDialog);
    QAction* combineAction = m_projectBar->addAction(tr("Combine options..."));
    combineAction->setObjectName(QStringLiteral("actionCombineOptions"));
    combineAction->setToolTip(tr("Bring another design option's work into this one, choosing where both changed the same thing"));
    connect(combineAction, &QAction::triggered, this, &MainWindow::combineDialog);
    m_projectBar->addSeparator();
    QAction* milestoneAction = m_projectBar->addAction(tr("Milestone..."));
    milestoneAction->setObjectName(QStringLiteral("actionAddMilestone"));
    milestoneAction->setToolTip(tr("Name the latest saved version (Concept, Schematic design, Tender...)"));
    connect(milestoneAction, &QAction::triggered, this, &MainWindow::milestoneDialog);
    QAction* objectHistoryAction = m_projectBar->addAction(tr("Object history..."));
    objectHistoryAction->setObjectName(QStringLiteral("actionObjectHistory"));
    objectHistoryAction->setToolTip(tr("The versions that changed the selected element"));
    connect(objectHistoryAction, &QAction::triggered, this, &MainWindow::objectHistoryDialog);
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
    m_compareA = revA;
    m_compareB = revB;
    m_history->setChanges(r);
    statusBar()->showMessage(tr("Compare: %1 added, %2 modified, %3 removed")
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
    statusBar()->showMessage(tr("Now working on option %1").arg(name));
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
    statusBar()->showMessage(tr("Milestone %1 marks the latest version").arg(name));
    return true;
}

void MainWindow::milestoneDialog()
{
    if (isDirty() && !m_quiet) {
        const auto answer = QMessageBox::question(this, tr("Milestone"),
            tr("A milestone names a saved version. Save a version of your changes first?"),
            QMessageBox::Save | QMessageBox::Cancel, QMessageBox::Save);
        if (answer != QMessageBox::Save)
            return;
        saveVersionDialog();
        if (isDirty())
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
        statusBar()->showMessage(tr("This option already contains everything in %1").arg(option));
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
        statusBar()->showMessage(status == QLatin1String("fast_forward")
                ? tr("This option now has %1's latest version").arg(option)
                : tr("Combined with %1: review it (changes from %1 in green, your choices in orange), then Save version or Discard").arg(option));
    });
    return true;
}

void MainWindow::combineDialog()
{
    if (!m_versioned) {
        statusBar()->showMessage(tr("Combining needs a versioned project with design options"));
        return;
    }
    if (isDirty() && !resolveUnsavedForSwitch())
        return;
    QStringList others;
    for (const auto& o : bridge("options").value("options").toArray())
        if (o.toString() != m_options->currentText())
            others << o.toString();
    if (others.isEmpty()) {
        statusBar()->showMessage(tr("There is no other option to combine with"));
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
    statusBar()->showMessage(tr("Option %1 deleted").arg(name));
    return true;
}

void MainWindow::deleteOptionDialog()
{
    QStringList others;
    for (const auto& o : bridge("options").value("options").toArray())
        if (o.toString() != m_options->currentText() && o.toString() != QLatin1String("main"))
            others << o.toString();
    if (others.isEmpty()) {
        statusBar()->showMessage(tr("No other option to delete (the current one and main can't be deleted)"));
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
        statusBar()->showMessage(tr("Select one element to see its history"));
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
    statusBar()->showMessage(tr("Move %1 m (Ctrl: copy, Alt: detach joined walls, Shift: straight)")
                                 .arg(QLocale().toString(std::hypot(delta.x(), delta.y()), 'f', 3)));
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
    QStringList names;
    for (const auto& v : bridge("views").value("views").toArray())
        names << v.toObject().value("name").toString();
    m_layersPanel->setViews(names, m_currentView);
}

void MainWindow::refreshAnnotations()
{
    QVector<Viewport::Annotation> list;
    for (const auto& v : bridge("annotations", {m_levels->activeStorey()}).value("annotations").toArray()) {
        const QJsonObject o = v.toObject();
        Viewport::Annotation a{o.value("guid").toString(), o.value("kind").toString(), o.value("text").toString(), {},
            o.value("size").toDouble(2.5)};
        for (const auto& p : o.value("points").toArray())
            a.points << QPointF(p.toArray().at(0).toDouble(), p.toArray().at(1).toDouble());
        list << a;
    }
    // Room stamps (Slice 18): kind "room", the stamp point first, then the outline.
    for (const auto& v : bridge("rooms", {m_levels->activeStorey()}).value("rooms").toArray()) {
        const QJsonObject o = v.toObject();
        const QJsonArray label = o.value("label").toArray();
        Viewport::Annotation a{o.value("guid").toString(), QStringLiteral("room"),
            o.value("name").toString() + QLatin1Char('\n') + o.value("number").toString() + QLatin1Char('\n')
                + QLocale().toString(o.value("area").toDouble(), 'f', 2) + QStringLiteral(" m²"),
            {QPointF(label.at(0).toDouble(), label.at(1).toDouble())}};
        for (const auto& p : o.value("points").toArray())
            a.points << QPointF(p.toArray().at(0).toDouble(), p.toArray().at(1).toDouble());
        list << a;
    }
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
        statusBar()->showMessage(tr("Could not add it: %1").arg(r.value("error").toString()));
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
            statusBar()->showMessage(tr("Leader: click where its text goes"));
            return;
        }
        const QVector<QPointF> pts = m_annotationPoints;
        m_annotationPoints.clear();
        bool ok = false;
        const QString text = m_quiet ? QStringLiteral("Note")
            : QInputDialog::getText(this, tr("Leader"), tr("Text:"), QLineEdit::Normal, QString(), &ok);
        if ((ok || m_quiet) && !text.trimmed().isEmpty())
            addAnnotation(QStringLiteral("leader"), pts, text.trimmed());
        statusBar()->showMessage(tr("Leader: click what it points at"));
        return;
    }
    if (m_tool == Tool::Dimension) {
        // Slice 15: Shift+click adds another point to the chain; a plain click after two points
        // places the dimension line (Archicad builds chains the same way, one click per point).
        const bool chainMore = m_annotationPoints.size() >= 2 && (modifiers & Qt::ShiftModifier);
        m_annotationPoints << p;
        if (m_annotationPoints.size() == 1)
            statusBar()->showMessage(tr("Dimension: click the second point"));
        else if (m_annotationPoints.size() == 2 || chainMore)
            statusBar()->showMessage(tr("Dimension: Shift+click to add a point, or click where the dimension line goes"));
        else {
            const QVector<QPointF> pts = m_annotationPoints;
            m_annotationPoints.clear();
            addAnnotation(QStringLiteral("dimension"), pts, QString());
            statusBar()->showMessage(tr("Dimension: click the first point to measure"));
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
        statusBar()->showMessage(section ? tr("Section: click where the section line ends")
                                         : tr("Elevation: click where the elevation line ends"));
    } else if (m_annotationPoints.size() == 2) {
        statusBar()->showMessage(tr("Click the side the drawing looks at"));
    } else {
        const QVector<QPointF> pts = m_annotationPoints;
        m_annotationPoints.clear();
        createDrawing(section ? QStringLiteral("section") : QStringLiteral("elevation"), pts[0], pts[1], pts[2]);
        statusBar()->showMessage(section ? tr("Section: click where the section line starts")
                                         : tr("Elevation: click where the elevation line starts"));
    }
}

bool MainWindow::createDrawing(const QString& kind, QPointF p1, QPointF p2, QPointF look)
{
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge(kind == QLatin1String("section") ? "create_section" : "create_elevation",
        {num(p1.x()), num(p1.y()), num(p2.x()), num(p2.y()), num(look.x()), num(look.y()), QStringLiteral("-1")});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not add it: %1").arg(r.value("error").toString()));
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
    for (int i = m_tabs->count() - 1; i > 0; --i) {
        auto* view = qobject_cast<DrawingView*>(m_tabs->widget(i));
        if (!view || view->guid().startsWith(QLatin1String("sheet:")))
            continue; // sheets are refreshed by refreshSheets()
        const auto it = byGuid.constFind(view->guid());
        if (it == byGuid.constEnd()) { // deleted (or undone): its tab goes too
            closeDrawingTab(i);
            continue;
        }
        m_tabs->setTabText(i, it->value("name").toString());
        view->setStale(it->value("stale").toBool());
    }
}

bool MainWindow::openDrawing(const QString& guid)
{
    if (DrawingView* view = m_drawingViews.value(guid)) {
        m_tabs->setCurrentWidget(view);
        return true;
    }
    QString name;
    for (const auto& v : bridge("drawings").value("drawings").toArray())
        if (v.toObject().value("guid").toString() == guid)
            name = v.toObject().value("name").toString();
    if (name.isEmpty())
        return false;
    auto* view = new DrawingView(guid, m_tabs);
    connect(view, &DrawingView::regenerateRequested, this, &MainWindow::regenerateDrawing);
    m_drawingViews.insert(guid, view);
    view->setStale(true);
    m_tabs->addTab(view, name);
    m_tabs->setCurrentWidget(view); // brings it up to date (currentChanged)
    if (!m_generating.contains(guid) && !view->hasDrawing())
        regenerateDrawing(guid);
    return true;
}

void MainWindow::showModelTab()
{
    m_tabs->setCurrentIndex(0);
}

void MainWindow::closeDrawingTab(int index)
{
    auto* view = qobject_cast<DrawingView*>(m_tabs->widget(index));
    if (!view)
        return; // the model tab stays
    m_drawingViews.remove(view->guid());
    m_tabs->removeTab(index);
    view->deleteLater();
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
    for (const auto& v : bridge("drawings").value("drawings").toArray()) {
        const QJsonObject d = v.toObject();
        if (d.value("guid").toString() != guid)
            continue;
        const QJsonArray pts = d.value("points").toArray(), look = d.value("look").toArray();
        const Bnd_Box bounds = m_viewport->boundsOf({});
        if (pts.size() != 2 || look.size() != 2 || bounds.IsVoid())
            break;
        double x0, y0, z0, x1, y1, z1;
        bounds.Get(x0, y0, z0, x1, y1, z1);
        auto pt = [](const QJsonValue& p) { return QPointF(p.toArray().at(0).toDouble(), p.toArray().at(1).toDouble()); };
        const double depth = d.value("depth").isNull() ? -1.0 : d.value("depth").toDouble();
        const auto seen = m_viewport->visibleFrom(pt(pts.at(0)), pt(pts.at(1)),
            QPointF(look.at(0).toDouble(), look.at(1).toDouble()), z0 - 1.0, z1 + 1.0, depth);
        if (seen) {
            QStringList sorted(seen->begin(), seen->end());
            sorted.sort(); // a stable list keeps the drawing cache useful
            include = QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(sorted)).toJson(QJsonDocument::Compact));
        }
        break;
    }
    m_lastDrawingVisible = include.isEmpty() ? -1 : int(QJsonDocument::fromJson(include.toUtf8()).array().size());
    // The bridge snapshots the model and runs IfcOpenShell's serializer in a child process, which
    // can take seconds on real files (spike S6); waiting for it here would freeze the window.
    QPointer<MainWindow> self(this);
    QThread* worker = QThread::create([self, guid, include] {
        QString error;
        const bool sheet = guid.startsWith(QLatin1String("sheet:"));
        const QJsonObject result = sheet
            ? PythonEngine::instance().callJson("sheet_svg", {guid.mid(6)}, &error).object()
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
        statusBar()->showMessage(tr("Could not generate the drawing: %1").arg(error.isEmpty() ? result.value("error").toString() : error));
        return;
    }
    view->setSvg(result.value("svg").toString().toUtf8());
    if (guid.startsWith(QLatin1String("sheet:"))) {
        refreshSheets(false); // the drawings' places, for dragging
        view->setStale(false);
        if (m_generateAgain.remove(guid) && m_tabs->currentWidget() == view)
            regenerateDrawing(guid);
        return;
    }
    refreshDrawings(); // stale again if the model changed while it was generated
    if (m_generateAgain.remove(guid) && view->isStale() && m_tabs->currentWidget() == view)
        regenerateDrawing(guid);
}

// ---------------------------------------------------------------- sheets (Slice 16)

QString MainWindow::addSheet(const QString& paper, const QString& title)
{
    const QJsonObject r = bridge("add_sheet", {paper, title});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not add it: %1").arg(r.value("error").toString()));
        return QString();
    }
    afterEdit(r);
    return r.value("number").toString();
}

bool MainWindow::placeOnSheet(const QString& number, const QString& drawingGuid)
{
    statusBar()->showMessage(tr("Placing the drawing..."));
    const QJsonObject r = bridge("place_drawing", {number, drawingGuid, QStringLiteral("-1"), QStringLiteral("-1"), QStringLiteral("100")});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not place it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    openSheet(number);
    return true;
}

bool MainWindow::openSheet(const QString& number)
{
    const QString key = QStringLiteral("sheet:") + number;
    if (DrawingView* view = m_drawingViews.value(key)) {
        m_tabs->setCurrentWidget(view);
        return true;
    }
    bool exists = false;
    for (const auto& v : bridge("sheets").value("sheets").toArray())
        exists = exists || v.toObject().value("number").toString() == number;
    if (!exists)
        return false;
    auto* view = new DrawingView(key, m_tabs);
    connect(view, &DrawingView::regenerateRequested, this, &MainWindow::regenerateDrawing);
    connect(view, &DrawingView::placedMoved, this, [this, number](const QString& drawing, QPointF topLeft) {
        const QJsonObject r = bridge("move_placed", {number, drawing, QString::number(topLeft.x(), 'f', 1),
            QString::number(topLeft.y(), 'f', 1)});
        if (!r.value("ok").toBool())
            statusBar()->showMessage(tr("Could not move it: %1").arg(r.value("error").toString()));
        afterEdit(r);
    });
    m_drawingViews.insert(key, view);
    view->setStale(true);
    m_tabs->addTab(view, tr("Sheet %1").arg(number));
    m_tabs->setCurrentWidget(view);
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
    for (int i = m_tabs->count() - 1; i > 0; --i) {
        auto* view = qobject_cast<DrawingView*>(m_tabs->widget(i));
        if (!view || !view->guid().startsWith(QLatin1String("sheet:")))
            continue;
        const auto it = byNumber.constFind(view->guid().mid(6));
        if (it == byNumber.constEnd()) {
            closeDrawingTab(i);
            continue;
        }
        QVector<DrawingView::Placed> placed;
        for (const auto& pv : it->value("views").toArray()) {
            const QJsonObject p = pv.toObject();
            placed.push_back({p.value("drawing").toString(),
                QRectF(p.value("x").toDouble(), p.value("y").toDouble(), p.value("w").toDouble(), p.value("h").toDouble())});
        }
        view->setPlaced(placed);
        m_tabs->setTabText(i, tr("Sheet %1").arg(it->value("number").toString()));
        if (changed && !m_generating.contains(view->guid()) && view->hasDrawing()) {
            view->setStale(true); // the model or the sheet changed: compose it again
            if (m_tabs->currentWidget() == view)
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
    statusBar()->showMessage(tr("Sheet %1 exported to %2").arg(number, path));
    return true;
}

void MainWindow::exportSheetDialog(bool pdf)
{
    QString number = m_sheetsPanel->selectedSheet();
    if (auto* view = qobject_cast<DrawingView*>(m_tabs->currentWidget()); view && view->guid().startsWith(QLatin1String("sheet:")))
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
        statusBar()->showMessage(tr("Could not create the roof: %1").arg(r.value("error").toString()));
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
        statusBar()->showMessage(tr("Select a roof and the walls to trim to it"));
        return false;
    }
    const QJsonObject r = bridge("attach_walls_to_roof", {roof,
        QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(walls)).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not trim the walls: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    statusBar()->showMessage(tr("%n wall(s) trimmed to the roof", nullptr, int(walls.size())));
    return true;
}

bool MainWindow::releaseWallsFromRoof(const QStringList& selection)
{
    const QJsonObject r = bridge("detach_walls_from_roof",
        {QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(selection)).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(r.value("error").toString());
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
        statusBar()->showMessage(tr("No room here: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    statusBar()->showMessage(tr("Room: click inside the walls that enclose it"));
    return true;
}

void MainWindow::roomScheduleDialog()
{
    QDialog dialog(this);
    dialog.setObjectName(QStringLiteral("roomScheduleDialog"));
    dialog.setWindowTitle(tr("Room schedule"));
    auto* layout = new QVBoxLayout(&dialog);
    auto* table = new QTableWidget(&dialog);
    table->setObjectName(QStringLiteral("roomScheduleTable"));
    const QStringList headers = {tr("Number"), tr("Name"), tr("Level"), tr("Area (m²)"), tr("Perimeter (m)"), tr("Height (m)")};
    table->setColumnCount(int(headers.size()));
    table->setHorizontalHeaderLabels(headers);
    table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    const QJsonObject data = bridge("room_schedule");
    const QJsonArray rows = data.value("rows").toArray();
    table->setRowCount(int(rows.size()) + 1);
    const QLocale locale;
    for (int i = 0; i < rows.size(); ++i) {
        const QJsonObject r = rows[i].toObject();
        const QStringList cells = {r.value("number").toString(), r.value("name").toString(), r.value("level").toString(),
            locale.toString(r.value("area").toDouble(), 'f', 2), locale.toString(r.value("perimeter").toDouble(), 'f', 2),
            locale.toString(r.value("height").toDouble(), 'f', 2)};
        for (int c = 0; c < cells.size(); ++c)
            table->setItem(i, c, new QTableWidgetItem(cells[c]));
    }
    table->setItem(int(rows.size()), 0, new QTableWidgetItem(tr("Total")));
    table->setItem(int(rows.size()), 3, new QTableWidgetItem(locale.toString(data.value("total_area").toDouble(), 'f', 2)));
    table->horizontalHeader()->setStretchLastSection(true);
    table->resizeColumnsToContents();
    table->setMinimumSize(560, 300);
    layout->addWidget(table);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Close, &dialog);
    QPushButton* csv = buttons->addButton(tr("Export &CSV..."), QDialogButtonBox::ActionRole);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    connect(csv, &QPushButton::clicked, &dialog, [this, &dialog] {
        const QString path = QFileDialog::getSaveFileName(&dialog, tr("Export room schedule"), QStringLiteral("rooms.csv"),
            tr("CSV files (*.csv)"));
        if (path.isEmpty())
            return;
        const QJsonObject r = bridge("export_room_schedule", {path});
        statusBar()->showMessage(r.value("ok").toBool() ? tr("Room schedule saved to %1").arg(path)
                                                        : tr("Could not export it: %1").arg(r.value("error").toString()));
    });
    layout->addWidget(buttons);
    dialog.exec();
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
        statusBar()->showMessage(tr("Could not copy: %1").arg(r.value("error").toString()));
        return false;
    }
    afterCopy(r);
    return true;
}

void MainWindow::copyToClipboard()
{
    m_clipboard = m_selection;
    statusBar()->showMessage(tr("%n element(s) copied", nullptr, int(m_clipboard.size())));
}

bool MainWindow::paste()
{
    if (m_clipboard.isEmpty())
        return false;
    const QJsonObject r = bridge("copy_elements", {jsonList(m_clipboard), QStringLiteral("0"), QStringLiteral("0"),
        QStringLiteral("0"), m_levels->activeStorey()});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not paste: %1").arg(r.value("error").toString()));
        return false;
    }
    afterCopy(r);
    statusBar()->showMessage(tr("Pasted; drag the copies where they go"));
    return true;
}

bool MainWindow::duplicateSelection()
{
    if (m_selection.isEmpty())
        return false;
    const QJsonObject r = bridge("duplicate_elements", {jsonList(m_selection)});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not duplicate: %1").arg(r.value("error").toString()));
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
        statusBar()->showMessage(tr("Could not mirror: %1").arg(r.value("error").toString()));
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
        statusBar()->showMessage(tr("Could not multiply: %1").arg(r.value("error").toString()));
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
        statusBar()->showMessage(tr("Could not offset: %1").arg(r.value("error").toString()));
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
        statusBar()->showMessage(tr("Select what to multiply first"));
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
        statusBar()->showMessage(tr("Select walls or slabs to offset first"));
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
    statusBar()->showMessage(tr("Draw the model here, then place it on levels with Place model (U)"));
    return true;
}

bool MainWindow::placeModelAt(QPointF p, bool turned)
{
    if (m_levels->activeIsModel()) {
        statusBar()->showMessage(tr("Choose a building level to place the model on"));
        return false;
    }
    QJsonObject model = m_tool == Tool::PlaceModel ? currentType() : QJsonObject();
    if (model.isEmpty())
        model = bridge("models").value("models").toArray().first().toObject();
    auto num = [](double v) { return QString::number(v, 'g', 17); };
    const QJsonObject r = bridge("place_model", {model.value("guid").toString(), m_levels->activeStorey(), num(p.x()),
        num(p.y()), num(turned ? M_PI / 2 : 0.0)});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not place it: %1").arg(r.value("error").toString()));
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
        statusBar()->showMessage(tr("There are no models yet"));
        return false;
    }
    const QJsonObject r = bridge("update_model_instances", {guid});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not update: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    statusBar()->showMessage(tr("%n instance(s) updated", nullptr, r.value("count").toInt()));
    return true;
}

bool MainWindow::explodeSelectedInstance()
{
    QString instance;
    for (const QString& g : std::as_const(m_selection))
        if (m_instanceOf.contains(g))
            instance = m_instanceOf.value(g);
    if (instance.isEmpty()) {
        statusBar()->showMessage(tr("Select a placed model first"));
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
        statusBar()->showMessage(tr("Could not create the layer: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    return true;
}

bool MainWindow::assignSelectionToLayer(const QString& layer)
{
    const QJsonObject r = bridge("assign_layer", {jsonList(m_selection), layer});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not change the layer: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    statusBar()->showMessage(tr("%n element(s) moved to %1", nullptr, int(m_selection.size())).arg(layer));
    return true;
}

void MainWindow::setLayerVisible(const QString& layer, bool visible)
{
    if (visible)
        m_hiddenLayers.remove(layer);
    else
        m_hiddenLayers.insert(layer);
    refreshLayers();
}

void MainWindow::setLayerLocked(const QString& layer, bool locked)
{
    if (locked)
        m_lockedLayers.insert(layer);
    else
        m_lockedLayers.remove(layer);
    refreshLayers();
}

bool MainWindow::setActiveLayer(const QString& layer)
{
    const QJsonObject r = bridge("set_active_layer", {layer});
    refreshLayers();
    if (r.value("ok").toBool())
        statusBar()->showMessage(tr("New elements go on layer %1").arg(layer));
    return r.value("ok").toBool();
}

bool MainWindow::saveView(const QString& name)
{
    QJsonObject data{{"hidden", QJsonArray::fromStringList(QStringList(m_hiddenLayers.begin(), m_hiddenLayers.end()))},
        {"locked", QJsonArray::fromStringList(QStringList(m_lockedLayers.begin(), m_lockedLayers.end()))},
        {"level", m_levels->activeStorey()}, {"plan", m_viewport->isPlanView()},
        {"cut", m_planCut->isChecked() ? QJsonValue(m_cutHeight->value()) : QJsonValue()},
        {"linesOnly", m_viewport->linesOnly()}};
    const QJsonObject r = bridge("save_view", {name, QString::fromUtf8(QJsonDocument(data).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        statusBar()->showMessage(tr("Could not save the view: %1").arg(r.value("error").toString()));
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
        refreshLayers();
        statusBar()->showMessage(tr("View %1").arg(name));
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
    m_hiddenLayers.clear();
    m_lockedLayers.clear();
    m_currentView.clear();
    refreshProject();
    refreshLayers();
    refreshAnnotations();
    refreshDrawings();
    refreshSheets();
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
