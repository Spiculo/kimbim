// SPDX-License-Identifier: GPL-3.0-or-later
#include "ProjectSettingsDialog.h"

#include <QComboBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
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
    m_scale = new QSpinBox(this);
    m_scale->setObjectName(QStringLiteral("drawingScale"));
    m_scale->setRange(1, 100000);
    m_scale->setPrefix(QStringLiteral("1:"));
    m_scale->setValue(settings.value("drawing_scale").toInt(100));
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
    if (m_scale->value() != m_settings.value("drawing_scale").toInt(100))
        out.insert("drawing_scale", m_scale->value());
    if (m_paper->currentText() != m_settings.value("sheet_paper").toString(QStringLiteral("A1")))
        out.insert("sheet_paper", m_paper->currentText());
    if (m_unit->currentText() != m_settings.value("length_unit").toString(QStringLiteral("m")))
        out.insert("length_unit", m_unit->currentText());
    if (m_decimals->value() != m_settings.value("length_decimals").toInt(2))
        out.insert("length_decimals", m_decimals->value());
    if (m_ifcStatus->currentData().toString() != m_settings.value("ifc_status_default").toString(QStringLiteral("existing")))
        out.insert("ifc_status_default", m_ifcStatus->currentData().toString());
    return out;
}

} // namespace kimbim
