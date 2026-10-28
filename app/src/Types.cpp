// SPDX-License-Identifier: GPL-3.0-or-later
// M2: the type manager and classifications dialogs; they edit the open model through the Python
// bridge and the window applies the result like any other edit.
#include "MainWindow.h"

#include "ClassificationsDialog.h"
#include "StatusStrip.h"
#include "TypeManagerDialog.h"

#include <QInputDialog>
#include <QJsonArray>
#include <QJsonDocument>
#include <QMessageBox>

namespace {
QString guidsJson(const QStringList& list)
{
    return QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(list)).toJson(QJsonDocument::Compact));
}
} // namespace

namespace kimbim {

void MainWindow::openTypeManager()
{
    TypeManagerDialog dialog(m_selection, this);
    connect(&dialog, &TypeManagerDialog::changed, this, [this] { afterEdit(); });
    dialog.exec();
}

bool MainWindow::addSlabEdges()
{
    if (m_selection.isEmpty())
        return false;
    QJsonObject result;
    for (const QString& guid : m_selection) {
        const QJsonObject r = bridge("add_slab_edge", {guid, QStringLiteral("0.02"), QStringLiteral("0.2")});
        if (!r.value("ok").toBool())
            result = r;
    }
    if (!result.isEmpty()) {
        m_status->showMessage(tr("Slab edge: %1").arg(result.value("error").toString()));
        return false;
    }
    afterEdit();
    m_status->showMessage(tr("Slab edges added"));
    return true;
}

void MainWindow::slabSlopeDialog()
{
    bool ok = false;
    const double sx = QInputDialog::getDouble(this, tr("Slab slope"), tr("Rise over run along X:"),
                                              0.0, -5.0, 5.0, 3, &ok);
    if (!ok)
        return;
    const double sy = QInputDialog::getDouble(this, tr("Slab slope"), tr("Rise over run along Y:"),
                                              0.0, -5.0, 5.0, 3, &ok);
    if (!ok)
        return;
    const QJsonObject r = bridge("set_slab_slope", {guidsJson(m_selection), QString::number(sx), QString::number(sy)});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not slope the slab: %1").arg(r.value("error").toString()));
        return;
    }
    afterEdit();
    m_status->showMessage(tr("Slab slope applied"));
}

void MainWindow::openClassifications()
{
    ClassificationsDialog dialog(m_selection, this);
    connect(&dialog, &ClassificationsDialog::changed, this, [this] { afterEdit(); });
    dialog.exec();
}

} // namespace kimbim
