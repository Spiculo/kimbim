// SPDX-License-Identifier: GPL-3.0-or-later
#include "ProjectSettingsDialog.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QJsonArray>
#include <QLabel>
#include <QSpinBox>
#include <QVBoxLayout>

#include <cmath>

namespace kimbim {

ProjectSettingsDialog::ProjectSettingsDialog(const QJsonObject& settings, bool kept, QWidget* parent)
    : QDialog(parent)
    , m_settings(settings)
{
    setWindowTitle(tr("Project settings"));
    auto* layout = new QVBoxLayout(this);
    auto* form = new QFormLayout;
    m_cut = new QDoubleSpinBox(this);
    m_cut->setObjectName(QStringLiteral("cutHeight"));
    m_cut->setRange(0.01, 20.0);
    m_cut->setDecimals(2);
    m_cut->setSingleStep(0.05);
    m_cut->setSuffix(QStringLiteral(" m"));
    m_cut->setValue(settings.value("plan_cut_height").toDouble(1.2));
    form->addRow(tr("Plan cut height:"), m_cut);
    // D91: how far below the level a plan still sees (Revit's view range).
    m_viewDepth = new QDoubleSpinBox(this);
    m_viewDepth->setObjectName(QStringLiteral("viewDepth"));
    m_viewDepth->setRange(0.0, 20.0);
    m_viewDepth->setDecimals(2);
    m_viewDepth->setSingleStep(0.05);
    m_viewDepth->setSuffix(QStringLiteral(" m"));
    m_viewDepth->setValue(settings.value("view_depth").toDouble(0.5));
    form->addRow(tr("Plan view depth below:"), m_viewDepth);
    // D93: the built-in scales (1:500, 1:100, 1:50, 1:20) plus the project's own; type a new one.
    m_scale = new QComboBox(this);
    m_scale->setObjectName(QStringLiteral("drawingScale"));
    m_scale->setEditable(true);
    m_scale->setInsertPolicy(QComboBox::NoInsert);
    for (const auto& s : settings.value("scales").toArray())
        m_scale->addItem(QString::number(s.toInt()));
    const QString currentScale = QString::number(settings.value("drawing_scale").toInt(100));
    if (m_scale->findText(currentScale) < 0)
        m_scale->addItem(currentScale);
    m_scale->setCurrentText(currentScale);
    form->addRow(tr("Drawings placed on sheets at:"), m_scale);
    m_paper = new QComboBox(this);
    m_paper->setObjectName(QStringLiteral("sheetPaper"));
    m_paper->addItems({QStringLiteral("A1"), QStringLiteral("A3")});
    m_paper->setCurrentText(settings.value("sheet_paper").toString(QStringLiteral("A1")));
    form->addRow(tr("New sheets:"), m_paper);
    m_unit = new QComboBox(this);
    m_unit->setObjectName(QStringLiteral("lengthUnit"));
    m_unit->addItems({QStringLiteral("m"), QStringLiteral("cm"), QStringLiteral("mm")});
    m_unit->setCurrentText(settings.value("length_unit").toString(QStringLiteral("m")));
    form->addRow(tr("Lengths in:"), m_unit);
    m_areaUnit = new QComboBox(this); // D92
    m_areaUnit->setObjectName(QStringLiteral("areaUnit"));
    m_areaUnit->addItems({QStringLiteral("m²"), QStringLiteral("cm²"), QStringLiteral("mm²")});
    m_areaUnit->setCurrentText(settings.value("area_unit").toString(QStringLiteral("m²")));
    form->addRow(tr("Areas in:"), m_areaUnit);
    m_levelReference = new QComboBox(this); // D92
    m_levelReference->setObjectName(QStringLiteral("levelReference"));
    m_levelReference->addItem(tr("Project zero"), QStringLiteral("project"));
    m_levelReference->addItem(tr("The level it is on"), QStringLiteral("level"));
    m_levelReference->addItem(tr("Sea level"), QStringLiteral("sea"));
    m_levelReference->setCurrentIndex(std::max(0, m_levelReference->findData(
        settings.value("level_reference").toString(QStringLiteral("project")))));
    m_levelReference->setToolTip(tr("What level and spot dimensions measure from"));
    form->addRow(tr("Level dimensions from:"), m_levelReference);
    m_seaLevel = new QDoubleSpinBox(this); // D92: the datum the sea-level reference needs
    m_seaLevel->setObjectName(QStringLiteral("seaLevel"));
    m_seaLevel->setRange(-10000.0, 10000.0);
    m_seaLevel->setDecimals(2);
    m_seaLevel->setSingleStep(0.5);
    m_seaLevel->setSuffix(QStringLiteral(" m"));
    m_seaLevel->setValue(settings.value("sea_level").toDouble(0.0));
    m_seaLevel->setToolTip(tr("The project zero's elevation above sea level"));
    m_seaLevel->setEnabled(m_levelReference->currentData().toString() == QLatin1String("sea"));
    connect(m_levelReference, &QComboBox::currentIndexChanged, this,
        [this] { m_seaLevel->setEnabled(m_levelReference->currentData().toString() == QLatin1String("sea")); });
    form->addRow(tr("Sea level:"), m_seaLevel);
    m_northStyle = new QComboBox(this); // D92
    m_northStyle->setObjectName(QStringLiteral("northArrowStyle"));
    m_northStyle->addItem(tr("Circle and arrow"), QStringLiteral("circle"));
    m_northStyle->addItem(tr("Needle"), QStringLiteral("needle"));
    m_northStyle->addItem(tr("Plain arrow"), QStringLiteral("arrow"));
    m_northStyle->setCurrentIndex(std::max(0, m_northStyle->findData(
        settings.value("north_arrow_style").toString(QStringLiteral("circle")))));
    m_northStyle->setToolTip(tr("The north arrow the North arrow tool and the plan drawings place"));
    form->addRow(tr("North arrow:"), m_northStyle);
    m_scaleBarStyle = new QComboBox(this); // D92
    m_scaleBarStyle->setObjectName(QStringLiteral("scaleBarStyle"));
    m_scaleBarStyle->addItem(tr("Alternating bar"), QStringLiteral("bar"));
    m_scaleBarStyle->addItem(tr("Line with ticks"), QStringLiteral("line"));
    m_scaleBarStyle->setCurrentIndex(std::max(0, m_scaleBarStyle->findData(
        settings.value("scale_bar_style").toString(QStringLiteral("bar")))));
    m_scaleBarStyle->setToolTip(tr("The scale bar the Scale bar tool and the plan drawings place"));
    form->addRow(tr("Scale bar:"), m_scaleBarStyle);
    m_stairRiser = new QDoubleSpinBox(this); // D92: stairs
    m_stairRiser->setObjectName(QStringLiteral("stairRiser"));
    m_stairRiser->setRange(0.05, 0.5);
    m_stairRiser->setDecimals(3);
    m_stairRiser->setSingleStep(0.005);
    m_stairRiser->setSuffix(QStringLiteral(" m"));
    m_stairRiser->setValue(settings.value("stair_riser").toDouble(0.175));
    m_stairRiser->setToolTip(tr("A new stair's target riser height"));
    form->addRow(tr("Stair riser target:"), m_stairRiser);
    m_stairTreadMode = new QComboBox(this);
    m_stairTreadMode->setObjectName(QStringLiteral("stairTreadMode"));
    m_stairTreadMode->addItem(tr("Fixed tread"), QStringLiteral("fixed"));
    m_stairTreadMode->addItem(tr("From 2 risers + tread = 625 mm"), QStringLiteral("blondel"));
    m_stairTreadMode->setCurrentIndex(std::max(0, m_stairTreadMode->findData(
        settings.value("stair_tread_mode").toString(QStringLiteral("fixed")))));
    m_stairTreadMode->setToolTip(tr("A new stair's tread: a fixed depth, or computed from the 2R+G rule"));
    form->addRow(tr("Stair tread:"), m_stairTreadMode);
    m_stairTread = new QDoubleSpinBox(this);
    m_stairTread->setObjectName(QStringLiteral("stairTread"));
    m_stairTread->setRange(0.05, 1.0);
    m_stairTread->setDecimals(3);
    m_stairTread->setSingleStep(0.005);
    m_stairTread->setSuffix(QStringLiteral(" m"));
    m_stairTread->setValue(settings.value("stair_tread").toDouble(0.28));
    m_stairTread->setEnabled(m_stairTreadMode->currentData().toString() == QLatin1String("fixed"));
    connect(m_stairTreadMode, &QComboBox::currentIndexChanged, this,
        [this] { m_stairTread->setEnabled(m_stairTreadMode->currentData().toString() == QLatin1String("fixed")); });
    form->addRow(QString(), m_stairTread);
    m_stairArrow = new QComboBox(this);
    m_stairArrow->setObjectName(QStringLiteral("stairArrow"));
    m_stairArrow->addItem(tr("At the top"), QStringLiteral("top"));
    m_stairArrow->addItem(tr("At the bottom"), QStringLiteral("bottom"));
    m_stairArrow->addItem(tr("At both ends"), QStringLiteral("both"));
    m_stairArrow->setCurrentIndex(std::max(0, m_stairArrow->findData(
        settings.value("stair_arrow").toString(QStringLiteral("top")))));
    m_stairArrow->setToolTip(tr("Where the plan symbol's arrow sits"));
    form->addRow(tr("Stair plan arrow:"), m_stairArrow);
    m_stairNumbers = new QCheckBox(tr("Number the risers on the plan"), this);
    m_stairNumbers->setObjectName(QStringLiteral("stairRiserNumbers"));
    m_stairNumbers->setChecked(settings.value("stair_riser_numbers").toBool(false));
    form->addRow(QString(), m_stairNumbers);
    m_layers3d = new QCheckBox(tr("Show each layer on the ends and tops of walls and slabs in 3D"), this); // D96
    m_layers3d->setObjectName(QStringLiteral("layersIn3d"));
    m_layers3d->setChecked(settings.value("layers_in_3d").toBool(true));
    form->addRow(QString(), m_layers3d);
    m_memberMaterial = new QComboBox(this); // D97
    m_memberMaterial->setObjectName(QStringLiteral("memberMaterialScope"));
    m_memberMaterial->addItem(tr("Each column or beam its own (Archicad)"), QStringLiteral("element"));
    m_memberMaterial->addItem(tr("Every column or beam of the type (Revit)"), QStringLiteral("type"));
    m_memberMaterial->setCurrentIndex(std::max(0, m_memberMaterial->findData(
        settings.value("member_material_scope").toString(QStringLiteral("element")))));
    m_memberMaterial->setToolTip(tr("What changing a column's or beam's building material changes"));
    form->addRow(tr("Column and beam material:"), m_memberMaterial);
    m_importedWalls = new QComboBox(this); // D92
    m_importedWalls->setObjectName(QStringLiteral("importedWalls"));
    m_importedWalls->addItem(tr("Rebuild with KimBim's shape"), QStringLiteral("rebuild"));
    m_importedWalls->addItem(tr("Keep the imported shape and cut it"), QStringLiteral("keep"));
    m_importedWalls->setCurrentIndex(m_importedWalls->findData(settings.value("imported_walls").toString(QStringLiteral("rebuild"))));
    m_importedWalls->setToolTip(tr("Splitting a wall imported from another program: rebuild it (so it edits and joins like one drawn here) or keep the other program's body and cut it"));
    form->addRow(tr("Imported walls:"), m_importedWalls);
    m_partialDups = new QCheckBox(tr("Flag partly overlapping elements as duplicates"), this); // D92
    m_partialDups->setObjectName(QStringLiteral("partialDuplicates"));
    m_partialDups->setChecked(settings.value("check_partial_duplicates").toBool(false));
    m_partialDups->setToolTip(tr("Model checks: also report same-type elements that overlap by half or more without being exactly in the same place"));
    form->addRow(QString(), m_partialDups);
    m_decimals = new QSpinBox(this);
    m_decimals->setObjectName(QStringLiteral("lengthDecimals"));
    m_decimals->setRange(0, 4);
    m_decimals->setValue(settings.value("length_decimals").toInt(2));
    form->addRow(tr("Decimals:"), m_decimals);
    // D91: which status an opened IFC offers for its unmarked elements (default Existing).
    m_ifcStatus = new QComboBox(this);
    m_ifcStatus->setObjectName(QStringLiteral("ifcStatusDefault"));
    m_ifcStatus->addItem(tr("Existing"), QStringLiteral("existing"));
    m_ifcStatus->addItem(tr("To be demolished"), QStringLiteral("demolish"));
    m_ifcStatus->addItem(tr("Leave them (they count as New)"), QStringLiteral("leave"));
    m_ifcStatus->setCurrentIndex(std::max(0, m_ifcStatus->findData(settings.value("ifc_status_default").toString(QStringLiteral("existing")))));
    form->addRow(tr("Unmarked elements in an opened IFC:"), m_ifcStatus);
    // D93: the active renovation-styles preset (the looks live in Graphics > Renovation styles).
    m_renovationPreset = new QComboBox(this);
    m_renovationPreset->setObjectName(QStringLiteral("renovationPreset"));
    m_renovationPreset->addItem(settings.value("renovation_preset").toString(QStringLiteral("Uruguay")));
    form->addRow(tr("Renovation styles:"), m_renovationPreset);
    // D91: what a sheet legend lists.
    m_legendMode = new QComboBox(this);
    m_legendMode->setObjectName(QStringLiteral("legendMode"));
    m_legendMode->addItem(tr("Every rule when it fits"), QStringLiteral("auto"));
    m_legendMode->addItem(tr("Every rule"), QStringLiteral("all"));
    m_legendMode->addItem(tr("Only the rules used"), QStringLiteral("used"));
    m_legendMode->setCurrentIndex(std::max(0, m_legendMode->findData(settings.value("legend_mode").toString(QStringLiteral("auto")))));
    form->addRow(tr("Sheet legend:"), m_legendMode);
    // D91: plans show library objects' 2D plan symbol (else their 3D body seen from above).
    m_planSymbols = new QCheckBox(tr("Library objects show their plan symbol in plans"), this);
    m_planSymbols->setObjectName(QStringLiteral("planSymbols"));
    m_planSymbols->setChecked(settings.value("plan_symbols").toBool(true));
    form->addRow(QString(), m_planSymbols);
    layout->addLayout(form);
    auto* note = new QLabel(tr("These settings aren't kept with a plain IFC file. Save as .kim to keep them."), this);
    note->setObjectName(QStringLiteral("notKeptNote"));
    note->setWordWrap(true);
    note->setVisible(!kept);
    layout->addWidget(note);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons);
}

QJsonObject ProjectSettingsDialog::changes() const
{
    QJsonObject out;
    if (std::lround(m_cut->value() * 100) != std::lround(m_settings.value("plan_cut_height").toDouble(1.2) * 100))
        out.insert("plan_cut_height", m_cut->value());
    if (std::lround(m_viewDepth->value() * 100) != std::lround(m_settings.value("view_depth").toDouble(0.5) * 100))
        out.insert("view_depth", m_viewDepth->value());
    const int scale = m_scale->currentText().toInt();
    if (scale > 0 && scale != m_settings.value("drawing_scale").toInt(100))
        out.insert("drawing_scale", scale);
    if (scale > 0 && m_scale->findText(QString::number(scale)) < 0) { // a typed scale joins the list
        QJsonArray scales = m_settings.value("scales").toArray();
        scales.append(scale);
        out.insert("scales", scales);
    }
    if (m_paper->currentText() != m_settings.value("sheet_paper").toString(QStringLiteral("A1")))
        out.insert("sheet_paper", m_paper->currentText());
    if (m_unit->currentText() != m_settings.value("length_unit").toString(QStringLiteral("m")))
        out.insert("length_unit", m_unit->currentText());
    if (m_areaUnit->currentText() != m_settings.value("area_unit").toString(QStringLiteral("m²")))
        out.insert("area_unit", m_areaUnit->currentText());
    if (m_levelReference->currentData().toString() != m_settings.value("level_reference").toString(QStringLiteral("project")))
        out.insert("level_reference", m_levelReference->currentData().toString());
    if (std::abs(m_seaLevel->value() - m_settings.value("sea_level").toDouble(0.0)) > 1e-9)
        out.insert("sea_level", m_seaLevel->value());
    if (m_northStyle->currentData().toString() != m_settings.value("north_arrow_style").toString(QStringLiteral("circle")))
        out.insert("north_arrow_style", m_northStyle->currentData().toString());
    if (m_scaleBarStyle->currentData().toString() != m_settings.value("scale_bar_style").toString(QStringLiteral("bar")))
        out.insert("scale_bar_style", m_scaleBarStyle->currentData().toString());
    if (std::abs(m_stairRiser->value() - m_settings.value("stair_riser").toDouble(0.175)) > 1e-9)
        out.insert("stair_riser", m_stairRiser->value());
    if (std::abs(m_stairTread->value() - m_settings.value("stair_tread").toDouble(0.28)) > 1e-9)
        out.insert("stair_tread", m_stairTread->value());
    if (m_stairTreadMode->currentData().toString() != m_settings.value("stair_tread_mode").toString(QStringLiteral("fixed")))
        out.insert("stair_tread_mode", m_stairTreadMode->currentData().toString());
    if (m_stairArrow->currentData().toString() != m_settings.value("stair_arrow").toString(QStringLiteral("top")))
        out.insert("stair_arrow", m_stairArrow->currentData().toString());
    if (m_stairNumbers->isChecked() != m_settings.value("stair_riser_numbers").toBool(false))
        out.insert("stair_riser_numbers", m_stairNumbers->isChecked());
    if (m_memberMaterial->currentData().toString()
        != m_settings.value("member_material_scope").toString(QStringLiteral("element")))
        out.insert("member_material_scope", m_memberMaterial->currentData().toString());
    if (m_layers3d->isChecked() != m_settings.value("layers_in_3d").toBool(true))
        out.insert("layers_in_3d", m_layers3d->isChecked());
    if (m_importedWalls->currentData().toString() != m_settings.value("imported_walls").toString(QStringLiteral("rebuild")))
        out.insert("imported_walls", m_importedWalls->currentData().toString());
    if (m_partialDups->isChecked() != m_settings.value("check_partial_duplicates").toBool(false))
        out.insert("check_partial_duplicates", m_partialDups->isChecked());
    if (m_decimals->value() != m_settings.value("length_decimals").toInt(2))
        out.insert("length_decimals", m_decimals->value());
    if (m_ifcStatus->currentData().toString() != m_settings.value("ifc_status_default").toString(QStringLiteral("existing")))
        out.insert("ifc_status_default", m_ifcStatus->currentData().toString());
    if (m_renovationPreset->currentText() != m_settings.value("renovation_preset").toString(QStringLiteral("Uruguay")))
        out.insert("renovation_preset", m_renovationPreset->currentText());
    if (m_legendMode->currentData().toString() != m_settings.value("legend_mode").toString(QStringLiteral("auto")))
        out.insert("legend_mode", m_legendMode->currentData().toString());
    if (m_planSymbols->isChecked() != m_settings.value("plan_symbols").toBool(true))
        out.insert("plan_symbols", m_planSymbols->isChecked());
    return out;
}

void ProjectSettingsDialog::setRenovationPresets(const QStringList& presets)
{
    const QString current = m_renovationPreset->currentText();
    m_renovationPreset->clear();
    m_renovationPreset->addItems(presets);
    if (!presets.contains(current))
        m_renovationPreset->addItem(current);
    m_renovationPreset->setCurrentText(current);
}

} // namespace kimbim
