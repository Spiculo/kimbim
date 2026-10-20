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
