// SPDX-License-Identifier: GPL-3.0-or-later
// D86: the object library in the main window (doc 14 §8): the Library panel and the Object tool.
// The objects, their types and plan symbols are python/kimbim/library.py's; one undo step each.
// D100: each object's current version (the last one used, a project setting) is what a click places.
#include <QAction>
#include <QCheckBox>
#include <QComboBox>
#include <QFileDialog>
#include <QInputDialog>
#include <QJsonArray>
#include <QJsonDocument>
#include <QMenu>
#include <QMessageBox>
#include <QPushButton>

#include <cmath>

#include "DockLayout.h"
#include "LevelsBar.h"
#include "LibraryPanel.h"
#include "MainWindow.h"
#include "ObjectSettingsDialog.h"
#include "Snapper.h"
#include "StatusStrip.h"
#include "TwoPointTool.h"
#include "Viewport.h"
#include "WallTool.h"

namespace kimbim {

namespace {

QString compactJson(const QJsonObject& o)
{
    return QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Compact));
}

QString num(double v)
{
    return QString::number(v, 'g', 17);
}

QJsonObject merged(QJsonObject base, const QJsonObject& over)
{
    for (auto it = over.begin(); it != over.end(); ++it)
        base.insert(it.key(), it.value());
    return base;
}

const QString kCustomItem = QStringLiteral("#custom"); // the Version dropdown's Custom entry

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
    if (m_library) {
        m_library->setListing(bridge("library_objects"));
        refreshObjectLabels();
    }
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
    refreshObjectLabels();
    connect(m_library, &LibraryPanel::placeRequested, this, [this] { setTool(Tool::Object); });
    connect(m_library, &LibraryPanel::settingsRequested, this, [this](const QString& id) { objectSettingsDialog(id); });
    connect(m_library, &LibraryPanel::currentChanged, this, [this] {
        loadObjectVersion();
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
    if (!libraryPanel()->selectObject(id))
        return false;
    setObjectVersion(id, QString(), params);
    setTool(Tool::Object);
    return m_tool == Tool::Object;
}

QJsonObject MainWindow::versionEntry(const QString& id) const
{
    if (id.isEmpty())
        return {};
    for (const auto& v : m_objectVersions.value("versions").toArray())
        if (v.toObject().value("id").toString() == id)
            return v.toObject();
    return {};
}

QString MainWindow::objectVersionName(const QJsonObject& last, const QJsonArray& versions) const
{
    if (last.contains(QStringLiteral("values")))
        return tr("Custom");
    const QString id = last.value("version").toString();
    if (!id.isEmpty())
        for (const auto& v : versions)
            if (v.toObject().value("id").toString() == id)
                return v.toObject().value("name").toString();
    return {}; // the Default
}

void MainWindow::loadObjectVersion()
{
    m_objectVersion.clear();
    m_objectCustom = false;
    m_objectValues = QJsonObject();
    m_objectVersions = QJsonObject();
    const QString key = m_library ? m_library->currentObject() : QString();
    if (!key.isEmpty()) {
        m_objectVersions = bridge("object_versions", {key}); // fails for an office IFC type: no versions
        m_objectValues = m_objectVersions.value("default").toObject();
        const QJsonObject last = m_objectVersions.value("last").toObject();
        if (last.contains(QStringLiteral("values"))) {
            m_objectCustom = true;
            m_objectValues = last.value("values").toObject();
        } else if (const QJsonObject v = versionEntry(last.value("version").toString()); !v.isEmpty()) {
            m_objectVersion = v.value("id").toString();
            m_objectValues = v.value("values").toObject();
        }
    }
    showObjectVersion();
}

void MainWindow::setObjectVersion(const QString& key, const QString& versionId, const QJsonObject& customValues)
{
    LibraryPanel* panel = libraryPanel();
    if (panel->currentObject() != key && !panel->selectObject(key))
        return;
    m_objectVersions = bridge("object_versions", {key}); // fresh: the dialog may have saved some
    QJsonObject last;
    if (!customValues.isEmpty()) {
        m_objectCustom = true;
        m_objectVersion.clear();
        m_objectValues = customValues;
        last.insert(QStringLiteral("values"), customValues);
    } else {
        const QJsonObject v = versionEntry(versionId);
        m_objectCustom = false;
        m_objectVersion = v.value("id").toString(); // "": the Default (or a version no longer there)
        m_objectValues = v.isEmpty() ? m_objectVersions.value("default").toObject() : v.value("values").toObject();
        last.insert(QStringLiteral("version"), m_objectVersion);
    }
    if (m_objectVersions.value("ok").toBool()) { // remembered per object, per project (not an undo step)
        const QJsonObject r = bridge("set_last_used", {key, compactJson(last)});
        if (r.value("ok").toBool()) {
            m_settings = r.value("settings").toObject();
            setWindowModified(isDirty());
        }
    }
    showObjectVersion();
    if (m_tool == Tool::Object)
        updateToolPreview();
}

void MainWindow::showObjectVersion()
{
    const QString key = m_library ? m_library->currentObject() : QString();
    if (m_library && !key.isEmpty())
        m_library->setVersionLabel(key, m_objectCustom ? tr("Custom") : versionEntry(m_objectVersion).value("name").toString());
    if (!m_objectVersionCombo)
        return;
    const QSignalBlocker block(m_objectVersionCombo);
    m_objectVersionCombo->clear();
    m_objectVersionCombo->setEnabled(m_objectVersions.value("ok").toBool());
    if (key.isEmpty())
        return;
    m_objectVersionCombo->addItem(tr("Default"), QString());
    if (m_objectCustom)
        m_objectVersionCombo->addItem(tr("Custom"), kCustomItem);
    bool office = false;
    for (const auto& v : m_objectVersions.value("versions").toArray()) {
        const QJsonObject o = v.toObject();
        if (o.value("source").toString() == QLatin1String("office") && !office) {
            office = true;
            m_objectVersionCombo->insertSeparator(m_objectVersionCombo->count());
        }
        m_objectVersionCombo->addItem(o.value("name").toString(), o.value("id").toString());
    }
    const int i = m_objectVersionCombo->findData(m_objectCustom ? kCustomItem : m_objectVersion);
    m_objectVersionCombo->setCurrentIndex(std::max(0, i));
}

void MainWindow::refreshObjectLabels()
{
    if (!m_library)
        return;
    const QJsonObject table = m_settings.value("object_last_used").toObject();
    for (const QString& id : m_library->objectIds()) {
        const QJsonObject last = table.value(id).toObject();
        QString label;
        if (last.contains(QStringLiteral("values")))
            label = tr("Custom");
        else if (!last.value("version").toString().isEmpty()) { // its name (or the Default: gone)
            const QJsonObject r = bridge("object_versions", {id});
            label = objectVersionName(r.value("last").toObject(), r.value("versions").toArray());
        }
        m_library->setVersionLabel(id, label);
    }
}

void MainWindow::fillObjectVersionMenu(QMenu* menu)
{
    menu->clear();
    const QString key = m_library ? m_library->currentObject() : QString();
    if (key.isEmpty())
        return;
    const auto add = [this, menu, key](const QString& text, const QString& id, bool checked) {
        QAction* a = menu->addAction(text);
        a->setCheckable(true);
        a->setChecked(checked);
        connect(a, &QAction::triggered, this, [this, key, id] { setObjectVersion(key, id); });
    };
    add(tr("Default"), QString(), !m_objectCustom && m_objectVersion.isEmpty());
    if (m_objectCustom) { // the values last placed: already what a click places
        QAction* custom = menu->addAction(tr("Custom"));
        custom->setCheckable(true);
        custom->setChecked(true);
    }
    bool office = false;
    for (const auto& v : m_objectVersions.value("versions").toArray()) {
        const QJsonObject o = v.toObject();
        if (o.value("source").toString() == QLatin1String("office") && !office) {
            office = true;
            menu->addSection(tr("Office library"));
        }
        add(o.value("name").toString(), o.value("id").toString(), !m_objectCustom && o.value("id").toString() == m_objectVersion);
    }
    menu->addSeparator();
    QAction* settings = menu->addAction(tr("Settings..."));
    connect(settings, &QAction::triggered, this, [this, key] { objectSettingsDialog(key); });
}

bool MainWindow::objectSettingsDialog(const QString& key)
{
    if (key.isEmpty())
        return false;
    ObjectSettingsDialog d(this, key, ObjectSettingsDialog::Mode::Place, this);
    const QJsonObject last = m_library && m_library->currentObject() == key
        ? (m_objectCustom ? QJsonObject{{"values", m_objectValues}} : QJsonObject{{"version", m_objectVersion}})
        : bridge("object_versions", {key}).value("last").toObject();
    if (last.contains(QStringLiteral("values")))
        d.setValues(last.value("values").toObject());
    else if (!last.value("version").toString().isEmpty())
        d.selectVersion(last.value("version").toString());
    const bool placed = d.exec() == QDialog::Accepted;
    refreshObjectLabels(); // versions renamed or deleted in the dialog
    if (m_library && m_library->currentObject() == key)
        loadObjectVersion();
    if (!placed)
        return false;
    QJsonObject custom;
    if (d.versionId().isEmpty()) { // the Default, or unsaved values (Custom)
        const QJsonObject values = d.values();
        if (values != bridge("object_versions", {key}).value("default").toObject())
            custom = values;
    }
    setObjectVersion(key, d.versionId(), custom);
    setTool(Tool::Object);
    return true;
}

bool MainWindow::editObjectSettings()
{
    if (m_selection.isEmpty())
        return false;
    const QString guids = QString::fromUtf8(QJsonDocument(QJsonArray::fromStringList(m_selection)).toJson(QJsonDocument::Compact));
    const QJsonObject of = bridge("object_settings_of", {guids});
    if (!of.value("ok").toBool()) {
        m_status->showMessage(tr("Could not edit the objects") + QStringLiteral(": ") + of.value("error").toString());
        return false;
    }
    const QString key = of.value("key").toString();
    const QString version = of.value("version").toString(); // "" for an unnamed type
    const QJsonObject values = of.value("values").toObject();
    ObjectSettingsDialog d(this, key, ObjectSettingsDialog::Mode::Edit, this);
    d.selectVersion(version); // highlighted in the list
    if (version.isEmpty() || d.versionId() != version)
        d.setValues(values); // the type's own values
    const bool accepted = d.exec() == QDialog::Accepted;
    refreshObjectLabels(); // versions renamed or deleted in the dialog
    if (m_library && m_library->currentObject() == key)
        loadObjectVersion();
    if (!accepted)
        return false;
    const QString picked = d.versionId();
    if (picked.isEmpty() ? d.values() == values : picked == version)
        return false; // nothing changed
    QJsonObject r;
    if (!picked.isEmpty()) {
        r = bridge("assign_version", {guids, picked}); // another saved version: the selection moves to it
    } else {
        const QString params = compactJson(d.values());
        r = bridge("apply_object_settings", {guids, params, QStringLiteral("auto")});
        if (!r.value("ok").toBool() && r.value("shared").toBool()) { // others use the type too: ask
            QString mode = m_editChoice;
            QString name = m_editChoiceName;
            const int uses = of.value("uses").toInt();
            if (!m_quiet) {
                QMessageBox box(QMessageBox::Question, tr("Change the object's type"),
                    tr("%n object(s) use this type; %1 of them are selected.", nullptr, uses).arg(of.value("selected").toInt()),
                    QMessageBox::NoButton, this);
                QPushButton* all = box.addButton(tr("Modify all %n objects of this type", nullptr, uses), QMessageBox::AcceptRole);
                QPushButton* create = box.addButton(tr("Create a new type..."), QMessageBox::AcceptRole);
                box.addButton(QMessageBox::Cancel);
                box.setDefaultButton(create);
                box.exec();
                mode = box.clickedButton() == all ? QStringLiteral("all")
                    : box.clickedButton() == create ? QStringLiteral("new")
                                                    : QString();
                name.clear();
            }
            if (mode == QLatin1String("all")) {
                r = bridge("apply_object_settings", {guids, params, mode});
            } else if (mode == QLatin1String("new")) {
                for (;;) { // a name the object has already: ask again
                    if (!m_quiet) {
                        bool ok = false;
                        name = QInputDialog::getText(this, tr("Create a new type"),
                            tr("Name of the new type (only the selected objects move to it):"), QLineEdit::Normal, name, &ok);
                        if (!ok)
                            return false;
                        if (name.trimmed().isEmpty())
                            continue;
                    }
                    r = bridge("apply_object_settings", {guids, params, mode, name});
                    if (r.value("ok").toBool() || !r.contains("exists") || m_quiet)
                        break;
                    QMessageBox::information(this, tr("Create a new type"),
                        tr("There is already a version called %1. Choose another name.").arg(name.trimmed()));
                }
            } else {
                return false; // cancelled
            }
        }
    }
    if (!r.value("ok").toBool()) {
        showError(tr("Could not change the objects"), r.value("error").toString());
        return false;
    }
    afterEdit(r);
    return true;
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

std::optional<MainWindow::ObjectFit> MainWindow::fitObjectToWall(QPointF p, double width, double depth) const
{
    // D97: the nearest wall face the cursor is in front of (within reach), the object's back against it,
    // its middle where the cursor is along the wall (front at y = 0, origin the left front corner).
    if (!m_objectFit || !m_objectFit->isChecked() || !m_wallTool)
        return std::nullopt;
    const double reach = std::max(0.6, depth);
    std::optional<ObjectFit> best;
    double bestDistance = reach;
    for (const SnapWall& w : m_wallTool->snapper().walls()) {
        if (w.arc)
            continue; // D97: a curved wall's face is no line to stand against
        const QPointF d = w.b - w.a;
        const double len = std::hypot(d.x(), d.y());
        if (len < 1e-9)
            continue;
        const QPointF along = d / len, left(-along.y(), along.x());
        for (const double side : {1.0, -1.0}) { // the face on the axis' left, then on its right
            const QPointF out = left * side; // away from the wall body
            const QPointF face = w.a + left * (w.centre + side * w.thickness / 2);
            const QPointF v = p - face;
            const double t = v.x() * along.x() + v.y() * along.y();
            const double dist = v.x() * out.x() + v.y() * out.y();
            if (t < 0 || t > len || dist < -0.02 || dist > bestDistance)
                continue;
            bestDistance = dist;
            const QPointF uy = -out; // the back faces the wall
            const QPointF ux(uy.y(), -uy.x());
            const QPointF onFace = face + along * t;
            ObjectFit fit;
            fit.origin = onFace - ux * (width / 2) - uy * depth;
            fit.angle = std::atan2(ux.y(), ux.x()) * 180.0 / M_PI;
            best = fit;
        }
    }
    return best;
}

bool MainWindow::placeObjectAt(QPointF p, bool turned)
{
    LibraryPanel* panel = libraryPanel();
    if (panel->currentObject().isEmpty()) {
        m_status->showMessage(tr("Pick an object in the Library panel first"));
        m_dock->raisePanel(QStringLiteral("library"));
        return false;
    }
    double angle = (m_objectAngle + (turned ? 90.0 : 0.0)) * M_PI / 180.0;
    const QJsonObject info = panel->currentInfo(merged(m_objectVersions.value("default").toObject(), m_objectValues));
    const double width = info.value("width").toDouble(1.0);
    if (const auto fit = fitObjectToWall(p, width, info.value("depth").toDouble(width))) {
        p = fit->origin;
        angle = fit->angle * M_PI / 180.0;
    }
    // D100: a saved (or office) version places its own type; Custom values an unnamed type (D99).
    const QString key = panel->currentObject();
    const QString version = currentObjectVersion();
    const QJsonObject custom = m_objectCustom ? m_objectValues : QJsonObject();
    const QJsonObject r = bridge("place_object", {m_levels->activeStorey(), key, compactJson(custom),
        num(p.x()), num(p.y()), num(angle),
        m_objectGravity && m_objectGravity->isChecked() ? QStringLiteral("1") : QString(), version});
    if (!r.value("ok").toBool()) {
        m_status->showMessage(tr("Could not place it: %1").arg(r.value("error").toString()));
        return false;
    }
    afterEdit(r);
    setObjectVersion(key, version, custom); // the last used (an office version is now the project's too)
    m_status->showMessage(tr("%1 placed").arg(panel->currentName()));
    return true;
}

void MainWindow::updateObjectPreview()
{
    QVector<Viewport::PreviewBox> boxes;
    if (m_objectHover && m_library && !m_library->currentObject().isEmpty()) {
        const QJsonObject info = m_library->currentInfo(merged(m_objectVersions.value("default").toObject(), m_objectValues));
        const double w = info.value("width").toDouble(1.0), d = info.value("depth").toDouble(w);
        const double h = info.value("height").toDouble(1.0), z = m_levels->activeElevation();
        double a = m_objectAngle * M_PI / 180.0;
        QPointF origin = *m_objectHover;
        if (const auto fit = fitObjectToWall(origin, w, d)) { // D97: against the wall
            origin = fit->origin;
            a = fit->angle * M_PI / 180.0;
        }
        const QPointF ux(std::cos(a), std::sin(a)), uy(-std::sin(a), std::cos(a));
        const QPointF mid = origin + uy * (d / 2); // the plan box: along x through its middle
        boxes.push_back({mid, mid + ux * w, d, z, z + h});
    }
    m_viewport->setPreviewBoxes(boxes);
}

} // namespace kimbim
