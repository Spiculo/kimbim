// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonObject>
#include <QStringList>

class QComboBox;
class QDoubleSpinBox;
class QSpinBox;

namespace kimbim {

// File > Project settings (D72): the settings kept with the project (.kim or folder) and versioned.
class ProjectSettingsDialog : public QDialog {
    Q_OBJECT
public:
    // kept: the open document keeps them (false for a plain IFC: the dialog says so).
    ProjectSettingsDialog(const QJsonObject& settings, bool kept, QWidget* parent);
    QJsonObject changes() const; // only the settings that differ from the ones passed in
    // D93: the renovation style presets to choose from (the active one is a project setting).
    void setRenovationPresets(const QStringList& presets);

private:
    QJsonObject m_settings;
    QDoubleSpinBox* m_cut;
    QSpinBox* m_scale;
    QComboBox* m_paper;
    QComboBox* m_unit;
    QSpinBox* m_decimals;
    QComboBox* m_ifcStatus;
    QComboBox* m_renovationPreset;
    QComboBox* m_legendMode;
};

} // namespace kimbim
