// SPDX-License-Identifier: GPL-3.0-or-later
#include "ObjectSettingsDialog.h"

#include "LibraryPanel.h"
#include "MainWindow.h"
#include "MeshChunk.h"
#include "PythonEngine.h"
#include "Viewport.h"

#include <QButtonGroup>
#include <QCheckBox>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QInputDialog>
#include <QJsonDocument>
#include <QLabel>
#include <QListWidget>
#include <QMenu>
#include <QMessageBox>
#include <QPainter>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QStackedWidget>
#include <QTimer>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>

namespace kimbim {

namespace {

enum { IdRole = Qt::UserRole + 1, SourceRole };

QString compact(const QJsonObject& o)
{
    return QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Compact));
}

const char* const kInvalidStyle = "background-color: #f8d7da; border: 1px solid #c0392b;";

} // namespace

// ---------------------------------------------------------------- ParameterForm

ParameterForm::ParameterForm(QWidget* parent)
    : QWidget(parent)
    , m_form(new QFormLayout(this))
{
    m_form->setContentsMargins(0, 0, 0, 0);
}

void ParameterForm::setObject(const QString& key, const QJsonObject& values, const QString& version)
{
    m_key = key;
    m_version = version;
    m_values = values;
    build();
}

void ParameterForm::setValues(const QJsonObject& values)
{
    for (auto it = values.begin(); it != values.end(); ++it)
        m_values.insert(it.key(), it.value());
    build();
}

void ParameterForm::markInvalid(const QString& key, const QString& reason)
{
    for (QWidget* field : findChildren<QWidget*>()) {
        if (!field->objectName().startsWith(QLatin1String("param_")))
            continue;
        const bool bad = !reason.isEmpty() && field->objectName() == QLatin1String("param_") + key;
        field->setStyleSheet(bad ? QString::fromLatin1(kInvalidStyle) : QString());
        field->setToolTip(bad ? reason : QString());
    }
}

void ParameterForm::edited(const QString& key, const QJsonValue& value, bool rebuild)
{
    m_values.insert(key, value);
    if (rebuild) // show_when and limits may change
        QMetaObject::invokeMethod(this, &ParameterForm::build, Qt::QueuedConnection);
    emit changed(key);
}

void ParameterForm::build()
{
    while (m_form->rowCount() > 0)
        m_form->removeRow(0);
    m_rows = 0;
    if (m_key.isEmpty())
        return;
    // D99: limits that are formulas and show_when depend on the current values, so Python makes the form.
    const QJsonObject form = PythonEngine::instance().callJson("object_form", {m_key, compact(m_values), m_version}).object();
    // the values as the definition reads them (every parameter; out-of-range ones clamped)
    const QJsonObject clean = form.value("values").toObject();
    for (auto it = clean.begin(); it != clean.end(); ++it)
        if (!m_values.contains(it.key()))
            m_values.insert(it.key(), it.value());
    QString group;
    QLabel* heading = nullptr;
    bool headingShown = false;
    auto closeGroup = [&] {
        if (heading)
            m_form->setRowVisible(heading, headingShown);
    };
    for (const auto& v : form.value("params").toArray()) {
        const QJsonObject p = v.toObject();
        const QString key = p.value("key").toString(), kind = p.value("kind").toString();
        const bool visible = p.value("visible").toBool(true);
        if (p.value("group").toString() != group) { // the definition's group headings
            closeGroup();
            group = p.value("group").toString();
            heading = nullptr;
            headingShown = false;
            if (!group.isEmpty()) {
                heading = new QLabel(LibraryPanel::translated(group, p.value("group_es").toString()), this);
                heading->setObjectName(QStringLiteral("paramGroup"));
                QFont bold = heading->font();
                bold.setBold(true);
                heading->setFont(bold);
                m_form->addRow(heading);
            }
        }
        headingShown = headingShown || visible;
        const QJsonValue value = m_values.contains(key) ? m_values.value(key) : p.value("value");
        QWidget* field = nullptr;
        if (kind == QLatin1String("material")) { // D97: a part's building material
            auto* combo = new QComboBox(this);
            for (const auto& c : p.value("choices").toArray())
                combo->addItem(c.toString());
            combo->setCurrentText(value.toString());
            connect(combo, &QComboBox::currentTextChanged, this, [this, key](const QString& name) { edited(key, name, false); });
            field = combo;
        } else if (kind == QLatin1String("choice")) {
            auto* combo = new QComboBox(this);
            for (const auto& c : p.value("options").toArray()) {
                const QJsonObject opt = c.toObject();
                combo->addItem(LibraryPanel::translated(opt.value("label").toString(), opt.value("label_es").toString()),
                    opt.value("id").toString());
            }
            combo->setCurrentIndex(std::max(0, combo->findData(value.toString())));
            connect(combo, &QComboBox::currentIndexChanged, this, [this, combo, key](int i) {
                edited(key, combo->itemData(i).toString(), true);
            });
            field = combo;
        } else if (kind == QLatin1String("bool")) {
            auto* check = new QCheckBox(this);
            check->setChecked(value.toBool());
            connect(check, &QCheckBox::toggled, this, [this, key](bool on) { edited(key, on, true); });
            field = check;
        } else if (kind == QLatin1String("count")) {
            auto* spin = new QSpinBox(this);
            spin->setRange(p.value("min").toInt(1), p.value("max").toInt(20));
            spin->setValue(int(std::lround(value.toDouble())));
            connect(spin, &QSpinBox::valueChanged, this, [this, key](int n) { edited(key, n, false); });
            field = spin;
        } else {
            auto* spin = new QDoubleSpinBox(this);
            if (kind == QLatin1String("angle")) {
                spin->setDecimals(1);
                spin->setSingleStep(1.0);
                spin->setSuffix(QStringLiteral("°"));
                spin->setRange(p.value("min").toDouble(-360), p.value("max").toDouble(360));
            } else {
                spin->setDecimals(3);
                spin->setSingleStep(0.05);
                // A length's own minimum (e.g. a seat height) holds; the general 0.01 m does not, so a
                // typed 0 reaches Python and shows why it doesn't build instead of jumping to 0.01.
                const double lo = p.value("min").toDouble(0.01);
                spin->setRange(lo > 0.01 ? lo : 0.0, p.value("max").toDouble(50.0));
                spin->setSuffix(QStringLiteral(" m"));
            }
            spin->setValue(value.toDouble());
            connect(spin, &QDoubleSpinBox::valueChanged, this, [this, key](double d) { edited(key, d, false); });
            field = spin;
        }
        field->setObjectName(QStringLiteral("param_%1").arg(key));
        m_form->addRow(LibraryPanel::translated(p.value("label").toString(), p.value("label_es").toString()) + QLatin1Char(':'), field);
        m_form->setRowVisible(field, visible);
        ++m_rows;
    }
    closeGroup();
}

// ---------------------------------------------------------------- PlanSymbolView

PlanSymbolView::PlanSymbolView(QWidget* parent)
    : QWidget(parent)
{
    setProperty("symbolCurves", 0);
    setMinimumSize(200, 200);
}

void PlanSymbolView::setSymbol(const QJsonArray& symbol, double width, double depth)
{
    m_symbol = symbol;
    m_width = width;
    m_depth = depth;
    setProperty("symbolCurves", int(symbol.size()));
    update();
}

void PlanSymbolView::paintEvent(QPaintEvent*)
{
    QPainter painter(this);
    painter.fillRect(rect(), Qt::white);
    const int side = std::min(width(), height());
    if (side <= 0)
        return;
    const QPixmap pixmap = LibraryPanel::symbolIcon(m_symbol, m_width, m_depth, side).pixmap(side, side);
    painter.drawPixmap((width() - side) / 2, (height() - side) / 2, pixmap);
}

// ---------------------------------------------------------------- ObjectSettingsDialog

ObjectSettingsDialog::ObjectSettingsDialog(MainWindow* window, const QString& key, Mode mode, QWidget* parent)
    : QDialog(parent ? parent : window)
    , m_window(window)
    , m_key(key)
    , m_mode(mode)
    , m_fixed(key.startsWith(QLatin1String("ifc:")))
    , m_list(new QListWidget(this))
    , m_preview(new Viewport(this))
    , m_plan(new PlanSymbolView(this))
    , m_views(new QStackedWidget(this))
    , m_form(new ParameterForm(this))
    , m_error(new QLabel(this))
    , m_accept(new QPushButton(mode == Mode::Place ? tr("Place") : tr("Apply"), this))
    , m_saveAs(new QPushButton(tr("Save as..."), this))
    , m_timer(new QTimer(this))
{
    setObjectName(QStringLiteral("objectSettingsDialog"));
    setModal(true);
    resize(1000, 580);
    const QJsonObject form = PythonEngine::instance().callJson("object_form", {m_key, QString()}).object();
    const QString name = LibraryPanel::translated(form.value("name").toString(m_key), form.value("name_es").toString());
    setWindowTitle(tr("%1 — settings").arg(name));

    auto* columns = new QHBoxLayout;
    // Left: the saved versions.
    auto* left = new QWidget(this);
    auto* leftLayout = new QVBoxLayout(left);
    leftLayout->setContentsMargins(0, 0, 0, 0);
    leftLayout->addWidget(new QLabel(tr("Saved"), left));
    m_list->setObjectName(QStringLiteral("objectSettingsVersions"));
    m_list->setContextMenuPolicy(Qt::CustomContextMenu);
    leftLayout->addWidget(m_list, 1);
    m_saveAs->setObjectName(QStringLiteral("objectSettingsSaveAs"));
    m_saveAs->setToolTip(tr("Save these values as a named version of the object in this project"));
    leftLayout->addWidget(m_saveAs);
    left->setFixedWidth(190);
    columns->addWidget(left);

    // Middle: the 3D preview or the plan symbol.
    auto* middle = new QVBoxLayout;
    m_preview->setObjectName(QStringLiteral("objectSettingsPreview"));
    m_preview->setMinimumSize(320, 300);
    m_plan->setObjectName(QStringLiteral("objectSettingsPlan"));
    m_views->addWidget(m_preview);
    m_views->addWidget(m_plan);
    middle->addWidget(m_views, 1);
    auto* toggles = new QHBoxLayout;
    auto* to3D = new QPushButton(tr("3D"), this);
    auto* toPlan = new QPushButton(tr("Plan"), this);
    to3D->setObjectName(QStringLiteral("objectSettingsToggle3D"));
    toPlan->setObjectName(QStringLiteral("objectSettingsTogglePlan"));
    auto* group = new QButtonGroup(this);
    for (QPushButton* b : {to3D, toPlan}) {
        b->setCheckable(true);
        group->addButton(b);
    }
    to3D->setChecked(true);
    toggles->addStretch();
    toggles->addWidget(to3D);
    toggles->addWidget(toPlan);
    toggles->addStretch();
    middle->addLayout(toggles);
    columns->addLayout(middle, 1);

    // Right: the parameters.
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setWidget(m_form);
    scroll->setMinimumWidth(300);
    columns->addWidget(scroll);

    auto* layout = new QVBoxLayout(this);
    layout->addLayout(columns, 1);
    auto* bottom = new QHBoxLayout;
    m_error->setObjectName(QStringLiteral("objectSettingsError"));
    m_error->setStyleSheet(QStringLiteral("color: #c0392b;"));
    m_error->setWordWrap(true);
    bottom->addWidget(m_error, 1);
    auto* buttons = new QDialogButtonBox(this);
    m_accept->setObjectName(QStringLiteral("objectSettingsAccept"));
    m_accept->setDefault(true);
    buttons->addButton(m_accept, QDialogButtonBox::AcceptRole);
    buttons->addButton(QDialogButtonBox::Cancel);
    bottom->addWidget(buttons);
    layout->addLayout(bottom);

    m_timer->setSingleShot(true);
    m_timer->setInterval(150);
    connect(m_timer, &QTimer::timeout, this, &ObjectSettingsDialog::updatePreview);
    connect(to3D, &QPushButton::clicked, this, [this] { showPlan(false); });
    connect(toPlan, &QPushButton::clicked, this, [this] { showPlan(true); });
    connect(m_accept, &QPushButton::clicked, this, &ObjectSettingsDialog::onAccept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    connect(m_saveAs, &QPushButton::clicked, this, &ObjectSettingsDialog::saveAsDialog);
    connect(m_form, &ParameterForm::changed, this, [this](const QString& k) {
        m_lastEdited = k;
        if (!m_versionId.isEmpty()) { // edited since the version was picked: unsaved values
            m_versionId.clear();
            const QSignalBlocker block(m_list);
            m_list->setCurrentItem(nullptr);
        }
        schedulePreview();
    });
    // The selection, not the current item: focus entering the list makes its first item current
    // without selecting it, and that must not drop unsaved values.
    connect(m_list, &QListWidget::itemSelectionChanged, this, [this] {
        const QList<QListWidgetItem*> picked = m_list->selectedItems();
        if (picked.size() == 1 && (picked.first()->flags() & Qt::ItemIsSelectable))
            selectVersion(picked.first()->data(IdRole).toString());
    });
    connect(m_list, &QListWidget::customContextMenuRequested, this, [this](const QPoint& pos) {
        QListWidgetItem* item = m_list->itemAt(pos);
        if (!item || item->data(SourceRole).toString() != QLatin1String("project"))
            return;
        QMenu menu(this);
        fillVersionMenu(&menu, item->data(IdRole).toString());
        menu.exec(m_list->viewport()->mapToGlobal(pos));
    });

    if (m_fixed) { // fixed geometry: nothing to set or save
        left->hide();
        scroll->hide();
        to3D->hide();
        toPlan->hide();
        m_form->setObject(QString());
        schedulePreview();
        return;
    }
    m_form->setObject(m_key);
    m_default = m_form->values();
    loadVersions(QString());
    selectVersion(QString());
}

QJsonObject ObjectSettingsDialog::values() const
{
    return m_form->values();
}

QJsonObject ObjectSettingsDialog::versionById(const QString& id) const
{
    for (const auto& v : m_versions)
        if (v.toObject().value("id").toString() == id)
            return v.toObject();
    return {};
}

void ObjectSettingsDialog::loadVersions(const QString& select)
{
    const QJsonObject r = PythonEngine::instance().callJson("object_versions", {m_key}).object();
    if (r.value("ok").toBool())
        m_default = r.value("default").toObject();
    m_versions = r.value("versions").toArray();
    const QSignalBlocker block(m_list);
    m_list->clear();
    auto* def = new QListWidgetItem(tr("Default"), m_list);
    def->setData(IdRole, QString());
    def->setToolTip(tr("The object as its definition ships"));
    bool office = false;
    for (const auto& v : m_versions) {
        const QJsonObject o = v.toObject();
        const QString source = o.value("source").toString();
        if (source == QLatin1String("office") && !office) {
            office = true;
            auto* separator = new QListWidgetItem(tr("— Office —"), m_list);
            separator->setFlags(Qt::NoItemFlags);
            separator->setTextAlignment(Qt::AlignCenter);
        }
        auto* item = new QListWidgetItem(o.value("name").toString(), m_list);
        item->setData(IdRole, o.value("id").toString());
        item->setData(SourceRole, source);
        const int uses = o.value("uses").toInt();
        if (source == QLatin1String("project"))
            item->setToolTip(tr("%n placed object(s) use it", nullptr, uses));
        else
            item->setToolTip(tr("From the office library"));
    }
    for (int i = 0; i < m_list->count(); ++i)
        if ((m_list->item(i)->flags() & Qt::ItemIsSelectable) && m_list->item(i)->data(IdRole).toString() == select)
            m_list->setCurrentItem(m_list->item(i));
}

void ObjectSettingsDialog::selectVersion(const QString& id)
{
    if (m_fixed)
        return;
    const QJsonObject version = versionById(id);
    if (!id.isEmpty() && version.isEmpty())
        return; // not one of this object's versions
    m_versionId = id;
    m_source = id;
    m_lastEdited.clear();
    {
        const QSignalBlocker block(m_list);
        for (int i = 0; i < m_list->count(); ++i)
            if ((m_list->item(i)->flags() & Qt::ItemIsSelectable) && m_list->item(i)->data(IdRole).toString() == id)
                m_list->setCurrentItem(m_list->item(i));
    }
    m_form->setObject(m_key, id.isEmpty() ? m_default : version.value("values").toObject(), id);
    schedulePreview();
}

void ObjectSettingsDialog::setValues(const QJsonObject& values)
{
    if (m_fixed)
        return;
    m_versionId.clear();
    {
        const QSignalBlocker block(m_list);
        m_list->setCurrentItem(nullptr);
    }
    m_form->setValues(values);
    schedulePreview();
}

void ObjectSettingsDialog::schedulePreview()
{
    m_timer->start(); // restarts: one update after the last of a quick run of edits
}

void ObjectSettingsDialog::updatePreview()
{
    m_timer->stop();
    PythonEngine& py = PythonEngine::instance();
    const QJsonObject values = m_fixed ? QJsonObject() : m_form->values();
    MeshChunk chunk;
    QString error;
    if (fetchObjectPreview(py, m_key, values, &chunk, &error, m_source)) {
        m_preview->replaceElements(chunk); // the preview element keeps its GlobalId: replaced, never added
        if (!m_hasPreview)
            m_preview->homeView(false);
        m_preview->fitAll();
        m_hasPreview = true;
        m_valid = true;
        m_error->clear();
        m_form->markInvalid(QString(), QString());
        if (!m_fixed) {
            const QJsonObject symbol = py.callJson("object_symbol", {m_key, compact(values), m_source}).object();
            m_plan->setSymbol(symbol.value("symbol").toArray(), symbol.value("width").toDouble(1.0), symbol.value("depth").toDouble(1.0));
        }
    } else { // the last good shape stays
        m_valid = false;
        m_error->setText(error);
        m_form->markInvalid(m_lastEdited, error);
    }
    m_accept->setEnabled(m_valid);
    m_saveAs->setEnabled(m_valid);
}

void ObjectSettingsDialog::showPlan(bool plan)
{
    m_views->setCurrentWidget(plan ? static_cast<QWidget*>(m_plan) : static_cast<QWidget*>(m_preview));
}

void ObjectSettingsDialog::onAccept()
{
    if (m_timer->isActive()) // values typed in the last moment: check them before accepting
        updatePreview();
    if (m_valid)
        accept();
}

bool ObjectSettingsDialog::editDone(const QJsonObject& result, const QString& failure)
{
    if (!result.value("ok").toBool()) {
        if (m_window && !m_window->m_quiet)
            QMessageBox::warning(this, failure, result.value("error").toString());
        return false;
    }
    if (m_window)
        m_window->afterEdit(result); // undo, the window's unsaved mark
    return true;
}

bool ObjectSettingsDialog::saveAs(const QString& name, bool replace)
{
    if (m_fixed || !m_window || name.trimmed().isEmpty())
        return false;
    if (m_timer->isActive())
        updatePreview();
    if (!m_valid)
        return false;
    const QJsonObject r = m_window->bridge("save_object_version",
        {m_key, name.trimmed(), compact(m_form->values()), replace ? QStringLiteral("1") : QString()});
    if (r.contains("exists") && !replace) {
        if (m_window->m_quiet)
            return false;
        const auto answer = QMessageBox::question(this, tr("Save as"),
            tr("There is already a version called %1. Replace it with these values?").arg(name.trimmed()));
        return answer == QMessageBox::Yes && saveAs(name, true);
    }
    if (!editDone(r, tr("Could not save the version")))
        return false;
    loadVersions(QString());
    selectVersion(r.value("id").toString());
    return true;
}

void ObjectSettingsDialog::saveAsDialog()
{
    bool ok = false;
    const QString name = QInputDialog::getText(this, tr("Save as"), tr("Name of the version:"), QLineEdit::Normal, QString(), &ok);
    if (ok)
        saveAs(name);
}

bool ObjectSettingsDialog::renameVersion(const QString& id, const QString& name)
{
    if (!m_window || !editDone(m_window->bridge("rename_version", {id, name}), tr("Could not rename the version")))
        return false;
    loadVersions(m_versionId);
    return true;
}

bool ObjectSettingsDialog::deleteVersion(const QString& id)
{
    if (!m_window)
        return false;
    const QJsonObject r = m_window->bridge("delete_version", {id});
    if (!r.value("ok").toBool() && r.contains("used")) {
        if (!m_window->m_quiet)
            QMessageBox::warning(this, tr("Could not delete the version"),
                tr("%n placed object(s) use this version. Change them to another version first.", nullptr, r.value("used").toInt()));
        return false;
    }
    if (!editDone(r, tr("Could not delete the version")))
        return false;
    const bool current = m_versionId == id;
    if (m_source == id) // its stored definition went with it: the object's from now on
        m_source.clear();
    loadVersions(current ? QString() : m_versionId);
    if (current) { // its values stay in the controls, now unsaved
        m_versionId.clear();
        const QSignalBlocker block(m_list);
        m_list->setCurrentItem(nullptr);
    }
    return true;
}

bool ObjectSettingsDialog::moveToLibrary(const QString& id, bool replace)
{
    if (!m_window)
        return false;
    const QJsonObject r = m_window->bridge("move_version_to_library", {id, replace ? QStringLiteral("1") : QString()});
    if (r.contains("exists") && !replace) {
        if (m_window->m_quiet)
            return false;
        const auto answer = QMessageBox::question(this, tr("Move to library"),
            tr("The office library already has a version with this name. Replace it?"));
        return answer == QMessageBox::Yes && moveToLibrary(id, true);
    }
    if (!editDone(r, tr("Could not move the version to the office library")))
        return false;
    loadVersions(m_versionId);
    return true;
}

void ObjectSettingsDialog::fillVersionMenu(QMenu* menu, const QString& id)
{
    const QString name = versionById(id).value("name").toString();
    menu->addAction(tr("Rename..."), this, [this, id, name] {
        bool ok = false;
        const QString text = QInputDialog::getText(this, tr("Rename version"), tr("Name of the version:"), QLineEdit::Normal, name, &ok);
        if (ok)
            renameVersion(id, text);
    });
    menu->addAction(tr("Delete"), this, [this, id] { deleteVersion(id); });
    QAction* move = menu->addAction(tr("Move to library"), this, [this, id] { moveToLibrary(id); });
    menu->setToolTipsVisible(true);
    const bool office = m_window && !m_window->preferences().value(QStringLiteral("office_library")).toString().trimmed().isEmpty();
    move->setEnabled(office);
    move->setToolTip(office ? tr("Share this version with every project through the office library")
                            : tr("Set the office library folder in the preferences first"));
}

} // namespace kimbim
