// SPDX-License-Identifier: GPL-3.0-or-later
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

#include <QInputDialog>
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
#include "LevelsBar.h"
#include "WallTool.h"
#include "MeshChunk.h"
#include "ModelLoader.h"
#include "ModelTreePanel.h"
#include "PropertiesPanel.h"
#include "PythonEngine.h"
#include "Viewport.h"

namespace kimcad {

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
    QAction* saveAction = file->addAction(tr("&Save"));
    saveAction->setObjectName(QStringLiteral("actionSave"));
    saveAction->setShortcut(QKeySequence::Save);
    connect(saveAction, &QAction::triggered, this, [this] { save(); });
    QAction* saveAs = file->addAction(tr("Save &As..."));
    saveAs->setObjectName(QStringLiteral("actionSaveAs"));
    saveAs->setShortcut(QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_S));
    connect(saveAs, &QAction::triggered, this, &MainWindow::saveAsDialog);
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
    m_wallTypes->clear();
    setWindowTitle(QStringLiteral("KIMCAD — %1[*]").arg(tr("Untitled")));
    afterEdit();
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
    m_wallTool = new WallTool(this);
    m_wallAction = bar->addAction(tr("&Wall"));
    m_wallAction->setObjectName(QStringLiteral("actionWallTool"));
    m_wallAction->setShortcut(Qt::Key_W);
    m_wallAction->setCheckable(true);
    m_wallAction->setToolTip(tr("Draw walls: click points, type a length + Enter, Esc to finish. Shift: right angles."));
    connect(m_wallAction, &QAction::toggled, this, &MainWindow::setWallToolActive);
    m_wallTypes = new QComboBox(bar);
    m_wallTypes->setObjectName(QStringLiteral("wallTypeCombo"));
    m_wallTypes->setToolTip(tr("Wall type"));
    m_wallTypes->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    m_wallTypes->setMinimumContentsLength(14);
    bar->addWidget(m_wallTypes);
    m_wallHeight = new QDoubleSpinBox(bar);
    m_wallHeight->setObjectName(QStringLiteral("wallHeight"));
    m_wallHeight->setRange(0.1, 100.0);
    m_wallHeight->setDecimals(2);
    m_wallHeight->setSingleStep(0.1);
    m_wallHeight->setValue(3.0);
    m_wallHeight->setSuffix(QStringLiteral(" m"));
    m_wallHeight->setToolTip(tr("Wall height"));
    bar->addWidget(m_wallHeight);
    m_lengthInput = new QLineEdit(bar);
    m_lengthInput->setObjectName(QStringLiteral("lengthInput"));
    m_lengthInput->setPlaceholderText(tr("Length (m)"));
    m_lengthInput->setMaximumWidth(110);
    bar->addWidget(m_lengthInput);
    connect(m_lengthInput, &QLineEdit::returnPressed, this, [this] {
        bool ok = false;
        double value = QLocale().toDouble(m_lengthInput->text(), &ok);
        if (!ok)
            value = QLocale::c().toDouble(QString(m_lengthInput->text()).replace(QLatin1Char(','), QLatin1Char('.')), &ok);
        if (ok && m_wallTool->typeLength(value))
            m_lengthInput->clear();
        m_viewport->setFocus();
    });

    connect(m_viewport, &Viewport::workPointMoved, this, [this](QPointF p, double tolerance, Qt::KeyboardModifiers mods) {
        m_wallTool->setTolerance(tolerance);
        m_wallTool->setOrtho(mods & Qt::ShiftModifier);
        showSnap(m_wallTool->move(p));
    });
    connect(m_viewport, &Viewport::workPointClicked, this, [this](QPointF p, double tolerance, Qt::KeyboardModifiers mods) {
        m_wallTool->setTolerance(tolerance);
        m_wallTool->setOrtho(mods & Qt::ShiftModifier);
        m_wallTool->click(p);
    });
    connect(m_viewport, &Viewport::drawingEnded, this, [this] {
        if (m_wallTool->isDrawing())
            m_wallTool->finish();
        else
            m_wallAction->setChecked(false);
    });
    connect(m_viewport, &Viewport::lengthKeyTyped, this, [this](const QString& text) {
        m_lengthInput->setFocus();
        m_lengthInput->insert(text);
    });
    connect(m_wallTool, &WallTool::previewChanged, this, [this] {
        const QJsonObject type = m_wallTypes->currentData().toJsonObject();
        m_viewport->setWallPreview(m_wallTool->preview(), type.value("thickness").toDouble(), m_wallHeight->value());
    });
    connect(m_wallTool, &WallTool::wallRequested, this, &MainWindow::createWall);
}

void MainWindow::refreshWallTypes()
{
    const QString current = m_wallTypes->currentData().toJsonObject().value("guid").toString();
    m_wallTypes->clear();
    for (const auto& t : bridge("wall_types").value("types").toArray()) {
        const QJsonObject o = t.toObject();
        m_wallTypes->addItem(o.value("name").toString(), o);
        if (o.value("guid").toString() == current)
            m_wallTypes->setCurrentIndex(m_wallTypes->count() - 1);
    }
}

void MainWindow::refreshSnapData()
{
    m_wallTool->snapper().setWalls(Snapper::parse(bridge("snap_data", {m_levels->activeStorey()})));
}

void MainWindow::showSnap(const Snap& snap)
{
    static const char* const names[] = {"", QT_TR_NOOP("endpoint"), QT_TR_NOOP("midpoint"), QT_TR_NOOP("perpendicular"),
        QT_TR_NOOP("on wall"), QT_TR_NOOP("angle"), QT_TR_NOOP("grid")};
    QString text = tr("Wall: click the next point, type a length, Esc to finish");
    if (const auto preview = m_wallTool->preview()) {
        const QPointF d = preview->second - preview->first;
        text = tr("Length %1 m").arg(QLocale().toString(std::hypot(d.x(), d.y()), 'f', 3));
    }
    if (snap.kind != Snap::None)
        text += QStringLiteral("  ·  ") + tr(names[snap.kind]);
    statusBar()->showMessage(text);
}

void MainWindow::setWallToolActive(bool on)
{
    if (m_wallAction->isChecked() != on) {
        m_wallAction->setChecked(on); // re-enters through toggled
        return;
    }
    if (on) {
        if (m_levels->activeStorey().isEmpty()) {
            m_wallAction->setChecked(false);
            showError(tr("Cannot draw walls"), tr("The model has no level. Add a level first."));
            return;
        }
        if (m_wallTypes->count() == 0)
            refreshWallTypes();
        refreshSnapData();
        m_viewport->setDrawingMode(true, m_levels->activeElevation());
        m_viewport->setFocus();
        statusBar()->showMessage(tr("Wall: click the start point"));
    } else {
        m_wallTool->finish();
        m_viewport->setDrawingMode(false);
        statusBar()->clearMessage();
    }
}

bool MainWindow::createWall(const WallSegment& s)
{
    const QJsonObject type = m_wallTypes->currentData().toJsonObject();
    auto num = [](double v) { return QString::number(v, 'g', 17); };
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
        if (!fetchElementMeshes(PythonEngine::instance(), changed, &chunk, &none, &error))
            showError(tr("Could not update the 3D view"), error);
        else if (!none)
            m_viewport->replaceElements(chunk);
    }
    m_tree->refreshTree(bridge("spatial_tree")); // elements can appear or disappear
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
    applyGeometry(result.value("geometry").toObject());
    refreshLevels();
    if (m_viewport->isDrawingMode())
        refreshSnapData(); // undo/redo can add or remove walls under the tool
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
    m_wallTypes->clear();
    m_undo->setEnabled(false);
    m_redo->setEnabled(false);
    QString error;
    const QJsonObject tree = PythonEngine::instance().callJson("spatial_tree", {}, &error).object();
    m_tree->setTree(tree);
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
