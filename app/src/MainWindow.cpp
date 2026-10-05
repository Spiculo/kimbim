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
#include <QInputDialog>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLineEdit>
#include <QJsonObject>
#include <QMenuBar>
#include <QMessageBox>
#include <QStatusBar>

#include "Cuts.h"
#include "ElementBatch.h"
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
    connect(m_undo, &QAction::triggered, this, [this] {
        bridge("undo");
        afterEdit();
    });
    m_redo = editMenu->addAction(tr("&Redo"));
    m_redo->setObjectName(QStringLiteral("actionRedo"));
    m_redo->setShortcuts({QKeySequence(Qt::CTRL | Qt::Key_Y), QKeySequence(Qt::CTRL | Qt::SHIFT | Qt::Key_Z)});
    m_redo->setEnabled(false);
    connect(m_redo, &QAction::triggered, this, [this] {
        bridge("redo");
        afterEdit();
    });

    QMenu* view = menuBar()->addMenu(tr("&View"));
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
    state.height = m_cutHeight->value();
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
    afterEdit();
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

void MainWindow::afterEdit()
{
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
