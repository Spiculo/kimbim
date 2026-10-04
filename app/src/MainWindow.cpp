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
        if (guids.isEmpty()) {
            m_properties->clear();
            return;
        }
        m_tree->selectGuid(guids.first());
        showPropertiesOf(guids.first());
    });
    connect(m_tree, &ModelTreePanel::guidsSelected, this, [this](const QStringList& guids) {
        m_viewport->selectGuids(guids);
        if (!guids.isEmpty())
            showPropertiesOf(guids.first());
    });
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
    file->addSeparator();
    QAction* quit = file->addAction(tr("&Quit"));
    quit->setShortcut(QKeySequence::Quit);
    connect(quit, &QAction::triggered, this, &QWidget::close);

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
    resizeDocks({treeDock, propsDock}, {300, 320}, Qt::Horizontal);
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
    stopLoading();
    event->accept();
}

void MainWindow::showPropertiesOf(const QString& guid)
{
    QString error;
    const QJsonObject props = PythonEngine::instance().callJson("properties", {guid}, &error).object();
    m_properties->showProperties(props.isEmpty() ? QJsonObject{{"error", error}} : props);
}

void MainWindow::onOpened(const QJsonObject& info)
{
    setWindowTitle(QStringLiteral("KIMCAD — %1").arg(QFileInfo(m_path).fileName()));
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
