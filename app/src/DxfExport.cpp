// SPDX-License-Identifier: GPL-3.0-or-later
// DXF export (D83): File > Export DXF... A MainWindow member kept in its own file; the export itself runs
// in Python (kimcad.dxf), one file per drawing or sheet, on the dialog's worker thread.
#include "MainWindow.h"

#include "DxfExportDialog.h"
#include "PythonEngine.h"
#include "StatusStrip.h"

#include <QDir>
#include <QFileInfo>
#include <QStandardPaths>

namespace kimcad {

void MainWindow::exportDxfDialog()
{
    const QJsonObject targets = bridge("dxf_targets");
    if (targets.value("drawings").toArray().isEmpty() && targets.value("sheets").toArray().isEmpty()) {
        showError(tr("Nothing to export"), tr("The model has no drawings or sheets yet."));
        return;
    }
    DxfExportDialog dialog(targets, [](const char* fn, const QStringList& args) {
        QString error;
        QJsonObject r = PythonEngine::instance().callJson(fn, args, &error).object();
        if (r.isEmpty())
            r = QJsonObject{{"ok", false}, {"error", error}};
        return r;
    }, this);
    const QString base = m_path.isEmpty()
        ? QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation)
        : QFileInfo(m_path).absolutePath();
    dialog.setFolder(QDir::toNativeSeparators(QDir(base).filePath(QStringLiteral("DXF"))));
    // The recovery copy waits while the files are written (it would only queue behind the GIL).
    m_recoveryTimer.stop();
    connect(&dialog, &DxfExportDialog::finished, this, [this](const QStringList& files, const QStringList& errors) {
        if (errors.isEmpty() && !files.isEmpty())
            m_status->showMessage(tr("Exported %n DXF file(s)", nullptr, int(files.size())));
    });
    dialog.exec();
    restartRecoveryTimer();
}

} // namespace kimcad
