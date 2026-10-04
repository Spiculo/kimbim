// SPDX-License-Identifier: GPL-3.0-or-later
#include "MainWindow.h"

#include <QApplication>
#include <QMenuBar>
#include <QMessageBox>
#include <QStatusBar>

namespace kimcad {

MainWindow::MainWindow(QWidget* parent)
    : QMainWindow(parent)
{
    setWindowTitle(QStringLiteral("KIMCAD"));
    resize(1280, 800);
    buildMenus();
    statusBar()->showMessage(tr("Ready"));
}

void MainWindow::buildMenus()
{
    QMenu* file = menuBar()->addMenu(tr("&File"));
    QAction* open = file->addAction(tr("&Open IFC..."));
    open->setShortcut(QKeySequence::Open);
    file->addSeparator();
    QAction* quit = file->addAction(tr("&Quit"));
    quit->setShortcut(QKeySequence::Quit);
    connect(quit, &QAction::triggered, qApp, &QApplication::quit);

    QMenu* view = menuBar()->addMenu(tr("&View"));
    QAction* fit = view->addAction(tr("&Fit all"));
    fit->setShortcut(Qt::Key_F);

    QMenu* help = menuBar()->addMenu(tr("&Help"));
    QAction* about = help->addAction(tr("&About KIMCAD"));
    connect(about, &QAction::triggered, this, &MainWindow::showAbout);
}

void MainWindow::showAbout()
{
    QMessageBox::about(this, tr("About KIMCAD"),
        tr("KIMCAD %1\nOpen-source native BIM for architects, with version control built in.\n"
           "License: GPL-3.0-or-later")
            .arg(QStringLiteral(KIMCAD_VERSION)));
}

} // namespace kimcad
