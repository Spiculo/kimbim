// SPDX-License-Identifier: GPL-3.0-or-later
#include "ObjectEditorDialog.h"

#include "LibraryPanel.h"
#include "MainWindow.h"
#include "MeshChunk.h"
#include "ObjectSettingsDialog.h"
#include "PythonEngine.h"
#include "Viewport.h"

#include <QButtonGroup>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QRegularExpression>
#include <QScrollArea>
#include <QStackedWidget>
#include <QTabWidget>
#include <QTableWidget>
#include <QTimer>
#include <QVBoxLayout>

namespace kimbim {

namespace {

enum { OriginalRole = Qt::UserRole + 1 }; // a row's parameter or material slot as the draft had it
enum ParamColumn { Key, Label, LabelEs, Kind, Default, Min, Max, Group, ShowWhen, Options, ParamColumns };
enum MaterialColumn { Slot, SlotLabel, SlotDefault, MaterialColumns };

const char* const kKinds[] = {"length", "angle", "count", "bool", "choice", "material"};
const char* const kIfcClasses[] = {"IfcFurnitureType", "IfcSanitaryTerminalType", "IfcElectricApplianceType",
    "IfcBuildingElementProxyType", "IfcGeographicElementType"};
const char* const kInvalidStyle = "background-color: #f8d7da; border: 1px solid #c0392b;";
const QColor kInvalidColor(0xf8, 0xd7, 0xda);

QString compact(const QJsonObject& o)
{
    return QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Compact));
}

// A label as the definition writes it: plain text, or {"en", "es"} when the Spanish is given.
QJsonValue label(const QString& en, const QString& es)
{
    if (es.trimmed().isEmpty())
        return en.trimmed();
    return QJsonObject{{"en", en.trimmed()}, {"es", es.trimmed()}};
}

QString english(const QJsonValue& v)
{
    return v.isObject() ? v.toObject().value("en").toString() : v.toString();
}

QString spanish(const QJsonValue& v)
{
    return v.isObject() ? v.toObject().value("es").toString() : QString();
}

QString cellText(const QJsonValue& v)
{
    if (v.isDouble())
        return QString::number(v.toDouble(), 'g', 12);
    if (v.isBool())
        return v.toBool() ? QStringLiteral("true") : QStringLiteral("false");
    if (v.isArray())
        return QString::fromUtf8(QJsonDocument(v.toArray()).toJson(QJsonDocument::Compact));
    if (v.isObject())
        return compact(v.toObject());
    return v.toString(); // text; nothing for null and undefined
}

// The value a cell's text stands for: the draft's own value while the text is what it showed (a list stays
// a list), a number when it reads as one, true/false for an on/off, else the text (a formula); undefined
// when empty.
QJsonValue cellValue(const QString& text, const QJsonValue& was, bool asText = false, bool isBool = false)
{
    const QString t = text.trimmed();
    if (t.isEmpty())
        return QJsonValue(QJsonValue::Undefined);
    if (t == cellText(was))
        return was;
    if (asText)
        return t;
    if (isBool && (t == QLatin1String("true") || t == QLatin1String("false")))
        return t == QLatin1String("true");
    bool ok = false;
    const double d = t.toDouble(&ok);
    return ok ? QJsonValue(d) : QJsonValue(t);
}

void put(QJsonObject& o, const char* key, const QJsonValue& v)
{
    if (v.isUndefined())
        o.remove(QLatin1String(key));
    else
        o.insert(QLatin1String(key), v);
}

// A choice's options as one cell: "id: Label, id2: Label 2".
QString optionsText(const QJsonArray& options)
{
    QStringList out;
    for (const auto& v : options) {
        const QJsonObject o = v.toObject();
        out << o.value("id").toString() + QStringLiteral(": ") + english(o.value("label"));
    }
    return out.join(QStringLiteral(", "));
}

// The options a cell's text stands for. An option whose id the draft had keeps its Spanish label.
QJsonValue optionsValue(const QString& text, const QJsonArray& was)
{
    if (text.trimmed().isEmpty())
        return QJsonValue(QJsonValue::Undefined);
    if (text.trimmed() == optionsText(was))
        return was;
    QJsonArray out;
    for (const QString& item : text.split(QLatin1Char(','), Qt::SkipEmptyParts)) {
        const int colon = item.indexOf(QLatin1Char(':'));
        const QString id = (colon < 0 ? item : item.left(colon)).trimmed();
        const QString en = colon < 0 ? QString() : item.mid(colon + 1).trimmed();
        QJsonObject o{{"id", id}};
        for (const auto& w : was)
            if (w.toObject().value("id").toString() == id)
                o = w.toObject();
        o.insert("label", label(en.isEmpty() ? id : en, spanish(o.value("label"))));
        out.append(o);
    }
    return out;
}

void markCell(QTableWidget* table, int row, int column, const QString& message)
{
    const auto tip = [&](const QString& old) { return old.isEmpty() ? message : old + QLatin1Char('\n') + message; };
    if (QWidget* w = table->cellWidget(row, column)) {
        w->setStyleSheet(QString::fromLatin1(kInvalidStyle));
        w->setToolTip(tip(w->toolTip()));
    } else if (QTableWidgetItem* item = table->item(row, column)) {
        item->setBackground(kInvalidColor);
        item->setToolTip(tip(item->toolTip()));
    }
}

QPushButton* tableButton(const QString& text, const char* name, QWidget* parent)
{
    auto* b = new QPushButton(text, parent);
    b->setObjectName(QLatin1String(name));
    b->setAutoDefault(false);
    return b;
}

} // namespace

ObjectEditorDialog::ObjectEditorDialog(MainWindow* window, const QString& source, QWidget* parent)
    : QDialog(parent ? parent : window)
    , m_window(window)
    , m_id(new QLineEdit(this))
    , m_name(new QLineEdit(this))
    , m_nameEs(new QLineEdit(this))
    , m_category(new QComboBox(this))
    , m_ifcClass(new QComboBox(this))
    , m_predefined(new QLineEdit(this))
    , m_params(new QTableWidget(this))
    , m_materials(new QTableWidget(this))
    , m_preview(new Viewport(this))
    , m_plan(new PlanSymbolView(this))
    , m_views(new QStackedWidget(this))
    , m_try(new ParameterForm(this))
    , m_error(new QLabel(this))
    , m_saveProject(new QPushButton(tr("Save to project"), this))
    , m_saveOffice(new QPushButton(tr("Save to office library"), this))
    , m_timer(new QTimer(this))
{
    setObjectName(QStringLiteral("objectEditorDialog"));
    setModal(true);
    resize(1320, 680);

    auto* columns = new QHBoxLayout;
    // Left: the object, its parameters and materials.
    auto* tabs = new QTabWidget(this);
    tabs->setObjectName(QStringLiteral("editorTabs"));
    tabs->setMinimumWidth(560);
    auto* object = new QWidget(tabs);
    auto* objectForm = new QFormLayout(object);
    m_id->setObjectName(QStringLiteral("editorId"));
    m_name->setObjectName(QStringLiteral("editorName"));
    m_nameEs->setObjectName(QStringLiteral("editorNameEs"));
    m_category->setObjectName(QStringLiteral("editorCategory"));
    m_ifcClass->setObjectName(QStringLiteral("editorIfcClass"));
    m_predefined->setObjectName(QStringLiteral("editorPredefined"));
    m_category->addItem(tr("Furniture"), QStringLiteral("furniture"));
    m_category->addItem(tr("Sanitary"), QStringLiteral("sanitary"));
    m_category->addItem(tr("Kitchen"), QStringLiteral("kitchen"));
    m_category->addItem(tr("Site"), QStringLiteral("site"));
    m_ifcClass->setEditable(true);
    for (const char* c : kIfcClasses)
        m_ifcClass->addItem(QLatin1String(c));
    objectForm->addRow(tr("Id:"), m_id);
    objectForm->addRow(tr("Name:"), m_name);
    objectForm->addRow(tr("Name (ES):"), m_nameEs);
    objectForm->addRow(tr("Category:"), m_category);
    objectForm->addRow(tr("IFC class:"), m_ifcClass);
    objectForm->addRow(tr("Predefined type:"), m_predefined);
    auto* idHelp = new QLabel(tr("The id names the object's file and its reference: lower-case letters, digits and _."), object);
    idHelp->setWordWrap(true);
    objectForm->addRow(idHelp);
    tabs->addTab(object, tr("Object"));

    auto* paramsTab = new QWidget(tabs);
    auto* paramsLayout = new QVBoxLayout(paramsTab);
    m_params->setObjectName(QStringLiteral("editorParams"));
    m_params->setColumnCount(ParamColumns);
    m_params->setHorizontalHeaderLabels({tr("Key"), tr("Label"), tr("Label (ES)"), tr("Kind"), tr("Default"), tr("Min"),
        tr("Max"), tr("Group"), tr("Show when"), tr("Options")});
    m_params->horizontalHeaderItem(Options)->setToolTip(tr("A choice's options: id: Label, id2: Label 2"));
    m_params->horizontalHeaderItem(ShowWhen)->setToolTip(tr("A formula: the parameter shows while it is true"));
    m_params->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_params->setSelectionMode(QAbstractItemView::SingleSelection);
    paramsLayout->addWidget(m_params, 1);
    auto* paramButtons = new QHBoxLayout;
    auto* paramAdd = tableButton(tr("Add"), "editorParamAdd", paramsTab);
    auto* paramRemove = tableButton(tr("Remove"), "editorParamRemove", paramsTab);
    auto* paramUp = tableButton(tr("Up"), "editorParamUp", paramsTab);
    auto* paramDown = tableButton(tr("Down"), "editorParamDown", paramsTab);
    for (QPushButton* b : {paramAdd, paramRemove, paramUp, paramDown})
        paramButtons->addWidget(b);
    paramButtons->addStretch();
    paramsLayout->addLayout(paramButtons);
    tabs->addTab(paramsTab, tr("Parameters"));

    auto* materialsTab = new QWidget(tabs);
    auto* materialsLayout = new QVBoxLayout(materialsTab);
    m_materials->setObjectName(QStringLiteral("editorMaterials"));
    m_materials->setColumnCount(MaterialColumns);
    m_materials->setHorizontalHeaderLabels({tr("Slot"), tr("Label"), tr("Default material")});
    m_materials->horizontalHeader()->setStretchLastSection(true);
    m_materials->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_materials->setSelectionMode(QAbstractItemView::SingleSelection);
    materialsLayout->addWidget(m_materials, 1);
    auto* materialButtons = new QHBoxLayout;
    auto* materialAdd = tableButton(tr("Add"), "editorMaterialAdd", materialsTab);
    auto* materialRemove = tableButton(tr("Remove"), "editorMaterialRemove", materialsTab);
    materialButtons->addWidget(materialAdd);
    materialButtons->addWidget(materialRemove);
    materialButtons->addStretch();
    materialsLayout->addLayout(materialButtons);
    tabs->addTab(materialsTab, tr("Materials"));
    columns->addWidget(tabs);

    // Middle: the 3D preview or the plan symbol.
    auto* middle = new QVBoxLayout;
    m_preview->setObjectName(QStringLiteral("editorPreview"));
    m_preview->setMinimumSize(320, 300);
    m_plan->setObjectName(QStringLiteral("editorPlan"));
    m_views->addWidget(m_preview);
    m_views->addWidget(m_plan);
    middle->addWidget(m_views, 1);
    auto* toggles = new QHBoxLayout;
    auto* to3D = tableButton(tr("3D"), "editorToggle3D", this);
    auto* toPlan = tableButton(tr("Plan"), "editorTogglePlan", this);
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

    // Right: Try values.
    auto* right = new QVBoxLayout;
    auto* tryLabel = new QLabel(tr("Try values"), this);
    tryLabel->setToolTip(tr("Values to preview the object with; they don't change the defaults"));
    right->addWidget(tryLabel);
    m_try->setObjectName(QStringLiteral("editorTryValues"));
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setWidget(m_try);
    scroll->setMinimumWidth(260);
    right->addWidget(scroll, 1);
    columns->addLayout(right);

    auto* layout = new QVBoxLayout(this);
    layout->addLayout(columns, 1);
    m_error->setObjectName(QStringLiteral("editorError"));
    m_error->setStyleSheet(QStringLiteral("color: #c0392b;"));
    m_error->setWordWrap(true);
    m_error->setTextInteractionFlags(Qt::TextSelectableByMouse);
    layout->addWidget(m_error);
    auto* buttons = new QDialogButtonBox(this);
    buttons->addButton(QDialogButtonBox::Cancel);
    m_saveProject->setObjectName(QStringLiteral("editorSaveProject"));
    m_saveProject->setToolTip(tr("Keep the object in this project: its placed objects follow"));
    m_saveOffice->setObjectName(QStringLiteral("editorSaveOffice"));
    for (QPushButton* b : {m_saveProject, m_saveOffice}) {
        b->setEnabled(false); // until the draft is checked
        b->setAutoDefault(false); // Enter edits the tables, it doesn't save
        buttons->addButton(b, QDialogButtonBox::ActionRole);
    }
    layout->addWidget(buttons);

    m_office = !PythonEngine::instance().callJson("library_objects", {}).object()
                    .value("office").toObject().value("folder").toString().isEmpty();
    m_saveOffice->setToolTip(m_office ? tr("Write the object's file to the office library, for every project")
                                      : tr("Set an office library folder in Preferences › Office library"));

    m_timer->setSingleShot(true);
    m_timer->setInterval(300);
    connect(m_timer, &QTimer::timeout, this, &ObjectEditorDialog::check);
    for (QLineEdit* field : {m_id, m_name, m_nameEs, m_predefined})
        connect(field, &QLineEdit::textChanged, this, &ObjectEditorDialog::scheduleCheck);
    for (QComboBox* combo : {m_category, m_ifcClass})
        connect(combo, &QComboBox::currentTextChanged, this, &ObjectEditorDialog::scheduleCheck);
    for (QLineEdit* field : {m_name, m_nameEs})
        connect(field, &QLineEdit::textChanged, this, [this] {
            setWindowTitle(tr("Object editor — %1").arg(LibraryPanel::translated(m_name->text(), m_nameEs->text())));
        });
    connect(m_params, &QTableWidget::itemChanged, this, &ObjectEditorDialog::scheduleCheck);
    connect(m_materials, &QTableWidget::itemChanged, this, &ObjectEditorDialog::scheduleCheck);
    connect(paramAdd, &QPushButton::clicked, this, &ObjectEditorDialog::addParam);
    connect(paramRemove, &QPushButton::clicked, this, [this] {
        if (m_params->currentRow() >= 0) {
            m_params->removeRow(m_params->currentRow());
            scheduleCheck();
        }
    });
    connect(paramUp, &QPushButton::clicked, this, [this] { moveParam(-1); });
    connect(paramDown, &QPushButton::clicked, this, [this] { moveParam(1); });
    connect(materialAdd, &QPushButton::clicked, this, &ObjectEditorDialog::addMaterial);
    connect(materialRemove, &QPushButton::clicked, this, [this] {
        if (m_materials->currentRow() >= 0) {
            m_materials->removeRow(m_materials->currentRow());
            scheduleCheck();
        }
    });
    connect(to3D, &QPushButton::clicked, this, [this] { m_views->setCurrentWidget(m_preview); });
    connect(toPlan, &QPushButton::clicked, this, [this] { m_views->setCurrentWidget(m_plan); });
    connect(m_try, &ParameterForm::changed, this, [this](const QString& key) {
        m_tried.insert(key, m_try->values().value(key));
        m_lastTried = key;
        scheduleCheck();
    });
    connect(buttons, &QDialogButtonBox::rejected, this, &ObjectEditorDialog::reject);
    connect(m_saveProject, &QPushButton::clicked, this, [this] { saveTo(QStringLiteral("project")); });
    connect(m_saveOffice, &QPushButton::clicked, this, [this] { saveTo(QStringLiteral("office")); });

    const QJsonObject r = PythonEngine::instance().callJson("object_draft", {source}).object();
    if (!r.value("ok").toBool()) { // nothing to edit
        m_error->setText(r.value("error").toString(tr("The object could not be opened")));
        m_saveProject->setEnabled(false);
        m_saveOffice->setEnabled(false);
        m_clean = draft();
        return;
    }
    setDraft(r.value("draft").toObject());
}

// ---------------------------------------------------------------- the fields and the draft

void ObjectEditorDialog::setDraft(const QJsonObject& draft)
{
    m_base = draft;
    {
        const QSignalBlocker b1(m_id), b2(m_nameEs), b3(m_category), b4(m_ifcClass), b5(m_predefined);
        m_id->setText(draft.value("id").toString());
        m_nameEs->setText(spanish(draft.value("name")));
        const QString category = draft.value("category").toString(QStringLiteral("furniture"));
        if (m_category->findData(category) < 0) // a category the dialog doesn't offer stays
            m_category->addItem(category, category);
        m_category->setCurrentIndex(m_category->findData(category));
        const QJsonArray ifc4 = draft.value("ifc").toObject().value("IFC4").toArray();
        m_ifcClass->setCurrentText(ifc4.at(0).toString());
        m_predefined->setText(ifc4.at(1).toString());
    }
    m_name->setText(english(draft.value("name"))); // the window title follows
    fillParams(draft.value("params").toArray());
    fillMaterials(draft.value("materials").toObject());
    m_clean = this->draft();
    m_checked.clear();
    m_tried = {};
    scheduleCheck();
}

QJsonObject ObjectEditorDialog::draft() const
{
    QJsonObject d = m_base;
    d.insert("id", m_id->text().trimmed());
    d.insert("name", label(m_name->text(), m_nameEs->text()));
    d.insert("category", m_category->currentData().toString());
    QJsonObject ifc = d.value("ifc").toObject();
    const QJsonArray ifc4 = ifc.value("IFC4").toArray();
    const QString cls = m_ifcClass->currentText().trimmed(), predefined = m_predefined->text().trimmed();
    ifc.insert("IFC4", QJsonArray{cls, predefined.isEmpty() ? QJsonValue() : QJsonValue(predefined), ifc4.size() > 2 ? ifc4.at(2) : QJsonValue()});
    if (cls != ifc4.at(0).toString() && ifc.contains(QLatin1String("IFC2X3"))) {
        // the IFC2X3 class follows; IFC2X3 has no geographic elements, a proxy stands in
        const QJsonArray old = ifc.value("IFC2X3").toArray();
        ifc.insert("IFC2X3", QJsonArray{cls == QLatin1String("IfcGeographicElementType") ? QStringLiteral("IfcBuildingElementProxyType") : cls,
            QJsonValue(), old.size() > 2 ? old.at(2) : QJsonValue()});
    }
    d.insert("ifc", ifc);
    d.insert("params", params());
    const QJsonObject mats = materials();
    if (mats.isEmpty())
        d.remove(QLatin1String("materials"));
    else
        d.insert("materials", mats);
    return d;
}

void ObjectEditorDialog::fillParams(const QJsonArray& params)
{
    const QSignalBlocker block(m_params);
    m_params->setRowCount(0);
    for (const auto& v : params) {
        const QJsonObject p = v.toObject();
        const int r = m_params->rowCount();
        m_params->insertRow(r);
        const QString cells[ParamColumns] = {p.value("key").toString(), english(p.value("label")), spanish(p.value("label")),
            QString(), cellText(p.value("default")), cellText(p.value("min")), cellText(p.value("max")),
            english(p.value("group")), cellText(p.value("show_when")), optionsText(p.value("options").toArray())};
        for (int c = 0; c < ParamColumns; ++c)
            if (c != Kind)
                m_params->setItem(r, c, new QTableWidgetItem(cells[c]));
        m_params->item(r, Key)->setData(OriginalRole, p);
        auto* kind = new QComboBox(m_params);
        for (const char* k : kKinds)
            kind->addItem(QLatin1String(k));
        const QString was = p.value("kind").toString();
        if (kind->findText(was) < 0) // an unknown kind stays, for the check to name
            kind->addItem(was);
        kind->setCurrentText(was);
        connect(kind, &QComboBox::currentTextChanged, this, &ObjectEditorDialog::scheduleCheck);
        m_params->setCellWidget(r, Kind, kind);
    }
}

QJsonArray ObjectEditorDialog::params() const
{
    QJsonArray out;
    for (int r = 0; r < m_params->rowCount(); ++r) {
        const auto text = [&](int c) { return m_params->item(r, c) ? m_params->item(r, c)->text() : QString(); };
        // the row's parameter as the draft had it: what the table doesn't show stays
        QJsonObject p = m_params->item(r, Key) ? m_params->item(r, Key)->data(OriginalRole).toJsonObject() : QJsonObject();
        const auto* kindBox = qobject_cast<QComboBox*>(m_params->cellWidget(r, Kind));
        const QString kind = kindBox ? kindBox->currentText() : p.value("kind").toString();
        p.insert("key", text(Key).trimmed());
        put(p, "label", text(Label).trimmed().isEmpty() ? QJsonValue(QJsonValue::Undefined) : label(text(Label), text(LabelEs)));
        p.insert("kind", kind);
        const bool named = kind == QLatin1String("choice") || kind == QLatin1String("material"); // an option id or a material name
        put(p, "default", cellValue(text(Default), p.value("default"), named, kind == QLatin1String("bool")));
        put(p, "min", cellValue(text(Min), p.value("min")));
        put(p, "max", cellValue(text(Max), p.value("max")));
        const QString group = text(Group).trimmed();
        if (group.isEmpty())
            p.remove(QLatin1String("group"));
        else if (english(p.value("group")) != group) // an unchanged heading keeps its Spanish
            p.insert("group", group);
        put(p, "show_when", cellValue(text(ShowWhen), p.value("show_when"), true));
        put(p, "options", optionsValue(text(Options), p.value("options").toArray()));
        out.append(p);
    }
    return out;
}

void ObjectEditorDialog::fillMaterials(const QJsonObject& materials)
{
    const QSignalBlocker block(m_materials);
    m_materials->setRowCount(0);
    for (auto it = materials.begin(); it != materials.end(); ++it) {
        const QJsonObject m = it.value().toObject();
        const int r = m_materials->rowCount();
        m_materials->insertRow(r);
        m_materials->setItem(r, Slot, new QTableWidgetItem(it.key()));
        m_materials->setItem(r, SlotLabel, new QTableWidgetItem(english(m.value("label"))));
        m_materials->setItem(r, SlotDefault, new QTableWidgetItem(m.value("default").toString()));
        m_materials->item(r, Slot)->setData(OriginalRole, m);
    }
}

QJsonObject ObjectEditorDialog::materials() const
{
    QJsonObject out;
    for (int r = 0; r < m_materials->rowCount(); ++r) {
        const auto text = [&](int c) { return m_materials->item(r, c) ? m_materials->item(r, c)->text().trimmed() : QString(); };
        QJsonObject m = m_materials->item(r, Slot) ? m_materials->item(r, Slot)->data(OriginalRole).toJsonObject() : QJsonObject();
        if (text(SlotLabel).isEmpty())
            m.remove(QLatin1String("label"));
        else if (english(m.value("label")) != text(SlotLabel)) // an unchanged label keeps its Spanish
            m.insert("label", text(SlotLabel));
        put(m, "default", text(SlotDefault).isEmpty() ? QJsonValue(QJsonValue::Undefined) : QJsonValue(text(SlotDefault)));
        out.insert(text(Slot), m);
    }
    return out;
}

void ObjectEditorDialog::addParam()
{
    QStringList keys;
    for (int r = 0; r < m_params->rowCount(); ++r)
        keys << (m_params->item(r, Key) ? m_params->item(r, Key)->text() : QString());
    QString key = QStringLiteral("param");
    for (int k = 2; keys.contains(key); ++k)
        key = QStringLiteral("param%1").arg(k);
    QJsonArray list = params();
    list.append(QJsonObject{{"key", key}, {"kind", "length"}, {"label", tr("Parameter")}, {"default", 0.1}});
    fillParams(list);
    m_params->setCurrentCell(list.size() - 1, Key);
    scheduleCheck();
}

void ObjectEditorDialog::moveParam(int by)
{
    const int row = m_params->currentRow(), to = row + by;
    if (row < 0 || to < 0 || to >= m_params->rowCount())
        return;
    QJsonArray list = params();
    const QJsonValue moved = list.at(row);
    list.removeAt(row);
    list.insert(to, moved);
    fillParams(list);
    m_params->setCurrentCell(to, m_params->currentColumn() < 0 ? 0 : m_params->currentColumn());
    scheduleCheck();
}

void ObjectEditorDialog::addMaterial()
{
    const QJsonObject mats = materials();
    QString slot = QStringLiteral("material");
    for (int k = 2; mats.contains(slot); ++k)
        slot = QStringLiteral("material%1").arg(k);
    const QSignalBlocker block(m_materials);
    const int r = m_materials->rowCount();
    m_materials->insertRow(r);
    m_materials->setItem(r, Slot, new QTableWidgetItem(slot));
    m_materials->setItem(r, SlotLabel, new QTableWidgetItem(tr("Material")));
    m_materials->setItem(r, SlotDefault, new QTableWidgetItem(QStringLiteral("Timber - finish")));
    m_materials->setCurrentCell(r, Slot);
    scheduleCheck();
}

bool ObjectEditorDialog::isDirty() const
{
    return draft() != m_clean;
}

// ---------------------------------------------------------------- check and preview

void ObjectEditorDialog::scheduleCheck()
{
    m_timer->start(); // restarts: one check after the last of a quick run of edits
}

void ObjectEditorDialog::check()
{
    m_timer->stop();
    PythonEngine& py = PythonEngine::instance();
    const QJsonObject d = draft();
    const QString text = compact(d);
    if (text != m_checked) { // a Try value alone doesn't check the draft again
        m_checked = text;
        const QJsonObject r = py.callJson("check_draft", {text}).object();
        m_valid = r.value("ok").toBool();
        QJsonArray errors = r.value("errors").toArray();
        if (!m_valid && errors.isEmpty())
            errors.append(QJsonObject{{"path", QString()}, {"message", r.value("error").toString(tr("The object could not be checked"))}});
        markErrors(errors);
        if (m_valid) { // the Try values of parameters the draft no longer has go
            QStringList keys;
            for (const auto& p : d.value("params").toArray())
                keys << p.toObject().value("key").toString();
            for (const QString& slot : d.value("materials").toObject().keys())
                keys << QStringLiteral("mat_") + slot;
            for (const QString& key : m_tried.keys())
                if (!keys.contains(key))
                    m_tried.remove(key);
            m_try->setDraft(d, m_tried);
        }
    }
    if (m_valid)
        updatePreview(d);
    showErrors();
    m_saveProject->setEnabled(m_valid);
    m_saveOffice->setEnabled(m_valid && m_office);
}

void ObjectEditorDialog::updatePreview(const QJsonObject& draft)
{
    PythonEngine& py = PythonEngine::instance();
    const QJsonObject values = m_try->values();
    MeshChunk chunk;
    QString error;
    if (fetchDraftPreview(py, draft, values, &chunk, &error)) {
        m_preview->replaceElements(chunk); // the preview element keeps its GlobalId: replaced, never added
        if (!m_hasPreview)
            m_preview->homeView(false);
        m_preview->fitAll();
        m_hasPreview = true;
        m_previewError.clear();
        m_try->markInvalid(QString(), QString());
        const QJsonObject symbol = py.callJson("draft_symbol", {compact(draft), compact(values)}).object();
        m_plan->setSymbol(symbol.value("symbol").toArray(), symbol.value("width").toDouble(1.0), symbol.value("depth").toDouble(1.0));
    } else { // the last good shape stays
        m_previewError = error;
        m_try->markInvalid(m_lastTried, error);
    }
}

void ObjectEditorDialog::showErrors()
{
    QStringList lines = m_checkErrors;
    if (m_valid && !m_previewError.isEmpty())
        lines << tr("Try values: %1").arg(m_previewError);
    m_error->setText(lines.join(QLatin1Char('\n')));
}

void ObjectEditorDialog::markErrors(const QJsonArray& errors)
{
    m_errorPaths.clear();
    m_checkErrors.clear();
    const QSignalBlocker b1(m_params), b2(m_materials); // marking an item is an itemChanged too
    for (QTableWidget* table : {m_params, m_materials})
        for (int r = 0; r < table->rowCount(); ++r)
            for (int c = 0; c < table->columnCount(); ++c) {
                if (QWidget* w = table->cellWidget(r, c)) {
                    w->setStyleSheet(QString());
                    w->setToolTip(QString());
                } else if (QTableWidgetItem* item = table->item(r, c)) {
                    item->setBackground(QBrush());
                    item->setToolTip(QString());
                }
            }
    const QList<QWidget*> fields{m_id, m_name, m_nameEs, m_category, m_ifcClass, m_predefined};
    for (QWidget* f : fields) {
        f->setStyleSheet(QString());
        f->setToolTip(QString());
    }

    // params[k].field (or params.<key> for a key used twice), materials.<slot>, the object's own fields
    static const QRegularExpression paramPath(QStringLiteral(R"(^params(?:\[(\d+)\]|\.(\w+))(?:\.(\w+))?)"));
    static const QRegularExpression slotPath(QStringLiteral(R"(^materials\.(\w+))"));
    static const QHash<QString, int> columnOf{{"key", Key}, {"label", Label}, {"kind", Kind}, {"default", Default},
        {"min", Min}, {"max", Max}, {"group", Group}, {"show_when", ShowWhen}, {"options", Options}};
    const QHash<QString, QList<QWidget*>> fieldsOf{{"id", {m_id}}, {"name", {m_name, m_nameEs}}, {"category", {m_category}},
        {"ifc", {m_ifcClass, m_predefined}}};
    for (const auto& v : errors) {
        const QJsonObject e = v.toObject();
        const QString path = e.value("path").toString(), message = e.value("message").toString();
        m_errorPaths << path;
        m_checkErrors << (path.isEmpty() ? message : path + QStringLiteral(": ") + message);
        if (const auto m = paramPath.match(path); m.hasMatch()) {
            QList<int> rows;
            if (!m.captured(1).isEmpty())
                rows << m.captured(1).toInt();
            else
                for (int r = 0; r < m_params->rowCount(); ++r)
                    if (m_params->item(r, Key) && m_params->item(r, Key)->text().trimmed() == m.captured(2))
                        rows << r;
            const QString field = m.captured(1).isEmpty() ? QStringLiteral("key") : m.captured(3);
            for (int r : rows) {
                if (r >= m_params->rowCount())
                    continue;
                if (columnOf.contains(field))
                    markCell(m_params, r, columnOf.value(field), message);
                else // the parameter as a whole
                    for (int c = 0; c < ParamColumns; ++c)
                        markCell(m_params, r, c, message);
            }
        } else if (const auto s = slotPath.match(path); s.hasMatch()) {
            for (int r = 0; r < m_materials->rowCount(); ++r)
                if (m_materials->item(r, Slot) && m_materials->item(r, Slot)->text().trimmed() == s.captured(1))
                    for (int c = 0; c < MaterialColumns; ++c)
                        markCell(m_materials, r, c, message);
        } else {
            for (QWidget* f : fieldsOf.value(path.section(QLatin1Char('.'), 0, 0).section(QLatin1Char('['), 0, 0))) {
                f->setStyleSheet(QString::fromLatin1(kInvalidStyle));
                f->setToolTip(f->toolTip().isEmpty() ? message : f->toolTip() + QLatin1Char('\n') + message);
            }
        }
    }
}

// ---------------------------------------------------------------- save and cancel

bool ObjectEditorDialog::saveTo(const QString& target, bool replace)
{
    if (!m_window)
        return false;
    if (m_timer->isActive() || m_checked.isEmpty()) // edits of the last moment: check them first
        check();
    if (!m_valid || (target == QLatin1String("office") && !m_office))
        return false;
    const QJsonObject d = draft();
    const QString id = d.value("id").toString();
    const QJsonObject r = m_window->bridge("save_draft", {compact(d), target, replace ? id : QString()});
    if (r.contains("exists") && !replace) {
        if (m_window->m_quiet)
            return false;
        const auto answer = QMessageBox::question(this, tr("Save to office library"),
            tr("The office library already has an object %1. Replace it?").arg(id));
        return answer == QMessageBox::Yes && saveTo(target, true);
    }
    if (!r.value("ok").toBool()) {
        if (r.contains("errors")) {
            markErrors(r.value("errors").toArray());
            m_valid = false;
        }
        m_error->setText(r.value("error").toString());
        if (!m_window->m_quiet)
            QMessageBox::warning(this, tr("Could not save the object"), r.value("error").toString());
        return false;
    }
    if (target == QLatin1String("project"))
        m_window->afterEdit(r); // undo, the window's unsaved mark
    m_outdated = target == QLatin1String("office") ? r.value("outdated").toInt() : 0;
    m_clean = d;
    accept();
    return true;
}

void ObjectEditorDialog::reject()
{
    if (isDirty() && !(m_window && m_window->m_quiet)) {
        const auto answer = QMessageBox::question(this, tr("Object editor"), tr("Discard the changes to this object?"));
        if (answer != QMessageBox::Yes)
            return;
    }
    QDialog::reject();
}

} // namespace kimbim
